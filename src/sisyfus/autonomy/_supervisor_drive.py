from __future__ import annotations

from typing import Any, Mapping

from .models import Decision, DecisionAction, TickResult
from .policy import ContinuationContext
from .store import ConcurrentUpdate, LeaseLost


class DriveMixin:
    def _drive(self, continuation: Mapping[str, Any], *, now: str) -> TickResult:
        continuation_id = str(continuation["id"])
        try:
            context = ContinuationContext.from_snapshot(self.store.snapshot(continuation_id))
            decision = self.planner.decide(context)
            if not isinstance(decision, Decision):
                raise TypeError(f"planner returned {type(decision).__name__}, expected Decision")
            if decision.action == DecisionAction.WAIT:
                return self._handle_wait(continuation, decision, now=now)
            if decision.action == DecisionAction.ABORT:
                return self._handle_abort(continuation, decision, now=now)
            if decision.action == DecisionAction.FINISH:
                return self._persist_and_verify_finish(context, continuation, decision, now=now)
            return self._execute_decision(context, continuation, decision, now=now)
        except (ConcurrentUpdate, LeaseLost) as exc:
            return TickResult(continuation_id, "LOST_RACE", {"error": str(exc)})
        except Exception as exc:
            return self._handle_internal_error(continuation_id, exc, now=now)
