from __future__ import annotations

from typing import Any, Mapping

from ._common import AutonomyStoreError, ConcurrentUpdate, LeaseLost, _canonical_ts, _decode_json
from .models import ContinuationState, canonical_json, utc_now


class ExecutionMixin:
    def record_execution(
        self,
        decision_id: str,
        *,
        worker_id: str,
        expected_version: int,
        result: Mapping[str, Any],
        now: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        now = _canonical_ts(now or utc_now())
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
            if decision["status"] == "EXECUTED":
                existing = _decode_json(decision["result_json"], {})
                if existing != dict(result):
                    raise AutonomyStoreError(f"decision {decision_id} already has a different execution result")
                return self._row(decision) or {}, self._row(continuation) or {}
            if decision["status"] != "RESERVED":
                raise AutonomyStoreError(f"decision {decision_id} is {decision['status']}, not RESERVED")
            connection.execute(
                "UPDATE decisions SET status = 'EXECUTED', result_json = ?, updated_at = ? WHERE id = ?",
                (canonical_json(dict(result)), now, decision_id),
            )
            connection.execute(
                "UPDATE continuations SET state = ?, version = version + 1, updated_at = ? WHERE id = ?",
                (ContinuationState.VERIFYING.value, now, continuation_id),
            )
            self._append_event(
                connection,
                continuation_id,
                "CAPABILITY_EXECUTED",
                worker_id,
                {"decision_id": decision_id, "result": dict(result)},
                now,
            )
            decision_row = connection.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone()
            continuation_row = connection.execute(
                "SELECT * FROM continuations WHERE id = ?", (continuation_id,)
            ).fetchone()
        decision_item = self._row(decision_row)
        continuation_item = self._row(continuation_row)
        assert decision_item is not None and continuation_item is not None
        return decision_item, continuation_item

