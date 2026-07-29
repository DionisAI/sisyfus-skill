from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .paths import ensure_layout
from .utils import read_json, write_json


DEFAULT_MODEL_POLICY: dict[str, Any] = {
    "schema_version": "sisyfus.model_policy.v0.6",
    "description": (
        "Configurable model routing policy. Model names are aliases/placeholders; "
        "map them to the actual CLI/SDK names used in your environment."
    ),
    "default_task_type": "implementation",
    "profiles": {
        "frontier_exploration": {
            "tier": "frontier",
            "description": "Divergent exploration, structural experiment design, factor research, AlphaGPT-style formula mining, and high-ambiguity failure investigation.",
            "model_aliases": ["anthropic-fable-5", "claude-fable-5", "gpt-5.6-xhigh", "gpt-5.5-xhigh"],
            "default_model": "claude-fable-5",
            "reasoning": "xhigh",
            "cost_class": "very_high",
            "context_max_chars": 160000,
            "allow_agent": True,
        },
        "strategic_planning": {
            "tier": "frontier_planning",
            "description": "Overall planning, architecture, sequencing, and policy design.",
            "model_aliases": ["gpt-5.5-xhigh", "gpt-5.6-xhigh", "anthropic-fable-5"],
            "default_model": "gpt-5.5-xhigh",
            "reasoning": "xhigh",
            "cost_class": "high",
            "context_max_chars": 120000,
            "allow_agent": True,
        },
        "grader_strong": {
            "tier": "grader",
            "description": "Independent Outcomes judge. Reads artifacts and rubric, not worker self-justification.",
            "model_aliases": ["claude-sonnet-4.6", "gpt-5.4-mini", "gpt-5.5-xhigh"],
            "default_model": "claude-sonnet-4.6",
            "reasoning": "high",
            "cost_class": "medium",
            "context_max_chars": 80000,
            "allow_agent": True,
        },
        "balanced_ops": {
            "tier": "balanced",
            "description": "Information collection, literature exploration, summarization, routine implementation, and agentops triage.",
            "model_aliases": ["claude-sonnet-4.6", "gpt-5.4-mini", "deepseek-v4"],
            "default_model": "claude-sonnet-4.6",
            "reasoning": "medium",
            "cost_class": "medium",
            "context_max_chars": 60000,
            "allow_agent": True,
        },
        "cheap_summary": {
            "tier": "compact",
            "description": "Session distillation, compression, extraction, and low-risk summaries.",
            "model_aliases": ["gpt-5.4-mini", "deepseek-v4", "claude-sonnet-4.6"],
            "default_model": "gpt-5.4-mini",
            "reasoning": "low",
            "cost_class": "low",
            "context_max_chars": 40000,
            "allow_agent": True,
        },
        "deterministic_program": {
            "tier": "program",
            "description": "Do not call a model. Use monitors/scripts/commands first.",
            "model_aliases": [],
            "default_model": "none",
            "reasoning": "none",
            "cost_class": "zero_model_tokens",
            "context_max_chars": 12000,
            "allow_agent": False,
        },
    },
    "routes": {
        "planning": {"profile": "strategic_planning"},
        "architecture": {"profile": "strategic_planning"},
        "exploratory": {"profile": "frontier_exploration"},
        "divergent": {"profile": "frontier_exploration"},
        "research_design": {"profile": "frontier_exploration"},
        "beam_search": {"profile": "frontier_exploration", "roles": {"distiller": {"profile": "cheap_summary"}}},
        "factor_research": {"profile": "frontier_exploration"},
        "alpha_mining": {"profile": "frontier_exploration"},
        "formula_alpha_mining": {"profile": "frontier_exploration"},
        "cross_sectional_research": {"profile": "frontier_exploration"},
        "beam_research": {"profile": "strategic_planning", "roles": {"grader": {"profile": "grader_strong"}, "distiller": {"profile": "cheap_summary"}}},
        "outcome_grading": {"profile": "grader_strong"},
        "experiment_golf": {"profile": "frontier_exploration", "roles": {"grader": {"profile": "grader_strong"}}},
        "memory_investigation": {"profile": "frontier_exploration", "roles": {"grader": {"profile": "grader_strong"}}},
        "implementation": {
            "profile": "balanced_ops",
            "roles": {
                "explorer": {"profile": "balanced_ops"},
                "implementer": {"profile": "balanced_ops"},
                "verifier": {"profile": "balanced_ops"},
                "distiller": {"profile": "cheap_summary"},
            },
        },
        "information_collection": {"profile": "balanced_ops"},
        "literature": {"profile": "balanced_ops"},
        "summarization": {"profile": "cheap_summary"},
        "distillation": {"profile": "cheap_summary"},
        "monitoring": {"profile": "deterministic_program", "allow_agent": False},
        "agentops": {"profile": "deterministic_program", "allow_agent": False},
        "backtest_monitor": {"profile": "deterministic_program", "allow_agent": False},
        "repeated_backtest": {"profile": "deterministic_program", "allow_agent": False},
    },
    "session_defaults": {
        "one_task_per_session": True,
        "auto_distill": True,
        "record_session_index": True,
        "read_recent_sessions": True,
        "recent_session_limit": 3,
        "session_context_max_chars": 12000,
        "never_load_raw_transcripts_by_default": True,
        "read_human_review": True,
        "human_review_max_chars": 10000,
    },
}


TASK_TYPE_ALIASES = {
    "explore": "exploratory",
    "exploration": "exploratory",
    "planning": "planning",
    "plan": "planning",
    "architecture": "architecture",
    "research": "information_collection",
    "literature_review": "literature",
    "summary": "summarization",
    "summarize": "summarization",
    "distill": "distillation",
    "monitor": "monitoring",
    "ops": "agentops",
    "agent_ops": "agentops",
    "agentops": "agentops",
    "backtest": "backtest_monitor",
    "beam": "beam_search",
    "beam_search": "beam_search",
    "factor": "factor_research",
    "factors": "factor_research",
    "alpha": "alpha_mining",
    "alpha_gpt": "formula_alpha_mining",
    "alphagpt": "formula_alpha_mining",
    "formula_alpha": "formula_alpha_mining",
    "cross_sectional": "cross_sectional_research",
    "cross_section": "cross_sectional_research",
    "beam": "beam_research",
    "outcome": "outcome_grading",
    "outcomes": "outcome_grading",
    "experiment": "experiment_golf",
    "parameter_golf": "experiment_golf",
    "memory_investigation": "memory_investigation",
    "repeated_backtest": "repeated_backtest",
}


def normalize_task_type(value: str | None, *, default: str = "implementation") -> str:
    raw = (value or default or "implementation").strip().lower().replace("-", "_").replace(" ", "_")
    return TASK_TYPE_ALIASES.get(raw, raw)


def model_policy_path(root: Path) -> Path:
    return ensure_layout(root) / "model_policy.json"


def write_default_model_policy(root: Path, *, force: bool = False) -> Path:
    path = model_policy_path(root)
    if force or not path.exists():
        write_json(path, DEFAULT_MODEL_POLICY)
    return path


def load_model_policy(root: Path) -> dict[str, Any]:
    path = model_policy_path(root)
    if not path.exists():
        write_default_model_policy(root)
    policy = read_json(path)
    if not isinstance(policy, dict):
        raise ValueError(f"Invalid model policy: {path}")
    merged = DEFAULT_MODEL_POLICY | policy
    merged["profiles"] = DEFAULT_MODEL_POLICY["profiles"] | dict(policy.get("profiles", {}))
    merged["routes"] = DEFAULT_MODEL_POLICY["routes"] | dict(policy.get("routes", {}))
    merged["session_defaults"] = DEFAULT_MODEL_POLICY["session_defaults"] | dict(policy.get("session_defaults", {}))
    return merged


def task_type_from_goal(goal: dict[str, Any], policy: dict[str, Any] | None = None) -> str:
    default = (policy or DEFAULT_MODEL_POLICY).get("default_task_type", "implementation")
    value = goal.get("task_type") or goal.get("classification", {}).get("task_type") or goal.get("model_policy", {}).get("task_type")
    return normalize_task_type(str(value) if value is not None else None, default=str(default))


def resolve_model_route(
    root: Path,
    *,
    goal: dict[str, Any] | None = None,
    task_type: str | None = None,
    role: str = "implementer",
    override_profile: str | None = None,
    override_model: str | None = None,
) -> dict[str, Any]:
    policy = load_model_policy(root)
    resolved_task_type = normalize_task_type(task_type, default=str(policy.get("default_task_type", "implementation")))
    if goal is not None:
        resolved_task_type = task_type_from_goal(goal, policy)

    route = dict(policy.get("routes", {}).get(resolved_task_type, {}))
    role_cfg = dict((goal or {}).get("agents", {}).get(role, {}) or {})
    role_route = dict(route.get("roles", {}).get(role, {}) or {})

    profile_id = (
        override_profile
        or role_cfg.get("model_profile")
        or role_cfg.get("profile")
        or role_route.get("profile")
        or route.get("profile")
        or policy.get("default_profile")
        or "balanced_ops"
    )
    profiles = policy.get("profiles", {})
    if profile_id not in profiles:
        raise ValueError(f"Unknown model profile {profile_id!r}. Add it to .sisyfus/model_policy.json")
    profile = dict(profiles[profile_id])

    model = override_model or role_cfg.get("model") or role_route.get("model") or profile.get("default_model") or "none"
    reasoning = role_cfg.get("reasoning") or role_route.get("reasoning") or profile.get("reasoning") or "medium"
    allow_agent = bool(profile.get("allow_agent", True))
    if route.get("allow_agent") is False or role_route.get("allow_agent") is False:
        allow_agent = False
    if role_cfg.get("allow_agent") is False:
        allow_agent = False
    if role_cfg.get("force_agent") is True:
        allow_agent = True

    context_max_chars = int(
        role_cfg.get("context_max_chars")
        or role_route.get("context_max_chars")
        or profile.get("context_max_chars")
        or 50000
    )
    return {
        "schema_version": "sisyfus.model_route.v0.6",
        "task_type": resolved_task_type,
        "role": role,
        "profile_id": profile_id,
        "tier": profile.get("tier"),
        "model": model,
        "model_aliases": list(profile.get("model_aliases", [])),
        "reasoning": reasoning,
        "cost_class": profile.get("cost_class"),
        "context_max_chars": context_max_chars,
        "estimated_context_tokens": estimate_tokens_from_chars(context_max_chars),
        "allow_agent": allow_agent,
        "description": profile.get("description", ""),
    }


def resolve_session_policy(goal: dict[str, Any], root: Path) -> dict[str, Any]:
    policy = load_model_policy(root)
    defaults = dict(policy.get("session_defaults", {}))
    return defaults | dict(goal.get("session_policy", {}) or {})


def enabled_roles(goal: dict[str, Any]) -> list[str]:
    roles: list[str] = []
    for role in ["explorer", "implementer", "verifier", "distiller"]:
        cfg = goal.get("agents", {}).get(role, {}) or {}
        if cfg.get("enabled", role in {"explorer", "implementer"}):
            roles.append(role)
    return roles


def context_budget_for_goal(root: Path, goal: dict[str, Any]) -> int:
    explicit = goal.get("context", {}).get("max_chars")
    if explicit:
        return int(explicit)
    budgets: list[int] = []
    for role in enabled_roles(goal):
        route = resolve_model_route(root, goal=goal, role=role)
        if route.get("allow_agent"):
            budgets.append(int(route.get("context_max_chars", 50000)))
    if not budgets:
        route = resolve_model_route(root, goal=goal, role="implementer")
        budgets.append(int(route.get("context_max_chars", 12000)))
    session_policy = resolve_session_policy(goal, root)
    # Recent session summaries are compact; keep them bounded even for frontier models.
    return max(8000, min(max(budgets), int(goal.get("context", {}).get("hard_max_chars") or max(budgets))))


def estimate_tokens_from_chars(chars: int) -> int:
    return int(math.ceil(max(chars, 0) / 4.0))
