"""Frozen A6 foundations. Protocol fixtures, never A7/A8 or native evidence.

All test directories/files are retained by scripts/test_retained.py. Assertions
cover canonical-state isolation, restart/retry, expiry, uploads and failures.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path

import pytest

from sisyfus.autonomy.policy import IdempotencyConflictError, LeaseLost
from sisyfus.autonomy.store import AutonomyStore
from sisyfus.workers.journal import DispatchBlocked, Journal
from sisyfus.workers.lead_journal import LeadJournal
from sisyfus.workers.mission_inbox import MissionInbox
import sisyfus.workers.node_claims as module
from sisyfus.workers.node_claims import NodeClaims
from sisyfus.workers.node_registry import NodeRegistry
from sisyfus.workers.protocol import Receipt, Request, digest


class Clock:
    def __init__(self): self.value = 1000.0
    def __call__(self): return self.value
    def advance(self, seconds): self.value += seconds


@pytest.fixture
def env(tmp_path):
    journal = LeadJournal(AutonomyStore(tmp_path / 'autonomy.sqlite3'))
    journal.bind({'parallelism': 20, 'max_calls': None, 'objective': 'fixed objective',
                  'acceptance_hash': 'immutable', 'checks': {'frozen': {'sha': 'fixed'}}})
    registry = NodeRegistry(journal)
    a = registry.enroll('enroll_0001', 'first', ['codex'], ['gpt-6.1-sol'])['node_id']
    b = registry.enroll('enroll_0002', 'second', ['codex'], ['gpt-6.1-sol'])['node_id']
    cwd = tmp_path / 'workspace'
    cwd.mkdir()
    clock = Clock()
    claims = NodeClaims(journal, registry, tmp_path / 'remote-artifacts', clock=clock)
    return journal, registry, a, b, cwd, clock, claims


def request(env, **changes):
    return Request(**({'task_id': 'build', 'prompt': 'Implement fixed task.', 'cwd': str(env[4]),
                      'model': 'gpt-6.1-sol', 'mode': 'workspace-write'} | changes))


def meta(path='result.txt', data=b'result'):
    return {'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}


def manifest(outputs=None, files=None):
    return {'files': [] if files is None else files, 'output_paths': ['result.txt'] if outputs is None else outputs}


def offer(env, key='run-first', node=None, req=None, inputs=None):
    req = req or request(env)
    env[0].reserve(key, req.task_id, digest(asdict(req)))
    return env[-1].offer(key, node or env[2], req, inputs or manifest())


def claimed(env, **kwargs):
    offer(env, **kwargs)
    return env[-1].claim(kwargs.get('node') or env[2], 'claimreq_0001')['claim']


def upload(env, claim, path='result.txt', data=b'result', **changes):
    args = {'node_id': env[2], 'claim_id': claim['claim_id'], 'epoch': claim['epoch'],
            'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'data': data}
    return env[-1].upload(**(args | changes))


def deliver(env, claim, status='COMPLETED', files=None, **changes):
    args = {'node_id': env[2], 'claim_id': claim['claim_id'], 'epoch': claim['epoch'],
            'receipt': Receipt(status, requested_model='gpt-6.1-sol'), 'manifest': [] if files is None else files}
    return env[-1].receipt(**(args | changes))


def test_offer_claim_retry_and_transport_not_core_settlement(env):
    journal, registry, a, b, cwd, clock, claims = env
    before = journal.spec()
    offered = offer(env)
    assert offered['status'] == 'OFFERED' and offered['epoch'] == 0
    assert offered['mission_id'] == registry.mission_id
    assert offered['prompt_hash'] == digest(request(env).prompt)
    assert offered['input_manifest_hash'] == digest(manifest())
    assert claims.offer('run-first', a, asdict(request(env)), manifest()) == offered
    assert claims.claim(b, 'claimreq_other')['status'] == 'NO_WORK'
    result = claims.claim(a, 'claimreq_0001')
    assert result['status'] == 'CLAIMED'
    claim = result['claim']
    assert claim['epoch'] == 1 and claim['lease_expires_at'] == 1030
    assert claims.claim(a, 'claimreq_0001') == result
    assert claims.claim(a, 'claimreq_0002')['status'] == 'NO_WORK'
    assert upload(env, claim) == meta() | {'status': 'STORED'}
    terminal = deliver(env, claim, files=[meta()])
    assert terminal['status'] == 'RECEIPTED'
    assert terminal['receipt']['status'] == 'COMPLETED'
    assert deliver(env, claim, files=[meta()]) == terminal
    assert claims.offer('run-first', a, request(env), manifest()) == terminal
    assert journal.runs()[0]['status'] == 'IN_FLIGHT'
    assert journal.runs()[0]['receipt'] is None
    assert journal.runs()[0]['verdict'] == 'UNVERIFIED'
    assert journal.spec() == before
    with journal.store._transaction(immediate=False) as db:
        assert db.execute('SELECT count(*) FROM evidence').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM native_worker_commands').fetchone()[0] == 0
    assert journal.store.verify_event_chain()['valid']


def test_empty_claim_retry_stays_empty_after_new_offer_and_restart(env):
    journal, registry, a, _, _, clock, claims = env
    empty = claims.claim(a, 'claimreq_empty')
    assert empty == {'mission_id': registry.mission_id, 'node_id': a, 'request_id': 'claimreq_empty',
                     'status': 'NO_WORK', 'claim': None}
    offer(env)
    reopened_journal = LeadJournal(AutonomyStore(journal.store.path))
    reopened = NodeClaims(reopened_journal, NodeRegistry(reopened_journal), claims.artifact_root, clock=clock)
    assert reopened.claim(a, 'claimreq_empty') == empty
    assert reopened.claim(a, 'claimreq_fresh')['status'] == 'CLAIMED'
    assert reopened.journal.store.verify_event_chain()['valid']


def test_restart_reuses_claim_upload_and_receipt(env):
    journal, _, a, _, _, clock, claims = env
    claim = claimed(env)
    uploaded = upload(env, claim)
    reopened_journal = LeadJournal(AutonomyStore(journal.store.path))
    reopened = NodeClaims(reopened_journal, NodeRegistry(reopened_journal), claims.artifact_root, clock=clock)
    assert reopened.claim(a, 'claimreq_0001')['claim'] == claim
    assert reopened.upload(a, claim['claim_id'], 1, 'result.txt', meta()['sha256'], b'result') == uploaded
    receipt = reopened.receipt(a, claim['claim_id'], 1, Receipt('COMPLETED'), [meta()])
    assert reopened.get('run-first') == receipt
    assert reopened.get('missing') is None
    assert list(journal.store.path.parent.rglob('*.sqlite3')) == [journal.store.path]
    assert journal.store.verify_event_chain()['valid']


def test_expiry_unknown_never_requeues_late_receipt_candidate(env):
    claim = claimed(env)
    env[5].advance(30)  # Equality is expired.
    changed = env[-1].expire()
    assert [r['run_key'] for r in changed] == ['run-first']
    assert changed[0]['status'] == 'UNKNOWN'
    assert env[-1].expire() == []
    assert env[-1].claim(env[2], 'claimreq_0001')['claim'] == claim
    assert env[-1].claim(env[2], 'claimreq_0002')['status'] == 'NO_WORK'
    with pytest.raises(LeaseLost):
        env[-1].heartbeat(env[2], claim['claim_id'], 1)
    with pytest.raises(LeaseLost):
        upload(env, claim)
    late = deliver(env, claim)
    assert late['status'] == 'RECONCILIATION_CANDIDATE'
    assert late['epoch'] == 1
    assert env[0].runs()[0]['status'] == 'IN_FLIGHT'
    assert env[0].store.verify_event_chain()['valid']


def test_heartbeat_renewal_not_new_claim_and_no_backward_shortening(env):
    claim = claimed(env)
    env[5].advance(10)
    heartbeat = env[-1].heartbeat(env[2], claim['claim_id'], 1)
    assert heartbeat['lease_expires_at'] == 1040
    assert heartbeat['claim_id'] == claim['claim_id'] and heartbeat['epoch'] == 1
    env[5].advance(-5)
    assert env[-1].heartbeat(env[2], claim['claim_id'], 1)['lease_expires_at'] == 1040
    assert env[-1].claim(env[2], 'claimreq_0001')['claim'] == claim
    env[5].advance(35)
    with pytest.raises(LeaseLost):
        env[-1].heartbeat(env[2], claim['claim_id'], 1)
    assert env[-1].get('run-first')['status'] == 'UNKNOWN'


@pytest.mark.parametrize('action', ['heartbeat', 'upload', 'receipt'])
@pytest.mark.parametrize('epoch', [0, 2, True, '1'])
def test_wrong_epoch_never_mutates_claim(env, action, epoch):
    claim = claimed(env)
    before = env[-1].get('run-first')
    with pytest.raises(LeaseLost, match='epoch'):
        if action == 'heartbeat': env[-1].heartbeat(env[2], claim['claim_id'], epoch)
        elif action == 'upload': upload(env, claim, epoch=epoch)
        else: deliver(env, claim, epoch=epoch)
    assert env[-1].get('run-first') == before


@pytest.mark.parametrize('action', ['heartbeat', 'upload', 'receipt'])
def test_cross_node_claim_access_fenced(env, action):
    claim = claimed(env)
    with pytest.raises(PermissionError):
        if action == 'heartbeat': env[-1].heartbeat(env[3], claim['claim_id'], 1)
        elif action == 'upload': upload(env, claim, node_id=env[3])
        else: deliver(env, claim, node_id=env[3])
    assert env[-1].get('run-first')['uploads'] == []


def test_revoke_fences_claim_and_retains_late_result(env):
    claim = claimed(env)
    upload(env, claim)
    env[1].revoke(env[2])
    with pytest.raises(PermissionError):
        env[-1].claim(env[2], 'claimreq_0002')
    with pytest.raises(PermissionError):
        upload(env, claim)
    with pytest.raises(PermissionError):
        env[-1].heartbeat(env[2], claim['claim_id'], 1)
    assert env[-1].get('run-first')['status'] == 'UNKNOWN'
    assert deliver(env, claim, files=[meta()])['status'] == 'RECONCILIATION_CANDIDATE'
    assert env[0].runs()[0]['receipt'] is None
    assert env[0].store.verify_event_chain()['valid']


def test_revoked_offer_is_never_claimed(env):
    offer(env)
    env[1].revoke(env[2])
    assert env[-1].expire()[0]['status'] == 'UNKNOWN'
    assert env[-1].claim(env[3], 'claimreq_0001')['status'] == 'NO_WORK'
    with pytest.raises(DispatchBlocked, match='shared spending'):
        offer(env, key='run-next')


@pytest.mark.parametrize('status', ['UNKNOWN', 'RECEIPTED'])
def test_core_loss_fences_claim_without_core_rewrite(env, status):
    claim = claimed(env)
    env[0].complete('run-first', {'status': 'UNKNOWN' if status == 'UNKNOWN' else 'COMPLETED'})
    with pytest.raises(LeaseLost):
        env[-1].heartbeat(env[2], claim['claim_id'], 1)
    assert env[-1].get('run-first')['status'] == 'UNKNOWN'
    assert deliver(env, claim)['status'] == 'RECONCILIATION_CANDIDATE'
    assert env[0].runs()[0]['status'] == status


@pytest.mark.parametrize('native', ['UNKNOWN', 'ERROR', 'INTERRUPTED'])
def test_native_terminal_status_remains_transport(env, native):
    claim = claimed(env)
    result = deliver(env, claim, status=native)
    assert result['status'] == ('UNKNOWN' if native == 'UNKNOWN' else 'RECEIPTED')
    assert result['receipt']['status'] == native
    assert env[-1].claim(env[2], 'claimreq_0002')['status'] == 'NO_WORK'
    assert env[0].runs()[0]['receipt'] is None


def test_no_offer_without_matching_live_run(env):
    with pytest.raises(LeaseLost):
        env[-1].offer('not-reserved', env[2], request(env), manifest())
    req = request(env)
    env[0].reserve('run-first', 'different-task', digest('reserved'))
    with pytest.raises(ValueError, match='task_id'):
        env[-1].offer('run-first', env[2], req, manifest())
    env[0].complete('run-first', {'status': 'COMPLETED'})
    with pytest.raises(LeaseLost):
        env[-1].offer('run-first', env[2], req, manifest())


def test_offer_conflicts_on_node_prompt_timeout_and_manifest(env):
    offered = offer(env)
    for node, req, inputs in [(env[3], request(env), manifest()),
            (env[2], request(env, prompt='different'), manifest()),
            (env[2], request(env, timeout=400), manifest()),
            (env[2], request(env), manifest(outputs=['other.txt']))]:
        with pytest.raises(IdempotencyConflictError):
            env[-1].offer('run-first', node, req, inputs)
    assert env[-1].get('run-first') == offered


@pytest.mark.parametrize('changes', [{'driver': 'shell'}, {'command': 'echo hi'}, {'model': 'auto'},
    {'mode': 'read-only'}, {'session_id': 'resume-other'}, {'timeout': True},
    {'max_output_bytes': 33_000_000}, {'max_turns': 0}, {'prompt': ''}, {'cwd': 'relative'}])
def test_request_is_native_shaped_and_v1_only(env, changes):
    env[0].reserve('run-first', 'build', digest('approved'))
    with pytest.raises(ValueError):
        env[-1].offer('run-first', env[2], asdict(request(env)) | changes, manifest())
    assert env[-1].get('run-first') is None


def test_frozen_context_and_role_cannot_be_overridden(env):
    inbox = MissionInbox(env[0])
    req = request(env)
    env[0].reserve('run-first', 'build', digest('approved'),
        on_reserved=lambda db: inbox.bind(db, 'run-first', role='worker', task_id='build', prompt=req.prompt))
    with pytest.raises(IdempotencyConflictError, match='prompt'):
        env[-1].offer('run-first', env[2], request(env, prompt='changed'), manifest())
    env[0].record('roles', 'run-first', {'driver': 'codex', 'model': 'gpt-6.1-sol',
                                      'mode': 'workspace-write', 'cwd': str(env[4])})
    other = env[4] / 'other'
    other.mkdir()
    with pytest.raises(IdempotencyConflictError, match='role'):
        env[-1].offer('run-first', env[2], request(env, cwd=str(other)), manifest())
    assert env[-1].offer('run-first', env[2], req, manifest())['status'] == 'OFFERED'
    assert env[0].store.verify_event_chain()['valid']


@pytest.mark.parametrize('path', ['', '/absolute', '../parent', 'a/../x', './x', 'a//x',
    'a/', 'a\\x', 'a\0x', 'a\nx', 'C:/x', '.git/config', 'x/.codex/auth.json',
    '.aws/credentials', '.ssh/key', '.agents/x', '.env', 'autonomy.sqlite3',
    'x/AUTONOMY.SQLITE3-WAL', 'auth.json', 'credentials.json'])
def test_manifest_path_boundary_before_offer(env, path):
    env[0].reserve('run-first', 'build', digest('approved'))
    with pytest.raises(ValueError):
        env[-1].offer('run-first', env[2], request(env), manifest(outputs=[path]))
    assert env[-1].get('run-first') is None


@pytest.mark.parametrize('paths', [['A.txt', 'a.txt'], ['A/x.txt', 'a/y.txt'],
    ['x', 'x/y'], ['x', 'x'], ['X', 'x/y']])
def test_case_and_file_directory_collisions(env, paths):
    env[0].reserve('run-first', 'build', digest('approved'))
    with pytest.raises(ValueError):
        env[-1].offer('run-first', env[2], request(env), manifest(outputs=paths))


def test_input_files_hash_size_and_symlinks(env):
    (env[4] / 'input.txt').write_bytes(b'input')
    item = meta('input.txt', b'input')
    env[0].reserve('run-first', 'build', digest('approved'))
    for bad in [item | {'size': 3}, item | {'sha256': '0'*64}, item | {'size': True},
                item | {'sha256': 'F'*64}, item | {'extra': 1}]:
        with pytest.raises(ValueError):
            env[-1].offer('run-first', env[2], request(env), manifest(files=[bad]))
    (env[4] / 'link.txt').symlink_to(env[4] / 'input.txt')
    with pytest.raises(OSError):
        env[-1].offer('run-first', env[2], request(env), manifest(files=[meta('link.txt', b'input')]))
    with pytest.raises(ValueError, match='symlink'):
        env[-1].offer('run-first', env[2], request(env), manifest(outputs=['link.txt']))
    offered = env[-1].offer('run-first', env[2], request(env), manifest(files=[item], outputs=['input.txt']))
    assert offered['input_manifest']['files'] == [item]


def test_missing_input_and_hardlink_fail_closed(env):
    env[0].reserve('run-first', 'build', digest('approved'))
    with pytest.raises(FileNotFoundError):
        env[-1].offer('run-first', env[2], request(env), manifest(files=[meta('missing.txt')]))
    (env[4] / 'original.txt').write_bytes(b'result')
    os.link(env[4] / 'original.txt', env[4] / 'hard.txt')
    with pytest.raises(ValueError, match='regular file'):
        env[-1].offer('run-first', env[2], request(env), manifest(files=[meta('hard.txt')]))


def test_manifest_file_count_total_and_per_file_limits(env, monkeypatch):
    env[0].reserve('run-first', 'build', digest('approved'))
    with pytest.raises(ValueError, match='count'):
        env[-1].offer('run-first', env[2], request(env), manifest(outputs=[f'f{i}' for i in range(129)]))
    with pytest.raises(ValueError, match='count'):
        env[-1].offer('run-first', env[2], request(env), manifest(files=[meta(f'f{i}') for i in range(129)]))
    with pytest.raises(ValueError, match='size'):
        env[-1].offer('run-first', env[2], request(env), manifest(files=[meta() | {'size': module.MAX_FILE_BYTES+1}]))
    with pytest.raises(ValueError, match='total'):
        env[-1].offer('run-first', env[2], request(env), manifest(files=[meta(f'f{i}') | {'size': module.MAX_FILE_BYTES} for i in range(5)]))
    monkeypatch.setattr(module, 'MAX_MANIFEST_BYTES', 50)
    with pytest.raises(ValueError, match='manifest'):
        env[-1].offer('run-first', env[2], request(env), manifest(outputs=['a'*60]))


def test_upload_allowlist_hash_size_duplicate_and_receipt_manifest(env):
    claim = claimed(env)
    with pytest.raises(ValueError, match='allowlist'): upload(env, claim, path='not-approved')
    with pytest.raises(ValueError, match='SHA256'): upload(env, claim, sha256='0'*64)
    with pytest.raises(ValueError, match='bytes'): upload(env, claim, data=bytearray(b'result'))
    with pytest.raises(ValueError, match='bytes'): upload(env, claim, data=b'x'*(module.MAX_FILE_BYTES+1))
    saved = upload(env, claim)
    assert upload(env, claim) == saved
    with pytest.raises(IdempotencyConflictError): upload(env, claim, data=b'changed')
    for files in [[], [meta() | {'size': 5}], [meta() | {'sha256': '0'*64}], [meta('other.txt')]]:
        with pytest.raises(ValueError, match='manifest'): deliver(env, claim, files=files)
    terminal = deliver(env, claim, files=[meta()])
    with pytest.raises(IdempotencyConflictError): deliver(env, claim, status='ERROR', files=[meta()])
    with pytest.raises(LeaseLost): upload(env, claim)
    assert env[-1].get('run-first') == terminal
    assert env[0].store.verify_event_chain()['valid']


def test_upload_total_and_count_bounds_include_preparing(env, monkeypatch):
    claim = claimed(env, inputs=manifest(outputs=['a', 'b', 'c']))
    monkeypatch.setattr(module, 'MAX_TOTAL_BYTES', 7)
    upload(env, claim, path='a', data=b'1234')
    with pytest.raises(ValueError, match='count/total'): upload(env, claim, path='b', data=b'1234')
    monkeypatch.setattr(module, 'MAX_TOTAL_BYTES', 100)
    monkeypatch.setattr(module, 'MAX_FILES', 1)
    with pytest.raises(ValueError, match='count/total'): upload(env, claim, path='b', data=b'1')
    assert len(env[-1].get('run-first')['uploads']) == 1


def test_symlink_artifact_root_and_nested_directory_are_rejected(env):
    link = env[4] / 'root-link'
    link.symlink_to(env[-1].artifact_root, target_is_directory=True)
    with pytest.raises(OSError):
        NodeClaims(env[0], env[1], link, clock=env[5])
    claim = claimed(env, inputs=manifest(outputs=['nested/result.txt']))
    retained = env[-1].artifact_root / claim['claim_id']
    retained.mkdir()
    (retained / 'nested').symlink_to(env[4], target_is_directory=True)
    with pytest.raises(OSError): upload(env, claim, path='nested/result.txt')
    assert not (env[4] / 'result.txt').exists()
    assert env[-1].get('run-first')['uploads'][0]['status'] == 'PREPARING'
    assert env[0].store.verify_event_chain()['valid']


def test_preexisting_file_not_overwritten_and_receipt_tamper_detected(env):
    claim = claimed(env)
    folder = env[-1].artifact_root / claim['claim_id']
    folder.mkdir()
    (folder / 'result.txt').write_bytes(b'unrelated')
    with pytest.raises(IdempotencyConflictError): upload(env, claim)
    assert (folder / 'result.txt').read_bytes() == b'unrelated'
    with pytest.raises(ValueError, match='mismatch'): upload(env, claim)
    assert env[-1].get('run-first')['uploads'][0]['status'] == 'PREPARING'
    with pytest.raises(ValueError, match='manifest'): deliver(env, claim, files=[meta()])


def test_completed_upload_tamper_before_receipt_is_rejected(env):
    claim = claimed(env)
    upload(env, claim)
    path = env[-1].artifact_root / claim['claim_id'] / 'result.txt'
    with path.open('ab') as file: file.write(b'tamper')
    with pytest.raises(ValueError, match='mismatch'): deliver(env, claim, files=[meta()])
    with pytest.raises(ValueError, match='mismatch'): upload(env, claim)
    assert env[-1].get('run-first')['receipt'] is None


def test_partial_write_is_retained_fenced_and_never_overwritten(env, monkeypatch):
    claim = claimed(env)
    original = module.os.write
    calls = []
    def partial(fd, data):
        if calls: raise OSError('injected write interruption')
        calls.append(True)
        return original(fd, data[:2])
    monkeypatch.setattr(module.os, 'write', partial)
    with pytest.raises(OSError, match='interruption'): upload(env, claim)
    monkeypatch.setattr(module.os, 'write', original)
    path = env[-1].artifact_root / claim['claim_id'] / 'result.txt'
    assert path.read_bytes() == b're'
    assert env[-1].get('run-first')['uploads'][0]['status'] == 'PREPARING'
    with pytest.raises(ValueError, match='mismatch'): upload(env, claim)
    assert path.read_bytes() == b're'
    with pytest.raises(ValueError, match='manifest'): deliver(env, claim, files=[meta()])
    assert env[0].store.verify_event_chain()['valid']


def test_complete_file_before_db_commit_recovers_after_restart(env, monkeypatch):
    claim = claimed(env)
    original = env[0].store._append_event
    def fail(*args, **kwargs):
        if kwargs['event_type'] == 'WORKER_NODE_UPLOADED':
            raise RuntimeError('injected upload commit failure')
        return original(*args, **kwargs)
    monkeypatch.setattr(env[0].store, '_append_event', fail)
    with pytest.raises(RuntimeError, match='commit failure'): upload(env, claim)
    assert env[-1].get('run-first')['uploads'][0]['status'] == 'PREPARING'
    assert (env[-1].artifact_root / claim['claim_id'] / 'result.txt').read_bytes() == b'result'
    journal = LeadJournal(AutonomyStore(env[0].store.path))
    reopened = NodeClaims(journal, NodeRegistry(journal), env[-1].artifact_root, clock=env[5])
    assert reopened.upload(env[2], claim['claim_id'], 1, 'result.txt', meta()['sha256'], b'result')['status'] == 'STORED'
    assert journal.store.verify_event_chain()['valid']


def test_offer_claim_and_receipt_event_failures_rollback(env, monkeypatch):
    original = env[0].store._append_event
    event = ['WORKER_NODE_OFFERED']
    def fail(*args, **kwargs):
        if kwargs['event_type'] == event[0]: raise RuntimeError('injected event failure')
        return original(*args, **kwargs)
    monkeypatch.setattr(env[0].store, '_append_event', fail)
    with pytest.raises(RuntimeError): offer(env)
    assert env[-1].get('run-first') is None
    event[0] = 'WORKER_NODE_CLAIMED'
    env[-1].offer('run-first', env[2], request(env), manifest())
    with pytest.raises(RuntimeError): env[-1].claim(env[2], 'claimreq_0001')
    assert env[-1].get('run-first')['status'] == 'OFFERED'
    event[0] = 'WORKER_NODE_RECEIPT'
    claim = env[-1].claim(env[2], 'claimreq_0001')['claim']
    with pytest.raises(RuntimeError): deliver(env, claim)
    assert env[-1].get('run-first')['status'] == 'CLAIMED'
    assert env[-1].get('run-first')['receipt'] is None
    assert env[0].store.verify_event_chain()['valid']


def test_concurrent_claims_are_one_identity_and_concurrent_uploads_idempotent(env):
    offer(env)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: env[-1].claim(env[2], 'claimreq_0001'), range(8)))
    assert all(r == results[0] for r in results)
    claim = results[0]['claim']
    with ThreadPoolExecutor(max_workers=4) as pool:
        uploaded = list(pool.map(lambda _: upload(env, claim), range(8)))
    assert all(u == meta() | {'status': 'STORED'} for u in uploaded)
    assert len(env[-1].get('run-first')['uploads']) == 1
    assert env[0].store.verify_event_chain()['valid']


def test_pause_stop_and_no_work_requests_do_not_dispatch(env):
    offer(env)
    env[0].pause(True)
    assert env[-1].claim(env[2], 'claimreq_paused')['status'] == 'NO_WORK'
    env[0].pause(False)
    env[0].update(lambda s: s.update(stopped=True))
    assert env[-1].claim(env[2], 'claimreq_stopped')['status'] == 'NO_WORK'
    env[0].update(lambda s: s.update(stopped=False))
    assert env[-1].claim(env[2], 'claimreq_paused')['status'] == 'NO_WORK'
    assert env[-1].claim(env[2], 'claimreq_fresh')['status'] == 'CLAIMED'
    assert len(env[0].runs()) == 1


def test_root_pin_store_mismatch_schema_and_clock_boundaries(env, tmp_path):
    other = NodeRegistry(Journal(AutonomyStore(tmp_path / 'other' / 'autonomy.sqlite3')))
    with pytest.raises(ValueError, match='share'): NodeClaims(env[0], other, env[-1].artifact_root)
    with pytest.raises(IdempotencyConflictError, match='root'): NodeClaims(env[0], env[1], tmp_path / 'different')
    for value in [True, -1, float('nan'), float('inf'), 'now']:
        with pytest.raises(ValueError, match='clock'):
            NodeClaims(env[0], env[1], env[-1].artifact_root, clock=lambda: value)
    for value in [True, 0, 3601, float('inf')]:
        with pytest.raises(ValueError): NodeClaims(env[0], env[1], env[-1].artifact_root, lease_seconds=value)
    with env[0].store._transaction() as db:
        db.execute("UPDATE metadata SET value='future' WHERE key='remote_claim_schema'")
    with pytest.raises(ValueError, match='schema'): NodeClaims(env[0], env[1], env[-1].artifact_root)


def test_plain_journal_compatibility_and_mission_isolation(env, tmp_path):
    journal = Journal(AutonomyStore(tmp_path / 'other' / 'autonomy.sqlite3'))
    journal.bind({'parallelism': 2, 'max_calls': None})
    registry = NodeRegistry(journal)
    node = registry.enroll('enroll_0001', 'other', ['codex'], ['gpt-6.1-sol'])['node_id']
    claims = NodeClaims(journal, registry, tmp_path / 'other-artifacts', clock=env[5])
    journal.reserve('run-first', 'build', digest('other'))
    with pytest.raises(PermissionError): claims.offer('run-first', env[2], request(env), manifest())
    claims.offer('run-first', node, request(env), manifest())
    assert env[-1].get('run-first') is None
    assert claims.get('run-first')['mission_id'] != env[1].mission_id
    assert journal.store.verify_event_chain()['valid']


def test_receipt_boundaries_redaction_attestation_and_chain(env, monkeypatch):
    claim = claimed(env)
    with pytest.raises(ValueError): deliver(env, claim, receipt={'status': 'PASS'})
    with pytest.raises(ValueError): deliver(env, claim, receipt={'status': 'COMPLETED', 'command': 'run'})
    with pytest.raises(ValueError): deliver(env, claim, receipt={'status': 'COMPLETED', 'requested_model': 'auto'})
    monkeypatch.setattr(module, 'MAX_RECEIPT_BYTES', 500)
    with pytest.raises(ValueError, match='bound'): deliver(env, claim, receipt=Receipt('COMPLETED', output='x'*501))
    monkeypatch.setattr(module, 'MAX_RECEIPT_BYTES', 1_000_000)
    result = deliver(env, claim, receipt=Receipt('COMPLETED', output='Bearer fixture-private-token',
                                               requested_model='gpt-6.1-sol', actual_model=None))
    assert result['receipt']['actual_model'] is None  # Never infer attestation.
    assert 'fixture-private-token' not in json.dumps(result)
    assert env[0].runs()[0]['receipt'] is None
    assert env[0].store.verify_event_chain()['valid']


def test_lease_loss_during_upload_retains_bytes_and_unknown(env, monkeypatch):
    claim = claimed(env)
    original = module.os.write
    def slow(fd, data):
        result = original(fd, data)
        env[5].advance(30)
        return result
    monkeypatch.setattr(module.os, 'write', slow)
    with pytest.raises(LeaseLost): upload(env, claim)
    assert (env[-1].artifact_root / claim['claim_id'] / 'result.txt').read_bytes() == b'result'
    assert env[-1].get('run-first')['uploads'][0]['status'] == 'PREPARING'
    assert env[-1].expire()[0]['status'] == 'UNKNOWN'
    assert env[-1].claim(env[2], 'claimreq_again')['status'] == 'NO_WORK'
    assert env[0].store.verify_event_chain()['valid']
