from __future__ import annotations

from pathlib import Path
from typing import Any

from .paths import ensure_layout, find_project_root
from .rubric import grade_rubric, load_rubric
from .utils import read_json, read_jsonl, utc_now, write_json


def outcome_enabled(goal: dict[str, Any]) -> bool:
    return bool((goal.get("outcome") or {}).get("enabled", False))


def outcome_spec(goal: dict[str, Any], root: str | Path | None = None) -> dict[str, Any]:
    spec = dict(goal.get("outcome") or {})
    if not spec.get("enabled"):
        spec["enabled"] = False
    spec.setdefault("mode", "rubric")
    spec.setdefault("max_iterations", int(goal.get("loop", {}).get("max_rounds", 3) or 3))
    spec.setdefault("pass_threshold", None)
    task_type = str(goal.get("task_type") or "implementation")
    if not spec.get("rubric_id"):
        if task_type in {"factor_research", "cross_sectional_research"}:
            spec["rubric_id"] = "crypto_factor_research_v1"
        elif task_type in {"formula_alpha_mining", "alpha_mining"}:
            spec["rubric_id"] = "alpha_formula_generation_v1"
        elif task_type in {"beam_research", "beam_search", "exploratory", "research_design"}:
            spec["rubric_id"] = "research_outcome_v1"
        else:
            spec["rubric_id"] = "coding_goal_v1"
    spec.setdefault("allow_pass_without_deterministic_verifier", task_type in {"information_collection", "literature", "summarization", "factor_research", "formula_alpha_mining", "beam_research"})
    spec.setdefault("grader", {"role": "independent_grader", "blind_to_worker_rationale": True, "grade_artifacts_only": True})
    return spec


def grade_outcome(
    *,
    root: str | Path | None,
    goal: dict[str, Any],
    run_dir: str | Path,
    round_index: int | None = None,
    verifier: dict[str, Any] | None = None,
    final: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = find_project_root(root)
    run_path = Path(run_dir).resolve()
    spec = outcome_spec(goal, root_path)
    rubric = load_rubric(root_path, str(spec.get("rubric_id")))
    if spec.get("pass_threshold") is not None:
        rubric = dict(rubric)
        rubric["pass_threshold"] = float(spec["pass_threshold"])
    if final is None and (run_path / "final.json").exists():
        final = read_json(run_path / "final.json")
    final = final or {"goal_id": goal.get("id"), "status": (verifier or {}).get("status", "UNKNOWN")}
    grade = grade_rubric(root=root_path, rubric=rubric, run_dir=run_path, final=final, verifier=verifier)
    result = {
        "schema_version": "sisyfus.outcome_grade.v0.6",
        "created_at": utc_now(),
        "goal_id": goal.get("id"),
        "round": round_index,
        "status": "PASSED" if grade["status"] == "PASSED" else "NOT_MET",
        "score": grade["score"],
        "pass_threshold": grade["pass_threshold"],
        "rubric_id": grade["rubric_id"],
        "rubric_grade": grade,
        "grader": spec.get("grader", {}),
        "feedback": outcome_feedback(grade),
    }
    name = f"outcome-round-{round_index:02d}.json" if round_index is not None else "outcome.json"
    write_json(run_path / name, result)
    write_outcome_markdown(run_path / name.replace(".json", ".md"), result)
    # Maintain a latest symlink-like copy for API/consumer simplicity.
    write_json(run_path / "outcome.latest.json", result)
    return result


def outcome_feedback(grade: dict[str, Any], *, limit: int = 5) -> str:
    criteria = sorted(grade.get("criteria", []), key=lambda c: float(c.get("score", 0)))
    lines = [f"Rubric {grade.get('rubric_id')} score {grade.get('score')} / threshold {grade.get('pass_threshold')} -> {grade.get('status')}"]
    for c in criteria[:limit]:
        lines.append(f"- {c.get('id')}: {c.get('score')} — {c.get('comment')}")
    return "\n".join(lines)


def write_outcome_markdown(path: Path, result: dict[str, Any]) -> None:
    lines = ["# Outcome Grade", "", f"Status: **{result['status']}**", f"Score: `{result['score']}` / threshold `{result['pass_threshold']}`", f"Rubric: `{result['rubric_id']}`", "", "## Criteria"]
    for c in result.get("rubric_grade", {}).get("criteria", []):
        lines.append(f"- `{c.get('id')}` weight `{round(float(c.get('weight', 0)), 3)}` score `{c.get('score')}` — {c.get('comment')}")
    lines.append("\n## Feedback\n")
    lines.append(result.get("feedback", ""))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def list_outcomes(root: str | Path | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
    root_path = find_project_root(root)
    ensure_layout(root_path)
    items: list[dict[str, Any]] = []
    for p in sorted((root_path / ".sisyfus" / "runs").glob("*/outcome.latest.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            item = read_json(p)
            if isinstance(item, dict):
                item["run_id"] = p.parent.name
                item["run_dir"] = str(p.parent)
                items.append(item)
        except Exception:
            continue
        if len(items) >= limit:
            break
    return items


def load_outcome(root: str | Path | None, run_id: str) -> dict[str, Any]:
    root_path = find_project_root(root)
    p = root_path / ".sisyfus" / "runs" / run_id / "outcome.latest.json"
    if not p.exists():
        raise FileNotFoundError(f"No outcome found for run_id {run_id}")
    return read_json(p)
