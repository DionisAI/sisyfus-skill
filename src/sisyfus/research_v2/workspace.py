from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platform
    fcntl = None  # type: ignore[assignment]

from ..paths import ensure_layout, find_project_root
from ..utils import read_jsonl, run_id as make_run_id
from .models import EVENT_SCHEMA_VERSION, EVENT_TYPES, canonical_hash, normalize_task_spec, safe_id


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_ts(value: str) -> str:
    """Normalize any ISO timestamp into the canonical UTC 'Z' second-precision form.

    All persisted wait timestamps share this format so ordering can be checked
    with plain string comparison during deterministic replay.
    """
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def add_minutes(value: str, minutes: int) -> str:
    parsed = datetime.fromisoformat(canonical_ts(value).replace("Z", "+00:00"))
    shifted = parsed + timedelta(minutes=int(minutes))
    return shifted.isoformat().replace("+00:00", "Z")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            Path(tmp_name).unlink(missing_ok=True)
        except OSError:
            pass


def atomic_write_json(path: Path, data: Any) -> None:
    _atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n")


@dataclass(frozen=True)
class ResearchWorkspace:
    root: Path
    research_id: str
    path: Path

    @property
    def task_path(self) -> Path:
        return self.path / "task.json"

    @property
    def events_path(self) -> Path:
        return self.path / "events.jsonl"

    @property
    def snapshot_path(self) -> Path:
        return self.path / "snapshot.json"

    @property
    def goal_graph_path(self) -> Path:
        return self.path / "goal_graph.json"

    @property
    def execution_graph_path(self) -> Path:
        return self.path / "execution_graph.json"

    @property
    def evidence_graph_path(self) -> Path:
        return self.path / "evidence_graph.json"

    @property
    def frontier_path(self) -> Path:
        return self.path / "frontier.json"

    @property
    def lessons_path(self) -> Path:
        return self.path / "lessons.json"

    @property
    def artifacts_dir(self) -> Path:
        return self.path / "artifacts"

    @property
    def attempts_dir(self) -> Path:
        return self.path / "attempts"

    @property
    def report_dir(self) -> Path:
        return self.path / "report"

    @property
    def report_path(self) -> Path:
        return self.report_dir / "index.html"

    @property
    def report_snapshot_path(self) -> Path:
        return self.report_dir / "snapshot.json"

    @property
    def report_frames_path(self) -> Path:
        return self.report_dir / "frames.json"

    @property
    def i18n_path(self) -> Path:
        """Presentation-layer translation sidecar; never part of the event chain."""
        return self.path / "i18n.json"

    @property
    def index_path(self) -> Path:
        return self.root / ".sisyfus" / "research" / "index.jsonl"

    @classmethod
    def create(cls, root: str | Path | None, raw_spec: dict[str, Any], *, actor: str = "user") -> "ResearchWorkspace":
        root_path = find_project_root(root)
        sf = ensure_layout(root_path)
        research_root = sf / "research" / "runs"
        research_root.mkdir(parents=True, exist_ok=True)
        spec = normalize_task_spec(raw_spec)
        research_id = safe_id(make_run_id(prefix=f"research-{spec['id']}-"))
        path = research_root / research_id
        path.mkdir(parents=True, exist_ok=False)
        for directory in ("artifacts", "attempts", "report"):
            (path / directory).mkdir(parents=True, exist_ok=True)
        workspace = cls(root=root_path, research_id=research_id, path=path)
        atomic_write_json(workspace.task_path, spec)
        workspace.events_path.touch()
        workspace.append_event(
            "RUN_CREATED",
            actor=actor,
            data={"task_id": spec["id"], "topic": spec["topic"], "task_hash": canonical_hash(spec)},
        )
        workspace.append_event("SPEC_LOCKED", actor="system", data={"task_hash": canonical_hash(spec)})
        workspace._append_index(
            {
                "schema_version": "sisyfus.research_index.v2",
                "created_at": utc_now(),
                "research_id": research_id,
                "task_id": spec["id"],
                "topic": spec["topic"],
                "status": "ACTIVE",
                "path": str(path.relative_to(root_path)),
            }
        )
        return workspace

    @classmethod
    def load(cls, root: str | Path | None, research_id: str) -> "ResearchWorkspace":
        root_path = find_project_root(root)
        ensure_layout(root_path)
        if research_id == "latest":
            items = cls.list(root_path)
            if not items:
                raise FileNotFoundError("no research runs exist")
            research_id = str(items[0]["research_id"])
        path = root_path / ".sisyfus" / "research" / "runs" / research_id
        if not path.exists():
            raise FileNotFoundError(f"research run not found: {research_id}")
        return cls(root=root_path, research_id=research_id, path=path)

    @classmethod
    def list(cls, root: str | Path | None, *, limit: int = 100) -> list[dict[str, Any]]:
        root_path = find_project_root(root)
        index_path = root_path / ".sisyfus" / "research" / "index.jsonl"
        items = read_jsonl(index_path)
        # Index is append-only; keep the latest row for each research id.
        latest: dict[str, dict[str, Any]] = {}
        for item in items:
            rid = str(item.get("research_id") or "")
            if rid:
                latest[rid] = item
        if not latest:
            runs_dir = root_path / ".sisyfus" / "research" / "runs"
            for path in sorted(runs_dir.glob("research-*"), reverse=True) if runs_dir.exists() else []:
                task_path = path / "task.json"
                if task_path.exists():
                    task = json.loads(task_path.read_text(encoding="utf-8"))
                    latest[path.name] = {
                        "research_id": path.name,
                        "task_id": task.get("id"),
                        "topic": task.get("topic"),
                        "status": "UNKNOWN",
                        "path": str(path.relative_to(root_path)),
                    }
        return sorted(latest.values(), key=lambda x: str(x.get("created_at") or x.get("research_id")), reverse=True)[:limit]

    def read_task(self, *, verify_lock: bool = True) -> dict[str, Any]:
        task = json.loads(self.task_path.read_text(encoding="utf-8"))
        if verify_lock and self.events_path.exists():
            events = self.read_events(verify_chain=True)
            locked_hash = next(
                (
                    (event.get("data") or {}).get("task_hash")
                    for event in reversed(events)
                    if event.get("event_type") == "SPEC_LOCKED"
                ),
                None,
            )
            if locked_hash and canonical_hash(task) != locked_hash:
                raise ValueError(
                    f"locked TaskSpec hash mismatch for {self.research_id}; "
                    "create a new research run instead of editing task.json"
                )
        return task

    def read_events(self, *, verify_chain: bool = True) -> list[dict[str, Any]]:
        events = read_jsonl(self.events_path)
        if verify_chain:
            previous_hash: str | None = None
            for index, event in enumerate(events, start=1):
                if int(event.get("seq") or 0) != index:
                    raise ValueError(f"event sequence gap at {self.events_path}:{index}")
                if event.get("prev_hash") != previous_hash:
                    raise ValueError(f"event hash chain mismatch at {self.events_path}:{index}")
                unsigned = {k: v for k, v in event.items() if k != "event_hash"}
                expected = canonical_hash(unsigned)
                if event.get("event_hash") != expected:
                    raise ValueError(f"event hash mismatch at {self.events_path}:{index}")
                previous_hash = expected
        return events

    @contextmanager
    def _event_write_lock(self) -> Iterator[None]:
        """Serialize read-chain-then-append across processes.

        The event chain is seq-numbered and hash-linked; two concurrent
        appenders (a CLI command and the live Observatory daemon settling a
        due wait) that both read length N would both write seq N+1 and break
        the chain. An exclusive advisory lock makes the critical section
        atomic; on platforms without fcntl it degrades to the old behavior.
        """
        if fcntl is None:
            yield
            return
        with (self.path / ".events.lock").open("w") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def append_event(
        self,
        event_type: str,
        *,
        actor: str,
        data: dict[str, Any] | None = None,
        visibility: str = "normal",
        expected_seq: int | None = None,
    ) -> dict[str, Any]:
        event_type = str(event_type).upper()
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unsupported research event type: {event_type}")
        with self._event_write_lock():
            return self._append_event_locked(
                event_type, actor=actor, data=data, visibility=visibility, expected_seq=expected_seq
            )

    def _append_event_locked(
        self,
        event_type: str,
        *,
        actor: str,
        data: dict[str, Any] | None,
        visibility: str,
        expected_seq: int | None,
    ) -> dict[str, Any]:
        events = self.read_events(verify_chain=True)
        seq = len(events) + 1
        if expected_seq is not None and expected_seq != seq:
            raise RuntimeError(f"concurrent event append detected: expected seq {expected_seq}, actual {seq}")
        previous_hash = events[-1].get("event_hash") if events else None
        event_id = f"evt-{seq:06d}-{hashlib.sha256(f'{self.research_id}:{seq}:{os.getpid()}'.encode()).hexdigest()[:8]}"
        event = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_id": event_id,
            "seq": seq,
            "ts": utc_now(),
            "research_id": self.research_id,
            "event_type": event_type,
            "actor": str(actor),
            "visibility": str(visibility),
            "prev_hash": previous_hash,
            "data": data or {},
        }
        event["event_hash"] = canonical_hash(event)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def write_projection(self, name: str, data: Any) -> Path:
        allowed = {
            "snapshot": self.snapshot_path,
            "goal_graph": self.goal_graph_path,
            "execution_graph": self.execution_graph_path,
            "evidence_graph": self.evidence_graph_path,
            "frontier": self.frontier_path,
            "lessons": self.lessons_path,
        }
        if name not in allowed:
            raise ValueError(f"unknown projection name: {name}")
        atomic_write_json(allowed[name], data)
        return allowed[name]

    def write_attempt_json(self, attempt_id: str, filename: str, data: Any) -> Path:
        path = self.attempts_dir / safe_id(attempt_id) / filename
        atomic_write_json(path, data)
        return path

    def write_attempt_text(self, attempt_id: str, filename: str, text: str) -> Path:
        path = self.attempts_dir / safe_id(attempt_id) / filename
        _atomic_write_text(path, text)
        return path

    def add_artifact(self, source: Path, *, filename: str | None = None) -> dict[str, Any]:
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(source)
        target_name = safe_id(filename or source.name, default="artifact")
        target = self.artifacts_dir / target_name
        if target.exists():
            stem, suffix = target.stem, target.suffix
            target = target.with_name(f"{stem}-{hashlib.sha256(source.read_bytes()).hexdigest()[:8]}{suffix}")
        shutil.copy2(source, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        return {
            "id": f"artifact-{digest[:12]}",
            "path": str(target.relative_to(self.path)),
            "sha256": digest,
            "size_bytes": target.stat().st_size,
        }

    def update_index(self, snapshot: dict[str, Any]) -> None:
        self._append_index(
            {
                "schema_version": "sisyfus.research_index.v2",
                "created_at": snapshot.get("created_at"),
                "updated_at": utc_now(),
                "research_id": self.research_id,
                "task_id": snapshot.get("task_id"),
                "topic": snapshot.get("topic"),
                "status": snapshot.get("run_status"),
                "objective_progress": (snapshot.get("progress") or {}).get("objective"),
                "epistemic_progress": (snapshot.get("progress") or {}).get("epistemic"),
                "path": str(self.path.relative_to(self.root)),
            }
        )

    def _append_index(self, item: dict[str, Any]) -> None:
        index_path = self.root / ".sisyfus" / "research" / "index.jsonl"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        with index_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, sort_keys=True, ensure_ascii=False, default=str) + "\n")
