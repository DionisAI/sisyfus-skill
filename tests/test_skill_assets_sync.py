"""The repo root is the canonical skill; the wheel payload must match it exactly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from sync_skill_assets import SKILL_FILES, drift  # noqa: E402


def test_root_skill_and_package_assets_are_identical():
    assert len(SKILL_FILES) >= 6
    assert drift() == [], "run: python3 scripts/sync_skill_assets.py"
