from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA = "sisyfus.research_os.v1"
FEATURES = ("goal_progress", "information_gain", "reusable_value", "novelty", "invalidity_risk", "duplication")
PREFLIGHT = ("authorization", "dependencies", "budget")


def digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def number(value: Any, *, minimum: float = 0, maximum: float = 1e12) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a finite number")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"number must be finite and in [{minimum}, {maximum}]")
    return result


@dataclass(frozen=True)
class Candidate:
    id: str
    research_id: str
    family: str
    title: str
    rationale: str
    features: tuple[float, ...]
    cost: float
    contract_hash: str
    action_hash: str
    requires: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.research_id or not self.family:
            raise ValueError("candidate identity must not be empty")
        if len(self.features) != len(FEATURES):
            raise ValueError("feature schema mismatch")
        for value in self.features:
            number(value, maximum=1)
        number(self.cost)

    def public(self) -> dict[str, Any]:
        # Deliberately no command, env, raw evidence, host-only criteria or outcomes.
        return asdict(self)

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "Candidate":
        return cls(**{**raw, "features": tuple(raw["features"]), "requires": tuple(raw.get("requires", ()))})


@dataclass(frozen=True)
class Judgment:
    actionable: float = 0.5
    duplicate: float = 0.5
    provider: str = "none"
    error: str | None = None

    def __post_init__(self) -> None:
        number(self.actionable, maximum=1)
        number(self.duplicate, maximum=1)


@dataclass(frozen=True)
class SOP:
    """Versioned execution contract; ordering can change, required gates cannot."""

    version: str = "research-sop-v1"
    preflight_order: tuple[str, ...] = PREFLIGHT
    max_attempts_per_experiment: int = 3

    def __post_init__(self) -> None:
        if len(self.preflight_order) != len(PREFLIGHT) or set(self.preflight_order) != set(PREFLIGHT):
            raise ValueError("SOP must retain every mandatory preflight gate exactly once")
        if type(self.max_attempts_per_experiment) is not int or not 1 <= self.max_attempts_per_experiment <= 100:
            raise ValueError("invalid SOP attempt limit")
        if not self.version:
            raise ValueError("SOP version required")

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LoopReport:
    research_id: str
    steps: int
    stop_reason: str
    run_status: str
    cost_units: float
    results: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    schema: str = SCHEMA
    reserved_cost_units: float = 0.0
    unresolved_attempts: tuple[str, ...] = ()
