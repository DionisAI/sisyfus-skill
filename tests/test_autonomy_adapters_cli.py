from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from sisyfus.autonomy import (
    AutonomyStore,
    CommandPlanner,
    DiscoveryPolicy,
    JsonInboxSensor,
    OpportunityDiscovery,
    OpportunitySignal,
    RunbookPlanner,
)
from sisyfus.autonomy.cli import main


def test_command_planner_uses_sanitized_environment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TOP_SECRET_TOKEN", "must-not-leak")
    script = tmp_path / "planner.py"
    script.write_text(
        """
import json, os
assert 'TOP_SECRET_TOKEN' not in os.environ
context = json.load(open(os.environ['SISYFUS_AUTONOMY_CONTEXT_PATH'], encoding='utf-8'))
assert context['continuation']['id'] == 'cont-1'
json.dump(
  {'kind': 'EXECUTE', 'reason': 'echo', 'capability': 'core.echo',
   'arguments': {'value': 'ok'}, 'risk_tier': 0},
  open(os.environ['SISYFUS_AUTONOMY_RESPONSE_PATH'], 'w', encoding='utf-8'),
)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    planner = CommandPlanner([sys.executable, str(script)], workspace=tmp_path)
    decision = planner({"id": "cont-1", "version": 2}, {"rules": []})
    assert decision.kind.value == "EXECUTE"
    assert decision.capability == "core.echo"


def test_command_planner_enforces_streamed_output_limit(tmp_path: Path) -> None:
    script = tmp_path / "noisy.py"
    script.write_text(
        "import sys\nsys.stdout.write('x' * 200000)\nsys.stdout.flush()\n",
        encoding="utf-8",
    )
    planner = CommandPlanner(
        [sys.executable, str(script)],
        workspace=tmp_path,
        max_response_bytes=4096,
        timeout_seconds=5,
    )
    with pytest.raises(RuntimeError, match="byte limit"):
        planner({"id": "cont-1", "version": 1}, {})


def test_json_inbox_quarantines_bad_file_and_keeps_good_file(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    quarantine = tmp_path / "quarantine"
    inbox.mkdir()
    (inbox / "bad.json").write_text("{not json", encoding="utf-8")
    (inbox / "good.json").write_text(
        json.dumps(
            {
                "source": "test",
                "title": "Good",
                "objective": "Verify good",
                "dedupe_key": "good-1",
            }
        ),
        encoding="utf-8",
    )
    result = JsonInboxSensor(
        inbox,
        quarantine_dir=quarantine,
    ).scan({})
    assert len(list(result.signals)) == 1
    assert len(result.errors) == 1
    assert (quarantine / "bad.json").exists()
    assert not (inbox / "bad.json").exists()


def test_discovery_rejects_before_persisting_open_opportunity(tmp_path: Path) -> None:
    store = AutonomyStore(tmp_path / "autonomy.sqlite3")

    class Sensor:
        name = "sensor"

        def scan(self, _context):
            return [
                OpportunitySignal(
                    source="denied",
                    title="Denied",
                    objective="Must not become open",
                    dedupe_key="denied-1",
                    priority=100,
                )
            ]

    discovery = OpportunityDiscovery(
        store,
        policy=DiscoveryPolicy(denied_sources=frozenset({"denied"})),
    )
    result = discovery.scan_once([Sensor()])
    assert result["rejected_count"] == 1
    assert store.list_opportunities() == []


def test_discovery_bounds_generator_without_materializing_all(tmp_path: Path) -> None:
    store = AutonomyStore(tmp_path / "autonomy.sqlite3")
    yielded = {"count": 0}

    class Sensor:
        name = "generator"

        def scan(self, _context):
            def generate():
                for index in range(1000):
                    yielded["count"] += 1
                    yield OpportunitySignal(
                        source="test",
                        title=f"Signal {index}",
                        objective="Bounded",
                        dedupe_key=f"signal-{index}",
                    )
            return generate()

    discovery = OpportunityDiscovery(
        store,
        policy=DiscoveryPolicy(max_signals_per_sensor=3),
    )
    result = discovery.scan_once([Sensor()])
    assert result["signal_count"] == 3
    assert yielded["count"] == 4  # one lookahead item detects overflow
    assert any(item["type"] == "SensorLimitExceeded" for item in result["errors"])


def test_runbook_planner_waits_when_exhausted() -> None:
    planner = RunbookPlanner(
        [
            {
                "kind": "EXECUTE",
                "reason": "echo",
                "capability": "core.echo",
                "arguments": {"value": 1},
                "risk_tier": 0,
            }
        ]
    )
    assert planner({"step_index": 0}, {}).kind.value == "EXECUTE"
    assert planner({"step_index": 1}, {}).kind.value == "WAIT"


def test_cli_import_init_submit_status_and_run_once(tmp_path: Path, capsys) -> None:
    assert main(["--root", str(tmp_path), "init"]) == 0
    initialized = json.loads(capsys.readouterr().out)
    assert initialized["schema_version"] == 2

    assert (
        main(
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
        == 0
    )
    submitted = json.loads(capsys.readouterr().out)
    assert submitted["continuation"]["state"] == "READY"

    assert main(["--root", str(tmp_path), "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert len(status["continuations"]) == 1
    assert status["event_chain"]["valid"] is True

    planner_script = tmp_path / "planner.py"
    planner_script.write_text(
        """
import json, os
context = json.load(open(os.environ['SISYFUS_AUTONOMY_CONTEXT_PATH'], encoding='utf-8'))
latest = context['context'].get('latest_evidence')
if latest and latest.get('verdict') == 'PASS':
    decision = {'kind': 'FINISH', 'reason': 'verified', 'evidence_id': latest['id']}
else:
    decision = {'kind': 'EXECUTE', 'reason': 'echo', 'capability': 'core.echo',
                'arguments': {'value': 'healthy'}, 'risk_tier': 0}
json.dump(decision, open(os.environ['SISYFUS_AUTONOMY_RESPONSE_PATH'], 'w', encoding='utf-8'))
""".strip()
        + "\n",
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "run",
                "--planner-command",
                f"{sys.executable} {planner_script}",
                "--once",
                "--idle-sleep",
                "0",
            ]
        )
        == 0
    )
    first = json.loads(capsys.readouterr().out)
    assert first["work"]["detail"]["verdict"] == "PASS"

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "run",
                "--planner-command",
                f"{sys.executable} {planner_script}",
                "--once",
                "--idle-sleep",
                "0",
            ]
        )
        == 0
    )
    second = json.loads(capsys.readouterr().out)
    assert second["work"]["state"] == "SUCCEEDED"


def test_cli_continuous_mode_requires_explicit_unsandboxed_opt_in(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "--root",
            str(tmp_path),
            "run",
            "--planner-command",
            f"{sys.executable} -c pass",
            "--max-cycles",
            "1",
        ]
    )
    assert code == 2
    error = json.loads(capsys.readouterr().err)
    assert "not OS-sandboxed" in error["error"]
