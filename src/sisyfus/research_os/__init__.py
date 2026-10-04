"""Budgeted research control over the existing Sisyfus evidence engine.

Judgments and replay are advisory. ResearchEngine remains the truth owner.
"""

from .controller import ResearchOS
from .policy import SchedulingPolicy

__all__ = ["ResearchOS", "SchedulingPolicy"]
