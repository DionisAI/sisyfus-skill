from __future__ import annotations

from pathlib import Path

from sisyfus.activity import render_activity_monitor, start_activity
from sisyfus.research_v2.observatory import render_observatory
from sisyfus.research_v2.workspace import ResearchWorkspace
from sisyfus.ui_theme import ARENA_THEME_CSS


def _workspace(tmp_path: Path) -> ResearchWorkspace:
    path = tmp_path / ".sisyfus" / "research" / "runs" / "research-flicker-test"
    (path / "report").mkdir(parents=True)
    return ResearchWorkspace(
        root=tmp_path,
        research_id="research-flicker-test",
        path=path,
    )


def test_feed_rows_do_not_replay_entry_animation_on_polling_rerender(
    tmp_path: Path,
) -> None:
    start_activity(tmp_path, title="Stable Intake feed")
    bootstrap = render_activity_monitor(tmp_path).read_text(encoding="utf-8")

    workspace = _workspace(tmp_path)
    render_observatory(
        workspace,
        {"topic": "Stable Arena feed"},
        events=[],
        frames=[],
    )
    arena = workspace.report_path.read_text(encoding="utf-8")

    # The bootstrap clock/heartbeat loop may call render every 500 ms and the
    # full Observatory may replace projections as snapshots advance. Base feed
    # rows must therefore be motionless; only a deliberately tagged new event
    # is allowed to run the one-shot entry animation.
    rule = ".feed-row { animation:none !important; }"
    opt_in = ".feed-row.feed-new { animation:feedin .35s var(--ease-out) !important; }"
    assert rule in ARENA_THEME_CSS
    assert opt_in in ARENA_THEME_CSS
    for document in (bootstrap, arena):
        assert rule in document
        assert opt_in in document


def test_intake_polling_still_updates_clock_without_visual_reentry(
    tmp_path: Path,
) -> None:
    start_activity(tmp_path, title="Heartbeat without flicker")
    document = render_activity_monitor(tmp_path).read_text(encoding="utf-8")

    assert "setInterval(render,500);" in document
    assert ".feed-row { animation:none !important; }" in document
