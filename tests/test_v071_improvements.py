from pathlib import Path
import json

from sisyfus.cli import main as cli_main
from sisyfus.research_v2.engine import ResearchEngine


def spec(task_id="v071-test", *, repetition=False, stop_policy=None, claims=None, contracts=None):
    contract = {
        "id": "verify-c1",
        "target_claim_id": "c1",
        "pass_if": {"all": [{"path": "metrics.score", "op": ">=", "value": 0.7}]},
        "fail_if": {"all": [{"path": "metrics.score", "op": "<", "value": 0.3}]},
    }
    if repetition:
        contract["repetition"] = {"min_passes": 2, "min_independent_contexts": 2}
    value = {
        "id": task_id,
        "topic": "v0.7.1 improvement test",
        "claims": claims or [{"id": "c1", "statement": "Candidate works"}],
        "verification_contracts": contracts or [contract],
        "budget": {"max_attempts": 12, "max_cost_units": 12},
    }
    if stop_policy:
        value["stop_policy"] = stop_policy
    return value


def experiment(exp_id, *, claim="c1", contract="verify-c1", context="a", action=None,
               from_state_id=None, mode="validate", note=None):
    value = {
        "id": exp_id,
        "title": exp_id,
        "target_claim_ids": [claim],
        "contract_id": contract,
        "context_id": context,
        "mode": mode,
        "action": action or {"kind": "external"},
        "expected_outcomes": {
            "pass": "supports",
            "fail": "refutes",
            "inconclusive": "uncertain",
            "invalid": "bad measurement",
        },
        "cost": {"units": 1},
    }
    if from_state_id:
        value["from_state_id"] = from_state_id
    if note:
        value["discriminating_note"] = note
    return value


def settle(engine, exp_id, score):
    attempt = engine.begin_attempt(exp_id)
    return engine.settle_attempt(attempt["id"], {"metrics": {"score": score}})


def initial_state_id(engine):
    snapshot = engine.snapshot()
    return next(s["id"] for s in snapshot["states"].values() if s["seq"] == 0)


def test_falsify_mode_is_valid(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, spec())
    result = engine.propose_experiment(experiment("e-fals", mode="falsify"))
    assert result["admission"]["accepted"]
    assert result["experiment"]["mode"] == "falsify"


def test_code_hashes_recorded_and_change_detected(tmp_path: Path):
    script = tmp_path / "measure.py"
    script.write_text("import json; print(json.dumps({'metrics': {'invalid': True}}))\n")
    contract = {
        "id": "verify-c1",
        "target_claim_id": "c1",
        "invalid_if": {"any": [{"path": "metrics.invalid", "op": "==", "value": True}]},
        "pass_if": {"all": [{"path": "metrics.score", "op": ">=", "value": 0.7}]},
        "fail_if": {"all": [{"path": "metrics.score", "op": "<", "value": 0.3}]},
    }
    engine = ResearchEngine.create(tmp_path, spec(contracts=[contract]))
    action = {
        "kind": "command",
        "command": "python3 measure.py",
        "cwd": str(tmp_path),
        "parse_stdout_json": True,
    }
    engine.propose_experiment(experiment("e-cmd", action=action))
    first = engine.execute_experiment("e-cmd")
    assert first["verdict"]["status"] == "INVALID"
    snapshot = engine.snapshot()
    first_attempt = snapshot["attempts"]["attempt-e-cmd-01"]
    assert "measure.py" in first_attempt["code_hashes"]
    assert first_attempt["code_hashes"]["measure.py"].startswith("sha256:")
    assert first["evidence"]["code_hashes"] == first_attempt["code_hashes"]

    # measurement code silently changes between attempts -> flagged
    script.write_text("import json; print(json.dumps({'metrics': {'score': 0.9}}))\n")
    second = engine.execute_experiment("e-cmd")
    assert second["verdict"]["status"] == "PASS"
    snapshot = engine.snapshot()
    second_attempt = snapshot["attempts"]["attempt-e-cmd-02"]
    assert second_attempt["code_changed_since_last_attempt"] is True


def test_contested_claim_blocks_solve_until_discriminating_note(tmp_path: Path):
    engine = ResearchEngine.create(
        tmp_path, spec(stop_policy={"require_uncontested_solve": True})
    )
    root = initial_state_id(engine)
    engine.propose_experiment(experiment("e-fail", context="a"))
    settled = settle(engine, "e-fail", 0.1)
    assert settled["verdict"]["status"] == "FAIL"

    # branch from the pre-FAIL checkpoint and pass WITHOUT a note -> contested
    engine.propose_experiment(experiment("e-pass", context="b", from_state_id=root))
    settle(engine, "e-pass", 0.9)
    snapshot = engine.snapshot()
    assert snapshot["claims"]["c1"]["status"] == "SUPPORTED"
    assert snapshot["claims"]["c1"]["contested"] is True
    assert snapshot["claims"]["c1"]["contest_resolved_by"] is None
    assert snapshot["contested_claims"] == ["c1"]
    assert snapshot["run_status"] == "ACTIVE"
    assert snapshot["terminal_assessment"] == "CONTESTED"
    try:
        engine.finalize(status="solved")
        raise AssertionError("finalize should refuse a contested SOLVED")
    except RuntimeError as exc:
        assert "contested" in str(exc)

    # a later PASS carrying a discriminating note resolves the contest
    engine.propose_experiment(
        experiment("e-resolve", context="c", from_state_id=root,
                   note="new measurement isolates the confounder that produced the earlier FAIL")
    )
    settle(engine, "e-resolve", 0.9)
    snapshot = engine.snapshot()
    assert snapshot["claims"]["c1"]["contest_resolved_by"] == "e-resolve"
    assert snapshot["contested_claims"] == []
    assert snapshot["run_status"] == "SOLVED"
    replay = engine.verify_replay()
    assert replay["deterministic"] and replay["event_chain_valid"]


def test_contested_is_visible_but_not_blocking_by_default(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, spec())
    root = initial_state_id(engine)
    engine.propose_experiment(experiment("e-fail", context="a"))
    settle(engine, "e-fail", 0.1)
    engine.propose_experiment(experiment("e-pass", context="b", from_state_id=root))
    settle(engine, "e-pass", 0.9)
    snapshot = engine.snapshot()
    assert snapshot["claims"]["c1"]["contested"] is True
    assert snapshot["contested_claims"] == ["c1"]
    assert snapshot["run_status"] == "SOLVED"  # backward-compatible default


def test_lesson_evidence_add_enables_promotion(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, spec(repetition=True))
    engine.propose_experiment(experiment("e1", context="a"))
    settle(engine, "e1", 0.9)
    engine.propose_experiment(experiment("e2", context="b"))
    settle(engine, "e2", 0.9)

    engine.add_lesson(
        {
            "id": "l1",
            "observation": "observed once",
            "recommendation": "do it this way",
            "evidence_ids": ["evidence-attempt-e1-01"],
        }
    )
    try:
        engine.promote_lesson("l1")
        raise AssertionError("promotion with one experiment must fail")
    except RuntimeError:
        pass
    lesson = engine.add_lesson_evidence("l1", ["evidence-attempt-e2-01"])
    assert lesson["evidence_ids"] == ["evidence-attempt-e1-01", "evidence-attempt-e2-01"]
    promoted = engine.promote_lesson("l1")
    assert promoted["status"] == "ACTIVE"
    replay = engine.verify_replay()
    assert replay["deterministic"]


def test_global_lesson_store_feeds_new_runs(tmp_path: Path):
    run1 = ResearchEngine.create(tmp_path, spec("run-one", repetition=True))
    run1.propose_experiment(experiment("e1", context="a"))
    settle(run1, "e1", 0.9)
    run1.propose_experiment(experiment("e2", context="b"))
    settle(run1, "e2", 0.9)
    run1.add_lesson(
        {
            "id": "l-global",
            "observation": "cross-run reusable observation",
            "recommendation": "reuse this method",
            "evidence_ids": ["evidence-attempt-e1-01", "evidence-attempt-e2-01"],
        }
    )
    run1.promote_lesson("l-global")
    store = tmp_path / ".sisyfus" / "research" / "global_lessons.jsonl"
    assert store.exists()

    run2 = ResearchEngine.create(tmp_path, spec("run-two"))
    context = run2.planner_context()
    globals_seen = {item["lesson_id"] for item in context["global_lessons"]}
    assert "l-global" in globals_seen

    run1.revoke_lesson("l-global", reason="contradicted later")
    context = run2.planner_context()
    assert all(item["lesson_id"] != "l-global" for item in context["global_lessons"])


def test_allow_provisional_prereq_admission(tmp_path: Path):
    claims = [
        {"id": "c1", "statement": "parent"},
        {"id": "c2", "statement": "child", "depends_on": ["c1"]},
    ]
    parent_contract = {
        "id": "verify-c1",
        "target_claim_id": "c1",
        "pass_if": {"all": [{"path": "metrics.score", "op": ">=", "value": 0.7}]},
        "fail_if": {"all": [{"path": "metrics.score", "op": "<", "value": 0.3}]},
        "repetition": {"min_passes": 2, "min_independent_contexts": 2},
    }
    child_contract = {
        "id": "verify-c2",
        "target_claim_id": "c2",
        "pass_if": {"all": [{"path": "metrics.score", "op": ">=", "value": 0.7}]},
        "fail_if": {"all": [{"path": "metrics.score", "op": "<", "value": 0.3}]},
    }

    # default: provisional parent blocks the child experiment
    strict = ResearchEngine.create(tmp_path / "strict", spec("strict", claims=claims, contracts=[parent_contract, child_contract]))
    strict.propose_experiment(experiment("p1", context="a"))
    settle(strict, "p1", 0.9)  # provisional (needs 2 contexts)
    result = strict.propose_experiment(experiment("child", claim="c2", contract="verify-c2"))
    assert not result["admission"]["accepted"]
    assert result["admission"]["reason"] == "claim_dependencies_not_supported"

    # opt-in: one provisional pass is enough to start dependent work
    relaxed = ResearchEngine.create(
        tmp_path / "relaxed",
        spec("relaxed", claims=claims, contracts=[parent_contract, child_contract],
             stop_policy={"allow_provisional_prereq": True}),
    )
    relaxed.propose_experiment(experiment("p1", context="a"))
    settle(relaxed, "p1", 0.9)
    result = relaxed.propose_experiment(experiment("child", claim="c2", contract="verify-c2"))
    assert result["admission"]["accepted"]


def test_cli_brief_and_structured_errors(tmp_path: Path, capsys):
    ResearchEngine.create(tmp_path, spec())
    code = cli_main(["research", "status", "latest", "--root", str(tmp_path), "--brief", "--no-report"])
    out = capsys.readouterr().out
    assert code == 0
    brief = json.loads(out)
    assert "attempts_remaining" in brief and "contested_claims" in brief

    code = cli_main(["research", "execute", "latest", "no-such-experiment", "--root", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 1
    error = json.loads(captured.err)
    assert error["error"]["type"] == "KeyError"
    assert "no-such-experiment" in error["error"]["message"]
