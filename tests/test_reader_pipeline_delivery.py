"""Human artifact delivery contracts added before the missing delivery repair."""
import json
from pathlib import Path

from test_reader_pipeline import api, run_fixture, ScriptedOpus, reader


def test_report_path_is_retained_readable_markdown_not_only_observatory_html():
    engine, _ = run_fixture()
    result = api().ReportCoordinator(engine, driver=ScriptedOpus()).compose(approved=True)
    path = Path(result["report_path"])
    assert path.suffix == ".md", "A retained human Markdown report is required, not just the rendered index"
    text = path.read_text()
    r = reader(engine)
    assert r["question"] in text and r["answer"] in text
    assert r["process"][0]["finding"] in text
    assert result["answer_state"] == "UNRESOLVED" and result["execution_status"] == "SOLVED"
    assert json.loads(Path(result["manifest_path"]).read_text())["answer_state"] == "UNRESOLVED"


def test_default_visible_scope_is_plain_chinese_not_controller_status_codes():
    engine, _ = run_fixture()
    api().ReportCoordinator(engine, driver=ScriptedOpus()).compose(approved=True)
    scope = reader(engine)["scope_note"]
    assert "研究流程已完成" in scope and "问题结论尚待证据" in scope
    assert all(code not in scope for code in ("SOLVED", "UNRESOLVED", "SUPPORTED", "PASS"))


def test_crash_before_native_reservation_expires_to_fenced_job(monkeypatch):
    import pytest
    reporting = api()
    engine, _ = run_fixture()
    now = [1000000000.0]
    fake = ScriptedOpus()
    c = reporting.ReportCoordinator(engine, driver=fake, clock=lambda: now[0])
    original = reporting._retain
    def crash(path, raw):
        if path.name == "evidence.json":
            raise SystemExit("Injected owner crash before a native reservation")
        return original(path, raw)
    with monkeypatch.context() as m:
        m.setattr(reporting, "_retain", crash)
        with pytest.raises(SystemExit): c.compose(approved=True)
    now[0] += 20000
    assert c.status()["jobs"][-1]["status"] == "FENCED"
    with pytest.raises(reporting.ReportError, match="FENCED"):
        c.compose(approved=True)
    assert not fake.calls


def test_stop_after_publication_claim_may_finish_without_new_native_call(monkeypatch):
    import os
    engine, _ = run_fixture()
    fake = ScriptedOpus()
    c = api().ReportCoordinator(engine, driver=fake)
    original = os.replace
    def stop(src, dst):
        if Path(dst) == engine.workspace.i18n_path:
            c.control("stop")
        return original(src, dst)
    with monkeypatch.context() as m:
        m.setattr(os, "replace", stop)
        assert c.compose(approved=True)["status"] == "PUBLISHED"
    assert c.status()["control"] == "STOPPED"
    assert reader(engine)["answer"] and len(fake.calls) == 2
