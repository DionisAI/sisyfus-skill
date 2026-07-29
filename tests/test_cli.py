from pathlib import Path

from sisyfus.cli import main


def test_cli_init_goal_eval(tmp_path: Path):
    assert main(["init", "--root", str(tmp_path)]) == 0
    assert (tmp_path / ".sisyfus" / "memory" / "index.md").exists()
    assert main(["goal", "new", "demo", "--root", str(tmp_path), "--objective", "demo", "--command", "printf ok"]) == 0
    assert (tmp_path / ".sisyfus" / "goals" / "demo.json").exists()
    assert main(["eval", "run", "--root", str(tmp_path)]) == 0
