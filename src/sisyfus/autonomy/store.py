from __future__ import annotations

from ._common import (
    AutonomyStoreError,
    ConcurrentUpdate,
    InvalidTransition,
    LeaseLost,
)
from ._database import StoreCore
from ._decisions import DecisionMixin
from ._leases import LeaseMixin
from ._opportunities import OpportunityMixin
from ._views import ViewMixin


class AutonomyStore(
    OpportunityMixin,
    LeaseMixin,
    DecisionMixin,
    ViewMixin,
    StoreCore,
):
    """Durable autonomy state, leases, idempotency, evidence and experience."""


__all__ = [
    "AutonomyStore",
    "AutonomyStoreError",
    "ConcurrentUpdate",
    "InvalidTransition",
    "LeaseLost",
]
