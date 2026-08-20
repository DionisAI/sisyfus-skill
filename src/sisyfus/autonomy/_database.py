from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from ._common import _decode_json
from .models import canonical_json


class StoreCore:
    """SQLite-backed control plane for long-running autonomous continuations.

    The store deliberately keeps external work outside database transactions.
    Workers claim a renewable lease, then every mutation uses optimistic
    ``version`` checks. This prevents stale planners, duplicate supervisors and
    restarted workers from silently overwriting newer truth.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _migrate(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS opportunities (
                    id TEXT PRIMARY KEY,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL CHECK(confidence >= 0.0 AND confidence <= 1.0),
                    status TEXT NOT NULL,
                    not_before TEXT,
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS continuations (
                    id TEXT PRIMARY KEY,
                    opportunity_id TEXT NOT NULL UNIQUE REFERENCES opportunities(id),
                    objective TEXT NOT NULL,
                    state TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    step_index INTEGER NOT NULL DEFAULT 0,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL CHECK(max_attempts > 0),
                    next_wake_at TEXT,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS continuation_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    continuation_id TEXT NOT NULL REFERENCES continuations(id),
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY,
                    continuation_id TEXT NOT NULL REFERENCES continuations(id),
                    step_index INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    capability TEXT,
                    risk_tier TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY,
                    continuation_id TEXT NOT NULL REFERENCES continuations(id),
                    decision_id TEXT NOT NULL UNIQUE REFERENCES decisions(id),
                    verifier_id TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS experiences (
                    id TEXT PRIMARY KEY,
                    pattern_key TEXT NOT NULL,
                    scope_hash TEXT NOT NULL,
                    polarity TEXT NOT NULL,
                    claim TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    confidence REAL NOT NULL CHECK(confidence >= 0.0 AND confidence <= 1.0),
                    status TEXT NOT NULL,
                    supports INTEGER NOT NULL DEFAULT 0,
                    counterexamples INTEGER NOT NULL DEFAULT 0,
                    evidence_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(pattern_key, scope_hash, polarity)
                );

                CREATE INDEX IF NOT EXISTS idx_opportunities_status_priority
                    ON opportunities(status, priority DESC, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_continuations_due
                    ON continuations(state, next_wake_at, lease_expires_at);
                CREATE INDEX IF NOT EXISTS idx_events_continuation_seq
                    ON continuation_events(continuation_id, seq);
                CREATE INDEX IF NOT EXISTS idx_decisions_continuation_step
                    ON decisions(continuation_id, step_index);
                CREATE INDEX IF NOT EXISTS idx_experiences_pattern
                    ON experiences(pattern_key, status);
                """
            )
            connection.execute(
                "INSERT INTO schema_meta(key, value) VALUES('schema_version', '1') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )
        finally:
            connection.close()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        for key in ("payload_json", "data_json", "result_json", "scope_json", "evidence_ids_json"):
            if key in item:
                default: Any = [] if key == "evidence_ids_json" else {}
                item[key.removesuffix("_json")] = _decode_json(item.pop(key), default)
        return item

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        continuation_id: str,
        event_type: str,
        actor: str,
        data: Mapping[str, Any] | None,
        now: str,
    ) -> dict[str, Any]:
        event_id = f"evt_{uuid.uuid4().hex}"
        cursor = connection.execute(
            """
            INSERT INTO continuation_events(event_id, continuation_id, event_type, actor, data_json, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (event_id, continuation_id, event_type, actor, canonical_json(data or {}), now),
        )
        return {
            "seq": int(cursor.lastrowid),
            "event_id": event_id,
            "continuation_id": continuation_id,
            "event_type": event_type,
            "actor": actor,
            "data": dict(data or {}),
            "created_at": now,
        }

