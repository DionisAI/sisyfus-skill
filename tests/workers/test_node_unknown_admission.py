"""Frozen v2 UNKNOWN shared-spending admission regressions; retained fixtures.

Two controller-reserved offers exist before uncertainty arises. Fresh remote
claims must durably return NO_WORK without releasing B; fresh Journal.reserve
must explicitly reject SAME-store UNKNOWN/RECONCILIATION_CANDIDATE transport.
Cached reads, core IN_FLIGHT truth, pause/stop, legacy stores and clean outcomes
retain their contracts. No native CLI, network, inbox hooks or settlement driver.
"""
from dataclasses import asdict, dataclass

import pytest

from sisyfus.autonomy.policy import IdempotencyConflictError
from sisyfus.autonomy.store import AutonomyStore
from sisyfus.workers.journal import DispatchBlocked, Journal
from sisyfus.workers.lead_journal import LeadJournal
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
    clock: Clock
    claimed_a: dict
    offered_b: dict
    requests: dict
    cached_receipt: dict


@pytest.fixture
def env(tmp_path):
    journal = LeadJournal(AutonomyStore(tmp_path / 'autonomy.sqlite3'))
    journal.bind({'parallelism': 12, 'max_calls': None, 'objective': 'fixed UNKNOWN gate',
                  'acceptance_hash': 'frozen', 'checks': {'fixed': {'sha': 'unchanged'}}})
    registry = NodeRegistry(journal)
    node_id = registry.enroll('enroll_unknown_0001', 'unknown gate fixture', ['codex'], ['gpt-6.1-sol'])['node_id']
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    requests = {key: Request(key, 'Fixed request ' + key, str(workspace), 'gpt-6.1-sol', mode='workspace-write')
                for key in ['offer-a', 'offer-b']}
    for key, request in requests.items():
        journal.reserve(key, request.task_id, digest(asdict(request)))
    journal.reserve('canonical-extra', 'local-task', digest('extra'))
    journal.reserve('cached-local', 'local-task', digest('cached'))
    cached = journal.complete('cached-local', {'status': 'COMPLETED', 'output': 'fixture cached result'})
    clock = Clock()
    claims = NodeClaims(journal, registry, tmp_path / 'retained-artifacts', clock=clock)
    for key, request in requests.items():
        claims.offer(key, node_id, request, {'files': [], 'output_paths': []})
    offered_b = claims.get('offer-b')
    first = claims.claim(node_id, 'claim_unknown_a')
    assert first['claim']['run_key'] == 'offer-a'
    return Fixture(journal, registry, claims, node_id, clock, first, offered_b, requests, cached)


def uncertain(env, cause):
    a = env.claimed_a['claim']
    if cause in {'expired', 'candidate'}:
        env.clock.advance(30)
        assert env.claims.expire()[0]['status'] == 'UNKNOWN'
        if cause == 'candidate':
            saved = env.claims.receipt(env.node_id, a['claim_id'], a['epoch'], Receipt('ERROR'), [])
            assert saved['status'] == 'RECONCILIATION_CANDIDATE'
    elif cause == 'native-unknown':
        saved = env.claims.receipt(env.node_id, a['claim_id'], a['epoch'], Receipt('UNKNOWN'), [])
        assert saved['status'] == 'UNKNOWN'
    elif cause == 'canonical-unknown':
        env.journal.complete('canonical-extra', {'status': 'UNKNOWN', 'error': 'fixture unresolved execution'})
    else:
        raise AssertionError('unknown fixture cause')


def core_snapshot(env):
    with env.journal.store._transaction(immediate=False) as db:
        return [dict(r) for r in db.execute('SELECT * FROM native_worker_runs ORDER BY key')]


def reboot(env):
    journal = LeadJournal(AutonomyStore(env.journal.store.path))
    registry = NodeRegistry(journal)
    claims = NodeClaims(journal, registry, env.claims.artifact_root, clock=env.clock)
    env.journal, env.registry, env.claims = journal, registry, claims


def assert_remote_fenced(env, request_id='claim_unknown_fresh'):
    before = core_snapshot(env)
    result = env.claims.claim(env.node_id, request_id)
    assert result == {'mission_id': env.registry.mission_id, 'node_id': env.node_id,
                      'request_id': request_id, 'status': 'NO_WORK', 'claim': None}
    assert env.claims.get('offer-b') == env.offered_b
    assert core_snapshot(env) == before
    events = env.journal.events()
    assert events[-1]['type'] == 'WORKER_NODE_CLAIM_EMPTY'
    assert env.claims.claim(env.node_id, request_id) == result
    assert env.claims.claim(env.node_id, 'claim_unknown_a') == env.claimed_a
    assert env.journal.events() == events
    assert env.journal.store.verify_event_chain()['valid']
    return result


@pytest.mark.parametrize('cause', ['expired', 'native-unknown', 'candidate', 'canonical-unknown'])
@pytest.mark.parametrize('restart', [False, True], ids=['same-process', 'reboot'])
def test_preexisting_b_offer_stays_offered_while_any_execution_unknown(env, cause, restart):
    uncertain(env, cause)
    if restart: reboot(env)
    blocked = assert_remote_fenced(env)
    assert_remote_fenced(env, 'claim_unknown_second')
    if cause != 'canonical-unknown':
        assert all(r['status'] == 'IN_FLIGHT' and r['receipt_json'] is None
                   for r in core_snapshot(env) if r['key'] in {'offer-a', 'offer-b'})
    reboot(env)
    assert env.claims.claim(env.node_id, 'claim_unknown_fresh') == blocked
    assert env.claims.claim(env.node_id, 'claim_unknown_a') == env.claimed_a
    assert env.claims.get('offer-b') == env.offered_b
    assert env.journal.spec()['acceptance_hash'] == 'frozen'
    assert env.journal.store.verify_event_chain()['valid']


def test_claim_sweeps_due_a_before_shared_admission_even_without_explicit_expire(env):
    env.clock.advance(30)
    assert env.claims.get('offer-a')['status'] == 'CLAIMED'
    result = env.claims.claim(env.node_id, 'claim_unknown_unswept')
    assert result['status'] == 'NO_WORK' and result['claim'] is None
    assert env.claims.get('offer-a')['status'] == 'UNKNOWN'
    assert env.claims.get('offer-b') == env.offered_b
    assert all(r['status'] == 'IN_FLIGHT' and r['receipt_json'] is None
               for r in core_snapshot(env) if r['key'] in {'offer-a', 'offer-b'})
    assert env.claims.claim(env.node_id, 'claim_unknown_a') == env.claimed_a
    assert env.journal.store.verify_event_chain()['valid']


@pytest.mark.parametrize('cause', ['expired', 'native-unknown', 'candidate', 'canonical-unknown'])
@pytest.mark.parametrize('via', ['base', 'lead', 'reboot', 'store-only-facade'])
def test_journal_reserve_blocks_fresh_shared_spending_before_callback(env, cause, via):
    uncertain(env, cause)
    if via == 'reboot': reboot(env)
    journal = env.journal
    if via == 'base': journal = Journal(journal.store)
    if via == 'store-only-facade':
        journal = Journal.__new__(Journal)
        journal.store = env.journal.store
    before, events = core_snapshot(env), env.journal.events()
    callbacks = []
    with pytest.raises(DispatchBlocked, match='shared spending'):
        journal.reserve('fresh-local', 'local-task', digest('new'), on_reserved=lambda db: callbacks.append(True))
    assert callbacks == []
    assert core_snapshot(env) == before
    assert env.journal.events() == events
    assert env.claims.get('offer-b') == env.offered_b
    assert env.journal.store.verify_event_chain()['valid']


@pytest.mark.parametrize('cause', ['expired', 'native-unknown', 'candidate', 'canonical-unknown'])
@pytest.mark.parametrize('restart', [False, True])
def test_cached_receipt_and_reservation_semantics_precede_unknown_gate(env, cause, restart):
    uncertain(env, cause)
    if restart: reboot(env)
    before, events = core_snapshot(env), env.journal.events()
    callbacks = []
    assert env.journal.reserve('cached-local', 'local-task', digest('cached'),
                               on_reserved=lambda db: callbacks.append(True)) == env.cached_receipt
    assert env.journal.complete('cached-local', env.cached_receipt) == env.cached_receipt
    with pytest.raises(IdempotencyConflictError):
        env.journal.reserve('cached-local', 'different-task', digest('cached'))
    with pytest.raises(IdempotencyConflictError):
        env.journal.reserve('cached-local', 'local-task', digest('changed'))
    with pytest.raises(DispatchBlocked, match='no durable receipt'):
        env.journal.reserve('offer-a', 'offer-a', digest(asdict(env.requests['offer-a'])))
    assert env.claims.claim(env.node_id, 'claim_unknown_a') == env.claimed_a
    assert env.claims.offer('offer-b', env.node_id, env.requests['offer-b'],
                            {'files': [], 'output_paths': []}) == env.offered_b
    assert callbacks == []
    assert core_snapshot(env) == before
    assert env.journal.events() == events
    assert env.journal.store.verify_event_chain()['valid']


@pytest.mark.parametrize('cause', ['expired', 'native-unknown', 'candidate', 'canonical-unknown'])
@pytest.mark.parametrize('control', ['pause', 'stop'])
def test_unknown_remains_fenced_after_pause_or_stop_controls_clear(env, cause, control):
    uncertain(env, cause)
    if control == 'pause': env.journal.pause(True)
    else: env.journal.update(lambda s: s.update(stopped=True))
    blocked = assert_remote_fenced(env)
    # Base admission avoids LeadJournal's intentional wait-on-pause behavior.
    with pytest.raises(DispatchBlocked):
        Journal.reserve(env.journal, 'paused-new', 'local-task', digest('paused'))
    if control == 'pause': env.journal.pause(False)
    else: env.journal.update(lambda s: s.update(stopped=False))
    assert env.claims.claim(env.node_id, 'claim_unknown_fresh') == blocked
    assert_remote_fenced(env, 'claim_unknown_after_control')
    with pytest.raises(DispatchBlocked, match='shared spending'):
        env.journal.reserve('after-control-new', 'local-task', digest('after-control'))
    assert env.journal.store.verify_event_chain()['valid']


@pytest.mark.parametrize('status', ['COMPLETED', 'ERROR', 'INTERRUPTED'])
@pytest.mark.parametrize('restart', [False, True])
def test_clean_receipted_transport_allows_b_and_new_native_admission(env, status, restart):
    a = env.claimed_a['claim']
    result = env.claims.receipt(env.node_id, a['claim_id'], a['epoch'], Receipt(status), [])
    assert result['status'] == 'RECEIPTED'
    if restart: reboot(env)
    before = core_snapshot(env)
    claim_b = env.claims.claim(env.node_id, 'claim_clean_b')
    assert claim_b['status'] == 'CLAIMED' and claim_b['claim']['run_key'] == 'offer-b'
    assert env.journal.reserve('fresh-clean', 'local-task', digest('clean')) is None
    assert env.claims.claim(env.node_id, 'claim_unknown_a') == env.claimed_a
    assert [r for r in core_snapshot(env) if r['key'] != 'fresh-clean'] == before
    assert env.journal.store.verify_event_chain()['valid']


@pytest.mark.parametrize('control', ['pause', 'stop'])
def test_clean_pause_stop_caches_no_work_but_fresh_request_claims_after_clear(env, control):
    if control == 'pause': env.journal.pause(True)
    else: env.journal.update(lambda s: s.update(stopped=True))
    blocked = assert_remote_fenced(env)
    if control == 'pause': env.journal.pause(False)
    else: env.journal.update(lambda s: s.update(stopped=False))
    assert env.claims.claim(env.node_id, 'claim_unknown_fresh') == blocked
    fresh = env.claims.claim(env.node_id, 'claim_clean_after_control')
    assert fresh['status'] == 'CLAIMED' and fresh['claim']['run_key'] == 'offer-b'
    assert env.journal.reserve('fresh-clean', 'local-task', digest('clean')) is None
    assert env.journal.store.verify_event_chain()['valid']


@pytest.mark.parametrize('cause', ['expired', 'native-unknown', 'candidate', 'canonical-unknown'])
def test_fence_is_mission_store_scoped_not_global(env, tmp_path, cause):
    uncertain(env, cause)
    other = Journal(AutonomyStore(tmp_path / 'other' / 'autonomy.sqlite3'))
    other.bind({'parallelism': 2, 'max_calls': None})
    assert other.reserve('clean-other', 'other-task', digest('other')) is None
    assert other.runs()[0]['status'] == 'IN_FLIGHT'
    assert other.store.verify_event_chain()['valid']
    with pytest.raises(DispatchBlocked, match='shared spending'):
        env.journal.reserve('blocked-original', 'local-task', digest('original'))


@pytest.mark.parametrize('cause', ['expired', 'native-unknown', 'candidate', 'canonical-unknown'])
def test_unknown_fence_covers_other_nodes_in_the_same_store(env, cause):
    other_node = env.registry.enroll('enroll_unknown_0002', 'second node', ['codex'], ['gpt-6.1-sol'])['node_id']
    request = Request('other-task', 'Other node fixed request', env.requests['offer-a'].cwd,
                      'gpt-6.1-sol', mode='workspace-write')
    env.journal.reserve('other-offer', request.task_id, digest(asdict(request)))
    offered = env.claims.offer('other-offer', other_node, request, {'files': [], 'output_paths': []})
    uncertain(env, cause)
    result = env.claims.claim(other_node, 'claim_unknown_other')
    assert result['status'] == 'NO_WORK' and result['claim'] is None
    assert env.claims.get('other-offer') == offered
    assert env.claims.get('offer-b') == env.offered_b
    assert env.journal.store.verify_event_chain()['valid']


def test_native_unknown_committed_after_expiry_sweep_is_seen_by_claim_transaction(env, monkeypatch):
    original = env.claims.expire
    def newly_unknown():
        result = original()
        env.journal.complete('canonical-extra', {'status': 'UNKNOWN'})
        return result
    monkeypatch.setattr(env.claims, 'expire', newly_unknown)
    result = env.claims.claim(env.node_id, 'claim_unknown_boundary')
    assert result['status'] == 'NO_WORK' and result['claim'] is None
    assert env.claims.get('offer-b') == env.offered_b
    assert env.claims.claim(env.node_id, 'claim_unknown_a') == env.claimed_a
    assert env.journal.store.verify_event_chain()['valid']


def test_legacy_store_without_remote_table_preserves_native_admission(tmp_path):
    journal = Journal(AutonomyStore(tmp_path / 'legacy' / 'autonomy.sqlite3'))
    journal.bind({'parallelism': 4, 'max_calls': None})
    with journal.store._transaction(immediate=False) as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='remote_offers'").fetchone() is None
    assert journal.reserve('legacy-completed', 'task', digest('first')) is None
    receipt = journal.complete('legacy-completed', {'status': 'COMPLETED', 'output': 'legacy cached'})
    assert journal.reserve('legacy-completed', 'task', digest('first')) == receipt
    assert journal.reserve('legacy-unknown', 'task', digest('second')) is None
    journal.complete('legacy-unknown', {'status': 'UNKNOWN'})
    with pytest.raises(DispatchBlocked, match='shared spending'):
        journal.reserve('legacy-new', 'task', digest('third'))
    assert journal.reserve('legacy-completed', 'task', digest('first')) == receipt
    with journal.store._transaction(immediate=False) as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='remote_offers'").fetchone() is None
    assert journal.store.verify_event_chain()['valid']


@pytest.mark.parametrize('cause', ['expired', 'native-unknown', 'candidate', 'canonical-unknown'])
def test_empty_claim_event_failure_rolls_back_blocked_request_only(env, monkeypatch, cause):
    uncertain(env, cause)
    before, events = core_snapshot(env), env.journal.events()
    original = env.journal.store._append_event
    def fail(*args, **kwargs):
        if kwargs['event_type'] == 'WORKER_NODE_CLAIM_EMPTY':
            raise RuntimeError('injected empty-claim event failure')
        return original(*args, **kwargs)
    monkeypatch.setattr(env.journal.store, '_append_event', fail)
    with pytest.raises(RuntimeError, match='event failure'):
        env.claims.claim(env.node_id, 'claim_unknown_rollback')
    assert env.claims.get('offer-b') == env.offered_b
    assert core_snapshot(env) == before
    assert env.journal.events() == events
    with env.journal.store._transaction(immediate=False) as db:
        assert db.execute('SELECT 1 FROM remote_claim_requests WHERE node_id=? AND request_id=?',
                          (env.node_id, 'claim_unknown_rollback')).fetchone() is None
    monkeypatch.setattr(env.journal.store, '_append_event', original)
    assert_remote_fenced(env, 'claim_unknown_rollback')
