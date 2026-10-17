"""Frozen v4 authentication regressions: real node-only ephemeral loopback.

Reuse the isolated public service fixture without changing its frozen scenarios.
Wrong credentials disclose no revocation state, create no backend, and preserve
the actual transport response for a valid active identity. Retained runner only.
"""
import json

import pytest

from test_node_gateway import call, env, gateway_type, no_session, state


ROUTES = [('claim', 'POST'), ('sync', 'POST'), ('heartbeat', 'POST'),
          ('status', 'POST'), ('receipt', 'POST'),
          ('inputs/claim_' + 'a' * 32 + '/1', 'GET'),
          ('uploads/claim_' + 'a' * 32 + '/1', 'PUT')]


@pytest.mark.parametrize('route,method', ROUTES)
def test_wrong_secret_cannot_distinguish_revoked_active_or_unknown_node(env, monkeypatch, route, method):
    e = env
    e.registry.revoke(e.node['node_id'])
    no_session(e, monkeypatch)
    before = state(e)
    # Another enrolled credential is valid hex but not valid for this node.
    wrong = e.other['secret']
    assert wrong != e.node['secret']
    identities = [e.node, e.other, {'node_id': 'node_' + '0' * 32}]
    messages = []
    for identity in identities:
        supplied = {**identity, 'secret': wrong if identity is not e.other else e.node['secret']}
        code, reply = call(e, route, method=method, node=supplied, raw=b'{}')
        assert state(e) == before and not (e.mission.directory / 'remote').exists()
        assert not e.mission.journal.runs()
        assert code == 401
        messages.append(reply['error']['message'])
        wire = json.dumps(reply)
        assert 'revoked' not in wire.lower()
        assert all(secret not in wire for secret in (e.node['secret'], e.other['secret']))
    assert len(set(messages)) == 1


@pytest.mark.parametrize('route,method', ROUTES)
def test_only_matching_stored_credential_gets_revoked_403_without_backend(env, monkeypatch, route, method):
    e = env
    e.registry.revoke(e.node['node_id'])
    no_session(e, monkeypatch)
    before = state(e)
    code, reply = call(e, route, method=method, raw=b'{}')
    assert code == 403 and reply['error']['message'] == 'node identity is revoked'
    assert state(e) == before and not (e.mission.directory / 'remote').exists()
    assert not e.mission.journal.runs()
    assert e.node['secret'] not in json.dumps(reply)


def test_active_credential_preserves_original_transport_wire_and_exact_replay(env):
    e = env
    body = {'request_id': 'gateway-revoked-auth-positive-01'}
    result = call(e, body=body)
    assert result == (200, {'controller_mission_id': e.ident, 'result': {
        'mission_id': e.registry.mission_id, 'node_id': e.node['node_id'],
        'request_id': body['request_id'], 'status': 'NO_WORK', 'claim': None}})
    before = state(e)
    assert call(e, body=body) == result and state(e) == before
    assert not e.mission.journal.runs()
