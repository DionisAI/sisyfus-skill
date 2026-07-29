from pathlib import Path
import json
import threading
import urllib.request
from datetime import datetime, timedelta

from sisyfus.research_v2.engine import ResearchEngine

# Loopback requests must never go through a system/user proxy.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def base_spec(*, repetition=False):
    contract = {
        "id": "verify-c1",
        "target_claim_id": "c1",
        "pass_if": {"all": [{"path": "metrics.score", "op": ">=", "value": 0.7}]},
        "fail_if": {"all": [{"path": "metrics.score", "op": "<", "value": 0.3}]},
    }
    if repetition:
        contract["repetition"] = {"min_passes": 2, "min_independent_contexts": 2}
    return {
        "id": "engine-test",
        "topic": "Engine test",
        "claims": [{"id": "c1", "statement": "Candidate works"}],
        "verification_contracts": [contract],
        "budget": {"max_attempts": 10, "max_cost_units": 10},
    }


def experiment(exp_id, *, context="a", action=None, from_state_id=None):
    value = {
        "id": exp_id,
        "title": exp_id,
        "target_claim_ids": ["c1"],
        "contract_id": "verify-c1",
        "context_id": context,
        "action": action or {"kind": "external"},
        "expected_outcomes": {
            "pass": "supports",
            "fail": "refutes",
            "inconclusive": "uncertain",
            "invalid": "bad measurement",
        },
        "cost": {"units": 1},
    }
    if from_state_id:
        value["from_state_id"] = from_state_id
    return value


def settle(engine, exp_id, score):
    attempt = engine.begin_attempt(exp_id)
    return engine.settle_attempt(attempt["id"], {"metrics": {"score": score}})


def test_engine_pass_and_deterministic_replay(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, base_spec())
    result = engine.propose_experiment(experiment("e1"))
    assert result["admission"]["accepted"]
    settled = settle(engine, "e1", 0.8)
    assert settled["verdict"]["status"] == "PASS"
    snapshot = settled["snapshot"]
    assert snapshot["claims"]["c1"]["status"] == "SUPPORTED"
    assert snapshot["run_status"] == "SOLVED"
    assert engine.verify_replay()["deterministic"]
    assert engine.workspace.report_path.exists()
    report = engine.workspace.report_path.read_text(encoding="utf-8")
    assert "Sisyfus Arena" in report
    assert "replaySlider" in report


def test_error_and_invalid_do_not_refute_claim_and_are_retried(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, base_spec())
    engine.propose_experiment(experiment("e1"))
    attempt = engine.begin_attempt("e1")
    result = engine.settle_attempt(attempt["id"], {"execution": {"error": "network"}})
    assert result["verdict"]["status"] == "ERROR"
    snapshot = result["snapshot"]
    assert snapshot["claims"]["c1"]["status"] == "OPEN"
    assert snapshot["experiments"]["e1"]["status"] == "ADMITTED"
    attempt = engine.begin_attempt("e1")
    result = engine.settle_attempt(attempt["id"], {"execution": {}, "metrics": {}})
    assert result["verdict"]["status"] == "INCONCLUSIVE"
    assert result["snapshot"]["claims"]["c1"]["status"] == "INCONCLUSIVE"


def test_repetition_gate_requires_independent_contexts(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, base_spec(repetition=True))
    engine.propose_experiment(experiment("e1", context="a"))
    first = settle(engine, "e1", 0.8)
    assert first["verdict"]["status"] == "PASS"
    assert first["claim_effects"][0]["provisional"] is True
    assert first["snapshot"]["claims"]["c1"]["status"] == "INCONCLUSIVE"
    engine.propose_experiment(experiment("e2", context="b"))
    second = settle(engine, "e2", 0.9)
    assert second["claim_effects"][0]["status"] == "SUPPORTED"
    assert second["snapshot"]["run_status"] == "SOLVED"


def test_missing_contract_and_duplicate_are_backlogged(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, base_spec())
    no_contract = experiment("no-v")
    no_contract["contract_id"] = None
    result = engine.propose_experiment(no_contract)
    assert result["admission"]["reason"] == "missing_verification_contract"
    assert engine.snapshot()["experiments"]["no-v"]["status"] == "BACKLOG"
    engine.propose_experiment(experiment("e1", context="same"))
    duplicate = engine.propose_experiment(experiment("e2", context="same"))
    assert duplicate["admission"]["reason"] == "duplicate_experiment"


def test_live_observatory_serves_fresh_snapshot(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, base_spec())
    engine.propose_experiment(experiment("e1"))
    settle(engine, "e1", 0.8)
    server, url = engine.serve_report(host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        page = _opener.open(url, timeout=5).read().decode("utf-8")
        snapshot_url = url.rsplit("/", 1)[0] + "/snapshot.json"
        payload = json.loads(_opener.open(snapshot_url, timeout=5).read())
        assert "Sisyfus Research Observatory" in page
        assert payload["snapshot"]["run_status"] == "SOLVED"
        assert payload["snapshot"]["snapshot_hash"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)



def test_admission_requires_supported_dependencies_and_allowed_action_family(tmp_path: Path):
    spec = {
        "id": "admission-gates",
        "topic": "Admission gates",
        "claims": [
            {"id": "a", "statement": "Foundation"},
            {"id": "b", "statement": "Dependent", "depends_on": ["a"]},
        ],
        "action_space": ["experiment"],
        "verification_contracts": [
            {"id": "va", "target_claim_id": "a", "pass_if": [{"path": "metrics.ok", "op": "==", "value": True}], "fail_if": [{"path": "metrics.ok", "op": "==", "value": False}]},
            {"id": "vb", "target_claim_id": "b", "pass_if": [{"path": "metrics.ok", "op": "==", "value": True}], "fail_if": [{"path": "metrics.ok", "op": "==", "value": False}]},
        ],
    }
    engine = ResearchEngine.create(tmp_path, spec)
    blocked = engine.propose_experiment({
        "id": "b-too-early", "title": "too early", "target_claim_ids": ["b"], "contract_id": "vb",
        "action_family": "experiment", "action": {"kind": "external"},
        "expected_outcomes": {"pass": "p", "fail": "f", "inconclusive": "i", "invalid": "x"},
    })
    assert blocked["admission"]["reason"] == "claim_dependencies_not_supported"
    disallowed = engine.propose_experiment({
        "id": "a-search", "title": "search", "target_claim_ids": ["a"], "contract_id": "va",
        "action_family": "search", "action": {"kind": "external"},
        "expected_outcomes": {"pass": "p", "fail": "f", "inconclusive": "i", "invalid": "x"},
    })
    assert disallowed["admission"]["reason"] == "action_family_not_allowed"


def test_locked_task_file_cannot_be_mutated(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, base_spec())
    task = engine.workspace.read_task()
    task["topic"] = "tampered"
    engine.workspace.task_path.write_text(json.dumps(task), encoding="utf-8")
    try:
        engine.snapshot()
    except ValueError as exc:
        assert "locked TaskSpec hash mismatch" in str(exc)
    else:
        raise AssertionError("mutated locked task should be rejected")



def test_live_wall_budget_preflight_finalizes_before_new_attempt(tmp_path: Path):
    spec = base_spec()
    spec["budget"]["max_wall_minutes"] = 1
    engine = ResearchEngine.create(tmp_path, spec)
    created = datetime.fromisoformat(engine.snapshot()["created_at"].replace("Z", "+00:00"))
    future = (created + timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    snapshot = engine.refresh_wall_budget(now=future)
    assert snapshot["run_status"] == "BUDGET_EXHAUSTED"
    assert snapshot["last_event_type"] == "RUN_FINALIZED"
    try:
        engine.propose_experiment(experiment("late"))
    except RuntimeError as exc:
        assert "BUDGET_EXHAUSTED" in str(exc)
    else:
        raise AssertionError("late experiment should not be admitted")



def test_inflight_reservations_cannot_oversubscribe_attempt_budget(tmp_path: Path):
    spec = base_spec()
    spec["budget"] = {"max_attempts": 1, "max_cost_units": 5}
    engine = ResearchEngine.create(tmp_path, spec)
    engine.propose_experiment(experiment("e1", context="one"))
    engine.propose_experiment(experiment("e2", context="two"))
    first = engine.begin_attempt("e1")
    snapshot = engine.snapshot()
    assert snapshot["budget"]["attempts_in_flight"] == 1
    assert snapshot["budget"]["attempts_remaining"] == 0
    try:
        engine.begin_attempt("e2")
    except RuntimeError as exc:
        assert "fully reserved" in str(exc)
    else:
        raise AssertionError("second reservation should exceed the attempt budget")
    engine.settle_attempt(first["id"], {"execution": {"error": "temporary"}})
    assert engine.snapshot()["budget"]["attempts_remaining"] == 1
    engine.begin_attempt("e2")


def test_experiment_estimate_cannot_exceed_cost_budget(tmp_path: Path):
    spec = base_spec()
    spec["budget"] = {"max_attempts": 5, "max_cost_units": 1}
    engine = ResearchEngine.create(tmp_path, spec)
    expensive = experiment("expensive")
    expensive["cost"] = {"attempts": 1, "units": 2}
    result = engine.propose_experiment(expensive)
    assert result["admission"]["reason"] == "budget_exceeded_by_experiment"



def test_hidden_contract_cannot_be_downgraded_to_normal_visibility(tmp_path: Path):
    spec = base_spec()
    spec["verification_contracts"][0]["visibility"] = "host_only"
    engine = ResearchEngine.create(tmp_path, spec)
    item = experiment("hidden")
    item["visibility"] = "normal"
    result = engine.propose_experiment(item)
    assert result["admission"]["reason"] == "hidden_visibility_downgrade"



def test_planner_context_redacts_host_only_event_details(tmp_path: Path):
    spec = base_spec()
    spec["verification_contracts"][0]["visibility"] = "host_only"
    engine = ResearchEngine.create(tmp_path, spec)
    item = experiment("hidden", context="held-out")
    item["mode"] = "hidden_eval"
    item["visibility"] = "host_only"
    engine.propose_experiment(item)
    attempt = engine.begin_attempt("hidden")
    engine.settle_attempt(attempt["id"], {"summary": "secret case", "metrics": {"score": 0.8}})
    context = engine.planner_context()
    hidden_rows = [row for row in context["recent_events"] if row.get("visibility") == "host_only"]
    assert hidden_rows
    assert all("data" not in row for row in hidden_rows)
    assert all("secret case" not in json.dumps(row) for row in hidden_rows)
