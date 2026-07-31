from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sisyfus.cli import main
from sisyfus.research_v2.engine import ResearchEngine

FUTURE = "2030-01-01T00:00:00Z"
BEFORE_FUTURE = "2029-12-31T23:00:00Z"


def exp(exp_id, claim, contract, context, wait=None):
    item = {
        "id": exp_id,
        "title": exp_id,
        "target_claim_ids": [claim],
        "contract_id": contract,
        "context_id": context,
        "action": {"kind": "external"},
        "expected_outcomes": {"pass": "p", "fail": "f", "inconclusive": "i", "invalid": "x"},
        "cost": {"units": 1},
    }
    if wait:
        item["wait"] = wait
    return item


def settle(engine, exp_id, ok):
    attempt = engine.begin_attempt(exp_id)
    return engine.settle_attempt(attempt["id"], {"metrics": {"ok": ok}})


def spec():
    return {
        "id": "wait-test",
        "topic": "Wait conditions",
        "claims": [
            {"id": "a", "statement": "Claim A holds", "weight": 1},
            {"id": "b", "statement": "Claim B holds", "weight": 1},
        ],
        "verification_contracts": [
            {"id": "va", "target_claim_id": "a", "pass_if": [{"path": "metrics.ok", "op": "==", "value": True}], "fail_if": [{"path": "metrics.ok", "op": "==", "value": False}]},
            {"id": "vb", "target_claim_id": "b", "pass_if": [{"path": "metrics.ok", "op": "==", "value": True}], "fail_if": [{"path": "metrics.ok", "op": "==", "value": False}]},
        ],
        # Wall budget must cover the whole calendar span a waiting run may live for.
        "budget": {"max_attempts": 10, "max_cost_units": 10, "max_wall_minutes": 100_000_000},
    }


def test_time_wait_blocks_attempt_until_wake(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, spec())
    engine.propose_experiment(exp("w1", "a", "va", "c1", wait={"kind": "time", "not_before": FUTURE}))
    snapshot = engine.snapshot()
    assert snapshot["experiments"]["w1"]["status"] == "WAITING"
    assert snapshot["frontier"] == []
    assert snapshot["next_wake_at"] == FUTURE
    assert snapshot["terminal_assessment"] == "WAITING"

    with pytest.raises(RuntimeError, match="waiting"):
        engine.begin_attempt("w1")

    snapshot = engine.refresh_waits(now=BEFORE_FUTURE)
    assert snapshot["experiments"]["w1"]["status"] == "WAITING"

    snapshot = engine.refresh_waits(now=FUTURE)
    assert snapshot["experiments"]["w1"]["status"] == "ADMITTED"
    assert [item["id"] for item in snapshot["frontier"]] == ["w1"]
    assert snapshot["next_wake_at"] is None
    assert snapshot["experiments"]["w1"]["wait"]["status"] == "FIRED"

    result = settle(engine, "w1", True)
    assert result["verdict"]["status"] == "PASS"
    assert engine.verify_replay()["deterministic"] is True


def test_auto_finalize_refuses_while_waiting(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, spec())
    engine.propose_experiment(exp("w1", "a", "va", "c1", wait={"kind": "time", "not_before": FUTURE}))
    with pytest.raises(RuntimeError, match="not terminal"):
        engine.finalize(status="auto")


def test_relative_after_wait_resolves_from_evidence(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, spec())
    engine.propose_experiment(exp("e1", "a", "va", "c1"))
    settled = settle(engine, "e1", True)
    evidence_id = settled["evidence"]["id"]
    engine.propose_experiment(
        exp("e2", "a", "va", "c2", wait={"kind": "time", "after": {"evidence_id": evidence_id, "minutes": 60}})
    )
    snapshot = engine.snapshot()
    wait = snapshot["experiments"]["e2"]["wait"]
    created = datetime.fromisoformat(str(snapshot["evidence"][evidence_id]["created_at"]).replace("Z", "+00:00"))
    expected = (created + timedelta(minutes=60)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    assert wait["not_before_ts"] == expected

    with pytest.raises(ValueError, match="unknown evidence"):
        engine.propose_experiment(
            exp("e3", "a", "va", "c3", wait={"kind": "time", "after": {"evidence_id": "evidence-nope", "minutes": 5}})
        )


def test_evidence_wait_satisfied_by_later_verdict(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, spec())
    engine.propose_experiment(
        exp("wb", "b", "vb", "cb", wait={"kind": "evidence", "until_evidence": {"claim_id": "a", "verdict": "PASS"}})
    )
    assert engine.snapshot()["experiments"]["wb"]["status"] == "WAITING"

    engine.propose_experiment(exp("a-fail", "a", "va", "c1"))
    settle(engine, "a-fail", False)
    assert engine.snapshot()["experiments"]["wb"]["status"] == "WAITING"

    engine.propose_experiment(exp("a-pass", "a", "va", "c2"))
    passed = settle(engine, "a-pass", True)
    snapshot = engine.snapshot()
    assert snapshot["experiments"]["wb"]["status"] == "ADMITTED"
    assert snapshot["experiments"]["wb"]["wait"]["status"] == "SATISFIED"
    assert snapshot["experiments"]["wb"]["wait"]["satisfied_by"] == passed["evidence"]["id"]
    assert engine.verify_replay()["deterministic"] is True


def test_deadline_expiry_backlogs_or_releases(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, spec())
    engine.propose_experiment(
        exp("w-backlog", "a", "va", "c1", wait={"kind": "time", "not_before": FUTURE, "deadline_minutes": 60})
    )
    engine.propose_experiment(
        exp(
            "w-release",
            "a",
            "va",
            "c2",
            wait={"kind": "time", "not_before": FUTURE, "deadline_minutes": 60, "on_expire": "release"},
        )
    )
    snapshot = engine.snapshot()
    # next_wake_at is the earliest actionable moment: here the deadlines, which precede not_before.
    assert snapshot["next_wake_at"] == snapshot["experiments"]["w-backlog"]["wait"]["deadline_ts"]

    snapshot = engine.refresh_waits(now=FUTURE)
    backlogged = snapshot["experiments"]["w-backlog"]
    released = snapshot["experiments"]["w-release"]
    assert backlogged["status"] == "BACKLOG"
    assert backlogged["backlog_reason"] == "wait_expired"
    assert backlogged["wait"]["status"] == "EXPIRED"
    assert released["status"] == "ADMITTED"
    assert released["wait"]["status"] == "EXPIRED"
    assert released["wait"]["released"] is True
    assert engine.verify_replay()["deterministic"] is True


def test_wait_validation_rejects_bad_shapes(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, spec())
    with pytest.raises(ValueError):
        engine.propose_experiment(exp("bad1", "a", "va", "c1", wait={"kind": "nap"}))
    with pytest.raises(ValueError):
        engine.propose_experiment(exp("bad2", "a", "va", "c1", wait={"kind": "time"}))
    with pytest.raises(ValueError):
        engine.propose_experiment(
            exp("bad3", "a", "va", "c1", wait={"kind": "evidence", "until_evidence": {"claim_id": "nope"}})
        )


def test_planner_context_exposes_waiting_and_next_wake(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, spec())
    engine.propose_experiment(exp("w1", "a", "va", "c1", wait={"kind": "time", "not_before": FUTURE}))
    context = engine.planner_context()
    assert context["next_wake_at"] == FUTURE
    assert [item["id"] for item in context["waiting"]] == ["w1"]


def test_observatory_renders_waiting_section(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, spec())
    engine.propose_experiment(exp("w1", "a", "va", "c1", wait={"kind": "time", "not_before": FUTURE}))
    report = engine.render_report()
    html_text = report.read_text(encoding="utf-8")
    assert 'id="waitingList"' in html_text
    assert 'id="nextWake"' in html_text
    assert "renderWaiting" in html_text


def test_wake_cli_execute_runs_released_command_experiment(tmp_path: Path, capsys):
    import json
    import sys

    engine = ResearchEngine.create(tmp_path, spec())
    command = f"{sys.executable} -c \"import json; json.dump({{'ok': True}}, open('metrics.json', 'w'))\""
    item = exp("w-cmd", "a", "va", "c1", wait={"kind": "time", "not_before": FUTURE})
    item["action"] = {"kind": "command", "command": command, "metrics_path": "metrics.json"}
    engine.propose_experiment(item)

    assert main(["research", "wake", "latest", "--root", str(tmp_path), "--now", FUTURE, "--execute", "--yes"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fired"] == ["w-cmd"]
    assert payload["executed"] == [{"experiment_id": "w-cmd", "verdict": "PASS", "reason_code": "pass_rule_matched"}]
    snapshot = engine.snapshot()
    assert snapshot["claims"]["a"]["status"] == "SUPPORTED"


def test_wake_cli_fires_and_reports(tmp_path: Path, capsys):
    import json

    engine = ResearchEngine.create(tmp_path, spec())
    engine.propose_experiment(exp("w1", "a", "va", "c1", wait={"kind": "time", "not_before": FUTURE}))
    assert main(["research", "wake", "latest", "--root", str(tmp_path), "--now", BEFORE_FUTURE]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fired"] == []
    assert payload["next_wake_at"] == FUTURE

    assert main(["research", "wake", "latest", "--root", str(tmp_path), "--now", FUTURE]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fired"] == ["w1"]
    assert payload["next_wake_at"] is None
