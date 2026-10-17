"""Review-blocking regressions frozen before the minimal implementation repair."""
import json
import sqlite3

import pytest

from sisyfus import cli
from test_reader_pipeline import api, run_fixture, ScriptedOpus


def test_publication_keeps_static_history_frames_without_engine_refresh():
    engine, _ = run_fixture()
    before = json.loads(engine.workspace.report_snapshot_path.read_text())
    events = engine.workspace.events_path.read_bytes()
    assert before["frames"], "Fixture must already expose replay before publication"
    assert api().ReportCoordinator(engine, driver=ScriptedOpus()).compose(approved=True)["status"] == "PUBLISHED"
    # No serve_report, sync or refresh here: publication must keep the static view.
    after = json.loads(engine.workspace.report_snapshot_path.read_text())
    assert after["frames"] == before["frames"], "Publishing a reader erased the existing graph/history timeline"
    assert engine.workspace.events_path.read_bytes() == events


@pytest.mark.parametrize("ready,research_code,expected_code", [(False, 2, 2), (True, 0, 5)])
def test_postwrite_sqlite_error_preserves_research_stdout_and_exit(ready, research_code, expected_code, monkeypatch, capsys):
    engine, attempt = run_fixture(settled=False)
    observation = engine.workspace.path / "artifacts/review-observation.json"
    observation.write_text(json.dumps({"metrics": {"ready": ready}}))
    settled = []
    original = engine.settle_attempt

    def record(*args, **kwargs):
        result = original(*args, **kwargs)
        settled.append(result)
        return result

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked; Bearer synthetic-review-secret")

    monkeypatch.setattr(engine, "settle_attempt", record)
    monkeypatch.setattr(cli, "_research_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(api(), "maybe_compose", locked)
    code = cli.main(["research", "settle", engine.workspace.research_id, attempt["id"], str(observation), "--root", str(engine.workspace.root)])
    captured = capsys.readouterr()
    assert code == expected_code, "A reporting SQLite error replaced the committed research exit boundary"
    assert len(settled) == 1
    result = settled[0]
    assert (0 if result["verdict"]["status"] == "PASS" else 2) == research_code
    legacy = {"verdict": result["verdict"], "claim_effects": result["claim_effects"],
              "evidence": result["evidence"], "state": cli._research_summary(result["snapshot"], engine)}
    assert captured.out == json.dumps(legacy, indent=2, sort_keys=True, default=str) + "\n"
    assert len(captured.err.splitlines()) == 1
    outcome = json.loads(captured.err)
    assert outcome["status"] == "FAILED" and outcome["error"]["code"] == "REPORT"
    assert "database is locked" in outcome["error"]["message"]
    assert "synthetic-review-secret" not in captured.err and "[REDACTED]" in captured.err
    assert len(engine.workspace.read_events()) > 1


def test_automatic_cli_reports_active_job_without_failure_or_duplicate_author(monkeypatch, capsys):
    reporting = api()
    engine, _ = run_fixture()
    fake = ScriptedOpus()
    coordinator = reporting.ReportCoordinator(engine, driver=fake)
    retain = reporting._retain

    def interrupt_before_native(path, raw):
        if path.name == "evidence.json":
            raise SystemExit("Retained active job before native reservation")
        return retain(path, raw)

    with monkeypatch.context() as patch:
        patch.setattr(reporting, "_retain", interrupt_before_native)
        with pytest.raises(SystemExit):
            coordinator.compose(approved=True)
    assert coordinator.status()["jobs"][-1]["status"] == "RESERVED"
    monkeypatch.setattr(cli, "_research_engine", lambda *args, **kwargs: engine)
    assert cli.main(["research", "finalize", engine.workspace.research_id, "--root", str(engine.workspace.root)]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["run_status"] == "SOLVED"
    assert len(captured.err.splitlines()) == 1 and json.loads(captured.err)["status"] == "IN_FLIGHT"
    assert not fake.calls
    assert coordinator.status()["jobs"][-1]["status"] == "RESERVED"
    with pytest.raises(reporting.ReportError, match="IN_FLIGHT"):
        coordinator.compose(approved=True)
    assert not fake.calls


def test_postwrite_does_not_swallow_operator_interrupt(monkeypatch):
    engine, _ = run_fixture()

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt("Operator interruption")

    monkeypatch.setattr(api(), "maybe_compose", interrupted)
    with pytest.raises(KeyboardInterrupt):
        cli._report_after_write(engine, 0)
