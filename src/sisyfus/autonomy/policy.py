from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Mapping, Protocol

from .models import CapabilityResult, Decision, DecisionKind, VerificationResult


class AutonomyError(RuntimeError):
    pass


class IncompatibleSchemaError(AutonomyError):
    pass


class NotFoundError(AutonomyError):
    pass


class ConcurrentUpdate(AutonomyError):
    pass


class LeaseLost(AutonomyError):
    pass


class InvalidTransition(AutonomyError):
    pass


class PolicyDeniedError(AutonomyError):
    pass


class IdempotencyConflictError(AutonomyError):
    pass


class UnknownCommitError(AutonomyError):
    pass


class VerificationRequiredError(AutonomyError):
    pass


class AttemptBudgetExceeded(AutonomyError):
    pass


class Capability(Protocol):
    name: str
    risk_tier: int
    replay_safe: bool
    description: str

    def execute(self, arguments: Mapping[str, Any], *, idempotency_key: str) -> CapabilityResult: ...


class Verifier(Protocol):
    verifier_id: str

    def verify(
        self,
        context: Mapping[str, Any],
        decision: Decision,
        result: CapabilityResult,
    ) -> VerificationResult: ...


class Planner(Protocol):
    def __call__(self, continuation: Mapping[str, Any], context: Mapping[str, Any]) -> Decision: ...


@dataclass(frozen=True)
class CapabilityBinding:
    capability: Capability
    verifier: Verifier


class CapabilityRegistry:
    def __init__(self) -> None:
        self._items: dict[str, CapabilityBinding] = {}
        self._lock = RLock()

    def register(self, capability: Capability, verifier: Verifier) -> None:
        name = str(capability.name).strip()
        if not name:
            raise ValueError("capability name must not be empty")
        if int(capability.risk_tier) not in {0, 1, 2, 3, 4}:
            raise ValueError("capability risk_tier must be between 0 and 4")
        with self._lock:
            if name in self._items:
                raise ValueError(f"capability already registered: {name}")
            self._items[name] = CapabilityBinding(capability, verifier)

    def get(self, name: str | None) -> CapabilityBinding:
        key = str(name or "")
        with self._lock:
            try:
                return self._items[key]
            except KeyError as exc:
                raise PolicyDeniedError(f"unregistered capability: {key}") from exc

    def list(self) -> list[CapabilityBinding]:
        with self._lock:
            return [self._items[key] for key in sorted(self._items)]


@dataclass(frozen=True)
class Authorization:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class AutonomyPolicy:
    max_unattended_risk: int = 1
    allowed_capabilities: frozenset[str] | None = None
    denied_capabilities: frozenset[str] = field(default_factory=frozenset)
    require_idempotency_from_risk: int = 1

    def authorize(self, decision: Decision, capability: Capability | None) -> Authorization:
        item = decision.normalized()
        if item.kind != DecisionKind.EXECUTE:
            return Authorization(True, "non-execution decision")
        if capability is None:
            return Authorization(False, f"unregistered capability: {item.capability}")
        name = str(capability.name)
        if name in self.denied_capabilities:
            return Authorization(False, f"capability explicitly denied: {name}")
        if self.allowed_capabilities is not None and name not in self.allowed_capabilities:
            return Authorization(False, f"capability not in allowlist: {name}")
        if int(capability.risk_tier) > int(self.max_unattended_risk):
            return Authorization(
                False,
                f"capability {name} is R{capability.risk_tier}; unattended ceiling is R{self.max_unattended_risk}",
            )
        if int(capability.risk_tier) >= int(self.require_idempotency_from_risk) and not item.idempotency_key:
            return Authorization(False, f"capability {name} requires an idempotency_key")
        if int(item.risk_tier) != int(capability.risk_tier):
            return Authorization(
                False,
                f"planner declared R{item.risk_tier} but capability {name} is R{capability.risk_tier}",
            )
        return Authorization(True, "authorized")
