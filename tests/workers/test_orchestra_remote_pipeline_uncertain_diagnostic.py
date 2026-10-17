"""ADDITIONAL_VERIFICATION of preexisting public uncertain diagnostics.

Reuse the untouched ec5e pipeline fixture, not any original test function.
Only ScriptedDriver is a protocol fake at Agent's native boundary. These two
independent cases do not replace the original8 or turn its two failures GREEN.
"""
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from sisyfus.autonomy.policy import LeaseLost
from sisyfus.workers.protocol import digest
from sisyfus.workers.remote_artifacts import full_tree_manifest
from test_orchestra_remote_pipeline import (
    INPUTS, OUTPUTS, _local, _read_db, _status, _wait, pipeline,
)


def _assert_original_identity_and_outbox(e, before):
    current = _local(e)
    assert len(current['attempts']) == len(before['attempts']) == 1
    first, now = before['attempts'][0], current['attempts'][0]
    for field in ('request_id', 'offer', 'workspace', 'receipt', 'tree'):
        assert now[field] == first[field]
    assert current['outbox'] == before['outbox']
    assert now['ack'] == len(before['outbox'])
    assert [row['seq'] for row in current['outbox']] == list(range(1, len(current['outbox']) + 1))
    synced = _read_db(e.m.store.path, ('remote_event_sync',))['remote_event_sync']
    assert [row['seq'] for row in synced] == [row['seq'] for row in current['outbox']]
    assert [row['raw_digest'] for row in synced] == [digest(json.loads(row['event'])) for row in current['outbox']]
    claims = _read_db(e.m.store.path, ('remote_claim_requests',))['remote_claim_requests']
    assert len(claims) == 1 and claims[0]['request_id'] == first['request_id']
    assert len(e.remote) == len(e.driver.requests) == 1
    return current


def _assert_physical_workspace_and_no_candidate(e):
    root = Path(e.driver.requests[0].cwd)
    for path, data in (INPUTS | OUTPUTS).items():
        assert Path(root, path).read_bytes() == data
    fixed = e.m.journal.get('run_placements', e.key)
    assert not Path(fixed['candidate_root']).exists()
    assert not Path(fixed['candidate_root'], 'candidate').exists()
    assert e.m.store.get_continuation(e.cont['id'])['lease_token'] == e.cont['lease_token']


def _save_independent_observation(e, name, view):
    local = _local(e)
    value = {
        'classification': 'ADDITIONAL_VERIFICATION_NOT_ORIGINAL8_REPLACEMENT',
        'case': name,
        'request_id': local['attempts'][0]['request_id'],
        'Agent_status': local['attempts'][0]['status'],
        'Driver_diagnostic': e.remote[0].materialization,
        'controller_transport_status': view['status'],
        'controller_receipt_status': view['receipt']['status'] if view['receipt'] is not None else None,
        'core_receipt_present': e.m.journal.runs()[0]['receipt'] is not None,
        'candidate_exists': Path(e.m.journal.get('run_placements', e.key)['candidate_root']).exists(),
        'outbox_seq': [row['seq'] for row in local['outbox']],
        'outbox_digests': [digest(json.loads(row['event'])) for row in local['outbox']],
        'original_acceptance_hash': e.acceptance,
        'physical_workspace_manifest': full_tree_manifest(e.driver.requests[0].cwd),
        'actual_RemoteCodexDriver_count': len(e.remote),
        'ScriptedDriver_protocol_count': len(e.driver.requests),
        'operator_native_control_ACK_asserted': False,
        'native_provider_process_crash_second_host_phone_A7_A8': False,
    }
    encoded = json.dumps(value, ensure_ascii=False, indent=2)
    assert e.node['secret'] not in encoded
    with (e.root / 'uncertain-independent-evidence.json').open('x') as file:
        file.write(encoded)


def test_unknown_diagnostic_retains_bytes_and_same_id_repeat_without_respawn(pipeline):
    e = pipeline
    e.start(mode='crash')
    with pytest.raises(KeyboardInterrupt):
        e.agent.run_once()
    before = _local(e)
    assert before['attempts'][0]['status'] == 'UNKNOWN'
    assert before['attempts'][0]['receipt'] is None and before['attempts'][0]['tree'] is None
    assert before['outbox'] and before['controls'] == []
    trace_start = len(e.trace)
    expected = {'request_id': before['attempts'][0]['request_id'], 'status': 'UNKNOWN'}
    assert e.restarted().run_once() == expected
    operations = [row['operation'] for row in e.trace[trace_start:]]
    assert operations.index('sync') < operations.index('status')
    _assert_original_identity_and_outbox(e, before)
    e.joined()
    assert e.error is None and e.result.status == 'UNKNOWN'
    assert e.remote[0].materialization == {
        'status': 'UNKNOWN', 'error': {'code': 'deadline_after_claim_or_unknown'},
    }
    assert 'candidate' not in e.result.observation
    core = e.m.journal.runs()[0]
    assert core['status'] == 'UNKNOWN' and core['receipt']['status'] == 'UNKNOWN'
    _assert_physical_workspace_and_no_candidate(e)
    assert e.restarted().run_once() == expected
    assert e.restarted().run_once() == expected
    _assert_original_identity_and_outbox(e, before)
    view = e.public_status_http()
    assert view['receipt'] is None and view['manifest'] is None and 'tree' not in view
    assert not view['uploads']
    e.independent_truth()
    _save_independent_observation(e, 'UNKNOWN', view)


def test_controller_lease_loss_keeps_native_terminal_subset_and_fenced_diagnostic(pipeline):
    e = pipeline
    e.drop_stage = 'uploads'  # Original actual HTTP send seam; real IO committed.
    e.start(lease_seconds=2)
    with pytest.raises(RuntimeError):
        e.agent.run_once()
    before = _local(e)
    assert json.loads(before['attempts'][0]['receipt'])['status'] == 'COMPLETED'
    assert json.loads(before['attempts'][0]['tree']) == full_tree_manifest(e.driver.requests[0].cwd)
    assert len(e.driver.requests) == 1 and len(e.dropped) == 1
    stored = [row for row in _status(e)['uploads'] if row['status'] == 'STORED']
    assert len(stored) == 1
    expiry = datetime.fromisoformat(e.cont['lease_expires_at'].replace('Z', '+00:00'))
    _wait(lambda: datetime.now(timezone.utc) > expiry, seconds=3)
    e.joined()
    assert isinstance(e.error, LeaseLost) and e.result is None
    expected = {'request_id': before['attempts'][0]['request_id'], 'status': 'RECONCILIATION_CANDIDATE'}
    assert e.restarted().run_once() == expected
    assert e.remote[0].materialization == {
        'status': 'UNKNOWN',
        'error': {'code': 'return_fence', 'exception_type': 'LeaseLost'},
        'retained': {'status': 'UNKNOWN', 'error': {'code': 'transport_failure', 'exception_type': 'LeaseLost'}},
    }
    view = e.public_status_http()
    assert view['status'] == 'RECONCILIATION_CANDIDATE' and view['receipt']['status'] == 'COMPLETED'
    assert view['manifest'] == [{key: row[key] for key in ('path', 'size', 'sha256')} for row in stored]
    assert set(view['tree']) == {'schema', 'files', 'tree', 'errors', 'complete'}
    assert view['tree']['complete'] is True and view['tree']['errors'] == []
    assert view['tree'] == full_tree_manifest(e.driver.requests[0].cwd)
    first = _assert_original_identity_and_outbox(e, before)
    assert first['attempts'][0]['lease_lost'] == 1
    for row in stored:
        assert Path(e.claims.artifact_root, view['claim_id'], row['path']).read_bytes() == OUTPUTS[row['path']]
    for upload in first['uploads']:
        assert upload['bytes'] == OUTPUTS[upload['path']]
        assert upload['stored'] == int(upload['path'] in {row['path'] for row in stored})
    assert len(first['controls']) == 1
    control = first['controls'][0]
    assert json.loads(control['control']) == {'id': 'local_lease_' + view['claim_id'], 'action': 'interrupt', 'text': ''}
    assert control['delivered'] == 0  # Local cooperative signal, not a native ACK.
    assert e.m.journal.runs()[0]['receipt'] is None
    _assert_physical_workspace_and_no_candidate(e)
    body = first['attempts'][0]['receipt_body']
    assert e.restarted().run_once() == expected
    second = _assert_original_identity_and_outbox(e, before)
    assert second['attempts'][0]['receipt_body'] == body
    assert second['uploads'] == first['uploads'] and second['controls'] == first['controls']
    assert e.public_status_http() == view
    assert e.m.journal.runs()[0]['receipt'] is None
    e.independent_truth()
    _save_independent_observation(e, 'CONTROLLER_LEASE_LOSS', view)
