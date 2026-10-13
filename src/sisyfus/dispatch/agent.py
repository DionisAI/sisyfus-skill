"""Headless research agent: command construction and stream-json event projection."""
from __future__ import annotations

import json
import re
from typing import Any

from .config import DispatchConfig

BASE_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "TodoWrite", "Skill"]
WEB_TOOLS = ["WebFetch", "WebSearch"]

SYSTEM_PROMPT = """You were dispatched from the operator's phone through Sisyfus Dispatch.
Work only inside the current project directory and use the sisyfus-research skill to run
this study end to end: Mission Control, clarification, TaskSpec, experiments, verdicts and
finalize. You run headless: nobody can answer you in the middle of a turn. If the
clarification gate needs the operator, record it with `sisyfus research monitor-clarify`,
then end your turn by writing the open questions as a short numbered list in the operator's
language. The operator will reply from the phone and this same session will resume.
End every turn with a brief plain-language status: what ran, current claim verdicts, and
what happens next. Never print credentials or tokens."""

# Credential-shaped values only: prose such as "basic momentum" or "Max tokens: 4096" stays readable.
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{16,}")
_SECRET = re.compile(r"(?i)([A-Z0-9_]*(?:token|secret|passw(?:or)?d|api[_-]?key|authorization)[A-Z0-9_]*)"
                     r"([\"']?\s*[:=]\s*)(\"[^\"\n]*\"|'[^'\n]*'|[^\s\"',}]+)")
_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")


def _mask(match: re.Match[str]) -> str:
    name, sep, value = match.group(1), match.group(2), match.group(3)
    bare = value.strip("\"'")
    if bare.lower() in {"<redacted>", "bearer", "basic"} or _NUMBER.match(bare):
        return match.group(0)
    quote = value[0] if value[:1] in {'"', "'"} else ""
    return f"{name}{sep}{quote}<redacted>{quote}"


def redact(text: str) -> str:
    """Mask credentials before agent output reaches the phone (bearer first, then key=value forms)."""
    return _SECRET.sub(_mask, _BEARER.sub(lambda m: f"{m.group(1)} <redacted>", text))


def first_prompt(brief: str) -> str:
    return f"研究任务（来自手机派发）：\n\n{brief.strip()}\n"


def build_command(config: DispatchConfig, *, resume_session: str | None = None) -> list[str]:
    """Agent argv. The prompt itself is written to stdin, never placed in argv."""
    tools = BASE_TOOLS + (WEB_TOOLS if config.allow_web else [])
    command = [*config.agent_command, "-p", "--output-format", "stream-json", "--verbose",
               "--permission-mode", "acceptEdits", "--permission-prompts", "none",
               "--max-budget-usd", f"{config.max_budget_usd:g}",
               "--append-system-prompt", SYSTEM_PROMPT]
    if config.model:
        command += ["--model", config.model]
    if resume_session:
        command += ["--resume", resume_session]
    return command + ["--allowedTools", *tools]


def _tool_summary(name: str, data: dict[str, Any]) -> str:
    if name == "Bash":
        return str(data.get("description") or data.get("command") or "")
    if name in {"Read", "Write", "Edit"}:
        return str(data.get("file_path") or "").rsplit("/", 1)[-1]
    if name == "Skill":
        return str(data.get("skill") or data.get("command") or "")
    if name in {"Glob", "Grep"}:
        return str(data.get("pattern") or "")
    if name in {"WebFetch", "WebSearch"}:
        return str(data.get("url") or data.get("query") or "")
    return ""


def project_line(line: str) -> list[dict[str, Any]]:
    """Map one stream-json line to zero or more compact, redacted events for the phone."""
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        return []
    if not isinstance(message, dict):
        return []
    kind = message.get("type")
    if kind == "system" and message.get("subtype") == "init":
        return [{"kind": "session", "session_id": message.get("session_id"), "model": message.get("model")}]
    if kind == "assistant":
        events = []
        for block in (message.get("message") or {}).get("content") or []:
            if block.get("type") == "text" and str(block.get("text") or "").strip():
                events.append({"kind": "text", "text": redact(str(block["text"]))[:6000]})
            elif block.get("type") == "tool_use":
                name = str(block.get("name") or "tool")
                summary = _tool_summary(name, block.get("input") or {})
                events.append({"kind": "tool", "name": name, "summary": redact(summary)[:240]})
        return events
    if kind == "result":
        return [{
            "kind": "result",
            "ok": not bool(message.get("is_error")),
            "subtype": message.get("subtype"),
            "text": redact(str(message.get("result") or ""))[:6000],
            "session_id": message.get("session_id"),
            "cost_usd": message.get("total_cost_usd"),
            "turns": message.get("num_turns"),
            "duration_ms": message.get("duration_ms"),
        }]
    return []
