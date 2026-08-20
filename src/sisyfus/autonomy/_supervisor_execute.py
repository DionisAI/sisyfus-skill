from __future__ import annotations

from typing import Any, Mapping

from .models import CapabilityResult, ContinuationState, Decision, TickResult, VerificationResult, stable_id
from .policy import ContinuationContext


class ExecuteMixin:
    def _execute_decision(
        self,
        context: ContinuationContext,
        continuation: Mapping[str, Any],
        decision: Decision,
        *,
        now: str,
    ) -> TickResult:
        continuation_id = str(continuation["id"])
        capability = self.capabilities.get(decision.capability)
        authorization = self.policy.authorize(decision, capability)
        if not authorization.allowed:
            updated = self.store.transition(
                continuation_id,
                worker_id=self.worker_id,
                expected_version=int(continuation["version"]),
                to_state=ContinuationState.BLOCKED,
                event_type="POLICY_BLOCKED",
                data={"decision": decision.as_dict(), "reason": authorization.reason},
                last_error=authorization.reason,
                now=now,
            )
            return TickResult(continuation_id, updated["state"], {"reason": authorization.reason})
        assert capability is not None

        idempotency_key = decision.idempotency_key or stable_id(
            "action",
            continuation_id,
            int(continuation["step_index"]),
            decision.fingerprint(),
            length=32,
        )
        executable = Decision(
            action=decision.action,
            rationale=decision.rationale,
            capability=decision.capability,
            arguments=decision.arguments,
            risk_tier=decision.risk_tier,
            verifier_id=decision.verifier_id,
            wait_until=decision.wait_until,
            terminal_on_pass=decision.terminal_on_pass,
            experience_key=decision.experience_key,
            experience_scope=decision.experience_scope,
            idempotency_key=idempotency_key,
        )
        decision_record, running, created = self.store.reserve_decision(
            continuation_id,
            worker_id=self.worker_id,
            expected_version=int(continuation["version"]),
            decision=executable,
            now=now,
        )
        if not created and decision_record["status"] == "VERIFIED":
            # A verified decision and a claimable continuation should be impossible
            # because verdict settlement is one transaction. Surface corruption
            # rather than executing the side effect again.
            raise RuntimeError(
                f"verified decision {decision_record['id']} is attached to claimable continuation {continuation_id}"
            )
        if not created and decision_record["status"] == "EXECUTED":
            capability_result = self._capability_result_from_record(decision_record)
            fresh_context = ContinuationContext.from_snapshot(self.store.snapshot(continuation_id))
            verification = self.verifier.verify(fresh_context, executable, capability_result)
            if not isinstance(verification, VerificationResult):
                raise TypeError(f"verifier returned {type(verification).__name__}, expected VerificationResult")
            return self._settle(
                continuation_id,
                decision_id=str(decision_record["id"]),
                continuation=running,
                decision=executable,
                verification=verification,
                now=now,
            )

        try:
            capability_result = capability.execute(executable.arguments, idempotency_key=idempotency_key)
            if not isinstance(capability_result, CapabilityResult):
                raise TypeError(
                    f"capability {capability.name!r} returned {type(capability_result).__name__}, expected CapabilityResult"
                )
        except Exception as exc:  # capability exceptions become verifier-visible ERROR observations
            capability_result = CapabilityResult(
                status="ERROR",
                observation={"exception_type": type(exc).__name__},
                error=str(exc),
            )

        _, verifying = self.store.record_execution(
            str(decision_record["id"]),
            worker_id=self.worker_id,
            expected_version=int(running["version"]),
            result=capability_result.as_dict(),
            now=now,
        )
        fresh_context = ContinuationContext.from_snapshot(self.store.snapshot(continuation_id))
        verification = self.verifier.verify(fresh_context, executable, capability_result)
        if not isinstance(verification, VerificationResult):
            raise TypeError(f"verifier returned {type(verification).__name__}, expected VerificationResult")
        return self._settle(
            continuation_id,
            decision_id=str(decision_record["id"]),
            continuation=verifying,
            decision=executable,
            verification=verification,
            now=now,
        )
