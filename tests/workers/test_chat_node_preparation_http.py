"""Frozen conversation planning-only HTTP boundary, real Handler without sockets.

This slice exercises parsing, authorization and exact delegation, not native
planning or remote/phone acceptance. Backend lifecycle has separate fixed tests.
"""
from email.message import Message
import io
import json
from types import SimpleNamespace

import pytest

from sisyfus.workers.lead_console import Handler, MAX_JSON_BYTES


TOKEN = 'chat-preparation-operator-fixture'
ROUTE = '/api/chat/prepare-placement'
PAYLOAD = {'chat_id': 'c_fixture0001', 'allow_planning': True,
           'request_id': 'chat_prepare_0001', 'approval_hash': 'a' * 64}


class Chats:
    def __init__(self, exc=None):
        self.calls = []
        self.exc = exc

    def prepare_placement(self, chat_id, allow_planning, request_id, approval_hash):
        self.calls.append((chat_id, allow_planning, request_id, approval_hash))
        if self.exc is not None:
            raise self.exc
        return {'id': chat_id, 'mission_id': 'm_fixture0001', 'status': 'IDLE',
                'placement_preparation': {'request_id': request_id, 'status': 'REQUESTED'},
                'proof': 'accepted preparation only, not worker consent or PASS'}

    def start(self, *_args, **_kwargs):
        pytest.fail('planning-only route dispatched chat Start')


class Hub:
    def create(self, *_args, **_kwargs):
        pytest.fail('HTTP bypassed ChatManager binding')

    def start(self, *_args, **_kwargs):
        pytest.fail('HTTP granted worker execution')


def call(chats, *, body=None, raw=None, headers=None, path=ROUTE, method='POST'):
    handler = object.__new__(Handler)
    handler.server = SimpleNamespace(token=TOKEN, server_port=8781, hub=Hub(), chats=chats)
    handler.path = path
    if raw is None:
        raw = json.dumps(PAYLOAD if body is None else body).encode()
    if isinstance(raw, str):
        raw = raw.encode()
    handler.headers = Message()
    defaults = [('Host', '127.0.0.1:8781'), ('Authorization', 'Bearer ' + TOKEN),
                ('Content-Type', 'application/json'), ('Content-Length', str(len(raw)))]
    replaced = {key.lower() for key, _ in headers or []}
    for key, value in [*(item for item in defaults if item[0].lower() not in replaced), *(headers or [])]:
        handler.headers[key] = value
    handler.rfile = io.BytesIO(raw)
    result = {}
    handler.send = lambda value, status=200, **_kwargs: result.update(status=status, value=value)
    getattr(handler, 'do_' + method)()
    return result['status'], result['value']


def test_preparation_is_exact_202_delegation_without_start_or_synthesized_success():
    chats = Chats()
    code, value = call(chats)
    assert code == 202
    assert chats.calls == [(PAYLOAD['chat_id'], True, PAYLOAD['request_id'], PAYLOAD['approval_hash'])]
    assert value['mission_id'] == 'm_fixture0001'
    assert value['placement_preparation']['status'] == 'REQUESTED'
    assert value['proof'] == 'accepted preparation only, not worker consent or PASS'
    assert 'all_verified' not in value


@pytest.mark.parametrize('key', sorted(PAYLOAD))
def test_missing_fields_rejected_before_backend(key):
    chats = Chats()
    code, _ = call(chats, body={k: v for k, v in PAYLOAD.items() if k != key})
    assert code == 400 and chats.calls == []


@pytest.mark.parametrize('extra', ['spec', 'source', 'node_id', 'argv', 'directory', 'acceptance',
                                 'allow_local_workers', 'dispatch', 'max_cycles', 'prompt', 'controls'])
def test_unknown_authority_fields_rejected_before_backend(extra):
    chats = Chats()
    code, _ = call(chats, body={**PAYLOAD, extra: True})
    assert code == 400 and chats.calls == []


@pytest.mark.parametrize('permission', [None, 0, 1, 'true', [], {}])
def test_nonboolean_planning_permission_rejected_before_backend(permission):
    chats = Chats()
    code, _ = call(chats, body={**PAYLOAD, 'allow_planning': permission})
    assert code == 400 and chats.calls == []


def test_false_permission_is_not_a_planning_grant():
    chats = Chats()
    code, _ = call(chats, body={**PAYLOAD, 'allow_planning': False})
    assert code == 403 and chats.calls == []


@pytest.mark.parametrize('headers, expected', [
    ([('Host', 'evil.invalid:8781')], 403),
    ([('Host', '127.0.0.1:8781'), ('Host', 'localhost:8781')], 403),
    ([('Origin', 'http://evil.invalid')], 403),
    ([('Origin', 'http://127.0.0.1:8781'), ('Origin', 'http://127.0.0.1:8781')], 403),
    ([('Authorization', 'Node fixture-secret')], 401),
    ([('Authorization', '')], 401),
    ([('Authorization', 'Bearer wrong-fixture')], 401),
    ([('Authorization', 'Bearer ' + TOKEN), ('Authorization', 'Bearer ' + TOKEN)], 401),
    ([('X-Sisyfus-Node', 'node_fixture')], 403),
    ([('X-Node-Identity', 'node_fixture')], 403),
    ([('X-Sisyfus-Node-Secret', 'fixture-secret')], 403),
])
def test_existing_operator_boundary_blocks_before_preparation(headers, expected):
    chats = Chats()
    code, _ = call(chats, headers=headers)
    assert code == expected and chats.calls == []


@pytest.mark.parametrize('headers', [
    [('Content-Type', 'text/plain')],
    [('Content-Type', 'application/json'), ('Content-Type', 'application/json')],
    [('Content-Length', '0')],
    [('Content-Length', str(MAX_JSON_BYTES + 1))],
    [('Content-Length', '-1')],
    [('Content-Length', '1'), ('Content-Length', '2')],
    [('Transfer-Encoding', 'chunked')],
])
def test_fixed_body_headers_rejected_before_backend(headers):
    chats = Chats()
    code, _ = call(chats, headers=headers)
    assert code == 400 and chats.calls == []


@pytest.mark.parametrize('raw', ['[]', 'null', '"text"', '{',
                              '{"allow_planning":true,"allow_planning":true}',
                              '{"allow_planning":NaN}', '{"allow_planning":Infinity}', b'\xff'])
def test_strict_json_rejected_before_backend(raw):
    chats = Chats()
    code, _ = call(chats, raw=raw)
    assert code == 400 and chats.calls == []


@pytest.mark.parametrize('exc, expected', [(ValueError('fixed validation'), 400),
    (PermissionError('explicit permission'), 403), (FileNotFoundError('fixed chat'), 404),
    (RuntimeError('uncertain binding'), 409), (OSError('fixed infrastructure'), 500)])
def test_backend_failure_is_explicit_and_does_not_become_ack(exc, expected):
    chats = Chats(exc)
    code, value = call(chats)
    assert code == expected and len(chats.calls) == 1
    assert 'error' in value and 'mission_id' not in value


def test_operator_token_in_backend_failure_is_redacted():
    chats = Chats(RuntimeError(TOKEN))
    code, value = call(chats)
    assert code == 409 and len(chats.calls) == 1
    assert TOKEN not in json.dumps(value)


@pytest.mark.parametrize('path, method', [(ROUTE + '?dispatch=true', 'POST'),
    ('/api/chat/prepare_placement', 'POST'), (ROUTE + '/', 'POST'), (ROUTE, 'GET')])
def test_no_query_alias_or_observational_dispatch(path, method):
    chats = Chats()
    code, _ = call(chats, path=path, method=method)
    assert code == 404 and chats.calls == []
