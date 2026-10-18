"""Frozen host-listener/CLI contract, not native, login, N6-process or A7/A8.

Real Hub/LeadMission and two real anonymous loopback listeners complement
explicit process/server DI at CLI constructors, Thread and browser boundaries.
DI does not replace a public readiness implementation or any task truth.
"""
from contextlib import contextmanager
import ast
import builtins
import http.client
import inspect
import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest

from sisyfus.workers import lead_cli, lead_console, node_gateway
from sisyfus.workers.lead_console import MissionHub, LeadConsole
from sisyfus.workers.lead_mission import LeadMission
from sisyfus.workers.node_gateway import NodeGateway
from sisyfus.workers.protocol import digest
from test_lead_mission import make_spec


def _host_api(hub):
    for name in ('attach_node_gateway', 'detach_node_gateway', 'node_gateway_state'):
        assert callable(getattr(hub, name, None)), 'HOST_LIFECYCLE_MISSING: ' + name
    signature = inspect.signature(hub.attach_node_gateway)
    assert signature.parameters['serve_thread'].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters['serve_thread'].default is inspect.Parameter.empty


def _state(hub):
    result = hub.node_gateway_state()
    assert set(result) == {'gateway', 'effective_ready', 'basis'}
    assert type(result['effective_ready']) is bool
    assert isinstance(result['basis'], str) and result['basis']
    if result['gateway'] is not None:
        assert set(result['gateway']) == {'url', 'host'}
    assert 'token=' not in json.dumps(result) and 'secret' not in json.dumps(result)
    return result


def _anonymous(server, path, *, post=False):
    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=1)
    try:
        headers = {'Host': '127.0.0.1:' + str(server.server_port)}
        body = None
        if post:
            headers['Content-Type'] = 'application/json'
            body = json.dumps({'request_id': 'fixture_host_lifecycle_0001'})
        connection.request('POST' if post else 'GET', path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read(32_001)
        assert len(raw) <= 32_000
        assert response.status == 401, 'REAL_LISTENER_CALIBRATION: anonymous request needs auth rejection'
        assert isinstance(json.loads(raw), dict)
        return response.status
    finally:
        connection.close()


@contextmanager
def _listeners(tmp_path):
    assert os.environ.get('SISYFUS_TEST_LOOPBACK') == '1'
    hub = MissionHub(tmp_path / 'hub')
    console = LeadConsole(hub, port=0)
    gateway = NodeGateway(hub, port=0)
    operator_thread = threading.Thread(target=console.serve_forever,
        kwargs={'poll_interval': .01}, daemon=True)
    gateway_thread = threading.Thread(target=gateway.serve_forever,
        kwargs={'poll_interval': .01}, daemon=True)
    operator_thread.start()
    gateway_thread.start()
    try:
        assert console.server_port != gateway.server_port
        assert gateway.hub is console.hub is hub
        assert _anonymous(console, '/api/missions') == 401
        assert _anonymous(gateway, '/node/v1/mission/claim', post=True) == 401
        print('FIXTURE_READY: real same-hub distinct loopback listeners; anonymous401; no dispatch')
        yield hub, console, gateway, gateway_thread
    finally:
        try:
            hub.close()
        finally:
            try:
                if gateway_thread.is_alive():
                    gateway.shutdown()
                gateway_thread.join(2)
                gateway.server_close()
            finally:
                if operator_thread.is_alive():
                    console.shutdown()
                operator_thread.join(2)
                console.server_close()
        assert not gateway_thread.is_alive() and not operator_thread.is_alive()


def _mission(hub, tmp_path, name):
    root = tmp_path / name
    root.mkdir()
    ident = hub.create(make_spec(root))['id']
    mission = hub._session(ident).mission
    assert type(mission) is LeadMission
    return ident, mission


def test_real_anonymous_listeners_are_not_node_online_or_worker_dispatch(tmp_path):
    with _listeners(tmp_path) as (hub, console, gateway, thread):
        assert hub.inventory()['missions'] == [] and hub._sessions == {}
        assert thread.is_alive() and gateway.socket.fileno() >= 0
        hub.close()
        assert thread.is_alive() and console.socket.fileno() >= 0
        assert _anonymous(gateway, '/node/v1/mission/claim', post=True) == 401


def test_public_host_state_signature_and_real_cached_future_mission_pins(tmp_path):
    with _listeners(tmp_path) as (hub, _, gateway, thread):
        ident, mission = _mission(hub, tmp_path, 'first')
        before = digest(mission.spec)
        placement = mission.placement('build')
        assert mission.remote_execution_ready() is False
        _host_api(hub)
        assert _state(hub) == {'gateway': None, 'effective_ready': False,
                              'basis': _state(hub)['basis']}
        hub.attach_node_gateway(gateway, serve_thread=thread)
        current = _state(hub)
        assert current['gateway'] == {'url': gateway.url,
            'host': '127.0.0.1:' + str(gateway.server_port)}
        assert current['effective_ready'] is True and mission.remote_execution_ready() is True
        _, future = _mission(hub, tmp_path, 'second')
        assert future.remote_execution_ready() is True
        assert digest(mission.spec) == before and mission.placement('build') == placement
        assert mission.journal.runs() == future.journal.runs() == []
        assert hub.snapshot(ident)['snapshot']['all_verified'] is False
        assert mission._node_claims is None and future._node_claims is None


def test_readiness_inside_write_tx_avoids_hub_session_locks_and_db_file_network(tmp_path):
    with _listeners(tmp_path) as (hub, _, gateway, thread):
        ident, mission = _mission(hub, tmp_path, 'callback')
        _host_api(hub)
        hub.attach_node_gateway(gateway, serve_thread=thread)
        locked, release, finished = threading.Event(), threading.Event(), threading.Event()
        result, failures, io_attempts = [], [], []
        active = {'thread': None, 'inside': False}

        def audit(event, args):
            if active['inside'] and active['thread'] == threading.get_ident():
                if event == 'open' or event.startswith(('sqlite3.', 'socket.connect',
                    'socket.bind', 'os.listdir', 'os.scandir', 'subprocess.', 'os.system')):
                    io_attempts.append(event)
                    raise AssertionError('READINESS_CALLBACK_IO: ' + event)

        sys.addaudithook(audit)

        def hold_locks():
            with hub._lock, hub._sessions[ident].lock:
                locked.set()
                release.wait(3)

        def invoke():
            try:
                with mission.store._transaction():
                    active.update(thread=threading.get_ident(), inside=True)
                    try:
                        result.append(mission.remote_execution_ready())
                    finally:
                        active['inside'] = False
            except BaseException as exc:
                failures.append(type(exc).__name__)
            finally:
                finished.set()

        owner = threading.Thread(target=hold_locks, daemon=True)
        caller = threading.Thread(target=invoke, daemon=True)
        owner.start()
        try:
            assert locked.wait(1)
            caller.start()
            completed_while_locked = finished.wait(.5)
        finally:
            active['inside'] = False
            release.set()
            owner.join(2)
            if caller.ident is not None:
                caller.join(2)
        assert completed_while_locked, 'READINESS_CALLBACK_LOCK: Hub/session lock blocked native TX callback'
        assert not failures and not io_attempts and result == [True]
        assert mission._node_claims is None and mission.journal.runs() == []


def test_detach_revokes_only_host_capability_not_external_server_ownership(tmp_path):
    with _listeners(tmp_path) as (hub, _, gateway, thread):
        _host_api(hub)
        hub.attach_node_gateway(gateway, serve_thread=thread)
        with pytest.raises((ValueError, RuntimeError)):
            hub.attach_node_gateway(gateway, serve_thread=thread)
        hub.detach_node_gateway()
        hub.detach_node_gateway()
        assert _state(hub)['gateway'] is None and _state(hub)['effective_ready'] is False
        assert thread.is_alive() and gateway.socket.fileno() >= 0
        assert _anonymous(gateway, '/node/v1/mission/claim', post=True) == 401


@pytest.mark.parametrize('loss', ['thread', 'socket'])
def test_listener_or_thread_loss_is_not_persisted_readiness(tmp_path, loss):
    with _listeners(tmp_path) as (hub, _, gateway, thread):
        _, mission = _mission(hub, tmp_path, 'loss')
        before = digest(mission.spec)
        _host_api(hub)
        hub.attach_node_gateway(gateway, serve_thread=thread)
        if loss == 'thread':
            gateway.shutdown()
            thread.join(2)
        else:
            gateway.server_close()
        assert _state(hub)['effective_ready'] is False
        assert mission.remote_execution_ready() is False
        assert digest(mission.spec) == before and mission.journal.runs() == []


def test_cooperative_hub_close_keeps_gateway_live_but_fences_late_attach(tmp_path):
    with _listeners(tmp_path) as (hub, _, gateway, thread):
        ident, mission = _mission(hub, tmp_path, 'close')
        _host_api(hub)
        hub.attach_node_gateway(gateway, serve_thread=thread)
        release, begun = threading.Event(), threading.Event()
        close_errors = []

        def cooperative_protocol_wait():
            begun.set()
            release.wait(3)

        worker = threading.Thread(target=cooperative_protocol_wait, daemon=True)
        hub._sessions[ident].thread = worker  # Process-wait DI, no Mission.run/native call.
        worker.start()

        def close():
            try:
                hub.close()
            except BaseException as exc:
                close_errors.append(type(exc).__name__)

        closing = threading.Thread(target=close, daemon=True)
        try:
            assert begun.wait(1)
            closing.start()
            deadline = time.monotonic() + 1
            while not mission.stop.is_set() and time.monotonic() < deadline:
                time.sleep(.005)
            assert mission.stop.is_set() and closing.is_alive()
            assert _state(hub)['effective_ready'] is False
            assert mission.remote_execution_ready() is False
            assert thread.is_alive() and _anonymous(gateway, '/node/v1/mission/claim', post=True) == 401
            hub.detach_node_gateway()
            with pytest.raises((ValueError, RuntimeError)):
                hub.attach_node_gateway(gateway, serve_thread=thread)
        finally:
            release.set()
            worker.join(2)
            if closing.ident is not None:
                closing.join(2)
        assert not close_errors and not worker.is_alive() and not closing.is_alive()
        assert _state(hub)['effective_ready'] is False
        with pytest.raises((ValueError, RuntimeError)):
            hub.attach_node_gateway(gateway, serve_thread=thread)
        assert mission.journal.runs() == [] and thread.is_alive()


class _CLIResources:
    """Process/server DI only. No socket, database, dispatch or native provider."""
    secret_text = 'fixture_lifecycle_secret'
    private_text = '/Users/fixture/private-host-lifecycle'

    def __init__(self, tmp_path, command, failure=None):
        self.root, self.command, self.failure = tmp_path, command, failure
        self.events, self.console, self.gateway, self.thread, self.hub = [], None, None, None, None
        self.expect_gateway = False

    def event(self, name):
        self.events.append(name)
        if name == self.failure:
            cls = OSError if name.endswith('.bind') else RuntimeError
            raise cls('lifecycle fixture failure ' + self.private_text + ' Bearer ' + self.secret_text)

    def install(self, monkeypatch):
        r = self

        class SocketDI:
            def __init__(self, owner):
                self.owner = owner

            def fileno(self):
                return -1 if self.owner.closed else self.owner.server_port

            def getsockname(self):
                return self.owner.server_address

            def getsockopt(self, level, option):
                return int(not self.owner.closed)

        class HubDI:
            def __init__(self, directory, *, single=False, mission_factory=None):
                self.directory, self.single = Path(directory), single
                self.attached, self.closing = None, False
                r.hub = self
                r.event('hub.construct')

            def inventory(self):
                return {'missions': [{'id': 'mission'}], 'issues': [], 'single': self.single}

            def create(self, spec, *, directory=None):
                r.event('hub.create')
                return {'id': 'mission', 'status': 'BOUND', 'started': False}

            def start(self, ident, *, allow_local_workers=False, max_cycles=None):
                assert ident == 'mission' and allow_local_workers is True and max_cycles is None
                assert r.console is not None
                if r.expect_gateway:
                    assert r.gateway is not None
                    assert r.thread is not None and r.thread.is_alive() and self.attached is r.gateway
                else:
                    assert r.gateway is None and r.thread is None
                r.event('hub.start')
                return {'status': 'ACK', 'terminal': False}

            def attach_node_gateway(self, gateway, *, serve_thread):
                assert gateway.hub is self and serve_thread is r.thread and serve_thread.is_alive()
                r.event('hub.attach')
                self.attached = gateway

            def detach_node_gateway(self):
                r.event('hub.detach')
                self.attached = None

            def node_gateway_state(self):
                return {'gateway': {'url': r.gateway.url, 'host': '127.0.0.1:43102'}
                        if self.attached is not None else None,
                        'effective_ready': bool(self.attached and not self.closing and r.thread.is_alive()),
                        'basis': 'host_listener_protocol_DI_not_node_online'}

            def close(self):
                self.closing = True
                if r.thread is not None and r.thread.started and not r.gateway.closed:
                    assert r.thread.is_alive(), 'gateway shut down before cooperative Hub.close'
                r.event('hub.close.begin')
                r.event('hub.close')
                self.attached = None
                r.event('hub.close.done')

        class ConsoleDI:
            def __init__(self, hub, *, port=lead_console.DEFAULT_PORT):
                r.event('console.bind')
                self.hub, self.closed = hub, False
                self.server_address, self.server_port = ('127.0.0.1', 43101), 43101
                self.origin = 'http://127.0.0.1:43101'
                self.socket = SocketDI(self)
                self.url = 'http://127.0.0.1:43101/#token=fixture_operator_only'
                r.console = self

            def serve_forever(self, poll_interval=.5):
                r.event('console.serve')
                raise KeyboardInterrupt

            def server_close(self):
                self.closed = True
                r.event('console.close')

        class GatewayDI:
            def __init__(self, hub, *, port=0):
                r.event('gateway.bind')
                self.hub, self.closed, self.stopping = hub, False, False
                self.server_address, self.server_port = ('127.0.0.1', 43102), 43102
                self.socket = SocketDI(self)
                self.url = 'http://127.0.0.1:43102'
                r.gateway = self

            def serve_forever(self, poll_interval=.5):
                r.event('gateway.serve')

            def shutdown(self):
                assert r.thread is not None and r.thread.started, 'shutdown on never-started gateway'
                self.stopping = True
                r.event('gateway.shutdown')

            def server_close(self):
                self.closed = True
                r.event('gateway.close')

        real_thread = threading.Thread

        class ThreadDI:
            def __new__(cls, *args, **kwargs):
                if kwargs.get('name') != 'techlead-node-gateway':
                    return real_thread(*args, **kwargs)
                return super().__new__(cls)

            def __init__(self, group=None, target=None, name=None, args=(), kwargs=None, *, daemon=None, context=None):
                assert callable(target)
                self.target, self.args, self.kwargs = target, args, kwargs or {}
                self.started, self.joined = False, False
                self.ident, self.name, self.daemon = None, name or 'gateway-process-DI', daemon
                self.context = context
                r.thread = self
                r.event('gateway.thread.construct')

            def start(self):
                r.event('gateway.thread.start')
                self.started = True
                self.ident = 1  # DI identity only, not a native or OS-process receipt.
                self.target(*self.args, **self.kwargs)

            def is_alive(self):
                return self.started and not r.gateway.stopping and not r.gateway.closed

            def join(self, timeout=None):
                assert self.started, 'join on never-started thread'
                self.joined = True
                r.event('gateway.thread.join')

        # Replace existing constructor references only; no new production aliases.
        references = [(lead_console.MissionHub, HubDI), (lead_console.LeadConsole, ConsoleDI),
                      (node_gateway.NodeGateway, GatewayDI), (threading.Thread, ThreadDI)]
        for name, value in list(vars(lead_cli).items()):
            for original, replacement in references:
                if value is original:
                    monkeypatch.setattr(lead_cli, name, replacement)
        monkeypatch.setattr(lead_console, 'MissionHub', HubDI)
        monkeypatch.setattr(lead_console, 'LeadConsole', ConsoleDI)
        monkeypatch.setattr(node_gateway, 'NodeGateway', GatewayDI)
        monkeypatch.setattr(threading, 'Thread', ThreadDI)

        def browser(url):
            assert url == r.console.url
            r.event('browser.open')
            return True

        monkeypatch.setattr(lead_cli.webbrowser, 'open', browser)
        print('FIXTURE_READY: exact public CLI/process/server DI; no native/socket/DB in DI')

    def argv(self, *, gateway=True, permission=True, browser=False):
        self.expect_gateway = gateway
        args = [self.command, '--directory', str(self.root / 'control'), '--port', '0']
        if self.command == 'up':
            spec = self.root / 'process-di-spec.json'
            with spec.open('x') as file:
                file.write('{"fixture":"process_server_DI_not_a_real_mission"}')
            args += [str(spec)]
            if permission:
                args.append('--allow-local-workers')
        if gateway:
            args += ['--node-gateway-port', '0']
        if browser:
            args.append('--open')
        return args

    def save(self):
        with (self.root / 'cli-resource-evidence.json').open('x') as file:
            json.dump({'classification': 'PROCESS_SERVER_DI_NOT_REAL_HOST_OR_DISPATCH',
                       'command': self.command, 'failure_stage': self.failure, 'events': self.events,
                       'console_closed': self.console.closed if self.console else None,
                       'gateway_closed': self.gateway.closed if self.gateway else None,
                       'gateway_thread_started': self.thread.started if self.thread else None,
                       'gateway_thread_joined': self.thread.joined if self.thread else None}, file, indent=2)


def _cli(resources, argv):
    try:
        return lead_cli.main(argv)
    except SystemExit as exc:
        pytest.fail('CLI_LIFECYCLE_MISSING: public service option rejected; parser exit=' + str(exc.code))
    finally:
        resources.save()


def _diagnostic(captured, expected):
    assert 'Traceback' not in captured.err
    assert _CLIResources.secret_text not in captured.err + captured.out
    assert _CLIResources.private_text not in captured.err + captured.out
    decoder, text, records = json.JSONDecoder(), captured.err.strip(), []
    while text:
        value, end = decoder.raw_decode(text)
        records.append(value)
        text = text[end:].strip()
    assert any(isinstance(value.get('error'), dict) and value['error']['type'] == expected
               for value in records), 'redacted cleanup/startup exception identity missing'


def test_service_parser_default_none_explicit_port_and_unlimited_cycles():
    for command in ('hub', 'serve', 'up'):
        args = [command, '--directory', '/fixture/controller']
        if command == 'up':
            args.append('/fixture/spec.json')
        plain = lead_cli.parser().parse_args(args)
        assert hasattr(plain, 'node_gateway_port'), 'CLI_LIFECYCLE_MISSING: node_gateway_port default'
        assert plain.node_gateway_port is None
        for port in (0, 65535):
            explicit = lead_cli.parser().parse_args(args + ['--node-gateway-port', str(port)])
            assert explicit.node_gateway_port == port and type(explicit.node_gateway_port) is int
        if command == 'up':
            assert plain.max_cycles is None and plain.allow_local_workers is False


def test_invalid_gateway_ports_need_positive_option_calibration_before_rejection():
    base = ['hub', '--directory', '/fixture/controller', '--node-gateway-port']
    try:
        positive = lead_cli.parser().parse_args(base + ['0'])
    except SystemExit as exc:
        pytest.fail('CLI_LIFECYCLE_MISSING: positive port calibration exit=' + str(exc.code))
    assert positive.node_gateway_port == 0
    for bad in ('-1', '65536', '2.5', 'bad'):
        with pytest.raises(SystemExit) as error:
            lead_cli.parser().parse_args(base + [bad])
        assert error.value.code == 2


def test_nonservice_option_rejection_precedes_any_hub_binding(monkeypatch):
    called = []

    def forbidden(*args, **kwargs):
        called.append(True)
        raise AssertionError('nonservice flag reached Hub construction')

    monkeypatch.setattr(lead_cli, 'MissionHub', forbidden)
    for command in ('new', 'run', 'status'):
        args = [command, '--directory', '/fixture/controller', '--node-gateway-port', '0']
        if command != 'status':
            args.append('/fixture/spec.json')
        with pytest.raises(SystemExit) as error:
            lead_cli.main(args)
        assert error.value.code == 2
    assert called == []


@pytest.mark.parametrize('command', ['hub', 'serve', 'up'])
def test_default_cli_constructs_no_gateway_thread_or_gateway_import(tmp_path, monkeypatch, command):
    module = ast.parse(Path(lead_cli.__file__).read_text())
    for node in module.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            assert 'node_gateway' not in ast.get_source_segment(Path(lead_cli.__file__).read_text(), node)
    resources = _CLIResources(tmp_path, command)
    resources.install(monkeypatch)
    imports = []
    original = builtins.__import__

    def observe(name, globals=None, locals=None, fromlist=(), level=0):
        if 'node_gateway' in name or 'node_gateway' in (fromlist or ()):
            imports.append(name)
        return original(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, '__import__', observe)
    assert _cli(resources, resources.argv(gateway=False)) == 130
    assert resources.gateway is None and resources.thread is None and imports == []
    assert resources.console.closed and 'hub.close' in resources.events


@pytest.mark.parametrize('command', ['hub', 'serve', 'up'])
def test_explicit_cli_binds_both_before_start_and_keeps_gateway_until_cooperative_close(tmp_path, monkeypatch, command):
    resources = _CLIResources(tmp_path, command)
    resources.install(monkeypatch)
    assert _cli(resources, resources.argv()) == 130
    events = resources.events
    assert resources.console.server_port != resources.gateway.server_port
    assert events.index('gateway.thread.start') < events.index('hub.attach')
    if command == 'up':
        for before in ('console.bind', 'gateway.bind', 'gateway.thread.start', 'hub.attach'):
            assert events.index(before) < events.index('hub.start')
    else:
        assert 'hub.start' not in events and 'hub.create' not in events
    assert events.index('hub.close.done') < events.index('gateway.shutdown')
    assert resources.thread.joined and resources.gateway.closed and resources.console.closed


def test_up_gateway_optin_does_not_replace_worker_permission(tmp_path, monkeypatch, capsys):
    resources = _CLIResources(tmp_path, 'up')
    resources.install(monkeypatch)
    assert _cli(resources, resources.argv(permission=False)) == 1
    assert not any(x in resources.events for x in ('hub.create', 'hub.start', 'console.bind', 'gateway.bind'))
    _diagnostic(capsys.readouterr(), 'PermissionError')


@pytest.mark.parametrize('stage', ['console.bind', 'gateway.bind', 'gateway.thread.start'])
def test_partial_startup_closes_every_acquired_resource_without_shutdown_of_unstarted_thread(tmp_path, monkeypatch, capsys, stage):
    resources = _CLIResources(tmp_path, 'up', stage)
    resources.install(monkeypatch)
    assert _cli(resources, resources.argv()) == 1
    assert stage in resources.events and 'hub.start' not in resources.events
    assert 'hub.close' in resources.events
    if resources.console:
        assert resources.console.closed
    if resources.gateway:
        assert resources.gateway.closed
    if not resources.thread or not resources.thread.started:
        assert 'gateway.shutdown' not in resources.events and 'gateway.thread.join' not in resources.events
    _diagnostic(capsys.readouterr(), 'OSError' if stage.endswith('.bind') else 'RuntimeError')


@pytest.mark.parametrize('stage', ['console.serve', 'browser.open'])
def test_serve_or_browser_failure_is_redacted_nonzero_and_all_owned_resources_close(tmp_path, monkeypatch, capsys, stage):
    resources = _CLIResources(tmp_path, 'hub', stage)
    resources.install(monkeypatch)
    assert _cli(resources, resources.argv(browser=stage == 'browser.open')) == 1
    assert stage in resources.events and 'hub.start' not in resources.events
    assert resources.gateway.closed and resources.console.closed and resources.thread.joined
    assert resources.events.index('hub.close') < resources.events.index('gateway.shutdown')
    _diagnostic(capsys.readouterr(), 'RuntimeError')


@pytest.mark.parametrize('stage', ['hub.close', 'gateway.shutdown', 'gateway.close', 'console.close'])
def test_cleanup_failure_is_never_exit_zero_or_130_and_other_resources_still_close(tmp_path, monkeypatch, capsys, stage):
    resources = _CLIResources(tmp_path, 'hub', stage)
    resources.install(monkeypatch)
    assert _cli(resources, resources.argv()) == 1
    assert stage in resources.events
    assert 'hub.close' in resources.events and 'gateway.close' in resources.events and 'console.close' in resources.events
    assert resources.gateway.closed and resources.console.closed
    assert resources.thread.joined
    _diagnostic(capsys.readouterr(), 'RuntimeError')
