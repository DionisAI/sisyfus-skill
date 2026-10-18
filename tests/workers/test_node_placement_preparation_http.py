"""Frozen operator preparation HTTP/Hub contracts, socket-free protocol fixtures.

Real Handler, MissionHub and LeadMission; no native CLI, sockets, deployments,
or user missions. Assertions are frozen before the first retained RED run.
Preparation ACK is acceptance of a request, never completion or worker consent.
"""
from __future__ import annotations

from email.message import Message
import io
import json
import socket
import threading
from types import SimpleNamespace

import pytest

from sisyfus.workers.lead_console import Handler, MAX_JSON_BYTES, MissionHub
from sisyfus.workers.lead_mission import LeadMission
from sisyfus.workers.protocol import Receipt, digest
from test_lead_mission import Stub, make_spec


TOKEN = 'placement-private-operator-fixture'
REQUEST = 'prepare_placement_0001'


def forbidden(*_args, **_kwargs):
    pytest.fail('this observation/preparation boundary must not dispatch execution')


@pytest.fixture(autouse=True)
def fixture_only(monkeypatch):
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(LeadMission, 'run', forbidden)


def factory(directory, spec=None):
    mission = LeadMission(directory, spec)
    mission.drivers = {'claude': Stub('claude'), 'codex': Stub('codex', forbidden)}
    return mission


@pytest.fixture
def hub(tmp_path):
    h = MissionHub(tmp_path / 'hub', mission_factory=factory)
    ident = h.create(make_spec(tmp_path))['id']
    try:
        yield h, ident
    finally:
        h.close()


def call(hub, path, *, method='GET', body=None, raw=None, headers=None):
    """Invoke actual Handler parsing/auth/routing without binding a socket."""
    handler = object.__new__(Handler)
    handler.server = SimpleNamespace(token=TOKEN, server_port=8781, hub=hub)
    handler.path = path
    handler.headers = Message()
    if raw is None and body is not None:
        raw = json.dumps(body).encode()
    if isinstance(raw, str):
        raw = raw.encode()
    raw = raw or b''
    defaults = [('Host', '127.0.0.1:8781'), ('Authorization', 'Bearer ' + TOKEN),
                ('Content-Type', 'application/json'), ('Content-Length', str(len(raw)))]
    replaced = {key.lower() for key, _ in headers or []}
    for key, value in [*(p for p in defaults if p[0].lower() not in replaced), *(headers or [])]:
        handler.headers[key] = value
    handler.rfile = io.BytesIO(raw)
    result = {}
    handler.send = lambda value, status=200, **_kwargs: result.update(status=status, value=value)
    getattr(handler, 'do_' + method)()
    return result['status'], result['value']


def route(ident):
    return '/api/missions/' + ident + '/prepare-placement'


def payload(**overrides):
    return {'request_id': REQUEST, 'allow_planning': True, **overrides}


def ack(value, ident, request_id=REQUEST):
    assert value['id'] == 'prepare-placement:' + request_id
    assert value['mission_id'] == ident and value['action'] == 'prepare-placement'
    assert value['status'] == 'ACK' and value['accepted'] is True
    assert value['terminal'] is False


def settle(h, ident):
    thread = h._session(ident).thread
    assert thread is not None
    thread.join(5)
    assert not thread.is_alive(), 'fixture preparation thread did not settle'
    return h.snapshot(ident)


def no_work(m):
    assert not m.drivers['codex'].requests
    assert all(r['role'] == 'lead' for r in m.journal.runs())
    assert not m.journal.records('reviews')
    assert not m.journal.records('integrations')
    assert not m.journal.records('diagnoses')
    assert m.integration_continuation() is None
    assert not m.snapshot()['all_verified']
    assert all(c['attempt_count'] == 0 for c in m.continuations().values())


def metadata(m):
    with m.store._transaction(immediate=False) as db:
        return [tuple(row) for row in db.execute('SELECT key,value FROM metadata ORDER BY key')]


@pytest.mark.parametrize('permission', [False, None, 0, 1, 'true', [], {}])
def test_hub_requires_literal_operator_planning_permission_without_effects(hub, permission):
    h, ident = hub
    m = h._session(ident).mission
    before = metadata(m)
    with pytest.raises(PermissionError):
        h.prepare_placement(ident, REQUEST, allow_planning=permission)
    assert metadata(m) == before and h.controls(ident) == []
    assert h._session(ident).thread is None
    no_work(m)


def test_hub_default_permission_is_not_a_grant(hub):
    h, ident = hub
    with pytest.raises(PermissionError):
        h.prepare_placement(ident, REQUEST)
    assert not h.controls(ident) and h._session(ident).thread is None


def test_initial_plan_prepare_freezes_then_replays_across_restart_without_thread(hub, monkeypatch):
    h, ident = hub
    m = h._session(ident).mission
    acceptance = m.spec['acceptance_hash']
    frozen_spec = digest(m.spec)
    first = h.prepare_placement(ident, REQUEST, allow_planning=True)
    ack(first, ident)
    view = settle(h, ident)
    record = view['snapshot']['placement_preparation']
    assert record['request_id'] == REQUEST and record['status'] == 'WAITING_PLACEMENT'
    assert view['snapshot']['phase'] == 'WAITING_PLACEMENT'
    assert record['revision'] == view['snapshot']['revision'] == 1
    assert record['task_hashes'] == {t['id']: digest(t) for t in m.active_tasks()}
    assert record['acceptance_hash'] == acceptance
    assert isinstance(record['plan_hash'], str) and len(record['plan_hash']) == 64
    assert all(c['context']['task_hash'] == record['task_hashes'][name]
               for name, c in m.continuations().items())
    assert digest(m.spec) == frozen_spec and not m.drivers['claude'].requests
    assert view['controller']['local_workers_acknowledged'] is False
    original_thread = h._session(ident).thread
    controls = h.controls(ident)
    assert len(controls) == 1 and controls[0]['id'] == first['id']
    assert controls[0]['action'] == 'prepare-placement' and controls[0]['status'] == 'ACK'
    assert controls[0]['terminal'] is False
    monkeypatch.setattr(m, 'prepare_for_placement', forbidden)
    assert h.prepare_placement(ident, REQUEST, allow_planning=True) == first
    assert h._session(ident).thread is original_thread and h.controls(ident) == controls
    h.close()
    monkeypatch.setattr(LeadMission, 'prepare_for_placement', forbidden)
    again = MissionHub(h.directory, mission_factory=factory)
    try:
        assert again.prepare_placement(ident, REQUEST, allow_planning=True) == first
        assert again._session(ident).thread is None
        assert again.snapshot(ident)['snapshot']['placement_preparation'] == record
        assert again.controls(ident) == controls
        no_work(again._session(ident).mission)
        assert again._session(ident).mission.store.verify_event_chain()['valid']
    finally:
        again.close()


def test_completed_preparation_conflicting_new_request_is_explicit(hub):
    h, ident = hub
    h.prepare_placement(ident, REQUEST, allow_planning=True)
    frozen = settle(h, ident)['snapshot']['placement_preparation']
    with pytest.raises(RuntimeError, match='request|conflict|prepar'):
        h.prepare_placement(ident, 'prepare_placement_0002', allow_planning=True)
    assert h.snapshot(ident)['snapshot']['placement_preparation'] == frozen
    no_work(h._session(ident).mission)


def test_native_fixture_ack_precedes_completion_and_start_is_excluded(tmp_path):
    h = MissionHub(tmp_path / 'hub', mission_factory=factory)
    ident = h.create(make_spec(tmp_path, initial=False))['id']
    m = h._session(ident).mission
    entered, release = threading.Event(), threading.Event()
    observed = {}
    def lead(request, _emit, _controls):
        observed['record'] = m.snapshot()['placement_preparation']
        observed['controls'] = h.controls(ident)
        observed['request'] = request
        entered.set()
        assert release.wait(5), 'fixture release not signalled'
    m.drivers['claude'] = Stub('claude', lead)
    try:
        first = call(h, route(ident), method='POST', body=payload())
        assert first[0] == 202
        ack(first[1], ident)
        assert entered.wait(3)
        assert observed['record']['request_id'] == REQUEST
        assert observed['record']['status'] == 'PLANNING'
        assert observed['controls'][0]['id'] == first[1]['id']
        assert observed['controls'][0]['status'] == 'ACK'
        assert observed['request'].model == 'claude-opus-5-5'
        assert h.snapshot(ident)['controller']['running'] is True
        assert h.snapshot(ident)['controller']['local_workers_acknowledged'] is False
        assert call(h, route(ident), method='POST', body=payload()) == first
        assert len(m.drivers['claude'].requests) == 1
        blocked = call(h, '/api/control', method='POST', body={
            'mission_id': ident, 'action': 'start', 'allow_local_workers': True})
        assert blocked[0] == 409
        assert h.snapshot(ident)['controller']['local_workers_acknowledged'] is False
        assert len(h.controls(ident)) == 1
        node = h.enroll_node(ident, 'node_enroll_0001', 'fixture concurrent assignment')
        assignment = {'request_id': 'node_placement_0001', 'task_id': 'build', 'node_id': node['node_id']}
        assert call(h, '/api/missions/' + ident + '/placements', method='POST', body=assignment)[0] == 400
        assert m.placement('build') == {'kind': 'local'}
    finally:
        release.set()
        if h._session(ident).thread:
            h._session(ident).thread.join(5)
        h.close()
    final = h.snapshot(ident)['snapshot']
    assert final['placement_preparation']['status'] == 'WAITING_PLACEMENT'
    assert final['placement_preparation']['acceptance_hash'] == m.spec['acceptance_hash']
    assert len(m.drivers['claude'].requests) == 1
    placed = call(h, '/api/missions/' + ident + '/placements', method='POST', body=assignment)
    assert placed[0] == 200 and placed[1]['execution_ready'] is False
    assert placed[1]['task_hash'] == final['placement_preparation']['task_hashes']['build']
    no_work(m)


@pytest.mark.parametrize('receipt_status,expected', [('UNKNOWN', 'UNKNOWN'), ('ERROR', 'ERROR')])
def test_native_unknown_or_error_replays_including_restart_without_resend(tmp_path, monkeypatch, receipt_status, expected):
    h = MissionHub(tmp_path / 'hub', mission_factory=factory)
    ident = h.create(make_spec(tmp_path, initial=False))['id']
    m = h._session(ident).mission
    m.drivers['claude'] = Stub('claude', lambda *_args: Receipt(
        receipt_status, error='retained fixture transport outcome', requested_model='claude-opus-5-5'))
    try:
        first = call(h, route(ident), method='POST', body=payload())
        assert first[0] == 202
        ack(first[1], ident)
        record = settle(h, ident)['snapshot']['placement_preparation']
        assert record['status'] == expected and len(m.drivers['claude'].requests) == 1
        assert m.journal.runs()[0]['receipt']['status'] == receipt_status
        thread = h._session(ident).thread
        monkeypatch.setattr(m, 'prepare_for_placement', forbidden)
        assert call(h, route(ident), method='POST', body=payload()) == first
        assert h._session(ident).thread is thread
        assert call(h, route(ident), method='POST', body=payload(request_id='prepare_placement_0002'))[0] == 409
        no_work(m)
    finally:
        h.close()
    monkeypatch.setattr(LeadMission, 'prepare_for_placement', forbidden)
    again = MissionHub(h.directory, mission_factory=factory)
    try:
        assert call(again, route(ident), method='POST', body=payload()) == first
        assert again._session(ident).thread is None
        assert again.snapshot(ident)['snapshot']['placement_preparation'] == record
        assert not again._session(ident).mission.drivers['claude'].requests
        assert len(again._session(ident).mission.journal.runs()) == 1
    finally:
        again.close()


def test_interrupted_pending_hub_control_is_readback_not_a_thread_restart(hub, monkeypatch):
    h, ident = hub
    h._record(h._session(ident), 'prepare-placement:' + REQUEST, 'prepare-placement')
    h.close()
    monkeypatch.setattr(LeadMission, 'prepare_for_placement', forbidden)
    again = MissionHub(h.directory, mission_factory=factory)
    try:
        result = again.prepare_placement(ident, REQUEST, allow_planning=True)
        ack(result, ident)
        assert again._session(ident).thread is None
        assert len(again.controls(ident)) == 1 and again.controls(ident)[0]['status'] == 'PENDING'
        no_work(again._session(ident).mission)
    finally:
        again.close()


def test_active_start_excludes_preparation_before_request_or_thread(hub, monkeypatch):
    h, ident = hub
    m = h._session(ident).mission
    entered, release = threading.Event(), threading.Event()
    def run(*, max_cycles=None):
        entered.set()
        assert release.wait(5)
        return m.snapshot()
    monkeypatch.setattr(m, 'run', run)
    h.start(ident, allow_local_workers=True)
    try:
        assert entered.wait(3)
        thread = h._session(ident).thread
        with pytest.raises(RuntimeError, match='running|controller|start|Start'):
            h.prepare_placement(ident, REQUEST, allow_planning=True)
        assert h._session(ident).thread is thread
        assert 'placement_preparation' not in m.snapshot()
        assert [c['action'] for c in h.controls(ident)] == ['start']
    finally:
        release.set()
        h._session(ident).thread.join(5)


def test_explicit_start_still_requires_worker_permission_and_reads_same_tasks(hub, monkeypatch):
    h, ident = hub
    h.prepare_placement(ident, REQUEST, allow_planning=True)
    frozen = settle(h, ident)['snapshot']['placement_preparation']
    m = h._session(ident).mission
    continuations = m.continuations()
    with pytest.raises(PermissionError):
        h.start(ident)
    assert h.snapshot(ident)['controller']['local_workers_acknowledged'] is False
    observed = {}
    def run(*, max_cycles=None):
        observed.update(record=m.snapshot()['placement_preparation'], tasks=m.continuations())
        return m.snapshot()
    monkeypatch.setattr(m, 'run', run)
    started = h.start(ident, allow_local_workers=True)
    assert started['accepted'] is True and started['terminal'] is False
    settle(h, ident)
    assert observed == {'record': frozen, 'tasks': continuations}
    assert h.snapshot(ident)['controller']['local_workers_acknowledged'] is True
    no_work(m)


@pytest.mark.parametrize('control', ['pause', 'stop'])
def test_preparation_keeps_operator_pause_stop_without_granting_workers(hub, control):
    h, ident = hub
    h.control(ident, control)
    before = h.snapshot(ident)['snapshot']
    result = call(h, route(ident), method='POST', body=payload())
    assert result[0] in {202, 409}
    if h._session(ident).thread:
        settle(h, ident)
    after = h.snapshot(ident)
    assert after['snapshot']['paused'] == before['paused']
    assert after['snapshot']['stopped'] == before['stopped']
    assert after['controller']['local_workers_acknowledged'] is False
    no_work(h._session(ident).mission)


def test_assign_before_plan_then_after_prepare_uses_frozen_task_and_staging(hub):
    h, ident = hub
    m = h._session(ident).mission
    node = h.enroll_node(ident, 'node_enroll_0001', 'fixture remote staging')
    assignment = {'request_id': 'node_placement_0001', 'task_id': 'build', 'node_id': node['node_id']}
    placement_route = '/api/missions/' + ident + '/placements'
    assert call(h, placement_route, method='POST', body=assignment)[0] == 400
    assert m.placement('build') == {'kind': 'local'}
    assert call(h, route(ident), method='POST', body=payload())[0] == 202
    record = settle(h, ident)['snapshot']['placement_preparation']
    placed = call(h, placement_route, method='POST', body=assignment)
    assert placed[0] == 200 and placed[1]['execution_ready'] is False
    assert placed[1]['task_hash'] == record['task_hashes']['build']
    assert placed[1]['revision'] == record['revision']
    assert call(h, placement_route, method='POST', body=assignment) == placed
    assert h.snapshot(ident)['snapshot']['placement_preparation'] == record
    assert h.nodes(ident)['execution_ready'] is False
    no_work(m)


@pytest.mark.parametrize('headers,status', [
    ([('Authorization', '')], 401), ([('Authorization', 'Bearer wrong')], 401),
    ([('Authorization', 'Node node_fixture_secret')], 401),
    ([('Authorization', 'Bearer ' + TOKEN), ('Authorization', 'Bearer ' + TOKEN)], 401),
    ([('Host', 'evil.example:8781')], 403),
    ([('Host', '127.0.0.1:8781'), ('Host', '127.0.0.1:8781')], 403),
    ([('Origin', 'https://evil.example')], 403),
    ([('Origin', 'http://127.0.0.1:8781'), ('Origin', 'http://127.0.0.1:8781')], 403),
    ([('X-Node-Id', 'node_fixture')], 403), ([('X-Sisyfus-Node-Id', 'node_fixture')], 403),
    ([('X-Sisyfus-Node', 'node_fixture')], 403), ([('X-Node-Secret', 'node_fixture_secret')], 403),
])
def test_http_auth_host_origin_node_identity_precede_preparation(hub, headers, status):
    h, ident = hub
    m = h._session(ident).mission
    before = metadata(m)
    result = call(h, route(ident), method='POST', body=payload(), headers=headers)
    assert result[0] == status and TOKEN not in json.dumps(result[1])
    assert metadata(m) == before and not h.controls(ident)
    assert h._session(ident).thread is None
    no_work(m)


@pytest.mark.parametrize('body,status', [
    ({}, 400), ({'request_id': REQUEST}, 400), ({'allow_planning': True}, 400),
    (payload(allow_planning=False), 403), (payload(allow_planning=None), 400),
    (payload(allow_planning=1), 400), (payload(allow_planning='true'), 400),
    (payload(request_id=[]), 400), (payload(request_id=True), 400),
    (payload(request_id='short'), 400), (payload(request_id='x' * 101), 400),
    (payload(request_id='bad/request'), 400), (payload(request_id='\ud800'), 400),
    (payload(spec={}), 400), (payload(argv=['shell']), 400),
    (payload(directory='/outside'), 400), (payload(node_id='node_fixture'), 400),
    (payload(acceptance='approve'), 400), (payload(allow_local_workers=True), 400),
    (payload(dispatch=True), 400), (payload(mission_id='other'), 400),
    (payload(task_id='build'), 400), (payload(max_cycles=1), 400),
])
def test_http_exact_body_and_permission_types_before_audit(hub, body, status):
    h, ident = hub
    m = h._session(ident).mission
    before = metadata(m)
    result = call(h, route(ident), method='POST', body=body)
    assert result[0] == status and 'message' in result[1]['error']
    assert metadata(m) == before and not h.controls(ident)
    assert h._session(ident).thread is None


@pytest.mark.parametrize('raw,headers', [
    ('[]', []), ('{"request_id":"first","request_id":"second","allow_planning":true}', []),
    ('{"x":NaN}', []), ('{', []), (b'\xff', []),
    ('{}', [('Content-Length', '-1')]), ('{}', [('Content-Length', '+2')]),
    ('{}', [('Content-Length', '2'), ('Content-Length', '2')]),
    ('{}', [('Content-Length', str(MAX_JSON_BYTES + 1))]),
    ('{}', [('Content-Length', '8')]), ('{}', [('Transfer-Encoding', 'chunked')]),
    ('{}', [('Content-Type', 'text/plain')]),
    ('{}', [('Content-Type', 'application/json'), ('Content-Type', 'text/plain')]),
])
def test_http_strict_json_framing_before_request_or_planning(hub, raw, headers):
    h, ident = hub
    m = h._session(ident).mission
    before = metadata(m)
    assert call(h, route(ident), method='POST', raw=raw, headers=headers)[0] == 400
    assert metadata(m) == before and not h.controls(ident)
    assert h._session(ident).thread is None


def test_http_exact_route_query_unknown_unbound_symlink_and_method(hub, tmp_path):
    h, ident = hub
    (h.directory / 'unbound').mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (h.directory / 'symlink').symlink_to(outside, target_is_directory=True)
    for target, expected in [('unknown', 404), ('unbound', 404), ('symlink', 400)]:
        assert call(h, route(target), method='POST', body=payload())[0] == expected
    for suffix in ['?x=1', '?allow_planning=true', '?request_id=' + REQUEST]:
        assert call(h, route(ident) + suffix, method='POST', body=payload())[0] == 400
    for path in [route(ident) + '/extra', '/api/missions/../prepare-placement',
                 '/api/missions/%2e%2e/prepare-placement']:
        assert call(h, path, method='POST', body=payload())[0] == 404
    assert call(h, route(ident))[0] == 404
    assert not list(outside.iterdir()) and not h.controls(ident)


def test_http_success_replay_conflict_and_restart_are_ack_not_completion(hub):
    h, ident = hub
    first = call(h, route(ident), method='POST', body=payload())
    assert first[0] == 202
    ack(first[1], ident)
    record = settle(h, ident)['snapshot']['placement_preparation']
    thread = h._session(ident).thread
    assert call(h, route(ident), method='POST', body=payload()) == first
    assert h._session(ident).thread is thread
    assert call(h, route(ident), method='POST', body=payload(request_id='prepare_placement_0002'))[0] == 409
    h.close()
    again = MissionHub(h.directory, mission_factory=factory)
    try:
        assert call(again, route(ident), method='POST', body=payload()) == first
        assert again._session(ident).thread is None
        assert again.snapshot(ident)['snapshot']['placement_preparation'] == record
        assert len(again.controls(ident)) == 1
        no_work(again._session(ident).mission)
    finally:
        again.close()


def test_read_inventory_events_messages_and_btw_never_prepare_or_backfill(hub, monkeypatch):
    h, ident = hub
    m = h._session(ident).mission
    before = metadata(m)
    monkeypatch.setattr(m, 'prepare_for_placement', forbidden, raising=False)
    for path in ['/api/missions', '/api/snapshot?mission_id=' + ident,
                 '/api/events?mission_id=' + ident, '/api/mission/messages?mission_id=' + ident]:
        assert call(h, path)[0] == 200
    assert metadata(m) == before
    status, reply = call(h, '/api/mission/message', method='POST', body={
        'mission_id': ident, 'request_id': 'btw_request_0001', 'message': '/btw'})
    assert status == 200 and reply['status'] == 'ANSWERED' and reply['answer']['observation_only']
    assert 'placement_preparation' not in m.snapshot()
    assert not h.controls(ident) and h._session(ident).thread is None
    no_work(m)
    h.close()
    again = MissionHub(h.directory, mission_factory=factory)
    try:
        monkeypatch.setattr(again._session(ident).mission, 'prepare_for_placement', forbidden, raising=False)
        assert 'placement_preparation' not in again.snapshot(ident)['snapshot']
        assert call(again, '/api/mission/messages?mission_id=' + ident)[0] == 200
        assert again._session(ident).thread is None
    finally:
        again.close()
