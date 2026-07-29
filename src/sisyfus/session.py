from __future__ import annotations

from pathlib import Path
from typing import Any

from .paths import ensure_layout
from .utils import append_jsonl, read_jsonl, truncate_middle, utc_now, write_json


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def summarize_agent_usage(final: dict[str, Any]) -> dict[str, Any]:
    prompt_chars = 0
    output_chars = 0
    calls = 0
    by_role: dict[str, dict[str, int]] = {}
    for result in final.get("agent_results", []) or []:
        calls += 1
        role = str(result.get("role", "unknown"))
        p = int(result.get("prompt_chars", 0) or 0)
        o = int(result.get("output_chars", 0) or 0)
        prompt_chars += p
        output_chars += o
        bucket = by_role.setdefault(role, {"calls": 0, "prompt_chars": 0, "output_chars": 0})
        bucket["calls"] += 1
        bucket["prompt_chars"] += p
        bucket["output_chars"] += o
    return {
        "agent_calls": calls,
        "prompt_chars": prompt_chars,
        "output_chars": output_chars,
        "approx_prompt_tokens": round(prompt_chars / 4),
        "approx_output_tokens": round(output_chars / 4),
        "by_role": by_role,
    }


def build_compact_session_summary(final: dict[str, Any], distill: dict[str, Any], *, max_chars: int = 12000) -> str:
    lines: list[str] = []
    lines.append("# Compact Sisyfus Session Summary")
    lines.append("")
    lines.append(f"Run/session: `{final.get('run_id')}`")
    lines.append(f"Goal: `{final.get('goal_id')}`")
    lines.append(f"Task type: `{final.get('task_type', '-')}`")
    lines.append(f"Status: **{final.get('status', 'UNKNOWN')}**")
    lines.append(f"Reason: {final.get('reason', '-')}")
    beam_meta = final.get("beam") or final.get("beam_node") or {}
    if isinstance(beam_meta, dict) and beam_meta:
        lines.append("")
        lines.append("## Beam")
        lines.append(f"- beam: `{beam_meta.get('beam_id')}` / `{beam_meta.get('beam_run_id')}`")
        lines.append(f"- node: `{beam_meta.get('node_id')}` parent `{beam_meta.get('parent_id')}` depth `{beam_meta.get('depth')}`")
        lines.append(f"- direction: `{beam_meta.get('direction_id')}` {beam_meta.get('title') or ''}")
    lines.append("")
    lines.append("## Model routes")
    routes = final.get("model_routes", {}) or {}
    if routes:
        for role, route in routes.items():
            lines.append(
                f"- `{role}`: profile `{route.get('profile_id')}`, model `{route.get('model')}`, "
                f"reasoning `{route.get('reasoning')}`, allow_agent `{route.get('allow_agent')}`"
            )
    else:
        lines.append("- none")
    lines.append("")
    usage = summarize_agent_usage(final)
    lines.append("## Approx usage")
    lines.append(f"- agent calls: `{usage['agent_calls']}`")
    lines.append(f"- prompt chars: `{usage['prompt_chars']}`")
    lines.append(f"- output chars: `{usage['output_chars']}`")
    lines.append("")
    lines.append("## Durable facts")
    facts = distill.get("facts", []) or []
    if facts:
        for fact in facts[:8]:
            lines.append(f"- {fact.get('claim')}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Failures / warnings")
    failures = distill.get("failures", []) or []
    hypotheses = distill.get("hypotheses", []) or []
    if failures:
        for failure in failures[:8]:
            lines.append(f"- FAILURE: {failure.get('claim')}")
    if hypotheses:
        for hyp in hypotheses[:8]:
            lines.append(f"- UNCERTAIN: {hyp.get('claim')}")
    if not failures and not hypotheses:
        lines.append("- none")
    lines.append("")
    lines.append("## Open follow-up tasks")
    tasks = distill.get("tasks", []) or []
    if tasks:
        for task in tasks[:8]:
            lines.append(f"- {task.get('title') or task.get('task_id')}: {task.get('reason', '')}")
    else:
        lines.append("- none")
    return truncate_middle("\n".join(lines) + "\n", max_chars)


def record_session(root: Path, run_dir: Path, final: dict[str, Any], distill: dict[str, Any], *, max_chars: int = 12000) -> dict[str, Any]:
    sf = ensure_layout(root)
    sessions_dir = sf / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    compact = build_compact_session_summary(final, distill, max_chars=max_chars)
    compact_path = run_dir / "session.compact.md"
    compact_path.write_text(compact, encoding="utf-8")
    usage = summarize_agent_usage(final)
    item = {
        "schema_version": "sisyfus.session_index.v0.6",
        "created_at": utc_now(),
        "session_id": final.get("run_id"),
        "run_id": final.get("run_id"),
        "goal_id": final.get("goal_id"),
        "task_type": final.get("task_type"),
        "status": final.get("status"),
        "reason": final.get("reason"),
        "run_dir": _rel(root, run_dir),
        "compact_path": _rel(root, compact_path),
        "distill_path": _rel(root, run_dir / "distill.json"),
        "model_routes": final.get("model_routes", {}),
        "beam": final.get("beam") or {},
        "usage": usage,
        "beam_node": final.get("beam") or final.get("beam_node") or {},
        "beam_id": (final.get("beam") or final.get("beam_node") or {}).get("beam_id") if (final.get("beam") or final.get("beam_node")) else None,
        "beam_run_id": (final.get("beam") or final.get("beam_node") or {}).get("beam_run_id") if (final.get("beam") or final.get("beam_node")) else None,
        "beam_node_id": (final.get("beam") or final.get("beam_node") or {}).get("node_id") if (final.get("beam") or final.get("beam_node")) else None,
        "beam_parent_node_id": (final.get("beam") or final.get("beam_node") or {}).get("parent_id") if (final.get("beam") or final.get("beam_node")) else None,
        "beam_depth": (final.get("beam") or final.get("beam_node") or {}).get("depth") if (final.get("beam") or final.get("beam_node")) else None,
    }
    append_jsonl(sessions_dir / "index.jsonl", item)
    write_json(sessions_dir / "latest.json", item)
    write_json(run_dir / "session.index_item.json", item)
    return item


def list_sessions(root: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    items = read_jsonl(ensure_layout(root) / "sessions" / "index.jsonl")
    items = list(reversed(items))
    if limit is not None:
        return items[:limit]
    return items


def load_recent_session_context(root: Path, *, limit: int = 3, max_chars: int = 12000) -> str:
    chunks: list[str] = []
    for item in list_sessions(root, limit=limit):
        path = root / str(item.get("compact_path", ""))
        if path.exists():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
        else:
            chunks.append(
                f"# Compact Sisyfus Session Summary\n\nRun/session: `{item.get('run_id')}`\n"
                f"Goal: `{item.get('goal_id')}`\nStatus: **{item.get('status')}**\nReason: {item.get('reason')}\n"
            )
    if not chunks:
        return ""
    text = "\n\n---\n\n".join(chunks)
    return truncate_middle(text, max_chars)
