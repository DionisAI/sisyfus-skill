from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any

from .model_policy import normalize_task_type
from .utils import read_json, slugify, write_json

DEFAULT_GOAL: dict[str, Any] = {
    "schema_version": "sisyfus.goal.v0.6",
    "id": "unnamed-goal",
    "objective": "",
    "task_type": "implementation",
    "context": {
        "read_memory": [".sisyfus/memory/index.md", ".sisyfus/memory/failures.jsonl"],
        "extra_files": [],
        "max_chars": None,
        "hard_max_chars": None,
        "read_recent_sessions": True,
        "recent_session_limit": 3,
    },
    "session_policy": {
        "one_task_per_session": True,
        "auto_distill": True,
        "record_session_index": True,
        "read_recent_sessions": True,
        "recent_session_limit": 3,
        "session_context_max_chars": 12000,
        "never_load_raw_transcripts_by_default": True,
    },
    "constraints": {
        "forbidden_paths": [],
        "require_tests": True,
        "require_small_diff": True,
        "max_changed_lines": 400,
    },
    "done_when": {
        "commands": [],
        "diff_requirements": [],
    },
    "monitors": [],
    "loop": {
        "max_rounds": 3,
        "max_wall_minutes": 45,
        "max_cost_usd": 5.0,
        "stop_if_same_failure_repeats": 2,
        "on_uncertain": "send_to_human_triage",
        "on_repeated_failure": "distill_failure_and_stop",
    },
    "worktree": {
        "isolate": False,
        "keep": True,
        "base_ref": "HEAD",
    },
    "model_policy": {
        "task_type": None,
        "default_profile": None,
    },
    "beam": {
        "enabled": False,
        "id": None,
        "width": 3,
        "max_depth": 1,
        "max_children_per_node": 3,
        "max_sessions_total": 9,
        "selection_metric": "score",
        "directions": [],
    },
    "outcome": {
        "enabled": False,
        "mode": "rubric",
        "rubric_id": None,
        "max_iterations": 3,
        "pass_threshold": None,
        "fail_fast_threshold": 0.25,
        "allow_pass_without_deterministic_verifier": False,
        "grader": {
            "role": "independent_grader",
            "model_profile": "balanced_ops",
            "blind_to_worker_rationale": True,
            "grade_artifacts_only": True
        }
    },
    "experiment_policy": {
        "enabled": False,
        "min_structural_ratio": 0.45,
        "max_scalar_chain_length": 3,
        "require_invalidation_branch": False,
        "require_baseline_comparison": False
    },
    "provider_policy": {
        "record_requested_actual_model": True,
        "record_cost_estimate": True,
        "warn_on_fallback": True
    },
    "beam_node": None,
    "agents": {
        "explorer": {"enabled": True},
        "implementer": {"enabled": True},
        "verifier": {"enabled": False},
    },
    "outputs": {
        "write_report": ".sisyfus/runs/{run_id}/report.md",
        "write_distill": ".sisyfus/runs/{run_id}/distill.json",
    },
}


def deep_merge(default: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(default)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def validate_goal(goal: dict[str, Any]) -> None:
    if not goal.get("objective"):
        raise ValueError("GoalSpec requires non-empty objective")
    if goal.get("session_policy", {}).get("one_task_per_session", True):
        for multi_key in ["objectives", "goals", "tasks"]:
            value = goal.get(multi_key)
            if isinstance(value, list) and len(value) > 1:
                raise ValueError(
                    f"GoalSpec has multiple {multi_key}; one_task_per_session requires one concrete task per run. "
                    "Split this into separate GoalSpecs."
                )


def load_goal(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"GoalSpec not found: {p}")
    suffix = p.suffix.lower()
    if suffix == ".json":
        raw = read_json(p)
    elif suffix == ".toml":
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"Unsupported GoalSpec format: {p.suffix}. v0.6 supports .json and .toml")
    if not isinstance(raw, dict):
        raise ValueError("GoalSpec root must be an object/table")
    goal = deep_merge(DEFAULT_GOAL, raw)
    goal["id"] = slugify(str(goal.get("id") or p.stem), default=p.stem)
    goal["task_type"] = normalize_task_type(
        str(goal.get("task_type") or goal.get("model_policy", {}).get("task_type") or "implementation")
    )
    validate_goal(goal)
    return goal


def create_goal_template(
    *,
    goal_id: str,
    objective: str,
    commands: list[str] | None = None,
    max_rounds: int = 3,
    task_type: str = "implementation",
) -> dict[str, Any]:
    goal = copy.deepcopy(DEFAULT_GOAL)
    goal["id"] = slugify(goal_id)
    goal["objective"] = objective
    goal["task_type"] = normalize_task_type(task_type)
    goal["done_when"]["commands"] = commands or []
    goal["loop"]["max_rounds"] = max_rounds
    if goal["task_type"] in {"monitoring", "agentops", "backtest_monitor"}:
        goal["agents"] = {
            "explorer": {"enabled": False},
            "implementer": {"enabled": False},
            "verifier": {"enabled": False},
        }
    return goal


def write_goal_template(
    path: Path,
    *,
    goal_id: str,
    objective: str,
    commands: list[str] | None = None,
    max_rounds: int = 3,
    task_type: str = "implementation",
) -> dict[str, Any]:
    goal = create_goal_template(goal_id=goal_id, objective=objective, commands=commands, max_rounds=max_rounds, task_type=task_type)
    write_json(path, goal)
    return goal
