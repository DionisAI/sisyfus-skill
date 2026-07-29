import pytest

from sisyfus.research_v2.models import normalize_contract, normalize_task_spec


def contract(claim_id: str = "c1") -> dict:
    return {
        "id": f"verify-{claim_id}",
        "target_claim_id": claim_id,
        "pass_if": {"all": [{"path": "metrics.ok", "op": "==", "value": True}]},
        "fail_if": {"all": [{"path": "metrics.ok", "op": "==", "value": False}]},
    }


def test_task_spec_builds_default_and_goal_graph():
    spec = normalize_task_spec(
        {
            "id": "demo",
            "topic": "Demo",
            "claims": [
                {"id": "c1", "statement": "One", "required": True},
                {"id": "c2", "statement": "Two", "required": True, "depends_on": ["c1"]},
            ],
            "verification_contracts": [contract("c1"), contract("c2")],
        }
    )
    assert spec["goal_graph"]["root_id"] == "goal-root"
    assert spec["goal_graph"]["nodes"][0]["kind"] == "AND"
    assert spec["stop_policy"]["max_error_attempts_per_experiment"] == 3


def test_task_spec_rejects_claim_dependency_cycle():
    with pytest.raises(ValueError, match="dependency cycle"):
        normalize_task_spec(
            {
                "topic": "cycle",
                "claims": [
                    {"id": "a", "statement": "A", "depends_on": ["b"]},
                    {"id": "b", "statement": "B", "depends_on": ["a"]},
                ],
            }
        )


def test_task_spec_rejects_goal_graph_cycle_and_missing_required_claim():
    with pytest.raises(ValueError, match="goal graph cycle"):
        normalize_task_spec(
            {
                "topic": "cycle",
                "claims": [{"id": "a", "statement": "A"}],
                "goal_graph": {
                    "root_id": "root",
                    "nodes": [
                        {"id": "root", "kind": "AND", "children": ["loop"]},
                        {"id": "loop", "kind": "OR", "children": ["root"]},
                        {"id": "a", "kind": "CLAIM", "claim_id": "a"},
                    ],
                },
            }
        )
    with pytest.raises(ValueError, match="not reachable"):
        normalize_task_spec(
            {
                "topic": "missing",
                "claims": [
                    {"id": "a", "statement": "A"},
                    {"id": "b", "statement": "B"},
                ],
                "goal_graph": {
                    "root_id": "a-node",
                    "nodes": [{"id": "a-node", "kind": "CLAIM", "claim_id": "a"}],
                },
            }
        )


def test_metric_contract_requires_decisive_pass_and_fail_rules():
    with pytest.raises(ValueError, match="pass_if"):
        normalize_contract({"id": "v", "target_claim_id": "c", "fail_if": [{"path": "x", "op": "==", "value": 0}]})
    with pytest.raises(ValueError, match="fail_if"):
        normalize_contract({"id": "v", "target_claim_id": "c", "pass_if": [{"path": "x", "op": "==", "value": 1}]})



def test_wall_clock_budget_is_enforced():
    from sisyfus.research_v2.reducer import reduce_research
    task = normalize_task_spec({
        "id": "wall", "topic": "wall", "claims": [{"id": "c", "statement": "c"}],
        "verification_contracts": [{"id": "v", "target_claim_id": "c", "pass_if": [{"path": "metrics.ok", "op": "==", "value": True}], "fail_if": [{"path": "metrics.ok", "op": "==", "value": False}]}],
        "budget": {"max_attempts": 5, "max_cost_units": 5, "max_wall_minutes": 1},
    })
    events = [
        {"research_id": "r", "event_id": "e1", "seq": 1, "ts": "2026-01-01T00:00:00Z", "event_type": "RUN_CREATED", "actor": "x", "visibility": "normal", "data": {}, "event_hash": "h1"},
        {"research_id": "r", "event_id": "e2", "seq": 2, "ts": "2026-01-01T00:02:00Z", "event_type": "REPORT_RENDERED", "actor": "x", "visibility": "normal", "data": {}, "event_hash": "h2"},
    ]
    snapshot = reduce_research(task, events)
    assert snapshot["run_status"] == "BUDGET_EXHAUSTED"
    assert snapshot["budget"]["wall_minutes_used"] == 2.0
