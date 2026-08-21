from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SKILL = ROOT / "src" / "sisyfus" / "skill_assets" / "sisyfus-research" / "SKILL.md"


def test_skill_requires_proactive_clarification_before_research() -> None:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert text.index("## Monitor-first lifecycle") < text.index("## Clarification gate — ask before acting")
    assert text.index("## Clarification gate — ask before acting") < text.index("## Security model")
    assert "**Scope**" in text
    assert "**Objective**" in text
    assert "**Verification**" in text
    assert "Do not begin web research, source collection, coding, experiments, or autonomous execution" in text
    assert "Ask the user one compact batch containing only the unresolved questions" in text
    assert "never ask the same question twice" in text
    assert "sisyfus research monitor-clarify" in text
    assert "sisyfus research monitor-resume" in text
    assert PACKAGE_SKILL.read_text(encoding="utf-8") == text
