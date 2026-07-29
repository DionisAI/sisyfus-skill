from pathlib import Path

from sisyfus.goal import write_goal_template
from sisyfus.orchestrator import SisyfusRunner
from sisyfus.scaffold import init_project
from sisyfus.utils import read_jsonl


def test_runner_passes_and_distills_fact(tmp_path: Path):
    init_project(tmp_path)
    goal_path = tmp_path / ".sisyfus" / "goals" / "pass.json"
    write_goal_template(goal_path, goal_id="pass", objective="pass command", commands=["printf ok"], max_rounds=1)
    final = SisyfusRunner(tmp_path).run(goal_path, adapter_name="mock", apply_distill=True)
    assert final["status"] == "PASSED"
    facts = read_jsonl(tmp_path / ".sisyfus" / "memory" / "facts.jsonl")
    assert any("pass" in f.get("claim", "") for f in facts)


def test_runner_failing_goal_creates_open_task(tmp_path: Path):
    init_project(tmp_path)
    goal_path = tmp_path / ".sisyfus" / "goals" / "fail.json"
    write_goal_template(goal_path, goal_id="fail", objective="fail command", commands=["false"], max_rounds=1)
    final = SisyfusRunner(tmp_path).run(goal_path, adapter_name="mock", apply_distill=True)
    assert final["status"] in {"FAILED", "NEEDS_HUMAN"}
    tasks = read_jsonl(tmp_path / ".sisyfus" / "tasks" / "open.jsonl")
    assert tasks
    assert tasks[0]["goal_id"] == "fail"
