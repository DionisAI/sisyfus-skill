from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .models import ContinuationState, Decision, DecisionAction, TickResult, Verdict, VerificationResult
from .store import AutonomyStoreError


class SettlementMixin:
    def _settle(
        self,
        continuation_id: str,
        *,
        decision_id: str,
        continuation: Mapping[str, Any],
        decision: Decision,
        verification: VerificationResult,
        now: str,
    ) -> TickResult:
        attempt_count = int(continuation["attempt_count"])
        max_attempts = int(continuation["max_attempts"])
        next_wake_at: str | None = None
        last_error: str | None = None
        if verification.verdict == Verdict.PASS:
            to_state = (
                ContinuationState.SUCCEEDED
                if decision.action == DecisionAction.FINISH or decision.terminal_on_pass
                else ContinuationState.READY
            )
        elif verification.verdict == Verdict.FAIL:
            to_state = ContinuationState.FAILED if attempt_count >= max_attempts else ContinuationState.READY
            last_error = verification.summary
        elif verification.verdict == Verdict.INCONCLUSIVE:
            to_state = ContinuationState.FAILED if attempt_count >= max_attempts else ContinuationState.WAITING
            next_wake_at = None if to_state == ContinuationState.FAILED else self._retry_at(now, attempt_count)
            last_error = verification.summary
        else:
            to_state = ContinuationState.FAILED if attempt_count >= max_attempts else ContinuationState.WAITING
            next_wake_at = None if to_state == ContinuationState.FAILED else self._retry_at(now, attempt_count)
            last_error = verification.summary

        experience = None
        if decision.experience_key:
            if verification.verdict == Verdict.PASS:
                polarity = "positive"
                outcome = "support"
            elif verification.verdict == Verdict.FAIL:
                polarity = "negative"
                outcome = "support"
            else:
                polarity = "operational"
                outcome = "support"
            experience = {
                "pattern_key": decision.experience_key,
                "polarity": polarity,
                "claim": verification.summary,
                "scope": dict(decision.experience_scope),
                "confidence": 0.75 if verification.verdict in {Verdict.PASS, Verdict.FAIL} else 0.4,
                "outcome": outcome,
            }

        evidence, updated = self.store.record_verdict(
            decision_id,
            worker_id=self.worker_id,
            expected_version=int(continuation["version"]),
            verification=verification,
            to_state=to_state,
            next_wake_at=next_wake_at,
            last_error=last_error,
            experience=experience,
            now=now,
        )
        return TickResult(
            continuation_id,
            updated["state"],
            {
                "decision_id": decision_id,
                "evidence_id": evidence["id"],
                "verdict": verification.verdict.value,
                "summary": verification.summary,
                "next_wake_at": next_wake_at,
            },
        )

    def _handle_internal_error(self, continuation_id: str, exc: Exception, *, now: str) -> TickResult:
        try:
            current = self.store.get_continuation(continuation_id)
            if current.get("lease_owner") != self.worker_id:
                return TickResult(continuation_id, "ERROR", {"error": str(exc), "lease_released": True})
            exhausted = int(current["attempt_count"]) >= int(current["max_attempts"])
            to_state = ContinuationState.FAILED if exhausted else ContinuationState.WAITING
            next_wake_at = None if exhausted else self._retry_at(now, int(current["attempt_count"]))
            updated = self.store.transition(
                continuation_id,
                worker_id=self.worker_id,
                expected_version=int(current["version"]),
                to_state=to_state,
                event_type="SUPERVISOR_ERROR",
                data={"exception_type": type(exc).__name__, "error": str(exc)},
                next_wake_at=next_wake_at,
                last_error=str(exc),
                now=now,
            )
            return TickResult(
                continuation_id,
                updated["state"],
                {"error": str(exc), "exception_type": type(exc).__name__, "next_wake_at": next_wake_at},
            )
        except (AutonomyStoreError, KeyError) as recovery_exc:
            return TickResult(
                continuation_id,
                "ERROR",
                {
                    "error": str(exc),
                    "exception_type": type(exc).__name__,
                    "recovery_error": str(recovery_exc),
                },
            )

    def _retry_at(self, now: str, attempt_count: int) -> str:
        seconds = min(self.retry_max_seconds, self.retry_base_seconds * (2 ** max(0, int(attempt_count) - 1)))
        parsed = datetime.fromisoformat(now.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (parsed.astimezone(timezone.utc) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
