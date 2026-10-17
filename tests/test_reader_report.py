"""Reader prose is presentation, never a substitute for deterministic facts."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from sisyfus.research_v2.observatory import _TEMPLATE

FIXTURE = Path(__file__).parent / "fixtures/reader_report_v1.json"


def run_reader_js(body: str) -> dict:
    match = re.search(r"/\* READER_PURE_START \*/(.*?)/\* READER_PURE_END \*/", _TEMPLATE, re.S)
    assert match, "Reader pure functions must be independently testable"
    node = shutil.which("node")
    assert node, "Installed Node is required for these JS contract tests"
    script = (
        "const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));\n"
        + match.group(1)
        + "\nconst fixture=" + FIXTURE.read_text() + ";\n"
        + body
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_reader_schema_and_exact_snapshot_binding() -> None:
    actual = run_reader_js("""
const good=validateReaderReport(fixture,'sha256:fixture',3);
const stale=validateReaderReport(fixture,'sha256:changed',3);
const count=validateReaderReport(fixture,'sha256:fixture',4);
const missing=validateReaderReport(null,'sha256:fixture',3);
const malformed=validateReaderReport({...fixture,sections:[{heading:'bad',paragraphs:42}]},'sha256:fixture',3);
console.log(JSON.stringify({good:!!good.report,stale:stale.diagnostic,count:count.diagnostic,missing:missing.diagnostic,malformed:malformed.diagnostic}));
""")
    assert actual == {"good": True, "stale": "stale", "count": "stale", "missing": "missing", "malformed": "invalid"}


def test_reader_text_is_escaped_and_tables_are_contained() -> None:
    actual = run_reader_js("""
const r=structuredClone(fixture);r.sections[0].paragraphs=['<img src=x onerror=alert(1)>'];
r.sections[0].table.rows[0][0]='<script>alert(2)</script>';
console.log(JSON.stringify({html:readerProseHtml(r)}));
""")
    assert "<img" not in actual["html"] and "<script" not in actual["html"]
    assert "&lt;img" in actual["html"] and "&lt;script" in actual["html"]
    assert 'class="reader-table-wrap"' in actual["html"]
    assert "overflow-x:auto" in _TEMPLATE


def test_reader_links_allow_only_https_and_confined_artifacts() -> None:
    actual = run_reader_js("""
console.log(JSON.stringify({https:safeReaderHref('https://example.org/source'),local:safeReaderHref('artifact/artifacts%2Freport.md'),script:safeReaderHref('javascript:alert(1)'),data:safeReaderHref('data:text/html,bad'),parent:safeReaderHref('artifact/../outside'),encoded:safeReaderHref('artifact/%2e%2e%2foutside'),remote:safeReaderHref('//example.org/x')}));
""")
    assert actual["https"] == "https://example.org/source"
    assert actual["local"] == "artifact/artifacts%2Freport.md"
    assert all(actual[key] == "" for key in ("script", "data", "parent", "encoded", "remote"))


def test_claim_explanations_do_not_leak_into_replay_or_other_statuses() -> None:
    actual = run_reader_js("""
console.log(JSON.stringify({latest:readerTakeaway(fixture,'profit','INCONCLUSIVE',true),old:readerTakeaway(fixture,'profit','OPEN',false),wrong:readerTakeaway(fixture,'profit','SUPPORTED',true)}));
""")
    assert actual["latest"] == "No complete cycle; profit remains unestablished."
    assert actual["old"] == actual["wrong"] == ""


def test_reader_event_notes_require_exact_sequence_and_event_type() -> None:
    actual = run_reader_js("""
console.log(JSON.stringify({good:readerEventNote(fixture,{seq:3,event_type:'VERDICT_ISSUED'}),wrong:readerEventNote(fixture,{seq:3,event_type:'ATTEMPT_STARTED'}),absent:readerEventNote(fixture,{seq:1,event_type:'RUN_CREATED'})}));
""")
    assert actual["good"]["feed"] == "No complete cycle found"
    assert actual["wrong"] is None and actual["absent"] is None


def test_human_answer_precedes_collapsed_controller_counts() -> None:
    report = _TEMPLATE.split("function renderReport()", 1)[1].split("function renderDetailTabs()", 1)[0]
    assert report.index("readerProseHtml") < report.index('id="reportAuditSummary"')
    assert '<details class="card card-pad rpt-fold" id="reportAuditSummary"' in report
    assert "reader.question" in report and "reader.answer" in report
    assert "readerReportState" in report


def test_no_profit_is_inferred_for_missing_or_stale_narrative() -> None:
    assert "rd_missing" in _TEMPLATE and "rd_stale" in _TEMPLATE and "rd_invalid" in _TEMPLATE
    assert "reader_claim" in _TEMPLATE and "reader.language" in _TEMPLATE
    assert "get('view')" in _TEMPLATE


def test_four_fill_denominator_and_single_venue_distinction() -> None:
    # Conditional arithmetic, not a daily-profit or capacity assertion.
    combined_volume = 20_000_000
    assert [combined_volume / 4 * bp / 10_000 for bp in (1, 2, 5)] == [500, 1000, 2500]
    assert 10_000_000 / 2 * 1 / 10_000 == 500
    assert 10_000_000 * 0.00009 == 900  # XYZ fees alone at zero spread gain.
