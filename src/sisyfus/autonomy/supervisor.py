from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .discovery import OpportunityDiscovery, Sensor
from .models import TickResult, utc_now
from .policy import Planner
from .runtime import AutonomousRuntime


@dataclass(frozen=True)
class SupervisorConfig:
    worker_id: str = "sisyfus-supervisor"
    lease_seconds: float = 60.0
    idle_sleep_seconds: float = 1.0
    error_sleep_seconds: float = 5.0
    discovery_every_cycles: int = 1
    heartbeat_path: str | Path | None = None

    def __post_init__(self) -> None:
        if not self.worker_id.strip():
            raise ValueError("worker_id must not be empty")
        if self.lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if self.idle_sleep_seconds < 0 or self.error_sleep_seconds < 0:
            raise ValueError("sleep durations must be non-negative")
        if self.discovery_every_cycles < 1:
            raise ValueError("discovery_every_cycles must be positive")


@dataclass
class SupervisorStats:
    started_at: str
    cycles: int = 0
    active_cycles: int = 0
    idle_cycles: int = 0
    errors: int = 0
    consecutive_errors: int = 0
    last_cycle_at: str | None = None
    last_error: str | None = None


class AutonomousSupervisor:
    """Long-running service wrapper around the canonical runtime."""

    def __init__(
        self,
        runtime: AutonomousRuntime,
        *,
        planner: Planner,
        config: SupervisorConfig | None = None,
        discovery: OpportunityDiscovery | None = None,
        sensors: Sequence[Sensor] = (),
    ) -> None:
        self.runtime = runtime
        self.planner = planner
        self.config = config or SupervisorConfig()
        self.discovery = discovery
        self.sensors = tuple(sensors)
        self.stats = SupervisorStats(started_at=utc_now())

    def _write_heartbeat(self, payload: Mapping[str, Any]) -> None:
        if self.config.heartbeat_path is None:
            return
        path = Path(self.config.heartbeat_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(dict(payload), handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def cycle(self) -> dict[str, Any]:
        cycle_number = self.stats.cycles + 1
        discovery_result: dict[str, Any] | None = None
        if (
            self.discovery is not None
            and self.sensors
            and (cycle_number - 1) % self.config.discovery_every_cycles == 0
        ):
            discovery_result = self.discovery.scan_once(
                self.sensors,
                context={"worker_id": self.config.worker_id, "cycle": cycle_number},
            )
        work = self.runtime.run_once(
            worker_id=self.config.worker_id,
            planner=self.planner,
            lease_seconds=self.config.lease_seconds,
        )
        self.stats.cycles += 1
        self.stats.last_cycle_at = utc_now()
        self.stats.consecutive_errors = 0
        self.stats.last_error = None
        if work is None:
            self.stats.idle_cycles += 1
        else:
            self.stats.active_cycles += 1
        payload = {
            "status": "RUNNING",
            "worker_id": self.config.worker_id,
            "updated_at": self.stats.last_cycle_at,
            "stats": asdict(self.stats),
            "discovery": discovery_result,
            "work": work.as_dict() if isinstance(work, TickResult) else None,
        }
        self._write_heartbeat(payload)
        return payload

    def run_forever(
        self,
        *,
        stop_event: threading.Event | None = None,
        max_cycles: int | None = None,
    ) -> SupervisorStats:
        stop = stop_event or threading.Event()
        while not stop.is_set():
            if max_cycles is not None and self.stats.cycles >= int(max_cycles):
                break
            try:
                result = self.cycle()
                if result["work"] is None and self.config.idle_sleep_seconds:
                    stop.wait(self.config.idle_sleep_seconds)
            except BaseException as exc:
                self.stats.cycles += 1
                self.stats.errors += 1
                self.stats.consecutive_errors += 1
                self.stats.last_cycle_at = utc_now()
                self.stats.last_error = f"{type(exc).__name__}: {exc}"
                self._write_heartbeat(
                    {
                        "status": "ERROR",
                        "worker_id": self.config.worker_id,
                        "updated_at": self.stats.last_cycle_at,
                        "stats": asdict(self.stats),
                    }
                )
                if max_cycles is not None and self.stats.cycles >= int(max_cycles):
                    break
                if self.config.error_sleep_seconds:
                    stop.wait(self.config.error_sleep_seconds)
        self._write_heartbeat(
            {
                "status": "STOPPED",
                "worker_id": self.config.worker_id,
                "updated_at": utc_now(),
                "stats": asdict(self.stats),
            }
        )
        return self.stats


# Compatibility names for callers of the first draft.
Supervisor = AutonomousSupervisor
RuntimeStats = SupervisorStats
