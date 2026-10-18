"""Frozen credential admission microfix, never native/HTTP acceptance.

Gateway's exact case-insensitive Node + whitespace + 64hex token boundary is
checked statically, without importing Gateway. Reject before any Claims write
transaction or input IO. All fixture credentials are fixed synthetic strings;
no environment credentials, transport model, socket or native process is used.
Independent fixtures/public APIs, no replacement interfaces or oracle aliases.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
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
from sisyfus.workers.lead_mission import LeadMission
import sisyfus.workers.node_claims as claims_module
from sisyfus.workers.node_claims import NodeClaims
from sisyfus.workers.node_registry import NodeRegistry
from sisyfus.workers.protocol import Receipt, Request, digest

TOKEN = '1a2b' * 16
PATTERN = r'(?i)\bNode\s+[0-9a-f]{64}(?![A-Za-z0-9._~-])'
MATCHES = ['Node ' + TOKEN, 'nOdE\n' + TOKEN, 'NODE\t' + TOKEN.upper(),
           'node\r\n' + TOKEN, 'node  ' + TOKEN + '!', 'Node\u2003' + TOKEN + '/end']
NONMATCHES = [TOKEN, 'xNode ' + TOKEN, '_Node ' + TOKEN, 'Node ' + TOKEN + '0',
              'Node ' + TOKEN + 'x', 'Node ' + TOKEN + '.', 'Node ' + TOKEN + '_',
              'Node ' + TOKEN + '~', 'Node ' + TOKEN + '-', 'Node ' + TOKEN[:63]]


def forbidden(*args, **kwargs):
    pytest.fail('credential admission reached native/network execution')


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(LeadMission, 'run', forbidden)
    for cls in (CodexDriver, ClaudeCodeDriver):
        monkeypatch.setattr(cls, 'run', forbidden)
        monkeypatch.setattr(cls, 'probe', forbidden)


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
    opp, _ = journal.store.submit_opportunity(OpportunitySignal('credential-fixture', 'input', 'fixed task'), now=clock.utc())
    journal.store.admit_opportunity(opp['id'], now=clock.utc())
    continuation = journal.store.claim_due_continuation('controller', lease_seconds=60, now=clock.utc())
    registry = NodeRegistry(journal)
    node = registry.enroll('credential-enroll-0001', 'synthetic fixture', ['codex'], ['gpt-6.1-sol'])['node_id']
    cwd, root = tmp_path / 'workspace', tmp_path / 'snapshot'
    cwd.mkdir()
    root.mkdir()
    claims = NodeClaims(journal, registry, tmp_path / 'retained-artifacts', clock=clock)
    proof = tmp_path_factory.mktemp('credential-admission-evidence')
    return SimpleNamespace(journal=journal, registry=registry, node=node, claims=claims,
                           cwd=cwd, root=root, tree=tmp_path, clock=clock, continuation=continuation,
                           request=Request('build', 'Fixed task.', str(cwd), 'gpt-6.1-sol', mode='workspace-write'),
                           proof=proof)


def reserve(env, request=None, key='admission-run'):
    request = env.request if request is None else request
    env.journal.reserve(key, request.task_id, digest(asdict(request)),
                        continuation_id=env.continuation['id'], lease_token=env.continuation['lease_token'])
    return key


def manifest(path='result.txt', input_path=None):
    files = [] if input_path is None else [{'path': input_path, 'sha256': hashlib.sha256(b'input').hexdigest(), 'size': 5}]
    return {'files': files, 'output_paths': [path]}


def put(env, path):
    for root in (env.cwd, env.root):
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open('xb') as stream:
            stream.write(b'input')


def snapshot(env):
    """Actual readonly logical evidence, separate from the held WAL tree task."""
    db = sqlite3.connect(env.journal.store.path.as_uri() + '?mode=ro', uri=True, isolation_level=None)
    try:
        db.execute('BEGIN')
        logical = '\n'.join(db.iterdump())
        counts = {table: db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                  for table in ('remote_offers', 'remote_input_snapshots', 'remote_claim_requests', 'events')}
        core = db.execute('SELECT key,status,receipt_json FROM native_worker_runs ORDER BY key').fetchall()
        db.execute('COMMIT')
    finally:
        db.close()
    entries = {}
    for path in sorted(env.tree.rglob('*')):
        if path.name.startswith('autonomy.sqlite3'):
            continue  # SQLite auxiliary authority is a separate SOURCE HOLD.
        info = path.lstat()
        entries[str(path.relative_to(env.tree))] = {
            'ino': info.st_ino, 'mode': info.st_mode,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None}
    return {'logical': logical, 'counts': counts, 'core': core, 'entries': entries}


def rejected(env, monkeypatch, operation):
    before = snapshot(env)
    original = env.journal.store._transaction
    transactions, io = [], []

    @contextmanager
    def observed(*, immediate=True):
        transactions.append(immediate)
        with original(immediate=immediate) as db:
            yield db

    def observe_io(name, original):
        def wrapped(*args, **kwargs):
            io.append(name)
            return original(*args, **kwargs)
        return wrapped

    result, error = None, None
    with monkeypatch.context() as guard:
        guard.setattr(env.journal.store, '_transaction', observed)
        for name in ('_snapshot_read', '_verify_file', '_directory'):
            guard.setattr(claims_module, name, observe_io(name, getattr(claims_module, name)))
        try:
            result = operation()
        except Exception as exc:
            error = exc
    after = snapshot(env)
    with (env.proof / 'admission.json').open('x') as stream:
        json.dump({'before': before, 'after': after, 'transactions': transactions, 'io': io,
                   'error_type': type(error).__name__, 'result': result}, stream, sort_keys=True)
    print(json.dumps({'retained_evidence': str(env.proof), 'error_type': type(error).__name__,
                      'transactions': transactions, 'io': io, 'before': before['counts'],
                      'after': after['counts']}, sort_keys=True))
    assert isinstance(error, ValueError), 'credential admission must reject before publication/binding'
    assert TOKEN not in str(error).lower() and not re.search(PATTERN, str(error))
    assert transactions == [] and io == [], 'rejection reached a Claims transaction or package IO'
    assert before == after, 'credential rejection changed canonical/transport/path/lease/event state'
    assert env.journal.store.verify_event_chain()['valid']


def test_static_gateway_pattern_is_exact_without_importing_gateway():
    path = Path(claims_module.__file__).with_name('node_gateway.py')
    tree = ast.parse(path.read_text())
    matches = [node for node in tree.body if isinstance(node, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == '_NODE_CREDENTIAL' for t in node.targets)]
    assert len(matches) == 1
    assert ast.literal_eval(matches[0].value.args[0]) == PATTERN
    assert all(re.search(PATTERN, text) for text in MATCHES)
    assert not any(re.search(PATTERN, text) for text in NONMATCHES)


@pytest.mark.parametrize('text', MATCHES)
@pytest.mark.parametrize('shape', ['Request', 'dict'])
def test_prompt_credential_rejects_before_offer_commit(env, monkeypatch, text, shape):
    req = replace(env.request, prompt='Context\n' + text + '\nEnd')
    key = reserve(env, req)
    raw = req if shape == 'Request' else dict(asdict(req), driver='codex')
    rejected(env, monkeypatch, lambda: env.claims.offer(key, env.node, raw, manifest()))


@pytest.mark.parametrize('field', ['task_id', 'cwd'])
def test_other_request_text_fields_are_checked_before_offer(env, monkeypatch, field):
    value = 'NoDe ' + TOKEN + '!'
    if field == 'cwd':
        directory = env.tree / value
        directory.mkdir()
        value = str(directory)
    req = replace(env.request, **{field: value})
    key = reserve(env, req)
    rejected(env, monkeypatch, lambda: env.claims.offer(key, env.node, req, manifest()))


@pytest.mark.parametrize('operation', ['offer', 'bind'])
@pytest.mark.parametrize('location', ['input_path', 'output_path'])
@pytest.mark.parametrize('text', ['Node ' + TOKEN, 'nOdE\u00a0' + TOKEN.upper()])
def test_manifest_path_text_credential_rejects_before_package_io_or_persist(env, monkeypatch, operation, location, text):
    path = 'package/' + text + '!/data.txt'
    inputs = manifest(path=path) if location == 'output_path' else manifest(input_path=path)
    if location == 'input_path':
        put(env, path)
    key = reserve(env)
    invoke = (lambda: env.claims.offer(key, env.node, env.request, inputs)) if operation == 'offer' else (
        lambda: env.claims.bind_input_snapshot(key, env.root, inputs))
    rejected(env, monkeypatch, invoke)


@pytest.mark.parametrize('shape', ['str', 'Path'])
def test_controller_snapshot_root_text_is_not_a_credential_echo(env, monkeypatch, shape):
    root = env.tree / ('prepared Node ' + TOKEN + '!')
    root.mkdir()
    key = reserve(env)
    rejected(env, monkeypatch, lambda: env.claims.bind_input_snapshot(key, root if shape == 'Path' else str(root), manifest()))


@pytest.mark.parametrize('operation', ['offer', 'bind'])
def test_run_key_text_cannot_publish_a_transport_credential(env, monkeypatch, operation):
    key = reserve(env, key='run Node ' + TOKEN + '!')
    invoke = (lambda: env.claims.offer(key, env.node, env.request, manifest())) if operation == 'offer' else (
        lambda: env.claims.bind_input_snapshot(key, env.root, manifest()))
    rejected(env, monkeypatch, invoke)


@pytest.mark.parametrize('text', NONMATCHES)
def test_exact_boundary_nonmatches_keep_public_pin_and_cached_claim_shape(env, text):
    req = replace(env.request, prompt='Fixed ' + text)
    key = reserve(env, req)
    pinned = env.claims.bind_input_snapshot(key, env.root, manifest())
    offered = env.claims.offer(key, env.node, req, manifest())
    assert pinned == {'mission_id': env.registry.mission_id, 'run_key': key, 'root': str(env.root),
                      'manifest': manifest(), 'manifest_hash': digest(manifest()),
                      'reservation_fingerprint': digest(asdict(req))}
    assert offered['request'] == asdict(req) and offered['input_manifest'] == manifest()
    claimed = env.claims.claim(env.node, 'admission-clean-claim')
    assert set(claimed) == {'mission_id', 'node_id', 'request_id', 'status', 'claim'}
    assert claimed['status'] == 'CLAIMED' and claimed['claim']['epoch'] == 1
    before = snapshot(env)
    assert env.claims.bind_input_snapshot(key, env.root, manifest()) == pinned
    assert env.claims.offer(key, env.node, req, manifest()) == claimed['claim']
    assert env.claims.claim(env.node, 'admission-clean-claim') == claimed
    assert snapshot(env) == before


@pytest.mark.parametrize('operation', ['offer', 'bind'])
def test_credential_rejection_preserves_existing_identity_and_readonly_replay(env, monkeypatch, operation):
    key = reserve(env)
    pin = env.claims.bind_input_snapshot(key, env.root, manifest())
    env.claims.offer(key, env.node, env.request, manifest())
    cached = env.claims.claim(env.node, 'admission-existing-claim')
    bad = replace(env.request, prompt='node\n' + TOKEN)
    invoke = (lambda: env.claims.offer(key, env.node, bad, manifest())) if operation == 'offer' else (
        lambda: env.claims.bind_input_snapshot(key, env.root, manifest(path='Node ' + TOKEN + '!')))
    rejected(env, monkeypatch, invoke)
    assert env.claims.bind_input_snapshot(key, env.root, manifest()) == pin
    assert env.claims.claim(env.node, 'admission-existing-claim') == cached


def test_rejected_prompt_then_restart_clean_claim_does_not_poison_shared_unknown_admission(env, monkeypatch):
    bad = replace(env.request, prompt='node\n' + TOKEN)
    key = reserve(env, bad)
    rejected(env, monkeypatch, lambda: env.claims.offer(key, env.node, bad, manifest()))
    reopened = Journal(AutonomyStore(env.journal.store.path))
    registry = NodeRegistry(reopened)
    claims = NodeClaims(reopened, registry, env.claims.artifact_root, clock=env.clock)
    env.journal, env.registry, env.claims = reopened, registry, claims
    assert claims.get(key) is None
    clean_key = reserve(env, key='clean-after-restart')
    offered = claims.offer(clean_key, env.node, env.request, manifest())
    assert offered['status'] == 'OFFERED' and offered['epoch'] == 0
    response = claims.claim(env.node, 'admission-after-restart')
    assert response['status'] == 'CLAIMED' and response['claim']['run_key'] == clean_key
    terminal = claims.receipt(env.node, response['claim']['claim_id'], 1, Receipt('COMPLETED'), [])
    assert terminal['status'] == 'RECEIPTED'
    assert all(row['status'] == 'IN_FLIGHT' and row['receipt'] is None for row in reopened.runs())
    assert reopened.store.verify_event_chain()['valid']
