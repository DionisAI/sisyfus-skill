#!/usr/bin/env python3
"""Sync the canonical repo-root skill into the wheel's package data.

The repository root IS the skill (SKILL.md + references/ + templates/).
`sisyfus init` installs the same files from src/sisyfus/skill_assets/, so that
copy must track the root byte-for-byte. Run this after editing the root skill;
tests/test_skill_assets_sync.py fails the build when the copies drift.
"""
from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "src" / "sisyfus" / "skill_assets" / "sisyfus-research"

SKILL_FILES = [
    "SKILL.md",
    "references/event-model.md",
    "references/task-spec.md",
    "references/verifier-contract.md",
    "templates/experiment.json",
    "templates/research-task.json",
]


def drift() -> list[str]:
    return [
        rel
        for rel in SKILL_FILES
        if not (PACKAGE / rel).is_file() or not filecmp.cmp(REPO / rel, PACKAGE / rel, shallow=False)
    ]


def main() -> int:
    if "--check" in sys.argv:
        stale = drift()
        if stale:
            print("skill assets out of sync:", ", ".join(stale))
            print("run: python3 scripts/sync_skill_assets.py")
            return 1
        print("skill assets in sync")
        return 0
    for rel in SKILL_FILES:
        target = PACKAGE / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, target)
        print("synced", rel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
