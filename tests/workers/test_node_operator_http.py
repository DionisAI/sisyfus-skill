"""Frozen N2 operator HTTP contracts; real Handler, bound MissionHub/LeadMission.

Socket-free parsing/auth/routing tests by default. The real retained loopback
case requires explicit SISYFUS_TEST_LOOPBACK=1; it invokes no native driver.
No frozen scenario/assertion is changed after observing implementation results.
"""
from __future__ import annotations

from email.message import Message
import http.client
import io
import json
import os
import threading
from types import SimpleNamespace

import pytest

from sisyfus.workers.lead_console import Handler, LeadConsole, MissionHub, MAX_JSON_BYTES
from sisyfus.workers.protocol import digest
from test_lead_mission import make_spec


@pytest.fixture
def hub(tmp_path):
    h = MissionHub(tmp_path / 'hub')
    ident = h.create(make_spec(tmp_path))['id']
    h._session(ident).mission._initial_plan()
    yield h, ident
    h.close()


def call(hub, path, *, method='GET', body=None, raw=None, headers=None):
    handler = object.__new__(Handler)
    handler.server = SimpleNamespace(token='N2-private-operator-fixture', server_port=8781, hub=hub)
    handler.path = path
    handler.headers = Message()
    defaults = [('Host', '127.0.0.1:8781'), ('Authorization', 'Bearer N2-private-operator-fixture')]
    if raw is None and body is not None:
        raw = json.dumps(body).encode()
    if isinstance(raw, str):
        raw = raw.encode()
    raw = raw or b''
    defaults += [('Content-Type', 'application/json'), ('Content-Length', str(len(raw)))]
    replaced = {key.lower() for key, _ in headers or []}
    for key, value in [*(p for p in defaults if p[0].lower() not in replaced), *(headers or [])]:
        handler.headers[key] = value
    handler.rfile = io.BytesIO(raw)
    result = {}
    handler.send = lambda value, status=200, **_kwargs: result.update(status=status, value=value)
    getattr(handler, 'do_' + method)()
    return result['status'], result['value']


def nodes(ident):
    return '/api/missions/' + ident + '/nodes'


def placements(ident):
    return '/api/missions/' + ident + '/placements'


def enroll(h, ident, serial=1):
    return call(h, nodes(ident), method='POST', body={'request_id': 'node_enroll_%04d' % serial, 'name': 'N2 node %d' % serial})


def backend_tables(m):
    with m.store._transaction(immediate=False) as db:
        return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'remote_%'")]


def test_operator_shapes_first_secret_only_inventory_and_no_dispatch(hub):
    h, ident = hub
    m = h._session(ident).mission
    frozen = digest(m.spec)
    status, node = enroll(h, ident)
    assert status == 201 and len(node['secret']) == 64 and node['execution_ready'] is False
    again_status, replay = enroll(h, ident)
    assert again_status == 200 and replay['node_id'] == node['node_id'] and replay['secret'] is None
    status, listing = call(h, nodes(ident))
    assert status == 200 and listing['mission_id'] == ident and listing['execution_ready'] is False
    assert len(listing['nodes']) == 1 and 'secret' not in listing['nodes'][0]
    payload = {'request_id': 'placement_0001', 'task_id': 'build', 'node_id': node['node_id']}
    assigned = call(h, placements(ident), method='POST', body=payload)
    assert assigned[0] == 200 and assigned[1]['execution_ready'] is False
    assert call(h, placements(ident), method='POST', body=payload) == assigned
    revoked = call(h, nodes(ident) + '/' + node['node_id'] + '/revoke', method='POST', body={})
    assert revoked[0] == 200 and revoked[1]['status'] == 'REVOKED' and 'secret' not in revoked[1]
    assert call(h, nodes(ident) + '/' + node['node_id'] + '/revoke', method='POST', body={}) == revoked
    assert node['secret'] not in json.dumps([listing, assigned, revoked, m.journal.events()])
    assert node['secret'] not in m.store.path.read_bytes().decode('latin1')
    assert not m.journal.runs() and digest(m.spec) == frozen and not m.snapshot()['all_verified']


@pytest.mark.parametrize('headers,status', [
    ([('Authorization', '')], 401), ([('Authorization', 'Bearer wrong')], 401),
    ([('Authorization', 'Node node_fixture_secret')], 401),
    ([('Authorization', 'Bearer N2-private-operator-fixture'), ('Authorization', 'Bearer N2-private-operator-fixture')], 401),
    ([('Host', 'evil.example:8781')], 403),
    ([('Host', '127.0.0.1:8781'), ('Host', '127.0.0.1:8781')], 403),
    ([('Origin', 'https://evil.example')], 403),
    ([('Origin', 'http://127.0.0.1:8781'), ('Origin', 'http://127.0.0.1:8781')], 403),
    ([('X-Node-Id', 'node_fixture')], 403), ([('X-Sisyfus-Node-Id', 'node_fixture')], 403),
])
@pytest.mark.parametrize('route', ['inventory', 'enroll', 'revoke', 'placement'])
def test_auth_identity_host_origin_before_lazy_backend_initialization(hub, headers, status, route):
    h, ident = hub
    m = h._session(ident).mission
    assert not backend_tables(m)
    path, method, body = nodes(ident), 'GET', None
    if route == 'enroll':
        method, body = 'POST', {'request_id': 'node_enroll_0001', 'name': 'first'}
    elif route == 'revoke':
        path, method, body = nodes(ident) + '/node_' + 'a' * 32 + '/revoke', 'POST', {}
    elif route == 'placement':
        path, method, body = placements(ident), 'POST', {'request_id': 'placement_0001', 'task_id': 'build', 'node_id': 'node_' + 'a' * 32}
    result = call(h, path, method=method, body=body, headers=headers)
    assert result[0] == status and 'N2-private-operator-fixture' not in json.dumps(result[1])
    assert not backend_tables(m) and not (m.directory / 'remote').exists() and not m.journal.runs()


@pytest.mark.parametrize('raw,headers', [
    ('[]', []), ('{"name":"x","name":"y"}', []), ('{"x":NaN}', []),
    ('{', []), (b'\xff', []), ('{}', [('Content-Length', '-1')]),
    ('{}', [('Content-Length', '+2')]), ('{}', [('Content-Length', '2'), ('Content-Length', '2')]),
    ('{}', [('Content-Length', str(MAX_JSON_BYTES + 1))]), ('{}', [('Content-Length', '8')]),
    ('{}', [('Transfer-Encoding', 'chunked')]), ('{}', [('Content-Type', 'text/plain')]),
    ('{}', [('Content-Type', 'application/json'), ('Content-Type', 'text/plain')]),
])
def test_malformed_json_framing_and_body_limits_precede_backend(hub, raw, headers):
    h, ident = hub
    assert call(h, nodes(ident), method='POST', raw=raw, headers=headers)[0] == 400
    assert not backend_tables(h._session(ident).mission)


@pytest.mark.parametrize('body', [{}, {'name': 'x'}, {'request_id': 'node_enroll_0001'},
    {'request_id': 'node_enroll_0001', 'name': 'x', 'drivers': ['shell']},
    {'request_id': 'node_enroll_0001', 'name': 'x', 'models': ['unapproved']},
    {'request_id': 'node_enroll_0001', 'name': 'x', 'directory': '/outside'},
    {'request_id': 'node_enroll_0001', 'name': 'x', 'acceptance': 'approve'}])
def test_exact_operator_enroll_fields_do_not_accept_capability_or_path_input(hub, body):
    h, ident = hub
    assert call(h, nodes(ident), method='POST', body=body)[0] == 400
    assert not backend_tables(h._session(ident).mission)


@pytest.mark.parametrize('changes', [{'request_id': []}, {'request_id': 'short'}, {'name': None},
    {'name': True}, {'name': 'x' * 201}, {'name': '\ud800'}, {'name': 'bad\nname'}])
def test_invalid_node_registration_types_are_explicit_errors(hub, changes):
    h, ident = hub
    result = call(h, nodes(ident), method='POST', body={'request_id': 'node_enroll_0001', 'name': 'x', **changes})
    assert result[0] == 400
    assert not h._session(ident).mission.journal.runs()


@pytest.mark.parametrize('changes', [{'request_id': []}, {'task_id': []}, {'task_id': 'planner'},
    {'task_id': 'integration:1'}, {'node_id': []}, {'role': 'worker'}, {'driver': 'codex'},
    {'acceptance': 'approve'}, {'allow_local_workers': True}, {'mission_id': 'other'}, {'revision': 0}])
def test_placement_input_never_chooses_role_acceptance_revision_or_other_mission(hub, changes):
    h, ident = hub
    _, node = enroll(h, ident)
    body = {'request_id': 'placement_0001', 'task_id': 'build', 'node_id': node['node_id'], **changes}
    assert call(h, placements(ident), method='POST', body=body)[0] == 400
    assert h._session(ident).mission.placement('build') == {'kind': 'local'}


def test_unknown_unbound_symlink_paths_and_strict_route_queries(hub, tmp_path):
    h, ident = hub
    m = h._session(ident).mission
    (h.directory / 'unbound').mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (h.directory / 'symlink').symlink_to(outside, target_is_directory=True)
    for target, expected in [('unknown', 404), ('unbound', 404), ('symlink', 400)]:
        assert call(h, nodes(target))[0] == expected
    for path in [nodes(ident) + '?cursor=0', nodes(ident) + '?mission_id=other', placements(ident) + '?x=1']:
        assert call(h, path, method='POST' if '/placements' in path else 'GET', body={} if '/placements' in path else None)[0] == 400
    for path in ['/api/missions/../nodes', '/api/missions/%2e%2e/nodes', nodes(ident) + '/extra']:
        assert call(h, path)[0] == 404
    assert not backend_tables(m) and not list(outside.iterdir())


def test_conflicts_reservations_revoked_cross_mission_and_trial_errors(hub, tmp_path):
    h, ident = hub
    _, node = enroll(h, ident)
    assert call(h, nodes(ident), method='POST', body={'request_id': 'node_enroll_0001', 'name': 'changed'})[0] == 409
    _, second = enroll(h, ident, 2)
    payload = {'request_id': 'placement_0001', 'task_id': 'build', 'node_id': node['node_id']}
    first = call(h, placements(ident), method='POST', body=payload)
    assert first[0] == 200
    assert call(h, placements(ident), method='POST', body={**payload, 'node_id': second['node_id']})[0] == 409
    m = h._session(ident).mission
    m.journal.reserve('prior-http', 'build', digest('fixture reservation'))
    assert call(h, placements(ident), method='POST', body=payload) == first
    assert call(h, placements(ident), method='POST', body={**payload, 'request_id': 'placement_0002'})[0] == 409
    other_root = tmp_path / 'other-source'
    other_root.mkdir()
    other = h.create(make_spec(other_root))['id']
    other_mission = h._session(other).mission
    other_mission._initial_plan()
    foreign = {**payload, 'request_id': 'placement_other'}
    assert call(h, placements(other), method='POST', body=foreign)[0] == 403
    _, other_node = enroll(h, other)
    assert call(h, nodes(other) + '/' + other_node['node_id'] + '/revoke', method='POST', body={'unknown': 1})[0] == 400
    assert call(h, nodes(other) + '/' + other_node['node_id'] + '/revoke', method='POST', body={})[0] == 200
    assert call(h, placements(other), method='POST', body={**foreign, 'node_id': other_node['node_id']})[0] == 403
    with other_mission.store._transaction() as db:
        db.execute('INSERT INTO metadata VALUES(?,?)', ('techlead:inbox_policy:trial-child', 'true'))
    assert call(h, nodes(other))[0] == 403
    assert call(h, placements(other), method='POST', body={**foreign, 'node_id': other_node['node_id']})[0] == 403


@pytest.mark.skipif(os.environ.get('SISYFUS_TEST_LOOPBACK') != '1', reason='explicit retained loopback permission required')
def test_real_loopback_operator_nodes_placement_restart_no_native(tmp_path):
    h = MissionHub(tmp_path / 'live-hub')
    ident = h.create(make_spec(tmp_path))['id']
    h._session(ident).mission._initial_plan()
    def request(server, path, *, body=None, auth=None):
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        try:
            connection.request('POST' if body is not None else 'GET', path,
                body=json.dumps(body) if body is not None else None,
                headers={'Authorization': auth or 'Bearer ' + server.token, 'Content-Type': 'application/json'})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()
    for generation in range(2):
        server = LeadConsole(h, port=0)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            assert request(server, nodes(ident), auth='Node synthetic-node-secret')[0] == 401
            assert request(server, nodes(ident))[0] == 200
            status, node = request(server, nodes(ident), body={'request_id': 'node_enroll_live', 'name': 'live fixture'})
            assert status == (201 if generation == 0 else 200)
            assert (node['secret'] is not None) is (generation == 0)
            status, placement = request(server, placements(ident), body={'request_id': 'placement_live', 'task_id': 'build', 'node_id': node['node_id']})
            assert status == 200 and placement['execution_ready'] is False
            if generation == 0:
                pinned = placement
            else:
                assert placement == pinned
            assert not h._session(ident).mission.journal.runs()
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
            h.close()
        h = MissionHub(tmp_path / 'live-hub')
    h.close()
