"""Frozen backend planning-only confirmation; retained offline protocol fixtures.

The real ChatSessions/MissionHub/LeadMission and canonical DB are exercised.
Chat replies are static Receipts; no native process, socket or evaluator runs.
Faults retain the original request/mission, never retry creation or planning.
"""
from __future__ import annotations

import copy
import json
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from sisyfus.workers import lead_chat
from sisyfus.workers.codex import CodexDriver
from sisyfus.workers.lead_chat import ChatSessions, MODEL
from sisyfus.workers.lead_console import MissionHub, approved_spec
from sisyfus.workers.lead_contracts import load_lead_spec
from sisyfus.workers.lead_mission import LeadMission
from sisyfus.workers.protocol import Receipt, digest
from test_lead_mission import make_spec


REQUEST = 'prepare-chat-0001'
START = 'start-chat-000001'
PLAN = {'objective': 'Implement the agreed bounded backend.',
        'architecture': 'Draft, explicit planning confirmation, frozen tasks, placement, separate Start.',
        'constraints': ['Keep canonical acceptance', 'Planning is not worker permission'],
        'deliverables': ['Bounded backend', 'Retained regressions'],
        'tasks': [{'title': 'Build backend', 'acceptance': 'Fixed check passes', 'depends_on': []}]}


class AdvisoryFixture:
    def __init__(self):
        self.calls = []

    def run(self, request, emit):
        self.calls.append(request)
        return Receipt('COMPLETED', output=json.dumps({'reply': 'Fixture proposal only', 'proposal': PLAN}),
                       requested_model=MODEL, actual_model=MODEL, exit_code=0)


class ObservedHub(MissionHub):
    """Observe only public hub boundaries, without replacing controller truth."""
    def __init__(self, directory):
        super().__init__(directory)
        self.creates, self.prepares, self.starts = [], [], []
        self.before_create = self.after_create = None
        self.before_prepare = self.after_prepare = None
        self.before_start = self.after_start = None
        self.allow_start = False

    def create(self, spec, **kwargs):
        self.creates.append(copy.deepcopy(spec))
        if self.before_create:
            self.before_create(spec)
        result = super().create(spec, **kwargs)
        return self.after_create(result) if self.after_create else result

    def prepare_placement(self, ident, request_id, *, allow_planning=False):
        self.prepares.append((ident, request_id, allow_planning))
        if self.before_prepare:
            self.before_prepare(ident, request_id, allow_planning)
        result = super().prepare_placement(ident, request_id, allow_planning=allow_planning)
        return self.after_prepare(result) if self.after_prepare else result

    def start(self, ident, *, allow_local_workers=False, **kwargs):
        assert self.allow_start, 'planning-only confirmation called hub.start'
        self.starts.append((ident, allow_local_workers))
        if self.before_start:
            self.before_start(ident, allow_local_workers)
        result = super().start(ident, allow_local_workers=allow_local_workers, **kwargs)
        return self.after_start(result) if self.after_start else result


@pytest.fixture(autouse=True)
def offline_guard(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail('offline backend fixture reached native/process/network IO')
    for cls in (lead_chat.ClaudeCodeDriver, CodexDriver):
        monkeypatch.setattr(cls, 'run', blocked)
        monkeypatch.setattr(cls, 'probe', blocked)
    monkeypatch.setattr(subprocess, 'Popen', blocked)
    monkeypatch.setattr(socket, 'socket', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)


@pytest.fixture
def env(tmp_path):
    spec = make_spec(tmp_path, initial=True,
                     constraints=['Keep canonical acceptance'], deliverables=['Bounded backend'],
                     rsi={'enabled': False, 'auto_promote': False})
    spec_file = tmp_path / 'approved.json'
    spec_file.write_text(json.dumps(spec))
    advisory = AdvisoryFixture()
    services, hubs = [], []
    hub = ObservedHub(tmp_path / 'hub')
    hubs.append(hub)
    chats = ChatSessions(hub, driver=advisory)
    services.append(chats)
    ident = chats.create()['id']
    chats.context(ident, spec_path=str(spec_file))
    chats.message(ident, 'Discuss only; no worker permission.', 'discussion-00001')
    chats.threads[ident].join(5)
    assert not chats.threads[ident].is_alive()
    assert chats.get(ident)['readiness']['ready'] is True
    value = SimpleNamespace(chats=chats, hub=hub, ident=ident, spec=spec, spec_file=spec_file,
                            approval=chats.get(ident)['approval_hash'], advisory=advisory,
                            path=chats.root / ident / 'draft.json', starts=[])

    def reopen(*, new_hub=False):
        value.chats.close()
        if new_hub:
            value.hub.close()
            value.hub = ObservedHub(hub.directory)
            hubs.append(value.hub)
        value.chats = ChatSessions(value.hub, driver=advisory)
        services.append(value.chats)
        return value.chats
    value.reopen = reopen
    yield value
    for service in reversed(services):
        service.close()
    for h in reversed(hubs):
        h.close()


def stored(env):
    return json.loads(env.path.read_text())


def update(env, **changes):
    value = stored(env)
    value.update(copy.deepcopy(changes))
    env.path.write_text(json.dumps(value))


def prepare(env, request_id=REQUEST, approval=None, permission=True):
    return env.chats.prepare_placement(env.ident, permission, request_id,
                                       env.approval if approval is None else approval)


def settle(env, mission_id=None):
    mission_id = mission_id or env.chats.get(env.ident)['mission_id']
    env.hub.wait(mission_id, 5)
    session = env.hub._session(mission_id)
    assert not session.thread or not session.thread.is_alive()
    return session.mission


def no_work(env, m=None):
    assert env.hub.starts == [] and len(env.advisory.calls) == 1
    if m:
        assert not m.journal.runs()
        assert not m.journal.records('reviews') and not m.journal.records('integrations')
        assert m.integration_continuation() is None
        assert m.store.verify_event_chain()['valid']
        assert not m.snapshot()['all_verified']


def worker_start_fixture(env, monkeypatch):
    env.hub.allow_start = True
    def run(m, max_cycles=None):
        env.starts.append(str(m.directory))
        return m.snapshot()
    monkeypatch.setattr(LeadMission, 'run', run)


def test_request_before_create_mapping_before_planning_and_exact_operator_spec(env):
    before = stored(env)
    stages = []
    def before_create(spec):
        state = stored(env)
        assert state['requests'][REQUEST] == {'kind': 'prepare-placement', 'approval_hash': env.approval}
        assert state['status'] == 'STARTING' and state['mission_id'] is None
        assert state['placement_preparation']['status'] == 'CREATING'
        assert state['placement_preparation']['spec_hash'] == digest(load_lead_spec(spec))
        stages.append('create')
    def before_prepare(mid, rid, permission):
        state = stored(env)
        assert rid == REQUEST and permission is True
        assert state['mission_id'] == state['placement_preparation']['mission_id'] == mid
        assert state['placement_preparation']['status'] == 'PLANNING'
        assert digest(approved_spec(env.hub.path(mid))) == state['placement_preparation']['spec_hash']
        stages.append('prepare')
    env.hub.before_create, env.hub.before_prepare = before_create, before_prepare
    result = prepare(env)
    assert stages == ['create', 'prepare']
    assert result['status'] == 'IDLE' and result['approval_hash'] == env.approval
    saved = result['placement_preparation']
    assert saved['status'] == 'ACK' and saved['scope'] == 'planning_only'
    assert saved['request_id'] == REQUEST and saved['approval_hash'] == env.approval
    assert saved['control']['mission_id'] == saved['mission_id'] == result['mission_id']
    assert saved['control']['terminal'] is False and saved['control']['accepted'] is True
    assert not result['readiness']['ready']
    assert stored(env)['bound_spec'] == before['bound_spec'] and stored(env)['proposal'] == before['proposal']
    spec = approved_spec(env.hub.path(result['mission_id']))
    baseline = load_lead_spec(env.spec)
    for field in ('checks', 'required_checks', 'integration_checks', 'acceptance_hash', 'source_hash',
                  'source', 'roles', 'drivers', 'initial_plan'):
        assert spec[field] == baseline[field], field
    assert spec['objective'].startswith(env.spec['objective'] + '\n\nOperator-confirmed conversation plan:\n')
    assert PLAN['objective'] in spec['objective'] and PLAN['architecture'] in spec['objective']
    assert json.dumps(PLAN['tasks'], ensure_ascii=False) in spec['objective']
    for field in ('constraints', 'deliverables'):
        assert spec[field] == list(dict.fromkeys([*env.spec[field], *PLAN[field]]))
    m = settle(env)
    assert m.snapshot()['phase'] == 'WAITING_PLACEMENT'
    assert m.snapshot()['placement_preparation']['status'] == 'WAITING_PLACEMENT'
    assert env.hub.snapshot(result['mission_id'])['controller']['local_workers_acknowledged'] is False
    no_work(env, m)


@pytest.mark.parametrize('restart', [False, True])
def test_exact_replay_is_readonly_even_if_checker_changes_and_after_reboot(env, monkeypatch, restart):
    original = prepare(env)
    m = settle(env)
    if restart:
        env.reopen(new_hub=True)
    original = env.chats.get(env.ident)
    raw = env.path.read_bytes()
    chain = m.store.verify_event_chain()
    checker = Path(next(iter(env.spec['checks']['a']['code_hashes'])))
    checker.write_text('retained changed checker, never executed')
    def forbidden(*args, **kwargs):
        pytest.fail('cached preparation reentered creation/planning/Start or validation IO')
    for method in ('create', 'prepare_placement', 'start'):
        monkeypatch.setattr(env.hub, method, forbidden)
    monkeypatch.setattr(lead_chat, 'load_lead_spec', forbidden)
    assert prepare(env) == original
    assert env.path.read_bytes() == raw and m.store.verify_event_chain() == chain
    assert original['mission_id'] and len(env.hub.inventory()['missions']) == 1
    assert len(env.advisory.calls) == 1


def test_concurrent_identical_requests_create_and_plan_once(env):
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: prepare(env), range(3)))
    assert results == [results[0]] * 3
    assert len(env.hub.creates) == len(env.hub.prepares) == 1
    no_work(env, settle(env))


@pytest.mark.parametrize('permission', [False, None, 1, 1.0, 'true', 'True', [], {}])
def test_planning_permission_is_literal_true_and_never_worker_permission(env, permission):
    raw = env.path.read_bytes()
    with pytest.raises(PermissionError):
        prepare(env, permission=permission)
    assert env.path.read_bytes() == raw and not env.hub.creates and not env.hub.prepares
    no_work(env)


@pytest.mark.parametrize('request_id', [None, True, 1, [], {}, '', 'short', '../not-a-request',
                                      'space request', 'a' * 101])
def test_invalid_request_identity_never_reserves_or_creates(env, request_id):
    raw = env.path.read_bytes()
    with pytest.raises(ValueError):
        prepare(env, request_id=request_id)
    assert env.path.read_bytes() == raw and not env.hub.creates


@pytest.mark.parametrize('approval', [None, True, 1, [], {}, b'a' * 64, '', 'g' * 64,
                                    'A' * 64, 'a' * 63, 'a' * 65])
def test_approval_type_and_hash_shape_are_strict_before_side_effects(env, approval):
    raw = env.path.read_bytes()
    with pytest.raises(ValueError):
        env.chats.prepare_placement(env.ident, True, REQUEST, approval)
    assert env.path.read_bytes() == raw and not env.hub.creates


def test_valid_but_stale_approval_never_reserves(env):
    raw = env.path.read_bytes()
    with pytest.raises(RuntimeError):
        prepare(env, approval='0' * 64)
    assert env.path.read_bytes() == raw and not env.hub.creates


@pytest.mark.parametrize('missing', ['proposal', 'source', 'spec', 'checks', 'RUNNING', 'STARTING', 'UNKNOWN', 'ERROR'])
def test_original_readiness_and_native_fences_apply_before_reservation(env, missing):
    state = stored(env)
    if missing == 'proposal':
        state['proposal'] = None
    elif missing == 'source':
        state['source'] = ''
    elif missing == 'spec':
        state['bound_spec'] = None
    elif missing == 'checks':
        state['bound_spec']['checks'] = {}
    else:
        state['status'] = missing
    env.path.write_text(json.dumps(state))
    raw = env.path.read_bytes()
    with pytest.raises((ValueError, RuntimeError)):
        prepare(env)
    assert env.path.read_bytes() == raw and not env.hub.creates


def test_single_hub_and_closed_chat_owner_reject_without_creation(env, monkeypatch):
    raw = env.path.read_bytes()
    monkeypatch.setattr(env.hub, 'single', True)
    with pytest.raises(ValueError):
        prepare(env)
    assert env.path.read_bytes() == raw and not env.hub.creates
    monkeypatch.setattr(env.hub, 'single', False)
    old = env.chats
    env.reopen()
    with pytest.raises(RuntimeError, match='closing'):
        old.prepare_placement(env.ident, True, REQUEST, env.approval)
    assert env.path.read_bytes() == raw and not env.hub.creates


@pytest.mark.parametrize('change', ['checker', 'source_non_directory', 'objective_bound'])
def test_hash_paths_and_original_approval_revalidate_before_create(env, change):
    if change == 'checker':
        checker = Path(next(iter(env.spec['checks']['a']['code_hashes'])))
        checker.write_text('changed checker retained')
    elif change == 'source_non_directory':
        source = Path(env.spec['source'])
        source.rename(source.with_name('retained-source'))
        source.write_text('not a source directory')
    else:
        state = stored(env)
        state['bound_spec']['objective'] += ' changed after approval'
        env.path.write_text(json.dumps(state))
    raw = env.path.read_bytes()
    with pytest.raises((ValueError, RuntimeError)):
        prepare(env)
    assert env.path.read_bytes() == raw and not env.hub.creates


@pytest.mark.parametrize('previous', [None, False, 0, [], {}, True,
    {'kind': 'message', 'hash': '0' * 64}, {'kind': 'start', 'approval_hash': '0' * 64},
    {'kind': 'directory'}, {'kind': ['prepare-placement']},
    {'kind': 'prepare-placement', 'approval_hash': '0' * 64}])
def test_request_id_conflicts_are_strict_even_for_falsy_or_malformed_old_slots(env, previous):
    state = stored(env)
    state['requests'][REQUEST] = previous
    env.path.write_text(json.dumps(state))
    raw = env.path.read_bytes()
    with pytest.raises(ValueError):
        prepare(env)
    assert env.path.read_bytes() == raw and not env.hub.creates


def test_different_operation_hash_or_new_preparation_cannot_rebind_frozen_draft(env):
    result = prepare(env)
    m = settle(env)
    raw = env.path.read_bytes()
    with pytest.raises(ValueError):
        env.chats.start(env.ident, True, REQUEST, env.approval)
    with pytest.raises(ValueError):
        prepare(env, approval='0' * 64)
    for operation in (
        lambda: prepare(env, request_id='different-prepare-02'),
        lambda: env.chats.message(env.ident, 'replace acceptance', 'new-message-0001'),
        lambda: env.chats.context(env.ident, spec_path=str(env.spec_file)),
        lambda: env.chats.prepare_directory(env.ident, 'new-directory-001'),
        lambda: env.chats.attach_mission(env.ident, result['mission_id']),
    ):
        with pytest.raises(RuntimeError):
            operation()
    assert env.path.read_bytes() == raw and len(env.hub.creates) == len(env.hub.prepares) == 1
    no_work(env, m)


@pytest.mark.parametrize('stage', ['before_create', 'after_create', 'before_prepare', 'after_prepare'])
def test_lost_create_or_planning_reply_is_unknown_readonly_and_never_reissued(env, stage):
    def lost(*args):
        raise RuntimeError('synthetic lost reply Authorization: Bearer fixture-transport-token')
    setattr(env.hub, stage, lost)
    with pytest.raises(RuntimeError, match='synthetic lost reply'):
        prepare(env)
    result = env.chats.get(env.ident)
    assert result['status'] == result['placement_preparation']['status'] == 'UNKNOWN'
    assert 'fixture-transport-token' not in json.dumps(result)
    count = len(env.hub.creates), len(env.hub.prepares)
    mission_id = result['mission_id']
    if stage.endswith('prepare'):
        assert mission_id and result['placement_preparation']['mission_id'] == mission_id
        if stage == 'after_prepare':
            settle(env)
    else:
        assert mission_id is None
    raw = env.path.read_bytes()
    assert prepare(env) == result and env.path.read_bytes() == raw
    env.reopen(new_hub=True)
    assert prepare(env) == result and env.path.read_bytes() == raw
    with pytest.raises(RuntimeError):
        prepare(env, request_id='unknown-new-0001')
    with pytest.raises(RuntimeError):
        env.chats.start(env.ident, True, START, env.approval)
    assert count[0] == 1 and not env.hub.creates and not env.hub.prepares and not env.hub.starts
    assert len(env.hub.inventory()['missions']) == (0 if stage == 'before_create' else 1)
    assert len(env.advisory.calls) == 1


@pytest.mark.parametrize('stage', ['before_create', 'after_create', 'before_prepare', 'after_prepare'])
def test_interrupted_reservation_recovers_original_mapping_and_fences_on_restart(env, stage):
    def interrupted(*args):
        raise KeyboardInterrupt('retained simulated crash')
    setattr(env.hub, stage, interrupted)
    with pytest.raises(KeyboardInterrupt):
        prepare(env)
    if stage == 'after_prepare':
        settle(env)
    old = stored(env)
    env.reopen(new_hub=True)
    result = env.chats.get(env.ident)
    assert result['status'] == result['placement_preparation']['status'] == 'UNKNOWN'
    assert result['mission_id'] == old['mission_id']
    assert result['placement_preparation']['mission_id'] == old['mission_id']
    raw = env.path.read_bytes()
    assert prepare(env) == result and env.path.read_bytes() == raw
    assert not env.hub.creates and not env.hub.prepares and not env.hub.starts
    assert len(env.hub.inventory()['missions']) == (0 if stage == 'before_create' else 1)


@pytest.mark.parametrize('stage', ['CREATING', 'MAPPED', 'PLANNING', 'ACK'])
@pytest.mark.parametrize('persist_then_raise', [False, True])
def test_durable_write_faults_never_cross_unrecorded_boundary_or_resend(env, monkeypatch, stage, persist_then_raise):
    save = env.chats._save
    faulted = []
    def fail_once(state):
        current = (state.get('placement_preparation') or {}).get('status')
        if current == stage and not faulted:
            faulted.append(True)
            if persist_then_raise:
                save(state)
            raise OSError('synthetic retained fsync outcome')
        save(state)
    monkeypatch.setattr(env.chats, '_save', fail_once)
    raw = env.path.read_bytes()
    with pytest.raises(OSError):
        prepare(env)
    if stage == 'CREATING' and not persist_then_raise:
        assert env.path.read_bytes() == raw and not env.hub.creates and not env.hub.prepares
        return
    assert len(env.hub.creates) == (0 if stage == 'CREATING' else 1)
    assert len(env.hub.prepares) == (1 if stage == 'ACK' else 0)
    if stage == 'ACK':
        settle(env)
    env.reopen(new_hub=True)
    result = env.chats.get(env.ident)
    assert result['status'] == result['placement_preparation']['status'] == 'UNKNOWN'
    raw = env.path.read_bytes()
    assert prepare(env) == result and env.path.read_bytes() == raw
    assert not env.hub.creates and not env.hub.prepares and not env.hub.starts


@pytest.mark.parametrize('created', [None, [], {}, {'id': None}, {'id': 1}, {'id': ''}, {'id': '../foreign'}])
def test_malformed_creation_mapping_fences_without_planning(env, created):
    env.hub.after_create = lambda _: copy.deepcopy(created)
    with pytest.raises((ValueError, RuntimeError)):
        prepare(env)
    result = env.chats.get(env.ident)
    assert result['status'] == result['placement_preparation']['status'] == 'UNKNOWN'
    assert not env.hub.prepares and not env.hub.starts
    raw = env.path.read_bytes()
    assert prepare(env) == result and env.path.read_bytes() == raw
    assert len(env.hub.creates) == 1 and len(env.hub.inventory()['missions']) == 1


def test_created_canonical_spec_must_equal_request_pin_before_planning(env, monkeypatch):
    real_create = MissionHub.create
    def substituted(spec, **kwargs):
        env.hub.creates.append(copy.deepcopy(spec))
        different = copy.deepcopy(spec)
        different['objective'] += ' substituted by a synthetic collaborator'
        return real_create(env.hub, different, **kwargs)
    monkeypatch.setattr(env.hub, 'create', substituted)
    with pytest.raises(RuntimeError):
        prepare(env)
    result = env.chats.get(env.ident)
    assert result['status'] == 'UNKNOWN' and result['mission_id']
    assert result['placement_preparation']['mission_id'] == result['mission_id']
    assert not env.hub.prepares and not env.hub.starts
    assert prepare(env) == result and len(env.hub.creates) == 1


@pytest.mark.parametrize('change', [None, [], {}, {'mission_id': 'foreign'}, {'request_id': 'different'},
    {'id': 'different'}, {'action': 'start'}, {'status': 'COMPLETED'}, {'accepted': 1},
    {'accepted': False}, {'terminal': 0}, {'terminal': True}, {'scope': 'worker'}, {'extra': 'unexpected'}])
def test_planning_ack_types_and_exact_identity_cannot_fake_acceptance(env, change):
    def malformed(result):
        if not isinstance(change, dict) or not change:
            return copy.deepcopy(change)
        return {**result, **change}
    env.hub.after_prepare = malformed
    with pytest.raises(ValueError):
        prepare(env)
    m = settle(env)
    result = env.chats.get(env.ident)
    assert result['status'] == result['placement_preparation']['status'] == 'UNKNOWN'
    assert result['placement_preparation']['control'] is None
    assert prepare(env) == result and len(env.hub.prepares) == len(env.hub.creates) == 1
    no_work(env, m)


@pytest.mark.parametrize('reboot', [False, True])
def test_later_explicit_start_uses_same_mission_and_original_worker_permission(env, monkeypatch, reboot):
    prepared = prepare(env)
    m = settle(env)
    if reboot:
        env.reopen(new_hub=True)
    worker_start_fixture(env, monkeypatch)
    def before_start(mid, permission):
        state = stored(env)
        assert permission is True and mid == prepared['mission_id']
        assert state['requests'][START] == {'kind': 'start', 'approval_hash': env.approval}
        assert state['placement_start']['status'] == 'STARTING'
        assert state['mission_id'] == mid and state['status'] == 'STARTING'
    env.hub.before_start = before_start
    result = env.chats.start(env.ident, True, START, env.approval)
    settle(env)
    assert result['status'] == 'IDLE' and result['mission_id'] == prepared['mission_id']
    assert result['placement_start']['status'] == 'ACK'
    assert result['placement_preparation'] == prepared['placement_preparation']
    assert env.hub.starts == [(prepared['mission_id'], True)] and len(env.starts) == 1
    assert env.hub.snapshot(prepared['mission_id'])['controller']['local_workers_acknowledged'] is True
    assert len(env.hub.inventory()['missions']) == 1
    raw = env.path.read_bytes()
    assert env.chats.start(env.ident, True, START, env.approval) == result
    assert env.path.read_bytes() == raw and len(env.hub.starts) == 1
    with pytest.raises(RuntimeError):
        env.chats.start(env.ident, True, 'second-start-0001', env.approval)
    assert len(env.advisory.calls) == 1 and m.store.verify_event_chain()['valid']


@pytest.mark.parametrize('permission', [False, None, 1, 1.0, 'true', [], {}])
def test_planning_ack_does_not_grant_later_worker_permission(env, permission):
    prepare(env)
    settle(env)
    raw = env.path.read_bytes()
    with pytest.raises(PermissionError):
        env.chats.start(env.ident, permission, START, env.approval)
    assert env.path.read_bytes() == raw and not env.hub.starts


@pytest.mark.parametrize('drift', ['approval', 'checker', 'source', 'mapping'])
def test_prepared_start_revalidates_approval_source_acceptance_and_original_mapping(env, drift):
    prepare(env)
    settle(env)
    approval = env.approval
    if drift == 'approval':
        approval = '0' * 64
    elif drift == 'checker':
        Path(next(iter(env.spec['checks']['a']['code_hashes']))).write_text('changed checker retained')
    elif drift == 'source':
        (Path(env.spec['source']) / 'README.md').write_text('changed source retained')
    else:
        update(env, mission_id='different-mission')
    raw = env.path.read_bytes()
    with pytest.raises((ValueError, RuntimeError)):
        env.chats.start(env.ident, True, START, approval)
    assert env.path.read_bytes() == raw and not env.hub.starts
    assert len(env.hub.creates) == len(env.hub.prepares) == 1


@pytest.mark.parametrize('failure', ['exception', 'interrupt'])
def test_lost_separate_start_never_recreates_replans_or_repeats_start(env, monkeypatch, failure):
    prepared = prepare(env)
    settle(env)
    worker_start_fixture(env, monkeypatch)
    def lost(*args):
        if failure == 'interrupt':
            raise KeyboardInterrupt('synthetic Start interruption')
        raise RuntimeError('synthetic lost Start outcome')
    env.hub.after_start = lost
    with pytest.raises(KeyboardInterrupt if failure == 'interrupt' else RuntimeError):
        env.chats.start(env.ident, True, START, env.approval)
    settle(env)
    assert len(env.starts) == 1
    env.reopen(new_hub=True)
    result = env.chats.get(env.ident)
    assert result['status'] == result['placement_start']['status'] == 'UNKNOWN'
    assert result['mission_id'] == prepared['mission_id']
    raw = env.path.read_bytes()
    assert env.chats.start(env.ident, True, START, env.approval) == result
    assert env.path.read_bytes() == raw
    assert not env.hub.creates and not env.hub.prepares and not env.hub.starts
    with pytest.raises(RuntimeError):
        env.chats.start(env.ident, True, 'lost-new-start-01', env.approval)


def test_old_immediate_start_contract_is_still_separate_and_unchanged(env, monkeypatch):
    worker_start_fixture(env, monkeypatch)
    result = env.chats.start(env.ident, True, START, env.approval)
    settle(env)
    assert result['mission_id'] and result['status'] == 'IDLE'
    assert 'placement_preparation' not in result and 'placement_start' not in result
    assert len(env.hub.creates) == len(env.hub.starts) == 1 and not env.hub.prepares
    raw = env.path.read_bytes()
    assert env.chats.start(env.ident, True, START, env.approval) == result
    assert env.path.read_bytes() == raw and len(env.hub.starts) == 1
