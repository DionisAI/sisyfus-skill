from __future__ import annotations
import copy
import hashlib
import sys
import pytest
from sisyfus.workers.lead_contracts import load_lead_spec, optional_limit, paths_overlap, validate_plan, write_path

def specification(tmp_path):
    source = tmp_path / "project"
    source.mkdir()
    (source / "module.py").write_text("value = 0\n")
    check = tmp_path / "trusted_check.py"
    check.write_text("import json; print(json.dumps({'accepted': True}))\n")
    return load_lead_spec({"source": str(source), "objective": "Implement a verified module",
        "checks": {"acceptance": {"argv": [sys.executable, str(check), "{candidate}"],
            "code_hashes": {str(check): hashlib.sha256(check.read_bytes()).hexdigest()},
            "contract": {"kind": "rules", "pass_if": {"all": [{"path": "accepted", "op": "eq", "value": True}]},
                         "fail_if": {"all": [{"path": "accepted", "op": "eq", "value": False}]}}}}})

def plan(tasks):
    return {"architecture": "Separate reusable modules and explicit interfaces", "interfaces": ["value:int"], "tasks": tasks}

def task(ident="build", paths=None, deps=None):
    return {"id": ident, "objective": "Implement module output", "check": "acceptance", "write_paths": paths or ["module.py"],
            "acceptance": "External acceptance suite passes", "depends_on": deps or []}

def test_defaults_are_genuinely_unlimited_and_models_explicit(tmp_path):
    spec = specification(tmp_path)
    for key in ("max_calls", "max_iterations", "max_tokens", "max_cost_usd", "max_wall_minutes", "max_turns"):
        assert spec[key] is None
    assert spec["roles"]["lead"]["model"] == "claude-opus-5-5"
    assert spec["roles"]["reviewer"]["model"] == "claude-opus-5-5"
    assert spec["roles"]["worker"]["model"] == "gpt-6.1-sol"
    assert spec["rsi"]["auto_promote"] is True

@pytest.mark.parametrize("value", [0, -1, True, float('inf'), float('nan'), 'unlimited'])
def test_invalid_aggregate_budgets_visible(value):
    with pytest.raises(ValueError): optional_limit(value, "max_calls", integer=True)

@pytest.mark.parametrize("value", ["../file", "/tmp/file", ".git/config", ".sisyfus/state", "inputs/dep", "src/../file", "*", ".", "src\\file"])
def test_task_ownership_cannot_escape_or_target_controller(value):
    with pytest.raises(ValueError): write_path(value)

def test_parallel_scope_conflict_is_rejected(tmp_path):
    spec = specification(tmp_path)
    with pytest.raises(ValueError, match="write conflict"):
        validate_plan(plan([task('auth', ['src/auth']), task('session', ['src/auth/session.py'])]), spec)

def test_disjoint_parallel_tasks_and_serial_shared_scope(tmp_path):
    spec = specification(tmp_path)
    assert len(validate_plan(plan([task('auth', ['src/auth']), task('export', ['src/export'])]), spec)['tasks']) == 2
    accepted = validate_plan(plan([task('auth'), task('review_changes', deps=['auth'])]), spec)
    assert accepted['tasks'][1]['driver'] == 'codex'

def test_plan_cannot_choose_models_commands_or_change_acceptance(tmp_path):
    spec = specification(tmp_path)
    for field in ('driver', 'command', 'contract', 'model', 'max_attempts'):
        value = task(); value[field] = 'unapproved'
        with pytest.raises(ValueError, match='unknown task'):
            validate_plan(plan([value]), spec)
    bad = plan([task()]); bad['checks'] = {}
    with pytest.raises(ValueError): validate_plan(bad, spec)

def test_cycle_missing_dependencies_and_missing_contracts(tmp_path):
    spec = specification(tmp_path)
    for entries in ([task('a', deps=['b']), task('b', deps=['a'])], [task('a', deps=['missing'])]):
        with pytest.raises(ValueError, match='dependency'): validate_plan(plan(entries), spec)
    bad = task(); bad['check'] = 'unknown'
    with pytest.raises(ValueError): validate_plan(plan([bad]), spec)

def test_historical_ids_are_immutable_and_repair_lineage_is_explicit(tmp_path):
    spec = specification(tmp_path)
    prior = validate_plan(plan([task()]), spec)['tasks']
    with pytest.raises(ValueError, match='historical'): validate_plan(plan([task()]), spec, existing=prior)
    repair = task('build_repair'); repair['repair_of'] = 'build'
    fixed = validate_plan(plan([repair]), spec, existing=prior)
    assert fixed['tasks'][0]['repair_of'] == 'build'

def test_unlimited_mission_has_no_lifetime_dag_size_ceiling(tmp_path):
    spec = specification(tmp_path)
    prior = []
    for i in range(40):
        entries = [task(f'task{i}', [f'module{i}.py'])]
        prior.extend(validate_plan(plan(entries), spec, existing=prior)['tasks'])
    assert len(prior) == 40

def test_checks_must_be_hash_pinned_and_outside_candidate(tmp_path):
    spec = specification(tmp_path)
    changed = copy.deepcopy(spec)
    code = next(iter(changed['checks']['acceptance']['code_hashes']))
    changed['checks']['acceptance']['code_hashes'][code] = '0' * 64
    # Resubmit only the public operator fields, not normalized controller fields.
    raw = {k:changed[k] for k in ('objective','source','checks')}
    with pytest.raises(ValueError, match='hash'): load_lead_spec(raw)

def test_operator_check_timeout_is_used_and_validated(tmp_path):
    spec = specification(tmp_path)
    raw = {k: spec[k] for k in ('objective', 'source', 'checks')}
    raw['checks']['acceptance'].pop('timeout', None)
    raw['check_timeout'] = 12
    assert load_lead_spec(raw)['checks']['acceptance']['timeout'] == 12
    raw['checks']['acceptance']['timeout'] = 8
    assert load_lead_spec(raw)['checks']['acceptance']['timeout'] == 8
    raw['check_timeout'] = True
    with pytest.raises(ValueError, match='check_timeout'): load_lead_spec(raw)

def test_malformed_task_and_root_scope_fail_with_clear_errors(tmp_path):
    spec = specification(tmp_path)
    bad = task(); bad['id'] = {'unexpected': 'object'}
    with pytest.raises(ValueError, match='identity'): validate_plan(plan([bad]), spec)
    for path in ('.//', 'src\0/file'):
        with pytest.raises(ValueError): write_path(path)
