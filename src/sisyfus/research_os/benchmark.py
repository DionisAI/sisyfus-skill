"""Paired, opt-in effectiveness pilot using actual ResearchOS execution.

The same text model proposes JSON data to three controllers. A fixed trusted
script measures candidates. Final tests run only AFTER every selection is frozen.
This is a bounded proposal/evaluation benchmark, not a full coding-agent arena.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import re
import shlex
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..research_v2.engine import ResearchEngine
from ..research_v2.workspace import atomic_write_json
from .benchmark_provider import Limits, Meter, Provider, Rates, count
from .controller import ResearchOS, configure, export_history
from .frontier import ready_frontier
from .models import FEATURES, digest, number
from .policy import SchedulingPolicy

ARMS = ("direct_refine", "independent_search", "research_os")
PROTOCOL = (
    "Propose up to three candidate JSON artifacts for the task, best first. "
    "Return ONLY a JSON object with a candidates array. Each entry has artifact "
    "(a JSON object), title, rationale, and priority (optional numbers 0..1 for "
    + ", ".join(FEATURES) + "). Artifacts are data, not tool commands. "
    "You cannot select a verifier, change the requirements, or mark results passed. "
    "Development feedback is evidence for iteration, not proof of final correctness."
)


def file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_suite(path: Path) -> dict:
    raw = json.loads(path.read_text())
    if raw.get("schema") != "sisyfus.benchmark_suite.v1" or not isinstance(raw.get("tasks"), list):
        raise ValueError("invalid benchmark suite")
    if not 1 <= len(raw["tasks"]) <= 100:
        raise ValueError("suite must have 1..100 tasks")
    ids, tasks = set(), []
    for item in raw["tasks"]:
        task = dict(item)
        for key in ("id", "family"):
            if not isinstance(task.get(key), str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", task[key]):
                raise ValueError("invalid task identity")
        if task["id"] in ids:
            raise ValueError("duplicate task ID")
        ids.add(task["id"])
        if not isinstance(task.get("prompt"), str) or not 1 <= len(task["prompt"]) <= 12000:
            raise ValueError("invalid public task prompt")
        task["threshold"] = number(task.get("threshold", 1), maximum=1)
        for key in ("evaluator", "cases"):
            source = (path.parent / task[key]).resolve()
            if not source.is_file() or source.stat().st_size > 5_000_000:
                raise ValueError("missing or oversized benchmark asset")
            task[key] = str(source)
            task[key + "_hash"] = file_hash(source)
        tasks.append(task)
    return {"schema": raw["schema"], "tasks": tasks}


class Audit:
    def __init__(self, path: Path):
        self.path, self.head, self.seq = path, None, 0

    def append(self, kind: str, data: Any) -> None:
        entry = {"sequence": self.seq, "previous": self.head, "kind": kind, "data": data}
        entry["hash"] = digest(entry)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True, allow_nan=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.head, self.seq = entry["hash"], self.seq + 1


def parse_candidates(text: str) -> list[dict]:
    raw = json.loads(text)
    if not isinstance(raw, dict) or set(raw) != {"candidates"}:
        raise ValueError("only the candidate envelope is accepted")
    items = raw["candidates"]
    if not isinstance(items, list) or not 1 <= len(items) <= 3:
        raise ValueError("provide 1..3 candidates")
    result = []
    for item in items:
        if not isinstance(item, dict) or set(item) - {"artifact", "title", "rationale", "priority"}:
            raise ValueError("unknown candidate field")
        if not isinstance(item.get("artifact"), dict):
            raise ValueError("candidate artifact must be a JSON object")
        if len(json.dumps(item, allow_nan=False).encode()) > 16000:
            raise ValueError("candidate too large")
        priority = item.get("priority", {})
        if not isinstance(priority, dict) or set(priority) - set(FEATURES):
            raise ValueError("invalid priority fields")
        title, rationale = item.get("title", "Candidate"), item.get("rationale", "")
        if not isinstance(title, str) or not isinstance(rationale, str) or len(title) > 500 or len(rationale) > 4000:
            raise ValueError("invalid candidate explanation")
        result.append({"artifact": item["artifact"], "title": title or "Candidate", "rationale": rationale,
                       "priority": {k: number(priority.get(k, 0), maximum=1) for k in FEATURES}})
    return result


def make_engine(root: Path, task: dict, limit: int, split: str) -> ResearchEngine:
    root.mkdir(parents=True)
    for src, name in (("evaluator", "evaluator.py"), ("cases", "cases.json")):
        if file_hash(Path(task[src])) != task[src + "_hash"]:
            raise RuntimeError("benchmark source changed after preregistration")
        shutil.copyfile(task[src], root / name)
    return ResearchEngine.create(root, {
        "id": root.name, "topic": task["prompt"],
        "claims": [{"id": "target", "statement": "Selected artifact meets the frozen tests"}],
        "verification_contracts": [{"id": "verify", "target_claim_id": "target",
            "pass_if": [{"path": "metrics.score", "op": ">=", "value": task["threshold"]}],
            "fail_if": [{"path": "metrics.score", "op": "<", "value": task["threshold"]}]}],
        "budget": {"max_attempts": limit, "max_cost_units": limit},
        "stop_policy": {"stop_on_goal_pass": False, "stop_on_goal_refuted": False},
        "metadata": {"task_family": task["family"], "benchmark_split": split},
    }, render=False)


def check_assets(engine: ResearchEngine, task: dict) -> None:
    for name, key in (("evaluator.py", "evaluator_hash"), ("cases.json", "cases_hash")):
        if file_hash(engine.workspace.root / name) != task[key]:
            raise RuntimeError("preregistered evaluator or cases changed")


def admit(engine: ResearchEngine, item: dict, index: int, split: str, timeout: float) -> str:
    eid = f"candidate-{index:04d}"
    root = engine.workspace.root
    atomic_write_json(root / (eid + ".json"), item["artifact"])
    argv = [sys.executable, "-I", "evaluator.py", "--cases", "cases.json", "--candidate", eid + ".json",
            "--split", split, "--output", eid + "-result.json"]
    result = engine.propose_experiment({
        "id": eid, "title": item["title"], "rationale": item["rationale"],
        "target_claim_ids": ["target"], "contract_id": "verify", "context_id": eid,
        "action": {"kind": "command", "command": shlex.join(argv), "cwd": str(root),
                   "timeout_seconds": max(1, min(30, int(timeout))), "parse_stdout_json": True,
                   "code_paths": ["evaluator.py", "cases.json", eid + ".json"],
                   "artifact_paths": [eid + "-result.json"]},
        "priority": item["priority"], "cost": {"units": 1},
        "expected_outcomes": {"pass": "meets frozen tests", "fail": "counterexample",
                              "inconclusive": "insufficient evidence", "invalid": "invalid measurement"},
    })
    if not result["admission"]["accepted"]:
        raise RuntimeError("benchmark candidate admission rejected")
    return eid


def score_result(engine: ResearchEngine, receipt: dict) -> dict:
    evidence = engine.snapshot()["evidence"][receipt["evidence_id"]]
    observation = evidence.get("observation", evidence)
    # Evidence carries the normalized metrics in the existing engine schema.
    score = number(observation.get("metrics", {}).get("score", 0), maximum=1)
    if receipt["verdict"] not in {"PASS", "FAIL", "INCONCLUSIVE"}:
        score = 0.0
    return {"verdict": receipt["verdict"], "score": score, "evidence_id": receipt["evidence_id"]}


def run_episode(root: Path, task: dict, arm: str, provider: Provider, limits: Limits,
                rates: Rates, policy: SchedulingPolicy, allowed_models: set[str], audit: Audit) -> dict:
    engine = make_engine(root, task, limits.max_evaluations, "development")
    active = policy if arm == "research_os" else SchedulingPolicy(name="model-ordered", selection="fifo")
    meter, seen, artifacts, feedback = Meter(limits, rates), set(), {}, []
    started, errors, actual_models, response_ids = time.monotonic(), [], set(), []
    state, fatal = "budget_exhausted", False
    while len(feedback) < limits.max_evaluations:
        remaining = limits.max_seconds - (time.monotonic() - started)
        if remaining < 1:
            state = "wall_budget_exhausted"
            break
        if not ready_frontier(engine.snapshot()):
            if meter.calls >= limits.max_calls or meter.outputs >= limits.max_output_tokens:
                break
            visible = feedback if arm != "independent_search" else []
            messages = [{"role": "developer", "content": PROTOCOL},
                        {"role": "user", "content": json.dumps({"task": task["prompt"], "development_feedback": visible})}]
            audit.append("INPUT_COUNT_INTENT", {"episode": root.name, "messages": messages})
            try:
                input_tokens = count(provider.count_input(messages, min(60, remaining)))
            except Exception as exc:
                errors.append("input_count:" + type(exc).__name__)
                audit.append("INPUT_COUNT_ERROR", {"episode": root.name, "error_type": type(exc).__name__})
                state, fatal = "input_count_error", True
                break
            cap = meter.reserve(input_tokens)
            if not cap:
                state = "provider_budget_exhausted"
                break
            audit.append("PROVIDER_INTENT", {"episode": root.name, "call": meter.calls,
                         "max_output_tokens": cap, "counted_input_tokens": input_tokens,
                         "reserved_usd": meter.reserved})
            try:
                remaining = limits.max_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    # No generation dispatched; release only this known-unused reservation.
                    meter.pending, meter.reserved = None, 0.0
                    state = "wall_budget_exhausted"
                    audit.append("PROVIDER_NOT_DISPATCHED", {"episode": root.name})
                    break
                reply = provider.generate(messages, cap, min(120, remaining))
                meter.settle(reply)
            except Exception as exc:
                audit.append("PROVIDER_UNRESOLVED", {"episode": root.name, "error_type": type(exc).__name__, "meter": meter.public()})
                errors.append("provider:" + type(exc).__name__)
                state, fatal = "provider_unresolved", True
                break  # No retry and no further tasks after uncertain spend.
            audit.append("PROVIDER_RECEIPT", {"episode": root.name, "reply": asdict(reply), "meter": meter.public()})
            actual_models.add(reply.actual_model)
            response_ids.append(reply.response_id)
            if reply.actual_model not in allowed_models or meter.violated:
                state, fatal = "model_or_budget_mismatch", True
                break
            if reply.status != "completed":
                errors.append("provider_status:" + reply.status)
                continue
            try:
                proposals = parse_candidates(reply.text)
            except (ValueError, TypeError, RecursionError):
                errors.append("invalid_candidate_response")
                continue  # Paid bad outputs remain charged in the denominator.
            check_assets(engine, task)
            for item in proposals:
                identity = digest(item["artifact"])
                if identity in seen:
                    audit.append("DUPLICATE", {"episode": root.name, "artifact_hash": identity})
                    continue
                seen.add(identity)
                eid = admit(engine, item, len(artifacts), "development", remaining)
                artifacts[eid] = item
            # This approves DATA with a preregistered executable, not generated code.
            configure(engine, policy=active)
            if not ready_frontier(engine.snapshot()):
                continue
        check_assets(engine, task)
        if limits.max_seconds - (time.monotonic() - started) < 1:
            state = "wall_budget_exhausted"
            break
        configure(engine, policy=active)
        if arm == "research_os":
            result = ResearchOS(engine).run(max_steps=1, allow_local_commands=True)
            if not result.results:
                state, fatal = result.stop_reason, True
                break
            receipt = result.results[0]
            eid = engine.snapshot()["attempts"][receipt["attempt_id"]]["experiment_id"]
        else:
            eid = active.rank(ready_frontier(engine.snapshot()))[0].id
            exp = engine.snapshot()["experiments"][eid]
            hashes = engine._action_code_hashes(exp["action"])
            outcome = engine.execute_experiment(eid, expected_code_hashes={p: hashes[p] for p in exp["action"]["code_paths"]})
            receipt = {"verdict": outcome["verdict"]["status"], "evidence_id": outcome["evidence"]["id"]}
        measured = score_result(engine, receipt)
        feedback.append({"artifact": artifacts[eid]["artifact"], **measured})
        audit.append("DEVELOPMENT_RESULT", {"episode": root.name, "candidate_id": eid, **measured})
        # Never silently retry an errored evaluator and call it additional evidence.
        if measured["verdict"] in {"ERROR", "INVALID"}:
            state, fatal = "evaluation_error", True
            break
    selected = max(range(len(feedback)), key=lambda i: feedback[i]["score"]) if feedback else None
    chosen = feedback[selected] if selected is not None else None
    record = {"episode": root.name, "task_id": task["id"], "family": task["family"], "arm": arm,
              "state": state, "fatal": fatal, "evaluations": len(feedback), "errors": errors,
              "elapsed_seconds": time.monotonic() - started, "meter": meter.public(),
              "actual_models": sorted(actual_models), "response_ids": response_ids,
              "wall_budget_overrun": time.monotonic() - started > limits.max_seconds,
              "selected": chosen, "policy_hash": active.hash,
              "evidence_head": engine.events[-1]["event_hash"]}
    atomic_write_json(root / "selection.json", record)
    if arm == "research_os":
        atomic_write_json(root / "history.json", export_history(engine))
    audit.append("SELECTION_FROZEN", record)
    return record


def paired_summary(rows: list[dict], planned: int, *, live: bool, seed: int) -> dict:
    """Pair by task; resample task families, not correlated attempts or repeats."""
    groups = {arm: [r for r in rows if r["arm"] == arm] for arm in ARMS}
    totals = {}
    for arm, entries in groups.items():
        totals[arm] = {"planned": planned, "attempted": len(entries), "completed_final_evaluations": sum(r.get("final", {}).get("verdict") in {"PASS", "FAIL"} for r in entries),
            "passed": sum(r.get("final", {}).get("verdict") == "PASS" for r in entries),
            "development_false_positives": sum(r["selected"] is not None and r["selected"]["verdict"] == "PASS" and r.get("final", {}).get("verdict") == "FAIL" for r in entries),
            "evaluations": sum(r["evaluations"] for r in entries),
            "provider_calls": sum(r["meter"]["calls"] for r in entries),
            "input_tokens": sum(r["meter"]["input_tokens"] for r in entries),
            "output_tokens": sum(r["meter"]["output_tokens"] for r in entries),
            "elapsed_seconds": sum(r["elapsed_seconds"] for r in entries),
            "token_priced_usd": sum(r["meter"]["token_priced_usd"] for r in entries),
            "reserved_usd": sum(r["meter"]["reserved_usd"] for r in entries)}
    comparisons = {}
    for baseline in ARMS[:2]:
        families: dict[str, list[float]] = {}
        for right in groups["research_os"]:
            left = next((r for r in groups[baseline] if r["task_id"] == right["task_id"] and r["repeat"] == right["repeat"]), None)
            if left is None or "final" not in left or "final" not in right:
                continue
            delta = float(right["final"]["verdict"] == "PASS") - float(left["final"]["verdict"] == "PASS")
            families.setdefault(right["family"], []).append(delta)
        family_means = [sum(v) / len(v) for v in families.values()]
        ci = None
        if len(family_means) >= 2:
            rng = random.Random(seed)
            samples = sorted(sum(rng.choices(family_means, k=len(family_means))) / len(family_means) for _ in range(2000))
            ci = [samples[49], samples[1949]]
        comparisons[baseline] = {"family_count": len(families), "family_weighted_pass_delta": sum(family_means) / len(family_means) if family_means else None,
                                 "paired_family_bootstrap_95": ci}
    actual = {m for r in rows for m in r["actual_models"]}
    comparable = len(rows) == planned * len(ARMS) and len(actual) == 1 and all(not r["fatal"] and r.get("final", {}).get("verdict") in {"PASS", "FAIL", "NOT_SUBMITTED"} and not r["meter"]["unresolved"] and not r.get("wall_budget_overrun", False) for r in rows)
    return {"arms": totals, "comparisons": comparisons, "complete_comparable_run": comparable,
            "real_llm_executed": live and any(r["response_ids"] for r in rows),
            "accounting_kind": "provider_receipts_operator_rate_estimates" if live else "synthetic_fixture_usage_not_real_dollars",
            "actual_models": sorted(actual), "beats_gpt6_astra": None,
            "automatic_policy_activation": False,
            "controller_training_cost_usd": None, "tool_execution_cost_usd": None,
            "scope": "bounded_artifact_proposal_pilot_not_full_coding_agent_or_general_superiority"}


def run_benchmark(suite_path: Path, output: Path, provider: Provider, *, limits: Limits,
                  rates: Rates, policy: SchedulingPolicy | None = None, repeats: int = 1,
                  seed: int = 0, allowed_models: set[str] | None = None, max_total_usd: float = 5.0) -> dict:
    if type(repeats) is not int or not 1 <= repeats <= 20:
        raise ValueError("repeats must be in 1..20")
    suite = load_suite(suite_path.resolve())
    number(max_total_usd, minimum=0.000001, maximum=10000)
    nominal_cap = len(suite["tasks"]) * repeats * len(ARMS) * limits.max_usd
    if provider.live and nominal_cap > max_total_usd + 1e-12:
        raise ValueError("nominal suite allowance exceeds max_total_usd; reduce per-arm limits or explicitly raise the suite cap")
    if output.exists() and any(output.iterdir()):
        raise ValueError("benchmark output must be empty; interrupted runs must be reconciled, not replayed")
    output.mkdir(parents=True, exist_ok=True)
    output = output.resolve()
    policy = policy or SchedulingPolicy()
    if policy.judgment_weight:
        raise ValueError("pilot has no paid judge budget; use zero judgment_weight")
    allowed = allowed_models or {provider.model}
    schedule = []
    rng = random.Random(seed)
    for repeat in range(repeats):
        for task in suite["tasks"]:
            arms = list(ARMS)
            rng.shuffle(arms)
            schedule.extend((task, repeat, arm) for arm in arms)
    source_hashes = {str(p.relative_to(Path(__file__).parent.parent)): file_hash(p)
                     for package in (Path(__file__).parent, Path(__file__).parent.parent / "research_v2")
                     for p in sorted(package.glob("*.py"))}
    manifest = {"suite": suite, "source_hashes": source_hashes, "nominal_suite_cap_usd": nominal_cap, "max_total_usd": max_total_usd, "limits": asdict(limits), "rates": asdict(rates),
                "provider": provider.describe(), "allowed_models": sorted(allowed),
                "policy": asdict(policy), "repeats": repeats, "seed": seed,
                "schedule": [[t["id"], n, a] for t, n, a in schedule],
                "protocol_hash": digest(PROTOCOL), "runner_hash": file_hash(Path(__file__)),
                "python": sys.version, "platform": platform.platform()}
    manifest["hash"] = digest(manifest)
    atomic_write_json(output / "manifest.json", manifest)
    audit = Audit(output / "audit.jsonl")
    audit.append("REGISTERED", manifest)
    rows = []
    try:
        for task, repeat, arm in schedule:
            root = output / f"{task['id']}-r{repeat:02d}-{arm}"
            row = run_episode(root, task, arm, provider, limits, rates, policy, allowed, audit)
            row["repeat"] = repeat
            rows.append(row)
            if row["fatal"]:
                break
        # Nothing from final tests can affect ANY generation or selection above.
        audit.append("ALL_SELECTIONS_FROZEN", {"selections": [digest(r) for r in rows], "count": len(rows)})
        for row in rows:
            if row["selected"] is None or row["fatal"]:
                row["final"] = {"verdict": "NOT_EVALUATED" if row["fatal"] else "NOT_SUBMITTED", "score": 0}
                continue
            task = next(t for t in suite["tasks"] if t["id"] == row["task_id"])
            engine = make_engine(output / (row["episode"] + "-final"), task, 1, "holdout")
            chosen = {"artifact": row["selected"]["artifact"], "title": "Frozen selection", "rationale": "", "priority": {}}
            admit(engine, chosen, 0, "holdout", 30)
            configure(engine)
            final = ResearchOS(engine).run(max_steps=1, allow_local_commands=True)
            if not final.results:
                raise RuntimeError("final evaluation unresolved")
            row["final"] = score_result(engine, final.results[0])
            audit.append("FINAL_RESULT", {"episode": row["episode"], **row["final"]})
    except Exception as exc:
        audit.append("RUN_ERROR", {"error_type": type(exc).__name__, "reconcile_before_restart": True})
        raise
    summary = paired_summary(rows, len(suite["tasks"]) * repeats, live=provider.live, seed=seed)
    summary.update(schema="sisyfus.benchmark_report.v1", manifest_hash=manifest["hash"], rows=rows)
    audit.append("SUMMARY", summary)
    summary["audit_head"] = audit.head
    atomic_write_json(output / "summary.json", summary)
    return summary


def inspect_benchmark(root: Path) -> dict:
    """Verify the benchmark hash chain and expose unresolved provider intentions."""
    head, pending, kinds, last_summary = None, {}, {}, None
    path = root / "audit.jsonl"
    for index, line in enumerate(path.read_text().splitlines()):
        event = json.loads(line)
        content = {k: v for k, v in event.items() if k != "hash"}
        if event.get("sequence") != index or event.get("previous") != head or event.get("hash") != digest(content):
            raise ValueError("benchmark audit chain mismatch")
        head = event["hash"]
        kind, data = event["kind"], event["data"]
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind == "PROVIDER_INTENT":
            if data["episode"] in pending:
                raise ValueError("overlapping provider reservation")
            pending[data["episode"]] = data
        elif kind in {"PROVIDER_RECEIPT", "PROVIDER_NOT_DISPATCHED"}:
            if data["episode"] not in pending:
                raise ValueError("provider receipt has no intent")
            del pending[data["episode"]]
        elif kind == "SUMMARY":
            last_summary = data
    summary_path = root / "summary.json"
    intact = False
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
        intact = summary.get("audit_head") == head and {k: v for k, v in summary.items() if k != "audit_head"} == last_summary
        if not intact:
            raise ValueError("benchmark summary does not match the audit")
    return {"audit_head": head, "events": sum(kinds.values()), "event_counts": kinds,
            "summary_verified": intact, "unresolved_requests": list(pending.values()),
            "can_auto_resume": False}
