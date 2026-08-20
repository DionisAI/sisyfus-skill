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
  width:min(430px,calc(100vw - 28px)); color:#f4f0e6;
  background:linear-gradient(160deg,rgba(35,31,26,.97),rgba(19,18,17,.97));
  border:1px solid rgba(224,177,75,.45); border-top:3px solid #dcae4b;
  box-shadow:0 18px 60px rgba(0,0,0,.55); font-family:ui-monospace,Menlo,Consolas,monospace;
  backdrop-filter:blur(14px); transition:opacity .2s,transform .2s;
}}
#sf-live-hud.sf-collapsed .sf-activity-body {{ display:none; }}
#sf-live-hud .sf-activity-head {{ display:flex; align-items:center; gap:9px; padding:8px 10px;
  border-bottom:1px solid rgba(255,255,255,.09); font-size:10px; letter-spacing:.14em; font-weight:900; }}
#sf-live-hud .sf-dot {{ width:9px;height:9px;border-radius:50%;background:#67d58c;
  box-shadow:0 0 12px #67d58c;animation:sf-pulse 1.5s ease-in-out infinite; }}
#sf-live-hud[data-status="ERROR"] .sf-dot,#sf-live-hud[data-status="ATTENTION"] .sf-dot {{ background:#ec6a5f;box-shadow:0 0 12px #ec6a5f; }}
#sf-live-hud[data-status="COMPLETED"] .sf-dot,#sf-live-hud[data-status="READY"] .sf-dot {{ background:#e0b14b;box-shadow:0 0 12px #e0b14b;animation:none; }}
#sf-live-hud.sf-stale .sf-dot {{ background:#8e8797;box-shadow:none;animation:none; }}
@keyframes sf-pulse {{50%{{opacity:.35}}}}
#sf-live-hud .sf-toggle {{ margin-left:auto;border:0;background:transparent;color:#aaa;cursor:pointer;font:inherit; }}
#sf-live-hud .sf-activity-body {{ padding:10px 12px 11px; }}
#sf-live-hud .sf-task {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-weight:800;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis; }}
#sf-live-hud .sf-phase-row {{ display:flex;align-items:baseline;gap:8px;margin-top:7px; }}
#sf-live-hud .sf-phase {{ color:#e0b14b;font-weight:900;font-size:13px;letter-spacing:.08em; }}
#sf-live-hud .sf-status {{ margin-left:auto;color:#a9a39a;font-size:10px; }}
#sf-live-hud .sf-operation {{ color:#ddd4c5;font-size:11px;margin-top:5px; }}
#sf-live-hud .sf-message {{ color:#aaa39a;font:11px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin-top:4px; }}
#sf-live-hud .sf-progress {{ height:8px;background:#111;border:1px solid rgba(255,255,255,.1);margin-top:9px;overflow:hidden; }}
#sf-live-hud .sf-progress i {{ display:block;height:100%;width:0;background:linear-gradient(90deg,#67d58c,#e0b14b);transition:width .35s; }}
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
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sisyfus Mission Control</title>
<style>
:root{color-scheme:dark;--bg:#12110f;--panel:#201d19;--line:#423a2f;--gold:#e0b14b;--green:#66d58a;--red:#e86b62;--ink:#f2ede4;--muted:#8f887d}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 50% -10%,#342d22 0,#12110f 48%);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh}
.top{height:56px;display:flex;align-items:center;padding:0 22px;border-bottom:2px solid var(--line);background:rgba(26,23,20,.94)}
.logo{font-weight:900;letter-spacing:.18em}.live{margin-left:auto;font:900 11px ui-monospace,monospace;color:var(--green);display:flex;gap:8px;align-items:center}.live i{width:9px;height:9px;border-radius:50%;background:var(--green);box-shadow:0 0 13px var(--green);animation:pulse 1.5s infinite}@keyframes pulse{50%{opacity:.3}}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 340px;min-height:calc(100vh - 56px)}
.arena{position:relative;display:grid;place-items:center;overflow:hidden;border-right:2px solid var(--line);min-height:650px}
.ring{position:absolute;width:min(78vw,760px);aspect-ratio:1;border:1px solid #3c352c;border-radius:50%;box-shadow:inset 0 0 90px #000}
.ring:before,.ring:after{content:"";position:absolute;inset:14%;border:1px dashed #4f4332;border-radius:50%;animation:spin 30s linear infinite}.ring:after{inset:29%;animation-direction:reverse;animation-duration:18s}@keyframes spin{to{transform:rotate(360deg)}}
.hero{position:relative;z-index:2;text-align:center;width:min(680px,88%)}.sigil{width:116px;height:116px;margin:auto;border-radius:50%;display:grid;place-items:center;font:900 44px ui-monospace,monospace;color:#18130b;background:linear-gradient(145deg,#f1ca6f,#9e7024);box-shadow:0 0 55px rgba(224,177,75,.3);animation:bob 2.4s ease-in-out infinite}@keyframes bob{50%{transform:translateY(-8px)}}
.kicker{font:900 11px ui-monospace,monospace;letter-spacing:.2em;color:var(--gold);margin-top:25px}.title{font-size:clamp(27px,4vw,54px);font-weight:900;line-height:1.08;margin:10px 0 8px}.objective{color:var(--muted);font-size:14px;line-height:1.55;max-width:600px;margin:auto}
.phase{font:900 18px ui-monospace,monospace;color:var(--green);margin-top:24px}.operation{font:12px ui-monospace,monospace;color:#d9d0c3;margin-top:7px}.message{color:#aaa196;margin-top:7px}
.bar{height:13px;background:#0b0a09;border:1px solid var(--line);margin:24px auto 0;max-width:520px;overflow:hidden}.bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--green),var(--gold));transition:width .35s}
.meta{display:flex;justify-content:center;gap:18px;flex-wrap:wrap;font:10px ui-monospace,monospace;color:#817a70;margin-top:10px}
.side{background:rgba(32,29,25,.96);display:flex;flex-direction:column;min-height:0}.side h2{margin:0;padding:13px 15px;border-bottom:1px solid var(--line);font:900 10px ui-monospace,monospace;letter-spacing:.15em;color:var(--muted)}
.feed{overflow:auto;flex:1}.event{padding:10px 14px;border-bottom:1px solid #312c26;border-left:3px solid var(--line)}.event.RUNNING{border-left-color:var(--green)}.event.ERROR,.event.ATTENTION{border-left-color:var(--red)}.event.COMPLETED,.event.READY{border-left-color:var(--gold)}.event .ephase{font:900 11px ui-monospace,monospace;color:var(--gold)}.event .emsg{font-size:12px;margin-top:4px}.event .ets{font:9px ui-monospace,monospace;color:var(--muted);margin-top:4px}
.notice{padding:13px 15px;border-top:1px solid var(--line);font-size:11px;line-height:1.5;color:var(--muted)}
@media(max-width:850px){.layout{grid-template-columns:1fr}.arena{border-right:0;min-height:70vh}.side{min-height:300px}}
</style>
</head>
<body>
<header class="top"><div class="logo">SISYFUS · MISSION CONTROL</div><div class="live"><i></i><span id="connection">LIVE</span></div></header>
<main class="layout">
<section class="arena">
<div class="ring"></div>
<div class="hero">
<div class="sigil">Σ</div>
<div class="kicker">RESEARCH ARENA INITIALIZING</div>
<div class="title" id="title">Awaiting mission</div>
<div class="objective" id="objective"></div>
<div class="phase" id="phase">INTAKE</div>
<div class="operation" id="operation">skill.bootstrap</div>
<div class="message" id="message">Compiling the research program.</div>
<div class="bar"><i id="progress"></i></div>
<div class="meta"><span id="elapsed">elapsed 00:00</span><span id="heartbeat">heartbeat —</span><span id="research"></span></div>
</div>
</section>
<aside class="side"><h2>MISSION FEED</h2><div class="feed" id="feed"></div><div class="notice">This bootstrap arena stays live while the Skill qualifies inputs and compiles the TaskSpec. When the research run becomes available, this tab automatically switches to the full game-style Observatory.</div></aside>
</main>
<script>
let A={}, events=[], misses=0;
const $=id=>document.getElementById(id);
const age=ts=>ts?Math.max(0,(Date.now()-Date.parse(ts))/1000):9999;
const fmt=x=>{x=Math.max(0,Math.floor(Number(x)||0));const h=Math.floor(x/3600),m=Math.floor((x%3600)/60),s=x%60;return h?`${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`:`${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`};
function render(){
 $('title').textContent=A.title||'Sisyfus mission';$('objective').textContent=A.objective||'';
 $('phase').textContent=String(A.phase||'IDLE').toUpperCase();$('operation').textContent=A.operation||'—';
 $('message').textContent=A.error||A.message||'';const p=A.progress||{};$('progress').style.width=p.percent==null?(A.status==='RUNNING'?'12%':'0%'):`${Math.max(0,Math.min(100,Number(p.percent)))}%`;
 const e=A.operation_started_at?Math.max(0,(Date.now()-Date.parse(A.operation_started_at))/1000):A.elapsed_seconds||0;
 $('elapsed').textContent=`elapsed ${fmt(e)}`;$('heartbeat').textContent=`heartbeat ${Math.round(age(A.heartbeat_at))}s`;$('research').textContent=A.research_id?`run ${A.research_id}`:'';
 $('connection').textContent=misses>=3?'RECONNECTING':String(A.status||'LIVE');
 $('feed').innerHTML=[...events].reverse().map(x=>`<div class="event ${x.status||''}"><div class="ephase">${x.phase||''} · ${x.operation||''}</div><div class="emsg">${(x.error||x.message||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}</div><div class="ets">${x.ts||''}</div></div>`).join('');
}
async function poll(){
 try{
  const [a,e]=await Promise.all([
   fetch(`activity.json?ts=${Date.now()}`,{cache:'no-store'}),
   fetch(`activity-events.json?ts=${Date.now()}`,{cache:'no-store'})
  ]);
  if(!a.ok)throw new Error(String(a.status));A=await a.json();
  if(e.ok){const p=await e.json();events=p.events||[];}misses=0;render();
  try{const s=await fetch(`snapshot.json?ts=${Date.now()}`,{cache:'no-store'});if(s.ok){const j=await s.json();if(j&&j.snapshot&&j.snapshot.snapshot_hash)location.reload();}}catch(_){}
 }catch(_){misses+=1;render();}
}
render();poll();setInterval(poll,600);setInterval(render,500);
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
    activity_index_path(canonical).write_text(_BOOTSTRAP_TEMPLATE, encoding="utf-8")
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
