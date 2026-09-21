from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any, Iterator

from ..research_v2.engine import ResearchEngine
from ..research_v2.workspace import atomic_write_json
from .frontier import ready_frontier
from .judgments import Judge, NullJudge, assess_safely
from .models import LoopReport, SOP, digest, number
from .policy import SchedulingPolicy

PREFIX = "RESEARCH_OS_"


@contextmanager
def coordinator_lock(engine: ResearchEngine) -> Iterator[None]:
    """Fence ResearchOS coordinators, not arbitrary same-user processes.

    This is not an OS sandbox. A separate process/user boundary is required for
    untrusted workers. Legacy direct engine calls must not run concurrently.
    """
    if os.name != "posix":
        raise RuntimeError("Research OS coordination currently requires POSIX flock")
    import fcntl

    path = engine.workspace.path / "research-os.lock"
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another ResearchOS coordinator owns this workspace") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def configuration(engine: ResearchEngine) -> dict[str, Any]:
    records = [e["data"] for e in engine.events if e["event_type"] in {PREFIX + "CONFIGURED", PREFIX + "POLICY_ACTIVATED", PREFIX + "SOP_ACTIVATED"}]
    if not records:
        raise RuntimeError("operator must configure and approve the run before execution")
    return records[-1]


def configure(engine: ResearchEngine, *, policy: SchedulingPolicy | None = None, sop: SOP | None = None, replay_mode: str = "prefix", actor: str = "operator") -> dict[str, Any]:
    """Explicit operator action. Never called by a judge, planner or learner.

    Approves EXACT currently admitted command actions and measurement code.
    New proposals require a new operator-reviewed configuration.
    """
    if replay_mode not in {"prefix", "independent"}:
        raise ValueError("unknown replay mode")
    with coordinator_lock(engine):
        snapshot = engine.snapshot()
        if any(a["status"] in {"RESERVED", "RUNNING"} for a in snapshot["attempts"].values()):
            raise RuntimeError("cannot configure with unresolved attempts")
        approvals = {}
        for exp in snapshot["experiments"].values():
            contract = snapshot["contracts"].get(exp.get("contract_id"))
            if exp["status"] != "ADMITTED" or exp["action"]["kind"] != "command" or not contract:
                continue
            all_hashes = engine._action_code_hashes(exp["action"])
            hashes = {p: all_hashes.get(p, "missing") for p in exp["action"].get("code_paths", ())}
            if not exp["action"].get("code_paths") or "missing" in hashes.values():
                raise ValueError("approved measurements require existing explicit action.code_paths")
            if replay_mode == "independent" and (exp.get("based_on", {}).get("evidence_ids") or exp.get("based_on", {}).get("lesson_ids") or any(snapshot["claims"][c].get("depends_on") for c in exp["target_claim_ids"])):
                raise ValueError("independent replay cannot contain evidence-dependent experiments")
            approvals[exp["id"]] = {
                "action_hash": digest(exp["action"]),
                "contract_hash": digest(contract),
                "code_hashes": hashes,
            }
        payload = {
            "policy": asdict(policy or SchedulingPolicy()), "sop": (sop or SOP()).public(),
            "approvals": approvals, "replay_mode": replay_mode,
            "task_hash": digest(engine.task), "actor": actor,
        }
        payload["config_hash"] = digest(payload)
        engine.workspace.append_event(PREFIX + "CONFIGURED", actor=actor, data=payload)
        engine.sync(render=False)
        return payload


class ResearchOS:
    """A bounded control loop over ResearchEngine, not a second truth runtime."""

    def __init__(self, engine: ResearchEngine, *, judge: Judge | None = None):
        self.engine = engine
        self.judge = judge or NullJudge()

    def frontier(self) -> list[dict[str, Any]]:
        return [c.public() for c in ready_frontier(self.engine.snapshot())]

    def run(self, *, max_steps: int = 10, allow_local_commands: bool = False) -> LoopReport:
        if type(max_steps) is not int or not 1 <= max_steps <= 1000:
            raise ValueError("max_steps must be an integer in [1, 1000]")
        if not allow_local_commands:
            raise PermissionError("local command execution requires explicit operator opt-in")
        with coordinator_lock(self.engine):
            return self._run(max_steps)

    def _run(self, max_steps: int, *, only_experiment: str | None = None, dispatch_context: dict[str, Any] | None = None) -> LoopReport:
        # Internal seam: caller holds the member coordinator lock. A portfolio
        # holds all member locks and passes one already-selected experiment.
        engine = self.engine
        config = configuration(engine)
        if digest(engine.task) != config["task_hash"]:
            raise ValueError("configured task changed")
        policy = SchedulingPolicy.load(config["policy"])
        sop = SOP(**{**config["sop"], "preflight_order": tuple(config["sop"]["preflight_order"])})
        results = []
        cost = 0.0
        stop = "step_limit"
        for _ in range(max_steps):
            snapshot = engine.refresh_waits()
            if snapshot["run_status"] != "ACTIVE":
                stop = "terminal:" + snapshot["run_status"]
                break
            if any(a["status"] in {"RESERVED", "RUNNING"} for a in snapshot["attempts"].values()):
                stop = "unresolved_attempt:reconcile_before_retry"
                break
            candidates = ready_frontier(snapshot, max_attempts=sop.max_attempts_per_experiment)
            if only_experiment is not None:
                candidates = [c for c in candidates if c.id == only_experiment]
            if not candidates:
                stop = "no_ready_action"
                break
            approved = [c for c in candidates if c.id in config["approvals"]]
            if not approved:
                stop = "needs_operator_approval"
                break
            started_judge = time.monotonic()
            judgments = assess_safely(self.judge if dispatch_context is None else NullJudge(), approved)
            judge_seconds = time.monotonic() - started_judge
            selected = policy.rank(approved, judgments)[0]
            # Refresh after external judgments. State changed => replan, not execute.
            current = engine.snapshot()
            if current["snapshot_hash"] != snapshot["snapshot_hash"]:
                stop = "state_changed:replan"
                break
            exp = current["experiments"][selected.id]
            approval = config["approvals"][selected.id]
            for check in sop.preflight_order:
                if check == "authorization":
                    if digest(exp["action"]) != approval["action_hash"] or digest(current["contracts"][exp["contract_id"]]) != approval["contract_hash"]:
                        raise RuntimeError("action or contract no longer matches operator approval")
                    if {p: engine._action_code_hashes(exp["action"]).get(p, "missing") for p in approval["code_hashes"]} != approval["code_hashes"]:
                        raise RuntimeError("measurement code changed after approval")
                elif check == "dependencies":
                    if selected.id not in {c.id for c in ready_frontier(current, max_attempts=sop.max_attempts_per_experiment)}:
                        raise RuntimeError("dependency or status gate failed")
                elif check == "budget":
                    remaining = current["budget"]["cost_units_remaining"]
                    if remaining is not None and selected.cost > number(remaining):
                        raise RuntimeError("budget gate failed")
            attempt_id = f"attempt-{selected.id}-{len(exp.get('attempt_ids', [])) + 1:02d}"
            decision = {
                "config_hash": config["config_hash"], "policy_hash": policy.hash,
                "sop_hash": digest(sop.public()), "state_id": current["current_state_id"],
                "state_hash": current["snapshot_hash"], "selected": selected.id,
                "attempt_id": attempt_id, "candidates": [c.public() for c in approved],
                "judgments": {k: asdict(v) for k, v in judgments.items()},
                "judge_seconds": judge_seconds, "judge_cost_usd": None,
                "selection_probability": None, "replay_mode": config["replay_mode"], "max_steps": max_steps,
                "dispatch_context": dispatch_context,
            }
            engine.workspace.append_event(PREFIX + "DECISION", actor="research-os", data=decision)
            started = time.monotonic()
            try:
                outcome = engine.execute_experiment(selected.id, expected_code_hashes=approval["code_hashes"])
            except Exception as exc:
                # Keep reservation/intention. Never pretend an unknown action failed.
                engine.workspace.append_event(PREFIX + "ERROR", actor="research-os", data={"attempt_id": attempt_id, "error_type": type(exc).__name__, "reconcile_required": True})
                stop = "execution_error:reconcile_before_retry"
                break
            receipt = {
                "attempt_id": attempt_id, "evidence_id": outcome["evidence"]["id"],
                "verdict": outcome["verdict"]["status"], "cost_units": selected.cost,
                "elapsed_seconds": time.monotonic() - started,
                "policy_hash": policy.hash, "sop_hash": digest(sop.public()),
            }
            engine.workspace.append_event(PREFIX + "RESULT", actor="research-os", data=receipt)
            engine.sync(render=False)
            results.append(receipt)
            cost += selected.cost
        final = engine.snapshot()
        report = LoopReport(engine.workspace.research_id, len(results), stop, final["run_status"], cost, tuple(results), reserved_cost_units=float(final["budget"].get("cost_units_reserved_in_flight", 0.0)), unresolved_attempts=tuple(a["id"] for a in final["attempts"].values() if a["status"] in {"RESERVED", "RUNNING"}))
        # A projection only; never used as the evidence source.
        atomic_write_json(engine.workspace.report_dir / "research-os.json", asdict(report))
        return report


def export_history(engine: ResearchEngine) -> dict[str, Any]:
    """Join decisions to engine-issued verdicts, NOT controller-supplied labels."""
    events = engine.events
    task = engine.task
    # Bind intent to the subsequent reservation. A late/duplicated diagnostic
    # event must not relabel an already executed action or expose future state.
    intents = {}
    decisions = []
    reservations = {}
    for event in events:
        if event["visibility"] == "host_only":
            continue
        if event["event_type"] == PREFIX + "DECISION":
            intents[event["data"]["attempt_id"]] = event
        elif event["event_type"] == "ATTEMPT_RESERVED":
            attempt = event["data"]["attempt"]
            if attempt["id"] in intents and attempt["id"] not in reservations:
                reservations[attempt["id"]] = attempt
                decisions.append(intents[attempt["id"]])
    verdicts = {e["data"]["attempt_id"]: e for e in events if e["event_type"] == "VERDICT_ISSUED" and e["visibility"] != "host_only"}
    nodes = []
    previous = []
    snapshot = engine.snapshot()
    for event in decisions:
        d = event["data"]
        verdict_event = verdicts.get(d["attempt_id"])
        if verdict_event is None:
            continue  # No outcome label for an unfinished attempt.
        v = verdict_event["data"]
        candidates = d["candidates"]
        chosen = next(c for c in candidates if c["id"] == d["selected"])
        attempt = reservations[d["attempt_id"]]
        if (attempt["experiment_id"] != d["selected"]
                or digest(attempt["action"]) != chosen["action_hash"]
                or attempt["cost_units_reserved"] != chosen["cost"]):
            raise ValueError("decision does not match the reserved experiment")
        # Prefix replay is always conservative. Independence is an operator claim.
        parents = list(previous) if d["replay_mode"] == "prefix" else []
        # Even independent actions that rely on an earlier supported claim retain it.
        for prior in nodes:
            prior_exp = snapshot["experiments"][prior["candidate"]["id"]]
            if set(chosen["requires"]) & set(prior_exp["target_claim_ids"]):
                parents.append(prior["id"])
        nodes.append({
            "id": d["attempt_id"], "candidate": chosen, "available_after": sorted(set(parents)),
            "outcome": {"verdict": v["verdict"]["status"], "label": int(v["verdict"]["status"] == "PASS"),
                        "cost_units": v["cost_units"], "evidence_id": v["evidence"]["id"],
                        "evidence_hash": verdict_event["event_hash"]},
            "provenance": {"decision_hash": event["event_hash"], "policy_hash": d["policy_hash"],
                           "sop_hash": d["sop_hash"], "config_hash": d["config_hash"]},
        })
        previous.append(d["attempt_id"])
    return {"schema": "sisyfus.replay.v1", "research_id": engine.workspace.research_id,
            "family": str(task.get("metadata", {}).get("task_family") or task["id"]),
            "source_event_head": events[-1]["event_hash"], "task_hash": digest(task),
            "support": "recorded_actions_only", "nodes": nodes}
