from __future__ import annotations

from typing import Any, Mapping

from .models import CapabilityResult, Decision, TickResult, VerificationResult, stable_id
from .policy import ContinuationContext


class FinishMixin:
    def _persist_and_verify_finish(
        self,
        context: ContinuationContext,
        continuation: Mapping[str, Any],
        decision: Decision,
        *,
        now: str,
    ) -> TickResult:
        continuation_id = str(continuation["id"])
        idempotency_key = decision.idempotency_key or stable_id(
            "finish", continuation_id, int(continuation["step_index"]), decision.fingerprint(), length=32
        )
        persisted = Decision(
            action=decision.action,
            rationale=decision.rationale,
            risk_tier=decision.risk_tier,
            verifier_id=decision.verifier_id,
            terminal_on_pass=True,
            experience_key=decision.experience_key,
            experience_scope=decision.experience_scope,
            idempotency_key=idempotency_key,
        )
        decision_record, running, created = self.store.reserve_decision(
            continuation_id,
            worker_id=self.worker_id,
            expected_version=int(continuation["version"]),
            decision=persisted,
            now=now,
        )
        if not created and decision_record["status"] == "VERIFIED":
            raise RuntimeError(
                f"verified finish decision {decision_record['id']} is attached to claimable continuation {continuation_id}"
            )
        if not created and decision_record["status"] == "EXECUTED":
            synthetic = self._capability_result_from_record(decision_record)
            verifying = running
        else:
            synthetic = CapabilityResult(
                status="FINISH_REQUESTED",
                observation={"rationale": decision.rationale},
            )
            _, verifying = self.store.record_execution(
                str(decision_record["id"]),
                worker_id=self.worker_id,
                expected_version=int(running["version"]),
                result=synthetic.as_dict(),
                now=now,
            )
        fresh_context = ContinuationContext.from_snapshot(self.store.snapshot(continuation_id))
        verification = self.verifier.verify(fresh_context, persisted, synthetic)
        if not isinstance(verification, VerificationResult):
            raise TypeError(f"verifier returned {type(verification).__name__}, expected VerificationResult")
        return self._settle(
            continuation_id,
            decision_id=str(decision_record["id"]),
            continuation=verifying,
            decision=persisted,
            verification=verification,
            now=now,
        )

    @staticmethod
    def _capability_result_from_record(decision_record: Mapping[str, Any]) -> CapabilityResult:
        raw = dict(decision_record.get("result") or {})
        artifacts = tuple(dict(item) for item in raw.get("artifacts") or [])
        return CapabilityResult(
            status=str(raw.get("status") or "UNKNOWN"),
            observation=dict(raw.get("observation") or {}),
            metrics=dict(raw.get("metrics") or {}),
            artifacts=artifacts,
            error=str(raw.get("error")) if raw.get("error") is not None else None,
        )

