"""Read-only projections of a project's research runs and live activity for the phone."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
FINAL_STATUSES = {"SOLVED", "REFUTED", "EXHAUSTED", "BUDGET_EXHAUSTED", "FAILED", "BLOCKED", "CANCELLED"}
_OBSERVATORY_FILES = {
    "index.html": ("report", "index.html", "text/html; charset=utf-8"),
    "snapshot.json": ("report", "snapshot.json", "application/json; charset=utf-8"),
}
_LIVE_FILES = {
    "activity.json": "activity.json",
    "activity-events.json": "activity-events.json",
}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def runs_dir(project: Path) -> Path:
    return project / ".sisyfus" / "research" / "runs"


def run_path(project: Path, research_id: str) -> Path:
    if not _RUN_ID.match(research_id or ""):
        raise LookupError("invalid research id")
    base = runs_dir(project).resolve()
    candidate = (base / research_id).resolve()
    if candidate.parent != base or not candidate.is_dir():
        raise LookupError("unknown research run")
    return candidate


def _claims(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"id": claim_id, "label": claim.get("label") or claim_id, "status": claim.get("status") or "OPEN",
         "statement": claim.get("statement") or "", "required": bool(claim.get("required", True)),
         "critical": bool(claim.get("critical"))}
        for claim_id, claim in (snapshot.get("claims") or {}).items()
    ]


def _budget(snapshot: dict[str, Any]) -> dict[str, Any]:
    budget = snapshot.get("budget") or {}
    return {key: budget.get(key) for key in (
        "attempts_committed", "max_attempts", "cost_units_used", "max_cost_units",
        "wall_minutes_used", "max_wall_minutes")}


def run_summary(project: Path, research_id: str) -> dict[str, Any]:
    path = run_path(project, research_id)
    snapshot = _read_json(path / "snapshot.json") or {}
    status = snapshot.get("run_status") or "UNKNOWN"
    return {
        "research_id": research_id,
        "topic": snapshot.get("topic") or research_id,
        "run_status": status,
        "final": status in FINAL_STATUSES,
        "terminal_assessment": snapshot.get("terminal_assessment"),
        "progress": snapshot.get("progress") or {},
        "claims": [{k: c[k] for k in ("id", "label", "status")} for c in _claims(snapshot)],
        "created_at": snapshot.get("created_at"),
        "updated_at": snapshot.get("updated_at"),
        "has_report": (path / "report" / "index.html").is_file(),
    }


def run_detail(project: Path, research_id: str) -> dict[str, Any]:
    path = run_path(project, research_id)
    snapshot = _read_json(path / "snapshot.json") or {}
    summary = run_summary(project, research_id)
    waits = [w for w in snapshot.get("waits") or [] if w.get("status") == "PENDING"]
    return {
        **summary,
        "claims": _claims(snapshot),
        "budget": _budget(snapshot),
        "frontier_size": len(snapshot.get("frontier") or []),
        "waiting": len(waits),
        "next_wake_at": snapshot.get("next_wake_at"),
        "last_event_type": snapshot.get("last_event_type"),
        "activity": activity(project, research_id=research_id),
    }


def list_runs(project: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    """Latest index entry per run (append-only index), newest first."""
    index = project / ".sisyfus" / "research" / "index.jsonl"
    latest: dict[str, dict[str, Any]] = {}
    try:
        lines = index.read_text(encoding="utf-8").split("\n")  # not splitlines(): topics may hold U+2028
    except OSError:
        lines = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("research_id"):
            latest[str(item["research_id"])] = item
    ordered = sorted(latest.values(), key=lambda i: str(i.get("updated_at") or i.get("created_at") or ""), reverse=True)
    runs = []
    for item in ordered[:limit]:
        try:
            runs.append(run_summary(project, str(item["research_id"])))
        except LookupError:
            continue
    return runs


def activity(project: Path, *, research_id: str | None = None) -> dict[str, Any] | None:
    """The project's live activity, or None when it belongs to another run."""
    raw = _read_json(project / ".sisyfus" / "live" / "activity.json")
    if not isinstance(raw, dict):
        return None
    if research_id and raw.get("research_id") and raw.get("research_id") != research_id:
        return None
    metadata = raw.get("metadata") or {}
    return {
        "status": raw.get("status"), "phase": raw.get("phase"), "operation": raw.get("operation"),
        "message": raw.get("message"), "detail": raw.get("detail"), "progress": raw.get("progress") or {},
        "heartbeat_at": raw.get("heartbeat_at"), "research_id": raw.get("research_id"),
        "title": raw.get("title"), "task_started_at": raw.get("task_started_at"),
        "clarification_questions": [str(q) for q in metadata.get("clarification_questions") or []],
    }


def observatory_file(project: Path, research_id: str, rel: str) -> tuple[Path, str]:
    """Resolve an Observatory resource for one run; anything else is refused."""
    path = run_path(project, research_id)
    if rel in _OBSERVATORY_FILES:
        folder, name, content_type = _OBSERVATORY_FILES[rel]
        return path / folder / name, content_type
    if rel in _LIVE_FILES:
        return project / ".sisyfus" / "live" / _LIVE_FILES[rel], "application/json; charset=utf-8"
    if rel.startswith("artifact/"):
        candidate = (path / rel[len("artifact/"):]).resolve()
        if candidate != path and path in candidate.parents and candidate.is_file():
            return candidate, ""
    raise LookupError("not an Observatory resource")
