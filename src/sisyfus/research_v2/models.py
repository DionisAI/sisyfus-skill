from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

SCHEMA_VERSION = "sisyfus.research.v2"
TASK_SCHEMA_VERSION = "sisyfus.research_task.v2"
EVENT_SCHEMA_VERSION = "sisyfus.research_event.v2"
SNAPSHOT_SCHEMA_VERSION = "sisyfus.research_snapshot.v2"

CLAIM_STATUSES = {
    "OPEN",
    "SUPPORTED",
    "REFUTED",
    "INCONCLUSIVE",
    "INVALIDATED",
}
VERDICT_STATUSES = {"PASS", "FAIL", "INCONCLUSIVE", "INVALID", "ERROR"}
EXPERIMENT_STATUSES = {
    "PROPOSED",
    "ADMITTED",
    "WAITING",
    "BACKLOG",
    "RESERVED",
    "RUNNING",
    "COMPLETED",
    "PRUNED",
}
RUN_STATUSES = {
    "CREATED",
    "ACTIVE",
    "SOLVED",
    "REFUTED",
    "BLOCKED",
    "EXHAUSTED",
    "BUDGET_EXHAUSTED",
    "PAUSED",
    "FAILED",
}
GOAL_NODE_KINDS = {"AND", "OR", "CLAIM"}
EXPERIMENT_MODES = {"explore", "validate", "falsify", "hidden_eval", "skillopt"}
ACTION_KINDS = {"command", "external", "manual"}
WAIT_KINDS = {"time", "evidence"}
WAIT_EXPIRE_POLICIES = {"backlog", "release"}
EVENT_TYPES = {
    "RUN_CREATED",
    "SPEC_LOCKED",
    "CONTRACT_ADDED",
    "EXPERIMENT_PROPOSED",
    "EXPERIMENT_ADMITTED",
    "EXPERIMENT_BACKLOGGED",
    "EXPERIMENT_PRUNED",
    "ATTEMPT_RESERVED",
    "ATTEMPT_STARTED",
    "OBSERVATION_RECORDED",
    "VERDICT_ISSUED",
    "WAIT_FIRED",
    "WAIT_EXPIRED",
    "LESSON_CANDIDATE_CREATED",
    "LESSON_EVIDENCE_ADDED",
    "LESSON_PROMOTED",
    "LESSON_REVOKED",
    "RUN_PAUSED",
    "RUN_RESUMED",
    "RUN_FAILED",
    "RUN_FINALIZED",
    "REPORT_RENDERED",
    "EVIDENCE_REPRODUCED",
}

_ID_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def safe_id(value: str, *, default: str = "item") -> str:
    value = _ID_RE.sub("-", str(value).strip()).strip("-._")
    return value or default


def canonical_hash(value: Any, *, prefix: str = "sha256:") -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return prefix + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_rule_group(value: Any) -> dict[str, list[dict[str, Any]]]:
    if not value:
        return {"all": [], "any": []}
    if isinstance(value, list):
        return {"all": [dict(x) for x in value if isinstance(x, dict)], "any": []}
    if not isinstance(value, dict):
        raise ValueError("rule group must be an object or a list of checks")
    return {
        "all": [dict(x) for x in _as_list(value.get("all")) if isinstance(x, dict)],
        "any": [dict(x) for x in _as_list(value.get("any")) if isinstance(x, dict)],
    }


def normalize_contract(raw: dict[str, Any], *, known_claim_ids: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("verification contract must be an object")
    contract = copy.deepcopy(raw)
    contract_id = safe_id(str(contract.get("id") or ""), default="")
    if not contract_id:
        raise ValueError("verification contract requires id")
    target_claim_id = safe_id(str(contract.get("target_claim_id") or ""), default="")
    if not target_claim_id:
        raise ValueError(f"contract {contract_id} requires target_claim_id")
    if known_claim_ids is not None and target_claim_id not in known_claim_ids:
        raise ValueError(f"contract {contract_id} targets unknown claim {target_claim_id}")
    kind = str(contract.get("kind") or "metric").strip().lower()
    if kind not in {"metric", "manual"}:
        raise ValueError(f"contract {contract_id} has unsupported kind {kind!r}")
    min_passes = max(1, _int((contract.get("repetition") or {}).get("min_passes"), 1))
    min_contexts = max(1, _int((contract.get("repetition") or {}).get("min_independent_contexts"), 1))
    preconditions = normalize_rule_group(contract.get("preconditions"))
    invalid_if = normalize_rule_group(contract.get("invalid_if"))
    pass_if = normalize_rule_group(contract.get("pass_if"))
    fail_if = normalize_rule_group(contract.get("fail_if"))
    guardrails = normalize_rule_group(contract.get("guardrails"))
    if kind == "metric":
        if not (pass_if["all"] or pass_if["any"]):
            raise ValueError(f"metric contract {contract_id} requires at least one pass_if check")
        if not (fail_if["all"] or fail_if["any"]):
            raise ValueError(f"metric contract {contract_id} requires at least one fail_if check")
    visibility = str(contract.get("visibility") or "normal")
    if visibility not in {"normal", "host_only"}:
        raise ValueError(f"contract {contract_id} has invalid visibility {visibility!r}")
    return {
        "id": contract_id,
        "version": str(contract.get("version") or "1"),
        "target_claim_id": target_claim_id,
        "kind": kind,
        "description": str(contract.get("description") or ""),
        "preconditions": preconditions,
        "invalid_if": invalid_if,
        "pass_if": pass_if,
        "fail_if": fail_if,
        "guardrails": guardrails,
        "required_artifacts": [str(x) for x in _as_list(contract.get("required_artifacts")) if str(x).strip()],
        "repetition": {
            "min_passes": min_passes,
            "min_independent_contexts": min_contexts,
        },
        "visibility": visibility,
        "metadata": dict(contract.get("metadata") or {}),
    }


def normalize_task_spec(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("research task spec must be an object")
    spec = copy.deepcopy(raw)
    topic = str(spec.get("topic") or spec.get("objective") or "").strip()
    if not topic:
        raise ValueError("research task spec requires topic")
    task_id = safe_id(str(spec.get("id") or topic[:64]), default="research")

    raw_claims = _as_list(spec.get("claims"))
    if not raw_claims:
        raise ValueError("research task spec requires at least one claim")
    claims: list[dict[str, Any]] = []
    claim_ids: set[str] = set()
    for index, item in enumerate(raw_claims, start=1):
        if isinstance(item, str):
            item = {"id": f"claim-{index}", "statement": item}
        if not isinstance(item, dict):
            raise ValueError(f"claim #{index} must be an object or string")
        claim_id = safe_id(str(item.get("id") or f"claim-{index}"))
        if claim_id in claim_ids:
            raise ValueError(f"duplicate claim id: {claim_id}")
        claim_ids.add(claim_id)
        statement = str(item.get("statement") or item.get("claim") or "").strip()
        if not statement:
            raise ValueError(f"claim {claim_id} requires statement")
        claims.append(
            {
                "id": claim_id,
                "statement": statement,
                "label": str(item.get("label") or "").strip()[:12],
                "required": bool(item.get("required", True)),
                "critical": bool(item.get("critical", False)),
                "weight": max(0.0, _float(item.get("weight"), 1.0)),
                "depends_on": [safe_id(str(x)) for x in _as_list(item.get("depends_on")) if str(x).strip()],
                "tags": [str(x) for x in _as_list(item.get("tags")) if str(x).strip()],
                "metadata": dict(item.get("metadata") or {}),
            }
        )
    for claim in claims:
        unknown = [x for x in claim["depends_on"] if x not in claim_ids]
        if unknown:
            raise ValueError(f"claim {claim['id']} depends on unknown claims: {unknown}")
        if claim["id"] in claim["depends_on"]:
            raise ValueError(f"claim {claim['id']} cannot depend on itself")

    # Reject dependency cycles because rollback/invalidation semantics would be ambiguous.
    dependency_map = {claim["id"]: list(claim["depends_on"]) for claim in claims}
    dep_visiting: set[str] = set()
    dep_visited: set[str] = set()

    def visit_dependency(claim_id: str) -> None:
        if claim_id in dep_visited:
            return
        if claim_id in dep_visiting:
            raise ValueError(f"claim dependency cycle detected at {claim_id}")
        dep_visiting.add(claim_id)
        for dependency in dependency_map.get(claim_id, []):
            visit_dependency(dependency)
        dep_visiting.remove(claim_id)
        dep_visited.add(claim_id)

    for claim_id in dependency_map:
        visit_dependency(claim_id)

    raw_graph = dict(spec.get("goal_graph") or {})
    raw_nodes = _as_list(raw_graph.get("nodes"))
    if not raw_nodes:
        root_id = "goal-root"
        nodes: list[dict[str, Any]] = [
            {
                "id": root_id,
                "kind": "AND",
                "title": topic,
                "children": [c["id"] for c in claims if c["required"]],
            }
        ]
        for claim in claims:
            nodes.append(
                {
                    "id": claim["id"],
                    "kind": "CLAIM",
                    "title": claim["statement"],
                    "claim_id": claim["id"],
                    "children": [],
                }
            )
    else:
        nodes = []
        seen_nodes: set[str] = set()
        for index, item in enumerate(raw_nodes, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"goal graph node #{index} must be an object")
            node_id = safe_id(str(item.get("id") or f"goal-node-{index}"))
            if node_id in seen_nodes:
                raise ValueError(f"duplicate goal graph node id: {node_id}")
            seen_nodes.add(node_id)
            kind = str(item.get("kind") or "CLAIM").upper()
            if kind not in GOAL_NODE_KINDS:
                raise ValueError(f"goal graph node {node_id} has invalid kind {kind!r}")
            node = {
                "id": node_id,
                "kind": kind,
                "title": str(item.get("title") or node_id),
                "children": [safe_id(str(x)) for x in _as_list(item.get("children")) if str(x).strip()],
            }
            if kind == "CLAIM":
                claim_id = safe_id(str(item.get("claim_id") or node_id))
                if claim_id not in claim_ids:
                    raise ValueError(f"goal node {node_id} references unknown claim {claim_id}")
                node["claim_id"] = claim_id
                node["children"] = []
            nodes.append(node)
        root_id = safe_id(str(raw_graph.get("root_id") or nodes[0]["id"]))
        node_ids = {n["id"] for n in nodes}
        if root_id not in node_ids:
            raise ValueError(f"goal_graph.root_id references unknown node {root_id}")
        for node in nodes:
            unknown = [x for x in node["children"] if x not in node_ids]
            if unknown:
                raise ValueError(f"goal node {node['id']} has unknown children: {unknown}")
            if node["kind"] in {"AND", "OR"} and not node["children"]:
                raise ValueError(f"goal node {node['id']} ({node['kind']}) requires children")

    # A required claim omitted from the reachable Goal Graph could let the run "solve" early.
    node_map = {node["id"]: node for node in nodes}
    graph_visiting: set[str] = set()
    graph_visited: set[str] = set()
    reachable_claims: set[str] = set()

    def visit_goal(node_id: str) -> None:
        if node_id in graph_visited:
            return
        if node_id in graph_visiting:
            raise ValueError(f"goal graph cycle detected at {node_id}")
        graph_visiting.add(node_id)
        node = node_map[node_id]
        if node["kind"] == "CLAIM":
            reachable_claims.add(node["claim_id"])
        for child in node.get("children") or []:
            visit_goal(child)
        graph_visiting.remove(node_id)
        graph_visited.add(node_id)

    visit_goal(root_id)
    missing_required = [claim["id"] for claim in claims if claim["required"] and claim["id"] not in reachable_claims]
    if missing_required:
        raise ValueError(f"required claims are not reachable from goal_graph.root_id: {missing_required}")

    contracts: list[dict[str, Any]] = []
    contract_ids: set[str] = set()
    for raw_contract in _as_list(spec.get("verification_contracts")):
        contract = normalize_contract(raw_contract, known_claim_ids=claim_ids)
        if contract["id"] in contract_ids:
            raise ValueError(f"duplicate verification contract id: {contract['id']}")
        contract_ids.add(contract["id"])
        contracts.append(contract)

    # Budgets are opt-in guardrails: an omitted limit means unlimited. A default
    # ceiling the author never chose must not be what ends a run.
    budget_raw = dict(spec.get("budget") or {})
    max_attempts = budget_raw.get("max_attempts")
    max_attempts = max(1, _int(max_attempts, 1)) if max_attempts is not None else None
    max_cost_units = budget_raw.get("max_cost_units")
    max_cost_units = max(0.0, _float(max_cost_units, 0.0)) if max_cost_units is not None else None
    max_wall_minutes = budget_raw.get("max_wall_minutes")
    max_wall_minutes = max(1, _int(max_wall_minutes, 1)) if max_wall_minutes is not None else None

    stop_raw = dict(spec.get("stop_policy") or {})
    action_space = list(
        dict.fromkeys(
            safe_id(str(x).lower())
            for x in _as_list(spec.get("action_space"))
            if str(x).strip()
        )
    )
    if not action_space:
        action_space = ["search", "inspect", "compare", "compute", "experiment", "falsify"]

    raw_i18n = spec.get("i18n") or {}
    if not isinstance(raw_i18n, dict) or any(not isinstance(v, dict) for v in raw_i18n.values()):
        raise ValueError("i18n must map language codes to translation objects")

    return {
        "schema_version": TASK_SCHEMA_VERSION,
        "id": task_id,
        "topic": topic,
        "i18n": copy.deepcopy(raw_i18n),
        "created_by": str(spec.get("created_by") or "user"),
        "claims": claims,
        "goal_graph": {"root_id": root_id, "nodes": nodes},
        "hard_constraints": [str(x) for x in _as_list(spec.get("hard_constraints")) if str(x).strip()],
        "action_space": action_space,
        "verification_contracts": contracts,
        "budget": {
            "max_attempts": max_attempts,
            "max_cost_units": max_cost_units,
            "max_wall_minutes": max_wall_minutes,
        },
        "stop_policy": {
            "stop_on_goal_pass": bool(stop_raw.get("stop_on_goal_pass", True)),
            "stop_on_goal_refuted": bool(stop_raw.get("stop_on_goal_refuted", False)),
            "block_without_verifier": bool(stop_raw.get("block_without_verifier", True)),
            "allow_manual_verdict": bool(stop_raw.get("allow_manual_verdict", False)),
            "max_invalid_attempts_per_experiment": max(1, _int(stop_raw.get("max_invalid_attempts_per_experiment"), 2)),
            "max_error_attempts_per_experiment": max(1, _int(stop_raw.get("max_error_attempts_per_experiment"), 3)),
            "require_uncontested_solve": bool(stop_raw.get("require_uncontested_solve", False)),
            "allow_provisional_prereq": bool(stop_raw.get("allow_provisional_prereq", False)),
            "require_citations": bool(stop_raw.get("require_citations", False)),
        },
        "metadata": dict(spec.get("metadata") or {}),
    }


def experiment_dedupe_key(experiment: dict[str, Any]) -> str:
    action = dict(experiment.get("action") or {})
    action.pop("notes", None)
    payload = {
        "target_claim_ids": sorted(experiment.get("target_claim_ids") or []),
        "contract_id": experiment.get("contract_id"),
        "mode": experiment.get("mode"),
        "context_id": experiment.get("context_id"),
        "action_family": experiment.get("action_family"),
        "action": action,
    }
    return canonical_hash(payload)


def normalize_wait(raw: Any, *, known_claim_ids: set[str] | None = None) -> dict[str, Any] | None:
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ValueError("experiment wait must be an object")
    kind = str(raw.get("kind") or "").strip().lower()
    if kind not in WAIT_KINDS:
        raise ValueError(f"wait.kind must be one of {sorted(WAIT_KINDS)}")
    on_expire = str(raw.get("on_expire") or "backlog").strip().lower()
    if on_expire not in WAIT_EXPIRE_POLICIES:
        raise ValueError(f"wait.on_expire must be one of {sorted(WAIT_EXPIRE_POLICIES)}")
    deadline_minutes = raw.get("deadline_minutes")
    if deadline_minutes is not None:
        deadline_minutes = _int(deadline_minutes, 0)
        if deadline_minutes <= 0:
            raise ValueError("wait.deadline_minutes must be a positive integer")
    wait: dict[str, Any] = {
        "kind": kind,
        "not_before": None,
        "after": None,
        "until_evidence": None,
        "deadline_minutes": deadline_minutes,
        "on_expire": on_expire,
    }
    if kind == "time":
        not_before = str(raw.get("not_before") or "").strip() or None
        after = raw.get("after")
        if after is not None:
            if not isinstance(after, dict) or not str(after.get("evidence_id") or "").strip():
                raise ValueError("wait.after requires evidence_id")
            minutes = _int(after.get("minutes"), 0)
            if minutes <= 0:
                raise ValueError("wait.after.minutes must be a positive integer")
            wait["after"] = {"evidence_id": safe_id(str(after["evidence_id"])), "minutes": minutes}
        if bool(not_before) == bool(wait["after"]):
            raise ValueError("time wait requires exactly one of not_before or after")
        wait["not_before"] = not_before
    else:
        until = raw.get("until_evidence")
        if not isinstance(until, dict) or not str(until.get("claim_id") or "").strip():
            raise ValueError("evidence wait requires until_evidence.claim_id")
        claim_id = safe_id(str(until["claim_id"]))
        if known_claim_ids is not None and claim_id not in known_claim_ids:
            raise ValueError(f"wait.until_evidence references unknown claim {claim_id}")
        verdict = str(until.get("verdict") or "").strip().upper() or None
        if verdict is not None and verdict not in {"PASS", "FAIL", "INCONCLUSIVE"}:
            raise ValueError("wait.until_evidence.verdict must be PASS, FAIL, or INCONCLUSIVE")
        wait["until_evidence"] = {
            "claim_id": claim_id,
            "contract_id": safe_id(str(until["contract_id"])) if until.get("contract_id") else None,
            "verdict": verdict,
            "context_id": str(until["context_id"]) if until.get("context_id") else None,
        }
    return wait


def normalize_based_on(raw: Any) -> dict[str, list[str]]:
    """Citations an experiment builds on: prior evidence and lessons by id."""
    if raw is None:
        return {"evidence_ids": [], "lesson_ids": []}
    if not isinstance(raw, dict):
        raise ValueError("experiment based_on must be an object with evidence_ids/lesson_ids")
    return {
        "evidence_ids": [safe_id(str(x)) for x in _as_list(raw.get("evidence_ids")) if str(x).strip()],
        "lesson_ids": [safe_id(str(x)) for x in _as_list(raw.get("lesson_ids")) if str(x).strip()],
    }


def normalize_experiment(
    raw: dict[str, Any],
    *,
    known_claim_ids: set[str],
    known_contract_ids: set[str],
    current_state_id: str,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("experiment must be an object")
    item = copy.deepcopy(raw)
    experiment_id = safe_id(str(item.get("id") or item.get("experiment_id") or ""), default="")
    if not experiment_id:
        raise ValueError("experiment requires id")
    targets = [safe_id(str(x)) for x in _as_list(item.get("target_claim_ids") or item.get("target_claim_id")) if str(x).strip()]
    if not targets:
        raise ValueError(f"experiment {experiment_id} requires target_claim_ids")
    unknown_targets = [x for x in targets if x not in known_claim_ids]
    if unknown_targets:
        raise ValueError(f"experiment {experiment_id} targets unknown claims: {unknown_targets}")
    contract_id = safe_id(str(item.get("contract_id") or ""), default="")
    mode = str(item.get("mode") or "validate").lower()
    if mode not in EXPERIMENT_MODES:
        raise ValueError(f"experiment {experiment_id} has invalid mode {mode!r}")
    action = dict(item.get("action") or {})
    action_kind = str(action.get("kind") or "external").lower()
    if action_kind not in ACTION_KINDS:
        raise ValueError(f"experiment {experiment_id} has unsupported action.kind {action_kind!r}")
    action["kind"] = action_kind
    if action_kind == "command" and not str(action.get("command") or "").strip():
        raise ValueError(f"command experiment {experiment_id} requires action.command")
    default_action_family = {"command": "compute", "external": "experiment", "manual": "inspect"}[action_kind]
    action_family = safe_id(
        str(item.get("action_family") or default_action_family).lower(),
        default=default_action_family,
    )
    expected = dict(item.get("expected_outcomes") or {})
    missing_expected = [x for x in ("pass", "fail", "inconclusive", "invalid") if not str(expected.get(x) or "").strip()]
    if missing_expected:
        raise ValueError(f"experiment {experiment_id} missing expected_outcomes: {missing_expected}")

    score_raw = dict(item.get("priority") or {})
    components = {
        "goal_progress": _float(score_raw.get("goal_progress"), 0.5),
        "information_gain": _float(score_raw.get("information_gain"), 0.5),
        "reusable_value": _float(score_raw.get("reusable_value"), 0.0),
        "novelty": _float(score_raw.get("novelty"), 0.0),
        "cost": _float(score_raw.get("cost"), _float((item.get("cost") or {}).get("units"), 1.0)),
        "invalidity_risk": _float(score_raw.get("invalidity_risk"), 0.0),
        "duplication": _float(score_raw.get("duplication"), 0.0),
    }
    priority_score = (
        components["goal_progress"]
        + components["information_gain"]
        + 0.35 * components["reusable_value"]
        + 0.25 * components["novelty"]
        - 0.20 * components["cost"]
        - 0.50 * components["invalidity_risk"]
        - 0.75 * components["duplication"]
    )
    visibility = str(item.get("visibility") or ("host_only" if mode == "hidden_eval" else "normal"))
    if visibility not in {"normal", "host_only"}:
        raise ValueError(f"experiment {experiment_id} has invalid visibility {visibility!r}")
    normalized = {
        "id": experiment_id,
        "title": str(item.get("title") or experiment_id),
        "rationale": str(item.get("rationale") or ""),
        "target_claim_ids": targets,
        "contract_id": contract_id or None,
        "mode": mode,
        "visibility": visibility,
        "from_state_id": str(item.get("from_state_id") or current_state_id),
        "action_family": action_family,
        "action": action,
        "expected_outcomes": {key: str(expected[key]) for key in ("pass", "fail", "inconclusive", "invalid")},
        "priority": {**components, "score": round(priority_score, 6)},
        "cost": {
            "attempts": max(1, _int((item.get("cost") or {}).get("attempts"), 1)),
            "units": max(0.0, _float((item.get("cost") or {}).get("units"), 1.0)),
        },
        "context_id": str(item.get("context_id") or "default"),
        "based_on": normalize_based_on(item.get("based_on")),
        "discriminating_note": str(item.get("discriminating_note") or "").strip(),
        "wait": normalize_wait(item.get("wait"), known_claim_ids=known_claim_ids),
        "metadata": dict(item.get("metadata") or {}),
    }
    normalized["dedupe_key"] = experiment_dedupe_key(normalized)
    normalized["has_known_contract"] = bool(contract_id and contract_id in known_contract_ids)
    return normalized


def normalize_lesson(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("lesson must be an object")
    lesson_id = safe_id(str(raw.get("id") or ""), default="")
    if not lesson_id:
        raise ValueError("lesson requires id")
    observation = str(raw.get("observation") or "").strip()
    recommendation = str(raw.get("recommendation") or "").strip()
    if not observation or not recommendation:
        raise ValueError("lesson requires observation and recommendation")
    return {
        "id": lesson_id,
        "type": str(raw.get("type") or "method"),
        "scope": dict(raw.get("scope") or {}),
        "preconditions": [str(x) for x in _as_list(raw.get("preconditions")) if str(x).strip()],
        "observation": observation,
        "recommendation": recommendation,
        "evidence_ids": [safe_id(str(x)) for x in _as_list(raw.get("evidence_ids")) if str(x).strip()],
        "counterexample_ids": [safe_id(str(x)) for x in _as_list(raw.get("counterexample_ids")) if str(x).strip()],
        "confidence": str(raw.get("confidence") or "medium"),
        "metadata": dict(raw.get("metadata") or {}),
    }
