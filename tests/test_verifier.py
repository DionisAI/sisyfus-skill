from pathlib import Path

from sisyfus.goal import create_goal_template
from sisyfus.verifier import verify_goal


def test_verifier_passes_command(tmp_path: Path):
    goal = create_goal_template(goal_id="pass", objective="pass", commands=["printf ok"], max_rounds=1)
    result = verify_goal(goal, workdir=tmp_path, run_dir=tmp_path)
    assert result["status"] == "PASSED"


def test_verifier_fails_command(tmp_path: Path):
    goal = create_goal_template(goal_id="fail", objective="fail", commands=["false"], max_rounds=1)
    result = verify_goal(goal, workdir=tmp_path, run_dir=tmp_path)
    assert result["status"] == "FAILED"
    assert result["failed_command_count"] == 1


def test_verifier_uncertain_without_commands(tmp_path: Path):
    goal = create_goal_template(goal_id="uncertain", objective="uncertain", commands=[], max_rounds=1)
    result = verify_goal(goal, workdir=tmp_path, run_dir=tmp_path)
    assert result["status"] == "UNCERTAIN"
