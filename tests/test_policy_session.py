from pathlib import Path

from sisyfus.cli import main
from sisyfus.goal import write_goal_template
from sisyfus.orchestrator import SisyfusRunner
from sisyfus.scaffold import init_project
from sisyfus.utils import read_json, read_jsonl, write_json


def test_model_policy_routes_frontier_and_program(tmp_path: Path):
    init_project(tmp_path)
    assert main(["model", "route", "--root", str(tmp_path), "--task-type", "exploratory", "--role", "explorer"]) == 0
    from sisyfus.model_policy import resolve_model_route

    exploratory = resolve_model_route(tmp_path, task_type="exploratory", role="explorer")
    assert exploratory["profile_id"] == "frontier_exploration"
    assert exploratory["allow_agent"] is True
    assert exploratory["reasoning"] == "xhigh"

    monitoring = resolve_model_route(tmp_path, task_type="monitoring", role="implementer")
    assert monitoring["profile_id"] == "deterministic_program"
    assert monitoring["allow_agent"] is False
    assert monitoring["model"] == "none"


def test_run_records_compact_session_without_promoting_memory(tmp_path: Path):
    init_project(tmp_path)
    goal_path = tmp_path / ".sisyfus" / "goals" / "pass.json"
    write_goal_template(goal_path, goal_id="pass", objective="pass command", commands=["printf ok"], max_rounds=1)
    final = SisyfusRunner(tmp_path).run(goal_path, adapter_name="mock", apply_distill=False)
    assert final["status"] == "PASSED"
    assert Path(final["session_compact_path"]).exists()
    sessions = read_jsonl(tmp_path / ".sisyfus" / "sessions" / "index.jsonl")
    assert len(sessions) == 1
    facts = read_jsonl(tmp_path / ".sisyfus" / "memory" / "facts.jsonl")
    assert facts == []


def test_monitoring_goal_skips_agent_roles_by_policy(tmp_path: Path):
    init_project(tmp_path)
    (tmp_path / "log.txt").write_text("alpha beta gamma", encoding="utf-8")
    goal_path = tmp_path / ".sisyfus" / "goals" / "monitor.json"
    goal = {
        "id": "monitor",
        "objective": "Check log contains beta",
        "task_type": "monitoring",
        "monitors": [{"id": "file.contains", "params": {"file": "log.txt", "pattern": "beta"}}],
        "agents": {"explorer": {"enabled": True}, "implementer": {"enabled": True}},
        "loop": {"max_rounds": 1},
    }
    write_json(goal_path, goal)
    final = SisyfusRunner(tmp_path).run(goal_path, adapter_name="mock")
    assert final["status"] == "PASSED"
    assert final["agent_results"] == []
    assert {x["reason"] for x in final["skipped_agents"]} == {"model_policy_disallows_agent"}
