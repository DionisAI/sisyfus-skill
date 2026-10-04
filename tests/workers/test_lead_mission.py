"""Retained protocol fixtures only: no real model or model identity claims."""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from sisyfus.autonomy.policy import IdempotencyConflictError
from sisyfus.workers.journal import DispatchBlocked
from sisyfus.workers.lead_contracts import load_lead_spec
from sisyfus.workers.lead_mission import LeadMission, strict_json
from sisyfus.workers.mission import files
from sisyfus.workers.protocol import Receipt, digest


def make_spec(root, *, two=False, initial=True, **overrides):
    source = root / "source"
    source.mkdir()
    (source / "README.md").write_text("frozen fixture project")
    evaluator = root / "check.py"
    evaluator.write_text("import json,pathlib,sys\np=pathlib.Path(sys.argv[1])\n"
                         "names=sys.argv[2:]\nprint(json.dumps({'ok':all((p/n).is_file() and (p/n).read_text()=='42' for n in names)}))\n")
    def check(names):
        return {"argv": [sys.executable, "-I", "-S", str(evaluator), "{candidate}", *names],
                "code_hashes": {str(evaluator): hashlib.sha256(evaluator.read_bytes()).hexdigest()},
                "contract": {"kind": "rules", "pass_if": {"all": [{"path": "ok", "op": "eq", "value": True}]},
                             "fail_if": {"all": [{"path": "ok", "op": "eq", "value": False}]}}}
    tasks = [task("build", "a.txt", "a")]
    checks = {"a": check(["a.txt"])}
    if two:
        tasks.append(task("other", "b.txt", "b"))
        checks["b"] = check(["b.txt"])
    checks["whole"] = check(["a.txt", "b.txt"] if two else ["a.txt"])
    spec = {"objective": "Implement fixture with frozen deterministic checks and independent reviews",
            "source": str(source), "checks": checks, "required_checks": ["a", "b"] if two else ["a"],
            "integration_checks": ["whole"], "timeout": 3, "parallelism": 2,
            "validation_kind": "OFFLINE_STUB_NOT_REAL_MODEL_CALLS"}
    if initial:
        spec["tasks"] = tasks
    spec.update(overrides)
    return spec


def task(ident, path="a.txt", check="a", *, deps=(), repair=None):
    result = {"id": ident, "objective": "write " + path, "check": check, "depends_on": list(deps),
              "write_paths": [path], "acceptance": "frozen " + check + " acceptance"}
    if repair:
        result["repair_of"] = repair
    return result


def plan(tasks):
    return {"architecture": "isolated modules, then explicit integration", "interfaces": ["42 is the fixture interface"], "tasks": tasks}


class Stub:
    controls = ("interrupt",)
    def __init__(self, kind, callback=None):
        self.kind, self.callback = kind, callback
        self.requests = []
        self.lock = threading.Lock()
    def probe(self):
        return {"available": True, "version": "PROTOCOL-STUB-NOT-A-MODEL", "controls": self.controls}
    def run(self, request, emit, controls):
        with self.lock:
            self.requests.append(request)
            serial = len(self.requests)
        if self.callback:
            result = self.callback(request, emit, controls)
            if result is not None:
                return result
        if self.kind == "codex":
            payload = json.loads(request.prompt.split("\n", 1)[1])
            for path in payload["task"]["write_paths"]:
                target = Path(request.cwd) / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("42")
            return Receipt("COMPLETED", session_id=f"stub-worker-{serial}", output="I claim success; not evidence", requested_model=request.model)
        payload = json.loads(request.prompt.split("\n", 1)[1])
        if request.prompt.startswith("Independent"):
            raw = {"verdict": "PASS", "reasons": ["fixture deterministic receipts inspected"], "evidence": payload["evidence_references"]}
        elif request.prompt.startswith("Classify"):
            raw = {"classification": "environment", "reasons": ["operator diagnosis required"],
                   "evidence": payload["evidence_references"], "action": "wait"}
        else:
            raw = plan([task("build")])
        return Receipt("COMPLETED", session_id=f"stub-claude-{serial}", output=json.dumps(raw), requested_model=request.model)


def mission(root, spec, *, worker=None, claude=None):
    m = LeadMission(root / "control", spec)
    m.drivers = {"codex": Stub("codex", worker), "claude": Stub("claude", claude)}
    return m


@pytest.mark.parametrize("bad", ['{"x":1,"x":2}', '{"x":NaN}', 'prose {"x":1}', '[{}]', '{"x":Infinity}', '```JSON\n{}\n```', '{} {}'])
def test_model_json_is_strict(bad):
    with pytest.raises(ValueError):
        strict_json(bad)


def test_optional_json_fence():
    assert strict_json('```json\n{"x":1}\n```') == {"x": 1}


def test_initial_lead_worker_review_integration_restart(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path, initial=False))
    before = files(Path(m.spec["source"]))
    result = m.run(max_cycles=20)
    assert result["all_verified"], result
    assert result["phase"] == "COMPLETED"
    assert result["integration"]["evidence"]["verdict"] == "PASS"
    assert [r["role"] for r in result["runs"]] == ["lead", "worker", "reviewer", "reviewer"]
    assert all(r["task_id"] == "planner" for r in result["runs"] if r["role"] != "worker")
    assert len({r["key"] for r in result["runs"]}) == 4
    assert all(r["receipt"]["actual_model"] is None for r in result["runs"])
    assert all(value is None for value in result["budgets"].values())
    assert set(result["budget_display"].values()) == {"unlimited"}
    assert files(Path(m.spec["source"])) == before
    assert m.store.verify_event_chain()["valid"]
    again = mission(tmp_path, None)
    resumed = again.run(max_cycles=3)
    assert resumed["all_verified"] and resumed["native_call_reservations"] == 4
    assert not any(d.requests for d in again.drivers.values())


def test_roles_override_conflicting_legacy_driver_models(tmp_path):
    raw = make_spec(tmp_path, initial=False, drivers={"codex": {"model": "legacy-wrong-worker"}, "claude": {"model": "legacy-wrong-lead"}})
    m = mission(tmp_path, raw)
    assert m.run(max_cycles=20)["all_verified"]
    assert all(r.model == "gpt-6.1-sol" for r in m.drivers["codex"].requests)
    assert all(r.model == "claude-opus-5-5" for r in m.drivers["claude"].requests)
    reviewers = [r for r in m.drivers["claude"].requests if r.prompt.startswith("Independent")]
    assert len(reviewers) == 2
    assert all(r.session_id is None and r.mode == "read-only" and r.task_id == "planner" for r in reviewers)
    assert all(r.max_turns is None for d in m.drivers.values() for r in d.requests)
    assert all("I claim success" not in r.prompt for r in reviewers)


def test_real_parallel_scoped_implementations(tmp_path):
    barrier = threading.Barrier(2)
    def worker(request, *_):
        barrier.wait(timeout=5)
    m = mission(tmp_path, make_spec(tmp_path, two=True), worker=worker)
    result = m.run(max_cycles=25)
    assert result["all_verified"], result
    active = peak = 0
    for event in m.journal.events(0, 1000):
        if event["type"] == "WORKER_RESERVED": active += 1
        if event["type"] == "WORKER_RECEIPT": active -= 1
        peak = max(peak, active)
    assert peak == 2 and active == 0
    candidate = Path(result["integration"]["evidence"]["payload"]["evidence"]["candidate"])
    assert (candidate / "a.txt").read_text() == (candidate / "b.txt").read_text() == "42"


def test_dependency_is_integrated_not_only_copied_under_inputs(tmp_path):
    def worker(request, *_):
        if request.task_id == "other":
            assert (Path(request.cwd) / "a.txt").read_text() == "42"
            assert not (Path(request.cwd) / "inputs").exists()
    raw = make_spec(tmp_path, two=True)
    raw["tasks"][1]["depends_on"] = ["build"]
    m = mission(tmp_path, raw, worker=worker)
    assert m.run(max_cycles=25)["all_verified"]


@pytest.mark.parametrize("role", ["lead", "worker", "reviewer"])
def test_unknown_calls_fence_restart_and_never_redispatch(tmp_path, role):
    def worker(*_):
        return Receipt("UNKNOWN", error="uncertain transport") if role == "worker" else None
    def claude(request, *_):
        is_review = request.prompt.startswith("Independent")
        if role == "lead" and not is_review or role == "reviewer" and is_review:
            return Receipt("UNKNOWN", error="uncertain transport")
    m = mission(tmp_path, make_spec(tmp_path, initial=False), worker=worker, claude=claude)
    result = m.run(max_cycles=10)
    assert result["unresolved"] and not result["all_verified"]
    count = result["native_call_reservations"]
    again = mission(tmp_path, None)
    result = again.run(max_cycles=3)
    assert result["phase"] == "UNKNOWN" and result["native_call_reservations"] == count
    assert not any(d.requests for d in again.drivers.values())


def test_orphan_role_reservation_becomes_unknown(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path))
    m.journal.reserve("stranded-lead", "planner", "fp")
    again = mission(tmp_path, None)
    result = again.run(max_cycles=3)
    assert result["phase"] == "UNKNOWN" and len(result["runs"]) == 1
    assert result["runs"][0]["status"] == "UNKNOWN"


def test_unlimited_is_not_an_eight_call_sentinel(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path))
    for index in range(50):
        key = "role-" + str(index)
        assert m.journal.reserve(key, "planner", str(index)) is None
        m.journal.complete(key, Receipt("COMPLETED", output="stub").as_dict())
    assert m.snapshot()["counters"]["calls"] == 50
    assert m.spec["max_calls"] is None


@pytest.mark.parametrize("cap,usage", [("max_calls", {}), ("max_tokens", {"total_tokens": 5}), ("max_cost_usd", {"cost_usd": 5})])
def test_optional_shared_caps_are_atomic(tmp_path, cap, usage):
    m = mission(tmp_path, make_spec(tmp_path, **{cap: 1 if cap == "max_calls" else 5}))
    m.journal.reserve("first", "planner", "fp")
    m.journal.complete("first", Receipt("COMPLETED", usage=usage).as_dict())
    with pytest.raises(DispatchBlocked):
        m.journal.reserve("second", "planner", "fp2")
    assert len(m.journal.runs()) == 1
    assert m.store.verify_event_chain()["valid"]


@pytest.mark.parametrize("cap", ["max_tokens", "max_cost_usd"])
def test_missing_telemetry_under_optional_cap_fences_spending(tmp_path, cap):
    m = mission(tmp_path, make_spec(tmp_path, **{cap: 100}))
    m.journal.reserve("first", "planner", "fp")
    with pytest.raises(DispatchBlocked, match="metering"):
        m.journal.reserve("concurrent", "planner", "fp2")
    m.journal.complete("first", Receipt("COMPLETED").as_dict())
    with pytest.raises(DispatchBlocked, match="metering"):
        m.journal.reserve("second", "planner", "fp3")


def test_session_totals_are_not_double_counted(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path))
    for index, total in enumerate([10, 15]):
        key = str(index)
        m.journal.reserve(key, "planner", key)
        m.journal.complete(key, Receipt("COMPLETED", session_id="same-native-session", usage={"total": {"totalTokens": total}, "cost_usd": total / 10}).as_dict())
    assert m.journal.counters()["tokens"] == 15
    assert m.journal.counters()["cost_usd"] == 1.5


def test_wall_cap_is_durable_and_bounds_next_call(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path, max_wall_minutes=.05, timeout=10))
    assert .05 <= m.call_timeout() <= 3
    m.journal.update(lambda s: s.update(created_at="2000-01-01T00:00:00Z"))
    assert m.run(max_cycles=1)["phase"] == "BUDGET_EXHAUSTED"
    with pytest.raises(DispatchBlocked):
        m.journal.reserve("new", "planner", "fp")


def test_pause_resume_persistent_stop_and_no_new_reservations(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path))
    m.journal.pause(True)
    result = m.run(max_cycles=2)
    assert result["phase"] == "PAUSED" and not result["runs"]
    m.journal.pause(False)
    assert m.run(max_cycles=20)["all_verified"]
    m.request_stop()
    again = mission(tmp_path, None)
    assert again.stop.is_set() and again.run(max_cycles=1)["phase"] == "STOPPED"
    with pytest.raises(DispatchBlocked, match="stopped"):
        again.journal.reserve("new", "planner", "fp")


def test_stop_interrupts_inflight_role(tmp_path):
    started = threading.Event()
    def claude(request, emit, controls):
        started.set()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            for command in controls():
                if command["action"] == "interrupt":
                    emit("control_ack", {"command_id": command["id"], "accepted": True})
                    return Receipt("INTERRUPTED")
            time.sleep(.01)
        raise AssertionError("stop interrupt not delivered")
    m = mission(tmp_path, make_spec(tmp_path, initial=False), claude=claude)
    results = []
    thread = threading.Thread(target=lambda: results.append(m.run(max_cycles=10)))
    thread.start()
    assert started.wait(3)
    m.request_stop()
    thread.join(5)
    assert not thread.is_alive() and results[0]["phase"] == "STOPPED"
    assert len(m.journal.runs()) == 1


@pytest.mark.parametrize("bad", ["prose PASS", '{"verdict":"PASS","reasons":["claim"],"evidence":["invented"]}',
                              '{"verdict":"PASS","reasons":[],"evidence":[]}', '{"verdict":"MAYBE","reasons":["x"],"evidence":["x"]}'])
def test_malformed_or_unsubstantiated_review_never_passes(tmp_path, bad):
    def claude(request, *_):
        if request.prompt.startswith("Independent"):
            return Receipt("COMPLETED", output=bad)
    m = mission(tmp_path, make_spec(tmp_path), claude=claude)
    result = m.run(max_cycles=10)
    assert not result["all_verified"] and result["nodes"][0]["verdict"] == "INVALID"
    assert result["diagnoses"][0]["data"]["classification"] == "environment"


def test_review_mutation_is_invalid_even_if_model_claims_pass(tmp_path):
    def claude(request, *_):
        if request.prompt.startswith("Independent"):
            (Path(request.cwd) / "a.txt").write_text("999")
    m = mission(tmp_path, make_spec(tmp_path), claude=claude)
    result = m.run(max_cycles=10)
    assert not result["all_verified"] and result["nodes"][0]["verdict"] == "INVALID"


@pytest.mark.parametrize("kind", ["scope", "model", "check", "nonzero"])
def test_integrity_and_process_outcome_cannot_be_spoofed(tmp_path, kind):
    def worker(request, *_):
        if kind == "scope":
            (Path(request.cwd) / "README.md").write_text("unauthorized change")
        if kind == "model":
            (Path(request.cwd) / "a.txt").write_text("42")
            return Receipt("COMPLETED", actual_model="wrong-attested-model")
    raw = make_spec(tmp_path)
    if kind == "nonzero":
        evaluator = tmp_path / "check.py"
        evaluator.write_text("import sys\nprint('{\"ok\":true,\"execution\":{\"exit_code\":0}}')\nsys.exit(7)\n")
        for check in raw["checks"].values():
            check["code_hashes"][str(evaluator)] = hashlib.sha256(evaluator.read_bytes()).hexdigest()
    m = mission(tmp_path, raw, worker=worker)
    if kind == "check":
        (tmp_path / "check.py").write_text("print('{\"ok\":true}')")
    result = m.run(max_cycles=10)
    assert not result["all_verified"]
    assert result["nodes"][0]["verdict"] == ("ERROR" if kind == "nonzero" else "INVALID")
    assert not any(r.prompt.startswith("Independent") for r in m.drivers["claude"].requests)


def test_repair_preserves_successful_sibling_and_historical_failure(tmp_path):
    def worker(request, *_):
        if request.task_id == "build":
            (Path(request.cwd) / "a.txt").write_text("wrong")
            return Receipt("COMPLETED", output="assert PASS")
    def claude(request, *_):
        if request.prompt.startswith("Classify"):
            payload = json.loads(request.prompt.split("\n", 1)[1])
            return Receipt("COMPLETED", output=json.dumps({"classification": "implementation", "reasons": ["bad value"],
                "evidence": payload["evidence_references"], "action": "repair", "plan": plan([task("fixed", repair="build")])}))
    m = mission(tmp_path, make_spec(tmp_path, two=True), worker=worker, claude=claude)
    result = m.run(max_cycles=25)
    assert result["all_verified"], result
    nodes = {n["id"]: n for n in result["nodes"]}
    assert nodes["build"]["verdict"] == "FAIL" and nodes["build"]["superseded_by"] == "fixed"
    assert nodes["other"]["verdict"] == "PASS" and nodes["other"]["attempts"] == 1
    assert [r.task_id for r in m.drivers["codex"].requests].count("other") == 1
    assert result["revision"] == 2 and len(result["diagnoses"]) == 1
    assert m.store.verify_event_chain()["valid"]


def test_frozen_acceptance_ids_and_dependency_repair_edges(tmp_path):
    raw = make_spec(tmp_path, two=True)
    raw["tasks"][1]["depends_on"] = ["build"]
    m = mission(tmp_path, raw)
    m._initial_plan()
    with pytest.raises(ValueError, match="dependency"):
        m.admit_plan(plan([task("fixed", repair="build")]), "bad-edge")
    bad = task("fixed", repair="build")
    bad["acceptance"] = "weaker"
    with pytest.raises(ValueError, match="acceptance"):
        m.admit_plan(plan([bad]), "bad-contract")
    m.admit_plan(plan([task("fixed", repair="build"), task("other_fixed", "b.txt", "b", deps=["fixed"], repair="other")]), "repair")
    with pytest.raises(ValueError, match="historical"):
        m.admit_plan(plan([task("build")]), "old-id")
    assert m.task("other")["depends_on"] == ["build"]
    assert m.task("other_fixed")["depends_on"] == ["fixed"]


def test_optional_revision_cap_stops_without_blind_retry(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path, max_iterations=1))
    m._initial_plan()
    with pytest.raises(DispatchBlocked, match="max_iterations"):
        m.admit_plan(plan([task("fixed", repair="build")]), "repair")
    assert len(m.tasks()) == 1


def test_more_than_32_historical_nodes_with_null_revision_limit(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path))
    m._initial_plan()
    previous = "build"
    for index in range(40):
        ident = "repair_" + str(index)
        m.admit_plan(plan([task(ident, repair=previous)]), ident)
        previous = ident
    assert len(m.tasks()) == 41 and len(m.active_tasks()) == 1
    assert m.snapshot()["counters"]["iterations"] == 41
    assert m.store.verify_event_chain()["valid"]


def test_completed_evidence_becomes_stale_without_rewriting_history(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path))
    assert m.run(max_cycles=20)["all_verified"]
    evidence = m.store.latest_evidence(m.continuations()["build"]["id"])
    (Path(evidence["payload"]["evidence"]["candidate"]) / "a.txt").write_text("corruption")
    result = m.snapshot()
    assert not result["all_verified"] and result["phase"] == "STALE"
    assert result["nodes"][0]["verdict"] == "PASS" and result["nodes"][0]["stale"]


@pytest.mark.parametrize("review_completed", [False, True])
def test_completed_receipts_replayed_after_crash_before_settlement(tmp_path, review_completed):
    m = mission(tmp_path, make_spec(tmp_path))
    m._initial_plan()
    c = m.store.claim_due_continuation("old-controller")
    decision = m.planner(c, m.runtime.planner_context(c))
    record, running, _ = m.store.reserve_decision(c["id"], worker_id="old-controller", lease_token=c["lease_token"], expected_version=c["version"], decision=decision)
    _, running = m.store.mark_execution_started(record["id"], worker_id="old-controller", lease_token=c["lease_token"], expected_version=running["version"])
    binding = m.registry.get("workers.execute")
    result = binding.capability.execute(decision.arguments, idempotency_key=decision.idempotency_key)
    if review_completed:
        _, verifying = m.store.record_execution(record["id"], worker_id="old-controller", lease_token=c["lease_token"], expected_version=running["version"], result=result.as_dict())
        assert binding.verifier.verify(m.runtime.planner_context(verifying), decision, result).normalized().verdict.value == "PASS"
    with m.store._transaction() as db:
        db.execute("UPDATE continuations SET lease_expires_at='2000-01-01T00:00:00Z' WHERE id=?", (c["id"],))
    again = mission(tmp_path, None)
    resumed = again.run(max_cycles=20)
    assert resumed["all_verified"], resumed
    assert not again.drivers["codex"].requests
    assert len(again.drivers["claude"].requests) == (1 if review_completed else 2)
    assert len(resumed["runs"]) == 3 and resumed["nodes"][0]["attempts"] == 1


def test_controller_lock_and_spec_binding(tmp_path):
    raw = make_spec(tmp_path)
    m = mission(tmp_path, raw)
    m._run_lock.acquire()
    try:
        with pytest.raises(DispatchBlocked, match="already"):
            m.run(max_cycles=1)
    finally:
        m._run_lock.release()
    changed = copy.deepcopy(raw)
    changed["objective"] = "different goal"
    with pytest.raises(IdempotencyConflictError):
        LeadMission(m.directory, changed)


def test_procedure_proposal_is_durable_not_unmeasured_promotion(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path))
    baseline = m.procedure()
    key = m.propose_procedure("inspect interfaces before fan-out", "fixture-diagnosis")
    again = mission(tmp_path, None)
    snap = again.snapshot()
    assert snap["procedure"] == baseline
    assert snap["improvements"][0]["key"] == key
    assert snap["improvements"][0]["data"]["status"] == "PROPOSED_UNGROUNDED"
    assert snap["improvements"][0]["data"]["proof_error"]
    assert again.store.verify_event_chain()["valid"]


def test_known_native_completion_with_invalid_artifact_is_not_unknown(tmp_path):
    def worker(request, *_):
        (Path(request.cwd) / "a.txt").symlink_to("/etc/passwd")
        return Receipt("COMPLETED", output="terminal completion")
    m = mission(tmp_path, make_spec(tmp_path), worker=worker)
    result = m.run(max_cycles=10)
    assert not result["all_verified"] and not result["unresolved"]
    assert result["nodes"][0]["verdict"] == "INVALID"
    assert result["runs"][0]["receipt"]["status"] == "COMPLETED"
    assert result["diagnoses"]


def test_integration_failed_check_is_diagnosed_not_task_success(tmp_path):
    raw = make_spec(tmp_path)
    raw["checks"]["whole"]["argv"][-1] = "missing-project-deliverable.txt"
    m = mission(tmp_path, raw)
    result = m.run(max_cycles=15)
    assert result["nodes"][0]["verdict"] == "PASS"
    assert not result["all_verified"] and result["integration"]["evidence"]["verdict"] == "FAIL"
    assert result["diagnoses"]
    assert len([r for r in result["runs"] if r["role"] == "reviewer"]) == 1


def test_reviewer_rejects_semantic_defect_despite_test_pass(tmp_path):
    def claude(request, *_):
        if request.prompt.startswith("Independent"):
            payload = json.loads(request.prompt.split("\n", 1)[1])
            return Receipt("COMPLETED", output=json.dumps({"verdict": "FAIL", "reasons": ["semantic contract violation"],
                           "evidence": payload["evidence_references"]}))
    m = mission(tmp_path, make_spec(tmp_path), claude=claude)
    result = m.run(max_cycles=12)
    node = result["nodes"][0]
    assert not result["all_verified"] and node["verdict"] == "FAIL"
    assert node["verification"]["evidence"]["checks"][0]["classification"]["status"] == "PASS"
    assert node["verification"]["evidence"]["review"]["verdict"] == "FAIL"


def test_multiple_integration_checks_all_require_review_references(tmp_path):
    raw = make_spec(tmp_path, integration_checks=["a", "whole"])
    m = mission(tmp_path, raw)
    result = m.run(max_cycles=20)
    assert result["all_verified"]
    integration = result["integration"]["evidence"]["payload"]["evidence"]
    assert len(integration["checks"]) == 2
    assert set(integration["review"]["evidence"]) == {c["id"] for c in integration["checks"]}


def test_malformed_initial_architecture_gets_evidence_bound_diagnosis(tmp_path):
    def claude(request, *_):
        if request.prompt.startswith("You are"):
            return Receipt("COMPLETED", output="prose rather than JSON")
    m = mission(tmp_path, make_spec(tmp_path, initial=False), claude=claude)
    result = m.run(max_cycles=5)
    assert not result["all_verified"] and result["phase"] == "WAITING_LEAD"
    refs = result["diagnoses"][0]["data"]["evidence"]
    assert len(refs) == 1 and refs[0].startswith("run:lead:architecture:")
    assert len(result["runs"]) == 3
    assert len(m.journal.records("format_errors")) == 2


def test_learning_manifest_precedes_direct_reservation(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path))
    m.configure_learning_trial(pair_id="frozen-pair", split="search", mission_id="fixture-arm")
    m.journal.reserve("manual-native", "planner", "fp")
    events = m.journal.events(0, 1000)
    frozen = [e for e in events if e["type"] == "LEAD_LEARNING_FROZEN"]
    reservation = next(e for e in events if e["type"] == "WORKER_RESERVED")
    assert len(frozen) == 1 and frozen[0]["seq"] < reservation["seq"]
    assert frozen[0]["data"]["pair_id"] == "frozen-pair" and frozen[0]["data"]["split"] == "search"
    assert "artifact" not in frozen[0]["data"]
    with pytest.raises(ValueError, match="precede"):
        m.configure_learning_trial(pair_id="changed", split="holdout")


def test_actual_unfrozen_orphan_is_unknown_without_backfilled_proof(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path))
    # Simulate an older controller, not a current API path.
    m.journal.before_reserve = None
    m.journal.reserve("legacy-orphan", "planner", "fp")
    again = mission(tmp_path, None)
    result = again.run(max_cycles=2)
    assert result["phase"] == "UNKNOWN" and len(result["runs"]) == 1
    assert not any(e["type"] == "LEAD_LEARNING_FROZEN" for e in again.journal.events(0, 1000))


def test_bound_procedure_is_shared_ledger_genesis_and_in_lead_prompt(tmp_path):
    raw = make_spec(tmp_path, initial=False, procedure="operator frozen candidate policy")
    m = mission(tmp_path, raw)
    assert m.procedure()["procedure"] == raw["procedure"]
    assert m.run(max_cycles=20)["all_verified"]
    first = m.drivers["claude"].requests[0]
    payload = json.loads(first.prompt.split("\n", 1)[1])
    assert payload["procedure"]["hash"] == digest(raw["procedure"])
    assert m.learning.active() == m.procedure()
    assert not m.journal.records("procedures")


def test_missing_native_attestation_remains_explicit_in_canonical_trial(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path, initial=False))
    assert m.run(max_cycles=20)["all_verified"]
    proof = m.learning.extract_trial()
    assert set(proof["attestation"].values()) == {"MISSING"}
    assert proof["invocations"] == 4
    assert all(r["receipt"]["actual_model"] is None for r in m.journal.runs())
    assert m.store.verify_event_chain()["valid"]


def test_trial_runner_hook_is_idempotent_and_never_claims_fixture_promotion(tmp_path):
    evaluation_root = tmp_path / "operator-catalog"
    evaluation_root.mkdir()
    raw = make_spec(tmp_path, rsi={"enabled": True, "auto_promote": True, "evaluation_root": str(evaluation_root)})
    m = mission(tmp_path, raw)
    # Only exercise controller handoff here. This stub is not paired evidence,
    # cannot activate anything, and says so in its structured result.
    m.journal.record("improvements", "fixture-handoff", {"ledger_proposal": {"id": "fixture-not-evaluated"}})
    calls = []
    def runner(**kwargs):
        calls.append(kwargs)
        return {"status": "FIXTURE_NOT_EVALUATED", "promoted": False}
    m.set_trial_runner(runner)
    baseline = m.learning.active()
    m._procedure_trial_boundary("completed")
    m._procedure_trial_boundary("completed")
    assert len(calls) == 1 and calls[0]["evaluation_root"] == evaluation_root.resolve()
    assert m.learning.active() == baseline
    assert m.journal.records("trial_results")[0]["data"]["promoted"] is False


def test_uncertain_trial_runner_handoff_is_not_repeated(tmp_path):
    root = tmp_path / "catalog"
    root.mkdir()
    m = mission(tmp_path, make_spec(tmp_path, rsi={"evaluation_root": str(root)}))
    ids = ["fixture-uncertain-candidate"]
    m.journal.record("improvements", "fixture", {"ledger_proposal": {"id": ids[0]}})
    key = digest({"candidate_id": ids[0], "root": str(root.resolve())})
    m.journal.record("trial_requests", key, {"boundary": "completed", "candidate_id": ids[0], "evaluation_root": str(root.resolve())})
    m.set_trial_runner(lambda **_: pytest.fail("uncertain handoff must not repeat"))
    with pytest.raises(DispatchBlocked, match="uncertain"):
        m._procedure_trial_boundary("completed")


def test_three_completed_architecture_answers_auto_correct_strict_schema(tmp_path):
    count = 0
    def claude(request, *_):
        nonlocal count
        if request.prompt.startswith("You are"):
            count += 1
            raw = plan([task("build")])
            if count == 1:
                raw["interfaces"] = {"module.function": "keyed map is invalid"}
            elif count == 2:
                raw["tasks"][0]["driver"] = "claude"
            return Receipt("COMPLETED", output=json.dumps(raw))
    m = mission(tmp_path, make_spec(tmp_path, initial=False), claude=claude)
    frozen = digest(m.spec["checks"])
    result = m.run(max_cycles=20)
    assert result["all_verified"] and count == 3
    leads = [r for r in result["runs"] if r["role"] == "lead"]
    assert len({r["key"] for r in leads}) == 3 and all(r["receipt"]["status"] == "COMPLETED" for r in leads)
    assert len(m.journal.records("format_errors")) == 2 and digest(m.spec["checks"]) == frozen
    assert "format_correction" in m.drivers["claude"].requests[1].prompt


def test_diagnosis_exact_refs_and_plan_schema_auto_correct_without_weakening(tmp_path):
    count = 0
    def worker(request, *_):
        if request.task_id == "build":
            (Path(request.cwd) / "a.txt").write_text("wrong")
            return Receipt("COMPLETED")
    def claude(request, *_):
        nonlocal count
        if request.prompt.startswith("Classify"):
            count += 1
            payload = json.loads(request.prompt.split("\n", 1)[1])
            raw = {"classification": "implementation", "reasons": ["repair frozen task"], "action": "repair",
                   "evidence": payload["evidence_references"], "plan": plan([task("fixed", repair="build")])}
            if count == 1:
                raw["evidence"] = [payload["evidence_references"][0] + " because it failed"]
            elif count == 2:
                raw["plan"]["interfaces"] = {"module": "must be an array"}
            return Receipt("COMPLETED", output=json.dumps(raw))
    m = mission(tmp_path, make_spec(tmp_path), worker=worker, claude=claude)
    result = m.run(max_cycles=25)
    assert result["all_verified"] and count == 3
    assert len(m.journal.records("format_errors")) == 2
    assert m.task("fixed")["acceptance"] == m.task("build")["acceptance"]
    assert m.task("fixed")["check"] == m.task("build")["check"]
    assert {n["id"]: n["verdict"] for n in result["nodes"]} == {"build": "FAIL", "fixed": "PASS"}


def test_changed_prompt_version_repairs_old_completed_invalid_calls(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path, initial=False))
    old_prompt = "Old ambiguous prompt"
    m._freeze_learning_trial()
    m.journal.record("roles", "lead:architecture:0", {"role": "lead", "driver": "claude", "model": "claude-opus-5-5"})
    m.journal.reserve("lead:architecture:0", "planner", digest(old_prompt))
    m.journal.complete("lead:architecture:0", Receipt("COMPLETED", output='{"interfaces":{}}').as_dict())
    again = mission(tmp_path, None)
    result = again.run(max_cycles=20)
    assert result["all_verified"] and result["runs"][0]["key"] == "lead:architecture:0"
    assert result["runs"][0]["receipt"]["output"] == '{"interfaces":{}}'
    new_leads = [r for r in result["runs"] if r["role"] == "lead" and r["key"] != "lead:architecture:0"]
    assert len(new_leads) == 1 and new_leads[0]["key"].startswith("lead:architecture:")


@pytest.mark.parametrize("cap", ["max_calls", "max_iterations", "max_tokens", "max_cost_usd", "max_wall_minutes"])
def test_finite_parent_caps_fence_trial_children_before_runner(tmp_path, cap):
    root = tmp_path / "catalog"
    root.mkdir()
    m = mission(tmp_path, make_spec(tmp_path, **{cap: 100}, rsi={"evaluation_root": str(root)}))
    m.journal.record("improvements", "fixture", {"ledger_proposal": {"id": "fixture-not-evaluated"}})
    m.set_trial_runner(lambda **_: pytest.fail("finite parent budget must fence before child construction"))
    m._procedure_trial_boundary("completed")
    result = m.journal.records("trial_results")[0]["data"]
    assert result["status"] == "BLOCKED_PARENT_BUDGET" and result["promoted"] is False
    assert result["enabled_caps"] == [cap] and not m.journal.runs()


def test_trial_runner_default_autowires_once_per_candidate(tmp_path, monkeypatch):
    root = tmp_path / "catalog"
    root.mkdir()
    m = mission(tmp_path, make_spec(tmp_path, rsi={"evaluation_root": str(root)}))
    m.journal.record("improvements", "fixture", {"ledger_proposal": {"id": "fixture-not-evaluated"}})
    calls = []
    def run_trials(origin, candidate_id, evaluation_root):
        calls.append((origin, candidate_id, evaluation_root))
        return {"status": "FIXTURE_NOT_EVALUATED", "promoted": False}
    monkeypatch.setitem(sys.modules, "sisyfus.workers.lead_trials", types.SimpleNamespace(run_trials=run_trials))
    m._procedure_trial_boundary("completed")
    m._procedure_trial_boundary("completed")
    assert calls == [(m, "fixture-not-evaluated", root.resolve())]


def test_registered_trial_children_receive_pause_resume_and_durable_stop(tmp_path):
    parent = mission(tmp_path, make_spec(tmp_path))
    child_root = tmp_path / "child-arm"
    child_root.mkdir()
    child = mission(child_root, make_spec(child_root))
    parent.register_trial_child(child)
    parent.journal.pause(True)
    assert child.journal.paused()
    parent.journal.pause(False)
    assert not child.journal.paused()
    parent.request_stop()
    assert child.stop.is_set() and child.journal.state()["stopped"]
    assert parent.journal.records("trial_children")[0]["data"]["directory"] == str(child.directory)
    parent.unregister_trial_child(child)
    assert not parent._trial_children


def test_completed_parent_calls_lead_for_grounded_procedure_before_trials(tmp_path):
    root = tmp_path / "operator-catalog"
    root.mkdir()
    def claude(request, *_):
        if request.prompt.startswith("Improve"):
            packet = json.loads(request.prompt.split("\n", 1)[1])
            assert "holdout" not in json.dumps(packet)
            raw = {"procedure": "Plan the smallest DAG covering every frozen check; copy exact JSON evidence IDs.",
                   "rationale": "reduce avoidable decomposition/format calls without changing gates",
                   "evidence": packet["evidence_references"]}
            return Receipt("COMPLETED", output=json.dumps(raw), requested_model=request.model)
    m = mission(tmp_path, make_spec(tmp_path, initial=False, rsi={"enabled": True, "evaluation_root": str(root)}), claude=claude)
    calls = []
    def runner(**args):
        calls.append(args)
        assert m.journal.state()["phase"] == "TRIAL_RUNNING"
        assert m.learning.validate_candidate(args["candidate_id"])
        return {"status": "FIXTURE_NOT_EVALUATED", "promoted": False}
    m.set_trial_runner(runner)
    result = m.run(max_cycles=20)
    assert result["all_verified"] and len(calls) == 1
    assert len([r for r in m.drivers["claude"].requests if r.prompt.startswith("Improve")]) == 1
    assert m.journal.records("procedure_proposals")[0]["data"]["status"] == "PROPOSED"
    assert len(m.learning.history()["versions"]) == 2
    assert m.learning.active()["id"] == "procedure_initial"  # No fixture promotion.


def test_disabled_child_rsi_does_not_recursively_propose_or_run_trials(tmp_path):
    root = tmp_path / "catalog"
    root.mkdir()
    m = mission(tmp_path, make_spec(tmp_path, initial=False, rsi={"enabled": False, "evaluation_root": str(root)}))
    m.set_trial_runner(lambda **_: pytest.fail("child RSI is disabled"))
    assert m.run(max_cycles=20)["all_verified"]
    assert not any(r.prompt.startswith("Improve") for r in m.drivers["claude"].requests)
    assert not m.journal.records("trial_requests")


def test_worker_receives_only_its_public_registered_checker(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path, two=True))
    assert m.run(max_cycles=25)["all_verified"]
    for request in m.drivers["codex"].requests:
        packet = json.loads(request.prompt.split("\n", 1)[1])
        name = packet["task"]["check"]
        assert packet["approved_check"] == {"id": name, **m.spec["checks"][name]}
        assert "checks" not in packet and "integration_checks" not in packet
        assert packet["candidate_substitution"]["replace_only_separate_argv_element"] is True
        assert "Do not search controller databases" in request.prompt
        assert "PYTHONDONTWRITEBYTECODE=1" in request.prompt


@pytest.mark.parametrize("field,value", [("id", {}), ("id", []), ("repair_of", {}), ("repair_of", [])])
def test_nonstring_plan_identifiers_are_completed_format_errors(tmp_path, field, value):
    responses = 0
    def claude(request, *_):
        nonlocal responses
        if request.prompt.startswith("You are"):
            responses += 1
            raw = plan([task("build")])
            if responses == 1:
                raw["tasks"][0][field] = value
            return Receipt("COMPLETED", output=json.dumps(raw), requested_model=request.model)
    m = mission(tmp_path, make_spec(tmp_path, initial=False), claude=claude)
    frozen = digest(m.spec["checks"])
    result = m.run(max_cycles=20)
    assert result["all_verified"] and responses == 2
    error = m.journal.records("format_errors")[0]["data"]
    assert "string identifiers" in error["validator_error"]
    assert digest(m.spec["checks"]) == frozen
    assert all(r["receipt"]["status"] == "COMPLETED" for r in result["runs"])


def test_snapshot_reads_child_reservations_once_without_initialization(tmp_path, monkeypatch):
    parent = mission(tmp_path, make_spec(tmp_path))
    root = tmp_path / "trial-arm"
    root.mkdir()
    child = mission(root, make_spec(root))
    parent.journal.reserve("parent", "planner", "fp")
    parent.journal.complete("parent", Receipt("COMPLETED", usage={"total_tokens": 2, "cost_usd": 1}).as_dict())
    for i, amount in enumerate((5, 8)):
        key = "child-" + str(i)
        child.journal.reserve(key, "planner", key)
        child.journal.complete(key, Receipt("COMPLETED", session_id="same-child-session",
                                          usage={"total_tokens": amount, "cost_usd": amount / 4}).as_dict())
    parent.register_trial_child(child)
    parent.journal.record("paired_trial_children", "arm", {"directory": str(child.directory), "arm": "baseline"})
    parent.journal.record("paired_trials", "lab", {"status": "PENDING"})
    child.journal.reserve("working", "planner", "fp")
    before = child.store.verify_event_chain()
    monkeypatch.setattr(LeadMission, "__init__", lambda *_a, **_k: pytest.fail("snapshot must not initialize any child"))
    snapshot = parent.snapshot()
    counters = snapshot["counters"]
    assert counters["parent_calls"] == 1 and counters["trial_child_calls"] == 3 and counters["total_calls"] == 4
    assert snapshot["native_call_reservations"] == 4 and snapshot["parent_native_call_reservations"] == 1
    assert snapshot["phase"] == "TRIAL_RUNNING" and counters["tokens"] is None
    observed = snapshot["procedure_trials"]["children"]
    assert len(observed) == 1 and len(observed[0]["registrations"]) == 2
    assert observed[0]["run_status_counts"] == {"RECEIPTED": 2, "IN_FLIGHT": 1}
    assert observed[0]["unresolved"] == ["working"]
    assert snapshot["procedure_trials"]["paired_trials"] and not snapshot["all_verified"]
    assert child.store.verify_event_chain() == before
    child.journal.complete("working", Receipt("ERROR", session_id="same-child-session",
                          usage={"total_tokens": 12, "cost_usd": 3}).as_dict())
    counters = parent.snapshot()["counters"]
    assert counters["trial_child_tokens"] == 12 and counters["tokens"] == 14
    assert counters["cost_usd"] == 4  # Same-session totals use max, not sum.


@pytest.mark.parametrize("kind", ["missing", "malformed", "missing-table", "bad-receipt"])
def test_child_database_failure_is_explicit_unknown_not_zero(tmp_path, kind):
    parent = mission(tmp_path, make_spec(tmp_path))
    root = tmp_path / "uncertain-arm"
    root.mkdir()
    registered = root
    database = root / "autonomy.sqlite3"
    if kind == "malformed":
        database.write_bytes(b"not a sqlite database")
    elif kind == "missing-table":
        db = sqlite3.connect(database)
        db.execute("CREATE TABLE metadata(key TEXT,value TEXT)")
        db.execute("INSERT INTO metadata VALUES('techlead:state',?)", (json.dumps({"phase": "TRIAL_RUNNING"}),))
        db.commit()
        db.close()
    elif kind == "bad-receipt":
        child = mission(root, make_spec(root))
        registered = child.directory
        child.journal.reserve("broken", "planner", "fp")
        with child.store._transaction() as db:
            db.execute("UPDATE native_worker_runs SET status='RECEIPTED',receipt_json='[]' WHERE key='broken'")
    parent.journal.record("paired_trial_children", "arm", {"directory": str(registered)})
    snapshot = parent.snapshot()
    assert snapshot["phase"] == "TRIAL_FENCED" and not snapshot["all_verified"]
    assert snapshot["counters"]["parent_calls"] == 0
    assert snapshot["counters"]["trial_child_calls"] is None and snapshot["counters"]["total_calls"] is None
    assert snapshot["counters"]["known_total_calls"] == 0
    assert snapshot["procedure_trials"]["children"][0]["error"]
    assert snapshot["procedure_trials"]["read_errors"]
    if kind == "missing":
        assert not database.exists()


def test_durable_trial_phase_settles_nested_handoffs_only_after_terminal(tmp_path):
    parent = mission(tmp_path, make_spec(tmp_path, initial=False))
    assert parent.run(max_cycles=20)["all_verified"]
    parent.journal.record("trial_requests", "core", {"status": "PENDING"})
    parent.begin_trial("core")
    parent.journal.record("paired_trials", "runner", {"status": "PENDING"})
    parent.begin_trial("runner")
    assert parent.journal.state()["phase"] == "TRIAL_RUNNING"
    assert parent.snapshot()["project_verified"] and not parent.snapshot()["all_verified"]
    report = {"status": "NONPROMOTION", "promoted": False}
    with pytest.raises(ValueError, match="persisted"):
        parent.settle_trial("runner", report)
    parent.journal.record("paired_trial_results", "runner", report)
    parent.settle_trial("runner", report)
    assert parent.journal.state()["phase"] == "TRIAL_RUNNING"
    parent.journal.record("trial_results", "core", report)
    parent.settle_trial("core", report)
    assert parent.snapshot()["phase"] == "COMPLETED" and parent.snapshot()["all_verified"]
    before = parent.store.verify_event_chain()
    parent.settle_trial("runner", report)
    parent.settle_trial("core", report)
    assert parent.store.verify_event_chain() == before


@pytest.mark.parametrize("status", ["PENDING", "ERROR", "FENCED", "UNKNOWN"])
def test_unsettled_trial_report_never_restores_completed(tmp_path, status):
    parent = mission(tmp_path, make_spec(tmp_path, initial=False))
    assert parent.run(max_cycles=20)["all_verified"]
    parent.journal.record("paired_trials", "lab", {"status": "PENDING"})
    parent.begin_trial("lab")
    report = {"status": status, "promoted": False}
    parent.journal.record("paired_trial_results", "lab", report)
    parent.settle_trial("lab", report)
    assert parent.journal.state()["phase"] == "TRIAL_FENCED"
    assert parent.snapshot()["phase"] != "COMPLETED" and not parent.snapshot()["all_verified"]


def test_cached_terminal_trial_reconciles_phase_without_replaying_native(tmp_path):
    parent = mission(tmp_path, make_spec(tmp_path, initial=False))
    assert parent.run(max_cycles=20)["all_verified"]
    parent.journal.record("paired_trials", "historical", {"status": "PENDING"})
    report = {"status": "NONPROMOTION", "promoted": False}
    parent.journal.record("paired_trial_results", "historical", report)
    parent.journal.phase("TRIAL_RUNNING")  # Crash after final, before old hook.
    calls = len(parent.journal.runs())
    parent.settle_trial("historical", report)
    assert parent.snapshot()["phase"] == "COMPLETED" and len(parent.journal.runs()) == calls
    assert parent.journal.get("trial_sessions", "historical")["historical_result"]
    parent.begin_trial("next")
    parent.journal.record("trial_results", "next", report)
    parent.request_stop()
    parent.settle_trial("next", report)
    assert parent.journal.state()["phase"] == "STOPPED" and parent.snapshot()["phase"] == "STOPPED"


def _failed_worker(request, *_):
    if request.task_id == "build":
        (Path(request.cwd) / "a.txt").write_text("wrong")
        return Receipt("COMPLETED", requested_model=request.model)


def test_review_fix_model_stop_is_advisory_not_operator_authority(tmp_path):
    def claude(request, *_):
        if request.prompt.startswith("Classify"):
            packet = json.loads(request.prompt.split("\n", 1)[1])
            return Receipt("COMPLETED", output=json.dumps({"classification": "environment", "action": "stop",
                "reasons": ["operator decision proposed"], "evidence": packet["evidence_references"]}))
    m = mission(tmp_path, make_spec(tmp_path), worker=_failed_worker, claude=claude)
    result = m.run(max_cycles=10)
    assert result["phase"] == "NEEDS_OPERATOR" and not result["stopped"]
    assert not m.stop.is_set() and m.journal.state()["stopped"] is False
    assert m.journal.records("diagnoses")[0]["data"]["action"] == "stop"
    again = mission(tmp_path, None, worker=_failed_worker, claude=claude)
    assert again.run(max_cycles=3)["phase"] == "NEEDS_OPERATOR"
    assert not again.journal.state()["stopped"] and not again.drivers["claude"].requests


@pytest.mark.parametrize("decision", ["wait", "stop"])
def test_review_fix_explicit_resume_rediagnoses_saved_wait(tmp_path, decision):
    diagnoses = 0
    def claude(request, *_):
        nonlocal diagnoses
        if request.prompt.startswith("Classify"):
            diagnoses += 1
            packet = json.loads(request.prompt.split("\n", 1)[1])
            raw = {"classification": "environment", "reasons": ["environment repaired after operator resume"],
                   "evidence": packet["evidence_references"], "action": decision if diagnoses == 1 else "repair"}
            if diagnoses > 1:
                raw["plan"] = plan([task("fixed", repair="build")])
            return Receipt("COMPLETED", output=json.dumps(raw))
    m = mission(tmp_path, make_spec(tmp_path), worker=_failed_worker, claude=claude)
    expected = "WAITING_LEAD" if decision == "wait" else "NEEDS_OPERATOR"
    assert m.run(max_cycles=10)["phase"] == expected and diagnoses == 1
    again = mission(tmp_path, None, worker=_failed_worker, claude=claude)
    assert again.run(max_cycles=3)["phase"] == expected and diagnoses == 1
    assert again.request_resume("environment repaired") == 1
    resumed = mission(tmp_path, None, worker=_failed_worker, claude=claude)
    result = resumed.run(max_cycles=15)
    assert result["all_verified"] and diagnoses == 2
    assert result["resume_epoch"] == 1 and len(result["diagnoses"]) == 2
    assert len({r["key"] for r in result["runs"] if r["role"] == "lead"}) == 2
    assert {n["id"]: n["attempts"] for n in result["nodes"]} == {"build": 1, "fixed": 1}
    resumed.request_stop()
    with pytest.raises(DispatchBlocked, match="stopped"):
        resumed.request_resume()


@pytest.mark.parametrize("role", ["lead", "worker", "reviewer"])
def test_review_fix_pause_reservation_race_retains_single_attempt(tmp_path, role):
    m = mission(tmp_path, make_spec(tmp_path, initial=role != "lead"))
    original = m.journal.before_reserve
    hit = threading.Event()
    outcome = {}
    def before_reserve():
        original()
        latest = m.journal.records("roles")[-1]["data"]
        if latest["role"] == role and not hit.is_set():
            m.journal.pause(True)
            hit.set()
    m.journal.before_reserve = before_reserve
    def run():
        try:
            outcome["result"] = m.run(max_cycles=20)
        except Exception as exc:
            outcome["error"] = exc
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        assert hit.wait(5), outcome
        # Hold the race open long enough to expose an ERROR on the old path.
        time.sleep(.08)
        m.journal.pause(False)
        thread.join(timeout=10)
        assert not thread.is_alive() and "error" not in outcome, outcome
        result = outcome["result"]
        assert result["all_verified"] and result["phase"] == "COMPLETED", result
        assert result["nodes"][0]["attempts"] == 1 and len(result["nodes"]) == 1
        assert not result["diagnoses"]
        with m.store._transaction(immediate=False) as db:
            assert all(e[0] == "PASS" for e in db.execute("SELECT verdict FROM evidence"))
        states = [e["data"]["state"]["phase"] for e in m.journal.events(0, 1000) if "state" in e["data"]]
        assert "BUDGET_EXHAUSTED" not in states and m.store.verify_event_chain()["valid"]
    finally:
        if thread.is_alive():
            m.request_stop()
            thread.join(timeout=5)


def test_review_fix_invalid_optional_improvement_preserves_completed(tmp_path):
    root = tmp_path / "catalog"
    root.mkdir()
    def claude(request, *_):
        if request.prompt.startswith("Improve"):
            return Receipt("COMPLETED", output='{"procedure":"bad incomplete response"}')
    m = mission(tmp_path, make_spec(tmp_path, initial=False, rsi={"evaluation_root": str(root)}), claude=claude)
    result = m.run(max_cycles=20)
    assert result["phase"] == "COMPLETED" and result["project_verified"] and result["all_verified"]
    assert m.journal.records("improvement_errors")
    assert len([r for r in result["runs"] if (r["role_metadata"] or {}).get("purpose") == "improvement"]) == 2
    assert not result["procedure_trials"]["requests"]
    again = mission(tmp_path, None, claude=claude)
    assert again.run(max_cycles=3)["phase"] == "COMPLETED"
    assert not again.drivers["claude"].requests


def test_review_fix_unknown_optional_improvement_remains_fenced(tmp_path):
    root = tmp_path / "catalog"
    root.mkdir()
    def claude(request, *_):
        if request.prompt.startswith("Improve"):
            return Receipt("UNKNOWN", error="unsettled optional transport")
    m = mission(tmp_path, make_spec(tmp_path, initial=False, rsi={"evaluation_root": str(root)}), claude=claude)
    result = m.run(max_cycles=20)
    assert result["phase"] == "UNKNOWN" and result["unresolved"] and not result["all_verified"]
    assert result["integration"]["current"] and not result["procedure_trials"]["requests"]
    again = mission(tmp_path, None, claude=claude)
    with pytest.raises(DispatchBlocked, match="UNKNOWN|unknown"):
        again.request_resume()
    assert again.run(max_cycles=3)["phase"] == "UNKNOWN" and not again.drivers["claude"].requests


def test_review_fix_disabled_rsi_candidate_is_format_repaired_before_plan_admission(tmp_path):
    answers = 0
    def claude(request, *_):
        nonlocal answers
        if request.prompt.startswith("Classify"):
            answers += 1
            packet = json.loads(request.prompt.split("\n", 1)[1])
            raw = {"classification": "implementation", "action": "repair", "reasons": ["fix frozen check"],
                   "evidence": packet["evidence_references"], "plan": plan([task("fixed", repair="build")])}
            if answers == 1:
                raw["procedure_candidate"] = "disabled optional policy"
            return Receipt("COMPLETED", output=json.dumps(raw))
    m = mission(tmp_path, make_spec(tmp_path, rsi={"enabled": False}), worker=_failed_worker, claude=claude)
    frozen = digest(m.spec["checks"])
    result = m.run(max_cycles=20)
    assert result["all_verified"] and answers == 2 and result["revision"] == 2
    assert "omit procedure_candidate" in next(r.prompt for r in m.drivers["claude"].requests if r.prompt.startswith("Classify"))
    assert len(m.journal.records("format_errors")) == 1 and not result["improvements"]
    assert len(result["rsi"]["versions"]) == 1 and digest(m.spec["checks"]) == frozen
