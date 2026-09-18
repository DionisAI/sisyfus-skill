"""Durable portfolio control records. Research verdicts stay in member ledgers."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .models import digest


class PortfolioStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        if not self.root.is_dir():
            raise FileNotFoundError("portfolio directory does not exist")

    @contextmanager
    def lock(self) -> Iterator[None]:
        if os.name != "posix":
            raise RuntimeError("portfolio coordination requires POSIX flock")
        import fcntl
        with (self.root / "portfolio.lock").open("a+") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("another portfolio coordinator holds the lock") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def events(self) -> list[dict]:
        path = self.root / "events.jsonl"
        if not path.exists():
            return []
        result, head = [], None
        with path.open() as handle:
            for index, line in enumerate(handle):
                try:
                    event = json.loads(line)
                except ValueError as exc:
                    raise ValueError("torn portfolio record; reconcile instead of truncating") from exc
                unsigned = {k: v for k, v in event.items() if k != "hash"}
                if event.get("seq") != index or event.get("previous") != head or digest(unsigned) != event.get("hash"):
                    raise ValueError("portfolio audit chain mismatch")
                head = event["hash"]
                result.append(event)
        return result

    def append(self, kind: str, data: dict) -> dict:
        # Caller must hold the portfolio lock for read/decide/append, not just append.
        events = self.events()
        event = {"seq": len(events), "previous": events[-1]["hash"] if events else None,
                 "kind": kind, "data": data}
        event["hash"] = digest(event)
        with (self.root / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def manifest(self) -> dict:
        value = json.loads((self.root / "manifest.json").read_text())
        records = self.events()
        if not records or records[0]["kind"] != "REGISTERED" or records[0]["data"] != value:
            raise ValueError("portfolio manifest differs from registered contract")
        return value

    def operations(self) -> list[dict]:
        operations: dict[str, dict] = {}
        pending = None
        for event in self.events():
            kind, data = event["kind"], event["data"]
            if kind == "INTENT":
                oid = data["operation_id"]
                if oid in operations or pending is not None:
                    raise ValueError("duplicate or overlapping portfolio intent")
                operations[oid] = {"intent": data, "intent_hash": event["hash"], "settlement": None, "release": None}
                pending = oid
            elif kind in {"SETTLED", "RELEASED"}:
                oid = data["operation_id"]
                if pending != oid or oid not in operations:
                    raise ValueError("portfolio settlement has no matching intent")
                operations[oid]["settlement" if kind == "SETTLED" else "release"] = data
                pending = None
        return list(operations.values())
