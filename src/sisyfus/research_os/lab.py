from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from ..research_v2.engine import ResearchEngine
from .controller import PREFIX, configuration, coordinator_lock, export_history
from .models import digest
from .policy import SchedulingPolicy, fit_policy
from .replay import evaluate_replay


def _identities(histories: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    ids = {h["research_id"] for h in histories}
    if len(ids) != len(histories):
        raise ValueError("duplicate research episode")
    return ids, {h["family"] for h in histories}


def optimize(train: list[dict[str, Any]], search: list[dict[str, Any]], holdout: list[dict[str, Any]], *, budget: float) -> dict[str, Any]:
    """Train on executed rows; select on search; inspect holdout exactly once.

    Baselines and learned policies receive the same replay budget. Returns an
    advisory candidate only, never an activated policy or production approval.
    """
    groups = [train, search, holdout]
    if any(not g for g in groups):
        raise ValueError("nonempty train, search and holdout episodes required")
    identities = [_identities(g) for g in groups]
    for i in range(3):
        for j in range(i):
            if identities[i][0] & identities[j][0] or identities[i][1] & identities[j][1]:
                raise ValueError("research IDs and task families must be disjoint across splits")
    rows = [{"candidate": n["candidate"], "label": n["outcome"]["label"]} for h in train for n in h["nodes"]]
    # Validate provenance, costs and labels before fitting, including unused data.
    for history in sum(groups, []):
        evaluate_replay(history, SchedulingPolicy(), budget=budget)
    learned = fit_policy(rows)
    fixed = SchedulingPolicy()
    fifo = SchedulingPolicy(name="fifo", selection="fifo")
    candidates = [fixed, fifo] + [replace(learned, name=f"learned-cost-{c}", cost_weight=c) for c in (0.0, 0.1, 0.2, 0.5)]

    def evaluate(policy: SchedulingPolicy, histories: list[dict[str, Any]]) -> dict[str, Any]:
        episodes = [evaluate_replay(h, policy, budget=budget) for h in histories]
        return {"policy": asdict(policy), "policy_hash": policy.hash, "episodes": episodes,
                "mean_passes": sum(e["passes"] for e in episodes) / len(episodes),
                "mean_cost": sum(e["cost_units"] for e in episodes) / len(episodes)}

    searched = [evaluate(p, search) for p in candidates]
    best_index = max(range(len(candidates)), key=lambda i: (searched[i]["mean_passes"], -searched[i]["mean_cost"], -i))
    best = candidates[best_index]
    report = {
        "schema": "sisyfus.policy_candidate.v1", "status": "REPLAY_ONLY",
        "candidate": asdict(best), "candidate_hash": best.hash,
        "baseline_hash": fixed.hash, "training_rows": len(rows),
        "feature_label": "PASS_under_recorded_contract_not_general_research_value",
        "search_results": searched,
        "holdout": {"fixed": evaluate(fixed, holdout), "fifo": evaluate(fifo, holdout), "candidate": evaluate(best, holdout)},
        "source_research_ids": sorted(set.union(*(i[0] for i in identities))),
        "source_families": sorted(set.union(*(i[1] for i in identities))),
        "budget_units_per_episode": budget,
        "claim": "Replay-only result; fresh matched execution and operator review required.",
    }
    report["report_hash"] = digest(report)
    return report


def record_candidate(engine: ResearchEngine, report: dict[str, Any]) -> str:
    copy = {k: v for k, v in report.items() if k != "report_hash"}
    if digest(copy) != report.get("report_hash") or report.get("status") != "REPLAY_ONLY":
        raise ValueError("invalid candidate report")
    if SchedulingPolicy.load(report["candidate"]).hash != report["candidate_hash"]:
        raise ValueError("candidate policy hash mismatch")
    event = engine.workspace.append_event(PREFIX + "POLICY_CANDIDATE", actor="policy-lab", data=report)
    return event["event_hash"]


def validate_fresh_trials(report: dict[str, Any], baseline: list[ResearchEngine], challenger: list[ResearchEngine]) -> dict[str, Any]:
    """Check real engine ledgers, not a supplied boolean 'online_passed'.

    This is a small deterministic pilot gate, not statistical proof of general
    superiority. No policy automatically becomes active when it passes.
    """
    if report.get("status") != "REPLAY_ONLY" or digest({k: v for k, v in report.items() if k != "report_hash"}) != report.get("report_hash"):
        raise ValueError("candidate report hash mismatch")
    if SchedulingPolicy.load(report["candidate"]).hash != report["candidate_hash"]:
        raise ValueError("candidate hash mismatch")
    if len(baseline) < 2 or len(baseline) != len(challenger):
        raise ValueError("at least two fresh matched pairs required")
    used = set(report["source_research_ids"])
    pairs = []
    for left, right in zip(baseline, challenger):
        configs = [configuration(left), configuration(right)]
        if SchedulingPolicy.load(configs[0]["policy"]).hash != report["baseline_hash"] or SchedulingPolicy.load(configs[1]["policy"]).hash != report["candidate_hash"]:
            raise ValueError("trial policy hashes do not match the frozen candidate")
        tasks = [left.task, right.task]
        manifests = []
        outcomes = []
        execution_manifests = []
        step_budgets = []
        for engine, task, cfg in zip((left, right), tasks, configs):
            if engine.workspace.research_id in used:
                raise ValueError("fresh trials must not reuse historical or paired episodes")
            used.add(engine.workspace.research_id)
            if task.get("metadata", {}).get("task_family") in report["source_families"]:
                raise ValueError("fresh task family overlaps policy development")
            snapshot = engine.snapshot()
            if any(a["status"] in {"RESERVED", "RUNNING"} for a in snapshot["attempts"].values()):
                raise ValueError("unsettled trial is not promotion evidence")
            history = export_history(engine)
            if not history["nodes"]:
                raise ValueError("trial contains no executed, verifier-linked observations")
            manifests.append(digest({k: task[k] for k in ("claims", "verification_contracts", "budget", "hard_constraints", "goal_graph", "stop_policy", "action_space")}))
            execution = {}
            for eid, approval in cfg["approvals"].items():
                exp = snapshot["experiments"][eid]
                action = {**exp["action"]}
                action["cwd"] = "$WORKSPACE"
                action["command"] = action["command"].replace(str(engine.workspace.root), "$WORKSPACE")
                execution[eid] = {"action": action, "code_hashes": approval["code_hashes"], "cost": exp["cost"], "contract": approval["contract_hash"], "priority": exp["priority"], "based_on": exp.get("based_on"), "context_id": exp["context_id"], "metadata": exp.get("metadata")}
            execution_manifests.append(digest({"experiments": execution, "sop": cfg["sop"]}))
            decisions = [e["data"] for e in engine.events if e["event_type"] == PREFIX + "DECISION"]
            if {d["policy_hash"] for d in decisions} != {SchedulingPolicy.load(cfg["policy"]).hash}:
                raise ValueError("mixed-policy trial")
            if any(d["config_hash"] != cfg["config_hash"] or d["sop_hash"] != digest(cfg["sop"]) for d in decisions):
                raise ValueError("mixed configuration or SOP in fresh trial")
            step_budgets.append({d["max_steps"] for d in decisions})
            outcomes.append({"research_id": engine.workspace.research_id, "event_head": history["source_event_head"],
                             "passes": sum(n["outcome"]["label"] for n in history["nodes"]),
                             "cost": sum(n["outcome"]["cost_units"] for n in history["nodes"])})
        if execution_manifests[0] != execution_manifests[1] or step_budgets[0] != step_budgets[1] or len(step_budgets[0]) != 1:
            raise ValueError("paired evaluator inputs, SOPs or execution budgets differ")
        if manifests[0] != manifests[1]:
            raise ValueError("paired task contracts or budgets differ")
        if not tasks[0].get("metadata", {}).get("evaluation_pair_id") or tasks[0]["metadata"]["evaluation_pair_id"] != tasks[1].get("metadata", {}).get("evaluation_pair_id"):
            raise ValueError("paired evaluation identity missing or mismatched")
        pairs.append({"baseline": outcomes[0], "challenger": outcomes[1]})
    noninferior = all(p["challenger"]["passes"] >= p["baseline"]["passes"] and p["challenger"]["cost"] <= p["baseline"]["cost"] for p in pairs)
    improved = any(p["challenger"]["passes"] > p["baseline"]["passes"] or p["challenger"]["cost"] < p["baseline"]["cost"] for p in pairs)
    return {"eligible_for_operator_review": noninferior and improved, "pairs": pairs,
            "automatically_activated": False, "scope": "fresh_matched_pilot_not_general_superiority"}


def promote(engine: ResearchEngine, report: dict[str, Any], baseline: list[ResearchEngine], challenger: list[ResearchEngine], *, approver: str) -> dict[str, Any]:
    """Explicit operator promotion; preserve every current approval and SOP gate."""
    if not approver.strip():
        raise ValueError("named operator approval required")
    with coordinator_lock(engine):
        known = [e["data"] for e in engine.events if e["event_type"] == PREFIX + "POLICY_CANDIDATE"]
        if not any(r.get("report_hash") == report.get("report_hash") for r in known):
            raise ValueError("candidate must first be staged in the research ledger")
        trials = validate_fresh_trials(report, baseline, challenger)
        if not trials["eligible_for_operator_review"]:
            raise ValueError("fresh pilot does not demonstrate a non-regressing improvement")
        if any(a["status"] in {"RESERVED", "RUNNING"} for a in engine.snapshot()["attempts"].values()):
            raise ValueError("cannot activate with unresolved work")
        cfg = {k: v for k, v in configuration(engine).items() if k != "config_hash"}
        cfg.update(policy=report["candidate"], actor=approver, fresh_trials=trials)
        cfg["config_hash"] = digest(cfg)
        engine.workspace.append_event(PREFIX + "POLICY_ACTIVATED", actor=approver, data=cfg)
        return {"activated": True, "policy_hash": report["candidate_hash"], "evidence": trials}
