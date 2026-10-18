"""Frozen N5 v2 four-cause microtests; real leased controller/loopback fixtures.

Node-only clock injection never patches the controller wall clock. Native work
is an injected protocol fixture, not a provider/model. All crash/unknown/outbox
and raw terminal bytes remain retained; original116/10/public13 are untouched.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from sisyfus.workers.node_claims import _receipt_payload
from sisyfus.workers.protocol import Receipt, Request, digest, environment, redact
from sisyfus.workers.remote_artifacts import full_tree_manifest
from test_node_agent import AgentDriver, agent_env, agent_type, execute, lose_response


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _local(e):
    db = sqlite3.connect((e.state / 'agent.sqlite3').as_uri() + '?mode=ro', uri=True, timeout=.5)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        rows = db.execute('SELECT * FROM attempts').fetchall()
        assert len(rows) == 1
        raw = dict(rows[0]); parsed = dict(raw)
        for key in ('offer', 'receipt', 'tree', 'receipt_body'):
            parsed[key] = json.loads(raw[key]) if raw[key] else None
        events = [dict(row) for row in db.execute('SELECT * FROM outbox ORDER BY seq')]
        return parsed, raw, events
    finally:
        db.close()


def _publish(e):
    """Actual core continuation token/lease, not SQL-manufactured lease truth."""
    e.v2_source = full_tree_manifest(e.source)
    e.v2_snapshot = full_tree_manifest(e.snapshot)
    e.v2_acceptance = digest(e.mission.spec)
    cont = e.mission.store.claim_due_continuation('v2-micro-controller', lease_seconds=30)
    assert cont is not None and cont['context']['native_task'] == 'build'
    e.v2_cont = cont
    e.mission.journal.record('roles', e.key, {'role': 'worker', 'driver': 'codex',
        'model': 'gpt-6.1-sol', 'mode': 'workspace-write', 'cwd': e.request.cwd})
    e.mission.journal.reserve(e.key, 'build', digest(asdict(e.request)),
        continuation_id=cont['id'], lease_token=cont['lease_token'],
        on_reserved=lambda db: e.mission.inbox.bind(db, e.key, role='worker', task_id='build', prompt=e.request.prompt))
    context = e.mission.inbox.for_run(e.key)
    if context:
        e.request = Request(**(asdict(e.request) | {'prompt': context['prompt']}))
    e.claims.bind_input_snapshot(e.key, e.snapshot, e.manifest)
    return e.claims.offer(e.key, e.node['node_id'], e.request, e.manifest)


def _status(e):
    local = _local(e)[0]
    claim = local['offer']
    return e.claims.status(e.node['node_id'], claim['claim_id'], claim['epoch'])


def _assert_core(e):
    core = e.mission.journal.runs()[0]
    assert core['status'] == 'IN_FLIGHT' and core['receipt'] is None and core['verdict'] == 'UNVERIFIED'
    cont = e.mission.store.get_continuation(e.v2_cont['id'])
    assert cont['lease_token'] == e.v2_cont['lease_token']
    assert datetime.fromisoformat(cont['lease_expires_at'].replace('Z', '+00:00')) > datetime.now(timezone.utc)
    assert digest(e.mission.spec) == e.v2_acceptance and not e.mission.snapshot()['all_verified']
    assert not e.mission.journal.records('reviews') and e.mission.integration_continuation() is None
    assert full_tree_manifest(e.source) == e.v2_source and full_tree_manifest(e.snapshot) == e.v2_snapshot
    assert e.mission.store.verify_event_chain()['valid']


def _assert_stored(e, expected):
    status = _status(e)
    entries = [{'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
               for path, data in sorted(expected.items())]
    assert status['manifest'] == entries
    assert status['uploads'] == [item | {'status': 'STORED'} for item in entries]
    for item in entries:
        assert (e.claims.artifact_root / status['claim_id'] / item['path']).read_bytes() == expected[item['path']]
    assert set(status['tree']) == {'schema', 'files', 'tree', 'errors', 'complete'}
    assert status['tree'] == _local(e)[0]['tree']
    return status


def _wait_controls(controls, seconds=1.2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = controls()
        if value:
            return value
        time.sleep(.01)
    return []


class NodeClock:
    """Only NodeAgent's module clock changes; controller UTC stays real."""
    def __init__(self, wall=0):
        self.wall = wall
        self.elapsed = 0
    def time(self):
        return time.time() + self.wall
    def monotonic(self):
        return time.monotonic() + self.elapsed


def test_local_404_cooperative_stop_does_not_skip_live_controller_uploads(agent_env, monkeypatch):
    e = agent_env; _publish(e)
    heartbeat = e.claims.heartbeat
    calls = []
    def missing(node_id, claim_id, epoch, *, admit_response=None):
        calls.append(1)
        if len(calls) > 1:
            raise FileNotFoundError('fixture heartbeat endpoint unavailable, not expired ownership')
        return heartbeat(node_id, claim_id, epoch, admit_response=admit_response)
    monkeypatch.setattr(e.claims, 'heartbeat', missing)
    def native(request, emit, controls):
        assert _wait_controls(controls), 'local 404 must request cooperative stop'
        assert _status(e)['status'] == 'CLAIMED' and _status(e)['lease_expires_at'] > time.time()
        Path(request.cwd, 'result.txt').write_bytes(b'42')
        return Receipt('COMPLETED', requested_model=request.model)
    agent, driver = execute(e, AgentDriver(native))
    assert agent.run_once()['status'] == 'RECEIPTED'
    assert _local(e)[0]['lease_lost'] == 1 and len(driver.requests) == 1
    assert _assert_stored(e, {'result.txt': b'42'})['status'] == 'RECEIPTED'
    _assert_core(e)


@pytest.mark.parametrize('wall_offset', [-86400, 86400])
def test_node_wall_skew_does_not_override_controller_pre_native_heartbeat(agent_env, monkeypatch, wall_offset):
    e = agent_env; _publish(e)
    module = importlib.import_module('sisyfus.workers.node_agent')
    clock = NodeClock(wall_offset)
    monkeypatch.setattr(module, 'time', clock)
    agent, driver = execute(e)
    assert agent.run_once()['status'] == 'RECEIPTED'
    assert len(driver.requests) == 1 and _local(e)[0]['lease_lost'] == 0
    assert _assert_stored(e, {'result.txt': b'42'})['status'] == 'RECEIPTED'
    _assert_core(e)


def test_transient_heartbeat_retry_after_wall_skew_stays_live(agent_env, monkeypatch):
    e = agent_env; _publish(e)
    module = importlib.import_module('sisyfus.workers.node_agent')
    clock = NodeClock(); monkeypatch.setattr(module, 'time', clock)
    heartbeat = e.claims.heartbeat
    seen, resumed = [], threading.Event()
    def transient(node_id, claim_id, epoch, *, admit_response=None):
        seen.append(1)
        if len(seen) == 2:
            raise OSError('fixture transient heartbeat failure')
        result = heartbeat(node_id, claim_id, epoch, admit_response=admit_response)
        if len(seen) >= 3:
            resumed.set()
        return result
    monkeypatch.setattr(e.claims, 'heartbeat', transient)
    def native(request, emit, controls):
        clock.wall = 86400  # Skew starts only AFTER the real initial heartbeat.
        assert resumed.wait(1.2), 'transient failure must retry instead of wall-clock lease loss'
        assert controls() == [] and _local(e)[0]['lease_lost'] == 0
        return None
    agent, driver = execute(e, AgentDriver(native))
    assert agent.run_once()['status'] == 'RECEIPTED'
    assert len(driver.requests) == 1 and len(seen) >= 3
    _assert_stored(e, {'result.txt': b'42'}); _assert_core(e)


def test_local_monotonic_failure_budget_stops_but_does_not_make_upstream_late(agent_env, monkeypatch):
    e = agent_env; _publish(e)
    module = importlib.import_module('sisyfus.workers.node_agent')
    clock = NodeClock(-86400); monkeypatch.setattr(module, 'time', clock)
    heartbeat = e.claims.heartbeat; calls = []
    def unavailable(node_id, claim_id, epoch, *, admit_response=None):
        calls.append(1)
        if len(calls) > 1:
            raise OSError('fixture transient outage over local monotonic grace')
        return heartbeat(node_id, claim_id, epoch, admit_response=admit_response)
    monkeypatch.setattr(e.claims, 'heartbeat', unavailable)
    def native(request, emit, controls):
        clock.elapsed = 10000  # No controller clock/lease mutation; no request is in flight yet.
        assert _wait_controls(controls), 'finite retries must use elapsed local monotonic time'
        assert _status(e)['status'] == 'CLAIMED' and _status(e)['lease_expires_at'] > time.time()
        Path(request.cwd, 'result.txt').write_bytes(b'42')
        return Receipt('COMPLETED', requested_model=request.model)
    agent, driver = execute(e, AgentDriver(native))
    assert agent.run_once()['status'] == 'RECEIPTED'
    assert len(driver.requests) == 1 and _local(e)[0]['lease_lost'] == 1
    _assert_stored(e, {'result.txt': b'42'}); _assert_core(e)


CRASH_SCRIPT = '''import json,os,sys\nfrom pathlib import Path\nfrom scripts.test_retained import guard_deletion\nsys.addaudithook(guard_deletion)\nfrom sisyfus.workers.node_agent import NodeAgent\nclass Crash:\n def run(self,request,emit,controls):\n  Path(sys.argv[3]).write_text(json.dumps({'pid':os.getpid(),'native_calls':1,'task':request.task_id}))\n  emit('process_started',{'pid':os.getpid(),'driver':'codex'})\n  emit('session_bound',{'session_id':'v2-fixture-session'})\n  emit('turn_bound',{'session_id':'v2-fixture-session','turn_id':'v2-fixture-turn'})\n  emit('native_event',{'method':'fixture','params':{'text':'durable before process crash'}})\n  os._exit(73)\nNodeAgent(sys.argv[1],sys.argv[2],driver=Crash()).run_once()\n'''


@pytest.mark.parametrize('state', ['IN_FLIGHT', 'UNKNOWN'])
@pytest.mark.parametrize('sync_mode', ['live', 'lost_ack', 'expired'])
def test_restart_replays_original_outbox_without_new_native(agent_env, monkeypatch, state, sync_mode):
    e = agent_env
    if sync_mode == 'expired':
        e.claims.lease_seconds = .3
    _publish(e)
    marker = e.root / 'v2-native-call.json'
    if state == 'IN_FLIGHT':
        child_env = environment() | {'PYTHONPATH': str(Path(__file__).resolve().parents[2]) + os.pathsep +
            str(Path(__file__).resolve().parents[2] / 'src'), 'PYTHONDONTWRITEBYTECODE': '1'}
        result = subprocess.run([sys.executable, '-c', CRASH_SCRIPT, str(e.auth), str(e.state), str(marker)],
            cwd=Path(__file__).resolve().parents[2], env=child_env, timeout=8, capture_output=True)
        assert result.returncode == 73, result.stderr.decode(errors='replace')
    else:
        def crash(request, emit, controls):
            marker.write_text(json.dumps({'pid': os.getpid(), 'native_calls': 1, 'task': request.task_id}))
            emit('process_started', {'pid': os.getpid(), 'driver': 'codex'})
            emit('session_bound', {'session_id': 'v2-fixture-session'})
            emit('turn_bound', {'session_id': 'v2-fixture-session', 'turn_id': 'v2-fixture-turn'})
            emit('native_event', {'method': 'fixture', 'params': {'text': 'durable before process crash'}})
            raise KeyboardInterrupt('fixture interruption after original durable events')
        agent, _ = execute(e, AgentDriver(crash))
        with pytest.raises(KeyboardInterrupt):
            agent.run_once()
    before, raw, events = _local(e)
    assert before['status'] == state and before['receipt'] is None and before['ack'] == 0
    assert [row['seq'] for row in events] == [1, 2, 3, 4]
    if sync_mode == 'expired':
        time.sleep(.4)
        e.claims.expire()  # Genuine controller clock/claim expiry; core token stays live.
    elif sync_mode == 'lost_ack':
        dropped = lose_response(e, monkeypatch, '/sync')
    driver = AgentDriver(); restarted, _ = execute(e, driver)
    if sync_mode == 'lost_ack':
        with pytest.raises(RuntimeError, match='RemoteDisconnected'):
            restarted.run_once()
        assert len(dropped) == 1
        restarted, _ = execute(e, driver)
    assert restarted.run_once() == {'request_id': before['request_id'], 'status': 'UNKNOWN'}
    after, after_raw, after_events = _local(e)
    assert not driver.requests and json.loads(marker.read_text())['native_calls'] == 1
    assert after['status'] == 'UNKNOWN' and after['receipt'] is None
    assert after_raw['offer'] == raw['offer'] and after_events == events
    assert after['request_id'] == before['request_id'] and after['workspace'] == before['workspace']
    with e.mission.store._transaction(immediate=False) as db:
        accepted = db.execute('SELECT seq,raw_digest FROM remote_event_sync ORDER BY seq').fetchall()
        claims = db.execute('SELECT count(*) FROM remote_claim_requests').fetchone()[0]
    assert claims == 1
    if sync_mode == 'expired':
        assert accepted == [] and after['ack'] == 0 and after['lease_lost'] == 1
        assert _status(e)['status'] == 'UNKNOWN'
    else:
        assert [row[0] for row in accepted] == [1, 2, 3, 4] and after['ack'] == 4
        assert [row[1] for row in accepted] == [digest(json.loads(row['event'])) for row in events]
        assert _status(e)['status'] == 'CLAIMED' and after['lease_lost'] == 0
    again, _ = execute(e, driver)
    assert again.run_once()['status'] == 'UNKNOWN' and not driver.requests
    assert _local(e)[2] == events
    _assert_core(e)


@pytest.mark.parametrize('native_status', ['COMPLETED', 'ERROR'])
@pytest.mark.parametrize('drop_ack', [False, True])
def test_partial_dict_receipt_ack_defaults_do_not_rewrite_raw_facts(agent_env, monkeypatch, native_status, drop_ack):
    e = agent_env; _publish(e)
    native_fact = {'status': native_status, 'output': 'partial dictionary protocol result'}
    def native(request, emit, controls):
        Path(request.cwd, 'result.txt').write_bytes(b'42')
        return dict(native_fact)
    agent, driver = execute(e, AgentDriver(native))
    if drop_ack:
        dropped = lose_response(e, monkeypatch, '/receipt')
        with pytest.raises(RuntimeError, match='RemoteDisconnected'):
            agent.run_once()
        assert len(dropped) == 1
        _, original_raw, _ = _local(e)
        agent, _ = execute(e, driver)
    assert agent.run_once()['status'] == 'RECEIPTED'
    local, raw, _ = _local(e)
    assert local['status'] == 'DONE' and len(driver.requests) == 1
    assert raw['receipt'] == _json(native_fact) and local['receipt_body']['receipt'] == native_fact
    wire = _assert_stored(e, {'result.txt': b'42'})
    assert wire['receipt'] == redact(_receipt_payload(native_fact))
    assert wire['receipt']['requested_model'] is None and wire['receipt']['actual_model'] is None
    assert wire['receipt']['status'] == native_status
    if drop_ack:
        assert all(raw[key] == original_raw[key] for key in ('receipt', 'tree', 'receipt_body', 'offer'))
    again, _ = execute(e, driver)
    assert again.run_once()['status'] == 'RECEIPTED'
    replay = _local(e)[1]
    assert all(replay[key] == raw[key] for key in ('receipt', 'tree', 'receipt_body', 'offer'))
    assert len(driver.requests) == 1
    _assert_core(e)


@pytest.mark.parametrize('rejected_operation', ['sync', 'upload'])
def test_only_actual_controller_409_selects_stored_subset(agent_env, monkeypatch, rejected_operation):
    e = agent_env; e.claims.lease_seconds = .3; _publish(e)
    upload = e.claims.upload; attempts = []
    def upload_and_expire(node, claim, epoch, path, sha, data, *, admit_response=None):
        attempts.append(path)
        if path == 'result.txt':
            time.sleep(.4)
            e.claims.expire()
        return upload(node, claim, epoch, path, sha, data, admit_response=admit_response)
    monkeypatch.setattr(e.claims, 'upload', upload_and_expire)
    def native(request, emit, controls):
        Path(request.cwd, 'partial.txt').write_bytes(b'partial')
        Path(request.cwd, 'result.txt').write_bytes(b'42')
        emit('native_event', {'method': 'fixture', 'params': {'text': 'known terminal before real lease rejection'}})
        return Receipt('COMPLETED', requested_model=request.model)
    agent, driver = execute(e, AgentDriver(native))
    if rejected_operation == 'sync':
        sync = e.claims.sync
        def sync_after_expiry(node_id, claim_id, epoch, events, *, admit_response=None):
            time.sleep(.4)
            e.claims.expire()
            return sync(node_id, claim_id, epoch, events, admit_response=admit_response)
        monkeypatch.setattr(e.claims, 'sync', sync_after_expiry)
    assert agent.run_once()['status'] == 'RECONCILIATION_CANDIDATE'
    assert len(driver.requests) == 1 and _local(e)[0]['lease_lost'] == 1
    expected = {} if rejected_operation == 'sync' else {'partial.txt': b'partial'}
    status = _assert_stored(e, expected)
    assert status['receipt']['status'] == 'COMPLETED' and status['status'] == 'RECONCILIATION_CANDIDATE'
    assert {item['path'] for item in status['tree']['files']} >= {'partial.txt', 'result.txt'}
    assert attempts == ([] if rejected_operation == 'sync' else ['partial.txt', 'result.txt'])
    _assert_core(e)
