from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sisyfus.autonomy import (
    AutonomyError,
    AutonomyStore,
    ConcurrentUpdate,
    IncompatibleSchemaError,
    LeaseLost,
    OpportunitySignal,
)


NOW = "2026-08-20T00:00:00.000000Z"


def make_store(tmp_path: Path, *, threshold: int = 2) -> AutonomyStore:
    return AutonomyStore(
        tmp_path / "autonomy.sqlite3",
        experience_validation_threshold=threshold,
    )


def seed(store: AutonomyStore, *, max_attempts: int = 3):
    opportunity, created = store.submit_opportunity(
        OpportunitySignal(
            source="test",
            title="Investigate",
            objective="Produce verifier-backed evidence",
            dedupe_key="seed",
            priority=10,
            confidence=0.9,
        ),
        now=NOW,
    )
    assert created
    continuation, admitted = store.admit_opportunity(
        opportunity["id"],
        max_attempts=max_attempts,
        now=NOW,
    )
    assert admitted
    return continuation


def test_one_schema_rejects_legacy_database(tmp_path: Path) -> None:
    path = tmp_path / "autonomy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT)")
        connection.execute("CREATE TABLE opportunities(id TEXT PRIMARY KEY, title TEXT)")
    with pytest.raises(IncompatibleSchemaError, match="legacy autonomy schema"):
        AutonomyStore(path)
    backup = AutonomyStore.migrate_legacy(path)
    assert backup.exists()
    store = AutonomyStore(path)
    assert store.verify_event_chain()["valid"] is True


def test_opportunity_dedupe_and_single_admission(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    signal = OpportunitySignal(
        source="sensor",
        title="Metric drop",
        objective="Restore fill rate",
        payload={"metric": "fill_rate"},
        dedupe_key="fill-rate-drop",
        priority=20,
        confidence=0.8,
    )
    first, first_created = store.submit_opportunity(signal, now=NOW)
    second, second_created = store.submit_opportunity(signal, now=NOW)
    assert first_created is True
    assert second_created is False
    assert first["id"] == second["id"]
    assert second["occurrence_count"] == 2

    continuation, admitted = store.admit_opportunity(first["id"], now=NOW)
    duplicate, admitted_again = store.admit_opportunity(first["id"], now=NOW)
    assert admitted is True
    assert admitted_again is False
    assert continuation["id"] == duplicate["id"]


def test_only_one_worker_claims_and_expiry_is_enforced(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    continuation = seed(store)

    def claim(worker: str):
        local = AutonomyStore(store.path)
        return local.claim_due_continuation(worker, lease_seconds=10, now=NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["a", "b"]))
    winners = [item for item in results if item is not None]
    assert len(winners) == 1
    claimed = winners[0]
    assert claimed["id"] == continuation["id"]

    with pytest.raises(LeaseLost, match="lease expired"):
        store.apply_non_execution_decision(
            continuation["id"],
            worker_id=str(claimed["lease_owner"]),
            lease_token=str(claimed["lease_token"]),
            expected_version=int(claimed["version"]),
            decision=__import__("sisyfus.autonomy", fromlist=["Decision"]).Decision(
                kind="WAIT", reason="too late", wait_seconds=1
            ),
            now="2026-08-20T00:00:11.000000Z",
        )


def test_heartbeat_does_not_invalidate_logical_version(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    continuation = seed(store)
    claimed = store.claim_due_continuation("worker", lease_seconds=10, now=NOW)
    assert claimed is not None
    renewed = store.renew_lease(
        continuation["id"],
        worker_id="worker",
        lease_token=str(claimed["lease_token"]),
        lease_seconds=20,
        now="2026-08-20T00:00:01.000000Z",
    )
    assert renewed["version"] == claimed["version"]
    updated = store.apply_non_execution_decision(
        continuation["id"],
        worker_id="worker",
        lease_token=str(claimed["lease_token"]),
        expected_version=int(claimed["version"]),
        decision=__import__("sisyfus.autonomy", fromlist=["Decision"]).Decision(
            kind="WAIT", reason="pause", wait_seconds=1
        ),
        now="2026-08-20T00:00:02.000000Z",
    )
    assert updated["state"] == "WAITING"


def test_event_chain_detects_tampering(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    seed(store)
    assert store.verify_event_chain()["valid"] is True
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE events SET data_json='{\"tampered\":true}' WHERE seq=1")
    with pytest.raises(AutonomyError, match="event hash mismatch"):
        store.verify_event_chain()
