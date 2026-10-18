"""Frozen regressions for the two P2s in node-foundation-review-v1.

P2a: late results retain the exact STORED subset and explicitly name PREPARING
paths in the receipt event, without repairing files or settling canonical runs.
P2b: every Receipt field and nested JSON/UTF-8/size boundary yields ValueError
before mutation on malformed input. These are local, retained protocol fixtures,
not native execution, independent-review completion or A7/A8 acceptance.
"""
from dataclasses import asdict, dataclass
import hashlib
import json

import pytest

from sisyfus.autonomy.policy import IdempotencyConflictError, LeaseLost
from sisyfus.autonomy.store import AutonomyStore
from sisyfus.workers.lead_journal import LeadJournal
import sisyfus.workers.node_claims as module
from sisyfus.workers.node_claims import NodeClaims
from sisyfus.workers.node_registry import NodeRegistry
from sisyfus.workers.protocol import Receipt, Request, digest


class Clock:
    def __init__(self): self.value = 1000.0
    def __call__(self): return self.value
    def advance(self, seconds): self.value += seconds


@dataclass
class Fixture:
    journal: LeadJournal
    registry: NodeRegistry
    claims: NodeClaims
    node_id: str
    claim_id: str
    epoch: int
    clock: Clock


@pytest.fixture
def env(tmp_path):
    journal = LeadJournal(AutonomyStore(tmp_path / 'autonomy.sqlite3'))
    journal.bind({'parallelism': 2, 'max_calls': None, 'objective': 'fixed review fixture',
                  'acceptance_hash': 'fixed', 'checks': {'frozen': {'sha': 'unchanged'}}})
    registry = NodeRegistry(journal)
    node_id = registry.enroll('enroll_review_0001', 'review fixture', ['codex'], ['gpt-6.1-sol'])['node_id']
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    request = Request('build', 'Fixed request.', str(workspace), 'gpt-6.1-sol', mode='workspace-write')
    journal.reserve('review-run', request.task_id, digest(asdict(request)))
    clock = Clock()
    claims = NodeClaims(journal, registry, tmp_path / 'retained-artifacts', clock=clock)
    claims.offer('review-run', node_id, request,
                 {'files': [], 'output_paths': ['partial.txt', 'stored.txt', 'second-partial.txt']})
    claim = claims.claim(node_id, 'claim_review_0001')['claim']
    return Fixture(journal, registry, claims, node_id, claim['claim_id'], claim['epoch'], clock)


def metadata(path, data):
    return {'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}


def file_snapshot(path):
    # Reading may update atime; compare identity, permissions, size, mtime, bytes.
    info = path.stat()
    return (info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, path.read_bytes())


def upload(env, path, data):
    return env.claims.upload(env.node_id, env.claim_id, env.epoch, path,
                             hashlib.sha256(data).hexdigest(), data)


def receive(env, receipt, manifest=None):
    return env.claims.receipt(env.node_id, env.claim_id, env.epoch, receipt,
                              [] if manifest is None else manifest)


def interrupt_upload(env, monkeypatch, path='partial.txt', *, lease_loss=False):
    original = module.os.write
    writes = []
    def interrupted(fd, data):
        if lease_loss:
            size = original(fd, data)
            env.clock.advance(30)
            return size
        if writes:
            raise OSError('injected partial-write interruption')
        writes.append(True)
        return original(fd, data[:2])
    monkeypatch.setattr(module.os, 'write', interrupted)
    try:
        with pytest.raises(LeaseLost if lease_loss else OSError):
            upload(env, path, b'partial-content')
    finally:
        monkeypatch.setattr(module.os, 'write', original)
    retained = env.claims.artifact_root / env.claim_id / path
    assert retained.read_bytes() == (b'partial-content' if lease_loss else b'pa')
    assert next(u for u in env.claims.get('review-run')['uploads'] if u['path'] == path)['status'] == 'PREPARING'
    return retained


def fence(env, cause='expired'):
    if cause in {'expired', 'unswept-lease'}:
        env.clock.advance(30)
        if cause == 'expired':
            env.claims.expire()
    elif cause == 'revoked':
        env.registry.revoke(env.node_id)
    elif cause == 'core-lost':
        env.journal.complete('review-run', {'status': 'UNKNOWN', 'error': 'fixture core ownership lost'})
    else:
        raise AssertionError('unknown fixture cause')


def assert_candidate(env, candidate, receipt_status, files, incomplete_paths, core_before):
    assert candidate['status'] == 'RECONCILIATION_CANDIDATE'
    assert candidate['receipt']['status'] == receipt_status
    assert candidate['manifest'] == files
    assert env.journal.runs() == core_before
    receipt_events = [e for e in env.journal.events() if e['type'] == 'WORKER_NODE_RECEIPT']
    assert len(receipt_events) == 1
    assert receipt_events[0]['data']['status'] == 'RECONCILIATION_CANDIDATE'
    assert receipt_events[0]['data']['incomplete_paths'] == incomplete_paths
    assert env.journal.store.verify_event_chain()['valid']
    with env.journal.store._transaction(immediate=False) as db:
        assert db.execute('SELECT count(*) FROM evidence').fetchone()[0] == 0
    assert env.claims.claim(env.node_id, 'claim_review_no_requeue')['status'] == 'NO_WORK'


@pytest.mark.parametrize('status', ['ERROR', 'UNKNOWN'])
@pytest.mark.parametrize('lease_loss', [True, False], ids=['lease-interruption', 'partial-write'])
def test_late_empty_manifest_after_interrupted_upload_is_retained(env, monkeypatch, status, lease_loss):
    retained = interrupt_upload(env, monkeypatch, lease_loss=lease_loss)
    if not lease_loss:
        env.clock.advance(30)
    assert env.claims.expire()[0]['status'] == 'UNKNOWN'
    before_file = file_snapshot(retained)
    core_before = env.journal.runs()
    candidate = receive(env, Receipt(status))
    assert_candidate(env, candidate, status, [], ['partial.txt'], core_before)
    assert core_before[0]['status'] == 'IN_FLIGHT' and core_before[0]['receipt'] is None
    assert file_snapshot(retained) == before_file
    events = env.journal.events()
    assert receive(env, Receipt(status)) == candidate
    assert env.journal.events() == events
    restarted_journal = LeadJournal(AutonomyStore(env.journal.store.path))
    restarted = NodeClaims(restarted_journal, NodeRegistry(restarted_journal), env.claims.artifact_root, clock=env.clock)
    assert restarted.get('review-run') == candidate
    assert restarted.receipt(env.node_id, env.claim_id, env.epoch, Receipt(status), []) == candidate
    assert restarted.journal.store.verify_event_chain()['valid']
    assert file_snapshot(retained) == before_file


@pytest.mark.parametrize('cause', ['expired', 'unswept-lease', 'revoked', 'core-lost'])
@pytest.mark.parametrize('status', ['ERROR', 'UNKNOWN', 'COMPLETED'])
def test_late_mixed_stored_preparing_accepts_exact_stored_subset(env, monkeypatch, cause, status):
    stored = metadata('stored.txt', b'complete-content')
    upload(env, stored['path'], b'complete-content')
    partial = interrupt_upload(env, monkeypatch)
    second = interrupt_upload(env, monkeypatch, path='second-partial.txt')
    before_files = {p.name: file_snapshot(p) for p in [partial, second]}
    fence(env, cause)
    core_before = env.journal.runs()
    original = module._verify_file
    verified = []
    def verify_stored_only(root, item):
        assert item['path'] == 'stored.txt', 'fenced PREPARING file must not be inspected or repaired'
        verified.append(item['path'])
        return original(root, item)
    monkeypatch.setattr(module, '_verify_file', verify_stored_only)
    candidate = receive(env, {'status': status}, [stored])
    # Revoked nodes have no fresh claim privilege; test that separately below.
    if cause == 'revoked':
        assert candidate['status'] == 'RECONCILIATION_CANDIDATE'
        assert candidate['manifest'] == [stored]
        assert candidate['receipt']['status'] == status
        assert env.journal.runs() == core_before
        event = [e for e in env.journal.events() if e['type'] == 'WORKER_NODE_RECEIPT'][0]
        assert event['data']['incomplete_paths'] == ['partial.txt', 'second-partial.txt']
        with pytest.raises(PermissionError): env.claims.claim(env.node_id, 'claim_review_revoked')
    else:
        assert_candidate(env, candidate, status, [stored], ['partial.txt', 'second-partial.txt'], core_before)
    assert verified == ['stored.txt']
    assert {p.name: file_snapshot(p) for p in [partial, second]} == before_files
    assert [u['status'] for u in candidate['uploads']] == ['PREPARING', 'PREPARING', 'STORED']
    with pytest.raises(IdempotencyConflictError):
        receive(env, {'status': 'ERROR', 'output': 'changed receipt'}, [stored])
    assert env.journal.store.verify_event_chain()['valid']


@pytest.mark.parametrize('status', ['COMPLETED', 'ERROR', 'UNKNOWN'])
@pytest.mark.parametrize('listed_preparing', [False, True])
def test_timely_receipts_keep_all_stored_manifest_requirement(env, monkeypatch, status, listed_preparing):
    interrupt_upload(env, monkeypatch)
    before, events = env.claims.get('review-run'), env.journal.events()
    assert before['status'] == 'CLAIMED'
    files = [metadata('partial.txt', b'partial-content')] if listed_preparing else []
    with pytest.raises(ValueError, match='manifest'):
        receive(env, Receipt(status), files)
    assert env.claims.get('review-run') == before
    assert env.journal.events() == events


@pytest.mark.parametrize('bad_manifest', ['missing-stored', 'includes-preparing', 'wrong-hash', 'wrong-size', 'extra-path'])
def test_late_manifest_must_equal_whole_stored_subset(env, monkeypatch, bad_manifest):
    stored = metadata('stored.txt', b'complete')
    upload(env, stored['path'], b'complete')
    interrupt_upload(env, monkeypatch)
    fence(env)
    files = {'missing-stored': [],
             'includes-preparing': [stored, metadata('partial.txt', b'partial-content')],
             'wrong-hash': [stored | {'sha256': '0'*64}],
             'wrong-size': [stored | {'size': stored['size'] + 1}],
             'extra-path': [stored, metadata('extra.txt', b'new')]}[bad_manifest]
    before, events = env.claims.get('review-run'), env.journal.events()
    with pytest.raises(ValueError, match='manifest'):
        receive(env, Receipt('ERROR'), files)
    assert env.claims.get('review-run') == before
    assert env.journal.events() == events


def test_late_stored_bytes_are_reverified_and_partial_file_untouched(env, monkeypatch):
    stored = metadata('stored.txt', b'complete')
    upload(env, stored['path'], b'complete')
    partial = interrupt_upload(env, monkeypatch)
    fence(env)
    stored_file = env.claims.artifact_root / env.claim_id / 'stored.txt'
    with stored_file.open('ab') as handle: handle.write(b'changed')
    before, events = env.claims.get('review-run'), env.journal.events()
    partial_before = file_snapshot(partial)
    with pytest.raises(ValueError, match='hash/size mismatch'):
        receive(env, Receipt('ERROR'), [stored])
    assert env.claims.get('review-run') == before
    assert env.journal.events() == events
    assert file_snapshot(partial) == partial_before


INVALID_FIELDS = [
    (name, value)
    for name in ['status', 'output']
    for value in [None, True, 5, 1.5, [], {}, b'text']
] + [('usage', value) for value in [None, True, 5, 1.5, 'x', [], (), b'json']] + [
    ('exit_code', value) for value in [True, False, 1.5, '0', [], {}, b'0']
] + [
    (name, value)
    for name in ['session_id', 'turn_id', 'error', 'requested_model', 'actual_model']
    for value in [True, 5, 1.5, [], {}, b'text']
]


@pytest.mark.parametrize('field,value', INVALID_FIELDS, ids=[f'{name}-{type(value).__name__}-{i}' for i, (name, value) in enumerate(INVALID_FIELDS)])
@pytest.mark.parametrize('form', ['dict', 'Receipt'])
def test_every_receipt_field_type_errors_are_value_errors_before_mutation(env, field, value, form):
    payload = {'status': 'COMPLETED', field: value}
    supplied = Receipt(**payload) if form == 'Receipt' else payload
    before, events, core = env.claims.get('review-run'), env.journal.events(), env.journal.runs()
    with pytest.raises(ValueError): receive(env, supplied)
    assert env.claims.get('review-run') == before
    assert env.journal.events() == events
    assert env.journal.runs() == core
    assert env.journal.store.verify_event_chain()['valid']


def nested_payload(kind):
    if kind == 'object': return {'nested': object()}
    if kind == 'bytes': return {'nested': b'unsupported'}
    if kind == 'set': return {'nested': {'a', 'b'}}
    if kind == 'mixed-key-types': return {'nested': {'first': 1, 2: 'invalid'}}
    if kind == 'non-string-key': return {'nested': {2: 'invalid'}}
    if kind == 'nan': return {'nested': float('nan')}
    if kind == 'infinity': return {'nested': [float('inf')]}
    if kind == 'negative-infinity': return {'nested': [float('-inf')]}
    if kind == 'cycle':
        data = {}
        data['cycle'] = data
        return data
    if kind == 'excessive-depth':
        data = {}
        for _ in range(1100): data = {'nested': data}
        return data
    raise AssertionError('unknown malformed JSON fixture')


@pytest.mark.parametrize('kind', ['object', 'bytes', 'set', 'mixed-key-types', 'non-string-key',
                                 'nan', 'infinity', 'negative-infinity', 'cycle', 'excessive-depth'])
@pytest.mark.parametrize('form', ['dict', 'Receipt'])
def test_malformed_nested_usage_json_is_value_error_before_mutation(env, kind, form):
    payload = {'status': 'COMPLETED', 'usage': nested_payload(kind)}
    supplied = Receipt(**payload) if form == 'Receipt' else payload
    before, events = env.claims.get('review-run'), env.journal.events()
    with pytest.raises(ValueError): receive(env, supplied)
    assert env.claims.get('review-run') == before
    assert env.journal.events() == events
    assert env.journal.store.verify_event_chain()['valid']


@pytest.mark.parametrize('form', ['dict', 'Receipt'])
@pytest.mark.parametrize('field', ['status', 'output', 'session_id', 'turn_id', 'error', 'requested_model', 'actual_model', 'usage'])
def test_invalid_utf8_receipt_fields_are_value_error_before_mutation(env, form, field):
    payload = {'status': 'COMPLETED', field: {'text': '\ud800'} if field == 'usage' else '\ud800'}
    supplied = Receipt(**payload) if form == 'Receipt' else payload
    before, events = env.claims.get('review-run'), env.journal.events()
    with pytest.raises(ValueError): receive(env, supplied)
    assert env.claims.get('review-run') == before
    assert env.journal.events() == events


@pytest.mark.parametrize('field', ['output', 'usage'])
@pytest.mark.parametrize('form', ['dict', 'Receipt'])
def test_receipt_size_limit_uses_utf8_bytes_before_mutation(env, monkeypatch, field, form):
    monkeypatch.setattr(module, 'MAX_RECEIPT_BYTES', 512)
    payload = {'status': 'COMPLETED', field: {'text': '中'*200} if field == 'usage' else '中'*200}
    supplied = Receipt(**payload) if form == 'Receipt' else payload
    before, events = env.claims.get('review-run'), env.journal.events()
    with pytest.raises(ValueError): receive(env, supplied)
    assert env.claims.get('review-run') == before
    assert env.journal.events() == events


@pytest.mark.parametrize('supplied', [None, [], 'COMPLETED', True, {},
    {'status': 'COMPLETED', 'unknown_field': 1}, {'status': 'PASS'},
    {'status': 'COMPLETED', 'requested_model': 'auto'}])
def test_receipt_shape_and_enum_failures_leave_offer_unchanged(env, supplied):
    before, events = env.claims.get('review-run'), env.journal.events()
    with pytest.raises(ValueError): receive(env, supplied)
    assert env.claims.get('review-run') == before
    assert env.journal.events() == events


@pytest.mark.parametrize('status', ['COMPLETED', 'ERROR', 'INTERRUPTED', 'UNKNOWN'])
@pytest.mark.parametrize('exit_code', [None, 0, -1, 1])
@pytest.mark.parametrize('form', ['dict', 'Receipt'])
def test_valid_receipt_fields_preserve_transport_semantics(env, status, exit_code, form):
    payload = {'status': status, 'output': '中文 result', 'usage': {'counts': [1, 2.5, None, True], 'native': {'label': 'fixture'}},
               'exit_code': exit_code, 'session_id': 'fixture-session', 'turn_id': 'fixture-turn',
               'error': None, 'requested_model': 'gpt-6.1-sol', 'actual_model': None}
    supplied = Receipt(**payload) if form == 'Receipt' else payload
    core = env.journal.runs()
    result = receive(env, supplied)
    assert result['receipt'] == payload
    assert result['status'] == ('UNKNOWN' if status == 'UNKNOWN' else 'RECEIPTED')
    assert result['receipt']['actual_model'] is None
    assert env.journal.runs() == core
    assert core[0]['status'] == 'IN_FLIGHT' and core[0]['receipt'] is None
    assert env.journal.store.verify_event_chain()['valid']


@pytest.mark.parametrize('field', ['session_id', 'turn_id', 'error', 'requested_model', 'actual_model'])
@pytest.mark.parametrize('value', [None, ''])
def test_optional_receipt_text_types_remain_valid_without_model_inference(env, field, value):
    # requested_model has a separate pinned-value constraint after its type check.
    if field == 'requested_model' and value == '':
        with pytest.raises(ValueError): receive(env, {'status': 'COMPLETED', field: value})
    else:
        result = receive(env, {'status': 'COMPLETED', field: value})
        assert result['receipt'][field] == value
        assert result['status'] == 'RECEIPTED'
    assert env.journal.store.verify_event_chain()['valid']
