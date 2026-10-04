from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

from .models import Candidate, number
from .policy import SchedulingPolicy


class UnsupportedAction(ValueError):
    """The recorded history has no compatible outcome for this action."""


class ReplayWorld:
    """Support-limited replay. Never exposes outcomes through the policy view.

    This is a local API boundary, NOT an adversarial Python sandbox. Generated
    policy code must not run in-process with access to the archive.
    """

    def __init__(self, history: dict[str, Any], *, budget: float):
        if history.get("schema") != "sisyfus.replay.v1":
            raise ValueError("unsupported replay schema")
        self._nodes = {n["id"]: deepcopy(n) for n in history["nodes"]}
        if len(self._nodes) != len(history["nodes"]):
            raise ValueError("duplicate replay node")
        self.remaining = number(budget)
        self.initial_budget = self.remaining
        self.reached: set[str] = set()
        self.observations: list[dict[str, Any]] = []
        for node in self._nodes.values():
            candidate = Candidate.load(node["candidate"])
            outcome = node["outcome"]
            if outcome["verdict"] not in {"PASS", "FAIL", "INCONCLUSIVE", "INVALID", "ERROR"}:
                raise ValueError("unsupported verdict")
            if outcome["label"] != int(outcome["verdict"] == "PASS"):
                raise ValueError("label disagrees with verifier verdict")
            if number(outcome["cost_units"]) != candidate.cost:
                raise ValueError("replay cost disagrees with recorded reservation")
            if set(node["available_after"]) - self._nodes.keys():
                raise ValueError("unknown replay parent")
            if not outcome.get("evidence_id") or not outcome.get("evidence_hash"):
                raise ValueError("replay needs evidence provenance")
        pending = set(self._nodes)
        seen: set[str] = set()
        while pending:
            ready = {i for i in pending if set(self._nodes[i]["available_after"]) <= seen}
            if not ready:
                raise ValueError("replay dependency cycle")
            pending -= ready
            seen |= ready

    def view(self) -> tuple[Candidate, ...]:
        return tuple(replace(Candidate.load(n["candidate"]), id=i) for i, n in sorted(self._nodes.items())
                     if i not in self.reached and set(n["available_after"]) <= self.reached
                     and n["candidate"]["cost"] <= self.remaining)

    def step(self, action_id: str) -> dict[str, Any]:
        if action_id not in self._nodes:
            raise UnsupportedAction("unrecorded action: new execution is required")
        if action_id not in {a.id for a in self.view()}:
            raise UnsupportedAction("unavailable, already consumed, or over-budget action")
        node = self._nodes[action_id]
        outcome = deepcopy(node["outcome"])
        self.remaining -= outcome["cost_units"]
        self.reached.add(action_id)
        self.observations.append({"id": action_id, **outcome})
        return outcome


def evaluate_replay(history: dict[str, Any], policy: SchedulingPolicy, *, budget: float) -> dict[str, Any]:
    if policy.judgment_weight:
        raise ValueError("replay cannot invent uncached counterfactual judge outputs")
    world = ReplayWorld(history, budget=budget)
    while world.view():
        action = policy.rank(world.view())[0]
        world.step(action.id)
    return {
        "research_id": history["research_id"], "family": history["family"],
        "policy_hash": policy.hash, "budget": budget,
        "cost_units": world.initial_budget - world.remaining,
        "passes": sum(o["verdict"] == "PASS" for o in world.observations),
        "valid_resolutions": sum(o["verdict"] in {"PASS", "FAIL"} for o in world.observations),
        "attempts": len(world.observations), "order": [o["id"] for o in world.observations],
        "scope": "recorded_support_only_not_counterfactual_proof",
    }
