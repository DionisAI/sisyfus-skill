from __future__ import annotations

import hashlib
import json
import math
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


def _finite_or_none(value: Any) -> Any:
    # activity.json is strict JSON; a NaN progress value must not stop heartbeats.
    return None if isinstance(value, float) and not math.isfinite(value) else value


def _normalise_progress(value: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(value or {})
    current = _finite_or_none(raw.get("current"))
    total = _finite_or_none(raw.get("total"))
    percent = _finite_or_none(raw.get("percent"))
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
            try:
                self._heartbeat_once()
            except Exception:  # one bad tick must not end the heartbeat; the next tick retries
                continue

    def _heartbeat_once(self) -> None:
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


# Plain-language labels shared by the live activity overlay and the bootstrap
# page. Raw phase/status enums stay in technical details; people read these.
_ACTIVITY_LABELS_JS = r"""
const SF_LABELS = {
 zh: {
  phase: {IDLE:'空闲', UNKNOWN:'状态未知', INTAKE:'理解任务', CLARIFYING:'澄清需求', INSPECTING:'检查工程',
   SOURCE_QUALIFICATION:'核验数据源', DISCOVERING:'查找资料', INITIALIZING:'初始化研究', PLANNING:'规划实验',
   AUTONOMY_PLANNING:'规划实验', VERIFIER_DESIGN:'设计验证', VERIFYING:'判定结果', AUTONOMY_VERIFYING:'判定结果',
   READY:'准备就绪', AUTONOMY_READY:'等待下一轮', EXECUTING:'执行实验', AUTONOMY_EXECUTING:'执行实验', AUTONOMOUS:'自主运行', COLLECTING:'收集结果',
   FINALIZING:'整理结论', COMPLETED:'已完成', STOPPED:'已停止', ERROR:'出错'},
  status: {RUNNING:'运行中', NEEDS_USER:'等你确认', ERROR:'出错了', ATTENTION:'需要关注', COMPLETED:'已完成',
   READY:'已就绪', IDLE:'空闲', STALE:'久未更新', RECONNECTING:'连接中断', BETWEEN:'等待下一步', OTHER:'另一项研究运行中',
   WAITING:'等待中', FAILED:'失败', EXHAUSTED:'预算用尽', BLOCKED:'受阻', CANCELLED:'已取消'},
  elapsed:'已运行', updated:'上次更新', tech:'技术细节', other_note:'这不是本页的研究。', details:'运行详情',
  operation:'操作', run:'研究', raw_phase:'阶段', raw_status:'状态', detail:'说明', heartbeat:'心跳',
  ago: s => s < 60 ? `${Math.max(1, Math.round(s))} 秒前` : s < 3600 ? `${Math.round(s / 60)} 分钟前` : `${Math.round(s / 3600)} 小时前`
 },
 en: {
  phase: {IDLE:'Idle', UNKNOWN:'Unknown', INTAKE:'Understanding the task', CLARIFYING:'Clarifying', INSPECTING:'Inspecting the project',
   SOURCE_QUALIFICATION:'Checking data sources', DISCOVERING:'Gathering material', INITIALIZING:'Setting up the study', PLANNING:'Planning experiments',
   AUTONOMY_PLANNING:'Planning experiments', VERIFIER_DESIGN:'Designing verification', VERIFYING:'Judging results', AUTONOMY_VERIFYING:'Judging results',
   READY:'Ready', AUTONOMY_READY:'Ready for next round', EXECUTING:'Experiment', AUTONOMY_EXECUTING:'Experiment', AUTONOMOUS:'Autonomous run', COLLECTING:'Collecting results',
   FINALIZING:'Writing conclusions', COMPLETED:'Completed', STOPPED:'Stopped', ERROR:'Error'},
  status: {RUNNING:'Running', NEEDS_USER:'Needs you', ERROR:'Error', ATTENTION:'Needs attention', COMPLETED:'Completed',
   READY:'Ready', IDLE:'Idle', STALE:'No recent update', RECONNECTING:'Reconnecting', BETWEEN:'Waiting for next step', OTHER:'Another study is running',
   WAITING:'Waiting', FAILED:'Failed', EXHAUSTED:'Budget exhausted', BLOCKED:'Blocked', CANCELLED:'Cancelled'},
  elapsed:'Running for', updated:'Last update', tech:'Technical details', other_note:'This is not the study on this page.', details:'Run details',
  operation:'Operation', run:'Run', raw_phase:'Phase', raw_status:'Status', detail:'Detail', heartbeat:'Heartbeat',
  ago: s => s < 60 ? `${Math.max(1, Math.round(s))}s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`
 }
};
function sfLang() { return String(document.documentElement.lang || '').toLowerCase().startsWith('en') ? 'en' : 'zh'; }
function sfL() { return SF_LABELS[sfLang()]; }
function sfPhase(p) { p = String(p || 'IDLE').toUpperCase(); return sfL().phase[p] || p.toLowerCase().replace(/_/g, ' '); }
function sfStatus(s) { s = String(s || 'IDLE').toUpperCase(); return sfL().status[s] || s.toLowerCase().replace(/_/g, ' '); }
function sfClock(seconds) {
  seconds = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60, two = n => String(n).padStart(2, '0');
  return h ? `${two(h)}:${two(m)}:${two(s)}` : `${two(m)}:${two(s)}`;
}
function sfAge(ts) { const t = Date.parse(ts || ''); return Number.isFinite(t) ? Math.max(0, (Date.now() - t) / 1000) : null; }
/* "34/40 folds · 85%" from the progress protocol; null when nothing is measured. */
function sfProgress(p) {
  p = p || {};
  const cur = Number(p.current), tot = Number(p.total), raw = Number(p.percent);
  const hasCount = p.total != null && Number.isFinite(tot) && tot > 0 && Number.isFinite(cur);
  const pct = p.percent != null && Number.isFinite(raw) ? raw : hasCount ? cur / tot * 100 : null;
  if (pct == null) return null;
  const bounded = Math.max(0, Math.min(100, pct));
  const count = hasCount ? `${cur}/${tot}${p.label ? ' ' + p.label : ''}` : '';
  return { pct: bounded, text: count ? `${count} · ${Math.round(bounded)}%` : `${Math.round(bounded)}%`, count };
}
/* Heartbeat cadence is learned, not assumed. One-shot RUNNING records (for
   example an external command) never beat, so they read "last update N ago"
   and only read "no recent update" after an hour without any change. */
function sfBeats() {
  let key = null, last = null, beats = 0, gap = 1;
  return {
    observe(A) {
      const k = [A.task_id, A.research_id, A.operation, A.operation_started_at].join('|');
      if (k !== key) { key = k; last = A.heartbeat_at; beats = 0; gap = 1; return; }
      if (A.heartbeat_at && A.heartbeat_at !== last) {
        const dt = (Date.parse(A.heartbeat_at) - Date.parse(last)) / 1000;
        if (Number.isFinite(dt) && dt > 0) gap = beats ? Math.min(gap, dt) : Math.min(120, dt);
        last = A.heartbeat_at; beats += 1;
      }
    },
    stale(A) {
      const age = sfAge(A.heartbeat_at);
      const limit = beats >= 2 ? Math.max(5, gap * 4) : 3600;  /* never-beating records: 1 h ceiling */
      return String(A.status || '').toUpperCase() === 'RUNNING' && age != null && age > limit;
    }
  };
}
"""

# Live activity, docked into the shared top bar next to the status chip. It is
# scoped to the page's own run: another run's activity in the same project is
# shown as such, never as this page's progress. Technical fields live in a
# closed disclosure; colours come from the theme's status tones.
_OVERLAY_TEMPLATE = r"""
<style id="sf-activity-style">
#sf-live-hud { position:relative; flex:0 1 auto; min-width:0; font-family:var(--font-sans); }
#sf-live-hud:not(.sf-docked) { position:fixed; right:16px; bottom:16px; z-index:50; }
#sf-live-hud .sf-toggle { --tone:var(--muted); --tone-bg:var(--surface); --tone-dot:var(--open);
  display:inline-flex; align-items:center; gap:7px; max-width:min(320px,62vw); height:30px; padding:0 10px 0 12px;
  border:1px solid var(--line); border-radius:999px; background:var(--tone-bg); color:var(--tone);
  font-size:12.5px; line-height:1; white-space:nowrap; }
#sf-live-hud .sf-toggle:hover { border-color:var(--line-strong); }
#sf-live-hud .sf-dot { width:7px; height:7px; border-radius:50%; flex:0 0 auto; background:var(--tone-dot); }
#sf-live-hud .sf-label { min-width:0; overflow:hidden; text-overflow:ellipsis; }
#sf-live-hud .sf-chev { flex:0 0 auto; font-size:10px; color:var(--faint); transition:transform .2s var(--ease-out); }
#sf-live-hud:not(.sf-collapsed) .sf-chev { transform:rotate(180deg); }
#sf-live-hud.sf-tone-run .sf-toggle { --tone:var(--accent-ink); --tone-bg:var(--accent-soft); --tone-dot:var(--accent); border-color:var(--accent-line); }
#sf-live-hud.sf-tone-warn .sf-toggle { --tone:var(--warn); --tone-bg:var(--warn-soft); --tone-dot:var(--warn); border-color:transparent; }
#sf-live-hud.sf-tone-bad .sf-toggle { --tone:var(--bad); --tone-bg:var(--bad-soft); --tone-dot:var(--bad); border-color:transparent; }
#sf-live-hud.sf-tone-muted .sf-toggle { --tone:var(--muted); --tone-bg:var(--surface); --tone-dot:var(--void); }
#sf-live-hud .sf-activity-body { position:absolute; top:calc(100% + 8px); right:0; z-index:60;
  width:min(340px,calc(100vw - 32px)); padding:12px 14px; background:var(--surface); color:var(--ink-2);
  border:1px solid var(--line); border-radius:var(--radius); box-shadow:var(--shadow-soft);
  font-size:13px; line-height:1.6; text-align:left; white-space:normal; }
#sf-live-hud.sf-collapsed .sf-activity-body { display:none; }
#sf-live-hud .sf-task { color:var(--ink); font-weight:600; overflow-wrap:anywhere;
  display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }
#sf-live-hud .sf-message { margin-top:4px; color:var(--ink-2); overflow-wrap:anywhere; }
#sf-live-hud .sf-message:empty,#sf-live-hud .sf-error:empty,#sf-live-hud .sf-count:empty { display:none; }
#sf-live-hud .sf-progress { height:3px; margin-top:10px; border-radius:2px; background:var(--sunk); overflow:hidden; }
#sf-live-hud .sf-progress i { display:block; height:100%; width:0; background:var(--accent); transition:width .35s var(--ease-out); }
#sf-live-hud .sf-count { margin-top:4px; font-size:12px; color:var(--muted); font-variant-numeric:tabular-nums; }
#sf-live-hud .sf-meta { margin-top:6px; font-size:12px; color:var(--muted); font-variant-numeric:tabular-nums; }
#sf-live-hud .sf-error { margin-top:8px; padding:6px 8px; border-radius:6px; background:var(--bad-soft); color:var(--bad);
  font-size:12.5px; overflow-wrap:anywhere; }
#sf-live-hud .sf-tech { margin-top:10px; border-top:1px solid var(--line); padding-top:6px; font-size:12px; color:var(--muted); }
#sf-live-hud .sf-tech summary { cursor:pointer; color:var(--muted); }
#sf-live-hud .sf-tech dl { display:grid; grid-template-columns:auto 1fr; gap:2px 10px; margin:6px 0 0; }
#sf-live-hud .sf-tech dt { color:var(--muted); }
#sf-live-hud .sf-tech dd { margin:0; font-family:var(--font-mono); font-size:11.5px; color:var(--ink-2); overflow-wrap:anywhere; }
#sf-live-hud .sf-sr { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); white-space:nowrap; }
@media (max-width:540px) {
  .topbar .top-actions { flex-wrap:wrap; }
  #sf-live-hud .sf-toggle { max-width:calc(100vw - 32px); }
  #sf-live-hud .sf-activity-body { right:auto; left:0; }
}
@media (prefers-reduced-motion:reduce) { #sf-live-hud .sf-progress i,#sf-live-hud .sf-chev { transition:none; } }
</style>
<aside id="sf-live-hud" class="sf-collapsed sf-tone-muted" data-status="IDLE" data-sisyfus-panel="LIVE MISSION" aria-label="运行状态 / Activity" hidden>
  <button class="sf-toggle" type="button" aria-expanded="false" aria-controls="sf-act-body"><span class="sf-dot" aria-hidden="true"></span><span class="sf-label" id="sf-act-status"></span><span class="sf-chev" aria-hidden="true">▾</span></button>
  <span class="sf-sr" id="sf-act-announce" aria-live="polite"></span>
  <div class="sf-activity-body" id="sf-act-body" role="group">
    <div class="sf-task" id="sf-act-title"></div>
    <div class="sf-message" id="sf-act-message"></div>
    <div class="sf-progress" id="sf-act-bar" hidden><i id="sf-act-progress"></i></div>
    <div class="sf-count" id="sf-act-count"></div>
    <div class="sf-meta" id="sf-act-meta"></div>
    <div class="sf-error" id="sf-act-error"></div>
    <details class="sf-tech"><summary id="sf-act-tech-label"></summary><dl id="sf-act-tech"></dl></details>
  </div>
</aside>
<script id="sf-activity-script">
(() => {
  let A = __SF_ACTIVITY__;
  let misses = 0;
  const $ = id => document.getElementById(id);
  __SF_LABELS__
  const beats = sfBeats();
  const live = location.protocol === 'http:' || location.protocol === 'https:';
  const hud = $('sf-live-hud'), toggle = hud && hud.querySelector('.sf-toggle');
  if (!hud || !toggle) return;
  const slot = document.querySelector('.topbar .top-actions');
  if (slot) { slot.insertBefore(hud, slot.firstChild); hud.classList.add('sf-docked'); }
  const put = (id, value) => { const el = $(id); value = String(value ?? ''); if (el && el.textContent !== value) el.textContent = value; };
  /* The page's own run, read from the Observatory's globals when they exist.
     Guarded: before boot or after a failed boot they may be unavailable. */
  function pageRun() {
    try {
      if (typeof S === 'object' && S && S.research_id) {
        let final = false;
        try { final = typeof isFinalStatus === 'function' && isFinalStatus(String(S.run_status || '')); } catch (_) {}
        return { id: String(S.research_id), final };
      }
    } catch (_) {}
    const data = document.getElementById('sisyfus-data');
    const match = data && /"research_id":\s*"([^"]+)"/.exec(data.textContent || '');
    return match ? { id: match[1], final: false } : null;
  }
  /* What the chip should say, or null to stay out of the way. */
  function view() {
    if (!live) return null;
    const status = String(A.status || 'IDLE').toUpperCase(), page = pageRun();
    /* start_activity keeps the previous research_id, so a new study's intake
       record can carry this page's id; bootstrap records are never this run's. */
    const mine = !page || (A.research_id === page.id && (A.metadata || {}).monitor_mode !== 'bootstrap');
    const running = status === 'RUNNING';
    if (!mine) return running && (sfAge(A.heartbeat_at) ?? 1e9) < 3600 ? { key:'OTHER', tone:'muted', other:true } : null;
    if (status === 'ERROR' || status === 'ATTENTION') return { key:status, tone:'bad' };
    if (page && page.final) return null;  /* the status chip already says the study ended */
    if (misses >= 3) return page ? null : { key:'RECONNECTING', tone:'warn' };  /* the page's status chip reports connectivity */
    if (running) return beats.stale(A) ? { key:'STALE', tone:'warn' } : { key:'RUNNING', tone:'run' };
    if (status === 'NEEDS_USER') return { key:'NEEDS_USER', tone:'warn' };
    if (status === 'FAILED') return { key:status, tone:'bad' };
    if (['EXHAUSTED', 'BLOCKED', 'CANCELLED'].includes(status)) return { key:status, tone:'warn' };
    return page ? { key:'BETWEEN', tone:'muted' } : { key:status, tone:'muted' };
  }
  let announced = '';
  function render() {
    const v = view();
    hud.hidden = !v;
    if (!v) return;
    const L = sfL(), p = sfProgress(A.progress);
    const label = v.key === 'RUNNING' ? [sfStatus('RUNNING'), sfPhase(A.phase), p && p.count].filter(Boolean).join(' · ') : sfStatus(v.key);
    hud.dataset.status = String(A.status || 'IDLE').toUpperCase();
    for (const tone of ['run', 'warn', 'bad', 'muted']) hud.classList.toggle('sf-tone-' + tone, v.tone === tone);
    put('sf-act-status', label);
    if (announced !== v.key) { announced = v.key; put('sf-act-announce', sfStatus(v.key)); }
    toggle.setAttribute('aria-label', `${label} · ${L.details}`);
    put('sf-act-title', v.other ? (A.title || sfStatus('OTHER')) : sfPhase(A.phase));
    put('sf-act-message', v.other ? L.other_note : (A.message || ''));
    $('sf-act-bar').hidden = v.other || !p;
    $('sf-act-progress').style.width = p ? `${p.pct}%` : '0%';
    put('sf-act-count', v.other || !p ? '' : p.text);
    const started = Date.parse(A.operation_started_at || '');
    const elapsed = v.key === 'RUNNING' && Number.isFinite(started) ? (Date.now() - started) / 1000 : Number(A.elapsed_seconds || 0);
    const age = sfAge(A.heartbeat_at);
    put('sf-act-meta', [`${L.elapsed} ${sfClock(elapsed)}`, age == null ? '' : `${L.updated} ${L.ago(age)}`].filter(Boolean).join(' · '));
    put('sf-act-error', v.other ? '' : (A.error || ''));
    put('sf-act-tech-label', L.tech);
    const rows = [[L.raw_status, A.status], [L.raw_phase, A.phase], [L.operation, A.operation], [L.run, A.research_id || A.task_id],
      [L.detail, A.detail], [L.heartbeat, A.heartbeat_at]].filter(r => r[1]);
    const sig = rows.map(r => r.join('=')).join('\n');
    const tech = $('sf-act-tech');
    if (tech.dataset.sig !== sig) {
      tech.dataset.sig = sig;
      tech.replaceChildren(...rows.flatMap(([k, val]) => {
        const dt = document.createElement('dt'), dd = document.createElement('dd');
        dt.textContent = k; dd.textContent = String(val); return [dt, dd];
      }));
    }
  }
  async function pollActivity() {
    if (document.hidden) return;
    try {
      const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 5000);
      try {
        const response = await fetch(`activity.json?ts=${Date.now()}`, {cache:'no-store', signal:ctl.signal});
        if (!response.ok) throw new Error(String(response.status));
        A = await response.json();
      } finally { clearTimeout(timer); }
      misses = 0; beats.observe(A); render();
    } catch (_) { misses += 1; render(); }
  }
  function setOpen(open) {
    hud.classList.toggle('sf-collapsed', !open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  toggle.addEventListener('click', () => setOpen(hud.classList.contains('sf-collapsed')));
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || hud.classList.contains('sf-collapsed')) return;
    const inside = hud.contains(document.activeElement);
    setOpen(false);
    if (inside) { toggle.focus(); event.stopPropagation(); }  /* don't also close the inspector */
  });
  hud.addEventListener('focusout', event => { if (event.relatedTarget && !hud.contains(event.relatedTarget)) setOpen(false); });
  document.addEventListener('click', event => { if (!hud.contains(event.target)) setOpen(false); });
  beats.observe(A);
  render();
  setInterval(render, 1000);
  if (live) {
    pollActivity(); setInterval(pollActivity, 700);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) pollActivity(); });
  }
})();
</script>
""".replace("__SF_LABELS__", _ACTIVITY_LABELS_JS.strip())


def activity_overlay_html(initial: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(initial),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).replace("</", "<\\/")
    return _OVERLAY_TEMPLATE.replace("__SF_ACTIVITY__", payload)


_BOOTSTRAP_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN" data-sisyfus-theme="__SISYFUS_THEME_ID__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="sisyfus-legacy-title" content="SISYFUS · MISSION CONTROL" />
<meta name="sisyfus-legacy-shell" content="Sisyfus Research Observatory · Arena" />
<title>Sisyfus 研究工作台</title>
<style>
__SISYFUS_THEME__

/* The bootstrap page uses the same light workspace shell as the post-TaskSpec
   Observatory (topbar/stage/deck/caster/tabs come from the shared theme). Only
   the data model changes during handoff: six preparation steps instead of the
   Claim graph. Everything below is page-local layout for those steps. */
.graph-head { display:flex; align-items:flex-end; justify-content:space-between; flex-wrap:wrap;
  gap:8px 16px; padding:16px 24px 8px; }
.graph-title { margin:0; font-family:var(--font-serif); font-size:16px; font-weight:500; color:var(--ink); }
.graph-sub { margin-top:2px; font-size:12.5px; color:var(--muted); }
.preflight-map { flex:1 1 auto; min-height:0; overflow-x:auto; overscroll-behavior-x:contain; padding:0 12px; }
#arena { display:block; width:100%; min-width:680px; height:auto; max-height:calc(var(--stage-height) - 190px);
  background:transparent; }
.edge { stroke:var(--edge); stroke-width:2; fill:none; marker-end:url(#preArrow); }
.edge.done { stroke:var(--ok); }
.edge.hot { stroke:var(--accent); stroke-dasharray:6 5; }
#preArrow path { fill:var(--edge-strong); }
.gate-node .halo { fill:none; stroke:none; }
.gate-node .core { fill:var(--surface); stroke:var(--line-strong); stroke-width:1.5; }
.gate-node .gate-index { fill:var(--muted); font:600 13px var(--font-mono); }
.gate-node .gate-title { fill:var(--ink); font:600 18px var(--font-sans); text-anchor:middle; }
.gate-node .gate-state { fill:var(--muted); font:600 13px var(--font-sans); text-anchor:middle; }
.gate-node.done .core { fill:var(--ok-soft); stroke:var(--ok); }
.gate-node.done .gate-state { fill:var(--ok); }
.gate-node.active .core { fill:var(--accent-soft); stroke:var(--accent); stroke-width:2; }
.gate-node.active .gate-state { fill:var(--accent-ink); }
.gate-node.blocked .core { fill:var(--warn-soft); stroke:var(--warn); }
.gate-node.blocked .gate-state { fill:var(--warn); }
/* Legacy continuity hooks: the old avatar group and phase banner survive as
   neutral, invisible elements so the bootstrap → arena handoff keeps its IDs. */
#hero,.hero-bob { display:none; animation:none; }
.announcer { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; }
.unit-card { margin:4px 24px 18px; padding:12px 16px; background:var(--surface); border:1px solid var(--line);
  border-radius:var(--radius); box-shadow:var(--shadow-soft); }
.uc-head { display:flex; align-items:baseline; flex-wrap:wrap; gap:4px 10px; }
.uc-num { font:600 12px var(--font-mono); color:var(--accent-ink); }
.uc-label { font-size:15px; font-weight:600; color:var(--ink); }
.uc-id { margin-left:auto; font-size:11px; color:var(--muted); }
.uc-body { margin-top:4px; font-size:13px; line-height:1.6; color:var(--ink-2); overflow-wrap:anywhere; }
.uc-detail { margin-top:2px; color:var(--muted); }
.uc-detail:empty { display:none; }

#feed { flex:1 1 auto; min-height:150px; overflow-y:auto; padding:2px 0 8px; }
.feed-row b { font-weight:600; color:var(--ink); }
.feed-row.info { color:var(--muted); }
.feed-row.pass { border-left-color:var(--ok); }
.feed-row.soft { border-left-color:var(--warn); }
.feed-row.miss { border-left-color:var(--bad); }
#quest { padding:0 0 6px; border-top:1px solid var(--line); }
.q-row { padding:8px 20px; border-bottom:1px solid var(--line); }
.q-row:last-child { border-bottom:0; }
.q-title { display:flex; gap:8px; align-items:baseline; font-size:13px; color:var(--ink-2); }
.q-mark { flex:0 0 18px; text-align:center; font-size:12px; color:var(--faint); }
.q-state { margin-left:auto; font-size:12px; font-weight:600; color:var(--muted); white-space:nowrap; }
.q-sub { margin-top:2px; padding-left:26px; font-size:12px; color:var(--muted); overflow-wrap:anywhere; }
.q-sub:empty { display:none; }
.q-DONE .q-mark,.q-DONE .q-state { color:var(--ok); }
.q-ACTIVE .q-title { color:var(--ink); font-weight:600; }
.q-ACTIVE .q-mark,.q-ACTIVE .q-state { color:var(--accent-ink); }
.q-BLOCKED .q-mark,.q-BLOCKED .q-state { color:var(--warn); }
#waitingList { border-top:1px solid var(--line); padding-bottom:8px; }
.wait-row { padding:8px 20px; font-size:12.5px; line-height:1.55; color:var(--ink-2); overflow-wrap:anywhere; }
.wait-row b { color:var(--warn); font-weight:600; }
.preflight-note { margin:16px 24px 28px; padding:12px 16px; background:var(--paper-raised);
  border:1px solid var(--line); border-radius:var(--radius); color:var(--muted); font-size:12.5px; line-height:1.65; }
.preflight-note b { color:var(--ink); font-weight:600; }

/* Setup has nothing to replay and no audit views yet: hide controls that could
   only ever be disabled. The shared deck/tabs markup stays for the handoff. */
.deck button[disabled],.tabs { display:none; }
.deck .stamp { flex:0 1 auto; }
#signalText { font-variant-numeric:tabular-nums; }

@media (max-width:960px) {
  #arena { max-height:none; }
  #feed { max-height:280px; }
  .graph-head { padding:14px 16px 6px; }
  .unit-card { margin:4px 16px 16px; }
  .preflight-note { margin:14px 16px 24px; }
}
@media (prefers-reduced-motion:reduce) {
  .edge.hot { stroke-dasharray:none; }
}
@media print {
  .deck,.tabs,.top-actions,#sf-live-hud { display:none !important; }
  .stage { grid-template-columns:1fr; }
  .rightcol { height:auto; overflow:visible; }
}
</style>
</head>
<body data-sisyfus-shell="broadcast">
<header class="topbar">
  <div class="brand"><span class="brand-mark" aria-hidden="true">✳</span><span>Sisyfus 研究工作台</span></div>
  <div class="headline matchinfo">
    <h1 id="title"></h1>
    <div class="sub">
      <span class="tally">
        <span><b id="readyScore">0</b> <span data-t="ready">已就绪</span></span>
        <span><b id="openScore">6</b> <span data-t="open">待完成</span></span>
      </span>
      <span id="phaseMeta"></span>
      <span id="operationMeta" class="mono" hidden></span>
    </div>
  </div>
  <div class="budget bars">
    <div class="budget-row"><span id="programText"></span><span class="meter" aria-hidden="true"><i id="programFill" style="transform:scaleX(0)"></i></span></div>
    <div class="budget-row"><span id="signalText"></span></div>
  </div>
  <div class="top-actions">
    <div class="livechip" id="liveChip" role="status"><span class="dot" aria-hidden="true"></span><span id="connection"></span></div>
    <button class="lang-btn" id="langBtn" type="button" title="切换语言 / switch language">EN</button>
  </div>
</header>

<div class="stage">
  <div class="arena-wrap" id="arenaWrap">
    <div class="graph-head">
      <div>
        <h2 class="graph-title" data-t="map">研究准备</h2>
        <div class="graph-sub" data-t="mapsub">任务规格确定后切换为命题依赖图</div>
      </div>
    </div>
    <div class="preflight-map">
      <svg id="arena" viewBox="0 70 1000 320" preserveAspectRatio="xMidYMid meet" role="img" aria-labelledby="gateTitle">
        <defs><marker id="preArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto"><path d="M0 0 L10 5 L0 10 z"/></marker></defs>
        <g id="edges"></g>
        <g id="bosses"></g>
        <g id="hero" aria-hidden="true"><g class="hero-bob"></g></g>
      </svg>
    </div>
    <div class="announcer" id="announcer" aria-live="polite"></div>
    <div class="unit-card">
      <div class="uc-head"><span class="uc-num" id="gateNumber">P1</span><span class="uc-label" id="gateTitle">任务范围</span><span class="uc-id mono" id="taskId"></span></div>
      <div class="uc-body"><div id="message"></div><div class="uc-detail" id="detail"></div></div>
    </div>
  </div>
  <aside class="rightcol">
    <div class="col-h caps"><span data-t="feed">活动记录</span><span id="feedCount"></span></div>
    <div id="feed"></div>
    <div class="col-h caps"><span data-t="gates">准备步骤</span><span id="gateCount">0 / 6</span></div>
    <div id="quest"></div>
    <div class="col-h caps"><span data-t="waiting">待确认</span><span id="waitState"></span></div>
    <div id="waitingList"></div>
  </aside>
</div>

<div class="deck">
  <button type="button" disabled>▶</button>
  <div class="timeline">
    <div class="tl-track"></div><div class="tl-fill" id="tlFill"></div><div class="tl-cursor" id="tlCursor"></div>
    <div class="tl-times mono"><span id="taskStart"></span><span id="taskNow"></span></div>
  </div>
  <button type="button" disabled data-t="live">实时</button>
  <div class="stamp" id="frameLabel"></div>
</div>
<div class="caster"><span class="tag caps" data-t="caster">当前</span><div id="casterLine"></div></div>

<nav class="tabs">
  <button class="tab active" type="button" data-t="watch">图谱</button>
  <button class="tab" type="button" disabled data-t="report">报告</button>
  <button class="tab" type="button" disabled data-t="goal">目标图</button>
  <button class="tab" type="button" disabled data-t="audit">审计</button>
  <button class="tab" type="button" disabled data-t="events">事件流</button>
</nav>
<div class="preflight-note"><b data-t="preflight">准备阶段</b> · <span data-t="note">确认任务范围、终局目标、数据来源和验证方式后，研究会自动开始；本页会在同一地址切换为命题依赖图。</span></div>

<script>
__SF_LABELS__
const beats = sfBeats();
let A = {}, events = [], misses = 0, lang = 'zh';
try {
 // canonical key shared with the Observatory first, legacy key as read fallback; only en/zh are honoured
 const saved=[localStorage.getItem('sisyfus_lang'),localStorage.getItem('sisyfus-lang')].find(v=>v==='en'||v==='zh');
 if(saved)lang=saved;
} catch (_) {}
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const age = ts => ts ? Math.max(0,(Date.now()-Date.parse(ts))/1000) : 9999;
const fmt = x => { x=Math.max(0,Math.floor(Number(x)||0)); const h=Math.floor(x/3600),m=Math.floor((x%3600)/60),s=x%60;
  return h?`${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`:`${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`; };
const TXT = {
 zh:{ready:'已就绪',open:'待完成',feed:'活动记录',gates:'准备步骤',waiting:'待确认',live:'实时',
  caster:'当前',watch:'图谱',report:'报告',goal:'目标图',audit:'审计',events:'事件流',
  map:'研究准备',mapsub:'任务规格确定后切换为命题依赖图',
  preflight:'准备阶段',note:'确认任务范围、终局目标、数据来源和验证方式后，研究会自动开始；本页会在同一地址切换为命题依赖图。',
  scope:'任务范围',objective:'终局目标',inputs:'高质量输入',claims:'命题图',verifier:'验证者',launch:'自主运行',
  locked:'已完成',active:'进行中',queued:'排队中',needs:'需要你确认',none:'无阻断条件',steps:'准备步骤',elapsed:'已用时',
  awaiting:'等待研究任务',online:'研究准备已开始。',clarify:'需要补充信息后才能继续。',prerun:'准备阶段',no_action:'无需操作'},
 en:{ready:'Ready',open:'Open',feed:'Activity',gates:'Setup steps',waiting:'Waiting on you',live:'Live',
  caster:'Now',watch:'Graph',report:'Report',goal:'Goal graph',audit:'Audit',events:'Events',
  map:'Research setup',mapsub:'Switches to the claim dependency graph once the task specification is settled',
  preflight:'Setup',note:'Once scope, objective, data sources and verification are settled, the study starts on its own and this address switches to the claim graph.',
  scope:'Scope',objective:'Terminal objective',inputs:'Qualified inputs',claims:'Claim graph',verifier:'Verifier',launch:'Autonomous run',
  locked:'Done',active:'Active',queued:'Queued',needs:'Needs you',none:'No blocking gate',steps:'Setup steps',elapsed:'Elapsed',
  awaiting:'Waiting for a research task',online:'Research setup has started.',clarify:'More information is needed before continuing.',prerun:'Setup',no_action:'Nothing needed'}
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
 const clarifying=String(A.status||'').toUpperCase()==='NEEDS_USER'&&String(A.phase||'').toUpperCase()==='CLARIFYING';
 if(i<active)return clarifying&&!g.field?'OPEN':'DONE';
 if(i===active)return String(A.status||'').toUpperCase()==='NEEDS_USER'?'BLOCKED':'ACTIVE';
 return 'OPEN';
}
function renderMap(){
 const active=gateIndex(), states=GATES.map((g,i)=>stateFor(g,i,active));
 $('edges').innerHTML=GATES.slice(0,-1).map((g,i)=>{
   const n=GATES[i+1], cls=i<active?'done':i===active?'hot':'', f=44/Math.max(1,Math.abs(n.y-g.y));
   const x1=g.x+(n.x-g.x)*f, y1=g.y+(n.y-g.y)*f, x2=n.x-(n.x-g.x)*f, y2=n.y-(n.y-g.y)*f;
   return `<path class="edge ${cls}" d="M${x1.toFixed(1)} ${y1.toFixed(1)} L${x2.toFixed(1)} ${y2.toFixed(1)}"/>`;
 }).join('');
 $('bosses').innerHTML=GATES.map((g,i)=>{
   const st=states[i], cls=st==='DONE'?'done':st==='ACTIVE'?'active':st==='BLOCKED'?'active blocked':'';
   return `<g class="gate-node ${cls}" transform="translate(${g.x} ${g.y})">
    <rect class="core" x="-84" y="-38" width="168" height="76" rx="9"/>
    <text class="gate-index" x="-74" y="-20">P${i+1}</text>
    <text class="gate-title" y="5">${esc(t(g.key))}</text>
    <text class="gate-state" y="27">${esc(st==='DONE'?t('locked'):st==='ACTIVE'?t('active'):st==='BLOCKED'?t('needs'):t('queued'))}</text>
   </g>`;
 }).join('');
 const current=GATES[active]||GATES[0];
 $('hero').setAttribute('transform',`translate(${current.x-54} ${current.y-6})`);
 $('gateNumber').textContent=`P${active+1}`;
 $('gateTitle').textContent=t(current.key);
 const ready=readySteps();
 $('readyScore').textContent=String(ready);
 $('openScore').textContent=String(GATES.length-ready);
 $('gateCount').textContent=`${ready} / ${GATES.length}`;
 $('quest').innerHTML=GATES.map((g,i)=>{
   const st=states[i], mark=st==='DONE'?'✓':st==='ACTIVE'?'●':st==='BLOCKED'?'!':'○';
   const label=st==='DONE'?t('locked'):st==='ACTIVE'?t('active'):st==='BLOCKED'?t('needs'):t('queued');
   return `<div class="q-row q-${st}"><div class="q-title"><span class="q-mark">${mark}</span><span>P${i+1} ${esc(t(g.key))}</span><span class="q-state">${esc(label)}</span></div><div class="q-sub">${st==='ACTIVE'||st==='BLOCKED'?esc(A.message||''):''}</div></div>`;
 }).join('');
}
function renderFeed(){
 $('feedCount').textContent=`${events.length}`;
 $('feed').innerHTML=[...events].reverse().map(x=>{
  const st=String(x.status||'').toUpperCase(), cls=st==='ERROR'?'miss':st==='NEEDS_USER'?'soft':st==='COMPLETED'||st==='READY'?'pass':'info';
  return `<div class="feed-row ${cls}"><span class="seq">#${esc(x.seq||'')}</span><span><b>${esc(sfPhase(x.phase))}</b><br>${esc(x.error||x.message||'')}</span><span class="ts">${esc((x.ts||'').slice(11,19))}</span></div>`;
 }).join('')||`<div class="feed-row info"><span class="seq">#0</span><span>${esc(A.message||t('online'))}</span></div>`;
}
function renderWaiting(){
 const questions=((A.metadata||{}).clarification_questions||[]).map(String);
 const waiting=String(A.status||'').toUpperCase()==='NEEDS_USER';
 $('waitState').textContent=waiting?t('needs'):t('no_action');
 $('waitingList').innerHTML=waiting
   ?questions.map((q,i)=>`<div class="wait-row"><b>Q${i+1}</b> · ${esc(q)}</div>`).join('')||`<div class="wait-row"><b>${esc(t('needs'))}</b> · ${esc(A.detail||t('clarify'))}</div>`
   :`<div class="wait-row">${esc(t('none'))}</div>`;
}
/* Header progress counts finished setup steps, so it only moves when a step
   completes; per-operation progress belongs to the active step card. */
function readySteps(){
 const active=gateIndex(), ready=GATES.filter((g,i)=>stateFor(g,i,active)==='DONE').length+(String(A.status||'').toUpperCase()==='READY'?1:0);
 return Math.min(GATES.length,ready);
}
function render(){
 const status=String(A.status||'IDLE').toUpperCase(), stale=beats.stale(A);
 $('title').textContent=A.title||t('awaiting');
 $('phaseMeta').textContent=sfPhase(A.phase);
 $('operationMeta').textContent=A.operation||'';
 $('taskId').textContent=A.task_id||'';
 $('message').textContent=A.error||A.message||'';
 const step=sfProgress(A.progress);
 $('detail').textContent=[step&&step.count?step.text:'',A.detail].filter(Boolean).join(' · ');
 $('casterLine').textContent=A.error||A.message||A.detail||t('online');
 $('frameLabel').textContent=`${t('prerun')} · ${sfPhase(A.phase)}`;
 const ready=readySteps(), pct=Math.round(ready/GATES.length*100);
 $('programFill').style.transform=`scaleX(${pct/100})`;
 $('programText').textContent=`${t('steps')} ${ready}/${GATES.length}`;
 const since=Date.parse(A.task_started_at||'');
 const end=['RUNNING','NEEDS_USER'].includes(status)?Date.now():Date.parse(A.updated_at||'');
 $('signalText').textContent=A.task_id&&Number.isFinite(since)&&Number.isFinite(end)?`${t('elapsed')} ${fmt((end-since)/1000)}`:'';
 $('tlFill').style.width=`${pct}%`; $('tlCursor').style.left=`${pct}%`;
 $('taskStart').textContent=(A.task_started_at||'').slice(11,19);
 $('taskNow').textContent=fmt(A.operation_started_at?Math.max(0,(Date.now()-Date.parse(A.operation_started_at))/1000):A.elapsed_seconds||0);
 const chip=$('liveChip'); chip.className='livechip';
 if(status==='NEEDS_USER')chip.classList.add('waiting');
 if(stale||misses>=3)chip.classList.add('stale');
 if(['COMPLETED','READY'].includes(status))chip.classList.add('ended');
 $('connection').textContent=sfStatus(misses>=3?'RECONNECTING':stale?'STALE':status);
 renderMap(); renderFeed(); renderWaiting();
}
let lastAnnounce='';
function maybeAnnounce(){
 const key=`${A.phase}|${A.status}|${A.operation}`;
 if(lastAnnounce&&key!==lastAnnounce){
  const label=String(A.status||'').toUpperCase()==='NEEDS_USER'?t('needs'):sfPhase(A.phase);
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
  A=next; misses=0; beats.observe(A); maybeAnnounce(); render();
  try{
   const s=await fetch(`snapshot.json?ts=${Date.now()}`,{cache:'no-store'});
   if(s.ok){const j=await s.json();if(j&&j.snapshot&&j.snapshot.snapshot_hash)location.reload();}
  }catch(_){}
 }catch(_){misses+=1;render();}
}
$('langBtn').addEventListener('click',()=>{lang=lang==='zh'?'en':'zh';try{localStorage.setItem('sisyfus_lang',lang);localStorage.setItem('sisyfus-lang',lang);}catch(_){}applyLanguage();});
applyLanguage(); poll(); setInterval(poll,600); setInterval(render,500);
</script>
</body>
</html>
""".replace("__SF_LABELS__", _ACTIVITY_LABELS_JS.strip())


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
