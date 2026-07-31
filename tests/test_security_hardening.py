"""Regression tests for the security hardening in the Unreleased changelog:

- an explicit ``--root`` is honored exactly (no upward escape);
- shell-command experiments are confirmation-gated at the CLI;
- command-template interpolation is shell-quoted.
"""

import json
import sys
from pathlib import Path

from sisyfus.cli import main
from sisyfus.paths import find_project_root
from sisyfus.research_v2.engine import ResearchEngine
from sisyfus.runner import adapter_from_name


def _spec():
    return {
        "id": "sec-test",
        "topic": "Security gates",
        "claims": [{"id": "a", "statement": "Claim A holds", "weight": 1}],
        "verification_contracts": [
            {
                "id": "va",
                "target_claim_id": "a",
                "pass_if": [{"path": "metrics.ok", "op": "==", "value": True}],
                "fail_if": [{"path": "metrics.ok", "op": "==", "value": False}],
            }
        ],
        "budget": {"max_attempts": 10, "max_cost_units": 10},
    }


def _command_exp(exp_id="cmd", command=None, wait=None):
    command = command or (
        f"{sys.executable} -c \"import json; json.dump({{'ok': True}}, open('metrics.json', 'w'))\""
    )
    item = {
        "id": exp_id,
        "title": exp_id,
        "target_claim_ids": ["a"],
        "contract_id": "va",
        "context_id": "ctx",
        "action": {"kind": "command", "command": command, "metrics_path": "metrics.json"},
        "expected_outcomes": {"pass": "p", "fail": "f", "inconclusive": "i", "invalid": "x"},
        "cost": {"units": 1},
    }
    if wait:
        item["wait"] = wait
    return item


def test_explicit_root_never_escapes_upward(tmp_path: Path):
    # An ancestor that owns a .sisyfus tree must not capture an explicit root.
    (tmp_path / ".sisyfus").mkdir()
    nested = tmp_path / "downloads" / "project"
    nested.mkdir(parents=True)
    assert find_project_root(nested) == nested
    assert find_project_root(str(nested)) == nested


def test_root_discovery_only_when_unspecified(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    (project / ".sisyfus").mkdir(parents=True)
    subdir = project / "a" / "b"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    assert find_project_root(None) == project
    # ...but an explicit path is still honored verbatim from the same cwd.
    other = tmp_path / "elsewhere"
    other.mkdir()
    assert find_project_root(other) == other


def test_execute_requires_confirmation_non_interactive(tmp_path: Path, capsys):
    engine = ResearchEngine.create(tmp_path, _spec())
    engine.propose_experiment(_command_exp(command=f"touch {tmp_path}/PWNED"))
    capsys.readouterr()

    code = main(["research", "execute", "latest", "cmd", "--root", str(tmp_path)])
    assert code == 4
    assert not (tmp_path / "PWNED").exists()
    err = capsys.readouterr().err
    assert "ConfirmationRequired" in err
    assert "touch" in err  # the exact command is surfaced for review

    # The attempt was never begun: the experiment is still executable afterwards.
    code = main(["research", "execute", "latest", "cmd", "--root", str(tmp_path), "--yes"])
    assert code in {0, 2}  # verdict depends on missing metrics, but the command ran
    assert (tmp_path / "PWNED").exists()


def test_execute_yes_runs_command(tmp_path: Path, capsys):
    engine = ResearchEngine.create(tmp_path, _spec())
    engine.propose_experiment(_command_exp())
    capsys.readouterr()
    code = main(["research", "execute", "latest", "cmd", "--root", str(tmp_path), "--yes"])
    out = capsys.readouterr().out
    assert code == 0
    assert json.loads(out)["verdict"]["status"] == "PASS"


def test_wake_execute_requires_confirmation(tmp_path: Path, capsys):
    future = "2030-01-01T00:00:00Z"
    engine = ResearchEngine.create(tmp_path, _spec())
    engine.propose_experiment(
        _command_exp(command=f"touch {tmp_path}/PWNED", wait={"kind": "time", "not_before": future})
    )
    capsys.readouterr()

    code = main(["research", "wake", "latest", "--root", str(tmp_path), "--now", future, "--execute"])
    assert code == 4
    assert not (tmp_path / "PWNED").exists()
    capsys.readouterr()

    # The refused wake still fired the wait, so the experiment now sits in the
    # frontier; executing it directly (with confirmation) runs the command.
    code = main(["research", "execute", "latest", "cmd", "--root", str(tmp_path), "--yes"])
    assert code in {0, 2}
    assert (tmp_path / "PWNED").exists()


def test_command_adapter_quotes_interpolated_values(tmp_path: Path):
    marker = tmp_path / "PWNED"
    adapter = adapter_from_name("command", command="printf '%s' {goal_id}")
    goal = {"id": f"x$(touch {marker})", "objective": "quoting test", "task_type": "implementation"}
    result = adapter.run(
        role="implementer",
        goal=goal,
        root=tmp_path,
        workdir=tmp_path,
        run_dir=tmp_path / "run",
        round_index=1,
        memory_context="",
    )
    assert result.exit_code == 0
    assert not marker.exists()
    # The goal id reached the command line as inert text.
    stdout = (tmp_path / "run" / "round-01" / "implementer" / "stdout.txt").read_text(encoding="utf-8")
    assert goal["id"] in stdout


def test_custom_monitor_quotes_params(tmp_path: Path):
    from sisyfus.monitor import MonitorRegistry

    marker = tmp_path / "PWNED"
    registry = MonitorRegistry(tmp_path)
    run_dir = tmp_path / "mon"
    run_dir.mkdir()
    result = registry._run_custom(
        {"id": "evil", "command": "printf '%s' {param.note}", "source": "test"},
        params={"note": f"hello $(touch {marker})"},
        workdir=tmp_path,
        run_dir=run_dir,
    )
    assert result["status"] == "PASSED"
    assert not marker.exists()
    stdout = (tmp_path / "mon" / "stdout.txt").read_text(encoding="utf-8")
    assert "$(touch" in stdout  # metacharacters survived as inert text
