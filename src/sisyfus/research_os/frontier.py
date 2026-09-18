from __future__ import annotations

from typing import Any

from .models import Candidate, FEATURES, digest, number


def ready_frontier(snapshot: dict[str, Any], *, max_attempts: int = 3) -> list[Candidate]:
    """A conservative, read-only projection of the existing evidence graph.

    Recheck CURRENT dependencies: admission at an old branch is insufficient.
    A scheduler never receives hidden-evaluation commands, criteria or evidence.
    """
    if snapshot["run_status"] != "ACTIVE":
        return []
    if any(a["status"] in {"RESERVED", "RUNNING"} for a in snapshot["attempts"].values()):
        return []
    budget = snapshot["budget"]
    if budget["attempts_remaining"] is not None and budget["attempts_remaining"] <= 0:
        return []
    ready = []
    for exp in snapshot["experiments"].values():
        if exp["status"] != "ADMITTED" or len(exp.get("attempt_ids", ())) >= max_attempts:
            continue
        contract = snapshot["contracts"].get(exp.get("contract_id"))
        if not contract or contract.get("kind") == "manual":
            continue
        if exp.get("visibility") == "host_only" or contract.get("visibility") == "host_only":
            continue
        if exp.get("mode") == "hidden_eval":
            continue
        targets = exp["target_claim_ids"]
        if targets != [contract["target_claim_id"]]:
            continue
        dependencies = set()
        for target in targets:
            dependencies.update(snapshot["claims"][target].get("depends_on", ()))
        if any(snapshot["claims"][d]["status"] != "SUPPORTED" or snapshot["claims"][d].get("contested") for d in dependencies):
            continue
        # Missing cited evidence is not a valid basis for execution.
        cited = exp.get("based_on", {}).get("evidence_ids", ())
        if any(e not in snapshot["evidence"] for e in cited):
            continue
        cost = number(exp["cost"]["units"])
        if budget["cost_units_remaining"] is not None and cost > budget["cost_units_remaining"]:
            continue
        features = tuple(number(exp["priority"].get(k, 0), maximum=1) for k in FEATURES)
        ready.append(Candidate(
            id=exp["id"], research_id=snapshot["research_id"],
            family=str(exp.get("metadata", {}).get("research_family") or exp["action_family"]),
            title=exp["title"], rationale=exp.get("rationale", ""), features=features,
            cost=cost, contract_hash=digest(contract), action_hash=digest(exp["action"]),
            requires=tuple(sorted(dependencies)),
        ))
    return sorted(ready, key=lambda x: x.id)
