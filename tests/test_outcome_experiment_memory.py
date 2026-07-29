from __future__ import annotations

from pathlib import Path

from sisyfus.cli import main
from sisyfus.experiment_ledger import list_experiments
from sisyfus.utils import write_json
from sisyfus.memory_fsm import MemoryFSMStore
from sisyfus.orchestrator import SisyfusRunner
from sisyfus.outcome import list_outcomes
from sisyfus.scaffold import init_project


def _outcome_goal(root: Path, command: str = "printf ok") -> Path:
    path = root / ".sisyfus" / "goals" / "outcome.json"
    write_json(path, {
        "id": "outcome-pass",
        "objective": "Pass command and rubric",
        "task_type": "implementation",
        "done_when": {"commands": [command]},
        "loop": {"max_rounds": 1},
        "outcome": {"enabled": True, "rubric_id": "coding_goal_v1", "max_iterations": 1},
    })
    return path


def test_outcome_grade_records_provider_and_memory_fsm(tmp_path: Path) -> None:
    init_project(tmp_path)
    goal = _outcome_goal(tmp_path)
    final = SisyfusRunner(tmp_path).run(goal, adapter_name="mock", apply_distill=True)
    assert final["status"] == "PASSED"
    assert final["latest_outcome"]["status"] == "PASSED"
    outcomes = list_outcomes(tmp_path)
    assert outcomes and outcomes[0]["rubric_id"] == "coding_goal_v1"
    assert (tmp_path / ".sisyfus" / "provider" / "usage.jsonl").exists()
    coverage = MemoryFSMStore(tmp_path).coverage()
    assert coverage["total"] >= 1
    assert coverage["verified_memory_coverage"] > 0


def test_experiment_ledger_records_factor_research(tmp_path: Path) -> None:
    init_project(tmp_path)
    path = tmp_path / ".sisyfus" / "goals" / "factor.json"
    write_json(path, {
        "id": "factor-exp",
        "objective": "Research a formula factor",
        "task_type": "factor_research",
        "done_when": {"commands": ["printf ok"]},
        "loop": {"max_rounds": 1},
        "outcome": {"enabled": True, "rubric_id": "research_outcome_v1", "pass_threshold": 0.1, "max_iterations": 1},
        "experiment_policy": {"enabled": True},
    })
    final = SisyfusRunner(tmp_path).run(path, adapter_name="mock")
    assert final.get("experiment")
    items = list_experiments(tmp_path)
    assert items
    assert items[0]["goal_id"] == "factor-exp"


def test_memory_fsm_verify_and_promote(tmp_path: Path) -> None:
    init_project(tmp_path)
    store = MemoryFSMStore(tmp_path)
    item = store.add(state="failure_note", claim="Need to verify pytest command", domain="tests")
    verified = store.verify(item["memory_id"], command="python -c 'print(1)'", workdir=tmp_path)
    assert verified["status"] == "PASSED"
    promoted = store.promote(item["memory_id"], rule="Use python command as a verified smoke check.")
    assert promoted["state"] == "general_rule"
    assert store.coverage()["verified_memory_coverage"] > 0


def test_new_cli_commands_smoke(tmp_path: Path) -> None:
    assert main(["init", "--root", str(tmp_path)]) == 0
    assert main(["rubric", "list", "--root", str(tmp_path)]) == 0
    assert main(["memory", "fsm-add", "CLI memory smoke", "--root", str(tmp_path)]) == 0
    assert main(["memory", "fsm-coverage", "--root", str(tmp_path)]) == 0
    assert main(["experiment", "summary", "--root", str(tmp_path)]) == 0
    assert main(["provider", "summary", "--root", str(tmp_path)]) == 0
