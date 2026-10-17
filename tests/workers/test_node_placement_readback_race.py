"""Frozen P2 real-identity races, before the placements binding repair.

Bound A/B fixtures, real rename/symlink/hardlink and independent SQLite I/O.
Every displaced original is retained. No deletion, native/network, acceptance
settlement, constructor on readback or change to existing frozen test oracles.
"""
from __future__ import annotations

import copy
import json
import os
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
from sisyfus.workers import lead_console as console
from sisyfus.workers.lead_mission import LeadMission
from sisyfus.workers.node_claims import NodeClaims
from sisyfus.workers.node_registry import NodeRegistry
from test_lead_mission import make_spec
from test_node_operator_http import call


def forbidden(*args, **kwargs):
    pytest.fail('identity readback reached a native/network/controller initialization boundary')


@pytest.fixture(autouse=True)
def offline_guard(monkeypatch):
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(LeadMission, 'run', forbidden)
    for cls in (CodexDriver, ClaudeCodeDriver):
        monkeypatch.setattr(cls, 'run', forbidden)
        monkeypatch.setattr(cls, 'probe', forbidden)


def dump(path, connect=sqlite3.connect):
    db = connect(Path(path).as_uri() + '?mode=ro', uri=True, isolation_level=None)
    try:
        db.execute('BEGIN')
        return list(db.iterdump())
    finally:
        db.close()


@pytest.fixture
def env(tmp_path):
    (tmp_path / 'a').mkdir()
    (tmp_path / 'b').mkdir()
    hub = console.MissionHub(tmp_path / 'hub')
    ident = hub.create(make_spec(tmp_path / 'a', rsi={'enabled': False, 'auto_promote': False}))['id']
    other = make_spec(tmp_path / 'b', rsi={'enabled': False, 'auto_promote': False})
    other['tasks'][0]['id'] = 'foreign'
    foreign_id = hub.create(other)['id']
    a, b = hub._session(ident).mission, hub._session(foreign_id).mission
    a._initial_plan()
    b._initial_plan()
    node = b.node_claims.registry.enroll('race-foreign-enroll', 'foreign fixture', ['codex'], ['gpt-6.1-sol'])
    pinned = b.assign_placement('foreign', node['node_id'], 'race-foreign-pin')
    image = tmp_path / 'foreign-image'
    image.mkdir()
    source = sqlite3.connect(b.store.path.as_uri() + '?mode=ro', uri=True)
    destination = sqlite3.connect(image / 'autonomy.sqlite3')
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    before_a, before_b = dump(a.store.path), dump(b.store.path)
    assert dump(image / 'autonomy.sqlite3') == before_b
    assert a.store.path.lstat().st_ino != b.store.path.lstat().st_ino
    assert console.approved_spec(a.directory) == a.spec
    assert console.approved_spec(a.directory) != b.spec
    yield SimpleNamespace(root=tmp_path, h=hub, ident=ident, a=a, b=b, pin=pinned,
                          image=image, before_a=before_a, before_b=before_b)
    hub.close()


def selected(env, mode):
    if mode == 'warm':
        return env.h
    return console.MissionHub(env.h.directory, mission_factory=forbidden)


def read_guard(hub, monkeypatch):
    for method in ('_session', 'create', 'snapshot', 'nodes', 'enroll_node', 'revoke_node',
                   'assign_placement', 'prepare_placement', 'start', 'control'):
        monkeypatch.setattr(hub, method, forbidden)
    monkeypatch.setattr(hub, 'mission_factory', forbidden)
    for cls in (AutonomyStore, Journal, NodeClaims, NodeRegistry):
        monkeypatch.setattr(cls, '__init__', forbidden)


def swapper(env, kind):
    state = {'done': False, 'retained_a': env.a.store.path, 'foreign_at': env.b.store.path}

    def swap():
        assert not state['done']
        state['done'] = True
        if kind.startswith('db_'):
            retained = env.root / 'retained-A.sqlite3'
            env.a.store.path.rename(retained)
            state['retained_a'] = retained
            state['foreign_at'] = env.a.store.path
            if kind == 'db_rename':
                (env.image / 'autonomy.sqlite3').rename(env.a.store.path)
            else:
                env.a.store.path.symlink_to(env.b.store.path)
        else:
            retained = env.root / 'retained-A-control'
            env.a.directory.rename(retained)
            state['retained_a'] = retained / 'autonomy.sqlite3'
            state['foreign_at'] = env.a.store.path
            if kind == 'directory_rename':
                env.image.rename(env.a.directory)
            else:
                env.a.directory.symlink_to(env.b.directory, target_is_directory=True)
    return swap, state


def instrument(env, monkeypatch, phase, swap):
    original_connect = sqlite3.connect
    original_approved = console.approved_spec
    state = {'opens': 0, 'sql': []}
    target = env.a.store.path

    class Connection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            cursor = super().execute(sql, parameters)
            if (phase == 'after_plans' and self.index == 2
                    and parameters == (len('techlead:plans:'), 'techlead:plans:')):
                swap()
            return cursor

    def connect(path, *args, **kwargs):
        text = str(path)
        if text == str(target) or text.startswith(target.as_uri() + '?'):
            state['opens'] += 1
            index = state['opens']
            if phase == 'at_open' and index == 2:
                swap()
            assert 'factory' not in kwargs
            db = original_connect(path, *args, factory=Connection, **kwargs)
            db.index = index
            db.set_trace_callback(lambda sql: state['sql'].append((index, sql)))
            return db
        return original_connect(path, *args, **kwargs)

    def approved(directory):
        result = original_approved(directory)
        if phase == 'after_gate' and directory == env.a.directory:
            swap()
        return result

    monkeypatch.setattr(console.sqlite3, 'connect', connect)
    monkeypatch.setattr(console, 'approved_spec', approved)
    return state


@pytest.mark.parametrize('mode', ['warm', 'cold'])
@pytest.mark.parametrize('kind', ['db_rename', 'db_symlink', 'directory_rename', 'directory_symlink'])
@pytest.mark.parametrize('phase', ['after_gate', 'at_open', 'after_plans'])
def test_real_identity_substitution_rejected_without_foreign_readback(env, monkeypatch, mode, kind, phase):
    hub = selected(env, mode)
    swap, state = swapper(env, kind)
    with monkeypatch.context() as guard:
        read_guard(hub, guard)
        instrument(env, guard, phase, swap)
        with pytest.raises(PermissionError):
            hub.placements(env.ident)
    assert state['done'], 'requested real identity race was not reached'
    assert dump(state['retained_a']) == env.before_a
    assert dump(state['foreign_at']) == env.before_b
    assert dump(env.b.store.path) == env.before_b
    assert mode == 'warm' or hub._sessions == {}


@pytest.mark.parametrize('mode', ['warm', 'cold'])
@pytest.mark.parametrize('kind', ['db_rename', 'db_symlink', 'directory_rename', 'directory_symlink'])
def test_operator_get_identity_race_is_403_not_foreign_mission_200(env, monkeypatch, mode, kind):
    hub = selected(env, mode)
    swap, state = swapper(env, kind)
    with monkeypatch.context() as guard:
        read_guard(hub, guard)
        instrument(env, guard, 'after_gate', swap)
        code, value = call(hub, '/api/missions/' + env.ident + '/placements')
    assert state['done']
    assert code == 403 and set(value) == {'error'}
    assert value['error']['type'] == 'PermissionError'
    assert env.pin['node_id'] not in json.dumps(value) and 'placements' not in value
    assert dump(state['retained_a']) == env.before_a
    assert dump(state['foreign_at']) == env.before_b


@pytest.mark.parametrize('mode', ['warm', 'cold'])
@pytest.mark.parametrize('change', ['schema', 'source', 'roles', 'foreign_binding'])
def test_native_spec_binding_changed_after_gate_is_rejected_in_read_snapshot(env, monkeypatch, mode, change):
    hub = selected(env, mode)
    original = console.approved_spec
    changed = copy.deepcopy(env.a.spec)
    if change == 'schema':
        changed['schema_version'] = 'foreign-schema'
    elif change == 'source':
        changed['source'] = str(env.a.directory)
    elif change == 'roles':
        changed['roles'] = None
    else:
        changed = copy.deepcopy(env.b.spec)
    after_write = []

    def approved(directory):
        result = original(directory)
        db = sqlite3.connect(env.a.store.path.as_uri() + '?mode=rw', uri=True, isolation_level=None)
        try:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE metadata SET value=? WHERE key='native_worker_spec'", (canonical_json(changed),))
            db.execute('COMMIT')
        finally:
            db.close()
        after_write.extend(dump(env.a.store.path))
        return result

    with monkeypatch.context() as guard:
        read_guard(hub, guard)
        guard.setattr(console, 'approved_spec', approved)
        with pytest.raises(PermissionError):
            hub.placements(env.ident)
    assert after_write and dump(env.a.store.path) == after_write
    assert dump(env.b.store.path) == env.before_b
    assert mode == 'warm' or hub._sessions == {}


@pytest.mark.parametrize('mode', ['warm', 'cold'])
def test_bound_spec_and_task_pin_queries_share_one_original_readonly_snapshot(env, monkeypatch, mode):
    hub = selected(env, mode)
    before = dump(env.a.store.path)
    with monkeypatch.context() as guard:
        read_guard(hub, guard)
        observed = instrument(env, guard, 'observe', forbidden)
        assert hub.placements(env.ident) == {'mission_id': env.ident, 'placements': [
            {'task_id': 'build', 'placement': {'kind': 'local'}}]}
    assert observed['opens'] == 2
    reads = [(index, sql) for index, sql in observed['sql'] if sql.lstrip().startswith('SELECT')]
    projection_connection = next(index for index, sql in reads if 'techlead:plans:' in sql)
    binding = [sql for index, sql in reads if index == projection_connection and 'native_worker_spec' in sql]
    assert len(binding) == 1, 'native schema/source/roles binding was not read in task/pin snapshot'
    snapshot = [sql for index, sql in observed['sql'] if index == projection_connection]
    assert next(i for i, sql in enumerate(snapshot) if 'BEGIN' in sql) < snapshot.index(binding[0])
    assert snapshot.index(binding[0]) < next(i for i, sql in enumerate(snapshot) if 'techlead:plans:' in sql)
    assert sum('techlead:placement:' in sql for sql in snapshot) == 1
    assert not any(sql.lstrip().split()[0].upper() in {'CREATE', 'INSERT', 'UPDATE', 'DELETE'} for sql in snapshot)
    assert dump(env.a.store.path) == before and dump(env.b.store.path) == env.before_b


def test_cached_store_is_bound_to_selected_database_identity(env, monkeypatch):
    with monkeypatch.context() as guard:
        read_guard(env.h, guard)
        guard.setattr(env.a.journal.store, 'path', env.b.store.path)
        with pytest.raises(PermissionError):
            env.h.placements(env.ident)
    assert dump(env.a.store.path) == env.before_a
    assert dump(env.b.store.path) == env.before_b


@pytest.mark.parametrize('mode', ['warm', 'cold'])
def test_database_identity_must_be_regular_single_link_not_an_alias(env, monkeypatch, mode):
    hub = selected(env, mode)
    alias = env.root / 'retained-database-hardlink.sqlite3'
    os.link(env.a.store.path, alias)
    assert env.a.store.path.lstat().st_nlink == 2
    with monkeypatch.context() as guard:
        read_guard(hub, guard)
        with pytest.raises(PermissionError):
            hub.placements(env.ident)
    assert alias.is_file() and dump(env.a.store.path) == env.before_a
