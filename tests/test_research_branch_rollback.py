from pathlib import Path

from sisyfus.research_v2.engine import ResearchEngine


def exp(exp_id, claim, contract, context, from_state=None):
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
    if from_state:
        item["from_state_id"] = from_state
    return item


def settle(engine, exp_id, ok):
    attempt = engine.begin_attempt(exp_id)
    return engine.settle_attempt(attempt["id"], {"metrics": {"ok": ok}})


def spec():
    return {
        "id": "branch-test",
        "topic": "Branch and rollback",
        "claims": [
            {"id": "a", "statement": "Foundation is sound", "weight": 1},
            {"id": "b", "statement": "Dependent method works", "depends_on": ["a"], "weight": 1},
        ],
        "verification_contracts": [
            {"id": "va", "target_claim_id": "a", "pass_if": [{"path": "metrics.ok", "op": "==", "value": True}], "fail_if": [{"path": "metrics.ok", "op": "==", "value": False}]},
            {"id": "vb", "target_claim_id": "b", "pass_if": [{"path": "metrics.ok", "op": "==", "value": True}], "fail_if": [{"path": "metrics.ok", "op": "==", "value": False}]},
        ],
        "budget": {"max_attempts": 10, "max_cost_units": 10},
    }


def test_sibling_branch_can_return_to_checkpoint(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, spec())
    engine.propose_experiment(exp("a-pass", "a", "va", "a1"))
    a_result = settle(engine, "a-pass", True)
    checkpoint = a_result["snapshot"]["current_state_id"]
    engine.propose_experiment(exp("b-fail", "b", "vb", "weak", checkpoint))
    failed = settle(engine, "b-fail", False)
    assert failed["snapshot"]["claims"]["b"]["status"] == "REFUTED"
    engine.propose_experiment(exp("b-alt", "b", "vb", "strong", checkpoint))
    passed = settle(engine, "b-alt", True)
    assert passed["snapshot"]["claims"]["a"]["status"] == "SUPPORTED"
    assert passed["snapshot"]["claims"]["b"]["status"] == "SUPPORTED"
    assert passed["snapshot"]["run_status"] == "SOLVED"
    assert len(passed["snapshot"]["states"]) == 4


def test_refuting_supported_upstream_claim_rolls_back_dependents(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, spec())
    engine.propose_experiment(exp("a-pass", "a", "va", "a1"))
    settle(engine, "a-pass", True)
    engine.propose_experiment(exp("b-pass", "b", "vb", "b1"))
    solved = settle(engine, "b-pass", True)
    assert solved["snapshot"]["run_status"] == "SOLVED"

    # The engine normally stops accepting experiments after SOLVED. Reopen this audit
    # scenario by branching from the solved state through an event-level proposal is
    # intentionally disallowed; create the falsification before the dependent pass.
    engine2 = ResearchEngine.create(tmp_path / "second", spec())
    engine2.propose_experiment(exp("a-pass", "a", "va", "a1"))
    settle(engine2, "a-pass", True)
    engine2.propose_experiment(exp("b-pass", "b", "vb", "b1"))
    b_attempt = engine2.begin_attempt("b-pass")
    # Reserve falsification while the run is still active, then settle B and A-fail.
    engine2.propose_experiment(exp("a-falsify", "a", "va", "a2"))
    a_attempt = engine2.begin_attempt("a-falsify")
    engine2.settle_attempt(b_attempt["id"], {"metrics": {"ok": True}})
    rolled = engine2.settle_attempt(a_attempt["id"], {"metrics": {"ok": False}})
    snapshot = rolled["snapshot"]
    assert snapshot["claims"]["a"]["status"] == "REFUTED"
    assert snapshot["claims"]["b"]["status"] == "INVALIDATED"
    assert snapshot["progress"]["objective"] == 0.0
    assert snapshot["recent_rollbacks"]
    assert any(item["progress_rollback"] for item in snapshot["recent_rollbacks"])



def test_evidence_graph_retains_inactive_sibling_branch_evidence(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, spec())
    engine.propose_experiment(exp("a-pass", "a", "va", "a1"))
    a_result = settle(engine, "a-pass", True)
    checkpoint = a_result["snapshot"]["current_state_id"]
    engine.propose_experiment(exp("b-fail", "b", "vb", "weak", checkpoint))
    failed = settle(engine, "b-fail", False)
    failed_evidence = failed["evidence"]["id"]
    engine.propose_experiment(exp("b-alt", "b", "vb", "strong", checkpoint))
    settle(engine, "b-alt", True)
    graph = engine.snapshot(persist=True)
    import json
    evidence_graph = json.loads(engine.workspace.evidence_graph_path.read_text())
    edge = next(item for item in evidence_graph["edges"] if item["from"] == failed_evidence)
    assert edge["relation"] == "refutes"
    assert edge["active_in_current_state"] is False
