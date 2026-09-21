import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sisyfus.research_os.benchmark import (
    ARMS, inspect_benchmark, load_suite, parse_candidates, run_benchmark,
)
from sisyfus.research_os.benchmark_fixture import FixtureProvider, create_fixture, measure
from sisyfus.research_os.benchmark_provider import Limits, Meter, OpenAIProvider, Rates, Reply
from sisyfus.research_os.policy import SchedulingPolicy
from sisyfus.research_v2.engine import ResearchEngine


@pytest.fixture(autouse=True)
def no_ui(monkeypatch):
    # Rendering is covered by the existing Observatory tests, not needed per pilot trial.
    original = ResearchEngine._persist
    monkeypatch.setattr(ResearchEngine, "_persist", lambda self, snap, *, render: original(self, snap, render=False))
    monkeypatch.setenv("SISYFUS_AUTO_SERVE", "0")


@pytest.fixture
def suite(tmp_path):
    path = create_fixture(tmp_path / "fixture")
    raw = json.loads(path.read_text())
    raw["tasks"] = raw["tasks"][:1]
    path.write_text(json.dumps(raw))
    return path


def pilot(path, output, provider=None, **kw):
    return run_benchmark(path, output, provider or FixtureProvider(),
                         limits=kw.pop("limits", Limits(max_calls=1, max_evaluations=1)),
                         rates=Rates(1, 1), **kw)


@pytest.mark.parametrize("bad", [True, -1, 0, 1.5, float("nan"), 10000001])
def test_invalid_limits(bad):
    with pytest.raises(ValueError):
        Limits(max_calls=bad)


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "cached_tokens", "reasoning_tokens"])
def test_invalid_usage_counts(field):
    kwargs = dict(text="x", response_id="response", actual_model="model", input_tokens=1, output_tokens=1)
    kwargs[field] = True
    with pytest.raises(ValueError):
        Reply(**kwargs)


def test_reasoning_tokens_not_double_billed_and_reserve_max_output():
    meter = Meter(Limits(max_output_per_call=10, max_output_tokens=12), Rates(2, 5))
    assert meter.reserve(100) == 10
    assert meter.reserved == pytest.approx(0.00025)
    meter.settle(Reply("", "a", "m", 100, 8, reasoning_tokens=7, cached_tokens=50))
    assert meter.outputs == 8
    assert meter.spent == pytest.approx(0.00024)
    assert meter.reserve(100) == 4
    with pytest.raises(RuntimeError, match="unresolved"):
        meter.reserve(100)


def test_no_generation_when_dollar_reservation_cannot_fit():
    meter = Meter(Limits(max_usd=0.000001), Rates(100, 100))
    assert meter.reserve(100) == 0
    assert meter.calls == 0


def test_oversized_usage_invalidates_envelope():
    meter = Meter(Limits(max_output_per_call=2), Rates(1, 1))
    meter.reserve(2)
    meter.settle(Reply("", "a", "m", 3, 3))
    assert meter.violated
    assert meter.spent == pytest.approx(6e-6)


@pytest.mark.parametrize("text", ["{}", '{"candidates":[]}', '{"candidates":[{"artifact":{},"command":"rm"}]}',
    '{"candidates":[{"artifact":{},"priority":{"goal_progress":NaN}}]}',
    '{"candidates":[{"artifact":{},"priority":{"goal_progress":true}}]}',
    '{"candidates":[{"artifact":{},"priority":{"verdict":1}}]}',
    '{"candidates":[{"artifact":{},"title":[]}]}'])
def test_provider_cannot_inject_controls(text):
    with pytest.raises((ValueError, TypeError)):
        parse_candidates(text)


def test_safe_artifact_accepts_json_but_does_not_execute_it(tmp_path):
    destination = tmp_path / "marker"
    result = measure({"expression": f"__import__('pathlib').Path('{destination}').touch()"},
                     [{"inputs": {"x": 1}, "expected": 1}])
    assert result["metrics"]["score"] == 0
    assert not destination.exists()


def test_empty_or_invalid_suite_rejected(suite):
    raw = json.loads(suite.read_text())
    raw["tasks"].append(raw["tasks"][0])
    suite.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="duplicate"):
        load_suite(suite)


def test_sdk_no_retries_count_and_usage_shape():
    calls = []
    response = SimpleNamespace(output_text='{"candidates":[]}', id="resp", model="exact", status="completed",
        usage=SimpleNamespace(input_tokens=20, output_tokens=30,
                              input_tokens_details=SimpleNamespace(cached_tokens=10),
                              output_tokens_details=SimpleNamespace(reasoning_tokens=25)))
    class Fake:
        def with_options(self, **kw):
            assert kw["max_retries"] == 0
            return self
        def count(self, **kw):
            calls.append(("count", kw))
            return SimpleNamespace(input_tokens=20)
        def create(self, **kw):
            calls.append(("create", kw))
            return response
    client = Fake()
    client.responses = client.input_tokens = client
    provider = OpenAIProvider("exact", client=client)
    messages = [{"role": "user", "content": "public only"}]
    assert provider.count_input(messages, 10) == 20
    reply = provider.generate(messages, 100, 10)
    assert reply.output_tokens == 30 and reply.reasoning_tokens == 25
    assert calls[1][1]["store"] is False
    assert "tools" not in calls[1][1]
    assert not provider.live


def test_no_credentials_fails_without_network(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="no provider request"):
        OpenAIProvider("explicit-model")


def test_end_to_end_same_limits_final_hidden_and_no_false_gain(suite, tmp_path):
    class Spy(FixtureProvider):
        messages = []
        def generate(self, messages, cap, timeout):
            self.messages.append(json.dumps(messages))
            return super().generate(messages, cap, timeout)
    provider = Spy()
    result = pilot(suite, tmp_path / "run", provider)
    assert len(provider.messages) == 3
    assert all('"holdout"' not in m and '"expected"' not in m and "-7" not in m for m in provider.messages)
    assert result["complete_comparable_run"]
    assert not result["real_llm_executed"] and result["beats_gpt6_astra"] is None
    assert result["accounting_kind"].startswith("synthetic")
    for arm in ARMS:
        assert result["arms"][arm]["provider_calls"] == 1
        assert result["arms"][arm]["evaluations"] == 1
        assert result["arms"][arm]["development_false_positives"] == 1
        assert result["arms"][arm]["passed"] == 0
    events = [json.loads(line) for line in (tmp_path / "run" / "audit.jsonl").read_text().splitlines()]
    frozen = next(i for i, e in enumerate(events) if e["kind"] == "ALL_SELECTIONS_FROZEN")
    assert all(i > frozen for i, e in enumerate(events) if e["kind"] == "FINAL_RESULT")
    assert all(i < frozen for i, e in enumerate(events) if e["kind"] == "PROVIDER_INTENT")
    assert inspect_benchmark(tmp_path / "run")["summary_verified"]


def test_fatal_provider_stops_whole_suite_keeps_reservation_redacts(suite, tmp_path):
    class Broken(FixtureProvider):
        attempts = 0
        def generate(self, *args):
            self.attempts += 1
            raise TimeoutError("sk-DO-NOT-LOG-SECRET")
    provider = Broken()
    result = pilot(suite, tmp_path / "run", provider)
    assert provider.attempts == 1 and len(result["rows"]) == 1
    assert not result["complete_comparable_run"]
    status = inspect_benchmark(tmp_path / "run")
    assert len(status["unresolved_requests"]) == 1
    assert status["unresolved_requests"][0]["reserved_usd"] > 0
    assert "DO-NOT-LOG-SECRET" not in (tmp_path / "run" / "audit.jsonl").read_text()
    assert all(s["planned"] == 1 for s in result["arms"].values())
    with pytest.raises(ValueError, match="empty"):
        pilot(suite, tmp_path / "run", provider)
    assert provider.attempts == 1


def test_input_count_error_never_generates(suite, tmp_path):
    class Broken(FixtureProvider):
        def count_input(self, *args):
            raise ValueError("bad counter")
        def generate(self, *args):
            raise AssertionError("must not generate")
    result = pilot(suite, tmp_path / "run", Broken())
    assert result["rows"][0]["state"] == "input_count_error"
    assert result["rows"][0]["meter"]["calls"] == 0


def test_incomplete_and_malformed_outputs_are_billed(suite, tmp_path):
    class Broken(FixtureProvider):
        def generate(self, messages, cap, timeout):
            reply = super().generate(messages, cap, timeout)
            return replace(reply, text="broken", status="incomplete")
    result = pilot(suite, tmp_path / "run", Broken())
    for row in result["rows"]:
        assert row["meter"]["calls"] == 1 and row["meter"]["token_priced_usd"] > 0
        assert row["final"]["verdict"] == "NOT_SUBMITTED"
        assert row["evaluations"] == 0


def test_model_fallback_stops_suite(suite, tmp_path):
    class Fallback(FixtureProvider):
        def generate(self, *args):
            return replace(super().generate(*args), actual_model="unapproved-model")
    result = pilot(suite, tmp_path / "run", Fallback())
    assert len(result["rows"]) == 1
    assert result["rows"][0]["state"] == "model_or_budget_mismatch"
    assert not result["complete_comparable_run"]


def test_suite_nominal_dollar_ceiling_before_request(suite, tmp_path):
    class PretendLive(FixtureProvider):
        live = True
        def count_input(self, *args):
            raise AssertionError("no network should be attempted")
    with pytest.raises(ValueError, match="nominal suite"):
        pilot(suite, tmp_path / "run", PretendLive(), max_total_usd=2)
    assert not (tmp_path / "run").exists()


def test_candidate_cannot_modify_evaluator_before_autoapproval(suite, tmp_path):
    class Tamper(FixtureProvider):
        def generate(self, *args):
            next((tmp_path / "run").glob("*/evaluator.py")).write_text("print('forged evaluator')")
            return super().generate(*args)
    with pytest.raises(RuntimeError, match="preregistered evaluator"):
        pilot(suite, tmp_path / "run", Tamper())
    audit = inspect_benchmark(tmp_path / "run")
    assert audit["event_counts"]["RUN_ERROR"] == 1
    assert audit["event_counts"].get("DEVELOPMENT_RESULT", 0) == 0


def test_real_controller_path_called(suite, tmp_path, monkeypatch):
    from sisyfus.research_os.controller import ResearchOS
    original = ResearchOS.run
    calls = []
    def track(self, **kw):
        calls.append(str(self.engine.workspace.root))
        return original(self, **kw)
    monkeypatch.setattr(ResearchOS, "run", track)
    pilot(suite, tmp_path / "run")
    assert len(calls) == 4  # OS development + all three independent final evaluations.
    assert sum(p.endswith("research_os") for p in calls) == 1


def test_baseline_refines_but_independent_search_has_no_feedback(suite, tmp_path):
    class Spy(FixtureProvider):
        seen_requests = []
        def generate(self, messages, cap, timeout):
            self.seen_requests.append(json.loads(messages[1]["content"]))
            return super().generate(messages, cap, timeout)
    provider = Spy()
    pilot(suite, tmp_path / "run", provider, limits=Limits(max_calls=2, max_evaluations=2))
    assert len(provider.seen_requests) == 6
    assert sum(bool(m["development_feedback"]) for m in provider.seen_requests) == 2


def test_audit_and_report_tampering_detected(suite, tmp_path):
    pilot(suite, tmp_path / "run")
    p = tmp_path / "run" / "summary.json"
    report = json.loads(p.read_text())
    report["real_llm_executed"] = True
    p.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="summary"):
        inspect_benchmark(tmp_path / "run")
    p.unlink()
    p = tmp_path / "run" / "audit.jsonl"
    p.write_text(p.read_text().replace('"REGISTERED"', '"TAMPERED"'))
    with pytest.raises(ValueError, match="chain"):
        inspect_benchmark(tmp_path / "run")


def test_crash_after_intent_inspectable_without_retry(suite, tmp_path):
    class Crash(FixtureProvider):
        def generate(self, *args):
            raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        pilot(suite, tmp_path / "run", Crash())
    result = inspect_benchmark(tmp_path / "run")
    assert result["unresolved_requests"] and not result["can_auto_resume"]


def test_paid_judge_without_accounting_rejected(suite, tmp_path):
    with pytest.raises(ValueError, match="paid judge"):
        pilot(suite, tmp_path / "run", policy=SchedulingPolicy(judgment_weight=1))


def test_cli_refuses_unapproved_live_calls():
    from sisyfus.research_os.cli import main
    assert main(["benchmark", "--suite", "unused", "--output", "unused", "--model", "x", "--rates", "unused"]) == 1


def test_final_evaluator_error_invalidates_comparison(suite, tmp_path):
    evaluator = suite.parent / 'evaluator.py'
    source = evaluator.read_text()
    source = source.replace('result = measure(json.loads', "\n    if args.split == 'holdout':\n        raise RuntimeError('broken final evaluator')\n    result = measure(json.loads")
    evaluator.write_text(source)
    result = pilot(suite, tmp_path / 'run')
    assert all(row['final']['verdict'] == 'ERROR' for row in result['rows'])
    assert not result['complete_comparable_run']


def test_output_syntax_failures_spend_budget_not_dropped(suite, tmp_path):
    class Invalid(FixtureProvider):
        def generate(self, *args):
            return replace(super().generate(*args), text='not-json')
    result = pilot(suite, tmp_path / 'run', Invalid())
    assert len(result['rows']) == 3
    for row in result['rows']:
        assert row['errors'] == ['invalid_candidate_response']
        assert row['meter']['calls'] == 1
        assert row['meter']['token_priced_usd'] > 0
        assert row['final']['verdict'] == 'NOT_SUBMITTED'


_HOLDOUT_CANARY = 'PRIVATE_HOLDOUT_CANARY_5adb9821'


def _assert_no_heldout_payload(value):
    # Match structured private data, not substrings in opaque IDs or hashes.
    if isinstance(value, dict):
        assert not {'holdout', 'cases', 'inputs', 'expected', 'private_canary'} & value.keys()
        for child in value.values():
            _assert_no_heldout_payload(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_heldout_payload(child)
    elif isinstance(value, str):
        assert _HOLDOUT_CANARY not in value
    elif type(value) in (int, float):
        assert value != -7


def test_development_export_does_not_include_final_data(suite, tmp_path, monkeypatch):
    # Reproduce the CI collision: a legitimate opaque run ID contains '-7'.
    monkeypatch.setattr('sisyfus.research_v2.workspace.make_run_id',
                        lambda prefix: prefix + 'frozen-7b6b5a9d')
    cases = suite.parent / 'absolute.json'
    private = json.loads(cases.read_text())
    private['holdout'][0]['private_canary'] = _HOLDOUT_CANARY
    cases.write_text(json.dumps(private))
    report = pilot(suite, tmp_path / 'run')
    history = json.loads(next((tmp_path / 'run').glob('*research_os/history.json')).read_text())
    assert '-7' in history['research_id']
    assert len(history['nodes']) == 1
    assert history['nodes'][0]['outcome']['verdict'] == 'PASS'
    assert all(row['final']['verdict'] == 'FAIL' for row in report['rows'])
    _assert_no_heldout_payload(history)


@pytest.mark.parametrize('leak', [
    {'holdout': []}, {'nested': [{'expected': 7}]},
    {'value': -7}, {'text': _HOLDOUT_CANARY},
])
def test_export_leakage_assertion_rejects_private_payload(leak):
    with pytest.raises(AssertionError):
        _assert_no_heldout_payload(leak)


def test_release_undispatched_reservation_does_not_count_provider_call():
    meter = Meter(Limits(max_calls=1, max_output_per_call=10), Rates(1, 1))
    assert meter.reserve(10) == 10
    assert meter.calls == 1 and meter.pending is not None
    meter.release()
    assert meter.calls == 0 and meter.pending is None and meter.reserved == 0
    with pytest.raises(RuntimeError, match="no reserved"):
        meter.release()
