from __future__ import annotations

import json
import shlex
import sys
from dataclasses import asdict
from pathlib import Path

from ..research_v2.engine import ResearchEngine
from ..research_v2.workspace import atomic_write_json
from .controller import ResearchOS, configure, export_history
from .lab import optimize
from .policy import SchedulingPolicy

FAMILIES = {
    "absolute": ["x", "abs(x)", "-x"],
    "square": ["x+1", "x*x", "abs(x)"],
    "nonnegative": ["x", "abs(x)", "max(x,0)"],
    "cube": ["x*x", "x*x*x", "abs(x)"],
}


def create_demo(root: Path, family: str, *, policy: SchedulingPolicy | None = None, episode: str | None = None) -> ResearchEngine:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / ".sisyfus" / "research").exists():
        raise ValueError("demo workspace already contains research; choose a new path")
    root.joinpath("measurement.py").write_text(Path(__file__).with_name("measurement.py").read_text())
    claims = [{"id": f"c{i}", "statement": f"Candidate {i} implements {family} on the fixed checks"} for i in range(3)]
    contracts = [{"id": f"v{i}", "target_claim_id": f"c{i}",
                  "required_artifacts": [f"measurement-{i}.json"],
                  "pass_if": [{"path": "metrics.score", "op": "==", "value": 1.0}],
                  "fail_if": [{"path": "metrics.score", "op": "<", "value": 1.0}]} for i in range(3)]
    spec = {"id": episode or family, "topic": f"Validate bounded {family} expressions", "claims": claims,
            "verification_contracts": contracts, "budget": {"max_attempts": 6, "max_cost_units": 6},
            "stop_policy": {"stop_on_goal_pass": False, "stop_on_goal_refuted": False},
            "metadata": {"task_family": family, "demo": True}}
    engine = ResearchEngine.create(root, spec, render=False)
    for i, expression in enumerate(FAMILIES[family]):
        root.joinpath(f"candidate-{i}.json").write_text(json.dumps({"expression": expression}))
        argv = [sys.executable, "-I", "measurement.py", "--candidate", f"candidate-{i}.json", "--family", family, "--output", f"measurement-{i}.json"]
        engine.propose_experiment({
            "id": f"e{i}", "title": f"Evaluate expression {expression}", "rationale": "Compare this expression to the fixed mathematical reference.",
            "target_claim_ids": [f"c{i}"], "contract_id": f"v{i}", "context_id": f"candidate-{i}",
            "action": {"kind": "command", "command": shlex.join(argv), "cwd": str(root),
                       "timeout_seconds": 10, "parse_stdout_json": True,
                       "code_paths": ["measurement.py", f"candidate-{i}.json"], "artifact_paths": [f"measurement-{i}.json"]},
            "expected_outcomes": {"pass": "matches reference", "fail": "counterexample found", "inconclusive": "insufficient cases", "invalid": "invalid measurement"},
            "priority": {"goal_progress": 0.5, "information_gain": 0.5, "novelty": min(len(expression) / 20, 1)},
            "cost": {"units": 1}, "metadata": {"research_family": family},
        })
    configure(engine, policy=policy, replay_mode="independent", actor="offline-demo-operator")
    return engine


def run_demo(root: Path) -> dict:
    root = root.resolve()
    histories = []
    runs = []
    for family in FAMILIES:
        engine = create_demo(root / family, family)
        report = ResearchOS(engine).run(max_steps=6, allow_local_commands=True)
        history = export_history(engine)
        histories.append(history)
        atomic_write_json(root / f"{family}-history.json", history)
        runs.append({**asdict(report), "deterministic_replay": engine.verify_replay()["deterministic"],
                     "valid_resolutions": sum(n["outcome"]["verdict"] in {"PASS", "FAIL"} for n in history["nodes"])})
    candidate = optimize(histories[:2], histories[2:3], histories[3:], budget=2)
    atomic_write_json(root / "policy-candidate.json", candidate)
    summary = {"scope": "real arithmetic subprocesses; no LLM generation or live Jev calls", "runs": runs,
               "candidate_status": candidate["status"], "holdout": candidate["holdout"],
               "real_llm_executed": False, "live_jev_executed": False,
               "automatic_policy_activation": False, "beats_gpt6_astra": None,
               "cost_units_are": "preregistered abstract evaluation units, not dollars or seconds"}
    atomic_write_json(root / "summary.json", summary)
    return summary
