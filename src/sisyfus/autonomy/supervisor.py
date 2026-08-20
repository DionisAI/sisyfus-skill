from __future__ import annotations

from dataclasses import dataclass, field

from ._supervisor_drive import DriveMixin
from ._supervisor_execute import ExecuteMixin
from ._supervisor_finish import FinishMixin
from ._supervisor_settlement import SettlementMixin
from ._supervisor_simple import SimpleActionMixin
from .models import TickResult, utc_now
from .policy import AutonomyPolicy, CapabilityRegistry, Planner, Verifier
from .store import AutonomyStore


@dataclass
class Supervisor(DriveMixin, SimpleActionMixin, ExecuteMixin, FinishMixin, SettlementMixin):
    store: AutonomyStore
    planner: Planner
    verifier: Verifier
    capabilities: CapabilityRegistry
    policy: AutonomyPolicy = field(default_factory=AutonomyPolicy)
    worker_id: str = "sisyfus-supervisor"
    lease_seconds: int = 60
    retry_base_seconds: int = 5
    retry_max_seconds: int = 300

    def tick(self, *, limit: int = 1, now: str | None = None) -> list[TickResult]:
        if int(limit) <= 0:
            return []
        now = now or utc_now()
        self.store.recover_expired_leases(now=now, retry_delay_seconds=self.retry_base_seconds)
        results: list[TickResult] = []
        for _ in range(int(limit)):
            continuation = self.store.claim_due_continuation(
                self.worker_id,
                lease_seconds=self.lease_seconds,
                now=now,
            )
            if continuation is None:
                break
            results.append(self._drive(continuation, now=now))
        return results
