from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator, Mapping

from .ui_theme import ARENA_THEME_CSS, ARENA_THEME_ID

_ACTIVITY_SCHEMA = "sisyfus.activity.v1"
_ACTIVITY_EVENTS_SCHEMA = "sisyfus.activity-events.v1"
_MAX_EVENTS = 120

_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()

try:  # pragma: no cover - unavailable on Windows
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore


def _root(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def activity_dir(root: str | Path) -> Path:
    return _root(root) / ".sisyfus" / "live"


def activity_state_path(root: str | Path) -> Path:
    return activity_dir(root) / "activity.json"


def activity_events_path(root: str | Path) -> Path:
    return activity_dir(root) / "activity-events.jsonl"


def activity_events_projection_path(root: str | Path) -> Path:
    return activity_dir(root) / "activity-events.json"


def activity_index_path(root: str | Path) -> Path:
    return activity_dir(root) / "index.html"


def progress_signal_path(root: str | Path) -> Path:
    return activity_dir(root) / "progress.json"


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _elapsed(started_at: str | None, *, now: str) -> float:
    start = _parse_ts(started_at)
    end = _parse_ts(now)
    if start is None or end is None:
        return 0.0
    return round(max(0.0, (end - start).total_seconds()), 3)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
            allow_nan=False,
        )
        + "\n"
    )
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(temporary, path)


def _process_lock(root: Path) -> threading.RLock:
    key = str(root)
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _activity_lock(root: Path) -> Iterator[None]:
    directory = activity_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    with _process_lock(root):
        lock_path = directory / ".activity.lock"
        with lock_path.open("a+b") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _new_task_id(title: str, objective: str) -> str:
    material = f"{title}\n{objective}\n{utc_now()}\n{os.getpid()}\n{time.time_ns()}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    return f"task-{digest}"


def _normalise_progress(value: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(value or {})
    current = raw.get("current")
    total = raw.get("total")
    percent = raw.get("percent")
    if percent is None and isinstance(current, (int, float)) and isinstance(total, (int, float)) and total:
        percent = (float(current) / float(total)) * 100.0
    if isinstance(percent, (int, float)):
        percent = round(max(0.0, min(100.0, float(percent))), 3)
    else:
        percent = None
    return {
        "current": current,
        "total": total,
        "percent": percent,
        "label": str(raw.get("label") or ""),
    }


def _default_activity(root: Path) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": _ACTIVITY_SCHEMA,
        "task_id": None,
        "research_id": None,
        "title": "Awaiting Sisyfus mission",
        "objective": "",
        "phase": "IDLE",
        "status": "IDLE",
        "operation": None,
        "message": "No active research operation.",
        "detail": "",
        "progress": _normalise_progress(None),
        "actor": "system",
        "metadata": {},
        "error": None,
        "task_started_at": None,
        "operation_started_at": None,
        "heartbeat_at": now,
        "updated_at": now,
        "elapsed_seconds": 0.0,
        "revision": 0,
        "root": str(root),
        "pid": None,
    }


def read_activity(root: str | Path) -> dict[str, Any]:
    canonical = _root(root)
    loaded = _read_json(activity_state_path(canonical), None)
    if not isinstance(loaded, dict):
        return _default_activity(canonical)
    return {**_default_activity(canonical), **loaded}


def read_activity_events(root: str | Path) -> list[dict[str, Any]]:
    loaded = _read_json(activity_events_projection_path(root), {})
    events = loaded.get("events") if isinstance(loaded, dict) else []
    if not isinstance(events, list):
        return []
    return [dict(item) for item in events if isinstance(item, dict)]


def _append_activity_event(root: Path, event: Mapping[str, Any]) -> None:
    path = activity_events_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (
        json.dumps(
            dict(event),
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)
    events = read_activity_events(root)
    events.append(dict(event))
    _atomic_write_json(
        activity_events_projection_path(root),
        {
            "schema_version": _ACTIVITY_EVENTS_SCHEMA,
            "events": events[-_MAX_EVENTS:],
        },
    )


def write_activity(
    root: str | Path,
    *,
    task_id: str | None = None,
    research_id: str | None = None,
    title: str | None = None,
    objective: str | None = None,
    phase: str | None = None,
    status: str | None = None,
    operation: str | None = None,
    message: str | None = None,
    detail: str | None = None,
    progress: Mapping[str, Any] | None = None,
    actor: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    error: str | None = None,
    heartbeat: bool = False,
    record_event: bool = True,
) -> dict[str, Any]:
    canonical = _root(root)
    now = utc_now()
    with _activity_lock(canonical):
        current = read_activity(canonical)
        previous_signature = (
            current.get("phase"),
            current.get("status"),
            current.get("operation"),
            current.get("message"),
            current.get("detail"),
            current.get("error"),
            json.dumps(current.get("progress") or {}, sort_keys=True, default=str),
        )
        next_task_id = task_id if task_id is not None else current.get("task_id")
        next_operation = operation if operation is not None else current.get("operation")
        next_status = str(status or current.get("status") or "IDLE").upper()
        task_changed = bool(next_task_id and next_task_id != current.get("task_id"))
        operation_changed = next_operation != current.get("operation")
        task_started_at = (
            now
            if task_changed or not current.get("task_started_at")
            else current.get("task_started_at")
        )
        operation_started_at = (
            now
            if operation_changed
            or (
                next_status == "RUNNING"
                and str(current.get("status") or "").upper() != "RUNNING"
            )
            else current.get("operation_started_at")
        )
        if next_status == "RUNNING" and not operation_started_at:
            operation_started_at = now
        item = {
            **current,
            "schema_version": _ACTIVITY_SCHEMA,
            "task_id": next_task_id,
            "research_id": (
                research_id if research_id is not None else current.get("research_id")
            ),
            "title": str(title if title is not None else current.get("title") or ""),
            "objective": str(
                objective
                if objective is not None
                else current.get("objective") or ""
            ),
            "phase": str(phase or current.get("phase") or "IDLE").upper(),
            "status": next_status,
            "operation": next_operation,
            "message": str(
                message if message is not None else current.get("message") or ""
            ),
            "detail": str(
                detail if detail is not None else current.get("detail") or ""
            ),
            "progress": (
                _normalise_progress(progress)
                if progress is not None
                else _normalise_progress(current.get("progress"))
            ),
            "actor": str(actor or current.get("actor") or "system"),
            "metadata": {
                **dict(current.get("metadata") or {}),
                **dict(metadata or {}),
            },
            "error": error,
            "task_started_at": task_started_at,
            "operation_started_at": operation_started_at,
            "heartbeat_at": now if heartbeat or next_status == "RUNNING" else current.get("heartbeat_at"),
            "updated_at": now,
            "elapsed_seconds": _elapsed(operation_started_at, now=now),
            "revision": int(current.get("revision") or 0) + 1,
            "root": str(canonical),
            "pid": os.getpid(),
        }
        _atomic_write_json(activity_state_path(canonical), item)
        next_signature = (
            item.get("phase"),
            item.get("status"),
            item.get("operation"),
            item.get("message"),
            item.get("detail"),
            item.get("error"),
            json.dumps(item.get("progress") or {}, sort_keys=True, default=str),
        )
        if record_event and next_signature != previous_signature:
            _append_activity_event(
                canonical,
                {
                    "seq": item["revision"],
                    "ts": now,
                    "task_id": item.get("task_id"),
                    "research_id": item.get("research_id"),
                    "phase": item.get("phase"),
                    "status": item.get("status"),
                    "operation": item.get("operation"),
                    "message": item.get("message"),
                    "detail": item.get("detail"),
                    "progress": item.get("progress"),
                    "actor": item.get("actor"),
                    "error": item.get("error"),
                },
            )
        return item


def ensure_activity(root: str | Path, *, title: str | None = None) -> dict[str, Any]:
    canonical = _root(root)
    if activity_state_path(canonical).exists():
        return read_activity(canonical)
    item = write_activity(
        canonical,
        title=title or "Awaiting Sisyfus mission",
        phase="IDLE",
        status="IDLE",
        operation="monitor.bootstrap",
        message="Mission monitor is online.",
        record_event=True,
    )
    render_activity_monitor(canonical)
    return item


def start_activity(
    root: str | Path,
    *,
    title: str,
    objective: str = "",
    task_id: str | None = None,
    actor: str = "skill",
) -> dict[str, Any]:
    canonical = _root(root)
    item = write_activity(
        canonical,
        task_id=task_id or _new_task_id(title, objective),
        research_id=None,
        title=title,
        objective=objective,
        phase="INTAKE",
        status="RUNNING",
        operation="skill.bootstrap",
        message="Mission monitor online. Compiling the research program.",
        detail="Preparing inputs, claims, verifier contracts, and completion conditions.",
        progress={"percent": 0.0, "label": "Research intake"},
        actor=actor,
        metadata={"monitor_mode": "bootstrap"},
    )
    render_activity_monitor(canonical)
    return item


def bind_research(
    root: str | Path,
    research_id: str,
    *,
    title: str | None = None,
    actor: str = "research-engine",
) -> dict[str, Any]:
    return write_activity(
        root,
        research_id=research_id,
        title=title,
        phase="READY",
        status="READY",
        operation="research.ready",
        message="Research program compiled. The autonomous loop is ready.",
        detail=f"Bound live monitor to research run {research_id}.",
        progress={"percent": 0.0, "label": "Research loop"},
        actor=actor,
        metadata={"monitor_mode": "research"},
    )


def update_activity(root: str | Path, **kwargs: Any) -> dict[str, Any]:
    return write_activity(root, **kwargs)


def _read_progress_signal(root: Path) -> tuple[dict[str, Any] | None, str | None, str | None]:
    raw = _read_json(progress_signal_path(root), None)
    if not isinstance(raw, dict):
        return None, None, None
    progress = raw.get("progress") if isinstance(raw.get("progress"), dict) else raw
    return (
        _normalise_progress(progress),
        str(raw.get("message")) if raw.get("message") is not None else None,
        str(raw.get("detail")) if raw.get("detail") is not None else None,
    )


@dataclass
class ActivityTracker:
    root: str | Path
    phase: str
    operation: str
    message: str
    research_id: str | None = None
    detail: str = ""
    actor: str = "engine"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    heartbeat_interval: float = 1.0
    clear_progress_signal: bool = True

    def __post_init__(self) -> None:
        self.root = _root(self.root)
        self.heartbeat_interval = max(0.05, float(self.heartbeat_interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False

    def start(self) -> "ActivityTracker":
        if self._started:
            return self
        if self.clear_progress_signal:
            try:
                progress_signal_path(self.root).unlink(missing_ok=True)
            except OSError:
                pass
        write_activity(
            self.root,
            research_id=self.research_id,
            phase=self.phase,
            status="RUNNING",
            operation=self.operation,
            message=self.message,
            detail=self.detail,
            progress={"percent": None, "label": ""},
            actor=self.actor,
            metadata=self.metadata,
            error=None,
            heartbeat=True,
        )
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"sisyfus-activity-{self.operation[:24]}",
            daemon=True,
        )
        self._thread.start()
        self._started = True
        return self

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.heartbeat_interval):
            progress, message, detail = _read_progress_signal(self.root)
            current = read_activity(self.root)
            write_activity(
                self.root,
                research_id=current.get("research_id") or self.research_id,
                phase=str(current.get("phase") or self.phase),
                status="RUNNING",
                operation=str(current.get("operation") or self.operation),
                message=message or str(current.get("message") or self.message),
                detail=detail or str(current.get("detail") or self.detail),
                progress=progress,
                actor=str(current.get("actor") or self.actor),
                metadata={**dict(self.metadata), **dict(current.get("metadata") or {})},
                error=None,
                heartbeat=True,
                record_event=bool(progress or message or detail),
            )

    def update(
        self,
        *,
        phase: str | None = None,
        message: str | None = None,
        detail: str | None = None,
        progress: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if phase is not None:
            self.phase = phase
        if message is not None:
            self.message = message
        if detail is not None:
            self.detail = detail
        if metadata:
            self.metadata = {**dict(self.metadata), **dict(metadata)}
        return write_activity(
            self.root,
            research_id=self.research_id,
            phase=self.phase,
            status="RUNNING",
            operation=self.operation,
            message=self.message,
            detail=self.detail,
            progress=progress,
            actor=self.actor,
            metadata=self.metadata,
            error=None,
            heartbeat=True,
        )

    def finish(
        self,
        *,
        exit_code: int = 0,
        message: str | None = None,
        detail: str | None = None,
    ) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.heartbeat_interval * 3.0))
        progress, signal_message, signal_detail = _read_progress_signal(self.root)
        current = read_activity(self.root)
        current_operation = str(current.get("operation") or self.operation)
        status = "COMPLETED" if int(exit_code) == 0 else "ATTENTION"
        item = write_activity(
            self.root,
            research_id=current.get("research_id") or self.research_id,
            phase=str(current.get("phase") or self.phase),
            status=status,
            operation=current_operation,
            message=message
            or signal_message
            or (
                f"{current_operation} completed."
                if int(exit_code) == 0
                else f"{current_operation} completed with exit code {exit_code}."
            ),
            detail=detail or signal_detail or str(current.get("detail") or self.detail),
            progress=progress,
            actor=str(current.get("actor") or self.actor),
            metadata={
                **dict(self.metadata),
                **dict(current.get("metadata") or {}),
                "exit_code": int(exit_code),
            },
            error=None,
            heartbeat=True,
        )
        self._started = False
        return item

    def fail(self, exc: BaseException) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.heartbeat_interval * 3.0))
        item = write_activity(
            self.root,
            research_id=self.research_id,
            phase=self.phase,
            status="ERROR",
            operation=self.operation,
            message=f"{self.operation} failed.",
            detail=self.detail,
            actor=self.actor,
            metadata=self.metadata,
            error=f"{type(exc).__name__}: {exc}",
            heartbeat=True,
        )
        self._started = False
        return item

    def __enter__(self) -> "ActivityTracker":
        return self.start()

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> bool:
        if exc is None:
            self.finish()
        else:
            self.fail(exc)
        return False


def activity_overlay_html(initial: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(initial),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).replace("</", "<\\/")
    return f"""
<style id="sf-activity-style">
#sf-live-hud {{
  position:fixed; left:14px; bottom:14px; z-index:2147483000;
  width:min(430px,calc(100vw - 28px)); color:var(--ink,#f4f0e6);
  background:linear-gradient(180deg,var(--panel,rgba(35,31,26,.97)),var(--arena-deep,rgba(19,18,17,.97)));
  border:1px solid var(--line,rgba(224,177,75,.45)); border-top:3px solid var(--gold,#dcae4b);
  box-shadow:var(--shadow-deep,0 18px 60px rgba(0,0,0,.55)); font-family:var(--font-mono,ui-monospace,Menlo,Consolas,monospace);
  backdrop-filter:blur(14px); transition:opacity .2s,transform .2s;
}}
#sf-live-hud.sf-collapsed .sf-activity-body {{ display:none; }}
#sf-live-hud .sf-activity-head {{ display:flex; align-items:center; gap:9px; padding:8px 10px;
  border-bottom:1px solid var(--line,rgba(255,255,255,.09)); background:linear-gradient(180deg,oklch(0.24 0.025 80),oklch(0.18 0.02 78)); font-size:10px; letter-spacing:.14em; font-weight:900; }}
#sf-live-hud .sf-dot {{ width:9px;height:9px;border-radius:50%;background:#67d58c;
  box-shadow:0 0 12px #67d58c;animation:sf-pulse 1.5s ease-in-out infinite; }}
#sf-live-hud[data-status="ERROR"] .sf-dot,#sf-live-hud[data-status="ATTENTION"] .sf-dot {{ background:#ec6a5f;box-shadow:0 0 12px #ec6a5f; }}
#sf-live-hud[data-status="COMPLETED"] .sf-dot,#sf-live-hud[data-status="READY"] .sf-dot,#sf-live-hud[data-status="NEEDS_USER"] .sf-dot {{ background:#e0b14b;box-shadow:0 0 12px #e0b14b;animation:none; }}
#sf-live-hud.sf-stale .sf-dot {{ background:#8e8797;box-shadow:none;animation:none; }}
@keyframes sf-pulse {{50%{{opacity:.35}}}}
#sf-live-hud .sf-toggle {{ margin-left:auto;border:0;background:transparent;color:#aaa;cursor:pointer;font:inherit; }}
#sf-live-hud .sf-activity-body {{ padding:10px 12px 11px; }}
#sf-live-hud .sf-task {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-weight:800;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis; }}
#sf-live-hud .sf-phase-row {{ display:flex;align-items:baseline;gap:8px;margin-top:7px; }}
#sf-live-hud .sf-phase {{ color:var(--gold,#e0b14b);font-weight:900;font-size:13px;letter-spacing:.08em; }}
#sf-live-hud .sf-status {{ margin-left:auto;color:#a9a39a;font-size:10px; }}
#sf-live-hud .sf-operation {{ color:#ddd4c5;font-size:11px;margin-top:5px; }}
#sf-live-hud .sf-message {{ color:#aaa39a;font:11px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin-top:4px; }}
#sf-live-hud .sf-progress {{ height:8px;background:oklch(0.13 0.01 75);border:1px solid var(--line,rgba(255,255,255,.1));margin-top:9px;overflow:hidden; }}
#sf-live-hud .sf-progress i {{ display:block;height:100%;width:0;background:linear-gradient(90deg,var(--radiant,#67d58c),var(--gold,#e0b14b));transition:width .35s; }}
#sf-live-hud .sf-meta {{ display:flex;gap:10px;flex-wrap:wrap;color:#817b73;font-size:9px;margin-top:7px; }}
#sf-live-hud .sf-detail {{ color:#77716a;font-size:9px;margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis; }}
@media (max-width:700px) {{ #sf-live-hud {{ left:8px;bottom:8px;width:calc(100vw - 16px); }} }}
</style>
<aside id="sf-live-hud" data-status="IDLE" aria-live="polite">
  <div class="sf-activity-head"><span class="sf-dot"></span><span>LIVE MISSION</span><button class="sf-toggle" type="button">−</button></div>
  <div class="sf-activity-body">
    <div class="sf-task" id="sf-act-title">Awaiting mission</div>
    <div class="sf-phase-row"><span class="sf-phase" id="sf-act-phase">IDLE</span><span class="sf-status" id="sf-act-status">IDLE</span></div>
    <div class="sf-operation" id="sf-act-operation">monitor.bootstrap</div>
    <div class="sf-message" id="sf-act-message">Mission monitor is online.</div>
    <div class="sf-progress"><i id="sf-act-progress"></i></div>
    <div class="sf-meta"><span id="sf-act-elapsed">00:00</span><span id="sf-act-heartbeat">heartbeat —</span><span id="sf-act-research"></span></div>
    <div class="sf-detail" id="sf-act-detail"></div>
  </div>
</aside>
<script id="sf-activity-script">
(() => {{
  let A = {payload};
  let misses = 0;
  const $ = id => document.getElementById(id);
  const fmt = seconds => {{
    seconds = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
    return h ? `${{String(h).padStart(2,'0')}}:${{String(m).padStart(2,'0')}}:${{String(s).padStart(2,'0')}}`
             : `${{String(m).padStart(2,'0')}}:${{String(s).padStart(2,'0')}}`;
  }};
  const age = ts => ts ? Math.max(0,(Date.now() - Date.parse(ts))/1000) : 9999;
  function render() {{
    const hud = $('sf-live-hud'); if (!hud) return;
    const status = String(A.status || 'IDLE').toUpperCase();
    hud.dataset.status = status;
    const stale = status === 'RUNNING' && age(A.heartbeat_at) > 5;
    hud.classList.toggle('sf-stale', stale || misses >= 3);
    $('sf-act-title').textContent = A.title || 'Sisyfus mission';
    $('sf-act-phase').textContent = String(A.phase || 'IDLE').toUpperCase();
    $('sf-act-status').textContent = stale ? 'STALE' : (misses >= 3 ? 'RECONNECTING' : status);
    $('sf-act-operation').textContent = A.operation || '—';
    $('sf-act-message').textContent = A.message || '';
    $('sf-act-detail').textContent = A.error || A.detail || '';
    const p = A.progress || {{}};
    $('sf-act-progress').style.width = p.percent == null ? (status === 'RUNNING' ? '12%' : '0%') : `${{Math.max(0,Math.min(100,Number(p.percent)))}}%`;
    const base = A.operation_started_at ? Math.max(0,(Date.now()-Date.parse(A.operation_started_at))/1000) : Number(A.elapsed_seconds || 0);
    $('sf-act-elapsed').textContent = `elapsed ${{fmt(base)}}`;
    $('sf-act-heartbeat').textContent = `heartbeat ${{Math.round(age(A.heartbeat_at))}}s`;
    $('sf-act-research').textContent = A.research_id ? `run ${{A.research_id}}` : '';
  }}
  async function pollActivity() {{
    try {{
      const response = await fetch(`activity.json?ts=${{Date.now()}}`, {{cache:'no-store'}});
      if (!response.ok) throw new Error(String(response.status));
      A = await response.json(); misses = 0; render();
    }} catch (_) {{ misses += 1; render(); }}
  }}
  const toggle = document.querySelector('#sf-live-hud .sf-toggle');
  if (toggle) toggle.addEventListener('click', () => {{
    const hud = $('sf-live-hud'); hud.classList.toggle('sf-collapsed');
    toggle.textContent = hud.classList.contains('sf-collapsed') ? '+' : '−';
  }});
  render();
  setInterval(render, 500);
  if (location.protocol === 'http:' || location.protocol === 'https:') {{
    pollActivity(); setInterval(pollActivity, 700);
  }}
}})();
</script>
"""


_BOOTSTRAP_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN" data-sisyfus-theme="__SISYFUS_THEME_ID__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sisyfus Research Observatory · Arena</title>
<style>
__SISYFUS_THEME__

/* The bootstrap page intentionally uses the exact broadcast shell of the
   post-TaskSpec Observatory. Only the data model changes during handoff. */
.topbar { display:flex; align-items:stretch; gap:0; border-bottom:2px solid var(--line);
  background:linear-gradient(180deg,oklch(0.24 0.025 80),oklch(0.18 0.02 78)); }
.scorebox { display:flex; align-items:center; gap:14px; padding:10px 22px; }
.score { font-size:44px; font-weight:900; line-height:1; letter-spacing:-.03em;
  font-variant-numeric:tabular-nums; }
.score.radiant { color:var(--radiant); } .score.amber { color:var(--amber); }
.score-label { font-size:10px; color:var(--muted); }
.vs { align-self:center; font-size:13px; color:var(--muted); font-weight:900; padding:0 4px; }
.matchinfo { flex:1; min-width:0; padding:9px 18px; border-left:1px solid var(--line); }
.matchinfo h1 { margin:0; font-size:14px; font-weight:700; line-height:1.35; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
.matchinfo .sub { font-size:11px; color:var(--muted); margin-top:4px; display:flex;
  gap:14px; flex-wrap:wrap; }
.bars { width:280px; padding:10px 18px; border-left:1px solid var(--line);
  display:grid; gap:7px; align-content:center; }
.bar { position:relative; height:14px; background:oklch(0.13 0.01 75);
  border:1px solid var(--line); overflow:hidden; }
.bar > i { position:absolute; inset:0; transform-origin:left;
  transition:transform .5s var(--ease-out); }
.bar.hp > i { background:linear-gradient(90deg,var(--hp),oklch(0.72 0.17 55)); }
.bar.mana > i { background:var(--mana); }
.bar b { position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
  font-size:9px; letter-spacing:.12em; color:oklch(0.98 0 0 / .92);
  mix-blend-mode:plus-lighter; }
.livechip { display:flex; align-items:center; gap:8px; padding:0 20px;
  border-left:1px solid var(--line); font-size:11px; font-weight:900;
  letter-spacing:.14em; white-space:nowrap; }
.livechip .dot { width:9px; height:9px; border-radius:50%; background:var(--radiant);
  box-shadow:0 0 10px var(--radiant); animation:pulse 1.8s ease-in-out infinite; }
.livechip.waiting .dot { background:var(--amber); box-shadow:0 0 10px var(--amber); animation:none; }
.livechip.stale .dot { background:var(--ghost); box-shadow:none; animation:none; }
.livechip.ended .dot { background:var(--muted); box-shadow:none; animation:none; }
@keyframes pulse { 50% { opacity:.4 } }
.lang-btn { font:inherit; font-weight:900; font-size:11px; letter-spacing:.1em;
  border:none; border-left:1px solid var(--line); background:transparent;
  color:var(--muted); padding:0 18px; cursor:pointer; }
.lang-btn:hover { color:var(--gold); }

.stage { display:grid; grid-template-columns:1fr var(--right-column); }
.arena-wrap { position:relative; overflow:hidden; border-right:2px solid var(--line); display:flex; }
#arena { display:block; width:100%; height:100%; min-height:520px; max-height:var(--stage-height); flex:1;
  background:
    radial-gradient(120% 90% at 50% -10%,oklch(0.24 0.03 90 / .55),transparent 55%),
    radial-gradient(90% 120% at 50% 115%,oklch(0.1 0.02 60),transparent 60%),
    var(--arena); }
.edge { stroke:var(--line); stroke-width:2.5; fill:none; transition:stroke .45s,stroke-width .45s; }
.edge.done { stroke:oklch(0.52 0.08 120); stroke-width:3; }
.edge.hot { stroke:var(--gold); stroke-width:3.2; stroke-dasharray:8 7;
  animation:dashmove 1.1s linear infinite; }
@keyframes dashmove { to { stroke-dashoffset:-30 } }
.gate-node .halo { fill:none; stroke:transparent; stroke-width:3; }
.gate-node .core { fill:var(--panel-strong); stroke:var(--line); stroke-width:3;
  transition:fill .35s,stroke .35s,filter .35s; }
.gate-node .gate-index { fill:var(--muted); font:900 11px var(--font-mono); text-anchor:middle; }
.gate-node .gate-title { fill:var(--ink); font:800 14px var(--font-sans); text-anchor:middle; }
.gate-node .gate-state { fill:var(--muted); font:900 9px var(--font-mono);
  text-anchor:middle; letter-spacing:.1em; }
.gate-node.done .core { fill:oklch(0.3 0.08 145); stroke:var(--radiant); }
.gate-node.done .gate-index,.gate-node.done .gate-state { fill:var(--radiant); }
.gate-node.active .core { fill:oklch(0.28 0.06 88); stroke:var(--gold);
  filter:drop-shadow(0 0 13px oklch(0.82 0.13 88 / .42)); }
.gate-node.active .halo { stroke:var(--gold); stroke-dasharray:7 7;
  animation:spin 8s linear infinite; }
.gate-node.active .gate-index,.gate-node.active .gate-state { fill:var(--gold); }
.gate-node.blocked .core { stroke:var(--amber); }
.gate-node.blocked .gate-state { fill:var(--amber); }
@keyframes spin { to { transform:rotate(360deg); } }
.hero-bob { animation:bob 2.6s ease-in-out infinite; }
@keyframes bob { 50% { transform:translateY(-5px); } }
.unit-card { position:absolute; left:50%; bottom:14px; transform:translateX(-50%); z-index:5;
  width:min(470px,calc(100% - 28px)); background:oklch(0.14 0.014 75/.93);
  backdrop-filter:blur(10px); border:1px solid var(--line); border-top:3px solid var(--gold);
  box-shadow:var(--shadow-deep); }
.uc-head { display:flex; align-items:baseline; gap:9px; padding:10px 13px 7px; }
.uc-num { font-weight:900; color:var(--gold); }
.uc-label { font-size:16px; font-weight:900; }
.uc-id { margin-left:auto; font-size:10px; color:var(--muted); }
.uc-body { padding:0 13px 11px; font-size:11.5px; line-height:1.6; }
.uc-detail { color:var(--muted); margin-top:3px; }
.announcer { position:absolute; left:0; right:0; top:28%; display:flex;
  justify-content:center; pointer-events:none; }
.announcer span { font-size:clamp(24px,4vw,48px); font-weight:900; letter-spacing:.06em;
  font-style:italic; padding:6px 34px; color:var(--gold);
  background:linear-gradient(90deg,transparent,oklch(0.1 0.01 60/.92) 18%,
  oklch(0.1 0.01 60/.92) 82%,transparent); border-block:2px solid currentColor;
  animation:slam 1.45s var(--ease-out) forwards; }
@keyframes slam { 0%{opacity:0;transform:scale(1.7)} 12%{opacity:1;transform:scale(1)}
  80%{opacity:1} 100%{opacity:0;transform:scale(.96) translateY(-8px)} }

.rightcol { display:flex; flex-direction:column; background:var(--panel); min-height:0;
  height:var(--stage-height); }
.col-h { padding:8px 14px 6px; font-size:10px; color:var(--muted);
  border-bottom:1px solid var(--line); display:flex; justify-content:space-between;
  align-items:baseline; }
#feed { flex:1.2; overflow-y:auto; min-height:170px; padding:6px 0; }
.feed-row { display:flex; gap:9px; padding:5px 14px; font-size:12px; line-height:1.45;
  align-items:baseline; animation:feedin .35s var(--ease-out); border-left:3px solid transparent; }
@keyframes feedin { from { opacity:0; transform:translateX(26px); } }
.feed-row.info { color:var(--muted); }
.feed-row.pass { border-left-color:var(--radiant); }
.feed-row.soft { border-left-color:var(--amber); }
.feed-row.miss { border-left-color:var(--ghost); }
.feed-row .seq { color:var(--muted); font-size:10px; min-width:30px; }
.feed-row .ts { margin-left:auto; color:var(--muted); font-size:9.5px; white-space:nowrap; opacity:.8; }
#quest { flex:1; overflow-y:auto; border-top:2px solid var(--line); min-height:150px; }
.q-row { padding:8px 14px; border-bottom:1px solid oklch(0.26 0.02 80); }
.q-title { display:flex; gap:8px; align-items:baseline; font-size:12.5px; font-weight:700; }
.q-mark { font-size:14px; width:20px; text-align:center; }
.q-state { margin-left:auto; font-size:9px; letter-spacing:.1em; font-weight:900; }
.q-sub { font-size:10.5px; color:var(--muted); margin-top:3px; padding-left:28px; }
.q-DONE .q-state { color:var(--radiant); }
.q-ACTIVE .q-state { color:var(--gold); }
.q-BLOCKED .q-state,.q-OPEN .q-state { color:var(--amber); }
#waitingList { max-height:122px; overflow-y:auto; border-top:1px solid var(--line); }
.wait-row { padding:8px 14px; font-size:11px; line-height:1.45; border-bottom:1px solid var(--line); }
.wait-row b { color:var(--amber); }

.deck { display:flex; align-items:center; gap:12px; padding:9px 14px;
  background:oklch(0.16 0.017 76); border-block:2px solid var(--line); }
.deck button,.deck select { font:inherit; border:1px solid var(--line); background:var(--panel);
  color:var(--muted); height:30px; min-width:38px; padding:0 10px; }
.timeline { position:relative; flex:1; height:30px; }
.tl-track { position:absolute; left:0; right:0; top:13px; height:3px; background:var(--line); }
.tl-fill { position:absolute; left:0; top:13px; height:3px; background:var(--gold); width:0; transition:width .35s; }
.tl-cursor { position:absolute; top:8px; width:2px; height:13px; background:var(--ink); left:0; transition:left .35s; }
.tl-times { position:absolute; inset:0; display:flex; justify-content:space-between;
  align-items:flex-end; font-size:8px; color:var(--muted); pointer-events:none; }
.deck .stamp { min-width:128px; text-align:right; color:var(--muted); font-size:10px; }
.caster { display:flex; gap:12px; align-items:flex-start; padding:9px 18px 11px;
  background:linear-gradient(90deg,oklch(0.19 0.025 82),oklch(0.15 0.016 75));
  border-bottom:1px solid var(--line); min-height:43px; }
.caster .tag { color:var(--gold); font-size:9px; padding-top:3px; white-space:nowrap; }
#casterLine { font-size:13px; line-height:1.45; font-weight:600; }
.tabs { display:flex; gap:5px; padding:12px 18px 0; overflow-x:auto; }
.tab { flex:0 0 auto; border:1px solid var(--line); border-bottom:none; background:transparent;
  color:var(--muted); padding:8px 15px; font-size:12px; letter-spacing:.05em; }
.tab.active { color:var(--ink); background:var(--panel); font-weight:800; }
.tab[disabled] { opacity:.52; cursor:not-allowed; }
.preflight-note { margin:0 18px 24px; padding:14px 16px; background:var(--panel);
  border:1px solid var(--line); color:var(--muted); font-size:11px; line-height:1.55; }
.preflight-note b { color:var(--gold); }

@media (prefers-reduced-motion:reduce) {
  .hero-bob,.edge.hot,.gate-node.active .halo,.announcer span,.feed-row,.livechip .dot { animation:none; }
}
@media (max-width:960px) {
  .stage { grid-template-columns:1fr; }
  #arena { min-height:360px; }
  .rightcol { border-top:2px solid var(--line); height:auto; }
  #feed { min-height:130px; max-height:260px; }
  #quest { max-height:340px; }
  .topbar { flex-wrap:wrap; }
  .scorebox { padding:8px 14px; gap:10px; flex:1; }
  .score { font-size:30px; }
  .livechip { padding:0 12px; }
  .matchinfo { order:5; flex:1 1 100%; border-left:none; border-top:1px solid var(--line); padding:8px 14px; }
  .matchinfo h1 { white-space:normal; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
  .bars { order:6; flex:1 1 100%; width:auto; border-left:none; border-top:1px solid var(--line); padding:8px 14px; }
  .deck { gap:8px; padding:8px 10px; flex-wrap:wrap; }
  .timeline { flex:1 1 100%; order:5; }
  .deck .stamp { display:none; }
  .caster { padding:8px 14px 10px; }
  #casterLine { font-size:13px; }
}
</style>
</head>
<body data-sisyfus-shell="broadcast">
<header class="topbar">
  <div class="scorebox">
    <div><div class="score radiant" id="readyScore">0</div><div class="score-label caps" data-t="ready">已锁定</div></div>
    <div class="vs">VS</div>
    <div><div class="score amber" id="openScore">6</div><div class="score-label caps" data-t="open">待完成</div></div>
  </div>
  <div class="matchinfo">
    <h1 id="title">Awaiting Sisyfus mission</h1>
    <div class="sub">
      <span class="caps" style="color:var(--gold)">SISYFUS · MISSION CONTROL</span><span class="caps">Sisyfus Research Observatory · Arena</span>
      <span id="phaseMeta" class="mono">INTAKE</span>
      <span id="operationMeta" class="mono">skill.bootstrap</span>
    </div>
  </div>
  <div class="bars">
    <div class="bar hp"><i id="programFill" style="transform:scaleX(0)"></i><b id="programText">PROGRAM 0%</b></div>
    <div class="bar mana"><i id="signalFill" style="transform:scaleX(1)"></i><b id="signalText">HEARTBEAT —</b></div>
  </div>
  <div class="livechip" id="liveChip"><span class="dot"></span><span id="connection">LIVE</span></div>
  <button class="lang-btn" id="langBtn" title="切换语言 / switch language">EN</button>
</header>

<div class="stage">
  <div class="arena-wrap" id="arenaWrap">
    <svg id="arena" viewBox="0 0 1000 560" preserveAspectRatio="xMidYMid meet">
      <g id="edges"></g>
      <g id="bosses"></g>
      <g id="hero" style="transition:transform .8s var(--ease-out)">
        <g class="hero-bob">
          <circle r="26" cy="6" fill="oklch(0.85 0.05 90)" opacity=".14"/>
          <circle class="stone" r="13" cx="15" cy="-2" fill="oklch(0.8 0.06 85)"
            stroke="oklch(0.95 0.04 90)" stroke-width="1.5"/>
          <g stroke="oklch(0.93 0.02 90)" stroke-width="3.4" stroke-linecap="round" fill="none">
            <circle cx="-6" cy="-14" r="5" fill="oklch(0.93 0.02 90)" stroke="none"/>
            <path d="M-6 -9 L-3 4 L-9 16 M-4 3 L6 13 M-5 -6 L8 -8 M-5 -5 L4 0"/>
          </g>
        </g>
      </g>
    </svg>
    <div class="announcer" id="announcer"></div>
    <div class="unit-card">
      <div class="uc-head"><span class="uc-num" id="gateNumber">P1</span><span class="uc-label" id="gateTitle">任务范围</span><span class="uc-id mono" id="taskId"></span></div>
      <div class="uc-body"><div id="message">Compiling the research program.</div><div class="uc-detail" id="detail"></div></div>
    </div>
  </div>
  <aside class="rightcol">
    <div class="col-h caps"><span data-t="feed">战况播报</span><span id="feedCount"></span></div>
    <div id="feed"></div>
    <div class="col-h caps"><span data-t="gates">任务面板</span><span id="gateCount">0 / 6</span></div>
    <div id="quest"></div>
    <div class="col-h caps"><span data-t="waiting">待命区</span><span id="waitState" class="mono"></span></div>
    <div id="waitingList"></div>
  </aside>
</div>

<div class="deck">
  <button type="button" disabled>▶</button>
  <div class="timeline">
    <div class="tl-track"></div><div class="tl-fill" id="tlFill"></div><div class="tl-cursor" id="tlCursor"></div>
    <div class="tl-times mono"><span id="taskStart"></span><span id="taskNow"></span></div>
  </div>
  <button type="button" disabled data-t="live">直播</button>
  <div class="stamp mono" id="frameLabel">PRE-RUN · INTAKE</div>
</div>
<div class="caster"><span class="tag caps" data-t="caster">解说席</span><div id="casterLine">Mission Control is online.</div></div>

<nav class="tabs">
  <button class="tab active" type="button" data-t="watch">观战</button>
  <button class="tab" type="button" disabled data-t="report">报告</button>
  <button class="tab" type="button" disabled data-t="goal">目标图</button>
  <button class="tab" type="button" disabled data-t="audit">审计</button>
  <button class="tab" type="button" disabled data-t="events">事件流</button>
</nav>
<div class="preflight-note"><b data-t="preflight">赛前编排</b> · <span data-t="note">启动页与正式 Arena 使用同一套转播壳层。TaskSpec 锁定后，本页在同一 URL 中切换为真实 Claim 依赖地图。</span></div>

<script>
let A = {}, events = [], misses = 0, lang = localStorage.getItem('sisyfus-lang') || 'zh';
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const age = ts => ts ? Math.max(0,(Date.now()-Date.parse(ts))/1000) : 9999;
const fmt = x => { x=Math.max(0,Math.floor(Number(x)||0)); const h=Math.floor(x/3600),m=Math.floor((x%3600)/60),s=x%60;
  return h?`${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`:`${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`; };
const TXT = {
 zh:{ready:'已锁定',open:'待完成',feed:'战况播报',gates:'任务面板',waiting:'待命区',live:'直播',
  caster:'解说席',watch:'观战',report:'报告',goal:'目标图',audit:'审计',events:'事件流',
  preflight:'赛前编排',note:'启动页与正式 Arena 使用同一套转播壳层。TaskSpec 锁定后，本页在同一 URL 中切换为真实 Claim 依赖地图。',
  scope:'任务范围',objective:'终局目标',inputs:'高质量输入',claims:'命题图',verifier:'验证者',launch:'自主运行',
  locked:'LOCKED',active:'ACTIVE',queued:'QUEUED',needs:'NEEDS USER',none:'无阻断条件',program:'PROGRAM',heartbeat:'HEARTBEAT'},
 en:{ready:'GATES READY',open:'OPEN',feed:'MATCH FEED',gates:'QUEST PANEL',waiting:'RESPAWN',live:'LIVE',
  caster:'CASTER',watch:'ARENA',report:'REPORT',goal:'GOAL GRAPH',audit:'AUDIT',events:'EVENTS',
  preflight:'PRE-MATCH PROGRAM',note:'Bootstrap and the full Arena share one broadcast shell. After TaskSpec lock, this URL switches to the evidence-backed Claim map.',
  scope:'Scope',objective:'Terminal objective',inputs:'Qualified inputs',claims:'Claim graph',verifier:'Verifier',launch:'Autonomous run',
  locked:'LOCKED',active:'ACTIVE',queued:'QUEUED',needs:'NEEDS USER',none:'No blocking gate',program:'PROGRAM',heartbeat:'HEARTBEAT'}
};
const t = key => (TXT[lang]||TXT.zh)[key] || key;
const GATES = [
 {id:'scope',x:125,y:310,key:'scope',field:'scope'},
 {id:'objective',x:280,y:145,key:'objective',field:'objective'},
 {id:'inputs',x:430,y:310,key:'inputs'},
 {id:'claims',x:580,y:145,key:'claims'},
 {id:'verifier',x:730,y:310,key:'verifier',field:'verification'},
 {id:'launch',x:875,y:145,key:'launch'}
];
function applyLanguage(){
 document.documentElement.lang=lang==='zh'?'zh-CN':'en';
 document.querySelectorAll('[data-t]').forEach(el=>el.textContent=t(el.dataset.t));
 $('langBtn').textContent=lang==='zh'?'EN':'中';
 render();
}
function gateIndex(){
 const phase=String(A.phase||'INTAKE').toUpperCase(), status=String(A.status||'').toUpperCase();
 const missing=((A.metadata||{}).missing_intake_fields||[]).map(String);
 if(status==='NEEDS_USER'){
  if(missing.includes('scope'))return 0;
  if(missing.includes('objective'))return 1;
  if(missing.includes('verification'))return 4;
 }
 if(['CLARIFYING'].includes(phase))return 0;
 if(['INTAKE'].includes(phase))return 1;
 if(['INSPECTING','SOURCE_QUALIFICATION','DISCOVERING'].includes(phase))return 2;
 if(['INITIALIZING','PLANNING','AUTONOMY_PLANNING'].includes(phase))return 3;
 if(['VERIFYING','VERIFIER_DESIGN','AUTONOMY_VERIFYING'].includes(phase))return 4;
 if(['READY','EXECUTING','AUTONOMY_EXECUTING','FINALIZING','COMPLETED'].includes(phase))return 5;
 return 0;
}
function stateFor(g,i,active){
 const missing=((A.metadata||{}).missing_intake_fields||[]).map(String);
 if(g.field&&missing.includes(g.field))return i===active?'BLOCKED':'OPEN';
 if(i<active)return 'DONE';
 if(i===active)return String(A.status||'').toUpperCase()==='NEEDS_USER'?'BLOCKED':'ACTIVE';
 return 'OPEN';
}
function renderMap(){
 const active=gateIndex(), states=GATES.map((g,i)=>stateFor(g,i,active));
 $('edges').innerHTML=GATES.slice(0,-1).map((g,i)=>{
   const n=GATES[i+1], cls=i<active?'done':i===active?'hot':'';
   return `<path class="edge ${cls}" d="M${g.x} ${g.y} L${n.x} ${n.y}"/>`;
 }).join('');
 $('bosses').innerHTML=GATES.map((g,i)=>{
   const st=states[i], cls=st==='DONE'?'done':st==='ACTIVE'?'active':st==='BLOCKED'?'active blocked':'';
   return `<g class="gate-node ${cls}" transform="translate(${g.x} ${g.y})">
    <circle class="halo" r="49"/><circle class="core" r="38"/>
    <text class="gate-index" y="4">P${i+1}</text>
    <text class="gate-title" y="62">${esc(t(g.key))}</text>
    <text class="gate-state" y="79">${esc(st==='DONE'?t('locked'):st==='ACTIVE'?t('active'):st==='BLOCKED'?t('needs'):t('queued'))}</text>
   </g>`;
 }).join('');
 const current=GATES[active]||GATES[0];
 $('hero').setAttribute('transform',`translate(${current.x-54} ${current.y-6})`);
 $('gateNumber').textContent=`P${active+1}`;
 $('gateTitle').textContent=t(current.key);
 const ready=states.filter(x=>x==='DONE').length + (String(A.status||'').toUpperCase()==='READY'?1:0);
 $('readyScore').textContent=String(Math.min(GATES.length,ready));
 $('openScore').textContent=String(Math.max(0,GATES.length-ready));
 $('gateCount').textContent=`${Math.min(GATES.length,ready)} / ${GATES.length}`;
 $('quest').innerHTML=GATES.map((g,i)=>{
   const st=states[i], mark=st==='DONE'?'👑':st==='ACTIVE'?'⚔':st==='BLOCKED'?'?!':'?';
   const label=st==='DONE'?t('locked'):st==='ACTIVE'?t('active'):st==='BLOCKED'?t('needs'):t('queued');
   return `<div class="q-row q-${st}"><div class="q-title"><span class="q-mark">${mark}</span><span>P${i+1} ${esc(t(g.key))}</span><span class="q-state">${esc(label)}</span></div><div class="q-sub">${st==='ACTIVE'||st==='BLOCKED'?esc(A.message||''):''}</div></div>`;
 }).join('');
}
function renderFeed(){
 $('feedCount').textContent=`${events.length}`;
 $('feed').innerHTML=[...events].reverse().map(x=>{
  const st=String(x.status||'').toUpperCase(), cls=st==='ERROR'?'miss':st==='NEEDS_USER'?'soft':st==='COMPLETED'||st==='READY'?'pass':'info';
  return `<div class="feed-row ${cls}"><span class="seq">#${esc(x.seq||'')}</span><span><b>${esc(x.phase||'')} · ${esc(x.operation||'')}</b><br>${esc(x.error||x.message||'')}</span><span class="ts">${esc((x.ts||'').slice(11,19))}</span></div>`;
 }).join('')||`<div class="feed-row info"><span class="seq">#0</span><span>${esc(A.message||'Mission Control is online.')}</span></div>`;
}
function renderWaiting(){
 const questions=((A.metadata||{}).clarification_questions||[]).map(String);
 const waiting=String(A.status||'').toUpperCase()==='NEEDS_USER';
 $('waitState').textContent=waiting?'NEEDS_USER':'READY';
 $('waitingList').innerHTML=waiting
   ?questions.map((q,i)=>`<div class="wait-row"><b>Q${i+1}</b> · ${esc(q)}</div>`).join('')||`<div class="wait-row"><b>NEEDS USER</b> · ${esc(A.detail||'Clarification required.')}</div>`
   :`<div class="wait-row">${esc(t('none'))}</div>`;
}
function render(){
 const status=String(A.status||'IDLE').toUpperCase(), stale=status==='RUNNING'&&age(A.heartbeat_at)>5;
 $('title').textContent=A.title||'Sisyfus mission';
 $('phaseMeta').textContent=String(A.phase||'IDLE').toUpperCase();
 $('operationMeta').textContent=A.operation||'—';
 $('taskId').textContent=A.task_id||'';
 $('message').textContent=A.error||A.message||'';
 $('detail').textContent=A.detail||'';
 $('casterLine').textContent=A.error||A.message||A.detail||'Mission Control is online.';
 $('frameLabel').textContent=`PRE-RUN · ${String(A.phase||'IDLE').toUpperCase()}`;
 const p=A.progress||{}, active=gateIndex();
 const pct=p.percent==null?Math.round((active/Math.max(1,GATES.length-1))*100):Math.max(0,Math.min(100,Number(p.percent)));
 $('programFill').style.transform=`scaleX(${pct/100})`;
 $('programText').textContent=`${t('program')} ${Math.round(pct)}%`;
 const hb=Math.max(0,1-Math.min(5,age(A.heartbeat_at))/5);
 $('signalFill').style.transform=`scaleX(${hb})`;
 $('signalText').textContent=`${t('heartbeat')} ${Math.round(age(A.heartbeat_at))}s`;
 $('tlFill').style.width=`${pct}%`; $('tlCursor').style.left=`${pct}%`;
 $('taskStart').textContent=(A.task_started_at||'').slice(11,19);
 $('taskNow').textContent=fmt(A.operation_started_at?Math.max(0,(Date.now()-Date.parse(A.operation_started_at))/1000):A.elapsed_seconds||0);
 const chip=$('liveChip'); chip.className='livechip';
 if(status==='NEEDS_USER')chip.classList.add('waiting');
 if(stale||misses>=3)chip.classList.add('stale');
 if(['COMPLETED','READY'].includes(status))chip.classList.add('ended');
 $('connection').textContent=misses>=3?'RECONNECTING':stale?'STALE':status==='NEEDS_USER'?'NEEDS USER':status;
 renderMap(); renderFeed(); renderWaiting();
}
let lastAnnounce='';
function maybeAnnounce(){
 const key=`${A.phase}|${A.status}|${A.operation}`;
 if(lastAnnounce&&key!==lastAnnounce){
  const label=String(A.status||'').toUpperCase()==='NEEDS_USER'?t('needs'):String(A.phase||'').toUpperCase();
  $('announcer').innerHTML=`<span>${esc(label)}</span>`;
  setTimeout(()=>{$('announcer').innerHTML='';},1500);
 }
 lastAnnounce=key;
}
async function poll(){
 try{
  const [a,e]=await Promise.all([
   fetch(`activity.json?ts=${Date.now()}`,{cache:'no-store'}),
   fetch(`activity-events.json?ts=${Date.now()}`,{cache:'no-store'})
  ]);
  if(!a.ok)throw new Error(String(a.status));
  const next=await a.json(); if(e.ok){const p=await e.json();events=Array.isArray(p.events)?p.events:[];}
  A=next; misses=0; maybeAnnounce(); render();
  try{
   const s=await fetch(`snapshot.json?ts=${Date.now()}`,{cache:'no-store'});
   if(s.ok){const j=await s.json();if(j&&j.snapshot&&j.snapshot.snapshot_hash)location.reload();}
  }catch(_){}
 }catch(_){misses+=1;render();}
}
$('langBtn').addEventListener('click',()=>{lang=lang==='zh'?'en':'zh';localStorage.setItem('sisyfus-lang',lang);applyLanguage();});
applyLanguage(); poll(); setInterval(poll,600); setInterval(render,500);
</script>
</body>
</html>
"""


def render_activity_monitor(root: str | Path) -> Path:
    canonical = _root(root)
    directory = activity_dir(canonical)
    directory.mkdir(parents=True, exist_ok=True)
    if not activity_state_path(canonical).exists():
        write_activity(
            canonical,
            phase="IDLE",
            status="IDLE",
            operation="monitor.bootstrap",
            message="Mission monitor is online.",
        )
    if not activity_events_projection_path(canonical).exists():
        _atomic_write_json(
            activity_events_projection_path(canonical),
            {"schema_version": _ACTIVITY_EVENTS_SCHEMA, "events": []},
        )
    document = (
        _BOOTSTRAP_TEMPLATE
        .replace("__SISYFUS_THEME_ID__", ARENA_THEME_ID)
        .replace("__SISYFUS_THEME__", ARENA_THEME_CSS)
    )
    activity_index_path(canonical).write_text(document, encoding="utf-8")
    return activity_index_path(canonical)


class _ActivityHandler(SimpleHTTPRequestHandler):
    verbose = False

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] == "/":
            self.path = "/index.html"
        super().do_GET()

    def log_message(self, format: str, *args: Any) -> None:
        if type(self).verbose:
            super().log_message(format, *args)


def serve_activity_monitor(
    root: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    verbose: bool = False,
) -> tuple[ThreadingHTTPServer, str]:
    canonical = _root(root)
    render_activity_monitor(canonical)
    handler_cls = type(
        "SisyfusActivityHandler",
        (_ActivityHandler,),
        {"verbose": bool(verbose)},
    )
    handler = partial(handler_cls, directory=str(activity_dir(canonical)))
    server = ThreadingHTTPServer((host, int(port)), handler)
    actual = int(server.server_address[1])
    return server, f"http://{host}:{actual}/index.html"
