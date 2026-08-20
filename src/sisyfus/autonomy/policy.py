from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .models import CapabilityResult, Decision, DecisionAction, RiskTier, VerificationResult


class Planner(Protocol):
    """Proposal generator. A planner never writes truth directly."""

    def decide(self, context: "ContinuationContext") -> Decision: ...


class Verifier(Protocol):
    """Independent evidence classifier. Only its verdict advances belief."""

    def verify(
        self,
        context: "ContinuationContext",
        decision: Decision,
        result: CapabilityResult,
    ) -> VerificationResult: ...


class Capability(Protocol):
    """Typed, bounded action surface exposed to autonomous decisions."""

    name: str
    risk_tier: RiskTier

    def execute(self, arguments: Mapping[str, Any], *, idempotency_key: str) -> CapabilityResult: ...


@dataclass(frozen=True)
class ContinuationContext:
    opportunity: Mapping[str, Any]
    continuation: Mapping[str, Any]
    events: tuple[Mapping[str, Any], ...]
    decisions: tuple[Mapping[str, Any], ...]
    evidence: tuple[Mapping[str, Any], ...]
    experiences: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> "ContinuationContext":
        return cls(
            opportunity=dict(snapshot.get("opportunity") or {}),
            continuation=dict(snapshot.get("continuation") or {}),
            events=tuple(dict(item or {}) for item in snapshot.get("events") or []),
            decisions=tuple(dict(item or {}) for item in snapshot.get("decisions") or []),
            evidence=tuple(dict(item or {}) for item in snapshot.get("evidence") or []),
            experiences=tuple(dict(item or {}) for item in snapshot.get("experiences") or []),
        )


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class AutonomyPolicy:
    """Capability admission policy for unattended execution.

    Defaults permit only deterministic/read-only and reversible local actions.
    Arbitrary shell, deployments, outbound messages, trading and destructive
    operations require an explicitly supplied policy rather than a global
    ``--yes`` switch.
    """

    allowed_risk_tiers: frozenset[RiskTier] = frozenset({RiskTier.R0, RiskTier.R1})
    denied_capabilities: frozenset[str] = frozenset(
        {
            "shell",
            "process.shell",
            "system.exec",
            "deployment.apply",
            "messaging.send",
            "trading.place_order",
            "filesystem.delete",
        }
    )
    allowed_capabilities: frozenset[str] | None = None

    def authorize(self, decision: Decision, capability: Capability | None = None) -> PolicyDecision:
        if decision.action != DecisionAction.EXECUTE:
            return PolicyDecision(True, "non-execution decision")
        name = str(decision.capability or "")
        if name in self.denied_capabilities:
            return PolicyDecision(False, f"capability {name!r} is explicitly denied")
        if self.allowed_capabilities is not None and name not in self.allowed_capabilities:
            return PolicyDecision(False, f"capability {name!r} is not in the allowlist")
        if decision.risk_tier not in self.allowed_risk_tiers:
            return PolicyDecision(False, f"risk tier {decision.risk_tier.value} is not authorized")
        if capability is None:
            return PolicyDecision(False, f"capability {name!r} is not registered")
        if capability.name != name:
            return PolicyDecision(False, f"capability registry mismatch: requested {name!r}, got {capability.name!r}")
        if capability.risk_tier != decision.risk_tier:
            return PolicyDecision(
                False,
                f"risk declaration mismatch: decision={decision.risk_tier.value}, capability={capability.risk_tier.value}",
            )
        return PolicyDecision(True, "authorized")


class CapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        name = str(capability.name).strip()
        if not name:
            raise ValueError("capability name must not be empty")
        if name in self._capabilities:
            raise ValueError(f"capability already registered: {name}")
        self._capabilities[name] = capability

    def get(self, name: str | None) -> Capability | None:
        return self._capabilities.get(str(name or ""))

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._capabilities))


