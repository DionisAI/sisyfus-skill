from __future__ import annotations

from typing import Any, Mapping

from .models import ContinuationState, Decision, TickResult


class SimpleActionMixin:
    def _handle_wait(self, continuation: Mapping[str, Any], decision: Decision, *, now: str) -> TickResult:
        continuation_id = str(continuation["id"])
        updated = self.store.transition(
            continuation_id,
            worker_id=self.worker_id,
            expected_version=int(continuation["version"]),
            to_state=ContinuationState.WAITING,
            event_type="PLANNER_WAIT",
            data={"rationale": decision.rationale},
            next_wake_at=decision.wait_until,
            now=now,
        )
        return TickResult(continuation_id, "WAITING", {"next_wake_at": updated["next_wake_at"]})

    def _handle_abort(self, continuation: Mapping[str, Any], decision: Decision, *, now: str) -> TickResult:
        continuation_id = str(continuation["id"])
        updated = self.store.transition(
            continuation_id,
            worker_id=self.worker_id,
            expected_version=int(continuation["version"]),
            to_state=ContinuationState.FAILED,
            event_type="PLANNER_ABORT",
            data={"rationale": decision.rationale},
            last_error=decision.rationale,
            now=now,
        )
        return TickResult(continuation_id, updated["state"], {"reason": decision.rationale})
