"""Frozen supersession commit boundary: correct static-reviewed public shapes.

Synthetic fixtures only. History/event/current replacement are one canonical
transaction. Every injected interruption is retained, never retried by readback.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import threading

import pytest

from sisyfus.workers.lead_console import MissionHub
from sisyfus.workers.lead_mission import LeadMission
from sisyfus.workers.protocol import digest
from test_lead_mission import Stub, make_spec, mission

OLD = 'atomic_prepare_old_0001'
NEW = 'atomic_prepare_new_0002'


def current(m):
    return m.snapshot()['placement_preparation']


def history(m):
    return m.journal.get('placement_preparation_history', OLD)


def proof(m):
    with m.store._transaction(immediate=False) as db:
        rows = db.execute("SELECT key,value FROM metadata WHERE key LIKE 'techlead:placement_preparation%' ORDER BY key").fetchall()
    return digest([tuple(r) for r in rows]), m.store.verify_event_chain(), digest(m.continuations()), digest(m.spec)


def factory(directory, spec=None):
    m = LeadMission(directory, spec)
    def forbidden(*args):
        pytest.fail('atomic preparation dispatched Sol')
    m.drivers = {'claude':Stub('claude'), 'codex':Stub('codex', forbidden)}
    return m


class Crash(KeyboardInterrupt):
    pass


def inject(m, monkeypatch, boundary):
    """Actual original-store transaction failures; no emulated journal truth."""
    if boundary == 'before_replacement':
        original = m.store._transaction
        class Connection:
            def __init__(self, db): self.db = db
            def __getattr__(self, name): return getattr(self.db, name)
            def execute(self, sql, parameters=()):
                if (sql.startswith('INSERT OR REPLACE INTO metadata') and parameters and
                        parameters[0] == m.journal.prefix + 'placement_preparation' and
                        json.loads(parameters[1])['request_id'] == NEW):
                    archive = self.db.execute('SELECT value FROM metadata WHERE key=?',
                        (m.journal.prefix+'placement_preparation_history:'+OLD,)).fetchone()
                    assert archive is not None, 'history must precede replacement inside the same transaction'
                    assert json.loads(archive[0])['data']['status'] == 'SUPERSEDED'
                    raise Crash('fixture interruption after history, before new metadata')
                return self.db.execute(sql, parameters)
        @contextmanager
        def transaction(*args, **kwargs):
            with original(*args, **kwargs) as db:
                yield Connection(db)
        monkeypatch.setattr(m.store, '_transaction', transaction)
    else:
        original = m.journal._event
        def event(db, kind, key, data, *args, **kwargs):
            result = original(db, kind, key, data, *args, **kwargs)
            if boundary == 'history_event' and kind == 'lead_placement_preparation_history' and key == OLD:
                raise RuntimeError('fixture history event callback failure')
            if boundary == 'replacement_event' and kind == 'placement_preparation' and key == NEW:
                raise Crash('fixture current preparation event callback failure')
            return result
        monkeypatch.setattr(m.journal, '_event', event)


@pytest.mark.parametrize('status', ['REQUESTED', 'BLOCKED'])
@pytest.mark.parametrize('boundary', ['before_replacement', 'history_event', 'replacement_event'])
def test_supersession_failure_rolls_back_history_current_and_event_chain(tmp_path, monkeypatch, status, boundary):
    m = mission(tmp_path, make_spec(tmp_path, initial=False))
    old = m._request_placement_preparation(OLD)
    if status == 'BLOCKED':
        old = m._save_placement_preparation({**old, 'status':status, 'reason':'fixture preflight blocked'})
    before = proof(m)
    with monkeypatch.context() as patch:
        inject(m, patch, boundary)
        with pytest.raises((Crash, RuntimeError)):
            m._request_placement_preparation(NEW)
    assert current(m) == old and history(m) is None
    assert proof(m) == before
    restarted = mission(tmp_path, None)
    assert restarted._request_placement_preparation(OLD) == old
    assert proof(restarted) == before
    assert not any(d.requests for d in restarted.drivers.values())
    fresh = restarted._request_placement_preparation(NEW)
    assert fresh['request_id'] == NEW and fresh['previous_request_id'] == OLD
    assert fresh['acceptance_hash'] == old['acceptance_hash'] and fresh['known_nonexecuted'] is True
    assert history(restarted) == {**old, 'status':'SUPERSEDED'}
    once = proof(restarted)
    assert restarted._request_placement_preparation(NEW) == fresh
    assert restarted.prepare_for_placement(OLD)['placement_preparation'] == history(restarted)
    assert proof(restarted) == once
    assert not any(d.requests for d in restarted.drivers.values())


def test_recorded_hub_old_control_retry_after_failed_supersession_is_readonly(tmp_path, monkeypatch):
    h = MissionHub(tmp_path/'hub', mission_factory=factory)
    ident = h.create(make_spec(tmp_path, initial=False))['id']
    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, 'start', lambda self: None)
        ack = h.prepare_placement(ident, OLD, allow_planning=True)
    m = h._session(ident).mission
    assert h.snapshot(ident)['snapshot']['placement_preparation']['request_id'] == OLD
    before = proof(m)
    with monkeypatch.context() as patch:
        inject(m, patch, 'before_replacement')
        with pytest.raises(Crash):
            m._request_placement_preparation(NEW)
    restarted = MissionHub(tmp_path/'hub', mission_factory=factory)
    try:
        again = restarted._session(ident).mission
        assert restarted.prepare_placement(ident, OLD, allow_planning=True) == ack
        snap = restarted.snapshot(ident)
        assert snap['snapshot']['placement_preparation']['request_id'] == OLD
        assert snap['controller']['running'] is False and restarted._session(ident).thread is None
        assert history(again) is None and proof(again) == before
        assert not any(d.requests for d in again.drivers.values())
        assert again.run(max_cycles=1)['placement_preparation']['request_id'] == OLD
        assert not any(d.requests for d in again.drivers.values())
    finally:
        restarted.close(); h.close()


@pytest.mark.parametrize('initial', [False, True])
def test_successful_atomic_pair_legacy_record_shape_and_stale_request_no_planning(tmp_path, monkeypatch, initial):
    m = mission(tmp_path, make_spec(tmp_path, initial=initial))
    old = m._request_placement_preparation(OLD)
    saved = m._request_placement_preparation(NEW)
    envelope = m.journal.records('placement_preparation_history')[0]
    assert set(envelope) == {'key','created_at','data'} and envelope['key'] == OLD
    assert envelope['data'] == {**old, 'status':'SUPERSEDED'}
    assert saved['previous_request_id'] == OLD and saved['status'] == 'REQUESTED'
    baseline = proof(m)
    original = m._initial_plan
    def forbidden(): pytest.fail('stale superseded preparation started planning')
    with monkeypatch.context() as patch:
        patch.setattr(m, '_initial_plan', forbidden)
        assert m.prepare_for_placement(OLD)['placement_preparation'] == envelope['data']
    assert proof(m) == baseline and not any(d.requests for d in m.drivers.values())
    result = m.prepare_for_placement(NEW)
    assert result['phase'] == 'WAITING_PLACEMENT' and result['placement_preparation']['request_id'] == NEW
    assert history(m) == envelope['data'] and not m.drivers['codex'].requests
    assert len(m.drivers['claude'].requests) == int(not initial)
    assert {t['id']:digest(t) for t in m.active_tasks()} == result['placement_preparation']['task_hashes']
    after = proof(m)
    assert m.prepare_for_placement(OLD)['placement_preparation'] == envelope['data']
    assert proof(m) == after and m.store.verify_event_chain()['valid']


def test_history_and_replacement_events_are_one_connection_and_one_commit(tmp_path, monkeypatch):
    m = mission(tmp_path, make_spec(tmp_path))
    m._request_placement_preparation(OLD)
    original_transaction = m.store._transaction
    original_event = m.journal._event
    commits, event_connections = [], []
    @contextmanager
    def transaction(*args, **kwargs):
        with original_transaction(*args, **kwargs) as db:
            yield db
            if not kwargs.get('immediate') is False:
                commits.append(id(db))
    def event(db, kind, key, data, *args, **kwargs):
        if kind == 'lead_placement_preparation_history' and key == OLD or kind == 'placement_preparation' and key == NEW:
            event_connections.append((kind,id(db)))
        return original_event(db, kind, key, data, *args, **kwargs)
    monkeypatch.setattr(m.store, '_transaction', transaction)
    monkeypatch.setattr(m.journal, '_event', event)
    m._request_placement_preparation(NEW)
    assert [kind for kind,_ in event_connections] == ['lead_placement_preparation_history','placement_preparation']
    assert event_connections[0][1] == event_connections[1][1]
    assert len(commits) == 1
