from __future__ import annotations

import json
import sys
from pathlib import Path

from sisyfus.autonomy.adapters import CommandPlanner, JsonInboxSensor, RunbookPlanner
from sisyfus.autonomy.cli import main


def test_command_planner_reads_context_and_writes_decision(tmp_path: Path):
    script = tmp_path / "planner.py"
    script.write_text(
        """
import json, os
context = json.load(open(os.environ['SISYFUS_AUTONOMY_CONTEXT_PATH'], encoding='utf-8'))
assert context['continuation']['id'] == 'cont-1'
json.dump(
    {'kind': 'EXECUTE', 'capability': 'core.echo', 'arguments': {'value': 'ok'}},
    open(os.environ['SISYFUS_AUTONOMY_RESPONSE_PATH'], 'w', encoding='utf-8'),
)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    planner = CommandPlanner([sys.executable, str(script)], workspace=tmp_path)
    decision = planner({"id": "cont-1", "version": 2}, {"rules": []})
    assert decision.kind == "EXECUTE"
    assert decision.capability == "core.echo"
    assert decision.arguments == {"value": "ok"}


def test_command_planner_rejects_nonzero_exit(tmp_path: Path):
    script = tmp_path / "bad_planner.py"
    script.write_text("raise SystemExit(7)\n", encoding="utf-8")
    planner = CommandPlanner([sys.executable, str(script)], workspace=tmp_path)
    try:
        planner({"id": "cont-1", "version": 2}, {})
    except RuntimeError as exc:
        assert "exited 7" in str(exc)
    else:
        raise AssertionError("nonzero planner exit was accepted")


def test_json_inbox_sensor_supports_batch_and_content_dedupe(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "signals.json").write_text(
        json.dumps(
            {
                "signals": [
                    {
                        "title": "One",
                        "objective": "Verify one",
                        "priority": 3,
                    },
                    {
                        "title": "Two",
                        "objective": "Verify two",
                        "dedupe_key": "explicit-two",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    signals = JsonInboxSensor(inbox).scan({})
    assert len(signals) == 2
    assert signals[0].dedupe_key.startswith("json-inbox:signals.json:0:")
    assert signals[1].dedupe_key == "explicit-two"
    assert signals[0].payload["_inbox_file"] == "signals.json"


def test_runbook_planner_waits_when_exhausted():
    planner = RunbookPlanner([{"kind": "EXECUTE", "capability": "core.echo", "arguments": {"value": 1}}])
    first = planner({"attempt_count": 0}, {})
    exhausted = planner({"attempt_count": 1}, {})
    assert first.kind == "EXECUTE"
    assert exhausted.kind == "WAIT"


def test_cli_submit_and_status(tmp_path: Path, capsys):
    assert main(["--root", str(tmp_path), "init"]) == 0
    capsys.readouterr()
    code = main(
        [
            "--root",
            str(tmp_path),
            "submit",
            "--source",
            "test",
            "--title",
            "Check",
            "--objective",
            "Produce evidence",
            "--dedupe-key",
            "check-1",
        ]
    )
    assert code == 0
    submitted = json.loads(capsys.readouterr().out)
    assert submitted["continuation"]["status"] == "WAITING"
    assert main(["--root", str(tmp_path), "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert len(status["continuations"]) == 1
    assert status["event_chain"]["valid"] is True


def test_cli_run_once_discovers_and_verifies(tmp_path: Path, capsys):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "opportunity.json").write_text(
        json.dumps(
            {
                "source": "test",
                "title": "Echo",
                "objective": "Verify echo",
                "dedupe_key": "echo-cli",
                "priority": 10,
            }
        ),
        encoding="utf-8",
    )
    script = tmp_path / "planner.py"
    script.write_text(
        """
import json, os
json.dump(
    {'kind': 'EXECUTE', 'capability': 'core.echo', 'arguments': {'value': 'healthy'}},
    open(os.environ['SISYFUS_AUTONOMY_RESPONSE_PATH'], 'w', encoding='utf-8'),
)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    code = main(
        [
            "--root",
            str(tmp_path),
            "run",
            "--planner-command",
            f"{sys.executable} {script}",
            "--inbox",
            str(inbox),
            "--once",
            "--idle-sleep",
            "0",
        ]
    )
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["discovery"]["admitted_count"] == 1
    assert result["work"]["evidence"]["verdict"] == "PASS"
