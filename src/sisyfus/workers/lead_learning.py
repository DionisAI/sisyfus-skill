"""Evidence-backed Lead procedures in the EXISTING AutonomyStore, no model calls.

Preferred core evidence interface
--------------------------------
1. Bind the normal operator spec through Journal. Construct ProcedureLedger(store,
   initial_procedure=spec['procedure']). Before ANY native reservation call
   freeze_trial(mission_id=None, pair_id=None, split='development', family=None,
   source_mission_ids=(), source_family_hashes=()). Core's before_reserve hook
   does this automatically; configure_learning_trial supplies paired metadata.
2. The sole extra mission event is LEAD_LEARNING_FROZEN (entity_type=lead_trial,
   entity_id=mission_id, actor=techlead-controller). Its schema is
   sisyfus.lead_trial.v1. Data: mission_id,pair_id,split,procedure_hash,family,
   source,source_hash,spec_hash,task_spec,source_mission_ids,source_family_hashes.
   Artifact is OMITTED: output hashes come from canonical task/integration proof.
   task_spec is the entire normalized bound operator spec minus procedure,source,
   source_hash,acceptance_hash,initial_plan,rsi; operator initial_plan.tasks are
   carried into tasks. Dynamic Lead-generated DAGs may differ across arms.
   Recording a standalone freeze does not require canonical trial role models
   or a nonempty source; extraction/evaluation enforce those eligibility gates.
3. Reuse the core's native_worker_runs / WORKER_RESERVED / WORKER_RECEIPT and
   hash-anchored LeadJournal roles, plans, state, measurements, reviews. All runs
   need pinned requested model/mode/procedure_hash BEFORE dispatch. Fresh reviews
   keep their native {verdict,reasons,evidence:[check:<digest>]} output; canonical
   workers.lead-check combined B-assurance verdicts settle AFTER review. Every
   active task and current integration must have latest canonical PASS, current
   own artifact/check/code/dependency hashes, complete checks and anchored review.
   No extra CHECK/REVIEW/CLOSED markers or copied verdicts are needed.
4. trial_spec(directory) reads this immutable manifest. extract_trial(directory,
   procedure_hash=None,split=None) revalidates proof and counts actual reservations.
   evaluate/promote(id,search=[(baseline_dir,candidate_dir)],holdout=[(...)],actor)
   require at least two disjoint pairs/families, one untouched holdout, identical
   frozen operator source/gates/configuration, no regressions, strictly fewer
   reservations on at least one pair. Semantic equivalence is the SAME frozen
   acceptance, not an identical model-authored DAG or bytes. Optional candidate
   scope.artifact_equivalence='exact_hash' requires identical integrated bytes.

Both missing actual models are admissible ONLY with identical per-role missing
status and explicit matching requested models. Reports conspicuously say
'requested-model matched pilot; runtime model unverified'. Wrong attested models,
mixed/different status or requested configuration reject; no model identity or
capability uplift is inferred. Missing costs stay None/UNMETERED, zero is measured
zero; only explicit incremental invocation_cost_usd is totaled (never cumulative
provider session totals). Explicit native_worker_execution=False or synthetic
execution_kind receipts are rejected as native trial proof by both adapters.
Unlimited aggregate defaults remain untouched.

Families are source CONTENT fingerprints plus transitive provenance, not display
names. Holdout freezes after proposal; previous development/search exposure and
other candidates' inspections reject. First inspection consumes holdout even on
rejection; identical proof revalidation is allowed for promotion. Reports,
versions, lineage and active metadata are event-anchored; rollback restores a
validated ancestor or original operator baseline without removing history.

Compatibility: manifests WITH artifact use explicit immutable tasks with
required_checks, plus controller LEAD_LEARNING_ROLE/CHECK/REVIEW/CLOSED events.
CHECK references an existing A-assurance canonical verdict; REVIEW binds the
native {target,verdict,candidate_hash,spec_hash,evidence_ids} JSON. No supplied
passed/improved/gain field establishes truth in either interface.

Trust boundary: deterministic controller owns the DB and frozen inputs. Hashes
detect tampering, not a malicious controller/DB owner. Closed directories must
stay immutable under controller ownership during evaluation; inputs/proofs are
checked again at the end, not protected by OS isolation here. Proof gaps raise
ProofUnavailable AFTER committing the rejection audit. Main reads active() on
each subsequent Lead call; console history is not a holdout-free Lead prompt.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from ..autonomy.models import canonical_json, stable_id, utc_now
from ..autonomy.store import AutonomyStore, _sha256
from ..research_v2.verifier import classify_observation
from .lead_contracts import DEFAULT_PROCEDURE, ROLE_DEFAULTS
from .mission import files
from .protocol import digest, redact

PREFIX = "LEAD_LEARNING_"
SCHEMA = "sisyfus.lead_trial.v1"
CORE_SCHEMA = "sisyfus.lead_trial.v2"
ACTOR = "techlead-controller"
ACTIVE_KEY = "lead_learning_active"


class ProofUnavailable(ValueError):
    """Explicit missing, stale, incomparable or inadmissible promotion proof."""


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise ProofUnavailable(message)


def _text(value: Any, name: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{name} required")
    return value


def _events(db: sqlite3.Connection) -> list[dict[str, Any]]:
    result, previous = [], None
    for seq, row in enumerate(db.execute("SELECT * FROM events ORDER BY seq"), 1):
        item = {k: row[k] for k in ("seq", "id", "ts", "continuation_id", "entity_type",
                                   "entity_id", "event_type", "actor", "prev_hash")}
        item["data"] = json.loads(row["data_json"])
        _require(item["seq"] == seq and item["prev_hash"] == previous
                 and _sha256(item) == row["event_hash"], f"canonical event chain corrupt at {seq}")
        previous = row["event_hash"]
        result.append({**item, "event_hash": previous})
    return result


def _path(value: Any) -> Path:
    raw = Path(_text(value, "absolute proof path"))
    _require(raw.is_absolute() and raw.exists(), f"proof path missing: {raw}")
    _require(not any(p.is_symlink() for p in (raw, *raw.parents)), f"symlink proof path: {raw}")
    return raw.resolve(strict=True)


@contextmanager
def _trial_db(directory: str | Path) -> Iterator[sqlite3.Connection]:
    path = _path(str(directory)) / "autonomy.sqlite3"
    _require(path.is_file() and not path.is_symlink(), f"existing trial database missing: {path}")
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN")
        yield db
    finally:
        db.close()


def _check(check: Mapping[str, Any]) -> None:
    _require(isinstance(check, dict) and check.get("argv") and check.get("code_hashes")
             and check.get("contract", {}).get("pass_if"), "frozen executable check/contract required")
    for name, expected in check["code_hashes"].items():
        path = _path(name)
        _require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                 f"check code hash mismatch: {name}")


def _operator_spec(bound: dict[str, Any]) -> dict[str, Any]:
    frozen = {k: v for k, v in bound.items()
              if k not in {"procedure", "source", "source_hash", "acceptance_hash", "initial_plan", "rsi"}}
    if bound.get("initial_plan"):
        frozen["tasks"] = bound["initial_plan"]["tasks"]
    return frozen


def _frozen(db: sqlite3.Connection, events: list[dict[str, Any]], *,
            require_trial_eligibility: bool = True) -> dict[str, Any]:
    rows = [e for e in events if e["event_type"] == PREFIX + "FROZEN"]
    _require(len(rows) == 1, "one controller-frozen mission manifest required")
    event = rows[0]
    m = event["data"]
    _require(event["actor"] == ACTOR and event["entity_type"] == "lead_trial"
             and event["entity_id"] == m.get("mission_id") and m.get("schema") in {SCHEMA, CORE_SCHEMA},
             "invalid controller frozen manifest")
    for key in ("mission_id", "pair_id", "procedure_hash"):
        _text(m.get(key), key)
    _require(m.get("split") in {"development", "search", "holdout"}, "invalid trial split")
    core = m.get("schema") == CORE_SCHEMA or "artifact" not in m
    spec = m.get("task_spec", {})
    _require(bool(spec) and digest(spec) == m.get("spec_hash"), "frozen mission spec hash mismatch")
    if require_trial_eligibility:
        _require(spec.get("roles") == ROLE_DEFAULTS, "explicit Lead/worker/reviewer role configuration required")
    _require(core or isinstance(spec.get("configuration"), dict), "frozen execution configuration required")
    if core:
        bound_row = db.execute("SELECT value FROM metadata WHERE key='native_worker_spec'").fetchone()
        _require(bound_row is not None, "canonical bound operator specification missing")
        bound = json.loads(bound_row[0])
        bindings = [e for e in events if e["event_type"] == "WORKER_MISSION_BOUND"]
        _require(len(bindings) == 1 and bindings[0]["data"].get("spec_hash") == digest(bound)
                 and bindings[0]["seq"] < event["seq"] and _operator_spec(bound) == spec
                 and bound["source"] == m.get("source"), "bound operator spec/code/configuration hash mismatch")
    _text(spec.get("objective"), "scoped mission objective")
    checks, tasks = spec.get("checks", {}), spec.get("tasks", [])
    _require(bool(checks) and (bool(tasks) or core), "frozen tasks and checks required")
    for check in checks.values():
        _check(check)
    targets = {}
    task_ids = set()
    for task in ([] if core else tasks):
        ident = _text(task.get("id"), "task ID")
        _require(ident not in task_ids and bool(task.get("required_checks")), "duplicate task or missing acceptance")
        task_ids.add(ident)
        for name in task["required_checks"]:
            _require(name in checks, "unregistered task check")
            targets[f"task:{ident}:{name}"] = name
    for name in spec.get("integration_checks", []):
        _require(name in checks, "unregistered integration check")
        targets[f"integration:{name}"] = name
    _require(bool(spec.get("integration_checks")) and bool(spec.get("required_checks"))
             and set(spec["required_checks"]) <= (set(checks) if core else set(targets.values())),
             "mandatory acceptance/integration coverage missing")
    source = files(_path(m.get("source")))
    _require(digest(source) == m.get("source_hash"), "frozen source hash mismatch")
    if require_trial_eligibility:
        _require(bool(source), "nonempty source required for paired trial evidence")
    # Labels and path renames cannot create independent underlying task families.
    family = digest(sorted(source.values()))
    for key in ("source_mission_ids", "source_family_hashes"):
        _require(isinstance(m.get(key, []), list) and all(isinstance(x, str) and x for x in m.get(key, [])),
                 "invalid transitive trial provenance")
    for e in events:
        if e["event_type"].startswith(PREFIX) and e["event_type"] != PREFIX + "FROZEN":
            _require(e["entity_type"] == "lead_trial" and e["entity_id"] == m["mission_id"]
                     and e["actor"] == ACTOR and e["seq"] > event["seq"], "invalid controller trial event authority/order")
    return {**m, "core": core, "freeze_event": event, "targets": targets, "family_hash": family,
            "families": sorted({family, *m.get("source_family_hashes", [])}),
            "missions": sorted({m["mission_id"], *m.get("source_mission_ids", [])})}


def _canonical_evidence(db: sqlite3.Connection, events: list[dict[str, Any]], evidence_id: str,
                        check: dict[str, Any], candidate_hash: str) -> tuple[dict[str, Any], dict[str, Any]]:
    row = db.execute("SELECT * FROM evidence WHERE id=?", (evidence_id,)).fetchone()
    _require(row is not None, f"canonical verdict missing: {evidence_id}")
    verdict_events = [e for e in events if e["event_type"] == "VERDICT_RECORDED" and e["entity_id"] == evidence_id]
    _require(len(verdict_events) == 1, "verdict not anchored in canonical events")
    anchor = verdict_events[0]
    decision = db.execute("SELECT * FROM decisions WHERE id=?", (row["decision_id"],)).fetchone()
    _require(decision is not None and decision["status"] == "VERIFIED" and decision["evidence_id"] == evidence_id
             and not decision["recovery_required"], "verdict decision is not settled/verified")
    latest = db.execute("SELECT id FROM evidence WHERE continuation_id=? ORDER BY created_at DESC,id DESC LIMIT 1",
                        (row["continuation_id"],)).fetchone()
    _require(latest[0] == evidence_id, "canonical evidence superseded")
    payload = json.loads(row["payload_json"])
    _require(stable_id("ev", row["decision_id"], payload, length=24) == evidence_id,
             "canonical evidence payload hash mismatch")
    proof = payload.get("evidence", {})
    _require(anchor["data"].get("decision_id") == row["decision_id"]
             and anchor["data"].get("verdict") == row["verdict"] == payload.get("verdict")
             and anchor["actor"] == row["verifier_id"] == payload.get("verifier_id")
             and row["verification_mode"] == payload.get("verification_mode") == "programmatic"
             and row["assurance"] == payload.get("assurance") == "A", "canonical verifier binding mismatch")
    _require(proof.get("check_hash") == digest(check), "canonical check hash mismatch")
    _require(proof.get("candidate_hash") == candidate_hash
             and digest(files(_path(proof.get("candidate")))) == candidate_hash, "canonical artifact hash mismatch")
    measurement = proof.get("measurement")
    _require(isinstance(measurement, dict), "canonical measurement missing")
    classified = classify_observation(check["contract"], measurement)
    _require(classified["status"] == row["verdict"], "canonical verdict differs from frozen reclassification")
    return {**dict(row), "proof": proof}, anchor


def _native_receipt(receipt: Mapping[str, Any]) -> None:
    """Explicit controlled fixtures are not native execution measurements.

    An absent marker is not runtime model attestation; requested/actual telemetry
    remains validated separately and missing actual models remain missing.
    """
    kind = receipt.get("execution_kind")
    _require(receipt.get("native_worker_execution") is not False
             and not (isinstance(kind, str) and "synthetic" in kind.casefold()),
             "explicit synthetic/non-native receipt is not native trial evidence")


def _runs(db: sqlite3.Connection, events: list[dict[str, Any]], m: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    _require("native_worker_runs" in tables, "actual invocation reservation ledger missing")
    rows = db.execute("SELECT * FROM native_worker_runs ORDER BY key").fetchall()
    _require(bool(rows), "no actual invocation reservations")
    roles = [e for e in events if e["event_type"] == PREFIX + "ROLE"]
    _require(len(roles) == len(rows), "every actual reservation needs one frozen role binding")
    result = {}
    for row in rows:
        key = row["key"]
        binding = [e for e in roles if e["data"].get("run_key") == key]
        reserved = [e for e in events if e["event_type"] == "WORKER_RESERVED" and e["entity_id"] == key]
        receipts = [e for e in events if e["event_type"] == "WORKER_RECEIPT" and e["entity_id"] == key]
        _require(len(binding) == len(reserved) == len(receipts) == 1, "reservation/role/receipt anchor missing or duplicate")
        role = binding[0]["data"].get("role")
        _require(role in ROLE_DEFAULTS and binding[0]["data"].get("procedure_hash") == m["procedure_hash"], "mixed procedure/role in trial")
        _require(m["freeze_event"]["seq"] < reserved[0]["seq"] <= binding[0]["seq"] < receipts[0]["seq"],
                 "role/request not frozen before invocation receipt")
        _require(reserved[0]["data"].get("fingerprint") == row["fingerprint"]
                 and reserved[0]["data"].get("task_id") == row["task_id"], "reservation row/event mismatch")
        _require(row["status"] == "RECEIPTED" and row["receipt_json"], "UNKNOWN or unresolved native run")
        receipt = json.loads(row["receipt_json"])
        _native_receipt(receipt)
        _require(receipt == receipts[0]["data"] and receipt.get("status") in {"COMPLETED", "ERROR", "FAILED"},
                 "canonical native receipt missing, forged or UNKNOWN")
        expected = m["task_spec"]["roles"][role]["model"]
        _require(receipt.get("requested_model") == expected and receipt.get("actual_model") in {None, expected},
                 "requested/actual role model mismatched")
        _require(binding[0]["data"].get("mode") == ("workspace-write" if role == "worker" else "read-only"),
                 "role invocation permission mode mismatch")
        cost = receipt.get("usage", {}).get("invocation_cost_usd")
        if cost is not None:
            _require(type(cost) in {float, int} and math.isfinite(cost) and cost >= 0, "invalid metered invocation cost")
        result[key] = {"role": role, "receipt": receipt, "cost": cost, "event": receipts[0]}
    _require({r["role"] for r in result.values()} == set(ROLE_DEFAULTS), "all three roles need actual invocation evidence")
    return result


def _attestation(runs: dict[str, dict[str, Any]], roles: dict[str, Any]) -> dict[str, str]:
    result = {}
    for role in roles:
        statuses = {"MISSING" if r["receipt"].get("actual_model") is None else "ATTESTED"
                    for r in runs.values() if r["role"] == role}
        _require(len(statuses) == 1, "mixed or absent actual-model attestation within role")
        result[role] = next(iter(statuses))
    return result


def _core_records(db: sqlite3.Connection, events: list[dict[str, Any]], category: str) -> dict[str, dict[str, Any]]:
    prefix = "techlead:" + category + ":"
    records = {}
    for row in db.execute("SELECT key,value FROM metadata WHERE substr(key,1,?)=?", (len(prefix), prefix)):
        saved = json.loads(row["value"])
        anchors = [e for e in events if e["event_type"] == "WORKER_LEAD_" + category.upper()
                   and e["entity_id"] == saved["key"] and e["data"] == saved]
        _require(len(anchors) == 1, f"canonical core {category} record unanchored or corrupt")
        records[saved["key"]] = {**saved, "event": anchors[0]}
    return records


def _core_state(db: sqlite3.Connection, events: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    row = db.execute("SELECT value FROM metadata WHERE key='techlead:state'").fetchone()
    _require(row is not None, "canonical core state missing")
    state = json.loads(row[0])
    anchors = [e for e in events if e["event_type"].startswith("WORKER_LEAD_") and "state" in e["data"]]
    _require(bool(anchors) and anchors[-1]["data"]["state"] == state, "canonical core state metadata/event mismatch")
    plans = _core_records(db, events, "plans")
    tasks = {t["id"]: t for plan in plans.values() for t in plan["data"]["plan"]["tasks"]}
    _require(len(state.get("active", [])) == len(set(state.get("active", []))), "duplicate active core task")
    _require(set(state.get("active", [])) <= tasks.keys(), "active task omitted from canonical plan")
    return state, tasks, anchors[-1]


def _core_runs(db: sqlite3.Connection, events: list[dict[str, Any]], m: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if any(e["event_type"] == PREFIX + "ROLE" for e in events):
        return _runs(db, events, m)
    roles = _core_records(db, events, "roles")
    result = {}
    for row in db.execute("SELECT * FROM native_worker_runs"):
        key = row["key"]
        reserved = [e for e in events if e["event_type"] == "WORKER_RESERVED" and e["entity_id"] == key]
        receipts = [e for e in events if e["event_type"] == "WORKER_RECEIPT" and e["entity_id"] == key]
        _require(len(reserved) == len(receipts) == 1 and m["freeze_event"]["seq"] < reserved[0]["seq"] < receipts[0]["seq"],
                 "canonical reservation/receipt missing or predates frozen mission")
        _require(row["status"] == "RECEIPTED" and row["receipt_json"], "UNKNOWN or unresolved native run")
        receipt = json.loads(row["receipt_json"])
        _native_receipt(receipt)
        _require(receipt == receipts[0]["data"] and receipt.get("status") in {"COMPLETED", "ERROR", "FAILED"},
                 "canonical native receipt forged or UNKNOWN")
        _require(reserved[0]["data"].get("fingerprint") == row["fingerprint"]
                 and reserved[0]["data"].get("task_id") == row["task_id"], "canonical reservation metadata mismatch")
        role = roles.get(key, {}).get("data", {}).get("role", "worker")
        _require(role in ROLE_DEFAULTS, "unknown canonical invocation role")
        if row["task_id"] == "planner":
            _require(key in roles and roles[key]["event"]["seq"] < reserved[0]["seq"], "role request was not pinned before dispatch")
            request = roles[key]["data"]["request"]
            _require(request["mode"] == "read-only" and request["model"] == m["task_spec"]["roles"][role]["model"],
                     "canonical role request mode/model mismatch")
        else:
            _require(role == "worker", "worker reservation masquerades as reviewer")
        _require(key in roles, "canonical core invocation role metadata missing")
        pinned = roles[key]["data"]
        _require(pinned.get("procedure_hash") == m["procedure_hash"]
                 and pinned.get("mode") == ("workspace-write" if role == "worker" else "read-only")
                 and pinned.get("model") == m["task_spec"]["roles"][role]["model"],
                 "canonical core role procedure/model/mode drift")
        expected = m["task_spec"]["roles"][role]["model"]
        _require(receipt.get("requested_model") == expected and receipt.get("actual_model") in {None, expected},
                 "requested/actual role model mismatched")
        cost = (receipt.get("usage") or {}).get("invocation_cost_usd")
        if cost is not None:
            _require(type(cost) in {int, float} and math.isfinite(cost) and cost >= 0, "invalid invocation cost")
        result[key] = {"role": role, "receipt": receipt, "cost": cost, "event": receipts[0]}
    _attestation(result, m["task_spec"]["roles"])
    return result


def _core_evidence(db: sqlite3.Connection, events: list[dict[str, Any]], eid: str, m: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    row = db.execute("SELECT * FROM evidence WHERE id=?", (eid,)).fetchone()
    _require(row is not None, "prior canonical core evidence required")
    payload = json.loads(row["payload_json"])
    _require(stable_id("ev", row["decision_id"], payload, length=24) == eid, "canonical evidence payload hash mismatch")
    anchors = [e for e in events if e["event_type"] == "VERDICT_RECORDED" and e["entity_id"] == eid]
    _require(len(anchors) == 1, "canonical combined verdict missing")
    anchor = anchors[0]
    decision = db.execute("SELECT * FROM decisions WHERE id=?", (row["decision_id"],)).fetchone()
    _require(decision is not None and decision["status"] == "VERIFIED" and decision["evidence_id"] == eid
             and not decision["recovery_required"], "canonical combined decision unsettled")
    latest = [e for e in events if e["event_type"] == "VERDICT_RECORDED" and e["continuation_id"] == row["continuation_id"]]
    _require(latest and latest[-1]["entity_id"] == eid, "canonical combined evidence superseded")
    _require(anchor["seq"] > m["freeze_event"]["seq"] and anchor["continuation_id"] == row["continuation_id"]
             and anchor["data"].get("decision_id") == row["decision_id"]
             and anchor["data"].get("verdict") == row["verdict"] == payload.get("verdict")
             and anchor["actor"] == row["verifier_id"] == payload.get("verifier_id") == "workers.lead-check"
             and row["assurance"] == payload.get("assurance") == "B"
             and row["verification_mode"] == payload.get("verification_mode") == "programmatic",
             "canonical combined verifier authority mismatch")
    proof = payload.get("evidence", {})
    artifact_hash = digest(files(_path(proof.get("candidate"))))
    _require(artifact_hash == proof.get("candidate_hash") and not proof.get("scope_error"), "current task/integration artifact hash mismatch")
    spec = m["task_spec"]
    acceptance_hash = digest({"checks": spec["checks"], "required": spec["required_checks"], "integration": spec["integration_checks"]})
    _require(proof.get("acceptance_hash") == acceptance_hash, "canonical acceptance hash mismatch")
    measurements = _core_records(db, events, "measurements")
    checks = proof.get("checks", [])
    _require(bool(checks) and len(checks) == len({c["check"] for c in checks}), "canonical measurement coverage missing/duplicate")
    for check in checks:
        name = check.get("check")
        _require(name in spec["checks"] and check.get("check_hash") == digest(spec["checks"][name])
                 and check.get("candidate_hash") == artifact_hash, "canonical check/code/artifact hash mismatch")
        key = "check:" + digest({"run": proof["run_key"], "check": check["check_hash"], "candidate": artifact_hash})
        _require(check["id"] == key and key in measurements
                 and measurements[key]["data"] == {k: v for k, v in check.items() if k != "id"}
                 and measurements[key]["event"]["seq"] < anchor["seq"], "immutable measurement record hash/anchor mismatch")
        classified = classify_observation(spec["checks"][name]["contract"], check["measurement"])
        _require(classified == check["classification"], "frozen deterministic reclassification differs")
        execution = check["measurement"].get("execution", {})
        if classified["status"] == "PASS":
            _require(type(execution.get("exit_code")) is int and execution["exit_code"] == 0
                     and not execution.get("timed_out") and not execution.get("error"), "canonical check process outcome not successful")
    _require(proof.get("check_hashes") == {c["check"]: c["check_hash"] for c in checks}, "canonical check hash coverage mismatch")
    failed = next((c["classification"]["status"] for c in checks if c["classification"]["status"] != "PASS"), None)
    if failed:
        _require(row["verdict"] == failed, "combined verdict hides failed deterministic gate")
    else:
        review = proof.get("review", {})
        key = review.get("run_key")
        reviews = _core_records(db, events, "reviews")
        roles = _core_records(db, events, "roles")
        _require(key in reviews and reviews[key]["data"] == review and key in roles, "canonical independent review record missing/stale")
        rr = db.execute("SELECT * FROM native_worker_runs WHERE key=?", (key,)).fetchone()
        _require(rr is not None and rr["status"] == "RECEIPTED" and rr["receipt_json"], "independent review run unsettled")
        receipt = json.loads(rr["receipt_json"])
        output = receipt.get("output", "").strip()
        if output.startswith("```json\n") or output.startswith("```\n"):
            output = "\n".join(output.splitlines()[1:-1])
        raw = json.loads(output)
        _require(raw == {k: review[k] for k in ("verdict", "reasons", "evidence")}
                 and review.get("candidate_hash") == artifact_hash and row["verdict"] == review.get("verdict"),
                 "combined review differs from native output/current artifact/verdict")
        refs = [c["id"] for c in checks]
        role = roles[key]["data"]
        _require(role.get("role") == "reviewer" and role["request"].get("session_id") is None
                 and role["request"].get("mode") == "read-only" and role.get("candidate_hash") == artifact_hash
                 and role.get("read_hash") == artifact_hash and set(role.get("test_references", [])) == set(refs),
                 "review request is not fresh read-only or its frozen inputs differ")
        _require(receipt.get("status") == "COMPLETED" and receipt.get("session_id")
                 and set(raw.get("evidence", [])) == set(refs) and bool(raw.get("reasons")), "review does not cover all frozen measurement references")
        native = [e for e in events if e["event_type"] == "WORKER_RECEIPT" and e["entity_id"] == key]
        _require(len(native) == 1 and native[0]["data"] == receipt
                 and max(measurements[c["id"]]["event"]["seq"] for c in checks)
                 < roles[key]["event"]["seq"] < native[0]["seq"] < reviews[key]["event"]["seq"] < anchor["seq"],
                 "combined measurement/review/settlement chronology invalid")
    return {**dict(row), "proof": proof}, anchor


def _trial_core(db: sqlite3.Connection, events: list[dict[str, Any]], m: dict[str, Any], directory: str | Path) -> dict[str, Any]:
    state, tasks, closure = _core_state(db, events)
    _require(state.get("phase") == "COMPLETED" and state.get("active"), "canonical core mission not COMPLETED")
    runs = _core_runs(db, events, m)
    conts = [dict(r) for r in db.execute("SELECT * FROM continuations")]
    active = {r["id"]: json.loads(r["context_json"]) for r in conts}
    task_cont = {ctx["native_task"]: cid for cid, ctx in active.items() if ctx.get("lead_kind") == "implementation"}
    integration = [cid for cid, ctx in active.items() if ctx.get("lead_integration") == state["revision"]]
    _require(len(integration) == 1, "current integration continuation missing/ambiguous")
    all_evidence, task_evidence = [], {}
    for ident in state["active"]:
        _require(ident in task_cont, "active task canonical continuation missing")
        cid = task_cont[ident]
        _require(active[cid].get("task_hash") == digest(tasks[ident]), "frozen task scope/hash changed")
        row = db.execute("SELECT id FROM evidence WHERE continuation_id=? ORDER BY created_at DESC,id DESC LIMIT 1", (cid,)).fetchone()
        _require(row is not None, "active task canonical verdict missing")
        task_evidence[ident] = row[0]
    for ident, cid in [(t, task_cont[t]) for t in state["active"]] + [("$integration", integration[0])]:
        cont = next(c for c in conts if c["id"] == cid)
        row = db.execute("SELECT id FROM evidence WHERE continuation_id=? ORDER BY created_at DESC,id DESC LIMIT 1", (cid,)).fetchone()
        _require(row is not None and cont["state"] == "SUCCEEDED", "required task/integration continuation not SUCCEEDED")
        ev, anchor = _core_evidence(db, events, row[0], m)
        proof = ev["proof"]
        _require(ev["verdict"] == "PASS" and anchor["seq"] < closure["seq"], "required combined verdict not canonical current PASS")
        names = m["task_spec"]["integration_checks"] if ident == "$integration" else [tasks[ident]["check"]]
        _require(set(proof["check_hashes"]) == set(names), "required task/integration acceptance omitted")
        deps = state["active"] if ident == "$integration" else tasks[ident]["depends_on"]
        _require(proof.get("dependencies") == {dep: task_evidence[dep] for dep in deps}, "current dependency verdicts differ from accepted inputs")
        reviewer = runs.get(proof["review"]["run_key"])
        _require(reviewer is not None and reviewer["role"] == "reviewer"
                 and reviewer["receipt"]["session_id"] not in {r["receipt"].get("session_id") for r in runs.values() if r["role"] != "reviewer"},
                 "reviewer shares execution/Lead session")
        if ident != "$integration":
            run = runs.get(proof["run_key"])
            _require(run is not None and run["role"] == "worker" and run["receipt"]["status"] == "COMPLETED", "accepted task lacks actual worker invocation")
        all_evidence.append(ev["id"])
        if ident == "$integration":
            artifact_hash = proof["candidate_hash"]
    _require(set(m["task_spec"]["required_checks"]) <= {tasks[t]["check"] for t in state["active"]}, "required operator acceptance not covered by active tasks")
    _frozen(db, events)
    costs = [r["cost"] for r in runs.values()]
    return {"directory": str(_path(str(directory))), "mission_id": m["mission_id"], "pair_id": m["pair_id"],
            "missions": m["missions"], "families": m["families"], "family_hash": m["family_hash"],
            "source_hash": m["source_hash"], "spec_hash": m["spec_hash"], "artifact_hash": artifact_hash,
            "freeze_ts": m["freeze_event"]["ts"], "proof_hash": digest(events), "evidence_ids": all_evidence,
            "invocations": len(runs), "cost_usd": sum(costs) if all(c is not None for c in costs) else None,
            "cost_status": "METERED" if all(c is not None for c in costs) else "UNMETERED", "invocation_costs": costs,
            "attestation": _attestation(runs, m["task_spec"]["roles"])}


def _trial(directory: str | Path, expected_hash: str, split: str) -> dict[str, Any]:
    with _trial_db(directory) as db:
        events = _events(db)
        m = _frozen(db, events)
        _require(m["procedure_hash"] == expected_hash and m["split"] == split, "trial procedure/split mismatch")
        if m["core"]:
            return _trial_core(db, events, m, directory)
        artifact_hash = digest(files(_path(m["artifact"])))
        runs = _runs(db, events, m)
        closes = [e for e in events if e["event_type"] == PREFIX + "CLOSED"]
        _require(bool(closes), "canonical mission closure missing")
        close = closes[-1]
        _require(close["data"].get("status") == "SUCCEEDED" and close["data"].get("candidate_hash") == artifact_hash,
                 "mission closure is not current accepted artifact")
        _require(not any(e["seq"] > close["seq"] and (e["event_type"].startswith(PREFIX)
                     or e["event_type"].startswith("WORKER_") or e["event_type"] == "VERDICT_RECORDED") for e in events),
                 "mission changed after canonical closure")
        _require(all(r["event"]["seq"] < close["seq"] for r in runs.values()), "closure predates native settlement")
        evidence = []
        for target, name in m["targets"].items():
            checks = [e for e in events if e["event_type"] == PREFIX + "CHECK" and e["data"].get("target") == target]
            reviews = [e for e in events if e["event_type"] == PREFIX + "REVIEW" and e["data"].get("review", {}).get("target") == target]
            _require(bool(checks) and bool(reviews), f"required acceptance/review missing: {target}")
            check_event, review_event = checks[-1], reviews[-1]
            _require(check_event["data"].get("check_id") == name, "target check identity mismatch")
            eid = check_event["data"].get("evidence_id")
            ev, anchor = _canonical_evidence(db, events, eid, m["task_spec"]["checks"][name], artifact_hash)
            _require(ev["verdict"] == "PASS", f"required canonical acceptance not PASS: {target}")
            execution = ev["proof"]["measurement"].get("execution", {})
            _require(type(execution.get("exit_code")) is int and execution["exit_code"] == 0
                     and not execution.get("timed_out") and not execution.get("error"), "deterministic check execution not successful")
            cont = db.execute("SELECT state FROM continuations WHERE id=?", (ev["continuation_id"],)).fetchone()
            _require(cont is not None and cont[0] == "SUCCEEDED", "acceptance continuation not SUCCEEDED")
            review = review_event["data"].get("review", {})
            run = runs.get(review_event["data"].get("run_key"))
            measured_run = runs.get(ev["proof"].get("run_key"))
            _require(measured_run is not None and measured_run["role"] != "reviewer"
                     and measured_run["receipt"]["status"] == "COMPLETED", "check lacks successful non-review execution")
            _require(run is not None and run["role"] == "reviewer" and run["receipt"]["status"] == "COMPLETED"
                     and run["receipt"].get("session_id")
                     and run["receipt"]["session_id"] not in {r["receipt"].get("session_id") for r in runs.values() if r["role"] != "reviewer"},
                     "review is not an independent native session")
            _require(review == {"target": target, "verdict": "PASS", "candidate_hash": artifact_hash,
                                "spec_hash": m["spec_hash"], "evidence_ids": [eid]}, "review proof stale, non-PASS or mismatched")
            try:
                output = json.loads(run["receipt"].get("output", ""))
            except (TypeError, ValueError) as exc:
                raise ProofUnavailable("reviewer canonical output is not review JSON") from exc
            _require(output == review, "review event differs from canonical reviewer output")
            _require(measured_run["event"]["seq"] < anchor["seq"] < check_event["seq"]
                     < run["event"]["seq"] <= review_event["seq"] < close["seq"], "check/review evidence chronology mismatch")
            evidence.extend([eid, check_event["id"], review_event["id"]])
        _frozen(db, events)  # catch source/code changes during evaluation
        _require(digest(files(_path(m["artifact"]))) == artifact_hash, "artifact changed during evaluation")
        costs = [r["cost"] for r in runs.values()]
        return {"directory": str(_path(str(directory))), "mission_id": m["mission_id"], "pair_id": m["pair_id"],
                "missions": m["missions"], "families": m["families"], "family_hash": m["family_hash"],
                "source_hash": m["source_hash"], "spec_hash": m["spec_hash"], "artifact_hash": artifact_hash,
                "freeze_ts": m["freeze_event"]["ts"], "proof_hash": digest(events), "evidence_ids": evidence,
                "invocations": len(runs), "cost_usd": sum(costs) if all(c is not None for c in costs) else None,
                "cost_status": "METERED" if all(c is not None for c in costs) else "UNMETERED",
                "invocation_costs": costs, "attestation": _attestation(runs, m["task_spec"]["roles"])}


class ProcedureLedger:
    """Immutable candidates, fresh paired evaluation, atomic activation/rollback."""

    def __init__(self, store: AutonomyStore, *, initial_procedure: str | None = None):
        self.store = store
        with store._transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS lead_procedure_versions (id TEXT PRIMARY KEY, version INTEGER UNIQUE NOT NULL, record_json TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS lead_procedure_evaluations (id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES lead_procedure_versions(id), report_json TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS lead_procedure_validated (id TEXT PRIMARY KEY REFERENCES lead_procedure_versions(id), evaluation_id TEXT)")
            schema = db.execute("SELECT value FROM metadata WHERE key='lead_learning_schema'").fetchone()
            _require(schema is None or schema[0] == "1", "incompatible procedure ledger schema")
            db.execute("INSERT OR IGNORE INTO metadata VALUES('lead_learning_schema','1')")
            if db.execute("SELECT value FROM metadata WHERE key=?", (ACTIVE_KEY,)).fetchone() is None:
                bound = db.execute("SELECT value FROM metadata WHERE key='native_worker_spec'").fetchone()
                baseline = json.loads(bound[0]).get("procedure", DEFAULT_PROCEDURE) if bound else DEFAULT_PROCEDURE
                if initial_procedure is not None:
                    _require(not bound or "procedure" not in json.loads(bound[0]) or initial_procedure == baseline,
                             "initial procedure differs from bound operator specification")
                    baseline = initial_procedure
                _text(baseline, "initial procedure")
                baseline = redact(baseline)
                record = {"id": "procedure_initial", "version": 1, "procedure": baseline,
                          "hash": digest(baseline), "parent_id": None, "rationale": "operator-owned initial procedure",
                          "scope": {"kind": "initial_operator_policy"}, "origins": [], "created_at": utc_now()}
                db.execute("INSERT INTO lead_procedure_versions VALUES(?,?,?)", (record["id"], 1, canonical_json(record)))
                db.execute("INSERT INTO lead_procedure_validated VALUES(?,NULL)", (record["id"],))
                db.execute("INSERT INTO metadata VALUES(?,?)", (ACTIVE_KEY, record["id"]))
                self._event(db, "INITIALIZED", record["id"], {"record": record}, "operator")

    def freeze_trial(self, mission_id: str | None = None, pair_id: str | None = None, split: str = "development",
                     family: str | None = None, source_mission_ids: Sequence[str] = (),
                     source_family_hashes: Sequence[str] = ()) -> dict[str, Any]:
        """Core bridge: freeze operator gates BEFORE planning; derive outputs later.

        Safe to repeat with identical arguments on restart. Configuring an arm
        after native dispatch is an explicit error. This records no verdict or
        paired-trial eligibility; those requirements are checked on extraction.
        """
        _require(split in {"development", "search", "holdout"}, "invalid learning split")
        with self.store._transaction() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='native_worker_spec'").fetchone()
            _require(row is not None, "bind an operator mission specification before freezing trial")
            bound = json.loads(row[0])
            spec = _operator_spec(bound)
            source = _path(bound["source"])
            source_hash = digest(files(source))
            ident = mission_id or digest({"directory": str(self.store.path.parent), "source_hash": source_hash,
                                          "operator_spec_hash": digest(spec)})
            manifest = {"schema": SCHEMA, "mission_id": ident, "pair_id": pair_id or "standalone:" + ident,
                        "split": split, "procedure_hash": self._record(db, self._active_id(db))["hash"],
                        "family": family or ident, "source": str(source), "source_hash": source_hash,
                        "spec_hash": digest(spec), "task_spec": spec,
                        "source_mission_ids": list(source_mission_ids), "source_family_hashes": list(source_family_hashes)}
            events = _events(db)
            existing = [e for e in events if e["event_type"] == PREFIX + "FROZEN"]
            if existing:
                _require(len(existing) == 1 and existing[0]["data"] == manifest, "learning trial manifest is immutable")
                return manifest
            _require(not any(e["event_type"] == "WORKER_RESERVED" for e in events), "freeze learning trial before native planning/reservations")
            self.store._append_event(db, continuation_id=None, entity_type="lead_trial", entity_id=ident,
                                     event_type=PREFIX + "FROZEN", actor=ACTOR, data=manifest, now=utc_now())
            # Freeze records dispatch inputs, not eligibility for an RSI claim.
            # Ordinary greenfield/custom-role missions remain valid; extraction
            # and evaluation retain strict roles/nonempty-source admission.
            _frozen(db, _events(db), require_trial_eligibility=False)
            return manifest

    def _event(self, db: sqlite3.Connection, kind: str, ident: str, data: dict[str, Any], actor: str) -> dict[str, Any]:
        return self.store._append_event(db, continuation_id=None, entity_type="lead_procedure", entity_id=ident,
                                        event_type="PROCEDURE_" + kind, actor=actor, data=redact(data), now=utc_now())

    def _record(self, db: sqlite3.Connection, ident: str) -> dict[str, Any]:
        events = _events(db)
        row = db.execute("SELECT * FROM lead_procedure_versions WHERE id=?", (ident,)).fetchone()
        _require(row is not None, f"procedure version missing: {ident}")
        record = json.loads(row["record_json"])
        anchors = [e for e in events if e["entity_id"] == ident and e["event_type"] in {"PROCEDURE_PROPOSED", "PROCEDURE_INITIALIZED"}]
        _require(len(anchors) == 1 and anchors[0]["data"].get("record") == record
                 and record["hash"] == digest(record["procedure"])
                 and record["version"] == row["version"] and record["id"] == row["id"], "immutable procedure record corrupt")
        return record

    def _active_id(self, db: sqlite3.Connection) -> str:
        ident = db.execute("SELECT value FROM metadata WHERE key=?", (ACTIVE_KEY,)).fetchone()[0]
        events = _events(db)
        activations = [e for e in events if e["event_type"] in {"PROCEDURE_INITIALIZED", "PROCEDURE_ACTIVATED", "PROCEDURE_ROLLED_BACK"}]
        _require(bool(activations) and activations[-1]["entity_id"] == ident, "active procedure metadata/event mismatch")
        return ident

    def active(self) -> dict[str, Any]:
        """Main reads this at each invocation, not a cached original spec value."""
        with self.store._transaction(immediate=False) as db:
            record = self._record(db, self._active_id(db))
            return {k: record[k] for k in ("id", "procedure", "hash", "version")}

    def propose(self, procedure: str, rationale: str, evidence_ids: Sequence[str], scope: Mapping[str, Any] | None = None) -> dict[str, Any]:
        _text(procedure, "procedure")
        _text(rationale, "rationale")
        _require(len(procedure) <= 20000 and not isinstance(evidence_ids, str) and bool(evidence_ids), "procedure/evidence IDs required")
        _require(scope is None or isinstance(scope, Mapping), "procedure scope must be an object")
        _require((scope or {}).get("artifact_equivalence", "frozen_acceptance") in {"frozen_acceptance", "exact_hash"},
                 "artifact equivalence must be frozen_acceptance or exact_hash")
        # Sanitize BEFORE storing so the immutable record and event stay identical.
        procedure, rationale = redact(procedure), redact(rationale)
        with self.store._transaction() as db:
            events = _events(db)
            m = _frozen(db, events)
            origins = []
            for eid in sorted(set(evidence_ids)):
                if m["core"]:
                    ev, anchor = _core_evidence(db, events, eid, m)
                    origins.append({"evidence_id": eid, "event_id": anchor["id"], "event_hash": anchor["event_hash"],
                                    "verdict": ev["verdict"], "missions": m["missions"], "families": m["families"]})
                    continue
                rows = [e for e in events if e["event_type"] == PREFIX + "CHECK" and e["data"].get("evidence_id") == eid]
                _require(bool(rows), "proposal requires prior canonical check evidence, not arbitrary JSON/IDs")
                e = rows[-1]
                name = e["data"].get("check_id")
                _require(name in m["task_spec"]["checks"] and m["targets"].get(e["data"].get("target")) == name,
                         "proposal check not frozen")
                ev, anchor = _canonical_evidence(db, events, eid, m["task_spec"]["checks"][name], digest(files(_path(m["artifact"]))))
                _require(m["freeze_event"]["seq"] < anchor["seq"] < e["seq"], "proposal evidence predates frozen acceptance")
                origins.append({"evidence_id": eid, "event_id": e["id"], "event_hash": e["event_hash"],
                                "verdict": ev["verdict"], "missions": m["missions"], "families": m["families"]})
            parent = self._record(db, self._active_id(db))
            _require(digest(procedure) != parent["hash"], "proposal is unchanged procedure")
            record = {"id": "procedure_" + uuid.uuid4().hex, "version": db.execute("SELECT max(version)+1 FROM lead_procedure_versions").fetchone()[0],
                      "procedure": procedure, "hash": digest(procedure), "parent_id": parent["id"],
                      "rationale": rationale, "scope": redact(dict(scope or {"kind": "matched_pilot_only"})),
                      "origins": origins, "created_at": utc_now()}
            db.execute("INSERT INTO lead_procedure_versions VALUES(?,?,?)", (record["id"], record["version"], canonical_json(record)))
            self._event(db, "PROPOSED", record["id"], {"record": record}, "lead")
            return record

    def _validate_origins(self, db: sqlite3.Connection, record: dict[str, Any]) -> None:
        events = _events(db)
        m = _frozen(db, events)
        for origin in record["origins"]:
            event = next((e for e in events if e["id"] == origin["event_id"]), None)
            _require(event is not None and event["event_hash"] == origin["event_hash"], "proposal origin event changed")
            if m["core"]:
                _core_evidence(db, events, origin["evidence_id"], m)
            else:
                name = event["data"]["check_id"]
                _canonical_evidence(db, events, origin["evidence_id"], m["task_spec"]["checks"][name], digest(files(_path(m["artifact"]))))

    def validate_candidate(self, candidate_id: str) -> dict[str, Any]:
        """Read-only, full canonical origin preflight BEFORE expensive trial calls.

        Returns the immutable candidate record plus baseline. Later evaluation
        repeats the same checks; this preflight is not a promotion verdict.
        """
        with self.store._transaction(immediate=False) as db:
            record = self._record(db, candidate_id)
            _require(record["parent_id"] == self._active_id(db), "candidate baseline is no longer active")
            self._validate_origins(db, record)
            baseline = self._record(db, record["parent_id"])
            return {**record, "baseline": {k: baseline[k] for k in ("id", "procedure", "hash", "version")}}

    def _evaluate(self, db: sqlite3.Connection, record: dict[str, Any], search: Sequence[tuple[str | Path, str | Path]],
                  holdout: Sequence[tuple[str | Path, str | Path]]) -> dict[str, Any]:
        _require(bool(search) and bool(holdout), "search and untouched independent holdout pairs required")
        _require(self._active_id(db) == record["parent_id"], "candidate baseline is no longer active")
        parent = self._record(db, record["parent_id"])
        self._validate_origins(db, record)
        used_missions = set(x for o in record["origins"] for x in o["missions"])
        used_families = set(x for o in record["origins"] for x in o["families"])
        pairs = []
        for split, group in (("search", search), ("holdout", holdout)):
            for pair in group:
                _require(len(pair) == 2, "baseline/candidate directory pair required")
                # Register exposure in canonical events BEFORE inspecting outcomes.
                manifests = []
                for directory in pair:
                    with _trial_db(directory) as trial_db:
                        manifests.append(_frozen(trial_db, _events(trial_db)))
                trial_hash = digest([str(_path(str(p))) for p in pair])
                for family in sorted(set(f for manifest in manifests for f in manifest["families"])):
                    canonical = _events(db)
                    prior = [e for e in canonical if e["event_type"] == "PROCEDURE_TRIAL_INSPECTED"
                             and e["data"].get("family_hash") == family]
                    same = [e for e in prior if e["entity_id"] == record["id"]
                            and e["data"].get("trial_hash") == trial_hash and e["data"].get("split") == split]
                    if split == "holdout":
                        _require(all(manifest["freeze_event"]["ts"] > record["created_at"] for manifest in manifests),
                                 "holdout was touched before proposal")
                        _require(len(prior) == len(same), "holdout already inspected by another candidate/pair or search")
                        development_families = {f for e in canonical if e["event_type"] == "PROCEDURE_PROPOSED"
                                                for o in e["data"]["record"]["origins"] for f in o["families"]}
                        _require(family not in development_families, "holdout overlaps procedure development")
                    if not same:
                        self._event(db, "TRIAL_INSPECTED", record["id"],
                                    {"family_hash": family, "trial_hash": trial_hash, "split": split}, ACTOR)
                left = _trial(pair[0], parent["hash"], split)
                right = _trial(pair[1], record["hash"], split)
                _require(left["directory"] != right["directory"] and left["pair_id"] == right["pair_id"], "paired mission identity mismatch")
                _require(left["spec_hash"] == right["spec_hash"] and left["source_hash"] == right["source_hash"], "paired frozen check/code/source/configuration/spec hashes differ")
                _require(left["attestation"] == right["attestation"], "paired requested/actual attestation status differs")
                if record["scope"].get("artifact_equivalence") == "exact_hash":
                    _require(left["artifact_hash"] == right["artifact_hash"], "paired accepted artifacts are not equivalent")
                _require(left["mission_id"] != right["mission_id"]
                         and left["mission_id"] not in right["missions"]
                         and right["mission_id"] not in left["missions"], "paired actual mission IDs/provenance overlap")
                # Shared donor provenance within a matched pair is legitimate;
                # only its union must be disjoint from training and other pairs.
                missions = set(left["missions"]) | set(right["missions"])
                families = set(left["families"]) | set(right["families"])
                _require(not missions & used_missions and not families & used_families, "mission split/family overlaps development or another pair")
                _require(not any(p["baseline"]["pair_id"] == left["pair_id"] for p in pairs), "duplicate evaluation pair ID")
                used_missions |= missions
                used_families |= families
                _require(right["invocations"] <= left["invocations"], "actual invocation reservation regression")
                metered = left["cost_status"] == right["cost_status"] == "METERED"
                if metered:
                    _require(right["cost_usd"] <= left["cost_usd"], "metered invocation cost regression")
                pairs.append({"split": split, "baseline": left, "candidate": right,
                              "invocations_saved": left["invocations"] - right["invocations"],
                              "cost_comparable": metered})
        _require(len(pairs) >= 2 and any(p["invocations_saved"] > 0 for p in pairs), "no strictly measured invocation improvement")
        # Re-open all authoritative ledgers after the sequential comparisons.
        for pair in pairs:
            for key, expected in (("baseline", parent["hash"]), ("candidate", record["hash"])):
                _require(_trial(pair[key]["directory"], expected, pair["split"]) == pair[key],
                         "trial proof changed during paired evaluation")
        return {"status": "ELIGIBLE", "pairs": pairs, "metric": "actual_native_invocation_reservations",
                "scope": record["scope"],
                "model_scope": ("requested-model matched pilot; runtime model unverified"
                                if any("MISSING" in p["baseline"]["attestation"].values() for p in pairs)
                                else "runtime-attested matched procedure pilot; no model capability claim"),
                "artifact_equivalence": record["scope"].get("artifact_equivalence", "frozen_acceptance"),
                "claim": "matched accepted-artifact pilot procedure improvement only",
                "previous_policy": {k: parent[k] for k in ("id", "hash", "version")}}

    def _assessment(self, db: sqlite3.Connection, candidate_id: str, search: Sequence[tuple[str | Path, str | Path]],
                    holdout: Sequence[tuple[str | Path, str | Path]], actor: str) -> tuple[dict[str, Any], ProofUnavailable | None]:
        record = self._record(db, candidate_id)
        error = None
        try:
            report = self._evaluate(db, record, search, holdout)
        except (ProofUnavailable, OSError, sqlite3.Error, KeyError, TypeError, ValueError) as exc:
            error = ProofUnavailable(str(exc))
            report = {"status": "PROOF_UNAVAILABLE", "reason": redact(str(exc)), "claim": "no demonstrated improvement"}
        report = {**report, "id": "evaluation_" + uuid.uuid4().hex, "candidate_id": candidate_id,
                  "candidate_hash": record["hash"], "actor": actor}
        # Revalidation may not silently replace already-inspected holdout outcomes.
        previous = [self._report(db, row[0]) for row in db.execute("SELECT id FROM lead_procedure_evaluations WHERE candidate_id=?", (candidate_id,))]
        if report["status"] == "ELIGIBLE":
            proof = digest(report["pairs"])
            for old in previous:
                if old["status"] != "ELIGIBLE" or digest(old["pairs"]) != proof:
                    error = ProofUnavailable("holdout proof changed after first inspection; propose a fresh candidate with fresh holdout")
                    report = {"id": report["id"], "candidate_id": candidate_id, "candidate_hash": record["hash"],
                              "actor": actor, "status": "PROOF_UNAVAILABLE", "reason": str(error)}
                    break
        report["report_hash"] = digest(report)
        db.execute("INSERT INTO lead_procedure_evaluations VALUES(?,?,?)", (report["id"], candidate_id, canonical_json(report)))
        self._event(db, "EVALUATED", candidate_id, {"report": report}, actor)
        return report, error

    def _report(self, db: sqlite3.Connection, evaluation_id: str) -> dict[str, Any]:
        row = db.execute("SELECT report_json FROM lead_procedure_evaluations WHERE id=?", (evaluation_id,)).fetchone()
        _require(row is not None, "procedure evaluation missing")
        report = json.loads(row[0])
        anchors = [e for e in _events(db) if e["event_type"] == "PROCEDURE_EVALUATED"
                   and e["data"].get("report", {}).get("id") == evaluation_id]
        _require(len(anchors) == 1 and anchors[0]["data"]["report"] == report
                 and digest({k: v for k, v in report.items() if k != "report_hash"}) == report.get("report_hash"),
                 "procedure evaluation audit hash mismatch")
        return report

    def evaluate(self, candidate_id: str, search: Sequence[tuple[str | Path, str | Path]],
                 holdout: Sequence[tuple[str | Path, str | Path]], actor: str) -> dict[str, Any]:
        _text(actor, "evaluation actor")
        with self.store._transaction() as db:
            report, error = self._assessment(db, candidate_id, search, holdout, actor)
        if error:
            raise error  # after audit/holdout consumption commit, never swallow
        return report

    def promote(self, candidate_id: str, search: Sequence[tuple[str | Path, str | Path]],
                holdout: Sequence[tuple[str | Path, str | Path]], actor: str) -> dict[str, Any]:
        _text(actor, "promotion actor")
        with self.store._transaction() as db:
            report, error = self._assessment(db, candidate_id, search, holdout, actor)
            if error is None:
                previous = self._active_id(db)
                db.execute("INSERT OR IGNORE INTO lead_procedure_validated VALUES(?,?)", (candidate_id, report["id"]))
                db.execute("UPDATE metadata SET value=? WHERE key=?", (candidate_id, ACTIVE_KEY))
                self._event(db, "ACTIVATED", candidate_id,
                            {"previous_id": previous, "evaluation_id": report["id"], "evidence": report}, actor)
        if error:
            raise error
        return {"active": self.active(), "previous_id": previous, "evaluation": report}

    def rollback(self, version_id: str, actor: str, rationale: str = "operator rollback") -> dict[str, Any]:
        _text(actor, "rollback actor")
        _text(rationale, "rollback rationale")
        with self.store._transaction() as db:
            previous = self._active_id(db)
            record = self._record(db, previous)
            ancestors = set()
            while record["parent_id"] is not None:
                ancestors.add(record["parent_id"])
                record = self._record(db, record["parent_id"])
            _require(version_id in ancestors, "rollback requires a prior validated ancestor")
            validated = db.execute("SELECT * FROM lead_procedure_validated WHERE id=?", (version_id,)).fetchone()
            _require(validated is not None, "rollback target has not been validated")
            if validated["evaluation_id"] is not None:
                anchors = [e for e in _events(db) if e["event_type"] == "PROCEDURE_ACTIVATED" and e["entity_id"] == version_id
                           and e["data"].get("evaluation_id") == validated["evaluation_id"]]
                _require(bool(anchors), "rollback validation is not canonical")
            db.execute("UPDATE metadata SET value=? WHERE key=?", (version_id, ACTIVE_KEY))
            self._event(db, "ROLLED_BACK", version_id, {"previous_id": previous, "rationale": redact(rationale)}, actor)
        return self.active()

    def trial_spec(self, directory: str | Path | None = None) -> dict[str, Any]:
        return trial_spec(directory or self.store.path.parent)

    def extract_trial(self, directory: str | Path | None = None, **expected: Any) -> dict[str, Any]:
        return extract_trial(directory or self.store.path.parent, **expected)

    def snapshot(self) -> dict[str, Any]:
        """Console audit projection; do not put held-out trial details in Lead prompts."""
        return self.history()

    inspect = snapshot

    def history(self) -> dict[str, Any]:
        with self.store._transaction(immediate=False) as db:
            return {"active_id": self._active_id(db),
                    "versions": [self._record(db, row[0]) for row in db.execute("SELECT id FROM lead_procedure_versions ORDER BY version")],
                    "evaluations": [self._report(db, row[0]) for row in db.execute("SELECT id FROM lead_procedure_evaluations ORDER BY rowid")]}


def trial_spec(directory: str | Path) -> dict[str, Any]:
    """Read the authoritative pre-planning manifest for the paired-runner adapter."""
    with _trial_db(directory) as db:
        m = _frozen(db, _events(db))
        return {**m["freeze_event"]["data"], "family_hash": m["family_hash"],
                "freeze_event_id": m["freeze_event"]["id"], "freeze_event_hash": m["freeze_event"]["event_hash"]}


def extract_trial(directory: str | Path, *, procedure_hash: str | None = None, split: str | None = None) -> dict[str, Any]:
    """Recompute proof/metrics; never read a supplied outcome/gain JSON report."""
    m = trial_spec(directory)
    return _trial(directory, procedure_hash or m["procedure_hash"], split or m["split"])
