from __future__ import annotations

import json
import secrets
from typing import Any

from ..autonomy.models import canonical_json, utc_now
from ..autonomy.policy import IdempotencyConflictError, LeaseLost
from ..autonomy.store import AutonomyStore
from .protocol import digest, redact


class DispatchBlocked(RuntimeError):
    pass


class Journal:
    """Native process receipts in the EXISTING autonomy database, not task truth.

    Continuations, leases, decisions, verdicts and the hash chain remain owned
    by AutonomyStore. Only transport receipts and operator commands live here.
    """

    def __init__(self, store: AutonomyStore):
        self.store = store
        with store._transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS native_worker_runs ("
                       "key TEXT PRIMARY KEY, task_id TEXT NOT NULL, continuation_id TEXT, "
                       "fingerprint TEXT NOT NULL, lease_token TEXT, status TEXT NOT NULL, "
                       "receipt_json TEXT, created_at TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS native_worker_commands ("
                       "id TEXT PRIMARY KEY, run_key TEXT NOT NULL REFERENCES native_worker_runs(key), "
                       "action TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)")
            row = db.execute("SELECT value FROM metadata WHERE key='native_worker_schema'").fetchone()
            if row is not None and row[0] != "1":
                raise ValueError("incompatible native worker schema")
            db.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('native_worker_schema','1')")

    def _event(self, db: Any, kind: str, key: str, data: dict[str, Any], continuation_id: str | None = None,
               actor: str = "native-worker") -> None:
        self.store._append_event(db, continuation_id=continuation_id, entity_type="native_worker",
                                 entity_id=key, event_type="WORKER_" + kind.upper(), actor=actor,
                                 data=redact(data), now=utc_now())

    def bind(self, specification: dict[str, Any]) -> None:
        raw = canonical_json(specification)
        with self.store._transaction() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='native_worker_spec'").fetchone()
            if row is not None and row[0] != raw:
                raise IdempotencyConflictError("mission specification changed; create a new mission directory")
            if row is None:
                db.execute("INSERT INTO metadata(key,value) VALUES('native_worker_spec',?)", (raw,))
                self._event(db, "mission_bound", "mission", {"spec_hash": digest(specification)})

    def spec(self) -> dict[str, Any]:
        with self.store._transaction(immediate=False) as db:
            row = db.execute("SELECT value FROM metadata WHERE key='native_worker_spec'").fetchone()
        if row is None:
            raise ValueError("no approved mission specification")
        return json.loads(row[0])

    def _fence(self, db: Any, row: Any) -> None:
        if row["continuation_id"] is None:
            return
        owner = db.execute("SELECT lease_token,lease_expires_at FROM continuations WHERE id=?",
                           (row["continuation_id"],)).fetchone()
        if owner is None or owner[0] != row["lease_token"] or not owner[1] or owner[1] <= utc_now():
            raise LeaseLost("native worker lost its continuation lease")

    def reconcile_expired(self) -> int:
        """Persist unknown ownership in a separate transaction before admission.

        Expiry never releases a reservation and never proves non-execution.
        A persisted terminal receipt, on the other hand, needs no live lease.
        """
        with self.store._transaction() as db:
            rows = db.execute(
                "SELECT r.* FROM native_worker_runs r LEFT JOIN continuations c ON c.id=r.continuation_id "
                "WHERE r.status='IN_FLIGHT' AND r.continuation_id IS NOT NULL "
                "AND (c.id IS NULL OR c.lease_token IS NULL OR c.lease_token != r.lease_token "
                "OR c.lease_expires_at IS NULL OR c.lease_expires_at<=?)", (utc_now(),)
            ).fetchall()
            for row in rows:
                db.execute("UPDATE native_worker_runs SET status='UNKNOWN' WHERE key=?", (row["key"],))
                self._event(db, "lost_ownership", row["key"], {"status": "UNKNOWN"}, row["continuation_id"])
        return len(rows)

    def reserve(self, key: str, task_id: str, fingerprint: str, *, continuation_id: str | None = None,
                lease_token: str | None = None) -> dict[str, Any] | None:
        self.reconcile_expired()
        with self.store._transaction() as db:
            row = db.execute("SELECT * FROM native_worker_runs WHERE key=?", (key,)).fetchone()
            if row is not None:
                if row["fingerprint"] != fingerprint:
                    raise IdempotencyConflictError("idempotency key reused for different worker input")
                if row["receipt_json"] is not None:
                    return json.loads(row["receipt_json"])
                raise DispatchBlocked("UNKNOWN execution: no durable receipt; do not redispatch")
            spec = json.loads(db.execute("SELECT value FROM metadata WHERE key='native_worker_spec'").fetchone()[0])
            pause = db.execute("SELECT value FROM metadata WHERE key='native_worker_paused'").fetchone()
            if pause and pause[0] == "1":
                raise DispatchBlocked("mission is paused")
            if db.execute("SELECT 1 FROM native_worker_runs WHERE status='UNKNOWN'").fetchone():
                raise DispatchBlocked("unresolved worker result blocks shared spending")
            if spec.get("max_calls") is not None and db.execute("SELECT count(*) FROM native_worker_runs").fetchone()[0] >= spec["max_calls"]:
                raise DispatchBlocked("native call budget exhausted")
            if db.execute("SELECT count(*) FROM native_worker_runs WHERE status='IN_FLIGHT'").fetchone()[0] >= spec["parallelism"]:
                raise DispatchBlocked("worker capacity exhausted")
            row = {"continuation_id": continuation_id, "lease_token": lease_token}
            self._fence(db, row)
            db.execute("INSERT INTO native_worker_runs VALUES(?,?,?,?,?,'IN_FLIGHT',NULL,?)",
                       (key, task_id, continuation_id, fingerprint, lease_token, utc_now()))
            self._event(db, "reserved", key, {"task_id": task_id, "fingerprint": fingerprint}, continuation_id)
        return None

    def event(self, key: str, kind: str, data: dict[str, Any]) -> None:
        with self.store._transaction() as db:
            row = db.execute("SELECT * FROM native_worker_runs WHERE key=?", (key,)).fetchone()
            if row is None or row["status"] != "IN_FLIGHT":
                raise LeaseLost("worker run no longer accepts events")
            self._fence(db, row)
            self._event(db, kind, key, data, row["continuation_id"])
            if kind == "control_ack":
                db.execute("UPDATE native_worker_commands SET status=? WHERE id=? AND run_key=? AND status='SENT'",
                           ("ACK" if data.get("accepted") else "REJECTED", data.get("command_id"), key))

    def complete(self, key: str, receipt: dict[str, Any]) -> dict[str, Any]:
        safe = redact(receipt)
        with self.store._transaction() as db:
            row = db.execute("SELECT * FROM native_worker_runs WHERE key=?", (key,)).fetchone()
            if row is None:
                raise ValueError("unknown worker run")
            if row["receipt_json"] is not None:
                if canonical_json(json.loads(row["receipt_json"])) != canonical_json(safe):
                    raise IdempotencyConflictError("conflicting terminal receipts")
                return json.loads(row["receipt_json"])
            self._fence(db, row)
            status = "UNKNOWN" if safe["status"] == "UNKNOWN" else "RECEIPTED"
            db.execute("UPDATE native_worker_runs SET status=?,receipt_json=? WHERE key=?",
                       (status, canonical_json(safe), key))
            self._event(db, "receipt", key, safe, row["continuation_id"])
        return safe

    def pause(self, paused: bool) -> None:
        with self.store._transaction() as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES('native_worker_paused',?)", ("1" if paused else "0",))
            self._event(db, "pause" if paused else "resume", "mission", {}, actor="operator")

    def paused(self) -> bool:
        with self.store._transaction(immediate=False) as db:
            row = db.execute("SELECT value FROM metadata WHERE key='native_worker_paused'").fetchone()
        return bool(row and row[0] == "1")

    def command(self, key: str, action: str, text: str = "") -> str:
        if action not in {"interrupt", "steer"} or len(text.encode()) > 20_000:
            raise ValueError("invalid control command")
        cid = secrets.token_hex(16)
        with self.store._transaction() as db:
            row = db.execute("SELECT * FROM native_worker_runs WHERE key=?", (key,)).fetchone()
            if row is None or row["status"] != "IN_FLIGHT":
                raise ValueError("no active native run")
            self._fence(db, row)
            spec = json.loads(db.execute("SELECT value FROM metadata WHERE key='native_worker_spec'").fetchone()[0])
            plan = spec.get("tasks")
            if not plan:
                saved = db.execute("SELECT value FROM metadata WHERE key='native_worker_plan'").fetchone()
                plan = json.loads(saved[0]) if saved else []
            driver = spec.get("planner") if row["task_id"] == "planner" else next(
                (t["driver"] for t in plan if t["id"] == row["task_id"]), None)
            if action == "steer" and (driver != "codex" or not text.strip()):
                raise ValueError("live steering requires Codex and a nonempty instruction")
            db.execute("INSERT INTO native_worker_commands VALUES(?,?,?,?, 'PENDING',?)",
                       (cid, key, action, text, utc_now()))
            self._event(db, "control_requested", key, {"id": cid, "action": action, "text": text},
                        row["continuation_id"], actor="operator")
        return cid

    def controls(self, key: str) -> list[dict[str, Any]]:
        with self.store._transaction() as db:
            row = db.execute("SELECT * FROM native_worker_runs WHERE key=?", (key,)).fetchone()
            if row is None or row["status"] != "IN_FLIGHT":
                raise LeaseLost("worker run is not active")
            self._fence(db, row)
            rows = db.execute("SELECT * FROM native_worker_commands WHERE run_key=? AND status='PENDING' ORDER BY created_at", (key,)).fetchall()
            db.execute("UPDATE native_worker_commands SET status='SENT' WHERE run_key=? AND status='PENDING'", (key,))
        # SENT is a handoff, not proof of delivery. Never silently resend on restart.
        return [dict(row) for row in rows]

    def runs(self) -> list[dict[str, Any]]:
        # Read-only join: historical attempt truth comes from canonical evidence,
        # never from a native receipt's success claim.
        with self.store._transaction(immediate=False) as db:
            rows = db.execute(
                "SELECT r.*, e.id AS evidence_id, e.verdict AS verifier_verdict, "
                "e.payload_json AS verification_json FROM native_worker_runs r "
                "LEFT JOIN decisions d ON d.idempotency_key=r.key AND d.capability='workers.execute' "
                "LEFT JOIN evidence e ON e.decision_id=d.id ORDER BY r.created_at,r.key"
            ).fetchall()
        return [{**dict(row), "receipt": json.loads(row["receipt_json"]) if row["receipt_json"] else None,
                 "verdict": row["verifier_verdict"] or ("NOT_APPLICABLE" if row["task_id"] == "planner" else "UNVERIFIED"),
                 "verification": json.loads(row["verification_json"]) if row["verification_json"] else None,
                 "lease_token": "[REDACTED]", "receipt_json": None, "verification_json": None} for row in rows]

    def events(self, cursor: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        if cursor < 0 or not 1 <= limit <= 1000:
            raise ValueError("invalid event cursor/limit")
        with self.store._transaction(immediate=False) as db:
            rows = db.execute("SELECT seq,ts,entity_id,event_type,data_json FROM events WHERE seq>? ORDER BY seq LIMIT ?",
                              (cursor, limit)).fetchall()
        return [{"seq": r[0], "time": r[1], "run_key": r[2], "type": r[3], "data": redact(json.loads(r[4]))} for r in rows]
