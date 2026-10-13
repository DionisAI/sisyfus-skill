"""Frozen UI acceptance: display changes never change deterministic truth."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

from sisyfus.activity import activity_overlay_html
from sisyfus.research_v2.observatory import _TEMPLATE, _json_for_script
from sisyfus.ui_theme import ARENA_THEME_CSS, ARENA_THEME_ID

ROOT = Path(__file__).resolve().parents[1]
FROZEN = json.loads((ROOT / "tests/fixtures/graph_redesign_truth_fingerprints.json").read_text())


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def test_shared_light_workspace_and_accessibility_contract() -> None:
    assert ARENA_THEME_ID == "sisyfus-research-workspace-v2"
    assert "color-scheme: light" in ARENA_THEME_CSS
    combined = ARENA_THEME_CSS + _TEMPLATE
    assert "prefers-reduced-motion" in combined
    assert ":focus-visible" in combined
    for control in ("graphFit", "graphZoomIn", "graphZoomOut", "graphReset"):
        assert f'id="{control}"' in _TEMPLATE
    assert 'role="button"' in _TEMPLATE
    assert 'tabindex="0"' in _TEMPLATE


def test_activity_hud_collapsed_with_accessible_toggle() -> None:
    document = activity_overlay_html({"title": "A research run"})
    assert re.search(r'<aside[^>]*id="sf-live-hud"[^>]*class="[^"]*sf-collapsed', document)
    assert 'aria-expanded="false"' in document
    assert "aria-expanded" in document.split('<script id="sf-activity-script">', 1)[1]


def test_hostile_claim_payload_remains_script_escaped_and_roundtrips() -> None:
    payload = {"topic": "</script><script>alert('x')</script>",
               "claims": {"中文": {"label": "<img src=x onerror=alert(1)> & 盈利？"}}}
    encoded = _json_for_script(payload)
    assert "</script>" not in encoded
    assert json.loads(encoded) == payload
    assert "const esc =" in _TEMPLATE


@pytest.mark.skipif(sys.version_info < (3, 13),
                    reason="fingerprints are ast.dump snapshots taken on 3.13+; older dump formats differ")
def test_nonpresentation_python_functions_are_unchanged() -> None:
    # Snapshot retained before native invocation, not an expected value edited
    # after observing a result. Rendering strings are the sole change boundary.
    for rel, allowed in (
        ("src/sisyfus/activity.py", {"activity_overlay_html"}),
        ("src/sisyfus/research_v2/observatory.py", set()),
    ):
        def functions(path):
            tree = ast.parse(path.read_text())
            return {node.name: sha(ast.dump(node, include_attributes=False))
                    for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                    and node.name not in allowed}
        assert functions(ROOT / rel) == FROZEN["python"][rel]


def test_frame_lookup_and_event_derivation_stay_frozen() -> None:
    # UI prose/layout may change; event prefixes and frame lookup may not.
    current = (ROOT / "src/sisyfus/research_v2/observatory.py").read_text()
    for name in ("frameAt", "deriveTimeline"):
        pattern = (rf"^function {name}\([^\n]*\)[^\n]*\{{[^\n]*$" if name == "frameAt"
                   else rf"^function {name}\([^\n]*\)[^\n]*\{{.*?^\}}")
        after = re.search(pattern, current, re.M | re.S)
        assert after, name
        assert sha(after.group()) == FROZEN["javascript"][name], name
