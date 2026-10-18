"""Frozen claim request-id admission, using direct public callers only.

Redact-changing request_id must raise fixed ValueError after syntax validation
but before expire/Claims transaction/IO, on first call and exact retry. Existing
offers, cached poisoned responses, canonical runs and lease/event state stay
untouched. Ordinary ids keep CLAIMED/NO_WORK cache and explicit expiry behavior.
Raw N1 events still hash their original normalized data and persist redacted data.

All fixtures are synthetic real SQLite stores; no Gateway import, HTTP/native,
process credential inspection, poisoned-row removal, or cleanup context. Actual
protocol.redact runs against an isolated environment. File checks deliberately
exclude SQLite/WAL auxiliary authority, which belongs to the console HOLD.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest

from sisyfus.autonomy.models import OpportunitySignal
from sisyfus.autonomy.store import AutonomyStore
from sisyfus.workers.claude_code import ClaudeCodeDriver
from sisyfus.workers.codex import CodexDriver
import sisyfus.workers.journal as journal_module
from sisyfus.workers.journal import Journal
from sisyfus.workers.lead_journal import LeadJournal
import sisyfus.workers.node_claims as claims_module
from sisyfus.workers.node_claims import NodeClaims
from sisyfus.workers.node_registry import NodeRegistry, validate_request_id
import sisyfus.workers.protocol as protocol_module
from sisyfus.workers.protocol import Request, digest, redact


UNSAFE_IDS = ['sk-abcdefghijklmnop', 'sk-abcdefghijkl', 'prefix-sk-abcdefghijklmnop']
ORDINARY_IDS = ['claim_id_0001', 'sk-abcdefghijk', 'xsk-abcdefghijklmnop', 'SK-abcdefghijklmnop', 'C' * 100]
INVALID_IDS = [None, True, 3, {'secret': 'synthetic'}, ['sk-abcdefghijklmnop'], 'short', 'Bearer fixture']
CLAIM_ERROR = 'claim request contains credential material'
SYNTAX_ERROR = 'request_id must be 8..100 letters, digits, underscores or hyphens'


def forbidden(*args, **kwargs):
    pytest.fail('claim admission reached native/network execution')


@pytest.fixture(autouse=True)
def isolated_offline(monkeypatch):
    monkeypatch.setattr(protocol_module, 'os', SimpleNamespace(environ={}))
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    for driver in (CodexDriver, ClaudeCodeDriver):
        monkeypatch.setattr(driver, 'run', forbidden)
        monkeypatch.setattr(driver, 'probe', forbidden)


class Clock:
    def __init__(self):
        self.value = 1000.0

    def __call__(self):
        return self.value

    def utc(self):
        return datetime.fromtimestamp(self.value, timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


@pytest.fixture(params=[Journal, LeadJournal], ids=['plain-Journal', 'LeadJournal'])
def env(request, tmp_path, tmp_path_factory, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(journal_module, 'utc_now', clock.utc)
    journal = request.param(AutonomyStore(tmp_path / 'autonomy.sqlite3'))
    journal.bind({'parallelism': 10, 'max_calls': None, 'acceptance_hash': 'fixed',
                  'checks': {'a': {'sha': 'immutable'}}, 'objective': 'fixed claim admission',
                  'tasks': [{'id': 'build-a', 'driver': 'codex'}, {'id': 'build-b', 'driver': 'codex'}]})
    opportunity, _ = journal.store.submit_opportunity(
        OpportunitySignal('claim-id-fixture', 'input', 'fixed task'), now=clock.utc())
    journal.store.admit_opportunity(opportunity['id'], now=clock.utc())
    continuation = journal.store.claim_due_continuation('controller', lease_seconds=60, now=clock.utc())
    registry = NodeRegistry(journal)
    node = registry.enroll('claim-admission-enroll-0001', 'synthetic fixture', ['codex'], ['gpt-6.1-sol'])['node_id']
    cwd = tmp_path / 'workspace'
    cwd.mkdir()
    claims = NodeClaims(journal, registry, tmp_path / 'retained-artifacts', clock=clock)
    return SimpleNamespace(journal=journal, journal_class=request.param, registry=registry, node=node,
                           claims=claims, cwd=cwd, tree=tmp_path, clock=clock, continuation=continuation,
                           proof=tmp_path_factory.mktemp('claim-id-admission-evidence'))


def offer_pair(env):
    for name in ('a', 'b'):
        request = Request('build-' + name, 'Fixed request ' + name, str(env.cwd), 'gpt-6.1-sol', mode='workspace-write')
        key = 'run-' + name
        env.journal.reserve(key, request.task_id, digest(asdict(request)),
                            continuation_id=env.continuation['id'], lease_token=env.continuation['lease_token'])
        env.claims.offer(key, env.node, request, {'files': [], 'output_paths': [name + '.txt']})


def prepare(env, state):
    if state == 'no-work':
        return
    offer_pair(env)
    if state == 'expired-node':
        cached = env.claims.claim(env.node, 'original_claim_0001')
        assert cached['claim']['run_key'] == 'run-a'
        env.clock.value += 30
    elif state == 'expired-core':
        env.clock.value += 60
    elif state == 'revoked':
        env.registry.revoke(env.node)
    else:
        assert state == 'offered'


def snapshot(env):
    db = sqlite3.connect(env.journal.store.path.as_uri() + '?mode=ro', uri=True, isolation_level=None)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        logical = '\n'.join(db.iterdump())
        counts = {table: db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                  for table in ('remote_offers', 'remote_claim_requests', 'remote_event_sync', 'events', 'native_worker_runs')}
        offers = db.execute('SELECT run_key,status,claim_id,epoch,lease_expires_at FROM remote_offers ORDER BY run_key').fetchall()
        core = db.execute('SELECT key,status,lease_token,receipt_json FROM native_worker_runs ORDER BY key').fetchall()
        db.execute('COMMIT')
    finally:
        db.close()
    entries = {}
    for path in sorted(env.tree.rglob('*')):
        if path.name in {'autonomy.sqlite3', 'autonomy.sqlite3-wal', 'autonomy.sqlite3-shm'}:
            continue
        info = path.lstat()
        entries[str(path.relative_to(env.tree))] = {
            'dev': info.st_dev, 'ino': info.st_ino, 'mode': info.st_mode,
            'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None}
    return {'logical': logical, 'counts': counts, 'offers': offers, 'core': core, 'entries': entries}


def retain(env, name, value):
    with (env.proof / name).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def rejected_twice(env, monkeypatch, request_id, message=CLAIM_ERROR):
    before = snapshot(env)
    expirations, transactions, io, outcomes, errors = [], [], [], [], []
    original_expire, original_transaction = env.claims.expire, env.journal.store._transaction

    def observed_expire():
        expirations.append(True)
        return original_expire()

    @contextmanager
    def observed_transaction(*, immediate=True):
        transactions.append(immediate)
        with original_transaction(immediate=immediate) as db:
            yield db

    def observe_io(name, original):
        def wrapped(*args, **kwargs):
            io.append(name)
            return original(*args, **kwargs)
        return wrapped

    with monkeypatch.context() as observer:
        observer.setattr(env.claims, 'expire', observed_expire)
        observer.setattr(env.journal.store, '_transaction', observed_transaction)
        for name in ('_directory', '_parent', '_verify_file', '_snapshot_read'):
            observer.setattr(claims_module, name, observe_io(name, getattr(claims_module, name)))
        for _ in range(2):
            try:
                # No gateway adapter: the public service protects its callers.
                result = env.claims.claim(node_id=env.node, request_id=request_id)
            except Exception as exc:
                errors.append(exc)
                outcomes.append({'error_type': type(exc).__name__, 'message': str(exc)})
            else:
                outcomes.append({'result': result})
    after = snapshot(env)
    chain = env.journal.store.verify_event_chain()
    retain(env, 'first-and-exact-retry.json', {'before': before, 'after': after, 'outcomes': outcomes,
                                            'expire_calls': expirations, 'transactions': transactions,
                                            'package_io': io, 'event_chain': chain})
    print(json.dumps({'retained_evidence': str(env.proof), 'outcomes': [o.get('error_type', 'returned') for o in outcomes],
                      'expire_calls': len(expirations), 'transactions': transactions, 'package_io': io,
                      'before': before['counts'], 'after': after['counts']}, sort_keys=True))
    assert len(errors) == 2 and all(type(error) is ValueError for error in errors), 'unsafe request_id was admitted or returned a later error'
    assert all(str(error) == message for error in errors), 'admission error must be fixed and echo no rejected text'
    assert expirations == [] and transactions == [], 'claim rejected only after expiry/transaction admission'
    assert io == [] and before == after, 'rejection changed rows/events/lease/path state'
    assert chain['valid']
    return before


def test_static_public_claim_and_redaction_corpus():
    assert all(validate_request_id(value) == value and redact(value) != value for value in UNSAFE_IDS)
    assert all(validate_request_id(value) == value and redact(value) == value for value in ORDINARY_IDS)
    tree = ast.parse(Path(claims_module.__file__).read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'NodeClaims')
    claim = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'claim')
    assert [arg.arg for arg in claim.args.args] == ['self', 'node_id', 'request_id']
    assert isinstance(claim.body[0], ast.Expr) and claim.body[0].value.func.id == 'validate_request_id'


@pytest.mark.parametrize('request_id', UNSAFE_IDS)
@pytest.mark.parametrize('state', ['offered', 'no-work', 'expired-node'])
def test_direct_claim_first_and_retry_reject_before_any_expiry_or_state_change(env, monkeypatch, request_id, state):
    prepare(env, state)
    before = rejected_twice(env, monkeypatch, request_id)
    assert before['counts']['remote_claim_requests'] == int(state == 'expired-node')
    if state == 'offered':
        assert all(row[1] == 'OFFERED' and row[2:] == (None, 0, None) for row in before['offers'])
    elif state == 'expired-node':
        assert env.claims.get('run-a')['status'] == 'CLAIMED'
        assert env.claims.get('run-b')['status'] == 'OFFERED'
        # Invalid input is read-only; explicit existing expiry still owns fencing.
        assert env.claims.expire()[0]['status'] == 'UNKNOWN'
        assert env.claims.get('run-b')['status'] == 'OFFERED'
    assert all(run['status'] == 'IN_FLIGHT' and run['receipt'] is None for run in env.journal.runs())


@pytest.mark.parametrize('state', ['expired-core', 'revoked'])
def test_bad_request_rejects_before_core_loss_or_revocation_sweep(env, monkeypatch, state):
    prepare(env, state)
    rejected_twice(env, monkeypatch, UNSAFE_IDS[0])
    assert env.claims.get('run-a')['status'] == env.claims.get('run-b')['status'] == 'OFFERED'
    assert all(run['status'] == 'IN_FLIGHT' for run in env.journal.runs())


@pytest.mark.parametrize('status', ['NO_WORK', 'CLAIMED'])
def test_retained_historical_poisoned_cache_is_never_cleared_or_returned(env, monkeypatch, status):
    if status == 'CLAIMED':
        offer_pair(env)
        cached = env.claims.claim(env.node, 'history_original_claim')
    else:
        cached = {'mission_id': env.registry.mission_id, 'node_id': env.node,
                  'request_id': 'history_original_empty', 'status': 'NO_WORK', 'claim': None}
    poisoned = cached | {'request_id': UNSAFE_IDS[0]}
    # Seed only a synthetic historical transport response, never patch service
    # validation or emulate a new public interface. Retain it after rejection.
    with env.journal.store._transaction() as db:
        db.execute('INSERT INTO remote_claim_requests VALUES(?,?,?)',
                   (env.node, UNSAFE_IDS[0], json.dumps(poisoned, sort_keys=True, separators=(',', ':'))))
        env.journal._event(db, 'historical_claim_fixture', env.node,
                           {'request_id_hash': digest(UNSAFE_IDS[0]), 'response_hash': digest(poisoned)})
    before = rejected_twice(env, monkeypatch, UNSAFE_IDS[0])
    assert before['counts']['remote_claim_requests'] == (2 if status == 'CLAIMED' else 1)
    assert snapshot(env) == before


@pytest.mark.parametrize('request_id', ORDINARY_IDS)
@pytest.mark.parametrize('state', ['offered', 'no-work'])
def test_ordinary_ids_keep_public_projection_and_readonly_cached_replay(env, request_id, state):
    prepare(env, state)
    first = env.claims.claim(env.node, request_id)
    assert set(first) == {'mission_id', 'node_id', 'request_id', 'status', 'claim'}
    assert first['mission_id'] == env.registry.mission_id and first['request_id'] == request_id
    assert first['status'] == ('CLAIMED' if state == 'offered' else 'NO_WORK')
    if state == 'offered':
        assert first['claim']['run_key'] == 'run-a' and first['claim']['epoch'] == 1
        assert env.claims.get('run-b')['status'] == 'OFFERED'
    else:
        assert first['claim'] is None
    before = snapshot(env)
    env.clock.value += 5
    assert NodeClaims.claim(env.claims, node_id=env.node, request_id=request_id) == first
    assert env.claims.claim(env.node, request_id) == first
    after = snapshot(env)
    retain(env, 'ordinary-cached-replay.json', {'before': before, 'after': after, 'response': first})
    assert before == after and redact(first) == first
    assert env.journal.store.verify_event_chain()['valid']


@pytest.mark.parametrize('request_id', INVALID_IDS)
def test_original_request_id_syntax_validation_still_precedes_everything(env, monkeypatch, request_id):
    prepare(env, 'expired-node')
    rejected_twice(env, monkeypatch, request_id, message=SYNTAX_ERROR)
    assert env.claims.get('run-a')['status'] == 'CLAIMED'


def test_cached_no_work_does_not_claim_later_new_offers(env):
    first = env.claims.claim(env.node, 'empty_original_0001')
    assert first['status'] == 'NO_WORK' and first['claim'] is None
    offer_pair(env)
    before = snapshot(env)
    assert env.claims.claim(env.node, 'empty_original_0001') == first
    assert snapshot(env) == before
    fresh = env.claims.claim(env.node, 'empty_new_request_0002')
    assert fresh['status'] == 'CLAIMED' and fresh['claim']['run_key'] == 'run-a'
    assert env.journal.store.verify_event_chain()['valid']


def test_ordinary_cached_replay_retains_original_expiry_fence_behavior(env):
    prepare(env, 'offered')
    cached = env.claims.claim(env.node, 'cached_expiry_original')
    env.clock.value += 30
    assert env.claims.claim(env.node, 'cached_expiry_original') == cached
    assert env.claims.get('run-a')['status'] == 'UNKNOWN'
    b = env.claims.get('run-b')
    assert b['status'] == 'OFFERED' and b['epoch'] == 0 and b['claim_id'] is None
    fresh = env.claims.claim(env.node, 'cached_expiry_fresh')
    assert fresh['status'] == 'NO_WORK' and fresh['claim'] is None
    assert all(run['status'] == 'IN_FLIGHT' for run in env.journal.runs())
    assert env.journal.store.verify_event_chain()['valid']


def test_raw_n1_digest_and_duplicate_sync_keep_their_existing_semantics(env):
    prepare(env, 'offered')
    cached = env.claims.claim(env.node, 'sync_original_claim')
    claim = cached['claim']
    event = {'seq': 1, 'kind': 'native_event', 'data': {'method': 'fixture.status', 'params': {'text': UNSAFE_IDS[0]}}}
    env.clock.value += 3
    fresh = env.claims.sync(env.node, claim['claim_id'], 1, [event])
    assert fresh['last_seq'] == 1 and fresh['lease_expires_at'] == 1033
    with env.journal.store._transaction(immediate=False) as db:
        row = db.execute('SELECT raw_digest,data_json FROM remote_event_sync WHERE claim_id=? AND epoch=1 AND seq=1',
                         (claim['claim_id'],)).fetchone()
    assert row['raw_digest'] == digest(event) and json.loads(row['data_json']) == redact(event['data'])
    assert UNSAFE_IDS[0] not in row['data_json']
    before = snapshot(env)
    env.clock.value += 3
    assert env.claims.sync(env.node, claim['claim_id'], 1, [event]) == fresh
    assert env.claims.sync(env.node, claim['claim_id'], 1, []) == fresh
    assert env.claims.claim(env.node, 'sync_original_claim') == cached
    assert snapshot(env) == before
    retain(env, 'raw-n1-and-replay.json', {'before': before, 'sync': fresh, 'raw_digest': row['raw_digest'],
                                       'persisted_data': json.loads(row['data_json'])})
    assert env.journal.store.verify_event_chain()['valid']


def test_rejection_then_restart_keeps_offers_and_clean_claim_identity(env, monkeypatch):
    prepare(env, 'offered')
    rejected_twice(env, monkeypatch, UNSAFE_IDS[0])
    journal = env.journal_class(AutonomyStore(env.journal.store.path))
    registry = NodeRegistry(journal)
    claims = NodeClaims(journal, registry, env.claims.artifact_root, clock=env.clock)
    env.journal, env.registry, env.claims = journal, registry, claims
    assert claims.get('run-a')['status'] == claims.get('run-b')['status'] == 'OFFERED'
    cached = claims.claim(env.node, 'restarted_clean_claim')
    assert cached['status'] == 'CLAIMED' and cached['claim']['run_key'] == 'run-a'
    before = snapshot(env)
    assert claims.claim(env.node, 'restarted_clean_claim') == cached
    assert snapshot(env) == before
    assert all(run['status'] == 'IN_FLIGHT' for run in journal.runs())
    assert journal.store.verify_event_chain()['valid']


def test_synthetic_environment_redaction_also_guards_direct_public_claim(env, monkeypatch):
    protocol_module.os.environ['OPENAI_API_KEY'] = 'ENV_FIXTURE_KEY_1234'
    request_id = 'claim-ENV_FIXTURE_KEY_1234'
    assert validate_request_id(request_id) == request_id and redact(request_id) != request_id
    prepare(env, 'offered')
    rejected_twice(env, monkeypatch, request_id)
