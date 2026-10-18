"""Frozen N4 gateway contracts. Isolated real loopback, never a native run.

Run with SISYFUS_TEST_LOOPBACK=1 through scripts/test_retained.py and approved
loopback permission. No skip/xfail, fake transport success, or artifact deletion.
The documented transport service dependency is exercised through its public API.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import http.client
import importlib
import json
import os
from pathlib import Path
import socket
import threading
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from sisyfus.workers.lead_console import MissionHub
from sisyfus.workers.node_claims import NodeClaims
from sisyfus.workers.node_registry import NodeRegistry
from sisyfus.workers.protocol import Receipt, Request, digest
from sisyfus.workers.remote_artifacts import create_input_snapshot, full_tree_manifest
from test_lead_mission import make_spec


class Clock:
    def __init__(self): self.value = 1000.0
    def __call__(self): return self.value
    def advance(self, seconds): self.value += seconds


@pytest.fixture
def gateway_type():
    return importlib.import_module('sisyfus.workers.node_gateway').NodeGateway


def forbidden_native(*_args, **_kwargs):
    raise AssertionError('gateway must never invoke native, controller Start, checks or review')


@pytest.fixture
def env(tmp_path, monkeypatch, gateway_type):
    assert os.environ.get('SISYFUS_TEST_LOOPBACK') == '1', 'explicit loopback opt-in required'
    hub = MissionHub(tmp_path / 'hub')
    ident = hub.create(make_spec(tmp_path))['id']
    m = hub._session(ident).mission
    for driver in m.drivers.values():
        monkeypatch.setattr(driver, 'run', forbidden_native)
    monkeypatch.setattr(hub, 'start', forbidden_native)
    monkeypatch.setattr(hub, 'control', forbidden_native)
    registry = NodeRegistry(m.journal)  # Auth has records, but no lazy claims backend yet.
    node = registry.enroll('gateway_enroll_01', 'gateway fixture', ['codex'], ['gpt-6.1-sol'])
    other = registry.enroll('gateway_enroll_02', 'other fixture', ['codex'], ['gpt-6.1-sol'])
    gateway = gateway_type(hub, port=0)
    thread = threading.Thread(target=gateway.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    e = SimpleNamespace(root=tmp_path, hub=hub, ident=ident, mission=m, registry=registry,
                        node=node, other=other, gateway=gateway, clock=Clock())
    yield e
    gateway.shutdown()
    gateway.server_close()
    thread.join(timeout=5)
    assert not thread.is_alive()
    hub.close()


def call(e, operation='claim', *, method='POST', body=None, raw=None, query=None,
         headers=(), node=None, target=None):
    selected = node or e.node
    target = target or '/node/v1/' + e.ident + '/' + operation
    if query is not None:
        target += '?' + (query if isinstance(query, str) else urlencode(query))
    if raw is None and body is not None:
        raw = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
    if isinstance(raw, str): raw = raw.encode()
    defaults = [('Host', '127.0.0.1:' + str(e.gateway.server_port)),
                ('Authorization', 'Node ' + selected['secret']), ('X-Sisyfus-Node', selected['node_id'])]
    if method in {'POST', 'PUT'} or raw is not None:
        defaults += [('Content-Length', str(len(raw or b''))),
                     ('Content-Type', 'application/octet-stream' if method == 'PUT' else 'application/json')]
    replaced = {key.lower() for key, _ in headers}
    connection = http.client.HTTPConnection('127.0.0.1', e.gateway.server_port, timeout=8)
    try:
        connection.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
        for key, value in [*(p for p in defaults if p[0].lower() not in replaced), *headers]:
            connection.putheader(key, value)
        connection.endheaders(raw)
        response = connection.getresponse()
        data = response.read()
        result = json.loads(data) if 'application/json' in response.getheader('Content-Type', '') else data
        return response.status, result
    finally:
        connection.close()


def state(e):
    with e.mission.store._transaction(immediate=False) as db:
        logical = '\n'.join(db.iterdump())
    paths = sorted(str(p.relative_to(e.hub.directory)) for p in e.hub.directory.rglob('*')
                   if not p.name.endswith(('-wal', '-shm')))
    return logical, paths


def no_session(e, monkeypatch):
    monkeypatch.setattr(e.hub, '_session', forbidden_native)


def fields(claim):
    return {'claim_id': claim['claim_id'], 'epoch': claim['epoch']}


def offer(e, *, transport=False, key='gateway-run', outputs=None):
    m = e.mission
    claims = NodeClaims(m.journal, e.registry, m.directory / 'remote' / 'artifacts', clock=e.clock)
    m._node_claims = claims
    source = e.root / ('prepared-' + key)
    source.mkdir()
    (source / 'input.txt').write_bytes(b'fixed input')
    snapshot = e.root / ('snapshot-' + key)
    manifest = create_input_snapshot(source, snapshot, ['result.txt'] if outputs is None else outputs)
    request = Request('build', 'Fixed gateway task; no acceptance changes.', str(snapshot),
                      'gpt-6.1-sol', mode='workspace-write')
    m.journal.reserve(key, 'build', digest(asdict(request)))
    if transport:
        claims.bind_input_snapshot(key, snapshot, manifest)
    claims.offer(key, e.node['node_id'], request, manifest)
    e.claims, e.snapshot, e.manifest, e.key = claims, snapshot, manifest, key
    return claims


def claim(e):
    status, result = call(e, body={'request_id': 'gateway_claim_01'})
    assert status == 200 and result['controller_mission_id'] == e.ident
    assert result['result']['status'] == 'CLAIMED'
    return result['result']['claim']


@pytest.mark.parametrize('port', [-1, 65536, True, 1.5, '0', None])
def test_port_validation_before_any_hub_work(gateway_type, port):
    with pytest.raises(ValueError): gateway_type(SimpleNamespace(), port=port)


def test_loopback_sidecar_constructor_and_no_work_exact_replay(env):
    e = env
    assert e.gateway.server_address[0] == '127.0.0.1' and e.gateway.server_port > 0
    assert not (e.mission.directory / 'remote').exists() and not e.mission.journal.runs()
    result = call(e, body={'request_id': 'gateway_empty_01'})
    assert result == (200, {'controller_mission_id': e.ident, 'result': {
        'mission_id': e.registry.mission_id, 'node_id': e.node['node_id'],
        'request_id': 'gateway_empty_01', 'status': 'NO_WORK', 'claim': None}})
    before = state(e)
    assert call(e, body={'request_id': 'gateway_empty_01'}) == result
    assert state(e) == before and not e.mission.journal.runs()


@pytest.mark.parametrize('route,method', [('claim', 'POST'), ('sync', 'POST'), ('heartbeat', 'POST'),
    ('status', 'POST'), ('receipt', 'POST'), ('inputs/claim_' + 'a'*32 + '/1', 'GET'),
    ('uploads/claim_' + 'a'*32 + '/1', 'PUT')])
@pytest.mark.parametrize('bad,status', [
    ('missing_auth', 401), ('bearer', 401), ('wrong_secret', 401), ('unknown_node', 401),
    ('double_auth', 401), ('double_node', 401), ('origin', 403), ('bad_host', 403),
    ('double_host', 403), ('forwarded', 400),
])
def test_boundary_auth_all_routes_no_state_or_lazy_backend(env, monkeypatch, route, method, bad, status):
    e = env
    host = '127.0.0.1:' + str(e.gateway.server_port)
    variants = {
        'missing_auth': [('Authorization', '')], 'bearer': [('Authorization', 'Bearer operator-fixture')],
        'wrong_secret': [('Authorization', 'Node ' + 'b'*64)],
        'unknown_node': [('X-Sisyfus-Node', 'node_' + 'f'*32)],
        'double_auth': [('Authorization', 'Node ' + e.node['secret'])]*2,
        'double_node': [('X-Sisyfus-Node', e.node['node_id'])]*2,
        'origin': [('Origin', 'http://' + host)], 'bad_host': [('Host', 'evil.example:' + str(e.gateway.server_port))],
        'double_host': [('Host', host)]*2, 'forwarded': [('X-Forwarded-Host', host)],
    }
    no_session(e, monkeypatch)
    before = state(e)
    result = call(e, route, method=method, raw=b'{}', headers=variants[bad])
    assert result[0] == status and e.node['secret'] not in json.dumps(result)
    assert state(e) == before and not (e.mission.directory / 'remote').exists()


def test_revoked_identity_readonly_auth_and_race_before_lazy_backend(env, monkeypatch):
    e = env
    original = NodeRegistry.authenticate
    revoked = []
    def racing(reader, node_id, secret):
        result = original(reader, node_id, secret)
        if result and not revoked:
            e.registry.revoke(node_id)
            revoked.append(node_id)
        return result
    monkeypatch.setattr(NodeRegistry, 'authenticate', racing)
    no_session(e, monkeypatch)
    assert call(e, body={'request_id': 'gateway_claim_01'})[0] == 403
    assert revoked == [e.node['node_id']] and not (e.mission.directory / 'remote').exists()
    before = state(e)
    assert call(e, body={'request_id': 'gateway_claim_01'})[0] == 403
    assert state(e) == before and not e.mission.journal.runs()


def test_unregistered_database_unknown_child_and_symlink_never_initialized(env, monkeypatch):
    e = env
    no_session(e, monkeypatch)
    before = state(e)
    missing = e.hub.directory / 'missing'
    assert call(e, target='/node/v1/missing/claim', body={'request_id': 'gateway_claim_01'})[0] == 404
    assert not missing.exists() and state(e) == before
    empty = e.hub.directory / 'empty'
    empty.mkdir()
    assert call(e, target='/node/v1/empty/claim', body={})[0] == 404
    assert list(empty.iterdir()) == []
    link = e.hub.directory / 'linked'
    link.symlink_to(e.mission.directory, target_is_directory=True)
    assert call(e, target='/node/v1/linked/claim', body={})[0] in {403, 404}
    assert not (e.mission.directory / 'remote').exists()


def test_bound_mission_without_registry_and_trial_child_have_no_lazy_writes(env, monkeypatch):
    e = env
    second = e.root / 'second-fixture'
    second.mkdir()
    ident = e.hub.create(make_spec(second))['id']
    other_mission = e.hub._session(ident).mission
    no_session(e, monkeypatch)
    before = state(e)
    assert call(e, target='/node/v1/' + ident + '/claim', body={})[0] == 401
    assert state(e) == before and not (other_mission.directory / 'remote').exists()
    with e.mission.store._transaction() as db:
        db.execute("INSERT INTO metadata VALUES('techlead:inbox_policy:trial-child','{}')")
    before = state(e)
    assert call(e, body={'request_id': 'gateway_claim_01'})[0] == 403
    assert state(e) == before


@pytest.mark.parametrize('raw', [b'{', b'[]', b'null', b'{"request_id":"gateway_claim_01","request_id":"gateway_claim_01"}',
    b'{"request_id":NaN}', b'{"request_id":Infinity}', b'{"request_id":-Infinity}',
    b'{"request_id":1e999}', b'{"request_id":"\\ud800"}', b'\xff', b'\xef\xbb\xbf{}',
    b'{} {}', b'{"request_id":"gateway_claim_01","argv":["touch","FORBIDDEN"]}',
    b'{"request_id":true}', b'{"request_id":"tiny"}', b'{"request_id":"gateway_claim_01","root":"/private"}'])
def test_strict_json_before_lazy_backend_no_unknown_payload_echo(env, monkeypatch, raw):
    e = env
    no_session(e, monkeypatch)
    before = state(e)
    result = call(e, raw=raw)
    assert result[0] == 400 and state(e) == before
    assert b'FORBIDDEN' not in json.dumps(result).encode()


@pytest.mark.parametrize('headers', [
    [('Content-Length', '-1')], [('Content-Length', '01')], [('Content-Length', '1.0')],
    [('Content-Length', '2'), ('Content-Length', '2')], [('Content-Length', '1500001')],
    [('Transfer-Encoding', 'chunked')], [('Content-Type', 'text/plain')],
    [('Content-Type', 'application/json'), ('Content-Type', 'application/json')],
    [('Expect', '100-continue')], [('Cookie', 'secret=FORBIDDEN')],
])
def test_strict_headers_framing_and_body_bounds_before_backend(env, monkeypatch, headers):
    e = env
    no_session(e, monkeypatch)
    before = state(e)
    result = call(e, raw=b'{}', headers=headers)
    assert result[0] == 400 and state(e) == before


def test_short_body_and_nested_duplicate_nonfinite_json(env, monkeypatch):
    e = env
    no_session(e, monkeypatch)
    before = state(e)
    host = '127.0.0.1:' + str(e.gateway.server_port)
    with socket.create_connection(('127.0.0.1', e.gateway.server_port), timeout=5) as s:
        s.sendall(('POST /node/v1/' + e.ident + '/claim HTTP/1.1\r\nHost: ' + host +
                   '\r\nAuthorization: Node ' + e.node['secret'] + '\r\nX-Sisyfus-Node: ' + e.node['node_id'] +
                   '\r\nContent-Type: application/json\r\nContent-Length: 20\r\n\r\n{}').encode())
        s.shutdown(socket.SHUT_WR)
        received = b''
        while data := s.recv(65536): received += data
    assert b' 400 ' in received.split(b'\r\n')[0] and e.node['secret'].encode() not in received
    for raw in [b'{"claim_id":"claim_' + b'a'*32 + b'","epoch":1,"events":[{"seq":1,"kind":"native_event","data":{"method":"fixture","params":{"x":1,"x":2}}}]}',
                b'{"claim_id":"claim_' + b'a'*32 + b'","epoch":1,"events":[{"seq":1,"kind":"native_event","data":{"method":"fixture","params":{"x":NaN}}}]}']:
        assert call(e, 'sync', raw=raw)[0] == 400
    nested = {'x': 0}
    for _ in range(70): nested = {'x': nested}
    assert call(e, 'sync', body={'claim_id': 'claim_' + 'a'*32, 'epoch': 1,
        'events': [{'seq': 1, 'kind': 'native_event', 'data': {'method': 'fixture', 'params': nested}}]})[0] == 400
    assert state(e) == before


@pytest.mark.parametrize('suffix,method,status', [
    ('claim?x=1', 'POST', 400), ('claim?request_id=a&request_id=b', 'POST', 400),
    ('claim?x=%ZZ', 'POST', 400), ('claim?x=%ff', 'POST', 400), ('claim#fragment', 'POST', 400),
    ('claim?' + 'x'*17000, 'POST', 400), ('claim', 'GET', 404), ('claim', 'PUT', 404),
    ('controls', 'POST', 404), ('start', 'POST', 404), ('nodes', 'POST', 404),
    ('../claim', 'POST', 404), ('%63laim', 'POST', 404), ('claim/extra', 'POST', 404),
])
def test_uri_query_and_exact_route_allowlist_before_backend(env, monkeypatch, suffix, method, status):
    e = env
    no_session(e, monkeypatch)
    before = state(e)
    result = call(e, suffix, method=method, raw=b'{}')
    assert result[0] == status and state(e) == before


@pytest.mark.parametrize('operation', ['sync', 'heartbeat', 'status', 'receipt'])
@pytest.mark.parametrize('epoch', [True, False, 0, -1, 1.0, '1', 2**63, None])
def test_epoch_types_are_not_execution_identities(env, monkeypatch, operation, epoch):
    e = env
    no_session(e, monkeypatch)
    body = {'claim_id': 'claim_' + 'a'*32, 'epoch': epoch}
    if operation == 'sync': body['events'] = []
    if operation == 'receipt': body.update(receipt={'status': 'ERROR'}, manifest=[], tree={'schema': 1, 'files': [], 'tree': [], 'errors': [], 'complete': True})
    before = state(e)
    assert call(e, operation, body=body)[0] == 400 and state(e) == before


def test_sync_native_acceptance_atomic_application_cursor_replay_and_concurrency(env):
    e = env
    offer(e)
    message = e.mission.inbox.submit('fixed operator data', 'gateway_context_01', task_id='build',
                                    snapshot={'nodes': [{'id': 'build'}]}, controller={'running': True})
    base = 'Fixed gateway context prompt.'
    e.mission.journal.reserve('context-run', 'build', digest(base), on_reserved=lambda db:
        e.mission.inbox.bind(db, 'context-run', role='worker', task_id='build', prompt=base))
    binding = e.mission.inbox.for_run('context-run')
    e.claims.offer('context-run', e.node['node_id'], Request('build', binding['prompt'], str(e.snapshot),
                   'gpt-6.1-sol', mode='workspace-write'), e.manifest)
    first = claim(e)
    status, response = call(e, body={'request_id': 'gateway_claim_02'})
    assert status == 200 and response['result']['claim']['run_key'] == 'context-run'
    c = response['result']['claim']
    spawn = [{'seq': 1, 'kind': 'process_started', 'data': {'pid': 17, 'driver': 'codex'}}]
    ack = call(e, 'sync', body=fields(c) | {'events': spawn})
    assert ack[0] == 200 and set(ack[1]['result']) == {'mission_id', 'run_key', 'node_id', 'claim_id', 'epoch', 'last_seq', 'lease_expires_at'}
    assert ack[1]['result'] == e.claims.sync(e.node['node_id'], c['claim_id'], 1, [])
    assert e.mission.inbox.messages()['messages'][0]['applications'][0]['status'] == 'BOUND'
    accepted = [{'seq': 2, 'kind': 'turn_bound', 'data': {'session_id': 'fixture-session', 'turn_id': 'fixture-turn'}}]
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: call(e, 'sync', body=fields(c) | {'events': accepted}), range(4)))
    assert all(r[0] == 200 for r in responses) and all(r == responses[0] for r in responses)
    page = e.mission.inbox.messages()
    assert page['messages'][0]['id'] == message['id'] and page['messages'][0]['status'] == 'APPLIED'
    updated = e.mission.inbox.messages(page['cursor'], application_cursor=0)
    assert any(item['id'] == message['id'] and item['status'] == 'APPLIED' for item in updated['updates'])
    before = state(e)
    assert call(e, 'sync', body=fields(c) | {'events': accepted}) == responses[0]
    assert state(e) == before
    conflict = [{'seq': 2, 'kind': 'turn_bound', 'data': {'session_id': 'other', 'turn_id': 'other'}}]
    assert call(e, 'sync', body=fields(c) | {'events': conflict})[0] == 409
    assert call(e, 'sync', body=fields(c) | {'events': [{'seq': 4, 'kind': 'session_bound', 'data': {'session_id': 'gap'}}]})[0] == 400
    assert state(e) == before and e.claims.get(e.key)['claim_id'] == first['claim_id']
    assert e.mission.store.verify_event_chain()['valid']


def test_heartbeat_is_independent_status_empty_duplicate_sync_never_renew(env):
    e = env
    offer(e, transport=True)
    c = claim(e)
    e.clock.advance(3)
    event = [{'seq': 1, 'kind': 'session_bound', 'data': {'session_id': 'fixture'}}]
    assert call(e, 'sync', body=fields(c) | {'events': event})[0] == 200
    deadline = e.claims.get(e.key)['lease_expires_at']
    e.clock.advance(3)
    before = state(e)
    assert call(e, 'sync', body=fields(c) | {'events': []})[0] == 200
    assert call(e, 'sync', body=fields(c) | {'events': event})[0] == 200
    assert call(e, 'status', body=fields(c))[1]['result'] == e.claims.status(e.node['node_id'], c['claim_id'], 1)
    assert e.claims.get(e.key)['lease_expires_at'] == deadline and state(e) == before
    e.claims.post_controls(e.key, [{'id': 'interrupt-fixture', 'action': 'interrupt', 'text': ''}])
    status, heartbeat = call(e, 'heartbeat', body=fields(c))
    assert status == 200 and heartbeat['result']['lease_expires_at'] > deadline
    assert heartbeat['controls'] == e.claims.pending_controls(e.node['node_id'], c['claim_id'], 1)
    assert heartbeat['controls'] == [{'id': 'interrupt-fixture', 'action': 'interrupt', 'text': ''}]
    assert 'controls' not in heartbeat['result']
    acknowledged = [{'seq': 2, 'kind': 'control_ack', 'data': {'command_id': 'interrupt-fixture', 'accepted': True}}]
    assert call(e, 'sync', body=fields(c) | {'events': acknowledged})[0] == 200
    assert call(e, 'heartbeat', body=fields(c))[1]['controls'] == []


def test_expired_status_owner_readback_unknown_no_new_claim_or_native(env):
    e = env
    offer(e, transport=True)
    c = claim(e)
    e.clock.advance(31)
    before = state(e)
    result = call(e, 'status', body=fields(c))
    assert result[0] == 200 and result[1]['result'] == e.claims.status(e.node['node_id'], c['claim_id'], 1)
    assert state(e) == before
    assert call(e, 'sync', body=fields(c) | {'events': []})[0] == 409
    assert call(e, 'heartbeat', body=fields(c))[0] == 409
    assert call(e, body={'request_id': 'gateway_claim_02'})[1]['result']['status'] == 'NO_WORK'
    assert call(e, body={'request_id': 'gateway_claim_01'})[1]['result']['claim'] == c
    assert e.claims.get(e.key)['status'] == 'UNKNOWN' and len(e.mission.journal.runs()) == 1


@pytest.mark.parametrize('operation,method', [('status', 'POST'), ('heartbeat', 'POST'), ('sync', 'POST'), ('receipt', 'POST'), ('inputs', 'GET'), ('uploads', 'PUT')])
def test_claim_owner_and_epoch_isolation(env, operation, method):
    e = env
    offer(e, transport=True)
    c = claim(e)
    body = fields(c)
    if operation == 'sync': body['events'] = []
    if operation == 'receipt': body.update(receipt={'status': 'ERROR'}, manifest=[], tree=full_tree_manifest(e.snapshot))
    target, query, raw = operation, None, None
    if operation in {'inputs', 'uploads'}:
        target += '/' + c['claim_id'] + '/1'
        query = {'path': 'input.txt' if operation == 'inputs' else 'result.txt'}
        if operation == 'uploads': query['sha256'], raw = hashlib.sha256(b'result').hexdigest(), b'result'
        body = None
    before = state(e)
    assert call(e, target, method=method, body=body, raw=raw, query=query, node=e.other)[0] == 403
    if body is not None: body['epoch'] = 2
    else: target = target[:-1] + '2'
    assert call(e, target, method=method, body=body, raw=raw, query=query)[0] == 409
    assert state(e) == before


def test_cross_mission_identity_no_transport_or_native_mutation(env):
    e = env
    second = e.root / 'second'
    second.mkdir()
    ident = e.hub.create(make_spec(second))['id']
    other_mission = e.hub._session(ident).mission
    registry = NodeRegistry(other_mission.journal)
    registry.enroll('gateway_enroll_03', 'second mission', ['codex'], ['gpt-6.1-sol'])
    before = state(e)
    assert call(e, target='/node/v1/' + ident + '/claim', body={'request_id': 'gateway_claim_01'})[0] == 401
    assert state(e) == before and not (other_mission.directory / 'remote').exists()


@pytest.mark.parametrize('attack', ['symlink', 'parent_symlink', 'hardlink', 'hash'])
def test_input_no_follow_ownership_and_hash_boundary(env, attack):
    e = env
    offer(e, transport=True)
    c = claim(e)
    path = e.snapshot / 'input.txt'
    retained = e.snapshot.with_name(e.snapshot.name + '-retained')
    if attack == 'symlink':
        path.rename(e.snapshot / 'input-retained.txt')
        path.symlink_to(e.snapshot / 'input-retained.txt')
    elif attack == 'parent_symlink':
        e.snapshot.rename(retained)
        e.snapshot.symlink_to(retained, target_is_directory=True)
    elif attack == 'hardlink': os.link(path, e.snapshot / 'hardlink-retained.txt')
    else: path.write_bytes(b'changed input')
    before = state(e)
    result = call(e, 'inputs/' + c['claim_id'] + '/1', method='GET', query={'path': 'input.txt'})
    assert result[0] in {400, 409} and state(e) == before
    assert e.claims.get(e.key)['status'] == 'CLAIMED'


def test_full_transport_inputs_upload_tree_receipt_retry_and_restart(env):
    e = env
    offer(e, transport=True)
    c = claim(e)
    assert call(e, 'inputs/' + c['claim_id'] + '/1', method='GET', query={'path': 'input.txt'}) == (200, b'fixed input')
    assert call(e, 'inputs/' + c['claim_id'] + '/1', method='GET', query={'path': 'missing.txt'})[0] == 404
    native_tree = e.root / 'node-worktree'
    native_tree.mkdir()
    (native_tree / 'input.txt').write_bytes(b'fixed input')
    (native_tree / 'result.txt').write_bytes(b'result')
    meta = {'path': 'result.txt', 'sha256': hashlib.sha256(b'result').hexdigest(), 'size': 6}
    upload = call(e, 'uploads/' + c['claim_id'] + '/1', method='PUT', raw=b'result', query={k: meta[k] for k in ('path', 'sha256')})
    assert upload == (200, {'controller_mission_id': e.ident, 'result': meta | {'status': 'STORED'}})
    body = fields(c) | {'receipt': asdict(Receipt('COMPLETED', requested_model='gpt-6.1-sol')),
                        'manifest': [meta], 'tree': full_tree_manifest(native_tree)}
    terminal = call(e, 'receipt', body=body)
    assert terminal[0] == 200 and terminal[1]['result']['status'] == 'RECEIPTED'
    assert terminal[1]['result'] == e.claims.status(e.node['node_id'], c['claim_id'], c['epoch'])
    before = state(e)
    assert call(e, 'receipt', body=body) == terminal and state(e) == before
    changed = dict(body, tree=dict(body['tree'], errors=[{'code': 'fixture', 'path': ''}], complete=False))
    assert call(e, 'receipt', body=changed)[0] == 409 and state(e) == before
    replacement = MissionHub(e.hub.directory)
    old_hub = e.gateway.hub
    e.gateway.hub = replacement
    try:
        assert call(e, 'receipt', body=body) == terminal
        assert call(e, 'status', body=fields(c))[1]['result'] == terminal[1]['result']
    finally:
        e.gateway.hub = old_hub
        replacement.close()
    assert e.mission.journal.runs()[0]['receipt'] is None
    assert e.mission.journal.runs()[0]['status'] == 'IN_FLIGHT'
    assert not e.mission.snapshot()['all_verified'] and e.mission.store.verify_event_chain()['valid']


@pytest.mark.parametrize('query', ['path=../input.txt', 'path=/input.txt', 'path=a%5Cb', 'path=.hidden',
    'path=auth.json', 'path=input.txt&path=input.txt', 'path=input.txt&root=/private', 'path=%ZZ',
    'path=%ff', 'path=input.txt&cursor=1', 'path=' + 'a'*1001, 'path=input.txt&sha256=' + 'b'*64])
def test_input_query_allowlist_and_paths(env, query):
    e = env
    offer(e, transport=True)
    c = claim(e)
    before = state(e)
    assert call(e, 'inputs/' + c['claim_id'] + '/1', method='GET', query=query)[0] == 400
    assert state(e) == before


def test_upload_limits_hash_conflicts_and_credentials_stay_out_of_artifacts(env):
    e = env
    offer(e)
    c = claim(e)
    route = 'uploads/' + c['claim_id'] + '/1'
    query = {'path': 'result.txt', 'sha256': hashlib.sha256(b'result').hexdigest()}
    before = state(e)
    assert call(e, route, method='PUT', raw=b'result', query=query, headers=[('Content-Length', '8000001')])[0] == 400
    assert call(e, route, method='PUT', raw=b'wrong', query=query)[0] == 400
    credential = ('Authorization: Node ' + e.node['secret']).encode()
    assert call(e, route, method='PUT', raw=credential, query={'path': 'result.txt', 'sha256': hashlib.sha256(credential).hexdigest()})[0] == 400
    assert state(e) == before and not (e.claims.artifact_root / c['claim_id']).exists()
    large = b'x'*8_000_000
    large_query = {'path': 'result.txt', 'sha256': hashlib.sha256(large).hexdigest()}
    assert call(e, route, method='PUT', raw=large, query=large_query)[0] == 200
    before = state(e)
    assert call(e, route, method='PUT', raw=large, query=large_query)[0] == 200 and state(e) == before
    assert call(e, route, method='PUT', raw=b'result', query=query)[0] == 409 and state(e) == before


@pytest.mark.parametrize('part,value', [('tree', None), ('tree', {}), ('tree', {'schema': True, 'files': [], 'tree': [], 'errors': [], 'complete': True}),
    ('tree', {'schema': 1, 'files': [], 'tree': [], 'errors': [], 'complete': 'true'}),
    ('manifest', [{'path': 'result.txt', 'sha256': 'bad', 'size': True}]),
    ('receipt', {'status': 'PASS'}), ('receipt', {'status': 'ERROR', 'usage': []}),
    ('receipt', {'status': 'ERROR', 'argv': ['FORBIDDEN']}),
    ('receipt', {'status': 'COMPLETED', 'exit_code': True})])
def test_transport_receipt_schema_requires_tree_before_any_mutation(env, part, value):
    e = env
    offer(e)
    c = claim(e)
    body = fields(c) | {'receipt': {'status': 'ERROR'}, 'manifest': [], 'tree': full_tree_manifest(e.snapshot)}
    body[part] = value
    before = state(e)
    result = call(e, 'receipt', body=body)
    assert result[0] == 400 and state(e) == before and 'FORBIDDEN' not in json.dumps(result)
    del body['tree']
    assert call(e, 'receipt', body=body)[0] == 400 and state(e) == before


def test_sync_schema_batches_and_secret_redaction_not_fake_native_identity(env):
    e = env
    offer(e)
    c = claim(e)
    before = state(e)
    bad = [
        [{'seq': True, 'kind': 'session_bound', 'data': {'session_id': 's'}}],
        [{'seq': 1, 'kind': 'shell', 'data': {'argv': ['FORBIDDEN']}}],
        [{'seq': 1, 'kind': 'process_started', 'data': {'pid': 2, 'driver': 'codex', 'acceptance': 'PASS'}}],
        [{'seq': n+1, 'kind': 'session_bound', 'data': {'session_id': 's'}} for n in range(101)],
        [{'seq': 1, 'kind': 'native_event', 'data': {'method': 'fixture', 'params': {'large': 'x'*64_000}}}],
    ]
    for events in bad:
        assert call(e, 'sync', body=fields(c) | {'events': events})[0] == 400 and state(e) == before
    secret = e.node['secret']
    event = [{'seq': 1, 'kind': 'native_event', 'data': {'method': 'fixture/event',
              'params': {'text': 'Authorization: Node ' + secret, 'secret': secret}}}]
    assert call(e, 'sync', body=fields(c) | {'events': event})[0] == 400
    assert secret not in state(e)[0]
    assert e.mission.journal.runs()[0]['status'] == 'IN_FLIGHT'


def test_internal_errors_have_correlated_sanitized_diagnostics_no_access_logging(env, monkeypatch, caplog, capsys):
    e = env
    offer(e)
    secret = e.node['secret']
    foreign = e.other['secret']
    def broken(*_args, **_kwargs):
        raise RuntimeError('fixture failure Authorization: Node ' + foreign + ' raw ' + secret + ' Bearer operator-fixture')
    monkeypatch.setattr(e.claims, 'claim', broken)
    status, error = call(e, body={'request_id': 'gateway_claim_01'})
    assert status == 500 and error['error']['diagnostic_id']
    assert error['error']['type'] == 'RuntimeError' and 'fixture failure' in error['error']['message']
    assert error['error']['diagnostic_id'] in caplog.text
    observed = json.dumps(error) + caplog.text + capsys.readouterr().out + capsys.readouterr().err
    assert secret not in observed and foreign not in observed and 'operator-fixture' not in observed
    assert 'POST /node/v1/' not in observed and not e.mission.journal.events()[-1]['type'].endswith('CLAIMED')

