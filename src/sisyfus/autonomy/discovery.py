from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .models import OpportunitySignal
from .store import AutonomyStore


@dataclass(frozen=True)
class SensorError:
    source: str
    item: str | None
    error_type: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "item": self.item,
            "type": self.error_type,
            "error": self.message,
        }


@dataclass(frozen=True)
class SensorScanResult:
    signals: Iterable[OpportunitySignal]
    errors: Sequence[SensorError] = field(default_factory=tuple)


class Sensor(Protocol):
    name: str

    def scan(self, context: Mapping[str, Any]) -> SensorScanResult | Iterable[OpportunitySignal]: ...


@dataclass(frozen=True)
class DiscoveryPolicy:
    min_priority: float = 0.0
    default_max_attempts: int = 8
    allowed_sources: frozenset[str] | None = None
    denied_sources: frozenset[str] = field(default_factory=frozenset)
    max_signals_per_sensor: int = 100

    def __post_init__(self) -> None:
        if self.default_max_attempts < 1:
            raise ValueError("default_max_attempts must be positive")
        if self.max_signals_per_sensor < 1:
            raise ValueError("max_signals_per_sensor must be positive")

    def evaluate(self, signal: OpportunitySignal) -> tuple[bool, str]:
        item = signal.normalized()
        if item.source in self.denied_sources:
            return False, "source_denied"
        if self.allowed_sources is not None and item.source not in self.allowed_sources:
            return False, "source_not_allowlisted"
        if item.priority < float(self.min_priority):
            return False, "priority_below_threshold"
        return True, "admitted"


class OpportunityDiscovery:
    def __init__(self, store: AutonomyStore, *, policy: DiscoveryPolicy | None = None) -> None:
        self.store = store
        self.policy = policy or DiscoveryPolicy()

    def scan_once(
        self,
        sensors: Sequence[Sensor],
        *,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        shared = dict(context or {})
        output: dict[str, Any] = {
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
                raw = sensor.scan(shared)
                if isinstance(raw, SensorScanResult):
                    iterable = raw.signals
                    output["errors"].extend(error.as_dict() for error in raw.errors)
                else:
                    iterable = raw
                bounded = list(
                    itertools.islice(iterable, int(self.policy.max_signals_per_sensor) + 1)
                )
                if len(bounded) > int(self.policy.max_signals_per_sensor):
                    output["errors"].append(
                        {
                            "source": sensor_name,
                            "item": None,
                            "type": "SensorLimitExceeded",
                            "error": (
                                f"sensor returned more than "
                                f"{self.policy.max_signals_per_sensor} signals"
                            ),
                        }
                    )
                    bounded = bounded[: int(self.policy.max_signals_per_sensor)]
            except BaseException as exc:
                output["errors"].append(
                    {
                        "source": sensor_name,
                        "item": None,
                        "type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                continue

            for raw_signal in bounded:
                try:
                    signal = raw_signal.normalized()
                    output["signal_count"] += 1
                    accepted, reason = self.policy.evaluate(signal)
                    if not accepted:
                        output["rejected_count"] += 1
                        output["items"].append(
                            {
                                "sensor": sensor_name,
                                "accepted": False,
                                "reason": reason,
                                "dedupe_key": signal.dedupe_key,
                            }
                        )
                        continue
                    opportunity, created = self.store.submit_opportunity(signal)
                    if created:
                        output["created_count"] += 1
                    else:
                        output["deduped_count"] += 1
                    continuation, admitted = self.store.admit_opportunity(
                        opportunity["id"],
                        max_attempts=int(
                            signal.max_attempts or self.policy.default_max_attempts
                        ),
                        context={
                            **dict(signal.context),
                            "discovered_by": sensor_name,
                            "signal_source": signal.source,
                        },
                    )
                    if admitted:
                        output["admitted_count"] += 1
                    output["items"].append(
                        {
                            "sensor": sensor_name,
                            "accepted": True,
                            "reason": reason,
                            "created": created,
                            "admitted": admitted,
                            "opportunity_id": opportunity["id"],
                            "continuation_id": continuation["id"],
                        }
                    )
                except BaseException as exc:
                    output["errors"].append(
                        {
                            "source": sensor_name,
                            "item": None,
                            "type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )
        return output
