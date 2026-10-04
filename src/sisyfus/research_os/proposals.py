from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, Callable

from ..autonomy.models import Decision, DecisionKind
from ..research_v2.engine import ResearchEngine
from ..research_v2.models import normalize_experiment
from .controller import PREFIX, coordinator_lock
from .models import digest


def propose_next(
    engine: ResearchEngine,
    planner: Callable[[dict[str, Any], dict[str, Any]], Decision],
    *,
    limit: int = 4,
) -> dict[str, Any]:
    """Reuse the existing proposal-only planner bridge; never execute its capability.

    The callable must return EXECUTE/research.propose with arguments.experiments.
    Code/contract authority is not delegated. New commands remain unapproved.
    Callers launching a local process must explicitly authorize that process and
    provide real OS isolation when it is untrusted.
    """
    if type(limit) is not int or not 1 <= limit <= 16:
        raise ValueError("proposal limit must be an integer in [1, 16]")
    with coordinator_lock(engine):
        snapshot = engine.snapshot()
        if snapshot["run_status"] != "ACTIVE":
            raise RuntimeError("cannot propose into a terminal or paused research run")
        if any(a["status"] in {"RESERVED", "RUNNING"} for a in snapshot["attempts"].values()):
            raise RuntimeError("reconcile unresolved execution before proposing")
        context = engine.planner_context()
        context["research_os"] = {
            "requested_capability": "research.propose",
            "max_experiments": limit,
            "rules": "Propose experiments only. Do not change contracts, evidence, permissions or execution state.",
        }
        continuation = {"id": engine.workspace.research_id, "version": len(engine.events)}
        before = engine.snapshot()["snapshot_hash"]
        started = time.monotonic()
        decision = planner(continuation, context).normalized()
        elapsed = time.monotonic() - started
        if engine.snapshot()["snapshot_hash"] != before:
            raise RuntimeError("research changed during proposal generation")
        if decision.kind != DecisionKind.EXECUTE.value or decision.capability != "research.propose":
            raise ValueError("planner may only propose research experiments, not execute or finish")
        raw = decision.arguments.get("experiments")
        if not isinstance(raw, list) or not 1 <= len(raw) <= limit:
            raise ValueError("invalid or oversized proposal batch")
        experiments = [normalize_experiment(e, known_claim_ids=set(snapshot["claims"]), known_contract_ids=set(snapshot["contracts"]), current_state_id=snapshot["current_state_id"]) for e in raw]
        ids = [e["id"] for e in experiments]
        if len(set(ids)) != len(ids) or set(ids) & set(snapshot["experiments"]):
            raise ValueError("proposal experiment IDs must be new and unique")
        if any(e["visibility"] == "host_only" or e["mode"] == "hidden_eval" for e in experiments):
            raise ValueError("planner cannot propose hidden evaluation work")
        engine.workspace.append_event(PREFIX + "PROPOSALS", actor="proposal-worker", data={
            "context_hash": digest(context), "decision": asdict(decision),
            "elapsed_seconds": elapsed, "provider_cost_usd": None,
            "authorization": "proposal_only_not_command_approval",
        })
        results = [engine.propose_experiment(e, actor="research-os-proposer")["admission"] for e in experiments]
        return {"proposed": ids, "admissions": results, "new_commands_approved": False,
                "elapsed_seconds": elapsed, "provider_cost_usd": None}
