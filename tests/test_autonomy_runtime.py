from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pytest

from sisyfus.autonomy import (
    AutonomyPolicy,
    AutonomyStore,
    AutonomousRuntime,
    CapabilityRegistry,
    CapabilityResult,
    ContinuationState,
    Decision,
    ExperienceLesson,
    ExperiencePolarity,
    OpportunitySignal,
    VerificationResult,
    Verdict,
    register_safe_builtins,
)


NOW = "2026-08-20T00:00:00.000000Z"


def make_store(tmp_path: Path, *, threshold: int = 2) -> AutonomyStore:
    return AutonomyStore(
        tmp_path / "autonomy.sqlite3",
        experience_validation_threshold=threshold,
    )


def seed(store: AutonomyStore, *, key: str = "seed", max_attempts: int = 3):
    opportunity, _ = store.submit_opportunity(
        OpportunitySignal(
            source="test",
            title=key,
            objective=f"Verify {key}",
            dedupe_key=key,
            priority=10,
            confidence=0.9,
        ),
        now=NOW,
    )
    continuation, _ = store.admit_opportunity(
        opportunity["id"], max_attempts=max_attempts, now=NOW
    )
    return continuation


@dataclass
class StaticCapability:
    name: str = "test.static"
    risk_tier: int = 0
    replay_safe: bool = True
    description: str = "test"
    calls: int = 0
    sleep_seconds: float = 0.0

    def execute(self, arguments: Mapping[str, Any], *, idempotency_key: str) -> CapabilityResult:
        self.calls += 1
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        return CapabilityResult(
            status="OK",
            observation={"idempotency_key": idempotency_key},
            metrics={"value": arguments.get("value")},
        )


@dataclass
class StaticVerifier:
    verdict: Verdict
    verifier_id: str = "test-verifier"
    calls: int = 0

    def verify(
        self,
        _context: Mapping[str, Any],
        _decision: Decision,
        _result: CapabilityResult,
    ) -> VerificationResult:
        self.calls += 1
        return VerificationResult(
            verdict=self.verdict,
            verifier_id=self.verifier_id,
            summary=f"verdict {self.verdict.value}",
            metrics={"ok": self.verdict == Verdict.PASS},
        )


def make_runtime(
    tmp_path: Path,
    store: AutonomyStore,
    *,
    capability: StaticCapability | None = None,
    verifier: StaticVerifier | None = None,
    policy: AutonomyPolicy | None = None,
):
    registry = CapabilityRegistry()
    capability = capability or StaticCapability()
    verifier = verifier or StaticVerifier(Verdict.PASS)
    registry.register(capability, verifier)
    runtime = AutonomousRuntime(
        store,
        registry,
        workspace=tmp_path / "workspace",
        policy=policy,
        retry_base_seconds=0,
        retry_max_seconds=0,
    )
    return runtime, capability, verifier


def test_policy_blocks_high_risk_before_execution(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    seed(store)
    capability = StaticCapability(name="deployment.apply", risk_tier=3)
    verifier = StaticVerifier(Verdict.PASS)
    runtime, capability, verifier = make_runtime(
        tmp_path, store, capability=capability, verifier=verifier
    )

    result = runtime.run_once(
        worker_id="w1",
        planner=lambda _continuation, _context: Decision(
            kind="EXECUTE",
            reason="deploy",
            capability="deployment.apply",
            arguments={},
            risk_tier=3,
            idempotency_key="deploy-1",
        ),
        lease_seconds=10,
    )
    assert result is not None
    assert result.state == ContinuationState.BLOCKED.value
    assert capability.calls == 0
    assert verifier.calls == 0


def test_pass_on_final_attempt_remains_claimable_for_finish(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    continuation = seed(store, max_attempts=1)
    runtime, capability, verifier = make_runtime(tmp_path, store)

    first = runtime.run_once(
        worker_id="w1",
        planner=lambda _continuation, _context: Decision(
            kind="EXECUTE",
            reason="run final experiment",
            capability="test.static",
            arguments={"value": 7},
            risk_tier=0,
            idempotency_key="final-experiment",
        ),
        lease_seconds=10,
    )
    assert first is not None
    assert first.state == ContinuationState.READY.value
    current = store.get_continuation(continuation["id"])
    assert current["attempt_count"] == current["max_attempts"] == 1
    evidence = store.latest_evidence(continuation["id"])
    assert evidence is not None and evidence["verdict"] == "PASS"

    second = runtime.run_once(
        worker_id="w2",
        planner=lambda _continuation, _context: Decision(
            kind="FINISH",
            reason="PASS evidence satisfies the objective",
            evidence_id=evidence["id"],
        ),
        lease_seconds=10,
    )
    assert second is not None
    assert second.state == ContinuationState.SUCCEEDED.value
    assert capability.calls == 1
    assert verifier.calls == 1


def test_inconclusive_final_attempt_becomes_exhausted(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    seed(store, max_attempts=1)
    runtime, _, _ = make_runtime(
        tmp_path,
        store,
        verifier=StaticVerifier(Verdict.INCONCLUSIVE),
    )
    result = runtime.run_once(
        worker_id="w1",
        planner=lambda _continuation, _context: Decision(
            kind="EXECUTE",
            reason="measure",
            capability="test.static",
            arguments={},
            risk_tier=0,
            idempotency_key="one-shot",
        ),
        lease_seconds=10,
    )
    assert result is not None
    assert result.state == ContinuationState.EXHAUSTED.value
    assert store.claim_due_continuation("w2", lease_seconds=10) is None


def test_duplicate_evidence_cannot_validate_experience(tmp_path: Path) -> None:
    store = make_store(tmp_path, threshold=2)
    continuation = seed(store)
    runtime, _, _ = make_runtime(tmp_path, store)
    result = runtime.run_once(
        worker_id="w1",
        planner=lambda _continuation, _context: Decision(
            kind="EXECUTE",
            reason="produce evidence",
            capability="test.static",
            arguments={},
            risk_tier=0,
            idempotency_key="evidence-one",
        ),
        lease_seconds=10,
    )
    assert result is not None
    evidence = store.latest_evidence(continuation["id"])
    assert evidence is not None
    lesson = ExperienceLesson(
        pattern_key="route-rule",
        polarity=ExperiencePolarity.POSITIVE,
        claim="Route is stable",
        scope={"venue": "alpha"},
    )
    first = store.record_experience(lesson, evidence_id=evidence["id"])
    duplicate = store.record_experience(lesson, evidence_id=evidence["id"])
    assert first["supports"] == 1
    assert duplicate["supports"] == 1
    assert duplicate["status"] == "candidate"
    assert duplicate["observation_inserted"] is False


def test_two_independent_evidence_validate_then_counterexample_contests(tmp_path: Path) -> None:
    store = make_store(tmp_path, threshold=2)
    lesson = ExperienceLesson(
        pattern_key="route-rule",
        polarity="positive",
        claim="Route is stable",
        scope={"venue": "alpha"},
    )
    evidence_ids: list[str] = []
    for index in range(2):
        continuation = seed(store, key=f"positive-{index}")
        runtime, _, _ = make_runtime(tmp_path / f"r{index}", store)
        runtime.run_once(
            worker_id=f"w{index}",
            planner=lambda _c, _x, index=index: Decision(
                kind="EXECUTE",
                reason="support",
                capability="test.static",
                arguments={"value": index},
                risk_tier=0,
                idempotency_key=f"support-{index}",
            ),
            lease_seconds=10,
        )
        evidence = store.latest_evidence(continuation["id"])
        assert evidence is not None
        evidence_ids.append(evidence["id"])
        current = store.record_experience(lesson, evidence_id=evidence["id"])
    assert current["status"] == "validated"
    assert current["supports"] == 2

    negative_continuation = seed(store, key="negative")
    runtime, _, _ = make_runtime(
        tmp_path / "negative-runtime",
        store,
        verifier=StaticVerifier(Verdict.FAIL),
    )
    runtime.run_once(
        worker_id="wn",
        planner=lambda _c, _x: Decision(
            kind="EXECUTE",
            reason="counterexample",
            capability="test.static",
            arguments={},
            risk_tier=0,
            idempotency_key="counterexample",
        ),
        lease_seconds=10,
    )
    negative_evidence = store.latest_evidence(negative_continuation["id"])
    assert negative_evidence is not None
    contested = store.record_experience(
        ExperienceLesson(
            pattern_key="route-rule",
            polarity="positive",
            claim="Route failed in a matched context",
            scope={"venue": "alpha"},
            outcome="counterexample",
        ),
        evidence_id=negative_evidence["id"],
    )
    assert contested["status"] == "contested"
    assert contested["counterexamples"] == 1
