"""Research progress UI: live status lives in the shared shell and speaks plainly."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from sisyfus.activity import (
    ActivityTracker,
    activity_overlay_html,
    progress_signal_path,
    read_activity,
    render_activity_monitor,
    start_activity,
)
from sisyfus.research_v2.observatory import _TEMPLATE, _json_for_script, render_observatory
from sisyfus.research_v2.workspace import ResearchWorkspace


def _workspace(tmp_path: Path) -> ResearchWorkspace:
    path = tmp_path / ".sisyfus" / "research" / "runs" / "research-progress-ui"
    (path / "report").mkdir(parents=True)
    return ResearchWorkspace(root=tmp_path, research_id="research-progress-ui", path=path)


def test_refuted_and_exhausted_runs_are_final() -> None:
    final = re.search(r"const FINAL_STATUSES = new Set\(\[([^\]]*)\]\)", _TEMPLATE)
    assert final
    for status in ("'REFUTED'", "'EXHAUSTED'", "'SOLVED'", "'BUDGET_EXHAUSTED'"):
        assert status in final.group(1)
    assert "rs_EXHAUSTED:" in _TEMPLATE


def test_non_finite_payload_still_boots_and_failures_are_visible(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    render_observatory(workspace, {"topic": "NaN metric", "metric": float("nan")}, events=[], frames=[])
    document = workspace.report_path.read_text(encoding="utf-8")
    # Browser-facing JSON carries non-finite metrics as text; older pages with
    # bare NaN still parse leniently instead of leaving a blank workbench.
    assert '"metric": "NaN"' in document
    assert '"metric": NaN' not in document
    snapshot = json.loads(workspace.report_snapshot_path.read_text(encoding="utf-8"),
                          parse_constant=lambda token: pytest.fail(f"non-JSON constant {token}"))
    assert snapshot["snapshot"]["metric"] == "NaN"
    assert "DATA = parseLenient(" in document
    assert "parseLenient(body)" in document
    assert "function showBootError" in document and "boot_error:" in document
    assert '<span id="liveText">LIVE</span>' not in document


def test_live_activity_is_docked_in_the_shell_and_scoped_to_the_run() -> None:
    overlay = activity_overlay_html({"title": "A research run", "status": "RUNNING"})
    assert "document.querySelector('.topbar .top-actions')" in overlay
    assert "A.research_id === page.id" in overlay
    assert "monitor_mode !== 'bootstrap'" in overlay
    assert "SF_LABELS" in overlay and "__SF_LABELS__" not in overlay
    # Raw enums and ids stay in a closed technical disclosure, not the headline.
    assert '<details class="sf-tech">' in overlay
    assert "position:fixed; right:16px; bottom:16px" not in overlay.split("#sf-live-hud:not(.sf-docked)", 1)[0]


def test_bootstrap_progress_counts_setup_steps_in_plain_language(tmp_path: Path) -> None:
    start_activity(tmp_path, title="Plain setup")
    document = render_activity_monitor(tmp_path).read_text(encoding="utf-8")
    assert "SF_LABELS" in document and "__SF_LABELS__" not in document
    assert "function readySteps()" in document
    assert "PRE-RUN" not in document
    assert "HEARTBEAT —" not in document
    assert 'id="signalFill"' not in document
    assert ".deck button[disabled],.tabs { display:none; }" in document


def test_script_payload_is_strict_json_for_non_finite_values() -> None:
    encoded = _json_for_script({"a": float("nan"), "b": [float("inf"), -float("inf")], "c": "</script>"})
    decoded = json.loads(encoded, parse_constant=lambda token: pytest.fail(f"non-JSON constant {token}"))
    assert decoded == {"a": "NaN", "b": ["Infinity", "-Infinity"], "c": "</script>"}
    assert "</script>" not in encoded


def test_non_finite_progress_signal_does_not_stop_heartbeats(tmp_path: Path) -> None:
    start_activity(tmp_path, title="NaN progress")
    tracker = ActivityTracker(tmp_path, phase="EXECUTING", operation="research.execute",
                              message="Running.", heartbeat_interval=0.03).start()
    progress_signal_path(tmp_path).write_text('{"current": NaN, "total": 5, "percent": Infinity}', encoding="utf-8")
    first = read_activity(tmp_path)["heartbeat_at"]
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and read_activity(tmp_path)["heartbeat_at"] == first:
        time.sleep(0.02)
    observed = read_activity(tmp_path)
    assert observed["heartbeat_at"] > first
    assert observed["progress"]["current"] is None and observed["progress"]["percent"] is None
    assert tracker._thread is not None and tracker._thread.is_alive()
    assert tracker.finish()["status"] == "COMPLETED"
