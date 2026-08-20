from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

from sisyfus.cli import main
from sisyfus.activity import (
    ActivityTracker,
    activity_events_projection_path,
    activity_index_path,
    activity_overlay_html,
    activity_state_path,
    progress_signal_path,
    read_activity,
    render_activity_monitor,
    serve_activity_monitor,
    start_activity,
)


def test_start_activity_creates_bootstrap_monitor(tmp_path: Path) -> None:
    item = start_activity(
        tmp_path,
        title="Build a market-making verifier",
        objective="Produce a backtested strategy with locked completion gates.",
    )

    assert item["task_id"].startswith("task-")
    assert item["phase"] == "INTAKE"
    assert item["status"] == "RUNNING"
    assert activity_state_path(tmp_path).exists()
    assert activity_events_projection_path(tmp_path).exists()
    assert activity_index_path(tmp_path).exists()

    document = activity_index_path(tmp_path).read_text(encoding="utf-8")
    assert "SISYFUS · MISSION CONTROL" in document
    assert "snapshot.json" in document
    assert "setInterval(poll,600)" in document


def test_activity_overlay_is_live_and_game_style(tmp_path: Path) -> None:
    initial = start_activity(tmp_path, title="Live research")
    overlay = activity_overlay_html(initial)

    assert 'id="sf-live-hud"' in overlay
    assert "LIVE MISSION" in overlay
    assert "activity.json" in overlay
    assert "setInterval(pollActivity, 700)" in overlay
    assert "heartbeat" in overlay


def test_tracker_heartbeats_and_consumes_progress_protocol(tmp_path: Path) -> None:
    start_activity(tmp_path, title="Backtest")
    tracker = ActivityTracker(
        tmp_path,
        phase="EXECUTING",
        operation="research.execute",
        message="Running event-driven backtest.",
        heartbeat_interval=0.03,
    ).start()
    progress_signal_path(tmp_path).write_text(
        json.dumps(
            {
                "current": 40,
                "total": 100,
                "label": "events",
                "message": "Replaying market events",
            }
        ),
        encoding="utf-8",
    )

    deadline = time.monotonic() + 1.0
    observed = {}
    while time.monotonic() < deadline:
        observed = read_activity(tmp_path)
        if (observed.get("progress") or {}).get("percent") == 40.0:
            break
        time.sleep(0.02)

    assert observed["status"] == "RUNNING"
    assert observed["message"] == "Replaying market events"
    assert observed["progress"]["percent"] == 40.0
    first_heartbeat = observed["heartbeat_at"]
    time.sleep(0.05)
    assert read_activity(tmp_path)["heartbeat_at"] >= first_heartbeat

    finished = tracker.finish()
    assert finished["status"] == "COMPLETED"
    assert finished["metadata"]["exit_code"] == 0


def test_tracker_records_exception(tmp_path: Path) -> None:
    start_activity(tmp_path, title="Failure path")
    tracker = ActivityTracker(
        tmp_path,
        phase="VERIFYING",
        operation="research.settle",
        message="Applying verifier.",
        heartbeat_interval=0.02,
    ).start()

    error = RuntimeError("verifier unavailable")
    failed = tracker.fail(error)

    assert failed["status"] == "ERROR"
    assert failed["error"] == "RuntimeError: verifier unavailable"


def test_bootstrap_server_serves_live_activity(tmp_path: Path) -> None:
    start_activity(tmp_path, title="Serve monitor")
    server, url = serve_activity_monitor(tmp_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            document = response.read().decode("utf-8")
            assert response.status == 200
            assert "MISSION CONTROL" in document
        with urllib.request.urlopen(
            url.rsplit("/", 1)[0] + "/activity.json",
            timeout=2,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
            assert payload["title"] == "Serve monitor"
            assert response.headers["Cache-Control"].startswith("no-store")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_render_monitor_is_idempotent(tmp_path: Path) -> None:
    first = render_activity_monitor(tmp_path)
    second = render_activity_monitor(tmp_path)

    assert first == second
    assert first.exists()


def test_monitor_start_cli_renders_before_taskspec(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("SISYFUS_AUTO_SERVE", "0")
    monkeypatch.setenv("SISYFUS_AUTO_OPEN", "0")

    assert (
        main(
            [
                "research",
                "monitor-start",
                "--task",
                "Qualify HFT research inputs",
                "--objective",
                "Compile verifier-gated research program",
                "--root",
                str(tmp_path),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "MONITOR_READY"
    assert payload["monitor_url"] is None
    assert Path(payload["monitor_entry"]).exists()
    assert read_activity(tmp_path)["phase"] == "INTAKE"
