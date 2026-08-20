from __future__ import annotations

from contextlib import closing
from typing import Any

from ._common import AutonomyStoreError, _canonical_ts
from .models import ContinuationState, OpportunityProposal, OpportunityStatus, canonical_json, stable_id, utc_now


class OpportunityMixin:
    def ingest_opportunity(
        self, proposal: OpportunityProposal, *, now: str | None = None
    ) -> tuple[dict[str, Any], bool]:
        now = _canonical_ts(now or utc_now())
        opportunity_id = stable_id("opp", proposal.dedupe_key)
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO opportunities(
                    id, dedupe_key, source, kind, payload_json, priority, confidence,
                    status, not_before, expires_at, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    opportunity_id,
                    proposal.dedupe_key,
                    proposal.source,
                    proposal.kind,
                    canonical_json(dict(proposal.payload)),
                    int(proposal.priority),
                    float(proposal.confidence),
                    OpportunityStatus.OPEN.value,
                    _canonical_ts(proposal.not_before) if proposal.not_before else None,
                    _canonical_ts(proposal.expires_at) if proposal.expires_at else None,
                    now,
                    now,
                ),
            )
            created = cursor.rowcount == 1
            row = connection.execute("SELECT * FROM opportunities WHERE dedupe_key = ?", (proposal.dedupe_key,)).fetchone()
        item = self._row(row)
        assert item is not None
        return item, created

    def get_opportunity(self, opportunity_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM opportunities WHERE id = ?", (opportunity_id,)).fetchone()
        item = self._row(row)
        if item is None:
            raise KeyError(f"unknown opportunity: {opportunity_id}")
        return item

    def admit_opportunity(
        self,
        opportunity_id: str,
        *,
        objective: str,
        max_attempts: int = 5,
        actor: str = "admission",
        now: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        if not objective.strip():
            raise ValueError("continuation objective must not be empty")
        if int(max_attempts) <= 0:
            raise ValueError("max_attempts must be positive")
        now = _canonical_ts(now or utc_now())
        continuation_id = stable_id("cont", opportunity_id)
        with self._transaction() as connection:
            opportunity = connection.execute("SELECT * FROM opportunities WHERE id = ?", (opportunity_id,)).fetchone()
            if opportunity is None:
                raise KeyError(f"unknown opportunity: {opportunity_id}")
            existing = connection.execute(
                "SELECT * FROM continuations WHERE opportunity_id = ?", (opportunity_id,)
            ).fetchone()
            if existing is not None:
                item = self._row(existing)
                assert item is not None
                return item, False
            if opportunity["status"] != OpportunityStatus.OPEN.value:
                raise AutonomyStoreError(
                    f"opportunity {opportunity_id} is {opportunity['status']}, not {OpportunityStatus.OPEN.value}"
                )
            if opportunity["expires_at"] and opportunity["expires_at"] <= now:
                connection.execute(
                    "UPDATE opportunities SET status = ?, updated_at = ? WHERE id = ?",
                    (OpportunityStatus.EXPIRED.value, now, opportunity_id),
                )
                raise AutonomyStoreError(f"opportunity {opportunity_id} has expired")
            connection.execute(
                "UPDATE opportunities SET status = ?, updated_at = ? WHERE id = ?",
                (OpportunityStatus.ADMITTED.value, now, opportunity_id),
            )
            connection.execute(
                """
                INSERT INTO continuations(
                    id, opportunity_id, objective, state, version, step_index, attempt_count,
                    max_attempts, next_wake_at, lease_owner, lease_expires_at,
                    last_error, created_at, updated_at
                ) VALUES(?, ?, ?, ?, 1, 0, 0, ?, ?, NULL, NULL, NULL, ?, ?)
                """,
                (
                    continuation_id,
                    opportunity_id,
                    objective,
                    ContinuationState.READY.value,
                    int(max_attempts),
                    opportunity["not_before"],
                    now,
                    now,
                ),
            )
            self._append_event(
                connection,
                continuation_id,
                "CONTINUATION_CREATED",
                actor,
                {"opportunity_id": opportunity_id, "objective": objective, "max_attempts": int(max_attempts)},
                now,
            )
            row = connection.execute("SELECT * FROM continuations WHERE id = ?", (continuation_id,)).fetchone()
        item = self._row(row)
        assert item is not None
        return item, True

    def get_continuation(self, continuation_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM continuations WHERE id = ?", (continuation_id,)).fetchone()
        item = self._row(row)
        if item is None:
            raise KeyError(f"unknown continuation: {continuation_id}")
        return item

