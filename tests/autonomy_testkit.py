from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sisyfus.autonomy import (
    AutonomyPolicy, AutonomyStore, CapabilityRegistry, CapabilityResult, Decision,
    OpportunityProposal, RiskTier, Supervisor, Verdict, VerificationResult,
)

NOW = "2026-08-20T00:00:00Z"


def make_store(tmp_path: Path) -> AutonomyStore:
    return AutonomyStore(tmp_path / "autonomy.sqlite3")


def seed_continuation(store: AutonomyStore, *, max_attempts: int = 3, priority: int = 10) -> dict[str, Any]:
    opportunity, created = store.ingest_opportunity(
        OpportunityProposal(
            source="test-sensor", kind="regression", payload={"target": "alpha"},
            dedupe_key="regression:alpha", priority=priority, confidence=0.9,
        ),
        now=NOW,
    )
    assert created
    continuation, admitted = store.admit_opportunity(
        opportunity["id"], objective="Repair the alpha regression",
        max_attempts=max_attempts, now=NOW,
    )
    assert admitted
    return continuation


@dataclass
class StaticPlanner:
    decision: Decision

    def decide(self, context: Any) -> Decision:
        return self.decision


@dataclass
class StaticVerifier:
    verdict: Verdict
    calls: int = 0

    def verify(self, context: Any, decision: Decision, result: CapabilityResult) -> VerificationResult:
        self.calls += 1
        return VerificationResult(
            verdict=self.verdict, verifier_id="test-verifier",
            summary=f"deterministic verdict: {self.verdict.value}",
            metrics={"ok": self.verdict == Verdict.PASS},
            evidence={"capability_status": result.status},
        )


@dataclass
class EchoCapability:
    name: str = "test.echo"
    risk_tier: RiskTier = RiskTier.R0
    calls: int = 0

    def execute(self, arguments: Mapping[str, Any], *, idempotency_key: str) -> CapabilityResult:
        self.calls += 1
        return CapabilityResult(
            status="OK", observation={"echo": dict(arguments), "idempotency_key": idempotency_key},
            metrics={"value": arguments.get("value")},
        )


def build_supervisor(
    store: AutonomyStore, *, decision: Decision, verdict: Verdict,
    capability: EchoCapability | None = None, policy: AutonomyPolicy | None = None,
) -> tuple[Supervisor, EchoCapability, StaticVerifier]:
    registry = CapabilityRegistry()
    capability = capability or EchoCapability()
    registry.register(capability)
    verifier = StaticVerifier(verdict)
    supervisor = Supervisor(
        store=store, planner=StaticPlanner(decision), verifier=verifier, capabilities=registry,
        policy=policy or AutonomyPolicy(), worker_id="worker-1", lease_seconds=60,
        retry_base_seconds=5, retry_max_seconds=60,
    )
    return supervisor, capability, verifier
