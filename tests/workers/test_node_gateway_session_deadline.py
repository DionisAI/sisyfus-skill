"""Frozen review-v2 regressions using the real authenticated loopback service.

Delays release real Hub/session/factory work, never a fabricated backend result.
The whole connection deadline must precede lazy writable NodeClaims setup.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time

import pytest

from sisyfus.workers.node_gateway import NodeGateway
from test_node_gateway import call, env, forbidden_native, state


DEADLINE = .4


@pytest.fixture
def gateway_type():
    class ShortGateway(NodeGateway):
        request_timeout = DEADLINE
    return ShortGateway


def wait_for(predicate, seconds=3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(.01)
    return bool(predicate())


@pytest.mark.parametrize('boundary', ['slow_session', 'hub_lock', 'mission_factory'])
def test_expired_session_never_constructs_writable_node_backend(
        env, monkeypatch, caplog, capsys, boundary):
    assert os.environ.get('SISYFUS_TEST_LOOPBACK') == '1'
    e = env
    original_session = e.hub._session
    original_factory = e.hub.mission_factory
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    baseline_threads = set(threading.enumerate())
    constructed = []
    lock_owned = False

    def real_session_after_delay(ident):
        entered.set()
        try:
            if boundary == 'slow_session':
                assert release.wait(5), 'fixture must release delayed real session'
            return original_session(ident)
        finally:
            exited.set()

    def real_factory_after_delay(*args, **kwargs):
        entered.set()
        assert release.wait(5), 'fixture must release real LeadMission constructor'
        mission = original_factory(*args, **kwargs)
        for driver in mission.drivers.values():
            monkeypatch.setattr(driver, 'run', forbidden_native)
        constructed.append(mission)
        return mission

    if boundary == 'mission_factory':
        # Drop only an in-memory cache entry: all canonical files/receipts remain.
        e.hub._sessions.pop(e.ident)
        monkeypatch.setattr(e.hub, 'mission_factory', real_factory_after_delay)
    elif boundary == 'hub_lock':
        e.hub._lock.acquire()
        lock_owned = True
    monkeypatch.setattr(e.hub, '_session', real_session_after_delay)

    before = state(e)
    client = socket.create_connection(('127.0.0.1', e.gateway.server_port), timeout=2)
    body = json.dumps({'request_id': 'session_deadline_01'}).encode()
    request = (f'POST /node/v1/{e.ident}/claim HTTP/1.1\r\n'
               f'Host: 127.0.0.1:{e.gateway.server_port}\r\n'
               f'Authorization: Node {e.node["secret"]}\r\n'
               f'X-Sisyfus-Node: {e.node["node_id"]}\r\n'
               'Content-Type: application/json\r\n'
               f'Content-Length: {len(body)}\r\n\r\n').encode() + body
    try:
        started = time.monotonic()
        client.sendall(request)
        assert entered.wait(2), 'authenticated request reached real session boundary'
        assert not exited.is_set()
        # The deadline closes the connection while the real session is blocked.
        assert client.recv(4096) == b'', 'expired connection must not receive an HTTP response'
        assert time.monotonic() - started < DEADLINE + .8
        assert not (e.mission.directory / 'remote').exists()
        release.set()
        if lock_owned:
            e.hub._lock.release()
            lock_owned = False
        assert exited.wait(3)
        assert wait_for(lambda: not any(t not in baseline_threads and t.is_alive()
                                       for t in threading.enumerate())), 'handler/timer must retire'
        assert state(e) == before, 'expired request must add no node metadata/event or other state'
        assert not (e.mission.directory / 'remote').exists()
        assert e.mission._node_claims is None
        assert all(m._node_claims is None for m in constructed)
        assert not e.mission.journal.runs()
        if boundary == 'mission_factory':
            assert len(constructed) == 1, 'the actual constructor was exercised'
        # Admission is usable again; this probe performs readonly invalid auth.
        assert call(e, body={}, headers=[('Authorization', '')])[0] == 401
        assert state(e) == before
        observed = caplog.text + capsys.readouterr().err
        assert e.node['secret'] not in observed and 'Traceback' not in observed
    finally:
        release.set()
        if lock_owned:
            e.hub._lock.release()
        client.close()
        assert exited.wait(3)
