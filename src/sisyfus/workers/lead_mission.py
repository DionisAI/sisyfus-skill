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
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from ..autonomy.models import AssuranceLevel, CapabilityResult, Decision, OpportunitySignal, VerificationResult, Verdict, canonical_json, stable_id, utc_now
from ..autonomy.policy import AutonomyPolicy, CapabilityRegistry, IdempotencyConflictError
from ..autonomy.runtime import AutonomousRuntime
from ..autonomy.supervisor import AutonomousSupervisor, SupervisorConfig
from ..research_v2.verifier import classify_observation
from .journal import DispatchBlocked
from .lead_contracts import load_lead_spec, paths_overlap, validate_plan
from .lead_journal import LeadJournal
from .lead_learning import ProcedureLedger, ProofUnavailable
from .mission import Mission, check_intact, copy_candidate, files
from .mission_inbox import MissionInbox
from .protocol import Receipt, Request, digest, environment, redact
from . import remote_artifacts
from .remote_driver import RemoteCodexDriver
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


class RemotePlacementUnavailable(DispatchBlocked):
    def __init__(self, placement: dict[str, Any]):
        super().__init__("远端执行传输尚未接入")
        self.placement = placement


class RemoteCurrencyLost(DispatchBlocked):
    """A transport identity change is uncertainty, not permission to settle."""


def remote_output_paths(before: dict[str, str], write_paths: list[str], candidate: Path) -> list[str]:
    """Pin exact v1 files; existing directory scopes never grant new descendants.

    Validate even excluded directory names. The final union obeys the node's
    size, strict relative-path and case-fold/file-parent collision boundaries.
    This read-only helper neither creates files nor broadens task ownership.
    """
    from .node_claims import MAX_FILES, _path, _paths
    if not isinstance(before, dict) or not isinstance(write_paths, list):
        raise ValueError("remote outputs require prepared files and fixed write paths")
    scopes = [_path(p) for p in write_paths]
    # Directory/file overlap is legitimate in task ownership, but only actual
    # directories may be excluded from the exact file allowlist below.
    _paths([p for p in scopes if not (candidate / p).is_dir()])
    for p in before:
        _path(p)
    outputs = sorted(set(before) | {p for p in scopes if not (candidate / p).is_dir()})
    if len(outputs) > MAX_FILES:
        raise ValueError("remote output path count exceeds 128-file bound")
    _paths(outputs)
    return outputs


def _remote_tree(root: Path) -> dict[str, Any]:
    """Read every entry, rejecting missing/incomplete/control/nonregular trees."""
    report = remote_artifacts.full_tree_manifest(root)
    _, errors = remote_artifacts._tree_integrity(report)
    if errors:
        raise remote_artifacts.ArtifactError({"valid": False, "errors": errors, "tree": report})
    return report


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
        self.inbox = MissionInbox(self.journal)
        self.journal.after_event = self.inbox.observe_native_in
        self._node_claims = None
        self._node_lock = threading.Lock()
        # Only the host may inject this process-local transport capability.
        # Registration, staging pins and persisted specs never enable it.
        self.remote_execution_ready: Callable[[], bool] = lambda: False
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

    @property
    def node_claims(self):
        """Lazy, same-store transport sidecar, not the capability registry.

        Construction/inventory never offers, claims or dispatches native work.
        Recheck trial policy even for a cached backend; trials stay local.
        """
        with self._node_lock:
            with self.store._transaction(immediate=False) as db:
                if not self.inbox.context_allowed(db):
                    raise PermissionError("node placement is excluded for trial children")
            if self._node_claims is None:
                from .node_claims import NodeClaims
                from .node_registry import NodeRegistry
                self._node_claims = NodeClaims(self.journal, NodeRegistry(self.journal),
                                               self.directory / "remote" / "artifacts")
            return self._node_claims

    def _placement_in(self, db, task_id: str) -> dict[str, Any]:
        row = db.execute("SELECT value FROM metadata WHERE key=?",
                         (self.journal.prefix + "placement:" + task_id,)).fetchone()
        return json.loads(row[0]) if row else {"kind": "local"}

    def placement(self, task_id: str) -> dict[str, Any]:
        """No legacy backfill, backend construction or local fingerprint change."""
        if not isinstance(task_id, str) or not task_id or len(task_id.encode()) > 100:
            raise ValueError("task_id must be bounded nonempty text")
        with self.store._transaction(immediate=False) as db:
            return self._placement_in(db, task_id)

    def assign_placement(self, task_id: str, node_id: str, request_id: str) -> dict[str, Any]:
        """Explicit operator-only pin; every eligibility check shares one commit.

        Request fingerprints cover operator input, not the evolving plan. Exact
        retries read the original pin even after supersession/revocation or a
        native reservation; a fresh request never rebinds such a reservation.
        """
        from .node_registry import validate_request_id
        validate_request_id(request_id)
        if not isinstance(task_id, str) or not task_id or len(task_id.encode()) > 100:
            raise ValueError("task_id must identify an active frozen implementation task")
        if not isinstance(node_id, str) or not node_id or len(node_id.encode()) > 100:
            raise ValueError("node_id must identify a mission node")
        fingerprint = digest({"task_id": task_id, "node_id": node_id})
        request_key = self.journal.prefix + "placement_request:" + request_id

        def cached(db):
            row = db.execute("SELECT value FROM metadata WHERE key=?", (request_key,)).fetchone()
            if row is None:
                return None
            saved = json.loads(row[0])
            if saved["fingerprint"] != fingerprint:
                raise IdempotencyConflictError("placement request_id reused for different input")
            return saved["placement"]

        with self.store._transaction(immediate=False) as db:
            replay = cached(db)
            if replay is not None:
                return replay
        registry = self.node_claims.registry  # Initialize outside the assignment transaction.
        with self.store._transaction() as db:
            replay = cached(db)
            if replay is not None:
                return replay
            if not self.inbox.context_allowed(db):
                raise PermissionError("node placement is excluded for trial children")
            state = json.loads(db.execute("SELECT value FROM metadata WHERE key=?",
                                          (self.journal.prefix + "state",)).fetchone()[0])
            plans = db.execute("SELECT value FROM metadata WHERE substr(key,1,?)=?",
                               (len(self.journal.prefix + "plans:"), self.journal.prefix + "plans:")).fetchall()
            tasks = [t for p in plans for t in json.loads(p[0])["data"]["plan"]["tasks"]]
            task = next((t for t in tasks if t["id"] == task_id), None)
            if task is None or task_id not in state["active"]:
                raise ValueError("placement requires an active frozen implementation task")
            task_hash = digest(task)
            prior = self._placement_in(db, task_id)
            if prior["kind"] != "local" and (prior["node_id"] != node_id or prior["task_hash"] != task_hash):
                raise IdempotencyConflictError("pinned placement node or task hash changed")
            contexts = [json.loads(r[0]) for r in db.execute("SELECT context_json FROM continuations").fetchall()]
            if not any(c.get("native_task") == task_id and c.get("lead_kind") == "implementation"
                       and c.get("task_hash") == task_hash for c in contexts):
                raise ValueError("placement requires a matching frozen implementation continuation")
            if db.execute("SELECT 1 FROM native_worker_runs WHERE task_id=? LIMIT 1", (task_id,)).fetchone():
                raise DispatchBlocked("existing native reservation fences new task placement")
            registry._active(db, node_id)
            placement = prior if prior["kind"] != "local" else {
                "kind": "remote", "mission_id": registry.mission_id, "task_id": task_id,
                "node_id": node_id, "task_hash": task_hash, "revision": state["revision"],
                "request_id": request_id, "execution_ready": False, "created_at": utc_now()}
            if prior["kind"] == "local":
                db.execute("INSERT INTO metadata VALUES(?,?)",
                           (self.journal.prefix + "placement:" + task_id, canonical_json(placement)))
            db.execute("INSERT INTO metadata VALUES(?,?)", (request_key,
                       canonical_json({"fingerprint": fingerprint, "placement": placement})))
            self.journal._event(db, "node_placement_assigned" if prior["kind"] == "local" else "node_placement_readback",
                                request_id, {"request_id": request_id, "placement": placement}, actor="operator")
            return placement

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
        child.journal.record("inbox_policy", "trial-child", {"operator_context": "excluded"})
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
        # Only ordinary orchestration may consume mission supplements. None is
        # the legacy controller-owned direct-call API (no declared purpose), not
        # a promotion purpose; preserve its context/replay compatibility. Every
        # explicit purpose outside this allowlist, including future procedure
        # generation/promotion purposes, stays outside the channel. A replay's
        # pinned purpose wins over new/default caller metadata.
        purpose = (pinned or metadata or {}).get("purpose")
        context_eligible = role == "lead" and purpose in (None, "architecture", "diagnosis")
        if pinned:
            if pinned["prompt_hash"] != digest(prompt) or pinned["role"] != role or pinned["cwd"] != str(cwd):
                raise ValueError("role call input drift under a reserved identity")
            request = Request(**pinned["request"])
        else:
            session = None
            if context_eligible:
                previous = [r for r in self.journal.runs() if r["role"] == "lead" and r["receipt"] and r["receipt"]["status"] == "COMPLETED"
                            and (r["role_metadata"] or {}).get("procedure_hash") == self.procedure()["hash"]
                            and (r["role_metadata"] or {}).get("purpose") in (None, "architecture", "diagnosis")]
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
        receipt = self.journal.reserve(key, "planner", digest(pinned),
            on_reserved=(lambda db: self.inbox.bind(db, key, role=role, task_id=None, prompt=prompt))
                        if context_eligible else None)
        if receipt is None:
            context = self.inbox.for_run(key) if context_eligible else None
            if context is not None:
                request = Request(**{**asdict(request), "prompt": context["prompt"]})
            elif role == "lead" and not context_eligible and request.session_id is not None:
                # Also isolate a role record pinned before admission by older
                # code: resuming an ordinary session would import its operator
                # data even without a new binding. Cached/UNKNOWN runs never
                # reach this branch and remain unmodified, never resent.
                request = Request(**{**asdict(request), "session_id": None})
            try:
                receipt = self.drivers[config["driver"]].run(request,
                    lambda k, d: self.native_event(key, k, d), lambda: self.controls(key)).as_dict()
                if len(receipt.get("output", "").encode()) > request.max_output_bytes:
                    receipt = Receipt("ERROR", error="role output limit exceeded", requested_model=request.model).as_dict()
            except Exception as exc:
                receipt = Receipt("UNKNOWN", error=f"role transport: {type(exc).__name__}: {exc}", requested_model=request.model).as_dict()
            if context is not None:
                receipt["context_binding_hash"] = digest(context)
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

    def native_event(self, key: str, kind: str, data: dict[str, Any]) -> None:
        self.journal.event(key, kind, data)

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

    @contextmanager
    def _placement_controller(self):
        """Preparation owns exactly the same exclusion boundaries as Start."""
        if not self._run_lock.acquire(blocking=False):
            raise DispatchBlocked("mission controller already running")
        try:
            with (self.directory / "lead-controller.lock").open("a+") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise DispatchBlocked("another controller owns this mission") from exc
                yield
        finally:
            self._run_lock.release()

    def _placement_preparation(self) -> dict[str, Any] | None:
        with self.store._transaction(immediate=False) as db:
            row = db.execute("SELECT value FROM metadata WHERE key=?",
                             (self.journal.prefix + "placement_preparation",)).fetchone()
        return json.loads(row[0]) if row else None

    def _save_placement_preparation(self, saved, *, phase=None, superseded=None) -> dict[str, Any]:
        """Request/state and their diagnostic event share the canonical commit."""
        with self.store._transaction() as db:
            if superseded is not None:
                self.journal.record_in(db, "placement_preparation_history", superseded["request_id"],
                                       {**superseded, "status": "SUPERSEDED"})
            db.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)",
                       (self.journal.prefix + "placement_preparation", canonical_json(saved)))
            state = json.loads(db.execute("SELECT value FROM metadata WHERE key=?",
                                          (self.journal.prefix + "state",)).fetchone()[0])
            paused = db.execute("SELECT value FROM metadata WHERE key='native_worker_paused'").fetchone()
            if phase is not None:
                state.update(phase="STOPPED" if state["stopped"] or self.stop.is_set() else
                             "PAUSED" if paused and paused[0] == "1" else phase,
                             reason=saved.get("reason", ""))
                db.execute("UPDATE metadata SET value=? WHERE key=?",
                           (canonical_json(state), self.journal.prefix + "state"))
            self.journal._event(db, "placement_preparation", saved["request_id"],
                                {"preparation": saved, "state": state}, actor="operator")
        return saved

    def _request_placement_preparation_locked(self, request_id) -> dict[str, Any]:
        from .node_registry import validate_request_id
        validate_request_id(request_id)
        with self.store._transaction(immediate=False) as db:
            if not self.inbox.context_allowed(db):
                raise PermissionError("placement preparation is excluded for trial children")
        saved = self._placement_preparation()
        if saved is None or saved["request_id"] != request_id:
            archived = self.journal.get("placement_preparation_history", request_id)
            if archived is not None:
                return archived
        if saved and saved["status"] == "PLANNING":
            # Owning both locks proves the previous planning owner is gone.
            # Even the durable-before-reservation gap is uncertain, not retryable.
            self.journal.reconcile_roles()
            saved = self._save_placement_preparation({**saved, "status": "UNKNOWN",
                "known_nonexecuted": False, "reason": "interrupted placement planning; reconcile before execution"},
                phase="UNKNOWN")
        if saved and saved["request_id"] == request_id:
            return saved
        if saved and not (saved["status"] in {"BLOCKED", "REQUESTED"} and
                          saved.get("known_nonexecuted") is True):
            raise IdempotencyConflictError("placement preparation request_id conflict")
        runs = self.journal.runs()
        state = self.journal.state()
        if any(r["role"] != "lead" for r in runs) or self.integration_continuation() is not None:
            raise DispatchBlocked("execution/review/integration already reserved; preparation rejected")
        if state["phase"] in {"COMPLETED", "STALE", "BUDGET_EXHAUSTED", "TRIAL_FENCED", "TRIAL_RUNNING", "UNKNOWN"}:
            raise DispatchBlocked("terminal or uncertain mission fences new placement preparation")
        if any(r["status"] in {"UNKNOWN", "IN_FLIGHT"} for r in runs):
            raise DispatchBlocked("UNKNOWN native execution fences placement preparation")
        requested = {"request_id": request_id, "status": "REQUESTED", "known_nonexecuted": True,
                     "acceptance_hash": self.spec["acceptance_hash"], "created_at": utc_now()}
        if saved:
            requested["previous_request_id"] = saved["request_id"]
        if state["stopped"] or self.stop.is_set() or self.journal.paused():
            requested.update(status="BLOCKED", reason="operator stopped or paused preparation")
        return self._save_placement_preparation(requested, superseded=saved)

    def _request_placement_preparation(self, request_id) -> dict[str, Any]:
        """Hub's synchronous durable request, before releasing to its thread.

        Returns the record, not completion or worker permission. Repeated
        REQUESTED is a readback; only prepare_for_placement may continue it.
        """
        with self._placement_controller():
            return self._request_placement_preparation_locked(request_id)

    def prepare_for_placement(self, request_id) -> dict[str, Any]:
        """Explicit planning/admission only; never enter the execution lifecycle."""
        with self._placement_controller():
            saved = self._request_placement_preparation_locked(request_id)
            current = self._placement_preparation()
            if saved["status"] != "REQUESTED" or current is None or current["request_id"] != request_id:
                return {**self.snapshot(), "placement_preparation": saved}
            if self.stop.is_set() or self.journal.state()["stopped"] or self.journal.paused():
                self._save_placement_preparation({**saved, "status": "BLOCKED",
                    "reason": "operator stopped or paused preparation"})
                return self.snapshot()
            needs_lead = not self.journal.state()["revision"] and not self.spec.get("initial_plan")
            if needs_lead:
                driver = self.spec["roles"]["lead"]["driver"]
                try:
                    probe = self.drivers[driver].probe()
                    self.versions[driver] = probe
                    if not probe["available"]:
                        raise DispatchBlocked("native Lead preflight failed")
                except Exception as exc:
                    self._save_placement_preparation({**saved, "status": "BLOCKED",
                        "reason": redact(f"Lead preflight: {type(exc).__name__}: {exc}")}, phase="PREFLIGHT_FAILED")
                    return self.snapshot()
            saved = self._save_placement_preparation({**saved, "status": "PLANNING",
                "known_nonexecuted": False}, phase="PLANNING")
            try:
                self._initial_plan()
                self.prepare()
            except BaseException as exc:
                # No diagnosis, repair trial or supervisor is part of this API.
                # Interrupted native ownership and pre-reservation gaps fence
                # identically; completed ERROR receipts remain explicit errors.
                self.journal.reconcile_roles()
                unknown = not isinstance(exc, Exception) or bool(self._unresolved())
                self._save_placement_preparation({**saved, "status": "UNKNOWN" if unknown else "ERROR",
                    "reason": redact(f"placement planning: {type(exc).__name__}: {exc}")},
                    phase="UNKNOWN" if unknown else "NEEDS_OPERATOR")
                if not isinstance(exc, Exception):
                    raise
                return self.snapshot()
            plans = self.journal.records("plans")
            lead_runs = [r for r in self.journal.runs() if r["role"] == "lead" and
                         (r["role_metadata"] or {}).get("purpose") == "architecture"]
            saved = {**saved, "status": "WAITING_PLACEMENT", "revision": self.journal.state()["revision"],
                     "plan_hash": digest([p["data"] for p in plans]),
                     "task_hashes": {t["id"]: digest(t) for t in self.active_tasks()},
                     "lead_runs": [{"run_key": r["key"], "receipt_hash": digest(r["receipt"]) if r["receipt"] else None}
                                   for r in lead_runs]}
            self._save_placement_preparation(saved, phase="WAITING_PLACEMENT")
            return self.snapshot()

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
                preparation = self._placement_preparation()
                if preparation and preparation["status"] == "PLANNING":
                    self.journal.reconcile_roles()
                    self._save_placement_preparation({**preparation, "status": "UNKNOWN",
                        "known_nonexecuted": False, "reason": "interrupted placement planning; no Start redispatch"},
                        phase="UNKNOWN")
                    return self.snapshot()
                if preparation and preparation["status"] in {"REQUESTED", "UNKNOWN", "ERROR", "BLOCKED"}:
                    # In particular REQUESTED fences the Hub-to-thread gap.
                    # This explicit Start grants workers, not preparation retry.
                    return self.snapshot()
                self.journal.reconcile_expired()
                self.journal.reconcile_roles()
                if self._unresolved():
                    if not self.journal.state()["stopped"] and not self.journal.paused():
                        self.journal.phase("UNKNOWN", "unresolved native execution; no redispatch")
                    return self.snapshot()
                # Read ORIGINAL canonical runs before current placement/readiness.
                # Completed/unknown work is not a new transport grant. This also
                # covers operator-supplied plans without a preparation session.
                tasks, continuations = self.active_tasks(), self.continuations()
                with self.store._transaction(immediate=False) as db:
                    fresh_remote = any(
                        not db.execute("SELECT 1 FROM native_worker_runs WHERE key=?",
                            (stable_id("lead", continuations[t["id"]]["id"], 1),)).fetchone()
                        and self._placement_in(db, t["id"])["kind"] == "remote"
                        for t in tasks if t["id"] in continuations)
                if fresh_remote and self.remote_execution_ready() is not True:
                    # N2 pins are staging, not an execution capability. Do not
                    # consume the task attempt or diagnose this known boundary.
                    if not self.journal.state()["stopped"] and not self.journal.paused():
                        self.journal.phase("WAITING_PLACEMENT", "remote execution transport is not ready")
                    return self.snapshot()
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
        result = {"objective": self.spec["objective"], "phase": phase, "reason": state.get("reason", ""), "paused": self.journal.paused(),
            "stopped": state["stopped"], "revision": state["revision"], "resume_epoch": state.get("resume_epoch", 0), "nodes": nodes, "runs": runs,
            "plans": self.journal.records("plans"), "diagnoses": self.journal.records("diagnoses"),
            "format_errors": self.journal.records("format_errors"),
            "reviews": self.journal.records("reviews"), "integration": {"continuation": integrated, "evidence": proof,
                "current": self._current_payload(integrated), "builds": self.journal.records("integrations")},
            "procedure": self.procedure(), "improvements": self.journal.records("improvements"),
            "improvement_errors": self.journal.records("improvement_errors"),
            "rsi": self.learning.history(),
            "rsi_configuration": copy.deepcopy(self.spec["rsi"]),
            "procedure_trials": trials, "counters": counters, "budgets": limits,
            "budget_display": {k: "unlimited" if v is None else str(v) for k, v in limits.items()},
            "native_call_reservations": counters["total_calls"], "parent_native_call_reservations": len(runs),
            "trial_native_call_reservations": counters["trial_child_calls"],
            "max_calls": self.spec["max_calls"], "unresolved": unresolved + trials["unresolved"],
            "project_verified": bool(verified), "all_verified": bool(verified) and trials["status"] == "IDLE",
            "controller_errors": self.journal.records("runtime_errors") + self.journal.records("diagnosis_errors"),
            "roles": self.spec["roles"], "validation_kind": self.spec["validation_kind"], "versions": self.versions}
        preparation = self._placement_preparation()
        if preparation is not None:
            # Readback never competes for controller ownership. Only run or
            # prepare, holding both actual locks, durably classifies an orphan.
            result["placement_preparation"] = preparation
            if preparation["status"] == "UNKNOWN" and phase not in {"STOPPED", "PAUSED"}:
                result["phase"] = "UNKNOWN"
        return result


class LeadCapability:
    name = "workers.execute"
    risk_tier = 1
    replay_safe = True  # Journal replay, not native-call redispatch.
    description = "Scoped Sol implementation on pinned, integrated dependency evidence"

    def __init__(self, mission):
        self.mission = mission

    def _admit_remote_in(self, db, placement, task, cont, claims) -> None:
        """Recheck new remote eligibility in the SAME canonical reserve transaction.

        No nested read, backend creation, lease renewal or dispatch. A rejected
        admission rolls back the reservation, inbox binding and placement.
        """
        m = self.mission
        if (m._placement_in(db, task["id"]) != placement or m.remote_execution_ready() is not True
                or not m.inbox.context_allowed(db)):
            raise RemotePlacementUnavailable(placement)
        state = json.loads(db.execute("SELECT value FROM metadata WHERE key=?",
                                      (m.journal.prefix + "state",)).fetchone()[0])
        plans = db.execute("SELECT value FROM metadata WHERE substr(key,1,?)=?",
                           (len(m.journal.prefix + "plans:"), m.journal.prefix + "plans:")).fetchall()
        fixed = [t for row in plans for t in json.loads(row[0])["data"]["plan"]["tasks"]]
        owner = db.execute("SELECT context_json FROM continuations WHERE id=?", (cont["id"],)).fetchone()
        context = json.loads(owner[0]) if owner else {}
        if (task not in fixed or task["id"] not in state["active"]
                or placement.get("mission_id") != claims.registry.mission_id
                or placement.get("task_id") != task["id"] or placement.get("task_hash") != digest(task)
                or context.get("lead_kind") != "implementation" or context.get("native_task") != task["id"]
                or context.get("task_hash") != digest(task)):
            raise RemotePlacementUnavailable(placement)
        try:
            claims.registry._active(db, placement["node_id"])
        except PermissionError as exc:
            raise RemotePlacementUnavailable(placement) from exc
        m.journal._fence(db, {"continuation_id": cont["id"], "lease_token": cont["lease_token"]})

    def _remote_materialized(self, key, task, cont, fingerprint, placement_record, claims,
                             request, native, materialization, prepared, artifact):
        """Validate statusless independent before/candidate, then retain a fixed copy.

        Read actual complete trees and bytes, not the ignore-list projection.
        Core ownership and the durable terminal transport identity remain pinned
        before/after IO; timely RECEIPTED needs no renewed node deadline. Reuse
        the artifact substrate's descriptor-pinned IO, without touching its code.
        This returns files/hash for the ORIGINAL verifier, never a PASS verdict.
        """
        m = self.mission
        if (not isinstance(materialization, dict) or set(materialization) != {"candidate", "before", "delta"}
                or not isinstance(materialization["delta"], dict) or materialization["delta"].get("valid") is not True):
            raise ValueError("remote materialization requires exact independent candidate/before/valid delta")
        envelope = Path(placement_record["candidate_root"])
        if (materialization["candidate"] != str(envelope / "candidate")
                or materialization["before"] != str(envelope / "before")):
            raise ValueError("remote materialization changed the fixed independent paths")
        candidate, before = envelope / "candidate", envelope / "before"
        original, snapshot = Path(request.cwd), Path(placement_record["input_snapshot"])

        def core():
            with m.store._transaction(immediate=False) as db:
                row = db.execute("SELECT * FROM native_worker_runs WHERE key=?", (key,)).fetchone()
                if (row is None or row["status"] != "IN_FLIGHT" or row["receipt_json"] is not None
                        or (row["task_id"], row["fingerprint"], row["continuation_id"], row["lease_token"])
                        != (task["id"], fingerprint, cont["id"], cont["lease_token"])):
                    raise RemoteCurrencyLost("remote canonical reservation identity changed")
                m.journal._fence(db, row)
                result = []
                for name in (m.journal.prefix + "roles:" + key, m.journal.prefix + "run_placements:" + key):
                    fixed = db.execute("SELECT value FROM metadata WHERE key=?", (name,)).fetchone()
                    if fixed is None:
                        raise RemoteCurrencyLost("remote fixed role/placement missing")
                    result.append(fixed[0])
                if json.loads(result[1])["data"] != placement_record:
                    raise RemoteCurrencyLost("remote fixed placement changed")
                binding = db.execute("SELECT binding_json FROM lead_mission_contexts WHERE run_key=?", (key,)).fetchone()
                result.append(binding[0] if binding else None)
                input_binding = db.execute("SELECT binding_json FROM remote_input_snapshots WHERE run_key=?", (key,)).fetchone()
                if input_binding is None:
                    raise RemoteCurrencyLost("remote fixed input binding missing")
                result.append(input_binding[0])
                return result

        fixed_core = core()
        basic = claims.get(key)
        if not basic or not basic.get("claim_id") or basic.get("status") != "RECEIPTED":
            raise RemoteCurrencyLost("remote materialization lacks a durable timely claim receipt")
        view = claims.status(placement_record["placement"]["node_id"], basic["claim_id"], basic["epoch"])
        if (any(view.get(k) != v for k, v in basic.items()) or view.get("receipt") != native
                or view.get("status") != "RECEIPTED" or view.get("run_key") != key
                or view.get("task_id") != task["id"] or view.get("request") != asdict(request)):
            raise RemoteCurrencyLost("remote terminal receipt/identity changed")
        manifest = remote_artifacts._input_manifest(view["input_manifest"])
        fixed_input = json.loads(fixed_core[-1])
        if (fixed_input != {"mission_id": claims.registry.mission_id, "run_key": key, "root": str(snapshot),
                           "manifest": manifest, "manifest_hash": digest(manifest), "reservation_fingerprint": fingerprint}
                or view["input_manifest_hash"] != digest(manifest)
                or manifest["files"] != prepared["files"]):
            raise RemoteCurrencyLost("remote terminal input binding changed")

        def currency():
            if core() != fixed_core:
                raise RemoteCurrencyLost("remote fixed role/context/input changed")
            current = claims.status(view["node_id"], view["claim_id"], view["epoch"])
            if current != view:
                raise RemoteCurrencyLost("remote terminal receipt/tree/owner/epoch changed during IO")
            if core() != fixed_core:
                raise RemoteCurrencyLost("remote core metadata changed during readback")

        roots = (original, snapshot, before, candidate, claims.artifact_root, Path(m.spec["source"]))
        # These copies must be actually disjoint, not merely distinct spellings.
        for i, root in enumerate(roots[:4]):
            for other in roots[i + 1:]:
                if remote_artifacts._overlap(root, other):
                    raise ValueError("remote materialization root_overlap")
        with ExitStack() as stack:
            boundary = remote_artifacts._IOBoundary(roots, stack)

            def unchanged():
                boundary.check()
                currency()
                for root in (original, snapshot, before):
                    if _remote_tree(root) != prepared:
                        raise ValueError("remote prepared/before/input tree changed: " + str(root))
                currency()
                boundary.check()

            unchanged()
            final = _remote_tree(candidate)
            deleted = sorted({item["path"] for item in manifest["files"]} - {item["path"] for item in final["files"]})
            delta = remote_artifacts.exact_delta(manifest, final, view["uploads"], deleted)
            if (not delta["valid"] or delta != materialization["delta"] or final != view.get("tree")):
                raise remote_artifacts.ArtifactError({**delta, "valid": False,
                    "errors": [*delta["errors"], {"code": "materialization_tree_delta", "path": ""}]})
            payloads = remote_artifacts._payloads(candidate, final["files"])
            unchanged()
            if _remote_tree(candidate) != final:
                raise ValueError("remote candidate changed before artifact copy")
            currency()
            fd = remote_artifacts._exclusive_directory(artifact, protected_roots=roots)
            pinned = boundary.adopt(fd, artifact)
            for path, data in sorted(payloads.items()):
                currency()
                remote_artifacts._write_file(artifact, path, data, pinned=pinned)
            unchanged()
            if _remote_tree(candidate) != final or _remote_tree(artifact) != final:
                raise ValueError("remote candidate/artifact changed during copy")
            after = {item["path"]: item["sha256"] for item in final["files"]}
            currency()
            boundary.check()
            return after, digest(after)

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
        envelope = {"arguments": arguments, "task": task, "spec": digest(m.spec)}
        with m.store._transaction(immediate=False) as db:
            prior_run = db.execute("SELECT * FROM native_worker_runs WHERE key=?", (idempotency_key,)).fetchone()
            saved = db.execute("SELECT value FROM metadata WHERE key=?",
                               (m.journal.prefix + "run_placements:" + idempotency_key,)).fetchone()
            placement_record = json.loads(saved[0])["data"] if saved else None
            # Canonical replay is based on its ORIGINAL placement, never today's
            # readiness, placement assignment, trial policy or node inventory.
            placement = placement_record["placement"] if placement_record else (
                {"kind": "local"} if prior_run else m._placement_in(db, task["id"]))
        if placement["kind"] == "remote":
            envelope["placement"] = placement
        fingerprint = digest(envelope)
        if placement_record is not None and prior_run is None:
            raise IdempotencyConflictError("remote run placement lacks its canonical reservation")
        if prior_run is not None and (prior_run["fingerprint"] != fingerprint or prior_run["task_id"] != task["id"]):
            raise IdempotencyConflictError("idempotency key reused for different worker input")

        def not_ready(placement):
            error = "远端执行传输尚未接入"
            data = {"status": "ERROR", "run_key": idempotency_key, "task_id": task["id"],
                    "task_hash": digest(task), "fingerprint": fingerprint, "placement": placement, "error": error}
            m.journal.record("placement_errors", idempotency_key, data)
            return CapabilityResult("ERROR", data, error=error)

        claims = None
        if prior_run is None and placement["kind"] == "remote":
            if m.remote_execution_ready() is not True:
                return not_ready(placement)
            try:
                claims = m.node_claims  # Never initialize a sidecar inside reserve.
            except PermissionError:
                return not_ready(placement)
            placement_record = {"placement": placement, "role": "worker", "driver": "codex",
                "model": m.spec["roles"]["worker"]["model"], "mode": "workspace-write", "cwd": str(candidate),
                "node": placement["node_id"], "task_id": task["id"], "task_hash": digest(task),
                "input_snapshot": str(base / "remote-input"), "candidate_root": str(base / "remote-candidate")}

        def on_reserved(db):
            # Close the local-lookup/assignment race in the canonical admission
            # transaction. Raising here rolls back the new run and its events.
            current = m._placement_in(db, task["id"])
            if current != placement:
                raise RemotePlacementUnavailable(current)
            if placement["kind"] == "remote":
                self._admit_remote_in(db, placement, task, cont, claims)
            m.inbox.bind(db, idempotency_key, role="worker", task_id=task["id"], prompt=arguments["prompt"])
            if placement["kind"] == "remote":
                m.journal.record_in(db, "run_placements", idempotency_key, placement_record)
                # Hooks must not commit context/placement after currency loss.
                self._admit_remote_in(db, placement, task, cont, claims)

        if prior_run is None or placement["kind"] != "remote":
            m.journal.record("roles", idempotency_key, {"role": "worker", "driver": "codex",
                "model": m.spec["roles"]["worker"]["model"], "mode": "workspace-write", "cwd": str(candidate),
                "procedure_hash": m.procedure()["hash"], "node": task["id"], "task_hash": digest(task)})
        try:
            receipt = m.journal.reserve(idempotency_key, task["id"], fingerprint,
                continuation_id=cont["id"], lease_token=cont["lease_token"],
                on_reserved=on_reserved)
        except RemotePlacementUnavailable as exc:
            return not_ready(exc.placement)
        except DispatchBlocked as exc:
            return CapabilityResult("UNKNOWN" if m._unresolved() else "ERROR", {"run_key": idempotency_key}, error=str(exc))
        if receipt is None:
            started = False
            native_receipt = None
            native_materialization = None
            try:
                before = m.build_candidate(candidate, task["depends_on"])
                config = m.spec["roles"]["worker"]
                context = m.inbox.for_run(idempotency_key)
                request = Request(task["id"], context["prompt"] if context else arguments["prompt"], str(candidate), config["model"], mode="workspace-write",
                                  timeout=m.call_timeout(), max_turns=m.spec["max_turns"])
                if placement["kind"] == "remote":
                    prepared = _remote_tree(candidate)
                    if {f["path"]: f["sha256"] for f in prepared["files"]} != before:
                        raise ValueError("remote prepared input differs from original before")
                    outputs = remote_output_paths(before, task["write_paths"], candidate)
                    driver = RemoteCodexDriver(claims, idempotency_key, placement["node_id"],
                        input_snapshot=placement_record["input_snapshot"], candidate_root=placement_record["candidate_root"],
                        output_paths=outputs)
                else:
                    driver = m.drivers["codex"]
                m.journal.event(idempotency_key, "driver", {"driver": "codex", "requested_model": request.model, "task_hash": digest(task)})
                started = True
                receipt = driver.run(request, lambda k, d: m.native_event(idempotency_key, k, d),
                    lambda: m.controls(idempotency_key)).as_dict()
                native_receipt = copy.deepcopy(receipt)
                if placement["kind"] == "remote":
                    native_materialization = copy.deepcopy(driver.materialization)
                if placement["kind"] == "remote" and receipt["status"] == "UNKNOWN":
                    # Unknown outcomes never enter materialization or a local
                    # fallback. Canonical complete persists the original fence.
                    if native_materialization is not None:
                        receipt["materialization"] = native_materialization
                else:
                    if placement["kind"] == "remote":
                        after, sha = self._remote_materialized(idempotency_key, task, cont, fingerprint, placement_record,
                            claims, request, native_receipt, native_materialization, prepared, artifact)
                    else:
                        after = files(candidate)
                        if any((candidate / name).exists() for name in (".git", ".sisyfus")):
                            raise ValueError("worker wrote candidate control directories")
                        sha = None
                    patch = {p: {"before": before.get(p), "after": after.get(p)} for p in sorted(before.keys() | after.keys())
                             if before.get(p) != after.get(p)}
                    outside = [p for p in patch if not any(paths_overlap(p, scope) and (p == scope or Path(scope) in Path(p).parents)
                                                           for scope in task["write_paths"])]
                    if outside:
                        receipt.update(scope_error="writes outside frozen ownership: " + ", ".join(outside))
                    if len(receipt.get("output", "").encode()) > request.max_output_bytes:
                        receipt.update(status="ERROR", error="worker output limit exceeded")
                    if sha is None:
                        sha = copy_candidate(candidate, artifact)
                    receipt.update(candidate=str(artifact), candidate_hash=sha, patch=patch, dependencies=arguments["dependencies"],
                                   task_hash=digest(task), requested_model=receipt.get("requested_model") or request.model)
            except Exception as exc:
                error = f"worker boundary: {type(exc).__name__}: {exc}"
                if isinstance(exc, RemoteCurrencyLost):
                    receipt = Receipt("UNKNOWN", error=error, requested_model=m.spec["roles"]["worker"]["model"]).as_dict()
                elif native_receipt is not None:
                    # A known terminal native receipt remains known even when
                    # local scope/snapshot validation fails afterward.
                    receipt = {**native_receipt, "integrity_error": error,
                               "requested_model": native_receipt.get("requested_model") or m.spec["roles"]["worker"]["model"]}
                else:
                    receipt = Receipt("UNKNOWN" if started else "ERROR", error=error,
                                      requested_model=m.spec["roles"]["worker"]["model"]).as_dict()
                if placement["kind"] == "remote" and native_materialization is not None:
                    # Persist the observed driver diagnostic, not an inferred
                    # successful candidate or a fabricated recovery location.
                    receipt["materialization"] = {"status": "UNKNOWN" if isinstance(exc, RemoteCurrencyLost) else "INVALID",
                        "error": error, "driver_report": native_materialization}
                if placement["kind"] == "remote" and isinstance(exc, remote_artifacts.ArtifactError):
                    receipt["materialization"] = {"status": "INVALID", "report": exc.report}
            context = m.inbox.for_run(idempotency_key)
            if context is not None:
                receipt["context_binding_hash"] = digest(context)
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
