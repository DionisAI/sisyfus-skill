"""Durable primitives for verifier-gated, continuously running agents.

The autonomy package is intentionally provider-neutral. Language models propose
bounded decisions; typed capabilities execute them; independent verifiers own
truth; :class:`AutonomyStore` owns durable state, leases and idempotency.
"""

from .models import (
    CapabilityResult,
    ContinuationState,
    Decision,
    DecisionAction,
    OpportunityProposal,
    RiskTier,
    TickResult,
    Verdict,
    VerificationResult,
)
from .store import AutonomyStore, ConcurrentUpdate, LeaseLost
from .policy import AutonomyPolicy, CapabilityRegistry, ContinuationContext
from .supervisor import Supervisor

__all__ = [
    "AutonomyPolicy",
    "AutonomyStore",
    "CapabilityRegistry",
    "CapabilityResult",
    "ConcurrentUpdate",
    "ContinuationContext",
    "ContinuationState",
    "Decision",
    "DecisionAction",
    "LeaseLost",
    "OpportunityProposal",
    "RiskTier",
    "Supervisor",
    "TickResult",
    "Verdict",
    "VerificationResult",
]
