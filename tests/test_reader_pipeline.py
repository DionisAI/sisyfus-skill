"""Frozen public report lifecycle checks; retained fixtures, no trading or deletion."""
from __future__ import annotations

import importlib
import json
import uuid
from pathlib import Path

import pytest

from sisyfus import cli
from sisyfus.research_v2.engine import ResearchEngine
from sisyfus.workers.claude_code import ClaudeCodeDriver
from sisyfus.workers.protocol import Receipt, digest

RETAIN = Path(__file__).resolve().parents[1] / "artifacts/techlead/report-pipeline-tests"


def policy():
    return {"schema_version": "sisyfus.reader-policy.v1", "enabled": True,
            "question": "这个策略是否盈利，收益来自哪里？", "primary_claim_ids": ["profit"],
            "artifact_paths": ["artifacts/metrics.json"],
            "facts": {"cycles": {"path": "artifacts/metrics.json", "pointer": "/cycles"},
                      "duration": {"path": "artifacts/metrics.json", "pointer": "/minutes"}}}


def run_fixture(*, configured=True, settled=True, optin=None):
    root = RETAIN / uuid.uuid4().hex
    root.mkdir(parents=True)
    spec = {"id": "report-fixture", "topic": "Retained synthetic reporting fixture",
            "claims": [{"id": "collection", "statement": "Fixture collection is complete"},
                       {"id": "profit", "statement": "A complete profitable cycle exists", "required": False}],
            "verification_contracts": [{"id": "collection-check", "target_claim_id": "collection",
                "pass_if": {"all": [{"path": "metrics.ready", "op": "==", "value": True}]},
                "fail_if": {"all": [{"path": "metrics.ready", "op": "==", "value": False}]}}],
            "metadata": {"reader_reporting": policy() if optin is None else optin} if configured else {}}
    engine = ResearchEngine.create(root, spec)
    (engine.workspace.path / "artifacts/metrics.json").write_text('{"cycles":0,"minutes":10}\n')
    engine.propose_experiment({"id": "collect", "target_claim_ids": ["collection"],
                               "contract_id": "collection-check", "action": {"kind": "external"},
                               "expected_outcomes": {"pass": "complete", "fail": "incomplete", "inconclusive": "uncertain", "invalid": "bad fixture"}})
    attempt = engine.begin_attempt("collect")
    if settled:
        engine.settle_attempt(attempt["id"], {"metrics": {"ready": True}})
    return engine, attempt


class ScriptedOpus:
    """Protocol fixture only; real native acceptance is a separate retained run."""
    def __init__(self, *, mutate=None, review_mutate=None, verdict="PASS", actual="claude-opus-5-5", same_session=False, status="COMPLETED", edit=None):
        self.calls = []
        self.mutate = mutate
        self.review_mutate = review_mutate
        self.verdict = verdict
        self.actual = actual
        self.same_session = same_session
        self.native_status = status
        self.edit = edit

    def run(self, request, emit, controls=None):
        self.calls.append(request)
        payload = json.loads(request.prompt)
        role = payload["role"]
        evidence = json.loads((Path(request.cwd) / "evidence.json").read_text())
        if role == "author":
            value = {"schema_version": "sisyfus.reader-report.v1", "basis": evidence["basis"],
                     "language": "zh", "title": "这项策略值不值得继续研究？", "question": evidence["question"],
                     "answer": "样本里完成循环为 {{fact:cycles}}，盈利尚未得到证实。",
                     "scope_note": "这是研究样本，不是实盘收益。",
                     "sections": [{"heading": "收益机制和测量结果", "paragraphs": ["观察了 {{fact:duration}} 分钟；价差要覆盖开平仓成本。"],
                                   "table": {"columns": ["指标", "结果"], "rows": [["完整循环", "{{fact:cycles}}"]]}}],
                     "process": [{"title": "检查完整循环", "what": "检查开仓与平仓。", "finding": "未观察到完整循环。", "meaning": "成交量不等于盈利。"}],
                     "claim_takeaways": {key: {"status": claim["status"], "text": "样本采集已完成。" if key == "collection" else "盈利证据仍待补齐。"}
                                         for key, claim in evidence["claims"].items()},
                     "event_notes": {}, "sources": [{"label": "冻结指标", "href": "artifact/artifacts%2Fmetrics.json"}]}
            if self.edit:
                self.edit(value)
            if self.mutate:
                self.mutate()
        else:
            value = {"schema_version": "sisyfus.reader-review.v1", "basis": evidence["basis"],
                     "draft_hash": payload["draft_hash"], "bundle_hash": payload["bundle_hash"], "verdict": self.verdict,
                     "findings": [] if self.verdict == "PASS" else ["Question answer overstates available evidence."]}
            if self.review_mutate:
                self.review_mutate()
        if controls:
            controls()
        emit("native_event", {"type": "system", "subtype": "init", "tools": [],
                              "session_id": "fixture-author" if self.same_session or role == "author" else "fixture-review"})
        emit("report_fixture", {"role": role})
        return Receipt(self.native_status, session_id="fixture-author" if self.same_session or role == "author" else "fixture-review",
                       exit_code=0, output=json.dumps(value, ensure_ascii=False),
                       requested_model=request.model, actual_model=self.actual)


def api():
    # Fail as missing product behavior, rather than a collection-time import error.
    assert importlib.util.find_spec("sisyfus.research_v2.reporting"), "Controller-owned report composition lifecycle is missing"
    return importlib.import_module("sisyfus.research_v2.reporting")


def reader(engine):
    return json.loads(engine.workspace.i18n_path.read_text())["zh"]["report"]["reader"]


def test_terminal_cli_settle_automatically_publishes_question_answer(monkeypatch, capsys):
    engine, attempt = run_fixture(settled=False)
    fake = ScriptedOpus()
    monkeypatch.setattr(ClaudeCodeDriver, "run", fake.run)
    monkeypatch.setattr(cli, "_research_engine", lambda *a, **kw: engine)
    observation = engine.workspace.path / "artifacts/observation.json"
    observation.write_text('{"metrics":{"ready":true}}')
    assert cli.main(["research", "settle", engine.workspace.research_id, attempt["id"], str(observation), "--root", str(engine.workspace.root)]) == 0
    capsys.readouterr()
    assert engine.workspace.i18n_path.exists(), "Terminal confirmed write command did not produce a human-readable report"
    r = reader(engine)
    assert "完成循环为 0" in r["answer"] and "盈利尚未得到证实" in r["answer"]
    assert len(fake.calls) == 2
    result = api().ReportCoordinator(engine, driver=fake).status()
    assert result["jobs"][-1]["answer_state"] == "UNRESOLVED"
    assert result["jobs"][-1]["execution_status"] == "SOLVED"


def test_publish_is_bound_reviewed_idempotent_and_preserves_truth_and_translations():
    engine, _ = run_fixture()
    old = {"en": {"report": {"title": "Existing translation"}}, "zh": {"claims": {"profit": {"label": "盈利"}}}}
    engine.workspace.i18n_path.write_text(json.dumps(old))
    task_before, events_before = engine.workspace.task_path.read_bytes(), engine.workspace.events_path.read_bytes()
    fake = ScriptedOpus()
    coordinator = api().ReportCoordinator(engine, driver=fake)
    result = coordinator.compose(approved=True)
    assert result["status"] == "PUBLISHED" and result["answer_state"] == "UNRESOLVED"
    assert len(fake.calls) == 2 and all(r.mode == "no-tools" and r.model == "claude-opus-5-5" and r.session_id is None for r in fake.calls)
    assert all(json.loads(r.prompt)["bundle"] for r in fake.calls)
    assert all(Path(r.cwd) != engine.workspace.path for r in fake.calls)
    assert coordinator.compose(approved=True)["cached"] is True and len(fake.calls) == 2
    i18n = json.loads(engine.workspace.i18n_path.read_text())
    assert i18n["en"] == old["en"] and i18n["zh"]["claims"] == old["zh"]["claims"]
    assert reader(engine)["basis"] == {"snapshot_hash": engine.snapshot()["snapshot_hash"], "event_count": len(engine.workspace.read_events())}
    assert "问题结论尚待证据" in reader(engine)["scope_note"]
    assert Path(result["report_path"]).is_file() and Path(result["manifest_path"]).is_file()
    assert engine.workspace.task_path.read_bytes() == task_before and engine.workspace.events_path.read_bytes() == events_before
    assert engine.verify_replay()["deterministic"]
    assert any(p.read_bytes() == json.dumps(old).encode() for p in Path(result["manifest_path"]).parent.rglob("*previous*"))


def test_legacy_manual_report_requires_confirmation_and_missing_optin_spends_nothing():
    engine, _ = run_fixture(configured=False)
    fake = ScriptedOpus()
    assert api().maybe_compose(engine, driver=fake)["status"] == "NOT_CONFIGURED"
    coordinator = api().ReportCoordinator(engine, policy=policy(), driver=fake)
    with pytest.raises(api().ReportError, match="APPROVAL"):
        coordinator.compose(approved=False)
    assert fake.calls == []
    assert coordinator.compose(approved=True)["status"] == "PUBLISHED"


def test_active_run_never_dispatches_report_model():
    engine, _ = run_fixture(settled=False)
    fake = ScriptedOpus()
    assert api().maybe_compose(engine, driver=fake)["status"] == "NOT_READY"
    assert fake.calls == []


@pytest.mark.parametrize("command", ["status", "report", "replay"])
def test_read_commands_and_engine_render_never_invoke_models(command, monkeypatch, capsys):
    engine, _ = run_fixture()
    fake = ScriptedOpus()
    monkeypatch.setattr(ClaudeCodeDriver, "run", fake.run)
    monkeypatch.setattr(cli, "_research_engine", lambda *a, **kw: engine)
    engine.sync(render=True)
    assert cli.main(["research", command, "--root", str(engine.workspace.root)]) == 0
    capsys.readouterr()
    assert not fake.calls and not engine.workspace.i18n_path.exists()


@pytest.mark.parametrize("verdict,actual,same,status,code", [
    ("REJECT", "claude-opus-5-5", False, "COMPLETED", "REVIEW"),
    ("PASS", None, False, "COMPLETED", "MODEL"),
    ("PASS", "claude-opus-5-5", True, "COMPLETED", "SESSION"),
    ("PASS", "claude-opus-5-5", False, "UNKNOWN", "UNKNOWN"),
    ("PASS", "claude-opus-5-5", False, "FAILED", "NATIVE")])
def test_failed_review_attestation_session_or_unknown_never_publishes_or_retries(verdict, actual, same, status, code):
    engine, _ = run_fixture()
    fake = ScriptedOpus(verdict=verdict, actual=actual, same_session=same, status=status)
    coordinator = api().ReportCoordinator(engine, driver=fake)
    with pytest.raises(api().ReportError, match=code):
        coordinator.compose(approved=True)
    calls = len(fake.calls)
    with pytest.raises(api().ReportError):
        coordinator.compose(approved=True)
    assert len(fake.calls) == calls and not engine.workspace.i18n_path.exists()
    assert coordinator.status()["jobs"]


def test_source_drift_before_review_is_rejected_and_retained():
    engine, _ = run_fixture()
    fake = ScriptedOpus(mutate=lambda: (engine.workspace.path / "artifacts/metrics.json").write_text('{"cycles":9,"minutes":10}'))
    coordinator = api().ReportCoordinator(engine, driver=fake)
    with pytest.raises(api().ReportError, match="DRIFT"):
        coordinator.compose(approved=True)
    assert len(fake.calls) == 1 and not engine.workspace.i18n_path.exists()


def test_source_drift_after_review_is_rejected_before_publication():
    engine, _ = run_fixture()
    fake = ScriptedOpus(review_mutate=lambda: (engine.workspace.path / "artifacts/metrics.json").write_text('{"cycles":9,"minutes":10}'))
    with pytest.raises(api().ReportError, match="DRIFT"):
        api().ReportCoordinator(engine, driver=fake).compose(approved=True)
    assert len(fake.calls) == 2 and not engine.workspace.i18n_path.exists()


def test_unknown_receipt_fences_changed_basis_too():
    engine, _ = run_fixture()
    fake = ScriptedOpus(status="UNKNOWN")
    coordinator = api().ReportCoordinator(engine, driver=fake)
    with pytest.raises(api().ReportError, match="UNKNOWN"):
        coordinator.compose(approved=True)
    (engine.workspace.path / "artifacts/metrics.json").write_text('{"cycles":1,"minutes":10}')
    with pytest.raises(api().ReportError, match="UNKNOWN"):
        coordinator.compose(approved=True)
    assert len(fake.calls) == 1


def test_existing_journal_spec_and_caps_are_respected_without_rebinding():
    from sisyfus.autonomy.store import AutonomyStore
    from sisyfus.workers.journal import Journal
    engine, _ = run_fixture()
    journal = Journal(AutonomyStore(engine.workspace.root / ".sisyfus/autonomy.sqlite3"))
    spec = {"parallelism": 1, "max_calls": 0, "planner": "claude", "tasks": []}
    journal.bind(spec)
    fake = ScriptedOpus()
    with pytest.raises(api().ReportError, match="BUDGET|BLOCKED|budget"):
        api().ReportCoordinator(engine, driver=fake).compose(approved=True)
    assert journal.spec() == spec and not fake.calls


def test_malformed_sidecar_is_explicit_and_never_overwritten():
    engine, _ = run_fixture()
    engine.workspace.i18n_path.write_text('{malformed')
    fake = ScriptedOpus()
    with pytest.raises(api().ReportError, match="SIDECAR|JSON"):
        api().ReportCoordinator(engine, driver=fake).compose(approved=True)
    assert engine.workspace.i18n_path.read_text() == '{malformed'


@pytest.mark.parametrize("path", ["../task.json", "/etc/passwd", "artifacts/../task.json", "artifacts/holdout/private.json"])
def test_unsafe_or_evaluation_paths_are_rejected_before_native_call(path):
    engine, _ = run_fixture()
    p = policy()
    p["artifact_paths"] = [path]
    fake = ScriptedOpus()
    with pytest.raises((api().ReportError, ValueError)):
        api().ReportCoordinator(engine, policy=p, driver=fake).compose(approved=True)
    assert not fake.calls


def test_symlink_artifact_and_missing_numeric_fact_fail_before_native_call():
    engine, _ = run_fixture()
    p = policy()
    p["facts"]["cycles"]["pointer"] = "/missing"
    fake = ScriptedOpus()
    with pytest.raises((api().ReportError, ValueError)):
        api().ReportCoordinator(engine, policy=p, driver=fake).compose(approved=True)
    link = engine.workspace.path / "artifacts/linked.json"
    link.symlink_to(engine.workspace.task_path)
    p = policy()
    p["artifact_paths"].append("artifacts/linked.json")
    with pytest.raises((api().ReportError, ValueError)):
        api().ReportCoordinator(engine, policy=p, driver=fake).compose(approved=True)
    assert not fake.calls


@pytest.mark.parametrize("edit", [
    lambda r: r.update(answer="每日可赚 999 美元。"),
    lambda r: r.update(answer="每日可赚 ９９９ 美元。"),
    lambda r: r.update(answer="每日可赚 ² 美元。"),
    lambda r: r.update(answer="收益是 {{fact:invented}}。"),
    lambda r: r["claim_takeaways"]["profit"].update(status="SUPPORTED"),
    lambda r: r["sources"][0].update(href="javascript:alert(1)"),
    lambda r: r.update(event_notes={"1": {"event_type": "WRONG", "feed": "完成", "caster": "完成"}}),
    lambda r: r["basis"].update(snapshot_hash="sha256:unrelated")])
def test_unbound_numerals_status_link_event_and_basis_fail_controller_validation(edit):
    engine, _ = run_fixture()
    fake = ScriptedOpus(edit=edit)
    with pytest.raises(api().ReportError):
        api().ReportCoordinator(engine, driver=fake).compose(approved=True)
    assert len(fake.calls) == 1 and not engine.workspace.i18n_path.exists()


def test_pause_gate_resume_and_stop_latch_are_report_only():
    engine, _ = run_fixture()
    fake = ScriptedOpus()
    coordinator = api().ReportCoordinator(engine, driver=fake)
    original = engine.workspace.events_path.read_bytes()
    assert coordinator.control("pause")["control"] == "PAUSED"
    with pytest.raises(api().ReportError, match="PAUSED"):
        coordinator.compose(approved=True)
    assert not fake.calls
    assert coordinator.control("resume")["control"] == "RUNNING"
    fake.mutate = lambda: coordinator.control("stop")
    with pytest.raises(api().ReportError, match="STOPPED|UNKNOWN"):
        coordinator.compose(approved=True)
    assert not engine.workspace.i18n_path.exists() and len(fake.calls) == 1
    with pytest.raises(api().ReportError, match="STOPPED"):
        coordinator.compose(approved=True)
    assert engine.workspace.events_path.read_bytes() == original


def test_concurrent_same_basis_is_fenced_before_second_author():
    engine, _ = run_fixture()
    other = ScriptedOpus()
    def concurrent():
        with pytest.raises(api().ReportError, match="UNKNOWN|IN_FLIGHT"):
            api().ReportCoordinator(engine, driver=other).compose(approved=True)
    fake = ScriptedOpus(mutate=concurrent)
    assert api().ReportCoordinator(engine, driver=fake).compose(approved=True)["status"] == "PUBLISHED"
    assert not other.calls


def test_malformed_optin_is_exposed_before_cli_mutates_research(monkeypatch, capsys):
    bad = policy()
    bad["primary_claim_ids"] = ["unrelated"]
    engine, _ = run_fixture(optin=bad)
    before = engine.workspace.events_path.read_bytes()
    monkeypatch.setattr(cli, "_research_engine", lambda *a, **kw: engine)
    assert cli.main(["research", "finalize", engine.workspace.research_id, "--root", str(engine.workspace.root)]) != 0
    capsys.readouterr()
    assert engine.workspace.events_path.read_bytes() == before


def test_report_compose_and_controls_are_explicit_cli_surfaces(monkeypatch, capsys):
    engine, _ = run_fixture(configured=False)
    fake = ScriptedOpus()
    monkeypatch.setattr(ClaudeCodeDriver, "run", fake.run)
    monkeypatch.setattr(cli, "_research_engine", lambda *a, **kw: engine)
    p = engine.workspace.path / "artifacts/policy.json"
    p.write_text(json.dumps(policy()))
    result = cli.main(["research", "report-compose", "--policy", str(p), "--root", str(engine.workspace.root)])
    assert result != 0 and not fake.calls
    assert cli.main(["research", "report-compose", "--yes", "--policy", str(p), "--root", str(engine.workspace.root)]) == 0
    assert cli.main(["research", "report-control", "latest", "status", "--root", str(engine.workspace.root)]) == 0
    capsys.readouterr()


def test_review_rejects_spelled_out_quantities_not_verified_by_numeric_guard():
    engine, _ = run_fixture()
    fake = ScriptedOpus(edit=lambda r: r.update(answer="每天稳赚五百美元。"), verdict="REJECT")
    with pytest.raises(api().ReportError, match="REVIEW"):
        api().ReportCoordinator(engine, driver=fake).compose(approved=True)
    assert len(fake.calls) == 2 and not engine.workspace.i18n_path.exists()


@pytest.mark.parametrize("data", ['{"cycles":NaN,"minutes":10}', '{"cycles":true,"minutes":10}', '{"cycles":0,"cycles":9,"minutes":10}'])
def test_nonfinite_boolean_and_duplicate_numeric_sources_fail(data):
    engine, _ = run_fixture()
    (engine.workspace.path / "artifacts/metrics.json").write_text(data)
    fake = ScriptedOpus()
    with pytest.raises(api().ReportError):
        api().ReportCoordinator(engine, driver=fake).compose(approved=True)
    assert not fake.calls


def test_pause_preserves_reviewed_work_and_resumes_without_repeat_calls():
    engine, _ = run_fixture()
    fake = ScriptedOpus()
    c = api().ReportCoordinator(engine, driver=fake)
    fake.review_mutate = lambda: c.control("pause")
    with pytest.raises(api().ReportError, match="PAUSED"):
        c.compose(approved=True)
    assert len(fake.calls) == 2 and not engine.workspace.i18n_path.exists()
    c.control("resume")
    assert c.compose(approved=True)["status"] == "PUBLISHED"
    assert len(fake.calls) == 2


def test_unknown_resolution_is_explicit_report_scoped_retains_receipt_and_does_not_retry():
    from sisyfus.autonomy.store import AutonomyStore
    from sisyfus.workers.journal import Journal
    engine, _ = run_fixture()
    fake = ScriptedOpus(status="UNKNOWN")
    c = api().ReportCoordinator(engine, driver=fake)
    with pytest.raises(api().ReportError, match="UNKNOWN"):
        c.compose(approved=True)
    journal = Journal(AutonomyStore(engine.workspace.root / ".sisyfus/autonomy.sqlite3"))
    run = journal.runs()[-1]
    with pytest.raises(api().ReportError, match="APPROVAL"):
        c.control("resolve-unknown", key=run["key"], note="Inspected native session; retain unknown", approved=False)
    assert c.control("resolve-unknown", key=run["key"], note="Inspected native session; retain unknown", approved=True)
    assert journal.runs()[-1]["receipt"] == run["receipt"]
    with pytest.raises(api().ReportError):
        c.compose(approved=True)
    assert len(fake.calls) == 1 and journal.store.verify_event_chain()["valid"]


def test_existing_english_reader_is_preserved_and_exposed_in_status():
    engine, _ = run_fixture()
    old = {"en": {"report": {"reader": {"basis": {"snapshot_hash": "older"}, "title": "Retained old translation"}}}}
    engine.workspace.i18n_path.write_text(json.dumps(old))
    c = api().ReportCoordinator(engine, driver=ScriptedOpus())
    c.compose(approved=True)
    assert json.loads(engine.workspace.i18n_path.read_text())["en"] == old["en"]
    assert c.status()["translation_warning"]


def test_append_after_publication_invalidates_basis_without_model_call(monkeypatch, capsys):
    engine, _ = run_fixture()
    fake = ScriptedOpus()
    api().ReportCoordinator(engine, driver=fake).compose(approved=True)
    old = reader(engine)["basis"]
    monkeypatch.setattr(ClaudeCodeDriver, "run", fake.run)
    monkeypatch.setattr(cli, "_research_engine", lambda *a, **kw: engine)
    assert cli.main(["research", "report", "--log-event", "--root", str(engine.workspace.root)]) == 0
    capsys.readouterr()
    assert reader(engine)["basis"] == old and old["event_count"] < len(engine.workspace.read_events()) and len(fake.calls) == 2


def test_publication_crash_after_replace_is_reconciled_without_native_repeat(monkeypatch):
    import os
    engine, _ = run_fixture()
    fake = ScriptedOpus()
    c = api().ReportCoordinator(engine, driver=fake)
    real = os.replace
    def crash(src, dst):
        real(src, dst)
        if Path(dst) == engine.workspace.i18n_path:
            raise SystemExit("Injected crash after sidecar replacement")
    with monkeypatch.context() as m:
        m.setattr(os, "replace", crash)
        with pytest.raises(SystemExit):
            c.compose(approved=True)
    assert c.compose(approved=True)["status"] == "PUBLISHED"
    assert len(fake.calls) == 2


def test_question_state_respects_contested_refutation():
    snapshot = {"claims": {"profit": {"status": "REFUTED"}}, "contested_claims": ["profit"], "run_status": "REFUTED"}
    assert api().answer_state(snapshot, ["profit"]) == "UNRESOLVED"
    snapshot["contested_claims"] = []
    assert api().answer_state(snapshot, ["profit"]) == "REFUTED"


def test_crashed_native_reservation_expires_to_unknown_without_redispatch():
    from sisyfus.autonomy.store import AutonomyStore
    from sisyfus.workers.journal import Journal
    engine, _ = run_fixture()
    now = [1000000000.0]
    class Crashed:
        def run(self, request, emit, controls=None):
            raise SystemExit("Injected native owner crash")
    c = api().ReportCoordinator(engine, driver=Crashed(), clock=lambda: now[0])
    with pytest.raises(SystemExit): c.compose(approved=True)
    now[0] += 20000
    assert c.status()["jobs"][-1]["status"] == "UNKNOWN"
    journal = Journal(AutonomyStore(engine.workspace.root / ".sisyfus/autonomy.sqlite3"))
    assert journal.runs()[-1]["receipt"]["status"] == "UNKNOWN"
    with pytest.raises(api().ReportError, match="UNKNOWN"):
        c.compose(approved=True)


def test_stop_during_review_then_resume_never_publishes_stopped_job():
    engine, _ = run_fixture()
    fake = ScriptedOpus()
    c = api().ReportCoordinator(engine, driver=fake)
    fake.review_mutate = lambda: c.control("stop")
    with pytest.raises(api().ReportError, match="STOPPED|UNKNOWN"):
        c.compose(approved=True)
    c.control("resume")
    with pytest.raises(api().ReportError, match="STOPPED"):
        c.compose(approved=True)
    assert len(fake.calls) == 2 and not engine.workspace.i18n_path.exists()


def test_same_snapshot_translation_edit_is_fenced_instead_of_lost():
    engine, _ = run_fixture()
    engine.workspace.i18n_path.write_text('{}')
    fake = ScriptedOpus(review_mutate=lambda: engine.workspace.i18n_path.write_text('{"en":{"operator":"new text"}}'))
    with pytest.raises(api().ReportError, match="DRIFT|SIDECAR|FENCED"):
        api().ReportCoordinator(engine, driver=fake).compose(approved=True)
    assert json.loads(engine.workspace.i18n_path.read_text()) == {"en": {"operator": "new text"}}
