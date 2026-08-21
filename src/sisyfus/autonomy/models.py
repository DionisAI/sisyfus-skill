from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum, StrEnum
from typing import Any, Mapping, Sequence


class OpportunityStatus(StrEnum):
    OPEN = "OPEN"
    ADMITTED = "ADMITTED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class ContinuationState(StrEnum):
    READY = "READY"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    EXHAUSTED = "EXHAUSTED"


class DecisionKind(StrEnum):
    EXECUTE = "EXECUTE"
    WAIT = "WAIT"
    FINISH = "FINISH"
    BLOCK = "BLOCK"
    CANCEL = "CANCEL"


# Compatibility alias for the first v0.8 draft API.
DecisionAction = DecisionKind


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    INVALID = "INVALID"
    ERROR = "ERROR"


class ExperiencePolarity(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    OPERATIONAL = "operational"


class RiskTier(IntEnum):
    R0 = 0
    R1 = 1
    R2 = 2
    R3 = 3
    R4 = 4


class AssuranceLevel(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    U = "U"


class VerificationMode(StrEnum):
    PROGRAMMATIC = "programmatic"
    HYBRID = "hybrid"
    MODEL_QUORUM = "model_quorum"
    HUMAN = "human"
    ENGINE = "engine"


TERMINAL_STATES = {
    ContinuationState.SUCCEEDED,
    ContinuationState.FAILED,
    ContinuationState.BLOCKED,
    ContinuationState.CANCELLED,
    ContinuationState.EXHAUSTED,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def finite_json(value: Any, *, path: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite number at {path}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            finite_json(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            finite_json(item, path=f"{path}[{index}]")


def canonical_json(value: Any) -> str:
    finite_json(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    )


def stable_id(prefix: str, *parts: Any, length: int = 24) -> str:
    material = "\x1f".join(canonical_json(part) for part in parts)
    digest = hashlib.sha256(material.encode("utf-8", errors="replace")).hexdigest()[:length]
    return f"{prefix}_{digest}"


def normalize_statement(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


@dataclass(frozen=True)
class OpportunitySignal:
    source: str
    title: str
    objective: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    kind: str = "research_need"
    priority: float = 0.0
    confidence: float = 0.5
    dedupe_key: str | None = None
    max_attempts: int | None = None
    context: Mapping[str, Any] = field(default_factory=dict)
    not_before: str | None = None
    expires_at: str | None = None

    def normalized(self) -> "OpportunitySignal":
        source = self.source.strip()
        title = self.title.strip()
        objective = self.objective.strip()
        kind = self.kind.strip() or "research_need"
        if not source:
            raise ValueError("opportunity source must not be empty")
        if not title:
            raise ValueError("opportunity title must not be empty")
        if not objective:
            raise ValueError("opportunity objective must not be empty")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("opportunity confidence must be between 0 and 1")
        if self.max_attempts is not None and int(self.max_attempts) < 1:
            raise ValueError("max_attempts must be positive")
        payload = dict(self.payload)
        context = dict(self.context)
        finite_json(payload)
        finite_json(context)
        return OpportunitySignal(
            source=source,
            title=title,
            objective=objective,
            payload=payload,
            kind=kind,
            priority=float(self.priority),
            confidence=float(self.confidence),
            dedupe_key=self.dedupe_key.strip() if self.dedupe_key else None,
            max_attempts=int(self.max_attempts) if self.max_attempts is not None else None,
            context=context,
            not_before=self.not_before,
            expires_at=self.expires_at,
        )


OpportunityProposal = OpportunitySignal


@dataclass(frozen=True)
class Decision:
    kind: DecisionKind | str
    reason: str
    capability: str | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)
    risk_tier: int | RiskTier = RiskTier.R0
    verifier_id: str = "default"
    idempotency_key: str | None = None
    evidence_id: str | None = None
    wait_seconds: float | None = None
    terminal_on_pass: bool = False
    experience_key: str | None = None
    experience_scope: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "Decision":
        raw_kind = self.kind.value if isinstance(self.kind, DecisionKind) else str(self.kind)
        kind = DecisionKind(raw_kind.upper())
        reason = self.reason.strip()
        if not reason:
            raise ValueError("decision reason must not be empty")
        if kind == DecisionKind.EXECUTE and not (self.capability or "").strip():
            raise ValueError("EXECUTE decision requires capability")
        if kind == DecisionKind.FINISH and not self.evidence_id:
            raise ValueError("FINISH decision requires verifier PASS evidence_id")
        if kind == DecisionKind.WAIT and self.wait_seconds is not None and float(self.wait_seconds) < 0:
            raise ValueError("wait_seconds must be non-negative")
        if kind != DecisionKind.EXECUTE and self.capability:
            raise ValueError(f"{kind.value} decision must not specify a capability")
        risk = int(self.risk_tier)
        if risk not in {0, 1, 2, 3, 4}:
            raise ValueError("risk_tier must be between 0 and 4")
        arguments = dict(self.arguments)
        scope = dict(self.experience_scope)
        finite_json(arguments)
        finite_json(scope)
        return Decision(
            kind=kind,
            reason=reason,
            capability=self.capability.strip() if self.capability else None,
            arguments=arguments,
            risk_tier=risk,
            verifier_id=self.verifier_id.strip() or "default",
            idempotency_key=self.idempotency_key.strip() if self.idempotency_key else None,
            evidence_id=self.evidence_id,
            wait_seconds=float(self.wait_seconds) if self.wait_seconds is not None else None,
            terminal_on_pass=bool(self.terminal_on_pass),
            experience_key=self.experience_key.strip() if self.experience_key else None,
            experience_scope=scope,
        )

    @property
    def action(self) -> DecisionKind:
        return self.normalized().kind  # compatibility

    @property
    def rationale(self) -> str:
        return self.reason

    def as_dict(self) -> dict[str, Any]:
        item = self.normalized()
        return {
            "kind": item.kind.value,
            "reason": item.reason,
            "capability": item.capability,
            "arguments": dict(item.arguments),
            "risk_tier": int(item.risk_tier),
            "verifier_id": item.verifier_id,
            "idempotency_key": item.idempotency_key,
            "evidence_id": item.evidence_id,
            "wait_seconds": item.wait_seconds,
            "terminal_on_pass": item.terminal_on_pass,
            "experience_key": item.experience_key,
            "experience_scope": dict(item.experience_scope),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Decision":
        return cls(
            kind=str(value.get("kind") or value.get("action") or ""),
            reason=str(value.get("reason") or value.get("rationale") or ""),
            capability=str(value["capability"]) if value.get("capability") is not None else None,
            arguments=dict(value.get("arguments") or {}),
            risk_tier=int(value.get("risk_tier") or 0),
            verifier_id=str(value.get("verifier_id") or "default"),
            idempotency_key=(
                str(value["idempotency_key"]) if value.get("idempotency_key") is not None else None
            ),
            evidence_id=str(value["evidence_id"]) if value.get("evidence_id") is not None else None,
            wait_seconds=float(value["wait_seconds"]) if value.get("wait_seconds") is not None else None,
            terminal_on_pass=bool(value.get("terminal_on_pass", False)),
            experience_key=(
                str(value["experience_key"]) if value.get("experience_key") is not None else None
            ),
            experience_scope=dict(value.get("experience_scope") or {}),
        ).normalized()

    def fingerprint(self) -> str:
        return stable_id("decision", self.as_dict(), length=32)


@dataclass(frozen=True)
class CapabilityResult:
    status: str
    observation: Mapping[str, Any] = field(default_factory=dict)
    metrics: Mapping[str, Any] = field(default_factory=dict)
    artifacts: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    error: str | None = None

    def normalized(self) -> "CapabilityResult":
        status = str(self.status).strip().upper()
        if not status:
            raise ValueError("capability result status must not be empty")
        observation = dict(self.observation)
        metrics = dict(self.metrics)
        artifacts = tuple(dict(item) for item in self.artifacts)
        finite_json(observation)
        finite_json(metrics)
        finite_json(artifacts)
        return CapabilityResult(status, observation, metrics, artifacts, self.error)

    def as_dict(self) -> dict[str, Any]:
        item = self.normalized()
        return {
            "status": item.status,
            "observation": dict(item.observation),
            "metrics": dict(item.metrics),
            "artifacts": [dict(entry) for entry in item.artifacts],
            "error": item.error,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CapabilityResult":
        return cls(
            status=str(value.get("status") or "ERROR"),
            observation=dict(value.get("observation") or {}),
            metrics=dict(value.get("metrics") or {}),
            artifacts=tuple(dict(item) for item in value.get("artifacts") or []),
            error=str(value["error"]) if value.get("error") is not None else None,
        ).normalized()


@dataclass(frozen=True)
class VerificationResult:
    verdict: Verdict | str
    verifier_id: str
    summary: str
    metrics: Mapping[str, Any] = field(default_factory=dict)
    evidence: Mapping[str, Any] = field(default_factory=dict)
    assurance: AssuranceLevel | str = AssuranceLevel.U
    verification_mode: VerificationMode | str = VerificationMode.PROGRAMMATIC
    lessons: Sequence["ExperienceLesson"] = field(default_factory=tuple)

    def normalized(self) -> "VerificationResult":
        verdict = self.verdict if isinstance(self.verdict, Verdict) else Verdict(str(self.verdict).upper())
        verifier_id = self.verifier_id.strip()
        summary = self.summary.strip()
        if not verifier_id:
            raise ValueError("verifier_id must not be empty")
        if not summary:
            raise ValueError("verification summary must not be empty")
        assurance_raw = self.assurance.value if isinstance(self.assurance, AssuranceLevel) else str(self.assurance)
        assurance_map = {
            "DETERMINISTIC": AssuranceLevel.A,
            "HYBRID": AssuranceLevel.B,
            "MODEL_QUORUM": AssuranceLevel.C,
            "HUMAN": AssuranceLevel.D,
            "UNKNOWN": AssuranceLevel.U,
        }
        assurance_key = assurance_raw.upper()
        assurance = assurance_map[assurance_key] if assurance_key in assurance_map else AssuranceLevel(assurance_key)
        mode_raw = self.verification_mode.value if isinstance(self.verification_mode, VerificationMode) else str(self.verification_mode)
        mode = VerificationMode(mode_raw.lower())
        metrics = dict(self.metrics)
        evidence = dict(self.evidence)
        finite_json(metrics)
        finite_json(evidence)
        return VerificationResult(
            verdict=verdict,
            verifier_id=verifier_id,
            summary=summary,
            metrics=metrics,
            evidence=evidence,
            assurance=assurance,
            verification_mode=mode,
            lessons=tuple(item.normalized() for item in self.lessons),
        )

    def as_dict(self) -> dict[str, Any]:
        item = self.normalized()
        return {
            "verdict": item.verdict.value,
            "verifier_id": item.verifier_id,
            "summary": item.summary,
            "metrics": dict(item.metrics),
            "evidence": dict(item.evidence),
            "assurance": item.assurance.value,
            "verification_mode": item.verification_mode.value,
            "lessons": [lesson.as_dict() for lesson in item.lessons],
        }


@dataclass(frozen=True)
class ExperienceLesson:
    pattern_key: str
    polarity: ExperiencePolarity | str
    claim: str
    scope: Mapping[str, Any] = field(default_factory=dict)
    confidence: float = 0.75
    outcome: str = "support"

    def normalized(self) -> "ExperienceLesson":
        pattern = self.pattern_key.strip()
        claim = self.claim.strip()
        if not pattern:
            raise ValueError("experience pattern_key must not be empty")
        if not claim:
            raise ValueError("experience claim must not be empty")
        polarity = self.polarity if isinstance(self.polarity, ExperiencePolarity) else ExperiencePolarity(str(self.polarity).lower())
        outcome = self.outcome.strip().lower()
        if outcome not in {"support", "counterexample"}:
            raise ValueError("experience outcome must be support or counterexample")
        confidence = max(0.0, min(1.0, float(self.confidence)))
        scope = dict(self.scope)
        finite_json(scope)
        return ExperienceLesson(pattern, polarity, claim, scope, confidence, outcome)

    def as_dict(self) -> dict[str, Any]:
        item = self.normalized()
        return {
            "pattern_key": item.pattern_key,
            "polarity": item.polarity.value,
            "claim": item.claim,
            "scope": dict(item.scope),
            "confidence": item.confidence,
            "outcome": item.outcome,
        }


@dataclass(frozen=True)
class TickResult:
    continuation_id: str
    state: str
    detail: Mapping[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return self.state

    def as_dict(self) -> dict[str, Any]:
        return {
            "continuation_id": self.continuation_id,
            "state": self.state,
            "status": self.state,
            "detail": dict(self.detail),
        }
