from __future__ import annotations

from pathlib import Path
from typing import Any

from .distill import make_distill
from .experiment_ledger import record_experiment_from_run
from .goal import load_goal
from .memory_fsm import MemoryFSMStore
from .model_policy import context_budget_for_goal, resolve_model_route, resolve_session_policy, task_type_from_goal
from .outcome import grade_outcome, outcome_enabled, outcome_feedback, outcome_spec
from .paths import ensure_layout, find_project_root
from .provider import provider_record_from_agent_result
from .runner import adapter_from_name, read_context
from .session import record_session
from .storage import EventLog, MemoryBroker
from .utils import run_id as make_run_id, utc_now, write_json
from .verifier import verify_goal
from .worktree import WorktreeManager


class SisyfusRunner:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = find_project_root(root)
        self.sf = ensure_layout(self.root)

    def run(
        self,
        goal_path: str | Path,
        *,
        adapter_name: str = "mock",
        agent_command: str | None = None,
        apply_distill: bool = False,
        session_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        goal = load_goal(goal_path)
        rid = make_run_id()
        run_dir = self.sf / "runs" / rid
        run_dir.mkdir(parents=True, exist_ok=False)
        task_type = task_type_from_goal(goal)
        session_policy = resolve_session_policy(goal, self.root)
        goal_outcome_enabled = outcome_enabled(goal)
        out_spec = outcome_spec(goal, self.root) if goal_outcome_enabled else None
        write_json(run_dir / "goal.normalized.json", goal)
        write_json(run_dir / "session_policy.json", session_policy)
        if out_spec:
            write_json(run_dir / "outcome.spec.json", out_spec)
        log = EventLog(run_dir, run_id=rid, goal_id=goal["id"])
        log.append(
            "session.started",
            status="IN_PROGRESS",
            data={
                "one_task_per_session": session_policy.get("one_task_per_session", True),
                "task_type": task_type,
                "goal_path": str(goal_path),
                "adapter": adapter_name,
                "beam_node": goal.get("beam_node"),
                "outcome_enabled": goal_outcome_enabled,
            },
        )

        wt = WorktreeManager(self.root)
        wt_info = wt.create_or_use(
            goal_id=goal["id"],
            run_id=rid,
            isolate=bool(goal.get("worktree", {}).get("isolate")),
            base_ref=str(goal.get("worktree", {}).get("base_ref") or "HEAD"),
        )
        workdir = Path(wt_info["workdir"]).resolve()
        write_json(run_dir / "worktree.json", wt_info)
        log.append("worktree.ready", status="IN_PROGRESS", data=wt_info)

        adapter = adapter_from_name(adapter_name, command=agent_command)
        model_routes: dict[str, dict[str, Any]] = {}
        roles_for_routing = ["explorer", "implementer", "verifier", "distiller", "grader"]
        for role in roles_for_routing:
            try:
                model_routes[role] = resolve_model_route(self.root, goal=goal, role="verifier" if role == "grader" else role)
                if role == "grader" and out_spec and isinstance(out_spec.get("grader"), dict):
                    requested = out_spec["grader"].get("model_profile")
                    if requested:
                        model_routes[role] = resolve_model_route(self.root, goal=goal, role="verifier", override_profile=str(requested))
                    model_routes[role]["role"] = "grader"
            except ValueError as exc:
                model_routes[role] = {"role": role, "status": "ERROR", "error": str(exc), "allow_agent": False}
        write_json(run_dir / "model_routes.json", model_routes)
        log.append("model_routes.resolved", status="IN_PROGRESS", data=model_routes)

        context_max_chars = context_budget_for_goal(self.root, goal)
        memory_context = read_context(self.root, goal, max_chars=context_max_chars)
        (run_dir / "loaded-context.txt").write_text(memory_context, encoding="utf-8")
        log.append(
            "context.loaded",
            status="IN_PROGRESS",
            data={
                "context_chars": len(memory_context),
                "context_max_chars": context_max_chars,
                "read_recent_sessions": goal.get("context", {}).get("read_recent_sessions"),
            },
        )

        final_status = "FAILED"
        reason = "max rounds reached"
        failure_signatures: dict[str, int] = {}
        previous_verifier: dict[str, Any] | None = None
        previous_outcome: dict[str, Any] | None = None
        agent_results: list[dict[str, Any]] = []
        skipped_agents: list[dict[str, Any]] = []
        provider_records: list[dict[str, Any]] = []
        outcome_results: list[dict[str, Any]] = []

        max_rounds = int(goal.get("loop", {}).get("max_rounds", 3) or 3)
        if out_spec:
            max_rounds = min(max_rounds, int(out_spec.get("max_iterations") or max_rounds)) if out_spec.get("max_iterations") else max_rounds
        repeat_limit = int(goal.get("loop", {}).get("stop_if_same_failure_repeats", 2) or 2)

        for round_index in range(1, max_rounds + 1):
            log.append("round.started", round_index=round_index, status="IN_PROGRESS")
            for role in ["explorer", "implementer"]:
                cfg = goal.get("agents", {}).get(role, {}) or {}
                enabled = cfg.get("enabled", True)
                route = model_routes.get(role, {})
                if not enabled:
                    skipped = {"role": role, "round": round_index, "reason": "disabled_in_goal"}
                    skipped_agents.append(skipped)
                    log.append("agent.skipped", round_index=round_index, status="IN_PROGRESS", data=skipped)
                    continue
                if route.get("allow_agent") is False and cfg.get("force_agent") is not True:
                    skipped = {"role": role, "round": round_index, "reason": "model_policy_disallows_agent", "model_route": route}
                    skipped_agents.append(skipped)
                    log.append("agent.skipped", round_index=round_index, status="IN_PROGRESS", data=skipped)
                    continue
                # Add independent grader/outcome feedback to the next iteration prompt through previous_verifier.
                feedback_context = previous_verifier
                if previous_outcome:
                    feedback_context = dict(previous_verifier or {})
                    feedback_context["outcome_feedback"] = outcome_feedback(previous_outcome.get("rubric_grade", previous_outcome)) if previous_outcome else ""
                    feedback_context["outcome"] = previous_outcome
                result = adapter.run(
                    role=role,
                    goal=goal,
                    root=self.root,
                    workdir=workdir,
                    run_dir=run_dir,
                    round_index=round_index,
                    memory_context=memory_context,
                    previous_verifier=feedback_context,
                    model_route=route,
                )
                result_dict = result.to_dict()
                agent_results.append(result_dict)
                try:
                    provider_records.append(provider_record_from_agent_result(self.root, run_dir=run_dir, result=result_dict))
                except Exception as exc:  # provider accounting must not break runs
                    log.append("provider.accounting_failed", round_index=round_index, status="IN_PROGRESS", data={"error": str(exc)})
                log.append("agent.finished", round_index=round_index, status="IN_PROGRESS", data=result_dict)
                if result.exit_code != 0:
                    log.append("agent.command_failed", round_index=round_index, status="FAILED", data=result_dict)

            log.append("verification.started", round_index=round_index, status="VERIFYING")
            verifier = verify_goal(goal, workdir=workdir, run_dir=run_dir, round_index=round_index, root=self.root)
            previous_verifier = verifier
            log.append("verification.finished", round_index=round_index, status=verifier["status"], data={"signature": verifier.get("signature")})

            if goal_outcome_enabled:
                outcome_result = grade_outcome(root=self.root, goal=goal, run_dir=run_dir, round_index=round_index, verifier=verifier, final={"goal_id": goal["id"], "status": verifier.get("status")})
                previous_outcome = outcome_result
                outcome_results.append(outcome_result)
                log.append("outcome.graded", round_index=round_index, status=outcome_result["status"], data={"score": outcome_result.get("score"), "rubric_id": outcome_result.get("rubric_id")})
                if outcome_result.get("score", 0) <= float((out_spec or {}).get("fail_fast_threshold", -1) or -1):
                    final_status = "NEEDS_HUMAN"
                    reason = f"outcome score {outcome_result.get('score')} fell below fail-fast threshold"
                    log.append("outcome.fail_fast", round_index=round_index, status=final_status, data=outcome_result)
                    break
                deterministic_ok = verifier["status"] == "PASSED"
                deterministic_absent_or_uncertain = verifier["status"] == "UNCERTAIN" and not verifier.get("commands") and not verifier.get("monitors")
                allow_no_det = bool((out_spec or {}).get("allow_pass_without_deterministic_verifier"))
                if outcome_result["status"] == "PASSED" and (deterministic_ok or (allow_no_det and deterministic_absent_or_uncertain)):
                    final_status = "PASSED"
                    reason = f"outcome rubric {outcome_result.get('rubric_id')} passed with score {outcome_result.get('score')}"
                    break
                if verifier["status"] == "FAILED":
                    signature = verifier.get("signature")
                    if signature:
                        failure_signatures[signature] = failure_signatures.get(signature, 0) + 1
                        if failure_signatures[signature] >= repeat_limit:
                            final_status = "NEEDS_HUMAN"
                            reason = f"same failure signature repeated {failure_signatures[signature]} times"
                            log.append("loop.repeated_failure", round_index=round_index, status=final_status, data={"signature": signature})
                            break
                if round_index == max_rounds:
                    final_status = "NEEDS_HUMAN" if outcome_result["status"] == "NOT_MET" else "UNCERTAIN"
                    reason = f"outcome not met after {round_index} iterations: score {outcome_result.get('score')}"
                continue

            # Original /goal-style deterministic loop.
            if verifier["status"] == "PASSED":
                final_status = "PASSED"
                reason = "deterministic verifier passed"
                break
            if verifier["status"] == "UNCERTAIN":
                final_status = "UNCERTAIN"
                reason = "deterministic verifier uncertain"
                break
            signature = verifier.get("signature")
            if signature:
                failure_signatures[signature] = failure_signatures.get(signature, 0) + 1
                if failure_signatures[signature] >= repeat_limit:
                    final_status = "NEEDS_HUMAN"
                    reason = f"same failure signature repeated {failure_signatures[signature]} times"
                    log.append("loop.repeated_failure", round_index=round_index, status=final_status, data={"signature": signature})
                    break

        final = {
            "schema_version": "sisyfus.final.v0.6",
            "session_id": rid,
            "run_id": rid,
            "goal_id": goal["id"],
            "task_type": task_type,
            "status": final_status,
            "reason": reason,
            "root": str(self.root),
            "workdir": str(workdir),
            "run_dir": str(run_dir),
            "finished_at": utc_now(),
            "context_chars": len(memory_context),
            "context_max_chars": context_max_chars,
            "model_routes": model_routes,
            "provider_usage": provider_records,
            "beam": goal.get("beam_node") or {},
            "agent_results": agent_results,
            "skipped_agents": skipped_agents,
            "beam_node": goal.get("beam_node"),
            "failure_signatures": failure_signatures,
            "outcome_enabled": goal_outcome_enabled,
            "outcome_results": outcome_results,
            "latest_outcome": outcome_results[-1] if outcome_results else None,
            "session_metadata": session_metadata or {},
        }
        if session_metadata and isinstance(session_metadata.get("beam"), dict):
            final["beam"] = session_metadata["beam"]
        write_json(run_dir / "final.json", final)
        self._write_report(run_dir, final, previous_verifier)
        log.append("run.finished", status=final_status, data={"reason": reason})

        distill = make_distill(run_dir)
        session_record: dict[str, Any] | None = None
        if session_policy.get("record_session_index", True):
            session_record = record_session(
                self.root,
                run_dir,
                final,
                distill,
                max_chars=int(session_policy.get("session_context_max_chars") or 12000),
            )
            final["session_record"] = session_record
            final["session_compact_path"] = str(run_dir / "session.compact.md")
            write_json(run_dir / "final.json", final)
            log.append("session.compacted", status=final_status, data=session_record)
        memory_fsm_counts = MemoryFSMStore(self.root).ingest_distill(distill)
        final["memory_fsm_counts"] = memory_fsm_counts
        experiment = record_experiment_from_run(self.root, run_dir=run_dir, goal=goal, final=final, outcome=outcome_results[-1] if outcome_results else None)
        if experiment:
            final["experiment"] = experiment
        write_json(run_dir / "final.json", final)
        if apply_distill:
            counts = MemoryBroker(self.root).apply_distill(distill)
            final["applied_distill_counts"] = counts
            write_json(run_dir / "final.json", final)
        return final

    def _write_report(self, run_dir: Path, final: dict[str, Any], verifier: dict[str, Any] | None) -> None:
        lines = [
            "# Sisyfus Run Report",
            "",
            f"Run/session: `{final['run_id']}`",
            f"Goal: `{final['goal_id']}`",
            f"Task type: `{final.get('task_type', '-')}`",
            f"Status: **{final['status']}**",
            f"Reason: {final['reason']}",
            "",
        ]
        beam = final.get("beam") or final.get("beam_node") or {}
        if isinstance(beam, dict) and beam:
            lines.append("## Beam branch")
            lines.append(f"- beam: `{beam.get('beam_id')}` / `{beam.get('beam_run_id')}`")
            lines.append(f"- node: `{beam.get('node_id')}` depth `{beam.get('depth')}`")
            lines.append(f"- parent: `{beam.get('parent_id') or '-'}`")
            lines.append(f"- direction: `{beam.get('direction_id')}` — {beam.get('title', '')}")
            lines.append("")
        lines.append(f"Workdir: `{final['workdir']}`")
        lines.append(f"Context chars: `{final.get('context_chars')}` / `{final.get('context_max_chars')}`")
        lines.append("")
        lines.append("## Model routes")
        for role, route in (final.get("model_routes") or {}).items():
            lines.append(f"- `{role}`: profile `{route.get('profile_id')}`, model `{route.get('model')}`, allow_agent `{route.get('allow_agent')}`")
        if final.get("provider_usage"):
            lines.append("")
            lines.append("## Provider usage")
            for rec in final.get("provider_usage", []):
                fallback = " fallback" if rec.get("safeguard_fallback") or rec.get("fallback_model") else ""
                lines.append(f"- `{rec.get('role')}` round `{rec.get('round')}` requested `{rec.get('requested_model')}` actual `{rec.get('actual_model')}` cost `${rec.get('estimated_usd')}`{fallback}")
        if final.get("latest_outcome"):
            out = final["latest_outcome"]
            lines.append("")
            lines.append("## Outcome grade")
            lines.append(f"Rubric: `{out.get('rubric_id')}`")
            lines.append(f"Status: **{out.get('status')}**")
            lines.append(f"Score: `{out.get('score')}` / threshold `{out.get('pass_threshold')}`")
            lines.append("")
            lines.append("Weakest criteria:")
            criteria = sorted(out.get("rubric_grade", {}).get("criteria", []), key=lambda c: float(c.get("score", 0)))
            for c in criteria[:5]:
                lines.append(f"- `{c.get('id')}` score `{c.get('score')}` — {c.get('comment')}")
        if final.get("skipped_agents"):
            lines.append("")
            lines.append("## Skipped agents")
            for skipped in final["skipped_agents"]:
                lines.append(f"- `{skipped.get('role')}` round `{skipped.get('round')}`: {skipped.get('reason')}")
        lines.append("")
        if verifier:
            lines.append("## Latest verifier")
            lines.append(f"Status: **{verifier['status']}**")
            lines.append(f"Changed files: {len(verifier.get('changed_files', []))}")
            if verifier.get("failed_command_count"):
                lines.append(f"Failed commands: {verifier['failed_command_count']}")
            if verifier.get("failed_monitor_count"):
                lines.append(f"Failed monitors: {verifier['failed_monitor_count']}")
            if verifier.get("monitors"):
                lines.append("Monitors:")
                for mon in verifier.get("monitors", []):
                    lines.append(f"- `{mon.get('monitor_id')}`: **{mon.get('status')}** — {mon.get('summary', '')}")
            if verifier.get("warnings"):
                lines.append("Warnings:")
                for w in verifier["warnings"]:
                    lines.append(f"- {w}")
            if verifier.get("violations"):
                lines.append("Violations:")
                for v in verifier["violations"]:
                    lines.append(f"- {v}")
        (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
