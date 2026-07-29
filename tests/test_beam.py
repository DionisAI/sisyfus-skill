from __future__ import annotations

from pathlib import Path

from sisyfus.beam import BeamRunner, BeamStore
from sisyfus.cli import main
from sisyfus.dashboard import dashboard_state
from sisyfus.scaffold import init_project
from sisyfus.utils import write_json


def _beam_goal(root: Path, *, width: int = 2, max_total: int = 2) -> Path:
    goal_path = root / ".sisyfus" / "goals" / "crypto-factor.beam.json"
    write_json(
        goal_path,
        {
            "id": "crypto-factor",
            "objective": "Research a crypto cross-sectional strategy using bounded branch search.",
            "task_type": "beam_research",
            "done_when": {"commands": ["printf ok"]},
            "loop": {"max_rounds": 1},
            "beam": {
                "enabled": True,
                "id": "crypto-factor-beam",
                "width": width,
                "max_depth": 1,
                "max_children_per_node": 3,
                "max_sessions_total": max_total,
                "directions": [
                    {"id": "network", "title": "Search known factors", "objective": "Collect known crypto factor ideas.", "task_type": "information_collection", "priority": "P1"},
                    {"id": "hand", "title": "Handcraft factors", "objective": "Generate handcrafted factor hypotheses.", "task_type": "factor_research", "priority": "P1"},
                    {"id": "formula", "title": "Formula mining", "objective": "Explore AlphaGPT-style formula factor variants.", "task_type": "formula_alpha_mining", "priority": "P2"},
                ],
            },
        },
    )
    return goal_path


def test_beam_runs_bounded_child_sessions(tmp_path: Path) -> None:
    init_project(tmp_path)
    goal_path = _beam_goal(tmp_path, width=2, max_total=2)
    summary = BeamRunner(tmp_path).run(goal_path, adapter_name="mock")
    assert summary["status"] == "COMPLETED"
    assert summary["session_count"] == 2
    detail = BeamStore(tmp_path).load_beam(summary["beam_id"])
    branch_nodes = [n for n in detail["nodes"] if n["node_id"] != "root"]
    assert len(branch_nodes) == 2
    assert all(n["status"] == "PASSED" for n in branch_nodes)
    assert (tmp_path / ".sisyfus" / "beams" / summary["beam_id"] / "beam.context.md").exists()


def test_beam_state_appears_in_dashboard(tmp_path: Path) -> None:
    init_project(tmp_path)
    summary = BeamRunner(tmp_path).run(_beam_goal(tmp_path), adapter_name="mock")
    state = dashboard_state(tmp_path)
    assert state["stats"]["beam_count"] == 1
    assert state["stats"]["beam_node_count"] >= 3
    assert state["beams"][0]["beam_id"] == summary["beam_id"]
    assert any(n.get("beam_id") == summary["beam_id"] for n in state["beam_nodes"])


def test_beam_cli_template_and_run(tmp_path: Path) -> None:
    assert main(["init", "--root", str(tmp_path)]) == 0
    assert main([
        "beam", "template", "demo-beam", "--root", str(tmp_path), "--objective", "Explore branches", "--command", "printf ok", "--width", "2", "--max-total-sessions", "2"
    ]) == 0
    goal_path = tmp_path / ".sisyfus" / "goals" / "demo-beam.beam.json"
    assert goal_path.exists()
    assert main(["beam", "run", str(goal_path), "--root", str(tmp_path), "--adapter", "mock"]) == 0
    assert main(["beam", "list", "--root", str(tmp_path)]) == 0
