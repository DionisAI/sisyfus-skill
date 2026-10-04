from __future__ import annotations

import json
import sys
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from sisyfus.research_os.controller import PREFIX, ResearchOS, configuration, configure, coordinator_lock, export_history
from sisyfus.research_os.demo import create_demo
from sisyfus.research_os.frontier import ready_frontier
from sisyfus.research_os.judgments import CallableJudge, JevJudge, assess_safely
from sisyfus.research_os.lab import optimize, promote, record_candidate, validate_fresh_trials
from sisyfus.research_os.models import Candidate, Judgment, SOP, digest
from sisyfus.research_os.policy import SchedulingPolicy, fit_policy
from sisyfus.research_os.replay import ReplayWorld, UnsupportedAction, evaluate_replay
from sisyfus.research_v2.engine import ResearchEngine


@pytest.fixture(autouse=True)
def lightweight_render(monkeypatch):
    # Keep engine persistence/evidence real; skip unrelated expensive HTML in unit tests.
    original = ResearchEngine._persist
    monkeypatch.setattr(ResearchEngine, "_persist", lambda self, snapshot, *, render: original(self, snapshot, render=False))


@pytest.fixture
def engine(tmp_path):
    return create_demo(tmp_path, "square")


def run(engine, **kwargs):
    return ResearchOS(engine, **kwargs).run(max_steps=6, allow_local_commands=True)


def test_real_closed_loop_records_positive_and_negative_evidence(engine):
    report = run(engine)
    assert report.steps == 3
    assert report.cost_units == 3
    assert report.stop_reason == "no_ready_action"
    assert sorted(r["verdict"] for r in report.results) == ["FAIL", "FAIL", "PASS"]
    assert engine.verify_replay()["deterministic"]
    assert run(engine).steps == 0
    history = export_history(engine)
    assert len(history["nodes"]) == 3
    assert sum(n["outcome"]["label"] for n in history["nodes"]) == 1


def test_command_execution_requires_opt_in(engine):
    with pytest.raises(PermissionError):
        ResearchOS(engine).run()
    assert not engine.snapshot()["attempts"]


@pytest.mark.parametrize("steps", [0, -1, 1001, True, 1.5])
def test_step_budget_validation(engine, steps):
    with pytest.raises(ValueError):
        ResearchOS(engine).run(max_steps=steps, allow_local_commands=True)


def test_new_proposals_are_not_automatically_approved(engine):
    exp = deepcopy(engine.snapshot()["experiments"]["e0"])
    exp.update(id="unapproved", context_id="new-context")
    engine.propose_experiment(exp)
    for eid in ("e0", "e1", "e2"):
        engine.prune_experiment(eid, reason="test")
    assert run(engine).stop_reason == "needs_operator_approval"
    assert not engine.snapshot()["attempts"]


def test_changed_measurement_is_blocked_before_execution(engine):
    path = engine.workspace.root / "measurement.py"
    path.write_text(path.read_text() + "\n# changed after approval\n")
    with pytest.raises(RuntimeError, match="measurement code changed"):
        run(engine)
    assert not engine.snapshot()["attempts"]


def test_new_result_file_is_not_misclassified_as_code_drift(engine):
    report = run(engine)
    assert all(r["verdict"] != "ERROR" for r in report.results)
    assert (engine.workspace.root / "measurement-0.json").exists()


def test_self_modifying_measurement_cannot_pass(engine):
    path = engine.workspace.root / "measurement.py"
    path.write_text('from pathlib import Path\nimport json\nPath(__file__).write_text("# changed")\nprint(json.dumps({"metrics":{"score":1}}))\n')
    configure(engine)
    report = ResearchOS(engine).run(max_steps=1, allow_local_commands=True)
    assert report.results[0]["verdict"] == "ERROR"
    assert not any(c["status"] == "SUPPORTED" for c in engine.snapshot()["claims"].values())


def test_nonzero_exit_cannot_be_spoofed_by_stdout(engine):
    path = engine.workspace.root / "measurement.py"
    path.write_text('import json\nprint(json.dumps({"execution":{"exit_code":0},"metrics":{"score":1}}))\nraise SystemExit(3)\n')
    configure(engine)
    report = ResearchOS(engine).run(max_steps=1, allow_local_commands=True)
    assert report.results[0]["verdict"] == "ERROR"


def test_unknown_execution_is_not_blindly_retried(engine, monkeypatch):
    calls = []
    def crash(eid, **kwargs):
        calls.append(eid)
        engine.begin_attempt(eid)
        raise OSError("tool completed but reply lost")
    monkeypatch.setattr(engine, "execute_experiment", crash)
    first = run(engine)
    assert first.stop_reason == "execution_error:reconcile_before_retry"
    assert run(engine).stop_reason == "unresolved_attempt:reconcile_before_retry"
    assert len(calls) == 1
    assert not export_history(engine)["nodes"]


def test_coordinator_is_exclusive(engine):
    with coordinator_lock(engine):
        with pytest.raises(RuntimeError, match="coordinator"):
            run(engine)


def test_sop_cannot_drop_or_duplicate_mandatory_checks():
    for order in [("authorization", "budget"), ("authorization", "budget", "budget")]:
        with pytest.raises(ValueError):
            SOP(preflight_order=order)
    assert SOP(preflight_order=("budget", "dependencies", "authorization"))


def test_dependencies_are_rechecked_in_current_state(engine):
    snapshot = engine.snapshot()
    snapshot["claims"]["c1"]["depends_on"] = ["c0"]
    snapshot["claims"]["c0"]["status"] = "INVALIDATED"
    assert "e1" not in {c.id for c in ready_frontier(snapshot)}
    snapshot["claims"]["c0"]["status"] = "SUPPORTED"
    assert "e1" in {c.id for c in ready_frontier(snapshot)}
    snapshot["claims"]["c0"]["contested"] = True
    assert "e1" not in {c.id for c in ready_frontier(snapshot)}


def test_hidden_evaluation_excluded(engine):
    snapshot = engine.snapshot()
    snapshot["experiments"]["e0"]["visibility"] = "host_only"
    snapshot["contracts"]["v1"]["visibility"] = "host_only"
    assert [c.id for c in ready_frontier(snapshot)] == ["e2"]


def test_budget_excludes_unaffordable_actions(engine):
    snapshot = engine.snapshot()
    snapshot["budget"]["cost_units_remaining"] = 0.5
    assert ready_frontier(snapshot) == []


def test_state_change_during_judgment_prevents_execution(engine):
    class PauseJudge:
        def assess(self, candidates):
            engine.pause(reason="operator paused")
            return {c.id: Judgment() for c in candidates}
    report = run(engine, judge=PauseJudge())
    assert report.stop_reason == "state_changed:replan"
    assert not engine.snapshot()["attempts"]


def test_optimistic_judge_cannot_create_success(engine):
    judge = CallableJudge(lambda candidates: {c["id"]: {"actionable": 1, "duplicate": 0} for c in candidates})
    report = run(engine, judge=judge)
    assert sum(r["verdict"] == "PASS" for r in report.results) == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1, True, "0.9"])
def test_invalid_judgment_rejected(value):
    with pytest.raises(ValueError):
        Judgment(actionable=value)


def test_judge_failure_falls_back_without_leaking_exception(engine):
    def broken(_):
        raise RuntimeError("secret-credential")
    candidates = ready_frontier(engine.snapshot())
    answers = assess_safely(CallableJudge(broken), candidates)
    assert all(j.provider == "fallback" for j in answers.values())
    assert "secret-credential" not in json.dumps({k: asdict(v) for k, v in answers.items()})


def test_jev_sdk_contract_and_minimal_payload(engine, monkeypatch):
    monkeypatch.setitem(sys.modules, "typesafe_sdk", SimpleNamespace(Noul=lambda **kw: kw))
    class Client:
        def system_one(self, *, state, questions):
            assert len(state) == 3 and len(questions) == 6
            assert all(set(v) == {"title", "rationale"} for v in state.values())
            return SimpleNamespace(nouls={k: SimpleNamespace(noul=0.7) for k in questions})
    result = JevJudge(Client()).assess(ready_frontier(engine.snapshot()))
    assert all(j.actionable == 0.7 for j in result.values())


def test_ledger_not_os_result_is_the_label_source(engine):
    run(engine)
    before = export_history(engine)
    engine.workspace.append_event(PREFIX + "RESULT", actor="test", data={"verdict": "PASS", "label": 1, "attempt_id": "fake"})
    after = export_history(engine)
    assert before["nodes"] == after["nodes"]


def test_duplicate_decision_does_not_duplicate_evidence(engine):
    run(engine)
    decision = next(e for e in engine.events if e["event_type"] == PREFIX + "DECISION")
    engine.workspace.append_event(PREFIX + "DECISION", actor="crash-recovery-test", data=decision["data"])
    history = export_history(engine)
    assert len(history["nodes"]) == len({n["outcome"]["evidence_id"] for n in history["nodes"]}) == 3


def history(name="a", family="a"):
    candidate = Candidate("e", name, family, "proposal", "a bounded test", (0.5, 0.5, 0, 0, 0, 0), 1, "contract", "action")
    nodes = []
    for i in range(3):
        c = {**candidate.public(), "id": f"e{i}", "features": [0.5, i / 2, 0, 0, 0, 0]}
        nodes.append({"id": f"n{i}", "candidate": c, "available_after": [],
                      "outcome": {"verdict": "PASS" if i == 2 else "FAIL", "label": int(i == 2), "cost_units": 1, "evidence_id": f"ev{i}", "evidence_hash": f"hash{i}"},
                      "provenance": {"policy_hash": "fixture"}})
    return {"schema": "sisyfus.replay.v1", "research_id": name, "family": family, "nodes": nodes}


def test_replay_never_exposes_outcomes_in_policy_view():
    world = ReplayWorld(history(), budget=2)
    assert all(not ({"outcome", "label", "evidence_id"} & asdict(c).keys()) for c in world.view())
    assert len(world.observations) == 0
    world.step("n0")
    assert len(world.observations) == 1


def test_replay_rejects_unknown_repeated_and_overbudget_actions():
    world = ReplayWorld(history(), budget=1)
    with pytest.raises(UnsupportedAction):
        world.step("unrecorded")
    world.step("n0")
    for action in ("n0", "n1"):
        with pytest.raises(UnsupportedAction):
            world.step(action)


def test_replay_does_not_jump_over_unreached_parent():
    h = history()
    h["nodes"][2]["available_after"] = ["n1"]
    h["nodes"][1]["available_after"] = ["n0"]
    w = ReplayWorld(h, budget=3)
    assert [c.id for c in w.view()] == ["n0"]
    with pytest.raises(UnsupportedAction):
        w.step("n2")


@pytest.mark.parametrize("mutation", ["cycle", "unknown_parent", "duplicate", "cost", "label"])
def test_corrupted_replay_rejected(mutation):
    h = history()
    if mutation == "cycle":
        h["nodes"][0]["available_after"] = ["n0"]
    elif mutation == "unknown_parent":
        h["nodes"][0]["available_after"] = ["missing"]
    elif mutation == "duplicate":
        h["nodes"].append(h["nodes"][0])
    elif mutation == "cost":
        h["nodes"][0]["outcome"]["cost_units"] = 0
    else:
        h["nodes"][0]["outcome"]["label"] = 1
    with pytest.raises(ValueError):
        ReplayWorld(h, budget=3)


def test_replay_refuses_to_invent_jev_outputs():
    with pytest.raises(ValueError, match="counterfactual"):
        evaluate_replay(history(), SchedulingPolicy(judgment_weight=1), budget=2)


def test_training_changes_model_weights_and_predictions():
    h = history()
    rows = [{"candidate": n["candidate"], "label": n["outcome"]["label"]} for n in h["nodes"]] * 8
    model = fit_policy(rows)
    assert model.learned
    assert model.predict(tuple(rows[2]["candidate"]["features"])) > model.predict(tuple(rows[0]["candidate"]["features"]))


def test_task_family_leakage_is_rejected():
    with pytest.raises(ValueError, match="disjoint"):
        optimize([history("a", "same")], [history("b", "same")], [history("c", "other")], budget=2)


def test_holdout_outcomes_cannot_affect_policy_selection():
    train, search, test = [history("train", "train")], [history("search", "search")], [history("test", "test")]
    first = optimize(train, search, test, budget=1)
    for n in test[0]["nodes"]:
        n["outcome"].update(verdict="PASS", label=1)
    second = optimize(train, search, test, budget=1)
    assert first["candidate_hash"] == second["candidate_hash"]
    assert first["status"] == "REPLAY_ONLY"


def test_replay_report_cannot_authorize_promotion(engine):
    report = optimize([history("train", "train")], [history("search", "search")], [history("test", "test")], budget=1)
    before = configuration(engine)
    record_candidate(engine, report)
    with pytest.raises(ValueError, match="fresh matched"):
        promote(engine, report, [], [], approver="operator")
    assert configuration(engine) == before


def test_forged_candidate_report_is_rejected(engine):
    report = optimize([history("train", "train")], [history("search", "search")], [history("test", "test")], budget=1)
    report["candidate"]["bias"] = 3
    with pytest.raises(ValueError):
        record_candidate(engine, report)
    with pytest.raises(ValueError):
        validate_fresh_trials(report, [], [])


def test_main_cli_exposes_research_os():
    from sisyfus.cli import build_parser
    args = build_parser().parse_args(["os", "frontier", "--root", "/tmp/project"])
    assert args.os_command == "frontier"


def test_late_decision_cannot_change_executed_training_features(engine):
    run(engine)
    before = export_history(engine)
    decision = deepcopy(next(e["data"] for e in engine.events if e["event_type"] == PREFIX + "DECISION"))
    decision["candidates"][0]["features"] = [0, 0, 0, 0, 0, 0]
    engine.workspace.append_event(PREFIX + "DECISION", actor="test-late-event", data=decision)
    assert export_history(engine)["nodes"] == before["nodes"]


def test_unknown_execution_cost_stays_reserved(engine, monkeypatch):
    def crash(eid, **kwargs):
        engine.begin_attempt(eid)
        raise OSError("reply missing")
    monkeypatch.setattr(engine, "execute_experiment", crash)
    report = run(engine)
    assert report.reserved_cost_units == 1
    assert len(report.unresolved_attempts) == 1
    assert report.cost_units == 0  # committed cost, not a claim the action was free


def test_proposal_worker_adds_unapproved_experiments(engine):
    from sisyfus.autonomy.models import Decision
    from sisyfus.research_os.proposals import propose_next
    before = configuration(engine)
    proposal = deepcopy(engine.snapshot()["experiments"]["e0"])
    proposal.update(id="next-idea", context_id="new-design")
    seen = []
    def planner(continuation, context):
        seen.append(context)
        return Decision("EXECUTE", "investigate the failure", capability="research.propose", arguments={"experiments": [proposal]})
    result = propose_next(engine, planner)
    assert result["proposed"] == ["next-idea"]
    assert not result["new_commands_approved"]
    assert "research_os" in seen[0]
    assert configuration(engine) == before
    assert not engine.snapshot()["attempts"]


@pytest.mark.parametrize("kind,capability", [("EXECUTE", "shell"), ("FINISH", None)])
def test_proposal_worker_cannot_execute_or_self_certify(engine, kind, capability):
    from sisyfus.autonomy.models import Decision
    from sisyfus.research_os.proposals import propose_next
    def planner(*_):
        return Decision(kind, "I say done", capability=capability, evidence_id="invented")
    with pytest.raises(ValueError, match="only propose"):
        propose_next(engine, planner)
    assert not engine.snapshot()["attempts"]


def test_existing_command_planner_can_propose_without_executing(engine):
    from sisyfus.autonomy.adapters import CommandPlanner
    from sisyfus.research_os.proposals import propose_next
    proposal = deepcopy(engine.snapshot()["experiments"]["e0"])
    proposal.update(id="worker-idea", context_id="worker-context")
    payload = {"kind": "EXECUTE", "reason": "try next", "capability": "research.propose", "arguments": {"experiments": [proposal]}}
    script = engine.workspace.root / "proposal_worker.py"
    script.write_text("import json, os\nfrom pathlib import Path\n" + "Path(os.environ['SISYFUS_AUTONOMY_RESPONSE_PATH']).write_text(" + repr(json.dumps(payload)) + ")\n")
    response = propose_next(engine, CommandPlanner([sys.executable, str(script)], engine.workspace.root, timeout_seconds=5))
    assert response["proposed"] == ["worker-idea"]
    assert not engine.snapshot()["attempts"]


def fresh_trial(root, episode, pair_id, policy):
    """Tiny real paired gate test, not a benchmark of LLM research quality."""
    import shlex
    from pathlib import Path
    from sisyfus.research_os import measurement
    root.mkdir(parents=True)
    (root / "measure.py").write_text(Path(measurement.__file__).read_text())
    spec = {
        "id": episode, "topic": "Frozen square check",
        "claims": [{"id": "c", "statement": "Candidate matches square on frozen cases"}],
        "verification_contracts": [{"id": "v", "target_claim_id": "c",
            "pass_if": [{"path": "metrics.score", "op": "==", "value": 1.0}],
            "fail_if": [{"path": "metrics.score", "op": "<", "value": 1.0}]}],
        "budget": {"max_attempts": 3, "max_cost_units": 3},
        "stop_policy": {"stop_on_goal_pass": False, "stop_on_goal_refuted": False},
        "metadata": {"task_family": "fresh-" + pair_id, "evaluation_pair_id": pair_id},
    }
    e = ResearchEngine.create(root, spec, render=False)
    for i, expression in enumerate(("x", "x*x")):
        (root / f"candidate-{i}.json").write_text(json.dumps({"expression": expression}))
        argv = [sys.executable, "-I", "measure.py", "--candidate", f"candidate-{i}.json", "--family", "square", "--output", f"out-{i}.json"]
        e.propose_experiment({
            "id": f"e{i}", "title": f"Candidate {i}", "target_claim_ids": ["c"], "contract_id": "v", "context_id": str(i),
            "action": {"kind": "command", "command": shlex.join(argv), "cwd": str(root), "timeout_seconds": 5,
                       "parse_stdout_json": True, "code_paths": ["measure.py", f"candidate-{i}.json"]},
            "expected_outcomes": {"pass": "supports", "fail": "refutes", "inconclusive": "uncertain", "invalid": "bad check"},
            "cost": {"units": 1}, "priority": {"goal_progress": 1-i, "information_gain": 1-i, "novelty": i},
        })
    configure(e, policy=policy)
    ResearchOS(e).run(max_steps=1, allow_local_commands=True)
    return e


def paired_gate_fixture(tmp_path):
    # Hand-built policy candidate isolates promotion mechanics. No claimed learning gain.
    report = optimize([history("train", "train")], [history("search", "search")], [history("test", "test")], budget=1)
    candidate = SchedulingPolicy(name="gate-test-novelty", weights=(0, 0, 0, 1, 0, 0))
    report.update(candidate=asdict(candidate), candidate_hash=candidate.hash)
    report["report_hash"] = digest({k: v for k, v in report.items() if k != "report_hash"})
    baseline, challenger = [], []
    for i in range(2):
        baseline.append(fresh_trial(tmp_path / f"baseline-{i}", f"baseline-{i}", f"pair-{i}", SchedulingPolicy()))
        challenger.append(fresh_trial(tmp_path / f"challenger-{i}", f"challenger-{i}", f"pair-{i}", candidate))
    return report, baseline, challenger


def test_operator_promotion_requires_real_matched_nonregressing_trials(engine, tmp_path):
    report, baseline, challenger = paired_gate_fixture(tmp_path)
    result = validate_fresh_trials(report, baseline, challenger)
    assert result["eligible_for_operator_review"]
    assert not result["automatically_activated"]
    original = configuration(engine)
    assert original["policy"] != report["candidate"]
    record_candidate(engine, report)
    promoted = promote(engine, report, baseline, challenger, approver="test-operator")
    assert promoted["activated"]
    assert configuration(engine)["approvals"] == original["approvals"]
    assert configuration(engine)["sop"] == original["sop"]
    assert digest(configuration(engine)["policy"]) == digest(report["candidate"])


def test_changed_evaluator_inputs_in_fresh_pairs_are_rejected(tmp_path):
    report, baseline, challenger = paired_gate_fixture(tmp_path)
    path = challenger[0].workspace.root / "candidate-0.json"
    path.write_text(json.dumps({"expression": "x*x"}))
    configure(challenger[0], policy=SchedulingPolicy.load(report["candidate"]))
    with pytest.raises(ValueError, match="inputs|mixed"):
        validate_fresh_trials(report, baseline, challenger)


def test_same_policy_fresh_pairs_do_not_demonstrate_improvement(tmp_path):
    report = optimize([history("train", "train")], [history("search", "search")], [history("test", "test")], budget=1)
    fixed = SchedulingPolicy()
    report.update(candidate=asdict(fixed), candidate_hash=fixed.hash)
    report["report_hash"] = digest({k: v for k, v in report.items() if k != "report_hash"})
    baseline = [fresh_trial(tmp_path / f"b{i}", f"b{i}", f"pair{i}", fixed) for i in range(2)]
    challenger = [fresh_trial(tmp_path / f"c{i}", f"c{i}", f"pair{i}", fixed) for i in range(2)]
    assert not validate_fresh_trials(report, baseline, challenger)["eligible_for_operator_review"]


def test_invalid_priority_skips_only_bad_candidate(engine):
    snapshot = engine.snapshot()
    snapshot["experiments"]["e1"]["priority"]["goal_progress"] = 2
    ids = {c.id for c in ready_frontier(snapshot)}
    assert "e1" not in ids
    assert ids  # Other valid candidates remain visible.
