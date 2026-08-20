from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .models import (
    ContinuationState,
    Decision,
    DecisionKind,
    ExperienceLesson,
    OpportunitySignal,
    OpportunityStatus,
    TERMINAL_STATES,
    VerificationResult,
    Verdict,
    canonical_json,
    normalize_statement,
    stable_id,
    utc_now,
)
from .policy import (
    AttemptBudgetExceeded,
    AutonomyError,
    ConcurrentUpdate,
    IdempotencyConflictError,
    IncompatibleSchemaError,
    InvalidTransition,
    LeaseLost,
    NotFoundError,
    VerificationRequiredError,
)


def _parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_ts(value: str) -> str:
    return _parse_ts(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _add_seconds(value: str, seconds: float) -> str:
    return (
        _parse_ts(value) + timedelta(seconds=max(0.0, float(seconds)))
    ).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _decode(value: str | None, default: Any) -> Any:
    if value in {None, ""}:
        return default
    return json.loads(str(value))


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


_ALLOWED_TRANSITIONS: dict[ContinuationState, set[ContinuationState]] = {
    ContinuationState.READY: {
        ContinuationState.RUNNING,
        ContinuationState.BLOCKED,
        ContinuationState.CANCELLED,
        ContinuationState.EXHAUSTED,
    },
    ContinuationState.RUNNING: {
        ContinuationState.READY,
        ContinuationState.WAITING,
        ContinuationState.VERIFYING,
        ContinuationState.SUCCEEDED,
        ContinuationState.FAILED,
        ContinuationState.BLOCKED,
        ContinuationState.CANCELLED,
        ContinuationState.EXHAUSTED,
    },
    ContinuationState.VERIFYING: {
        ContinuationState.READY,
        ContinuationState.WAITING,
        ContinuationState.SUCCEEDED,
        ContinuationState.FAILED,
        ContinuationState.BLOCKED,
        ContinuationState.CANCELLED,
        ContinuationState.EXHAUSTED,
    },
    ContinuationState.WAITING: {
        ContinuationState.RUNNING,
        ContinuationState.BLOCKED,
        ContinuationState.CANCELLED,
        ContinuationState.EXHAUSTED,
    },
    ContinuationState.SUCCEEDED: set(),
    ContinuationState.FAILED: {ContinuationState.READY, ContinuationState.CANCELLED},
    ContinuationState.BLOCKED: {ContinuationState.READY, ContinuationState.CANCELLED},
    ContinuationState.CANCELLED: set(),
    ContinuationState.EXHAUSTED: {ContinuationState.READY, ContinuationState.CANCELLED},
}


class AutonomyStore:
    """Canonical SQLite-WAL store for verifier-gated autonomous continuations."""

    SCHEMA_VERSION = 2

    def __init__(self, path: str | Path, *, experience_validation_threshold: int = 2) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.experience_validation_threshold = max(2, int(experience_validation_threshold))
        self._migrate()

    @classmethod
    def migrate_legacy(cls, path: str | Path) -> Path:
        database = Path(path).expanduser().resolve()
        if not database.exists():
            raise FileNotFoundError(database)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = database.with_name(f"{database.name}.legacy-{stamp}.bak")
        counter = 1
        while backup.exists():
            backup = database.with_name(f"{database.name}.legacy-{stamp}-{counter}.bak")
            counter += 1
        shutil.copy2(database, backup)
        database.unlink()
        for suffix in ("-wal", "-shm"):
            Path(str(database) + suffix).unlink(missing_ok=True)
        return backup

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 30000")
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
            tables = {
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            if tables:
                if "metadata" not in tables:
                    raise IncompatibleSchemaError(
                        "legacy autonomy schema detected; run sisyfus-autonomy migrate-legacy"
                    )
                row = connection.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()
                if row is None or str(row["value"]) != str(self.SCHEMA_VERSION):
                    raise IncompatibleSchemaError(
                        "legacy autonomy schema detected; run sisyfus-autonomy migrate-legacy"
                    )
                required = {
                    "source",
                    "kind",
                    "title",
                    "objective",
                    "occurrence_count",
                }
                columns = {
                    str(row["name"])
                    for row in connection.execute("PRAGMA table_info(opportunities)").fetchall()
                }
                if not required.issubset(columns):
                    raise IncompatibleSchemaError(
                        "legacy autonomy schema detected; run sisyfus-autonomy migrate-legacy"
                    )
                return

            connection.executescript(
                """
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE opportunities (
                    id TEXT PRIMARY KEY,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    priority REAL NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL CHECK(confidence >= 0.0 AND confidence <= 1.0),
                    status TEXT NOT NULL,
                    rejection_reason TEXT,
                    occurrence_count INTEGER NOT NULL DEFAULT 1,
                    not_before TEXT,
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE continuations (
                    id TEXT PRIMARY KEY,
                    opportunity_id TEXT NOT NULL UNIQUE REFERENCES opportunities(id),
                    objective TEXT NOT NULL,
                    state TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    step_index INTEGER NOT NULL DEFAULT 0,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL CHECK(max_attempts > 0),
                    context_json TEXT NOT NULL,
                    next_wake_at TEXT,
                    lease_owner TEXT,
                    lease_token TEXT,
                    lease_expires_at TEXT,
                    heartbeat_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE decisions (
                    id TEXT PRIMARY KEY,
                    continuation_id TEXT NOT NULL REFERENCES continuations(id),
                    step_index INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    capability TEXT,
                    risk_tier INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    recovery_required INTEGER NOT NULL DEFAULT 0,
                    evidence_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE evidence (
                    id TEXT PRIMARY KEY,
                    continuation_id TEXT NOT NULL REFERENCES continuations(id),
                    decision_id TEXT NOT NULL UNIQUE REFERENCES decisions(id),
                    verifier_id TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    assurance TEXT NOT NULL,
                    verification_mode TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE experiences (
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
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(pattern_key, scope_hash, polarity)
                );

                CREATE TABLE experience_observations (
                    experience_id TEXT NOT NULL REFERENCES experiences(id),
                    evidence_id TEXT NOT NULL REFERENCES evidence(id),
                    outcome TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(experience_id, evidence_id, outcome)
                );

                CREATE TABLE events (
                    seq INTEGER PRIMARY KEY,
                    id TEXT NOT NULL UNIQUE,
                    ts TEXT NOT NULL,
                    continuation_id TEXT,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    prev_hash TEXT,
                    event_hash TEXT NOT NULL UNIQUE
                );

                CREATE INDEX idx_opportunities_status_priority
                    ON opportunities(status, priority DESC, created_at ASC);
                CREATE INDEX idx_continuations_due
                    ON continuations(state, next_wake_at, lease_expires_at);
                CREATE INDEX idx_decisions_pending
                    ON decisions(continuation_id, status, created_at);
                CREATE INDEX idx_evidence_continuation
                    ON evidence(continuation_id, created_at);
                CREATE INDEX idx_experiences_status
                    ON experiences(status, updated_at);
                """
            )
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(self.SCHEMA_VERSION),),
            )
        finally:
            connection.close()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        for key in ("payload_json", "context_json", "result_json"):
            if key in item:
                default: Any = {}
                item[key.removesuffix("_json")] = _decode(item.pop(key), default)
        if "recovery_required" in item:
            item["recovery_required"] = bool(item["recovery_required"])
        return item

    def _append_event(
        self,
        connection: sqlite3.Connection,
        *,
        continuation_id: str | None,
        entity_type: str,
        entity_id: str,
        event_type: str,
        actor: str,
        data: Mapping[str, Any] | None,
        now: str,
    ) -> dict[str, Any]:
        row = connection.execute(
            "SELECT seq, event_hash FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        seq = int(row["seq"]) + 1 if row else 1
        prev_hash = str(row["event_hash"]) if row else None
        item = {
            "seq": seq,
            "id": f"evt_{uuid.uuid4().hex}",
            "ts": now,
            "continuation_id": continuation_id,
            "entity_type": str(entity_type),
            "entity_id": str(entity_id),
            "event_type": str(event_type).upper(),
            "actor": str(actor),
            "data": dict(data or {}),
            "prev_hash": prev_hash,
        }
        event_hash = _sha256(item)
        connection.execute(
            """
            INSERT INTO events(
                seq, id, ts, continuation_id, entity_type, entity_id,
                event_type, actor, data_json, prev_hash, event_hash
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                seq,
                item["id"],
                now,
                continuation_id,
                item["entity_type"],
                item["entity_id"],
                item["event_type"],
                item["actor"],
                canonical_json(item["data"]),
                prev_hash,
                event_hash,
            ),
        )
        return {**item, "event_hash": event_hash}

    # ------------------------------------------------------------------
    # Opportunities
    # ------------------------------------------------------------------
    def submit_opportunity(
        self,
        signal: OpportunitySignal,
        *,
        now: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        item = signal.normalized()
        current = _canonical_ts(now or utc_now())
        key = item.dedupe_key or _sha256(
            {
                "source": item.source,
                "kind": item.kind,
                "title": item.title,
                "objective": item.objective,
                "payload": dict(item.payload),
            }
        )
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM opportunities WHERE dedupe_key = ?", (key,)
            ).fetchone()
            if existing is not None:
                connection.execute(
                    """
                    UPDATE opportunities
                    SET occurrence_count = occurrence_count + 1,
                        priority = MAX(priority, ?), confidence = MAX(confidence, ?),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (item.priority, item.confidence, current, existing["id"]),
                )
                self._append_event(
                    connection,
                    continuation_id=None,
                    entity_type="opportunity",
                    entity_id=str(existing["id"]),
                    event_type="OPPORTUNITY_SEEN_AGAIN",
                    actor="discovery",
                    data={"dedupe_key": key},
                    now=current,
                )
                row = connection.execute(
                    "SELECT * FROM opportunities WHERE id = ?", (existing["id"],)
                ).fetchone()
                assert row is not None
                return self._row(row) or {}, False

            opportunity_id = f"opp_{uuid.uuid4().hex}"
            connection.execute(
                """
                INSERT INTO opportunities(
                    id, dedupe_key, source, kind, title, objective, payload_json,
                    priority, confidence, status, rejection_reason, occurrence_count,
                    not_before, expires_at, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, ?, ?, ?, ?)
                """,
                (
                    opportunity_id,
                    key,
                    item.source,
                    item.kind,
                    item.title,
                    item.objective,
                    canonical_json(dict(item.payload)),
                    item.priority,
                    item.confidence,
                    OpportunityStatus.OPEN.value,
                    item.not_before,
                    item.expires_at,
                    current,
                    current,
                ),
            )
            self._append_event(
                connection,
                continuation_id=None,
                entity_type="opportunity",
                entity_id=opportunity_id,
                event_type="OPPORTUNITY_DISCOVERED",
                actor="discovery",
                data={"source": item.source, "kind": item.kind, "dedupe_key": key},
                now=current,
            )
            row = connection.execute(
                "SELECT * FROM opportunities WHERE id = ?", (opportunity_id,)
            ).fetchone()
            assert row is not None
            return self._row(row) or {}, True

    # Compatibility with the earlier name used in the branch.
    ingest_opportunity = submit_opportunity

    def list_opportunities(self, *, status: str | None = None) -> list[dict[str, Any]]:
        with self._transaction(immediate=False) as connection:
            if status:
                rows = connection.execute(
                    "SELECT * FROM opportunities WHERE status = ? ORDER BY priority DESC, created_at",
                    (status.upper(),),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM opportunities ORDER BY priority DESC, created_at"
                ).fetchall()
        return [self._row(row) or {} for row in rows]

    def admit_opportunity(
        self,
        opportunity_id: str,
        *,
        objective: str | None = None,
        max_attempts: int = 8,
        context: Mapping[str, Any] | None = None,
        actor: str = "admission",
        now: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        if int(max_attempts) < 1:
            raise ValueError("max_attempts must be positive")
        current = _canonical_ts(now or utc_now())
        with self._transaction() as connection:
            opportunity = connection.execute(
                "SELECT * FROM opportunities WHERE id = ?", (opportunity_id,)
            ).fetchone()
            if opportunity is None:
                raise NotFoundError(f"opportunity not found: {opportunity_id}")
            existing = connection.execute(
                "SELECT * FROM continuations WHERE opportunity_id = ?", (opportunity_id,)
            ).fetchone()
            if existing is not None:
                return self._row(existing) or {}, False
            if opportunity["status"] != OpportunityStatus.OPEN.value:
                raise AutonomyError(
                    f"opportunity cannot be admitted from status {opportunity['status']}"
                )
            continuation_id = f"cont_{uuid.uuid4().hex}"
            connection.execute(
                """
                INSERT INTO continuations(
                    id, opportunity_id, objective, state, version, step_index,
                    attempt_count, max_attempts, context_json, next_wake_at,
                    lease_owner, lease_token, lease_expires_at, heartbeat_at,
                    last_error, created_at, updated_at
                ) VALUES(?, ?, ?, ?, 1, 0, 0, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?)
                """,
                (
                    continuation_id,
                    opportunity_id,
                    str(objective or opportunity["objective"]),
                    ContinuationState.READY.value,
                    int(max_attempts),
                    canonical_json(dict(context or {})),
                    current,
                    current,
                ),
            )
            connection.execute(
                "UPDATE opportunities SET status = ?, updated_at = ? WHERE id = ?",
                (OpportunityStatus.ADMITTED.value, current, opportunity_id),
            )
            self._append_event(
                connection,
                continuation_id=continuation_id,
                entity_type="continuation",
                entity_id=continuation_id,
                event_type="CONTINUATION_CREATED",
                actor=actor,
                data={"opportunity_id": opportunity_id, "max_attempts": int(max_attempts)},
                now=current,
            )
            row = connection.execute(
                "SELECT * FROM continuations WHERE id = ?", (continuation_id,)
            ).fetchone()
            assert row is not None
            return self._row(row) or {}, True

    # ------------------------------------------------------------------
    # Continuations and leases
    # ------------------------------------------------------------------
    def get_continuation(self, continuation_id: str) -> dict[str, Any]:
        with self._transaction(immediate=False) as connection:
            row = connection.execute(
                "SELECT * FROM continuations WHERE id = ?", (continuation_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(f"continuation not found: {continuation_id}")
        return self._row(row) or {}

    def list_continuations(self, *, state: str | None = None) -> list[dict[str, Any]]:
        with self._transaction(immediate=False) as connection:
            if state:
                rows = connection.execute(
                    "SELECT * FROM continuations WHERE state = ? ORDER BY created_at",
                    (state.upper(),),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM continuations ORDER BY created_at"
                ).fetchall()
        return [self._row(row) or {} for row in rows]

    def claim_due_continuation(
        self,
        worker_id: str,
        *,
        lease_seconds: float = 60.0,
        now: str | None = None,
    ) -> dict[str, Any] | None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        current = _canonical_ts(now or utc_now())
        expires = _add_seconds(current, lease_seconds)
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM continuations
                WHERE state IN (?, ?)
                  AND (next_wake_at IS NULL OR next_wake_at <= ?)
                  AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                ORDER BY step_index ASC, created_at, id
                LIMIT 1
                """,
                (
                    ContinuationState.READY.value,
                    ContinuationState.WAITING.value,
                    current,
                    current,
                ),
            ).fetchone()
            if row is None:
                return None
            token = secrets.token_urlsafe(24)
            cursor = connection.execute(
                """
                UPDATE continuations
                SET state = ?, version = version + 1, lease_owner = ?, lease_token = ?,
                    lease_expires_at = ?, heartbeat_at = ?, next_wake_at = NULL, updated_at = ?
                WHERE id = ? AND version = ? AND state IN (?, ?)
                  AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                """,
                (
                    ContinuationState.RUNNING.value,
                    worker_id,
                    token,
                    expires,
                    current,
                    current,
                    row["id"],
                    row["version"],
                    ContinuationState.READY.value,
                    ContinuationState.WAITING.value,
                    current,
                ),
            )
            if cursor.rowcount != 1:
                raise ConcurrentUpdate(f"lease race lost for continuation {row['id']}")
            self._append_event(
                connection,
                continuation_id=str(row["id"]),
                entity_type="continuation",
                entity_id=str(row["id"]),
                event_type="LEASE_ACQUIRED",
                actor=worker_id,
                data={"lease_expires_at": expires, "previous_state": row["state"]},
                now=current,
            )
            claimed = connection.execute(
                "SELECT * FROM continuations WHERE id = ?", (row["id"],)
            ).fetchone()
            assert claimed is not None
            return self._row(claimed)

    # Compatibility alias.
    lease_next = claim_due_continuation

    def renew_lease(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_token: str,
        lease_seconds: float = 60.0,
        now: str | None = None,
    ) -> dict[str, Any]:
        current = _canonical_ts(now or utc_now())
        expires = _add_seconds(current, lease_seconds)
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE continuations
                SET lease_expires_at = ?, heartbeat_at = ?, updated_at = ?
                WHERE id = ? AND lease_owner = ? AND lease_token = ?
                  AND lease_expires_at IS NOT NULL AND lease_expires_at > ?
                  AND state IN (?, ?)
                """,
                (
                    expires,
                    current,
                    current,
                    continuation_id,
                    worker_id,
                    lease_token,
                    current,
                    ContinuationState.RUNNING.value,
                    ContinuationState.VERIFYING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise LeaseLost(f"lease expired or is not owned by {worker_id!r}")
            self._append_event(
                connection,
                continuation_id=continuation_id,
                entity_type="continuation",
                entity_id=continuation_id,
                event_type="LEASE_RENEWED",
                actor=worker_id,
                data={"lease_expires_at": expires},
                now=current,
            )
            row = connection.execute(
                "SELECT * FROM continuations WHERE id = ?", (continuation_id,)
            ).fetchone()
            assert row is not None
            return self._row(row) or {}

    def _owned_row(
        self,
        connection: sqlite3.Connection,
        continuation_id: str,
        *,
        worker_id: str,
        lease_token: str,
        expected_version: int,
        now: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM continuations WHERE id = ?", (continuation_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"continuation not found: {continuation_id}")
        if int(row["version"]) != int(expected_version):
            raise ConcurrentUpdate(
                f"continuation {continuation_id} version is {row['version']}; expected {expected_version}"
            )
        if row["lease_owner"] != worker_id or row["lease_token"] != lease_token:
            raise LeaseLost(f"continuation {continuation_id} is not leased by {worker_id}")
        if not row["lease_expires_at"] or str(row["lease_expires_at"]) <= now:
            raise LeaseLost(f"lease expired for continuation {continuation_id}")
        if row["state"] not in {
            ContinuationState.RUNNING.value,
            ContinuationState.VERIFYING.value,
        }:
            raise InvalidTransition(
                f"continuation {continuation_id} is in state {row['state']}"
            )
        return row

    def transition(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_token: str,
        expected_version: int,
        to_state: ContinuationState,
        event_type: str,
        data: Mapping[str, Any] | None = None,
        next_wake_at: str | None = None,
        last_error: str | None = None,
        release_lease: bool = True,
        increment_step: bool = False,
        now: str | None = None,
    ) -> dict[str, Any]:
        current = _canonical_ts(now or utc_now())
        wake = _canonical_ts(next_wake_at) if next_wake_at else None
        with self._transaction() as connection:
            row = self._owned_row(
                connection,
                continuation_id,
                worker_id=worker_id,
                lease_token=lease_token,
                expected_version=expected_version,
                now=current,
            )
            from_state = ContinuationState(str(row["state"]))
            if to_state not in _ALLOWED_TRANSITIONS[from_state]:
                raise InvalidTransition(
                    f"cannot transition {continuation_id} from {from_state.value} to {to_state.value}"
                )
            connection.execute(
                """
                UPDATE continuations
                SET state = ?, version = version + 1,
                    step_index = step_index + ?, next_wake_at = ?,
                    lease_owner = ?, lease_token = ?, lease_expires_at = ?, heartbeat_at = ?,
                    last_error = ?, updated_at = ?
                WHERE id = ? AND version = ?
                """,
                (
                    to_state.value,
                    1 if increment_step else 0,
                    wake,
                    None if release_lease else worker_id,
                    None if release_lease else lease_token,
                    None if release_lease else row["lease_expires_at"],
                    None if release_lease else row["heartbeat_at"],
                    last_error,
                    current,
                    continuation_id,
                    row["version"],
                ),
            )
            self._append_event(
                connection,
                continuation_id=continuation_id,
                entity_type="continuation",
                entity_id=continuation_id,
                event_type=event_type,
                actor=worker_id,
                data={
                    "from_state": from_state.value,
                    "to_state": to_state.value,
                    "next_wake_at": wake,
                    "last_error": last_error,
                    **dict(data or {}),
                },
                now=current,
            )
            updated = connection.execute(
                "SELECT * FROM continuations WHERE id = ?", (continuation_id,)
            ).fetchone()
            assert updated is not None
            return self._row(updated) or {}

    def recover_expired_leases(
        self,
        *,
        now: str | None = None,
        retry_delay_seconds: float = 1.0,
    ) -> list[str]:
        current = _canonical_ts(now or utc_now())
        wake = _add_seconds(current, retry_delay_seconds)
        recovered: list[str] = []
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM continuations
                WHERE state IN (?, ?) AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= ?
                ORDER BY lease_expires_at, id
                """,
                (ContinuationState.RUNNING.value, ContinuationState.VERIFYING.value, current),
            ).fetchall()
            for row in rows:
                pending = connection.execute(
                    """
                    SELECT * FROM decisions
                    WHERE continuation_id = ? AND status IN ('RESERVED','EXECUTING','EXECUTED')
                    ORDER BY created_at DESC, id DESC LIMIT 1
                    """,
                    (row["id"],),
                ).fetchone()
                if pending is not None and pending["status"] in {"RESERVED", "EXECUTING"}:
                    connection.execute(
                        "UPDATE decisions SET recovery_required = 1, updated_at = ? WHERE id = ?",
                        (current, pending["id"]),
                    )
                has_pass = connection.execute(
                    "SELECT 1 FROM evidence WHERE continuation_id = ? AND verdict = 'PASS' LIMIT 1",
                    (row["id"],),
                ).fetchone() is not None
                exhausted = int(row["attempt_count"]) >= int(row["max_attempts"])
                if exhausted and pending is None and not has_pass:
                    state = ContinuationState.EXHAUSTED
                    next_wake = None
                    error = "attempt budget exhausted after lease expiry"
                else:
                    state = ContinuationState.READY
                    next_wake = wake
                    error = "worker lease expired"
                connection.execute(
                    """
                    UPDATE continuations
                    SET state = ?, version = version + 1, next_wake_at = ?,
                        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                        heartbeat_at = NULL, last_error = ?, updated_at = ?
                    WHERE id = ? AND version = ?
                    """,
                    (state.value, next_wake, error, current, row["id"], row["version"]),
                )
                self._append_event(
                    connection,
                    continuation_id=str(row["id"]),
                    entity_type="continuation",
                    entity_id=str(row["id"]),
                    event_type="LEASE_EXPIRED",
                    actor="recovery",
                    data={
                        "previous_owner": row["lease_owner"],
                        "previous_state": row["state"],
                        "to_state": state.value,
                        "pending_decision_status": pending["status"] if pending else None,
                    },
                    now=current,
                )
                recovered.append(str(row["id"]))
        return recovered

    # ------------------------------------------------------------------
    # Decisions, execution and verification
    # ------------------------------------------------------------------
    def pending_decision(self, continuation_id: str) -> dict[str, Any] | None:
        with self._transaction(immediate=False) as connection:
            row = connection.execute(
                """
                SELECT * FROM decisions
                WHERE continuation_id = ? AND status IN ('RESERVED','EXECUTING','EXECUTED')
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (continuation_id,),
            ).fetchone()
        return self._row(row)

    latest_pending_decision = pending_decision

    def reserve_decision(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_token: str,
        expected_version: int,
        decision: Decision,
        now: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        item = decision.normalized()
        if item.kind != DecisionKind.EXECUTE:
            raise ValueError("reserve_decision only accepts EXECUTE decisions")
        current = _canonical_ts(now or utc_now())
        key = item.idempotency_key or stable_id(
            "idem", continuation_id, expected_version, item.fingerprint(), length=32
        )
        payload = item.as_dict() | {"idempotency_key": key}
        request_hash = _sha256(
            {"continuation_id": continuation_id, "capability": item.capability, "arguments": dict(item.arguments)}
        )
        with self._transaction() as connection:
            row = self._owned_row(
                connection,
                continuation_id,
                worker_id=worker_id,
                lease_token=lease_token,
                expected_version=expected_version,
                now=current,
            )
            existing = connection.execute(
                "SELECT * FROM decisions WHERE idempotency_key = ?", (key,)
            ).fetchone()
            if existing is not None:
                existing_payload = _decode(existing["payload_json"], {})
                if existing["continuation_id"] != continuation_id or existing_payload != payload:
                    raise IdempotencyConflictError(
                        f"idempotency key {key!r} was used for a different request"
                    )
                return self._row(existing) or {}, self._row(row) or {}, False
            if int(row["attempt_count"]) >= int(row["max_attempts"]):
                raise AttemptBudgetExceeded(
                    f"attempt budget exhausted for continuation {continuation_id}"
                )
            decision_id = stable_id("dec", key, length=24)
            connection.execute(
                """
                INSERT INTO decisions(
                    id, continuation_id, step_index, kind, capability, risk_tier,
                    payload_json, request_hash, idempotency_key, status,
                    result_json, error, recovery_required, evidence_id,
                    created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'RESERVED', NULL, NULL, 0, NULL, ?, ?)
                """,
                (
                    decision_id,
                    continuation_id,
                    int(row["step_index"]),
                    item.kind.value,
                    item.capability,
                    int(item.risk_tier),
                    canonical_json(payload),
                    request_hash,
                    key,
                    current,
                    current,
                ),
            )
            connection.execute(
                """
                UPDATE continuations
                SET version = version + 1, attempt_count = attempt_count + 1, updated_at = ?
                WHERE id = ? AND version = ?
                """,
                (current, continuation_id, row["version"]),
            )
            self._append_event(
                connection,
                continuation_id=continuation_id,
                entity_type="decision",
                entity_id=decision_id,
                event_type="DECISION_RESERVED",
                actor=worker_id,
                data={
                    "idempotency_key": key,
                    "capability": item.capability,
                    "request_hash": request_hash,
                },
                now=current,
            )
            decision_row = connection.execute(
                "SELECT * FROM decisions WHERE id = ?", (decision_id,)
            ).fetchone()
            continuation_row = connection.execute(
                "SELECT * FROM continuations WHERE id = ?", (continuation_id,)
            ).fetchone()
            assert decision_row is not None and continuation_row is not None
            return self._row(decision_row) or {}, self._row(continuation_row) or {}, True

    def mark_execution_started(
        self,
        decision_id: str,
        *,
        worker_id: str,
        lease_token: str,
        expected_version: int,
        now: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        current = _canonical_ts(now or utc_now())
        with self._transaction() as connection:
            decision = connection.execute(
                "SELECT * FROM decisions WHERE id = ?", (decision_id,)
            ).fetchone()
            if decision is None:
                raise NotFoundError(f"decision not found: {decision_id}")
            row = self._owned_row(
                connection,
                str(decision["continuation_id"]),
                worker_id=worker_id,
                lease_token=lease_token,
                expected_version=expected_version,
                now=current,
            )
            if decision["status"] == "EXECUTING":
                return self._row(decision) or {}, self._row(row) or {}
            if decision["status"] != "RESERVED":
                raise AutonomyError(
                    f"decision {decision_id} is {decision['status']}, not RESERVED"
                )
            connection.execute(
                "UPDATE decisions SET status='EXECUTING', updated_at=? WHERE id=?",
                (current, decision_id),
            )
            connection.execute(
                "UPDATE continuations SET version=version+1, updated_at=? WHERE id=? AND version=?",
                (current, row["id"], row["version"]),
            )
            self._append_event(
                connection,
                continuation_id=str(row["id"]),
                entity_type="decision",
                entity_id=decision_id,
                event_type="EXECUTION_STARTED",
                actor=worker_id,
                data={},
                now=current,
            )
            drow = connection.execute(
                "SELECT * FROM decisions WHERE id = ?", (decision_id,)
            ).fetchone()
            crow = connection.execute(
                "SELECT * FROM continuations WHERE id = ?", (row["id"],)
            ).fetchone()
            assert drow is not None and crow is not None
            return self._row(drow) or {}, self._row(crow) or {}

    def record_execution(
        self,
        decision_id: str,
        *,
        worker_id: str,
        lease_token: str,
        expected_version: int,
        result: Mapping[str, Any],
        now: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        current = _canonical_ts(now or utc_now())
        result_dict = dict(result)
        canonical_json(result_dict)
        with self._transaction() as connection:
            decision = connection.execute(
                "SELECT * FROM decisions WHERE id = ?", (decision_id,)
            ).fetchone()
            if decision is None:
                raise NotFoundError(f"decision not found: {decision_id}")
            row = self._owned_row(
                connection,
                str(decision["continuation_id"]),
                worker_id=worker_id,
                lease_token=lease_token,
                expected_version=expected_version,
                now=current,
            )
            if decision["status"] == "EXECUTED":
                if _decode(decision["result_json"], {}) != result_dict:
                    raise AutonomyError(
                        f"decision {decision_id} already has a different execution result"
                    )
                return self._row(decision) or {}, self._row(row) or {}
            if decision["status"] not in {"RESERVED", "EXECUTING"}:
                raise AutonomyError(
                    f"decision {decision_id} is {decision['status']}, not executable"
                )
            connection.execute(
                """
                UPDATE decisions
                SET status='EXECUTED', result_json=?, recovery_required=0, updated_at=?
                WHERE id=?
                """,
                (canonical_json(result_dict), current, decision_id),
            )
            connection.execute(
                """
                UPDATE continuations
                SET state=?, version=version+1, updated_at=?
                WHERE id=? AND version=?
                """,
                (
                    ContinuationState.VERIFYING.value,
                    current,
                    row["id"],
                    row["version"],
                ),
            )
            self._append_event(
                connection,
                continuation_id=str(row["id"]),
                entity_type="decision",
                entity_id=decision_id,
                event_type="CAPABILITY_EXECUTED",
                actor=worker_id,
                data={"result_hash": _sha256(result_dict)},
                now=current,
            )
            drow = connection.execute(
                "SELECT * FROM decisions WHERE id=?", (decision_id,)
            ).fetchone()
            crow = connection.execute(
                "SELECT * FROM continuations WHERE id=?", (row["id"],)
            ).fetchone()
            assert drow is not None and crow is not None
            return self._row(drow) or {}, self._row(crow) or {}

    def record_verdict(
        self,
        decision_id: str,
        *,
        worker_id: str,
        lease_token: str,
        expected_version: int,
        verification: VerificationResult,
        to_state: ContinuationState,
        next_wake_at: str | None = None,
        last_error: str | None = None,
        experiences: Sequence[ExperienceLesson] = (),
        now: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        current = _canonical_ts(now or utc_now())
        wake = _canonical_ts(next_wake_at) if next_wake_at else None
        verified = verification.normalized()
        with self._transaction() as connection:
            decision = connection.execute(
                "SELECT * FROM decisions WHERE id=?", (decision_id,)
            ).fetchone()
            if decision is None:
                raise NotFoundError(f"decision not found: {decision_id}")
            row = self._owned_row(
                connection,
                str(decision["continuation_id"]),
                worker_id=worker_id,
                lease_token=lease_token,
                expected_version=expected_version,
                now=current,
            )
            existing = connection.execute(
                "SELECT * FROM evidence WHERE decision_id=?", (decision_id,)
            ).fetchone()
            if existing is not None:
                if _decode(existing["payload_json"], {}) != verified.as_dict():
                    raise AutonomyError(f"decision {decision_id} already has a different verdict")
                return self._row(existing) or {}, self._row(row) or {}
            if decision["status"] != "EXECUTED":
                raise AutonomyError(
                    f"decision {decision_id} is {decision['status']}, not EXECUTED"
                )
            from_state = ContinuationState(str(row["state"]))
            if to_state not in _ALLOWED_TRANSITIONS[from_state]:
                raise InvalidTransition(
                    f"cannot transition {row['id']} from {from_state.value} to {to_state.value}"
                )
            evidence_id = stable_id("ev", decision_id, verified.as_dict(), length=24)
            connection.execute(
                """
                INSERT INTO evidence(
                    id, continuation_id, decision_id, verifier_id, verdict,
                    summary, payload_json, assurance, verification_mode, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    row["id"],
                    decision_id,
                    verified.verifier_id,
                    verified.verdict.value,
                    verified.summary,
                    canonical_json(verified.as_dict()),
                    verified.assurance.value,
                    verified.verification_mode.value,
                    current,
                ),
            )
            connection.execute(
                """
                UPDATE decisions
                SET status='VERIFIED', evidence_id=?, recovery_required=0, updated_at=?
                WHERE id=?
                """,
                (evidence_id, current, decision_id),
            )
            connection.execute(
                """
                UPDATE continuations
                SET state=?, version=version+1, step_index=step_index+1,
                    next_wake_at=?, lease_owner=NULL, lease_token=NULL,
                    lease_expires_at=NULL, heartbeat_at=NULL,
                    last_error=?, updated_at=?
                WHERE id=? AND version=?
                """,
                (
                    to_state.value,
                    wake,
                    last_error,
                    current,
                    row["id"],
                    row["version"],
                ),
            )
            self._append_event(
                connection,
                continuation_id=str(row["id"]),
                entity_type="evidence",
                entity_id=evidence_id,
                event_type="VERDICT_RECORDED",
                actor=verified.verifier_id,
                data={
                    "decision_id": decision_id,
                    "verdict": verified.verdict.value,
                    "to_state": to_state.value,
                    "summary": verified.summary,
                },
                now=current,
            )
            for lesson in (*verified.lessons, *tuple(experiences)):
                item = lesson.normalized()
                self._record_experience_locked(
                    connection,
                    evidence_id=evidence_id,
                    lesson=item,
                    now=current,
                )
            erow = connection.execute(
                "SELECT * FROM evidence WHERE id=?", (evidence_id,)
            ).fetchone()
            crow = connection.execute(
                "SELECT * FROM continuations WHERE id=?", (row["id"],)
            ).fetchone()
            assert erow is not None and crow is not None
            return self._row(erow) or {}, self._row(crow) or {}

    def apply_non_execution_decision(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_token: str,
        expected_version: int,
        decision: Decision,
        now: str | None = None,
    ) -> dict[str, Any]:
        item = decision.normalized()
        if item.kind == DecisionKind.EXECUTE:
            raise ValueError("use reserve_decision for EXECUTE")
        current = _canonical_ts(now or utc_now())
        with self._transaction() as connection:
            row = self._owned_row(
                connection,
                continuation_id,
                worker_id=worker_id,
                lease_token=lease_token,
                expected_version=expected_version,
                now=current,
            )
            if item.kind == DecisionKind.FINISH:
                evidence = connection.execute(
                    """
                    SELECT * FROM evidence
                    WHERE id=? AND continuation_id=? AND verdict='PASS'
                    """,
                    (item.evidence_id, continuation_id),
                ).fetchone()
                if evidence is None:
                    raise VerificationRequiredError(
                        "FINISH requires verifier PASS evidence from this continuation"
                    )
                state = ContinuationState.SUCCEEDED
                wake = None
            elif item.kind == DecisionKind.WAIT:
                state = ContinuationState.WAITING
                wake = _add_seconds(current, float(item.wait_seconds or 0.0))
            elif item.kind == DecisionKind.CANCEL:
                state = ContinuationState.CANCELLED
                wake = None
            else:
                state = ContinuationState.BLOCKED
                wake = None
            decision_id = stable_id(
                "dec", continuation_id, row["step_index"], item.as_dict(), length=24
            )
            connection.execute(
                """
                INSERT INTO decisions(
                    id, continuation_id, step_index, kind, capability, risk_tier,
                    payload_json, request_hash, idempotency_key, status,
                    result_json, error, recovery_required, evidence_id,
                    created_at, updated_at
                ) VALUES(?, ?, ?, ?, NULL, 0, ?, ?, ?, 'VERIFIED', NULL, NULL, 0, ?, ?, ?)
                """,
                (
                    decision_id,
                    continuation_id,
                    row["step_index"],
                    item.kind.value,
                    canonical_json(item.as_dict()),
                    _sha256(item.as_dict()),
                    item.idempotency_key or decision_id,
                    item.evidence_id,
                    current,
                    current,
                ),
            )
            connection.execute(
                """
                UPDATE continuations
                SET state=?, version=version+1, step_index=step_index+1,
                    next_wake_at=?, lease_owner=NULL, lease_token=NULL,
                    lease_expires_at=NULL, heartbeat_at=NULL,
                    last_error=?, updated_at=?
                WHERE id=? AND version=?
                """,
                (
                    state.value,
                    wake,
                    item.reason if state in {ContinuationState.BLOCKED, ContinuationState.CANCELLED} else None,
                    current,
                    continuation_id,
                    row["version"],
                ),
            )
            self._append_event(
                connection,
                continuation_id=continuation_id,
                entity_type="decision",
                entity_id=decision_id,
                event_type=f"DECISION_{item.kind.value}",
                actor=worker_id,
                data={
                    "reason": item.reason,
                    "evidence_id": item.evidence_id,
                    "next_wake_at": wake,
                    "to_state": state.value,
                },
                now=current,
            )
            updated = connection.execute(
                "SELECT * FROM continuations WHERE id=?", (continuation_id,)
            ).fetchone()
            assert updated is not None
            return self._row(updated) or {}

    def block_owned_continuation(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_token: str,
        expected_version: int,
        reason: str,
        now: str | None = None,
    ) -> dict[str, Any]:
        return self.apply_non_execution_decision(
            continuation_id,
            worker_id=worker_id,
            lease_token=lease_token,
            expected_version=expected_version,
            decision=Decision(kind=DecisionKind.BLOCK, reason=reason),
            now=now,
        )

    def mark_exhausted(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_token: str,
        expected_version: int,
        reason: str = "execution budget exhausted",
        now: str | None = None,
    ) -> dict[str, Any]:
        return self.transition(
            continuation_id,
            worker_id=worker_id,
            lease_token=lease_token,
            expected_version=expected_version,
            to_state=ContinuationState.EXHAUSTED,
            event_type="CONTINUATION_EXHAUSTED",
            data={"reason": reason},
            last_error=reason,
            now=now,
        )

    # ------------------------------------------------------------------
    # Experience
    # ------------------------------------------------------------------
    def _experience_status(self, supports: int, counterexamples: int) -> str:
        if supports > 0 and counterexamples > 0:
            return "contested"
        if counterexamples >= self.experience_validation_threshold:
            return "contradicted"
        if supports >= self.experience_validation_threshold:
            return "validated"
        return "candidate"

    def _record_experience_locked(
        self,
        connection: sqlite3.Connection,
        *,
        evidence_id: str,
        lesson: ExperienceLesson,
        now: str,
    ) -> dict[str, Any]:
        item = lesson.normalized()
        scope_hash = stable_id("scope", dict(item.scope), length=24)
        experience_id = stable_id(
            "exp", item.pattern_key, scope_hash, item.polarity.value, length=24
        )
        connection.execute(
            """
            INSERT INTO experiences(
                id, pattern_key, scope_hash, polarity, claim, scope_json,
                confidence, status, supports, counterexamples, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, 'candidate', 0, 0, ?, ?)
            ON CONFLICT(pattern_key, scope_hash, polarity) DO NOTHING
            """,
            (
                experience_id,
                item.pattern_key,
                scope_hash,
                item.polarity.value,
                item.claim,
                canonical_json(dict(item.scope)),
                item.confidence,
                now,
                now,
            ),
        )
        row = connection.execute(
            """
            SELECT * FROM experiences
            WHERE pattern_key=? AND scope_hash=? AND polarity=?
            """,
            (item.pattern_key, scope_hash, item.polarity.value),
        ).fetchone()
        assert row is not None
        experience_id = str(row["id"])
        inserted = False
        try:
            connection.execute(
                """
                INSERT INTO experience_observations(experience_id, evidence_id, outcome, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (experience_id, evidence_id, item.outcome, now),
            )
            inserted = True
        except sqlite3.IntegrityError:
            inserted = False
        counts = connection.execute(
            """
            SELECT
              SUM(CASE WHEN outcome='support' THEN 1 ELSE 0 END) AS supports,
              SUM(CASE WHEN outcome='counterexample' THEN 1 ELSE 0 END) AS counterexamples
            FROM experience_observations WHERE experience_id=?
            """,
            (experience_id,),
        ).fetchone()
        supports = int(counts["supports"] or 0)
        counterexamples = int(counts["counterexamples"] or 0)
        status = self._experience_status(supports, counterexamples)
        empirical = (supports + 1.0) / (supports + counterexamples + 2.0)
        confidence = max(0.0, min(1.0, 0.5 * float(row["confidence"]) + 0.5 * empirical))
        connection.execute(
            """
            UPDATE experiences
            SET claim=?, scope_json=?, confidence=?, status=?, supports=?,
                counterexamples=?, updated_at=?
            WHERE id=?
            """,
            (
                item.claim,
                canonical_json(dict(item.scope)),
                confidence,
                status,
                supports,
                counterexamples,
                now,
                experience_id,
            ),
        )
        self._append_event(
            connection,
            continuation_id=None,
            entity_type="experience",
            entity_id=experience_id,
            event_type=("EXPERIENCE_OBSERVED" if inserted else "EXPERIENCE_DUPLICATE_IGNORED"),
            actor="experience-engine",
            data={
                "evidence_id": evidence_id,
                "outcome": item.outcome,
                "supports": supports,
                "counterexamples": counterexamples,
                "status": status,
            },
            now=now,
        )
        result = connection.execute(
            "SELECT * FROM experiences WHERE id=?", (experience_id,)
        ).fetchone()
        output = self._row(result) or {}
        output["observation_inserted"] = inserted
        output["evidence_ids"] = [
            str(entry["evidence_id"])
            for entry in connection.execute(
                """
                SELECT DISTINCT evidence_id FROM experience_observations
                WHERE experience_id=? ORDER BY evidence_id
                """,
                (experience_id,),
            ).fetchall()
        ]
        return output

    def record_experience(
        self,
        lesson: ExperienceLesson,
        *,
        evidence_id: str,
        now: str | None = None,
    ) -> dict[str, Any]:
        current = _canonical_ts(now or utc_now())
        with self._transaction() as connection:
            evidence = connection.execute(
                "SELECT id FROM evidence WHERE id=?", (evidence_id,)
            ).fetchone()
            if evidence is None:
                raise NotFoundError(f"evidence not found: {evidence_id}")
            return self._record_experience_locked(
                connection,
                evidence_id=evidence_id,
                lesson=lesson,
                now=current,
            )

    def list_experiences(self, *, status: str | None = None) -> list[dict[str, Any]]:
        with self._transaction(immediate=False) as connection:
            if status:
                rows = connection.execute(
                    "SELECT * FROM experiences WHERE status=? ORDER BY updated_at DESC",
                    (status.lower(),),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM experiences ORDER BY updated_at DESC"
                ).fetchall()
            output: list[dict[str, Any]] = []
            for row in rows:
                item = self._row(row) or {}
                item["scope"] = _decode(row["scope_json"], {})
                item["evidence_ids"] = [
                    str(entry["evidence_id"])
                    for entry in connection.execute(
                        """
                        SELECT DISTINCT evidence_id FROM experience_observations
                        WHERE experience_id=? ORDER BY evidence_id
                        """,
                        (row["id"],),
                    ).fetchall()
                ]
                output.append(item)
        return output

    # ------------------------------------------------------------------
    # Views and integrity
    # ------------------------------------------------------------------
    def latest_evidence(self, continuation_id: str) -> dict[str, Any] | None:
        with self._transaction(immediate=False) as connection:
            row = connection.execute(
                """
                SELECT * FROM evidence WHERE continuation_id=?
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (continuation_id,),
            ).fetchone()
        item = self._row(row)
        if item is not None:
            item["payload"] = _decode(row["payload_json"], {}) if row is not None else {}
        return item

    def snapshot(self, continuation_id: str) -> dict[str, Any]:
        with self._transaction(immediate=False) as connection:
            continuation = connection.execute(
                "SELECT * FROM continuations WHERE id=?", (continuation_id,)
            ).fetchone()
            if continuation is None:
                raise NotFoundError(f"continuation not found: {continuation_id}")
            opportunity = connection.execute(
                "SELECT * FROM opportunities WHERE id=?", (continuation["opportunity_id"],)
            ).fetchone()
            decisions = connection.execute(
                "SELECT * FROM decisions WHERE continuation_id=? ORDER BY created_at, id",
                (continuation_id,),
            ).fetchall()
            evidence = connection.execute(
                "SELECT * FROM evidence WHERE continuation_id=? ORDER BY created_at, id",
                (continuation_id,),
            ).fetchall()
            events = connection.execute(
                "SELECT * FROM events WHERE continuation_id=? ORDER BY seq",
                (continuation_id,),
            ).fetchall()
        return {
            "opportunity": self._row(opportunity),
            "continuation": self._row(continuation),
            "decisions": [self._row(row) for row in decisions],
            "evidence": [self._row(row) for row in evidence],
            "events": [self._row(row) for row in events],
            "experiences": self.list_experiences(),
        }

    def cancel(
        self,
        continuation_id: str,
        *,
        actor: str = "operator",
        now: str | None = None,
    ) -> dict[str, Any]:
        current = _canonical_ts(now or utc_now())
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM continuations WHERE id=?", (continuation_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"continuation not found: {continuation_id}")
            if ContinuationState(str(row["state"])) in TERMINAL_STATES:
                return self._row(row) or {}
            connection.execute(
                """
                UPDATE continuations
                SET state=?, version=version+1, next_wake_at=NULL,
                    lease_owner=NULL, lease_token=NULL, lease_expires_at=NULL,
                    heartbeat_at=NULL, updated_at=?
                WHERE id=? AND version=?
                """,
                (ContinuationState.CANCELLED.value, current, continuation_id, row["version"]),
            )
            self._append_event(
                connection,
                continuation_id=continuation_id,
                entity_type="continuation",
                entity_id=continuation_id,
                event_type="CONTINUATION_CANCELLED",
                actor=actor,
                data={"previous_state": row["state"]},
                now=current,
            )
            updated = connection.execute(
                "SELECT * FROM continuations WHERE id=?", (continuation_id,)
            ).fetchone()
            assert updated is not None
            return self._row(updated) or {}

    def verify_event_chain(self) -> dict[str, Any]:
        with self._transaction(immediate=False) as connection:
            rows = connection.execute("SELECT * FROM events ORDER BY seq").fetchall()
        previous_hash: str | None = None
        for expected_seq, row in enumerate(rows, start=1):
            if int(row["seq"]) != expected_seq:
                raise AutonomyError(f"event sequence gap at {expected_seq}")
            if row["prev_hash"] != previous_hash:
                raise AutonomyError(f"event prev_hash mismatch at seq {expected_seq}")
            item = {
                "seq": expected_seq,
                "id": row["id"],
                "ts": row["ts"],
                "continuation_id": row["continuation_id"],
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "event_type": row["event_type"],
                "actor": row["actor"],
                "data": _decode(row["data_json"], {}),
                "prev_hash": row["prev_hash"],
            }
            calculated = _sha256(item)
            if calculated != row["event_hash"]:
                raise AutonomyError(f"event hash mismatch at seq {expected_seq}")
            previous_hash = calculated
        return {"valid": True, "event_count": len(rows), "head": previous_hash}
