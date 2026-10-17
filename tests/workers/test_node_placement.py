"""Frozen N2 controller placement scenarios; protocol fixtures, no native/network.

Freeze before implementation: lazy same-store backend, explicit active frozen
implementation scope, atomic reservation/assignment races, immutable retry/hash/
revision, cross-mission/revoked/trial fences, unchanged local fingerprint and
staging remote ERROR before any new native reservation. No acceptance changes.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading

import pytest

from sisyfus.autonomy.policy import CapabilityRegistry, IdempotencyConflictError
from sisyfus.workers.journal import DispatchBlocked
from sisyfus.workers.node_claims import NodeClaims
from sisyfus.workers.protocol import Receipt, digest
from test_lead_mission import make_spec, mission, plan, task


@pytest.fixture
def m(tmp_path):
    controller = mission(tmp_path, make_spec(tmp_path))
    controller._initial_plan()
    return controller


def enroll(m, serial=1):
    return m.node_claims.registry.enroll('node_enroll_%04d' % serial, 'N2 node %d' % serial,
                                       ['codex'], ['gpt-6.1-sol'])


def assign(m, node, request='placement_0001', task_id='build'):
    return m.assign_placement(task_id, node['node_id'], request)


def remote_tables(m):
    with m.store._transaction(immediate=False) as db:
        return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'remote_%'")]


def truth(m):
    with m.store._transaction(immediate=False) as db:
        return {'spec': m.spec, 'state': m.journal.state(), 'procedure': m.procedure(),
                'evidence': [tuple(r) for r in db.execute('SELECT * FROM evidence')],
                'commands': [tuple(r) for r in db.execute('SELECT * FROM native_worker_commands')],
                'runs': [tuple(r) for r in db.execute('SELECT * FROM native_worker_runs')]}


def execution(m):
    cont = m.store.claim_due_continuation('N2-protocol-fixture')
    assert cont is not None and cont['context']['native_task'] == 'build'
    decision = m.planner(cont, m.runtime.planner_context(cont))
    assert decision.capability == 'workers.execute'
    return m.registry.get('workers.execute').capability, decision.arguments


def test_default_local_lookup_is_lazy_and_creates_no_legacy_records(m):
    before = m.store.verify_event_chain()
    assert not remote_tables(m)
    for ident in ('build', 'missing', 'planner', 'integration:1'):
        assert m.placement(ident) == {'kind': 'local'}
    assert not remote_tables(m) and not (m.directory / 'remote').exists()
    assert m.store.verify_event_chain() == before


def test_node_backend_is_lazy_same_store_pinned_root_and_separate_capability_registry(m):
    capabilities = m.registry
    backend = m.node_claims
    assert isinstance(backend, NodeClaims) and m.node_claims is backend
    assert backend.journal is m.journal and backend.registry.journal is m.journal
    assert backend.journal.store.path == m.store.path
    assert backend.artifact_root == m.directory / 'remote' / 'artifacts'
    assert backend.artifact_root.is_dir() and backend.artifact_root.stat().st_mode & 0o777 == 0o700
    assert m.registry is capabilities and isinstance(m.registry, CapabilityRegistry)
    assert m.registry.get('workers.execute').capability.mission is m
    assert not m.journal.runs() and m.store.verify_event_chain()['valid']


def test_assignment_is_fixed_controller_metadata_not_acceptance_or_dispatch(m):
    node = enroll(m)
    before = truth(m)
    saved = assign(m, node)
    assert saved['kind'] == 'remote' and saved['execution_ready'] is False
    assert saved['node_id'] == node['node_id'] and saved['task_id'] == 'build'
    assert saved['task_hash'] == digest(m.task('build'))
    assert saved['revision'] == m.journal.state()['revision']
    assert saved['request_id'] == 'placement_0001'
    assert saved['mission_id'] == node['mission_id']
    assert m.placement('build') == saved and truth(m) == before
    assert not m.drivers['codex'].requests and not m.drivers['claude'].requests
    assert m.store.verify_event_chain()['valid']


def test_retry_restart_conflict_and_pinned_node_identity(m, tmp_path):
    node, other = enroll(m), enroll(m, 2)
    saved = assign(m, node)
    before = m.store.verify_event_chain()
    assert assign(m, node) == saved
    reopened = mission(tmp_path, None)
    assert reopened.placement('build') == saved and assign(reopened, node) == saved
    assert reopened.store.verify_event_chain() == before
    with pytest.raises(IdempotencyConflictError):
        assign(reopened, other)
    with pytest.raises(IdempotencyConflictError):
        assign(reopened, other, 'placement_0002')
    assert reopened.placement('build') == saved


@pytest.mark.parametrize('status', ['IN_FLIGHT', 'UNKNOWN', 'COMPLETED', 'ERROR'])
def test_any_prior_same_task_native_reservation_fences_new_placement(m, status):
    node = enroll(m)
    m.journal.reserve('prior-reservation', 'build', digest('existing frozen native input'))
    if status != 'IN_FLIGHT':
        m.journal.complete('prior-reservation', Receipt(status).as_dict())
    before = m.store.verify_event_chain()
    with pytest.raises(DispatchBlocked, match='reservation'):
        assign(m, node)
    assert m.placement('build') == {'kind': 'local'}
    assert m.store.verify_event_chain() == before


def test_cached_assignment_reads_back_after_reservation_and_revocation(m):
    node = enroll(m)
    saved = assign(m, node)
    m.journal.reserve('prior-after-pin', 'build', digest('fixture reservation'))
    m.journal.complete('prior-after-pin', Receipt('UNKNOWN').as_dict())
    m.node_claims.registry.revoke(node['node_id'])
    before = m.store.verify_event_chain()
    assert assign(m, node) == saved
    with pytest.raises(DispatchBlocked, match='reservation'):
        assign(m, node, 'placement_0002')
    assert m.store.verify_event_chain() == before


def test_plan_revision_keeps_pinned_revision_and_superseded_retry_readback(m):
    node = enroll(m)
    saved = assign(m, node)
    m.admit_plan(plan([task('extension', 'extension.txt')]), 'extension-plan')
    assert m.journal.state()['revision'] > saved['revision']
    assert m.placement('build') == saved
    m.admit_plan(plan([task('replacement', 'a.txt', repair='build')]), 'replacement-plan')
    assert 'build' not in m.journal.state()['active']
    before = m.store.verify_event_chain()
    assert assign(m, node) == saved
    with pytest.raises(ValueError, match='active'):
        assign(m, node, 'placement_0002')
    assert m.store.verify_event_chain() == before
    replacement = assign(m, node, 'placement_0003', 'replacement')
    assert replacement['task_hash'] == digest(m.task('replacement'))
    assert replacement['revision'] == m.journal.state()['revision']


def test_pinned_hash_drift_is_explicit_conflict_and_never_overwrites(m):
    node = enroll(m)
    saved = assign(m, node)
    # Synthetic canonical corruption, not an edit to acceptance or a test file.
    with m.store._transaction() as db:
        key, raw = db.execute("SELECT key,value FROM metadata WHERE key LIKE 'techlead:plans:%'").fetchone()
        value = json.loads(raw)
        value['data']['plan']['tasks'][0]['objective'] = 'changed synthetic task hash'
        db.execute('UPDATE metadata SET value=? WHERE key=?', (json.dumps(value), key))
    with pytest.raises(IdempotencyConflictError, match='hash'):
        assign(m, node, 'placement_0002')
    assert m.placement('build') == saved


@pytest.mark.parametrize('ident', ['missing', 'planner', 'reviewer', 'rsi', 'integration:1'])
def test_only_admitted_active_implementation_tasks_are_eligible(m, ident):
    node = enroll(m)
    before = truth(m)
    with pytest.raises(ValueError):
        assign(m, node, task_id=ident)
    assert truth(m) == before


def test_unadmitted_initial_task_and_invalid_continuation_scope_are_rejected(tmp_path):
    controller = mission(tmp_path, make_spec(tmp_path))
    node = enroll(controller)
    with pytest.raises(ValueError, match='active'):
        assign(controller, node)
    controller._initial_plan()
    with controller.store._transaction() as db:
        row = db.execute('SELECT id,context_json FROM continuations').fetchone()
        context = json.loads(row['context_json'])
        context['lead_kind'] = 'reviewer'
        db.execute('UPDATE continuations SET context_json=? WHERE id=?', (json.dumps(context), row['id']))
    with pytest.raises(ValueError, match='implementation'):
        assign(controller, node)
    assert controller.placement('build') == {'kind': 'local'}


@pytest.mark.parametrize('field,value', [('task_id', None), ('task_id', []), ('node_id', []),
    ('request_id', None), ('request_id', 'short'), ('request_id', 'x' * 101)])
def test_operator_identity_types_are_validated(m, field, value):
    node = enroll(m)
    arguments = {'task_id': 'build', 'node_id': node['node_id'], 'request_id': 'placement_0001'}
    arguments[field] = value
    with pytest.raises(ValueError):
        m.assign_placement(**arguments)
    assert m.placement('build') == {'kind': 'local'}


def test_revoked_and_other_mission_nodes_do_not_grant_placement(m, tmp_path):
    node = enroll(m)
    other_root = tmp_path / 'other-fixture'
    other_root.mkdir()
    other = mission(other_root, make_spec(other_root))
    other._initial_plan()
    foreign = enroll(other)
    with pytest.raises(PermissionError):
        assign(m, foreign)
    m.node_claims.registry.revoke(node['node_id'])
    with pytest.raises(PermissionError):
        assign(m, node)
    assert m.placement('build') == {'kind': 'local'}
    saved = assign(other, foreign)
    assert saved['mission_id'] != node['mission_id'] and m.placement('build') == {'kind': 'local'}


@pytest.mark.parametrize('marker', ['techlead:inbox_policy:trial-child', 'techlead:learning_config:trial'])
def test_trial_children_are_excluded_before_node_backend_initialization(m, marker):
    with m.store._transaction() as db:
        db.execute('INSERT INTO metadata VALUES(?,?)', (marker, '{}'))
    before = m.store.verify_event_chain()
    with pytest.raises(PermissionError, match='trial'):
        _ = m.node_claims
    with pytest.raises(PermissionError, match='trial'):
        m.assign_placement('build', 'node_' + 'a' * 32, 'placement_0001')
    assert not remote_tables(m) and m.store.verify_event_chain() == before


def test_concurrent_conflicting_assignment_has_one_pin(m):
    a, b = enroll(m), enroll(m, 2)
    barrier = threading.Barrier(2)
    def attempt(node, ident):
        barrier.wait(timeout=5)
        try:
            return assign(m, node, ident)
        except IdempotencyConflictError:
            return 'CONFLICT'
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, a, 'placement_0001'), pool.submit(attempt, b, 'placement_0002')]
        results = [f.result(timeout=10) for f in futures]
    assert results.count('CONFLICT') == 1
    winner = next(r for r in results if isinstance(r, dict))
    assert m.placement('build') == winner
    assert sum(e['type'] == 'WORKER_NODE_PLACEMENT_ASSIGNED' for e in m.journal.events()) == 1


def test_assignment_hash_chain_callback_failure_rolls_back_pin_and_request(m, monkeypatch):
    node = enroll(m)
    before = m.store.verify_event_chain()
    original = m.journal._event
    def broken(db, kind, key, data, *args, **kwargs):
        original(db, kind, key, data, *args, **kwargs)
        if kind == 'node_placement_assigned':
            raise ValueError('fixture placement transaction crash')
    with monkeypatch.context() as patch:
        patch.setattr(m.journal, '_event', broken)
        with pytest.raises(ValueError, match='fixture placement transaction crash'):
            assign(m, node)
    assert m.placement('build') == {'kind': 'local'} and m.store.verify_event_chain() == before
    assert assign(m, node)['node_id'] == node['node_id']


def test_local_execution_preserves_original_fingerprint_and_cached_receipt(m):
    capability, arguments = execution(m)
    expected = digest({'arguments': arguments, 'task': m.task('build'), 'spec': digest(m.spec)})
    result = capability.execute(arguments, idempotency_key='local-original')
    assert result.status == 'COMPLETED'
    with m.store._transaction(immediate=False) as db:
        row = db.execute('SELECT fingerprint,task_id FROM native_worker_runs WHERE key=?', ('local-original',)).fetchone()
        assert row['fingerprint'] == expected and row['task_id'] == 'build'
    assert not remote_tables(m) and m.placement('build') == {'kind': 'local'}
    assert capability.execute(arguments, idempotency_key='local-original').observation == result.observation
    assert len(m.drivers['codex'].requests) == 1
    with pytest.raises(IdempotencyConflictError):
        capability.execute({**arguments, 'prompt': arguments['prompt'] + ' changed'}, idempotency_key='local-original')


def test_staging_remote_execution_fails_before_reservation_candidate_or_native(m, tmp_path):
    node = enroll(m)
    saved = assign(m, node)
    capability, arguments = execution(m)
    frozen = digest(m.spec)
    result = capability.execute(arguments, idempotency_key='remote-not-ready')
    assert result.status == 'ERROR' and '远端执行传输尚未接入' in (result.error or result.observation.get('error', ''))
    assert result.observation['placement'] == saved
    assert not m.journal.runs() and not m.drivers['codex'].requests and not m.drivers['claude'].requests
    assert not (m.directory / 'attempts' / 'remote-not-ready').exists()
    errors = m.journal.records('placement_errors')
    assert len(errors) == 1 and errors[0]['data']['status'] == 'ERROR'
    assert '远端执行传输尚未接入' in errors[0]['data']['error']
    assert digest(m.spec) == frozen and not m.snapshot()['all_verified']
    reopened = mission(tmp_path, None)
    again = reopened.registry.get('workers.execute').capability.execute(arguments, idempotency_key='remote-not-ready')
    assert again.observation == result.observation and not reopened.journal.runs()
    assert len(reopened.journal.records('placement_errors')) == 1


def test_assignment_wins_race_before_local_reservation_and_prevents_local_fallback(m, monkeypatch):
    node = enroll(m)
    capability, arguments = execution(m)
    entered, release = threading.Event(), threading.Event()
    original = m.journal.reserve
    def gated(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=10)
        return original(*args, **kwargs)
    monkeypatch.setattr(m.journal, 'reserve', gated)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(capability.execute, arguments, idempotency_key='placement-race')
        assert entered.wait(timeout=5)
        try:
            saved = assign(m, node)
        finally:
            release.set()
        result = future.result(timeout=10)
    assert result.status == 'ERROR' and result.observation['placement'] == saved
    assert not m.journal.runs() and not m.drivers['codex'].requests


def test_reservation_transaction_wins_race_and_assignment_reads_committed_run(m):
    node = enroll(m)
    entered, release = threading.Event(), threading.Event()
    def gate(_db):
        entered.set()
        assert release.wait(timeout=10)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reserved = pool.submit(m.journal.reserve, 'race-first', 'build', digest('reservation wins'), on_reserved=gate)
        assert entered.wait(timeout=5)
        pending = pool.submit(assign, m, node)
        release.set()
        assert reserved.result(timeout=10) is None
        with pytest.raises(DispatchBlocked, match='reservation'):
            pending.result(timeout=10)
    assert m.placement('build') == {'kind': 'local'}
