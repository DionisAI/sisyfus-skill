import json
from pathlib import Path

from sisyfus.research_v2.engine import ResearchEngine


def base_spec(**stop_policy):
    spec = {
        "id": "v073-test",
        "topic": "Funding rate arbitrage stability research",
        "claims": [{"id": "c1", "statement": "Candidate works"}],
        "verification_contracts": [
            {
                "id": "verify-c1",
                "target_claim_id": "c1",
                "pass_if": {"all": [{"path": "metrics.score", "op": ">=", "value": 0.7}]},
                "fail_if": {"all": [{"path": "metrics.score", "op": "<", "value": 0.3}]},
            }
        ],
        "budget": {"max_attempts": 10, "max_cost_units": 10},
    }
    if stop_policy:
        spec["stop_policy"] = stop_policy
    return spec


def experiment(exp_id, *, context="a", based_on=None, action=None):
    value = {
        "id": exp_id,
        "title": exp_id,
        "target_claim_ids": ["c1"],
        "contract_id": "verify-c1",
        "context_id": context,
        "action": action or {"kind": "external", "notes": exp_id},
        "expected_outcomes": {
            "pass": "supports",
            "fail": "refutes",
            "inconclusive": "uncertain",
            "invalid": "bad measurement",
        },
        "cost": {"units": 1},
    }
    if based_on is not None:
        value["based_on"] = based_on
    return value


def settle(engine, exp_id, score):
    attempt = engine.begin_attempt(exp_id)
    return engine.settle_attempt(attempt["id"], {"metrics": {"score": score}})


def write_global_lessons(root: Path, items):
    path = root / ".sisyfus" / "research" / "global_lessons.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items), encoding="utf-8")


# ---------- visual replay frames ----------


def test_replay_frames_cover_every_event_and_match_live_snapshot(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, base_spec())
    engine.propose_experiment(experiment("e1"))
    settle(engine, "e1", 0.8)
    events = engine.events
    frames = json.loads(engine.workspace.report_frames_path.read_text(encoding="utf-8"))["frames"]
    assert len(frames) == len(events)
    assert [f["seq"] for f in frames] == [e["seq"] for e in events]
    snapshot = engine.snapshot()
    assert frames[-1]["objective"] == snapshot["progress"]["objective"]
    assert frames[-1]["current_state_id"] == snapshot["current_state_id"]
    assert frames[0]["objective"] == 0.0
    assert frames[-1]["claim_statuses"]["c1"] == "SUPPORTED"


def test_replay_frames_cache_extends_incrementally_without_rewriting_prefix(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, base_spec(stop_on_goal_pass=False))
    engine.propose_experiment(experiment("e1"))
    settle(engine, "e1", 0.8)
    before = json.loads(engine.workspace.report_frames_path.read_text(encoding="utf-8"))["frames"]
    engine.propose_experiment(experiment("e2", context="b"))
    settle(engine, "e2", 0.9)
    after = json.loads(engine.workspace.report_frames_path.read_text(encoding="utf-8"))["frames"]
    assert len(after) > len(before)
    assert after[: len(before)] == before


def test_replay_frames_flag_progress_rollback(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, base_spec(stop_on_goal_pass=False))
    engine.propose_experiment(experiment("e1"))
    settle(engine, "e1", 0.8)
    engine.propose_experiment(experiment("e2", context="b"))
    settle(engine, "e2", 0.1)
    frames = json.loads(engine.workspace.report_frames_path.read_text(encoding="utf-8"))["frames"]
    rollback_frames = [f for f in frames if f.get("rollback")]
    assert rollback_frames
    assert rollback_frames[-1]["rollback"]["progress_rollback"] is True
    assert frames[-1]["claim_statuses"]["c1"] == "REFUTED"


def test_report_embeds_frames_and_replay_controls(tmp_path: Path):
    spec = base_spec()
    spec["claims"][0]["label"] = "候选有效"
    spec["i18n"] = {"en": {"topic": "Candidate viability study", "claims": {"c1": {"label": "viability", "statement": "The candidate works"}}}}
    engine = ResearchEngine.create(tmp_path, spec)
    engine.propose_experiment(experiment("e1"))
    settle(engine, "e1", 0.8)
    snapshot = engine.snapshot()
    assert snapshot["claims"]["c1"]["label"] == "候选有效"
    assert snapshot["i18n"]["en"]["claims"]["c1"]["label"] == "viability"
    page = engine.workspace.report_path.read_text(encoding="utf-8")
    assert "replaySlider" in page
    assert '"frames"' in page
    assert "unitCard" in page
    assert "候选有效" in page
    assert "Candidate viability study" in page


def test_report_merges_translation_sidecar(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, base_spec())
    engine.workspace.i18n_path.write_text(
        json.dumps({"zh": {"topic": "候选研究可行性", "claims": {"c1": {"label": "可行性", "statement": "候选方法有效"}}}}, ensure_ascii=False),
        encoding="utf-8",
    )
    engine.propose_experiment(experiment("e1"))
    settle(engine, "e1", 0.8)
    payload = json.loads(engine.workspace.report_snapshot_path.read_text(encoding="utf-8"))
    assert payload["translations"]["zh"]["claims"]["c1"]["label"] == "可行性"
    assert "候选研究可行性" in engine.workspace.report_path.read_text(encoding="utf-8")
    payload = json.loads(engine.workspace.report_snapshot_path.read_text(encoding="utf-8"))
    assert payload["frames"]
    assert payload["frames"][-1]["run_status"] == "SOLVED"


def test_replay_stays_deterministic_with_new_projections(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, base_spec())
    engine.propose_experiment(experiment("e1"))
    settle(engine, "e1", 0.8)
    assert engine.verify_replay()["deterministic"]


def test_omitted_budget_means_unlimited(tmp_path: Path):
    spec = base_spec(stop_on_goal_pass=False)
    del spec["budget"]
    engine = ResearchEngine.create(tmp_path, spec)
    snapshot = engine.snapshot()
    budget = snapshot["budget"]
    assert budget["max_attempts"] is None
    assert budget["attempts_remaining"] is None
    assert budget["cost_units_remaining"] is None
    assert budget["wall_minutes_remaining"] is None
    big = experiment("e-big")
    big["cost"] = {"attempts": 1, "units": 9999}
    assert engine.propose_experiment(big)["admission"]["accepted"], "no budget gate when unlimited"
    settle(engine, "e-big", 0.8)
    after = engine.snapshot()
    assert after["run_status"] == "ACTIVE"
    assert after["budget"]["cost_units_used"] == 9999
    assert engine.verify_replay()["deterministic"]


def test_declared_budget_still_hard(tmp_path: Path):
    spec = base_spec(stop_on_goal_pass=False)
    spec["budget"] = {"max_cost_units": 2}
    engine = ResearchEngine.create(tmp_path, spec)
    engine.propose_experiment(experiment("e1"))
    settle(engine, "e1", 0.8)
    engine.propose_experiment(experiment("e2", context="b"))
    settle(engine, "e2", 0.8)
    assert engine.snapshot()["run_status"] == "BUDGET_EXHAUSTED"


def test_goal_refuted_assessment_and_auto_finalize(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, base_spec())
    engine.propose_experiment(experiment("e1"))
    settle(engine, "e1", 0.1)
    snapshot = engine.snapshot()
    assert snapshot["run_status"] == "ACTIVE", "advisory by default; branch recovery stays possible"
    assert snapshot["terminal_assessment"] == "REFUTED"
    final = engine.finalize()
    assert final["run_status"] == "REFUTED"
    import pytest
    with pytest.raises(RuntimeError):
        engine.propose_experiment(experiment("e2", context="b"))


def test_stop_on_goal_refuted_hard_stops_without_budget(tmp_path: Path):
    spec = base_spec(stop_on_goal_refuted=True)
    del spec["budget"]
    engine = ResearchEngine.create(tmp_path, spec)
    engine.propose_experiment(experiment("e1"))
    settle(engine, "e1", 0.1)
    snapshot = engine.snapshot()
    assert snapshot["run_status"] == "REFUTED"
    import pytest
    with pytest.raises(RuntimeError):
        engine.propose_experiment(experiment("e2", context="b"))
    assert engine.verify_replay()["deterministic"]


def test_goal_refuted_not_assessed_while_experiments_in_flight(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, base_spec(stop_on_goal_refuted=True))
    engine.propose_experiment(experiment("e1"))
    engine.propose_experiment(experiment("e2", context="b"))
    settle(engine, "e1", 0.1)
    snapshot = engine.snapshot()
    assert snapshot["run_status"] == "ACTIVE", "e2 is still admitted and could rescue the goal"
    assert snapshot["terminal_assessment"] == "CONTINUE"


# ---------- citation discipline ----------


def test_citation_out_of_context_is_rejected(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, base_spec())
    result = engine.propose_experiment(
        experiment("e1", based_on={"lesson_ids": ["ghost-lesson"]})
    )
    assert not result["admission"]["accepted"]
    assert result["admission"]["reason"] == "citation_out_of_context"
    assert engine.snapshot()["experiments"]["e1"]["status"] == "BACKLOG"


def test_require_citations_allows_first_experiment_then_enforces(tmp_path: Path):
    engine = ResearchEngine.create(tmp_path, base_spec(require_citations=True, stop_on_goal_pass=False))
    first = engine.propose_experiment(experiment("e1"))
    assert first["admission"]["accepted"], "nothing citable yet, so the opening move is exempt"
    settled = settle(engine, "e1", 0.8)
    evidence_id = settled["evidence"]["id"]
    uncited = engine.propose_experiment(experiment("e2", context="b"))
    assert uncited["admission"]["reason"] == "missing_citations"
    cited = engine.propose_experiment(
        experiment("e3", context="c", based_on={"evidence_ids": [evidence_id]})
    )
    assert cited["admission"]["accepted"]


def test_citing_global_lesson_is_in_context_and_usage_is_tracked(tmp_path: Path):
    write_global_lessons(
        tmp_path,
        [
            {
                "research_id": "research-earlier",
                "lesson_id": "funding-snapshot-timing",
                "status": "ACTIVE",
                "topic": "funding arbitrage",
                "scope": {"tags": ["funding", "arbitrage"]},
                "observation": "Snapshots taken minutes before settlement are unstable",
                "recommendation": "Sample funding twice, one hour apart",
                "confidence": "high",
                "promoted_at": "2026-07-24T00:00:00Z",
            }
        ],
    )
    engine = ResearchEngine.create(tmp_path, base_spec())
    result = engine.propose_experiment(
        experiment("e1", based_on={"lesson_ids": ["funding-snapshot-timing"]})
    )
    assert result["admission"]["accepted"]
    settle(engine, "e1", 0.8)
    usage = engine.snapshot()["lesson_usage"]["funding-snapshot-timing"]
    assert usage["experiment_ids"] == ["e1"]
    assert usage["verdicts"] == {"PASS": 1}


# ---------- deterministic reproduction ----------


def command_experiment(exp_id, command, metrics_path):
    value = experiment(exp_id, action={"kind": "command", "command": command})
    value["action"]["metrics_path"] = metrics_path
    return value


def test_reproduce_stable_evidence(tmp_path: Path):
    import sys

    engine = ResearchEngine.create(tmp_path, base_spec())
    command = f"{sys.executable} -c \"import json; json.dump({{'score': 0.9}}, open('m.json', 'w'))\""
    engine.propose_experiment(command_experiment("e1", command, "m.json"))
    result = engine.execute_experiment("e1")
    assert result["verdict"]["status"] == "PASS"
    evidence_id = result["evidence"]["id"]
    outcome = engine.reproduce_evidence(evidence_id)
    assert outcome["code_intact"] is True
    assert outcome["contract_intact"] is True
    assert outcome["deterministic_match"] is True
    assert outcome["verdict_stable"] is True
    assert outcome["reproduced_status"] == "PASS"
    snapshot = engine.snapshot()
    repro = snapshot["evidence"][evidence_id]["reproductions"]
    assert len(repro) == 1 and repro[0]["verdict_stable"] is True
    assert engine.verify_replay()["deterministic"]


def test_reproduce_flags_drift_and_flipped_verdict(tmp_path: Path):
    import sys

    engine = ResearchEngine.create(tmp_path, base_spec(stop_on_goal_pass=False))
    (tmp_path / "data.txt").write_text("0.9", encoding="utf-8")
    script = tmp_path / "measure.py"
    script.write_text(
        "import json\nscore = float(open('data.txt').read())\n"
        "json.dump({'score': score}, open('m.json', 'w'))\n",
        encoding="utf-8",
    )
    engine.propose_experiment(command_experiment("e1", f"{sys.executable} measure.py", "m.json"))
    result = engine.execute_experiment("e1")
    assert result["verdict"]["status"] == "PASS"
    evidence_id = result["evidence"]["id"]
    (tmp_path / "data.txt").write_text("0.1", encoding="utf-8")  # world changed; code intact
    outcome = engine.reproduce_evidence(evidence_id)
    assert outcome["code_intact"] is True
    assert outcome["deterministic_match"] is False
    assert outcome["metric_drift"]["score"] == {"recorded": 0.9, "reproduced": 0.1}
    assert outcome["reproduced_status"] == "FAIL"
    assert outcome["verdict_stable"] is False
    assert engine.verify_replay()["deterministic"]


def test_reproduce_refuses_external_evidence(tmp_path: Path):
    import pytest

    engine = ResearchEngine.create(tmp_path, base_spec())
    engine.propose_experiment(experiment("e1"))
    settled = settle(engine, "e1", 0.8)
    with pytest.raises(RuntimeError):
        engine.reproduce_evidence(settled["evidence"]["id"])


# ---------- scope-aware retrieval and efficacy ----------


def test_global_lessons_rank_relevant_scope_above_recent_unrelated(tmp_path: Path):
    write_global_lessons(
        tmp_path,
        [
            {
                "research_id": "research-old",
                "lesson_id": "funding-related",
                "status": "ACTIVE",
                "topic": "funding rate arbitrage",
                "scope": {"tags": ["funding", "arbitrage", "stability"]},
                "observation": "Funding rate stability requires repeated sampling",
                "recommendation": "Check funding stability across settlements",
                "promoted_at": "2026-07-01T00:00:00Z",
            },
            {
                "research_id": "research-newer",
                "lesson_id": "webscrape-unrelated",
                "status": "ACTIVE",
                "topic": "web scraping etiquette",
                "scope": {"tags": ["scraping", "robots"]},
                "observation": "Crawlers get blocked without delays",
                "recommendation": "Throttle crawler requests",
                "promoted_at": "2026-07-20T00:00:00Z",
            },
        ],
    )
    engine = ResearchEngine.create(tmp_path, base_spec())
    lessons = engine.global_lessons()
    assert [x["lesson_id"] for x in lessons] == ["funding-related", "webscrape-unrelated"]
    assert lessons[0]["relevance"] > lessons[1]["relevance"]


def test_lesson_efficacy_aggregates_across_runs_and_reaches_planner_context(tmp_path: Path):
    write_global_lessons(
        tmp_path,
        [
            {
                "research_id": "research-earlier",
                "lesson_id": "funding-snapshot-timing",
                "status": "ACTIVE",
                "topic": "funding arbitrage stability",
                "scope": {"tags": ["funding"]},
                "observation": "obs",
                "recommendation": "rec",
                "promoted_at": "2026-07-24T00:00:00Z",
            }
        ],
    )
    engine = ResearchEngine.create(tmp_path, base_spec())
    engine.propose_experiment(
        experiment("e1", based_on={"lesson_ids": ["funding-snapshot-timing"]})
    )
    settle(engine, "e1", 0.8)
    stats = engine.lesson_efficacy()
    assert stats["funding-snapshot-timing"]["uses"] == 1
    assert stats["funding-snapshot-timing"]["verdicts"] == {"PASS": 1}
    assert stats["funding-snapshot-timing"]["runs"] == [engine.workspace.research_id]
    context = engine.planner_context()
    entry = next(x for x in context["global_lessons"] if x["lesson_id"] == "funding-snapshot-timing")
    assert entry["efficacy"]["uses"] == 1
