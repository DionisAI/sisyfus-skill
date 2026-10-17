"""Frozen N4 review boundaries: real isolated loopback, retained artifacts.

The public constructor stays NodeGateway(hub, *, port=0). A subclass may set
request_timeout (default 5 seconds, finite 0 < value <= 30) to shorten the
whole connection budget. Tests observe sockets/capacity/threads, not a chosen
timer or reader implementation. The original 192 gateway tests stay frozen.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import threading
import time
from types import SimpleNamespace

import pytest

from sisyfus.workers.node_gateway import MAX_REQUESTS, NodeGateway
from test_node_gateway import call, env, no_session, state


DEADLINE = 1.0
MARKER = 'UNTRUSTED_QUERY_CONTENT_MUST_NOT_BE_ECHOED'


@pytest.fixture(autouse=True)
def explicit_loopback_only():
    assert os.environ.get('SISYFUS_TEST_LOOPBACK') == '1'


@pytest.fixture
def gateway_type():
    class ShortDeadlineGateway(NodeGateway):
        request_timeout = DEADLINE
    return ShortDeadlineGateway


def wait_for(predicate, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(.015)
    return bool(predicate())


def new_threads(baseline):
    return [t.name for t in threading.enumerate() if t not in baseline and t.is_alive()]


def connect(e):
    return socket.create_connection(('127.0.0.1', e.gateway.server_port), timeout=.5)


def head(e, length):
    return (f'POST /node/v1/{e.ident}/claim HTTP/1.1\r\n'
            f'Host: 127.0.0.1:{e.gateway.server_port}\r\n'
            f'Authorization: Node {e.node["secret"]}\r\n'
            f'X-Sisyfus-Node: {e.node["node_id"]}\r\n'
            'Content-Type: application/json\r\n'
            f'Content-Length: {length}\r\n\r\n').encode()


def probe(e):
    # A complete unauthorized request observes admission only, never a backend.
    return call(e, body={}, headers=[('Authorization', '')])[0]


def drain_closed(connection, seconds=.25):
    wire = bytearray()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        connection.settimeout(max(.001, end - time.monotonic()))
        try:
            chunk = connection.recv(4096)
        except (ConnectionResetError, BrokenPipeError):
            return True, bytes(wire)
        except socket.timeout:
            return False, bytes(wire)
        if not chunk:
            return True, bytes(wire)
        wire.extend(chunk)
    return False, bytes(wire)


@pytest.mark.parametrize('operation,method', [
    ('claim', 'POST'), ('inputs/claim_' + 'a' * 32 + '/1', 'GET')])
@pytest.mark.parametrize('query', [MARKER, 'path=a&' + MARKER, 'path=%ff',
    '%ff=value', 'path=%c0%af', 'path=a&x=1&' + MARKER])
def test_malformed_query_diagnostic_is_fixed_content_free_before_backend(
        env, monkeypatch, caplog, operation, method, query):
    e = env
    no_session(e, monkeypatch)
    before = state(e)
    status, result = call(e, operation, method=method, query=query,
                          body={'request_id': 'boundary_query_01'} if method == 'POST' else None)
    assert status == 400
    assert result['error']['message'] == 'invalid URI query'
    observed = json.dumps(result) + caplog.text
    assert MARKER not in observed and query not in observed and e.node['secret'] not in observed
    assert state(e) == before and not (e.mission.directory / 'remote').exists()
    assert not e.mission.journal.runs()


@pytest.mark.parametrize('duration', [0, -1, True, None, '1', float('nan'), float('inf'), 31])
def test_deadline_configuration_is_finite_and_bounded_before_socket_setup(duration):
    class InvalidDeadlineGateway(NodeGateway):
        request_timeout = duration
    gateway = None
    try:
        with pytest.raises(ValueError):
            gateway = InvalidDeadlineGateway(SimpleNamespace(), port=0)
    finally:
        if gateway is not None:
            gateway.server_close()


@pytest.mark.parametrize('phase', ['headers', 'authenticated_body'])
def test_drip_clients_release_all_capacity_within_whole_connection_deadline(
        env, monkeypatch, caplog, capsys, phase):
    e = env
    no_session(e, monkeypatch)
    before = state(e)
    baseline = set(threading.enumerate())
    clients = []
    stop = threading.Event()
    dripper = None
    started = time.monotonic()
    try:
        for _ in range(MAX_REQUESTS):
            connection = connect(e)
            clients.append(connection)
            prefix = head(e, 4096)
            connection.sendall(prefix[:-2] + b'X-Drip: ' if phase == 'headers' else prefix + b'{')

        def drip():
            while not stop.wait(.04):
                for connection in clients:
                    try:
                        connection.sendall(b' ')
                    except OSError:
                        pass  # The peer deadline or fixture cleanup closes it.

        dripper = threading.Thread(target=drip, daemon=True)
        dripper.start()
        assert wait_for(lambda: probe(e) == 503, .3), 'fixture did not occupy all admitted slots'
        remaining = max(0, started + DEADLINE + 1.0 - time.monotonic())
        assert wait_for(lambda: probe(e) == 401, remaining), 'drip traffic retained admission past whole deadline'
        for connection in clients:
            closed, wire = drain_closed(connection)
            assert closed, 'expired connection still accepts header/body traffic'
            assert e.node['secret'].encode() not in wire
    finally:
        stop.set()
        for connection in clients:
            connection.close()
        if dripper is not None:
            dripper.join(timeout=1)
            assert not dripper.is_alive()
    assert wait_for(lambda: not new_threads(baseline), .4), new_threads(baseline)
    assert probe(e) == 401 and state(e) == before
    assert not (e.mission.directory / 'remote').exists() and not e.mission.journal.runs()
    observed = caplog.text + capsys.readouterr().err
    assert e.node['secret'] not in observed and 'Authorization: Node' not in observed


def test_header_and_authenticated_body_share_the_original_setup_deadline(env, monkeypatch, caplog):
    e = env
    no_session(e, monkeypatch)
    before = state(e)
    baseline = set(threading.enumerate())
    connection = connect(e)
    try:
        # Neither phase exceeds its own per-recv timeout; their total exceeds
        # the connection budget. A new timeout at body admission is insufficient.
        connection.sendall(head(e, 4096)[:-2])
        time.sleep(DEADLINE * .65)
        connection.sendall(b'\r\n{')
        time.sleep(DEADLINE * .55)
        closed, wire = drain_closed(connection)
        assert closed, 'body phase reset the setup deadline'
        assert e.node['secret'].encode() not in wire
    finally:
        connection.close()
    assert wait_for(lambda: not new_threads(baseline), .4), new_threads(baseline)
    assert state(e) == before and probe(e) == 401 and not e.mission.journal.runs()
    assert e.node['secret'] not in caplog.text


def test_completed_request_deadline_never_closes_a_later_connection(env):
    e = env
    baseline = set(threading.enumerate())
    assert call(e, body={'request_id': 'boundary_early_01'})[0] == 200
    time.sleep(DEADLINE * .55)
    body = json.dumps({'request_id': 'boundary_later_01'}).encode()
    connection = connect(e)
    response = None
    try:
        connection.sendall(head(e, len(body)) + body[:-1])
        # Cross the earlier request's deadline but remain within this one.
        time.sleep(DEADLINE * .65)
        connection.sendall(body[-1:])
        connection.settimeout(.5)
        response = http.client.HTTPResponse(connection)
        response.begin()
        value = json.loads(response.read())
        assert response.status == 200 and value['result']['status'] == 'NO_WORK'
        assert value['controller_mission_id'] == e.ident
    finally:
        if response is not None:
            response.close()
        connection.close()
    assert wait_for(lambda: not new_threads(baseline), .4), new_threads(baseline)
    assert call(e, body={'request_id': 'boundary_after_01'})[0] == 200
    assert not e.mission.journal.runs()


def test_early_complete_and_aborted_connections_cancel_deadline_work(env, caplog, capsys):
    e = env
    baseline = set(threading.enumerate())
    for number in range(8):
        assert call(e, body={'request_id': f'boundary_complete_{number:02}'})[0] == 200
    for phase in ('headers', 'body'):
        for _ in range(4):
            connection = connect(e)
            try:
                connection.sendall(head(e, 4096)[:-2] if phase == 'headers' else head(e, 4096) + b'{')
            finally:
                connection.close()
    assert wait_for(lambda: not new_threads(baseline), .4), new_threads(baseline)
    assert call(e, body={'request_id': 'boundary_recovered_01'})[0] == 200
    assert not e.mission.journal.runs()
    observed = caplog.text + capsys.readouterr().err
    assert e.node['secret'] not in observed and 'Authorization: Node' not in observed
