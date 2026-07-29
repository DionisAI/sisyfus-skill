from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import ensure_layout, find_project_root
from .utils import read_json, truncate_middle, write_json


BUILTIN_RUBRICS: dict[str, dict[str, Any]] = {
    "coding_goal_v1": {
        "id": "coding_goal_v1",
        "title": "Coding goal outcome rubric",
        "pass_threshold": 0.85,
        "criteria": [
            {"id": "deterministic_verification", "weight": 0.50, "description": "Declared commands/monitors pass."},
            {"id": "focused_diff", "weight": 0.15, "description": "Diff is focused and avoids unrelated edits."},
            {"id": "constraints_respected", "weight": 0.20, "description": "Forbidden paths and other constraints are respected."},
            {"id": "session_artifacts", "weight": 0.15, "description": "Run artifacts are present for audit and future compaction."},
        ],
    },
    "research_outcome_v1": {
        "id": "research_outcome_v1",
        "title": "General automatic research outcome rubric",
        "pass_threshold": 0.80,
        "criteria": [
            {"id": "hypothesis_clarity", "weight": 0.16, "description": "The research hypothesis is explicit and falsifiable."},
            {"id": "evidence_artifact", "weight": 0.18, "description": "Evidence artifacts exist; the result is not only narrative."},
            {"id": "baseline_comparison", "weight": 0.14, "description": "A baseline or control comparison is recorded."},
            {"id": "invalidation_attempt", "weight": 0.16, "description": "The session tried to falsify the conclusion."},
            {"id": "next_action_quality", "weight": 0.12, "description": "Follow-up directions are concrete and bounded."},
            {"id": "memory_quality", "weight": 0.12, "description": "Durable learnings are compact and evidence-linked."},
            {"id": "cost_awareness", "weight": 0.12, "description": "The work used programmatic checks where possible and avoided wasteful model calls."},
        ],
    },
    "crypto_factor_research_v1": {
        "id": "crypto_factor_research_v1",
        "title": "Crypto cross-sectional factor research rubric",
        "pass_threshold": 0.82,
        "criteria": [
            {"id": "falsifiable_hypothesis", "weight": 0.08, "description": "Factor idea is explicit and falsifiable."},
            {"id": "exact_factor_definition", "weight": 0.12, "description": "Formula/config/spec defines exact ranking signal."},
            {"id": "data_availability", "weight": 0.10, "description": "Data fields, timestamps, lags, and universe are specified."},
            {"id": "lag_and_execution_safety", "weight": 0.18, "description": "No same-bar execution leakage or lookahead."},
            {"id": "baseline_comparison", "weight": 0.08, "description": "Compared to a relevant baseline."},
            {"id": "oos_validation", "weight": 0.12, "description": "Uses OOS or walk-forward validation."},
            {"id": "fee_and_slippage_stress", "weight": 0.10, "description": "Transaction-cost stress is present."},
            {"id": "turnover_and_capacity", "weight": 0.08, "description": "Turnover/capacity are measured or bounded."},
            {"id": "parameter_stability", "weight": 0.08, "description": "Shows parameter plateau / robustness, not a single lucky point."},
            {"id": "invalidation_attempt", "weight": 0.06, "description": "Actively tries to disprove the factor."},
        ],
    },
    "alpha_formula_generation_v1": {
        "id": "alpha_formula_generation_v1",
        "title": "Alpha formula generation rubric",
        "pass_threshold": 0.82,
        "criteria": [
            {"id": "exact_factor_definition", "weight": 0.22, "description": "Formula is syntactically exact in a declared grammar."},
            {"id": "data_availability", "weight": 0.14, "description": "Inputs exist in the target data store."},
            {"id": "lag_and_execution_safety", "weight": 0.22, "description": "Formula is lag-safe."},
            {"id": "implementation_artifact", "weight": 0.16, "description": "Compiler/config/test artifact exists."},
            {"id": "invalidation_attempt", "weight": 0.12, "description": "Includes anti-lookahead and sanity tests."},
            {"id": "next_action_quality", "weight": 0.14, "description": "Next evaluation step is deterministic and bounded."},
        ],
    },
    "memory_quality_v1": {
        "id": "memory_quality_v1",
        "title": "Memory lifecycle quality rubric",
        "pass_threshold": 0.80,
        "criteria": [
            {"id": "failure_documented", "weight": 0.10, "description": "A failure or uncertainty is documented."},
            {"id": "root_cause_investigated", "weight": 0.20, "description": "Root cause was investigated rather than only noted."},
            {"id": "verification_artifact_exists", "weight": 0.25, "description": "A command, test, monitor, or other verifier artifact exists."},
            {"id": "generalized_rule_created", "weight": 0.25, "description": "The learning was compacted into a reusable rule."},
            {"id": "future_consult_instruction_added", "weight": 0.20, "description": "Future sessions know when to consult this rule."},
        ],
    },
    "parameter_golf_v1": {
        "id": "parameter_golf_v1",
        "title": "Experiment golf / hillclimb rubric",
        "pass_threshold": 0.80,
        "criteria": [
            {"id": "baseline_comparison", "weight": 0.15, "description": "Baseline is run and recorded."},
            {"id": "experiment_ledger", "weight": 0.25, "description": "Experiments are recorded with kept/discarded/crashed status."},
            {"id": "structural_exploration", "weight": 0.20, "description": "Includes structural experiments, not only scalar tweaking."},
            {"id": "score_improvement", "weight": 0.15, "description": "Best score improves or failures are useful."},
            {"id": "invalidation_attempt", "weight": 0.15, "description": "Regression, crash, and sanity checks are recorded."},
            {"id": "bounded_budget", "weight": 0.10, "description": "Iteration/time/cost bounds are obeyed."},
        ],
    },
}


def rubric_dir(root: str | Path | None = None) -> Path:
    return ensure_layout(find_project_root(root)) / "rubrics"


def write_builtin_rubrics(root: str | Path | None = None, *, force: bool = False) -> list[Path]:
    out: list[Path] = []
    rd = rubric_dir(root)
    for rid, rubric in BUILTIN_RUBRICS.items():
        path = rd / f"{rid}.json"
        if force or not path.exists():
            write_json(path, rubric)
        out.append(path)
    return out


def list_rubrics(root: str | Path | None = None) -> list[dict[str, Any]]:
    root_path = find_project_root(root)
    write_builtin_rubrics(root_path)
    items: dict[str, dict[str, Any]] = {rid: {"source": "builtin", **rubric} for rid, rubric in BUILTIN_RUBRICS.items()}
    for path in sorted((ensure_layout(root_path) / "rubrics").glob("*.json")):
        try:
            raw = read_json(path)
            if isinstance(raw, dict) and raw.get("id"):
                items[str(raw["id"])] = {"source": str(path), **raw}
        except Exception:
            continue
    return list(items.values())


def load_rubric(root: str | Path | None, rubric_id_or_path: str | None) -> dict[str, Any]:
    rid = rubric_id_or_path or "coding_goal_v1"
    p = Path(rid)
    if p.exists():
        raw = read_json(p)
        if not isinstance(raw, dict):
            raise ValueError(f"Rubric file must contain JSON object: {p}")
        return raw
    root_path = find_project_root(root)
    write_builtin_rubrics(root_path)
    candidate = ensure_layout(root_path) / "rubrics" / f"{rid}.json"
    if candidate.exists():
        raw = read_json(candidate)
        if isinstance(raw, dict):
            return raw
    if rid in BUILTIN_RUBRICS:
        return BUILTIN_RUBRICS[rid]
    raise ValueError(f"Unknown rubric {rid!r}. Run `sisyfus rubric list`.")


def normalize_rubric(rubric: dict[str, Any]) -> dict[str, Any]:
    criteria = []
    total = 0.0
    for idx, c in enumerate(rubric.get("criteria", []) or [], start=1):
        if not isinstance(c, dict):
            continue
        w = float(c.get("weight", 0) or 0)
        total += w
        criteria.append({"id": str(c.get("id") or f"criterion_{idx}"), "weight": w, "description": str(c.get("description") or "")})
    if not criteria:
        criteria = [{"id": "deterministic_verification", "weight": 1.0, "description": "Verifier passes."}]
        total = 1.0
    if total <= 0:
        total = float(len(criteria))
        for c in criteria:
            c["weight"] = 1.0 / len(criteria)
    else:
        for c in criteria:
            c["weight"] = c["weight"] / total
    out = dict(rubric)
    out["criteria"] = criteria
    out["pass_threshold"] = float(out.get("pass_threshold", 0.8) or 0.8)
    out["id"] = str(out.get("id") or "unnamed_rubric")
    return out


def _artifact_text(run_dir: Path, max_chars: int = 100000) -> str:
    parts: list[str] = []
    for name in ["report.md", "final.json", "distill.json", "experiment.json", "beam_result.json", "score.json"]:
        p = run_dir / name
        if p.exists() and p.is_file():
            try:
                parts.append(f"\n--- {name} ---\n" + p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                pass
    for p in sorted(run_dir.glob("**/*.md"))[:25]:
        if p.name in {"report.md"}:
            continue
        try:
            parts.append(f"\n--- {p.relative_to(run_dir)} ---\n" + p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
    for p in sorted(run_dir.glob("**/*.json"))[:50]:
        if p.name in {"final.json", "distill.json"}:
            continue
        try:
            parts.append(f"\n--- {p.relative_to(run_dir)} ---\n" + p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
    return truncate_middle("\n".join(parts), max_chars).lower()


def _criterion_score(cid: str, *, final: dict[str, Any], verifier: dict[str, Any] | None, distill: dict[str, Any] | None, run_dir: Path, text: str) -> tuple[float, str, dict[str, Any]]:
    status = str(final.get("status") or (verifier or {}).get("status") or "UNKNOWN")
    commands = (verifier or {}).get("commands", []) if verifier else []
    monitors = (verifier or {}).get("monitors", []) if verifier else []
    changed_files = (verifier or {}).get("changed_files", []) if verifier else []
    failed_count = int((verifier or {}).get("failed_command_count", 0) or 0) + int((verifier or {}).get("failed_monitor_count", 0) or 0)
    violations = (verifier or {}).get("violations", []) if verifier else []
    facts = (distill or {}).get("facts", []) if distill else []
    failures = (distill or {}).get("failures", []) if distill else []
    hypotheses = (distill or {}).get("hypotheses", []) if distill else []
    tasks = (distill or {}).get("tasks", []) if distill else []
    artifacts_present = any((run_dir / name).exists() for name in ["report.md", "final.json", "distill.json", "experiment.json", "beam_result.json", "score.json"]) or bool(list(run_dir.glob("verifier-round-*.json"))) or bool(list(run_dir.glob("round-*/*/prompt.md")))

    # Deterministic artifact-based grading. This is intentionally conservative;
    # an external grader sub-agent can write outcome.grader.json to override later.
    if cid in {"deterministic_verification", "command_verification"}:
        if not commands and not monitors:
            return 0.50, "No deterministic command/monitor declared; verifier cannot prove completion.", {}
        return (1.0 if status == "PASSED" and failed_count == 0 else 0.0, f"verifier status={status}, failures={failed_count}", {})
    if cid in {"focused_diff"}:
        n = len(changed_files)
        return (1.0 if n <= 8 else 0.5 if n <= 20 else 0.0, f"changed_files={n}", {"changed_files": changed_files[:20]})
    if cid in {"constraints_respected", "bounded_budget"}:
        return (1.0 if not violations else 0.0, f"violations={len(violations)}", {"violations": violations})
    if cid in {"session_artifacts", "evidence_artifact", "implementation_artifact", "verification_artifact_exists", "experiment_ledger"}:
        exp_exists = (run_dir / "experiment.json").exists() or (run_dir / "score.json").exists()
        if cid == "experiment_ledger":
            return (1.0 if exp_exists else 0.35 if artifacts_present else 0.0, "experiment.json/score.json present" if exp_exists else "no explicit experiment card", {})
        return (1.0 if artifacts_present else 0.0, "run audit artifacts present" if artifacts_present else "missing run artifacts", {})
    if cid in {"hypothesis_clarity", "falsifiable_hypothesis"}:
        hit = any(k in text for k in ["hypothesis", "falsifiable", "factor", "claim", "assumption"])
        return (0.85 if hit else 0.45 if hypotheses else 0.2, "hypothesis language/artifacts found" if hit else "hypothesis not explicit", {})
    if cid in {"exact_factor_definition"}:
        hit = any(k in text for k in ["formula", "expr", "factor_id", "factorspec", "rank(", "ts_rank", "zscore", "config"])
        return (0.9 if hit else 0.25, "factor formula/spec found" if hit else "no exact factor definition artifact", {})
    if cid in {"data_availability"}:
        hit = any(k in text for k in ["fields", "universe", "timestamp", "data_requirements", "ohlcv", "volume", "close"])
        return (0.85 if hit else 0.35, "data requirements appear specified" if hit else "data lineage weak", {})
    if cid in {"lag_and_execution_safety", "no_lookahead"}:
        bad = any(k in text for k in ["lookahead violation", "same-bar", "same bar", "future information"])
        good = any(k in text for k in ["lag", "shift", "t+1", "no lookahead", "lookahead-safe", "purged", "embargo"])
        return (0.0 if bad and not good else 0.9 if good else 0.35, "lag/lookahead checks found" if good else "lag safety not proven", {})
    if cid in {"baseline_comparison"}:
        hit = any(k in text for k in ["baseline", "buy & hold", "control", "comparison"])
        return (0.85 if hit else 0.3, "baseline comparison found" if hit else "no baseline comparison", {})
    if cid in {"oos_validation", "parameter_stability"}:
        words = ["oos", "out-of-sample", "walk-forward", "walk forward", "plateau", "stability", "robustness"]
        hit = any(k in text for k in words)
        return (0.85 if hit else 0.25, "robustness/OOS language found" if hit else "no OOS/plateau evidence", {})
    if cid in {"fee_and_slippage_stress", "turnover_and_capacity"}:
        words = ["fee", "slippage", "turnover", "capacity", "cost stress"]
        hit = any(k in text for k in words)
        return (0.85 if hit else 0.25, "cost/turnover evidence found" if hit else "no cost/turnover evidence", {})
    if cid in {"invalidation_attempt", "root_cause_investigated"}:
        hit = bool(failures) or any(k in text for k in ["invalidate", "falsify", "disprove", "failure", "root cause", "sanity", "crash", "rejected"])
        return (0.85 if hit else 0.25, "failure/invalidation evidence found" if hit else "no invalidation attempt", {})
    if cid in {"next_action_quality", "future_consult_instruction_added"}:
        hit = bool(tasks) or any(k in text for k in ["next", "follow-up", "follow up", "todo", "future session", "consult"])
        return (0.8 if hit else 0.35, "bounded next action found" if hit else "no concrete next action", {})
    if cid in {"memory_quality", "failure_documented", "generalized_rule_created"}:
        if facts or failures or hypotheses:
            return (0.75 if cid == "memory_quality" else 0.85, "distill contains memory candidates", {})
        return (0.25, "no memory candidates", {})
    if cid in {"cost_awareness"}:
        model_routes = final.get("model_routes") or {}
        disallowed = [r for r in model_routes.values() if r.get("allow_agent") is False]
        return (0.8 if disallowed or "deterministic" in text or "monitor" in text else 0.45, "cost-aware route/monitor evidence" if disallowed else "cost awareness weak", {})
    if cid in {"score_improvement", "structural_exploration"}:
        hit = any(k in text for k in ["score", "improved", "kept", "structural", "architecture", "new factor", "discarded", "crashed"])
        return (0.75 if hit else 0.35, "experiment-golf evidence found" if hit else "no score/structural evidence", {})
    # Unknown criteria get neutral score instead of false pass.
    return 0.5, f"No deterministic grader rule for criterion {cid}; neutral score assigned.", {}


def grade_rubric(
    *,
    root: str | Path | None,
    rubric: dict[str, Any],
    run_dir: str | Path,
    final: dict[str, Any] | None = None,
    verifier: dict[str, Any] | None = None,
    distill: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_path = Path(run_dir).resolve()
    rubric = normalize_rubric(rubric)
    if final is None and (run_path / "final.json").exists():
        final = read_json(run_path / "final.json")
    final = final or {}
    if verifier is None:
        reports = sorted(run_path.glob("verifier-round-*.json")) + sorted(run_path.glob("verifier.json"))
        verifier = read_json(reports[-1]) if reports else None
    if distill is None and (run_path / "distill.json").exists():
        try:
            distill = read_json(run_path / "distill.json")
        except Exception:
            distill = None
    text = _artifact_text(run_path)

    criterion_results = []
    weighted = 0.0
    for c in rubric["criteria"]:
        score, comment, evidence = _criterion_score(c["id"], final=final, verifier=verifier, distill=distill, run_dir=run_path, text=text)
        score = max(0.0, min(1.0, float(score)))
        weighted += score * float(c["weight"])
        criterion_results.append({**c, "score": score, "comment": comment, "evidence": evidence})
    status = "PASSED" if weighted >= float(rubric.get("pass_threshold", 0.8)) else "NOT_MET"
    result = {
        "schema_version": "sisyfus.rubric_grade.v0.6",
        "rubric_id": rubric["id"],
        "rubric_title": rubric.get("title"),
        "score": round(weighted, 4),
        "pass_threshold": rubric.get("pass_threshold"),
        "status": status,
        "criteria": criterion_results,
        "grader": "deterministic_artifact_grader",
        "grader_blind_to_worker_rationale": True,
        "grade_artifacts_only": True,
        "run_dir": str(run_path),
    }
    write_json(run_path / "rubric.grade.json", result)
    return result
