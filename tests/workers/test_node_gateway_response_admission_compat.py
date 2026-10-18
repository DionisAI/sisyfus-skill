"""ADDITIONAL_VERIFICATION: seven retained scenarios on the named admission API.

Real authenticated loopback and original NodeClaims transactions; no native run.
Old tests, their generic wrappers and all recorded failures remain untouched.
Freeze this file before its first retained outcome; it is not a RED/fix cycle.
"""
from __future__ import annotations

import inspect
import json
import re
import threading

import pytest

from sisyfus.workers.node_claims import _NO_TREE
from test_node_gateway import call, env, offer, state
from test_node_gateway_response_deadline import (
    assert_retired, delayed_timers, gateway_type, prepared, wire,
)


def _same_public_parameters(wrapper, original):
    def parameters(method):
        return [(p.name, p.kind, p.default)
                for p in inspect.signature(method).parameters.values()]
    assert parameters(wrapper) == parameters(original)
    parameter = inspect.signature(wrapper).parameters['admit_response']
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None


def _postcommit_wrapper(original, operation, after_commit):
    # Each concrete signature preserves positional arity, tree/default and the
    # exact Gateway callback; no synthetic signature or response is installed.
    def returned(result):
        after_commit(result)
        return result

    if operation == 'claim':
        def wrapper(node_id, request_id, *, admit_response=None):
            assert callable(admit_response)
            return returned(original(node_id, request_id, admit_response=admit_response))
    elif operation == 'upload':
        def wrapper(node_id, claim_id, epoch, path, sha256, data, *, admit_response=None):
            assert callable(admit_response)
            return returned(original(node_id, claim_id, epoch, path, sha256, data,
                                     admit_response=admit_response))
    elif operation == 'receipt':
        def wrapper(node_id, claim_id, epoch, receipt, manifest,
                    *, tree=_NO_TREE, admit_response=None):
            assert callable(admit_response)
            return returned(original(node_id, claim_id, epoch, receipt, manifest,
                                     tree=tree, admit_response=admit_response))
    elif operation == 'heartbeat':
        def wrapper(node_id, claim_id, epoch, *, admit_response=None):
            assert callable(admit_response)
            return returned(original(node_id, claim_id, epoch, admit_response=admit_response))
    elif operation == 'sync':
        def wrapper(node_id, claim_id, epoch, events, *, admit_response=None):
            assert callable(admit_response)
            return returned(original(node_id, claim_id, epoch, events,
                                     admit_response=admit_response))
    else:
        raise AssertionError('unexpected supplemental operation')
    _same_public_parameters(wrapper, original)
    return wrapper


def test_actual_internal_exception_has_correlated_sanitized_500(
        env, monkeypatch, caplog, capsys):
    e = env
    claims = offer(e, transport=True)
    original_claim, original_event = claims.claim, claims._event
    before = state(e)
    calls, faults = [], []

    def forwarding_claim(node_id, request_id, *, admit_response=None):
        assert callable(admit_response)
        calls.append((node_id, request_id))
        return original_claim(node_id, request_id, admit_response=admit_response)

    def fail_claim_event(db, kind, key, data):
        if kind == 'claimed':
            faults.append((kind, key))
            raise RuntimeError('fixture failure Authorization: Node ' + e.other['secret']
                               + ' raw ' + e.node['secret'] + ' Bearer operator-fixture')
        return original_event(db, kind, key, data)

    _same_public_parameters(forwarding_claim, original_claim)
    monkeypatch.setattr(claims, 'claim', forwarding_claim)
    monkeypatch.setattr(claims, '_event', fail_claim_event)
    request_id = 'compat_diagnostic_claim_01'
    status, body = call(e, body={'request_id': request_id})
    monkeypatch.setattr(claims, 'claim', original_claim)
    monkeypatch.setattr(claims, '_event', original_event)
    assert calls == [(e.node['node_id'], request_id)] and faults == [('claimed', e.key)]
    assert status == 500 and set(body) == {'error'}
    error = body['error']
    assert error['type'] == 'RuntimeError' and 'fixture failure' in error['message']
    assert re.fullmatch(r'ng_[0-9a-f]{24}', error['diagnostic_id'])
    assert error['diagnostic_id'] in caplog.text
    assert 'response admission requires' not in error['message']
    captured = capsys.readouterr()
    observed = json.dumps(body) + caplog.text + captured.out + captured.err
    assert all(value not in observed for value in
               (e.node['secret'], e.other['secret'], 'operator-fixture'))
    assert 'POST /node/v1/' not in observed and 'Traceback' not in observed
    assert state(e) == before, 'real claim writes and event must roll back together'
    assert claims.get(e.key)['status'] == 'OFFERED'
    assert not e.mission.journal.events()[-1]['type'].endswith('CLAIMED')
    assert len(e.mission.journal.runs()) == 1
    assert e.mission.journal.runs()[0]['status'] == 'IN_FLIGHT'
    assert e.mission.store.verify_event_chain()['valid']


@pytest.mark.parametrize('operation', ['claim', 'upload', 'receipt', 'heartbeat', 'sync'])
def test_real_named_admission_commit_survives_whole_connection_deadline(
        env, monkeypatch, delayed_timers, caplog, capsys, operation):
    e, gate = env, delayed_timers
    claims, request, c = prepared(e, operation)
    original = getattr(claims, operation)
    baseline = set(threading.enumerate())
    fingerprint = e.mission.journal.runs()[0]['fingerprint']
    input_bytes = (e.snapshot / 'input.txt').read_bytes()
    committed, after_commit = [], []

    def delay_after_commit(result):
        committed.append(result)
        after_commit.append(state(e))
        # The original public method has returned: its transaction really
        # committed. Delay only return scheduling, never the admission callback.
        assert gate.due.wait(3), 'real monotonic connection budget must expire'

    wrapper = _postcommit_wrapper(original, operation, delay_after_commit)
    monkeypatch.setattr(claims, operation, wrapper)
    target = 'uploads/' + c['claim_id'] + '/' + str(c['epoch']) if operation == 'upload' else operation
    received = wire(e, target, **request)
    monkeypatch.setattr(claims, operation, original)
    assert_retired(e, gate, baseline, caplog, capsys)
    assert received == b'', 'no late success, rejection status, headers or body'
    assert len(committed) == 1 and state(e) == after_commit[0]
    view = claims.get(e.key)
    assert view['node_id'] == e.node['node_id'] and view['epoch'] == 1
    assert view['status'] == ('RECEIPTED' if operation == 'receipt' else 'CLAIMED')
    runs = e.mission.journal.runs()
    assert len(runs) == 1 and runs[0]['fingerprint'] == fingerprint
    assert runs[0]['status'] == 'IN_FLIGHT', 'transport is not native/core acceptance'
    assert (e.snapshot / 'input.txt').read_bytes() == input_bytes == b'fixed input'
    assert e.mission.store.verify_event_chain()['valid']
    owner, before_read = view['claim_id'], state(e)
    status, readback = call(e, 'status', body={'claim_id': owner, 'epoch': 1})
    assert status == 200 and set(readback) == {'controller_mission_id', 'result'}
    assert readback['controller_mission_id'] == e.ident
    assert readback['result']['status'] == view['status'] and state(e) == before_read
    if operation == 'receipt':
        # Tree is a status/receipt public projection, not the legacy get view.
        assert readback['result']['tree'] == request['body']['tree']
        assert readback['result']['manifest'] == request['body']['manifest']
        assert readback['result']['receipt'] == request['body']['receipt']
        assert readback['result']['tree']['complete'] is True
        assert all(row['status'] == 'STORED' for row in readback['result']['uploads'])
    assert call(e, 'status', body={'claim_id': owner, 'epoch': 1}, node=e.other)[0] == 403
    assert state(e) == before_read
    if operation in {'claim', 'upload', 'receipt', 'sync'}:
        assert call(e, target, **request) == (200, {
            'controller_mission_id': e.ident, 'result': committed[0]})
        assert state(e) == before_read, 'exact replay never duplicates commit or reservation'
    if operation == 'claim':
        e.clock.advance(31)
        claims.expire()
        assert claims.get(e.key)['status'] == 'UNKNOWN'
        assert call(e, body={'request_id': 'compat_deadline_new_01'})[1]['result']['status'] == 'NO_WORK'
        assert claims.get(e.key)['claim_id'] == owner and len(e.mission.journal.runs()) == 1


def test_real_postcommit_revocation_is_close_only_after_deadline(
        env, monkeypatch, delayed_timers, caplog, capsys):
    e, gate = env, delayed_timers
    claims = offer(e, transport=True)
    original = claims.claim
    baseline = set(threading.enumerate())
    committed, retained = [], []

    def revoke_after_commit(result):
        committed.append(result)
        assert gate.due.wait(3), 'revoke only after real connection deadline'
        e.registry.revoke(e.node['node_id'])
        retained.append(state(e))

    monkeypatch.setattr(claims, 'claim', _postcommit_wrapper(original, 'claim', revoke_after_commit))
    request = {'request_id': 'compat_deadline_revoke_01'}
    received = wire(e, 'claim', body=request)
    monkeypatch.setattr(claims, 'claim', original)
    assert_retired(e, gate, baseline, caplog, capsys)
    assert received == b'', 'postcommit revocation emits neither late 403 nor other response bytes'
    assert len(committed) == 1 and committed[0]['status'] == 'CLAIMED'
    assert state(e) == retained[0]
    view = claims.get(e.key)
    assert view['claim_id'] == committed[0]['claim']['claim_id'] and view['status'] == 'CLAIMED'
    assert view['node_id'] == e.node['node_id'] and view['epoch'] == 1
    assert next(row for row in e.registry.inventory() if row['node_id'] == e.node['node_id'])['status'] == 'REVOKED'
    assert call(e, body=request)[0] == 403 and state(e) == retained[0]
    assert len(e.mission.journal.runs()) == 1
    assert e.mission.journal.runs()[0]['status'] == 'IN_FLIGHT'
    assert (e.snapshot / 'input.txt').read_bytes() == b'fixed input'
    assert e.mission.store.verify_event_chain()['valid']
