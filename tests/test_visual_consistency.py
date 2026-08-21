from __future__ import annotations

from pathlib import Path

from sisyfus.activity import activity_index_path, render_activity_monitor, start_activity
from sisyfus.research_v2.observatory import render_observatory
from sisyfus.research_v2.workspace import ResearchWorkspace
from sisyfus.ui_theme import ARENA_THEME_CSS, ARENA_THEME_ID


SHELL_MARKERS = (
    'data-sisyfus-shell="broadcast"',
    '<header class="topbar">',
    '<div class="stage">',
    'class="arena-wrap"',
    'id="arena"',
    '<aside class="rightcol">',
    '<div class="deck">',
    '<div class="caster">',
    '<nav class="tabs">',
    'Sisyfus Research Observatory · Arena',
)


def _workspace(tmp_path: Path) -> ResearchWorkspace:
    path = tmp_path / ".sisyfus" / "research" / "runs" / "research-theme-test"
    (path / "report").mkdir(parents=True)
    return ResearchWorkspace(
        root=tmp_path,
        research_id="research-theme-test",
        path=path,
    )


def test_bootstrap_and_arena_render_the_same_broadcast_shell(tmp_path: Path) -> None:
    start_activity(
        tmp_path,
        title="Unify Mission Control",
        objective="Keep bootstrap and Claim-map presentation continuous.",
    )
    render_activity_monitor(tmp_path)
    bootstrap = activity_index_path(tmp_path).read_text(encoding="utf-8")

    workspace = _workspace(tmp_path)
    render_observatory(
        workspace,
        {"topic": "Unified Arena"},
        events=[],
        frames=[],
    )
    arena = workspace.report_path.read_text(encoding="utf-8")

    for document in (bootstrap, arena):
        assert f'data-sisyfus-theme="{ARENA_THEME_ID}"' in document
        assert "__SISYFUS_THEME__" not in document
        assert "__SISYFUS_THEME_ID__" not in document
        for marker in SHELL_MARKERS:
            assert marker in document

    assert "--arena:oklch(0.17 0.018 75)" in ARENA_THEME_CSS
    assert "--radiant:oklch(0.78 0.17 150)" in bootstrap
    assert "--radiant:oklch(0.78 0.17 150)" in arena


def test_bootstrap_is_an_arena_preflight_map_not_a_separate_splash(tmp_path: Path) -> None:
    start_activity(tmp_path, title="Preflight map")
    document = render_activity_monitor(tmp_path).read_text(encoding="utf-8")

    assert 'class="gate-node' in document
    assert 'id="edges"' in document
    assert 'id="bosses"' in document
    assert 'id="hero"' in document
    assert "Scope" in document
    assert "Terminal objective" in document
    assert "Qualified inputs" in document
    assert "Verifier" in document
    assert "Autonomous run" in document
    assert 'class="sigil"' not in document
    assert 'class="ring"' not in document


def test_full_arena_and_bootstrap_share_theme_source_in_code() -> None:
    root = Path(__file__).resolve().parents[1]
    activity_source = (root / "src" / "sisyfus" / "activity.py").read_text(encoding="utf-8")
    arena_source = (
        root / "src" / "sisyfus" / "research_v2" / "observatory.py"
    ).read_text(encoding="utf-8")

    for source in (activity_source, arena_source):
        assert "ARENA_THEME_CSS" in source
        assert "ARENA_THEME_ID" in source
        assert "__SISYFUS_THEME__" in source
