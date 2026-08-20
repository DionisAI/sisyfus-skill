from __future__ import annotations

from typing import Any, Mapping

from ._common import (
    AutonomyStoreError, ConcurrentUpdate, InvalidTransition, LeaseLost,
    _ALLOWED_TRANSITIONS, _canonical_ts, _decode_json,
)
from .models import ContinuationState, VerificationResult, canonical_json, stable_id, utc_now


class VerdictMixin:
    def record_verdict(
        self,
        decision_id: str,
        *,
        worker_id: str,
        expected_version: int,
        verification: VerificationResult,
        to_state: ContinuationState,
        next_wake_at: str | None = None,
        last_error: str | None = None,
        experience: Mapping[str, Any] | None = None,
        now: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        now = _canonical_ts(now or utc_now())
        next_wake_at = _canonical_ts(next_wake_at) if next_wake_at else None
        with self._transaction() as connection:
            decision = connection.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone()
            if decision is None:
                raise KeyError(f"unknown decision: {decision_id}")
            continuation_id = str(decision["continuation_id"])
            continuation = connection.execute(
                "SELECT * FROM continuations WHERE id = ?", (continuation_id,)
            ).fetchone()
            if continuation is None:
                raise KeyError(f"unknown continuation: {continuation_id}")
            if continuation["lease_owner"] != worker_id or not continuation["lease_expires_at"] or continuation[
                "lease_expires_at"
            ] <= now:
                raise LeaseLost(f"worker {worker_id!r} no longer owns continuation {continuation_id}")
            if int(continuation["version"]) != int(expected_version):
                raise ConcurrentUpdate(
                    f"continuation {continuation_id} version changed: expected {expected_version}, actual {continuation['version']}"
                )
            current_state = ContinuationState(str(continuation["state"]))
            if to_state not in _ALLOWED_TRANSITIONS[current_state]:
                raise InvalidTransition(f"cannot transition {continuation_id} from {current_state} to {to_state}")
            existing_evidence = connection.execute(
                "SELECT * FROM evidence WHERE decision_id = ?", (decision_id,)
            ).fetchone()
            if existing_evidence is not None:
                existing_payload = _decode_json(existing_evidence["payload_json"], {})
                if existing_payload != verification.as_dict():
                    raise AutonomyStoreError(f"decision {decision_id} already has a different verdict")
                return self._row(existing_evidence) or {}, self._row(continuation) or {}
            if decision["status"] != "EXECUTED":
                raise AutonomyStoreError(f"decision {decision_id} is {decision['status']}, not EXECUTED")
            evidence_id = stable_id("evidence", decision_id, verification.as_dict(), length=24)
            connection.execute(
                """
                INSERT INTO evidence(
                    id, continuation_id, decision_id, verifier_id, verdict,
                    summary, payload_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    continuation_id,
                    decision_id,
                    verification.verifier_id,
                    verification.verdict.value,
                    verification.summary,
                    canonical_json(verification.as_dict()),
                    now,
                ),
            )
            connection.execute(
                "UPDATE decisions SET status = 'VERIFIED', updated_at = ? WHERE id = ?", (now, decision_id)
            )
            connection.execute(
                """
                UPDATE continuations
                SET state = ?, version = version + 1, step_index = step_index + 1,
                    next_wake_at = ?, lease_owner = NULL, lease_expires_at = NULL,
                    last_error = ?, updated_at = ?
                WHERE id = ? AND version = ? AND lease_owner = ?
                """,
                (
                    to_state.value,
                    next_wake_at,
                    last_error,
                    now,
                    continuation_id,
                    int(expected_version),
                    worker_id,
                ),
            )
            self._append_event(
                connection,
                continuation_id,
                "VERDICT_RECORDED",
                verification.verifier_id,
                {
                    "decision_id": decision_id,
                    "evidence_id": evidence_id,
                    "verdict": verification.verdict.value,
                    "summary": verification.summary,
                    "to_state": to_state.value,
                    "next_wake_at": next_wake_at,
                },
                now,
            )
            if experience:
                self._upsert_experience_locked(connection, evidence_id=evidence_id, now=now, **dict(experience))
            evidence_row = connection.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
            continuation_row = connection.execute(
                "SELECT * FROM continuations WHERE id = ?", (continuation_id,)
            ).fetchone()
        evidence_item = self._row(evidence_row)
        continuation_item = self._row(continuation_row)
        assert evidence_item is not None and continuation_item is not None
        return evidence_item, continuation_item

