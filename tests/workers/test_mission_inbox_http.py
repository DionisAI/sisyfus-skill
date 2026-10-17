"""Frozen HTTP acceptance through actual Handler + actual MissionHub/LeadMission.

The default harness is socket-free (real parsing/auth/route/body paths). Set
SISYFUS_TEST_LOOPBACK=1 for the retained real HTTP integration test on a host
permitting sockets. No scenario is adjusted after execution.
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
from test_lead_mission import make_spec


@pytest.fixture
def hub(tmp_path):
    hub = MissionHub(tmp_path / 'hub')
    ident = hub.create(make_spec(tmp_path))['id']
    yield hub, ident
    hub.close()


def call(hub, path='/api/mission/messages', *, method='GET', body=None, raw=None, headers=None):
    handler = object.__new__(Handler)
    handler.server = SimpleNamespace(token='fixture-token-private', server_port=8781, hub=hub)
    handler.path = path
    handler.headers = Message()
    defaults = [('Host', '127.0.0.1:8781'), ('Authorization', 'Bearer fixture-token-private')]
    if raw is None and body is not None:
        raw = json.dumps(body).encode()
    if isinstance(raw, str):
        raw = raw.encode()
    raw = raw or b''
    defaults += [('Content-Type', 'application/json'), ('Content-Length', str(len(raw)))]
    replaced = {key.lower() for key, _ in headers or []}
    for key, value in [*(entry for entry in defaults if entry[0].lower() not in replaced), *(headers or [])]:
        handler.headers[key] = value
    handler.rfile = io.BytesIO(raw)
    result = {}
    def send(value, status=200, **_kwargs):
        result.update(status=status, value=value)
    handler.send = send
    getattr(handler, 'do_' + method)()
    return result['status'], result['value']


def payload(ident, **kwargs):
    return {'mission_id': ident, 'message': '资料', 'request_id': 'request_0001', **kwargs}


def test_http_shapes_idempotence_query_answers_and_no_worker_dispatch(hub):
    h, ident = hub
    first = call(h, '/api/mission/message', method='POST', body=payload(ident))
    assert first[0] == 200 and first[1]['status'] == 'RECEIVED'
    assert call(h, '/api/mission/message', method='POST', body=payload(ident)) == first
    status, data = call(h, '/api/mission/messages?mission_id=' + ident + '&cursor=0')
    assert status == 200 and data['messages'] == [first[1]]
    assert data['cursor'] == first[1]['seq']
    assert call(h, '/api/mission/message', method='POST', body=payload(ident, message='different'))[0] == 409
    status, query = call(h, '/api/mission/message', method='POST', body=payload(ident, message='/btw', request_id='request_0002'))
    assert status == 200 and query['status'] == 'ANSWERED' and query['answer']['observation_only']
    assert not h._session(ident).mission.journal.runs()


@pytest.mark.parametrize('headers,status', [
    ([('Authorization', '')], 401), ([('Authorization', 'Bearer wrong')], 401),
    ([('Authorization', 'Bearer fixture-token-private'), ('Authorization', 'Bearer fixture-token-private')], 401),
    ([('Host', 'evil.example:8781')], 403),
    ([('Host', '127.0.0.1:8781'), ('Host', '127.0.0.1:8781')], 403),
    ([('Origin', 'https://evil.example')], 403),
    ([('Origin', 'http://127.0.0.1:8781'), ('Origin', 'http://127.0.0.1:8781')], 403),
])
@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_api_auth_host_origin_before_side_effects(hub, headers, status, method):
    h, ident = hub
    path = '/api/mission/message' if method == 'POST' else '/api/mission/messages?mission_id=' + ident
    result = call(h, path, method=method, body=payload(ident) if method == 'POST' else None, headers=headers)
    assert result[0] == status and 'fixture-token-private' not in json.dumps(result[1])
    assert not h.messages(ident)['messages'] and not h._session(ident).mission.journal.runs()


@pytest.mark.parametrize('query', [
    'cursor=-1', 'cursor=+1', 'cursor=1.2', 'cursor=', 'cursor=9223372036854775808',
    'cursor=0&cursor=1', 'unknown=1', 'mission_id=', 'mission_id=%ZZ',
    'mission_id=%FF', 'bad', 'application_cursor=-1', 'application_cursor=1e3',
    'cursor=' + '0' * 200, 'x=' + 'a' * 17000,
])
def test_http_malformed_and_bounded_queries(hub, query):
    h, ident = hub
    base = '' if 'mission_id=' in query else 'mission_id=' + ident + '&'
    assert call(h, '/api/mission/messages?' + base + query)[0] == 400
    assert not h.messages(ident)['messages']


@pytest.mark.parametrize('override', [
    {'mission_id': []}, {'mission_id': '../outside'}, {'message': None}, {'message': True},
    {'message': 'x' * 20001}, {'message': '\ud800'}, {'request_id': []},
    {'task_id': {}}, {'task_id': 'other-mission'}, {'unknown': 'ignored?'},
])
def test_http_invalid_input_types_and_scopes(hub, override):
    h, ident = hub
    assert call(h, '/api/mission/message', method='POST', body=payload(ident, **override))[0] == 400
    assert not h.messages(ident)['messages']


@pytest.mark.parametrize('raw,headers', [
    ('[]', []), ('{"mission_id":"x","mission_id":"x"}', []), ('{"x":NaN}', []),
    ('{', []), (b'\xff', []), ('{}', [('Content-Length', '-1')]),
    ('{}', [('Content-Length', '+2')]), ('{}', [('Content-Length', '2'), ('Content-Length', '2')]),
    ('{}', [('Content-Length', str(MAX_JSON_BYTES + 1))]),
    ('{}', [('Content-Length', '8')]), ('{}', [('Transfer-Encoding', 'chunked')]),
    ('{}', [('Content-Type', 'text/plain')]),
    ('{}', [('Content-Type', 'application/json'), ('Content-Type', 'text/plain')]),
])
def test_http_malformed_json_framing_and_content_types(hub, raw, headers):
    h, ident = hub
    assert call(h, '/api/mission/message', method='POST', raw=raw, headers=headers)[0] == 400
    assert not h.messages(ident)['messages']


def test_http_unknown_mission_and_malformed_url_have_explicit_errors(hub):
    h, _ident = hub
    assert call(h, '/api/mission/messages?mission_id=unknown')[0] == 404
    assert call(h, 'http://[broken')[0] == 400
    assert call(h, '/api/mission/message?extra=1', method='POST', body={})[0] == 404


def test_http_application_refresh_shape(hub):
    from sisyfus.workers.protocol import digest
    h, ident = hub
    _, first = call(h, '/api/mission/message', method='POST', body=payload(ident))
    m = h._session(ident).mission
    m.journal.reserve('bound', 'build', digest('base'), on_reserved=lambda db: m.inbox.bind(
        db, 'bound', role='worker', task_id='build', prompt='base'))
    url = '/api/mission/messages?mission_id=' + ident + '&cursor=' + str(first['seq'])
    status, refresh = call(h, url + '&application_cursor=0')
    assert status == 200 and not refresh['messages'] and refresh['updates'][0]['id'] == first['id']
    m.native_event('bound', 'turn_bound', {'turn_id': 'native-accepted'})
    status, applied = call(h, url + '&application_cursor=' + str(refresh['application_cursor']))
    assert status == 200 and applied['updates'][0]['status'] == 'APPLIED'


@pytest.mark.skipif(os.environ.get('SISYFUS_TEST_LOOPBACK') != '1', reason='explicit loopback socket permission required')
def test_real_http_round_trip_restart_and_mission_isolation(tmp_path):
    root = tmp_path / 'source-one'
    root.mkdir()
    second = tmp_path / 'source-two'
    second.mkdir()
    h = MissionHub(tmp_path / 'live-hub')
    a, b = h.create(make_spec(root))['id'], h.create(make_spec(second))['id']
    def session(hub):
        server = LeadConsole(hub, port=0)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        return server, thread
    def request(server, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        try:
            conn.request('POST' if body else 'GET', path, body=json.dumps(body) if body else None,
                headers={'Authorization': 'Bearer ' + server.token, 'Content-Type': 'application/json'})
            result = conn.getresponse()
            return result.status, json.loads(result.read())
        finally:
            conn.close()
    server, thread = session(h)
    try:
        first = request(server, '/api/mission/message', payload(a))
        assert first[0] == 200
        assert not request(server, '/api/mission/messages?mission_id=' + b + '&cursor=0')[1]['messages']
    finally:
        server.shutdown()
        server.server_close()
        thread.join(10)
        h.close()
    again = MissionHub(tmp_path / 'live-hub')
    server, thread = session(again)
    try:
        assert request(server, '/api/mission/message', payload(a)) == first
        assert len(request(server, '/api/mission/messages?mission_id=' + a + '&cursor=0')[1]['messages']) == 1
        assert not again._session(a).mission.journal.runs()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(10)
        again.close()


def test_btw_cache_miss_constructor_does_not_reconcile_or_dispatch(tmp_path, monkeypatch):
    from sisyfus.workers.lead_journal import LeadJournal
    from sisyfus.workers.lead_mission import LeadMission
    from sisyfus.workers.protocol import digest
    h = MissionHub(tmp_path / 'read-hub')
    ident = h.create(make_spec(tmp_path))['id']
    m = h._session(ident).mission
    m.journal.reserve('orphan', 'planner', digest('unknown ownership'))
    before = m.store.verify_event_chain()
    h.close()
    def forbidden(*_args, **_kwargs):
        pytest.fail('observation must never reconcile, run, or reserve')
    monkeypatch.setattr(LeadJournal, 'reconcile_roles', forbidden)
    monkeypatch.setattr(LeadJournal, 'reconcile_expired', forbidden)
    monkeypatch.setattr(LeadJournal, 'reserve', forbidden)
    monkeypatch.setattr(LeadMission, 'run', forbidden)
    again = MissionHub(tmp_path / 'read-hub')
    try:
        status, query = call(again, '/api/mission/message', method='POST', body=payload(ident, message='/btw'))
        assert status == 200 and query['answer']['phase'] == 'UNKNOWN'
        runs = again._session(ident).mission.journal.runs()
        assert len(runs) == 1 and runs[0]['status'] == 'IN_FLIGHT'
        assert query['answer']['observed_event_cursor'] == before['event_count']
    finally:
        again.close()
