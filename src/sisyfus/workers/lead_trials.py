"""Execute operator-frozen paired Lead procedure trials, never synthetic calls.

Public API: run_trials(origin, candidate_id, evaluation_root) -> dict.
manifest.json has nonempty search/holdout lists of {id, spec}; spec is a public
mapping or JSON path (relative paths resolve against evaluation_root). Optional
source_missions paths are resolved through canonical extract_trial; optional
source_mission_ids/source_family_hashes extend, never replace, that provenance.

All audit records live in origin.journal, all child truth in each child's existing
autonomy.sqlite3. A request lacking its final result is fenced, not resumed.
Finalized fence/error reports never clear unresolved registered child spending.
Defaults really are unlimited. Until atomic shared spending is available, any
enabled parent aggregate cap conservatively fences all trial dispatch.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .journal import DispatchBlocked
from .lead_contracts import ROLE_DEFAULTS, load_lead_spec
from .lead_learning import ProofUnavailable, extract_trial, trial_spec
from .lead_mission import LeadMission
from .mission import files
from .protocol import digest, redact

ACTOR = "techlead-controller"
AGGREGATE_CAPS = ("max_calls", "max_iterations", "max_tokens", "max_cost_usd", "max_wall_minutes")
MAX_MANIFEST_BYTES = 1_000_000
FINAL_REPORT_STATUSES = {"FENCED", "ERROR", "NONPROMOTION", "ELIGIBLE", "PROMOTED"}


def _json(path: Path) -> tuple[Any, str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("operator JSON must be a regular non-symlink file of at most 1MB")
    raw = path.read_bytes()
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("operator JSON exceeds 1MB")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate operator JSON field: " + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError("nonfinite operator JSON: " + value)
    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant), hashlib.sha256(raw).hexdigest()


def _strings(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise ValueError(name + " must be an array of nonempty strings")
    return sorted(set(value))


def _input_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    path = path if path.is_absolute() else root / path
    if path.is_symlink():
        raise ValueError("operator input symlink rejected")
    return path.resolve(strict=True)


def _catalog(root: Path) -> dict[str, Any]:
    manifest, manifest_hash = _json(root / "manifest.json")
    if not isinstance(manifest, dict) or set(manifest) - {"schema", "search", "holdout"}:
        raise ValueError("manifest fields are schema, search and holdout")
    cases, ids, inputs = [], set(), {}
    for split in ("search", "holdout"):
        entries = manifest.get(split)
        if not isinstance(entries, list) or not entries or len(entries) > 64:
            raise ValueError(split + " needs 1..64 frozen operator cases")
        for entry in entries:
            allowed = {"id", "spec", "source_missions", "source_mission_ids", "source_family_hashes"}
            if not isinstance(entry, dict) or set(entry) - allowed:
                raise ValueError("unknown trial case fields")
            ident = entry.get("id")
            if not isinstance(ident, str) or not 1 <= len(ident) <= 200 or ident in ids:
                raise ValueError("case IDs must be unique nonempty strings of at most 200 characters")
            ids.add(ident)
            raw = entry.get("spec")
            if isinstance(raw, str):
                path = _input_path(root, raw)
                raw, code_hash = _json(path)
                inputs[str(path)] = code_hash
            if not isinstance(raw, dict):
                raise ValueError("case spec must be a public spec mapping or JSON path")
            spec = load_lead_spec(raw)
            if spec["roles"] != ROLE_DEFAULTS:
                raise ValueError("paired procedure trials require the canonical explicit role models")
            if any(not c.get("contract", {}).get("fail_if") for c in spec["checks"].values()):
                raise ValueError("frozen acceptance requires both pass_if and fail_if")
            source = Path(spec["source"])
            manifest_files = files(source)
            if not manifest_files:
                raise ValueError("trial source must contain content for family independence")
            family_hash = digest(sorted(manifest_files.values()))
            missions = set(_strings(entry.get("source_mission_ids", []), "source_mission_ids"))
            families = {family_hash, *_strings(entry.get("source_family_hashes", []), "source_family_hashes")}
            donors = _strings(entry.get("source_missions", []), "source_missions")
            # A canonical mission artifact used as source carries its lineage even
            # if the operator omitted a source_missions declaration.
            donors += [str(p) for p in (source, *source.parents) if (p / "autonomy.sqlite3").is_file()]
            provenance = []
            for donor in sorted({_input_path(root, p) for p in donors}):
                proof = extract_trial(donor)
                frozen = trial_spec(donor)
                missions.update(proof["missions"])
                families.update(proof["families"])
                provenance.append({"directory": str(donor), "proof_hash": proof["proof_hash"],
                                   "mission_id": frozen["mission_id"], "missions": proof["missions"],
                                   "families": proof["families"]})
            spec["rsi"] = {"enabled": False, "auto_promote": False}
            cases.append({"id": ident, "split": split, "raw": copy.deepcopy(raw), "spec": spec,
                          "family_hash": family_hash, "families": sorted(families), "missions": sorted(missions),
                          "provenance": provenance})
    frozen = {"manifest_hash": manifest_hash, "input_hashes": inputs,
              "cases": [{k: v for k, v in case.items() if k != "raw"} for case in cases]}
    return {**frozen, "freeze_hash": digest(frozen), "execution_cases": cases}


def _directory(origin: LeadMission, request: str, case: dict, arm: str) -> Path:
    root = origin.directory.resolve()
    parts = ("procedure-trials", request, case["split"], digest(case["id"]), arm)
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("fixed trial control path is a symlink")
    if not path.resolve().is_relative_to(root):
        raise ValueError("trial control path escaped the origin")
    return path


def _independent(origin: LeadMission, candidate: dict, catalog: dict, request: str) -> None:
    versions = origin.learning.history()["versions"]
    families = {f for version in versions for o in version["origins"] for f in o["families"]}
    missions = {m for version in versions for o in version["origins"] for m in o["missions"]}
    # Even an interrupted previous catalog exposure is not fresh holdout.
    for previous in origin.journal.records("paired_trials"):
        if previous["key"] == request:
            continue
        for case in previous["data"].get("catalog", {}).get("cases", []):
            families.update(case["families"])
            missions.update(case["missions"])
    with origin.store._transaction(immediate=False) as db:
        for row in db.execute("SELECT data_json FROM events WHERE event_type='PROCEDURE_TRIAL_INSPECTED'"):
            families.add(json.loads(row[0])["family_hash"])
    scheduled_ids = {digest({"request": request, "case": c["id"], "split": c["split"], "arm": arm})
                     for c in catalog["execution_cases"] for arm in ("baseline", "candidate")}
    for case in catalog["execution_cases"]:
        if scheduled_ids.intersection(case["missions"]):
            raise ProofUnavailable("fresh arm mission identity appears in transitive source aliases")
        if families.intersection(case["families"]) or missions.intersection(case["missions"]):
            raise ProofUnavailable("trial source content/transitive provenance overlaps development, a prior trial or another pair/split")
        families.update(case["families"])
        missions.update(case["missions"])
        for arm in ("baseline", "candidate"):
            control = _directory(origin, request, case, arm)
            source = Path(case["spec"]["source"])
            if source.is_relative_to(control) or control.is_relative_to(source):
                raise ValueError("trial source and control must be disjoint")
            if control.exists():
                raise DispatchBlocked("existing child control is never blindly adopted or rerun; preserve and reconcile it")


def _global_trial_fence(origin: LeadMission, *, request: str | None = None,
                        active_children: set[Path] | None = None) -> None:
    """Unsettled historical children fence every candidate/catalog of this origin.

    Read the existing child transport ledger without constructing a controller,
    reconciling ownership or creating a DB. Only this runner's active children
    may have IN_FLIGHT reservations; UNKNOWN is never exempted. The current
    immutable request is pending while we execute it, not a completed result.
    """
    finals = {r["key"] for r in origin.journal.records("paired_trial_results")
              if r["data"].get("status") in FINAL_REPORT_STATUSES}
    for previous in origin.journal.records("paired_trials"):
        if previous["key"] != request and previous["key"] not in finals:
            raise DispatchBlocked("prior paired trial request is pending/uncertain across candidates: " + previous["key"])
    active = active_children or set()
    directories = set()
    for category in ("trial_children", "paired_trial_children"):
        for registration in origin.journal.records(category):
            value = registration["data"].get("directory")
            if not isinstance(value, str) or not value or not Path(value).is_absolute():
                raise DispatchBlocked("registered trial child has no fixed absolute control path")
            directory = Path(value)
            if directory.is_symlink() or directory.resolve() != directory or directory == origin.directory.resolve():
                raise DispatchBlocked("registered trial child control path is aliased or invalid: " + value)
            directories.add(directory)
    for directory in sorted(directories):
        path = directory / "autonomy.sqlite3"
        if path.is_symlink() or not path.is_file():
            raise DispatchBlocked("registered trial child DB is missing/uncertain; preserve and reconcile: " + str(directory))
        try:
            db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
            try:
                rows = db.execute("SELECT key,status,receipt_json FROM native_worker_runs ORDER BY key").fetchall()
            finally:
                db.close()
        except sqlite3.Error as exc:
            raise DispatchBlocked("registered trial child DB inspection failed: " + str(directory) + ": " + str(exc)) from exc
        for key, status, raw in rows:
            if status == "IN_FLIGHT" and directory in active and raw is None:
                continue  # Real parallel native calls of this active arm only.
            if status != "RECEIPTED" or raw is None:
                raise DispatchBlocked("registered trial child native execution " + status +
                                      "/unsettled blocks all candidate spending: " + str(directory) + " run=" + key)
            try:
                receipt = json.loads(raw)
                settled = receipt["status"] in {"COMPLETED", "ERROR", "INTERRUPTED", "FAILED", "CANCELLED"}
            except (ValueError, KeyError, TypeError) as exc:
                raise DispatchBlocked("registered trial child receipt malformed: " + str(directory) + " run=" + key) from exc
            if not settled:
                raise DispatchBlocked("registered trial child receipt UNKNOWN/unsettled blocks all candidate spending: " +
                                      str(directory) + " run=" + key)


def _parent_fence(origin: LeadMission, *, request: str | None = None,
                  active_children: set[Path] | None = None) -> None:
    if origin.stop.is_set() or origin.journal.state()["stopped"]:
        raise DispatchBlocked("parent durably stopped")
    enabled = [k for k in AGGREGATE_CAPS if origin.spec.get(k) is not None]
    if enabled:
        raise DispatchBlocked("enabled parent aggregate caps require atomic shared accounting; trial dispatch conservatively fenced: " + ", ".join(enabled))
    if any(r["status"] in {"UNKNOWN", "IN_FLIGHT"} for r in origin.journal.runs()):
        raise DispatchBlocked("parent native execution is UNKNOWN or unsettled; no trial spending")
    _global_trial_fence(origin, request=request, active_children=active_children)


class _Controls:
    """A registered active child follows durable parent controls during a call."""
    def __init__(self, origin: LeadMission, request: str):
        self.origin = origin
        self.request = request
        self.children: dict[str, tuple[LeadMission, bool]] = {}
        self.lock = threading.RLock()
        self.done = threading.Event()
        self.error: Exception | None = None
        self.thread = threading.Thread(target=self._watch, name="lead-trial-controls", daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.done.set()
        self.thread.join()

    def _watch(self):
        while not self.done.wait(.02):
            try:
                self.sync()
            except Exception as exc:
                self.error = exc
                with self.lock:
                    for child, _ in self.children.values():
                        child.stop.set()
                return

    def sync(self):
        stopped = self.origin.stop.is_set() or self.origin.journal.state()["stopped"]
        paused = self.origin.journal.paused()
        with self.lock:
            for ident, (child, propagated) in list(self.children.items()):
                if stopped:
                    if not child.journal.state()["stopped"]:
                        child.stop.set()
                        child.request_stop()
                elif paused != propagated:
                    child.journal.pause(paused)
                    self.children[ident] = (child, paused)

    def ready(self):
        while True:
            if self.error:
                raise RuntimeError("parent control propagation failed: " + str(self.error))
            with self.lock:
                active = {child.directory.resolve() for child, _ in self.children.values()}
            _parent_fence(self.origin, request=self.request, active_children=active)
            if not self.origin.journal.paused():
                self.sync()  # Clear a propagated pause before child reserve.
                return
            self.done.wait(.02)

    def register(self, ident: str, child: LeadMission):
        with self.lock:
            self.children[ident] = (child, False)
        register = getattr(self.origin, "register_trial_child", None)
        if register:
            register(child)

    def release(self, ident: str, child: LeadMission):
        with self.lock:
            self.children.pop(ident, None)
        unregister = getattr(self.origin, "unregister_trial_child", None)
        if unregister:
            unregister(child)


def _error(exc: Exception) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": redact(str(exc))[:4000]}


def _fence_report(origin: LeadMission, request: str, exc: Exception, *, rejected_before_request: bool = False) -> dict:
    # A proven no-dispatch rejection is terminal, not uncertain execution. Never
    # use it for an existing request, a failed spending guard or a begin failure.
    report = {"status": "NONPROMOTION" if rejected_before_request else "FENCED", "promoted": False, "request_id": request,
              "error": _error(exc), "claim": "no demonstrated improvement; no blind trial replay"}
    origin.journal.record("paired_trial_fences", digest(report), report)
    return report


def run_trials(origin: LeadMission, candidate_id: str, evaluation_root: Path) -> dict:
    """Run fresh search then holdout pairs; promote only canonical measured proof.

    Native execution acknowledgement belongs to the original operator run path.
    A stop, cap, stale catalog/proposal, partial request or unknown run fences new
    calls. No automatic retries, child DB removal or fake invocation receipts.
    """
    root = Path(evaluation_root).expanduser().resolve()
    request = digest({"candidate_id": candidate_id, "evaluation_root": str(root)})
    with (origin.directory / "paired-trials.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return _fence_report(origin, request, DispatchBlocked("another paired trial runner owns the origin"))
        before_request = False
        try:
            existing = origin.journal.get("paired_trials", request)
            final = origin.journal.get("paired_trial_results", request)
            if existing is not None and (not final or final.get("status") not in FINAL_REPORT_STATUSES):
                raise DispatchBlocked("existing paired trial request is pending/uncertain; reconcile child DBs, never blind rerun")
            if existing is None:
                if final is not None:
                    raise DispatchBlocked("paired result has no immutable original request; reconcile before new spending")
                _parent_fence(origin)
                before_request = True  # Inherited uncertainty was checked first.
            catalog = _catalog(root)
            if existing is not None:
                if final["status"] in {"ELIGIBLE", "PROMOTED", "NONPROMOTION"}:
                    _global_trial_fence(origin)  # A cached success never clears another unsettled lab.
                if existing["catalog"]["freeze_hash"] != catalog["freeze_hash"]:
                    raise ProofUnavailable("operator manifest/spec/source/provenance changed after request freeze")
                for arm in final.get("arms", []):
                    if arm.get("proof"):
                        current = extract_trial(arm["directory"], procedure_hash=arm["procedure_hash"], split=arm["split"])
                        if current != arm["proof"]:
                            raise ProofUnavailable("completed trial canonical proof changed; no cached success")
                if final["status"] in {"ELIGIBLE", "PROMOTED", "NONPROMOTION"}:
                    settle = getattr(origin, "settle_trial", None)
                    if settle is not None:
                        settle(request, final)  # Recover a persisted result, never replay a native arm.
                return final
            if not origin.spec["rsi"].get("enabled", True):
                raise ValueError("parent RSI disabled; procedure trial dispatch rejected before any child")
            candidate = origin.learning.validate_candidate(candidate_id)
            if not candidate["origins"]:
                raise ProofUnavailable("candidate requires prior positive or failed canonical evidence")
            _independent(origin, candidate, catalog, request)
            frozen = {k: v for k, v in catalog.items() if k != "execution_cases"}
            before_request = False  # The immutable handoff/write boundary may be uncertain.
            origin.journal.record("paired_trials", request,
                                  {"status": "PENDING", "candidate_id": candidate_id, "evaluation_root": str(root),
                                   "candidate_hash": candidate["hash"], "baseline": candidate["baseline"], "catalog": frozen})
            begin = getattr(origin, "begin_trial", None)
            if begin is not None:
                begin(request)
        except Exception as exc:
            return _fence_report(origin, request, exc, rejected_before_request=
                                 before_request and isinstance(exc, (ProofUnavailable, ValueError)))

        arms, pairs = [], {"search": [], "holdout": []}
        report = {"request_id": request, "candidate_id": candidate_id, "promoted": False,
                  "metric": "actual_native_invocation_reservations", "arms": arms,
                  "claim": "no demonstrated improvement"}
        try:
            with _Controls(origin, request) as controls:
                for case in catalog["execution_cases"]:
                    pair = []
                    for arm in ("baseline", "candidate"):
                        controls.ready()
                        # Rehash every operator input before each actual arm.
                        if _catalog(root)["freeze_hash"] != catalog["freeze_hash"]:
                            raise ProofUnavailable("frozen operator catalog/source/check/provenance drift before dispatch")
                        current = origin.learning.validate_candidate(candidate_id)
                        if current != candidate:
                            raise ProofUnavailable("candidate/baseline changed during paired execution")
                        procedure = candidate["baseline"] if arm == "baseline" else candidate
                        spec = copy.deepcopy(case["spec"])
                        spec["procedure"] = procedure["procedure"]
                        control = _directory(origin, request, case, arm)
                        mission_id = digest({"request": request, "case": case["id"], "split": case["split"], "arm": arm})
                        pair_id = digest({"request": request, "case": case["id"], "split": case["split"]})
                        origin.journal.record("paired_trial_children", mission_id,
                                              {"status": "REGISTERED", "request_id": request, "directory": str(control), "split": case["split"],
                                               "arm": arm, "pair_id": pair_id, "procedure_hash": procedure["hash"]})
                        child = LeadMission(control, spec)
                        child.configure_learning_trial(pair_id=pair_id, split=case["split"], mission_id=mission_id,
                                                       family=case["id"], source_mission_ids=case["missions"],
                                                       source_family_hashes=case["families"])
                        original_freeze = child.journal.before_reserve
                        def before_reserve(freeze=original_freeze):
                            controls.ready()
                            freeze()
                        child.journal.before_reserve = before_reserve
                        controls.register(mission_id, child)
                        arm_result = {"mission_id": mission_id, "case_id": case["id"], "split": case["split"],
                                      "arm": arm, "directory": str(control), "procedure_hash": procedure["hash"]}
                        arms.append(arm_result)
                        try:
                            outcome = child.run()  # None/unlimited default; actual native core path.
                        except Exception as exc:
                            arm_result.update(phase="ERROR", reservations=len(child.journal.runs()), error=_error(exc))
                            origin.journal.record("paired_trial_arms", mission_id, arm_result)
                            raise
                        finally:
                            controls.release(mission_id, child)
                        if controls.error:
                            raise RuntimeError("parent control monitor failed: " + str(controls.error))
                        runs = child.journal.runs()
                        arm_result.update(phase=outcome.get("phase"), reservations=len(runs))
                        if any(r["status"] in {"UNKNOWN", "IN_FLIGHT"} for r in runs):
                            origin.journal.record("paired_trial_arms", mission_id, arm_result)
                            raise DispatchBlocked("child native execution UNKNOWN/unsettled; preserve partial DB and fence further arms")
                        try:
                            arm_result["proof"] = extract_trial(control, procedure_hash=procedure["hash"], split=case["split"])
                        except ProofUnavailable as exc:
                            arm_result["proof_error"] = _error(exc)
                        origin.journal.record("paired_trial_arms", mission_id, arm_result)
                        pair.append(control)
                    pairs[case["split"]].append(tuple(pair))
                controls.ready()
                if _catalog(root)["freeze_hash"] != catalog["freeze_hash"]:
                    raise ProofUnavailable("frozen operator catalog changed before evaluation")
                try:
                    assessment = origin.learning.evaluate(candidate_id, pairs["search"], pairs["holdout"], actor=ACTOR)
                except ProofUnavailable as exc:
                    report.update(status="NONPROMOTION", error=_error(exc),
                                  assessment=[e for e in origin.learning.history()["evaluations"] if e["candidate_id"] == candidate_id][-1])
                else:
                    report.update(status="ELIGIBLE", assessment=assessment, model_scope=assessment["model_scope"],
                                  measured_invocations_saved=sum(p["invocations_saved"] for p in assessment["pairs"]),
                                  claim=assessment["claim"])
                    if origin.spec["rsi"].get("auto_promote", False):
                        controls.ready()
                        promotion = origin.learning.promote(candidate_id, pairs["search"], pairs["holdout"], actor=ACTOR)
                        report.update(status="PROMOTED", promoted=True, promotion=promotion)
        except Exception as exc:
            report.update(status="FENCED" if isinstance(exc, DispatchBlocked) else "NONPROMOTION" if isinstance(exc, ProofUnavailable) else "ERROR",
                          error=_error(exc), claim="no demonstrated improvement", promoted=False)
        origin.journal.record("paired_trial_results", request, report)
        settle = getattr(origin, "settle_trial", None)
        if settle is not None:
            settle(request, report)
        return report
