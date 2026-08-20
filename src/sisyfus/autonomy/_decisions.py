from __future__ import annotations

from ._execution import ExecutionMixin
from ._experiences import ExperienceMixin
from ._reservation import ReservationMixin
from ._verdicts import VerdictMixin


class DecisionMixin(ReservationMixin, ExecutionMixin, VerdictMixin, ExperienceMixin):
    """Decision reservation, execution, verification and experience persistence."""
