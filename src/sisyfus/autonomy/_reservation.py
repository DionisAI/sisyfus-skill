from __future__ import annotations

from typing import Any

from ._common import AutonomyStoreError, ConcurrentUpdate, InvalidTransition, LeaseLost, _canonical_ts
from .models import ContinuationState, Decision, canonical_json, stable_id, utc_now


class ReservationMixin:
    def reserve_decision(
        self,
        continuation_id: str,
        *,
        worker_id: str,
        expected_version: int,
        decision: Decision,
        now: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        now = _canonical_ts(now or utc_now())
        idempotency_key = decision.idempotency_key or stable_id(
            "idem", continuation_id, expected_version, decision.fingerprint(), length=32
        )
        decision_id = stable_id("dec", idempotency_key, length=24)
        payload = decision.as_dict() | {"idempotency_key": idempotency_key}
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM decisions WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if existing is not None:
                existing_item = self._row(existing)
                assert existing_item is not None
                if existing_item["continuation_id"] != continuation_id or existing_item["payload"] != payload:
                    raise AutonomyStoreError(f"idempotency key collision: {idempotency_key}")
                continuation = connection.execute(
                    "SELECT * FROM continuations WHERE id = ?", (continuation_id,)
                ).fetchone()
                continuation_item = self._row(continuation)
                assert continuation_item is not None
                return existing_item, continuation_item, False
            row = connection.execute("SELECT * FROM continuations WHERE id = ?", (continuation_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown continuation: {continuation_id}")
            if row["lease_owner"] != worker_id or not row["lease_expires_at"] or row["lease_expires_at"] <= now:
                raise LeaseLost(f"worker {worker_id!r} no longer owns continuation {continuation_id}")
            if int(row["version"]) != int(expected_version):
                raise ConcurrentUpdate(
                    f"continuation {continuation_id} version changed: expected {expected_version}, actual {row['version']}"
                )
            if row["state"] != ContinuationState.RUNNING.value:
                raise InvalidTransition(f"cannot reserve a decision while continuation is {row['state']}")
            attempt_count = int(row["attempt_count"])
            if decision.action.value == "EXECUTE":
                attempt_count += 1
                if attempt_count > int(row["max_attempts"]):
                    raise AutonomyStoreError(f"continuation {continuation_id} exhausted its attempt budget")
            connection.execute(
                """
                INSERT INTO decisions(
                    id, continuation_id, step_index, action, capability, risk_tier,
                    payload_json, idempotency_key, status, result_json, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'RESERVED', NULL, ?, ?)
                """,
                (
                    decision_id,
                    continuation_id,
                    int(row["step_index"]),
                    decision.action.value,
                    decision.capability,
                    decision.risk_tier.value,
                    canonical_json(payload),
                    idempotency_key,
                    now,
                    now,
                ),
            )
            cursor = connection.execute(
                """
                UPDATE continuations
                SET version = version + 1, attempt_count = ?, updated_at = ?
                WHERE id = ? AND version = ? AND lease_owner = ?
                """,
                (attempt_count, now, continuation_id, int(expected_version), worker_id),
            )
            if cursor.rowcount != 1:
                raise ConcurrentUpdate(f"continuation {continuation_id} changed while reserving decision")
            self._append_event(
                connection,
                continuation_id,
                "DECISION_RESERVED",
                worker_id,
                {
                    "decision_id": decision_id,
                    "idempotency_key": idempotency_key,
                    "action": decision.action.value,
                    "capability": decision.capability,
                    "risk_tier": decision.risk_tier.value,
                },
                now,
            )
            decision_row = connection.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone()
            continuation_row = connection.execute(
                "SELECT * FROM continuations WHERE id = ?", (continuation_id,)
            ).fetchone()
        decision_item = self._row(decision_row)
        continuation_item = self._row(continuation_row)
        assert decision_item is not None and continuation_item is not None
        return decision_item, continuation_item, True

