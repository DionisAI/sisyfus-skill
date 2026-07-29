from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from .models import SNAPSHOT_SCHEMA_VERSION, canonical_hash


def _minutes_between(start: str | None, end: str | None) -> float:
    if not start or not end:
        return 0.0
    try:
        start_dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (end_dt - start_dt).total_seconds() / 60.0)


def _claim_map(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for claim in task.get("claims") or []:
        result[claim["id"]] = {
            **copy.deepcopy(claim),
            "status": "OPEN",
            "evidence_ids": [],
            "verdict_event_ids": [],
            "invalidated_by": [],
            "provisional_passes": 0,
            "last_updated_seq": 0,
        }
    return result


def _contract_map(task: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: copy.deepcopy(item) for item in task.get("verification_contracts") or []}


def _merge_statuses(statuses: list[str]) -> str:
    clean = [str(x or "OPEN") for x in statuses]
    if "REFUTED" in clean:
        return "REFUTED"
    if "SUPPORTED" in clean:
        return "SUPPORTED"
    if "INVALIDATED" in clean:
        return "INVALIDATED"
    if "INCONCLUSIVE" in clean:
        return "INCONCLUSIVE"
    return "OPEN"


def _dependent_claims(claims: dict[str, dict[str, Any]], claim_id: str) -> list[str]:
    return [cid for cid, claim in claims.items() if claim_id in (claim.get("depends_on") or [])]


def _propagate_invalidation(
    statuses: dict[str, str],
    claims: dict[str, dict[str, Any]],
    refuted_claim_id: str,
) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    queue = [refuted_claim_id]
    visited: set[str] = set()
    while queue:
        source = queue.pop(0)
        if source in visited:
            continue
        visited.add(source)
        for dependent in _dependent_claims(claims, source):
            old = statuses.get(dependent, "OPEN")
            if old != "REFUTED" and old != "INVALIDATED":
                statuses[dependent] = "INVALIDATED"
                changes.append({"claim_id": dependent, "source_claim_id": source, "previous_status": old})
            queue.append(dependent)
    return changes


def _state_payload(statuses: dict[str, str], evidence: dict[str, list[str]], budgets: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_statuses": dict(sorted(statuses.items())),
        "claim_evidence": {key: sorted(value) for key, value in sorted(evidence.items())},
        "budget": {
            "attempts_committed": budgets.get("attempts_committed", 0),
            "cost_units_used": budgets.get("cost_units_used", 0.0),
        },
    }


def _new_state(
    *,
    seq: int,
    parent_state_ids: list[str],
    statuses: dict[str, str],
    evidence: dict[str, list[str]],
    budgets: dict[str, Any],
    verdict_event_id: str | None,
    experiment_id: str | None,
    rollback: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    payload = _state_payload(statuses, evidence, budgets)
    digest = canonical_hash(payload).split(":", 1)[-1]
    return {
        "id": f"state-{seq:06d}-{digest[:10]}",
        "seq": seq,
        "parent_state_ids": list(dict.fromkeys(parent_state_ids)),
        "claim_statuses": copy.deepcopy(statuses),
        "claim_evidence": copy.deepcopy(evidence),
        "state_hash": f"sha256:{digest}",
        "verdict_event_id": verdict_event_id,
        "experiment_id": experiment_id,
        "rollback": rollback or [],
    }


def _goal_status(task: dict[str, Any], statuses: dict[str, str]) -> dict[str, Any]:
    graph = task["goal_graph"]
    nodes = {item["id"]: item for item in graph["nodes"]}
    cache: dict[str, str] = {}
    visiting: set[str] = set()

    def visit(node_id: str) -> str:
        if node_id in cache:
            return cache[node_id]
        if node_id in visiting:
            cache[node_id] = "INVALID"
            return "INVALID"
        visiting.add(node_id)
        node = nodes[node_id]
        kind = node["kind"]
        if kind == "CLAIM":
            claim_status = statuses.get(node["claim_id"], "OPEN")
            if claim_status == "SUPPORTED":
                value = "PASS"
            elif claim_status == "REFUTED":
                value = "FAIL"
            else:
                value = "OPEN"
        else:
            child_values = [visit(child) for child in node.get("children") or []]
            if kind == "AND":
                if any(x in {"FAIL", "INVALID"} for x in child_values):
                    value = "FAIL"
                elif child_values and all(x == "PASS" for x in child_values):
                    value = "PASS"
                else:
                    value = "OPEN"
            else:  # OR
                if any(x == "PASS" for x in child_values):
                    value = "PASS"
                elif child_values and all(x in {"FAIL", "INVALID"} for x in child_values):
                    value = "FAIL"
                else:
                    value = "OPEN"
        visiting.remove(node_id)
        cache[node_id] = value
        return value

    root_status = visit(graph["root_id"])
    enriched = []
    for node in graph["nodes"]:
        enriched.append({**copy.deepcopy(node), "status": cache.get(node["id"]) or visit(node["id"])})
    return {"root_id": graph["root_id"], "root_status": root_status, "nodes": enriched}


def _progress(task: dict[str, Any], statuses: dict[str, str]) -> dict[str, float]:
    required = [claim for claim in task.get("claims") or [] if claim.get("required", True)]
    total = sum(max(0.0, float(claim.get("weight") or 0.0)) for claim in required) or 1.0
    objective = sum(
        max(0.0, float(claim.get("weight") or 0.0))
        for claim in required
        if statuses.get(claim["id"]) == "SUPPORTED"
    )
    resolved = sum(
        max(0.0, float(claim.get("weight") or 0.0))
        for claim in required
        if statuses.get(claim["id"]) in {"SUPPORTED", "REFUTED"}
    )
    return {
        "objective": round(100.0 * objective / total, 2),
        "epistemic": round(100.0 * resolved / total, 2),
    }


def _planner_gap(task: dict[str, Any], claims: dict[str, dict[str, Any]], contracts: dict[str, dict[str, Any]]) -> list[str]:
    covered = {contract.get("target_claim_id") for contract in contracts.values()}
    return [
        claim_id
        for claim_id, claim in claims.items()
        if claim.get("required", True)
        and claim.get("status") not in {"SUPPORTED", "REFUTED"}
        and claim_id not in covered
    ]


def reduce_research(task: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    claims = _claim_map(task)
    contracts = _contract_map(task)
    experiments: dict[str, dict[str, Any]] = {}
    attempts: dict[str, dict[str, Any]] = {}
    evidence: dict[str, dict[str, Any]] = {}
    lessons: dict[str, dict[str, Any]] = {}
    run_status = "CREATED"
    explicit_status: str | None = None
    created_at = events[0]["ts"] if events else None
    last_event = events[-1] if events else None
    budgets = {
        **copy.deepcopy(task["budget"]),
        "attempts_reserved": 0,
        "attempts_committed": 0,
        "infra_error_attempts": 0,
        "cost_units_used": 0.0,
    }
    initial_statuses = {claim_id: "OPEN" for claim_id in claims}
    initial_evidence = {claim_id: [] for claim_id in claims}
    initial_state = _new_state(
        seq=0,
        parent_state_ids=[],
        statuses=initial_statuses,
        evidence=initial_evidence,
        budgets=budgets,
        verdict_event_id=None,
        experiment_id=None,
    )
    states: dict[str, dict[str, Any]] = {initial_state["id"]: initial_state}
    current_state_id = initial_state["id"]
    frontier: set[str] = set()
    recent_rollbacks: list[dict[str, Any]] = []
    # cross-branch contradiction accounting: every REFUTED effect and every PASS
    # verdict is recorded for the claim regardless of which branch it lives on
    claim_refute_records: dict[str, list[dict[str, Any]]] = {}
    claim_pass_records: dict[str, list[dict[str, Any]]] = {}

    for event in events:
        event_type = event["event_type"]
        data = event.get("data") or {}
        seq = int(event.get("seq") or 0)
        if event_type == "RUN_CREATED":
            run_status = "ACTIVE"
        elif event_type == "CONTRACT_ADDED":
            contract = copy.deepcopy(data["contract"])
            contracts[contract["id"]] = contract
        elif event_type == "EXPERIMENT_PROPOSED":
            experiment = copy.deepcopy(data["experiment"])
            experiment.update(
                {
                    "status": "PROPOSED",
                    "created_at": event["ts"],
                    "created_event_id": event["event_id"],
                    "attempt_ids": [],
                    "to_state_ids": [],
                    "last_verdict": None,
                }
            )
            experiments[experiment["id"]] = experiment
        elif event_type == "EXPERIMENT_ADMITTED":
            experiment_id = data["experiment_id"]
            if experiment_id in experiments:
                experiments[experiment_id]["admission"] = copy.deepcopy(data.get("admission") or {})
                wait = experiments[experiment_id].get("wait")
                if wait:
                    wait["status"] = "PENDING"
                    wait["admitted_seq"] = seq
                    experiments[experiment_id]["status"] = "WAITING"
                    frontier.discard(experiment_id)
                else:
                    experiments[experiment_id]["status"] = "ADMITTED"
                    frontier.add(experiment_id)
        elif event_type == "EXPERIMENT_BACKLOGGED":
            experiment_id = data["experiment_id"]
            if experiment_id in experiments:
                experiments[experiment_id]["status"] = "BACKLOG"
                experiments[experiment_id]["backlog_reason"] = data.get("reason")
                frontier.discard(experiment_id)
        elif event_type == "EXPERIMENT_PRUNED":
            experiment_id = data["experiment_id"]
            if experiment_id in experiments:
                experiments[experiment_id]["status"] = "PRUNED"
                experiments[experiment_id]["prune_reason"] = data.get("reason")
                frontier.discard(experiment_id)
        elif event_type == "ATTEMPT_RESERVED":
            attempt = copy.deepcopy(data["attempt"])
            attempt.update(
                {
                    "status": "RESERVED",
                    "reserved_at": event["ts"],
                    "reserved_event_id": event["event_id"],
                    "observation": None,
                    "verdict": None,
                }
            )
            attempts[attempt["id"]] = attempt
            budgets["attempts_reserved"] += 1
            experiment_id = attempt["experiment_id"]
            if experiment_id in experiments:
                experiments[experiment_id]["status"] = "RESERVED"
                experiments[experiment_id]["attempt_ids"].append(attempt["id"])
                frontier.discard(experiment_id)
        elif event_type == "ATTEMPT_STARTED":
            attempt_id = data["attempt_id"]
            if attempt_id in attempts:
                attempts[attempt_id]["status"] = "RUNNING"
                attempts[attempt_id]["started_at"] = event["ts"]
                experiment_id = attempts[attempt_id]["experiment_id"]
                if experiment_id in experiments:
                    experiments[experiment_id]["status"] = "RUNNING"
        elif event_type == "OBSERVATION_RECORDED":
            attempt_id = data["attempt_id"]
            if attempt_id in attempts:
                attempts[attempt_id]["observation"] = copy.deepcopy(data.get("observation") or {})
                attempts[attempt_id]["observation_event_id"] = event["event_id"]
        elif event_type == "VERDICT_ISSUED":
            attempt_id = data["attempt_id"]
            experiment_id = data["experiment_id"]
            verdict = copy.deepcopy(data["verdict"])
            verdict["event_id"] = event["event_id"]
            verdict["issued_at"] = event["ts"]
            evidence_item = copy.deepcopy(data.get("evidence") or {})
            evidence_id = evidence_item.get("id")
            if evidence_id:
                evidence_item.update(
                    {
                        "verdict_status": verdict["status"],
                        "experiment_id": experiment_id,
                        "attempt_id": attempt_id,
                        "created_at": event["ts"],
                        "visibility": event.get("visibility", "normal"),
                    }
                )
                evidence[evidence_id] = evidence_item

            attempt = attempts.get(attempt_id)
            if attempt:
                attempt["status"] = "COMPLETED"
                attempt["completed_at"] = event["ts"]
                attempt["verdict"] = verdict
                attempt["to_state_id"] = None
            experiment = experiments.get(experiment_id)
            if experiment:
                experiment["last_verdict"] = verdict

            if verdict["status"] == "ERROR":
                budgets["infra_error_attempts"] += 1
            else:
                budgets["attempts_committed"] += 1
            budgets["cost_units_used"] = round(
                budgets["cost_units_used"] + float(data.get("cost_units") or 0.0), 6
            )

            from_state_id = str((experiment or {}).get("from_state_id") or current_state_id)
            if from_state_id not in states:
                from_state_id = current_state_id
            merge_parent_ids = [
                str(x)
                for x in ((experiment or {}).get("metadata") or {}).get("merge_parent_state_ids", [])
                if str(x) in states and str(x) != from_state_id
            ]
            parent_ids = [from_state_id, *merge_parent_ids]
            parent_states = [states[state_id] for state_id in parent_ids]
            statuses: dict[str, str] = {}
            claim_evidence: dict[str, list[str]] = {}
            for claim_id in claims:
                statuses[claim_id] = _merge_statuses(
                    [state["claim_statuses"].get(claim_id, "OPEN") for state in parent_states]
                )
                merged_evidence: list[str] = []
                for state in parent_states:
                    merged_evidence.extend(state["claim_evidence"].get(claim_id, []))
                claim_evidence[claim_id] = list(dict.fromkeys(merged_evidence))

            effects = data.get("claim_effects") or []
            for effect in effects:
                effect_claim_id = effect.get("claim_id")
                if not effect_claim_id:
                    continue
                if effect.get("status") == "REFUTED":
                    claim_refute_records.setdefault(effect_claim_id, []).append(
                        {"seq": seq, "experiment_id": experiment_id, "evidence_id": evidence_id}
                    )
            if verdict.get("status") == "PASS":
                for target_claim_id in (experiment or {}).get("target_claim_ids") or []:
                    claim_pass_records.setdefault(target_claim_id, []).append(
                        {"seq": seq, "experiment_id": experiment_id}
                    )
            rollbacks: list[dict[str, str]] = []
            for effect in effects:
                claim_id = effect["claim_id"]
                effect_status = effect.get("status")
                old_status = statuses.get(claim_id, "OPEN")
                if effect_status in {"SUPPORTED", "REFUTED"}:
                    statuses[claim_id] = effect_status
                elif effect_status == "INCONCLUSIVE" and old_status not in {"SUPPORTED", "REFUTED"}:
                    statuses[claim_id] = "INCONCLUSIVE"
                if evidence_id and effect_status in {"SUPPORTED", "REFUTED", "INCONCLUSIVE"}:
                    claim_evidence.setdefault(claim_id, [])
                    if evidence_id not in claim_evidence[claim_id]:
                        claim_evidence[claim_id].append(evidence_id)
                if old_status == "SUPPORTED" and statuses.get(claim_id) == "REFUTED":
                    rollbacks.append(
                        {
                            "claim_id": claim_id,
                            "previous_status": old_status,
                            "new_status": "REFUTED",
                        }
                    )
                if statuses.get(claim_id) == "REFUTED":
                    rollbacks.extend(_propagate_invalidation(statuses, claims, claim_id))

            new_state = _new_state(
                seq=seq,
                parent_state_ids=parent_ids,
                statuses=statuses,
                evidence=claim_evidence,
                budgets=budgets,
                verdict_event_id=event["event_id"],
                experiment_id=experiment_id,
                rollback=rollbacks,
            )
            states[new_state["id"]] = new_state
            current_state_id = new_state["id"]
            if rollbacks:
                recent_rollbacks.append(
                    {
                        "state_id": new_state["id"],
                        "event_id": event["event_id"],
                        "progress_rollback": any(
                            change.get("previous_status") == "SUPPORTED"
                            for change in rollbacks
                        ),
                        "changes": rollbacks,
                    }
                )

            if attempt:
                attempt["to_state_id"] = new_state["id"]
            if experiment:
                experiment["to_state_ids"].append(new_state["id"])
                status = verdict["status"]
                invalid_attempts = sum(
                    1
                    for aid in experiment.get("attempt_ids", [])
                    if ((attempts.get(aid) or {}).get("verdict") or {}).get("status") == "INVALID"
                )
                error_attempts = sum(
                    1
                    for aid in experiment.get("attempt_ids", [])
                    if ((attempts.get(aid) or {}).get("verdict") or {}).get("status") == "ERROR"
                )
                if status == "ERROR" and error_attempts < int(task["stop_policy"].get("max_error_attempts_per_experiment", 3)):
                    experiment["status"] = "ADMITTED"
                    frontier.add(experiment_id)
                elif status == "INVALID" and invalid_attempts < int(task["stop_policy"]["max_invalid_attempts_per_experiment"]):
                    experiment["status"] = "ADMITTED"
                    frontier.add(experiment_id)
                else:
                    experiment["status"] = "COMPLETED"
                    frontier.discard(experiment_id)

            # Evidence waits are satisfied deterministically from the log itself:
            # a WAITING experiment whose until_evidence filter matches this settled
            # verdict re-enters the frontier without any wall-clock event.
            if evidence_id and effects:
                effect_claim_ids = {item.get("claim_id") for item in effects}
                for waiting_id, waiting_experiment in experiments.items():
                    if waiting_experiment.get("status") != "WAITING":
                        continue
                    wait = waiting_experiment.get("wait") or {}
                    if wait.get("kind") != "evidence" or wait.get("status") != "PENDING":
                        continue
                    condition = wait.get("until_evidence") or {}
                    if condition.get("claim_id") not in effect_claim_ids:
                        continue
                    if condition.get("contract_id") and condition["contract_id"] != evidence_item.get("contract_id"):
                        continue
                    if condition.get("verdict") and condition["verdict"] != verdict["status"]:
                        continue
                    if condition.get("context_id") and condition["context_id"] != evidence_item.get("context_id"):
                        continue
                    wait["status"] = "SATISFIED"
                    wait["satisfied_by"] = evidence_id
                    wait["satisfied_seq"] = seq
                    waiting_experiment["status"] = "ADMITTED"
                    frontier.add(waiting_id)
        elif event_type == "WAIT_FIRED":
            experiment_id = data["experiment_id"]
            experiment = experiments.get(experiment_id)
            if experiment and experiment.get("status") == "WAITING":
                wait = experiment.get("wait") or {}
                wait["status"] = "FIRED"
                wait["fired_at"] = data.get("now") or event["ts"]
                experiment["status"] = "ADMITTED"
                frontier.add(experiment_id)
        elif event_type == "WAIT_EXPIRED":
            experiment_id = data["experiment_id"]
            experiment = experiments.get(experiment_id)
            if experiment and experiment.get("status") == "WAITING":
                wait = experiment.get("wait") or {}
                wait["status"] = "EXPIRED"
                wait["expired_at"] = data.get("now") or event["ts"]
                if wait.get("on_expire") == "release":
                    wait["released"] = True
                    experiment["status"] = "ADMITTED"
                    frontier.add(experiment_id)
                else:
                    experiment["status"] = "BACKLOG"
                    experiment["backlog_reason"] = "wait_expired"
                    frontier.discard(experiment_id)
        elif event_type == "EVIDENCE_REPRODUCED":
            target = evidence.get(str(data.get("evidence_id") or ""))
            if target is not None:
                target.setdefault("reproductions", []).append(
                    {
                        "seq": seq,
                        "ts": event["ts"],
                        "actor": event.get("actor"),
                        "code_intact": bool(data.get("code_intact")),
                        "deterministic_match": bool(data.get("deterministic_match")),
                        "verdict_stable": bool(data.get("verdict_stable")),
                        "reproduced_status": data.get("reproduced_status"),
                    }
                )
        elif event_type == "LESSON_CANDIDATE_CREATED":
            lesson = copy.deepcopy(data["lesson"])
            lesson.update(
                {
                    "status": "CANDIDATE",
                    "created_at": event["ts"],
                    "created_event_id": event["event_id"],
                }
            )
            lessons[lesson["id"]] = lesson
        elif event_type == "LESSON_EVIDENCE_ADDED":
            lesson_id = data["lesson_id"]
            if lesson_id in lessons:
                merged = list(lessons[lesson_id].get("evidence_ids") or [])
                for item in data.get("evidence_ids") or []:
                    if item not in merged:
                        merged.append(item)
                lessons[lesson_id]["evidence_ids"] = merged
        elif event_type == "LESSON_PROMOTED":
            lesson_id = data["lesson_id"]
            if lesson_id in lessons:
                lessons[lesson_id]["status"] = "ACTIVE"
                lessons[lesson_id]["promoted_at"] = event["ts"]
                lessons[lesson_id]["promotion_event_id"] = event["event_id"]
        elif event_type == "LESSON_REVOKED":
            lesson_id = data["lesson_id"]
            if lesson_id in lessons:
                lessons[lesson_id]["status"] = "REVOKED"
                lessons[lesson_id]["revoked_at"] = event["ts"]
                lessons[lesson_id]["revoke_reason"] = data.get("reason")
        elif event_type == "RUN_PAUSED":
            explicit_status = "PAUSED"
        elif event_type == "RUN_RESUMED":
            explicit_status = None
            run_status = "ACTIVE"
        elif event_type == "RUN_FAILED":
            explicit_status = "FAILED"
        elif event_type == "RUN_FINALIZED":
            explicit_status = str(data.get("status") or "EXHAUSTED")

    current_state = states[current_state_id]
    for claim_id, claim in claims.items():
        claim["status"] = current_state["claim_statuses"].get(claim_id, "OPEN")
        claim["evidence_ids"] = current_state["claim_evidence"].get(claim_id, [])
        claim["verdict_event_ids"] = [
            event["event_id"]
            for event in events
            if event["event_type"] == "VERDICT_ISSUED"
            and any(effect.get("claim_id") == claim_id for effect in (event.get("data") or {}).get("claim_effects", []))
        ]
        claim["last_updated_seq"] = max(
            [
                int(event.get("seq") or 0)
                for event in events
                if event["event_type"] == "VERDICT_ISSUED"
                and any(effect.get("claim_id") == claim_id for effect in (event.get("data") or {}).get("claim_effects", []))
            ]
            or [0]
        )
        invalidated_sources = []
        for rollback in recent_rollbacks:
            for change in rollback["changes"]:
                if change.get("claim_id") == claim_id and change.get("source_claim_id"):
                    invalidated_sources.append(change["source_claim_id"])
        claim["invalidated_by"] = list(dict.fromkeys(invalidated_sources))
        claim["provisional_passes"] = sum(
            1
            for attempt in attempts.values()
            if ((attempt.get("verdict") or {}).get("status") == "PASS")
            and claim_id in ((experiments.get(attempt.get("experiment_id")) or {}).get("target_claim_ids") or [])
        )
        # Cross-branch contradiction accounting: a claim SUPPORTED on the
        # current branch while FAIL evidence exists on any branch is contested
        # until a later PASS experiment carries a discriminating_note that
        # explains why the new measurement supersedes the refutation.
        refutes = claim_refute_records.get(claim_id, [])
        claim["contradicting_evidence_ids"] = [
            item["evidence_id"] for item in refutes if item.get("evidence_id")
        ]
        claim["contested"] = bool(refutes) and claim["status"] == "SUPPORTED"
        resolved_by = None
        if claim["contested"]:
            last_refute_seq = max(item["seq"] for item in refutes)
            for record in claim_pass_records.get(claim_id, []):
                if record["seq"] <= last_refute_seq:
                    continue
                candidate = experiments.get(record["experiment_id"]) or {}
                if str(candidate.get("discriminating_note") or "").strip():
                    resolved_by = record["experiment_id"]
                    break
        claim["contest_resolved_by"] = resolved_by

    contested_unresolved = sorted(
        claim_id
        for claim_id, claim in claims.items()
        if claim.get("contested") and not claim.get("contest_resolved_by") and claim.get("required", True)
    )

    goal_evaluation = _goal_status(task, current_state["claim_statuses"])
    progress = _progress(task, current_state["claim_statuses"])
    wall_minutes_used = round(
        _minutes_between(created_at, last_event.get("ts") if last_event else created_at),
        6,
    )
    budgets["wall_minutes_used"] = wall_minutes_used
    budgets["wall_minutes_remaining"] = (
        max(0.0, round(float(budgets["max_wall_minutes"]) - wall_minutes_used, 6))
        if budgets["max_wall_minutes"] is not None
        else None
    )
    if explicit_status:
        run_status = explicit_status
    elif (
        (budgets["max_attempts"] is not None and budgets["attempts_committed"] >= budgets["max_attempts"])
        or (budgets["max_cost_units"] is not None and budgets["cost_units_used"] >= budgets["max_cost_units"])
        or (budgets["max_wall_minutes"] is not None and budgets["wall_minutes_used"] >= budgets["max_wall_minutes"])
    ):
        run_status = "BUDGET_EXHAUSTED"
    elif goal_evaluation["root_status"] == "PASS" and task["stop_policy"].get("stop_on_goal_pass", True):
        if contested_unresolved and task["stop_policy"].get("require_uncontested_solve", False):
            run_status = "ACTIVE"
        else:
            run_status = "SOLVED"
    elif (
        task["stop_policy"].get("stop_on_goal_refuted", False)
        and goal_evaluation["root_status"] == "FAIL"
        and not any(
            item.get("status") in {"ADMITTED", "WAITING", "RESERVED", "RUNNING"}
            for item in experiments.values()
        )
    ):
        # The goal is refuted and nothing in flight could still rescue it; the
        # question has its (negative) answer, so stop symmetrically to SOLVED.
        run_status = "REFUTED"
    elif run_status == "CREATED":
        run_status = "ACTIVE"
    elif run_status not in {"PAUSED", "FAILED"}:
        run_status = "ACTIVE"

    frontier_items = sorted(
        [experiments[item] for item in frontier if item in experiments],
        key=lambda x: (-float((x.get("priority") or {}).get("score") or 0.0), str(x.get("id"))),
    )
    verifier_gaps = _planner_gap(task, claims, contracts)
    if run_status == "ACTIVE":
        if (
            contested_unresolved
            and goal_evaluation["root_status"] == "PASS"
            and task["stop_policy"].get("require_uncontested_solve", False)
        ):
            terminal_assessment = "CONTESTED"
        elif verifier_gaps and task["stop_policy"].get("block_without_verifier", True):
            terminal_assessment = "BLOCKED"
        elif goal_evaluation["root_status"] == "FAIL" and not any(
            item.get("status") in {"ADMITTED", "WAITING", "RESERVED", "RUNNING"}
            for item in experiments.values()
        ):
            # Advisory twin of the stop_on_goal_refuted hard stop: nothing in
            # flight can rescue a failed root; finalize resolves it as REFUTED.
            terminal_assessment = "REFUTED"
        elif not frontier_items and any(
            item.get("status") == "WAITING" for item in experiments.values()
        ):
            terminal_assessment = "WAITING"
        elif not frontier_items and experiments and all(
            item.get("status") in {"COMPLETED", "PRUNED", "BACKLOG"} for item in experiments.values()
        ):
            terminal_assessment = "EXHAUSTED"
        else:
            terminal_assessment = "CONTINUE"
    else:
        terminal_assessment = run_status

    waits = []
    for item in experiments.values():
        wait = item.get("wait")
        if not wait or not wait.get("status"):
            continue
        waits.append(
            {
                "experiment_id": item["id"],
                "kind": wait.get("kind"),
                "status": wait.get("status"),
                "not_before_ts": wait.get("not_before_ts"),
                "deadline_ts": wait.get("deadline_ts"),
                "on_expire": wait.get("on_expire"),
                "until_evidence": wait.get("until_evidence"),
                "satisfied_by": wait.get("satisfied_by"),
                "released": wait.get("released", False),
            }
        )
    waits.sort(key=lambda x: str(x["experiment_id"]))
    # Canonical UTC 'Z' timestamps order correctly under plain string comparison.
    wake_candidates = [
        candidate
        for wait in waits
        if wait["status"] == "PENDING"
        for candidate in (wait.get("not_before_ts"), wait.get("deadline_ts"))
        if candidate
    ]
    next_wake_at = min(wake_candidates) if wake_candidates else None

    lesson_usage: dict[str, dict[str, Any]] = {}
    for experiment in experiments.values():
        for lesson_id in (experiment.get("based_on") or {}).get("lesson_ids") or []:
            usage = lesson_usage.setdefault(lesson_id, {"experiment_ids": [], "verdicts": {}})
            usage["experiment_ids"].append(experiment["id"])
            verdict_status = (experiment.get("last_verdict") or {}).get("status")
            if verdict_status:
                usage["verdicts"][verdict_status] = usage["verdicts"].get(verdict_status, 0) + 1
    for usage in lesson_usage.values():
        usage["experiment_ids"] = sorted(usage["experiment_ids"])

    in_flight_attempts = [
        attempt
        for attempt in attempts.values()
        if attempt.get("status") in {"RESERVED", "RUNNING"} and not attempt.get("verdict")
    ]
    attempts_in_flight = len(in_flight_attempts)
    cost_units_reserved_in_flight = round(
        sum(float(attempt.get("cost_units_reserved") or 0.0) for attempt in in_flight_attempts),
        6,
    )

    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "research_id": events[0]["research_id"] if events else None,
        "task_id": task["id"],
        "topic": task["topic"],
        "i18n": dict(task.get("i18n") or {}),
        "created_at": created_at,
        "updated_at": last_event["ts"] if last_event else created_at,
        "run_status": run_status,
        "terminal_assessment": terminal_assessment,
        "last_event_seq": int(last_event.get("seq") or 0) if last_event else 0,
        "last_event_type": last_event.get("event_type") if last_event else None,
        "current_state_id": current_state_id,
        "progress": progress,
        "budget": {
            **budgets,
            "attempts_in_flight": attempts_in_flight,
            "cost_units_reserved_in_flight": cost_units_reserved_in_flight,
            "attempts_remaining": (
                max(0, budgets["max_attempts"] - budgets["attempts_committed"] - attempts_in_flight)
                if budgets["max_attempts"] is not None
                else None
            ),
            "cost_units_remaining": (
                max(
                    0.0,
                    round(
                        budgets["max_cost_units"]
                        - budgets["cost_units_used"]
                        - cost_units_reserved_in_flight,
                        6,
                    ),
                )
                if budgets["max_cost_units"] is not None
                else None
            ),
        },
        "goal_evaluation": goal_evaluation,
        "claims": claims,
        "contracts": contracts,
        "experiments": experiments,
        "attempts": attempts,
        "evidence": evidence,
        "lessons": lessons,
        "lesson_usage": {key: lesson_usage[key] for key in sorted(lesson_usage)},
        "states": states,
        "frontier": frontier_items,
        "waits": waits,
        "next_wake_at": next_wake_at,
        "verifier_gaps": verifier_gaps,
        "contested_claims": contested_unresolved,
        "recent_rollbacks": recent_rollbacks[-10:],
        "event_chain_head": last_event.get("event_hash") if last_event else None,
    }
    snapshot["snapshot_hash"] = canonical_hash({k: v for k, v in snapshot.items() if k != "snapshot_hash"})
    return snapshot


FRAMES_SCHEMA_VERSION = "sisyfus.replay_frames.v3"


def replay_frame(snapshot: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Project one visual-replay keyframe from a prefix-reduced snapshot."""
    rollback = None
    if snapshot["recent_rollbacks"]:
        last = snapshot["recent_rollbacks"][-1]
        if last.get("event_id") == event.get("event_id"):
            rollback = {
                "progress_rollback": bool(last.get("progress_rollback")),
                "changes": len(last.get("changes") or []),
            }
    return {
        "seq": int(event.get("seq") or 0),
        "ts": event.get("ts"),
        "event_type": event.get("event_type"),
        "actor": event.get("actor"),
        "objective": snapshot["progress"]["objective"],
        "epistemic": snapshot["progress"]["epistemic"],
        "run_status": snapshot["run_status"],
        "current_state_id": snapshot["current_state_id"],
        "claim_statuses": dict(sorted(snapshot["states"][snapshot["current_state_id"]]["claim_statuses"].items())),
        "frontier_size": len(snapshot["frontier"]),
        "attempts_remaining": snapshot["budget"]["attempts_remaining"],
        "cost_units_remaining": snapshot["budget"]["cost_units_remaining"],
        "n_lessons": len(snapshot["lessons"]),
        "rollback": rollback,
    }


def replay_frames(task: dict[str, Any], events: list[dict[str, Any]], *, start: int = 0) -> list[dict[str, Any]]:
    """Keyframes for event prefixes start+1..len(events), via the same reducer the live snapshot uses.

    Replay is re-derivation, not animation fiction: frame k is reduce_research over
    events[:k], so a scrubbed frame carries exactly the facts that were true then.
    The log is append-only and hash-chained, so frames for existing prefixes never
    change and callers may cache them and extend incrementally.
    """
    return [
        replay_frame(reduce_research(task, events[:k]), events[k - 1])
        for k in range(max(0, start) + 1, len(events) + 1)
    ]


def projection_bundle(snapshot: dict[str, Any]) -> dict[str, Any]:
    goal_graph = {
        "schema_version": "sisyfus.goal_graph.v2",
        "research_id": snapshot["research_id"],
        "root_id": snapshot["goal_evaluation"]["root_id"],
        "root_status": snapshot["goal_evaluation"]["root_status"],
        "nodes": snapshot["goal_evaluation"]["nodes"],
    }
    execution_graph = {
        "schema_version": "sisyfus.execution_graph.v2",
        "research_id": snapshot["research_id"],
        "current_state_id": snapshot["current_state_id"],
        "states": list(snapshot["states"].values()),
        "experiments": list(snapshot["experiments"].values()),
        "attempts": list(snapshot["attempts"].values()),
    }
    evidence_nodes = list(snapshot["evidence"].values())
    evidence_edges: list[dict[str, Any]] = []
    for item in evidence_nodes:
        evidence_id = item.get("id")
        for effect in item.get("claim_effects") or []:
            claim_id = effect.get("claim_id")
            if not evidence_id or claim_id not in snapshot["claims"]:
                continue
            effect_status = effect.get("status")
            relation = (
                "supports"
                if effect_status == "SUPPORTED"
                else "provisional_support"
                if item.get("verdict_status") == "PASS" and effect.get("provisional")
                else "refutes"
                if effect_status == "REFUTED"
                else "qualifies"
            )
            active_ids = set(snapshot["claims"][claim_id].get("evidence_ids") or [])
            evidence_edges.append(
                {
                    "from": evidence_id,
                    "to": claim_id,
                    "relation": relation,
                    "active_in_current_state": evidence_id in active_ids,
                }
            )
    evidence_graph = {
        "schema_version": "sisyfus.evidence_graph.v2",
        "research_id": snapshot["research_id"],
        "claims": list(snapshot["claims"].values()),
        "evidence": evidence_nodes,
        "edges": evidence_edges,
    }
    frontier = {
        "schema_version": "sisyfus.frontier.v2",
        "research_id": snapshot["research_id"],
        "items": snapshot["frontier"],
        "waits": snapshot.get("waits") or [],
        "next_wake_at": snapshot.get("next_wake_at"),
    }
    lessons = {
        "schema_version": "sisyfus.lessons.v2",
        "research_id": snapshot["research_id"],
        "items": list(snapshot["lessons"].values()),
    }
    return {
        "snapshot": snapshot,
        "goal_graph": goal_graph,
        "execution_graph": execution_graph,
        "evidence_graph": evidence_graph,
        "frontier": frontier,
        "lessons": lessons,
    }


def planner_context(snapshot: dict[str, Any], *, recent_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    claims = []
    for claim in snapshot["claims"].values():
        claims.append(
            {
                "id": claim["id"],
                "statement": claim["statement"],
                "status": claim["status"],
                "depends_on": claim.get("depends_on") or [],
                "evidence_count": len(claim.get("evidence_ids") or []),
                "provisional_passes": claim.get("provisional_passes", 0),
                "contested": claim.get("contested", False),
                "contest_resolved_by": claim.get("contest_resolved_by"),
            }
        )
    frontier = []
    for experiment in snapshot["frontier"]:
        frontier.append(
            {
                "id": experiment["id"],
                "title": experiment["title"],
                "target_claim_ids": experiment["target_claim_ids"],
                "mode": experiment["mode"],
                "action_family": experiment.get("action_family"),
                "priority": experiment["priority"],
                "contract_id": experiment.get("contract_id"),
                "expected_outcomes": experiment.get("expected_outcomes"),
            }
        )
    waiting = []
    for experiment in snapshot["experiments"].values():
        if experiment.get("status") != "WAITING":
            continue
        wait = experiment.get("wait") or {}
        waiting.append(
            {
                "id": experiment["id"],
                "title": experiment["title"],
                "target_claim_ids": experiment["target_claim_ids"],
                "wait": {
                    "kind": wait.get("kind"),
                    "not_before_ts": wait.get("not_before_ts"),
                    "deadline_ts": wait.get("deadline_ts"),
                    "until_evidence": wait.get("until_evidence"),
                    "on_expire": wait.get("on_expire"),
                },
            }
        )
    waiting.sort(key=lambda x: str(x["id"]))
    visible_lessons = [
        {
            "id": lesson["id"],
            "status": lesson["status"],
            "scope": lesson.get("scope") or {},
            "preconditions": lesson.get("preconditions") or [],
            "observation": lesson["observation"],
            "recommendation": lesson["recommendation"],
            "confidence": lesson.get("confidence"),
        }
        for lesson in snapshot["lessons"].values()
        if lesson.get("status") == "ACTIVE"
    ]
    recent = []
    for event in (recent_events or [])[-12:]:
        if event.get("visibility") == "host_only":
            recent.append(
                {
                    "seq": event.get("seq"),
                    "event_type": event.get("event_type"),
                    "visibility": "host_only",
                    "summary": "Hidden evaluation event recorded; details withheld from planner context.",
                }
            )
        else:
            data = copy.deepcopy(event.get("data") or {})
            if event.get("event_type") == "OBSERVATION_RECORDED":
                observation = data.get("observation") or {}
                data["observation"] = {
                    "summary": observation.get("summary"),
                    "metrics": observation.get("metrics"),
                    "artifact_count": len(observation.get("artifacts") or []),
                }
            recent.append(
                {
                    "seq": event.get("seq"),
                    "event_type": event.get("event_type"),
                    "data": data,
                }
            )
    return {
        "schema_version": "sisyfus.planner_context.v2",
        "research_id": snapshot["research_id"],
        "topic": snapshot["topic"],
        "run_status": snapshot["run_status"],
        "terminal_assessment": snapshot["terminal_assessment"],
        "current_state_id": snapshot["current_state_id"],
        "progress": snapshot["progress"],
        "budget": snapshot["budget"],
        "goal_root_status": snapshot["goal_evaluation"]["root_status"],
        "claims": claims,
        "frontier": frontier,
        "waiting": waiting,
        "next_wake_at": snapshot.get("next_wake_at"),
        "verifier_gaps": snapshot["verifier_gaps"],
        "contested_claims": snapshot.get("contested_claims") or [],
        "active_lessons": visible_lessons,
        "recent_events": recent,
        "planner_rules": [
            "Propose at most three decision-relevant experiments.",
            "Every admitted experiment must target a claim and bind a preregistered verifier contract.",
            "Treat ERROR and INVALID as execution/design failures, not evidence against the claim.",
            "Include at least one falsification or critical-uncertainty experiment when possible.",
            "Do not infer hidden-evaluation details from aggregate outcomes.",
            "When the frontier is empty but experiments are waiting, schedule a wake at next_wake_at instead of finalizing.",
        ],
    }
