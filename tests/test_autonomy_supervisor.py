from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sisyfus.autonomy import (
    CapabilityResult, ContinuationState, Decision, DecisionAction, RiskTier, Verdict,
)
from autonomy_testkit import NOW, EchoCapability, build_supervisor, make_store, seed_continuation

def test_supervisor_executes_then_independent_verifier_finishes(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    continuation = seed_continuation(store)
    decision = Decision(
        action=DecisionAction.EXECUTE,
        rationale="Run the deterministic repair probe",
        capability="test.echo",
        arguments={"value": 7},
        risk_tier=RiskTier.R0,
        verifier_id="test-verifier",
        terminal_on_pass=True,
        experience_key="repair-probe",
        experience_scope={"project": "alpha"},
    )
    supervisor, capability, verifier = build_supervisor(store, decision=decision, verdict=Verdict.PASS)

    results = supervisor.tick(now=NOW)
    current = store.get_continuation(continuation["id"])
    snapshot = store.snapshot(continuation["id"])
    experiences = store.list_experiences()

    assert [item.status for item in results] == [ContinuationState.SUCCEEDED.value]
    assert current["state"] == ContinuationState.SUCCEEDED.value
    assert capability.calls == 1
    assert verifier.calls == 1
    assert snapshot["decisions"][0]["status"] == "VERIFIED"
    assert snapshot["evidence"][0]["verdict"] == Verdict.PASS.value
    assert experiences[0]["pattern_key"] == "repair-probe"
    assert experiences[0]["polarity"] == "positive"
    assert experiences[0]["evidence_ids"] == [snapshot["evidence"][0]["id"]]


def test_policy_blocks_unattended_high_risk_action_before_execution(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    continuation = seed_continuation(store)
    capability = EchoCapability(name="deployment.apply", risk_tier=RiskTier.R3)
    decision = Decision(
        action=DecisionAction.EXECUTE,
        rationale="Deploy directly",
        capability="deployment.apply",
        arguments={"environment": "prod"},
        risk_tier=RiskTier.R3,
    )
    supervisor, capability, verifier = build_supervisor(
        store, decision=decision, verdict=Verdict.PASS, capability=capability
    )

    result = supervisor.tick(now=NOW)[0]
    current = store.get_continuation(continuation["id"])

    assert result.status == ContinuationState.BLOCKED.value
    assert current["state"] == ContinuationState.BLOCKED.value
    assert capability.calls == 0
    assert verifier.calls == 0
    assert "explicitly denied" in str(result.detail["reason"])


def test_failed_verification_accumulates_negative_experience_and_stops_at_budget(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    continuation = seed_continuation(store, max_attempts=1)
    decision = Decision(
        action=DecisionAction.EXECUTE,
        rationale="Try one bounded experiment",
        capability="test.echo",
        arguments={"value": 0},
        risk_tier=RiskTier.R0,
        experience_key="bad-route",
        experience_scope={"environment": "test"},
    )
    supervisor, capability, _ = build_supervisor(store, decision=decision, verdict=Verdict.FAIL)

    result = supervisor.tick(now=NOW)[0]
    current = store.get_continuation(continuation["id"])
    experiences = store.list_experiences()

    assert result.status == ContinuationState.FAILED.value
    assert current["attempt_count"] == 1
    assert capability.calls == 1
    assert experiences[0]["pattern_key"] == "bad-route"
    assert experiences[0]["polarity"] == "negative"
    assert experiences[0]["supports"] == 1
    assert experiences[0]["counterexamples"] == 0


def test_capability_exception_is_observed_and_retried_not_stranded(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    continuation = seed_continuation(store, max_attempts=2)

    @dataclass
    class CrashingCapability:
        name: str = "test.echo"
        risk_tier: RiskTier = RiskTier.R0

        def execute(self, arguments: Mapping[str, Any], *, idempotency_key: str) -> CapabilityResult:
            raise RuntimeError("boom")

    decision = Decision(
        action=DecisionAction.EXECUTE,
        rationale="Exercise failure recovery",
        capability="test.echo",
        arguments={},
        risk_tier=RiskTier.R0,
        experience_key="capability-crash",
    )
    supervisor, _, _ = build_supervisor(
        store,
        decision=decision,
        verdict=Verdict.ERROR,
        capability=CrashingCapability(),  # type: ignore[arg-type]
    )

    result = supervisor.tick(now=NOW)[0]
    current = store.get_continuation(continuation["id"])
    snapshot = store.snapshot(continuation["id"])

    assert result.status == ContinuationState.WAITING.value
    assert current["lease_owner"] is None
    assert current["next_wake_at"] == "2026-08-20T00:00:05Z"
    assert snapshot["decisions"][0]["result"]["status"] == "ERROR"
    assert snapshot["evidence"][0]["verdict"] == Verdict.ERROR.value


def test_finish_request_cannot_self_certify_without_verifier_pass(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    continuation = seed_continuation(store)
    decision = Decision(action=DecisionAction.FINISH, rationale="Planner thinks the objective is complete")
    supervisor, _, verifier = build_supervisor(store, decision=decision, verdict=Verdict.INCONCLUSIVE)

    result = supervisor.tick(now=NOW)[0]
    current = store.get_continuation(continuation["id"])

    assert result.status == ContinuationState.WAITING.value
    assert current["state"] == ContinuationState.WAITING.value
    assert verifier.calls == 1
    snapshot = store.snapshot(continuation["id"])
    assert snapshot["decisions"][0]["action"] == DecisionAction.FINISH.value
    assert snapshot["evidence"][0]["verdict"] == Verdict.INCONCLUSIVE.value


def test_executed_decision_is_verified_after_worker_crash_without_reexecution(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    continuation = seed_continuation(store, max_attempts=2)
    decision = Decision(
        action=DecisionAction.EXECUTE,
        rationale="Use a stable external idempotency key",
        capability="test.echo",
        arguments={"value": 9},
        risk_tier=RiskTier.R0,
        terminal_on_pass=True,
        idempotency_key="stable-action-key",
    )

    claimed = store.claim_due_continuation("crashed-worker", lease_seconds=5, now=NOW)
    assert claimed is not None
    decision_record, running, created = store.reserve_decision(
        continuation["id"],
        worker_id="crashed-worker",
        expected_version=int(claimed["version"]),
        decision=decision,
        now=NOW,
    )
    assert created
    _, verifying = store.record_execution(
        decision_record["id"],
        worker_id="crashed-worker",
        expected_version=int(running["version"]),
        result=CapabilityResult(status="OK", metrics={"value": 9}).as_dict(),
        now=NOW,
    )
    assert verifying["state"] == ContinuationState.VERIFYING.value

    store.recover_expired_leases(now="2026-08-20T00:00:06Z", retry_delay_seconds=1)
    capability = EchoCapability()
    supervisor, capability, verifier = build_supervisor(
        store,
        decision=decision,
        verdict=Verdict.PASS,
        capability=capability,
    )
    result = supervisor.tick(now="2026-08-20T00:00:08Z")[0]

    assert result.status == ContinuationState.SUCCEEDED.value
    assert capability.calls == 0
    assert verifier.calls == 1
    assert len(store.snapshot(continuation["id"])["evidence"]) == 1
