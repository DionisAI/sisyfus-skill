"""Frozen N1 staging regressions; no native CLI, network or execution approval.

sync returns {mission_id, run_key, node_id, claim_id, epoch, last_seq,
lease_expires_at}. last_seq is the durable transport high-water mark, not a
native acceptance field. Event limits are normalized UTF-8 bytes: 64_000 per
record, 1_000_000 per list, 100 records. All artifacts are retained by runner.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json

import pytest

from sisyfus.autonomy.models import OpportunitySignal, canonical_json
from sisyfus.autonomy.policy import IdempotencyConflictError, LeaseLost
from sisyfus.autonomy.store import AutonomyStore
import sisyfus.workers.journal as journal_module
from sisyfus.workers.journal import Journal
from sisyfus.workers.lead_journal import LeadJournal
from sisyfus.workers.mission_inbox import MissionInbox
from sisyfus.workers.node_claims import NodeClaims
from sisyfus.workers.node_registry import NodeRegistry
from sisyfus.workers.protocol import Receipt, Request, digest, redact


class Clock:
    def __init__(self): self.value = 1000.0
    def __call__(self): return self.value
    def advance(self, seconds): self.value += seconds
    def utc(self):
        return datetime.fromtimestamp(self.value, timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


@dataclass
class Fixture:
    journal: Journal
    registry: NodeRegistry
    claims: NodeClaims
    node: str
    foreign: str
    clock: Clock
    claim: dict
    continuation: dict
    workspace: str


@pytest.fixture(params=[Journal, LeadJournal], ids=['plain-journal', 'lead-journal'])
def env(tmp_path, monkeypatch, request):
    clock = Clock()
    monkeypatch.setattr(journal_module, 'utc_now', clock.utc)
    journal = request.param(AutonomyStore(tmp_path / 'autonomy.sqlite3'))
    journal.bind({'parallelism': 10, 'max_calls': None, 'objective': 'fixed N1 slice',
                  'acceptance_hash': 'frozen', 'checks': {'fixed': {'sha': 'unchanged'}},
                  'tasks': [{'id': 'build', 'driver': 'codex'}]})
    opportunity, _ = journal.store.submit_opportunity(
        OpportunitySignal('N1-fixture', 'fixed continuation', 'fixed task'), now=clock.utc())
    journal.store.admit_opportunity(opportunity['id'], now=clock.utc())
    continuation = journal.store.claim_due_continuation('fixture-controller', lease_seconds=60, now=clock.utc())
    registry = NodeRegistry(journal)
    node = registry.enroll('enroll_sync_0001', 'sync node', ['codex'], ['gpt-6.1-sol'])['node_id']
    foreign = registry.enroll('enroll_sync_0002', 'foreign node', ['codex'], ['gpt-6.1-sol'])['node_id']
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    native = Request('build', 'Fixed N1 task.', str(workspace), 'gpt-6.1-sol', mode='workspace-write')
    journal.reserve('run-core', 'build', digest(asdict(native)), continuation_id=continuation['id'],
                    lease_token=continuation['lease_token'])
    claims = NodeClaims(journal, registry, tmp_path / 'retained-artifacts', clock=clock)
    claims.offer('run-core', node, native, {'files': [], 'output_paths': []})
    claim = claims.claim(node, 'claim_sync_0001')['claim']
    return Fixture(journal, registry, claims, node, foreign, clock, claim, continuation, str(workspace))


def event(seq=1, kind='native_event', data=None):
    return {'seq': seq, 'kind': kind, 'data': {'method': 'item/completed', 'params': {}} if data is None else data}


def sync(env, events, **changes):
    args = {'node_id': env.node, 'claim_id': env.claim['claim_id'], 'epoch': env.claim['epoch'], 'events': events}
    return env.claims.sync(**(args | changes))


def dump(env):
    with env.journal.store._transaction(immediate=False) as db:
        return '\n'.join(db.iterdump())


def unchanged(env, before):
    assert dump(env) == before
    assert env.journal.store.verify_event_chain()['valid']


def projection(env, last_seq, expiry):
    return {'mission_id': env.registry.mission_id, 'run_key': env.claim['run_key'], 'node_id': env.node,
            'claim_id': env.claim['claim_id'], 'epoch': env.claim['epoch'],
            'last_seq': last_seq, 'lease_expires_at': expiry}


def reboot(env):
    journal = type(env.journal)(AutonomyStore(env.journal.store.path))
    registry = NodeRegistry(journal)
    env.claims = NodeClaims(journal, registry, env.claims.artifact_root, clock=env.clock)
    env.journal, env.registry = journal, registry


def inbox_run(env):
    inbox = MissionInbox(env.journal)
    entry = inbox.submit('固定补充数据，不改变验收。', 'context_sync_0001', task_id='build',
                         snapshot={'phase': 'IMPLEMENTING', 'nodes': [{'id': 'build'}]}, controller={'running': True})
    base = 'Fixed worker prompt.\n' + canonical_json({'acceptance': 'frozen'})
    env.journal.reserve('run-context', 'build', digest(base), on_reserved=lambda db:
                        inbox.bind(db, 'run-context', role='worker', task_id='build', prompt=base))
    binding = inbox.for_run('run-context')
    native = Request('build', binding['prompt'], env.workspace, 'gpt-6.1-sol', mode='workspace-write')
    env.claims.offer('run-context', env.node, native, {'files': [], 'output_paths': []})
    env.claim = env.claims.claim(env.node, 'claim_sync_context')['claim']
    env.journal.after_event = inbox.observe_native_in
    assert inbox.messages()['messages'][0]['status'] == 'RECEIVED'
    return inbox, entry, binding


def test_event_in_joins_caller_transaction_without_nested_write(env, monkeypatch):
    seen = []
    env.journal.after_event = lambda db, key, kind, data: seen.append((db, key, kind, data))
    before = dump(env)
    with pytest.raises(RuntimeError, match='outer rollback'):
        with env.journal.store._transaction() as db:
            def nested(**_): raise AssertionError('nested transaction')
            with monkeypatch.context() as patch:
                patch.setattr(env.journal.store, '_transaction', nested)
                assert env.journal.event_in(db, 'run-core', 'session_bound', {'session_id': 'session'}) is None
                assert seen == [(db, 'run-core', 'session_bound', {'session_id': 'session'})]
            raise RuntimeError('outer rollback')
    unchanged(env, before)


def test_event_wrapper_is_one_transaction_and_callback_error_rolls_back_ack(env, monkeypatch):
    command = env.journal.command('run-core', 'interrupt')
    env.journal.controls('run-core')
    before = dump(env)
    original = env.journal.store._transaction
    transactions = []
    @contextmanager
    def tracked(*, immediate=True):
        transactions.append(immediate)
        with original(immediate=immediate) as db: yield db
    def broken(db, key, kind, data):
        assert db.in_transaction and key == 'run-core' and kind == 'control_ack'
        assert db.execute('SELECT status FROM native_worker_commands WHERE id=?', (command,)).fetchone()[0] == 'SENT'
        assert db.execute('SELECT event_type FROM events ORDER BY seq DESC LIMIT 1').fetchone()[0] == 'WORKER_CONTROL_ACK'
        db.execute("INSERT INTO metadata VALUES('n1-callback','pending')")
        raise ValueError('fixture callback failure')
    env.journal.after_event = broken
    with monkeypatch.context() as patch:
        patch.setattr(env.journal.store, '_transaction', tracked)
        with pytest.raises(ValueError, match='fixture callback failure'):
            env.journal.event('run-core', 'control_ack', {'command_id': command, 'accepted': True})
    assert transactions == [True]
    unchanged(env, before)


@pytest.mark.parametrize('hook', [False, True])
def test_reporter_store_only_facade_event_and_event_in_compatibility(env, hook):
    # Same store-only TransactionView shape as reader ReportPipeline._journal_in.
    with env.journal.store._transaction() as db:
        original_store = env.journal.store
        class TransactionView:
            @contextmanager
            def _transaction(self, *, immediate=True): yield db
            def _append_event(self, connection, **kwargs):
                return original_store._append_event(connection, **kwargs)
        facade = object.__new__(Journal)
        facade.store = TransactionView()
        seen = []
        if hook:
            facade.after_event = lambda connection, key, kind, data: seen.append((connection, kind))
        facade.event('run-core', 'process_started', {'pid': 7, 'driver': 'codex'})
        facade.event_in(db, 'run-core', 'session_bound', {'session_id': 'session'})
        assert seen == ([(db, 'process_started'), (db, 'session_bound')] if hook else [])
    assert env.journal.store.verify_event_chain()['valid']


@pytest.mark.parametrize('loss', ['missing', 'terminal', 'token', 'expiry'])
def test_event_in_retains_original_core_and_continuation_fences(env, loss):
    key = 'run-core'
    if loss == 'missing': key = 'no-reservation'
    elif loss == 'terminal': env.journal.complete(key, {'status': 'ERROR'})
    else:
        with env.journal.store._transaction() as db:
            if loss == 'token': db.execute("UPDATE continuations SET lease_token='other-owner' WHERE id=?", (env.continuation['id'],))
            else: db.execute('UPDATE continuations SET lease_expires_at=? WHERE id=?', (env.clock.utc(), env.continuation['id']))
    before = dump(env)
    with pytest.raises(LeaseLost):
        with env.journal.store._transaction() as db:
            env.journal.event_in(db, key, 'turn_bound', {'turn_id': 'turn'})
    unchanged(env, before)


def test_sync_retry_prefix_append_restart_and_empty_are_read_only(env):
    batch = [event(1, 'process_started', {'pid': 7, 'driver': 'codex'}),
             event(2, 'session_bound', {'session_id': 'session'})]
    seen = []
    env.journal.after_event = lambda db, key, kind, data: seen.append((key, kind, data))
    env.clock.advance(2)
    result = sync(env, batch)
    assert result == projection(env, 2, 1032)
    assert seen == [('run-core', e['kind'], e['data']) for e in batch]
    env.clock.advance(1)
    before = dump(env)
    assert sync(env, [{'data': e['data'], 'kind': e['kind'], 'seq': e['seq']} for e in batch]) == result
    assert sync(env, []) == result
    unchanged(env, before)
    assert len(seen) == 2
    turn = event(3, 'turn_bound', {'turn_id': 'turn', 'session_id': 'session'})
    assert sync(env, [batch[1], turn]) == projection(env, 3, 1033)
    assert seen[-1] == ('run-core', 'turn_bound', turn['data']) and len(seen) == 3
    reboot(env)
    before = dump(env)
    assert sync(env, [*batch, turn]) == projection(env, 3, 1033)
    assert sync(env, []) == projection(env, 3, 1033)
    unchanged(env, before)


def test_sync_one_writer_transaction_and_ordered_callback_with_control_ack(env, monkeypatch):
    command = env.journal.command('run-core', 'interrupt')
    env.journal.controls('run-core')
    batch = [event(1), event(2, 'control_ack', {'command_id': command, 'accepted': True})]
    original = env.journal.store._transaction
    connections, seen = [], []
    @contextmanager
    def single(*, immediate=True):
        assert not connections, 'nested store transaction'
        with original(immediate=immediate) as db:
            connections.append(db)
            yield db
    def observe(db, key, kind, data):
        assert db is connections[0] and db.in_transaction and key == 'run-core'
        assert db.execute('SELECT event_type FROM events ORDER BY seq DESC LIMIT 1').fetchone()[0] == 'WORKER_' + kind.upper()
        if kind == 'control_ack':
            assert db.execute('SELECT status FROM native_worker_commands WHERE id=?', (command,)).fetchone()[0] == 'SENT'
        seen.append((kind, data))
    env.journal.after_event = observe
    with monkeypatch.context() as patch:
        patch.setattr(env.journal.store, '_transaction', single)
        assert sync(env, batch) == projection(env, 2, 1030)
    assert len(connections) == 1 and seen == [(e['kind'], e['data']) for e in batch]
    with original(immediate=False) as db:
        assert db.execute('SELECT status FROM native_worker_commands WHERE id=?', (command,)).fetchone()[0] == 'ACK'
    assert env.journal.store.verify_event_chain()['valid']


@pytest.mark.parametrize('accepted', [False, True])
def test_sync_ack_is_existing_journal_command_behavior_not_operator_authority(env, accepted):
    command = env.journal.command('run-core', 'interrupt')
    env.journal.controls('run-core')
    sync(env, [event(1, 'control_ack', {'command_id': command, 'accepted': accepted})])
    with env.journal.store._transaction(immediate=False) as db:
        assert db.execute('SELECT status FROM native_worker_commands WHERE id=?', (command,)).fetchone()[0] == ('ACK' if accepted else 'REJECTED')
    assert env.journal.runs()[0]['status'] == 'IN_FLIGHT'


def test_inbox_native_turn_applies_once_and_remote_receipt_never_settles_core(env):
    inbox, entry, binding = inbox_run(env)
    spec = env.journal.spec()
    batch = [event(1, 'process_started', {'pid': 7, 'driver': 'codex'}),
             event(2, 'session_bound', {'session_id': 'session'})]
    sync(env, batch)
    assert inbox.messages()['messages'][0]['status'] == 'RECEIVED'
    turn = event(3, 'turn_bound', {'session_id': 'session', 'turn_id': 'accepted-turn'})
    sync(env, [*batch, turn])
    row = inbox.messages()['messages'][0]
    assert row['id'] == entry['id'] and row['status'] == 'APPLIED'
    application = row['applications'][0]
    assert application['delivery']['native_boundary'] == 'turn_bound'
    assert application['receipt_status'] is None and 'seq' not in application['delivery']
    assert inbox.for_run(env.claim['run_key']) == binding and env.journal.spec() == spec
    before = dump(env)
    sync(env, [turn])
    unchanged(env, before)
    # Even turn/completed is only native transport data, not completion truth.
    sync(env, [event(4, 'native_event', {'method': 'turn/completed', 'params': {'turn': {'id': 'accepted-turn', 'status': 'completed'}}})])
    result = env.claims.receipt(env.node, env.claim['claim_id'], env.claim['epoch'], Receipt('COMPLETED'), [])
    assert result['status'] == 'RECEIPTED'
    run = next(r for r in env.journal.runs() if r['key'] == env.claim['run_key'])
    assert run['status'] == 'IN_FLIGHT' and run['receipt'] is None and run['verdict'] == 'UNVERIFIED'
    assert inbox.messages()['messages'][0]['applications'][0]['receipt_status'] is None
    events = [e for e in env.journal.events(0, 1000) if e['run_key'] == env.claim['run_key']]
    assert sum(e['type'] == 'WORKER_MISSION_CONTEXT_APPLIED' for e in events) == 1
    assert not any(e['type'] == 'WORKER_RECEIPT' for e in events)
    with env.journal.store._transaction(immediate=False) as db:
        assert db.execute('SELECT count(*) FROM evidence').fetchone()[0] == 0
    assert env.journal.store.verify_event_chain()['valid']


def test_sync_callback_failure_rolls_back_real_inbox_ack_sequence_lease_and_chain(env):
    inbox, _, _ = inbox_run(env)
    command = env.journal.command(env.claim['run_key'], 'interrupt')
    env.journal.controls(env.claim['run_key'])
    batch = [event(1, 'turn_bound', {'session_id': 'session', 'turn_id': 'accepted'}),
             event(2, 'control_ack', {'command_id': command, 'accepted': True})]
    seen = []
    def broken(db, key, kind, data):
        inbox.observe_native_in(db, key, kind, data)
        seen.append(kind)
        if kind == 'control_ack':
            assert db.execute('SELECT delivered_json FROM lead_mission_contexts WHERE run_key=?', (key,)).fetchone()[0]
            raise ValueError('fixture after real inbox application')
    env.journal.after_event = broken
    env.clock.advance(2)
    before = dump(env)
    with pytest.raises(ValueError, match='fixture after real inbox application'): sync(env, batch)
    assert seen == ['turn_bound', 'control_ack']
    unchanged(env, before)
    assert inbox.messages()['messages'][0]['status'] == 'RECEIVED'
    env.journal.after_event = inbox.observe_native_in
    assert sync(env, batch) == projection(env, 2, 1032)
    types = [e['type'] for e in env.journal.events(0, 1000) if e['run_key'] == env.claim['run_key']][-4:]
    assert types == ['WORKER_TURN_BOUND', 'WORKER_MISSION_CONTEXT_APPLIED', 'WORKER_CONTROL_ACK', 'WORKER_NODE_EVENTS_SYNCED']


def test_review_and_other_run_events_do_not_apply_bound_worker_context(env):
    inbox, _, _ = inbox_run(env)
    worker_claim = env.claim
    before = dump(env)
    with pytest.raises(ValueError, match='independent verdicts'):
        with env.journal.store._transaction() as db:
            inbox.bind(db, 'review-fixture', role='review', task_id='build', prompt='Independent review')
    unchanged(env, before)
    env.claim = env.claims.get('run-core')
    sync(env, [event(1, 'turn_bound', {'session_id': 'other-session', 'turn_id': 'other-turn'})])
    assert inbox.messages()['messages'][0]['status'] == 'RECEIVED'
    assert inbox.messages()['messages'][0]['applications'][0]['run_key'] == worker_claim['run_key']
    assert inbox.messages()['messages'][0]['applications'][0]['status'] == 'BOUND'
    # Review reservation remains local and has no supplementary binding.
    env.journal.reserve('review-local', 'review-build', digest('Independent review'))
    env.journal.event('review-local', 'turn_bound', {'session_id': 'review-session', 'turn_id': 'review-turn'})
    assert inbox.for_run('review-local') is None
    assert inbox.messages()['messages'][0]['status'] == 'RECEIVED'


@pytest.mark.parametrize('loss', ['node-clock', 'core-clock', 'revoked-in-callback', 'core-token-in-callback', 'core-status-in-callback', 'bad-clock'])
def test_commit_rechecks_lease_node_and_core_after_callbacks_and_rolls_back(env, loss):
    inbox, _, _ = inbox_run(env)
    # Attach the real continuation to this context run, still within its original lease.
    with env.journal.store._transaction() as db:
        db.execute('UPDATE native_worker_runs SET continuation_id=?,lease_token=? WHERE key=?',
                   (env.continuation['id'], env.continuation['lease_token'], env.claim['run_key']))
        if loss == 'core-clock':
            db.execute('UPDATE continuations SET lease_expires_at=? WHERE id=?',
                       (datetime.fromtimestamp(1005, timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z'), env.continuation['id']))
    before = dump(env)
    seen = []
    def crossing(db, key, kind, data):
        inbox.observe_native_in(db, key, kind, data)
        seen.append(kind)
        if kind == 'native_event':
            if loss == 'node-clock': env.clock.advance(30)
            elif loss == 'core-clock': env.clock.advance(5)
            elif loss == 'revoked-in-callback': db.execute("UPDATE remote_nodes SET status='REVOKED' WHERE node_id=?", (env.node,))
            elif loss == 'core-token-in-callback': db.execute("UPDATE continuations SET lease_token='other-owner' WHERE id=?", (env.continuation['id'],))
            elif loss == 'core-status-in-callback': db.execute("UPDATE native_worker_runs SET status='UNKNOWN' WHERE key=?", (key,))
            else: env.clock.value = float('nan')
    env.journal.after_event = crossing
    error = PermissionError if loss == 'revoked-in-callback' else ValueError if loss == 'bad-clock' else LeaseLost
    with pytest.raises(error):
        sync(env, [event(1, 'turn_bound', {'session_id': 'session', 'turn_id': 'accepted'}), event(2)])
    assert seen == ['turn_bound', 'native_event']
    unchanged(env, before)
    assert inbox.messages()['messages'][0]['status'] == 'RECEIVED'
    if loss in {'node-clock', 'core-clock'}:
        assert any(r['run_key'] == env.claim['run_key'] and r['status'] == 'UNKNOWN' for r in env.claims.expire())
        assert next(r for r in env.journal.runs() if r['key'] == env.claim['run_key'])['status'] == 'IN_FLIGHT'


@pytest.mark.parametrize('batch_kind', ['fresh', 'duplicate', 'empty'])
@pytest.mark.parametrize('loss', ['revoked', 'foreign', 'missing-claim', 'epoch', 'bool-epoch', 'node-expired', 'core-expired', 'core-token', 'core-terminal', 'transport-terminal'])
def test_sync_even_readbacks_require_this_node_epoch_and_both_live_leases(env, loss, batch_kind):
    first = event(1)
    if batch_kind == 'duplicate': sync(env, [first])
    overrides = {}
    if loss == 'revoked': env.registry.revoke(env.node)
    elif loss == 'foreign': overrides['node_id'] = env.foreign
    elif loss == 'missing-claim': overrides['claim_id'] = 'claim_absent'
    elif loss == 'epoch': overrides['epoch'] = 2
    elif loss == 'bool-epoch': overrides['epoch'] = True
    elif loss == 'node-expired': env.clock.advance(30)
    elif loss in {'core-expired', 'core-token'}:
        with env.journal.store._transaction() as db:
            if loss == 'core-expired': db.execute('UPDATE continuations SET lease_expires_at=? WHERE id=?', (env.clock.utc(), env.continuation['id']))
            else: db.execute("UPDATE continuations SET lease_token='other-owner' WHERE id=?", (env.continuation['id'],))
    elif loss == 'core-terminal': env.journal.complete('run-core', {'status': 'UNKNOWN'})
    else: env.claims.receipt(env.node, env.claim['claim_id'], env.claim['epoch'], Receipt('COMPLETED'), [])
    before = dump(env)
    error = PermissionError if loss in {'revoked', 'foreign', 'missing-claim'} else LeaseLost
    with pytest.raises(error): sync(env, [] if batch_kind == 'empty' else [first], **overrides)
    unchanged(env, before)


@pytest.mark.parametrize('changes', [{'node_id': None}, {'claim_id': 5}, {'epoch': None}])
def test_sync_identity_type_errors_are_explicit(env, changes):
    before = dump(env)
    with pytest.raises(ValueError if 'epoch' not in changes else LeaseLost): sync(env, [], **changes)
    unchanged(env, before)


def test_raw_digest_conflict_survives_redaction_and_restart_without_leaking(env):
    raw = {'method': 'item/completed', 'params': {'authorization': 'Bearer FIXTURE_SECRET_ONE',
           'nested': [{'api_key': 'sk-fixture_value_123456', 'text': 'Bearer FIXTURE_TOKEN'}]}}
    seen = []
    env.journal.after_event = lambda db, key, kind, data: seen.append(data)
    sync(env, [event(1, data=raw)])
    assert seen == [redact(raw)]
    persisted = dump(env)
    for secret in ['FIXTURE_SECRET_ONE', 'sk-fixture_value_123456', 'FIXTURE_TOKEN']:
        assert secret not in persisted
    assert digest(event(1, data=raw)) in persisted
    assert raw['params']['authorization'] == 'Bearer FIXTURE_SECRET_ONE'
    reboot(env)
    before = dump(env)
    assert sync(env, [event(1, data=json.loads(canonical_json(raw)))]) == projection(env, 1, 1030)
    altered = json.loads(canonical_json(raw))
    altered['params']['authorization'] = 'Bearer FIXTURE_SECRET_TWO'
    assert redact(altered) == redact(raw)
    with pytest.raises(IdempotencyConflictError) as error:
        sync(env, [event(1, data=altered), event(2)])
    assert 'FIXTURE_SECRET' not in str(error.value)
    unchanged(env, before)


@pytest.mark.parametrize('batch', [[event(2)], [event(1), event(3)], [event(2), event(1)],
                                  [event(1), event(1)], [event(0)], [event(-1)], [event(True)],
                                  [event('1')], [event(1.0)], [event(None)], [event(2**63)]])
def test_sequences_are_positive_bounded_integer_and_contiguous(env, batch):
    before = dump(env)
    with pytest.raises(ValueError): sync(env, batch)
    unchanged(env, before)


def test_stored_prefix_gap_and_kind_conflict_fail_before_callbacks_or_new_writes(env):
    sync(env, [event(1), event(2)])
    seen = []
    env.journal.after_event = lambda *args: seen.append(args)
    before = dump(env)
    with pytest.raises(ValueError): sync(env, [event(4)])
    with pytest.raises(ValueError): sync(env, [event(2), event(4)])
    with pytest.raises(IdempotencyConflictError):
        sync(env, [event(2, 'session_bound', {'session_id': 'different'}), event(3)])
    assert seen == []
    unchanged(env, before)


VALID = [
    ('process_started', {'pid': 7, 'driver': 'codex'}),
    ('model_identity', {'requested_model': 'gpt-6.1-sol', 'actual_model': None, 'telemetry': 'missing'}),
    ('model_identity', {'requested_model': 'gpt-6.1-sol', 'actual_model': 'fixture-attestation', 'telemetry': 'native'}),
    ('session_bound', {'session_id': 'session'}),
    ('turn_bound', {'session_id': 'session', 'turn_id': 'turn'}),
    ('native_event', {'method': 'thread/tokenUsage/updated', 'params': {'tokenUsage': {'totalTokens': 5}}}),
    ('approval_denied', {'method': 'item/commandExecution/requestApproval', 'request_id': 0}),
    ('approval_denied', {'method': 'item/fileChange/requestApproval', 'request_id': 'rpc-request'}),
    ('control_ack', {'command_id': 'command', 'accepted': False}),
    ('control_ack', {'command_id': 'command', 'accepted': True, 'error': None}),
    ('control_ack', {'command_id': 'command', 'accepted': False, 'error': {'code': -32601, 'message': 'unsupported'}}),
]


@pytest.mark.parametrize('kind,data', VALID)
def test_current_codex_emit_shapes_are_accepted_without_receipt_or_verdict(env, kind, data):
    assert sync(env, [event(1, kind, data)]) == projection(env, 1, 1030)
    native = [e for e in env.journal.events(0, 1000) if e['type'] == 'WORKER_' + kind.upper()]
    assert native[-1]['run_key'] == 'run-core' and native[-1]['data'] == redact(data)
    assert env.journal.runs()[0]['status'] == 'IN_FLIGHT'
    assert env.journal.runs()[0]['receipt'] is None and env.journal.runs()[0]['verdict'] == 'UNVERIFIED'


BAD_FIELDS = [
    ('process_started', {}), ('process_started', {'pid': True, 'driver': 'codex'}),
    ('process_started', {'pid': 0, 'driver': 'codex'}), ('process_started', {'pid': '7', 'driver': 'codex'}),
    ('process_started', {'pid': 7, 'driver': 'claude'}),
    ('model_identity', {}), ('model_identity', {'requested_model': [], 'actual_model': None, 'telemetry': 'missing'}),
    ('model_identity', {'requested_model': 'other-model', 'actual_model': None, 'telemetry': 'missing'}),
    ('model_identity', {'requested_model': 'gpt-6.1-sol', 'actual_model': False, 'telemetry': 'missing'}),
    ('model_identity', {'requested_model': 'gpt-6.1-sol', 'actual_model': None, 'telemetry': {}}),
    ('session_bound', {}), ('session_bound', {'session_id': None}), ('session_bound', {'session_id': ''}),
    ('session_bound', {'session_id': 7}), ('turn_bound', {}), ('turn_bound', {'turn_id': 'turn'}),
    ('turn_bound', {'session_id': 'session', 'turn_id': ''}), ('turn_bound', {'session_id': 'session', 'turn_id': '  '}),
    ('turn_bound', {'session_id': '', 'turn_id': 'turn'}), ('turn_bound', {'session_id': 'session', 'turn_id': False}),
    ('turn_bound', {'session_id': 'session', 'turn_id': 'turn', 'accepted': True}),
    ('native_event', {}), ('native_event', {'method': '', 'params': {}}),
    ('native_event', {'method': [], 'params': {}}), ('native_event', {'method': 'item/completed', 'params': []}),
    ('native_event', {'type': 'assistant', 'message': {'model': 'gpt-6.1-sol'}}),
    ('approval_denied', {}), ('approval_denied', {'method': 'approval', 'request_id': True}),
    ('approval_denied', {'method': 'approval', 'request_id': None}), ('approval_denied', {'method': 7, 'request_id': 1}),
    ('control_ack', {}), ('control_ack', {'command_id': 'cmd', 'accepted': 1}),
    ('control_ack', {'command_id': [], 'accepted': True}), ('control_ack', {'command_id': '', 'accepted': True}),
    ('control_ack', {'command_id': 'cmd', 'accepted': False, 'error': 'error'}),
    ('control_ack', {'command_id': 'cmd', 'accepted': True, 'operator': True}),
]


@pytest.mark.parametrize('kind,data', BAD_FIELDS)
def test_kind_specific_core_fields_fail_atomically_before_any_callback(env, kind, data):
    seen = []
    env.journal.after_event = lambda *args: seen.append(args)
    before = dump(env)
    with pytest.raises(ValueError): sync(env, [event(1), event(2, kind, data)])
    assert seen == []
    unchanged(env, before)


@pytest.mark.parametrize('kind', ['receipt', 'verifier', 'operator', 'pause', 'resume', 'mission_context_applied',
                                'control_requested', 'spawn', 'turn_completed', '', None, [], 7])
def test_non_codex_receipt_verifier_operator_kinds_fail_explicitly(env, kind):
    before = dump(env)
    with pytest.raises(ValueError): sync(env, [event(1, kind)])
    unchanged(env, before)


@pytest.mark.parametrize('batch', [None, {}, '[]', (), [None], [{}], [1],
                                  [{'seq': 1, 'kind': 'native_event'}],
                                  [dict(event(), extra='authority')], [dict(event(), data=[])],
                                  [dict(event(), data=None)]])
def test_strict_batch_record_fields_and_containers(env, batch):
    before = dump(env)
    with pytest.raises(ValueError): sync(env, batch)
    unchanged(env, before)


def cyclic():
    value = {}
    value['cycle'] = value
    return value


def deep():
    value = {}
    for _ in range(100): value = {'nested': value}
    return value


@pytest.mark.parametrize('factory', [lambda: float('nan'), lambda: float('inf'), lambda: float('-inf'),
                                    lambda: b'bytes', lambda: (1,), lambda: {1: 'not a string key'},
                                    lambda: {1, 2}, lambda: object(), lambda: complex(1, 2),
                                    lambda: '\ud800', cyclic, deep, lambda: 10**5000])
def test_finite_strict_json_nesting_encoding_and_serialization_errors_are_value_errors(env, factory):
    before = dump(env)
    with pytest.raises(ValueError): sync(env, [event(1, data={'method': 'item/completed', 'params': {'value': factory()}})])
    unchanged(env, before)


def sized(seq, target):
    value = event(seq, data={'method': 'item/completed', 'params': {'padding': ''}})
    amount = target - len(canonical_json(value).encode())
    assert amount >= 0
    value['data']['params']['padding'] = 'x' * amount
    assert len(canonical_json(value).encode()) == target
    return value


@pytest.mark.parametrize('size,valid', [(64_000, True), (64_001, False)])
def test_event_normalized_utf8_size_bound_is_exact(env, size, valid):
    value = sized(1, size)
    if valid: assert sync(env, [value]) == projection(env, 1, 1030)
    else:
        before = dump(env)
        with pytest.raises(ValueError): sync(env, [value])
        unchanged(env, before)


def test_utf8_not_character_count_sets_event_bound(env):
    before = dump(env)
    with pytest.raises(ValueError):
        sync(env, [event(1, data={'method': 'item/completed', 'params': {'text': '中' * 22_000}})])
    unchanged(env, before)


@pytest.mark.parametrize('count,valid', [(100, True), (101, False)])
def test_batch_event_count_bound_is_exact(env, count, valid):
    batch = [event(i) for i in range(1, count + 1)]
    if valid: assert sync(env, batch) == projection(env, count, 1030)
    else:
        before = dump(env)
        with pytest.raises(ValueError): sync(env, batch)
        unchanged(env, before)


@pytest.mark.parametrize('size,valid', [(1_000_000, True), (1_000_001, False)])
def test_whole_batch_utf8_bound_is_exact_even_with_valid_individual_events(env, size, valid):
    batch = [sized(i, 64_000) for i in range(1, 16)]
    batch.append(sized(16, size - 15 * 64_000 - 17))
    assert len(canonical_json(batch).encode()) == size
    if valid: assert sync(env, batch) == projection(env, 16, 1030)
    else:
        before = dump(env)
        with pytest.raises(ValueError): sync(env, batch)
        unchanged(env, before)


def test_concurrent_exact_replay_appends_callbacks_and_chain_only_once(env):
    seen = []
    env.journal.after_event = lambda db, key, kind, data: seen.append(kind)
    batch = [event(1), event(2, 'session_bound', {'session_id': 'session'})]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: sync(env, batch), range(2)))
    assert results == [projection(env, 2, 1030)] * 2
    assert seen == ['native_event', 'session_bound']
    assert sum(e['type'] == 'WORKER_NODE_EVENTS_SYNCED' for e in env.journal.events(0, 1000)) == 1
    assert env.journal.store.verify_event_chain()['valid']


def test_sync_store_only_journal_with_no_optional_hook(env):
    facade = object.__new__(Journal)
    facade.store = env.journal.store
    env.claims.journal = facade
    assert sync(env, [event(1)]) == projection(env, 1, 1030)
    assert env.journal.store.verify_event_chain()['valid']
