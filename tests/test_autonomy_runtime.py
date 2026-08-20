from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sisyfus.autonomy import (
    AutonomyError,
    AutonomyStore,
    AutonomousRuntime,
    Capability,
    CapabilityRegistry,
    Decision,
    ExperienceLesson,
    IdempotencyConflictError,
    StaleVersionError,
    VerificationRequiredError,
    VerificationResult,
    register_safe_builtins,
)


def make_store(tmp_path: Path, *, threshold: int = 2) -> AutonomyStore:
    return AutonomyStore(tmp_path / "autonomy.sqlite3", experience_validation_threshold=threshold)


def make_continuation(store: AutonomyStore, *, max_attempts: int = 4):
    opportunity, _ = store.submit_opportunity(
        source="test",
        title="Investigate",
        objective="Produce verifier-backed evidence",
        payload={"x": 1},
        priority=1.0,
    )
    return store.admit_opportunity(opportunity["id"], max_attempts=max_attempts)


def lease(store: AutonomyStore, worker: str = "w1"):
    item = store.lease_next(worker, lease_seconds=60)
    assert item is not None
    return item


def make_runtime(tmp_path: Path, store: AutonomyStore | None = None):
    store = store or make_store(tmp_path)
    registry = CapabilityRegistry()
    register_safe_builtins(registry)
    runtime = AutonomousRuntime(store, registry, workspace=tmp_path / "workspace")
    return store, registry, runtime


def test_opportunity_dedupe_is_durable(tmp_path: Path):
    store = make_store(tmp_path)
    first, created_first = store.submit_opportunity(
        source="sensor", title="same", objective="same", payload={"a": 1}, dedupe_key="k"
    )
    second, created_second = store.submit_opportunity(
        source="sensor", title="same", objective="same", payload={"a": 1}, dedupe_key="k"
    )
    assert created_first is True
    assert created_second is False
    assert first["id"] == second["id"]
    assert second["occurrence_count"] == 2


def test_only_one_worker_wins_the_same_lease(tmp_path: Path):
    store = make_store(tmp_path)
    make_continuation(store)

    def acquire(worker: str):
        return store.lease_next(worker, lease_seconds=60)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(acquire, ["w1", "w2"]))
    winners = [item for item in results if item is not None]
    assert len(winners) == 1
    assert winners[0]["lease_owner"] in {"w1", "w2"}


def test_stale_version_cannot_mutate_continuation(tmp_path: Path):
    store = make_store(tmp_path)
    make_continuation(store)
    active = lease(store)
    store.renew_lease(active["id"], worker_id="w1", lease_token=active["lease_token"])
    store.apply_non_execution_decision(
        active["id"],
        worker_id="w1",
        lease_token=active["lease_token"],
        expected_version=active["version"],
        decision=Decision(kind="WAIT", wait_seconds=0),
    )
    with pytest.raises(StaleVersionError):
        store.apply_non_execution_decision(
            active["id"],
            worker_id="w1",
            lease_token=active["lease_token"],
            expected_version=active["version"],
            decision=Decision(kind="BLOCK", reason="stale"),
        )


def test_expired_lease_recovers_to_waiting(tmp_path: Path):
    store = make_store(tmp_path)
    make_continuation(store)
    active = store.lease_next("w1", lease_seconds=0, now="2026-01-01T00:00:00Z")
    assert active is not None
    recovered = store.recover_expired_leases(now="2026-01-01T00:00:01Z")
    assert len(recovered) == 1
    assert recovered[0]["status"] == "WAITING"
    assert recovered[0]["lease_token"] is None


def test_policy_blocks_r2_capability_without_running_it(tmp_path: Path):
    store, registry, runtime = make_runtime(tmp_path)
    make_continuation(store)
    calls = {"n": 0}

    def handler(_args, _ctx):
        calls["n"] += 1
        return {"ok": True}

    registry.register(
        Capability(
            name="external.send",
            risk_tier=2,
            handler=handler,
            verifier=lambda _a, _r, _c: VerificationResult("PASS", "ok"),
        )
    )
    result = runtime.run_once(
        worker_id="w1",
        planner=lambda _c, _ctx: Decision(
            kind="EXECUTE", capability="external.send", arguments={}, idempotency_key="send-1"
        ),
    )
    assert result is not None
    assert result["status"] == "BLOCKED"
    assert calls["n"] == 0


def test_idempotent_replay_does_not_repeat_side_effect(tmp_path: Path):
    store, registry, runtime = make_runtime(tmp_path)
    continuation = make_continuation(store)
    calls = {"n": 0}

    def handler(args, _ctx):
        calls["n"] += 1
        return {"value": args["value"]}

    registry.register(
        Capability(
            name="test.once",
            risk_tier=1,
            handler=handler,
            verifier=lambda a, r, _c: VerificationResult(
                "PASS" if a["value"] == r["value"] else "FAIL", "checked"
            ),
        )
    )
    active = lease(store)
    first = runtime.apply_decision(
        active,
        Decision(kind="EXECUTE", capability="test.once", arguments={"value": 3}, idempotency_key="once"),
        worker_id="w1",
    )
    assert first["evidence"]["verdict"] == "PASS"
    active2 = lease(store)
    second = runtime.apply_decision(
        active2,
        Decision(kind="EXECUTE", capability="test.once", arguments={"value": 3}, idempotency_key="once"),
        worker_id="w1",
    )
    assert second["cached"] is True
    assert calls["n"] == 1
    assert store.get_continuation(continuation["id"])["attempt_count"] == 1


def test_idempotency_key_rejects_different_request(tmp_path: Path):
    store, _registry, runtime = make_runtime(tmp_path)
    make_continuation(store)
    active = lease(store)
    runtime.apply_decision(
        active,
        Decision(kind="EXECUTE", capability="core.echo", arguments={"value": 1}, idempotency_key="same"),
        worker_id="w1",
    )
    active2 = lease(store)
    with pytest.raises(IdempotencyConflictError):
        runtime.apply_decision(
            active2,
            Decision(kind="EXECUTE", capability="core.echo", arguments={"value": 2}, idempotency_key="same"),
            worker_id="w1",
        )


def test_planner_cannot_finish_without_pass_evidence(tmp_path: Path):
    store, _registry, runtime = make_runtime(tmp_path)
    make_continuation(store)
    active = lease(store)
    with pytest.raises(VerificationRequiredError):
        store.apply_non_execution_decision(
            active["id"],
            worker_id="w1",
            lease_token=active["lease_token"],
            expected_version=active["version"],
            decision=Decision(kind="FINISH", evidence_id="ev_missing"),
        )

    store.apply_non_execution_decision(
        active["id"],
        worker_id="w1",
        lease_token=active["lease_token"],
        expected_version=active["version"],
        decision=Decision(kind="WAIT", wait_seconds=0),
    )
    active2 = lease(store)
    executed = runtime.apply_decision(
        active2,
        Decision(kind="EXECUTE", capability="core.echo", arguments={"value": "ok"}),
        worker_id="w1",
    )
    active3 = lease(store)
    finished = runtime.apply_decision(
        active3,
        Decision(kind="FINISH", evidence_id=executed["evidence"]["id"], reason="objective verified"),
        worker_id="w1",
    )
    assert finished["continuation"]["status"] == "SUCCEEDED"


def test_failed_verification_records_negative_experience(tmp_path: Path):
    store, registry, runtime = make_runtime(tmp_path)
    make_continuation(store)
    registry.register(
        Capability(
            name="test.bad",
            risk_tier=0,
            handler=lambda _a, _c: {"score": 0},
            verifier=lambda _a, _r, _c: VerificationResult(
                "FAIL",
                "score below threshold",
                lessons=(
                    ExperienceLesson(
                        statement="Zero-score candidate should be rejected",
                        polarity="negative",
                        scope={"domain": "test"},
                    ),
                ),
            ),
            replay_safe=True,
        )
    )
    active = lease(store)
    result = runtime.apply_decision(
        active,
        Decision(kind="EXECUTE", capability="test.bad", arguments={}),
        worker_id="w1",
    )
    assert result["evidence"]["verdict"] == "FAIL"
    assert result["experiences"][0]["negative_count"] == 1
    assert result["continuation"]["status"] == "WAITING"


def test_repeated_experience_validates_then_counterexample_contradicts(tmp_path: Path):
    store, _registry, runtime = make_runtime(tmp_path, store=make_store(tmp_path, threshold=2))
    make_continuation(store)
    active = lease(store)
    first = runtime.apply_decision(
        active,
        Decision(kind="EXECUTE", capability="core.echo", arguments={"value": 1}),
        worker_id="w1",
    )
    evidence_id = first["evidence"]["id"]
    lesson = ExperienceLesson(
        statement="Exact echo is stable in this environment",
        polarity="positive",
        scope={"environment": "unit"},
    )
    one = store.record_experience(lesson, evidence_id=evidence_id)
    two = store.record_experience(lesson, evidence_id=evidence_id)
    assert one["status"] == "CANDIDATE"
    assert two["status"] == "VALIDATED"
    contradicted = store.record_experience(
        ExperienceLesson(
            statement=lesson.statement,
            polarity="negative",
            scope=lesson.scope,
        ),
        evidence_id=evidence_id,
    )
    assert contradicted["status"] == "CONTRADICTED"


def test_event_chain_detects_database_tampering(tmp_path: Path):
    store = make_store(tmp_path)
    make_continuation(store)
    assert store.verify_event_chain()["valid"] is True
    with sqlite3.connect(store.path) as con:
        con.execute("UPDATE events SET data_json = '{\"tampered\":true}' WHERE seq = 1")
        con.commit()
    with pytest.raises(AutonomyError, match="event hash mismatch"):
        store.verify_event_chain()
