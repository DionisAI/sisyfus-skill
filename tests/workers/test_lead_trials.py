"""Real-core canonical paired protocol fixtures, not native model benchmarks.

Only test drivers are stubbed. Runner uses the actual core, evaluator subprocess,
autonomy evidence/hash chains, and ProcedureLedger origin/promotion validators.
All test artifacts are retained by scripts/test_retained.py.
"""
from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

import pytest

from sisyfus.workers import lead_trials
from sisyfus.workers.lead_learning import extract_trial
from sisyfus.workers.lead_mission import LeadMission as RealMission
from sisyfus.workers.protocol import Receipt, digest
from test_lead_mission import Stub, make_spec, plan, task


def public_spec(root, name):
    root.mkdir()
    spec = make_spec(root, initial=False)
    (Path(spec["source"]) / "README.md").write_text("unique frozen family: " + name)
    return spec


@pytest.fixture
def setup(tmp_path, monkeypatch):
    raw = public_spec(tmp_path / "development", "development")
    raw["rsi"] = {"enabled": True, "auto_promote": False}

    def invalid(request, *_):
        (Path(request.cwd) / "a.txt").write_text("wrong")
        return Receipt("COMPLETED", session_id="origin-worker", output="asserted success is not acceptance",
                       requested_model=request.model)

    origin = RealMission(tmp_path / "origin", raw)
    origin.drivers = {"codex": Stub("codex", invalid), "claude": Stub("claude")}
    outcome = origin.run(max_cycles=25)
    assert not outcome["all_verified"] and outcome["nodes"][0]["verdict"] == "FAIL"
    proposal = origin.learning.propose("Inspect frozen interfaces; diagnose before redispatch.",
                                       "Current canonical failed implementation shows avoidable retries.",
                                       [outcome["nodes"][0]["evidence_id"]])
    root = tmp_path / "evaluation"
    root.mkdir()
    search = public_spec(root / "search", "search")
    holdout = public_spec(root / "holdout", "holdout")
    manifest = {"schema": "sisyfus.lead_trials.v1", "search": [{"id": "search-one", "spec": search}],
                "holdout": [{"id": "holdout-one", "spec": holdout}]}
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest))
    children, run_args = [], []
    options = {"improve": False, "unknown": False, "fail": False, "worker_callback": None, "run_callback": None}

    def factory(directory, spec):
        child = RealMission(directory, spec)
        baseline = spec["procedure"] == origin.learning.active()["procedure"]

        def worker(request, emit, controls):
            callback = options["worker_callback"]
            if callback:
                result = callback(child, request, emit, controls)
                if result is not None:
                    return result
            if options["unknown"]:
                return Receipt("UNKNOWN", error="uncertain fixture transport", requested_model=request.model)
            if options["fail"] or options["improve"] and baseline and request.task_id == "build":
                (Path(request.cwd) / "a.txt").write_text("wrong")
                return Receipt("COMPLETED", session_id="worker-failed", output="fixture bad output",
                               requested_model=request.model)

        def claude(request, *_):
            if options["improve"] and not options["fail"] and request.prompt.startswith("Classify"):
                payload = json.loads(request.prompt.split("\n", 1)[1])
                return Receipt("COMPLETED", session_id="lead-diagnosis", requested_model=request.model,
                               output=json.dumps({"classification": "implementation", "reasons": ["wrong value"],
                                                  "evidence": payload["evidence_references"], "action": "repair",
                                                  "plan": plan([task("fixed", repair="build")])}))

        child.drivers = {"codex": Stub("codex", worker), "claude": Stub("claude", claude)}
        original_run = child.run

        def run(max_cycles=None):
            run_args.append(max_cycles)
            callback = options["run_callback"]
            return callback(child) if callback else original_run(max_cycles=max_cycles)

        child.run = run
        children.append(child)
        return child

    monkeypatch.setattr(lead_trials, "LeadMission", factory)
    return {"origin": origin, "proposal": proposal, "root": root, "manifest": manifest, "path": path,
            "children": children, "run_args": run_args, "options": options}


def execute(s):
    return lead_trials.run_trials(s["origin"], s["proposal"]["id"], s["root"])


def write_manifest(s):
    s["path"].write_text(json.dumps(s["manifest"]))


def fresh_candidate_catalog(s):
    """A different grounded procedure AND content-disjoint operator catalog."""
    s["proposal"] = s["origin"].learning.propose(
        "Another grounded procedure; inspect interfaces and preserve acceptance.",
        "Use the same current development evidence, not previous lab assertions.",
        [s["origin"].snapshot()["nodes"][0]["evidence_id"]])
    s["root"] = s["root"].parent / "fresh-evaluation"
    s["root"].mkdir()
    s["manifest"] = {split: [{"id": split + "-fresh", "spec": public_spec(s["root"] / split, split + "-fresh")}]
                     for split in ("search", "holdout")}
    s["path"] = s["root"] / "manifest.json"
    write_manifest(s)


def accepted_origin(s, tmp_path):
    raw = public_spec(tmp_path / "accepted-public", "accepted-development")
    raw["rsi"] = {"enabled": True, "auto_promote": False}
    origin = RealMission(tmp_path / "accepted-control", raw)
    origin.drivers = {"codex": Stub("codex"), "claude": Stub("claude")}
    snapshot = origin.run(max_cycles=25)
    assert snapshot["phase"] == "COMPLETED" and snapshot["all_verified"]
    s["origin"] = origin
    s["proposal"] = origin.learning.propose(
        "Inspect approved interfaces before native dispatch; retain every acceptance gate.",
        "Current accepted canonical evidence grounds a procedure-only proposal.",
        [snapshot["nodes"][0]["evidence_id"]])
    return snapshot


def controller_handoff(s):
    """Use the core's durable callback lifecycle, including explicit RSI-off calls."""
    origin = s["origin"]
    key = digest({"candidate_id": s["proposal"]["id"], "root": str(s["root"].resolve())})
    origin.journal.record("trial_requests", key, {"candidate_id": s["proposal"]["id"], "evaluation_root": str(s["root"]),
                                                "boundary": "completed"})
    origin.begin_trial(key)
    report = execute(s)
    origin.journal.record("trial_results", key, report)
    origin.settle_trial(key, report)
    return report


@pytest.mark.parametrize("kind", ["overlap", "invalid_catalog", "candidate_missing", "rsi_disabled"])
def test_no_dispatch_deterministic_rejection_preserves_canonical_accepted_project(setup, tmp_path, kind):
    s = setup
    before = accepted_origin(s, tmp_path)
    if kind == "overlap":
        s["manifest"]["search"][0]["spec"]["source"] = s["origin"].spec["source"]
        write_manifest(s)
    elif kind == "invalid_catalog":
        s["path"].write_text('{"search": [], "holdout": []}')
    elif kind == "candidate_missing":
        s["proposal"] = {"id": "missing-canonical-candidate"}
    else:
        s["origin"].spec["rsi"]["enabled"] = False
    report = controller_handoff(s)
    assert report["status"] == "NONPROMOTION" and not report["promoted"], report
    assert report["error"]["type"] in {"ProofUnavailable", "ValueError"}
    assert not s["children"] and not s["origin"].journal.records("paired_trials")
    assert not s["origin"].journal.records("paired_trial_children")
    after = s["origin"].snapshot()
    assert after["procedure_trials"]["status"] == "IDLE", after["procedure_trials"]
    assert after["phase"] == "COMPLETED" and after["all_verified"] and after["project_verified"]
    assert after["counters"]["trial_child_calls"] == 0
    assert after["counters"]["parent_calls"] == after["counters"]["total_calls"] == before["counters"]["total_calls"]
    assert after["integration"]["evidence"] == before["integration"]["evidence"]
    assert [n["evidence_id"] for n in after["nodes"]] == [n["evidence_id"] for n in before["nodes"]]
    assert s["origin"].store.verify_event_chain()["valid"]


def test_automatic_completed_boundary_overlap_is_terminal_without_child_calls(setup, tmp_path):
    s = setup
    before = accepted_origin(s, tmp_path)
    s["manifest"]["search"][0]["spec"]["source"] = s["origin"].spec["source"]
    write_manifest(s)
    s["origin"].spec["rsi"]["evaluation_root"] = str(s["root"])
    s["origin"]._procedure_trial_boundary("completed")  # Real default lazy runner, not a callback stub.
    results = s["origin"].journal.records("trial_results")
    assert len(results) == 1 and results[0]["data"]["status"] == "NONPROMOTION"
    assert not s["children"]
    after = s["origin"].snapshot()
    assert after["all_verified"] and after["phase"] == "COMPLETED"
    assert after["procedure_trials"]["status"] == "IDLE"
    assert after["counters"]["trial_child_calls"] == 0
    assert after["counters"]["total_calls"] == before["counters"]["total_calls"]


@pytest.mark.parametrize("uncertainty", ["pending", "UNKNOWN", "IN_FLIGHT", "missing_db"])
def test_bad_catalog_never_clears_inherited_uncertain_spending(setup, tmp_path, uncertainty):
    s = setup
    accepted_origin(s, tmp_path)
    previous = digest("prior-uncertain-candidate")
    foreign = None
    if uncertainty == "pending":
        s["origin"].journal.record("paired_trials", previous, {"status": "PENDING"})
    elif uncertainty == "missing_db":
        directory = tmp_path / "missing-prior-child"
        s["origin"].journal.record("trial_children", previous, {"directory": str(directory)})
    else:
        foreign = RealMission(tmp_path / "prior-uncertain-child", s["manifest"]["search"][0]["spec"])
        foreign.journal.reserve("prior-native", "planner", digest("prior-native"))
        if uncertainty == "UNKNOWN":
            foreign.journal.complete("prior-native", Receipt("UNKNOWN", error="prior uncertain transport").as_dict())
        s["origin"].register_trial_child(foreign)
        s["origin"].unregister_trial_child(foreign)
    retained = foreign.journal.runs() if foreign else None
    s["path"].write_text("invalid operator JSON, but spending uncertainty takes precedence")
    report = controller_handoff(s)
    assert report["status"] == "FENCED" and report["error"]["type"] == "DispatchBlocked", report
    assert not s["children"]
    snapshot = s["origin"].snapshot()
    assert snapshot["project_verified"] and not snapshot["all_verified"]
    assert snapshot["procedure_trials"]["status"] != "IDLE"
    if foreign:
        assert foreign.journal.runs() == retained
    if uncertainty == "pending":
        assert s["origin"].journal.get("paired_trial_results", previous) is None
    if uncertainty == "missing_db":
        assert not (directory / "autonomy.sqlite3").exists()


def test_real_core_equal_actual_calls_are_explicit_nonpromotion(setup):
    s = setup
    before = {name: len(driver.requests) for name, driver in s["origin"].drivers.items()}
    report = execute(s)
    assert report["status"] == "NONPROMOTION", report
    assert not report["promoted"] and report["claim"] == "no demonstrated improvement"
    assert "no strictly measured invocation improvement" in report["error"]["message"]
    assert report["assessment"]["status"] == "PROOF_UNAVAILABLE"
    assert len(s["children"]) == 4 and s["run_args"] == [None] * 4
    for base, candidate in zip(s["children"][::2], s["children"][1::2]):
        lhs, rhs = copy.deepcopy(base.spec), copy.deepcopy(candidate.spec)
        assert lhs.pop("procedure") != rhs.pop("procedure")
        assert lhs == rhs
        assert lhs["rsi"] == {"enabled": False, "auto_promote": False}
        assert lhs["max_calls"] is None and lhs["max_iterations"] is None and lhs["max_turns"] is None
        assert lhs["timeout"] == 3 and lhs["parallelism"] == 2
        assert len(base.journal.runs()) == len(candidate.journal.runs())
        assert base.store.verify_event_chain()["valid"] and candidate.store.verify_event_chain()["valid"]
    assert before == {name: len(driver.requests) for name, driver in s["origin"].drivers.items()}  # no holdout development prompt
    assert all(a["reservations"] == a["proof"]["invocations"] for a in report["arms"])
    assert s["origin"].learning.active()["id"] == "procedure_initial"
    assert s["origin"].store.verify_event_chain()["valid"]
    assert not (s["root"] / "autonomy.sqlite3").exists()


def test_trial_phase_hooks_follow_immutable_request_and_result_records(setup):
    s = setup
    calls = []
    def begin(request):
        assert s["origin"].journal.get("paired_trials", request)["status"] == "PENDING"
        assert not s["children"]
        calls.append(("begin", request))
        s["origin"].journal.phase("TRIAL_RUNNING", "explicit paired trial test fixture")
    def settle(request, report):
        assert s["origin"].journal.get("paired_trial_results", request) == report
        assert len(s["children"]) == 4
        assert s["origin"].journal.state()["phase"] == "TRIAL_RUNNING"
        calls.append(("settle", request))
    s["origin"].begin_trial, s["origin"].settle_trial = begin, settle
    def worker(*_):
        assert s["origin"].journal.state()["phase"] == "TRIAL_RUNNING"
    s["options"]["worker_callback"] = worker
    report = execute(s)
    assert report["status"] == "NONPROMOTION", report
    assert calls == [("begin", report["request_id"]), ("settle", report["request_id"])]


def test_known_final_replay_settles_interrupted_phase_without_native_replay(setup):
    s = setup
    previous_phase = s["origin"].journal.state()["phase"]
    settle = s["origin"].settle_trial
    def interrupted(*_):
        raise RuntimeError("fixture interruption after immutable paired result")
    s["origin"].settle_trial = interrupted
    with pytest.raises(RuntimeError, match="after immutable"):
        execute(s)
    assert s["origin"].journal.state()["phase"] == "TRIAL_RUNNING"
    assert len(s["children"]) == 4
    s["origin"].settle_trial = settle
    report = execute(s)
    assert report["status"] == "NONPROMOTION", report
    assert len(s["children"]) == 4 and s["run_args"] == [None] * 4
    assert s["origin"].journal.state()["phase"] == previous_phase
    assert not s["origin"].journal.state()["active_trials"]


@pytest.mark.parametrize("auto", [False, True])
def test_actual_canonical_call_improvement_is_only_eligible_or_promoted(setup, auto):
    s = setup
    s["options"]["improve"] = True
    s["origin"].spec["rsi"]["auto_promote"] = auto
    report = execute(s)
    assert report["status"] == ("PROMOTED" if auto else "ELIGIBLE"), report
    assert report["promoted"] is auto
    assert report["measured_invocations_saved"] > 0
    assert report["model_scope"] == "requested-model matched pilot; runtime model unverified"
    assert report["metric"] == "actual_native_invocation_reservations"
    for pair in report["assessment"]["pairs"]:
        assert pair["baseline"]["invocations"] > pair["candidate"]["invocations"]
        assert pair["invocations_saved"] == pair["baseline"]["invocations"] - pair["candidate"]["invocations"]
        assert all(v == "MISSING" for v in pair["baseline"]["attestation"].values())
    assert s["origin"].learning.active()["id"] == (s["proposal"]["id"] if auto else "procedure_initial")
    assert execute(s) == report  # same frozen proof is read, never redispatched
    assert len(s["children"]) == 4


def test_completed_cached_proof_tamper_fences_not_false_success(setup):
    s = setup
    s["options"]["improve"] = True
    report = execute(s)
    assert report["status"] == "ELIGIBLE", report
    snapshot = s["children"][1].snapshot()
    candidate = Path(snapshot["integration"]["evidence"]["payload"]["evidence"]["candidate"])
    (candidate / "a.txt").write_text("tampered")
    again = execute(s)
    assert again["status"] == "FENCED" and not again["promoted"]
    assert len(s["children"]) == 4


def test_cached_eligible_report_is_not_false_success_over_another_pending_lab(setup):
    s = setup
    s["options"]["improve"] = True
    report = execute(s)
    assert report["status"] == "ELIGIBLE", report
    s["origin"].journal.record("paired_trials", digest("other-candidate-pending"), {"status": "PENDING"})
    again = execute(s)
    assert again["status"] == "FENCED" and "across candidates" in again["error"]["message"]
    assert len(s["children"]) == 4
    assert s["origin"].journal.get("paired_trial_results", report["request_id"]) == report


def test_unknown_child_db_and_reservations_retained_never_replayed(setup):
    s = setup
    s["options"]["unknown"] = True
    report = execute(s)
    assert report["status"] == "FENCED" and "UNKNOWN" in report["error"]["message"]
    assert len(s["children"]) == 1
    child = s["children"][0]
    before = child.journal.runs()
    assert any(r["status"] == "UNKNOWN" for r in before)
    assert (child.directory / "autonomy.sqlite3").is_file()
    assert execute(s) == report
    assert len(s["children"]) == 1 and child.journal.runs() == before


def test_new_candidate_and_fresh_catalog_never_bypass_previous_child_unknown(setup):
    s = setup
    s["options"]["unknown"] = True
    previous = execute(s)
    assert previous["status"] == "FENCED"
    old_child = s["children"][0]
    before = old_child.journal.runs()
    fresh_candidate_catalog(s)
    s["options"]["unknown"] = False
    report = execute(s)
    assert report["request_id"] != previous["request_id"]
    assert report["status"] == "FENCED" and "UNKNOWN" in report["error"]["message"]
    assert "all candidate spending" in report["error"]["message"]
    assert len(s["children"]) == 1 and old_child.journal.runs() == before
    assert s["origin"].journal.get("paired_trials", report["request_id"]) is None


@pytest.mark.parametrize("pending_result", [False, True])
def test_prior_other_candidate_pending_request_globally_fences_new_catalog(setup, pending_result):
    s = setup
    previous = digest({"candidate_id": s["proposal"]["id"], "evaluation_root": str(s["root"])})
    s["origin"].journal.record("paired_trials", previous, {"status": "PENDING"})
    if pending_result:
        s["origin"].journal.record("paired_trial_results", previous, {"status": "PENDING"})
    fresh_candidate_catalog(s)
    report = execute(s)
    assert report["status"] == "FENCED" and "across candidates" in report["error"]["message"]
    assert previous in report["error"]["message"] and not s["children"]


@pytest.mark.parametrize("status", ["UNKNOWN", "IN_FLIGHT"])
def test_core_only_registered_child_unsettled_db_fences_readonly(setup, status):
    s = setup
    # A prior core callback may register a child without runner metadata.
    foreign = RealMission(s["root"].parent / "foreign-child", s["manifest"]["search"][0]["spec"])
    foreign.journal.reserve("foreign-native", "planner", digest("foreign-native"))
    if status == "UNKNOWN":
        foreign.journal.complete("foreign-native", Receipt("UNKNOWN", error="prior transport uncertain").as_dict())
    s["origin"].register_trial_child(foreign)
    s["origin"].unregister_trial_child(foreign)
    before, events = foreign.journal.runs(), foreign.store.verify_event_chain()
    report = execute(s)
    assert report["status"] == "FENCED" and status in report["error"]["message"]
    assert not s["children"] and foreign.journal.runs() == before
    assert foreign.store.verify_event_chain() == events  # Inspection never reconciles or rewrites child truth.


@pytest.mark.parametrize("malformed", [False, True])
def test_registered_missing_or_malformed_db_is_preserved_and_fenced(setup, malformed):
    s = setup
    directory = s["root"].parent / "partial-registered-child"
    directory.mkdir()
    path = directory / "autonomy.sqlite3"
    if malformed:
        path.write_bytes(b"partial invalid SQLite; retain for diagnosis")
    s["origin"].journal.record("trial_children", digest(str(directory)), {"directory": str(directory)})
    report = execute(s)
    assert report["status"] == "FENCED" and "DB" in report["error"]["message"]
    assert not s["children"]
    if malformed:
        assert path.read_bytes() == b"partial invalid SQLite; retain for diagnosis"
    else:
        assert not path.exists()


def test_settled_prior_children_do_not_fence_fresh_independent_trials(setup):
    s = setup
    assert execute(s)["status"] == "NONPROMOTION"
    fresh_candidate_catalog(s)
    report = execute(s)
    assert report["status"] == "NONPROMOTION", report
    assert len(s["children"]) == 8


def test_current_arm_inflight_is_exempt_but_its_unknown_is_not(setup):
    s = setup
    child = RealMission(s["root"].parent / "active-child", s["manifest"]["search"][0]["spec"])
    request = digest("current-paired-request")
    s["origin"].journal.record("paired_trials", request, {"status": "PENDING"})
    s["origin"].register_trial_child(child)
    child.journal.reserve("active-native", "planner", digest("active-native"))
    lead_trials._global_trial_fence(s["origin"], request=request, active_children={child.directory})
    child.journal.complete("active-native", Receipt("UNKNOWN", error="current transport uncertain").as_dict())
    with pytest.raises(lead_trials.DispatchBlocked, match="UNKNOWN"):
        lead_trials._global_trial_fence(s["origin"], request=request, active_children={child.directory})
    s["origin"].unregister_trial_child(child)


def test_global_guard_rechecks_prior_children_before_next_native_reservation(setup):
    s = setup
    foreign = RealMission(s["root"].parent / "later-uncertain-child", s["manifest"]["search"][0]["spec"])
    def worker(*_):
        foreign.journal.reserve("later-native", "planner", digest("later-native"))
        foreign.journal.complete("later-native", Receipt("UNKNOWN", error="other process became uncertain").as_dict())
        s["origin"].register_trial_child(foreign)
        s["origin"].unregister_trial_child(foreign)
    s["options"]["worker_callback"] = worker
    report = execute(s)
    assert report["status"] == "FENCED" and "UNKNOWN" in report["error"]["message"]
    assert len(s["children"]) == 1
    # Real worker settled, but the independent reviewer and remaining arms never dispatched.
    child = s["children"][0]
    assert [r["role"] for r in child.journal.runs()] == ["lead", "worker"]


@pytest.mark.parametrize("pending_result", [False, True])
def test_pending_origin_request_is_not_a_completed_or_retryable_trial(setup, pending_result):
    s = setup
    key = digest({"candidate_id": s["proposal"]["id"], "evaluation_root": str(s["root"].resolve())})
    s["origin"].journal.record("paired_trials", key, {"status": "PENDING"})
    if pending_result:
        s["origin"].journal.record("paired_trial_results", key, {"status": "PENDING"})
    report = execute(s)
    assert report["status"] == "FENCED" and "pending/uncertain" in report["error"]["message"]
    assert not s["children"]
    assert s["origin"].journal.get("paired_trial_results", key) == ({"status": "PENDING"} if pending_result else None)


@pytest.mark.parametrize("cap", lead_trials.AGGREGATE_CAPS)
def test_each_enabled_parent_cap_fences_before_child_construction(setup, cap):
    s = setup
    s["origin"].spec[cap] = 100
    report = execute(s)
    assert report["status"] == "FENCED" and cap in report["error"]["message"]
    assert not s["children"]
    assert s["origin"].journal.records("paired_trial_fences")


def test_missing_metering_under_cap_is_not_treated_as_zero(setup):
    s = setup
    assert s["origin"].journal.counters()["cost_usd"] is None
    s["origin"].spec["max_cost_usd"] = 0.5
    assert execute(s)["status"] == "FENCED"
    assert not s["children"]


def test_parent_unknown_fences_before_children(setup):
    s = setup
    journal = s["origin"].journal
    journal.reserve("unknown-origin", "planner", "unknown-fingerprint")
    journal.complete("unknown-origin", Receipt("UNKNOWN", error="transport uncertain").as_dict())
    report = execute(s)
    assert report["status"] == "FENCED" and "UNKNOWN" in report["error"]["message"]
    assert not s["children"]


def test_frozen_manifest_drift_between_arms_fences_without_retry(setup):
    s = setup
    changed = threading.Event()
    def worker(_child, _request, *_):
        if not changed.is_set():
            changed.set()
            s["manifest"]["search"][0]["spec"]["objective"] += " changed after outcome"
            write_manifest(s)
    s["options"]["worker_callback"] = worker
    report = execute(s)
    assert report["status"] == "NONPROMOTION" and "drift" in report["error"]["message"]
    assert len(s["children"]) == 1 and s["children"][0].snapshot()["all_verified"]
    assert execute(s)["status"] == "FENCED" and len(s["children"]) == 1


def test_external_spec_json_paths_are_hashed_and_fixed(setup):
    s = setup
    spec_path = s["root"] / "public-search.json"
    spec_path.write_text(json.dumps(s["manifest"]["search"][0]["spec"]))
    s["manifest"]["search"][0]["spec"] = spec_path.name
    write_manifest(s)
    report = execute(s)
    assert report["status"] == "NONPROMOTION", report
    frozen = s["origin"].journal.records("paired_trials")[0]["data"]["catalog"]
    assert str(spec_path) in frozen["input_hashes"] and frozen["manifest_hash"]


@pytest.mark.parametrize("kind", ["renamed_content", "transitive_family", "development", "duplicate_id"])
def test_source_family_and_provenance_disjoint_before_any_calls(setup, kind):
    s = setup
    search, holdout = s["manifest"]["search"][0], s["manifest"]["holdout"][0]
    if kind == "renamed_content":
        alias = s["root"] / "renamed-family"
        alias.mkdir()
        (alias / "different-filename.txt").write_text((Path(search["spec"]["source"]) / "README.md").read_text())
        holdout["spec"]["source"] = str(alias)
    elif kind == "transitive_family":
        alias = digest("shared-original-family")
        search["source_family_hashes"] = [alias]
        holdout["source_family_hashes"] = [alias]
    elif kind == "development":
        search["spec"]["source"] = s["origin"].spec["source"]
    else:
        holdout["id"] = search["id"]
    write_manifest(s)
    report = execute(s)
    assert report["status"] == "NONPROMOTION" and not s["children"]


def test_canonical_origin_staleness_rejected_preflight(setup):
    s = setup
    ev = s["origin"].snapshot()["nodes"][0]["verification"]
    (Path(ev["evidence"]["candidate"]) / "a.txt").write_text("changed after proposal")
    report = execute(s)
    assert report["status"] == "NONPROMOTION" and not s["children"]


def test_ungrounded_candidate_id_never_dispatches(setup):
    s = setup
    report = lead_trials.run_trials(s["origin"], "not-a-canonical-candidate", s["root"])
    assert report["status"] == "NONPROMOTION" and "missing" in report["error"]["message"]
    assert not s["children"]


def test_partial_or_foreign_child_db_is_preserved_not_adopted(setup):
    s = setup
    key = digest({"candidate_id": s["proposal"]["id"], "evaluation_root": str(s["root"].resolve())})
    case = {"id": "search-one", "split": "search"}
    path = lead_trials._directory(s["origin"], key, case, "baseline")
    path.mkdir(parents=True)
    sentinel = path / "partial-evidence.txt"
    sentinel.write_text("preserve uncertain child state")
    report = execute(s)
    assert report["status"] == "FENCED" and not s["children"]
    assert sentinel.read_text() == "preserve uncertain child state"


def test_durable_cross_process_parent_pause_resume_stop_propagates(setup):
    s = setup
    running, paused, resumed = threading.Event(), threading.Event(), threading.Event()
    def run(child):
        running.set()
        while not child.stop.wait(.01):
            if child.journal.paused():
                paused.set()
            elif paused.is_set():
                resumed.set()
        return child.snapshot()
    s["options"]["run_callback"] = run
    result = []
    thread = threading.Thread(target=lambda: result.append(execute(s)))
    thread.start()
    try:
        assert running.wait(3)
        # Fresh controller object has no local registered children: propagation
        # must observe the existing parent's durable DB, not only its Event.
        other = RealMission(s["origin"].directory)
        other.journal.pause(True)
        assert paused.wait(3)
        other.journal.pause(False)
        assert resumed.wait(3)
        other.request_stop()
        thread.join(5)
        assert not thread.is_alive()
        child = s["children"][0]
        assert child.stop.is_set() and child.journal.state()["stopped"]
        assert result[0]["status"] == "FENCED" and len(s["children"]) == 1
        assert not s["origin"]._trial_children
    finally:
        s["origin"].request_stop()
        thread.join(5)


def test_parent_pause_blocks_construction_and_pre_reservation_freeze(setup):
    s = setup
    s["origin"].journal.pause(True)
    running = threading.Event()
    def run(child):
        running.set()
        child.stop.wait(3)
        return child.snapshot()
    s["options"]["run_callback"] = run
    results = []
    thread = threading.Thread(target=lambda: results.append(execute(s)))
    thread.start()
    try:
        assert not running.wait(.15) and not s["children"]
        s["origin"].journal.pause(False)
        assert running.wait(3)
        s["origin"].request_stop()
        thread.join(5)
        assert results[0]["status"] == "FENCED"
    finally:
        s["origin"].request_stop()
        thread.join(5)


def test_failed_canonical_trials_are_nonpromotion_not_success(setup):
    s = setup
    s["options"]["fail"] = True
    report = execute(s)
    assert report["status"] == "NONPROMOTION" and not report["promoted"]
    assert len(s["children"]) == 4
    assert all(a.get("proof_error") for a in report["arms"])
    assert s["origin"].learning.active()["id"] == "procedure_initial"


def test_source_mission_paths_expand_all_canonical_provenance(setup, tmp_path):
    s = setup
    raw = public_spec(tmp_path / "donor-public", "independent-donor")
    donor = RealMission(tmp_path / "donor-control", raw)
    donor.drivers = {"codex": Stub("codex"), "claude": Stub("claude")}
    assert donor.run(max_cycles=25)["all_verified"]
    proof = extract_trial(donor.directory)
    s["manifest"]["search"][0]["source_missions"] = [str(donor.directory)]
    write_manifest(s)
    report = execute(s)
    assert report["status"] == "NONPROMOTION", report
    assert "no strictly measured invocation improvement" in report["error"]["message"]
    for child in s["children"][:2]:
        frozen = child.learning.trial_spec()
        assert set(proof["missions"]) <= set(frozen["source_mission_ids"])
        assert set(proof["families"]) <= set(frozen["source_family_hashes"])


@pytest.mark.parametrize("content", ['{"search":[],"search":[],"holdout":[]}', '{"search":NaN,"holdout":[]}', '[]', '{'])
def test_invalid_manifest_fail_fast_no_children(setup, content):
    s = setup
    s["path"].write_text(content)
    report = execute(s)
    assert report["status"] == "NONPROMOTION" and report["error"]["type"]
    assert not s["children"]


def test_fixed_children_never_follow_symlinks_or_case_path_strings(setup, tmp_path):
    s = setup
    # IDs are display strings, hashed before they can become a filesystem path.
    s["manifest"]["search"][0]["id"] = "../../outside"
    write_manifest(s)
    key = digest({"candidate_id": s["proposal"]["id"], "evaluation_root": str(s["root"].resolve())})
    trial_root = s["origin"].directory / "procedure-trials"
    external = tmp_path / "outside"
    external.mkdir()
    trial_root.symlink_to(external, target_is_directory=True)
    assert execute(s)["status"] == "NONPROMOTION" and not s["children"]
    assert list(external.iterdir()) == []


def test_operator_single_call_limits_and_optional_case_caps_preserved(setup):
    s = setup
    for split in ("search", "holdout"):
        spec = s["manifest"][split][0]["spec"]
        spec.update(timeout=2.5, parallelism=1, max_calls=20, max_iterations=4)
    write_manifest(s)
    report = execute(s)
    assert report["status"] == "NONPROMOTION", report
    assert all(c.spec["timeout"] == 2.5 and c.spec["parallelism"] == 1 and c.spec["max_calls"] == 20 for c in s["children"])
    for child in s["children"]:
        assert all(r.timeout <= 2.5 for d in child.drivers.values() for r in d.requests)
