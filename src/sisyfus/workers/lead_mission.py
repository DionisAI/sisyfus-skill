"""Continuous Lead orchestration on the released, verifier-gated runtime.

Models propose plans/reviews. Historical contracts, transport reservations and
canonical continuation evidence survive restart. An integrated candidate is a
separate continuation, never an inference from independently passing branches.
"""
from __future__ import annotations

import copy
import fcntl
import json
import os
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..autonomy.models import AssuranceLevel, CapabilityResult, Decision, OpportunitySignal, VerificationResult, Verdict, stable_id
from ..autonomy.policy import AutonomyPolicy, CapabilityRegistry
from ..autonomy.runtime import AutonomousRuntime
from ..autonomy.supervisor import AutonomousSupervisor, SupervisorConfig
from ..research_v2.verifier import classify_observation
from .journal import DispatchBlocked
from .lead_contracts import load_lead_spec, paths_overlap, validate_plan
from .lead_journal import LeadJournal
from .lead_learning import ProcedureLedger, ProofUnavailable
from .mission import Mission, check_intact, copy_candidate, files
from .protocol import Receipt, Request, digest, environment, redact
from .transport import Process


def strict_json(text: str) -> dict[str, Any]:
    """No prose extraction, duplicate keys, nonfinite numbers or loose JSON."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0] not in {"```", "```json"} or lines[-1] != "```":
            raise ValueError("invalid JSON code fence")
        text = "\n".join(lines[1:-1])
    def pairs(entries):
        result = {}
        for key, value in entries:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError("nonfinite JSON number: " + value)
    raw = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(raw, dict):
        raise ValueError("model answer must be a JSON object")
    return raw


def _text_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError(name + " must be a nonempty text array")
    return value


class ProposalInvalid(ValueError):
    def __init__(self, run_key: str, reason: str):
        super().__init__(reason)
        self.run_key = run_key


TRIAL_TERMINAL_STATUSES = frozenset({"ELIGIBLE", "PROMOTED", "NONPROMOTION", "BLOCKED_PARENT_BUDGET",
                                     "FIXTURE_NOT_EVALUATED"})


class LeadMission(Mission):
    def __init__(self, directory: Path | str, spec=None):
        if spec is not None:
            # The console may pass the already normalized operator contract.
            spec = copy.deepcopy(spec) if isinstance(spec, dict) and "acceptance_hash" in spec else load_lead_spec(spec)
        super().__init__(Path(directory), spec)
        if "roles" not in self.spec:
            raise ValueError("Tech Lead requires an operator-owned Lead specification")
        self.journal = LeadJournal(self.store)
        self.journal.stop_event = self.stop
        self.registry = CapabilityRegistry()
        self.registry.register(LeadCapability(self), LeadVerifier(self))
        self.registry.register(IntegrationCapability(self), LeadVerifier(self))
        self.runtime = AutonomousRuntime(self.store, self.registry, workspace=self.directory,
            policy=AutonomyPolicy(allowed_capabilities=frozenset({"workers.execute", "workers.integrate"})), retry_base_seconds=.02)
        self._run_lock = threading.Lock()
        self.trial_runner = None
        self._trial_children = {}
        self._children_lock = threading.Lock()
        self.learning = ProcedureLedger(self.store, initial_procedure=self.spec["procedure"])
        self.journal.before_reserve = self._freeze_learning_trial
        self._freeze_lock = threading.Lock()
        self.journal.on_control = self.sync_trial_children
        if self.journal.state()["stopped"]:
            self.stop.set()

    def tasks(self) -> list[dict[str, Any]]:
        return [t for p in self.journal.records("plans") for t in p["data"]["plan"]["tasks"]]

    def active_tasks(self) -> list[dict[str, Any]]:
        active = set(self.journal.state()["active"])
        return [t for t in self.tasks() if t["id"] in active]

    def continuations(self) -> dict[str, dict[str, Any]]:
        return {c["context"]["native_task"]: c for c in self.store.list_continuations()
                if c["context"].get("lead_kind") == "implementation"}

    def integration_continuation(self) -> dict[str, Any] | None:
        revision = self.journal.state()["revision"]
        return next((c for c in self.store.list_continuations() if c["context"].get("lead_integration") == revision), None)

    def procedure(self) -> dict[str, Any]:
        # The shared, same-store ledger is the ONLY active procedure lineage.
        # Promotions/rollbacks are observed by every subsequent Lead call.
        return self.learning.active()

    def configure_learning_trial(self, *, pair_id: str, split: str = "development", mission_id: str | None = None,
                                 family: str | None = None, source_mission_ids=(), source_family_hashes=()) -> None:
        if self.journal.runs():
            raise ValueError("learning trial configuration must precede every native reservation")
        mission_id = mission_id or digest({"directory": str(self.directory), "source_hash": self.spec["source_hash"]})
        self.journal.record("learning_config", "trial", {"mission_id": mission_id, "pair_id": pair_id, "split": split,
            "family": family, "source_mission_ids": list(source_mission_ids), "source_family_hashes": list(source_family_hashes)})

    def _freeze_learning_trial(self) -> None:
        with self._freeze_lock:
            with self.store._transaction(immediate=False) as db:
                frozen = db.execute("SELECT 1 FROM events WHERE event_type='LEAD_LEARNING_FROZEN'").fetchone()
            if frozen:
                return  # The original manifest remains frozen, never rehashed.
            if self.journal.runs():
                self.journal.record("proof_gaps", "unfrozen-legacy", {"status": "PROOF_UNAVAILABLE",
                    "reason": "legacy native reservations lack a prior frozen manifest; no backfilled claim"})
                return
            config = self.journal.get("learning_config", "trial")
            if config is None:
                mission_id = digest({"directory": str(self.directory), "source_hash": self.spec["source_hash"]})
                config = {"mission_id": mission_id, "pair_id": "standalone:" + mission_id, "split": "development",
                          "family": None, "source_mission_ids": [], "source_family_hashes": []}
            self.learning.freeze_trial(**config)

    def set_trial_runner(self, runner) -> None:
        """Main's paired runner owns catalog execution; core owns its handoff.

        Callback: runner(mission=self, candidate_id=str, evaluation_root=Path,
        boundary=str). Default: lead_trials.run_trials(self, candidate_id, root).
        The root is an operator-owned frozen search/holdout catalog, never model
        output. Child missions must omit evaluation_root to prevent recursion.
        """
        if not callable(runner):
            raise TypeError("trial runner must be callable")
        self.trial_runner = runner

    def _procedure_trial_boundary(self, boundary: str) -> None:
        root = self.spec["rsi"].get("evaluation_root")
        if not root or not self.spec["rsi"].get("enabled", True):
            return
        enabled = [name for name in ("max_calls", "max_iterations", "max_tokens", "max_cost_usd", "max_wall_minutes")
                   if self.spec[name] is not None]
        history = self.learning.history()
        candidates = [r["id"] for r in history["versions"] if r.get("parent_id") == history["active_id"] and r.get("origins")]
        # Retain pending handoffs staged through the core's proposal API too.
        candidates = sorted(set(candidates) | {r["data"]["ledger_proposal"]["id"] for r in self.journal.records("improvements")
                                               if r["data"].get("ledger_proposal")})
        if not candidates and boundary == "completed" and not enabled:
            try:
                proposed = self._propose_from_completed_evidence()
            except DispatchBlocked as exc:
                self._dispatch_blocked_phase(exc)
                return
            if proposed is not None:
                candidates = [proposed]
        if not candidates:
            return
        root = Path(root).expanduser().resolve(strict=True)
        runner = self.trial_runner
        if runner is None:
            try:
                from .lead_trials import run_trials
            except ModuleNotFoundError as exc:
                if exc.name != __package__ + ".lead_trials":
                    raise
            else:
                runner = lambda **args: run_trials(args["mission"], args["candidate_id"], args["evaluation_root"])
        for candidate_id in candidates:
            key = digest({"candidate_id": candidate_id, "root": str(root)})
            if self.journal.get("trial_results", key):
                continue
            if self.stop.is_set() or self.journal.state()["stopped"]:
                return
            if self._unresolved():
                raise DispatchBlocked("unknown parent invocation fences paired trials")
            if enabled:
                self.journal.record("trial_results", key, {"status": "BLOCKED_PARENT_BUDGET", "promoted": False,
                    "reason": "finite parent aggregate caps conservatively fence child construction", "enabled_caps": enabled})
                continue
            if runner is None:
                self.journal.record("trial_pending", key, {"status": "RUNNER_REQUIRED", "evaluation_root": str(root),
                    "candidate_id": candidate_id, "auto_promote": self.spec["rsi"].get("auto_promote", False)})
                continue
            if self.journal.get("trial_requests", key):
                raise DispatchBlocked("paired trial handoff is uncertain; reconcile child mission receipts before replay")
            self.journal.record("trial_requests", key, {"boundary": boundary, "candidate_id": candidate_id,
                                                       "evaluation_root": str(root)})
            self.begin_trial(key)
            try:
                report = runner(mission=self, candidate_id=candidate_id, evaluation_root=root, boundary=boundary)
                if not isinstance(report, dict):
                    raise TypeError("trial runner must return a structured evidence report")
            except Exception as exc:
                report = {"status": "ERROR", "promoted": False, "error": f"{type(exc).__name__}: {exc}"}
                self.journal.record("trial_results", key, report)
                self.settle_trial(key, report)
                raise
            self.journal.record("trial_results", key, report)
            self.settle_trial(key, report)

    def begin_trial(self, request_id: str) -> None:
        """Durable lab lifecycle hook after immutable request reservation.

        Native trials use a separate RUNNING phase, without changing accepted
        task/integration verdicts. Nested core handoff/runner hooks are idempotent.
        """
        if not isinstance(request_id, str) or not request_id or len(request_id) > 256:
            raise ValueError("trial request ID must be bounded nonempty text")
        state = self.journal.state()
        if self.stop.is_set() or state["stopped"]:
            raise DispatchBlocked("operator stopped mission before trial start")
        saved = self.journal.get("trial_sessions", request_id)
        if saved is None:
            saved = {"return_phase": state.get("trial_return_phase", state["phase"])}
            self.journal.record("trial_sessions", request_id, saved)
        if self.journal.get("trial_settlements", request_id):
            raise DispatchBlocked("settled/uncertain trial lifecycle is never restarted")
        def change(s):
            if s["stopped"]:
                raise DispatchBlocked("operator stopped mission before trial start")
            s.setdefault("active_trials", {})[request_id] = {"return_phase": saved["return_phase"]}
            s.setdefault("trial_return_phase", saved["return_phase"])
            s.update(phase="TRIAL_RUNNING", reason="paired procedure trial in progress")
        self.journal.update(change, kind="lead_trial_started")

    def settle_trial(self, request_id: str, report: dict[str, Any]) -> None:
        """Restore the prior phase only after a durable, known terminal report.

        UNKNOWN, pending reports, read failures and runner errors remain visible;
        no terminal process acknowledgement is inferred from a returned object.
        """
        if not isinstance(report, dict) or not isinstance(report.get("status"), str):
            raise ValueError("trial settlement requires a classified structured report")
        durable = self.journal.get("paired_trial_results", request_id) or self.journal.get("trial_results", request_id)
        if durable is None or durable != redact(report):
            raise ValueError("trial settlement requires the same immutable persisted result")
        session = self.journal.get("trial_sessions", request_id)
        if session is None:
            # Upgrade/restart recovery after a validated cached final: a lifecycle
            # reconciliation, not backfilled native reservations or test proof.
            if report["status"] not in TRIAL_TERMINAL_STATUSES or not (
                self.journal.get("paired_trials", request_id) or self.journal.get("trial_requests", request_id)):
                raise ValueError("trial settlement lacks a prior begin_trial or known historical request")
            state = self.journal.state()
            fallback = "COMPLETED" if self._current_payload(self.integration_continuation()) else state["phase"]
            session = {"return_phase": state.get("trial_return_phase", fallback), "historical_result": True}
            self.journal.record("trial_sessions", request_id, session)
        observations = self._trial_observations()
        terminal = report["status"] in TRIAL_TERMINAL_STATUSES and not observations["read_errors"] and not observations["unresolved"] and not observations["fenced_request_ids"]
        previous = self.journal.get("trial_settlements", request_id)
        if previous is not None and previous["report_hash"] != digest(durable):
            raise ValueError("trial settlement report differs from its immutable acknowledgement")
        if previous is None:
            self.journal.record("trial_settlements", request_id, {"status": report["status"], "terminal": terminal,
                                                                "report_hash": digest(durable)})
        def change(s):
            active = s.setdefault("active_trials", {})
            if terminal:
                active.pop(request_id, None)
            else:
                active.setdefault(request_id, {"return_phase": session["return_phase"]})["status"] = report["status"]
            if s["stopped"]:
                return  # Never undo persistent stop on a racing terminal receipt.
            if not terminal:
                s.update(phase="UNKNOWN" if observations["unresolved"] else "TRIAL_FENCED",
                         reason="trial report is unsettled or its child proof is unreadable")
            elif active or observations["pending_request_ids"]:
                s.update(phase="TRIAL_RUNNING", reason="another paired trial handoff remains active")
            else:
                s.update(phase=s.pop("trial_return_phase", session["return_phase"]), reason="")
        self.journal.update(change, kind="lead_trial_settled")

    def _propose_from_completed_evidence(self) -> str | None:
        """Actual Lead improvement proposal from THIS mission, not holdout data."""
        conts = [self.continuations()[t["id"]] for t in self.active_tasks()]
        integrated = self.integration_continuation()
        if integrated is None or not self._current_payload(integrated):
            return None
        evidence = [self.store.latest_evidence(c["id"]) for c in [*conts, integrated]]
        refs = [e["id"] for e in evidence]
        seed = digest({"revision": self.journal.state()["revision"], "evidence": refs, "procedure": self.procedure()["hash"]})
        if self._unresolved():
            raise DispatchBlocked("UNKNOWN parent invocation fences procedure proposals")
        if self.journal.get("improvement_errors", seed):
            return None  # Retain the known failed optional proposal; no replay.
        saved = self.journal.get("procedure_proposals", seed)
        if saved:
            return saved.get("candidate_id")
        packet = self.journal.get("improvement_inputs", seed)
        if packet is None:
            packet = {"active_procedure": self.procedure(), "objective": self.spec["objective"],
                "evidence_references": refs, "canonical_evidence": [{"id": e["id"], "verdict": e["verdict"],
                    "summary": e["payload"]["summary"], "checks": e["payload"]["evidence"]["checks"],
                    "review": e["payload"]["evidence"]["review"]} for e in evidence],
                "native_reservations": len(self.journal.runs()), "active_tasks": self.active_tasks(),
                "diagnoses": self.journal.records("diagnoses")[-4:]}
            self.journal.record("improvement_inputs", seed, packet)
        prompt = ("Improve the Lead orchestration procedure using ONLY this mission's canonical test/review/diagnosis "
            "evidence. Propose a concrete change to planning/decomposition/format discipline or repair strategy that "
            "could reduce native calls while preserving every frozen acceptance and independent review gate. Do not "
            "change role models, checks, budgets or controller authority; do not claim unmeasured improvement. "
            "Return ONLY JSON {procedure,rationale,evidence}. procedure is the complete new bounded policy STRING, "
            "rationale is a nonempty STRING, and evidence is a nonempty JSON ARRAY of ONLY exact verdict ID strings "
            "copied verbatim from evidence_references, no annotations or invented IDs. No evaluation/holdout data "
            "is supplied; never request it.\n" + json.dumps(packet, ensure_ascii=False))
        def validate(raw):
            if set(raw) != {"procedure", "rationale", "evidence"}:
                raise ValueError("procedure proposal requires exact procedure/rationale/evidence fields")
            if not isinstance(raw["procedure"], str) or not 1 <= len(raw["procedure"]) <= 20000 or digest(raw["procedure"]) == packet["active_procedure"]["hash"]:
                raise ValueError("procedure proposal requires changed bounded policy text")
            if not isinstance(raw["rationale"], str) or not raw["rationale"].strip():
                raise ValueError("procedure proposal requires a nonempty rationale string")
            if set(_text_list(raw["evidence"], "procedure evidence")) - set(refs):
                raise ValueError("procedure evidence must contain only exact current verdict IDs")
        self.journal.phase("IMPROVING")
        try:
            raw, key = self._lead_json("improvement", seed, prompt, validate)
            candidate_id = self.propose_procedure(raw["procedure"], raw["rationale"], raw["evidence"])
            grounded = candidate_id.startswith("procedure_")
            self.journal.record("procedure_proposals", seed, {"run_key": key, "answer": raw,
                "candidate_id": candidate_id if grounded else None, "status": "PROPOSED" if grounded else "PROOF_UNAVAILABLE"})
            return candidate_id if grounded else None
        except ValueError as exc:
            self.journal.record("improvement_errors", seed, {"status": "PROPOSAL_INVALID", "promoted": False,
                "error": f"{type(exc).__name__}: {exc}", "run_key": getattr(exc, "run_key", None),
                "evidence_references": refs, "procedure_hash": packet["active_procedure"]["hash"]})
            return None
        finally:
            if not self.stop.is_set():
                self.journal.phase("UNKNOWN" if self._unresolved() else "COMPLETED")

    def register_trial_child(self, child) -> None:
        if child is self:
            raise ValueError("a mission cannot register itself as a trial child")
        key = digest(str(child.directory))
        self.journal.record("trial_children", key, {"directory": str(child.directory)})
        with self._children_lock:
            self._trial_children[str(child.directory)] = child
        self.sync_trial_children()

    def unregister_trial_child(self, child) -> None:
        with self._children_lock:
            self._trial_children.pop(str(child.directory), None)

    def sync_trial_children(self) -> None:
        with self._children_lock:
            children = list(self._trial_children.values())
        paused = self.journal.paused()
        stopped = self.stop.is_set() or self.journal.state()["stopped"]
        for child in children:
            if child.journal.paused() != paused:
                child.journal.pause(paused)
            if stopped and not child.stop.is_set():
                child.request_stop()

    def admit_plan(self, raw: dict[str, Any], key: str) -> None:
        saved = self.journal.get("plans", key)
        if saved is None:
            saved = self._plan_revision(raw)
            self.journal.record("plans", key, saved)
        def project(state):
            if state["revision"] < saved["revision"]:
                state.update(revision=saved["revision"], active=saved["active"], superseded=saved["superseded"], phase="IMPLEMENTING", reason="")
        self.journal.update(project, kind="lead_plan_admitted")
        self.prepare()

    def _plan_revision(self, raw) -> dict[str, Any]:
        state = self.journal.state()
        cap = self.spec["max_iterations"]
        if cap is not None and state["revision"] >= cap:
            raise DispatchBlocked("max_iterations exhausted")
        historical = {t["id"]: t for t in self.tasks()}
        entries = raw.get("tasks", [])
        if not isinstance(entries, list) or any(not isinstance(t, dict) for t in entries):
            raise ValueError("plan tasks must be objects")
        if any(not isinstance(t.get("id"), str) or not isinstance(t.get("check"), str) or
               (t.get("repair_of") is not None and not isinstance(t["repair_of"], str)) for t in entries):
            raise ValueError("task id/check/repair_of must be exact string identifiers")
        replacing = [t.get("repair_of") for t in entries if t.get("repair_of") is not None]
        if len(replacing) != len(set(replacing)):
            raise ValueError("multiple replacements of one node require a single explicit repair root")
        for task in entries:
            if task.get("id") in historical:
                raise ValueError("historical task IDs are immutable, including superseded nodes")
            target = task.get("repair_of")
            if target is not None:
                if target not in state["active"]:
                    raise ValueError("repair_of must reference an active historical node")
                old = historical[target]
                if task.get("check") != old["check"] or task.get("acceptance") != old["acceptance"]:
                    raise ValueError("repair cannot weaken or change frozen acceptance/check")
        preserved = [t for t in self.active_tasks() if t["id"] not in replacing]
        plan = validate_plan(raw, self.spec, existing=preserved)
        active = [t["id"] for t in preserved] + [t["id"] for t in plan["tasks"]]
        superseded = {**state["superseded"], **{t["repair_of"]: t["id"] for t in plan["tasks"] if t.get("repair_of")}}
        return {"revision": state["revision"] + 1, "plan": plan, "active": active,
                "superseded": superseded, "procedure_hash": self.procedure()["hash"], "acceptance_hash": self.spec["acceptance_hash"]}

    def prepare(self) -> None:
        for task in self.tasks():
            opportunity, _ = self.store.submit_opportunity(OpportunitySignal(source="techlead", title=task["id"],
                objective=task["objective"], dedupe_key="techlead-task:" + task["id"]))
            cont, _ = self.store.admit_opportunity(opportunity["id"], max_attempts=1,
                context={"native_task": task["id"], "lead_kind": "implementation", "task_hash": digest(task)})
            if task["id"] in self.journal.state()["superseded"]:
                self.store.cancel(cont["id"], actor="lead-plan")

    def _unresolved(self) -> list[str]:
        return [r["key"] for r in self.journal.runs() if r["status"] == "UNKNOWN"]

    def call_timeout(self) -> float:
        timeout = float(self.spec["timeout"])
        cap = self.spec["max_wall_minutes"]
        if cap is not None:
            remaining = 60 * (cap - self.journal.counters()["wall_minutes"])
            if remaining < .05:
                raise DispatchBlocked("max_wall_minutes exhausted")
            timeout = min(timeout, remaining)
        return timeout

    def controls(self, key: str) -> list[dict[str, Any]]:
        controls = self.journal.controls(key)
        cap = self.spec["max_wall_minutes"]
        if self.stop.is_set() or (cap is not None and self.journal.counters()["wall_minutes"] >= cap):
            controls.append({"id": key + ":controller-stop", "action": "interrupt", "text": ""})
        return controls

    def role_call(self, role: str, key: str, prompt: str, cwd: Path, *, metadata=None) -> dict[str, Any]:
        config = self.spec["roles"][role]
        pinned = self.journal.get("roles", key)
        if pinned:
            if pinned["prompt_hash"] != digest(prompt) or pinned["role"] != role or pinned["cwd"] != str(cwd):
                raise ValueError("role call input drift under a reserved identity")
            request = Request(**pinned["request"])
        else:
            session = None
            if role == "lead":
                previous = [r for r in self.journal.runs() if r["role"] == "lead" and r["receipt"] and r["receipt"]["status"] == "COMPLETED"
                            and (r["role_metadata"] or {}).get("procedure_hash") == self.procedure()["hash"]]
                if previous:
                    session = previous[-1]["receipt"].get("session_id")
            request = Request("planner", prompt, str(cwd), config["model"], timeout=self.call_timeout(),
                              max_turns=self.spec["max_turns"], session_id=session)
            pinned = {"role": role, "driver": config["driver"], "model": config["model"], "cwd": str(cwd),
                      "mode": "read-only", "procedure_hash": self.procedure()["hash"],
                      "prompt_hash": digest(prompt), "read_hash": digest(files(cwd)), "request": asdict(request), **(metadata or {})}
            self.journal.record("roles", key, pinned)
        if digest(files(cwd)) != pinned["read_hash"]:
            raise ValueError("read-only role input changed before dispatch")
        receipt = self.journal.reserve(key, "planner", digest(pinned))
        if receipt is None:
            try:
                receipt = self.drivers[config["driver"]].run(request,
                    lambda k, d: self.journal.event(key, k, d), lambda: self.controls(key)).as_dict()
                if len(receipt.get("output", "").encode()) > request.max_output_bytes:
                    receipt = Receipt("ERROR", error="role output limit exceeded", requested_model=request.model).as_dict()
            except Exception as exc:
                receipt = Receipt("UNKNOWN", error=f"role transport: {type(exc).__name__}: {exc}", requested_model=request.model).as_dict()
            receipt["requested_model"] = receipt.get("requested_model") or request.model
            receipt = self.journal.complete(key, receipt)
        if receipt["status"] == "UNKNOWN":
            raise DispatchBlocked("UNKNOWN role call requires reconciliation")
        if receipt["status"] != "COMPLETED":
            raise ValueError("role execution did not complete: " + str(receipt.get("error") or receipt["status"]))
        if digest(files(cwd)) != pinned["read_hash"]:
            raise ValueError("read-only role mutated its input")
        if receipt.get("actual_model") is not None and receipt["actual_model"] != request.model:
            raise ValueError("runtime-attested role model differs from requested model")
        return receipt

    def planning_prompt(self) -> str:
        return ("You are the persistent Tech Lead. Propose architecture and interfaces BEFORE implementation. "
                "Return ONLY one JSON object {architecture,interfaces,tasks,rationale?}. "
                "architecture is a nonempty STRING. interfaces MUST be a JSON ARRAY (never a keyed object), "
                "whose entries are strings or objects, e.g. [{\"name\":\"job.poll_job\",\"signature\":\"poll_job(fetch, job_id)\"}]. "
                "tasks MUST be a JSON ARRAY of objects. Each task has "
                "id,objective,check,depends_on,write_paths,acceptance,interface?; IDs are lowercase slugs. "
                "depends_on and write_paths are JSON ARRAYS of exact strings; acceptance is a nonempty STRING. "
                "Use 1..32 tasks per response, disjoint parallel scopes, cover required_checks; omit driver/max_attempts. "
                "Do not run implementations or change approved checks/policies.\n" + json.dumps({
                    "objective": self.spec["objective"], "checks": self.spec["checks"],
                    "required_checks": self.spec["required_checks"], "constraints": self.spec["constraints"],
                    "deliverables": self.spec["deliverables"], "procedure": self.procedure()}, ensure_ascii=False))

    def _lead_json(self, purpose: str, seed: str, prompt: str, validator) -> tuple[dict[str, Any], str]:
        """Versioned format repair of COMPLETED answers, never uncertain calls.

        Invalid answers remain immutable transport receipts. Corrective context
        changes both prompt and reservation key. No aggregate retry sentinel;
        repeated identical invalid output is an explicit liveness boundary.
        """
        prefix, packet = prompt.split("\n", 1)
        packet = json.loads(packet)
        base_hash = digest(prompt)
        while True:
            if self.stop.is_set():
                raise DispatchBlocked("operator stopped mission")
            while self.journal.paused() and not self.stop.is_set():
                self.stop.wait(.02)
            errors = [r["data"] for r in self.journal.records("format_errors")
                      if r["data"]["base_hash"] == base_hash and r["data"]["seed"] == seed]
            signatures = [(e["validator_error"], e["answer_hash"]) for e in errors]
            if len(signatures) != len(set(signatures)):
                raise ProposalInvalid(errors[-1]["run_key"], "repeated identical invalid Lead answer: " + errors[-1]["validator_error"])
            corrections = [{"validator_error": e["validator_error"], "prior_run_reference": "run:" + e["run_key"],
                            "prior_answer_hash": e["answer_hash"], "prior_final_answer_excerpt": e["final_answer_excerpt"]}
                           for e in errors[-3:]]
            current = prefix + "\n" + json.dumps({**packet, **({"format_correction": corrections,
                "correction_instruction": "Repair the exact validation errors. Return only the specified JSON schema; never annotate ID-array entries."}
                if corrections else {})}, ensure_ascii=False)
            key = "lead:" + purpose + ":" + digest({"seed": seed, "prompt": current})
            receipt = self.role_call("lead", key, current, Path(self.spec["source"]), metadata={"purpose": purpose})
            try:
                raw = strict_json(receipt["output"])
                validator(raw)
                return raw, key
            except ValueError as exc:
                error = {"purpose": purpose, "seed": seed, "base_hash": base_hash, "run_key": key,
                         "validator_error": str(exc), "answer_hash": digest(receipt["output"]),
                         "final_answer_excerpt": receipt["output"][:12000]}
                self.journal.record("format_errors", key, error)
                if any(e["validator_error"] == error["validator_error"] and e["answer_hash"] == error["answer_hash"] for e in errors):
                    raise ProposalInvalid(key, "repeated identical invalid Lead answer: " + str(exc)) from exc

    def _initial_plan(self) -> None:
        if self.journal.state()["revision"]:
            return
        if self.spec.get("initial_plan"):
            plan = copy.deepcopy(self.spec["initial_plan"])
            # validate_plan consumes model fields, not normalized executor fields.
            for t in plan["tasks"]:
                t.pop("driver", None)
                t.pop("max_attempts", None)
            self.admit_plan(plan, "initial")
            return
        self._lead_json("architecture", "initial", self.planning_prompt(),
                        lambda raw: self.admit_plan(raw, "architecture:" + digest(raw)))

    def planner(self, continuation, context) -> Decision:
        if self.stop.is_set() or self.journal.state()["stopped"]:
            return Decision("BLOCK", "operator stopped mission")
        if self.journal.paused():
            return Decision("WAIT", "operator paused new dispatch", wait_seconds=.05)
        if self._unresolved():
            return Decision("BLOCK", "unknown transport receipt requires reconciliation")
        reason = self.journal.budget_reason()
        if reason:
            return Decision("WAIT", reason, wait_seconds=.05)
        integration = continuation["context"].get("lead_integration")
        if integration is not None:
            ids = [t["id"] for t in self.active_tasks()]
            if integration != self.journal.state()["revision"]:
                return Decision("BLOCK", "integration revision superseded")
            capability = "workers.integrate"
            prompt = "Integrate verified scoped patches; no model implementation call."
            ident = "integration:" + str(integration)
        else:
            ident = continuation["context"]["native_task"]
            if ident not in self.journal.state()["active"]:
                return Decision("BLOCK", "historical node superseded")
            task = self.task(ident)
            ids = task["depends_on"]
            capability = "workers.execute"
            plan = self.journal.records("plans")[-1]["data"]["plan"]
            prompt = ("Implement ONLY this frozen task in the provided candidate. Dependencies are already "
                      "integrated into this snapshot. Do not alter evaluators, tests, credentials, control state "
                      "or files outside write_paths. Remove files only with /usr/bin/trash absolute-path, no '--'. "
                      "The public frozen task checker is supplied below. If self-testing, run ONLY this registered "
                      "argv, substituting its separate {candidate} element with your absolute current working directory; "
                      "leave every other element unchanged and set PYTHONDONTWRITEBYTECODE=1. Do not search controller "
                      "databases, sibling missions, global installed releases, other evaluators or unrelated checks. "
                      "Never modify the checker. Integration checks remain controller-owned and are not supplied. "
                      "Your report is not acceptance evidence.\n" + json.dumps({"task": task,
                      "architecture": plan["architecture"], "interfaces": plan["interfaces"],
                      "approved_check": {"id": task["check"], **self.spec["checks"][task["check"]]},
                      "candidate_substitution": {"placeholder": "{candidate}", "value": "absolute current working directory",
                                                 "replace_only_separate_argv_element": True},
                      "constraints": self.spec["constraints"]}, ensure_ascii=False))
        proofs = {}
        for dep in ids:
            upstream = self.continuations().get(dep)
            if not upstream or upstream["state"] in {"READY", "WAITING", "RUNNING", "VERIFYING"}:
                return Decision("WAIT", "waiting for dependency " + dep, wait_seconds=.02)
            if not self.evidence_current(dep):
                return Decision("BLOCK", "dependency lacks current independent evidence: " + dep)
            proofs[dep] = self.store.latest_evidence(upstream["id"])["id"]
        return Decision("EXECUTE", "frozen prerequisites verified", capability=capability,
            arguments={"task_id": ident, "continuation_id": continuation["id"], "dependencies": proofs, "prompt": prompt},
            risk_tier=1, verifier_id="workers.lead-check", terminal_on_pass=True,
            idempotency_key=stable_id("lead", continuation["id"], 1))

    def _current_payload(self, cont, seen=None) -> bool:
        if not cont or cont["state"] != "SUCCEEDED":
            return False
        evidence = self.store.latest_evidence(cont["id"])
        if not evidence or evidence["verdict"] != "PASS":
            return False
        data = evidence["payload"].get("evidence", {})
        try:
            if digest(files(Path(data["candidate"]))) != data["candidate_hash"] or data["acceptance_hash"] != self.spec["acceptance_hash"]:
                return False
            for name, sha in data["check_hashes"].items():
                if sha != digest(self.spec["checks"][name]) or not check_intact(self.spec["checks"][name]):
                    return False
            if data.get("review", {}).get("verdict") != "PASS":
                return False
            for dep, expected in data.get("dependencies", {}).items():
                upstream = self.continuations().get(dep)
                if not self.evidence_current(dep, seen) or self.store.latest_evidence(upstream["id"])["id"] != expected:
                    return False
            return True
        except (KeyError, OSError, ValueError):
            return False

    def evidence_current(self, ident: str, seen=None) -> bool:
        seen = set(seen or ())
        if ident in seen:
            return False
        return self._current_payload(self.continuations().get(ident), seen | {ident})

    def _ordered(self, ids: list[str]) -> list[str]:
        ordered, seen = [], set()
        def visit(ident):
            if ident in seen:
                return
            for dep in self.task(ident)["depends_on"]:
                visit(dep)
            seen.add(ident)
            ordered.append(ident)
        for ident in ids:
            visit(ident)
        return ordered

    def build_candidate(self, destination: Path, ids: list[str]) -> dict[str, str]:
        source = Path(self.spec["source"])
        if digest(files(source)) != self.spec["source_hash"]:
            raise ValueError("operator-approved source snapshot changed")
        copy_candidate(source, destination)
        for ident in self._ordered(ids):
            if not self.evidence_current(ident):
                raise ValueError("stale input evidence: " + ident)
            evidence = self.store.latest_evidence(self.continuations()[ident]["id"])["payload"]["evidence"]
            artifact = Path(evidence["candidate"])
            current = files(destination)
            for name, patch in evidence["patch"].items():
                if current.get(name) == patch["after"]:
                    continue
                if current.get(name) != patch["before"]:
                    raise ValueError(f"integration conflict: {ident}:{name}")
                target = destination / name
                if patch["after"] is None:
                    result = subprocess.run(["/usr/bin/trash", str(target.absolute())], capture_output=True, timeout=30)
                    if result.returncode or target.exists():
                        raise ValueError("recoverable Trash removal failed: " + name)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(artifact / name, target)
            if digest(files(artifact)) != evidence["candidate_hash"]:
                raise ValueError("input artifact changed during integration")
        return files(destination)

    def _admit_integration(self) -> None:
        revision = self.journal.state()["revision"]
        opportunity, _ = self.store.submit_opportunity(OpportunitySignal(source="techlead-integration",
            title=f"integration-{revision}", objective=self.spec["objective"], dedupe_key=f"techlead-integration:{revision}"))
        self.store.admit_opportunity(opportunity["id"], max_attempts=1, context={"lead_integration": revision})
        self.journal.phase("INTEGRATING")

    def _failures(self) -> list[dict[str, Any]]:
        failures = []
        for task in self.active_tasks():
            cont = self.continuations().get(task["id"])
            if cont and (cont["state"] in {"FAILED", "EXHAUSTED", "BLOCKED", "CANCELLED"} or
                         cont["state"] == "SUCCEEDED" and not self.evidence_current(task["id"])):
                evidence = self.store.latest_evidence(cont["id"])
                failures.append({"task": task, "state": cont["state"], "evidence": evidence,
                    "meaningful_outcome": bool(evidence and evidence["verdict"] in {"PASS", "FAIL"})})
        integrated = self.integration_continuation()
        if integrated and (integrated["state"] in {"FAILED", "BLOCKED", "EXHAUSTED"} or
                           integrated["state"] == "SUCCEEDED" and not self._current_payload(integrated)):
            evidence = self.store.latest_evidence(integrated["id"])
            failures.append({"task": {"id": "integration"}, "state": integrated["state"], "evidence": evidence,
                             "meaningful_outcome": bool(evidence and evidence["verdict"] == "FAIL")})
        return failures

    def diagnose(self, failures: list[dict[str, Any]]) -> bool:
        state = self.journal.state()
        identity = {"revision": state["revision"], "failures": failures}
        if state.get("resume_epoch", 0):
            identity["resume_epoch"] = state["resume_epoch"]
        key = "lead:diagnosis:" + digest(identity)
        if self.journal.get("diagnoses", key):
            saved = self.journal.get("diagnoses", key)
            if saved.get("plan"):
                self.admit_plan(saved["plan"], key)
                return True
            self.journal.phase("NEEDS_OPERATOR" if saved["action"] == "stop" else "WAITING_LEAD", "; ".join(saved["reasons"]))
            return False
        references = [f["evidence"]["id"] if f.get("evidence") else f.get("reference", "task:" + f["task"]["id"]) for f in failures]
        prompt = ("Classify the failed layer; ERROR/INVALID are operational/integrity failures, not meaningful "
            "implementation test outcomes. Never blindly retry. Return ONLY JSON {classification,reasons,evidence,action,plan?" +
            (",procedure_candidate?}. " if self.spec["rsi"].get("enabled", True) else "}. RSI disabled: omit procedure_candidate entirely. ") +
            "classification is specification|architecture|dependency|implementation|environment|integration. "
            "action is repair|replan|wait|stop. reasons is a nonempty JSON ARRAY of explanatory STRINGS. "
            "evidence is a nonempty JSON ARRAY containing ONLY exact strings copied verbatim from evidence_references: "
            "NO annotations, explanations, prefixes, suffixes or invented IDs in that array. Put explanations in reasons. "
            "For repair/replan include a full plan {architecture,interfaces,tasks,rationale?} with NEW task IDs. "
            "interfaces MUST be a JSON ARRAY of strings/objects, never a keyed object. "
            "To replace a node set repair_of to its active ID and preserve EXACT check/acceptance. Replace dependent "
            "nodes with NEW IDs and repaired edges too; do not modify historical nodes. Successful independent nodes "
            "remain automatically. Do not change executable checks, role models or budgets.\n" + json.dumps({
                "failures": redact(failures), "evidence_references": references, "active_tasks": self.active_tasks(),
                "checks": list(self.spec["checks"]), "required_checks": self.spec["required_checks"],
                "procedure": self.procedure(), "operator_resume": {"epoch": state.get("resume_epoch", 0), "reason": state.get("resume_reason")},
                "recent_diagnoses": self.journal.records("diagnoses")[-4:]}, ensure_ascii=False))
        raw, run_key = self._lead_json("diagnosis", key, prompt, lambda raw: self._validate_diagnosis(raw, references))
        self.journal.record("diagnoses", key, {**raw, "lead_run_key": run_key,
            "failure_references": references, "procedure_hash": self.procedure()["hash"]})
        if raw.get("procedure_candidate"):
            self.propose_procedure(raw["procedure_candidate"], key,
                                   [f["evidence"]["id"] for f in failures if f.get("evidence")])
        if raw["action"] == "stop":
            self.journal.phase("NEEDS_OPERATOR", "Lead stop proposal: " + "; ".join(raw["reasons"]))
            return False
        if raw.get("plan"):
            self.admit_plan(raw["plan"], key)
            return True
        self.journal.phase("WAITING_LEAD", "; ".join(raw["reasons"]))
        return False

    def _validate_diagnosis(self, raw, references) -> None:
        if set(raw) - {"classification", "reasons", "evidence", "action", "plan", "procedure_candidate"}:
            raise ValueError("unknown diagnosis fields")
        if "procedure_candidate" in raw and not self.spec["rsi"].get("enabled", True):
            raise ValueError("RSI disabled: omit procedure_candidate entirely")
        if not isinstance(raw.get("classification"), str) or raw["classification"] not in {"specification", "architecture", "dependency", "implementation", "environment", "integration"}:
            raise ValueError("Lead must classify a supported failure layer")
        _text_list(raw.get("reasons"), "diagnosis reasons")
        refs = _text_list(raw.get("evidence"), "diagnosis evidence")
        if set(refs) - set(references) or not isinstance(raw.get("action"), str) or raw["action"] not in {"repair", "replan", "wait", "stop"}:
            raise ValueError("diagnosis action or evidence references invalid")
        if raw["action"] in {"repair", "replan"} and not isinstance(raw.get("plan"), dict):
            raise ValueError("repair/replan requires a versioned plan")
        if raw["action"] in {"wait", "stop"} and raw.get("plan") is not None:
            raise ValueError("wait/stop diagnosis must not admit work")
        if raw.get("procedure_candidate") is not None and (not isinstance(raw["procedure_candidate"], str) or not 1 <= len(raw["procedure_candidate"]) <= 20000):
            raise ValueError("procedure_candidate must be bounded text")
        if raw.get("plan"):
            self._plan_revision(raw["plan"])

    def propose_procedure(self, text: str, origin: str, evidence_ids=None) -> str:
        if not self.spec["rsi"].get("enabled", True):
            raise ValueError("procedure proposals disabled by operator")
        if not isinstance(text, str) or not 1 <= len(text) <= 20000:
            raise ValueError("procedure proposal requires bounded text")
        key = digest({"text": text, "baseline": self.procedure()["hash"]})
        proposal = None
        error = None
        try:
            proposal = self.learning.propose(text, origin, list(evidence_ids or ()))
        except ProofUnavailable as exc:
            error = str(exc)
        self.journal.record("improvements", key, {"text": text, "hash": digest(text), "origin": origin,
            "baseline_hash": self.procedure()["hash"], "acceptance_hash": self.spec["acceptance_hash"],
            "status": "PROPOSED" if proposal else "PROPOSED_UNGROUNDED", "ledger_proposal": proposal,
            "proof_error": error, "promotion": "requires canonical frozen comparison, independent holdout and review evidence"})
        return proposal["id"] if proposal else key

    def request_stop(self) -> None:
        self.stop.set()
        self.journal.request_stop()
        self.sync_trial_children()

    def request_resume(self, reason: str = "operator resume") -> int:
        """Explicit operator resume; returns the durable re-diagnosis epoch.

        Saved wait/stop proposals remain evidence. Persistent stop and UNKNOWN
        reservations are never cleared by this API. Also resumes paused dispatch.
        """
        return self.journal.request_resume(reason)

    def _dispatch_blocked_phase(self, exc: DispatchBlocked) -> None:
        if self.stop.is_set() or self.journal.state()["stopped"]:
            phase = "STOPPED"
        elif self._unresolved() or "UNKNOWN" in str(exc):
            phase = "UNKNOWN"
        elif self.journal.paused():
            phase = "PAUSED"
        elif self.journal.budget_reason() or "max_iterations" in str(exc):
            phase = "BUDGET_EXHAUSTED"
        else:
            phase = "NEEDS_OPERATOR"
        self.journal.phase(phase, str(exc))

    def run(self, max_cycles: int | None = None) -> dict[str, Any]:
        if max_cycles is not None and (type(max_cycles) is not int or max_cycles < 1):
            raise ValueError("max_cycles must be a positive integer or None")
        if not self._run_lock.acquire(blocking=False):
            raise DispatchBlocked("mission controller already running")
        try:
            with (self.directory / "lead-controller.lock").open("a+") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise DispatchBlocked("another controller owns this mission") from exc
                self.journal.reconcile_expired()
                self.journal.reconcile_roles()
                self.prepare()
                if self.stop.is_set():
                    return self.snapshot()
                if not all(v["available"] for v in self.doctor().values()):
                    self.journal.phase("PREFLIGHT_FAILED", "native CLI preflight failed")
                    raise DispatchBlocked("native CLI preflight failed")
                supervisors = [AutonomousSupervisor(self.runtime, planner=self.planner,
                    config=SupervisorConfig(worker_id=f"lead-{os.getpid()}-{i}", idle_sleep_seconds=.02))
                    for i in range(self.spec["parallelism"])]
                cycles = 0
                with ThreadPoolExecutor(max_workers=self.spec["parallelism"]) as pool:
                    while not self.stop.is_set() and (max_cycles is None or cycles < max_cycles):
                        cycles += 1
                        if self.journal.paused():
                            self.journal.phase("PAUSED")
                            self.stop.wait(.02)
                            continue
                        if self._unresolved():
                            self.journal.phase("UNKNOWN", "unresolved native execution; no redispatch")
                            break
                        reason = self.journal.budget_reason()
                        if reason:
                            self.journal.phase("BUDGET_EXHAUSTED", reason)
                            break
                        try:
                            self._initial_plan()
                        except DispatchBlocked as exc:
                            self._dispatch_blocked_phase(exc)
                            break
                        except (ValueError, OSError) as exc:
                            latest = getattr(exc, "run_key", None)
                            if latest is None:
                                role_runs = [r for r in self.journal.runs() if r["role"] == "lead"]
                                latest = role_runs[-1]["key"] if role_runs else "planner-preflight"
                            failure = {"task": {"id": "planner"}, "state": "INVALID", "reference": "run:" + latest,
                                       "error": f"{type(exc).__name__}: {exc}", "meaningful_outcome": False}
                            self.journal.record("planning_errors", latest, failure)
                            if not self._diagnose_boundary([failure]):
                                break
                        work = [pool.submit(s.cycle) for s in supervisors]
                        for future in work:
                            result = future.result()
                            if (result.get("work") or {}).get("detail", {}).get("error"):
                                self.journal.record("runtime_errors", str(cycles) + ":" + result["worker_id"], result["work"])
                        if self._unresolved():
                            continue
                        failures = self._failures()
                        if failures:
                            self.journal.phase("DIAGNOSING")
                            if not self._diagnose_boundary(failures):
                                break
                            self._procedure_trial_boundary("diagnosed")
                            continue
                        if self.active_tasks() and all(self.evidence_current(t["id"]) for t in self.active_tasks()):
                            integrated = self.integration_continuation()
                            if integrated is None:
                                self._admit_integration()
                            elif self._current_payload(integrated):
                                self.journal.phase("COMPLETED")
                                self._procedure_trial_boundary("completed")
                                break
                        else:
                            self.journal.phase("IMPLEMENTING")
                        self.stop.wait(.02)
                return self.snapshot()
        finally:
            self._run_lock.release()

    def _diagnose_boundary(self, failures) -> bool:
        try:
            return self.diagnose(failures)
        except DispatchBlocked as exc:
            self._dispatch_blocked_phase(exc)
        except (ValueError, OSError) as exc:
            self.journal.record("diagnosis_errors", digest(failures), {"error": f"{type(exc).__name__}: {exc}"})
            self.journal.phase("NEEDS_OPERATOR", f"invalid Lead diagnosis: {exc}")
        return False

    def _trial_observations(self) -> dict[str, Any]:
        """Same-store runner records plus read-only registered child transport.

        Child projections are not verdict copies. A missing DB is an explicit
        unknown, never a zero-reservation arm. No child controller is constructed.
        """
        records = {name: self.journal.records(name) for name in (
            "trial_pending", "trial_requests", "trial_results", "paired_trials", "paired_trial_arms",
            "paired_trial_results", "paired_trial_fences", "trial_children", "paired_trial_children",
            "trial_sessions", "trial_settlements")}
        registrations = {}
        for category in ("trial_children", "paired_trial_children"):
            for row in records[category]:
                directory = row["data"].get("directory")
                registrations.setdefault(directory, []).append({"category": category, **row})
        children = []
        for directory, refs in registrations.items():
            if isinstance(directory, str) and Path(directory).resolve() == self.directory.resolve():
                child = {"directory": directory, "read_status": "ERROR", "phase": "UNKNOWN", "reservations": None,
                         "runs": None, "unresolved": None, "metering": None,
                         "error": "registered trial child aliases its parent control"}
            else:
                child = LeadJournal.inspect_child(directory)
            children.append({**child, "registrations": refs})
        children.sort(key=lambda c: str(c["directory"]))
        read_errors = [{"directory": c["directory"], "error": c["error"]} for c in children if c["read_status"] != "OK"]
        unresolved = ["trial:" + c["directory"] + ":" + key for c in children if c["read_status"] == "OK" for key in c["unresolved"]]
        unknown = any(r["status"] == "UNKNOWN" or r["receipt_status"] == "UNKNOWN"
                      for c in children if c["read_status"] == "OK" for r in c["runs"])
        pending, fenced = [], []
        for request_category, result_category in (("trial_requests", "trial_results"), ("paired_trials", "paired_trial_results")):
            results = {r["key"]: r["data"] for r in records[result_category]}
            for request in records[request_category]:
                result = results.get(request["key"])
                ident = request_category + ":" + request["key"]
                if result is None or result.get("status") in {"PENDING", "IN_FLIGHT"}:
                    pending.append(ident)
                elif result.get("status") not in TRIAL_TERMINAL_STATUSES:
                    fenced.append(ident)
        active = self.journal.state().get("active_trials", {})
        terminal_core_keys = {r["key"] for r in records["trial_results"] if r["data"].get("status") in TRIAL_TERMINAL_STATUSES}
        pending.extend("trial_pending:" + r["key"] for r in records["trial_pending"] if r["key"] not in terminal_core_keys)
        active_fenced = any(r.get("status") in {"FENCED", "ERROR", "UNKNOWN"} for r in active.values())
        status = "ERROR" if read_errors else "UNKNOWN" if unknown else "FENCED" if fenced or active_fenced else \
                 "RUNNING" if pending or active or unresolved else "IDLE"
        return {"pending": records["trial_pending"], "requests": records["trial_requests"], "results": records["trial_results"],
                **{k: v for k, v in records.items() if not k.startswith("trial_")},
                "trial_children": records["trial_children"], "sessions": records["trial_sessions"],
                "settlements": records["trial_settlements"], "children": children, "active": active,
                "pending_request_ids": pending, "fenced_request_ids": fenced, "read_errors": read_errors,
                "unresolved": unresolved, "status": status}

    def _snapshot_counters(self, trials: dict[str, Any]) -> dict[str, Any]:
        parent = self.journal.counters()
        children = trials["children"]
        observed = [c for c in children if c["read_status"] == "OK"]
        known = sum(c["reservations"] for c in observed)
        child_calls = None if trials["read_errors"] else known
        total = None if child_calls is None else parent["calls"] + child_calls
        amounts = {}
        missing = copy.deepcopy(parent["missing_metering"])
        for field in ("tokens", "cost_usd"):
            measured = [c["metering"][field] for c in observed]
            child_amount = sum(measured) if not trials["read_errors"] and all(v is not None for v in measured) else None
            amounts["parent_" + field] = parent[field]
            amounts["trial_child_" + field] = child_amount
            amounts[field] = parent[field] + child_amount if parent[field] is not None and child_amount is not None else None
            for child in observed:
                missing[field].extend("trial:" + child["directory"] + ":" + k for k in child["metering"]["missing_metering"][field])
        return {**parent, **amounts, "calls": total, "parent_calls": parent["calls"], "trial_child_calls": child_calls,
                "total_calls": total, "known_trial_child_calls": known, "known_total_calls": parent["calls"] + known,
                "missing_metering": missing, "child_read_errors": trials["read_errors"],
                "metering_scope": "parent_and_registered_trial_children",
                "aggregate_cap_policy": "finite parent caps conservatively fence child construction"}

    def snapshot(self) -> dict[str, Any]:
        state = self.journal.state()
        nodes = []
        for task in self.tasks():
            cont = self.continuations().get(task["id"])
            evidence = self.store.latest_evidence(cont["id"]) if cont else None
            nodes.append({**task, "state": cont["state"] if cont else "ADMITTING", "attempts": cont["attempt_count"] if cont else 0,
                "active": task["id"] in state["active"], "superseded_by": state["superseded"].get(task["id"]),
                "verdict": evidence["verdict"] if evidence else "UNVERIFIED", "evidence_id": evidence["id"] if evidence else None,
                "verification": evidence["payload"] if evidence else None,
                "stale": bool(cont and cont["state"] == "SUCCEEDED" and not self.evidence_current(task["id"]))})
        integrated = self.integration_continuation()
        proof = self.store.latest_evidence(integrated["id"]) if integrated else None
        runs = self.journal.runs()
        unresolved = [r["key"] for r in runs if r["status"] in {"UNKNOWN", "IN_FLIGHT"}]
        verified = not unresolved and bool(nodes) and self._current_payload(integrated) and all(
            n["state"] == "SUCCEEDED" and not n["stale"] for n in nodes if n["active"])
        trials = self._trial_observations()
        counters = self._snapshot_counters(trials)
        phase = "STOPPED" if state["stopped"] else "PAUSED" if self.journal.paused() else state["phase"]
        if phase not in {"STOPPED", "PAUSED"}:
            if trials["status"] == "UNKNOWN":
                phase = "UNKNOWN"
            elif trials["status"] in {"ERROR", "FENCED"}:
                phase = "TRIAL_FENCED"
            elif trials["status"] == "RUNNING":
                phase = "TRIAL_RUNNING"
        if phase == "COMPLETED" and not verified:
            phase = "STALE"
        limits = {name: self.spec[name] for name in ("max_calls", "max_iterations", "max_tokens", "max_cost_usd", "max_wall_minutes", "max_turns")}
        return {"objective": self.spec["objective"], "phase": phase, "reason": state.get("reason", ""), "paused": self.journal.paused(),
            "stopped": state["stopped"], "revision": state["revision"], "resume_epoch": state.get("resume_epoch", 0), "nodes": nodes, "runs": runs,
            "plans": self.journal.records("plans"), "diagnoses": self.journal.records("diagnoses"),
            "format_errors": self.journal.records("format_errors"),
            "reviews": self.journal.records("reviews"), "integration": {"continuation": integrated, "evidence": proof,
                "current": self._current_payload(integrated), "builds": self.journal.records("integrations")},
            "procedure": self.procedure(), "improvements": self.journal.records("improvements"),
            "improvement_errors": self.journal.records("improvement_errors"),
            "rsi": self.learning.history(),
            "procedure_trials": trials, "counters": counters, "budgets": limits,
            "budget_display": {k: "unlimited" if v is None else str(v) for k, v in limits.items()},
            "native_call_reservations": counters["total_calls"], "parent_native_call_reservations": len(runs),
            "trial_native_call_reservations": counters["trial_child_calls"],
            "max_calls": self.spec["max_calls"], "unresolved": unresolved + trials["unresolved"],
            "project_verified": bool(verified), "all_verified": bool(verified) and trials["status"] == "IDLE",
            "controller_errors": self.journal.records("runtime_errors") + self.journal.records("diagnosis_errors"),
            "roles": self.spec["roles"], "validation_kind": self.spec["validation_kind"], "versions": self.versions}


class LeadCapability:
    name = "workers.execute"
    risk_tier = 1
    replay_safe = True  # Journal replay, not native-call redispatch.
    description = "Scoped Sol implementation on pinned, integrated dependency evidence"

    def __init__(self, mission):
        self.mission = mission

    def execute(self, arguments, *, idempotency_key) -> CapabilityResult:
        m = self.mission
        task = m.task(arguments["task_id"])
        cont = m.store.get_continuation(arguments["continuation_id"])
        if cont["context"].get("task_hash") != digest(task):
            raise ValueError("frozen task/continuation mismatch")
        if not check_intact(m.spec["checks"][task["check"]]):
            return CapabilityResult("INVALID", {"integrity_error": "immutable evaluator hash changed before dispatch"})
        base = m.directory / "attempts" / idempotency_key
        candidate, artifact = base / "candidate", base / "artifact"
        fingerprint = digest({"arguments": arguments, "task": task, "spec": digest(m.spec)})
        m.journal.record("roles", idempotency_key, {"role": "worker", "driver": "codex",
            "model": m.spec["roles"]["worker"]["model"], "mode": "workspace-write", "cwd": str(candidate),
            "procedure_hash": m.procedure()["hash"], "node": task["id"], "task_hash": digest(task)})
        try:
            receipt = m.journal.reserve(idempotency_key, task["id"], fingerprint,
                continuation_id=cont["id"], lease_token=cont["lease_token"])
        except DispatchBlocked as exc:
            return CapabilityResult("UNKNOWN" if m._unresolved() else "ERROR", {"run_key": idempotency_key}, error=str(exc))
        if receipt is None:
            started = False
            native_receipt = None
            try:
                before = m.build_candidate(candidate, task["depends_on"])
                config = m.spec["roles"]["worker"]
                request = Request(task["id"], arguments["prompt"], str(candidate), config["model"], mode="workspace-write",
                                  timeout=m.call_timeout(), max_turns=m.spec["max_turns"])
                m.journal.event(idempotency_key, "driver", {"driver": "codex", "requested_model": request.model, "task_hash": digest(task)})
                started = True
                receipt = m.drivers["codex"].run(request, lambda k, d: m.journal.event(idempotency_key, k, d),
                    lambda: m.controls(idempotency_key)).as_dict()
                native_receipt = receipt
                after = files(candidate)
                if any((candidate / name).exists() for name in (".git", ".sisyfus")):
                    raise ValueError("worker wrote candidate control directories")
                patch = {p: {"before": before.get(p), "after": after.get(p)} for p in sorted(before.keys() | after.keys())
                         if before.get(p) != after.get(p)}
                outside = [p for p in patch if not any(paths_overlap(p, scope) and (p == scope or Path(scope) in Path(p).parents)
                                                       for scope in task["write_paths"])]
                if outside:
                    receipt.update(scope_error="writes outside frozen ownership: " + ", ".join(outside))
                if len(receipt.get("output", "").encode()) > request.max_output_bytes:
                    receipt.update(status="ERROR", error="worker output limit exceeded")
                sha = copy_candidate(candidate, artifact)
                receipt.update(candidate=str(artifact), candidate_hash=sha, patch=patch, dependencies=arguments["dependencies"],
                               task_hash=digest(task), requested_model=receipt.get("requested_model") or request.model)
            except Exception as exc:
                error = f"worker boundary: {type(exc).__name__}: {exc}"
                if native_receipt is not None:
                    # A known terminal native receipt remains known even when
                    # local scope/snapshot validation fails afterward.
                    receipt = {**native_receipt, "integrity_error": error,
                               "requested_model": native_receipt.get("requested_model") or m.spec["roles"]["worker"]["model"]}
                else:
                    receipt = Receipt("UNKNOWN" if started else "ERROR", error=error,
                                      requested_model=m.spec["roles"]["worker"]["model"]).as_dict()
            receipt = m.journal.complete(idempotency_key, receipt)
        return CapabilityResult(receipt["status"], {**receipt, "run_key": idempotency_key})


class IntegrationCapability:
    name = "workers.integrate"
    risk_tier = 1
    replay_safe = True
    description = "Apply verified nonconflicting scoped patches to a fresh integrated project"

    def __init__(self, mission):
        self.mission = mission

    def execute(self, arguments, *, idempotency_key) -> CapabilityResult:
        m = self.mission
        saved = m.journal.get("integrations", idempotency_key)
        if saved:
            return CapabilityResult(saved["status"], saved)
        candidate = m.directory / "integration" / idempotency_key / "candidate"
        try:
            after = m.build_candidate(candidate, list(arguments["dependencies"]))
            before = files(Path(m.spec["source"]))
            patch = {p: {"before": before.get(p), "after": after.get(p)} for p in sorted(before.keys() | after.keys())
                     if before.get(p) != after.get(p)}
            saved = {"status": "COMPLETED", "candidate": str(candidate), "candidate_hash": digest(files(candidate)),
                     "dependencies": arguments["dependencies"], "run_key": idempotency_key, "patch": patch}
        except Exception as exc:
            saved = {"status": "ERROR", "run_key": idempotency_key, "error": f"integration boundary: {type(exc).__name__}: {exc}"}
        m.journal.record("integrations", idempotency_key, saved)
        return CapabilityResult(saved["status"], saved)


class LeadVerifier:
    verifier_id = "workers.lead-check"

    def __init__(self, mission):
        self.mission = mission

    def check(self, name: str, data: dict[str, Any]) -> dict[str, Any]:
        m = self.mission
        check = m.spec["checks"][name]
        key = "check:" + digest({"run": data["run_key"], "check": digest(check), "candidate": data["candidate_hash"]})
        cached = m.journal.get("measurements", key)
        if cached:
            return {"id": key, **cached}
        observation = {}
        if not check_intact(check):
            classified = {"status": "INVALID", "summary": "immutable evaluator hash changed"}
        else:
            proc = None
            try:
                argv = [data["candidate"] if a == "{candidate}" else a for a in check["argv"]]
                proc = Process(argv, cwd=str(m.directory), env={**environment(), "PYTHONDONTWRITEBYTECODE": "1"},
                               timeout=min(check.get("timeout", 30), m.call_timeout()), max_bytes=1_000_000)
                proc.send_bytes(b"", close=True)
                messages = []
                while True:
                    try:
                        message = proc.receive()
                    except EOFError:
                        break
                    if message is not None:
                        messages.append(message)
                code = proc.wait()
                if len(messages) != 1 or not isinstance(messages[0], dict):
                    raise ValueError("measurement requires exactly one JSON object")
                observation = messages[0]
                observation["execution"] = {"exit_code": code, "timed_out": False}
            except Exception as exc:
                observation = {"execution": {"error": f"{type(exc).__name__}: {exc}"}}
            finally:
                if proc is not None:
                    proc.close()
            classified = classify_observation(check["contract"], observation)
            if not check_intact(check) or digest(files(Path(data["candidate"]))) != data["candidate_hash"]:
                classified = {"status": "INVALID", "summary": "candidate/evaluator changed during measurement"}
        saved = {"check": name, "check_hash": digest(check), "candidate_hash": data["candidate_hash"],
                 "classification": classified, "measurement": redact(observation)}
        m.journal.record("measurements", key, saved)
        return {"id": key, **saved}

    def verify(self, context, decision, result) -> VerificationResult:
        m = self.mission
        data = dict(result.observation)
        def verdict(status, summary):
            return VerificationResult(status, self.verifier_id, summary, assurance=AssuranceLevel.B, evidence=data)
        if result.status == "INVALID":
            return verdict(Verdict.INVALID, data.get("integrity_error") or "candidate/evaluator integrity invalid")
        if result.status != "COMPLETED":
            return verdict(Verdict.ERROR, result.error or data.get("error") or "execution did not complete")
        if data.get("integrity_error"):
            return verdict(Verdict.INVALID, data["integrity_error"])
        if data.get("scope_error"):
            return verdict(Verdict.INVALID, data["scope_error"])
        if data.get("actual_model") is not None and data["actual_model"] != m.spec["roles"]["worker"]["model"]:
            return verdict(Verdict.INVALID, "runtime-attested worker model differs from requested model")
        if digest(files(Path(data["candidate"]))) != data["candidate_hash"]:
            return verdict(Verdict.INVALID, "candidate changed before verification")
        for dep, expected in data.get("dependencies", {}).items():
            upstream = m.continuations().get(dep)
            if not m.evidence_current(dep) or m.store.latest_evidence(upstream["id"])["id"] != expected:
                return verdict(Verdict.INVALID, "dependency evidence drift")
        integration = decision.capability == "workers.integrate"
        task = {"objective": m.spec["objective"], "acceptance": "whole-project integration checks", "id": decision.arguments["task_id"]} if integration else m.task(decision.arguments["task_id"])
        names = m.spec["integration_checks"] if integration else [task["check"]]
        if not all(check_intact(m.spec["checks"][name]) for name in names):
            return verdict(Verdict.INVALID, "immutable evaluator hash changed before verification")
        checks = [self.check(name, data) for name in names]
        data.update(checks=checks, check_hashes={c["check"]: c["check_hash"] for c in checks}, acceptance_hash=m.spec["acceptance_hash"])
        failed = next((c for c in checks if c["classification"]["status"] != "PASS"), None)
        if failed:
            return verdict(failed["classification"]["status"], failed["classification"]["summary"])
        key = "review:" + data["run_key"]
        review = m.journal.get("reviews", key)
        if review is None:
            refs = [c["id"] for c in checks]
            prompt = ("Independent read-only review in a NEW session, not the Lead/worker session. Inspect the frozen "
                "task, candidate and deterministic receipts. Return ONLY JSON {verdict,reasons,evidence}; verdict "
                "is PASS or FAIL, reasons is a nonempty JSON ARRAY of explanatory strings. evidence is a nonempty JSON ARRAY "
                "of ONLY EXACT strings copied verbatim from evidence_references, with no annotations, explanations or invented IDs. "
                "Cite ALL provided deterministic receipt IDs "
                "for PASS. Missing/failed test evidence is never approvable. Do not edit any file.\n" + json.dumps({
                    "task": task, "mission_objective": m.spec["objective"], "deliverables": m.spec["deliverables"],
                    "kind": "integration" if integration else "task", "candidate_hash": data["candidate_hash"],
                    "patch": data.get("patch", {}), "deterministic_evidence": checks, "evidence_references": refs,
                    "dependencies": data.get("dependencies", {}), "constraints": m.spec["constraints"]}, ensure_ascii=False))
            try:
                # Pause suppresses NEW calls while retaining the completed worker
                # receipt. The running verifier remains leased until resume/stop.
                while m.journal.paused() and not m.stop.is_set():
                    m.stop.wait(.02)
                receipt = m.role_call("reviewer", key, prompt, Path(data["candidate"]), metadata={
                    "node": task["id"], "candidate_hash": data["candidate_hash"], "test_references": refs})
                raw = strict_json(receipt["output"])
                if set(raw) != {"verdict", "reasons", "evidence"} or not isinstance(raw["verdict"], str) or raw["verdict"] not in {"PASS", "FAIL"}:
                    raise ValueError("review requires classified PASS/FAIL, reasons and evidence")
                _text_list(raw["reasons"], "review reasons")
                _text_list(raw["evidence"], "review evidence")
                if set(raw["evidence"]) - set(refs) or raw["verdict"] == "PASS" and set(raw["evidence"]) != set(refs):
                    raise ValueError("review references missing or unrecognized test evidence")
                review = {**raw, "candidate_hash": data["candidate_hash"], "run_key": key}
            except DispatchBlocked as exc:
                return verdict(Verdict.ERROR, str(exc))
            except ValueError as exc:
                review = {"verdict": "INVALID", "reasons": [str(exc)], "evidence": [], "run_key": key,
                          "candidate_hash": data["candidate_hash"]}
            if digest(files(Path(data["candidate"]))) != data["candidate_hash"]:
                review = {**review, "verdict": "INVALID", "reasons": ["read-only reviewer mutated candidate"]}
            m.journal.record("reviews", key, review)
        data["review"] = review
        if not all(check_intact(m.spec["checks"][name]) for name in names) or digest(files(Path(data["candidate"]))) != data["candidate_hash"]:
            return verdict(Verdict.INVALID, "candidate/evaluator changed during independent review")
        return verdict(review["verdict"], "; ".join(review["reasons"]))
