"""Frozen v3 error-classification microchecks; real authenticated fixture HTTP.

Protocol drivers only. Public status/receipt shape is checked against frozen v2
helpers; controller-clock leases and original pending bytes remain authoritative.
"""
from pathlib import Path
import importlib
import json
import threading
import time

import pytest

from sisyfus.autonomy.policy import IdempotencyConflictError
from sisyfus.workers.protocol import Receipt
from test_node_agent import AgentDriver, agent_env, agent_type, execute, retained_bytes
from test_node_agent_review_v2_micro import _publish, _local, _status, _assert_core, _assert_stored


def _native(request, emit, controls):
    Path(request.cwd, 'partial.txt').write_bytes(b'partial')
    Path(request.cwd, 'result.txt').write_bytes(b'42')
    emit('native_event', {'method': 'fixture', 'params': {'text': 'original durable event'}})
    return Receipt('COMPLETED', requested_model=request.model)


def _same_original(before, after, events, next_events):
    assert all(before[k] == after[k] for k in ('offer', 'workspace', 'receipt'))
    if before['tree'] is not None:
        assert before['tree'] == after['tree']
    assert before['request_id'] == after['request_id'] and events == next_events


def test_live_upload_io_409_retains_pending_bytes_then_retries_full_manifest(agent_env, monkeypatch):
    e = agent_env; _publish(e)
    module = importlib.import_module('sisyfus.workers.node_claims')
    parent, upload = module._parent, e.claims.upload
    attempts, faults = [], []
    def io_fault(root, relative, **kwargs):
        if e.claims.artifact_root in Path(root).parents and relative == 'result.txt' and not faults:
            faults.append(1)
            raise OSError('fixture transient artifact parent IO')
        return parent(root, relative, **kwargs)
    def trace(node, claim, epoch, path, sha, data, *, admit_response=None):
        attempts.append((claim, epoch, path, sha, data))
        return upload(node, claim, epoch, path, sha, data, admit_response=admit_response)
    monkeypatch.setattr(module, '_parent', io_fault)
    monkeypatch.setattr(e.claims, 'upload', trace)
    agent, driver = execute(e, AgentDriver(_native))
    with pytest.raises(RuntimeError, match='OSError'):
        agent.run_once()
    local, raw, events = _local(e)
    assert faults == [1] and len(driver.requests) == 1
    assert local['status'] == 'TERMINAL' and local['lease_lost'] == 0 and raw['receipt_body'] is None
    assert _status(e)['status'] == 'CLAIMED' and _status(e)['receipt'] is None
    assert {u['path']: u['status'] for u in _status(e)['uploads']} == {'partial.txt': 'STORED', 'result.txt': 'PREPARING'}
    restarted, _ = execute(e, driver)
    assert restarted.run_once()['status'] == 'RECEIPTED'
    after, next_raw, next_events = _local(e)
    assert after['lease_lost'] == 0 and len(driver.requests) == 1
    _same_original(raw, next_raw, events, next_events)
    assert [a[2] for a in attempts] == ['partial.txt', 'result.txt', 'result.txt'] and attempts[1] == attempts[2]
    _assert_stored(e, {'partial.txt': b'partial', 'result.txt': b'42'}); _assert_core(e)
    fixed_body = next_raw['receipt_body']
    assert restarted.run_once()['status'] == 'RECEIPTED' and _local(e)[1]['receipt_body'] == fixed_body


def test_live_sync_conflict_409_is_explicit_without_freezing_empty_receipt(agent_env, monkeypatch):
    e = agent_env; _publish(e)
    sync, calls = e.claims.sync, []
    def conflict(node_id, claim_id, epoch, events, *, admit_response=None):
        calls.append(json.dumps(events, sort_keys=True))
        if len(calls) == 1:
            raise IdempotencyConflictError('fixture recoverable controller boundary conflict')
        return sync(node_id, claim_id, epoch, events, admit_response=admit_response)
    monkeypatch.setattr(e.claims, 'sync', conflict)
    agent, driver = execute(e, AgentDriver(_native))
    with pytest.raises(RuntimeError, match='IdempotencyConflictError'):
        agent.run_once()
    local, raw, events = _local(e)
    assert local['lease_lost'] == 0 and raw['receipt_body'] is None and _status(e)['receipt'] is None
    assert _status(e)['status'] == 'CLAIMED' and _status(e)['uploads'] == []
    restarted, _ = execute(e, driver)
    assert restarted.run_once()['status'] == 'RECEIPTED'
    _same_original(raw, _local(e)[1], events, _local(e)[2])
    assert calls[0] == calls[1] and len(driver.requests) == 1
    _assert_stored(e, {'partial.txt': b'partial', 'result.txt': b'42'}); _assert_core(e)


def test_unknown_restart_conflict_keeps_outbox_and_never_reserves_again(agent_env, monkeypatch):
    e = agent_env; _publish(e)
    def interrupted(request, emit, controls):
        emit('native_event', {'method': 'fixture', 'params': {'text': 'original unknown event'}})
        raise KeyboardInterrupt('fixture unknown native outcome')
    agent, driver = execute(e, AgentDriver(interrupted))
    with pytest.raises(KeyboardInterrupt): agent.run_once()
    _, raw, events = _local(e)
    sync, calls = e.claims.sync, []
    def conflict(node_id, claim_id, epoch, events, *, admit_response=None):
        calls.append(json.dumps(events, sort_keys=True))
        if len(calls) == 1: raise IdempotencyConflictError('fixture unknown sync conflict')
        return sync(node_id, claim_id, epoch, events, admit_response=admit_response)
    monkeypatch.setattr(e.claims, 'sync', conflict)
    restarted, _ = execute(e, driver)
    with pytest.raises(RuntimeError, match='IdempotencyConflictError'): restarted.run_once()
    local, after, next_events = _local(e)
    assert local['status'] == 'UNKNOWN' and local['lease_lost'] == 0 and local['ack'] == 0
    assert after['receipt_body'] is None
    _same_original(raw, after, events, next_events)
    assert restarted.run_once() == {'request_id': local['request_id'], 'status': 'UNKNOWN'}
    assert _local(e)[0]['ack'] == 1 and len(driver.requests) == 1 and calls[0] == calls[1]
    assert _status(e)['receipt'] is None; _assert_core(e)


@pytest.mark.parametrize('exception', [IdempotencyConflictError, ValueError])
def test_heartbeat_conflict_or_schema_is_explicit_not_lease_expiry(agent_env, monkeypatch, exception):
    e = agent_env; _publish(e)
    heartbeat, calls, seen = e.claims.heartbeat, [], threading.Event()
    def fault(node_id, claim_id, epoch, *, admit_response=None):
        calls.append(1)
        if len(calls) > 1:
            seen.set(); raise exception('fixture heartbeat protocol error')
        return heartbeat(node_id, claim_id, epoch, admit_response=admit_response)
    monkeypatch.setattr(e.claims, 'heartbeat', fault)
    def native(request, emit, controls):
        assert seen.wait(1)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            try: value = controls()
            except RuntimeError as exc:
                assert 'heartbeat fatal' in str(exc) and exception.__name__ in str(exc)
                return _native(request, emit, controls)
            assert value == [], 'schema/conflict is not a lease-loss interrupt'
            time.sleep(.01)
        raise AssertionError('heartbeat error must be explicit')
    agent, driver = execute(e, AgentDriver(native))
    with pytest.raises(RuntimeError, match='heartbeat fatal'): agent.run_once()
    local, raw, events = _local(e)
    assert local['lease_lost'] == 0 and local['status'] == 'TERMINAL' and raw['receipt_body'] is None
    assert _status(e)['status'] == 'CLAIMED'
    assert agent.run_once()['status'] == 'RECEIPTED' and len(driver.requests) == 1
    _same_original(raw, _local(e)[1], events, _local(e)[2])
    _assert_stored(e, {'partial.txt': b'partial', 'result.txt': b'42'}); _assert_core(e)


def test_genuine_controller_lease_lost_409_retains_terminal_subset(agent_env):
    e = agent_env; e.claims.lease_seconds = .3; _publish(e)
    # Native has independent renewal; first terminal sync delays on the
    # controller after the heartbeat thread stops, without patching UTC.
    agent, driver = execute(e, AgentDriver(_native))
    original = e.claims.sync
    def expired(node_id, claim_id, epoch, events, *, admit_response=None):
        time.sleep(.4); e.claims.expire(); return original(node_id, claim_id, epoch, events, admit_response=admit_response)
    e.claims.sync = expired
    assert agent.run_once()['status'] == 'RECONCILIATION_CANDIDATE'
    local, raw, events = _local(e)
    assert local['lease_lost'] == 1 and len(driver.requests) == 1
    _assert_stored(e, {}); _assert_core(e)
    with pytest.raises(Exception) as caught:
        agent._call('heartbeat', agent._identity_body(local['offer']))
    assert caught.value.status == 409 and getattr(caught.value, 'error_type', None) == 'LeaseLost'
    assert agent.run_once()['status'] == 'RECONCILIATION_CANDIDATE'
    assert _local(e)[1]['receipt_body'] == raw['receipt_body'] and _local(e)[2] == events


def test_actual_revocation_records_authority_loss_without_new_native(agent_env):
    e = agent_env; _publish(e)
    def native(request, emit, controls):
        fact = _native(request, emit, controls); e.registry.revoke(e.node['node_id']); return fact
    agent, driver = execute(e, AgentDriver(native))
    with pytest.raises(RuntimeError, match='HTTP (401|403)'): agent.run_once()
    local, raw, events = _local(e)
    assert local['lease_lost'] == 1 and local['receipt']['status'] == 'COMPLETED' and raw['receipt_body'] is None
    with pytest.raises(RuntimeError, match='HTTP (401|403)'): agent.run_once()
    assert len(driver.requests) == 1
    _same_original(raw, _local(e)[1], events, _local(e)[2]); _assert_core(e)


def _wire_error(e, monkeypatch, raw, status=409):
    module = importlib.import_module('sisyfus.workers.node_gateway')
    send = module._Handler._send
    def error(self, value, code=200, **kwargs):
        if self.path.endswith('/status'):
            self.send_response(status)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Content-Type', 'application/json')
            self.end_headers(); self.wfile.write(raw); self.wfile.flush()
            return
        return send(self, value, code, **kwargs)
    monkeypatch.setattr(module._Handler, '_send', error)


@pytest.mark.parametrize('kind', ['LeaseLost', 'IdempotencyConflictError', 'OSError'])
def test_bounded_real_wire_error_type_only_never_message_or_secret(agent_env, monkeypatch, kind):
    e = agent_env; _publish(e); agent, _ = execute(e); agent.run_once()
    _, raw, events = _local(e)
    private = 'PRIVATE-MESSAGE ' + e.node['secret'] + ' Bearer fixture-private-value'
    _wire_error(e, monkeypatch, json.dumps({'error': {'type': kind, 'message': private, 'diagnostic_id': 'ng_fixture'}}).encode())
    with pytest.raises(Exception) as caught: agent._call('status', agent._identity_body(json.loads(raw['offer'])))
    assert caught.value.status == 409 and getattr(caught.value, 'error_type', None) == kind
    assert kind in str(caught.value) and 'PRIVATE-MESSAGE' not in str(caught.value)
    assert e.node['secret'] not in str(caught.value) and b'PRIVATE-MESSAGE' not in retained_bytes(e.state)
    assert e.node['secret'].encode() not in retained_bytes(e.state)
    assert raw == _local(e)[1] and events == _local(e)[2]; _assert_core(e)


@pytest.mark.parametrize('body', [
    b'not json', b'\xff', b'{}', b'{"error":{"type":"LeaseLost"}}',
    b'{"error":{"type":"LeaseLost","type":"OSError","message":"x"}}',
    b'{"error":{"type":"LeaseLost","message":"x"},"extra":1}',
    b'{"error":{"type":4,"message":"x"}}',
    b'{"error":{"type":"LeaseLost\\n","message":"x"}}',
    b'{"error":{"type":"LeaseLost","message":"x","extra":1}}',
])
def test_invalid_error_envelope_is_unknown_http_not_inferred_lease_loss(agent_env, monkeypatch, body):
    e = agent_env; _publish(e); agent, _ = execute(e); agent.run_once()
    _, raw, events = _local(e); _wire_error(e, monkeypatch, body)
    with pytest.raises(Exception) as caught: agent._call('status', agent._identity_body(json.loads(raw['offer'])))
    assert caught.value.status == 409 and getattr(caught.value, 'error_type', None) is None
    assert 'HTTP 409' in str(caught.value) and 'LeaseLost' not in str(caught.value)
    assert raw == _local(e)[1] and events == _local(e)[2] and _local(e)[0]['lease_lost'] == 0
    _assert_core(e)


def test_oversize_error_response_is_bounded_unknown_http_without_echo(agent_env, monkeypatch):
    e = agent_env; _publish(e); agent, _ = execute(e); agent.run_once()
    _, raw, events = _local(e)
    _wire_error(e, monkeypatch, b'PRIVATE-MESSAGE ' + b'x' * 16384)
    with pytest.raises(Exception) as caught: agent._call('status', agent._identity_body(json.loads(raw['offer'])))
    assert caught.value.status == 409 and getattr(caught.value, 'error_type', None) is None
    assert 'exceeds bound' in str(caught.value) and 'PRIVATE-MESSAGE' not in str(caught.value)
    assert raw == _local(e)[1] and events == _local(e)[2]; _assert_core(e)
