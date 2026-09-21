"""Support-limited SOP evolution with fresh-trial promotion.

Only the retry limit is learnable in v1. Mandatory preflight gates remain fixed.
Replay can evaluate stricter limits from recorded trajectories, never unseen retries.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from ..research_v2.engine import ResearchEngine
from .controller import PREFIX, configuration, coordinator_lock, export_history
from .models import PREFLIGHT, SOP, digest, number
from .policy import SchedulingPolicy


def _ids(histories: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    ids, families = set(), set()
    for h in histories:
        if h.get("schema") != "sisyfus.replay.v1" or not h.get("research_id") or not h.get("family"):
            raise ValueError("invalid replay history")
        ids.add(h["research_id"])
        families.add(h["family"])
        ids |= set(h.get("source_research_ids", ()))
        families |= set(h.get("source_families", ()))
    return ids, families


def evaluate_sop(history: dict[str, Any], sop: SOP, *, budget: float) -> dict[str, Any]:
    """Chronological support-only evaluation of a stricter retry policy."""
    number(budget, minimum=0.000001)
    if history.get("schema") != "sisyfus.replay.v1" or history.get("support") != "recorded_actions_only":
        raise ValueError("unsupported replay history")
    reached, counts, cost, passes, selected = set(), {}, 0.0, 0, []
    nodes = history.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("history nodes required")
    for node in nodes:
        if not isinstance(node, dict) or set(node) < {"id", "candidate", "available_after", "outcome"}:
            raise ValueError("invalid replay node")
        cid = node["candidate"]["id"]
        if counts.get(cid, 0) >= sop.max_attempts_per_experiment:
            continue
        if any(parent not in reached for parent in node["available_after"]):
            continue
        outcome = node["outcome"]
        c = number(outcome["cost_units"])
        if cost + c > budget + 1e-12:
            continue
        label = outcome["label"]
        if label not in (0, 1) or isinstance(label, bool):
            raise ValueError("binary recorded label required")
        counts[cid] = counts.get(cid, 0) + 1
        reached.add(node["id"])
        selected.append(node["id"])
        cost += c
        passes += label
    return {"sop": sop.public(), "sop_hash": digest(sop.public()), "passes": passes,
            "cost_units": cost, "selected": selected, "support": "recorded_actions_only"}


def optimize_sop(train: list[dict[str, Any]], search: list[dict[str, Any]], holdout: list[dict[str, Any]], *, budget: float,
                 max_retry_candidate: int = 5) -> dict[str, Any]:
    """Select a retry limit on search; inspect holdout once; never activate it."""
    groups = [train, search, holdout]
    if any(not g for g in groups) or type(max_retry_candidate) is not int or not 1 <= max_retry_candidate <= 20:
        raise ValueError("nonempty splits and bounded retry search required")
    identities = [_ids(g) for g in groups]
    for i in range(3):
        for j in range(i):
            if identities[i][0] & identities[j][0] or identities[i][1] & identities[j][1]:
                raise ValueError("research IDs and task families must be disjoint across splits")
    # Train is provenance-only in v1: validate it so future learned SOP features cannot smuggle holdout data.
    for h in train:
        evaluate_sop(h, SOP(), budget=budget)
    candidates = [SOP(version=f"research-sop-retry-{n}", max_attempts_per_experiment=n) for n in range(1, max_retry_candidate + 1)]

    def score(sop: SOP, histories: list[dict[str, Any]]) -> dict[str, Any]:
        episodes = [evaluate_sop(h, sop, budget=budget) for h in histories]
        return {"sop": sop.public(), "sop_hash": digest(sop.public()), "episodes": episodes,
                "mean_passes": sum(e["passes"] for e in episodes) / len(episodes),
                "mean_cost": sum(e["cost_units"] for e in episodes) / len(episodes)}

    searched = [score(s, search) for s in candidates]
    best_i = max(range(len(candidates)), key=lambda i: (searched[i]["mean_passes"], -searched[i]["mean_cost"], -i))
    best = candidates[best_i]
    baseline = SOP()
    report = {"schema": "sisyfus.sop_candidate.v1", "status": "REPLAY_ONLY",
              "candidate": best.public(), "candidate_hash": digest(best.public()),
              "baseline": baseline.public(), "baseline_hash": digest(baseline.public()),
              "search_results": searched,
              "holdout": {"baseline": score(baseline, holdout), "candidate": score(best, holdout)},
              "source_research_ids": sorted(set.union(*(x[0] for x in identities))),
              "source_families": sorted(set.union(*(x[1] for x in identities))),
              "budget_units_per_episode": budget,
              "claim": "Replay-only stricter-retry result; fresh matched execution and operator review required."}
    report["report_hash"] = digest(report)
    return report


def _validate_report(report: dict[str, Any]) -> tuple[SOP, SOP]:
    raw = {k: v for k, v in report.items() if k != "report_hash"}
    if report.get("schema") != "sisyfus.sop_candidate.v1" or report.get("status") != "REPLAY_ONLY" or digest(raw) != report.get("report_hash"):
        raise ValueError("invalid SOP candidate report")
    baseline = SOP(**{**report["baseline"], "preflight_order": tuple(report["baseline"]["preflight_order"])})
    candidate = SOP(**{**report["candidate"], "preflight_order": tuple(report["candidate"]["preflight_order"])})
    if baseline.preflight_order != PREFLIGHT or candidate.preflight_order != PREFLIGHT:
        raise ValueError("mandatory preflight gates cannot change")
    if digest(baseline.public()) != report["baseline_hash"] or digest(candidate.public()) != report["candidate_hash"]:
        raise ValueError("SOP hash mismatch")
    return baseline, candidate


def record_sop_candidate(engine: ResearchEngine, report: dict[str, Any]) -> str:
    _validate_report(report)
    event = engine.workspace.append_event(PREFIX + "SOP_CANDIDATE", actor="sop-lab", data=report)
    return event["event_hash"]


def validate_sop_fresh_trials(report: dict[str, Any], baseline: list[ResearchEngine], challenger: list[ResearchEngine]) -> dict[str, Any]:
    baseline_sop, candidate_sop = _validate_report(report)
    if len(baseline) < 2 or len(baseline) != len(challenger):
        raise ValueError("at least two fresh matched pairs required")
    used = set(report["source_research_ids"])
    pairs = []
    for left, right in zip(baseline, challenger):
        pair = []
        for engine, expected_sop in ((left, baseline_sop), (right, candidate_sop)):
            if engine.workspace.research_id in used:
                raise ValueError("fresh trials must not reuse SOP-development episodes")
            used.add(engine.workspace.research_id)
            family = str(engine.task.get("metadata", {}).get("task_family") or engine.task["id"])
            if family in report["source_families"]:
                raise ValueError("fresh task family overlaps SOP development")
            cfg = configuration(engine)
            actual_sop = SOP(**{**cfg["sop"], "preflight_order": tuple(cfg["sop"]["preflight_order"])})
            if digest(actual_sop.public()) != digest(expected_sop.public()):
                raise ValueError("fresh trial SOP does not match frozen candidate")
            snap = engine.snapshot()
            if any(a["status"] in {"RESERVED", "RUNNING"} for a in snap["attempts"].values()):
                raise ValueError("unsettled fresh trial")
            history = export_history(engine)
            if not history["nodes"]:
                raise ValueError("fresh trial has no verifier-linked observations")
            decisions = [e["data"] for e in engine.events if e["event_type"] == PREFIX + "DECISION"]
            if any(d["sop_hash"] != digest(actual_sop.public()) or d["config_hash"] != cfg["config_hash"] for d in decisions):
                raise ValueError("mixed SOP/configuration in fresh trial")
            execution = {}
            for eid, approval in cfg["approvals"].items():
                exp = snap["experiments"][eid]
                action = {**exp["action"]}
                action["cwd"] = "$WORKSPACE"
                action["command"] = action["command"].replace(str(engine.workspace.root), "$WORKSPACE")
                execution[eid] = {"action": action, "code_hashes": approval["code_hashes"],
                                  "contract": approval["contract_hash"], "cost": exp["cost"],
                                  "priority": exp["priority"], "context_id": exp["context_id"]}
            pair.append({"research_id": engine.workspace.research_id,
                         "passes": sum(n["outcome"]["label"] for n in history["nodes"]),
                         "cost": sum(n["outcome"]["cost_units"] for n in history["nodes"]),
                         "task_contract_hash": digest({k: engine.task[k] for k in ("claims", "verification_contracts", "budget", "hard_constraints", "goal_graph", "stop_policy", "action_space")}),
                         "execution_hash": digest(execution),
                         "policy_hash": SchedulingPolicy.load(cfg["policy"]).hash,
                         "step_budgets": sorted({d["max_steps"] for d in decisions}),
                         "pair_id": engine.task.get("metadata", {}).get("evaluation_pair_id")})
        if not pair[0]["pair_id"] or pair[0]["pair_id"] != pair[1]["pair_id"]:
            raise ValueError("paired evaluation identity missing or mismatched")
        if pair[0]["task_contract_hash"] != pair[1]["task_contract_hash"] or pair[0]["execution_hash"] != pair[1]["execution_hash"]:
            raise ValueError("paired contracts or approved evaluator inputs differ")
        if pair[0]["policy_hash"] != pair[1]["policy_hash"] or pair[0]["step_budgets"] != pair[1]["step_budgets"] or len(pair[0]["step_budgets"]) != 1:
            raise ValueError("paired scheduling policies or execution budgets differ")
        pairs.append({"baseline": pair[0], "challenger": pair[1]})
    noninferior = all(p["challenger"]["passes"] >= p["baseline"]["passes"] and p["challenger"]["cost"] <= p["baseline"]["cost"] for p in pairs)
    improved = any(p["challenger"]["passes"] > p["baseline"]["passes"] or p["challenger"]["cost"] < p["baseline"]["cost"] for p in pairs)
    return {"eligible_for_operator_review": noninferior and improved, "pairs": pairs,
            "automatically_activated": False, "scope": "fresh_matched_sop_pilot_not_general_superiority"}


def promote_sop(engine: ResearchEngine, report: dict[str, Any], baseline: list[ResearchEngine], challenger: list[ResearchEngine], *, approver: str) -> dict[str, Any]:
    if not isinstance(approver, str) or not approver.strip():
        raise ValueError("named operator approval required")
    _, candidate = _validate_report(report)
    with coordinator_lock(engine):
        known = [e["data"] for e in engine.events if e["event_type"] == PREFIX + "SOP_CANDIDATE"]
        if not any(r.get("report_hash") == report.get("report_hash") for r in known):
            raise ValueError("SOP candidate must first be staged")
        trials = validate_sop_fresh_trials(report, baseline, challenger)
        if not trials["eligible_for_operator_review"]:
            raise ValueError("fresh pilot does not demonstrate a non-regressing SOP improvement")
        if any(a["status"] in {"RESERVED", "RUNNING"} for a in engine.snapshot()["attempts"].values()):
            raise ValueError("cannot activate SOP with unresolved work")
        cfg = {k: v for k, v in configuration(engine).items() if k != "config_hash"}
        cfg.update(sop=candidate.public(), actor=approver, fresh_sop_trials=trials)
        cfg["config_hash"] = digest(cfg)
        engine.workspace.append_event(PREFIX + "SOP_ACTIVATED", actor=approver, data=cfg)
        return {"activated": True, "sop_hash": report["candidate_hash"], "evidence": trials}
