import json
from pathlib import Path

from sisyfus.research_v2.engine import ResearchEngine
from sisyfus.scaffold import init_project


def test_command_experiment_and_skill_install(tmp_path: Path):
    init_project(tmp_path)
    skill = tmp_path / ".sisyfus" / "skills" / "sisyfus-research" / "SKILL.md"
    assert skill.exists()
    assert "PASS`, `FAIL`, `INCONCLUSIVE`, `INVALID`, `ERROR" in skill.read_text(encoding="utf-8")

    script = tmp_path / "emit.py"
    script.write_text(
        "import json\nfrom pathlib import Path\nPath('metrics.json').write_text(json.dumps({'score': 0.9}))\nPath('summary.json').write_text('{}')\n",
        encoding="utf-8",
    )
    engine = ResearchEngine.create(
        tmp_path,
        {
            "id": "command",
            "topic": "Command experiment",
            "claims": [{"id": "c", "statement": "Command result passes"}],
            "verification_contracts": [
                {
                    "id": "vc",
                    "target_claim_id": "c",
                    "pass_if": [{"path": "metrics.score", "op": ">=", "value": 0.8}],
                    "fail_if": [{"path": "metrics.score", "op": "<", "value": 0.2}],
                    "required_artifacts": ["summary.json"],
                }
            ],
        },
    )
    engine.propose_experiment(
        {
            "id": "cmd",
            "title": "run command",
            "target_claim_ids": ["c"],
            "contract_id": "vc",
            "context_id": "local",
            "action": {
                "kind": "command",
                "command": "python emit.py",
                "metrics_path": "metrics.json",
                "artifact_paths": ["summary.json"],
            },
            "expected_outcomes": {"pass": "p", "fail": "f", "inconclusive": "i", "invalid": "x"},
        }
    )
    result = engine.execute_experiment("cmd", workdir=tmp_path)
    assert result["verdict"]["status"] == "PASS"
    assert result["snapshot"]["run_status"] == "SOLVED"
    assert json.loads(engine.workspace.report_snapshot_path.read_text(encoding="utf-8"))["snapshot"]["run_status"] == "SOLVED"
