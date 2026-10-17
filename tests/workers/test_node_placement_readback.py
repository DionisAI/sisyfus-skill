"""Frozen exact placement readback; same-store snapshots, socket-free Handler.

Warm readers use the original store's readonly transaction. Cold/legacy readers
must not initialize a controller, registry, schema or metadata. Readback grants
no planning, worker, native, heartbeat, online or acceptance authority.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
from email.message import Message
import io
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest

from sisyfus.autonomy.models import canonical_json
from sisyfus.autonomy.store import AutonomyStore
from sisyfus.workers.claude_code import ClaudeCodeDriver
from sisyfus.workers.codex import CodexDriver
from sisyfus.workers.journal import Journal
from sisyfus.workers.lead_console import Handler, MissionHub
from sisyfus.workers.lead_contracts import load_lead_spec
from sisyfus.workers.lead_mission import LeadMission
from sisyfus.workers.node_claims import NodeClaims
from sisyfus.workers.node_registry import NodeRegistry
from sisyfus.workers.protocol import digest
from test_lead_mission import make_spec, plan, task


TOKEN = 'readback-operator-fixture'


def forbidden(*args, **kwargs):
    pytest.fail('placement observation reached a controller/native/network/write boundary')


@pytest.fixture(autouse=True)
def offline_guard(monkeypatch):
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    for cls in (ClaudeCodeDriver, CodexDriver):
        monkeypatch.setattr(cls, 'run', forbidden)
        monkeypatch.setattr(cls, 'probe', forbidden)
    monkeypatch.setattr(LeadMission, 'run', forbidden)


@pytest.fixture
def env(tmp_path):
    spec = make_spec(tmp_path, two=True, rsi={'enabled': False, 'auto_promote': False})
    hub = MissionHub(tmp_path / 'hub')
    ident = hub.create(spec)['id']
    m = hub._session(ident).mission
    m._initial_plan()
    yield SimpleNamespace(h=hub, ident=ident, m=m, spec=spec)
    hub.close()


def view(hub, ident):
    return hub.placements(ident)


def route(ident):
    return '/api/missions/' + ident + '/placements'


def call(hub, path, *, headers=None, method='GET', body=None):
    handler = object.__new__(Handler)
    handler.server = SimpleNamespace(token=TOKEN, server_port=8781, hub=hub)
    handler.path = path
    handler.headers = Message()
    raw = json.dumps(body).encode() if body is not None else b''
    defaults = [('Host', '127.0.0.1:8781'), ('Authorization', 'Bearer ' + TOKEN),
                ('Content-Type', 'application/json'), ('Content-Length', str(len(raw)))]
    replaced = {key.lower() for key, _ in headers or []}
    for key, value in [*(p for p in defaults if p[0].lower() not in replaced), *(headers or [])]:
        handler.headers[key] = value
    handler.rfile = io.BytesIO(raw)
    result = {}
    handler.send = lambda value, status=200, **_: result.update(status=status, value=value)
    getattr(handler, 'do_' + method)()
    return result['status'], result['value']


def truth(m):
    with m.store._transaction(immediate=False) as db:
        return {'metadata': [tuple(r) for r in db.execute('SELECT * FROM metadata ORDER BY key')],
                'schema': [tuple(r) for r in db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name')],
                'events': [tuple(r) for r in db.execute('SELECT * FROM events ORDER BY seq')],
                'runs': [tuple(r) for r in db.execute('SELECT * FROM native_worker_runs ORDER BY key')]}


def isolate_read(hub, monkeypatch):
    for method in ('_session', 'create', 'snapshot', 'nodes', 'assign_placement', 'enroll_node',
                   'revoke_node', 'prepare_placement', 'start', 'control'):
        monkeypatch.setattr(hub, method, forbidden)
    monkeypatch.setattr(hub, 'mission_factory', forbidden)
    monkeypatch.setattr(LeadMission, 'node_claims', property(forbidden))
    monkeypatch.setattr(NodeClaims, '__init__', forbidden)
    monkeypatch.setattr(NodeRegistry, '__init__', forbidden)


def exact(env):
    return {'mission_id': env.ident,
            'placements': [{'task_id': t['id'], 'placement': env.m.placement(t['id'])}
                           for t in env.m.tasks()]}


def remote(env, task_id='build'):
    node = env.m.node_claims.registry.enroll('readback-enroll-0001', 'readback fixture',
                                           ['codex'], ['gpt-6.1-sol'])
    return env.m.assign_placement(task_id, node['node_id'], 'readback-assign-0001')


def test_static_exact_public_shape_default_local_no_alias_or_lazy_backend(env, monkeypatch):
    expected = exact(env)
    before = truth(env.m)
    assert env.m._node_claims is None
    isolate_read(env.h, monkeypatch)
    result = view(env.h, env.ident)
    assert result == expected == {'mission_id': env.ident, 'placements': [
        {'task_id': 'build', 'placement': {'kind': 'local'}},
        {'task_id': 'other', 'placement': {'kind': 'local'}}]}
    assert set(result) == {'mission_id', 'placements'}
    assert all(set(row) == {'task_id', 'placement'} for row in result['placements'])
    assert all(set(row['placement']) == {'kind'} for row in result['placements'])
    assert truth(env.m) == before and env.m._node_claims is None
    assert not (env.m.directory / 'remote').exists() and env.m.store.verify_event_chain()['valid']
    result['placements'][0]['placement']['kind'] = 'caller mutation'
    assert view(env.h, env.ident) == expected


def test_remote_pin_is_exact_and_history_or_revocation_does_not_filter_or_rewrite(env, monkeypatch):
    pinned = remote(env)
    env.m.node_claims.registry.revoke(pinned['node_id'])
    env.m.journal.update(lambda state: state.update(active=['other'], superseded={'build': 'other'}))
    assert [t['id'] for t in env.m.active_tasks()] == ['other']
    expected = exact(env)
    before = truth(env.m)
    isolate_read(env.h, monkeypatch)
    result = view(env.h, env.ident)
    assert result == expected
    assert result['placements'][0] == {'task_id': 'build', 'placement': pinned}
    assert result['placements'][1] == {'task_id': 'other', 'placement': {'kind': 'local'}}
    assert pinned['mission_id'] != env.ident and result['mission_id'] == env.ident
    assert set(result['placements'][0]['placement']) == set(pinned)
    assert truth(env.m) == before and env.m.store.verify_event_chain()['valid']


def test_all_immutable_plan_records_not_only_latest_or_continuations_or_orphan_pins(env, monkeypatch):
    later = load_lead_spec({**env.spec, 'required_checks': ['a'], 'tasks': [task('later', 'later.txt', 'a')]})['initial_plan']
    env.m.journal.record('plans', 'later-plan', {'revision': 2, 'plan': later})
    env.m.journal.record('plans_shadow', 'not-a-plan', {'revision': 3, 'plan': later})
    with env.m.store._transaction() as db:
        db.execute('INSERT INTO metadata VALUES(?,?)', ('techlead:placement:not-a-task', canonical_json({'kind': 'remote'})))
        env.m.journal._event(db, 'readback_fixture_orphan', 'not-a-task', {})
    expected = exact(env)
    before = truth(env.m)
    isolate_read(env.h, monkeypatch)
    result = view(env.h, env.ident)
    assert result == expected
    assert [row['task_id'] for row in result['placements']] == ['build', 'other', 'later']
    assert result['placements'][-1] == {'task_id': 'later', 'placement': {'kind': 'local'}}
    assert truth(env.m) == before


@pytest.mark.parametrize('state', ['unplanned', 'paused', 'stopped'])
def test_empty_or_operator_controlled_missions_are_observed_without_planning_or_start(env, monkeypatch, state):
    h, ident, m = env.h, env.ident, env.m
    if state == 'unplanned':
        created = h.create(env.spec)
        ident = created['id']
        m = h._session(ident).mission
    elif state == 'paused':
        m.journal.pause(True)
    else:
        m.request_stop()
    expected = {'mission_id': ident, 'placements': [
        {'task_id': t['id'], 'placement': m.placement(t['id'])} for t in m.tasks()]}
    before = truth(m)
    isolate_read(h, monkeypatch)
    assert view(h, ident) == expected
    if state == 'unplanned':
        assert expected['placements'] == []
    assert truth(m) == before and m.store.verify_event_chain()['valid']


def test_original_store_single_read_transaction_no_nested_tasks_or_per_task_transactions(env, monkeypatch):
    expected = exact(env)
    before = truth(env.m)
    original, connect = env.m.store._transaction, sqlite3.connect
    admissions, statements = [], []
    class Connection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            cursor = super().execute(sql, parameters)
            if sql.split()[0].upper() == 'BEGIN':
                admissions.append('IMMEDIATE' in sql.upper())
                assert admissions == [False]
                super().execute('PRAGMA query_only=ON')
                self.set_trace_callback(statements.append)
            return cursor
    def observed(path, *args, **kwargs):
        assert str(path).endswith('?mode=ro') and kwargs.get('uri') is True
        return connect(path, *args, factory=Connection, **kwargs)
    isolate_read(env.h, monkeypatch)
    monkeypatch.setattr(env.m, 'tasks', forbidden)
    monkeypatch.setattr(env.m, 'active_tasks', forbidden)
    monkeypatch.setattr(env.m, 'placement', forbidden)
    monkeypatch.setattr(env.m.journal, 'records', forbidden)
    monkeypatch.setattr(env.m.store, '_transaction', forbidden)
    monkeypatch.setattr(sqlite3, 'connect', observed)
    assert view(env.h, env.ident) == expected
    assert admissions == [False]
    assert all(s.lstrip().split()[0].upper() in {'SELECT', 'COMMIT'} for s in statements)
    assert statements[-1] == 'COMMIT' and sum('techlead:plans:' in s for s in statements) == 1
    assert sum('techlead:placement:' in s for s in statements) == 2
    monkeypatch.setattr(sqlite3, 'connect', connect)
    monkeypatch.setattr(env.m.store, '_transaction', original)
    assert truth(env.m) == before


def test_tasks_and_pins_share_snapshot_while_writer_commits_new_pin_and_plan(env, monkeypatch):
    node = env.m.node_claims.registry.enroll('readback-race-enroll', 'race fixture', ['codex'], ['gpt-6.1-sol'])
    original = sqlite3.connect
    before = exact(env)
    inserted = []
    later = load_lead_spec({**env.spec, 'required_checks': ['a'], 'tasks': [task('later', 'later.txt', 'a')]})['initial_plan']
    class Connection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.split()[0].upper() == 'BEGIN':
                reads.append('IMMEDIATE' in sql.upper())
            result = super().execute(sql, parameters)
            if 'techlead:plans:' in parameters and not inserted:
                inserted.append(True)
                # Count only the observation transaction, not the independent
                # writer's legitimate registry/assignment transactions.
                monkeypatch.setattr(sqlite3, 'connect', original)
                try:
                    pinned = env.m.assign_placement('build', node['node_id'], 'readback-race-pin')
                    env.m.journal.record('plans', 'concurrent-plan', {'revision': 2, 'plan': later})
                finally:
                    monkeypatch.setattr(sqlite3, 'connect', observed)
                inserted.append(pinned)
            return result
    reads = []
    def observed(path, *args, **kwargs):
        assert str(path).endswith('?mode=ro') and kwargs.get('uri') is True
        return original(path, *args, factory=Connection, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', observed)
    assert view(env.h, env.ident) == before
    assert reads == [False] and len(inserted) == 2
    monkeypatch.setattr(sqlite3, 'connect', original)
    after = view(env.h, env.ident)
    assert after['placements'][0] == {'task_id': 'build', 'placement': inserted[1]}
    assert [p['task_id'] for p in after['placements']] == ['build', 'other', 'later']
    assert after == exact(env) and env.m.store.verify_event_chain()['valid']


@pytest.mark.parametrize('single', [False, True])
def test_reboot_readback_does_not_construct_or_reconcile_core_or_renew_native_run(env, monkeypatch, single):
    expected = exact(env)
    with env.m.store._transaction() as db:
        db.execute("INSERT INTO native_worker_runs VALUES(?,?,NULL,?,NULL,'IN_FLIGHT',NULL,?)",
                   ('readback-unresolved', 'build', digest({'fixture': True}), '2026-10-06T00:00:00Z'))
        env.m.journal._event(db, 'readback_fixture_in_flight', 'build', {})
    before = truth(env.m)
    env.h.close()
    cold = MissionHub(env.m.directory if single else env.h.directory, single=single, mission_factory=forbidden)
    ident = 'mission' if single else env.ident
    expected['mission_id'] = ident
    isolate_read(cold, monkeypatch)
    assert view(cold, ident) == expected
    assert cold._sessions == {}
    assert truth(env.m) == before and before['runs'][0][6] is None
    assert env.m.journal.runs()[0]['status'] == 'IN_FLIGHT'
    assert env.m.store.verify_event_chain()['valid']
    cold.close()


def legacy(tmp_path):
    spec = load_lead_spec(make_spec(tmp_path, rsi={'enabled': False, 'auto_promote': False}))
    h = MissionHub(tmp_path / 'legacy-hub', mission_factory=forbidden)
    ident = 'legacy'
    store = AutonomyStore(h.path(ident) / 'autonomy.sqlite3')
    journal = Journal(store)
    journal.bind(spec)
    entries = [('z-first-insert', '2030-01-01T00:00:00Z', ['last']),
               ('z-early', '2020-01-01T00:00:00Z', ['middle']),
               ('a-early', '2020-01-01T00:00:00Z', ['first'])]
    with store._transaction() as db:
        for key, created, ids in entries:
            tasks = [{**copy.deepcopy(spec['initial_plan']['tasks'][0]), 'id': tid} for tid in ids]
            record = {'key': key, 'created_at': created,
                      'data': {'revision': 1, 'plan': {**copy.deepcopy(spec['initial_plan']), 'tasks': tasks}}}
            db.execute('INSERT INTO metadata VALUES(?,?)', ('techlead:plans:' + key, canonical_json(record)))
            journal._event(db, 'readback_legacy_plan', key, record)
        pin = {'kind': 'remote', 'node_id': 'node_' + 'a' * 32, 'task_id': 'middle',
               'mission_id': 'legacy-canonical-identity', 'revision': 1, 'request_id': 'legacy-fixed-request',
               'task_hash': '0' * 64, 'execution_ready': False, 'created_at': '2020-01-01T00:00:00Z'}
        db.execute('INSERT INTO metadata VALUES(?,?)', ('techlead:placement:middle', canonical_json(pin)))
        journal._event(db, 'readback_legacy_pin', 'middle', pin)
    return h, ident, store, pin


def test_minimal_legacy_store_readonly_no_new_schema_or_metadata_with_record_sort_order(tmp_path, monkeypatch):
    h, ident, store, pin = legacy(tmp_path)
    with store._transaction(immediate=False) as db:
        before = list(db.iterdump())
        keys = {r[0] for r in db.execute('SELECT key FROM metadata')}
    assert 'techlead:state' not in keys and 'lead_mission_inbox_schema' not in keys
    assert not any(k.startswith('remote_') for k in keys)
    isolate_read(h, monkeypatch)
    result = view(h, ident)
    assert result == {'mission_id': ident, 'placements': [
        {'task_id': 'first', 'placement': {'kind': 'local'}},
        {'task_id': 'middle', 'placement': pin},
        {'task_id': 'last', 'placement': {'kind': 'local'}}]}
    with store._transaction(immediate=False) as db:
        assert list(db.iterdump()) == before
    assert h._sessions == {} and not (h.path(ident) / 'remote').exists()
    assert store.verify_event_chain()['valid']
    h.close()


def test_get_handler_exact_readback_no_query_and_no_backend_construction(env, monkeypatch):
    expected = exact(env)
    before = truth(env.m)
    isolate_read(env.h, monkeypatch)
    assert call(env.h, route(env.ident)) == (200, expected)
    assert truth(env.m) == before and env.m._node_claims is None


@pytest.mark.parametrize('headers,status', [
    ([('Authorization', '')], 401), ([('Authorization', 'Bearer wrong')], 401),
    ([('Authorization', 'Node node_fixture')], 401),
    ([('Authorization', 'Bearer ' + TOKEN), ('Authorization', 'Bearer ' + TOKEN)], 401),
    ([('Host', 'evil.example:8781')], 403),
    ([('Host', '127.0.0.1:8781'), ('Host', '127.0.0.1:8781')], 403),
    ([('Origin', 'https://evil.example')], 403), ([('Origin', 'null')], 403),
    ([('Origin', 'http://127.0.0.1:8781'), ('Origin', 'http://127.0.0.1:8781')], 403),
    ([('X-Sisyfus-Node', 'node_fixture')], 403), ([('X-Sisyfus-Node-Id', 'node_fixture')], 403),
    ([('X-Sisyfus-Node-Secret', 'fixture')], 403), ([('X-Node-Id', 'fixture')], 403),
    ([('x-NoDe-ToKeN', 'fixture')], 403),
])
def test_existing_host_origin_bearer_and_node_header_boundary_precedes_readback(env, monkeypatch, headers, status):
    before = truth(env.m)
    monkeypatch.setattr(env.h, 'placements', forbidden, raising=False)
    isolate_read(env.h, monkeypatch)
    result = call(env.h, route(env.ident), headers=headers)
    assert result[0] == status and TOKEN not in json.dumps(result[1])
    assert truth(env.m) == before


@pytest.mark.parametrize('headers', [[], [('Origin', 'http://127.0.0.1:8781')],
                                   [('Host', 'localhost:8781'), ('Origin', 'http://localhost:8781')],
                                   [('X-Sisyfus-Other', 'ordinary')]])
def test_ordinary_operator_readback_keeps_existing_allowed_header_forms(env, monkeypatch, headers):
    expected = exact(env)
    before = truth(env.m)
    isolate_read(env.h, monkeypatch)
    assert call(env.h, route(env.ident), headers=headers) == (200, expected)
    assert truth(env.m) == before


@pytest.mark.parametrize('query', ['?', '?cursor=0', '?mission_id=other', '?x=', '?x=1&x=2', '?%', '?x=%FF'])
def test_readback_rejects_every_query_before_store_access(env, monkeypatch, query):
    before = truth(env.m)
    monkeypatch.setattr(env.h, 'placements', forbidden, raising=False)
    isolate_read(env.h, monkeypatch)
    assert call(env.h, route(env.ident) + query)[0] == 400
    assert truth(env.m) == before


@pytest.mark.parametrize('suffix', ['/', '/extra', '/node_' + 'a' * 32 + '/revoke', '/node_' + 'a' * 32])
def test_get_readback_only_exact_route_never_accepts_revoke_or_trailing_children(env, monkeypatch, suffix):
    before = truth(env.m)
    monkeypatch.setattr(env.h, 'placements', forbidden, raising=False)
    isolate_read(env.h, monkeypatch)
    assert call(env.h, route(env.ident) + suffix)[0] == 404
    assert truth(env.m) == before


@pytest.mark.parametrize('path', ['/api/missions/../placements', '/api/missions/%2e%2e/placements',
                                 '/api/missions//placements', '/api/missions/' + 'a' * 65 + '/placements'])
def test_invalid_http_mission_identifiers_never_reach_store(env, monkeypatch, path):
    monkeypatch.setattr(env.h, 'placements', forbidden, raising=False)
    isolate_read(env.h, monkeypatch)
    assert call(env.h, path)[0] == 404


@pytest.mark.parametrize('ident', [None, True, 1, [], {}, '', '../outside', 'a' * 65])
def test_invalid_direct_mission_identity_has_no_lazy_initialization(env, monkeypatch, ident):
    before = truth(env.m)
    isolate_read(env.h, monkeypatch)
    with pytest.raises(ValueError):
        view(env.h, ident)
    assert truth(env.m) == before


@pytest.mark.parametrize('kind,status', [('unknown', 404), ('unbound', 404), ('mission_symlink', 400), ('db_symlink', 404)])
def test_missing_unbound_or_symlink_store_fails_without_creation(env, tmp_path, monkeypatch, kind, status):
    outside = tmp_path / 'outside'
    outside.mkdir()
    ident = 'readback-target'
    control = env.h.directory / ident
    if kind == 'unbound':
        control.mkdir()
    elif kind == 'mission_symlink':
        control.symlink_to(outside, target_is_directory=True)
    elif kind == 'db_symlink':
        control.mkdir()
        (control / 'autonomy.sqlite3').symlink_to(env.m.store.path)
    isolate_read(env.h, monkeypatch)
    assert call(env.h, route(ident))[0] == status
    assert not list(outside.iterdir())
    assert not control.exists() if kind == 'unknown' else True
    if kind == 'unbound':
        assert not list(control.iterdir())


@pytest.mark.parametrize('corrupt', ['plan', 'pin'])
def test_malformed_stored_json_is_explicit_error_never_silent_local_default(env, monkeypatch, corrupt):
    with env.m.store._transaction() as db:
        if corrupt == 'plan':
            db.execute("UPDATE metadata SET value='{' WHERE key LIKE 'techlead:plans:%'")
        else:
            db.execute('INSERT INTO metadata VALUES(?,?)', ('techlead:placement:build', '{'))
        env.m.journal._event(db, 'readback_fixture_corrupt', corrupt, {})
    before = truth(env.m)
    isolate_read(env.h, monkeypatch)
    with pytest.raises(ValueError):
        view(env.h, env.ident)
    assert call(env.h, route(env.ident))[0] == 400
    assert truth(env.m) == before


def test_existing_nodes_get_and_placement_post_projection_remain_separate(env, monkeypatch):
    pinned = remote(env)
    expected_nodes = env.h.nodes(env.ident)
    expected_view = exact(env)
    before = truth(env.m)
    body = {'task_id': 'build', 'node_id': pinned['node_id'], 'request_id': pinned['request_id']}
    # Exact POST retry is the pre-existing readback behavior, not the new GET API.
    assert call(env.h, route(env.ident), method='POST', body=body) == (200, pinned)
    assert truth(env.m) == before
    monkeypatch.setattr(env.h, 'nodes', lambda ident: expected_nodes)
    assert call(env.h, '/api/missions/' + env.ident + '/nodes') == (200, expected_nodes)
    assert call(env.h, route(env.ident)) == (200, expected_view)
    assert set(expected_nodes) == {'mission_id', 'nodes', 'execution_ready'}
    assert set(expected_view) == {'mission_id', 'placements'}
    assert truth(env.m) == before and env.m.store.verify_event_chain()['valid']
