from __future__ import annotations

from dataclasses import asdict

import pytest

from sisyfus.research_os.models import SOP, Candidate
from sisyfus.research_os.sop_lab import evaluate_sop, optimize_sop, record_sop_candidate
from sisyfus.research_os.demo import create_demo


def candidate(cid="e0"):
    return Candidate(cid, "r", "f", "t", "r", (0, 0, 0, 0, 0, 0), 1, "c", "a").public()


def history(rid, family, labels, *, same="e0"):
    nodes, previous = [], []
    for i, label in enumerate(labels):
        nodes.append({"id": f"a{i}", "candidate": candidate(same), "available_after": list(previous),
                      "outcome": {"verdict": "PASS" if label else "FAIL", "label": label, "cost_units": 1,
                                  "evidence_id": f"ev{i}", "evidence_hash": f"h{i}"}, "provenance": {}})
        previous.append(f"a{i}")
    return {"schema": "sisyfus.replay.v1", "research_id": rid, "family": family,
            "source_event_head": "head", "task_hash": "task", "support": "recorded_actions_only", "nodes": nodes}


def test_retry_sop_replay_is_support_limited():
    h = history("r1", "f1", [0, 0, 1])
    one = evaluate_sop(h, SOP(max_attempts_per_experiment=1), budget=5)
    three = evaluate_sop(h, SOP(max_attempts_per_experiment=3), budget=5)
    assert one["passes"] == 0 and one["cost_units"] == 1 and one["selected"] == ["a0"]
    assert three["passes"] == 1 and three["cost_units"] == 3


def test_skipped_parent_does_not_expose_future_recorded_outcome():
    h = history("r1", "f1", [0, 1])
    out = evaluate_sop(h, SOP(max_attempts_per_experiment=1), budget=10)
    assert out["selected"] == ["a0"] and out["passes"] == 0


def test_sop_search_selects_on_search_not_holdout():
    train = [history("tr", "train", [0, 1])]
    search = [history("se", "search", [1, 0, 0])]
    holdout = [history("ho", "holdout", [0, 0, 1])]
    report = optimize_sop(train, search, holdout, budget=5, max_retry_candidate=3)
    assert report["candidate"]["max_attempts_per_experiment"] == 1
    assert report["holdout"]["candidate"]["mean_passes"] == 0
    assert report["holdout"]["baseline"]["mean_passes"] == 1
    assert report["status"] == "REPLAY_ONLY"


def test_split_overlap_rejected():
    h = history("same", "same", [1])
    with pytest.raises(ValueError, match="disjoint"):
        optimize_sop([h], [h], [history("h", "h", [1])], budget=1)


def test_malformed_or_counterfactual_history_rejected():
    h = history("r", "f", [1])
    h["support"] = "simulated"
    with pytest.raises(ValueError, match="unsupported"):
        evaluate_sop(h, SOP(), budget=1)


def test_candidate_report_must_be_hash_valid(tmp_path):
    engine = create_demo(tmp_path / "engine", "square")
    report = optimize_sop([history("tr", "train", [0, 1])], [history("se", "search", [1])],
                          [history("ho", "holdout", [0])], budget=2)
    assert record_sop_candidate(engine, report)
    broken = {**report, "candidate": {**report["candidate"], "max_attempts_per_experiment": 99}}
    with pytest.raises(ValueError):
        record_sop_candidate(engine, broken)


def test_mandatory_preflight_gates_cannot_evolve():
    with pytest.raises(ValueError):
        SOP(preflight_order=("authorization", "budget"))
