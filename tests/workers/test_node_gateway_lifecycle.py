"""Frozen host-owned gateway readiness, not remote/native/device acceptance.

Static interfaces checked before freeze: actual NodeGateway has url, socket,
server_address; Thread is explicitly passed, no gateway.serve_thread property;
MissionHub owns _sessions and close; CLI parser lives in workers/lead_cli.py.
Only new attach/detach/readback and opt-in parser behavior are requested here.
"""
from pathlib import Path
import os
import threading

import pytest

from sisyfus.workers.lead_console import MissionHub
from sisyfus.workers.node_gateway import NodeGateway
from sisyfus.workers.lead_cli import parser
from sisyfus.workers.protocol import digest
from test_lead_mission import make_spec


@pytest.fixture
def host(tmp_path):
    assert os.environ.get('SISYFUS_TEST_LOOPBACK') == '1', 'explicit isolated fixture loopback required'
    hub = MissionHub(tmp_path / 'hub')
    gateway = NodeGateway(hub, port=0)
    thread = threading.Thread(target=gateway.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    try:
        yield hub, gateway, thread
    finally:
        hub.close()
        gateway.shutdown()
        thread.join(5)
        gateway.server_close()
        assert not thread.is_alive()


def state(h):
    value = h.node_gateway_state()
    assert set(value) == {'gateway', 'effective_ready', 'basis'}
    assert type(value['effective_ready']) is bool
    assert isinstance(value['basis'], str) and value['basis']
    assert 'token' not in str(value) and 'secret' not in str(value)
    return value


def test_default_hub_has_no_remote_transport_authority(tmp_path):
    h = MissionHub(tmp_path / 'hub')
    try:
        assert state(h)['gateway'] is None and state(h)['effective_ready'] is False
        ident = h.create(make_spec(tmp_path))['id']; m = h._session(ident).mission
        assert m.remote_execution_ready() is False
        assert m.journal.runs() == []
    finally:
        h.close()


def test_attach_real_listener_applies_to_existing_and_future_sessions_without_spec_mutation(host, tmp_path):
    h, g, t = host
    first = h.create(make_spec(tmp_path))['id']; m = h._session(first).mission
    spec_hash = digest(m.spec); prior = m.placement('no-new-placement')
    assert m.remote_execution_ready() is False
    h.attach_node_gateway(g, serve_thread=t)
    assert state(h)['effective_ready'] is True
    assert state(h)['gateway'] == {'url': g.url, 'host': f'{g.server_address[0]}:{g.server_address[1]}'}
    assert m.remote_execution_ready() is True
    (tmp_path / 'second').mkdir(); second = h.create(make_spec(tmp_path / 'second'))['id']; other = h._session(second).mission
    assert other.remote_execution_ready() is True
    assert m.journal.runs() == other.journal.runs() == []
    assert digest(m.spec) == spec_hash and m.placement('no-new-placement') == prior == {'kind': 'local'}


def test_attach_requires_explicit_live_thread_and_same_hub(host, tmp_path):
    h, g, t = host
    with pytest.raises(TypeError):
        h.attach_node_gateway(g)
    dead = threading.Thread(target=g.serve_forever, daemon=True)
    with pytest.raises((ValueError, RuntimeError)):
        h.attach_node_gateway(g, serve_thread=dead)
    other = MissionHub(tmp_path / 'other-hub')
    try:
        with pytest.raises((ValueError, RuntimeError)):
            other.attach_node_gateway(g, serve_thread=t)
        assert state(other)['effective_ready'] is False
    finally:
        other.close()
    assert state(h)['effective_ready'] is False


def test_second_attach_conflicts_and_detach_only_revokes_host_readiness(host):
    h, g, t = host
    h.attach_node_gateway(g, serve_thread=t)
    with pytest.raises((ValueError, RuntimeError)):
        h.attach_node_gateway(g, serve_thread=t)
    h.detach_node_gateway(); h.detach_node_gateway()
    assert state(h)['effective_ready'] is False
    assert t.is_alive() and g.socket.fileno() >= 0, 'detach is not externally owned server destruction'


@pytest.mark.parametrize('loss', ['serve-thread', 'listener-socket'])
def test_live_readiness_turns_false_after_external_transport_loss(host, tmp_path, loss):
    h, g, t = host
    ident = h.create(make_spec(tmp_path))['id']; m = h._session(ident).mission
    before = digest(m.spec)
    h.attach_node_gateway(g, serve_thread=t)
    if loss == 'serve-thread':
        g.shutdown(); t.join(5)
    else:
        g.server_close()
    assert state(h)['effective_ready'] is False
    assert m.remote_execution_ready() is False and digest(m.spec) == before
    assert m.journal.runs() == []


@pytest.mark.parametrize('command', ['hub', 'serve', 'up'])
def test_opt_in_service_parser_has_no_implicit_gateway(command):
    argv = [command, '--directory', '/synthetic/hub']
    if command == 'up': argv.append('/synthetic/spec.json')
    plain = parser().parse_args(argv)
    assert plain.node_gateway_port is None
    selected = parser().parse_args(argv + ['--node-gateway-port', '0'])
    assert selected.node_gateway_port == 0


@pytest.mark.parametrize('command', ['new', 'run', 'status'])
def test_nonservice_command_rejects_gateway_option_before_binding(command):
    argv = [command, '--directory', '/synthetic/hub']
    if command != 'status': argv.append('/synthetic/spec.json')
    with pytest.raises(SystemExit) as exc:
        parser().parse_args(argv + ['--node-gateway-port', '0'])
    assert exc.value.code == 2


@pytest.mark.parametrize('port', ['-1', '65536', 'bad'])
def test_gateway_port_rejected_before_any_service_start(port):
    with pytest.raises(SystemExit) as exc:
        parser().parse_args(['hub', '--directory', '/synthetic/hub', '--node-gateway-port', port])
    assert exc.value.code == 2
