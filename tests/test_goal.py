from pathlib import Path

from sisyfus.goal import load_goal, write_goal_template


def test_goal_template_roundtrip(tmp_path: Path):
    path = tmp_path / "goal.json"
    write_goal_template(path, goal_id="Fix Auth Tests", objective="Fix tests", commands=["printf 1"], max_rounds=4)
    goal = load_goal(path)
    assert goal["id"] == "fix-auth-tests"
    assert goal["objective"] == "Fix tests"
    assert goal["loop"]["max_rounds"] == 4
    assert goal["done_when"]["commands"] == ["printf 1"]
