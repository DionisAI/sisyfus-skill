from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import ensure_layout, find_project_root
from .utils import append_jsonl, read_json, read_jsonl, sha256_text, slugify, utc_now, write_json


EXPERIMENTAL_TASK_TYPES = {
    "beam_research",
    "beam_search",
    "factor_research",
    "alpha_mining",
    "formula_alpha_mining",
    "cross_sectional_research",
    "research_design",
    "exploratory",
}


def experiment_dir(root: str | Path | None = None) -> Path:
    return ensure_layout(find_project_root(root)) / "experiments"


def ledger_path(root: str | Path | None = None) -> Path:
    return experiment_dir(root) / "ledger.jsonl"


def _load_optional(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            raw = read_json(path)
            if isinstance(raw, dict):
                return raw
    except Exception:
        return {}
    return {}


def _latest_verifier(run_dir: Path) -> dict[str, Any] | None:
    reports = sorted(run_dir.glob("verifier-round-*.json")) + sorted(run_dir.glob("verifier.json"))
    if not reports:
        return None
    try:
        raw = read_json(reports[-1])
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def should_record_experiment(goal: dict[str, Any], final: dict[str, Any], run_dir: str | Path) -> bool:
    if (goal.get("experiment_policy") or {}).get("enabled") is True:
        return True
    if (goal.get("outcome") or {}).get("enabled") is True:
        return True
    if str(goal.get("task_type") or final.get("task_type") or "") in EXPERIMENTAL_TASK_TYPES:
        return True
    run_path = Path(run_dir)
    return any((run_path / name).exists() for name in ["experiment.json", "score.json", "beam_result.json"])


def record_experiment_from_run(root: str | Path | None, *, run_dir: str | Path, goal: dict[str, Any], final: dict[str, Any], outcome: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not should_record_experiment(goal, final, run_dir):
        return None
    root_path = find_project_root(root)
    exp_dir = experiment_dir(root_path)
    run_path = Path(run_dir).resolve()
    explicit = _load_optional(run_path / "experiment.json")
    score_json = _load_optional(run_path / "score.json")
    beam_result = _load_optional(run_path / "beam_result.json")
    verifier = _latest_verifier(run_path) or {}
    exp_id = explicit.get("experiment_id") or explicit.get("id") or f"exp_{sha256_text(str(run_path))[-12:]}"
    status = explicit.get("status")
    if not status:
        if final.get("status") == "PASSED":
            status = "kept"
        elif final.get("status") in {"FAILED", "NEEDS_HUMAN"}:
            status = "discarded"
        else:
            status = "uncertain"
    experiment_type = explicit.get("type") or ("structural" if str(goal.get("task_type")) in {"factor_research", "formula_alpha_mining", "beam_research", "exploratory"} else "scalar")
    metrics = {}
    for src in [score_json.get("metrics") if isinstance(score_json, dict) else None, beam_result.get("metrics") if isinstance(beam_result, dict) else None, explicit.get("metrics") if isinstance(explicit, dict) else None]:
        if isinstance(src, dict):
            metrics.update(src)
    if score_json.get("score") is not None:
        metrics.setdefault("score", score_json.get("score"))
    if outcome:
        metrics.setdefault("rubric_score", outcome.get("score"))
    item = {
        "schema_version": "sisyfus.experiment.v0.6",
        "experiment_id": str(exp_id),
        "created_at": utc_now(),
        "goal_id": final.get("goal_id") or goal.get("id"),
        "run_id": final.get("run_id") or run_path.name,
        "run_dir": str(run_path),
        "beam_id": (final.get("beam_node") or final.get("beam") or {}).get("beam_id") if isinstance(final.get("beam_node") or final.get("beam"), dict) else None,
        "beam_node_id": (final.get("beam_node") or final.get("beam") or {}).get("node_id") if isinstance(final.get("beam_node") or final.get("beam"), dict) else None,
        "parent_experiment_id": explicit.get("parent_experiment_id"),
        "type": experiment_type,
        "status": status,
        "hypothesis": explicit.get("hypothesis") or beam_result.get("summary") or goal.get("objective"),
        "change_summary": explicit.get("change_summary") or final.get("reason"),
        "artifact": explicit.get("artifact") or {"run_dir": str(run_path)},
        "metrics": metrics,
        "verifier": {
            "status": verifier.get("status"),
            "failed_command_count": verifier.get("failed_command_count"),
            "failed_monitor_count": verifier.get("failed_monitor_count"),
        },
        "grader": {
            "rubric_id": (outcome or {}).get("rubric_id"),
            "rubric_score": (outcome or {}).get("score"),
            "verdict": (outcome or {}).get("status"),
            "main_objection": ((outcome or {}).get("feedback") or "").splitlines()[1:2][0] if len(((outcome or {}).get("feedback") or "").splitlines()) > 1 else None,
        },
        "cost": explicit.get("cost") or {},
        "explicit_experiment": explicit,
    }
    exp_path = exp_dir / f"{slugify(str(exp_id))}.json"
    write_json(exp_path, item)
    append_jsonl(ledger_path(root_path), item)
    write_json(run_path / "experiment.record.json", item)
    return item


def list_experiments(root: str | Path | None = None, *, limit: int = 200, status: str | None = None, beam_id: str | None = None) -> list[dict[str, Any]]:
    items = read_jsonl(ledger_path(root))
    if status:
        items = [x for x in items if str(x.get("status")) == status]
    if beam_id:
        items = [x for x in items if str(x.get("beam_id")) == beam_id]
    items = list(reversed(items))
    return items[:limit]


def load_experiment(root: str | Path | None, experiment_id: str) -> dict[str, Any]:
    path = experiment_dir(root) / f"{slugify(experiment_id)}.json"
    if path.exists():
        return read_json(path)
    for item in read_jsonl(ledger_path(root)):
        if item.get("experiment_id") == experiment_id:
            return item
    raise FileNotFoundError(f"Experiment not found: {experiment_id}")


def experiment_summary(root: str | Path | None = None) -> dict[str, Any]:
    items = read_jsonl(ledger_path(root))
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    best = None
    for item in items:
        by_status[str(item.get("status") or "unknown")] = by_status.get(str(item.get("status") or "unknown"), 0) + 1
        by_type[str(item.get("type") or "unknown")] = by_type.get(str(item.get("type") or "unknown"), 0) + 1
        score = item.get("metrics", {}).get("score", item.get("metrics", {}).get("rubric_score"))
        try:
            val = float(score)
        except Exception:
            continue
        if best is None or val > best[0]:
            best = (val, item)
    return {
        "schema_version": "sisyfus.experiment_summary.v0.6",
        "count": len(items),
        "by_status": by_status,
        "by_type": by_type,
        "structural_ratio": (by_type.get("structural", 0) / len(items)) if items else 0.0,
        "best_experiment": best[1] if best else None,
    }


def experiment_chart_data(root: str | Path | None = None, *, limit: int = 500) -> dict[str, Any]:
    items = list(reversed(read_jsonl(ledger_path(root))))[-limit:]
    points = []
    best = None
    for idx, item in enumerate(items):
        score = item.get("metrics", {}).get("score", item.get("metrics", {}).get("rubric_score"))
        try:
            y = float(score)
        except Exception:
            y = None
        if y is not None:
            best = y if best is None else max(best, y)
        points.append({
            "x": idx,
            "experiment_id": item.get("experiment_id"),
            "score": y,
            "best_so_far": best,
            "status": item.get("status"),
            "type": item.get("type"),
            "goal_id": item.get("goal_id"),
            "run_id": item.get("run_id"),
            "hypothesis": item.get("hypothesis"),
        })
    return {"schema_version": "sisyfus.experiment_chart.v0.6", "points": points, "summary": experiment_summary(root)}
