"""Frozen explicit planning boundary: retained protocol fixtures, no native calls.

This suite is frozen and RED is retained before changing either implementation.
Preparation never grants execution, approval, review, trial or integration.
"""
from __future__ import annotations

import fcntl
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from sisyfus.autonomy.policy import IdempotencyConflictError
from sisyfus.workers.journal import DispatchBlocked
from sisyfus.workers.protocol import Receipt, digest
from test_lead_mission import make_spec, mission


def no_execution(m, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('preparation entered execution/verification/review/trial')
    for name in ('planner', 'diagnose', '_diagnose_boundary', '_admit_integration',
                 '_procedure_trial_boundary', 'build_candidate'):
        monkeypatch.setattr(m, name, forbidden)
    for entry in ('workers.execute', 'workers.integrate'):
        monkeypatch.setattr(m.registry.get(entry).capability, 'execute', forbidden)
    monkeypatch.setattr(m.drivers['codex'], 'probe', forbidden)
    monkeypatch.setattr(m.drivers['codex'], 'run', forbidden)


def record(m):
    return m.snapshot()['placement_preparation']


def assert_prepared(m, result):
    assert result['phase'] == 'WAITING_PLACEMENT'
    saved = result['placement_preparation']
    assert saved['status'] == 'WAITING_PLACEMENT'
    assert saved['acceptance_hash'] == m.spec['acceptance_hash']
    assert saved['revision'] == result['revision'] == 1
    assert saved['task_hashes'] == {t['id']: digest(t) for t in m.active_tasks()}
    assert isinstance(saved['plan_hash'], str) and len(saved['plan_hash']) == 64
    assert set(m.continuations()) == set(saved['task_hashes'])
    assert all(c['context']['task_hash'] == saved['task_hashes'][t]
               for t, c in m.continuations().items())
    assert not any(r['role'] != 'lead' for r in m.journal.runs())
    assert not m.drivers['codex'].requests
    assert not result['reviews'] and result['integration']['continuation'] is None
    assert result['procedure_trials']['status'] == 'IDLE'
    assert not result['all_verified'] and m.store.verify_event_chain()['valid']
    return saved


def test_initial_plan_preparation_zero_native_and_frozen_acceptance(tmp_path, monkeypatch):
    m = mission(tmp_path, make_spec(tmp_path, two=True))
    frozen = digest(m.spec)
    no_execution(m, monkeypatch)
    monkeypatch.setattr(m.drivers['claude'], 'probe', lambda: pytest.fail('initial plan needs no doctor'))
    saved = assert_prepared(m, m.prepare_for_placement('prepare_initial_0001'))
    assert saved['request_id'] == 'prepare_initial_0001'
    assert digest(m.spec) == frozen and not m.journal.runs()


def test_native_lead_only_preflight_durable_before_dispatch(tmp_path, monkeypatch):
    def lead(request, *args):
        saved = record(m)
        assert saved['request_id'] == 'prepare_native_0001'
        assert saved['status'] == 'PLANNING'
        assert m.journal.runs()[0]['status'] == 'IN_FLIGHT'
        assert request.model == 'claude-opus-5-5' and request.mode == 'read-only'
    m = mission(tmp_path, make_spec(tmp_path, initial=False), claude=lead)
    frozen = digest(m.spec)
    no_execution(m, monkeypatch)
    assert_prepared(m, m.prepare_for_placement('prepare_native_0001'))
    assert len(m.drivers['claude'].requests) == 1 and digest(m.spec) == frozen


def test_exact_replay_restart_and_conflict_do_not_replan(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path, initial=False))
    original = assert_prepared(m, m.prepare_for_placement('prepare_replay_0001'))
    before = m.store.verify_event_chain()
    assert record(m) == original
    assert m.prepare_for_placement('prepare_replay_0001')['placement_preparation'] == original
    restarted = mission(tmp_path, None)
    assert restarted.prepare_for_placement('prepare_replay_0001')['placement_preparation'] == original
    assert not any(d.requests for d in restarted.drivers.values())
    assert restarted.store.verify_event_chain() == before
    with pytest.raises(IdempotencyConflictError):
        restarted.prepare_for_placement('prepare_conflict_0002')


@pytest.mark.parametrize('failure', ['unknown', 'interrupt'])
def test_unknown_and_interrupted_native_are_never_resent(tmp_path, failure):
    def lead(*args):
        if failure == 'interrupt':
            raise KeyboardInterrupt('synthetic controller interruption')
        return Receipt('UNKNOWN', error='fixture transport unknown')
    m = mission(tmp_path, make_spec(tmp_path, initial=False), claude=lead)
    if failure == 'interrupt':
        with pytest.raises(KeyboardInterrupt):
            m.prepare_for_placement('prepare_unknown_0001')
    else:
        m.prepare_for_placement('prepare_unknown_0001')
    assert len(m.drivers['claude'].requests) == 1
    restarted = mission(tmp_path, None)
    result = restarted.prepare_for_placement('prepare_unknown_0001')
    assert result['phase'] == 'UNKNOWN'
    assert result['placement_preparation']['status'] == 'UNKNOWN'
    assert not any(d.requests for d in restarted.drivers.values())
    with pytest.raises(IdempotencyConflictError):
        restarted.prepare_for_placement('prepare_unknown_0002')
    restarted.run(max_cycles=1)
    assert not any(d.requests for d in restarted.drivers.values())


def test_known_nonexecuted_preflight_requires_new_explicit_request(tmp_path, monkeypatch):
    m = mission(tmp_path, make_spec(tmp_path, initial=False))
    monkeypatch.setattr(m.drivers['claude'], 'probe', lambda: {'available': False})
    first = m.prepare_for_placement('prepare_preflight_0001')
    assert first['placement_preparation']['status'] == 'BLOCKED'
    assert not m.journal.runs()
    monkeypatch.setattr(m.drivers['claude'], 'probe', lambda: {'available': True})
    assert m.prepare_for_placement('prepare_preflight_0001')['placement_preparation'] == first['placement_preparation']
    assert not m.drivers['claude'].requests
    assert_prepared(m, m.prepare_for_placement('prepare_preflight_0002'))
    events = str(m.journal.events())
    assert 'prepare_preflight_0001' in events and 'prepare_preflight_0002' in events


@pytest.mark.parametrize('control', ['stop', 'pause'])
def test_preparation_preserves_operator_stop_and_pause(tmp_path, control):
    m = mission(tmp_path, make_spec(tmp_path, initial=False))
    if control == 'stop':
        m.request_stop()
    else:
        m.journal.pause(True)
    result = m.prepare_for_placement('prepare_control_0001')
    assert result['phase'] == {'stop': 'STOPPED', 'pause': 'PAUSED'}[control]
    assert not any(d.requests for d in m.drivers.values()) and not m.journal.runs()


@pytest.mark.parametrize('marker', ['techlead:inbox_policy:trial-child', 'techlead:learning_config:trial'])
def test_trial_children_do_not_gain_preparation_permission(tmp_path, marker):
    m = mission(tmp_path, make_spec(tmp_path))
    with m.store._transaction() as db:
        db.execute('INSERT INTO metadata VALUES(?,?)', (marker, '{}'))
    with pytest.raises(PermissionError, match='trial'):
        m.prepare_for_placement('prepare_trial_0001')
    assert 'placement_preparation' not in m.snapshot() and not m.journal.runs()


@pytest.mark.parametrize('request_id', [None, True, [], 'short', 'a' * 101, '../prepare_0001'])
def test_request_identity_validated_without_metadata_backfill(tmp_path, request_id):
    m = mission(tmp_path, make_spec(tmp_path))
    with pytest.raises(ValueError):
        m.prepare_for_placement(request_id)
    assert 'placement_preparation' not in m.snapshot()


def test_default_snapshot_restart_and_readonly_btw_do_not_prepare(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path))
    before = m.store.verify_event_chain()
    assert 'placement_preparation' not in m.snapshot()
    m.inbox.submit('/btw', 'readonly_btw_0001', snapshot=m.snapshot(), controller={})
    restarted = mission(tmp_path, None)
    assert 'placement_preparation' not in restarted.snapshot()
    assert not any(d.requests for d in restarted.drivers.values())
    with m.store._transaction(immediate=False) as db:
        assert not db.execute("SELECT 1 FROM metadata WHERE key LIKE '%placement_preparation%'").fetchone()
    assert before['valid'] and restarted.store.verify_event_chain()['valid']


def test_prepare_and_start_share_both_controller_locks(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def lead(*args):
        entered.set()
        assert release.wait(5)
    m = mission(tmp_path, make_spec(tmp_path, initial=False), claude=lead)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(m.prepare_for_placement, 'prepare_race_0001')
        try:
            assert entered.wait(5)
            with pytest.raises(DispatchBlocked):
                m.run(max_cycles=1)
            other = mission(tmp_path, None)
            with pytest.raises(DispatchBlocked):
                other.run(max_cycles=1)
            with pytest.raises(DispatchBlocked):
                other.prepare_for_placement('prepare_race_0001')
        finally:
            release.set()
        assert_prepared(m, pending.result(5))
    assert not m.drivers['codex'].requests


def test_existing_file_controller_owner_rejects_preparation(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path))
    with (m.directory / 'lead-controller.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(DispatchBlocked):
            m.prepare_for_placement('prepare_lock_0001')
    assert 'placement_preparation' not in m.snapshot()


def test_assign_before_admission_rejected_then_same_pinned_tasks_start(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def lead(*args):
        entered.set()
        assert release.wait(5)
    m = mission(tmp_path, make_spec(tmp_path, initial=False), claude=lead)
    node = m.node_claims.registry.enroll('node_prepare_0001', 'fixture', ['codex'], ['gpt-6.1-sol'])
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(m.prepare_for_placement, 'prepare_assign_0001')
        try:
            assert entered.wait(5)
            with pytest.raises(ValueError, match='active'):
                m.assign_placement('build', node['node_id'], 'placement_prepare_0001')
        finally:
            release.set()
        saved = assert_prepared(m, pending.result(5))
    pin = m.assign_placement('build', node['node_id'], 'placement_prepare_0001')
    assert pin['task_hash'] == saved['task_hashes']['build'] and pin['execution_ready'] is False
    result = m.run(max_cycles=1)
    assert m.placement('build') == pin and digest(m.task('build')) == saved['task_hashes']['build']
    assert len(m.drivers['claude'].requests) == 1 and not m.drivers['codex'].requests
    assert not result['all_verified'] and not any(r['role'] == 'worker' for r in m.journal.runs())


def test_explicit_start_uses_prepared_plan_with_original_execution_gates(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path, initial=False))
    saved = assert_prepared(m, m.prepare_for_placement('prepare_start_0001'))
    continuations = {t: c['id'] for t, c in m.continuations().items()}
    result = m.run(max_cycles=20)
    assert result['all_verified'] and result['phase'] == 'COMPLETED'
    assert {t: c['id'] for t, c in m.continuations().items()} == continuations
    assert {t['id']: digest(t) for t in m.active_tasks()} == saved['task_hashes']
    assert len(m.drivers['codex'].requests) == 1
    assert len([r for r in m.journal.runs() if r['role'] == 'lead']) == 1
    before = m.store.verify_event_chain()
    assert m.prepare_for_placement('prepare_start_0001')['phase'] == 'COMPLETED'
    assert m.store.verify_event_chain() == before
