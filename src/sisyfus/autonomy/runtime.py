from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Literal, Mapping, Sequence


Verdict = Literal["PASS", "FAIL", "INCONCLUSIVE", "ERROR"]
DecisionKind = Literal["EXECUTE", "WAIT", "FINISH", "BLOCK"]
ExperiencePolarity = Literal["positive", "negative", "operational"]


class AutonomyError(RuntimeError):
    """Base class for deterministic autonomous-runtime failures."""


class NotFoundError(AutonomyError):
    pass


class StaleVersionError(AutonomyError):
    pass


class LeaseError(AutonomyError):
    pass


class PolicyDeniedError(AutonomyError):
    pass


class IdempotencyConflictError(AutonomyError):
    pass


class UnknownCommitError(AutonomyError):
    pass


class VerificationRequiredError(AutonomyError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _future_ts(seconds: float, *, now: str | None = None) -> str:
    base = _parse_ts(now) if now else datetime.now(timezone.utc)
    return (base + timedelta(seconds=max(0.0, float(seconds)))).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _loads(value: str | None, default: Any) -> Any:
    if value in {None, ""}:
        return default
    return json.loads(str(value))


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _normalize_statement(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _finite_json(value: Any, *, path: str = "$") -> None:
    """Reject NaN/Infinity before they can enter verifier truth or event hashes."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite number at {path}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _finite_json(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _finite_json(item, path=f"{path}[{index}]")


@dataclass(frozen=True)
class ExperienceLesson:
    statement: str
    polarity: ExperiencePolarity
    scope: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ExperienceLesson":
        statement = self.statement.strip()
        if not statement:
            raise ValueError("experience lesson statement must not be empty")
        if self.polarity not in {"positive", "negative", "operational"}:
            raise ValueError(f"invalid experience polarity: {self.polarity}")
        _finite_json(dict(self.scope))
        return ExperienceLesson(statement=statement, polarity=self.polarity, scope=dict(self.scope))


@dataclass(frozen=True)
class VerificationResult:
    verdict: Verdict
    summary: str
    metrics: Mapping[str, Any] = field(default_factory=dict)
    lessons: Sequence[ExperienceLesson] = field(default_factory=tuple)

    def normalized(self) -> "VerificationResult":
        verdict = str(self.verdict).upper()
        if verdict not in {"PASS", "FAIL", "INCONCLUSIVE", "ERROR"}:
            raise ValueError(f"invalid verifier verdict: {self.verdict}")
        metrics = dict(self.metrics)
        _finite_json(metrics)
        return VerificationResult(
            verdict=verdict,  # type: ignore[arg-type]
            summary=str(self.summary).strip(),
            metrics=metrics,
            lessons=tuple(item.normalized() for item in self.lessons),
        )


@dataclass(frozen=True)
class Decision:
    kind: DecisionKind
    capability: str | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    evidence_id: str | None = None
    wait_seconds: float | None = None
    reason: str = ""

    def normalized(self) -> "Decision":
        kind = str(self.kind).upper()
        if kind not in {"EXECUTE", "WAIT", "FINISH", "BLOCK"}:
            raise ValueError(f"invalid decision kind: {self.kind}")
        args = dict(self.arguments)
        _finite_json(args)
        if kind == "EXECUTE" and not self.capability:
            raise ValueError("EXECUTE decision requires capability")
        if kind == "FINISH" and not self.evidence_id:
            raise ValueError("FINISH decision requires a verifier PASS evidence_id")
        if kind == "WAIT" and self.wait_seconds is not None and float(self.wait_seconds) < 0:
            raise ValueError("wait_seconds must be non-negative")
        return Decision(
            kind=kind,  # type: ignore[arg-type]
            capability=self.capability,
            arguments=args,
            idempotency_key=self.idempotency_key,
            evidence_id=self.evidence_id,
            wait_seconds=self.wait_seconds,
            reason=str(self.reason),
        )


@dataclass(frozen=True)
class CapabilityContext:
    continuation_id: str
    decision_id: str
    worker_id: str
    workspace: Path


CapabilityHandler = Callable[[Mapping[str, Any], CapabilityContext], Mapping[str, Any]]
CapabilityVerifier = Callable[[Mapping[str, Any], Mapping[str, Any], CapabilityContext], VerificationResult]


@dataclass(frozen=True)
class Capability:
    name: str
    risk_tier: int
    handler: CapabilityHandler
    verifier: CapabilityVerifier
    replay_safe: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name or not re.fullmatch(r"[a-zA-Z0-9_.-]+", self.name):
            raise ValueError(f"invalid capability name: {self.name!r}")
        if int(self.risk_tier) not in {0, 1, 2, 3, 4}:
            raise ValueError("risk_tier must be between 0 and 4")


class CapabilityRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Capability] = {}
        self._lock = threading.RLock()

    def register(self, capability: Capability) -> None:
        with self._lock:
            if capability.name in self._items:
                raise ValueError(f"capability already registered: {capability.name}")
            self._items[capability.name] = capability

    def get(self, name: str) -> Capability:
        with self._lock:
            try:
                return self._items[name]
            except KeyError as exc:
                raise PolicyDeniedError(f"unregistered capability: {name}") from exc

    def list(self) -> list[Capability]:
        with self._lock:
            return [self._items[key] for key in sorted(self._items)]


@dataclass(frozen=True)
class AutonomyPolicy:
    max_unattended_risk: int = 1
    allowed_capabilities: frozenset[str] | None = None
    denied_capabilities: frozenset[str] = frozenset()
    require_idempotency_from_risk: int = 1

    def evaluate(self, capability: Capability, decision: Decision) -> None:
        if capability.name in self.denied_capabilities:
            raise PolicyDeniedError(f"capability explicitly denied: {capability.name}")
        if self.allowed_capabilities is not None and capability.name not in self.allowed_capabilities:
            raise PolicyDeniedError(f"capability not in allowlist: {capability.name}")
        if capability.risk_tier > int(self.max_unattended_risk):
            raise PolicyDeniedError(
                f"capability {capability.name} is R{capability.risk_tier}; "
                f"unattended ceiling is R{self.max_unattended_risk}"
            )
        if capability.risk_tier >= int(self.require_idempotency_from_risk) and not decision.idempotency_key:
            raise PolicyDeniedError(f"capability {capability.name} requires an idempotency_key")


class AutonomyStore:
    """SQLite-WAL durable control plane for opportunities and continuations.

    Mutations use ``BEGIN IMMEDIATE``. Continuation state uses optimistic
    versions, while workers own renewable opaque lease tokens. The append-only
    event table is hash chained inside the same transaction as each mutation.
    """

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path, *, experience_validation_threshold: int = 2) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.experience_validation_threshold = max(2, int(experience_validation_threshold))
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30.0, isolation_level=None, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = FULL")
        con.execute("PRAGMA busy_timeout = 30000")
        return con

    @contextmanager
    def _tx(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _init_schema(self) -> None:
        with self._tx() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS opportunities (
                    id TEXT PRIMARY KEY,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    priority REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    occurrence_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS continuations (
                    id TEXT PRIMARY KEY,
                    opportunity_id TEXT,
                    objective TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    priority REAL NOT NULL DEFAULT 0,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    context_json TEXT NOT NULL,
                    next_wake_at TEXT,
                    lease_owner TEXT,
                    lease_token TEXT,
                    lease_expires_at TEXT,
                    heartbeat_at TEXT,
                    terminal_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
                );
                CREATE INDEX IF NOT EXISTS idx_continuations_frontier
                    ON continuations(status, next_wake_at, priority, created_at);

                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY,
                    continuation_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    capability TEXT,
                    arguments_json TEXT NOT NULL,
                    idempotency_key TEXT,
                    request_hash TEXT,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    evidence_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(continuation_id) REFERENCES continuations(id)
                );
                CREATE INDEX IF NOT EXISTS idx_decisions_continuation
                    ON decisions(continuation_id, created_at);

                CREATE TABLE IF NOT EXISTS receipts (
                    idempotency_key TEXT PRIMARY KEY,
                    continuation_id TEXT NOT NULL,
                    decision_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    verdict TEXT,
                    evidence_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY,
                    continuation_id TEXT NOT NULL,
                    decision_id TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    result_hash TEXT NOT NULL,
                    verifier TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(continuation_id) REFERENCES continuations(id),
                    FOREIGN KEY(decision_id) REFERENCES decisions(id)
                );
                CREATE INDEX IF NOT EXISTS idx_evidence_continuation
                    ON evidence(continuation_id, created_at);

                CREATE TABLE IF NOT EXISTS experiences (
                    fingerprint TEXT PRIMARY KEY,
                    statement TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    positive_count INTEGER NOT NULL DEFAULT 0,
                    negative_count INTEGER NOT NULL DEFAULT 0,
                    operational_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    evidence_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY,
                    id TEXT NOT NULL UNIQUE,
                    ts TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    prev_hash TEXT,
                    event_hash TEXT NOT NULL UNIQUE
                );
                """
            )
            con.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(self.SCHEMA_VERSION),),
            )

    def _append_event(
        self,
        con: sqlite3.Connection,
        *,
        entity_type: str,
        entity_id: str,
        event_type: str,
        data: Mapping[str, Any] | None = None,
        ts: str | None = None,
    ) -> dict[str, Any]:
        payload_data = dict(data or {})
        _finite_json(payload_data)
        row = con.execute("SELECT seq, event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        seq = int(row["seq"]) + 1 if row else 1
        prev_hash = str(row["event_hash"]) if row else None
        item = {
            "seq": seq,
            "id": _new_id("evt"),
            "ts": ts or utc_now(),
            "entity_type": str(entity_type),
            "entity_id": str(entity_id),
            "event_type": str(event_type).upper(),
            "data": payload_data,
            "prev_hash": prev_hash,
        }
        event_hash = _sha256(item)
        con.execute(
            """
            INSERT INTO events(seq, id, ts, entity_type, entity_id, event_type, data_json, prev_hash, event_hash)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                seq,
                item["id"],
                item["ts"],
                item["entity_type"],
                item["entity_id"],
                item["event_type"],
                _json(payload_data),
                prev_hash,
                event_hash,
            ),
        )
        return {**item, "event_hash": event_hash}

    @staticmethod
    def _opportunity(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["payload"] = _loads(item.pop("payload_json"), {})
        return item

    @staticmethod
    def _continuation(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["context"] = _loads(item.pop("context_json"), {})
        return item

    @staticmethod
    def _evidence(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["metrics"] = _loads(item.pop("metrics_json"), {})
        return item

    def submit_opportunity(
        self,
        *,
        source: str,
        title: str,
        objective: str,
        payload: Mapping[str, Any] | None = None,
        priority: float = 0.0,
        dedupe_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        payload_dict = dict(payload or {})
        _finite_json(payload_dict)
        key = dedupe_key or _sha256(
            {"source": source, "title": title.strip(), "objective": objective.strip(), "payload": payload_dict}
        )
        now = utc_now()
        with self._tx() as con:
            existing = con.execute("SELECT * FROM opportunities WHERE dedupe_key = ?", (key,)).fetchone()
            if existing:
                con.execute(
                    """
                    UPDATE opportunities
                    SET occurrence_count = occurrence_count + 1,
                        priority = MAX(priority, ?),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (float(priority), now, existing["id"]),
                )
                self._append_event(
                    con,
                    entity_type="opportunity",
                    entity_id=str(existing["id"]),
                    event_type="OPPORTUNITY_SEEN_AGAIN",
                    data={"dedupe_key": key},
                    ts=now,
                )
                row = con.execute("SELECT * FROM opportunities WHERE id = ?", (existing["id"],)).fetchone()
                assert row is not None
                return self._opportunity(row), False
            oid = _new_id("opp")
            con.execute(
                """
                INSERT INTO opportunities(
                    id, dedupe_key, source, title, objective, payload_json,
                    priority, status, occurrence_count, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, 'OPEN', 1, ?, ?)
                """,
                (oid, key, source, title.strip(), objective.strip(), _json(payload_dict), float(priority), now, now),
            )
            self._append_event(
                con,
                entity_type="opportunity",
                entity_id=oid,
                event_type="OPPORTUNITY_DISCOVERED",
                data={"dedupe_key": key, "source": source, "priority": float(priority)},
                ts=now,
            )
            row = con.execute("SELECT * FROM opportunities WHERE id = ?", (oid,)).fetchone()
            assert row is not None
            return self._opportunity(row), True

    def admit_opportunity(
        self,
        opportunity_id: str,
        *,
        max_attempts: int = 8,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if int(max_attempts) < 1:
            raise ValueError("max_attempts must be positive")
        context_dict = dict(context or {})
        _finite_json(context_dict)
        now = utc_now()
        with self._tx() as con:
            opportunity = con.execute("SELECT * FROM opportunities WHERE id = ?", (opportunity_id,)).fetchone()
            if not opportunity:
                raise NotFoundError(f"opportunity not found: {opportunity_id}")
            existing = con.execute(
                "SELECT * FROM continuations WHERE opportunity_id = ? ORDER BY created_at LIMIT 1",
                (opportunity_id,),
            ).fetchone()
            if existing:
                return self._continuation(existing)
            if opportunity["status"] not in {"OPEN", "ADMITTED"}:
                raise AutonomyError(f"opportunity cannot be admitted from status {opportunity['status']}")
            cid = _new_id("cont")
            con.execute(
                """
                INSERT INTO continuations(
                    id, opportunity_id, objective, status, version, priority,
                    attempt_count, max_attempts, context_json, created_at, updated_at
                ) VALUES(?, ?, ?, 'WAITING', 1, ?, 0, ?, ?, ?, ?)
                """,
                (
                    cid,
                    opportunity_id,
                    opportunity["objective"],
                    float(opportunity["priority"]),
                    int(max_attempts),
                    _json(context_dict),
                    now,
                    now,
                ),
            )
            con.execute("UPDATE opportunities SET status = 'ADMITTED', updated_at = ? WHERE id = ?", (now, opportunity_id))
            self._append_event(
                con,
                entity_type="continuation",
                entity_id=cid,
                event_type="CONTINUATION_CREATED",
                data={"opportunity_id": opportunity_id, "max_attempts": int(max_attempts)},
                ts=now,
            )
            row = con.execute("SELECT * FROM continuations WHERE id = ?", (cid,)).fetchone()
            assert row is not None
            return self._continuation(row)

    def get_continuation(self, continuation_id: str) -> dict[str, Any]:
        with self._tx(immediate=False) as con:
            row = con.execute("SELECT * FROM continuations WHERE id = ?", (continuation_id,)).fetchone()
            if not row:
                raise NotFoundError(f"continuation not found: {continuation_id}")
            return self._continuation(row)

    def list_continuations(self, *, status: str | None = None) -> list[dict[str, Any]]:
        with self._tx(immediate=False) as con:
            if status:
                rows = con.execute(
                    "SELECT * FROM continuations WHERE status = ? ORDER BY priority DESC, created_at",
                    (status.upper(),),
                ).fetchall()
            else:
                rows = con.execute("SELECT * FROM continuations ORDER BY created_at").fetchall()
            return [self._continuation(row) for row in rows]

    def lease_next(
        self,
        worker_id: str,
        *,
        lease_seconds: float = 60.0,
        now: str | None = None,
    ) -> dict[str, Any] | None:
        current = now or utc_now()
        expires = _future_ts(lease_seconds, now=current)
        with self._tx() as con:
            row = con.execute(
                """
                SELECT * FROM continuations
                WHERE status = 'WAITING'
                  AND (next_wake_at IS NULL OR next_wake_at <= ?)
                  AND attempt_count < max_attempts
                ORDER BY priority DESC, created_at, id
                LIMIT 1
                """,
                (current,),
            ).fetchone()
            if not row:
                return None
            token = secrets.token_urlsafe(24)
            cur = con.execute(
                """
                UPDATE continuations
                SET status = 'RUNNING', version = version + 1,
                    lease_owner = ?, lease_token = ?, lease_expires_at = ?,
                    heartbeat_at = ?, updated_at = ?, next_wake_at = NULL
                WHERE id = ? AND version = ? AND status = 'WAITING'
                """,
                (worker_id, token, expires, current, current, row["id"], int(row["version"])),
            )
            if cur.rowcount != 1:
                raise StaleVersionError(f"lease race lost for continuation {row['id']}")
            self._append_event(
                con,
                entity_type="continuation",
                entity_id=str(row["id"]),
                event_type="LEASE_ACQUIRED",
                data={"worker_id": worker_id, "lease_expires_at": expires},
                ts=current,
            )
            leased = con.execute("SELECT * FROM continuations WHERE id = ?", (row["id"],)).fetchone()
            assert leased is not None
            return self._continuation(leased)

    def renew_lease(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_token: str,
        lease_seconds: float = 60.0,
        now: str | None = None,
    ) -> dict[str, Any]:
        current = now or utc_now()
        expires = _future_ts(lease_seconds, now=current)
        with self._tx() as con:
            cur = con.execute(
                """
                UPDATE continuations
                SET lease_expires_at = ?, heartbeat_at = ?, updated_at = ?
                WHERE id = ? AND lease_owner = ? AND lease_token = ?
                  AND status IN ('RUNNING', 'VERIFYING')
                """,
                (expires, current, current, continuation_id, worker_id, lease_token),
            )
            if cur.rowcount != 1:
                raise LeaseError(f"lease is not owned by {worker_id} for {continuation_id}")
            self._append_event(
                con,
                entity_type="continuation",
                entity_id=continuation_id,
                event_type="LEASE_RENEWED",
                data={"worker_id": worker_id, "lease_expires_at": expires},
                ts=current,
            )
            row = con.execute("SELECT * FROM continuations WHERE id = ?", (continuation_id,)).fetchone()
            assert row is not None
            return self._continuation(row)

    def _owned_row(
        self,
        con: sqlite3.Connection,
        continuation_id: str,
        *,
        worker_id: str,
        lease_token: str,
        expected_version: int,
    ) -> sqlite3.Row:
        row = con.execute("SELECT * FROM continuations WHERE id = ?", (continuation_id,)).fetchone()
        if not row:
            raise NotFoundError(f"continuation not found: {continuation_id}")
        if int(row["version"]) != int(expected_version):
            raise StaleVersionError(
                f"continuation {continuation_id} version is {row['version']}; expected {expected_version}"
            )
        if row["lease_owner"] != worker_id or row["lease_token"] != lease_token:
            raise LeaseError(f"continuation {continuation_id} is not leased by {worker_id}")
        if row["status"] not in {"RUNNING", "VERIFYING"}:
            raise LeaseError(f"continuation {continuation_id} is in status {row['status']}")
        return row

    def recover_expired_leases(self, *, now: str | None = None) -> list[dict[str, Any]]:
        current = now or utc_now()
        recovered: list[dict[str, Any]] = []
        with self._tx() as con:
            rows = con.execute(
                """
                SELECT * FROM continuations
                WHERE status IN ('RUNNING', 'VERIFYING')
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= ?
                ORDER BY lease_expires_at, id
                """,
                (current,),
            ).fetchall()
            for row in rows:
                exhausted = int(row["attempt_count"]) >= int(row["max_attempts"])
                status = "FAILED" if exhausted else "WAITING"
                reason = "attempt_budget_exhausted_after_lease_expiry" if exhausted else None
                con.execute(
                    """
                    UPDATE continuations
                    SET status = ?, version = version + 1,
                        lease_owner = NULL, lease_token = NULL,
                        lease_expires_at = NULL, heartbeat_at = NULL,
                        terminal_reason = ?, updated_at = ?
                    WHERE id = ? AND version = ?
                    """,
                    (status, reason, current, row["id"], int(row["version"])),
                )
                self._append_event(
                    con,
                    entity_type="continuation",
                    entity_id=str(row["id"]),
                    event_type="LEASE_EXPIRED",
                    data={"previous_worker": row["lease_owner"], "recovered_status": status},
                    ts=current,
                )
                refreshed = con.execute("SELECT * FROM continuations WHERE id = ?", (row["id"],)).fetchone()
                assert refreshed is not None
                recovered.append(self._continuation(refreshed))
        return recovered

    def reserve_execution(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_token: str,
        expected_version: int,
        capability: Capability,
        decision: Decision,
    ) -> dict[str, Any]:
        now = utc_now()
        request = {
            "continuation_id": continuation_id,
            "capability": capability.name,
            "arguments": dict(decision.arguments),
        }
        request_hash = _sha256(request)
        key = decision.idempotency_key or f"r0:{request_hash}"
        with self._tx() as con:
            row = self._owned_row(
                con,
                continuation_id,
                worker_id=worker_id,
                lease_token=lease_token,
                expected_version=expected_version,
            )
            receipt = con.execute("SELECT * FROM receipts WHERE idempotency_key = ?", (key,)).fetchone()
            if receipt and receipt["request_hash"] != request_hash:
                raise IdempotencyConflictError(
                    f"idempotency key {key!r} was already used for a different request"
                )
            if receipt and receipt["status"] == "IN_PROGRESS" and not capability.replay_safe:
                raise UnknownCommitError(
                    f"idempotency key {key!r} has an unresolved in-progress side effect"
                )
            did = _new_id("dec")
            if receipt and receipt["status"] == "COMPLETED":
                result = _loads(receipt["result_json"], {})
                con.execute(
                    """
                    INSERT INTO decisions(
                        id, continuation_id, kind, capability, arguments_json,
                        idempotency_key, request_hash, status, result_json,
                        evidence_id, created_at, updated_at
                    ) VALUES(?, ?, 'EXECUTE', ?, ?, ?, ?, 'IDEMPOTENT_REPLAY', ?, ?, ?, ?)
                    """,
                    (
                        did,
                        continuation_id,
                        capability.name,
                        _json(dict(decision.arguments)),
                        key,
                        request_hash,
                        _json(result),
                        receipt["evidence_id"],
                        now,
                        now,
                    ),
                )
                con.execute(
                    """
                    UPDATE continuations
                    SET status = 'WAITING', version = version + 1,
                        lease_owner = NULL, lease_token = NULL,
                        lease_expires_at = NULL, heartbeat_at = NULL,
                        updated_at = ?
                    WHERE id = ? AND version = ?
                    """,
                    (now, continuation_id, int(row["version"])),
                )
                self._append_event(
                    con,
                    entity_type="decision",
                    entity_id=did,
                    event_type="IDEMPOTENCY_REPLAYED",
                    data={"idempotency_key": key, "evidence_id": receipt["evidence_id"]},
                    ts=now,
                )
                refreshed = con.execute("SELECT * FROM continuations WHERE id = ?", (continuation_id,)).fetchone()
                assert refreshed is not None
                return {
                    "cached": True,
                    "decision_id": did,
                    "continuation": self._continuation(refreshed),
                    "result": result,
                    "verdict": receipt["verdict"],
                    "evidence_id": receipt["evidence_id"],
                    "idempotency_key": key,
                }
            if int(row["attempt_count"]) >= int(row["max_attempts"]):
                raise AutonomyError(f"attempt budget exhausted for continuation {continuation_id}")
            con.execute(
                """
                INSERT INTO decisions(
                    id, continuation_id, kind, capability, arguments_json,
                    idempotency_key, request_hash, status, created_at, updated_at
                ) VALUES(?, ?, 'EXECUTE', ?, ?, ?, ?, 'EXECUTING', ?, ?)
                """,
                (did, continuation_id, capability.name, _json(dict(decision.arguments)), key, request_hash, now, now),
            )
            if receipt:
                con.execute(
                    """
                    UPDATE receipts
                    SET decision_id = ?, status = 'IN_PROGRESS', result_json = NULL,
                        error = NULL, verdict = NULL, evidence_id = NULL, updated_at = ?
                    WHERE idempotency_key = ?
                    """,
                    (did, now, key),
                )
            else:
                con.execute(
                    """
                    INSERT INTO receipts(
                        idempotency_key, continuation_id, decision_id, capability,
                        request_hash, status, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, 'IN_PROGRESS', ?, ?)
                    """,
                    (key, continuation_id, did, capability.name, request_hash, now, now),
                )
            cur = con.execute(
                """
                UPDATE continuations
                SET status = 'VERIFYING', version = version + 1,
                    attempt_count = attempt_count + 1, updated_at = ?
                WHERE id = ? AND version = ?
                """,
                (now, continuation_id, int(row["version"])),
            )
            if cur.rowcount != 1:
                raise StaleVersionError(f"continuation changed while reserving {did}")
            self._append_event(
                con,
                entity_type="decision",
                entity_id=did,
                event_type="EXECUTION_RESERVED",
                data={
                    "continuation_id": continuation_id,
                    "capability": capability.name,
                    "risk_tier": capability.risk_tier,
                    "idempotency_key": key,
                    "request_hash": request_hash,
                },
                ts=now,
            )
            refreshed = con.execute("SELECT * FROM continuations WHERE id = ?", (continuation_id,)).fetchone()
            assert refreshed is not None
            return {
                "cached": False,
                "decision_id": did,
                "continuation": self._continuation(refreshed),
                "idempotency_key": key,
                "request_hash": request_hash,
            }

    def finalize_execution(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_token: str,
        expected_version: int,
        decision_id: str,
        idempotency_key: str,
        result: Mapping[str, Any],
        verification: VerificationResult,
        verifier_name: str,
    ) -> dict[str, Any]:
        result_dict = dict(result)
        _finite_json(result_dict)
        verification = verification.normalized()
        now = utc_now()
        with self._tx() as con:
            row = self._owned_row(
                con,
                continuation_id,
                worker_id=worker_id,
                lease_token=lease_token,
                expected_version=expected_version,
            )
            decision = con.execute(
                "SELECT * FROM decisions WHERE id = ? AND continuation_id = ?",
                (decision_id, continuation_id),
            ).fetchone()
            if not decision or decision["status"] != "EXECUTING":
                raise StaleVersionError(f"decision {decision_id} is already settled or missing")
            evidence_id = _new_id("ev")
            con.execute(
                """
                INSERT INTO evidence(
                    id, continuation_id, decision_id, verdict, summary,
                    metrics_json, result_hash, verifier, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    continuation_id,
                    decision_id,
                    verification.verdict,
                    verification.summary,
                    _json(dict(verification.metrics)),
                    _sha256(result_dict),
                    verifier_name,
                    now,
                ),
            )
            decision_status = {
                "PASS": "VERIFIED_PASS",
                "FAIL": "VERIFIED_FAIL",
                "INCONCLUSIVE": "INCONCLUSIVE",
                "ERROR": "ERROR",
            }[verification.verdict]
            con.execute(
                """
                UPDATE decisions
                SET status = ?, result_json = ?, evidence_id = ?, updated_at = ?
                WHERE id = ? AND status = 'EXECUTING'
                """,
                (decision_status, _json(result_dict), evidence_id, now, decision_id),
            )
            con.execute(
                """
                UPDATE receipts
                SET status = 'COMPLETED', result_json = ?, verdict = ?,
                    evidence_id = ?, updated_at = ?
                WHERE idempotency_key = ? AND decision_id = ?
                """,
                (_json(result_dict), verification.verdict, evidence_id, now, idempotency_key, decision_id),
            )
            terminal = (
                verification.verdict in {"FAIL", "ERROR"}
                and int(row["attempt_count"]) >= int(row["max_attempts"])
            )
            next_status = "FAILED" if terminal else "WAITING"
            reason = "attempt_budget_exhausted" if terminal else None
            cur = con.execute(
                """
                UPDATE continuations
                SET status = ?, version = version + 1,
                    lease_owner = NULL, lease_token = NULL,
                    lease_expires_at = NULL, heartbeat_at = NULL,
                    terminal_reason = ?, updated_at = ?
                WHERE id = ? AND version = ?
                """,
                (next_status, reason, now, continuation_id, int(row["version"])),
            )
            if cur.rowcount != 1:
                raise StaleVersionError(f"continuation changed while settling {decision_id}")
            self._append_event(
                con,
                entity_type="evidence",
                entity_id=evidence_id,
                event_type="VERDICT_ISSUED",
                data={
                    "continuation_id": continuation_id,
                    "decision_id": decision_id,
                    "verdict": verification.verdict,
                    "summary": verification.summary,
                    "verifier": verifier_name,
                },
                ts=now,
            )
            lessons = list(verification.lessons)
            if not lessons:
                capability_name = str(decision["capability"] or "unknown")
                polarity: ExperiencePolarity = (
                    "positive"
                    if verification.verdict == "PASS"
                    else "negative"
                    if verification.verdict == "FAIL"
                    else "operational"
                )
                lessons = [
                    ExperienceLesson(
                        statement=f"Capability {capability_name} produced verifier-backed {verification.verdict}",
                        polarity=polarity,
                        scope={"capability": capability_name},
                    )
                ]
            experiences = [
                self._record_experience_locked(con, lesson, evidence_id=evidence_id, now=now)
                for lesson in lessons
            ]
            refreshed = con.execute("SELECT * FROM continuations WHERE id = ?", (continuation_id,)).fetchone()
            assert refreshed is not None
            evidence_row = con.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
            assert evidence_row is not None
            return {
                "cached": False,
                "continuation": self._continuation(refreshed),
                "evidence": self._evidence(evidence_row),
                "experiences": experiences,
                "result": result_dict,
            }

    def fail_execution(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_token: str,
        expected_version: int,
        decision_id: str,
        idempotency_key: str,
        error: BaseException,
        verifier_name: str = "engine.execution-boundary",
    ) -> dict[str, Any]:
        message = f"{type(error).__name__}: {error}"
        return self.finalize_execution(
            continuation_id,
            worker_id=worker_id,
            lease_token=lease_token,
            expected_version=expected_version,
            decision_id=decision_id,
            idempotency_key=idempotency_key,
            result={"execution": {"ok": False, "error": message}},
            verification=VerificationResult(
                verdict="ERROR",
                summary="capability execution failed before deterministic verification",
                metrics={"exception_type": type(error).__name__},
                lessons=(
                    ExperienceLesson(
                        statement=f"Execution failed with {type(error).__name__}",
                        polarity="operational",
                        scope={"exception_type": type(error).__name__},
                    ),
                ),
            ),
            verifier_name=verifier_name,
        )

    def apply_non_execution_decision(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_token: str,
        expected_version: int,
        decision: Decision,
    ) -> dict[str, Any]:
        decision = decision.normalized()
        if decision.kind == "EXECUTE":
            raise ValueError("use reserve_execution for EXECUTE")
        now = utc_now()
        with self._tx() as con:
            row = self._owned_row(
                con,
                continuation_id,
                worker_id=worker_id,
                lease_token=lease_token,
                expected_version=expected_version,
            )
            did = _new_id("dec")
            evidence_id = decision.evidence_id
            if decision.kind == "FINISH":
                evidence = con.execute(
                    "SELECT * FROM evidence WHERE id = ? AND continuation_id = ?",
                    (evidence_id, continuation_id),
                ).fetchone()
                if not evidence or evidence["verdict"] != "PASS":
                    raise VerificationRequiredError(
                        "planner FINISH cannot complete a continuation without verifier PASS evidence"
                    )
                next_status = "SUCCEEDED"
                next_wake = None
                decision_status = "VERIFIED_FINISH"
            elif decision.kind == "WAIT":
                next_status = "WAITING"
                next_wake = _future_ts(float(decision.wait_seconds or 0.0), now=now)
                decision_status = "WAITING"
            else:
                next_status = "BLOCKED"
                next_wake = None
                decision_status = "BLOCKED"
            con.execute(
                """
                INSERT INTO decisions(
                    id, continuation_id, kind, capability, arguments_json,
                    status, evidence_id, created_at, updated_at
                ) VALUES(?, ?, ?, NULL, '{}', ?, ?, ?, ?)
                """,
                (did, continuation_id, decision.kind, decision_status, evidence_id, now, now),
            )
            cur = con.execute(
                """
                UPDATE continuations
                SET status = ?, version = version + 1, next_wake_at = ?,
                    lease_owner = NULL, lease_token = NULL,
                    lease_expires_at = NULL, heartbeat_at = NULL,
                    terminal_reason = ?, updated_at = ?
                WHERE id = ? AND version = ?
                """,
                (
                    next_status,
                    next_wake,
                    decision.reason or ("planner_blocked" if next_status == "BLOCKED" else None),
                    now,
                    continuation_id,
                    int(row["version"]),
                ),
            )
            if cur.rowcount != 1:
                raise StaleVersionError(f"continuation changed while applying {decision.kind}")
            self._append_event(
                con,
                entity_type="decision",
                entity_id=did,
                event_type=f"DECISION_{decision.kind}",
                data={
                    "continuation_id": continuation_id,
                    "reason": decision.reason,
                    "evidence_id": evidence_id,
                    "next_wake_at": next_wake,
                },
                ts=now,
            )
            refreshed = con.execute("SELECT * FROM continuations WHERE id = ?", (continuation_id,)).fetchone()
            assert refreshed is not None
            return {"decision_id": did, "continuation": self._continuation(refreshed)}

    def block_owned_continuation(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        lease_token: str,
        expected_version: int,
        reason: str,
    ) -> dict[str, Any]:
        return self.apply_non_execution_decision(
            continuation_id,
            worker_id=worker_id,
            lease_token=lease_token,
            expected_version=expected_version,
            decision=Decision(kind="BLOCK", reason=reason),
        )["continuation"]

    def get_evidence(self, evidence_id: str) -> dict[str, Any]:
        with self._tx(immediate=False) as con:
            row = con.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
            if not row:
                raise NotFoundError(f"evidence not found: {evidence_id}")
            return self._evidence(row)

    def latest_evidence(self, continuation_id: str) -> dict[str, Any] | None:
        with self._tx(immediate=False) as con:
            row = con.execute(
                "SELECT * FROM evidence WHERE continuation_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                (continuation_id,),
            ).fetchone()
            return self._evidence(row) if row else None

    def _record_experience_locked(
        self,
        con: sqlite3.Connection,
        lesson: ExperienceLesson,
        *,
        evidence_id: str,
        now: str,
    ) -> dict[str, Any]:
        lesson = lesson.normalized()
        scope = dict(lesson.scope)
        fingerprint = _sha256({"statement": _normalize_statement(lesson.statement), "scope": scope})
        row = con.execute("SELECT * FROM experiences WHERE fingerprint = ?", (fingerprint,)).fetchone()
        counts = {
            "positive_count": int(row["positive_count"]) if row else 0,
            "negative_count": int(row["negative_count"]) if row else 0,
            "operational_count": int(row["operational_count"]) if row else 0,
        }
        counts[f"{lesson.polarity}_count"] += 1
        evidence_ids = list(_loads(row["evidence_ids_json"], [])) if row else []
        if evidence_id not in evidence_ids:
            evidence_ids.append(evidence_id)
        if counts["positive_count"] and counts["negative_count"]:
            status = "CONTRADICTED"
        elif max(counts.values()) >= self.experience_validation_threshold:
            status = "VALIDATED"
        else:
            status = "CANDIDATE"
        if row:
            con.execute(
                """
                UPDATE experiences
                SET statement = ?, scope_json = ?, positive_count = ?,
                    negative_count = ?, operational_count = ?, status = ?,
                    evidence_ids_json = ?, updated_at = ?
                WHERE fingerprint = ?
                """,
                (
                    lesson.statement,
                    _json(scope),
                    counts["positive_count"],
                    counts["negative_count"],
                    counts["operational_count"],
                    status,
                    _json(evidence_ids),
                    now,
                    fingerprint,
                ),
            )
        else:
            con.execute(
                """
                INSERT INTO experiences(
                    fingerprint, statement, scope_json, positive_count,
                    negative_count, operational_count, status,
                    evidence_ids_json, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fingerprint,
                    lesson.statement,
                    _json(scope),
                    counts["positive_count"],
                    counts["negative_count"],
                    counts["operational_count"],
                    status,
                    _json(evidence_ids),
                    now,
                    now,
                ),
            )
        self._append_event(
            con,
            entity_type="experience",
            entity_id=fingerprint,
            event_type="EXPERIENCE_UPDATED",
            data={
                "polarity": lesson.polarity,
                "status": status,
                "evidence_id": evidence_id,
                **counts,
            },
            ts=now,
        )
        return {
            "fingerprint": fingerprint,
            "statement": lesson.statement,
            "scope": scope,
            **counts,
            "status": status,
            "evidence_ids": evidence_ids,
        }

    def record_experience(
        self,
        lesson: ExperienceLesson,
        *,
        evidence_id: str,
    ) -> dict[str, Any]:
        now = utc_now()
        with self._tx() as con:
            evidence = con.execute("SELECT id FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
            if not evidence:
                raise NotFoundError(f"evidence not found: {evidence_id}")
            return self._record_experience_locked(con, lesson, evidence_id=evidence_id, now=now)

    def list_experiences(self, *, status: str | None = None) -> list[dict[str, Any]]:
        with self._tx(immediate=False) as con:
            if status:
                rows = con.execute(
                    "SELECT * FROM experiences WHERE status = ? ORDER BY updated_at DESC",
                    (status.upper(),),
                ).fetchall()
            else:
                rows = con.execute("SELECT * FROM experiences ORDER BY updated_at DESC").fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["scope"] = _loads(item.pop("scope_json"), {})
                item["evidence_ids"] = _loads(item.pop("evidence_ids_json"), [])
                out.append(item)
            return out

    def verify_event_chain(self) -> dict[str, Any]:
        with self._tx(immediate=False) as con:
            rows = con.execute("SELECT * FROM events ORDER BY seq").fetchall()
        prev_hash: str | None = None
        for expected_seq, row in enumerate(rows, start=1):
            if int(row["seq"]) != expected_seq:
                raise AutonomyError(f"event sequence gap at {expected_seq}")
            if row["prev_hash"] != prev_hash:
                raise AutonomyError(f"event prev_hash mismatch at seq {expected_seq}")
            item = {
                "seq": expected_seq,
                "id": row["id"],
                "ts": row["ts"],
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "event_type": row["event_type"],
                "data": _loads(row["data_json"], {}),
                "prev_hash": row["prev_hash"],
            }
            calculated = _sha256(item)
            if calculated != row["event_hash"]:
                raise AutonomyError(f"event hash mismatch at seq {expected_seq}")
            prev_hash = calculated
        return {"valid": True, "event_count": len(rows), "head": prev_hash}


Planner = Callable[[dict[str, Any], Mapping[str, Any]], Decision]


class AutonomousRuntime:
    """One deterministic supervisor worker around planner proposals.

    The planner may propose, but policy admits capabilities, the engine records
    execution, and the capability verifier owns PASS/FAIL. A planner cannot mark
    a continuation successful without referencing persisted PASS evidence.
    """

    def __init__(
        self,
        store: AutonomyStore,
        registry: CapabilityRegistry,
        *,
        workspace: str | Path,
        policy: AutonomyPolicy | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.policy = policy or AutonomyPolicy()

    def planner_context(self, continuation: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "continuation": dict(continuation),
            "latest_evidence": self.store.latest_evidence(str(continuation["id"])),
            "validated_experiences": self.store.list_experiences(status="VALIDATED")[:50],
            "capabilities": [
                {
                    "name": item.name,
                    "risk_tier": item.risk_tier,
                    "description": item.description,
                    "replay_safe": item.replay_safe,
                }
                for item in self.registry.list()
                if item.risk_tier <= self.policy.max_unattended_risk
            ],
            "rules": [
                "A FINISH proposal requires verifier PASS evidence.",
                "Never treat planner confidence as evidence.",
                "Prefer WAIT over inventing observations when the environment has not changed.",
            ],
        }

    def apply_decision(
        self,
        continuation: Mapping[str, Any],
        decision: Decision,
        *,
        worker_id: str,
    ) -> dict[str, Any]:
        normalized = decision.normalized()
        continuation_id = str(continuation["id"])
        lease_token = str(continuation.get("lease_token") or "")
        expected_version = int(continuation["version"])
        if not lease_token:
            raise LeaseError("continuation has no active lease token")
        if normalized.kind != "EXECUTE":
            return self.store.apply_non_execution_decision(
                continuation_id,
                worker_id=worker_id,
                lease_token=lease_token,
                expected_version=expected_version,
                decision=normalized,
            )

        capability = self.registry.get(str(normalized.capability))
        self.policy.evaluate(capability, normalized)
        reservation = self.store.reserve_execution(
            continuation_id,
            worker_id=worker_id,
            lease_token=lease_token,
            expected_version=expected_version,
            capability=capability,
            decision=normalized,
        )
        if reservation["cached"]:
            return reservation
        reserved_continuation = reservation["continuation"]
        decision_id = str(reservation["decision_id"])
        context = CapabilityContext(
            continuation_id=continuation_id,
            decision_id=decision_id,
            worker_id=worker_id,
            workspace=self.workspace,
        )
        try:
            raw_result = capability.handler(dict(normalized.arguments), context)
            if not isinstance(raw_result, Mapping):
                raise TypeError("capability handler must return a mapping")
            result = dict(raw_result)
            _finite_json(result)
        except BaseException as exc:
            return self.store.fail_execution(
                continuation_id,
                worker_id=worker_id,
                lease_token=lease_token,
                expected_version=int(reserved_continuation["version"]),
                decision_id=decision_id,
                idempotency_key=str(reservation["idempotency_key"]),
                error=exc,
            )
        try:
            verification = capability.verifier(dict(normalized.arguments), result, context).normalized()
        except BaseException as exc:
            verification = VerificationResult(
                verdict="ERROR",
                summary=f"verifier raised {type(exc).__name__}",
                metrics={"exception_type": type(exc).__name__},
                lessons=(
                    ExperienceLesson(
                        statement=f"Verifier for {capability.name} failed with {type(exc).__name__}",
                        polarity="operational",
                        scope={"capability": capability.name},
                    ),
                ),
            )
        return self.store.finalize_execution(
            continuation_id,
            worker_id=worker_id,
            lease_token=lease_token,
            expected_version=int(reserved_continuation["version"]),
            decision_id=decision_id,
            idempotency_key=str(reservation["idempotency_key"]),
            result=result,
            verification=verification,
            verifier_name=f"capability:{capability.name}",
        )

    def run_once(
        self,
        *,
        worker_id: str,
        planner: Planner,
        lease_seconds: float = 60.0,
    ) -> dict[str, Any] | None:
        self.store.recover_expired_leases()
        continuation = self.store.lease_next(worker_id, lease_seconds=lease_seconds)
        if continuation is None:
            return None
        try:
            decision = planner(continuation, self.planner_context(continuation))
            return self.apply_decision(continuation, decision, worker_id=worker_id)
        except (PolicyDeniedError, IdempotencyConflictError, UnknownCommitError, VerificationRequiredError) as exc:
            try:
                blocked = self.store.block_owned_continuation(
                    str(continuation["id"]),
                    worker_id=worker_id,
                    lease_token=str(continuation["lease_token"]),
                    expected_version=int(continuation["version"]),
                    reason=f"{type(exc).__name__}: {exc}",
                )
            except AutonomyError:
                blocked = self.store.get_continuation(str(continuation["id"]))
            return {"status": "BLOCKED", "error": str(exc), "continuation": blocked}
        except BaseException as exc:
            try:
                waiting = self.store.apply_non_execution_decision(
                    str(continuation["id"]),
                    worker_id=worker_id,
                    lease_token=str(continuation["lease_token"]),
                    expected_version=int(continuation["version"]),
                    decision=Decision(kind="WAIT", wait_seconds=5.0, reason=f"planner_error:{type(exc).__name__}"),
                )["continuation"]
            except AutonomyError:
                waiting = self.store.get_continuation(str(continuation["id"]))
            return {"status": "PLANNER_ERROR", "error": str(exc), "continuation": waiting}


def register_safe_builtins(registry: CapabilityRegistry) -> None:
    """Register only R0/R1 capabilities; intentionally no arbitrary shell."""

    def echo_handler(arguments: Mapping[str, Any], _context: CapabilityContext) -> Mapping[str, Any]:
        return {"value": arguments.get("value")}

    def echo_verifier(
        arguments: Mapping[str, Any], result: Mapping[str, Any], _context: CapabilityContext
    ) -> VerificationResult:
        passed = result.get("value") == arguments.get("value")
        return VerificationResult(
            verdict="PASS" if passed else "FAIL",
            summary="echo result matched input" if passed else "echo result differed from input",
            metrics={"matched": passed},
        )

    registry.register(
        Capability(
            name="core.echo",
            risk_tier=0,
            handler=echo_handler,
            verifier=echo_verifier,
            replay_safe=True,
            description="Pure deterministic echo used for runtime checks.",
        )
    )

    def write_handler(arguments: Mapping[str, Any], context: CapabilityContext) -> Mapping[str, Any]:
        rel = str(arguments.get("path") or "").strip()
        if not rel:
            raise ValueError("path is required")
        target = (context.workspace / rel).resolve()
        try:
            target.relative_to(context.workspace)
        except ValueError as exc:
            raise ValueError("artifact path escapes workspace") from exc
        content = str(arguments.get("content") or "")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {
            "relative_path": str(target.relative_to(context.workspace)),
            "sha256": "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "bytes": len(content.encode("utf-8")),
        }

    def write_verifier(
        arguments: Mapping[str, Any], result: Mapping[str, Any], context: CapabilityContext
    ) -> VerificationResult:
        rel = str(result.get("relative_path") or "")
        target = (context.workspace / rel).resolve()
        expected = str(arguments.get("content") or "")
        exists = target.is_file()
        actual = target.read_text(encoding="utf-8") if exists else None
        passed = exists and actual == expected
        return VerificationResult(
            verdict="PASS" if passed else "FAIL",
            summary="artifact exists with exact requested content" if passed else "artifact verification failed",
            metrics={"exists": exists, "bytes": len(actual.encode("utf-8")) if actual is not None else 0},
            lessons=(
                ExperienceLesson(
                    statement="Workspace artifact writes are verified by reading back exact content",
                    polarity="positive" if passed else "negative",
                    scope={"capability": "workspace.write_text"},
                ),
            ),
        )

    registry.register(
        Capability(
            name="workspace.write_text",
            risk_tier=1,
            handler=write_handler,
            verifier=write_verifier,
            replay_safe=False,
            description="Write one UTF-8 artifact inside the configured workspace and verify it by read-back.",
        )
    )
