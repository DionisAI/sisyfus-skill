"""Frozen schema2 profile: real public loopback, protocol fake, zero native IO.

Wire fault injection occurs only after the real controller has admitted a
response, or before a request via a public authority transition. No old helper,
oracle, driver alias or acceptance is replaced. Timing is synthetic evidence.
"""
from dataclasses import asdict
import ast
import hashlib
import inspect
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from sisyfus.workers.codex import CodexDriver
from sisyfus.workers.claude_code import ClaudeCodeDriver
from sisyfus.workers.lead_console import MissionHub
from sisyfus.workers.node_agent import NodeAgent, _encoded, _HEARTBEAT_RETRY_SECONDS
from sisyfus.workers.node_gateway import NodeGateway
import sisyfus.workers.node_gateway as wire
from sisyfus.workers.node_registry import NodeRegistry
from sisyfus.workers.protocol import Receipt, Request, digest
from sisyfus.workers.remote_artifacts import create_input_snapshot, full_tree_manifest

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / 'artifacts/techlead/orchestra-20261008/full-delivery-b9e7b9660c534c98bfaaba7f7fede382/node-network-profile-sol'
SECRET = 'ab' * 32


@pytest.fixture(autouse=True)
def zero_native(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('network-profile protocol fixture: actual native/provider calls forbidden')
    for cls in (CodexDriver, ClaudeCodeDriver):
        monkeypatch.setattr(cls, 'run', forbidden)
        monkeypatch.setattr(cls, 'probe', forbidden)


def credential(root, config, name='credential.json'):
    path = root / name
    with path.open('xb') as stream:
        stream.write(json.dumps(config).encode())
    path.chmod(0o600)
    return path


def config(schema=1, budget=1.0):
    value = dict(schema=schema, controller_mission_id='m_fixture', node_id='node_' + '12' * 16,
                 secret=SECRET, gateway_url='http://127.0.0.1:12345', gateway_host='127.0.0.1:12345')
    if schema == 2:
        value['heartbeat_timeout_seconds'] = budget
    return value


def local(state):
    db = sqlite3.connect((state / 'agent.sqlite3').as_uri() + '?mode=ro', uri=True, timeout=.5)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        rows = [dict(row) for row in db.execute('SELECT * FROM attempts')]
        for row in rows:
            row['diagnostic'] = '\n'.join(item[0] for item in db.execute(
                'SELECT message FROM diagnostics WHERE request_id=? ORDER BY id', (row['request_id'],)))
        return (rows,
                db.execute('SELECT count(*) FROM outbox').fetchone()[0],
                db.execute("SELECT value FROM configuration WHERE key='identity'").fetchone()[0])
    finally:
        db.close()


class Protocol:
    """Explicit protocol fake; actual_model is absent, never an attestation."""
    def __init__(self, callback=None):
        self.resolved = 0
        self.calls = 0
        self.callback = callback

    @property
    def run(self):
        self.resolved += 1
        return self._run

    def _run(self, request, emit, controls):
        self.calls += 1
        if self.callback:
            self.callback(request, emit, controls)
        Path(request.cwd, 'result.txt').write_bytes(b'42')
        emit('process_started', {'pid': os.getpid(), 'driver': 'codex'})
        emit('session_bound', {'session_id': 'profile-protocol'})
        emit('turn_bound', {'session_id': 'profile-protocol', 'turn_id': 'profile-turn'})
        emit('model_identity', {'requested_model': request.model, 'actual_model': None, 'telemetry': 'missing'})
        return Receipt('COMPLETED', requested_model=request.model, actual_model=None,
                       session_id='profile-protocol', turn_id='profile-turn', output='protocol only; not acceptance')


@pytest.fixture
def public(tmp_path):
    assert os.environ.get('SISYFUS_TEST_LOOPBACK') == '1'
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'input.txt').write_bytes(b'fixed public profile input')
    checker = tmp_path / 'checker.py'
    checker.write_text("print('{\"ok\":true}')\n")  # Never executed by this fixture.
    check = {'argv': [sys.executable, '-I', '-S', str(checker), '{candidate}'],
             'code_hashes': {str(checker): hashlib.sha256(checker.read_bytes()).hexdigest()},
             'contract': {'kind': 'rules', 'pass_if': {'all': [{'path': 'ok', 'op': 'eq', 'value': True}]},
                          'fail_if': {'all': [{'path': 'ok', 'op': 'eq', 'value': False}]}}}
    task = {'id': 'build', 'objective': 'profile protocol output', 'check': 'one', 'depends_on': [],
            'write_paths': ['result.txt'], 'acceptance': 'frozen protocol check, independent review pending'}
    spec = dict(objective='Network profile protocol fixture', source=str(source), checks={'one': check},
                required_checks=['one'], integration_checks=['one'], timeout=5, parallelism=1,
                validation_kind='OFFLINE_STUB_NOT_REAL_MODEL_CALLS')
    hub = MissionHub(tmp_path / 'hub')
    gateway = None
    server = None
    try:
        ident = hub.create(spec)['id']
        mission = hub._session(ident).mission
        mission.admit_plan({'architecture': 'isolated protocol', 'interfaces': ['result.txt'], 'tasks': [task]},
                           'fixed-profile-plan')
        registry = NodeRegistry(mission.journal)
        node = registry.enroll('profile_enroll', 'protocol-only profile node', ['codex'], ['gpt-6.1-sol'])
        claims = mission.node_claims
        snapshot = tmp_path / 'snapshot'
        manifest = create_input_snapshot(source, snapshot, ['result.txt'])
        request = Request('build', 'Fixed protocol request, no provider.', str(snapshot), 'gpt-6.1-sol',
                          mode='workspace-write', timeout=5, max_turns=None)
        continuation = mission.store.claim_due_continuation('profile-controller', lease_seconds=60)
        assert continuation is not None and continuation['context']['native_task'] == 'build'
        key = 'profile-run'
        mission.journal.record('roles', key, {'role': 'worker', 'driver': 'codex', 'model': request.model,
                                            'mode': request.mode, 'cwd': request.cwd})
        mission.journal.reserve(key, 'build', digest(asdict(request)),
                                continuation_id=continuation['id'], lease_token=continuation['lease_token'])
        claims.bind_input_snapshot(key, snapshot, manifest)
        claims.offer(key, node['node_id'], request, manifest)
        gateway = NodeGateway(hub, port=0)
        server = threading.Thread(target=gateway.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        server.start()
        assert hub.attach_node_gateway(gateway, serve_thread=server)['effective_ready']
        base = dict(schema=1, controller_mission_id=ident, node_id=node['node_id'], secret=node['secret'],
                    gateway_url=gateway.url, gateway_host='127.0.0.1:' + str(gateway.server_port))
        yield SimpleNamespace(root=tmp_path, hub=hub, mission=mission, registry=registry, node=node, claims=claims,
                              snapshot=snapshot, source=source, manifest=manifest, key=key, base=base,
                              state=tmp_path / 'state', continuation=continuation)
    finally:
        if gateway:
            gateway.shutdown()
            gateway.server_close()
        if server:
            server.join(3)
            assert not server.is_alive()
        hub.close()


def agent(e, schema, budget=1.0, driver=None, name='credential.json'):
    value = dict(e.base, schema=schema)
    if schema == 2:
        value['heartbeat_timeout_seconds'] = budget
    return NodeAgent(credential(e.root, value, name), e.state, driver=driver or Protocol())


@pytest.fixture
def fault(monkeypatch):
    """Real socket writes of admitted response; backend contract stays intact."""
    original = wire._Handler._send
    active = []
    settings = SimpleNamespace(operation='heartbeat', delay=0, mode='body', after=0, count=0,
                               entered=threading.Event(), mutate=None, statuses=[])

    def send(handler, value, status=200, *, binary=False):
        operation = handler.path.split('?')[0].split('/')[4]
        if operation != settings.operation:
            return original(handler, value, status, binary=binary)
        settings.count += 1
        if settings.count <= settings.after:
            return original(handler, value, status, binary=binary)
        done = threading.Event()
        active.append(done)
        settings.statuses.append(status)
        settings.entered.set()
        raw = value if binary else value.raw if isinstance(value, wire._Response) else _encoded(value)
        if settings.mutate:
            status, raw = settings.mutate(status, raw)
        try:
            handler.send_response(status)
            handler.send_header('Content-Type', 'application/octet-stream' if binary else 'application/json')
            handler.send_header('Content-Length', str(len(raw)))
            handler.send_header('Connection', 'close')
            handler.close_connection = True
            if settings.mode == 'headers':
                # Flush valid status/header prefix, then incomplete extra header:
                # frequent successful reads do not defeat aggregate deadline.
                handler.flush_headers()
                handler.wfile.write(b'X-Drip: ')
                end = time.monotonic() + settings.delay
                while time.monotonic() < end:
                    handler.wfile.write(b'x')
                    time.sleep(.08)
                handler.wfile.write(b'\r\n\r\n' + raw)
            else:
                handler.end_headers()
                if settings.mode == 'drip':
                    end = time.monotonic() + settings.delay
                    offset = 0
                    while time.monotonic() < end and offset < len(raw) - 1:
                        handler.wfile.write(raw[offset:offset + 1])
                        offset += 1
                        time.sleep(.08)
                    handler.wfile.write(raw[offset:])
                else:
                    time.sleep(settings.delay)
                    handler.wfile.write(raw)
        except OSError:
            pass  # Deliberate client deadline disconnect, not backend success.
        finally:
            done.set()

    monkeypatch.setattr(wire._Handler, '_send', send)
    yield settings
    for done in active:
        assert done.wait(3), 'retained wire fault must drain within bound'


def test_static_constructor_cli_and_only_duration_change():
    assert str(inspect.signature(NodeAgent)) == '(credential_file, state_directory, *, driver=None)'
    assert (ROOT / 'src/sisyfus/workers/node_cli.py').read_bytes() == (EVIDENCE / 'node_cli.before.py').read_bytes()
    help_run = subprocess.run([sys.executable, '-m', 'sisyfus.workers.node_cli', '--help'],
                              capture_output=True, timeout=5)
    assert help_run.returncode == 0 and help_run.stderr == b''
    assert help_run.stdout == (EVIDENCE / 'node_cli.help.before.txt').read_bytes()
    before = (EVIDENCE / 'node_agent.before.py').read_text()
    after = (ROOT / 'src/sisyfus/workers/node_agent.py').read_text()
    old_tree, new_tree = ast.parse(before), ast.parse(after)
    old_cls = next(n for n in old_tree.body if isinstance(n, ast.ClassDef) and n.name == 'NodeAgent')
    new_cls = next(n for n in new_tree.body if isinstance(n, ast.ClassDef) and n.name == 'NodeAgent')
    old_methods = {n.name: ast.get_source_segment(before, n) for n in old_cls.body if isinstance(n, ast.FunctionDef)}
    new_methods = {n.name: ast.get_source_segment(after, n) for n in new_cls.body if isinstance(n, ast.FunctionDef)}
    assert old_methods.keys() == new_methods.keys()
    for name in old_methods.keys() - {'__init__', '_call'}:
        assert old_methods[name] == new_methods[name], name
    assert new_methods['_call'] == old_methods['_call'].replace(
        'duration = 0.4 if operation == "heartbeat" else 2',
        'duration = self._heartbeat_timeout_seconds if operation == "heartbeat" else 2')
    assert _HEARTBEAT_RETRY_SECONDS == 2.0


def test_v1_identity_bytes_secret_only_and_default(tmp_path):
    value = config()
    first = NodeAgent(credential(tmp_path, value), tmp_path / 'state', driver=Protocol())
    expected = _encoded({key: child for key, child in value.items() if key != 'secret'}).decode()
    assert local(first.state_directory)[2] == expected
    again = NodeAgent(credential(tmp_path, dict(value, secret='cd' * 32), 'other.json'),
                      first.state_directory, driver=Protocol())
    assert local(again.state_directory)[2] == expected
    assert first._heartbeat_timeout_seconds == again._heartbeat_timeout_seconds == .4


@pytest.mark.parametrize('budget', [.4, 1, 1.0])
def test_schema2_boundaries_accept_exact_identity(tmp_path, budget):
    value = config(2, budget)
    instance = NodeAgent(credential(tmp_path, value), tmp_path / 'state', driver=Protocol())
    assert local(instance.state_directory)[2] == _encoded({k: v for k, v in value.items() if k != 'secret'}).decode()
    assert type(instance._configuration['heartbeat_timeout_seconds']) is type(budget)
    assert instance._heartbeat_timeout_seconds == budget


@pytest.mark.parametrize('budget', [True, False, '1', None, float('nan'), float('inf'), float('-inf'),
                                   .399, 1.001, -1, 0, 1e300])
def test_schema2_invalid_numbers_fail_redacted_before_state(tmp_path, budget):
    auth = credential(tmp_path, config(2, budget))
    with pytest.raises(ValueError, match='invalid node credential configuration') as caught:
        NodeAgent(auth, tmp_path / 'state', driver=Protocol())
    assert SECRET not in str(caught.value) and 'heartbeat_timeout_seconds' not in str(caught.value)
    assert not (tmp_path / 'state').exists()


@pytest.mark.parametrize('change', ['v2_missing', 'v2_extra', 'v2_old_missing', 'v1_extra', 'bool_schema', 'unknown_schema'])
def test_schema_exact_fields(tmp_path, change):
    value = config(2)
    if change == 'v2_missing': del value['heartbeat_timeout_seconds']
    if change == 'v2_extra': value['extra'] = 0
    if change == 'v2_old_missing': del value['gateway_host']
    if change == 'v1_extra': value['schema'] = 1
    if change == 'bool_schema': value['schema'] = True
    if change == 'unknown_schema': value['schema'] = 3
    with pytest.raises(ValueError, match='invalid node credential configuration'):
        NodeAgent(credential(tmp_path, value), tmp_path / 'state', driver=Protocol())
    assert not (tmp_path / 'state').exists()


@pytest.mark.parametrize('old,new', [(config(), config(2)), (config(2, 1.0), config(2, .5)),
                                    (config(2, 1), config(2, 1.0))])
def test_fixed_identity_drift_fail_closed(tmp_path, old, new):
    state = tmp_path / 'state'
    NodeAgent(credential(tmp_path, old), state, driver=Protocol())
    fixed = local(state)[2]
    with pytest.raises(ValueError, match='another fixed configuration'):
        NodeAgent(credential(tmp_path, new, 'new.json'), state, driver=Protocol())
    assert local(state)[2] == fixed


@pytest.mark.parametrize('schema,budget,accept', [(1, .4, False), (2, .4, False), (2, 1.0, True)])
def test_real_delayed_heartbeat_preserves_spawn_boundary(public, fault, schema, budget, accept):
    e = public
    fault.delay = .6
    states = []
    def boundary(request, emit, controls):
        states.append(local(e.state)[0][0]['status'])
        assert states[-1] == 'IN_FLIGHT'
        assert Path(request.cwd, 'input.txt').read_bytes() == b'fixed public profile input'
    protocol = Protocol(boundary)
    instance = agent(e, schema, budget, protocol)
    start = time.monotonic()
    if accept:
        assert instance.run_once()['status'] == 'RECEIPTED'
        rows, events, _ = local(e.state)
        assert rows[0]['status'] == 'DONE' and json.loads(rows[0]['receipt'])['actual_model'] is None
        assert protocol.resolved == protocol.calls == 1 and events == 4 and states == ['IN_FLIGHT']
        assert e.claims.get(e.key)['receipt']['status'] == 'COMPLETED'
        assert not e.mission.snapshot()['all_verified'] and not e.mission.journal.records('reviews')
    else:
        with pytest.raises(RuntimeError, match='TimeoutError: gateway aggregate wall-clock deadline exceeded'):
            instance.run_once()
        rows, events, _ = local(e.state)
        assert rows[0]['status'] == 'INPUTS' and rows[0]['receipt'] is None and events == 0
        assert protocol.resolved == protocol.calls == 0
        assert list((e.state / 'workspaces').rglob('input.txt'))[0].read_bytes() == b'fixed public profile input'
    elapsed = time.monotonic() - start
    assert elapsed < 2
    assert fault.statuses == [200]
    print('PROFILE_DELAY', json.dumps(dict(schema=schema, budget=budget, seconds=elapsed,
                                          protocol_calls=protocol.calls, actual_native_calls=0)))


@pytest.mark.parametrize('mode', ['body', 'drip', 'headers'])
def test_overbudget_and_slowdrip_aggregate_prespawn(public, fault, mode):
    fault.delay = 1.25
    fault.mode = mode
    protocol = Protocol()
    instance = agent(public, 2, driver=protocol)
    start = time.monotonic()
    with pytest.raises(RuntimeError, match='TimeoutError'):
        instance.run_once()
    assert .9 <= time.monotonic() - start < 1.7
    rows, events, _ = local(public.state)
    assert rows[0]['status'] == 'INPUTS' and events == protocol.resolved == protocol.calls == 0


@pytest.mark.parametrize('schema', [1, 2])
@pytest.mark.parametrize('operation', ['claim', 'inputs', 'sync', 'status', 'uploads', 'receipt'])
def test_nonheartbeat_real_http_stays_two_seconds(public, fault, schema, operation):
    instance = agent(public, schema)
    offer = None
    if operation != 'claim':
        offer = instance._call('claim', {'request_id': 'profile_direct_claim'})['result']['claim']
    identity = instance._identity_body(offer) if offer else {}
    fault.operation = operation
    fault.delay = 2.2
    options = {}
    body = identity
    if operation == 'claim': body = {'request_id': 'profile_direct_claim'}
    if operation == 'sync': body = identity | {'events': []}
    if operation == 'inputs': body, options = None, dict(offer=offer, path='input.txt')
    if operation == 'uploads':
        body, options = None, dict(offer=offer, path='result.txt', data=b'42', sha=hashlib.sha256(b'42').hexdigest())
    if operation == 'receipt':
        body = identity | {'receipt': Receipt('COMPLETED', requested_model='gpt-6.1-sol').as_dict(),
                           'manifest': [], 'tree': full_tree_manifest(public.snapshot)}
    start = time.monotonic()
    with pytest.raises(TimeoutError, match='gateway aggregate wall-clock deadline exceeded'):
        instance._call(operation, body, **options)
    elapsed = time.monotonic() - start
    assert 1.9 <= elapsed < 2.6 and fault.statuses == [200]
    print('NORMAL_BUDGET', json.dumps(dict(schema=schema, operation=operation, seconds=elapsed, actual_native_calls=0)))


@pytest.mark.parametrize('schema', [1, 2])
@pytest.mark.parametrize('loss', ['node', 'core'])
def test_public_authority_loss_prespawn(public, monkeypatch, schema, loss):
    e = public
    original = wire._Handler._request
    changed = []
    def request(handler):
        if handler.path.endswith('/heartbeat') and not changed:
            changed.append(True)
            if loss == 'node':
                e.registry.revoke(e.node['node_id'])
            else:
                current = e.mission.store.get_continuation(e.continuation['id'])
                e.mission.store.block_owned_continuation(current['id'], worker_id=current['lease_owner'],
                    lease_token=current['lease_token'], expected_version=current['version'], reason='fixture core authority loss')
        return original(handler)
    monkeypatch.setattr(wire._Handler, '_request', request)
    protocol = Protocol()
    instance = agent(e, schema, driver=protocol)
    with pytest.raises(RuntimeError, match='HTTP (403|409)'):
        instance.run_once()
    assert changed and protocol.resolved == protocol.calls == local(e.state)[1] == 0
    assert local(e.state)[0][0]['status'] == 'INPUTS'


@pytest.mark.parametrize('kind', ['409', '404', 'inactive', 'identity'])
def test_real_heartbeat_wire_rejections_prespawn(public, fault, kind):
    def mutate(status, raw):
        assert status == 200
        value = json.loads(raw)
        if kind in {'409', '404'}:
            return int(kind), _encoded({'error': {'type': 'LeaseLost' if kind == '409' else 'FileNotFoundError',
                                                 'message': 'synthetic wire rejection'}})
        value['result']['status' if kind == 'inactive' else 'node_id'] = 'UNKNOWN' if kind == 'inactive' else 'node_' + '98' * 16
        return 200, _encoded(value)
    fault.mutate = mutate
    protocol = Protocol()
    instance = agent(public, 2, driver=protocol)
    with pytest.raises((ValueError, RuntimeError)):
        instance.run_once()
    assert protocol.resolved == protocol.calls == local(public.state)[1] == 0
    assert local(public.state)[0][0]['status'] == 'INPUTS'


@pytest.mark.parametrize('reserved', ['IN_FLIGHT', 'UNKNOWN'])
def test_existing_local_reservation_never_relaunch(public, fault, reserved):
    fault.delay = .6
    protocol = Protocol()
    instance = agent(public, 2, .4, protocol)
    with pytest.raises(RuntimeError, match='TimeoutError'): instance.run_once()
    row = local(public.state)[0][0]
    # Explicit NEW local crash fixture, not old real task truth.
    instance._update(row['request_id'], status=reserved)
    fault.delay = 0
    restarted = NodeAgent(public.root / 'credential.json', public.state, driver=protocol)
    assert restarted.run_once()['status'] == 'UNKNOWN'
    assert restarted.run_once()['status'] == 'UNKNOWN'
    assert protocol.resolved == protocol.calls == 0


def test_inloop_timeout_after_stop_joins_under_two(public, fault):
    fault.after = 1
    fault.delay = 1.25
    joins = []
    start_times = {}
    def observe(frame, event, arg):
        if frame.f_code is threading.Thread.join.__code__ and frame.f_locals.get('self').name == 'node-agent-heartbeat':
            if event == 'call':
                assert frame.f_locals['timeout'] == 2
                start_times[id(frame)] = time.monotonic()
            if event == 'return':
                joins.append(time.monotonic() - start_times.pop(id(frame)))
    def protocol_run(request, emit, controls):
        assert fault.entered.wait(1), 'second real heartbeat must be in flight when terminal stop occurs'
    protocol = Protocol(protocol_run)
    instance = agent(public, 2, driver=protocol)
    previous = sys.getprofile()
    sys.setprofile(observe)
    try:
        assert instance.run_once()['status'] == 'RECEIPTED'
    finally:
        sys.setprofile(previous)
    assert len(joins) == 1 and .5 < joins[0] < 2
    assert not any(t.name == 'node-agent-heartbeat' and t.is_alive() for t in threading.enumerate())
    row = local(public.state)[0][0]
    assert row['status'] == 'DONE' and row['lease_lost'] == 0 and protocol.calls == 1
    assert 'TimeoutError' in row['diagnostic']
    print('STOP_JOIN', json.dumps(dict(seconds=joins[0], actual_native_calls=0)))


def test_inloop_retry_loss_window_unchanged(public, fault):
    fault.after = 1
    fault.delay = 1.25
    lost = []
    def protocol_run(request, emit, controls):
        start = time.monotonic()
        while time.monotonic() - start < 4:
            pending = controls()
            if pending:
                assert pending[0]['action'] == 'interrupt'
                lost.append(time.monotonic() - start)
                return
            time.sleep(.02)
        raise AssertionError('fixed two-second retry window failed to declare loss')
    instance = agent(public, 2, driver=Protocol(protocol_run))
    assert instance.run_once()['status'] == 'RECEIPTED'
    assert len(lost) == 1 and 2 <= lost[0] < 3.4
    assert local(public.state)[0][0]['lease_lost'] == 1 and fault.count >= 3
