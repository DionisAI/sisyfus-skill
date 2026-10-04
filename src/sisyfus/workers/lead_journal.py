"""Tech Lead projections and transport metadata in the canonical autonomy store.

These records are not task verdicts. Only AutonomyStore.record_verdict grants
PASS. Every mutation below participates in its existing event hash chain.
"""
from __future__ import annotations

import json
import math
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..autonomy.models import canonical_json, utc_now
from ..autonomy.policy import IdempotencyConflictError
from .journal import DispatchBlocked, Journal
from .protocol import digest, redact


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def metering(receipt: dict[str, Any]) -> tuple[float | None, float | None]:
    """Read provider telemetry, never estimate missing spending from text size."""
    usage = receipt.get("usage") or {}
    tokens = _number(usage.get("total_tokens"))
    native = usage.get("total") or usage.get("tokens") or {}
    if isinstance(native, dict):
        if tokens is None:
            tokens = _number(native.get("totalTokens", native.get("total_tokens")))
        if tokens is None and "input_tokens" in native and "output_tokens" in native:
            parts = [native.get(k, 0) for k in ("input_tokens", "output_tokens",
                     "cache_creation_input_tokens", "cache_read_input_tokens")]
            if all(_number(p) is not None for p in parts):
                tokens = sum(parts)
    cost = _number(usage.get("reported_total_cost_usd", usage.get("cost_usd")))
    return tokens, cost


def reservation_metering(rows) -> dict[str, Any]:
    """Provider totals from actual reservations, with missing telemetry explicit."""
    sessions: dict[str, dict[str, float]] = {}
    missing = {"tokens": [], "cost_usd": []}
    for row in rows:
        if not row["receipt_json"]:
            for field in missing:
                missing[field].append(row["key"])
            continue
        receipt = json.loads(row["receipt_json"])
        # Provider session totals are cumulative; never sum resumed totals.
        ident = receipt.get("session_id") or row["key"]
        for field, value in zip(("tokens", "cost_usd"), metering(receipt)):
            if value is None:
                missing[field].append(row["key"])
            else:
                bucket = sessions.setdefault(ident, {})
                bucket[field] = max(bucket.get(field, 0), value)
    return {field: sum(s.get(field, 0) for s in sessions.values()) if not missing[field] else None
            for field in missing} | {"missing_metering": missing}


class LeadJournal(Journal):
    prefix = "techlead:"

    def __init__(self, store):
        super().__init__(store)
        self.before_reserve = None
        self.on_control = None
        self.stop_event = None
        with self.store._transaction() as db:
            if db.execute("SELECT 1 FROM metadata WHERE key=?", (self.prefix + "state",)).fetchone() is None:
                state = {"phase": "PLANNING", "revision": 0, "active": [], "superseded": {},
                         "procedure_version": 1, "resume_epoch": 0, "stopped": False, "created_at": utc_now()}
                db.execute("INSERT INTO metadata VALUES(?,?)", (self.prefix + "state", canonical_json(state)))
                self._event(db, "lead_initialized", "mission", state)

    def state(self) -> dict[str, Any]:
        with self.store._transaction(immediate=False) as db:
            return json.loads(db.execute("SELECT value FROM metadata WHERE key=?", (self.prefix + "state",)).fetchone()[0])

    def update(self, change: Callable[[dict[str, Any]], None], *, kind: str = "lead_state") -> dict[str, Any]:
        with self.store._transaction() as db:
            state = json.loads(db.execute("SELECT value FROM metadata WHERE key=?", (self.prefix + "state",)).fetchone()[0])
            before = digest(state)
            change(state)
            if digest(state) != before:
                db.execute("UPDATE metadata SET value=? WHERE key=?", (canonical_json(state), self.prefix + "state"))
                self._event(db, kind, "mission", {"before_hash": before, "state": state})
            return state

    def phase(self, phase: str, reason: str = "") -> None:
        self.update(lambda s: s.update(phase=phase, reason=redact(reason)))

    def record(self, category: str, key: str, data: dict[str, Any]) -> dict[str, Any]:
        """Immutable, idempotent receipt/proposal; no extra database or verdict table."""
        safe = redact(data)
        name = self.prefix + category + ":" + key
        with self.store._transaction() as db:
            row = db.execute("SELECT value FROM metadata WHERE key=?", (name,)).fetchone()
            if row:
                saved = json.loads(row[0])
                if saved["data"] != safe:
                    raise IdempotencyConflictError(f"conflicting {category} record: {key}")
                return saved
            saved = {"key": key, "created_at": utc_now(), "data": safe}
            db.execute("INSERT INTO metadata VALUES(?,?)", (name, canonical_json(saved)))
            self._event(db, "lead_" + category, key, saved)
            return saved

    def get(self, category: str, key: str) -> dict[str, Any] | None:
        with self.store._transaction(immediate=False) as db:
            row = db.execute("SELECT value FROM metadata WHERE key=?", (self.prefix + category + ":" + key,)).fetchone()
        return json.loads(row[0])["data"] if row else None

    def records(self, category: str) -> list[dict[str, Any]]:
        prefix = self.prefix + category + ":"
        with self.store._transaction(immediate=False) as db:
            rows = db.execute("SELECT value FROM metadata WHERE substr(key,1,?)=?", (len(prefix), prefix)).fetchall()
        return sorted((json.loads(r[0]) for r in rows), key=lambda r: (r["created_at"], r["key"]))

    def counters(self, db=None, *, exclude: str | None = None) -> dict[str, Any]:
        if db is None:
            with self.store._transaction(immediate=False) as connection:
                return self.counters(connection, exclude=exclude)
        rows = db.execute("SELECT key,status,receipt_json FROM native_worker_runs").fetchall()
        rows = [r for r in rows if r["key"] != exclude]
        state = json.loads(db.execute("SELECT value FROM metadata WHERE key=?", (self.prefix + "state",)).fetchone()[0])
        started = datetime.fromisoformat(state["created_at"].replace("Z", "+00:00"))
        return {"calls": len(rows), "iterations": state["revision"], **reservation_metering(rows),
                "wall_minutes": max(0, (datetime.now(timezone.utc) - started).total_seconds() / 60)}

    @staticmethod
    def inspect_child(directory: str) -> dict[str, Any]:
        """Read an existing child DB; never initialize/reconcile a controller.

        This is observability, not a copied verdict or model attestation. Missing
        or malformed databases produce unknown counts and an explicit error.
        """
        result = {"directory": directory, "read_status": "ERROR", "phase": "UNKNOWN",
                  "reservations": None, "run_status_counts": None, "receipt_status_counts": None,
                  "runs": None, "unresolved": None, "metering": None, "observation_only": True}
        db = None
        try:
            path = Path(directory)
            if not path.is_absolute() or path.is_symlink() or path.resolve() != path:
                raise ValueError("child control path must be fixed, absolute and unaliased")
            database = path / "autonomy.sqlite3"
            if database.is_symlink() or not database.is_file():
                raise ValueError("registered child database is missing or aliased")
            db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")  # State and transport rows from one read snapshot.
            row = db.execute("SELECT value FROM metadata WHERE key='techlead:state'").fetchone()
            if row is None:
                raise ValueError("registered child lacks canonical Lead state")
            state = json.loads(row[0])
            if not isinstance(state, dict) or not isinstance(state.get("phase"), str):
                raise ValueError("registered child Lead state is malformed")
            paused = db.execute("SELECT value FROM metadata WHERE key='native_worker_paused'").fetchone()
            rows = db.execute("SELECT key,task_id,status,receipt_json FROM native_worker_runs ORDER BY created_at,key").fetchall()
            transport, receipts, runs, unresolved = {}, {}, [], []
            for row in rows:
                status = row["status"]
                if status not in {"RECEIPTED", "IN_FLIGHT", "UNKNOWN"}:
                    raise ValueError("registered child transport status is malformed: " + row["key"])
                receipt = json.loads(row["receipt_json"]) if row["receipt_json"] else None
                if receipt is not None and (not isinstance(receipt, dict) or not isinstance(receipt.get("status"), str)):
                    raise ValueError("registered child native receipt is malformed: " + row["key"])
                if receipt is not None and receipt.get("usage") is not None and not isinstance(receipt["usage"], dict):
                    raise ValueError("registered child native usage is malformed: " + row["key"])
                if status == "RECEIPTED" and receipt is None:
                    raise ValueError("registered child settled reservation lacks receipt: " + row["key"])
                terminal = receipt["status"] if receipt else None
                transport[status] = transport.get(status, 0) + 1
                if terminal is not None:
                    receipts[terminal] = receipts.get(terminal, 0) + 1
                if status != "RECEIPTED" or terminal not in {"COMPLETED", "ERROR", "FAILED", "INTERRUPTED", "CANCELLED"}:
                    unresolved.append(row["key"])
                runs.append({"key": row["key"], "task_id": row["task_id"], "status": status,
                             "receipt_status": terminal,
                             "requested_model": receipt.get("requested_model") if receipt else None,
                             "actual_model": receipt.get("actual_model") if receipt else None})
            result.update(read_status="OK", phase="STOPPED" if state.get("stopped") else
                          "PAUSED" if paused and paused[0] == "1" else state["phase"],
                          paused=bool(paused and paused[0] == "1"), stopped=bool(state.get("stopped")),
                          reservations=len(rows), run_status_counts=transport, receipt_status_counts=receipts,
                          runs=runs, unresolved=unresolved, metering=reservation_metering(rows))
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
            result["error"] = redact(f"{type(exc).__name__}: {exc}")
        finally:
            if db is not None:
                db.close()
        return result

    def budget_reason(self, *, db=None, reserving: bool = False) -> str | None:
        if db is None:
            with self.store._transaction(immediate=False) as connection:
                return self.budget_reason(db=connection, reserving=reserving)
        spec = json.loads(db.execute("SELECT value FROM metadata WHERE key='native_worker_spec'").fetchone()[0])
        latest = db.execute("SELECT key FROM native_worker_runs ORDER BY created_at DESC,rowid DESC LIMIT 1").fetchone() if reserving else None
        counts = self.counters(db, exclude=latest[0] if latest else None)
        # At the reservation event the new row has already been inserted.
        calls = counts["calls"]
        for name, amount in (("max_calls", calls), ("max_tokens", counts["tokens"]),
                             ("max_cost_usd", counts["cost_usd"]), ("max_wall_minutes", counts["wall_minutes"])):
            cap = spec.get(name)
            if cap is None:
                continue
            if amount is None:
                missing = counts["missing_metering"]["tokens" if name == "max_tokens" else "cost_usd"]
                if missing:
                    return f"{name}: provider metering missing; shared spending fenced"
            elif amount >= cap:
                return f"{name} exhausted"
        return None

    def _event(self, db, kind, key, data, continuation_id=None, actor="native-worker"):
        if kind == "reserved":
            state = json.loads(db.execute("SELECT value FROM metadata WHERE key=?", (self.prefix + "state",)).fetchone()[0])
            if state["stopped"]:
                raise DispatchBlocked("operator stopped mission")
            reason = self.budget_reason(db=db, reserving=True)
            if reason:
                raise DispatchBlocked(reason)
        super()._event(db, kind, key, data, continuation_id, actor)

    def runs(self) -> list[dict[str, Any]]:
        roles = {r["key"]: r["data"] for r in self.records("roles")}
        return [{**r, "role": roles.get(r["key"], {}).get("role", "worker"),
                 "role_metadata": roles.get(r["key"])} for r in super().runs()]

    def reserve(self, key, task_id, fingerprint, *, continuation_id=None, lease_token=None):
        # The core-owned freeze happens before even direct/manual reservation
        # paths. It creates no replacement truth and never backfills legacy runs.
        while True:
            if self.before_reserve is not None:
                self.before_reserve()
            try:
                return super().reserve(key, task_id, fingerprint, continuation_id=continuation_id, lease_token=lease_token)
            except DispatchBlocked as exc:
                if str(exc) != "mission is paused":
                    raise
                # The failed reservation transaction wrote no run. Keep the
                # same capability attempt/lease alive instead of recording an
                # ERROR that would exhaust its one admitted revision attempt.
                while self.paused():
                    if self.state()["stopped"] or self.stop_event is not None and self.stop_event.is_set():
                        raise DispatchBlocked("operator stopped mission during pause") from exc
                    self.phase("PAUSED")
                    if self.stop_event is None:
                        time.sleep(.02)
                    else:
                        self.stop_event.wait(.02)

    def request_resume(self, reason: str = "operator resume") -> int:
        """Operator-owned epoch: re-diagnose saved wait/stop, never clear UNKNOWN."""
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 20000:
            raise ValueError("operator resume reason must be bounded nonempty text")
        with self.store._transaction() as db:
            state = json.loads(db.execute("SELECT value FROM metadata WHERE key=?", (self.prefix + "state",)).fetchone()[0])
            if state["stopped"] or self.stop_event is not None and self.stop_event.is_set():
                raise DispatchBlocked("operator stopped mission; persistent stop remains set")
            if db.execute("SELECT 1 FROM native_worker_runs WHERE status='UNKNOWN'").fetchone():
                raise DispatchBlocked("UNKNOWN execution requires reconciliation before operator resume")
            before = digest(state)
            state["resume_epoch"] = state.get("resume_epoch", 0) + 1
            state["resume_reason"] = redact(reason)
            if state["phase"] in {"WAITING_LEAD", "NEEDS_OPERATOR", "PAUSED"}:
                state.update(phase="DIAGNOSING" if state["active"] else "PLANNING", reason=redact(reason))
            db.execute("UPDATE metadata SET value=? WHERE key=?", (canonical_json(state), self.prefix + "state"))
            db.execute("INSERT OR REPLACE INTO metadata VALUES('native_worker_paused','0')")
            self._event(db, "lead_operator_resume", "mission", {"before_hash": before, "state": state}, actor="operator")
            self._event(db, "resume", "mission", {"resume_epoch": state["resume_epoch"]}, actor="operator")
        if self.on_control is not None:
            self.on_control()
        return state["resume_epoch"]

    def pause(self, paused: bool) -> None:
        super().pause(paused)
        if self.on_control is not None:
            self.on_control()

    def reconcile_roles(self) -> int:
        """Only call while owning the mission run lock: orphan role calls fence."""
        with self.store._transaction() as db:
            rows = db.execute("SELECT key FROM native_worker_runs WHERE task_id='planner' AND status='IN_FLIGHT'").fetchall()
            for row in rows:
                db.execute("UPDATE native_worker_runs SET status='UNKNOWN' WHERE key=?", (row[0],))
                self._event(db, "lost_role_ownership", row[0], {"status": "UNKNOWN"})
        return len(rows)

    def request_stop(self) -> None:
        self.update(lambda s: s.update(stopped=True, phase="STOPPED"), kind="lead_stop")
        self.reconcile_expired()
        # Selection and command insertion share the write transaction. A native
        # completion racing with stop is normal, not an operator-control error.
        with self.store._transaction() as db:
            rows = db.execute("SELECT * FROM native_worker_runs WHERE status='IN_FLIGHT'").fetchall()
            for row in rows:
                self._fence(db, row)
                cid = secrets.token_hex(16)
                db.execute("INSERT INTO native_worker_commands VALUES(?,?,?,?, 'PENDING',?)",
                           (cid, row["key"], "interrupt", "", utc_now()))
                self._event(db, "control_requested", row["key"], {"id": cid, "action": "interrupt", "text": ""},
                            row["continuation_id"], actor="operator")
