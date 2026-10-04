from __future__ import annotations

import http.client
import json
import threading

import pytest

from sisyfus.workers.console import Console
from sisyfus.workers.mission import Mission
from test_workers import make_spec


@pytest.fixture
def console(tmp_path):
    _, spec = make_spec(tmp_path)
    mission = Mission(tmp_path / 'control', spec)
    mission.prepare()
    server = Console(mission, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join()


def request(server, path, *, body=None, auth=True, headers=None):
    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
    h = {'Authorization': 'Bearer ' + server.token} if auth else {}
    h.update(headers or {})
    raw = json.dumps(body) if body is not None else None
    if raw is not None: h['Content-Type'] = 'application/json'
    connection.request('POST' if body is not None else 'GET', path, body=raw, headers=h)
    response = connection.getresponse()
    content = response.read()
    connection.close()
    return response.status, content, dict(response.getheaders())


def test_auth_origin_host_and_read_only_get(console):
    before = console.mission.store.verify_event_chain()['event_count']
    assert request(console, '/api/snapshot', auth=False)[0] == 401
    assert request(console, '/api/snapshot', headers={'Host': 'evil.example'})[0] == 403
    assert request(console, '/api/snapshot', headers={'Origin': 'https://evil.example'})[0] == 403
    assert request(console, '/api/snapshot')[0] == 200
    assert console.mission.store.verify_event_chain()['event_count'] == before
    status, raw, headers = request(console, '/', auth=False)
    assert status == 200 and console.token.encode() not in raw
    assert 'nonce-' in headers['Content-Security-Policy']
    assert b'innerHTML' not in raw


def test_pause_and_cursor_replay(console):
    status, raw, _ = request(console, '/api/control', body={'action': 'pause'})
    assert status == 202 and json.loads(raw)['scope'] == 'new_dispatch_only'
    assert console.mission.journal.paused()
    status, raw, _ = request(console, '/api/events?cursor=0')
    events = json.loads(raw)['events']
    cursor = events[-1]['seq']
    assert request(console, '/api/control', body={'action': 'resume'})[0] == 202
    later = json.loads(request(console, '/api/events?cursor=' + str(cursor))[1])['events']
    assert all(e['seq'] > cursor for e in later) and later[-1]['type'] == 'WORKER_RESUME'
    assert request(console, '/api/control', body={'action': 'approve', 'verdict': 'PASS'})[0] == 400


def test_control_ack_is_not_native_completion(console):
    j = console.mission.journal
    j.reserve('one', 'build', 'fp')
    status, raw, _ = request(console, '/api/control', body={'action': 'interrupt', 'run_key': 'one'})
    assert status == 202 and json.loads(raw)['terminal'] is False
    assert j.runs()[0]['status'] == 'IN_FLIGHT' and j.runs()[0]['receipt'] is None
    controls = j.controls('one')
    assert len(controls) == 1 and j.controls('one') == []
    j.event('one', 'control_ack', {'command_id': controls[0]['id'], 'accepted': True})
    assert j.runs()[0]['status'] == 'IN_FLIGHT'


def test_claude_live_steering_rejected_not_faked(console):
    j = console.mission.journal
    j.reserve('review-call', 'review', 'fp')
    status, raw, _ = request(console, '/api/control', body={'action': 'steer', 'run_key': 'review-call', 'text': 'do this'})
    assert status == 400 and b'Codex' in raw
