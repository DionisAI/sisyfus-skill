"""Socket timeout vs watchdog race: both share one deadline, one error.

The per-recv socket timeout and the aggregate watchdog expire at the same
instant. Whichever wins, callers must see the aggregate deadline error, not a
raw socket TimeoutError('timed out'). The watchdog is delayed here so the
socket side always wins, which makes the race deterministic.
"""
import json
import os
import socket
import threading
import time

import pytest

import sisyfus.workers.node_agent as node_agent
from sisyfus.workers.node_agent import NodeAgent


@pytest.fixture
def silent_gateway():
    assert os.environ.get('SISYFUS_TEST_LOOPBACK') == '1', 'explicit loopback opt-in required'
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    accepted = []

    def accept():
        try:
            accepted.append(listener.accept()[0])  # Read nothing, answer nothing.
        except OSError:
            pass

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield listener.getsockname()[1]
    listener.close()
    for connection in accepted:
        connection.close()
    thread.join(1)


@pytest.fixture
def late_watchdog(monkeypatch):
    class LateTimer(threading.Timer):
        def __init__(self, interval, function, *args, **kwargs):
            super().__init__(interval + 5, function, *args, **kwargs)
    monkeypatch.setattr(node_agent.threading, 'Timer', LateTimer)


def agent(tmp_path, port):
    credential = tmp_path / 'credential.json'
    with credential.open('xb') as stream:
        stream.write(json.dumps(dict(
            schema=1, controller_mission_id='m_fixture', node_id='node_' + '12' * 16, secret='ab' * 32,
            gateway_url=f'http://127.0.0.1:{port}', gateway_host=f'127.0.0.1:{port}')).encode())
    credential.chmod(0o600)
    state = tmp_path / 'state'
    state.mkdir(mode=0o700)
    return NodeAgent(credential, state)


def test_socket_timeout_winning_the_race_reports_aggregate_deadline(tmp_path, silent_gateway, late_watchdog):
    instance = agent(tmp_path, silent_gateway)
    start = time.monotonic()
    with pytest.raises(TimeoutError, match='gateway aggregate wall-clock deadline exceeded'):
        instance._call('claim', {'request_id': 'race_claim_0001'})
    assert time.monotonic() - start < 2.6  # The socket budget, not the delayed watchdog.
