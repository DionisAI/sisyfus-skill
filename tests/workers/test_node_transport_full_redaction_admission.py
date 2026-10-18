"""Frozen full-record transport admission regressions; no HTTP/native acceptance.

offer must reject redact-changing immutable input before a Claims transaction
or package IO, whether a snapshot exists or not. Exact retry has the same fixed
ValueError and leaves canonical/transport/path/event state unchanged. Existing
bind_input_snapshot rejects these strings inside its transaction, before package
IO; that established boundary is preserved, not widened by this test slice.

All text is synthetic, and protocol.redact uses an isolated empty environment.
Its implementation is unchanged. Gateway is inspected as source, never imported
or called. Real SQLite fixtures and failed publication evidence are retained.
SQLite WAL auxiliary-file authority belongs to the separate console HOLD; these
tests compare logical database state and the non-SQLite retained file tree.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
from dataclasses import asdict, replace
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
import sisyfus.workers.node_claims as claims_module
from sisyfus.workers.node_claims import NodeClaims
from sisyfus.workers.node_registry import NodeRegistry
import sisyfus.workers.protocol as protocol_module
from sisyfus.workers.protocol import Request, digest, redact


REDACTING_PATHS = [
    'sk-learn-notebooks/run.txt',
    'Bearer fixture.txt',
    'exports/sk-abcdefghijklmnop.txt',
    'exports/bEaReR\u00a0fixture.txt',
]
ORDINARY_PATHS = [
    'notes/learn-notebooks/run.txt',
    'sk-short.txt',
    'sk-abcdefghijk.txt',
    'xsk-abcdefghijklmnop.txt',
    'SK-abcdefghijklmnop.txt',
    'bearer-fixture.txt',
]
DATA = b'fixed input'


def forbidden(*args, **kwargs):
    pytest.fail('full-record admission reached native/network execution')


@pytest.fixture(autouse=True)
def isolated_offline(monkeypatch):
    # Replace only the protocol environment boundary; do not inspect process
    # credentials or replace the actual redact/admission/IO implementations.
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


@pytest.fixture
def env(tmp_path, tmp_path_factory, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(journal_module, 'utc_now', clock.utc)
    journal = Journal(AutonomyStore(tmp_path / 'autonomy.sqlite3'))
    journal.bind({'parallelism': 10, 'max_calls': None, 'acceptance_hash': 'fixed',
                  'checks': {'a': {'sha': 'immutable'}}, 'tasks': [{'id': 'build', 'driver': 'codex'}]})
    opportunity, _ = journal.store.submit_opportunity(
        OpportunitySignal('full-redaction-fixture', 'input', 'fixed task'), now=clock.utc())
    journal.store.admit_opportunity(opportunity['id'], now=clock.utc())
    continuation = journal.store.claim_due_continuation('controller', lease_seconds=60, now=clock.utc())
    registry = NodeRegistry(journal)
    node = registry.enroll('full-redaction-enroll-0001', 'synthetic fixture', ['codex'], ['gpt-6.1-sol'])['node_id']
    cwd, root = tmp_path / 'workspace', tmp_path / 'snapshot'
    cwd.mkdir()
    root.mkdir()
    claims = NodeClaims(journal, registry, tmp_path / 'retained-artifacts', clock=clock)
    return SimpleNamespace(journal=journal, registry=registry, node=node, claims=claims,
                           cwd=cwd, root=root, tree=tmp_path, clock=clock, continuation=continuation,
                           request=Request('build', 'Fixed task.', str(cwd), 'gpt-6.1-sol', mode='workspace-write'),
                           proof=tmp_path_factory.mktemp('full-redaction-evidence'))


def reserve(env, key='full-redaction-run', request=None):
    request = env.request if request is None else request
    env.journal.reserve(key, request.task_id, digest(asdict(request)),
                        continuation_id=env.continuation['id'], lease_token=env.continuation['lease_token'])
    return key


def manifest(path=None, location='input'):
    input_path = path if path is not None and location == 'input' else 'source/input.txt'
    output_path = path if path is not None and location == 'output' else 'out/result.txt'
    return {'files': [{'path': input_path, 'sha256': hashlib.sha256(DATA).hexdigest(), 'size': len(DATA)}],
            'output_paths': [output_path]}


def put_inputs(env, inputs):
    for root in (env.cwd, env.root):
        for item in inputs['files']:
            target = root / item['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                assert target.read_bytes() == DATA
            else:
                with target.open('xb') as stream:
                    stream.write(DATA)


def state(env):
    db = sqlite3.connect(env.journal.store.path.as_uri() + '?mode=ro', uri=True, isolation_level=None)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        counts = {table: db.execute('SELECT count(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0]
                  for table in tables}
        logical = '\n'.join(db.iterdump())
        core = db.execute('SELECT key,status,receipt_json FROM native_worker_runs ORDER BY key').fetchall()
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
            'size': info.st_size, 'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None}
    return {'logical': logical, 'counts': counts, 'core': core, 'entries': entries}


def retain(env, name, value):
    with (env.proof / name).open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')


def rejected_twice(env, monkeypatch, invoke, *, binding=False):
    before = state(env)
    transactions, io, outcomes, errors = [], [], [], []
    original_transaction = env.journal.store._transaction

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
        observer.setattr(env.journal.store, '_transaction', observed_transaction)
        for name in ('_snapshot_read', '_verify_file', '_directory', '_parent'):
            observer.setattr(claims_module, name, observe_io(name, getattr(claims_module, name)))
        for _ in range(2):
            try:
                result = invoke()
            except Exception as exc:
                errors.append(exc)
                outcomes.append({'error_type': type(exc).__name__, 'message': str(exc)})
            else:
                outcomes.append({'result': result})
    after = state(env)
    chain = env.journal.store.verify_event_chain()
    retain(env, 'rejection-and-replay.json', {'before': before, 'after': after, 'outcomes': outcomes,
                                           'transactions': transactions, 'package_io': io, 'event_chain': chain})
    print(json.dumps({'retained_evidence': str(env.proof), 'outcomes': [o.get('error_type', 'returned') for o in outcomes],
                      'transactions': transactions, 'package_io': io,
                      'before_counts': before['counts'], 'after_counts': after['counts']}, sort_keys=True))
    message = 'input binding contains credential material' if binding else 'offer contains credential material'
    assert len(errors) == 2 and all(type(error) is ValueError for error in errors), (
        'redact-changing admission and its exact replay require ValueError before publication')
    assert all(str(error) == message for error in errors), 'errors must be fixed and contain no rejected fixture text'
    assert transactions == ([True, True] if binding else []), 'offer rejection entered a Claims transaction'
    assert io == [], 'redact-changing admission reached package IO'
    assert before == after, 'rejection changed canonical/transport/path/lease/event state'
    assert chain['valid']
    return before


def test_static_gateway_uses_actual_redact_and_exact_public_service_shape():
    assert all(redact(path) != path for path in REDACTING_PATHS)
    assert all(redact(path) == path for path in ORDINARY_PATHS)
    source = Path(claims_module.__file__).read_text()
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'NodeClaims')
    methods = {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef)}
    assert [arg.arg for arg in methods['offer'].args.args] == ['self', 'run_key', 'node_id', 'request', 'input_manifest']
    assert [arg.arg for arg in methods['bind_input_snapshot'].args.args] == ['self', 'run_key', 'root', 'manifest']
    gateway = Path(claims_module.__file__).with_name('node_gateway.py').read_text()
    clean = next(node for node in ast.parse(gateway).body if isinstance(node, ast.FunctionDef) and node.name == '_clean')
    first = next(node for node in clean.body if isinstance(node, ast.Assign))
    assert isinstance(first.value, ast.Call) and isinstance(first.value.func, ast.Name) and first.value.func.id == 'redact'


@pytest.mark.parametrize('path', REDACTING_PATHS)
@pytest.mark.parametrize('location', ['input', 'output'])
@pytest.mark.parametrize('pinned', [False, True], ids=['legacy-unbound', 'snapshot-bound'])
@pytest.mark.parametrize('shape', ['Request', 'dict'])
def test_complete_offer_record_rejected_before_transaction_or_package_io(env, monkeypatch, path, location, pinned, shape):
    inputs = manifest(path, location)
    put_inputs(env, inputs)
    key = reserve(env)
    if pinned:
        clean = manifest()
        put_inputs(env, clean)
        env.claims.bind_input_snapshot(key, env.root, clean)
    raw = env.request if shape == 'Request' else dict(asdict(env.request), driver='codex')
    before = rejected_twice(env, monkeypatch, lambda: env.claims.offer(key, env.node, raw, inputs))
    assert before['counts']['remote_offers'] == 0 and before['counts']['remote_claim_requests'] == 0
    assert before['counts']['remote_input_snapshots'] == int(pinned)
    assert env.claims.get(key) is None
    assert env.journal.runs()[0]['status'] == 'IN_FLIGHT' and env.journal.runs()[0]['receipt'] is None


@pytest.mark.parametrize('path', REDACTING_PATHS)
@pytest.mark.parametrize('location', ['input', 'output'])
def test_existing_binding_guard_retains_its_transaction_boundary_without_io(env, monkeypatch, path, location):
    inputs = manifest(path, location)
    put_inputs(env, inputs)
    key = reserve(env)
    before = rejected_twice(env, monkeypatch, lambda: env.claims.bind_input_snapshot(key, env.root, inputs), binding=True)
    assert before['counts']['remote_input_snapshots'] == 0 and before['counts']['remote_offers'] == 0


@pytest.mark.parametrize('path', ORDINARY_PATHS)
@pytest.mark.parametrize('pinned', [False, True], ids=['legacy-unbound', 'snapshot-bound'])
def test_ordinary_paths_keep_exact_projection_and_cached_identity(env, path, pinned):
    inputs = manifest(path, 'input')
    inputs['output_paths'] = ['outputs/' + path]
    put_inputs(env, inputs)
    key = reserve(env)
    if pinned:
        saved = env.claims.bind_input_snapshot(key, env.root, inputs)
        assert saved == {'mission_id': env.registry.mission_id, 'run_key': key, 'root': str(env.root),
                         'manifest': inputs, 'manifest_hash': digest(inputs),
                         'reservation_fingerprint': digest(asdict(env.request))}
    offered = env.claims.offer(key, env.node, env.request, inputs)
    assert offered['input_manifest'] == inputs and offered['request'] == asdict(env.request)
    assert set(offered) == {'mission_id', 'run_key', 'node_id', 'task_id', 'driver', 'request', 'prompt_hash',
                            'input_manifest', 'input_manifest_hash', 'fingerprint', 'created_at', 'status',
                            'claim_id', 'epoch', 'lease_expires_at', 'receipt', 'manifest', 'uploads'}
    cached = env.claims.claim(env.node, 'full-redaction-clean-claim')
    assert cached['status'] == 'CLAIMED' and cached['claim']['epoch'] == 1
    assert set(cached) == {'mission_id', 'node_id', 'request_id', 'status', 'claim'}
    assert redact(cached) == cached
    before = state(env)
    assert env.claims.offer(key, env.node, env.request, inputs) == cached['claim']
    if pinned:
        assert env.claims.bind_input_snapshot(key, env.root, inputs) == saved
        assert env.claims.read_input(env.node, cached['claim']['claim_id'], 1, path) == DATA
    env.clock.value += 5
    assert env.claims.claim(env.node, 'full-redaction-clean-claim') == cached
    assert env.claims.status(env.node, cached['claim']['claim_id'], 1) == cached['claim']
    after = state(env)
    retain(env, 'ordinary-cached-readback.json', {'before': before, 'after': after, 'claim': cached})
    assert before == after
    assert env.journal.store.verify_event_chain()['valid']


@pytest.mark.parametrize('text', ['sk-abcdefghijklmnop', 'Bearer fixture'])
@pytest.mark.parametrize('shape', ['Request', 'dict'])
def test_request_redaction_admission_remains_fixed_before_transaction(env, monkeypatch, text, shape):
    request = replace(env.request, prompt='Context ' + text)
    key = reserve(env, request=request)
    raw = request if shape == 'Request' else dict(asdict(request), driver='codex')
    rejected_twice(env, monkeypatch, lambda: env.claims.offer(key, env.node, raw, manifest()))


@pytest.mark.parametrize('pinned', [False, True])
@pytest.mark.parametrize('claimed', [False, True], ids=['offered', 'claimed'])
def test_rejected_conflicting_manifest_never_changes_existing_clean_identity(env, monkeypatch, pinned, claimed):
    inputs = manifest()
    put_inputs(env, inputs)
    key = reserve(env)
    if pinned:
        env.claims.bind_input_snapshot(key, env.root, inputs)
    current = env.claims.offer(key, env.node, env.request, inputs)
    cached = None
    if claimed:
        cached = env.claims.claim(env.node, 'full-redaction-existing-claim')
        current = cached['claim']
    env.clock.value += 5
    bad = manifest(REDACTING_PATHS[0], 'output')
    rejected_twice(env, monkeypatch, lambda: env.claims.offer(key, env.node, env.request, bad))
    before = state(env)
    assert env.claims.get(key) == current
    assert env.claims.offer(key, env.node, env.request, inputs) == current
    if cached is not None:
        assert env.claims.claim(env.node, 'full-redaction-existing-claim') == cached
    assert state(env) == before


@pytest.mark.parametrize('key', ['run-sk-abcdefghijklmnop', 'run Bearer fixture'])
def test_full_record_run_key_redaction_rejected_before_publication(env, monkeypatch, key):
    inputs = manifest()
    put_inputs(env, inputs)
    reserve(env, key=key)
    rejected_twice(env, monkeypatch, lambda: env.claims.offer(key, env.node, env.request, inputs))


def test_rejected_legacy_manifest_then_restart_clean_claim_keeps_core_truth(env, monkeypatch):
    bad = manifest(REDACTING_PATHS[0], 'input')
    put_inputs(env, bad)
    key = reserve(env)
    rejected_twice(env, monkeypatch, lambda: env.claims.offer(key, env.node, env.request, bad))
    reopened = Journal(AutonomyStore(env.journal.store.path))
    registry = NodeRegistry(reopened)
    claims = NodeClaims(reopened, registry, env.claims.artifact_root, clock=env.clock)
    env.journal, env.registry, env.claims = reopened, registry, claims
    assert claims.get(key) is None
    clean = manifest()
    put_inputs(env, clean)
    clean_key = reserve(env, key='full-redaction-after-restart')
    claims.bind_input_snapshot(clean_key, env.root, clean)
    offered = claims.offer(clean_key, env.node, env.request, clean)
    assert offered['status'] == 'OFFERED' and offered['epoch'] == 0
    cached = claims.claim(env.node, 'full-redaction-restarted-claim')
    assert cached['status'] == 'CLAIMED' and cached['claim']['run_key'] == clean_key
    assert redact(cached) == cached
    assert all(run['status'] == 'IN_FLIGHT' and run['receipt'] is None for run in reopened.runs())
    assert reopened.store.verify_event_chain()['valid']
