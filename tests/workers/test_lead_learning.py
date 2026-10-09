"""Protocol fixtures only: no benchmark/model capability claims from these tests."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from sisyfus.autonomy.models import (ContinuationState, Decision, OpportunitySignal,
                                     VerificationResult, canonical_json, utc_now)
from sisyfus.autonomy.store import AutonomyStore
from sisyfus.workers.journal import Journal
from sisyfus.workers.lead_contracts import ROLE_DEFAULTS
from sisyfus.workers.lead_learning import (ACTOR, PREFIX, SCHEMA, ProcedureLedger,
                                          ProofUnavailable)
from sisyfus.workers.mission import files
from sisyfus.workers.protocol import digest


def event(store, mission, kind, data, *, actor=ACTOR, now=None):
    with store._transaction() as db:
        return store._append_event(db, continuation_id=None, entity_type="lead_trial",
                                   entity_id=mission, event_type=PREFIX + kind,
                                   actor=actor, data=data, now=now or utc_now())


def check_spec(root):
    code = root / "locked_check.py"
    if not code.exists():
        code.write_text("# fixed controller evaluator fixture\n")
    return {"argv": ["python", str(code), "{candidate}"],
            "code_hashes": {str(code): hashlib.sha256(code.read_bytes()).hexdigest()},
            "contract": {"pass_if": {"all": [{"path": "valid", "op": "==", "value": 1}]},
                         "fail_if": {"all": [{"path": "valid", "op": "==", "value": 0}]}},
            "timeout": 10}


def new_trial(root, name, procedure_hash, *, family, split, pair_id=None, extra_calls=0,
              verdict="PASS", cost=None, actual=True, frozen_time=None, task_spec=None, receipt_markers=None):
    directory = root / name
    directory.mkdir()
    source, artifact = directory / "source", directory / "artifact"
    source.mkdir()
    artifact.mkdir()
    (source / "input.txt").write_text("scoped-family-input:" + family)
    (artifact / "result.txt").write_text("equivalent accepted artifact:" + family)
    store = AutonomyStore(directory / "autonomy.sqlite3")
    journal = Journal(store)
    journal.bind({"parallelism": 64, "max_calls": None})
    spec = task_spec or {"objective": "Implement scoped family " + family,
                        "tasks": [{"id": "build", "required_checks": ["functional"]}],
                        "checks": {"functional": check_spec(root)},
                        "required_checks": ["functional"], "integration_checks": ["functional"],
                        "roles": copy.deepcopy(ROLE_DEFAULTS),
                        "configuration": {"parallelism": 2, "timeout": 10, "max_calls": None,
                                          "max_iterations": None, "max_cost_usd": None}}
    manifest = {"schema": SCHEMA, "mission_id": name, "pair_id": pair_id or family,
                "split": split, "procedure_hash": procedure_hash, "family": family,
                "source": str(source), "source_hash": digest(files(source)), "artifact": str(artifact),
                "spec_hash": digest(spec), "task_spec": spec,
                "source_mission_ids": [], "source_family_hashes": []}
    event(store, name, "FROZEN", manifest, now=frozen_time)
    trial = {"dir": directory, "store": store, "journal": journal, "manifest": manifest,
             "source": source, "artifact": artifact, "spec": spec, "evidence": [], "reviews": []}

    def run(key, role, output="fixture", *, unknown=False):
        journal.reserve(key, key, digest({"task": key, "procedure": procedure_hash}))
        event(store, name, "ROLE", {"run_key": key, "role": role, "procedure_hash": procedure_hash,
                                   "mode": "workspace-write" if role == "worker" else "read-only"})
        journal.complete(key, {"status": "UNKNOWN" if unknown else "COMPLETED", "output": output,
                               "session_id": name + ":" + key, "requested_model": ROLE_DEFAULTS[role]["model"],
                               "actual_model": ROLE_DEFAULTS[role]["model"] if actual else None,
                               "usage": {"invocation_cost_usd": cost} if cost is not None else {},
                               **(receipt_markers or {})})

    trial["run"] = run
    run("lead", "lead")
    run("worker", "worker")
    for index in range(extra_calls):
        run(f"repair-{index}", "worker")
    for target in ("task:build:functional", "integration:functional"):
        measurement = {"valid": 1 if verdict == "PASS" else 0,
                       "execution": {"exit_code": 0, "timed_out": False},
                       "improved": True, "gain": 100000}
        proof = {"candidate": str(artifact), "candidate_hash": digest(files(artifact)),
                 "check_hash": digest(spec["checks"]["functional"]), "measurement": measurement,
                 "run_key": "worker"}
        eid = canonical_verdict(store, target, verdict, proof)
        trial["evidence"].append(eid)
        event(store, name, "CHECK", {"target": target, "check_id": "functional", "evidence_id": eid})
        review = {"target": target, "verdict": "PASS", "candidate_hash": digest(files(artifact)),
                  "spec_hash": digest(spec), "evidence_ids": [eid]}
        key = "review:" + target
        run(key, "reviewer", json.dumps(review))
        event(store, name, "REVIEW", {"run_key": key, "review": review})
        trial["reviews"].append(review)
    event(store, name, "CLOSED", {"status": "SUCCEEDED", "candidate_hash": digest(files(artifact))})
    return trial


def canonical_verdict(store, target, verdict, proof):
    opportunity, _ = store.submit_opportunity(OpportunitySignal(source="fixture-controller", title=target,
                                                               objective=target, dedupe_key=target))
    store.admit_opportunity(opportunity["id"], max_attempts=100)
    cont = store.claim_due_continuation("fixture-controller", lease_seconds=120)
    decision, cont, _ = store.reserve_decision(cont["id"], worker_id="fixture-controller",
                                              lease_token=cont["lease_token"], expected_version=cont["version"],
                                              decision=Decision("EXECUTE", "frozen deterministic check", capability="check",
                                                                arguments={"target": target}))
    _, cont = store.record_execution(decision["id"], worker_id="fixture-controller", lease_token=cont["lease_token"],
                                    expected_version=cont["version"], result={"measurement": proof["measurement"]})
    ev, _ = store.record_verdict(decision["id"], worker_id="fixture-controller", lease_token=cont["lease_token"],
                                expected_version=cont["version"],
                                verification=VerificationResult(verdict, "locked-check", "fixture result", evidence=proof, assurance="A"),
                                to_state=ContinuationState.SUCCEEDED if verdict == "PASS" else ContinuationState.FAILED)
    return ev["id"]


@pytest.fixture
def scenario(tmp_path):
    initial_hash = digest(__import__("sisyfus.workers.lead_contracts", fromlist=["DEFAULT_PROCEDURE"]).DEFAULT_PROCEDURE)
    development = new_trial(tmp_path, "development", initial_hash, family="development", split="development", verdict="FAIL")
    ledger = ProcedureLedger(development["store"])
    candidate = ledger.propose("Inspect frozen interfaces first; diagnose failure layer before redispatch.",
                               "Prior failed check shows avoidable blind redispatch.", development["evidence"],
                               {"kind": "matched_pilot_only"})
    search_b = new_trial(tmp_path, "search-b", initial_hash, family="search", split="search", extra_calls=2)
    search_c = new_trial(tmp_path, "search-c", candidate["hash"], family="search", split="search")
    hold_b = new_trial(tmp_path, "holdout-b", initial_hash, family="holdout", split="holdout", extra_calls=1)
    hold_c = new_trial(tmp_path, "holdout-c", candidate["hash"], family="holdout", split="holdout")
    return {"root": tmp_path, "ledger": ledger, "candidate": candidate, "development": development,
            "search_b": search_b, "search_c": search_c, "hold_b": hold_b, "hold_c": hold_c}


def assess(s, promote=False):
    action = s["ledger"].promote if promote else s["ledger"].evaluate
    return action(s["candidate"]["id"], [(s["search_b"]["dir"], s["search_c"]["dir"])],
                  [(s["hold_b"]["dir"], s["hold_c"]["dir"])], actor="operator")


def amend_frozen(trial, update):
    """Test malicious pre-execution manifests by rebuilding ONLY their chain.

    Production has no such mutation API. Content forgery tests deliberately edit
    the fixture DB to simulate a hostile producer and exercise semantic gates.
    """
    with trial["store"]._transaction() as db:
        row = db.execute("SELECT * FROM events WHERE event_type=?", (PREFIX + "FROZEN",)).fetchone()
        data = json.loads(row["data_json"])
        update(data)
        db.execute("UPDATE events SET data_json=? WHERE seq=?", (canonical_json(data), row["seq"]))
        rechain(db)


def rechain(db):
    from sisyfus.autonomy.store import _sha256
    previous = None
    for row in db.execute("SELECT * FROM events ORDER BY seq").fetchall():
        item = {key: row[key] for key in ("seq", "id", "ts", "continuation_id", "entity_type", "entity_id", "event_type", "actor")}
        item.update(data=json.loads(row["data_json"]), prev_hash=previous)
        current = _sha256(item)
        db.execute("UPDATE events SET prev_hash=?,event_hash=? WHERE seq=?", (previous, current, row["seq"]))
        previous = current


def test_valid_promotion_rollback_and_inheritance(scenario):
    s = scenario
    original = s["ledger"].active()
    report = assess(s)
    assert report["status"] == "ELIGIBLE"
    assert [p["invocations_saved"] for p in report["pairs"]] == [2, 1]
    assert s["ledger"].active() == original  # evaluate is advisory
    result = assess(s, promote=True)
    assert result["active"]["id"] == s["candidate"]["id"]
    reopened = ProcedureLedger(AutonomyStore(s["development"]["store"].path))
    assert reopened.active()["procedure"] == s["candidate"]["procedure"]
    assert reopened.rollback(original["id"], actor="operator") == original
    assert len(reopened.history()["versions"]) == 2
    assert s["development"]["store"].verify_event_chain()["valid"]
    assert not list(s["root"].glob("*learning*.sqlite*"))


def test_unknown_json_ids_do_not_ground_candidate(scenario):
    s = scenario
    with pytest.raises(ProofUnavailable, match="prior canonical"):
        s["ledger"].propose("new policy", "improved:true", ["forged-passed"])
    assert len(s["ledger"].history()["versions"]) == 2


@pytest.mark.parametrize("arm", ["search_c", "hold_c"])
def test_unknown_native_run_is_fenced(scenario, arm):
    s = scenario
    t = s[arm]
    t["run"]("unknown", "worker", unknown=True)
    with pytest.raises(ProofUnavailable, match="UNKNOWN"):
        assess(s)
    assert s["ledger"].active()["version"] == 1
    assert s["ledger"].history()["evaluations"][-1]["status"] == "PROOF_UNAVAILABLE"


@pytest.mark.parametrize("kind", ["check", "source", "code", "artifact", "spec"])
def test_hash_mismatch_rejects(scenario, kind):
    s = scenario
    t = s["search_c"]
    if kind == "source":
        (t["source"] / "input.txt").write_text("changed source after freeze")
    elif kind == "code":
        (s["root"] / "locked_check.py").write_text("changed acceptance code")
    elif kind == "artifact":
        (t["artifact"] / "result.txt").write_text("unreviewed mutation")
    elif kind == "spec":
        amend_frozen(t, lambda m: m["task_spec"]["configuration"].update(max_calls=3))
    else:
        with t["store"]._transaction() as db:
            row = db.execute("SELECT payload_json FROM evidence WHERE id=?", (t["evidence"][0],)).fetchone()
            payload = json.loads(row[0])
            payload["evidence"]["check_hash"] = "forged"
            db.execute("UPDATE evidence SET payload_json=? WHERE id=?", (canonical_json(payload), t["evidence"][0]))
    with pytest.raises(ProofUnavailable, match="hash|current accepted|corrupt"):
        assess(s)


def test_chain_tampering_rejects(scenario):
    s = scenario
    with s["search_c"]["store"]._transaction() as db:
        db.execute("UPDATE events SET data_json='{}' WHERE seq=1")
    with pytest.raises(ProofUnavailable, match="chain corrupt"):
        assess(s)


def test_fake_renamed_family_does_not_create_holdout(scenario):
    s = scenario
    # Same underlying source content, different family display label and filename.
    data = (s["search_b"]["source"] / "input.txt").read_text()
    for name in ("hold_b", "hold_c"):
        t = s[name]
        (t["source"] / "input.txt").write_text(data)
        amend_frozen(t, lambda m: m.update(family="totally-new-independent-family", source_hash=digest(files(t["source"]))))
    with pytest.raises(ProofUnavailable, match="split/family overlaps|already inspected"):
        assess(s)


def test_transitive_alias_overlap_rejects(scenario):
    s = scenario
    amend_frozen(s["hold_c"], lambda m: m.update(source_mission_ids=["search-b"]))
    with pytest.raises(ProofUnavailable, match="overlap"):
        assess(s)


def test_single_pair_or_search_as_holdout_rejects(scenario):
    s = scenario
    with pytest.raises(ProofUnavailable, match="holdout pairs required"):
        s["ledger"].evaluate(s["candidate"]["id"], [(s["search_b"]["dir"], s["search_c"]["dir"])], [], "operator")


def test_pretouched_holdout_rejects(scenario):
    s = scenario
    with s["hold_b"]["store"]._transaction() as db:
        db.execute("UPDATE events SET ts='2001-01-01T00:00:00.000000Z' WHERE event_type=?", (PREFIX + "FROZEN",))
        rechain(db)
    with pytest.raises(ProofUnavailable, match="touched before proposal"):
        assess(s)


def test_gain_booleans_cannot_replace_actual_improvement(scenario):
    s = scenario
    for old, family, split in (("search_b", "search", "search"), ("hold_b", "holdout", "holdout")):
        s[old] = new_trial(s["root"], old + "-same-calls", s["ledger"].active()["hash"], family=family, split=split)
    with pytest.raises(ProofUnavailable, match="no strictly measured"):
        assess(s, promote=True)
    assert s["ledger"].active()["version"] == 1


def test_one_regressing_pair_rejects_even_if_total_calls_improve(scenario):
    s = scenario
    s["hold_c"] = new_trial(s["root"], "holdout-c-regression", s["candidate"]["hash"],
                             family="holdout", split="holdout", extra_calls=2)
    with pytest.raises(ProofUnavailable, match="reservation regression"):
        assess(s)


def test_fail_gate_or_review_rejects(scenario):
    s = scenario
    s["search_c"] = new_trial(s["root"], "search-c-fail", s["candidate"]["hash"], family="search", split="search", verdict="FAIL")
    with pytest.raises(ProofUnavailable, match="not PASS"):
        assess(s)


def test_latest_review_supersedes_old_pass(scenario):
    s = scenario
    t = s["search_c"]
    event(t["store"], t["manifest"]["mission_id"], "REVIEW", {"run_key": "review:task:build:functional",
          "review": {**t["reviews"][0], "verdict": "FAIL"}})
    event(t["store"], t["manifest"]["mission_id"], "CLOSED", {"status": "SUCCEEDED", "candidate_hash": digest(files(t["artifact"]))})
    with pytest.raises(ProofUnavailable, match="review proof stale"):
        assess(s)


def test_actual_model_null_is_not_configuration_attestation(scenario):
    s = scenario
    s["search_c"] = new_trial(s["root"], "search-c-null-actual", s["candidate"]["hash"], family="search", split="search", actual=False)
    with pytest.raises(ProofUnavailable, match="requested/actual"):
        assess(s)


def test_cost_zero_is_distinct_from_unmetered(scenario):
    s = scenario
    for name, split, family, extra, policy in (("search_b", "search", "search", 1, s["ledger"].active()["hash"]),
                                              ("search_c", "search", "search", 0, s["candidate"]["hash"])):
        s[name] = new_trial(s["root"], name + "-zero", policy, family=family, split=split, extra_calls=extra, cost=0)
    report = assess(s)
    metered = report["pairs"][0]
    assert metered["baseline"]["cost_usd"] == metered["candidate"]["cost_usd"] == 0
    assert metered["cost_comparable"] is True
    unknown = report["pairs"][1]
    assert unknown["baseline"]["cost_usd"] is None and unknown["cost_comparable"] is False
    assert unknown["baseline"]["cost_status"] == "UNMETERED"


def test_measured_cost_regression_blocks_call_savings(scenario):
    s = scenario
    s["search_b"] = new_trial(s["root"], "search-b-cost", s["ledger"].active()["hash"], family="search", split="search", extra_calls=1, cost=0)
    s["search_c"] = new_trial(s["root"], "search-c-cost", s["candidate"]["hash"], family="search", split="search", cost=1)
    with pytest.raises(ProofUnavailable, match="cost regression"):
        assess(s)


def test_unvalidated_or_nonancestor_rollback_rejects(scenario):
    s = scenario
    with pytest.raises(ProofUnavailable, match="validated ancestor"):
        s["ledger"].rollback(s["candidate"]["id"], "operator")
    assert s["ledger"].active()["version"] == 1


def test_immutable_candidate_record_tampering_detected(scenario):
    s = scenario
    with s["development"]["store"]._transaction() as db:
        altered = {**s["candidate"], "procedure": "forged active policy"}
        db.execute("UPDATE lead_procedure_versions SET record_json=? WHERE id=?", (canonical_json(altered), s["candidate"]["id"]))
    with pytest.raises(ProofUnavailable, match="immutable procedure"):
        assess(s)


def test_blank_actor_rejected(scenario):
    s = scenario
    with pytest.raises(ProofUnavailable, match="actor required"):
        s["ledger"].evaluate(s["candidate"]["id"], [], [], " ")


def test_trial_missing_db_is_not_created(scenario):
    s = scenario
    blank = s["root"] / "no-proof"
    blank.mkdir()
    with pytest.raises(ProofUnavailable, match="database missing"):
        s["ledger"].evaluate(s["candidate"]["id"], [(blank, s["search_c"]["dir"])],
                              [(s["hold_b"]["dir"], s["hold_c"]["dir"])], "operator")
    assert not (blank / "autonomy.sqlite3").exists()


def test_matching_missing_actual_models_are_limited_pilot(scenario):
    s = scenario
    for name, split, family, extra, policy in (
        ("search_b", "search", "search", 1, s["ledger"].active()["hash"]),
        ("search_c", "search", "search", 0, s["candidate"]["hash"]),
        ("hold_b", "holdout", "holdout", 1, s["ledger"].active()["hash"]),
        ("hold_c", "holdout", "holdout", 0, s["candidate"]["hash"]),
    ):
        s[name] = new_trial(s["root"], name + "-unverified", policy, family=family, split=split,
                            extra_calls=extra, actual=False)
    report = assess(s, promote=True)["evaluation"]
    assert report["model_scope"] == "requested-model matched pilot; runtime model unverified"
    assert all(set(p["candidate"]["attestation"].values()) == {"MISSING"} for p in report["pairs"])


def test_wrong_attested_model_rejects_even_with_requested_match(scenario):
    s = scenario
    t = s["search_c"]
    with t["store"]._transaction() as db:
        row = db.execute("SELECT receipt_json FROM native_worker_runs WHERE key='worker'").fetchone()
        receipt = json.loads(row[0])
        receipt["actual_model"] = "another-runtime-model"
        db.execute("UPDATE native_worker_runs SET receipt_json=? WHERE key='worker'", (canonical_json(receipt),))
        db.execute("UPDATE events SET data_json=? WHERE event_type='WORKER_RECEIPT' AND entity_id='worker'", (canonical_json(receipt),))
        rechain(db)
    with pytest.raises(ProofUnavailable, match="requested/actual"):
        assess(s)


def test_report_table_tampering_detected(scenario):
    s = scenario
    report = assess(s)
    with s["development"]["store"]._transaction() as db:
        forged = {**report, "status": "improved:true"}
        db.execute("UPDATE lead_procedure_evaluations SET report_json=? WHERE id=?", (canonical_json(forged), report["id"]))
    with pytest.raises(ProofUnavailable, match="audit hash"):
        s["ledger"].history()


def test_core_bridge_freezes_before_dynamic_planning_and_extracts(tmp_path):
    from test_lead_mission import make_spec, mission
    from sisyfus.workers.lead_learning import extract_trial, trial_spec
    spec = make_spec(tmp_path, initial=False, procedure="Bound operator procedure")
    m = mission(tmp_path, spec)
    assert m.learning.active()["procedure"] == spec["procedure"]
    m.configure_learning_trial(pair_id="pilot-1", split="search", mission_id="core-search")
    result = m.run(max_cycles=100)
    assert result["all_verified"], result
    manifest = trial_spec(m.directory)
    assert manifest["pair_id"] == "pilot-1" and "artifact" not in manifest
    assert "tasks" not in manifest["task_spec"]  # dynamic task DAG is not paired acceptance
    proof = extract_trial(m.directory)
    assert proof["invocations"] == result["native_call_reservations"]
    assert set(proof["attestation"].values()) == {"MISSING"}
    assert len(proof["evidence_ids"]) == 2
    # Repeat exactly the saved config, as core does on restart.
    assert m.learning.freeze_trial(mission_id="core-search", pair_id="pilot-1", split="search") == manifest_without_projection(manifest)
    with pytest.raises(ProofUnavailable, match="immutable"):
        m.learning.freeze_trial(mission_id="core-search", pair_id="different", split="search")


def manifest_without_projection(manifest):
    return {k: v for k, v in manifest.items() if k not in {"family_hash", "freeze_event_id", "freeze_event_hash"}}


def test_core_proposal_grounded_failed_deterministic_evidence(tmp_path):
    from test_lead_mission import make_spec, mission
    from sisyfus.workers.protocol import Receipt
    def wrong_worker(request, emit, controls):
        (Path(request.cwd) / "a.txt").write_text("wrong result")
        return Receipt("COMPLETED", session_id="bad-worker-session", requested_model=request.model)
    m = mission(tmp_path, make_spec(tmp_path, initial=False), worker=wrong_worker)
    m.run(max_cycles=100)
    failures = [e["id"] for c in m.store.list_continuations() for e in m.store.snapshot(c["id"])["evidence"] if e["verdict"] == "FAIL"]
    assert failures
    candidate = m.learning.propose("Diagnose failed deterministic layer before another invocation.", "Recorded actual check FAIL", failures)
    assert candidate["origins"][0]["verdict"] == "FAIL"
    assert m.learning.active()["version"] == 1


def test_core_bridge_uses_task_artifact_and_separate_integration(tmp_path):
    from test_lead_mission import make_spec, mission, plan, task
    from sisyfus.workers.lead_learning import extract_trial
    from sisyfus.workers.protocol import Receipt
    def two_task_lead(request, emit, controls):
        if not request.prompt.startswith("Independent"):
            return Receipt("COMPLETED", session_id="two-task-lead", requested_model=request.model,
                           output=json.dumps(plan([task("build"), task("other", "b.txt", "b")])))
    m = mission(tmp_path, make_spec(tmp_path, two=True, initial=False), claude=two_task_lead)
    result = m.run(max_cycles=100)
    assert result["all_verified"]
    proof = extract_trial(m.directory)
    assert len(proof["evidence_ids"]) == 3
    hashes = [m.store.latest_evidence(c["id"])["payload"]["evidence"]["candidate_hash"]
              for c in m.store.list_continuations()]
    assert len(set(hashes)) > 1  # per-task snapshots differ; all remain current


def test_core_immutable_measurement_tampering_rejects(tmp_path):
    from test_lead_mission import make_spec, mission
    from sisyfus.workers.lead_learning import extract_trial
    m = mission(tmp_path, make_spec(tmp_path, initial=False))
    assert m.run(max_cycles=100)["all_verified"]
    with m.store._transaction() as db:
        row = db.execute("SELECT key,value FROM metadata WHERE key LIKE 'techlead:measurements:%' LIMIT 1").fetchone()
        record = json.loads(row[1])
        record["data"]["measurement"]["improved"] = True
        db.execute("UPDATE metadata SET value=? WHERE key=?", (canonical_json(record), row[0]))
    with pytest.raises(ProofUnavailable, match="measurements record unanchored"):
        extract_trial(m.directory)


def core_pair(s, family, split, *, candidate_dag=False):
    """Real core controller/verifier, synthetic native transport (NOT live RSI)."""
    from test_lead_mission import make_spec, plan, task, Stub
    from sisyfus.workers.lead_mission import LeadMission
    from sisyfus.workers.protocol import Receipt
    root = s["root"] / ("core-pair-" + family)
    root.mkdir()
    spec = make_spec(root, initial=False)
    (root / "source" / "README.md").write_text("Distinct scoped task family: " + family)
    trials = []
    for arm in ("baseline", "candidate"):
        arm_spec = {**spec, "procedure": s["ledger"].active()["procedure"] if arm == "baseline" else s["candidate"]["procedure"]}
        m = LeadMission(root / arm, arm_spec)
        def revised_plan(request, emit, controls):
            if arm == "candidate" and candidate_dag and not request.prompt.startswith("Independent"):
                return Receipt("COMPLETED", session_id="revised-lead-plan", requested_model=request.model,
                    output=json.dumps(plan([task("build"), task("annotate", "marker.txt", "a", deps=["build"])])))
        m.drivers = {"claude": Stub("claude", revised_plan), "codex": Stub("codex")}
        m.configure_learning_trial(pair_id="core-pair:" + family, split=split, mission_id=family + ":" + arm)
        if arm == "baseline":
            # Actual retained reservation rows, not a fabricated gain/count field.
            for i in range(4):
                m.role_call("lead", "redundant-read:" + str(i), m.planning_prompt(), Path(m.spec["source"]))
        assert m.run(max_cycles=100)["all_verified"]
        trials.append(m)
    return trials


def test_core_paired_promotion_allows_different_scoped_dag_and_semantic_artifact(scenario):
    s = scenario
    search = core_pair(s, "search-core", "search", candidate_dag=True)
    holdout = core_pair(s, "holdout-core", "holdout", candidate_dag=True)
    report = s["ledger"].promote(s["candidate"]["id"], [(search[0].directory, search[1].directory)],
                                   [(holdout[0].directory, holdout[1].directory)], "operator")["evaluation"]
    assert report["artifact_equivalence"] == "frozen_acceptance"
    assert report["model_scope"] == "requested-model matched pilot; runtime model unverified"
    for pair in report["pairs"]:
        assert pair["baseline"]["artifact_hash"] != pair["candidate"]["artifact_hash"]
        assert pair["invocations_saved"] == 2
    assert len(search[0].active_tasks()) == 1 and len(search[1].active_tasks()) == 2


def test_core_exact_hash_scope_rejects_distinct_accepted_artifacts(scenario):
    s = scenario
    exact = s["ledger"].propose("Different exact-hash pilot policy.", "retained failed checks", s["development"]["evidence"],
                                {"artifact_equivalence": "exact_hash"})
    s["candidate"] = exact
    search = core_pair(s, "strict-search-core", "search", candidate_dag=True)
    holdout = core_pair(s, "strict-holdout-core", "holdout", candidate_dag=True)
    with pytest.raises(ProofUnavailable, match="artifacts are not equivalent"):
        s["ledger"].evaluate(exact["id"], [(search[0].directory, search[1].directory)],
                                [(holdout[0].directory, holdout[1].directory)], "operator")


def test_public_candidate_preflight_revalidates_current_origins(scenario):
    s = scenario
    validated = s["ledger"].validate_candidate(s["candidate"]["id"])
    assert validated["baseline"] == s["ledger"].active()
    assert validated["origins"] == s["candidate"]["origins"]
    (s["development"]["artifact"] / "result.txt").write_text("stale origin artifact")
    with pytest.raises(ProofUnavailable, match="artifact hash"):
        s["ledger"].validate_candidate(s["candidate"]["id"])
    assert not s["ledger"].history()["evaluations"]  # preflight runs no children/evaluation


def test_shared_provenance_donors_within_pair_are_allowed(scenario):
    s = scenario
    for name in ("search_b", "search_c"):
        amend_frozen(s[name], lambda m: m.update(source_mission_ids=["shared-source-donor"],
                                                source_family_hashes=["shared-donor-family"]))
    assert assess(s)["status"] == "ELIGIBLE"


def test_one_arm_cannot_use_other_actual_mission_as_source(scenario):
    s = scenario
    amend_frozen(s["search_c"], lambda m: m.update(source_mission_ids=["search-b"]))
    with pytest.raises(ProofUnavailable, match="paired actual mission IDs"):
        assess(s)


def test_already_inspected_holdout_proof_is_not_replaceable(scenario):
    s = scenario
    assess(s)
    t = s["hold_c"]
    event(t["store"], t["manifest"]["mission_id"], "CLOSED", {"status": "SUCCEEDED", "candidate_hash": digest(files(t["artifact"]))})
    with pytest.raises(ProofUnavailable, match="holdout proof changed"):
        assess(s, promote=True)
    assert s["ledger"].active()["version"] == 1


@pytest.mark.parametrize("ordinary_case", ["custom_roles", "empty_source"])
def test_standalone_freeze_does_not_gate_ordinary_dispatch(tmp_path, ordinary_case, scenario):
    from test_lead_mission import make_spec, mission
    from sisyfus.workers.lead_learning import extract_trial
    spec = make_spec(tmp_path, initial=False, rsi={"enabled": False, "auto_promote": False})
    if ordinary_case == "custom_roles":
        spec["roles"] = {name: {**config, "model": "operator-" + name}
                         for name, config in ROLE_DEFAULTS.items()}
        error = "role configuration required"
    else:
        empty = tmp_path / "greenfield-source"
        empty.mkdir()
        spec["source"] = str(empty)
        error = "nonempty source required"
    m = mission(tmp_path, spec)
    result = m.run(max_cycles=100)
    assert result["all_verified"], result
    assert result["native_call_reservations"] > 0
    assert m.spec["rsi"]["enabled"] is False
    with m.store._transaction(immediate=False) as db:
        freezes = db.execute("SELECT * FROM events WHERE event_type=?", (PREFIX + "FROZEN",)).fetchall()
        first_reservation = db.execute("SELECT min(seq) FROM events WHERE event_type='WORKER_RESERVED'").fetchone()[0]
    assert len(freezes) == 1 and freezes[0]["seq"] < first_reservation
    manifest = json.loads(freezes[0]["data_json"])
    assert manifest["task_spec"]["roles"] == m.spec["roles"]
    if ordinary_case == "empty_source":
        assert manifest["source_hash"] == digest({})
    with pytest.raises(ProofUnavailable, match=error):
        extract_trial(m.directory)
    with pytest.raises(ProofUnavailable, match=error):
        scenario["ledger"].evaluate(scenario["candidate"]["id"],
            [(m.directory, scenario["search_c"]["dir"])],
            [(scenario["hold_b"]["dir"], scenario["hold_c"]["dir"])], "operator")
    assert scenario["ledger"].active()["version"] == 1
    assert scenario["ledger"].history()["evaluations"][-1]["status"] == "PROOF_UNAVAILABLE"
    assert m.store.verify_event_chain()["valid"]


SYNTHETIC_MARKERS = [
    {"native_worker_execution": False},
    {"execution_kind": "controlledsynthetic"},
    {"execution_kind": "CONTROLLED_SYNTHETIC_WORKER_NEGATIVE_VALIDATION"},
    {"native_worker_execution": True, "execution_kind": "synthetic"},
]


@pytest.mark.parametrize("markers", SYNTHETIC_MARKERS)
def test_explicit_receipt_adapter_rejects_synthetic_execution(tmp_path, markers):
    from sisyfus.workers.lead_contracts import DEFAULT_PROCEDURE
    from sisyfus.workers.lead_learning import extract_trial
    t = new_trial(tmp_path, "marked-receipt", digest(DEFAULT_PROCEDURE), family="marked-direct",
                  split="search", receipt_markers=markers)
    assert t["store"].verify_event_chain()["valid"]
    with pytest.raises(ProofUnavailable, match="synthetic/non-native receipt"):
        extract_trial(t["dir"])


@pytest.mark.parametrize("markers", SYNTHETIC_MARKERS)
def test_core_receipt_adapter_rejects_controlled_synthetic_worker(tmp_path, markers):
    from dataclasses import dataclass
    from test_lead_mission import make_spec, mission
    from sisyfus.workers.lead_learning import extract_trial
    from sisyfus.workers.protocol import Receipt
    @dataclass(frozen=True)
    class MarkedReceipt(Receipt):
        native_worker_execution: bool | None = None
        execution_kind: str | None = None
    def marked_worker(request, emit, controls):
        (Path(request.cwd) / "a.txt").write_text("42")
        return MarkedReceipt("COMPLETED", session_id="controlled-worker", requested_model=request.model,
                             **markers)
    m = mission(tmp_path, make_spec(tmp_path, initial=False), worker=marked_worker)
    assert m.run(max_cycles=100)["all_verified"]  # canonical control validation != native RSI proof
    assert m.store.verify_event_chain()["valid"]
    with pytest.raises(ProofUnavailable, match="synthetic/non-native receipt"):
        extract_trial(m.directory)
    worker_receipt = next(r["receipt"] for r in m.journal.runs() if r["role"] == "worker")
    assert worker_receipt["actual_model"] is None  # no inferred execution telemetry
