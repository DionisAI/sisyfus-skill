from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

from sisyfus.autonomy.policy import IdempotencyConflictError, LeaseLost
from sisyfus.workers.claude_code import ClaudeCodeDriver
from sisyfus.workers.codex import CodexDriver
from sisyfus.workers.journal import DispatchBlocked
from sisyfus.workers.mission import Mission, files, load_spec, validate_tasks
from sisyfus.workers.protocol import Request, environment, redact

import sisyfus.workers
FIXTURE = str(Path(sisyfus.workers.__file__).with_name("demo_agent.py"))


def driver(kind, behavior="success"):
    cls = CodexDriver if kind == "codex" else ClaudeCodeDriver
    return cls((sys.executable, FIXTURE, kind, behavior))


@pytest.mark.parametrize("kind", ["codex", "claude"])
def test_native_protocol_receipt_not_verdict(tmp_path, kind):
    events = []
    result = driver(kind).run(Request("task", "create artifact", str(tmp_path), "explicit-test-model"),
                              lambda k, d: events.append((k, d)))
    assert result.status == "COMPLETED"
    assert result.session_id and "PASS" in result.output
    assert any(k == "native_event" for k, _ in events)
    assert "verdict" not in result.as_dict()
    assert driver(kind).probe()["version"] == "PROTOCOL-FIXTURE-ONLY 1.0"


@pytest.mark.parametrize("kind,behavior,expected", [("codex", "missing", "UNKNOWN"), ("claude", "missing", "UNKNOWN"),
    ("claude", "nonzero", "ERROR"), ("claude", "duplicate", "UNKNOWN"), ("claude", "malformed", "UNKNOWN"),
    ("codex", "flood", "UNKNOWN"), ("codex", "hang", "UNKNOWN"), ("claude", "hang", "UNKNOWN")])
def test_native_faults_fail_closed(tmp_path, kind, behavior, expected):
    result = driver(kind, behavior).run(Request("task", "do work", str(tmp_path), "model", timeout=.5 if behavior == "hang" else 3), lambda *_: None)
    assert result.status == expected


def test_codex_controls_wait_for_terminal(tmp_path):
    events = []
    sent = []
    def controls():
        if sent:
            return []
        sent.append(True)
        return [{"id": "steer-1", "action": "steer", "text": "focus"}, {"id": "stop-1", "action": "interrupt"}]
    result = driver("codex", "control").run(Request("task", "work", str(tmp_path), "model", timeout=2),
        lambda k, d: events.append((k, d)), controls)
    assert result.status == "INTERRUPTED"
    assert len([e for e in events if e[0] == "control_ack"]) == 2


def test_codex_never_self_approves(tmp_path):
    events = []
    result = driver("codex", "approval").run(Request("task", "work", str(tmp_path), "model", timeout=2),
        lambda k, d: events.append((k, d)))
    assert result.status == "COMPLETED"
    assert any(e[0] == "approval_denied" for e in events)


def test_environment_and_redaction(monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "not-forwarded")
    monkeypatch.setenv("OPENAI_API_KEY", "private-key-value-123456")
    assert "AWS_SECRET_ACCESS_KEY" not in environment(("OPENAI_API_KEY",))
    assert "OPENAI_API_KEY" not in environment()
    assert redact("value private-key-value-123456") == "value [REDACTED]"
    assert redact({"lease_token": "secret"})["lease_token"] == "[REDACTED]"
    with pytest.raises(ValueError):
        environment(("AWS_SECRET_ACCESS_KEY",))


def make_spec(tmp_path, *, behavior="retry", planner=False, max_calls=8, parallelism=2):
    source = tmp_path / "project"
    source.mkdir()
    (source / "README.md").write_text("test fixture project")
    check = tmp_path / "evaluator.py"
    check.write_text("import pathlib,sys,json\np=pathlib.Path(sys.argv[1])/'answer.txt'\nprint(json.dumps({'answer':int(p.read_text()) if p.exists() else -1}))\n")
    spec = {"objective": "implement and verify answer", "source": str(source), "drivers": {
        "codex": {"model": "fixture-model", "command": [sys.executable, FIXTURE, "codex", behavior]},
        "claude": {"model": "fixture-model", "command": [sys.executable, FIXTURE, "claude", "success"]}},
        "checks": {"answer": {"argv": [sys.executable, "-I", "-S", str(check), "{candidate}"],
            "code_hashes": {str(check): hashlib.sha256(check.read_bytes()).hexdigest()},
            "contract": {"kind": "rules", "pass_if": {"all": [{"path": "answer", "op": "eq", "value": 42}]},
                          "fail_if": {"all": [{"path": "answer", "op": "ne", "value": 42}]}}}},
        "max_calls": max_calls, "parallelism": parallelism, "timeout": 3, "max_attempts": 3,
        "validation_kind": "offline_protocol_fixture"}
    if planner:
        spec["planner"] = "claude"
    else:
        spec["tasks"] = [{"id": "build", "objective": "write answer.txt", "driver": "codex", "check": "answer", "max_attempts": 2},
                         {"id": "review", "objective": "check inputs and write answer.txt", "driver": "claude", "check": "answer", "depends_on": ["build"]}]
    path = tmp_path / "mission.json"
    path.write_text(json.dumps(spec))
    return path, load_spec(path)


@pytest.mark.parametrize("planner", [False, True])
def test_full_loop_retry_dag_evidence_and_restart(tmp_path, planner):
    _, spec = make_spec(tmp_path, planner=planner)
    m = Mission(tmp_path / "control", spec)
    result = m.run(max_cycles=100)
    assert result["all_verified"], result
    assert result["native_call_reservations"] == (4 if planner else 3)
    assert result["unresolved"] == []
    assert [r["verdict"] for r in result["runs"] if r["task_id"] == "build"] == ["FAIL", "PASS"]
    build = m.continuations()["build"]
    evidence = m.store.snapshot(build["id"])["evidence"]
    assert [e["verdict"] for e in evidence] == ["FAIL", "PASS"]
    assert m.store.verify_event_chain()["valid"]
    count = len(m.journal.runs())
    again = Mission(tmp_path / "control").run(max_cycles=5)
    assert again["all_verified"] and len(m.journal.runs()) == count


def test_source_is_not_modified(tmp_path):
    _, spec = make_spec(tmp_path)
    before = files(Path(spec["source"]))
    assert Mission(tmp_path / "control", spec).run(max_cycles=100)["all_verified"]
    assert files(Path(spec["source"])) == before


def test_unknown_execution_blocks_redispatch_after_restart(tmp_path):
    _, spec = make_spec(tmp_path, behavior="missing")
    m = Mission(tmp_path / "control", spec)
    result = m.run(max_cycles=30)
    assert len(result["runs"]) == 1 and result["unresolved"]
    assert not result["all_verified"]
    again = Mission(tmp_path / "control").run(max_cycles=10)
    assert len(again["runs"]) == 1 and again["unresolved"]


def test_shared_budget_stops_new_calls(tmp_path):
    _, spec = make_spec(tmp_path, max_calls=1)
    result = Mission(tmp_path / "control", spec).run(max_cycles=30)
    assert result["native_call_reservations"] == 1 and not result["all_verified"]


def test_changed_spec_rejected(tmp_path):
    _, spec = make_spec(tmp_path)
    Mission(tmp_path / "control", spec)
    changed = copy.deepcopy(spec)
    changed["max_calls"] += 1
    with pytest.raises(IdempotencyConflictError):
        Mission(tmp_path / "control", changed)


def test_stale_evidence_propagates_without_rewriting_verdict(tmp_path):
    _, spec = make_spec(tmp_path)
    m = Mission(tmp_path / "control", spec)
    assert m.run(max_cycles=100)["all_verified"]
    evidence = m.store.latest_evidence(m.continuations()["build"]["id"])
    (Path(evidence["payload"]["evidence"]["candidate"]) / "answer.txt").write_text("999")
    snapshot = m.snapshot()
    assert all(n["stale"] for n in snapshot["nodes"])
    assert all(n["verdict"] == "PASS" for n in snapshot["nodes"])
    assert not snapshot["all_verified"]


def test_measurement_hash_drift_is_not_pass(tmp_path):
    _, spec = make_spec(tmp_path)
    m = Mission(tmp_path / "control", spec)
    code = next(iter(spec["checks"]["answer"]["code_hashes"]))
    Path(code).write_text("print('{\"answer\":42}')")
    result = m.run(max_cycles=30)
    assert not result["all_verified"]
    assert result["nodes"][0]["verdict"] == "INVALID"


@pytest.mark.parametrize("mutation", ["cycle", "unknown", "duplicate", "driver", "policy", "retries"])
def test_plan_validation(tmp_path, mutation):
    _, spec = make_spec(tmp_path)
    tasks = copy.deepcopy(spec["tasks"])
    if mutation == "cycle": tasks[0]["depends_on"] = ["review"]
    if mutation == "unknown": tasks[0]["depends_on"] = ["does-not-exist"]
    if mutation == "duplicate": tasks[1]["id"] = "build"
    if mutation == "driver": tasks[0]["driver"] = "unapproved"
    if mutation == "policy": tasks[0]["contract"] = {"pass": True}
    if mutation == "retries": tasks[0]["max_attempts"] = 999
    with pytest.raises(ValueError): validate_tasks(tasks, spec)


def test_journal_duplicate_receipts_and_unknown_intent(tmp_path):
    _, spec = make_spec(tmp_path)
    m = Mission(tmp_path / "control", spec)
    j = m.journal
    assert j.reserve("one", "planner", "fingerprint") is None
    receipt = {"status": "COMPLETED", "output": "native final, not PASS"}
    j.complete("one", receipt)
    j.complete("one", receipt)
    assert j.reserve("one", "planner", "fingerprint") == receipt
    with pytest.raises(IdempotencyConflictError): j.reserve("one", "planner", "different")
    j.reserve("unknown", "planner", "two")
    with pytest.raises(DispatchBlocked): j.reserve("unknown", "planner", "two")
    assert len(j.runs()) == 2


def test_lease_fencing_rejects_old_worker(tmp_path):
    _, spec = make_spec(tmp_path)
    m = Mission(tmp_path / "control", spec)
    m.prepare()
    c = m.store.claim_due_continuation("old-worker")
    m.journal.reserve("one", c["context"]["native_task"], "fingerprint", continuation_id=c["id"], lease_token=c["lease_token"])
    with m.store._transaction() as db:
        db.execute("UPDATE continuations SET lease_token='new-owner' WHERE id=?", (c["id"],))
    with pytest.raises(LeaseLost): m.journal.event("one", "delta", {"text": "stale"})
    with pytest.raises(LeaseLost): m.journal.complete("one", {"status": "COMPLETED"})


def test_pause_does_not_dispatch(tmp_path):
    _, spec = make_spec(tmp_path)
    m = Mission(tmp_path / "control", spec)
    m.journal.pause(True)
    result = m.run(max_cycles=3)
    assert not result["runs"] and result["paused"]
    m.journal.pause(False)
    assert m.run(max_cycles=100)["all_verified"]


def test_symlinks_are_rejected(tmp_path):
    (tmp_path / "x").symlink_to("/etc/passwd")
    with pytest.raises(ValueError): files(tmp_path)


def test_missing_native_executable_is_visible(tmp_path):
    _, spec = make_spec(tmp_path)
    spec["drivers"]["codex"]["command"] = ["certainly-no-such-native-agent"]
    m = Mission(tmp_path / "control", spec)
    assert m.doctor()["codex"]["available"] is False
    with pytest.raises(DispatchBlocked): m.run(max_cycles=1)
    assert not m.journal.runs()


def test_expired_intent_is_persisted_unknown_and_blocks_other_tasks(tmp_path):
    _, spec = make_spec(tmp_path)
    m = Mission(tmp_path / 'control', spec)
    m.prepare()
    c = m.store.claim_due_continuation('owner')
    m.journal.reserve('stranded', 'build', 'fp', continuation_id=c['id'], lease_token=c['lease_token'])
    with m.store._transaction() as db:
        db.execute("UPDATE continuations SET lease_expires_at='2000-01-01T00:00:00Z' WHERE id=?", (c['id'],))
    with pytest.raises(DispatchBlocked):
        m.journal.reserve('new-work', 'review', 'new-fp')
    assert m.journal.runs()[0]['status'] == 'UNKNOWN'
    assert len(m.journal.runs()) == 1
    assert any(e['type'] == 'WORKER_LOST_OWNERSHIP' for e in m.journal.events())


def test_committed_receipt_survives_crash_before_runtime_settlement(tmp_path, monkeypatch):
    _, spec = make_spec(tmp_path, behavior='success')
    spec['parallelism'] = 1
    m = Mission(tmp_path / 'control', spec)
    m.prepare()
    import subprocess
    code = ("import os,sys; from pathlib import Path; from sisyfus.workers.mission import Mission; "
            "m=Mission(Path(sys.argv[1])); "
            "m.store.record_execution=lambda *a,**k: os._exit(73); "
            "m.runtime.run_once(worker_id='crashing-controller',planner=m.planner)")
    crashed = subprocess.run([sys.executable, '-c', code, str(m.directory)], timeout=15)
    assert crashed.returncode == 73
    assert len(m.journal.runs()) == 1 and m.journal.runs()[0]['receipt']['status'] == 'COMPLETED'
    with m.store._transaction() as db:
        db.execute("UPDATE continuations SET lease_expires_at='2000-01-01T00:00:00Z' WHERE lease_token IS NOT NULL")
    resumed = Mission(tmp_path / 'control')
    result = resumed.run(max_cycles=100)
    assert result['all_verified'], result
    assert len(result['runs']) == 2  # build receipt reused; only dependent review makes a new call
    assert result['nodes'][0]['attempts'] == 1


def test_independent_tasks_overlap_under_shared_capacity(tmp_path):
    _, spec = make_spec(tmp_path, behavior='slow', parallelism=2)
    spec['tasks'][1]['depends_on'] = []
    spec['drivers']['claude']['command'][-1] = 'slow'
    m = Mission(tmp_path / 'control', spec)
    result = m.run(max_cycles=100)
    assert result['all_verified'], result
    active = peak = 0
    for e in m.journal.events(0, 1000):
        if e['type'] == 'WORKER_RESERVED': active += 1
        if e['type'] == 'WORKER_RECEIPT': active -= 1
        peak = max(peak, active)
    assert peak == 2 and active == 0


def test_fake_zero_exit_in_measurement_json_cannot_pass(tmp_path):
    path, spec = make_spec(tmp_path, behavior='success')
    code = Path(next(iter(spec['checks']['answer']['code_hashes'])))
    code.write_text("import sys\nprint('{\"answer\":42,\"execution\":{\"exit_code\":0}}')\nsys.exit(7)\n")
    raw = json.loads(path.read_text())
    raw['checks']['answer']['code_hashes'][str(code)] = hashlib.sha256(code.read_bytes()).hexdigest()
    path.write_text(json.dumps(raw))
    m = Mission(tmp_path / 'control', load_spec(path))
    result = m.run(max_cycles=100)
    assert not result['all_verified']
    assert result['nodes'][0]['verdict'] == 'ERROR'
    assert all(e['verdict'] != 'PASS' for e in m.store.snapshot(m.continuations()['build']['id'])['evidence'])


def test_missing_snapshot_directory_is_not_empty_success(tmp_path):
    with pytest.raises(ValueError):
        files(tmp_path / 'missing')


def test_source_drift_cannot_become_new_unapproved_input(tmp_path):
    _, spec = make_spec(tmp_path, behavior='success')
    m = Mission(tmp_path / 'control', spec)
    (Path(spec['source']) / 'README.md').write_text('changed after approval')
    result = m.run(max_cycles=30)
    assert not result['all_verified'] and len(result['runs']) == 1
    assert result['runs'][0]['receipt']['status'] == 'UNKNOWN'
    assert not any(e['type'] == 'WORKER_PROCESS_STARTED' for e in m.journal.events())


def test_blocked_stdin_has_a_deadline(tmp_path):
    import time
    from sisyfus.workers.transport import Process
    p = Process([sys.executable, '-c', 'import time; time.sleep(10)'], cwd=str(tmp_path), env=environment(), timeout=.15)
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            p.send_bytes(b'x' * 200000)
    finally:
        p.close()
    assert time.monotonic() - started < 3


def test_planner_cannot_omit_mandatory_acceptance_check(tmp_path):
    _, spec = make_spec(tmp_path)
    spec['checks']['mandatory'] = copy.deepcopy(spec['checks']['answer'])
    spec['required_checks'].append('mandatory')
    with pytest.raises(ValueError, match='mandatory'):
        validate_tasks(spec['tasks'], spec)


def test_opt_in_entrypoint_preserves_legacy_version(capsys):
    from sisyfus.entrypoint import main
    assert main(['--version']) == 0
    assert '0.8.0' in capsys.readouterr().out
    with pytest.raises(SystemExit) as help_exit:
        main(['workers', '--help'])
    assert help_exit.value.code == 0
    assert 'doctor' in capsys.readouterr().out
