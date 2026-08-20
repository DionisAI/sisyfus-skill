from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from ._common import (
    AutonomyStoreError,
    ConcurrentUpdate,
    InvalidTransition,
    LeaseLost,
    _ALLOWED_TRANSITIONS,
    _add_seconds,
    _canonical_ts,
)
from .models import ContinuationState, TERMINAL_STATES, utc_now


class LeaseMixin:
    def claim_due_continuation(
        self,
        worker_id: str,
        *,
        lease_seconds: int = 60,
        now: str | None = None,
    ) -> dict[str, Any] | None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        now = _canonical_ts(now or utc_now())
        lease_expires_at = _add_seconds(now, lease_seconds)
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT c.*
                FROM continuations c
                JOIN opportunities o ON o.id = c.opportunity_id
                WHERE c.state IN (?, ?)
                  AND c.attempt_count < c.max_attempts
                  AND (c.next_wake_at IS NULL OR c.next_wake_at <= ?)
                  AND (c.lease_expires_at IS NULL OR c.lease_expires_at <= ? OR c.lease_owner = ?)
                ORDER BY o.priority DESC, o.confidence DESC, c.created_at ASC
                LIMIT 1
                """,
                (
                    ContinuationState.READY.value,
                    ContinuationState.WAITING.value,
                    now,
                    now,
                    worker_id,
                ),
            ).fetchone()
            if row is None:
                return None
            old_version = int(row["version"])
            cursor = connection.execute(
                """
                UPDATE continuations
                SET state = ?, version = version + 1, lease_owner = ?, lease_expires_at = ?,
                    next_wake_at = NULL, updated_at = ?
                WHERE id = ? AND version = ?
                  AND (lease_expires_at IS NULL OR lease_expires_at <= ? OR lease_owner = ?)
                """,
                (
                    ContinuationState.RUNNING.value,
                    worker_id,
                    lease_expires_at,
                    now,
                    row["id"],
                    old_version,
                    now,
                    worker_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ConcurrentUpdate(f"continuation {row['id']} was claimed concurrently")
            self._append_event(
                connection,
                str(row["id"]),
                "LEASE_ACQUIRED",
                worker_id,
                {"lease_expires_at": lease_expires_at, "previous_state": row["state"]},
                now,
            )
            claimed = connection.execute("SELECT * FROM continuations WHERE id = ?", (row["id"],)).fetchone()
        return self._row(claimed)

    def renew_lease(
        self,
        continuation_id: str,
        worker_id: str,
        *,
        expected_version: int,
        lease_seconds: int = 60,
        now: str | None = None,
    ) -> dict[str, Any]:
        now = _canonical_ts(now or utc_now())
        lease_expires_at = _add_seconds(now, lease_seconds)
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE continuations
                SET version = version + 1, lease_expires_at = ?, updated_at = ?
                WHERE id = ? AND version = ? AND lease_owner = ?
                  AND state IN (?, ?) AND lease_expires_at > ?
                """,
                (
                    lease_expires_at,
                    now,
                    continuation_id,
                    int(expected_version),
                    worker_id,
                    ContinuationState.RUNNING.value,
                    ContinuationState.VERIFYING.value,
                    now,
                ),
            )
            if cursor.rowcount != 1:
                self._raise_lease_or_version(connection, continuation_id, worker_id, expected_version, now)
            self._append_event(
                connection,
                continuation_id,
                "LEASE_RENEWED",
                worker_id,
                {"lease_expires_at": lease_expires_at},
                now,
            )
            row = connection.execute("SELECT * FROM continuations WHERE id = ?", (continuation_id,)).fetchone()
        item = self._row(row)
        assert item is not None
        return item

    @staticmethod
    def _raise_lease_or_version(
        connection: sqlite3.Connection,
        continuation_id: str,
        worker_id: str,
        expected_version: int,
        now: str,
    ) -> None:
        row = connection.execute("SELECT * FROM continuations WHERE id = ?", (continuation_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown continuation: {continuation_id}")
        if row["lease_owner"] != worker_id or not row["lease_expires_at"] or row["lease_expires_at"] <= now:
            raise LeaseLost(f"worker {worker_id!r} no longer owns continuation {continuation_id}")
        raise ConcurrentUpdate(
            f"continuation {continuation_id} version changed: expected {expected_version}, actual {row['version']}"
        )

    def transition(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        expected_version: int,
        to_state: ContinuationState,
        event_type: str,
        data: Mapping[str, Any] | None = None,
        next_wake_at: str | None = None,
        last_error: str | None = None,
        release_lease: bool = True,
        increment_step: bool = False,
        increment_attempt: bool = False,
        now: str | None = None,
    ) -> dict[str, Any]:
        now = _canonical_ts(now or utc_now())
        next_wake_at = _canonical_ts(next_wake_at) if next_wake_at else None
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM continuations WHERE id = ?", (continuation_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown continuation: {continuation_id}")
            if row["lease_owner"] != worker_id or not row["lease_expires_at"] or row["lease_expires_at"] <= now:
                raise LeaseLost(f"worker {worker_id!r} no longer owns continuation {continuation_id}")
            if int(row["version"]) != int(expected_version):
                raise ConcurrentUpdate(
                    f"continuation {continuation_id} version changed: expected {expected_version}, actual {row['version']}"
                )
            from_state = ContinuationState(str(row["state"]))
            if to_state not in _ALLOWED_TRANSITIONS[from_state]:
                raise InvalidTransition(f"cannot transition {continuation_id} from {from_state} to {to_state}")
            next_step = int(row["step_index"]) + (1 if increment_step else 0)
            next_attempt = int(row["attempt_count"]) + (1 if increment_attempt else 0)
            if next_attempt > int(row["max_attempts"]):
                raise AutonomyStoreError(f"continuation {continuation_id} exhausted its attempt budget")
            lease_owner = None if release_lease else worker_id
            lease_expires_at = None if release_lease else row["lease_expires_at"]
            cursor = connection.execute(
                """
                UPDATE continuations
                SET state = ?, version = version + 1, step_index = ?, attempt_count = ?,
                    next_wake_at = ?, lease_owner = ?, lease_expires_at = ?,
                    last_error = ?, updated_at = ?
                WHERE id = ? AND version = ? AND lease_owner = ?
                """,
                (
                    to_state.value,
                    next_step,
                    next_attempt,
                    next_wake_at,
                    lease_owner,
                    lease_expires_at,
                    last_error,
                    now,
                    continuation_id,
                    int(expected_version),
                    worker_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ConcurrentUpdate(f"continuation {continuation_id} changed during transition")
            self._append_event(
                connection,
                continuation_id,
                event_type,
                worker_id,
                {
                    "from_state": from_state.value,
                    "to_state": to_state.value,
                    "next_wake_at": next_wake_at,
                    "last_error": last_error,
                    **dict(data or {}),
                },
                now,
            )
            updated = connection.execute("SELECT * FROM continuations WHERE id = ?", (continuation_id,)).fetchone()
        item = self._row(updated)
        assert item is not None
        return item

    def recover_expired_leases(self, *, now: str | None = None, retry_delay_seconds: int = 5) -> list[str]:
        now = _canonical_ts(now or utc_now())
        next_wake_at = _add_seconds(now, retry_delay_seconds)
        recovered: list[str] = []
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT * FROM continuations
                WHERE state IN (?, ?) AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?
                ORDER BY lease_expires_at ASC
                """,
                (ContinuationState.RUNNING.value, ContinuationState.VERIFYING.value, now),
            ).fetchall()
            for row in rows:
                exhausted = int(row["attempt_count"]) >= int(row["max_attempts"])
                to_state = ContinuationState.FAILED if exhausted else ContinuationState.WAITING
                wake = None if exhausted else next_wake_at
                connection.execute(
                    """
                    UPDATE continuations
                    SET state = ?, version = version + 1, next_wake_at = ?, lease_owner = NULL,
                        lease_expires_at = NULL, last_error = 'worker lease expired', updated_at = ?
                    WHERE id = ? AND version = ?
                    """,
                    (to_state.value, wake, now, row["id"], row["version"]),
                )
                self._append_event(
                    connection,
                    str(row["id"]),
                    "LEASE_EXPIRED",
                    "supervisor",
                    {
                        "previous_owner": row["lease_owner"],
                        "previous_state": row["state"],
                        "to_state": to_state.value,
                        "next_wake_at": wake,
                    },
                    now,
                )
                recovered.append(str(row["id"]))
        return recovered

    def cancel(self, continuation_id: str, *, actor: str = "operator", now: str | None = None) -> dict[str, Any]:
        now = _canonical_ts(now or utc_now())
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM continuations WHERE id = ?", (continuation_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown continuation: {continuation_id}")
            current = ContinuationState(str(row["state"]))
            if current in TERMINAL_STATES:
                return self._row(row) or {}
            connection.execute(
                """
                UPDATE continuations
                SET state = ?, version = version + 1, lease_owner = NULL, lease_expires_at = NULL,
                    next_wake_at = NULL, updated_at = ?
                WHERE id = ? AND version = ?
                """,
                (ContinuationState.CANCELLED.value, now, continuation_id, row["version"]),
            )
            self._append_event(
                connection,
                continuation_id,
                "CONTINUATION_CANCELLED",
                actor,
                {"previous_state": current.value},
                now,
            )
            updated = connection.execute("SELECT * FROM continuations WHERE id = ?", (continuation_id,)).fetchone()
        item = self._row(updated)
        assert item is not None
        return item
