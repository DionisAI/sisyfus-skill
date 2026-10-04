from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import json

import pytest

from sisyfus.research_os.controller import ResearchOS, configure, coordinator_lock
from sisyfus.research_os.demo import create_demo
from sisyfus.research_os.judgments import CallableJudge
from sisyfus.research_os.models import digest
from sisyfus.research_os.policy import SchedulingPolicy
from sisyfus.research_os.portfolio import Portfolio, SCHEMA
from sisyfus.research_os.replay import ReplayWorld, UnsupportedAction
from sisyfus.research_v2.engine import ResearchEngine


@pytest.fixture(autouse=True)
def no_ui(monkeypatch):
    original = ResearchEngine._persist
    monkeypatch.setattr(ResearchEngine, '_persist', lambda self, s, *, render: original(self, s, render=False))
    monkeypatch.setenv('SISYFUS_AUTO_SERVE', '0')


@pytest.fixture
def pair(tmp_path):
    return [create_demo(tmp_path / name, 'square') for name in ('a', 'b')]


def spec(engines, **overrides):
    raw = {'schema': SCHEMA, 'id': 'portfolio', 'projects': [
        {'id': chr(97+i), 'root': str(e.workspace.root)} for i, e in enumerate(engines)],
        'budget': {'max_attempts': 20, 'max_cost_units': 20}}
    raw.update(overrides)
    return raw


def make(tmp_path, engines, **overrides):
    return Portfolio.create(tmp_path / 'portfolio', spec(engines, **overrides), actor='operator')


def run(p, n=10, **kwargs):
    return p.run(max_steps=n, allow_local_commands=True, **kwargs)


def one(e):
    for eid in ('e0', 'e2'):
        e.prune_experiment(eid, reason='fixture retains one valid candidate')
    configure(e)


def add_bad(e):
    exp = deepcopy(e.snapshot()['experiments']['e1'])
    exp.update(id='zz-bad', context_id='contradiction')
    exp['action']['command'] = exp['action']['command'].replace('candidate-1.json', 'candidate-0.json')
    exp['action']['code_paths'] = ['measurement.py', 'candidate-0.json']
    exp['priority'] = {k: 0 for k in ('goal_progress', 'information_gain', 'reusable_value', 'novelty')}
    assert e.propose_experiment(exp)['admission']['accepted']
    configure(e)


def test_global_budget_smaller_than_sum_of_local_budgets(tmp_path, pair):
    p = make(tmp_path, pair, budget={'max_attempts': 10, 'max_cost_units': 2.5})
    r = run(p)
    assert r['steps_this_call'] == 2
    assert r['budget']['cost_used'] == 2
    assert r['budget']['cost_remaining'] == .5
    assert run(Portfolio(tmp_path / 'portfolio'))['steps_this_call'] == 0
    assert sum(len(e.snapshot()['attempts']) for e in pair) == 2


def test_global_attempt_budget_even_when_cost_available(tmp_path, pair):
    p = make(tmp_path, pair, budget={'max_attempts': 1, 'max_cost_units': 100})
    assert run(p)['steps_this_call'] == 1
    assert run(p)['steps_this_call'] == 0


def test_priority_competes_across_real_workspaces(tmp_path, pair):
    raw = spec(pair)
    raw['projects'][1]['weight'] = 100
    p = Portfolio.create(tmp_path / 'p', raw, actor='operator')
    r = run(p, 1)
    assert r['outcomes'][0]['project'] == 'b'
    assert len(pair[0].snapshot()['attempts']) == 0


def test_fairness_survives_controller_restart(tmp_path, pair):
    raw = spec(pair, max_consecutive=1)
    raw['projects'][0]['weight'] = 100
    p = Portfolio.create(tmp_path / 'p', raw, actor='operator')
    assert run(p, 1)['outcomes'][0]['project'] == 'a'
    r = run(Portfolio(tmp_path / 'p'), 1)
    assert [x['project'] for x in r['outcomes']] == ['a', 'b']
    assert p.store.operations()[-1]['intent']['fairness_applied']


def test_dependency_opens_only_after_source_verdict(tmp_path, pair):
    for e in pair:
        one(e)
    raw = spec(pair)
    raw['projects'][1].update(weight=100, requires=[{'project': 'a', 'claim': 'c1'}])
    p = Portfolio.create(tmp_path / 'p', raw, actor='operator')
    assert {c['project'] for c in p.status()['choices']} == {'a'}
    r = run(p)
    assert [o['project'] for o in r['outcomes']] == ['a', 'b']
    proof = r['outcomes'][1]['dependency_proofs'][0]
    assert proof['verdict_event_hash'] == r['outcomes'][0]['source_event_hash']
    assert all(not o['stale_dependencies'] for o in r['outcomes'])


def test_transitive_invalidation_does_not_rewrite_scientific_history(tmp_path, pair):
    engines = pair + [create_demo(tmp_path / 'c', 'square')]
    for e in engines:
        one(e)
    add_bad(engines[0])
    raw = spec(engines, max_consecutive=10)
    for i in (1, 2):
        raw['projects'][i].update(weight=10**i, requires=[{'project': chr(96+i), 'claim': 'c1'}])
    p = Portfolio.create(tmp_path / 'p', raw, actor='operator')
    r = run(p, 3)
    assert [o['project'] for o in r['outcomes']] == ['a', 'b', 'c']
    assert all(o['verdict'] == 'PASS' for o in r['outcomes'])
    r = run(p, 1)
    assert r['outcomes'][-1]['verdict'] == 'FAIL'
    assert [o['stale_dependencies'] for o in r['outcomes'][:3]] == [False, True, True]
    assert engines[2].snapshot()['claims']['c1']['status'] == 'SUPPORTED'
    assert len(p.export()['nodes']) == 4  # Preserve historical labels, tag current staleness.


def test_existing_unbound_middle_result_cannot_satisfy_new_dependencies(tmp_path, pair):
    one(pair[0]); one(pair[1])
    ResearchOS(pair[0]).run(max_steps=1, allow_local_commands=True)
    ResearchOS(pair[1]).run(max_steps=1, allow_local_commands=True)
    c = create_demo(tmp_path / 'c', 'square'); one(c)
    raw = spec(pair + [c])
    raw['projects'][1]['requires'] = [{'project': 'a', 'claim': 'c1'}]
    raw['projects'][2]['requires'] = [{'project': 'b', 'claim': 'c1'}]
    p = Portfolio.create(tmp_path / 'p', raw, actor='operator')
    assert not p.status()['choices']
    assert any('stale_dependency_provenance' in x for x in p.status()['projects']['c']['blocked'])


def test_removed_evidence_artifact_blocks_consumers(tmp_path, pair):
    for e in pair:
        one(e)
    raw = spec(pair)
    raw['projects'][1]['requires'] = [{'project': 'a', 'claim': 'c1'}]
    p = Portfolio.create(tmp_path / 'p', raw, actor='operator')
    run(p, 1)
    ref = next(iter(pair[0].snapshot()['evidence'].values()))['artifact_refs'][0]
    (pair[0].workspace.path / ref['path']).unlink()
    r = run(p, 1)
    assert r['steps_this_call'] == 0
    assert any('modified_artifact' in x for x in r['projects']['b']['blocked'])


def test_before_dispatch_crash_keeps_reservation_then_explicit_cancel(tmp_path, pair, monkeypatch):
    p = make(tmp_path, pair)
    original = ResearchOS._run
    monkeypatch.setattr(ResearchOS, '_run', lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        run(p, 1)
    monkeypatch.setattr(ResearchOS, '_run', original)
    assert p.reconcile()['budget']['cost_reserved'] == 1
    assert run(p, 1)['steps_this_call'] == 0
    r = p.cancel_unstarted('op-000000', actor='operator')
    assert r['budget']['cost_reserved'] == 0
    assert r['budget']['attempts_used_or_reserved'] == 0
    r = run(p, 1)
    assert r['steps_this_call'] == 1 and r['budget']['cost_used'] == 1
    assert len(p.export()['nodes']) == 1


def test_after_verdict_crash_reconciles_without_reexecution(tmp_path, pair, monkeypatch):
    p = make(tmp_path, pair)
    original = p.store.append
    def crash(kind, data):
        if kind == 'SETTLED':
            raise KeyboardInterrupt
        return original(kind, data)
    monkeypatch.setattr(p.store, 'append', crash)
    with pytest.raises(KeyboardInterrupt):
        run(p, 1)
    assert sum(len(e.snapshot()['attempts']) for e in pair) == 1
    p = Portfolio(tmp_path / 'portfolio')
    assert p.status()['unresolved'][0]['receipt_available']
    r = p.reconcile()
    assert r['budget']['cost_used'] == 1 and r['budget']['cost_reserved'] == 0
    assert not r['unresolved']
    assert p.reconcile()['budget']['cost_used'] == 1
    assert sum(len(e.snapshot()['attempts']) for e in pair) == 1


def test_unknown_tool_and_legacy_recovery_do_not_refund_or_retry(tmp_path, pair, monkeypatch):
    p = make(tmp_path, pair)
    def crash(self, eid, **kw):
        self.begin_attempt(eid)
        raise KeyboardInterrupt
    monkeypatch.setattr(ResearchEngine, 'execute_experiment', crash)
    with pytest.raises(KeyboardInterrupt):
        run(p, 1)
    pending = p.status()['unresolved'][0]
    assert pending and p.status()['budget']['cost_reserved'] == 1
    with pytest.raises(ValueError, match='may have started'):
        p.cancel_unstarted(pending['operation_id'], actor='operator')
    p.engines[pending['project']].recover_stranded()
    assert p.reconcile()['unresolved']
    assert run(p, 1)['steps_this_call'] == 0
    assert not p.export()['nodes']


def test_spoofed_settlement_is_not_evidence(tmp_path, pair, monkeypatch):
    p = make(tmp_path, pair)
    monkeypatch.setattr(ResearchOS, '_run', lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        run(p, 1)
    with p.store.lock():
        p.store.append('SETTLED', {'operation_id': 'op-000000', 'verdict_event_hash': 'made-up'})
    with pytest.raises(ValueError, match='source verifier'):
        p.status()


def test_local_config_refresh_retains_global_budget(tmp_path, pair):
    p = make(tmp_path, pair, budget={'max_attempts': 2, 'max_cost_units': 2})
    run(p, 1)
    configure(pair[0], policy=SchedulingPolicy(name='operator-revised'))
    assert 'a:configuration_changed' in run(p, 1)['problems']
    p.refresh_binding('a', actor='operator')
    r = run(p)
    assert r['budget']['cost_used'] == 2 and r['steps_this_call'] == 1


def test_unmanaged_local_work_is_detected(tmp_path, pair):
    p = make(tmp_path, pair)
    ResearchOS(pair[0]).run(max_steps=1, allow_local_commands=True)
    r = run(p)
    assert r['steps_this_call'] == 0
    assert any('unmanaged_attempt' in x for x in r['problems'])


def test_member_lock_is_respected_before_any_reservation(tmp_path, pair):
    p = make(tmp_path, pair)
    with coordinator_lock(pair[1]):
        with pytest.raises(RuntimeError, match='coordinator'):
            run(p)
    assert not p.store.operations()


def test_portfolio_lock_is_exclusive(tmp_path, pair):
    p = make(tmp_path, pair)
    with p.store.lock():
        with pytest.raises(RuntimeError, match='coordinator'):
            p.status()


def test_measurement_drift_rejected_before_shared_reservation(tmp_path, pair):
    p = make(tmp_path, pair)
    path = pair[0].workspace.root / 'measurement.py'
    path.write_text(path.read_text() + '\n# drift\n')
    r = run(p)
    assert r['stop_reason'] == 'approved_inputs_changed'
    assert not p.store.operations() and not pair[0].snapshot()['attempts']


def test_zero_judge_weight_never_calls_provider(tmp_path, pair):
    p = make(tmp_path, pair)
    def nope(*args):
        raise AssertionError('judge must not run')
    assert run(p, 1, judge=CallableJudge(nope))['steps_this_call'] == 1


def test_judgments_require_explicit_opt_in(tmp_path, pair):
    p = make(tmp_path, pair, policy=asdict(SchedulingPolicy(judgment_weight=1)))
    with pytest.raises(PermissionError, match='judgment'):
        run(p)


def test_judge_cannot_bypass_cross_project_dependency(tmp_path, pair):
    one(pair[0]); one(pair[1])
    raw = spec(pair, policy=asdict(SchedulingPolicy(judgment_weight=1)))
    raw['projects'][1]['requires'] = [{'project': 'a', 'claim': 'c1'}]
    p = Portfolio.create(tmp_path / 'p', raw, actor='operator')
    seen = []
    def assess(cs):
        seen.extend(c['id'] for c in cs)
        assert 'command' not in json.dumps(cs)
        return {c['id']: {'actionable': 1, 'duplicate': 0} for c in cs}
    run(p, 1, judge=CallableJudge(assess), allow_judgments=True)
    assert seen == ['a::e1']


def test_judge_state_mutation_blocks_dispatch(tmp_path, pair):
    p = make(tmp_path, pair, policy=asdict(SchedulingPolicy(judgment_weight=1)))
    def mutate(cs):
        pair[0].pause(reason='changed during decision')
        return {c['id']: {'actionable': 1, 'duplicate': 0} for c in cs}
    r = run(p, 1, judge=CallableJudge(mutate), allow_judgments=True)
    assert r['stop_reason'] == 'state_changed_during_judgment'
    assert not p.store.operations()


def test_export_only_reached_results_and_underlying_dataset_identity(tmp_path, pair):
    p = make(tmp_path, pair)
    run(p, 2)
    h = p.export()
    assert set(h['source_research_ids']) == {e.workspace.research_id for e in pair}
    world = ReplayWorld(h, budget=2)
    assert len(world.view()) == 1
    assert 'outcome' not in world.view()[0].public()
    with pytest.raises(UnsupportedAction):
        world.step('made-up')
    world.step(world.view()[0].id)
    assert len(world.view()) == 1


def test_portfolio_alias_cannot_hide_dataset_leakage():
    from sisyfus.research_os.lab import optimize
    a = {'research_id': 'portfolio-a', 'family': 'A', 'source_research_ids': ['same-underlying-run'], 'nodes': []}
    b = {'research_id': 'portfolio-b', 'family': 'B', 'source_research_ids': ['same-underlying-run'], 'nodes': []}
    c = {'research_id': 'portfolio-c', 'family': 'C', 'nodes': []}
    with pytest.raises(ValueError, match='disjoint'):
        optimize([a], [b], [c], budget=1)


def test_registration_pins_latest_not_a_moving_alias(tmp_path, pair):
    p = make(tmp_path, pair)
    assert p.projects['a']['research_id'] == pair[0].workspace.research_id
    new = ResearchEngine.create(pair[0].workspace.root, pair[0].task, render=False)
    assert new.workspace.research_id != pair[0].workspace.research_id
    reloaded = Portfolio(tmp_path / 'portfolio')
    run(reloaded, 1)
    assert not new.snapshot()['attempts']


@pytest.mark.parametrize('budget', [
    {'max_attempts': True, 'max_cost_units': 2}, {'max_attempts': 0, 'max_cost_units': 2},
    {'max_attempts': 2, 'max_cost_units': float('nan')}, {'max_attempts': 2, 'max_cost_units': -1},
    {'max_attempts': 2},
])
def test_budget_validation_before_registration(tmp_path, pair, budget):
    with pytest.raises(ValueError):
        make(tmp_path, pair, budget=budget)
    assert not (tmp_path / 'portfolio').exists()


@pytest.mark.parametrize('fault', ['cycle', 'missing-project', 'missing-claim', 'alias', 'duplicate', 'relative'])
def test_bad_graph_registration(tmp_path, pair, fault):
    raw = spec(pair)
    if fault == 'cycle':
        raw['projects'][0]['requires'] = [{'project': 'b', 'claim': 'c1'}]
        raw['projects'][1]['requires'] = [{'project': 'a', 'claim': 'c1'}]
    elif fault == 'missing-project':
        raw['projects'][0]['requires'] = [{'project': 'unknown', 'claim': 'c1'}]
    elif fault == 'missing-claim':
        raw['projects'][0]['requires'] = [{'project': 'b', 'claim': 'missing'}]
    elif fault == 'alias':
        raw['projects'][1]['root'] = raw['projects'][0]['root']
    elif fault == 'duplicate':
        raw['projects'][1]['id'] = 'a'
    else:
        raw['projects'][1]['root'] = 'relative/path'
    with pytest.raises(ValueError):
        Portfolio.create(tmp_path / 'p', raw, actor='operator')
    assert not (tmp_path / 'p').exists()


def test_manifest_and_event_chain_tampering(tmp_path, pair):
    p = make(tmp_path, pair)
    path = p.store.root / 'manifest.json'
    old = path.read_text()
    raw = json.loads(old); raw['budget']['max_cost_units'] = 999
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match='manifest'):
        p.status()
    path.write_text(old)
    path = p.store.root / 'events.jsonl'
    path.write_text(path.read_text().replace('REGISTERED', 'FORGED'))
    with pytest.raises(ValueError, match='chain'):
        p.status()


def test_torn_event_is_not_silently_discarded(tmp_path, pair):
    p = make(tmp_path, pair)
    with (p.store.root / 'events.jsonl').open('a') as f:
        f.write('{"unfinished":')
    with pytest.raises(ValueError, match='torn'):
        p.status()


def test_permission_is_required(tmp_path, pair):
    p = make(tmp_path, pair)
    with pytest.raises(PermissionError):
        p.run()
    assert not p.store.operations()


def test_cli_demo_and_readonly_status(tmp_path, capsys):
    from sisyfus.research_os.cli import main
    root = tmp_path / 'demo'
    assert main(['portfolio', 'demo', '--directory', str(root)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary['order_after_restart'] == ['reference', 'dependent', 'independent']
    assert summary['verdicts'] == ['PASS'] * 3
    assert summary['budget']['cost_used'] == 3
    assert summary['member_replay_valid']
    assert not summary['real_llm_executed']
    event_path = root / 'registry' / 'events.jsonl'
    before = event_path.read_bytes()
    assert main(['portfolio', 'status', '--directory', str(root / 'registry')]) == 0
    capsys.readouterr()
    assert event_path.read_bytes() == before


def test_portfolio_dispatch_cannot_masquerade_as_local_policy_trial(tmp_path, pair):
    from sisyfus.research_os.lab import validate_fresh_trials
    p = make(tmp_path, pair)
    run(p, 1)
    fixed = SchedulingPolicy()
    report = {'status': 'REPLAY_ONLY', 'candidate': asdict(fixed),
              'candidate_hash': fixed.hash, 'baseline_hash': fixed.hash,
              'source_research_ids': [], 'source_families': []}
    report['report_hash'] = digest(report)
    with pytest.raises(ValueError, match='portfolio-dispatched'):
        validate_fresh_trials(report, pair, list(reversed(pair)))
