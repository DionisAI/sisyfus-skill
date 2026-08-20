from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sisyfus.autonomy import (
    AutonomyStore,
    AutonomousRuntime,
    CapabilityRegistry,
    CapabilityResult,
    ContinuationState,
    Decision,
    OpportunitySignal,
    VerificationResult,
    Verdict,
)


NOW = "2026-08-20T00:00:00.000000Z"


def make_store(tmp_path: Path) -> AutonomyStore:
    return AutonomyStore(tmp_path / "autonomy.sqlite3")


def seed(store: AutonomyStore, *, key: str, max_attempts: int = 3):
    opportunity, _ = store.submit_opportunity(
        OpportunitySignal(
            source="test",
            title=key,
            objective=f"verify {key}",
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
class CountingCapability:
    name: str = "test.action"
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
class CountingVerifier:
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
            verdict=Verdict.PASS,
            verifier_id=self.verifier_id,
            summary="verified",
        )


def make_runtime(
    tmp_path: Path,
    store: AutonomyStore,
    capability: CountingCapability,
    verifier: CountingVerifier,
) -> AutonomousRuntime:
    registry = CapabilityRegistry()
    registry.register(capability, verifier)
    return AutonomousRuntime(
        store,
        registry,
        workspace=tmp_path / "workspace",
        retry_base_seconds=0,
        retry_max_seconds=0,
    )


def decision(*, replay_key: str = "action-key") -> Decision:
    return Decision(
        kind="EXECUTE",
        reason="persist and execute",
        capability="test.action",
        arguments={"value": 9},
        risk_tier=0,
        idempotency_key=replay_key,
        terminal_on_pass=True,
    )


def test_reserved_replay_safe_decision_resumes_without_planner(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    continuation = seed(store, key="reserved")
    claimed = store.claim_due_continuation("crashed", lease_seconds=5, now=NOW)
    assert claimed is not None
    record, _, created = store.reserve_decision(
        continuation["id"],
        worker_id="crashed",
        lease_token=claimed["lease_token"],
        expected_version=claimed["version"],
        decision=decision(),
        now=NOW,
    )
    assert created and record["status"] == "RESERVED"
    store.recover_expired_leases(
        now="2026-08-20T00:00:06.000000Z",
        retry_delay_seconds=0,
    )

    capability = CountingCapability(replay_safe=True)
    verifier = CountingVerifier()
    runtime = make_runtime(tmp_path, store, capability, verifier)

    def planner_must_not_run(_continuation, _context):
        raise AssertionError("planner must not replace a persisted decision")

    result = runtime.run_once(
        worker_id="recovery",
        planner=planner_must_not_run,
        lease_seconds=10,
        now="2026-08-20T00:00:07.000000Z",
    )
    assert result is not None
    assert result.state == ContinuationState.SUCCEEDED.value
    assert capability.calls == 1
    assert verifier.calls == 1


def test_reserved_non_replay_safe_decision_blocks_unknown_commit(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    continuation = seed(store, key="unknown")
    claimed = store.claim_due_continuation("crashed", lease_seconds=5, now=NOW)
    assert claimed is not None
    store.reserve_decision(
        continuation["id"],
        worker_id="crashed",
        lease_token=claimed["lease_token"],
        expected_version=claimed["version"],
        decision=decision(replay_key="unsafe-key"),
        now=NOW,
    )
    store.recover_expired_leases(
        now="2026-08-20T00:00:06.000000Z",
        retry_delay_seconds=0,
    )
    capability = CountingCapability(replay_safe=False)
    verifier = CountingVerifier()
    runtime = make_runtime(tmp_path, store, capability, verifier)
    result = runtime.run_once(
        worker_id="recovery",
        planner=lambda _c, _x: decision(),
        lease_seconds=10,
        now="2026-08-20T00:00:07.000000Z",
    )
    assert result is not None
    assert result.state == ContinuationState.BLOCKED.value
    assert capability.calls == 0
    assert verifier.calls == 0
    assert "may have committed externally" in result.detail["error"]


def test_executed_decision_resumes_verification_without_reexecution(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    continuation = seed(store, key="executed")
    claimed = store.claim_due_continuation("crashed", lease_seconds=5, now=NOW)
    assert claimed is not None
    record, running, _ = store.reserve_decision(
        continuation["id"],
        worker_id="crashed",
        lease_token=claimed["lease_token"],
        expected_version=claimed["version"],
        decision=decision(),
        now=NOW,
    )
    _, verifying = store.record_execution(
        record["id"],
        worker_id="crashed",
        lease_token=running["lease_token"],
        expected_version=running["version"],
        result=CapabilityResult(status="OK", metrics={"value": 9}).as_dict(),
        now=NOW,
    )
    assert verifying["state"] == "VERIFYING"
    store.recover_expired_leases(
        now="2026-08-20T00:00:06.000000Z",
        retry_delay_seconds=0,
    )
    capability = CountingCapability(replay_safe=False)
    verifier = CountingVerifier()
    runtime = make_runtime(tmp_path, store, capability, verifier)
    result = runtime.run_once(
        worker_id="recovery",
        planner=lambda _c, _x: (_ for _ in ()).throw(AssertionError("no planner")),
        lease_seconds=10,
        now="2026-08-20T00:00:07.000000Z",
    )
    assert result is not None
    assert result.state == ContinuationState.SUCCEEDED.value
    assert capability.calls == 0
    assert verifier.calls == 1


def test_heartbeat_prevents_second_worker_during_slow_capability(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    seed(store, key="slow")
    capability = CountingCapability(replay_safe=True, sleep_seconds=1.4)
    verifier = CountingVerifier()
    runtime = make_runtime(tmp_path, store, capability, verifier)
    result_box: list[Any] = []

    def run_first() -> None:
        result_box.append(
            runtime.run_once(
                worker_id="worker-a",
                planner=lambda _c, _x: decision(),
                lease_seconds=0.6,
            )
        )

    thread = threading.Thread(target=run_first)
    thread.start()
    time.sleep(0.9)
    store.recover_expired_leases()
    assert store.claim_due_continuation("worker-b", lease_seconds=1.0) is None
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert result_box[0].state == ContinuationState.SUCCEEDED.value
    assert capability.calls == 1
