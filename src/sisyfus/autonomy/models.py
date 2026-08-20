from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping


class OpportunityStatus(StrEnum):
    OPEN = "OPEN"
    ADMITTED = "ADMITTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class ContinuationState(StrEnum):
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class DecisionAction(StrEnum):
    EXECUTE = "EXECUTE"
    WAIT = "WAIT"
    FINISH = "FINISH"
    ABORT = "ABORT"


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    ERROR = "ERROR"


class RiskTier(StrEnum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"


TERMINAL_STATES = {
    ContinuationState.SUCCEEDED,
    ContinuationState.FAILED,
    ContinuationState.BLOCKED,
    ContinuationState.CANCELLED,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def stable_id(prefix: str, *parts: Any, length: int = 20) -> str:
    material = "\x1f".join(canonical_json(part) for part in parts)
    digest = hashlib.sha256(material.encode("utf-8", errors="replace")).hexdigest()[:length]
    return f"{prefix}_{digest}"


@dataclass(frozen=True)
class OpportunityProposal:
    source: str
    kind: str
    payload: Mapping[str, Any]
    dedupe_key: str
    priority: int = 0
    confidence: float = 0.5
    not_before: str | None = None
    expires_at: str | None = None

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("opportunity source must not be empty")
        if not self.kind.strip():
            raise ValueError("opportunity kind must not be empty")
        if not self.dedupe_key.strip():
            raise ValueError("opportunity dedupe_key must not be empty")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("opportunity confidence must be between 0 and 1")


@dataclass(frozen=True)
class Decision:
    action: DecisionAction
    rationale: str
    capability: str | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)
    risk_tier: RiskTier = RiskTier.R0
    verifier_id: str = "default"
    wait_until: str | None = None
    terminal_on_pass: bool = False
    experience_key: str | None = None
    experience_scope: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if self.action == DecisionAction.EXECUTE and not (self.capability or "").strip():
            raise ValueError("EXECUTE decisions require a capability")
        if self.action == DecisionAction.WAIT and not self.wait_until:
            raise ValueError("WAIT decisions require wait_until")
        if self.action != DecisionAction.EXECUTE and self.capability:
            raise ValueError(f"{self.action} decisions must not specify a capability")
        if not self.rationale.strip():
            raise ValueError("decision rationale must not be empty")

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "rationale": self.rationale,
            "capability": self.capability,
            "arguments": dict(self.arguments),
            "risk_tier": self.risk_tier.value,
            "verifier_id": self.verifier_id,
            "wait_until": self.wait_until,
            "terminal_on_pass": self.terminal_on_pass,
            "experience_key": self.experience_key,
            "experience_scope": dict(self.experience_scope),
            "idempotency_key": self.idempotency_key,
        }

    def fingerprint(self) -> str:
        return stable_id("decision", self.as_dict())


@dataclass(frozen=True)
class CapabilityResult:
    status: str
    observation: Mapping[str, Any] = field(default_factory=dict)
    metrics: Mapping[str, Any] = field(default_factory=dict)
    artifacts: tuple[Mapping[str, Any], ...] = ()
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "observation": dict(self.observation),
            "metrics": dict(self.metrics),
            "artifacts": [dict(item) for item in self.artifacts],
            "error": self.error,
        }


@dataclass(frozen=True)
class VerificationResult:
    verdict: Verdict
    verifier_id: str
    summary: str
    metrics: Mapping[str, Any] = field(default_factory=dict)
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.verifier_id.strip():
            raise ValueError("verifier_id must not be empty")
        if not self.summary.strip():
            raise ValueError("verification summary must not be empty")

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "verifier_id": self.verifier_id,
            "summary": self.summary,
            "metrics": dict(self.metrics),
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class TickResult:
    continuation_id: str
    status: str
    detail: Mapping[str, Any] = field(default_factory=dict)
