"""Frozen standalone controller driver contracts; scripted local nodes only.

Reservations belong to this fixture's controller. Real NodeClaims transport and
retained artifact IO are exercised; no native, SSH, acceptance or Lead wiring.
Deletion is derived from tree.files, and historical offers are strictly read-only.
"""
import copy
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import uuid

import pytest

from sisyfus.autonomy.models import OpportunitySignal
from sisyfus.autonomy.store import AutonomyStore
from sisyfus.workers import journal as journal_module
from sisyfus.workers import remote_artifacts as artifacts
from sisyfus.workers import remote_driver as module
from sisyfus.workers.lead_journal import LeadJournal
from sisyfus.workers.node_claims import NodeClaims
from sisyfus.workers.node_registry import NodeRegistry
from sisyfus.workers.protocol import Receipt, Request, digest


class Clock:
    def __init__(self):
        self.wall, self.tick = 1000.0, 0.0
        self.steps = []
        self.sleeps = []

    def utc(self):
        return datetime.fromtimestamp(self.wall, timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')

    def sleep(self, seconds):
        assert 0 < seconds <= 0.2
        self.sleeps.append(seconds)
        if self.steps:
            self.steps.pop(0)()
        self.wall += seconds
        self.tick += seconds


@dataclass
class Fixture:
    journal: LeadJournal
    claims: NodeClaims
    node: str
    foreign: str
    continuation: dict
    clock: Clock
    request: Request
    snapshot: Path
    candidate: Path
    root: Path
    outputs: list


def meta(path, data):
    return {'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}


def put(root, path, data):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(data)
    return target


@pytest.fixture
def env(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(journal_module, 'utc_now', clock.utc)
    monkeypatch.setattr(module.time, 'sleep', clock.sleep)
    journal = LeadJournal(AutonomyStore(tmp_path / 'autonomy.sqlite3'))
    journal.bind({'parallelism': 10, 'max_calls': None, 'objective': 'fixed driver fixture',
                  'acceptance_hash': 'frozen', 'checks': {'fixed': {'sha': 'unchanged'}},
                  'tasks': [{'id': 'build', 'driver': 'codex'}]})
    opportunity, _ = journal.store.submit_opportunity(
        OpportunitySignal('driver-fixture', 'fixed input', 'fixed task'), now=clock.utc())
    journal.store.admit_opportunity(opportunity['id'], now=clock.utc())
    continuation = journal.store.claim_due_continuation('controller', lease_seconds=60, now=clock.utc())
    registry = NodeRegistry(journal)
    node = registry.enroll('enroll_driver_a', 'A', ['codex'], ['gpt-6.1-sol'])['node_id']
    foreign = registry.enroll('enroll_driver_b', 'B', ['codex'], ['gpt-6.1-sol'])['node_id']
    workspace = tmp_path / 'workspace'
    put(workspace, 'main.txt', b'original')
    put(workspace, 'keep.txt', b'keep')
    request = Request('build', 'Fixed worker input.', str(workspace), 'gpt-6.1-sol',
                      mode='workspace-write', timeout=0.6)
    # Canonical fingerprints are controller-owned, NOT assumed to be Request hashes.
    journal.reserve('run-worker', 'build', digest({'controller': 'fixed reservation'}),
                    continuation_id=continuation['id'], lease_token=continuation['lease_token'])
    journal.record('roles', 'run-worker', {'role': 'worker', 'driver': 'codex',
        'model': request.model, 'mode': request.mode, 'cwd': request.cwd, 'node': 'build'})
    claims = NodeClaims(journal, registry, tmp_path / 'uploads', clock=lambda: clock.wall)
    return Fixture(journal, claims, node, foreign, continuation, clock, request,
                   tmp_path / 'input-snapshot', tmp_path / 'candidate-envelope', tmp_path,
                   ['main.txt', 'out/new.txt'])


def driver(env, **changes):
    args = dict(input_snapshot=env.snapshot, candidate_root=env.candidate,
                output_paths=env.outputs, clock=lambda: env.clock.tick, poll_seconds=0.2)
    return module.RemoteCodexDriver(env.claims, 'run-worker', env.node, **(args | changes))


def core(env):
    with env.journal.store._transaction(immediate=False) as db:
        return dict(db.execute("SELECT * FROM native_worker_runs WHERE key='run-worker'").fetchone())


def projection(env):
    with env.journal.store._transaction(immediate=False) as db:
        tables = ('native_worker_runs', 'native_worker_commands', 'remote_offers',
                  'remote_input_snapshots', 'remote_withdrawals', 'remote_transport_controls',
                  'remote_receipt_trees', 'remote_uploads', 'events')
        return {t: [tuple(row) for row in db.execute('SELECT * FROM ' + t + ' ORDER BY rowid')]
                for t in tables}


def originals(env):
    return {str(p): artifacts.full_tree_manifest(p) for p in
            (Path(env.request.cwd), env.snapshot, env.claims.artifact_root) if p.exists()}


def claim(env):
    result = env.claims.claim(env.node, 'claim_driver_' + uuid.uuid4().hex)
    assert result['status'] == 'CLAIMED'
    return result['claim']


def terminal(env, *, contents=None, uploaded=None, status='COMPLETED', actual=None,
             report=None, omit_tree=False):
    owned = claim(env)
    assert env.claims.read_input(env.node, owned['claim_id'], 1, 'main.txt') == b'original'
    final = env.root / ('node-final-' + uuid.uuid4().hex)
    final.mkdir()
    contents = {'main.txt': b'new', 'keep.txt': b'keep', 'out/new.txt': b'result'} if contents is None else contents
    for path, data in contents.items():
        put(final, path, data)
    uploaded = {'main.txt': b'new', 'out/new.txt': b'result'} if uploaded is None else uploaded
    manifest = []
    for path, data in sorted(uploaded.items()):
        env.claims.upload(env.node, owned['claim_id'], 1, path, meta(path, data)['sha256'], data)
        manifest.append(meta(path, data))
    # Zero-upload claims still have a controller-prepared, independent namespace.
    (env.claims.artifact_root / owned['claim_id']).mkdir(exist_ok=True)
    native = Receipt(status, 'native-session', 'native-turn', 0, 'native output',
                     {'total_tokens': 17}, None, 'gpt-6.1-sol', actual)
    tree = artifacts.full_tree_manifest(final) if report is None else report
    kwargs = {} if omit_tree else {'tree': tree}
    saved = env.claims.receipt(env.node, owned['claim_id'], 1, native, manifest, **kwargs)
    assert saved['status'] == ('UNKNOWN' if status == 'UNKNOWN' else 'RECEIPTED')
    return owned, native, tree


def old_offer(env):
    manifest = artifacts.create_input_snapshot(env.request.cwd, env.snapshot, env.outputs)
    env.claims.bind_input_snapshot('run-worker', env.snapshot, manifest)
    return env.claims.offer('run-worker', env.node, env.request, manifest)


def assert_no_settlement(env, before):
    assert core(env) == before
    assert env.journal.runs()[0]['verdict'] == 'UNVERIFIED'
    assert env.journal.store.verify_event_chain()['valid'] is True


def forbid(monkeypatch, obj, names):
    def prohibited(*args, **kwargs):
        raise AssertionError('forbidden controller mutation/native entry')
    for name in names:
        monkeypatch.setattr(obj, name, prohibited)


def test_public_driver_contract_and_required_transport_methods(env):
    d = driver(env)
    assert d.name == 'codex' and d.controls == ('interrupt',)
    assert d.materialization is None
    assert d.__class__.__doc__ and d.run.__doc__
    for name in ('bind_input_snapshot', 'status', 'read_input', 'withdraw', 'post_controls'):
        assert callable(getattr(env.claims, name))


@pytest.mark.parametrize('value', [True, False, 0, -1, float('inf'), float('nan'), '0.2', None])
def test_poll_requires_strict_positive_finite_number(env, value):
    with pytest.raises(ValueError):
        driver(env, poll_seconds=value)
    assert env.claims.get('run-worker') is None and not env.snapshot.exists()


@pytest.mark.parametrize('value', [True, float('inf'), float('nan'), 'now', None])
def test_clock_requires_finite_numeric_samples_without_offer(env, value):
    with pytest.raises(ValueError):
        driver(env, clock=lambda: value)
    assert env.claims.get('run-worker') is None


@pytest.mark.parametrize('field,value', [('input_snapshot', 'relative'), ('candidate_root', '../bad'),
    ('output_paths', ['.hidden']), ('output_paths', ['credentials.json']),
    ('output_paths', ['x', 'X']), ('output_paths', ['x', 'x/y']),
    ('output_paths', ['x', 'x']), ('output_paths', 'main.txt'), ('output_paths', ['new\x00.txt'])])
def test_constructor_rejects_unsafe_controller_paths_and_outputs(env, field, value):
    with pytest.raises(ValueError):
        driver(env, **{field: value})
    assert not env.snapshot.exists() and not env.candidate.exists()


def test_success_binds_snapshot_before_offer_keeps_original_request_and_no_native_emit(env, monkeypatch):
    before_core, before_workspace = core(env), artifacts.full_tree_manifest(env.request.cwd)
    d, emitted, order = driver(env), [], []
    bind, offer = env.claims.bind_input_snapshot, env.claims.offer

    def binding(*args):
        order.append('bind')
        assert artifacts.full_tree_manifest(env.snapshot) == before_workspace
        return bind(*args)

    def offering(*args):
        order.append('offer')
        assert order == ['bind', 'offer'] and args[2] is env.request
        assert args[2].cwd == env.request.cwd
        return offer(*args)

    monkeypatch.setattr(env.claims, 'bind_input_snapshot', binding)
    monkeypatch.setattr(env.claims, 'offer', offering)
    forbid(monkeypatch, env.journal, ('reserve', 'complete'))
    forbid(monkeypatch, env.claims, ('heartbeat',))
    forbid(monkeypatch, env.journal.store, ('renew_lease',))
    expected = []

    def node():
        owned, native, _ = terminal(env, actual='attested-native-model')
        expected.append(native)
        # N1 already persists these facts; driver must not re-emit them.
        # Terminal receipt is already committed, so sync belongs before receipt
        # in its own separate protocol test below, not after terminal here.
        assert owned['request'] == asdict(env.request)

    env.clock.steps.append(node)
    result = d.run(env.request, lambda k, v: emitted.append((k, v)))
    assert result == expected[0] and emitted == []
    assert order == ['bind', 'offer']
    assert set(d.materialization) == {'candidate', 'before', 'delta'}
    assert Path(d.materialization['candidate']) == env.candidate / 'candidate'
    assert Path(d.materialization['before']) == env.candidate / 'before'
    assert d.materialization['delta']['valid'] is True
    assert d.materialization['delta']['modified'] == ['main.txt']
    assert d.materialization['delta']['added'] == ['out/new.txt']
    assert (env.candidate / 'candidate/main.txt').read_bytes() == b'new'
    assert artifacts.full_tree_manifest(env.request.cwd) == before_workspace
    assert artifacts.full_tree_manifest(env.snapshot) == artifacts.full_tree_manifest(env.candidate / 'before') == before_workspace
    assert_no_settlement(env, before_core)


def test_controller_output_list_is_detached_at_construction(env):
    d = driver(env)
    env.outputs.append('ungranted.txt')
    env.clock.steps.append(lambda: terminal(env))
    assert d.run(env.request, lambda *a: None).status == 'COMPLETED'
    assert env.claims.get('run-worker')['input_manifest']['output_paths'] == ['main.txt', 'out/new.txt']


def test_binding_supplies_snapshot_not_mutable_original_cwd(env, monkeypatch):
    offer = env.claims.offer

    def change_source_after_binding(*args):
        (Path(env.request.cwd) / 'main.txt').write_bytes(b'operator changed original')
        return offer(*args)

    monkeypatch.setattr(env.claims, 'offer', change_source_after_binding)
    env.clock.steps.append(lambda: terminal(env))
    d = driver(env)
    assert d.run(env.request, lambda *a: None).status == 'COMPLETED'
    assert (env.snapshot / 'main.txt').read_bytes() == b'original'
    assert (Path(env.request.cwd) / 'main.txt').read_bytes() == b'operator changed original'
    assert env.claims.get('run-worker')['request']['cwd'] == env.request.cwd


@pytest.mark.parametrize('status', ['COMPLETED', 'ERROR', 'INTERRUPTED'])
def test_known_native_status_and_telemetry_are_preserved_not_configuration_inferred(env, status):
    expected = []
    env.clock.steps.append(lambda: expected.append(terminal(env, status=status)[1]))
    d = driver(env)
    assert d.run(env.request, lambda *a: None) == expected[0]
    assert expected[0].actual_model is None
    assert d.materialization['delta']['valid'] is True


def test_each_driver_instance_runs_once_without_second_offer(env):
    d = driver(env)
    env.clock.steps.append(lambda: terminal(env))
    assert d.run(env.request, lambda *a: None).status == 'COMPLETED'
    before = projection(env)
    with pytest.raises(RuntimeError):
        d.run(env.request, lambda *a: None)
    assert projection(env) == before


@pytest.mark.parametrize('state', ['OFFERED', 'CLAIMED', 'WITHDRAWN', 'UNKNOWN', 'RECONCILIATION_CANDIDATE', 'RECEIPTED'])
def test_historical_offer_is_strictly_readonly_and_never_materialized(env, monkeypatch, state):
    old_offer(env)
    native = None
    if state in {'CLAIMED', 'UNKNOWN', 'RECONCILIATION_CANDIDATE'}:
        owned = claim(env)
        if state != 'CLAIMED':
            env.clock.wall += 31
            env.claims.expire()
            if state == 'RECONCILIATION_CANDIDATE':
                native = Receipt('COMPLETED', output='late result')
                env.claims.receipt(env.node, owned['claim_id'], 1, native, [])
    elif state == 'WITHDRAWN':
        env.claims.withdraw('run-worker', 'old reason')
    elif state == 'RECEIPTED':
        _, native, _ = terminal(env)
        env.clock.wall += 31  # Natural node expiry is not a new permission.
    before, trees = projection(env), originals(env)
    assert env.claims.get('run-worker')['status'] == state
    forbid(monkeypatch, env.claims, ('offer', 'bind_input_snapshot', 'expire', 'withdraw', 'post_controls', 'heartbeat'))
    forbid(monkeypatch, artifacts, ('create_input_snapshot', 'materialize_candidate'))
    d = driver(env)
    result = d.run(env.request, lambda *a: None, lambda: [{'id': 'old-stop', 'action': 'interrupt', 'text': ''}])
    assert result.status == ('COMPLETED' if state == 'RECEIPTED' else 'ERROR' if state == 'WITHDRAWN' else 'UNKNOWN')
    if state == 'RECEIPTED':
        assert result == native and d.materialization['status'] == 'NOT_MATERIALIZED'
    assert projection(env) == before and originals(env) == trees
    assert not env.candidate.exists()


@pytest.mark.parametrize('field,value', [('task_id', 'foreign-task'), ('fingerprint', 'f' * 64),
    ('continuation_id', 'foreign-continuation'), ('lease_token', 'foreign-owner'),
    ('status', 'UNKNOWN'), ('receipt_json', '{}')])
def test_core_identity_change_during_wait_is_unknown_never_new_offer(env, field, value):
    def mutate():
        with env.journal.store._transaction() as db:
            db.execute('UPDATE native_worker_runs SET ' + field + "=? WHERE key='run-worker'", (value,))
    env.clock.steps.append(mutate)
    d = driver(env)
    result = d.run(env.request, lambda *a: None)
    assert result.status == 'UNKNOWN' and result.error
    assert env.claims.get('run-worker') is not None and not env.candidate.exists()


@pytest.mark.parametrize('initial', ['missing', 'no-continuation', 'wrong-task', 'lost-lease'])
def test_no_matching_current_canonical_reservation_does_not_prepare(env, initial):
    with env.journal.store._transaction() as db:
        if initial == 'missing':
            db.execute("UPDATE native_worker_runs SET key='other-key' WHERE key='run-worker'")
        elif initial == 'no-continuation':
            db.execute("UPDATE native_worker_runs SET continuation_id=NULL,lease_token=NULL")
        elif initial == 'wrong-task':
            db.execute("UPDATE native_worker_runs SET task_id='different'")
        else:
            db.execute("UPDATE continuations SET lease_token='new-owner' WHERE id=?", (env.continuation['id'],))
    assert driver(env).run(env.request, lambda *a: None).status == 'UNKNOWN'
    assert not env.snapshot.exists() and env.claims.get('run-worker') is None


@pytest.mark.parametrize('field,value', [('model', 'other-model'), ('mode', 'read-only'),
    ('cwd', '/different-role'), ('role', 'reviewer'), ('node', 'other-task')])
def test_frozen_role_mismatch_is_explicit_no_offer(env, field, value):
    with env.journal.store._transaction() as db:
        row = db.execute("SELECT value FROM metadata WHERE key='techlead:roles:run-worker'").fetchone()
        saved = json.loads(row[0]); saved['data'][field] = value
        db.execute("UPDATE metadata SET value=? WHERE key='techlead:roles:run-worker'", (json.dumps(saved),))
    result = driver(env).run(env.request, lambda *a: None)
    assert result.status in {'ERROR', 'UNKNOWN'} and result.error
    assert env.claims.get('run-worker') is None and not env.snapshot.exists()


@pytest.mark.parametrize('kind', ['roles', 'context'])
def test_frozen_metadata_changes_are_fenced_even_when_request_fields_stay_same(env, kind):
    with env.journal.store._transaction() as db:
        db.execute('CREATE TABLE IF NOT EXISTS lead_mission_contexts (run_key TEXT PRIMARY KEY,binding_json TEXT)')
        db.execute('INSERT INTO lead_mission_contexts VALUES(?,?)',
                   ('run-worker', json.dumps({'prompt_hash': digest(env.request.prompt), 'role': 'worker', 'task_id': 'build'})))
    def mutate():
        with env.journal.store._transaction() as db:
            if kind == 'roles':
                saved = json.loads(db.execute("SELECT value FROM metadata WHERE key='techlead:roles:run-worker'").fetchone()[0])
                saved['data']['revision'] = 2
                db.execute("UPDATE metadata SET value=? WHERE key='techlead:roles:run-worker'", (json.dumps(saved),))
            else:
                db.execute("UPDATE lead_mission_contexts SET binding_json=?", (json.dumps({'prompt_hash': digest(env.request.prompt), 'revision': 2}),))
    env.clock.steps.append(mutate)
    assert driver(env).run(env.request, lambda *a: None).status == 'UNKNOWN'
    assert not env.candidate.exists()


@pytest.mark.parametrize('kind', ['hidden', 'control', 'symlink', 'fifo', 'oversized', 'occupied-snapshot', 'missing-parent', 'overlap'])
def test_input_preparation_error_never_offers_and_retains_original_tree(env, kind):
    changes = {}
    source = Path(env.request.cwd)
    if kind == 'hidden': put(source, '.hidden', b'diagnostic')
    if kind == 'control': put(source, 'auth.json', b'synthetic control data')
    if kind == 'symlink': (source / 'link').symlink_to(source / 'main.txt')
    if kind == 'fifo': os.mkfifo(source / 'pipe')
    if kind == 'oversized':
        with (source / 'large').open('xb') as stream: stream.truncate(8_000_001)
    if kind == 'occupied-snapshot':
        env.snapshot.mkdir(); put(env.snapshot, 'retained.txt', b'previous failure')
    if kind == 'missing-parent': changes['input_snapshot'] = env.root / 'missing/child/snapshot'
    if kind == 'overlap': changes['input_snapshot'] = source / 'snapshot'
    baseline = artifacts.full_tree_manifest(source)
    result = driver(env, **changes).run(env.request, lambda *a: None)
    assert result.status == 'ERROR' and result.error
    assert env.claims.get('run-worker') is None and artifacts.full_tree_manifest(source) == baseline
    assert not env.candidate.exists()
    if kind == 'occupied-snapshot': assert (env.snapshot / 'retained.txt').read_bytes() == b'previous failure'


@pytest.mark.parametrize('target', ['source', 'uploads', 'snapshot'])
def test_candidate_overlap_is_rejected_before_any_snapshot_creation(env, target):
    root = {'source': Path(env.request.cwd), 'uploads': env.claims.artifact_root, 'snapshot': env.snapshot}[target]
    baseline = originals(env)
    d = driver(env, candidate_root=root if target == 'snapshot' else root / 'candidate')
    assert d.run(env.request, lambda *a: None).status == 'ERROR'
    assert originals(env) == baseline and not env.snapshot.exists()
    assert env.claims.get('run-worker') is None


def test_single_deadline_includes_preparation_time_and_preserves_created_snapshot(env, monkeypatch):
    create = artifacts.create_input_snapshot
    def slow(*args, **kwargs):
        manifest = create(*args, **kwargs)
        env.clock.tick += 0.7
        return manifest
    monkeypatch.setattr(artifacts, 'create_input_snapshot', slow)
    result = driver(env).run(env.request, lambda *a: None)
    assert result.status == 'ERROR' and result.error
    assert env.snapshot.is_dir() and (env.snapshot / 'main.txt').read_bytes() == b'original'
    assert env.claims.get('run-worker') is None


@pytest.mark.parametrize('commit', [False, True])
def test_offer_exception_never_resends_even_if_commit_is_unknown(env, monkeypatch, commit):
    offer, calls = env.claims.offer, []
    def interrupted(*args):
        calls.append(args)
        if commit: offer(*args)
        raise OSError('fixed unknown submit outcome')
    monkeypatch.setattr(env.claims, 'offer', interrupted)
    d = driver(env)
    assert d.run(env.request, lambda *a: None).status == 'UNKNOWN'
    assert len(calls) == 1 and env.snapshot.is_dir() and not env.candidate.exists()
    assert (env.claims.get('run-worker') is not None) is commit


def test_unclaimed_timeout_withdraws_only_with_known_nonexecution_proof(env):
    before = core(env)
    result = driver(env).run(env.request, lambda *a: None)
    assert result.status == 'ERROR' and result.error
    view = env.claims.get('run-worker')
    assert (view['status'], view['epoch'], view['claim_id']) == ('WITHDRAWN', 0, None)
    assert sum(env.clock.sleeps) == pytest.approx(env.request.timeout)
    assert_no_settlement(env, before)


def test_interrupt_unclaimed_withdraws_and_never_calls_native_ack(env):
    events = []
    result = driver(env).run(env.request, lambda *a: events.append(a),
        lambda: [{'id': 'stop-before-claim', 'action': 'interrupt', 'text': ''}])
    assert result.status == 'ERROR' and env.claims.get('run-worker')['status'] == 'WITHDRAWN'
    assert not any(kind == 'control_ack' and data.get('accepted') for kind, data in events)
    assert env.claims.claim(env.node, 'claim_after_withdraw')['status'] == 'NO_WORK'


def test_withdraw_race_claimed_is_unknown_not_counterfeit_nonexecution(env, monkeypatch):
    withdraw = env.claims.withdraw
    def racing(*args):
        claim(env)
        return withdraw(*args)
    monkeypatch.setattr(env.claims, 'withdraw', racing)
    result = driver(env).run(env.request, lambda *a: None)
    assert result.status == 'UNKNOWN' and env.claims.get('run-worker')['status'] == 'CLAIMED'
    assert not env.candidate.exists()


def test_claimed_timeout_has_no_reoffer_renewal_or_completion(env, monkeypatch):
    env.clock.steps.append(lambda: claim(env))
    before = core(env)
    forbid(monkeypatch, env.claims, ('heartbeat',))
    result = driver(env).run(env.request, lambda *a: None)
    assert result.status == 'UNKNOWN' and env.claims.get('run-worker')['epoch'] == 1
    assert env.clock.tick == pytest.approx(env.request.timeout)
    assert_no_settlement(env, before)


def test_claimed_node_expiry_is_persisted_unknown_without_renewal(env):
    def node_lost():
        claim(env)
        env.clock.wall += 31
    env.clock.steps.append(node_lost)
    assert driver(env).run(env.request, lambda *a: None).status == 'UNKNOWN'
    assert env.claims.get('run-worker')['status'] == 'UNKNOWN'
    assert not env.candidate.exists()


def test_controller_lease_expiry_fences_every_return_including_known_terminal(env):
    def lose_core():
        terminal(env)
        env.clock.wall += 61
    env.clock.steps.append(lose_core)
    assert driver(env).run(env.request, lambda *a: None).status == 'UNKNOWN'
    assert env.claims.get('run-worker')['status'] == 'RECEIPTED'
    assert not env.candidate.exists()


def test_timely_terminal_survives_natural_node_deadline_with_current_core(env, monkeypatch):
    expected = []
    def node():
        expected.append(terminal(env)[1])
        env.clock.wall += 31
    env.clock.steps.append(node)
    forbid(monkeypatch, env.claims, ('heartbeat',))
    d = driver(env)
    assert d.run(env.request, lambda *a: None) == expected[0]
    assert env.claims.get('run-worker')['status'] == 'RECEIPTED'
    assert d.materialization['delta']['valid'] is True


def test_synced_events_are_not_duplicate_emitted_and_interrupt_delivery_is_not_ack(env):
    owned, events = [], []
    command = {'id': 'operator-stop-001', 'action': 'interrupt', 'text': ''}
    def node_claim():
        c = claim(env); owned.append(c)
        env.claims.sync(env.node, c['claim_id'], 1, [{'seq': 1, 'kind': 'native_event',
                       'data': {'method': 'fixture/event', 'params': {'fixed': True}}}])
    def node_ack():
        c = owned[0]
        assert env.claims.pending_controls(env.node, c['claim_id'], 1) == [command]
        env.claims.sync(env.node, c['claim_id'], 1, [{'seq': 2, 'kind': 'control_ack',
                       'data': {'command_id': command['id'], 'accepted': True}}])
        assert env.claims.pending_controls(env.node, c['claim_id'], 1) == []
        (env.claims.artifact_root / c['claim_id']).mkdir(exist_ok=True)
        env.claims.receipt(env.node, c['claim_id'], 1, Receipt('INTERRUPTED'), [],
                          tree=artifacts.full_tree_manifest(env.snapshot))
    env.clock.steps.extend([node_claim, node_ack])
    d = driver(env)
    result = d.run(env.request, lambda k, v: events.append((k, v)), lambda: [command] if owned else [])
    assert result.status == 'INTERRUPTED' and d.materialization['delta']['valid']
    assert events == []
    with env.journal.store._transaction(immediate=False) as db:
        assert db.execute('SELECT status FROM remote_transport_controls WHERE id=?', (command['id'],)).fetchone()[0] == 'ACK'
        assert db.execute('SELECT count(*) FROM remote_event_sync').fetchone()[0] == 2


@pytest.mark.parametrize('action', ['steer', 'shell', 'approve', 'resume'])
def test_unsupported_controls_are_explicit_rejected_ack_and_not_transport(env, action):
    events = []
    env.clock.steps.append(lambda: terminal(env))
    d = driver(env)
    result = d.run(env.request, lambda k, v: events.append((k, v)),
                   lambda: [{'id': 'unsupported-001', 'action': action, 'text': 'data'}])
    assert result.status == 'COMPLETED'
    assert len(events) == 1
    kind, data = events[0]
    assert kind == 'control_ack' and data['command_id'] == 'unsupported-001' and data['accepted'] is False
    assert data['error']
    with env.journal.store._transaction(immediate=False) as db:
        assert db.execute('SELECT count(*) FROM remote_transport_controls').fetchone()[0] == 0


def test_invalid_interrupt_payload_is_not_relayed_as_arbitrary_command(env):
    events = []
    env.clock.steps.append(lambda: terminal(env))
    result = driver(env).run(env.request, lambda k, v: events.append((k, v)),
        lambda: [{'id': 'invalid-stop', 'action': 'interrupt', 'text': 'arbitrary shell text'}])
    assert result.status in {'UNKNOWN', 'COMPLETED'}
    assert any(k == 'control_ack' and v['accepted'] is False for k, v in events)
    with env.journal.store._transaction(immediate=False) as db:
        assert db.execute('SELECT count(*) FROM remote_transport_controls').fetchone()[0] == 0


@pytest.mark.parametrize('state', ['UNKNOWN', 'RECONCILIATION_CANDIDATE'])
def test_unknown_or_late_native_receipt_never_becomes_terminal_permission(env, state):
    def node():
        if state == 'UNKNOWN':
            terminal(env, status='UNKNOWN')
        else:
            c = claim(env)
            env.clock.wall += 31
            env.claims.receipt(env.node, c['claim_id'], 1, Receipt('COMPLETED'), [],
                              tree=artifacts.full_tree_manifest(env.snapshot))
    env.clock.steps.append(node)
    d = driver(env)
    assert d.run(env.request, lambda *a: None).status == 'UNKNOWN'
    assert env.claims.get('run-worker')['status'] == state and not env.candidate.exists()


@pytest.mark.parametrize('kind', ['missing-tree', 'incomplete', 'diagnostics', 'wrong-file-hash',
    'missing-upload', 'out-of-scope', 'hidden', 'control', 'symlink', 'fifo',
    'file-to-directory', 'malformed-tree'])
def test_known_terminal_kept_with_invalid_full_tree_and_no_candidate(env, monkeypatch, kind):
    expected = []
    def node():
        contents, uploaded = {'main.txt': b'original', 'keep.txt': b'keep'}, {}
        report = None
        if kind == 'missing-upload': contents['main.txt'] = b'unuploaded modification'
        if kind == 'out-of-scope': contents['foreign.txt'] = b'not allowed'
        if kind in {'incomplete', 'diagnostics', 'wrong-file-hash', 'file-to-directory', 'hidden', 'control', 'symlink', 'fifo'}:
            final = env.root / 'diagnostic-tree'
            final.mkdir()
            for p, b in contents.items():
                if kind != 'file-to-directory' or p != 'main.txt': put(final, p, b)
            if kind == 'file-to-directory': (final / 'main.txt').mkdir()
            if kind == 'hidden': put(final, '.hidden', b'not ordinary')
            if kind == 'control': put(final, 'auth.json', b'synthetic excluded control')
            if kind == 'symlink': (final / 'link').symlink_to(final / 'main.txt')
            if kind == 'fifo': os.mkfifo(final / 'pipe')
            report = artifacts.full_tree_manifest(final)
            if kind == 'incomplete': report['complete'] = False
            if kind == 'diagnostics': report['errors'].append({'code': 'read_error', 'path': 'main.txt'})
            if kind == 'wrong-file-hash': report['files'][0]['sha256'] = 'f' * 64
        _, native, _ = terminal(env, contents=contents, uploaded=uploaded, report=report,
                                omit_tree=kind in {'missing-tree', 'malformed-tree'})
        expected.append(native)
        if kind == 'malformed-tree':
            status = env.claims.status
            monkeypatch.setattr(env.claims, 'status', lambda *a: status(*a) | {'tree': {'files': None}})
    env.clock.steps.append(node)
    d = driver(env)
    assert d.run(env.request, lambda *a: None) == expected[0]
    assert d.materialization['status'] == 'INVALID'
    assert d.materialization['report']['errors'] and d.materialization['report']['valid'] is False
    assert not env.candidate.exists()
    assert (env.snapshot / 'main.txt').read_bytes() == (Path(env.request.cwd) / 'main.txt').read_bytes() == b'original'


@pytest.mark.parametrize('kind', ['hash', 'size', 'missing', 'symlink'])
def test_upload_bytes_revalidated_not_merely_declared_stored(env, kind):
    expected = []
    def node():
        c, native, _ = terminal(env)
        expected.append(native)
        path = env.claims.artifact_root / c['claim_id'] / 'main.txt'
        if kind in {'hash', 'size'}:
            path.write_bytes(b'bad' if kind == 'hash' else b'bad-size')
        else:
            os.rename(path, path.with_name('retained-upload.txt'))
            if kind == 'symlink': path.symlink_to(path.with_name('retained-upload.txt'))
    env.clock.steps.append(node)
    d = driver(env)
    assert d.run(env.request, lambda *a: None) == expected[0]
    assert d.materialization['status'] == 'INVALID' and d.materialization['report']['errors']
    assert not env.candidate.exists()
    assert (env.snapshot / 'main.txt').read_bytes() == b'original'


def test_deletions_come_from_regular_files_and_real_trash_is_uniquely_recoverable(env, monkeypatch):
    name = 'deleted-' + uuid.uuid4().hex + '.txt'
    data = b'run-bound deletion:' + secrets.token_bytes(48)
    put(Path(env.request.cwd), name, data)
    env.outputs.append(name)
    before = artifacts.full_tree_manifest(env.request.cwd)
    calls, moves = [], []
    run, rename = subprocess.run, os.rename
    def observe(argv, **kwargs):
        assert len(argv) == 2 and argv[0] == '/usr/bin/trash' and '--' not in argv
        p = Path(argv[1]); assert p.is_absolute() and p.name == name
        assert p.parent.parent == env.candidate and p.parent.name.startswith('trash-')
        assert p.read_bytes() == data
        calls.append(argv)
        return run(argv, **kwargs)
    def move(src, dst, **kwargs):
        assert kwargs.get('src_dir_fd') is not None and kwargs.get('dst_dir_fd') is not None
        moves.append((src, dst)); return rename(src, dst, **kwargs)
    monkeypatch.setattr(artifacts.subprocess, 'run', observe)
    monkeypatch.setattr(artifacts.os, 'rename', move)
    recovered = Path.home() / '.Trash' / name
    assert not os.path.lexists(recovered)
    env.clock.steps.append(lambda: terminal(env))
    d = driver(env)
    assert d.run(env.request, lambda *a: None).status == 'COMPLETED'
    assert d.materialization['delta']['deleted'] == [name]
    assert len(calls) == len(moves) == 1 and recovered.read_bytes() == data
    assert artifacts.full_tree_manifest(env.request.cwd) == artifacts.full_tree_manifest(env.snapshot) == artifacts.full_tree_manifest(env.candidate / 'before') == before


def test_failed_materialization_retains_native_terminal_and_partial_envelope(env, monkeypatch):
    write = artifacts._write_file
    def partial(root, path, data, **kwargs):
        write(root, path, data, **kwargs)
        if Path(root).name == 'candidate': raise OSError('fixed fixture IO failure')
    monkeypatch.setattr(artifacts, '_write_file', partial)
    env.clock.steps.append(lambda: terminal(env))
    d = driver(env)
    assert d.run(env.request, lambda *a: None).status == 'COMPLETED'
    assert d.materialization['status'] == 'INVALID' and d.materialization['report']['errors']
    assert env.candidate.is_dir() and (env.candidate / 'before/main.txt').read_bytes() == b'original'
    assert (env.snapshot / 'main.txt').read_bytes() == (Path(env.request.cwd) / 'main.txt').read_bytes() == b'original'


@pytest.mark.parametrize('change', ['core-token', 'owner', 'epoch', 'status', 'receipt', 'tree'])
@pytest.mark.parametrize('boundary', ['before', 'after'])
def test_materialization_currency_checks_both_sides_and_retains_failed_envelope(env, monkeypatch, change, boundary):
    original = artifacts.materialize_candidate
    def mutate():
        with env.journal.store._transaction() as db:
            if change == 'core-token': db.execute("UPDATE continuations SET lease_token='replacement-owner'")
            if change == 'owner': db.execute("UPDATE remote_offers SET node_id=?", (env.foreign,))
            if change == 'epoch': db.execute('UPDATE remote_offers SET epoch=2')
            if change == 'status': db.execute("UPDATE remote_offers SET status='RECONCILIATION_CANDIDATE'")
            if change == 'receipt':
                saved = json.loads(db.execute('SELECT receipt_json FROM remote_offers').fetchone()[0])
                saved['output'] = 'replaced receipt'
                db.execute('UPDATE remote_offers SET receipt_json=?', (json.dumps(saved),))
            if change == 'tree':
                saved = json.loads(db.execute('SELECT tree_json FROM remote_receipt_trees').fetchone()[0])
                saved['complete'] = False
                db.execute('UPDATE remote_receipt_trees SET tree_json=?', (json.dumps(saved),))
    if boundary == 'after':
        def materialize(*args, **kwargs):
            result = original(*args, **kwargs); mutate(); return result
        monkeypatch.setattr(artifacts, 'materialize_candidate', materialize)
    else:
        delta = artifacts.exact_delta
        def before_io(*args, **kwargs):
            result = delta(*args, **kwargs); mutate(); return result
        monkeypatch.setattr(artifacts, 'exact_delta', before_io)
    env.clock.steps.append(lambda: terminal(env))
    d = driver(env)
    result = d.run(env.request, lambda *a: None)
    assert result.status == 'UNKNOWN' and result.error
    assert not d.materialization or d.materialization.get('status') != 'VALID'
    assert not d.materialization or 'candidate' not in d.materialization
    assert (env.snapshot / 'main.txt').read_bytes() == (Path(env.request.cwd) / 'main.txt').read_bytes() == b'original'
    if boundary == 'after':
        assert env.candidate.is_dir() and (env.candidate / 'before/main.txt').read_bytes() == b'original'
    else: assert not env.candidate.exists()


@pytest.mark.parametrize('field', ['prompt_hash', 'input_manifest_hash', 'fingerprint'])
def test_mutated_offer_hash_is_not_accepted_as_same_identity(env, field):
    def mutate():
        with env.journal.store._transaction() as db:
            saved = json.loads(db.execute('SELECT offer_json FROM remote_offers').fetchone()[0])
            saved[field] = 'e' * 64
            db.execute('UPDATE remote_offers SET offer_json=?', (json.dumps(saved),))
    env.clock.steps.append(mutate)
    assert driver(env).run(env.request, lambda *a: None).status == 'UNKNOWN'
    assert not env.candidate.exists()


def test_clock_reversal_during_wait_is_explicit_unknown_not_unbounded_retry(env):
    env.clock.steps.append(lambda: setattr(env.clock, 'tick', -10))
    result = driver(env).run(env.request, lambda *a: None)
    assert result.status == 'UNKNOWN' and result.error
    assert len(env.clock.sleeps) == 1 and not env.candidate.exists()
