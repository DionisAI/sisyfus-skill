"""Operator-owned role/acceptance boundaries for continuous Tech Lead missions.

Models may revise task decomposition, never executable checks, role authority or
aggregate budgets. A null aggregate limit is genuinely unlimited, not a sentinel.
"""
from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .mission import load_spec as load_native_spec
from .protocol import bounded, digest

SCHEMA = "sisyfus.techlead.v1"
ROLE_DEFAULTS = {
    "lead": {"driver": "claude", "model": "claude-opus-5-5"},
    "worker": {"driver": "codex", "model": "gpt-6.1-sol"},
    "reviewer": {"driver": "claude", "model": "claude-opus-5-5"},
}
DEFAULT_PROCEDURE = (
    "Understand architecture and interfaces before decomposition. Specify each "
    "task's deliverable, write ownership, dependencies and frozen acceptance. "
    "Delegate implementation to workers; inspect independent evidence. Diagnose "
    "the failed layer, propose a concrete repair, and preserve successful work. "
    "Never weaken acceptance or infer success from agent prose."
)

def optional_limit(value: Any, name: str, *, integer: bool = False) -> Any:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be positive or null (unlimited)")
    if not math.isfinite(value) or value <= 0 or (integer and type(value) is not int):
        raise ValueError(f"{name} must be a finite positive {'integer' if integer else 'number'} or null")
    return value

def write_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise ValueError("write paths must be nonempty portable relative paths")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"..", ".git", ".sisyfus", "inputs"} for part in path.parts):
        raise ValueError("write path escapes the candidate or targets control state")
    if str(path) == "." or "*" in value or "?" in value:
        raise ValueError("declare concrete files/directories, not wildcard project ownership")
    return str(path)

def paths_overlap(left: str, right: str) -> bool:
    a, b = PurePosixPath(left), PurePosixPath(right)
    return a == b or a in b.parents or b in a.parents

def load_lead_spec(value: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    raw = json.loads(Path(value).read_text()) if isinstance(value, (str, Path)) else copy.deepcopy(dict(value))
    if not isinstance(raw, dict):
        raise ValueError("Tech Lead mission specification must be an object")
    allowed = {"schema_version", "objective", "source", "drivers", "roles", "checks", "required_checks",
               "integration_checks", "parallelism", "timeout", "check_timeout", "max_turns", "max_calls",
               "max_iterations", "max_tokens", "max_cost_usd", "max_wall_minutes", "validation_kind",
               "procedure", "rsi", "tasks", "constraints", "deliverables"}
    if set(raw) - allowed:
        raise ValueError("unknown Tech Lead mission fields: " + ", ".join(sorted(set(raw) - allowed)))
    if raw.get("schema_version", SCHEMA) != SCHEMA:
        raise ValueError("unsupported Tech Lead mission schema")
    roles = copy.deepcopy(ROLE_DEFAULTS)
    if not isinstance(raw.get("roles", {}), dict):
        raise ValueError("roles must be a mapping")
    for name, config in raw.get("roles", {}).items():
        if name not in roles or not isinstance(config, dict) or set(config) - {"driver", "model"}:
            raise ValueError("unknown role or role configuration")
        roles[name].update(config)
    for name, config in roles.items():
        if config["driver"] != ROLE_DEFAULTS[name]["driver"] or not isinstance(config["model"], str) or not config["model"].strip():
            raise ValueError("Lead/reviewer require Claude and implementation requires Codex with explicit models")
    drivers = copy.deepcopy(raw.get("drivers", {}))
    if not isinstance(drivers, dict) or any(not isinstance(c, dict) for c in drivers.values()):
        raise ValueError("drivers must map native driver names to configurations")
    for name, model in (("claude", roles["lead"]["model"]), ("codex", roles["worker"]["model"])):
        drivers.setdefault(name, {"model": model, "command": [name]})
        drivers[name].setdefault("model", model)
    checks = copy.deepcopy(raw.get("checks", {}))
    if not isinstance(checks, dict) or not checks or any(not isinstance(c, dict) for c in checks.values()):
        raise ValueError("operator-owned deterministic acceptance checks are required")
    check_timeout = raw.get("check_timeout", 30)
    if isinstance(check_timeout, bool) or not isinstance(check_timeout, (int, float)) or not math.isfinite(check_timeout):
        raise ValueError("check_timeout must be a finite number")
    bounded(check_timeout, .05, 300, "check_timeout")
    for check in checks.values():
        check.setdefault("timeout", check_timeout)
    # Reuse the released native schema for executable/hash/timeout validation.
    # Its finite legacy budget is only a validation input; no sentinel persists.
    native = {"objective": raw.get("objective"), "source": raw.get("source"), "drivers": drivers,
              "checks": checks, "required_checks": raw.get("required_checks", sorted(checks)),
              "parallelism": raw.get("parallelism", 2), "timeout": raw.get("timeout", 900),
              "max_turns": 8, "max_calls": 8, "max_attempts": 1, "planner": "claude",
              "validation_kind": raw.get("validation_kind", "native_cli_unvalidated")}
    # Native load_spec takes a file; use the same validation without temporary
    # files by factoring its JSON loader through an in-memory mapping subclass.
    class JSONInput:
        def read_text(self): return json.dumps(native)
    normalized = load_native_spec(JSONInput())
    result = {**normalized, "schema_version": SCHEMA, "roles": roles,
              "procedure": raw.get("procedure", DEFAULT_PROCEDURE),
              "integration_checks": raw.get("integration_checks", normalized["required_checks"]),
              "constraints": raw.get("constraints", []), "deliverables": raw.get("deliverables", []),
              "rsi": raw.get("rsi", {"enabled": True, "auto_promote": True})}
    result.pop("planner", None)
    for name in ("max_calls", "max_iterations", "max_tokens", "max_cost_usd", "max_wall_minutes"):
        result[name] = optional_limit(raw.get(name), name, integer=name in {"max_calls", "max_iterations", "max_tokens"})
    turns = raw.get("max_turns")
    result["max_turns"] = optional_limit(turns, "max_turns", integer=True)
    if not isinstance(result["procedure"], str) or not 1 <= len(result["procedure"]) <= 20000:
        raise ValueError("Lead procedure must be 1..20000 characters")
    integration = result["integration_checks"]
    if not isinstance(integration, list) or not integration or any(not isinstance(c, str) for c in integration) or len(integration) != len(set(integration)) or set(integration) - set(checks):
        raise ValueError("integration_checks must select registered immutable checks")
    if not isinstance(result["constraints"], list) or not all(isinstance(x, str) for x in result["constraints"]):
        raise ValueError("constraints must be text entries")
    if not isinstance(result["deliverables"], list) or not all(isinstance(x, str) for x in result["deliverables"]):
        raise ValueError("deliverables must be text entries")
    if not isinstance(result["rsi"], dict) or set(result["rsi"]) - {"enabled", "auto_promote", "evaluation_root"}:
        raise ValueError("unsupported RSI configuration")
    for flag in ("enabled", "auto_promote"):
        if flag in result["rsi"] and type(result["rsi"][flag]) is not bool:
            raise ValueError("RSI flags must be booleans")
    if "tasks" in raw:
        result["initial_plan"] = validate_plan({"architecture": "operator supplied", "interfaces": [], "tasks": raw["tasks"]}, result)
    result["acceptance_hash"] = digest({"checks": result["checks"], "required": result["required_checks"],
                                        "integration": result["integration_checks"]})
    return result

def validate_plan(raw: Any, spec: Mapping[str, Any], *, existing: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) - {"architecture", "interfaces", "tasks", "rationale"}:
        raise ValueError("plan accepts only architecture, interfaces, tasks and rationale")
    if not isinstance(raw.get("architecture"), str) or not raw["architecture"].strip():
        raise ValueError("architecture description required")
    interfaces = raw.get("interfaces", [])
    if not isinstance(interfaces, list) or not all(isinstance(x, (str, dict)) for x in interfaces):
        raise ValueError("interfaces must be explicit text/object entries")
    entries = raw.get("tasks")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 32:
        raise ValueError("a plan revision needs 1..32 tasks")
    previous = list(existing or [])
    old_ids = {t["id"] for t in previous}
    stripped, scopes, annotations = [], {}, {}
    for task in entries:
        if not isinstance(task, dict) or set(task) - {"id", "objective", "depends_on", "check", "write_paths", "acceptance", "interface", "repair_of"}:
            raise ValueError("unknown task contract fields; models cannot choose executors or change checks")
        if not isinstance(task.get("id"), str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", task["id"]):
            raise ValueError("invalid task identity")
        if task.get("id") in old_ids:
            raise ValueError("plan revisions append new task identities; historical tasks are immutable")
        paths = task.get("write_paths")
        if not isinstance(paths, list) or not paths:
            raise ValueError("every implementation task needs concrete write ownership")
        paths = [write_path(p) for p in paths]
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate write paths")
        if not isinstance(task.get("acceptance"), str) or not task["acceptance"].strip():
            raise ValueError("every task needs explicit acceptance text")
        ident = task.get("id")
        scopes[ident] = paths
        annotations[ident] = {k: task[k] for k in ("acceptance", "interface", "repair_of") if k in task}
        stripped.append({"id": ident, "objective": task.get("objective"), "check": task.get("check"),
                         "depends_on": task.get("depends_on", []), "driver": "codex", "max_attempts": 1})
    # Validate each revision without imposing a lifetime task-count ceiling.
    # Graph size may grow over unlimited Lead iterations; each response is bounded.
    all_tasks = previous + stripped
    ids = [t.get("id") for t in all_tasks]
    if any(not isinstance(i, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", i) or i == "planner" for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("invalid or duplicate task identity")
    for task in all_tasks:
        if task.get("check") not in spec["checks"] or not isinstance(task.get("objective"), str) or not 1 <= len(task["objective"]) <= 20000:
            raise ValueError("task needs a registered check and a concrete objective")
        deps = task.get("depends_on", [])
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps) or len(deps) != len(set(deps)):
            raise ValueError("invalid dependencies")
    if set(spec["required_checks"]) - {t["check"] for t in all_tasks}:
        raise ValueError("plan omits a required acceptance check")
    graph = {t["id"]: t["depends_on"] for t in all_tasks}
    visiting, visited = set(), set()
    def visit(ident):
        if ident not in graph or ident in visiting:
            raise ValueError("unknown dependency or dependency cycle")
        if ident in visited: return
        visiting.add(ident)
        for dep in graph[ident]: visit(dep)
        visiting.remove(ident)
        visited.add(ident)
    for ident in graph: visit(ident)
    def depends(a, b):
        return b in graph[a] or any(depends(p, b) for p in graph[a])
    scope_map = {t["id"]: t.get("write_paths", []) for t in previous}
    scope_map.update(scopes)
    for index, left in enumerate(all_tasks):
        for right in all_tasks[index + 1:]:
            if annotations.get(right["id"], {}).get("repair_of") == left["id"] or annotations.get(left["id"], {}).get("repair_of") == right["id"]:
                continue
            if depends(left["id"], right["id"]) or depends(right["id"], left["id"]):
                continue
            if any(paths_overlap(a, b) for a in scope_map[left["id"]] for b in scope_map[right["id"]]):
                raise ValueError(f"parallel write conflict: {left['id']} and {right['id']}")
    normalized = [{**t, "write_paths": scopes[t["id"]], **annotations[t["id"]]}
                  for t in all_tasks if t["id"] not in old_ids]
    return {"architecture": raw["architecture"], "interfaces": interfaces,
            "tasks": normalized, "rationale": raw.get("rationale", "")}
