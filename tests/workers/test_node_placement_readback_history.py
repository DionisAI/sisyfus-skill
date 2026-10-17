"""Additional verification of the already implemented placements API.

Exactly two independent history/WAL scenarios. Original frozen60 and its two
setup failures remain untouched. validate_plan receives existing fixed tasks;
required checks a+b, Core truth and all production interfaces stay unchanged.
These are additional verification, not a new red/fix TDD source cycle.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import json
import socket
import sqlite3
import subprocess
import threading
from types import SimpleNamespace

import pytest

from sisyfus.autonomy.models import canonical_json
from sisyfus.workers.claude_code import ClaudeCodeDriver
from sisyfus.workers.codex import CodexDriver
from sisyfus.workers.lead_console import MissionHub
from sisyfus.workers.lead_contracts import validate_plan
from sisyfus.workers.lead_mission import LeadMission
from sisyfus.workers.node_claims import NodeClaims
from sisyfus.workers.node_registry import NodeRegistry
from sisyfus.workers.protocol import digest
from test_lead_mission import make_spec, plan, task
from test_node_operator_http import call


def forbidden(*args, **kwargs):
    pytest.fail('placement verification reached native/network/controller initialization')


@pytest.fixture(autouse=True)
def offline_guard(monkeypatch):
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(LeadMission, 'run', forbidden)
    for cls in (CodexDriver, ClaudeCodeDriver):
        monkeypatch.setattr(cls, 'run', forbidden)
        monkeypatch.setattr(cls, 'probe', forbidden)


@pytest.fixture
def env(tmp_path):
    spec = make_spec(tmp_path, two=True, rsi={'enabled': False, 'auto_promote': False})
    hub = MissionHub(tmp_path / 'hub')
    ident = hub.create(spec)['id']
    mission = hub._session(ident).mission
    mission._initial_plan()
    yield SimpleNamespace(h=hub, ident=ident, m=mission)
    hub.close()


def later_plan(env):
    existing = env.m.tasks()
    before = copy.deepcopy(env.m.spec)
    assert env.m.spec['required_checks'] == ['a', 'b']
    assert [(t['id'], t['check']) for t in existing] == [('build', 'a'), ('other', 'b')]
    raw = plan([task('later', 'later.txt', 'a')])
    normalized = validate_plan(raw, env.m.spec, existing=existing)
    assert env.m.spec == before
    assert normalized == {
        'architecture': raw['architecture'], 'interfaces': raw['interfaces'],
        'tasks': [{'id': 'later', 'objective': 'write later.txt', 'check': 'a',
                   'depends_on': [], 'driver': 'codex', 'max_attempts': 1,
                   'write_paths': ['later.txt'], 'acceptance': 'frozen a acceptance'}],
        'rationale': ''}
    return normalized


def truth(mission):
    with mission.store._transaction(immediate=False) as db:
        return list(db.iterdump())


def isolate_read(env, monkeypatch):
    for method in ('_session', 'create', 'snapshot', 'nodes', 'enroll_node',
                   'revoke_node', 'assign_placement', 'prepare_placement', 'start', 'control'):
        monkeypatch.setattr(env.h, method, forbidden)
    monkeypatch.setattr(env.h, 'mission_factory', forbidden)
    for method in ('tasks', 'active_tasks', 'placement'):
        monkeypatch.setattr(env.m, method, forbidden)
    monkeypatch.setattr(env.m.journal, 'records', forbidden)
    monkeypatch.setattr(NodeClaims, '__init__', forbidden)
    monkeypatch.setattr(NodeRegistry, '__init__', forbidden)


def test_fixed_history_exact_pins_with_existing_required_checks(env, monkeypatch):
    later = later_plan(env)
    acceptance = env.m.spec['acceptance_hash']
    registry = env.m.node_claims.registry
    node = registry.enroll('history-enroll-0001', 'retained history fixture',
                           ['codex'], ['gpt-6.1-sol'])
    pinned = env.m.assign_placement('build', node['node_id'], 'history-pin-0001')
    env.m.journal.record('plans', 'history-later-plan', {'revision': 2, 'plan': later})
    env.m.journal.record('plans_shadow', 'history-shadow', {'revision': 3, 'plan': later})
    with env.m.store._transaction() as db:
        db.execute('INSERT INTO metadata VALUES(?,?)',
                   ('techlead:placement:orphan', canonical_json({'kind': 'remote'})))
        env.m.journal._event(db, 'history_fixture_orphan', 'orphan', {})
    env.m.journal.update(lambda state: state.update(active=['later'],
                                                     superseded={'build': 'later'}))
    registry.revoke(node['node_id'])
    assert [t['id'] for t in env.m.active_tasks()] == ['later']
    assert [t['id'] for t in env.m.tasks()] == ['build', 'other', 'later']
    assert env.m.placement('build') == pinned
    assert env.m.placement('other') == env.m.placement('later') == {'kind': 'local'}
    expected = {'mission_id': env.ident, 'placements': [
        {'task_id': 'build', 'placement': pinned},
        {'task_id': 'other', 'placement': {'kind': 'local'}},
        {'task_id': 'later', 'placement': {'kind': 'local'}}]}
    assert pinned['mission_id'] != env.ident
    before = truth(env.m)
    chain = env.m.store.verify_event_chain()
    isolate_read(env, monkeypatch)
    actual = env.h.placements(env.ident)
    assert actual == expected
    assert set(actual) == {'mission_id', 'placements'}
    assert all(set(row) == {'task_id', 'placement'} for row in actual['placements'])
    assert set(actual['placements'][0]['placement']) == set(pinned)
    assert call(env.h, '/api/missions/' + env.ident + '/placements') == (200, expected)
    assert truth(env.m) == before
    assert env.m.spec['required_checks'] == ['a', 'b']
    assert env.m.spec['acceptance_hash'] == acceptance
    assert env.m.store.verify_event_chain() == chain and chain['valid']
    print('ADDITIONAL_VERIFICATION history: build/other/later, historical revoked pin exact, no writes')


def test_wal_writer_commits_after_task_read_without_mixed_pin_snapshot(env, monkeypatch):
    later = later_plan(env)
    spec = copy.deepcopy(env.m.spec)
    node = env.m.node_claims.registry.enroll('history-wal-enroll', 'retained WAL fixture',
                                            ['codex'], ['gpt-6.1-sol'])
    expected_before = {'mission_id': env.ident, 'placements': [
        {'task_id': 'build', 'placement': {'kind': 'local'}},
        {'task_id': 'other', 'placement': {'kind': 'local'}}]}
    assert env.h.placements(env.ident) == expected_before
    original = sqlite3.connect
    owner = threading.get_ident()
    task_rows_read, writer_done = threading.Event(), threading.Event()
    writer_result, writer_errors, reader_transactions, statements = [], [], [], []
    writer_connections, reader_connections = [], []

    def writer():
        try:
            assert task_rows_read.wait(10), 'reader did not establish its task snapshot'
            pinned = env.m.assign_placement('build', node['node_id'], 'history-wal-pin')
            saved = env.m.journal.record('plans', 'history-wal-plan',
                                         {'revision': 2, 'plan': later})
            writer_result.append({'placement': pinned, 'plan': saved})
        except BaseException as exc:
            writer_errors.append(exc)
        finally:
            writer_done.set()

    class SnapshotRows:
        def __init__(self, cursor):
            self.cursor = cursor

        def fetchall(self):
            rows = self.cursor.fetchall()
            assert len(rows) == 1, 'expected original immutable plan before writer'
            task_rows_read.set()
            assert writer_done.wait(10), 'WAL writer did not commit while reader was open'
            if writer_errors:
                raise writer_errors[0]
            return rows

    class SnapshotConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.split()[0].upper() == 'BEGIN':
                reader_transactions.append('IMMEDIATE' in sql.upper())
                assert reader_transactions == [False]
                assert super().execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
            cursor = super().execute(sql, parameters)
            if sql.split()[0].upper() == 'BEGIN':
                reader_connections.append(self)
                super().execute('PRAGMA query_only=ON')
                self.set_trace_callback(statements.append)
            if parameters == (len('techlead:plans:'), 'techlead:plans:'):
                return SnapshotRows(cursor)
            return cursor

    def observed(path, *args, **kwargs):
        if threading.get_ident() == owner:
            assert str(path).endswith('?mode=ro') and kwargs.get('uri') is True
            return original(path, *args, factory=SnapshotConnection, **kwargs)
        db = original(path, *args, **kwargs)
        if str(path) == str(env.m.store.path):
            assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
            writer_connections.append(db)
        return db

    isolate_read(env, monkeypatch)
    monkeypatch.setattr(sqlite3, 'connect', observed)
    thread = threading.Thread(target=writer, name='placement-readback-WAL-fixture', daemon=True)
    thread.start()
    try:
        during = env.h.placements(env.ident)
    finally:
        task_rows_read.set()
        thread.join(15)
    assert not thread.is_alive(), 'writer fixture remained active'
    assert not writer_errors, writer_errors
    assert writer_done.is_set() and len(writer_result) == 1
    assert during == expected_before
    assert reader_transactions == [False]
    assert len(reader_connections) == 1 and len(writer_connections) >= 2
    assert all(db is not reader_connections[0] for db in writer_connections)
    assert all(s.lstrip().split()[0].upper() in {'SELECT', 'COMMIT'} for s in statements)
    assert sum('techlead:plans:' in s for s in statements) == 1
    assert sum('techlead:placement:' in s for s in statements) == 2
    monkeypatch.setattr(sqlite3, 'connect', original)
    expected_after = {'mission_id': env.ident, 'placements': [
        {'task_id': 'build', 'placement': writer_result[0]['placement']},
        {'task_id': 'other', 'placement': {'kind': 'local'}},
        {'task_id': 'later', 'placement': {'kind': 'local'}}]}
    assert writer_result[0]['plan']['data'] == {'revision': 2, 'plan': later}
    assert writer_result[0]['placement']['task_hash'] == digest(spec['initial_plan']['tasks'][0])
    before_read = truth(env.m)
    assert env.h.placements(env.ident) == expected_after
    assert call(env.h, '/api/missions/' + env.ident + '/placements') == (200, expected_after)
    assert truth(env.m) == before_read and env.m.spec == spec
    assert env.m.store.verify_event_chain()['valid']
    print('ADDITIONAL_VERIFICATION WAL: separate writer committed during readonly snapshot;'
          ' old two local pins during read, exact new remote pin + later task on next read')
