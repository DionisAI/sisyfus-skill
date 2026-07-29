from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

# Loopback requests must never go through a system/user proxy.
urlopen = build_opener(ProxyHandler({})).open

from sisyfus.cli import main
from sisyfus.dashboard import dashboard_state, serve_dashboard
from sisyfus.goal import write_goal_template
from sisyfus.orchestrator import SisyfusRunner
from sisyfus.review import ReviewStore, load_review_context
from sisyfus.scaffold import init_project


def _run_pass_session(root: Path) -> dict:
    init_project(root)
    goal_path = root / ".sisyfus" / "goals" / "pass.json"
    write_goal_template(goal_path, goal_id="pass", objective="pass command", commands=["printf ok"], max_rounds=1)
    return SisyfusRunner(root).run(goal_path, adapter_name="mock", apply_distill=False)


def test_human_review_marks_claim_and_enters_future_context(tmp_path: Path) -> None:
    final = _run_pass_session(tmp_path)
    store = ReviewStore(tmp_path)
    claims = store.claims()
    assert claims
    claim = claims[0]
    item = store.annotate(
        target_id=claim["claim_id"],
        target_type="claim",
        verdict="correct",
        note="human accepted this distill",
        run_id=claim["run_id"],
        goal_id=claim["goal_id"],
        claim=claim["claim"],
    )
    assert item["verdict"] == "correct"
    context = load_review_context(tmp_path)
    assert "Human-confirmed correct conclusions" in context
    assert claim["claim"] in context
    assert final["status"] == "PASSED"


def test_wrong_annotation_can_create_followup_task(tmp_path: Path) -> None:
    _run_pass_session(tmp_path)
    store = ReviewStore(tmp_path)
    claim = store.claims()[0]
    store.annotate(
        target_id=claim["claim_id"],
        target_type="claim",
        verdict="wrong",
        note="bad conclusion",
        run_id=claim["run_id"],
        goal_id=claim["goal_id"],
        claim=claim["claim"],
        next_action="re-run verifier with stricter checks",
    )
    tasks = (tmp_path / ".sisyfus" / "tasks" / "open.jsonl").read_text(encoding="utf-8")
    assert "re-run verifier" in tasks


def test_dashboard_state_and_http_feedback_api(tmp_path: Path) -> None:
    _run_pass_session(tmp_path)
    state = dashboard_state(tmp_path)
    assert state["stats"]["session_count"] == 1
    assert state["conclusions"]

    server, url = serve_dashboard(tmp_path, port=0, verbose=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        api_state = json.loads(urlopen(url + "api/state", timeout=5).read().decode("utf-8"))
        assert api_state["sessions"]
        claim = api_state["conclusions"][0]
        req = Request(
            url + "api/feedback",
            data=json.dumps({
                "target_id": claim["claim_id"],
                "target_type": "claim",
                "verdict": "wrong",
                "note": "human rejected",
                "run_id": claim["run_id"],
                "goal_id": claim["goal_id"],
                "claim": claim["claim"],
                "create_task": True,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        response = json.loads(urlopen(req, timeout=5).read().decode("utf-8"))
        assert response["verdict"] == "wrong"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_review_and_panel_cli(tmp_path: Path) -> None:
    _run_pass_session(tmp_path)
    assert main(["review", "claims", "--root", str(tmp_path)]) == 0
    assert main(["guidance", "add", "Next session should inspect verifier evidence", "--root", str(tmp_path), "--create-task"]) == 0
    assert main(["review", "context", "--root", str(tmp_path)]) == 0
    assert main(["panel", "state", "--root", str(tmp_path)]) == 0
    assert main(["panel", "snapshot", "--root", str(tmp_path)]) == 0
    assert (tmp_path / ".sisyfus" / "dashboard" / "snapshot.json").exists()
