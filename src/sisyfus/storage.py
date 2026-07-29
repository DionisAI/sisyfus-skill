from __future__ import annotations

from pathlib import Path
from typing import Any

from .paths import ensure_layout
from .utils import append_jsonl, read_jsonl, utc_now, write_json


class EventLog:
    def __init__(self, run_dir: Path, *, run_id: str, goal_id: str) -> None:
        self.run_dir = run_dir
        self.run_id = run_id
        self.goal_id = goal_id
        self.path = run_dir / "events.jsonl"
        run_dir.mkdir(parents=True, exist_ok=True)

    def append(self, event: str, *, round_index: int | None = None, status: str | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
        item = {
            "ts": utc_now(),
            "event": event,
            "run_id": self.run_id,
            "goal_id": self.goal_id,
            "round": round_index,
            "status": status,
            "data": data or {},
        }
        append_jsonl(self.path, item)
        return item


class MemoryBroker:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.sf = ensure_layout(root)

    @property
    def memory_dir(self) -> Path:
        return self.sf / "memory"

    @property
    def tasks_dir(self) -> Path:
        return self.sf / "tasks"

    def append_fact(self, item: dict[str, Any]) -> None:
        item = {"type": "fact", "created_at": utc_now(), "status": "active", **item}
        append_jsonl(self.memory_dir / "facts.jsonl", item)

    def append_failure(self, item: dict[str, Any]) -> None:
        item = {"type": "failure", "created_at": utc_now(), "status": "active", **item}
        append_jsonl(self.memory_dir / "failures.jsonl", item)

    def append_hypothesis(self, item: dict[str, Any]) -> None:
        item = {"type": "hypothesis", "created_at": utc_now(), "status": "active", **item}
        append_jsonl(self.memory_dir / "hypotheses.jsonl", item)

    def append_open_task(self, item: dict[str, Any]) -> None:
        item = {"created_at": utc_now(), "status": "open", **item}
        append_jsonl(self.tasks_dir / "open.jsonl", item)

    def apply_distill(self, distill: dict[str, Any]) -> dict[str, int]:
        counts = {"facts": 0, "failures": 0, "hypotheses": 0, "tasks": 0}
        for fact in distill.get("facts", []):
            self.append_fact(fact)
            counts["facts"] += 1
        for failure in distill.get("failures", []):
            self.append_failure(failure)
            counts["failures"] += 1
        for hypothesis in distill.get("hypotheses", []):
            self.append_hypothesis(hypothesis)
            counts["hypotheses"] += 1
        for task in distill.get("tasks", []):
            self.append_open_task(task)
            counts["tasks"] += 1
        write_json(self.sf / "last_apply_distill.json", {"applied_at": utc_now(), "counts": counts, "run_id": distill.get("run_id")})
        return counts

    def read_open_tasks(self) -> list[dict[str, Any]]:
        return read_jsonl(self.tasks_dir / "open.jsonl")

    def read_failures(self) -> list[dict[str, Any]]:
        return read_jsonl(self.memory_dir / "failures.jsonl")
