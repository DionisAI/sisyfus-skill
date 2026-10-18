"""Frozen Gateway-v6 ingress regression with a real Claims0073 control.

Loopback opt-in and retained deletion guard required. The public NodeClaims
implementation is loaded byte-for-byte from the readonly frozen 0073 packet,
so concurrent Claims admission changes never explain a Gateway green result.
No fake backend success, response aliases, native calls or old-test edits.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

import sisyfus.workers.node_claims as claims_module
import sisyfus.workers.node_gateway as gateway_module
import test_node_gateway as fixtures
from sisyfus.workers.node_registry import validate_request_id
from sisyfus.workers.protocol import redact
from test_node_gateway import call, env, gateway_type, no_session, offer, state


BASELINE_SHA = '0073e15cefe0a219a90e55537f4484a9bfd38c024c2036aabf43aa571c323dd1'
BAD_IDS = ['sk-abcdefghijklmnop', 'gateway-sk-abcdefghijklmnop', 'gateway_fixture_api_credential']
GOOD_IDS = ['gateway_claim_admission_01', 'SK-abcdefghijklmnop', 'gateway_sk-abcdefghijklmnop', 'ordinary_request_002']


@pytest.fixture(autouse=True)
def pinned_claims_0073(monkeypatch):
    # Fixture credentials only. Never inspect or copy the user's provider keys.
    monkeypatch.setenv('OPENAI_API_KEY', BAD_IDS[-1])
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    path = Path(os.environ['SISYFUS_GATEWAY_CLAIMS_BASELINE'])
    assert path.is_absolute() and path.is_file()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == BASELINE_SHA
    assert path.stat().st_mode & 0o222 == 0, 'independent baseline stays readonly'
    spec = importlib.util.spec_from_file_location('sisyfus.workers._gateway_claims_0073_control', path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(__import__('sys').modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(claims_module, 'NodeClaims', module.NodeClaims)
    monkeypatch.setattr(fixtures, 'NodeClaims', module.NodeClaims)
    return module.NodeClaims


def prepared(e, stage):
    if stage == 'cold':
        assert e.mission._node_claims is None and not (e.mission.directory / 'remote').exists()
        return None
    claims = offer(e, transport=True)
    if stage in {'expired', 'unknown'}:
        assert claims.claim(e.node['node_id'], 'preexisting_claim_normal_01')['status'] == 'CLAIMED'
        e.clock.advance(claims.lease_seconds + 1)
        if stage == 'unknown':
            claims.expire()
            assert claims.get(e.key)['status'] == 'UNKNOWN'
        else:
            assert claims.get(e.key)['status'] == 'CLAIMED', 'prepare does not opportunistically expire'
    return claims


def facts(e):
    with e.mission.store._transaction(immediate=False) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        requests = db.execute('SELECT COUNT(*) FROM remote_claim_requests').fetchone()[0] if 'remote_claim_requests' in tables else 0
        events = db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
    return {'claim_requests': requests, 'events': events,
            'lazy_backend_initialized': e.mission._node_claims is not None,
            'offer_status': e.claims.get(e.key)['status'] if hasattr(e, 'claims') else None}


@pytest.mark.parametrize('request_id', BAD_IDS)
def test_claim_schema_rejects_redaction_changing_identity_content_free(request_id):
    assert validate_request_id(request_id) == request_id
    assert redact(request_id) != request_id
    with pytest.raises(ValueError) as caught:
        gateway_module._body_schema('claim', {'request_id': request_id})
    assert request_id not in str(caught.value) and 'request_id' in str(caught.value)


@pytest.mark.parametrize('request_id', BAD_IDS)
def test_authenticated_invalid_claim_is_400_before_hub_session(env, monkeypatch, request_id, caplog, capsys):
    e = env
    no_session(e, monkeypatch)
    before = state(e)
    replies = [call(e, body={'request_id': request_id}) for _ in range(2)]
    assert [code for code, _ in replies] == [400, 400]
    assert state(e) == before and not (e.mission.directory / 'remote').exists()
    assert e.mission._node_claims is None and not e.mission.journal.runs()
    observed = json.dumps(replies) + caplog.text + capsys.readouterr().err
    assert request_id not in observed and e.node['secret'] not in observed


@pytest.mark.parametrize('stage', ['cold', 'offered', 'expired', 'unknown'])
@pytest.mark.parametrize('request_id', BAD_IDS)
def test_ingress_preserves_real_rows_events_offers_and_expiry_before_exact_retry(
        env, monkeypatch, stage, request_id, caplog, capsys):
    e = env
    prepared(e, stage)
    before, before_facts = state(e), facts(e)
    original = e.hub._session
    sessions = []

    def real_session(ident):
        sessions.append(ident)
        return original(ident)

    monkeypatch.setattr(e.hub, '_session', real_session)
    replies = [call(e, body={'request_id': request_id}) for _ in range(2)]
    after, after_facts = state(e), facts(e)
    # Retained RED shows the actual old committed fact without logging secrets
    # or treating a concurrent fixed service as Gateway evidence.
    print(json.dumps({'stage': stage, 'http_statuses': [code for code, _ in replies],
                      'before': before_facts, 'after': after_facts, 'hub_session_calls': len(sessions)}))
    assert [code for code, _ in replies] == [400, 400]
    assert sessions == [], 'syntax admission precedes lazy session/backend and expire'
    assert after == before and after_facts == before_facts
    assert e.mission.store.verify_event_chain()['valid']
    if stage == 'cold':
        assert not (e.mission.directory / 'remote').exists() and e.mission._node_claims is None
    else:
        assert e.mission.journal.runs()[0]['status'] == 'IN_FLIGHT', 'no core settlement or UNKNOWN clearing'
    observed = json.dumps(replies) + caplog.text + capsys.readouterr().err
    assert request_id not in observed and e.node['secret'] not in observed
    assert all(reply['error']['type'] == 'ValueError' for _, reply in replies)


@pytest.mark.parametrize('stage', ['cold', 'offered'])
@pytest.mark.parametrize('request_id', GOOD_IDS)
def test_ordinary_identity_and_positive_public_wire_exact_replay_are_unchanged(env, stage, request_id):
    e = env
    prepared(e, stage)
    assert redact(request_id) == request_id
    gateway_module._body_schema('claim', {'request_id': request_id})
    body = {'request_id': request_id}
    result = call(e, body=body)
    status, reply = result
    assert status == 200 and set(reply) == {'controller_mission_id', 'result'}
    assert reply['controller_mission_id'] == e.ident
    assert reply['result']['mission_id'] == e.registry.mission_id
    assert reply['result']['node_id'] == e.node['node_id'] and reply['result']['request_id'] == request_id
    assert reply['result']['status'] == ('CLAIMED' if stage == 'offered' else 'NO_WORK')
    before = state(e)
    assert call(e, body=body) == result and state(e) == before
    assert e.node['secret'] not in json.dumps(reply)
    assert e.mission.store.verify_event_chain()['valid']
    if stage == 'offered':
        assert e.claims.get(e.key)['status'] == 'CLAIMED' and e.mission.journal.runs()[0]['status'] == 'IN_FLIGHT'
    else:
        assert reply['result']['claim'] is None and not e.mission.journal.runs()


@pytest.mark.parametrize('stage', ['cold', 'offered'])
def test_independent_readonly_0073_source_control_exhibits_original_raw_identity_commit(env, stage, pinned_claims_0073):
    e = env
    claims = prepared(e, stage) or e.mission.node_claims
    assert isinstance(claims, pinned_claims_0073)
    bad = BAD_IDS[0]
    result = claims.claim(e.node['node_id'], bad)  # Real old public service, bypassing Gateway only in this control.
    assert result['request_id'] == bad and redact(result) != result
    assert result['status'] == ('CLAIMED' if stage == 'offered' else 'NO_WORK')
    with e.mission.store._transaction(immediate=False) as db:
        row = db.execute('SELECT response_json FROM remote_claim_requests WHERE node_id=? AND request_id=?',
                         (e.node['node_id'], bad)).fetchone()
    assert row is not None and json.loads(row[0]) == result
    before = state(e)
    assert claims.claim(e.node['node_id'], bad) == result and state(e) == before
    assert e.mission.store.verify_event_chain()['valid']
