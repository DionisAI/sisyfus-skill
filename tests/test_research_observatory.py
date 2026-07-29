from __future__ import annotations

from pathlib import Path

from sisyfus.research_v2.engine import ResearchEngine


def spec() -> dict:
    return {
        "id": "observatory-report",
        "topic": "Report rendering",
        "claims": [{"id": "a", "statement": "Claim A holds", "label": "A"}],
        "action_space": ["experiment"],
        "verification_contracts": [
            {"id": "va", "target_claim_id": "a", "pass_if": [{"path": "metrics.ok", "op": "==", "value": True}], "fail_if": [{"path": "metrics.ok", "op": "==", "value": False}]},
        ],
    }


def test_observatory_renders_report_tab_and_reason_i18n(tmp_path: Path) -> None:
    engine = ResearchEngine.create(tmp_path, spec())
    engine.propose_experiment({
        "id": "e1",
        "title": "e1",
        "target_claim_ids": ["a"],
        "contract_id": "va",
        "context_id": "c1",
        "action": {"kind": "external"},
        "expected_outcomes": {"pass": "p", "fail": "f", "inconclusive": "i", "invalid": "x"},
        "cost": {"units": 1},
    })
    attempt = engine.begin_attempt("e1")
    engine.settle_attempt(attempt["id"], {"metrics": {"ok": True}})
    html_text = engine.render_report().read_text(encoding="utf-8")
    assert 'id="view-report"' in html_text
    assert 'data-view="report"' in html_text
    assert "renderReport" in html_text
    assert "rpt_answer" in html_text
    assert "rsn_pass_rule_matched" in html_text
    assert "reasonSummary" in html_text
    assert "trClaimConclusion" in html_text
    assert "trReportBlock" in html_text
    assert "@media print" in html_text
