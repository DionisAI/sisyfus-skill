from pathlib import Path

from sisyfus.cli import main


def test_research_demo_cli(tmp_path: Path):
    assert main(["init", "--root", str(tmp_path)]) == 0
    assert main(["research", "demo", "--root", str(tmp_path)]) == 0
    assert main(["research", "replay", "latest", "--root", str(tmp_path)]) == 0
    assert main(["research", "status", "latest", "--root", str(tmp_path)]) == 0
    reports = list((tmp_path / ".sisyfus" / "research" / "runs").glob("*/report/index.html"))
    assert len(reports) == 1
