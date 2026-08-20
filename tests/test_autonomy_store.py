from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from sisyfus.autonomy import AutonomyStore, ConcurrentUpdate, ContinuationState, OpportunityProposal
from autonomy_testkit import NOW, make_store, seed_continuation

def test_opportunity_dedupe_and_single_admission(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    proposal = OpportunityProposal(
        source="sensor",
        kind="metric_drop",
        payload={"metric": "fill_rate", "delta": -0.12},
        dedupe_key="metric_drop:fill_rate:2026-08-20",
        priority=50,
        confidence=0.8,
    )
    first, first_created = store.ingest_opportunity(proposal, now=NOW)
    second, second_created = store.ingest_opportunity(proposal, now=NOW)

    assert first_created is True
    assert second_created is False
    assert first["id"] == second["id"]

    continuation, admitted = store.admit_opportunity(first["id"], objective="Restore fill rate", now=NOW)
    duplicate, duplicate_admitted = store.admit_opportunity(first["id"], objective="Ignored duplicate", now=NOW)

    assert admitted is True
    assert duplicate_admitted is False
    assert duplicate["id"] == continuation["id"]
    assert duplicate["objective"] == "Restore fill rate"


def test_lease_allows_only_one_worker_and_rejects_stale_version(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    continuation = seed_continuation(store)

    claimed = store.claim_due_continuation("worker-a", lease_seconds=60, now=NOW)
    assert claimed is not None
    assert claimed["id"] == continuation["id"]
    assert store.claim_due_continuation("worker-b", lease_seconds=60, now=NOW) is None

    renewed = store.renew_lease(
        continuation["id"],
        "worker-a",
        expected_version=int(claimed["version"]),
        lease_seconds=120,
        now="2026-08-20T00:00:10Z",
    )
    with pytest.raises(ConcurrentUpdate):
        store.transition(
            continuation["id"],
            worker_id="worker-a",
            expected_version=int(claimed["version"]),
            to_state=ContinuationState.WAITING,
            event_type="STALE_WRITE",
            next_wake_at="2026-08-20T00:01:00Z",
            now="2026-08-20T00:00:11Z",
        )

    waited = store.transition(
        continuation["id"],
        worker_id="worker-a",
        expected_version=int(renewed["version"]),
        to_state=ContinuationState.WAITING,
        event_type="WAIT",
        next_wake_at="2026-08-20T00:01:00Z",
        now="2026-08-20T00:00:11Z",
    )
    assert waited["state"] == ContinuationState.WAITING.value
    assert waited["lease_owner"] is None


def test_expired_worker_lease_is_recovered(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    continuation = seed_continuation(store)
    claimed = store.claim_due_continuation("dead-worker", lease_seconds=5, now=NOW)
    assert claimed is not None

    recovered = store.recover_expired_leases(now="2026-08-20T00:00:06Z", retry_delay_seconds=4)
    current = store.get_continuation(continuation["id"])

    assert recovered == [continuation["id"]]
    assert current["state"] == ContinuationState.WAITING.value
    assert current["lease_owner"] is None
    assert current["next_wake_at"] == "2026-08-20T00:00:10Z"

def test_concurrent_supervisors_cannot_claim_same_continuation(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    continuation = seed_continuation(store)
    barrier = Barrier(2)

    def claim(worker: str) -> dict[str, Any] | None:
        local = AutonomyStore(store.path)
        barrier.wait()
        return local.claim_due_continuation(worker, lease_seconds=60, now=NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, ["worker-a", "worker-b"]))

    winners = [item for item in claims if item is not None]
    assert len(winners) == 1
    assert winners[0]["id"] == continuation["id"]
