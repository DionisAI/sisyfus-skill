"""Frozen v3c boundary: monotonic expiry never becomes a late HTTP rejection.

Real authenticated loopback and real public NodeClaims commits. The actual
Timer thread is held after its wait expires, simulating late scheduling only;
clock, backend transactions, payloads and results stay real and unchanged.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
import socket
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from sisyfus.workers import node_gateway as gateway_module
from sisyfus.workers.node_gateway import NodeGateway
from sisyfus.workers.protocol import Receipt
from sisyfus.workers.remote_artifacts import full_tree_manifest
from test_node_gateway import call, env, fields, forbidden_native, offer, state


DEADLINE = .6


@pytest.fixture
def gateway_type():
    class ShortGateway(NodeGateway):
        request_timeout = DEADLINE
    return ShortGateway


@pytest.fixture
def delayed_timers(monkeypatch):
    assert os.environ.get('SISYFUS_TEST_LOOPBACK') == '1'
    real_timer = threading.Timer
    gate = SimpleNamespace(due=threading.Event(), release=threading.Event(), calls=0, timers=[])

    class SchedulingDelayedTimer(real_timer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            gate.timers.append(self)

        def run(self):
            try:
                if self.finished.wait(self.interval):
                    return
                gate.due.set()
                while not gate.release.wait(.002):
                    if self.finished.is_set():
                        return  # Real cancellation still unblocks finish/join.
                if not self.finished.is_set():
                    gate.calls += 1
                    self.function(*self.args, **self.kwargs)
            finally:
                self.finished.set()

    monkeypatch.setattr(gateway_module.threading, 'Timer', SchedulingDelayedTimer)
    yield gate
    gate.release.set()
    for timer in gate.timers:
        timer.cancel()
        timer.join(timeout=3)
        assert not timer.is_alive()


def wait_for(predicate, seconds=3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(.01)
    return bool(predicate())


def wire(e, operation, *, method='POST', body=None, raw=None, query=None, headers=()):
    target = '/node/v1/' + e.ident + '/' + operation
    if query is not None:
        target += '?' + urlencode(query)
    if raw is None:
        raw = json.dumps(body, allow_nan=False).encode() if body is not None else b''
    defaults = [('Host', '127.0.0.1:' + str(e.gateway.server_port)),
                ('Authorization', 'Node ' + e.node['secret']), ('X-Sisyfus-Node', e.node['node_id'])]
    if method != 'GET':
        defaults += [('Content-Length', str(len(raw))),
                     ('Content-Type', 'application/octet-stream' if method == 'PUT' else 'application/json')]
    replaced = {name.lower() for name, _ in headers}
    head = (f'{method} {target} HTTP/1.1\r\n' + ''.join(
        f'{name}: {value}\r\n' for name, value in [*(x for x in defaults if x[0].lower() not in replaced), *headers]) + '\r\n').encode()
    result = bytearray()
    with socket.create_connection(('127.0.0.1', e.gateway.server_port), timeout=3) as connection:
        connection.sendall(head + raw)
        while True:
            try:
                data = connection.recv(65536)
            except ConnectionResetError:
                break  # A closed peer is acceptable; any prior bytes are not.
            if not data:
                break
            result.extend(data)
    return bytes(result)


def assert_retired(e, gate, baseline, caplog, capsys):
    assert gate.calls == 0, 'deadline must be enforced before delayed timer callback runs'
    assert wait_for(lambda: not any(t not in baseline and t.is_alive() for t in threading.enumerate()))
    assert all(not timer.is_alive() for timer in gate.timers)
    assert call(e, body={}, headers=[('Authorization', '')])[0] == 401, 'capacity must be reusable'
    assert wait_for(lambda: all(not timer.is_alive() for timer in gate.timers))
    observed = caplog.text + capsys.readouterr().err
    assert e.node['secret'] not in observed and 'Authorization: Node' not in observed and 'Traceback' not in observed


def prepared(e, operation):
    claims = offer(e, transport=True)
    if operation == 'claim':
        return claims, {'body': {'request_id': 'response_deadline_claim_01'}}, None
    c = claims.claim(e.node['node_id'], 'response_deadline_initial_01')['claim']
    if operation == 'heartbeat':
        e.clock.advance(2)
        return claims, {'body': fields(c)}, c
    if operation == 'sync':
        e.clock.advance(2)
        return claims, {'body': fields(c) | {'events': [
            {'seq': 1, 'kind': 'session_bound', 'data': {'session_id': 'fixed-response-session'}}]}}, c
    data = b'result'
    entry = {'path': 'result.txt', 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}
    if operation == 'upload':
        return claims, {'method': 'PUT', 'raw': data, 'query': {key: entry[key] for key in ('path', 'sha256')}}, c
    claims.upload(e.node['node_id'], c['claim_id'], c['epoch'], entry['path'], entry['sha256'], data)
    tree = e.root / 'node-response-tree'
    tree.mkdir()
    (tree / 'input.txt').write_bytes(b'fixed input')
    (tree / 'result.txt').write_bytes(data)
    return claims, {'body': fields(c) | {'receipt': asdict(Receipt('COMPLETED', requested_model='gpt-6.1-sol')),
                                       'manifest': [entry], 'tree': full_tree_manifest(tree)}}, c


@pytest.mark.parametrize('operation', ['claim', 'upload', 'receipt', 'heartbeat', 'sync'])
def test_committed_transport_fact_survives_expiry_without_late_400(
        env, monkeypatch, delayed_timers, caplog, capsys, operation):
    e, gate = env, delayed_timers
    claims, request, c = prepared(e, operation)
    original = getattr(claims, operation)
    baseline = set(threading.enumerate())
    committed, after_commit = [], []

    def real_commit_then_late_return(*args, **kwargs):
        result = original(*args, **kwargs)
        committed.append(result)
        after_commit.append(state(e))
        assert gate.due.wait(3), 'real monotonic setup budget must expire'
        return result

    monkeypatch.setattr(claims, operation, real_commit_then_late_return)
    target = 'uploads/' + c['claim_id'] + '/' + str(c['epoch']) if operation == 'upload' else operation
    received = wire(e, target, **request)
    monkeypatch.setattr(claims, operation, original)
    assert_retired(e, gate, baseline, caplog, capsys)
    assert len(committed) == 1 and state(e) == after_commit[0]
    view = claims.get(e.key)
    assert view['node_id'] == e.node['node_id'] and view['epoch'] == 1
    assert view['status'] == ('RECEIPTED' if operation == 'receipt' else 'CLAIMED')
    assert e.mission.journal.runs()[0]['status'] == 'IN_FLIGHT', 'gateway never completes core/native acceptance'
    assert e.mission.store.verify_event_chain()['valid']
    # An unexpired new connection can read the retained owner fact. Replay
    # restores the same identity/result; it is not a new native reservation.
    owner = view['claim_id']
    before_read = state(e)
    status, readback = call(e, 'status', body={'claim_id': owner, 'epoch': 1})
    assert status == 200 and readback['result']['status'] == view['status'] and state(e) == before_read
    assert call(e, 'status', body={'claim_id': owner, 'epoch': 1}, node=e.other)[0] == 403
    assert state(e) == before_read
    if operation in {'claim', 'upload', 'receipt', 'sync'}:
        replay = call(e, target, **request)
        assert replay == (200, {'controller_mission_id': e.ident, 'result': committed[0]})
        assert state(e) == before_read, 'replay must not duplicate commit/event or reservation'
    if operation == 'claim':
        e.clock.advance(31)
        claims.expire()
        assert claims.get(e.key)['status'] == 'UNKNOWN'
        assert call(e, body={'request_id': 'response_deadline_new_01'})[1]['result']['status'] == 'NO_WORK'
        assert claims.get(e.key)['claim_id'] == owner and len(e.mission.journal.runs()) == 1
    assert received == b'', 'monotonic expiry must close without any late HTTP status/body'


@pytest.mark.parametrize('kind', ['success_json', 'success_binary', 'error400', 'error401', 'error403', 'error404', 'error409'])
def test_send_boundary_suppresses_success_and_error_bytes_after_budget(
        env, monkeypatch, delayed_timers, caplog, capsys, kind):
    e, gate = env, delayed_timers
    request = {'body': {'request_id': 'response_deadline_send_01'}}
    target = 'claim'
    read_only = kind != 'success_json'
    if kind in {'success_binary', 'error404', 'error409'}:
        claims = offer(e, transport=True)
        c = claims.claim(e.node['node_id'], 'response_deadline_send_initial')['claim']
        if kind == 'error409':
            target, request = 'status', {'body': fields(c) | {'epoch': 2}}
        else:
            target = 'inputs/' + c['claim_id'] + '/1'
            request = {'method': 'GET', 'query': {'path': 'input.txt' if kind == 'success_binary' else 'absent.txt'}}
    elif kind == 'error400':
        request['body']['extra'] = 'fixed untrusted data'
    elif kind == 'error401':
        request['headers'] = [('Authorization', 'Node ' + 'f' * 64)]
    elif kind == 'error403':
        request['headers'] = [('Origin', 'http://127.0.0.1:' + str(e.gateway.server_port))]
    if kind in {'error400', 'error401', 'error403'}:
        monkeypatch.setattr(e.hub, '_session', forbidden_native)
    before = state(e)
    baseline = set(threading.enumerate())
    original_send = gateway_module._Handler._send
    statuses, expired = [], []

    def late_real_send(handler, value, status=200, **kwargs):
        statuses.append(status)
        assert gate.due.wait(3)
        expired.append(time.monotonic() >= handler._deadline)
        return original_send(handler, value, status, **kwargs)

    monkeypatch.setattr(gateway_module._Handler, '_send', late_real_send)
    received = wire(e, target, **request)
    monkeypatch.setattr(gateway_module._Handler, '_send', original_send)
    assert_retired(e, gate, baseline, caplog, capsys)
    assert expired and all(expired)
    assert statuses[0] == (200 if kind.startswith('success') else int(kind[5:]))
    if read_only:
        assert state(e) == before
    else:
        before_replay = state(e)
        assert call(e, body=request['body'])[0] == 200
        assert state(e) == before_replay, 'committed empty claim request must replay once'
    assert received == b'', 'neither success nor error _send may emit a byte after setup deadline'


def test_postcommit_revocation_never_sends_late_permission_rejection(
        env, monkeypatch, delayed_timers, caplog, capsys):
    e, gate = env, delayed_timers
    claims = offer(e, transport=True)
    original = claims.claim
    baseline = set(threading.enumerate())
    results, retained = [], []

    def commit_then_revoke_after_deadline(*args, **kwargs):
        result = original(*args, **kwargs)
        results.append(result)
        assert gate.due.wait(3)
        e.registry.revoke(e.node['node_id'])
        retained.append(state(e))
        return result

    monkeypatch.setattr(claims, 'claim', commit_then_revoke_after_deadline)
    received = wire(e, 'claim', body={'request_id': 'response_deadline_revoke_01'})
    monkeypatch.setattr(claims, 'claim', original)
    assert_retired(e, gate, baseline, caplog, capsys)
    assert len(results) == 1 and results[0]['status'] == 'CLAIMED' and state(e) == retained[0]
    view = claims.get(e.key)
    assert view['claim_id'] == results[0]['claim']['claim_id'] and view['status'] == 'CLAIMED'
    assert e.registry.inventory()[0]['status'] == 'REVOKED'
    assert call(e, body={'request_id': 'response_deadline_revoke_01'})[0] == 403
    assert state(e) == retained[0] and e.mission.store.verify_event_chain()['valid']
    assert received == b'', 'postcommit identity fencing is still close-only after expiry'


def test_early_completion_cancels_delayed_timer_without_cross_connection_effect(env, delayed_timers):
    e, gate = env, delayed_timers
    assert call(e, body={'request_id': 'response_deadline_early_01'})[0] == 200
    assert wait_for(lambda: all(not timer.is_alive() for timer in gate.timers))
    time.sleep(DEADLINE + .05)
    gate.release.set()
    assert call(e, body={'request_id': 'response_deadline_later_01'})[0] == 200
    assert wait_for(lambda: all(not timer.is_alive() for timer in gate.timers))
    assert gate.calls == 0 and not e.mission.journal.runs()
