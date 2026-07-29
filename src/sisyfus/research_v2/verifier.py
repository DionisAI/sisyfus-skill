from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from .models import VERDICT_STATUSES

_MISSING = object()


def get_path(data: Any, path: str, default: Any = _MISSING) -> Any:
    if not path:
        return data
    current = data
    for token in str(path).split("."):
        if isinstance(current, dict):
            if token not in current:
                return default
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError):
                return default
        else:
            return default
    return current


def _compare(observed: Any, op: str, expected: Any, tolerance: float | None = None) -> bool:
    op = op.lower().strip()
    if op == "exists":
        return observed is not _MISSING
    if op == "not_exists":
        return observed is _MISSING
    if observed is _MISSING:
        return False
    if op in {"truthy", "is_true"}:
        return bool(observed)
    if op in {"falsy", "is_false"}:
        return not bool(observed)
    if op in {"==", "eq"}:
        return observed == expected
    if op in {"!=", "ne"}:
        return observed != expected
    if op in {">", "gt"}:
        return observed > expected
    if op in {">=", "gte"}:
        return observed >= expected
    if op in {"<", "lt"}:
        return observed < expected
    if op in {"<=", "lte"}:
        return observed <= expected
    if op == "in":
        return observed in expected
    if op == "not_in":
        return observed not in expected
    if op == "contains":
        return expected in observed
    if op == "not_contains":
        return expected not in observed
    if op == "regex":
        return re.search(str(expected), str(observed)) is not None
    if op in {"approx", "approximately"}:
        tol = float(tolerance if tolerance is not None else 1e-9)
        return math.isclose(float(observed), float(expected), rel_tol=tol, abs_tol=tol)
    raise ValueError(f"unsupported verifier operator: {op}")


def evaluate_check(data: dict[str, Any], check: dict[str, Any]) -> dict[str, Any]:
    path = str(check.get("path") or "")
    op = str(check.get("op") or "==")
    expected = check.get("value")
    observed = get_path(data, path)
    try:
        passed = _compare(observed, op, expected, check.get("tolerance"))
        error = None
    except (TypeError, ValueError) as exc:
        passed = False
        error = str(exc)
    return {
        "path": path,
        "op": op,
        "expected": expected,
        "observed": None if observed is _MISSING else observed,
        "missing": observed is _MISSING,
        "passed": bool(passed),
        "label": str(check.get("label") or path or op),
        "error": error,
    }


def evaluate_group(data: dict[str, Any], group: dict[str, list[dict[str, Any]]], *, empty_default: bool) -> dict[str, Any]:
    all_checks = [evaluate_check(data, check) for check in group.get("all", [])]
    any_checks = [evaluate_check(data, check) for check in group.get("any", [])]
    has_checks = bool(all_checks or any_checks)
    all_pass = all(x["passed"] for x in all_checks) if all_checks else True
    any_pass = any(x["passed"] for x in any_checks) if any_checks else True
    matched = (all_pass and any_pass) if has_checks else empty_default
    return {
        "matched": matched,
        "has_checks": has_checks,
        "all": all_checks,
        "any": any_checks,
    }


def _artifact_names(observation: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for artifact in observation.get("artifacts") or []:
        if isinstance(artifact, str):
            names.add(artifact)
            names.add(Path(artifact).name)
        elif isinstance(artifact, dict):
            for key in ("id", "path", "name", "filename"):
                value = artifact.get(key)
                if value:
                    names.add(str(value))
                    names.add(Path(str(value)).name)
    return names


def classify_observation(contract: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    execution = dict(observation.get("execution") or {})
    checks: dict[str, Any] = {}

    if contract.get("kind") == "manual":
        manual = str(observation.get("manual_verdict") or "").upper()
        if manual not in VERDICT_STATUSES:
            return {
                "status": "INCONCLUSIVE",
                "reason_code": "manual_verdict_missing",
                "summary": "Manual contract did not receive a valid manual_verdict.",
                "checks": checks,
            }
        return {
            "status": manual,
            "reason_code": str(observation.get("reason_code") or "manual_verdict"),
            "summary": str(observation.get("summary") or f"Manual verdict: {manual}"),
            "checks": checks,
        }

    if execution.get("timed_out") is True:
        return {
            "status": "ERROR",
            "reason_code": "execution_timeout",
            "summary": "Experiment execution timed out; no claim inference is allowed.",
            "checks": checks,
        }
    if execution.get("error"):
        return {
            "status": "ERROR",
            "reason_code": "execution_error",
            "summary": str(execution.get("error")),
            "checks": checks,
        }
    if execution.get("exit_code") not in (None, 0) and not bool((contract.get("metadata") or {}).get("nonzero_exit_is_valid")):
        return {
            "status": "ERROR",
            "reason_code": "command_nonzero_exit",
            "summary": f"Command exited with {execution.get('exit_code')}; treated as infrastructure/execution failure.",
            "checks": checks,
        }

    required_artifacts = list(contract.get("required_artifacts") or [])
    names = _artifact_names(observation)
    missing_artifacts = [required for required in required_artifacts if required not in names and Path(required).name not in names]
    checks["required_artifacts"] = {
        "required": required_artifacts,
        "observed": sorted(names),
        "missing": missing_artifacts,
        "matched": not missing_artifacts,
    }
    if missing_artifacts:
        return {
            "status": "INVALID",
            "reason_code": "required_artifact_missing",
            "summary": f"Required artifacts missing: {', '.join(missing_artifacts)}",
            "checks": checks,
        }

    preconditions = evaluate_group(observation, contract.get("preconditions") or {}, empty_default=True)
    checks["preconditions"] = preconditions
    if not preconditions["matched"]:
        return {
            "status": "INVALID",
            "reason_code": "precondition_failed",
            "summary": "The experiment did not satisfy the preregistered preconditions.",
            "checks": checks,
        }

    invalid = evaluate_group(observation, contract.get("invalid_if") or {}, empty_default=False)
    checks["invalid_if"] = invalid
    if invalid["matched"]:
        return {
            "status": "INVALID",
            "reason_code": "invalid_rule_matched",
            "summary": "The experiment matched a preregistered invalidity condition.",
            "checks": checks,
        }

    guardrails = evaluate_group(observation, contract.get("guardrails") or {}, empty_default=True)
    checks["guardrails"] = guardrails
    if not guardrails["matched"]:
        return {
            "status": "FAIL",
            "reason_code": "guardrail_failed",
            "summary": "The experiment was valid, but a hard guardrail failed.",
            "checks": checks,
        }

    passed = evaluate_group(observation, contract.get("pass_if") or {}, empty_default=False)
    failed = evaluate_group(observation, contract.get("fail_if") or {}, empty_default=False)
    checks["pass_if"] = passed
    checks["fail_if"] = failed

    if passed["matched"] and failed["matched"]:
        return {
            "status": "INVALID",
            "reason_code": "contradictory_contract",
            "summary": "Both PASS and FAIL rules matched; the verification contract is contradictory for this observation.",
            "checks": checks,
        }
    if passed["matched"]:
        return {
            "status": "PASS",
            "reason_code": "pass_rule_matched",
            "summary": "The observation satisfied the preregistered PASS rule and all guardrails.",
            "checks": checks,
        }
    if failed["matched"]:
        return {
            "status": "FAIL",
            "reason_code": "fail_rule_matched",
            "summary": "The observation satisfied the preregistered FAIL rule.",
            "checks": checks,
        }
    return {
        "status": "INCONCLUSIVE",
        "reason_code": "no_decisive_rule_matched",
        "summary": "The experiment was valid, but neither the PASS nor FAIL rule was decisive.",
        "checks": checks,
    }
