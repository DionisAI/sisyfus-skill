"""Offline canonical helper checks, never evidence of real Opus/Sol execution."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from sisyfus.workers.protocol import Receipt


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/live_review_negative.py"
SPEC = importlib.util.spec_from_file_location("live_review_negative_helpers", SCRIPT)
helper = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = helper
SPEC.loader.exec_module(helper)

# Independent test-side contract, kept outside the candidate. Six behavior tests
# intentionally omit payload-output assertions to expose the reviewer gate.
CHECKER = '''import importlib.util, json, pathlib, sys, unittest
spec = importlib.util.spec_from_file_location("job", pathlib.Path(sys.argv[1]) / "job.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
class Acceptance(unittest.TestCase):
    def test_success(self):
        self.assertEqual(module.poll_job(lambda _: {"status": "succeeded", "result": 42}, "job"), 42)
    def test_pending(self):
        states = iter([{"status": "queued"}, {"status": "running"}, {"status": "succeeded", "result": 42}])
        calls = []
        def fetch(ident):
            calls.append(ident)
            return next(states)
        self.assertEqual(module.poll_job(fetch, "job", max_attempts=3), 42)
        self.assertEqual(calls, ["job"] * 3)
    def test_failure(self):
        with self.assertRaises(RuntimeError):
            module.poll_job(lambda _: {"status": "failed", "error": "fixture failure"}, "job")
    def test_timeout(self):
        calls = []
        def fetch(ident):
            calls.append(ident)
            return {"status": "running"}
        with self.assertRaises(TimeoutError):
            module.poll_job(fetch, "job", max_attempts=2)
        self.assertEqual(len(calls), 2)
    def test_transient(self):
        calls = []
        def fetch(ident):
            calls.append(ident)
            if len(calls) == 1:
                raise OSError("fixture transport error")
            return {"status": "succeeded", "result": 42}
        self.assertEqual(module.poll_job(fetch, "job", max_attempts=2), 42)
    def test_invalid(self):
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.poll_job(lambda _: {"status": "succeeded", "result": 42}, "job", max_attempts=value)
result = unittest.TestResult()
unittest.defaultTestLoader.loadTestsFromTestCase(Acceptance).run(result)
print(json.dumps({"accepted": result.wasSuccessful(), "tests": result.testsRun,
                 "failures": [trace for _, trace in result.failures + result.errors]}))
'''


@pytest.fixture
def prepared(tmp_path):
    source = tmp_path / "approved-project"
    source.mkdir()
    (source / "README.md").write_text("immutable operator fixture")
    checker = tmp_path / "trusted-check.py"
    checker.write_text(CHECKER)
    raw = {"objective": "Implement poll_job(fetch, job_id, max_attempts=5). Never print or log job payloads.",
        "source": str(source), "constraints": ["Only job.py is writable", "No payload logging"],
        "checks": {"polling": {"argv": [sys.executable, "-I", "-S", str(checker), "{candidate}"],
            "code_hashes": {str(checker): hashlib.sha256(checker.read_bytes()).hexdigest()},
            "contract": {"kind": "rules", "pass_if": {"all": [{"path": "accepted", "op": "eq", "value": True},
                                                              {"path": "tests", "op": "eq", "value": 6}]},
                "fail_if": {"all": [{"path": "accepted", "op": "eq", "value": False}]}}}},
        "required_checks": ["polling"], "integration_checks": ["polling"], "timeout": 3}
    mission_path = tmp_path / "approved-mission.json"
    helper.write_json(mission_path, raw)
    return helper.prepare(mission_path, tmp_path / "negative-controls")


class OfflineReview:
    def __init__(self, verdict="FAIL"):
        self.requests = []
        self.verdict = verdict

    def run(self, request, emit, controls):
        self.requests.append(request)
        payload = json.loads(request.prompt.split("\n", 1)[1])
        assert "No payload logging" in payload["constraints"]
        assert payload["deterministic_evidence"][0]["classification"]["status"] == "PASS"
        assert "Never print or log" in payload["mission_objective"]
        assert 'file=sys.stderr' in (Path(request.cwd) / "job.py").read_text()
        emit("offline_review_fixture", {"not_native": True})
        return Receipt("COMPLETED", session_id="OFFLINE_REVIEW_FIXTURE_NOT_NATIVE", requested_model=request.model,
            output=json.dumps({"verdict": self.verdict, "reasons": ["offline fixture: code logs payloads to stderr"],
                               "evidence": payload["evidence_references"]}))


def test_prepare_preserves_contract_and_never_dispatches(prepared):
    assert prepared["status"] == "PREPARED_NOT_EXECUTED"
    original = json.loads(Path(prepared["mission"]).read_text())
    for case in prepared["cases"].values():
        raw = json.loads(Path(case["specification"]).read_text())
        assert raw["checks"] == original["checks"]
        assert raw["objective"] == original["objective"] and raw["constraints"] == original["constraints"]
        assert raw["tasks"][0]["acceptance"] == original["objective"]
        assert raw["tasks"][0]["write_paths"] == ["job.py"]
        assert "ONLY exact" in raw["tasks"][0]["interface"]["review_receipt_format"]
        assert not Path(case["controller"]).exists()


def test_logging_specimen_passes_six_tests_and_canonical_review_rejects(prepared):
    reviewer = OfflineReview()
    case = prepared["cases"]["payload-logging"]
    proof = helper.exercise_case(case, "payload-logging", reviewer=reviewer)
    data = proof["evidence"]["payload"]["evidence"]
    assert proof["evidence"]["verdict"] == "FAIL" and proof["event_chain"]["valid"]
    assert data["checks"][0]["measurement"]["tests"] == 6
    assert data["checks"][0]["classification"]["status"] == "PASS"
    assert data["review"]["verdict"] == "FAIL"
    assert data["execution_kind"] == helper.SYNTHETIC and data["native_worker_execution"] is False
    assert data["actual_model"] is None and data["session_id"] is None
    assert len(reviewer.requests) == 1 and reviewer.requests[0].session_id is None
    assert reviewer.requests[0].mode == "read-only" and reviewer.requests[0].model == helper.OPUS
    assert not proof["snapshot"]["all_verified"]
    from sisyfus.workers.lead_mission import LeadMission
    reopened = LeadMission(Path(case["controller"]))
    assert reopened.store.latest_evidence(proof["continuation"]["id"])["id"] == proof["evidence"]["id"]
    assert reopened.store.verify_event_chain()["valid"]
    # Offline fixture success at the helper level must NEVER claim a real gate.
    with pytest.raises(ValueError, match="native-attested completion"):
        helper.require_negative(proof)


def test_obvious_bad_result_is_canonical_deterministic_fail_without_review(prepared):
    reviewer = OfflineReview()
    proof = helper.exercise_case(prepared["cases"]["obvious-bad-output"], "obvious-bad-output", reviewer=reviewer)
    assert proof["evidence"]["verdict"] == "FAIL"
    assert not reviewer.requests and not proof["reviews"]
    assert proof["evidence"]["payload"]["evidence"]["checks"][0]["measurement"]["tests"] == 6
    helper.require_negative(proof)


def test_independent_pass_does_not_count_as_negative_proof(prepared):
    proof = helper.exercise_case(prepared["cases"]["payload-logging"], "payload-logging", reviewer=OfflineReview("PASS"))
    assert proof["evidence"]["verdict"] == "PASS"
    with pytest.raises(ValueError, match="canonical negative evidence"):
        helper.require_negative(proof)


def test_prose_evidence_is_retained_as_invalid_not_relabelled_fail(prepared):
    class ProseReview(OfflineReview):
        def run(self, request, emit, controls):
            receipt = super().run(request, emit, controls)
            raw = json.loads(receipt.output)
            raw["evidence"] = ["job.py prints payloads to stderr"]
            return Receipt("COMPLETED", requested_model=request.model, output=json.dumps(raw))

    proof = helper.exercise_case(prepared["cases"]["payload-logging"], "payload-logging", reviewer=ProseReview())
    assert proof["evidence"]["verdict"] == "INVALID"
    assert proof["evidence"]["payload"]["evidence"]["checks"][0]["classification"]["status"] == "PASS"
    assert "unrecognized test evidence" in proof["evidence"]["payload"]["evidence"]["review"]["reasons"][0]
    with pytest.raises(ValueError, match="observed INVALID"):
        helper.require_negative(proof)


@pytest.mark.parametrize("target", ["specimen", "specification", "source"])
def test_prepared_drift_fails_before_native_dispatch(prepared, target):
    case = prepared["cases"]["payload-logging"]
    path = Path(case[target]) if target != "source" else Path(prepared["directory"]) / "source/README.md"
    with path.open("a") as stream:
        stream.write("\nchanged\n")
    with pytest.raises(ValueError, match="drift"):
        helper.exercise_case(case, "payload-logging", reviewer=OfflineReview())
    assert not Path(case["controller"]).exists()


def test_reexecution_preserves_canonical_failure_and_never_redispatches(prepared):
    reviewer = OfflineReview()
    case = prepared["cases"]["payload-logging"]
    proof = helper.exercise_case(case, "payload-logging", reviewer=reviewer)
    with pytest.raises(ValueError, match="never automatically redispatched"):
        helper.exercise_case(case, "payload-logging", reviewer=reviewer)
    assert len(reviewer.requests) == 1 and proof["evidence"]["verdict"] == "FAIL"


def test_exports_are_canonical_readbacks_and_fail_on_overwrite(prepared):
    case = prepared["cases"]["obvious-bad-output"]
    proof = helper.exercise_case(case, "obvious-bad-output", reviewer=OfflineReview())
    directory = Path(case["directory"])
    helper.export_proof(directory, proof)
    assert json.loads((directory / "evidence.json").read_text())["id"] == proof["evidence"]["id"]
    assert json.loads((directory / "event_chain.json").read_text())["valid"]
    lines = (directory / "events.jsonl").read_text().splitlines()
    assert len(lines) == len(proof["events"])
    with pytest.raises(FileExistsError):
        helper.export_proof(directory, proof)


def test_run_marker_prevents_unknown_or_failed_native_redispatch(prepared, monkeypatch):
    calls = []

    def fail(case, name):
        calls.append(name)
        raise ValueError("fixture unknown native outcome; no success proof")

    monkeypatch.setattr(helper, "exercise_case", fail)
    result = helper.run_prepared(prepared)
    assert result["status"] == "VALIDATION_ERROR"
    assert len(calls) == 2
    with pytest.raises(FileExistsError):
        helper.run_prepared(prepared)
    assert len(calls) == 2
