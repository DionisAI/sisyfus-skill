from __future__ import annotations

import tomllib
from pathlib import Path

import sisyfus


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.8.0"
TAG = "v0.8.0"


def test_release_version_is_consistent() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == VERSION
    assert sisyfus.__version__ == VERSION


def test_release_install_pins_and_notes_are_current() -> None:
    for relative in ("README.md", "README.zh-CN.md", "SKILL.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert f"@{TAG}" in text
        assert "@v0.7.4" not in text

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {VERSION} — 2026-08-20" in changelog
    assert "## Unreleased" not in changelog.split("## 0.7.4", 1)[0]

    notes = ROOT / f"RELEASE_NOTES_v{VERSION}.md"
    assert notes.exists()
    assert f"# Sisyfus {TAG}" in notes.read_text(encoding="utf-8")


def test_packaged_skill_matches_release_skill() -> None:
    canonical = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    packaged = (
        ROOT / "src" / "sisyfus" / "skill_assets" / "sisyfus-research" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert packaged == canonical
