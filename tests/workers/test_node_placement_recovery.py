"""Frozen REQUESTED-gap recovery fixtures. No sockets or native execution."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from sisyfus.autonomy.policy import IdempotencyConflictError
from sisyfus.workers.lead_console import MissionHub
from sisyfus.workers.lead_mission import LeadMission
from sisyfus.workers.protocol import digest
from test_lead_mission import Stub, make_spec, mission

OLD = 'prepare_recovery_old_001'
NEW = 'prepare_recovery_new_002'


def factory(directory, spec=None):
    m = LeadMission(directory, spec)
    def forbidden(*args):
        pytest.fail('recovery dispatched Sol')
    m.drivers = {'claude': Stub('claude'), 'codex': Stub('codex', forbidden)}
    return m


def current(m):
    return m.snapshot()['placement_preparation']


def archived(m):
    old = m.journal.get('placement_preparation_history', OLD)
    assert old['status'] == 'SUPERSEDED'
    assert old['known_nonexecuted'] is True
    assert old['request_id'] == OLD
    assert current(m)['previous_request_id'] == OLD
    return old


def settled(h, ident):
    thread = h._session(ident).thread
    assert thread is not None
    thread.join(5)
    assert not thread.is_alive()
    return h.snapshot(ident)


def test_crash_after_hub_record_exact_retry_readonly_fresh_request_recovers(tmp_path, monkeypatch):
    h = MissionHub(tmp_path/'hub', mission_factory=factory)
    ident = h.create(make_spec(tmp_path, initial=False))['id']
    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, 'start', lambda self: None)
        first = h.prepare_placement(ident, OLD, allow_planning=True)
    assert current(h._session(ident).mission)['status'] == 'REQUESTED'
    restarted = MissionHub(tmp_path/'hub', mission_factory=factory)
    try:
        m = restarted._session(ident).mission
        before = m.store.verify_event_chain()
        assert restarted.prepare_placement(ident, OLD, allow_planning=True) == first
        assert restarted._session(ident).thread is None
        assert m.store.verify_event_chain() == before
        assert m.run(max_cycles=1)['placement_preparation']['status'] == 'REQUESTED'
        assert not any(d.requests for d in m.drivers.values())
        assert restarted.prepare_placement(ident, NEW, allow_planning=True)['status'] == 'ACK'
        assert settled(restarted, ident)['snapshot']['phase'] == 'WAITING_PLACEMENT'
        archived(m)
        assert len(m.drivers['claude'].requests) == 1
        assert not m.drivers['codex'].requests
    finally:
        restarted.close()
        h.close()


def test_cross_hub_start_wins_file_lock_then_explicit_fresh_request_recovers(tmp_path, monkeypatch):
    h = MissionHub(tmp_path/'hub', mission_factory=factory)
    ident = h.create(make_spec(tmp_path, initial=False))['id']
    other = MissionHub(tmp_path/'hub', mission_factory=factory)
    m = h._session(ident).mission
    b = other._session(ident).mission
    ready, attempt, start_locked, release = (threading.Event() for _ in range(4))
    original_prepare = m.prepare_for_placement
    def delayed(request_id):
        ready.set()
        assert attempt.wait(5)
        return original_prepare(request_id)
    original_read = b._placement_preparation
    def read_with_start_lock():
        start_locked.set()
        assert release.wait(5)
        return original_read()
    monkeypatch.setattr(m, 'prepare_for_placement', delayed)
    monkeypatch.setattr(b, '_placement_preparation', read_with_start_lock)
    try:
        h.prepare_placement(ident, OLD, allow_planning=True)
        assert ready.wait(5)
        with ThreadPoolExecutor(max_workers=1) as pool:
            start = pool.submit(b.run, 1)
            try:
                assert start_locked.wait(5)
                attempt.set()
                settled(h, ident)
                assert h._session(ident).error is not None
                assert current(m)['status'] == 'REQUESTED'
            finally:
                release.set()
            assert start.result(5)['placement_preparation']['status'] == 'REQUESTED'
        monkeypatch.setattr(m, 'prepare_for_placement', original_prepare)
        assert h.prepare_placement(ident, NEW, allow_planning=True)['status'] == 'ACK'
        assert settled(h, ident)['snapshot']['phase'] == 'WAITING_PLACEMENT'
        archived(m)
        assert len(m.drivers['claude'].requests) == 1
        assert not any(d.requests for d in b.drivers.values())
    finally:
        release.set()
        attempt.set()
        h.close()
        other.close()


@pytest.mark.parametrize('status', ['REQUESTED', 'BLOCKED'])
@pytest.mark.parametrize('complete_new', [False, True])
def test_stale_old_thread_never_continues_or_mutates_new_record(tmp_path, status, complete_new):
    m = mission(tmp_path, make_spec(tmp_path, initial=False))
    old = m._request_placement_preparation(OLD)
    if status == 'BLOCKED':
        m._save_placement_preparation({**old, 'status': status, 'reason': 'fixture preflight'})
    m._request_placement_preparation(NEW)
    if complete_new:
        m.prepare_for_placement(NEW)
    archive = archived(m)
    pins = digest(current(m)), digest(m.continuations()), m.store.verify_event_chain()
    restarted = mission(tmp_path, None)
    result = restarted.prepare_for_placement(OLD)
    assert result['placement_preparation'] == archive
    assert pins == (digest(current(m)), digest(m.continuations()), m.store.verify_event_chain())
    assert not any(d.requests for d in restarted.drivers.values())
    assert len(m.drivers['claude'].requests) == int(complete_new)
    assert not m.drivers['codex'].requests


def test_exact_requested_reservation_duplicate_readonly_and_start_does_not_retry(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path, initial=False))
    old = m._request_placement_preparation(OLD)
    before = m.store.verify_event_chain()
    assert m._request_placement_preparation(OLD) == old
    restarted = mission(tmp_path, None)
    assert restarted._request_placement_preparation(OLD) == old
    assert restarted.run(max_cycles=1)['placement_preparation'] == old
    assert restarted.store.verify_event_chain() == before
    assert not any(d.requests for d in restarted.drivers.values())


@pytest.mark.parametrize('status', ['PLANNING', 'UNKNOWN', 'ERROR', 'REQUESTED'])
def test_uncertain_or_native_started_record_never_superseded(tmp_path, status):
    m = mission(tmp_path, make_spec(tmp_path, initial=False))
    old = m._request_placement_preparation(OLD)
    m._save_placement_preparation({**old, 'status': status, 'known_nonexecuted': False})
    with pytest.raises(IdempotencyConflictError):
        m.prepare_for_placement(NEW)
    saved = current(m)
    assert saved['request_id'] == OLD
    assert saved['status'] == ('UNKNOWN' if status == 'PLANNING' else status)
    assert m.journal.get('placement_preparation_history', OLD) is None
    assert not any(d.requests for d in m.drivers.values())


def test_fixed_initial_plan_recovery_preserves_immutable_checks_and_continuations(tmp_path, monkeypatch):
    m = mission(tmp_path, make_spec(tmp_path, two=True))
    frozen = digest(m.spec)
    m._request_placement_preparation(OLD)
    def forbidden(*args, **kwargs):
        pytest.fail('fixed plan recovery invoked a native or execution boundary')
    for d in m.drivers.values():
        monkeypatch.setattr(d, 'probe', forbidden)
        monkeypatch.setattr(d, 'run', forbidden)
    for name in ('planner', 'diagnose', '_diagnose_boundary', '_admit_integration',
                 '_procedure_trial_boundary', 'build_candidate'):
        monkeypatch.setattr(m, name, forbidden)
    result = m.prepare_for_placement(NEW)
    assert result['phase'] == 'WAITING_PLACEMENT'
    saved = current(m)
    assert saved['task_hashes'] == {t['id']: digest(t) for t in m.active_tasks()}
    assert set(m.continuations()) == set(saved['task_hashes'])
    assert digest(m.spec) == frozen and not m.journal.runs()
    archived(m)
    pins = digest(saved), digest(m.continuations()), m.store.verify_event_chain()
    assert m.prepare_for_placement(NEW)['placement_preparation'] == saved
    assert pins == (digest(current(m)), digest(m.continuations()), m.store.verify_event_chain())
    assert m.store.verify_event_chain()['valid']
