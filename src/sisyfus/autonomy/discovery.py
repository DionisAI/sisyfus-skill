from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .runtime import AutonomyStore


@dataclass(frozen=True)
class OpportunitySignal:
    """A sensor observation that may justify a new autonomous continuation."""

    source: str
    title: str
    objective: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    priority: float = 0.0
    dedupe_key: str | None = None
    max_attempts: int | None = None
    context: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "OpportunitySignal":
        source = self.source.strip()
        title = self.title.strip()
        objective = self.objective.strip()
        if not source:
            raise ValueError("opportunity signal source must not be empty")
        if not title:
            raise ValueError("opportunity signal title must not be empty")
        if not objective:
            raise ValueError("opportunity signal objective must not be empty")
        if self.max_attempts is not None and int(self.max_attempts) < 1:
            raise ValueError("max_attempts must be positive")
        return OpportunitySignal(
            source=source,
            title=title,
            objective=objective,
            payload=dict(self.payload),
            priority=float(self.priority),
            dedupe_key=self.dedupe_key,
            max_attempts=self.max_attempts,
            context=dict(self.context),
        )


class Sensor(Protocol):
    name: str

    def scan(self, context: Mapping[str, Any]) -> Iterable[OpportunitySignal]: ...


@dataclass(frozen=True)
class DiscoveryPolicy:
    """Deterministic admission policy applied after sensor discovery."""

    min_priority: float = 0.0
    default_max_attempts: int = 8
    allowed_sources: frozenset[str] | None = None
    denied_sources: frozenset[str] = frozenset()
    max_signals_per_sensor: int = 100

    def evaluate(self, signal: OpportunitySignal) -> tuple[bool, str]:
        if signal.source in self.denied_sources:
            return False, "source_denied"
        if self.allowed_sources is not None and signal.source not in self.allowed_sources:
            return False, "source_not_allowlisted"
        if signal.priority < float(self.min_priority):
            return False, "priority_below_threshold"
        return True, "admitted"


class OpportunityDiscovery:
    """Runs sensors, deduplicates signals, and admits bounded continuations."""

    def __init__(self, store: AutonomyStore, *, policy: DiscoveryPolicy | None = None) -> None:
        self.store = store
        self.policy = policy or DiscoveryPolicy()

    def scan_once(
        self,
        sensors: Sequence[Sensor],
        *,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        shared_context = dict(context or {})
        result: dict[str, Any] = {
            "sensor_count": len(sensors),
            "signal_count": 0,
            "created_count": 0,
            "deduped_count": 0,
            "admitted_count": 0,
            "rejected_count": 0,
            "errors": [],
            "items": [],
        }
        for sensor in sensors:
            sensor_name = str(getattr(sensor, "name", type(sensor).__name__))
            try:
                raw_signals = sensor.scan(shared_context)
                signals = list(raw_signals)
            except Exception as exc:  # sensor failures are observations, not supervisor crashes
                result["errors"].append(
                    {"sensor": sensor_name, "type": type(exc).__name__, "error": str(exc)}
                )
                continue
            if len(signals) > int(self.policy.max_signals_per_sensor):
                result["errors"].append(
                    {
                        "sensor": sensor_name,
                        "type": "SensorLimitExceeded",
                        "error": (
                            f"sensor returned {len(signals)} signals; "
                            f"limit is {self.policy.max_signals_per_sensor}"
                        ),
                    }
                )
                signals = signals[: int(self.policy.max_signals_per_sensor)]
            for raw_signal in signals:
                try:
                    signal = raw_signal.normalized()
                    result["signal_count"] += 1
                    opportunity, created = self.store.submit_opportunity(
                        source=signal.source,
                        title=signal.title,
                        objective=signal.objective,
                        payload=signal.payload,
                        priority=signal.priority,
                        dedupe_key=signal.dedupe_key,
                    )
                    if created:
                        result["created_count"] += 1
                    else:
                        result["deduped_count"] += 1
                    accepted, reason = self.policy.evaluate(signal)
                    item: dict[str, Any] = {
                        "sensor": sensor_name,
                        "opportunity_id": opportunity["id"],
                        "created": created,
                        "accepted": accepted,
                        "reason": reason,
                    }
                    if accepted:
                        continuation = self.store.admit_opportunity(
                            opportunity["id"],
                            max_attempts=int(signal.max_attempts or self.policy.default_max_attempts),
                            context={
                                **dict(signal.context),
                                "discovered_by": sensor_name,
                                "signal_source": signal.source,
                            },
                        )
                        item["continuation_id"] = continuation["id"]
                        result["admitted_count"] += 1
                    else:
                        result["rejected_count"] += 1
                    result["items"].append(item)
                except Exception as exc:
                    result["errors"].append(
                        {"sensor": sensor_name, "type": type(exc).__name__, "error": str(exc)}
                    )
        return result
