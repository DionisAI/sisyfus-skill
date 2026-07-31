from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .beam import BeamRunner, BeamStore
from .distill import make_distill
from .evals import run_builtin_evals
from .experiment_ledger import experiment_chart_data, experiment_summary, list_experiments, load_experiment
from .memory_fsm import MemoryFSMStore
from .outcome import grade_outcome, list_outcomes, load_outcome
from .provider import summarize_provider_usage
from .rubric import grade_rubric, list_rubrics, load_rubric, write_builtin_rubrics
from .goal import load_goal, write_goal_template
from .model_policy import load_model_policy, resolve_model_route, write_default_model_policy
from .monitor import MonitorRegistry, parse_param_assignments, route_ops_task
from .orchestrator import SisyfusRunner
from .paths import ensure_layout, find_project_root
from .promote import promote_repeated_failures
from .review import ReviewStore, load_review_context
from .research_v2.engine import ResearchEngine, build_demo, load_json_object
from .research_v2.live import (
    AlreadyServing,
    clear_live_state,
    ensure_observatory,
    live_observatory_url,
    observatory_entry_path,
    read_live_state,
    resolve_serve_port,
    write_live_state,
)
from .research_v2.workspace import ResearchWorkspace
from .scaffold import init_project
from .session import list_sessions, load_recent_session_context
from .storage import MemoryBroker
from .utils import read_jsonl, write_json
from .verifier import verify_goal


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True, default=str))


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root or Path.cwd()).resolve()
    sf = init_project(root, force=args.force)
    print(f"Initialized Sisyfus at {sf}")
    return 0


def cmd_goal_new(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    ensure_layout(root)
    out = Path(args.out) if args.out else root / ".sisyfus" / "goals" / f"{args.id}.json"
    goal = write_goal_template(
        out,
        goal_id=args.id,
        objective=args.objective,
        commands=args.command or [],
        max_rounds=args.max_rounds,
        task_type=args.task_type,
    )
    print(f"Wrote GoalSpec: {out}")
    if args.print_json:
        _print_json(goal)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    final = SisyfusRunner(args.root).run(args.goal, adapter_name=args.adapter, agent_command=args.agent_command, apply_distill=args.apply_distill)
    _print_json(final)
    return 0 if final["status"] == "PASSED" else 2


def cmd_verify(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    goal = load_goal(args.goal)
    run_dir = Path(args.run_dir) if args.run_dir else root / ".sisyfus" / "runs" / "manual-verify"
    run_dir.mkdir(parents=True, exist_ok=True)
    result = verify_goal(goal, workdir=Path(args.workdir or root).resolve(), run_dir=run_dir, root=root)
    _print_json(result)
    return 0 if result["status"] == "PASSED" else 2


def cmd_distill(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    distill = make_distill(Path(args.run_dir))
    if args.apply:
        counts = MemoryBroker(root).apply_distill(distill)
        distill["applied_counts"] = counts
    _print_json(distill)
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    _print_json(promote_repeated_failures(root, threshold=args.threshold))
    return 0


def cmd_inbox(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    tasks = MemoryBroker(root).read_open_tasks()
    if args.json:
        _print_json(tasks)
        return 0
    if not tasks:
        print("Inbox is empty.")
        return 0
    for i, task in enumerate(tasks, start=1):
        print(f"[{i}] {task.get('title') or task.get('task_id')}")
        print(f"    status: {task.get('status', 'open')} priority: {task.get('priority', '-')}")
        print(f"    reason: {task.get('reason', '-')}")
        if task.get("run_dir"):
            print(f"    run: {task['run_dir']}")
    return 0


def cmd_memory(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    sf = ensure_layout(root)
    path = sf / "tasks" / "open.jsonl" if args.kind == "open-tasks" else sf / "memory" / f"{args.kind}.jsonl"
    items = read_jsonl(path)
    if args.json:
        _print_json(items)
    else:
        for item in items:
            print(json.dumps(item, sort_keys=True, default=str))
    return 0


def cmd_monitor_list(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    items = MonitorRegistry(root).list(include_builtin=not args.custom_only)
    if args.json:
        _print_json(items)
        return 0
    for item in items:
        tags = ", ".join(map(str, item.get("tags", [])))
        print(f"{item.get('id')} [{item.get('source')}] - {item.get('description')}")
        if tags:
            print(f"    tags: {tags}")
    return 0


def cmd_monitor_suggest(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    _print_json({"task": args.task, "suggestions": MonitorRegistry(root).suggest(args.task, top_k=args.top_k)})
    return 0


def cmd_monitor_run(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    result = MonitorRegistry(root).run(args.id, params=parse_param_assignments(args.param), workdir=Path(args.workdir or root).resolve())
    _print_json(result)
    return 0 if result["status"] == "PASSED" else 2


def cmd_monitor_add(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    _print_json(MonitorRegistry(root).add_custom(args.id, description=args.description, command=args.command, tags=args.tag or []))
    return 0


def cmd_ops_route(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    result = route_ops_task(root, task=args.task, params=parse_param_assignments(args.param), threshold=args.threshold, workdir=Path(args.workdir or root).resolve())
    _print_json(result)
    return 0 if result.get("status") == "PASSED" else (3 if result.get("status") == "NEEDS_AGENT" else 2)


def cmd_model_policy(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    if args.write_default:
        path = write_default_model_policy(root, force=args.force)
        print(f"Wrote model policy: {path}")
        return 0
    _print_json(load_model_policy(root))
    return 0


def cmd_model_route(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    goal = load_goal(args.goal) if args.goal else None
    _print_json(resolve_model_route(root, goal=goal, task_type=args.task_type, role=args.role, override_profile=args.profile, override_model=args.model))
    return 0


def cmd_session_list(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    items = list_sessions(root, limit=args.limit)
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("No sessions recorded.")
        return 0
    for item in items:
        beam = f" beam={item.get('beam_id')} node={item.get('beam_node_id')}" if item.get("beam_id") else ""
        print(f"{item.get('run_id')}  {item.get('status')}  {item.get('goal_id')}  [{item.get('task_type')}]{beam}")
        print(f"    {item.get('reason')}")
        print(f"    compact: {item.get('compact_path')}")
    return 0


def cmd_session_context(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    print(load_recent_session_context(root, limit=args.limit, max_chars=args.max_chars) or "")
    return 0


def cmd_beam_run(args: argparse.Namespace) -> int:
    summary = BeamRunner(args.root).run(args.goal, adapter_name=args.adapter, agent_command=args.agent_command, apply_distill=args.apply_distill)
    _print_json(summary)
    return 0 if summary.get("status") in {"COMPLETED", "EMPTY"} else 2


def cmd_beam_list(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    items = BeamStore(root).list_beams(limit=args.limit)
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("No beam runs recorded.")
        return 0
    for item in items:
        print(f"{item.get('beam_id')}  {item.get('status')}  sessions={item.get('session_count')} nodes={item.get('node_count')}  goal={item.get('goal_id')}")
        print(f"    {item.get('objective')}")
        print(f"    dir: {item.get('beam_dir')}")
    return 0


def cmd_beam_status(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    _print_json(BeamStore(root).load_beam(args.beam_id))
    return 0


def cmd_beam_context(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    print(BeamStore(root).build_context(args.beam_id, max_chars=args.max_chars))
    return 0


def cmd_beam_template(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    ensure_layout(root)
    directions = []
    for i, branch in enumerate(args.branch or [], start=1):
        directions.append({"id": f"branch-{i}", "title": branch, "objective": branch, "task_type": args.branch_task_type, "priority": "P2"})
    if not directions:
        directions = [
            {"id": "network-factor-search", "title": "Search known factor ideas", "objective": "Collect known crypto cross-sectional factor families and convert them into testable hypotheses.", "task_type": "information_collection", "priority": "P1"},
            {"id": "handcrafted-factor", "title": "Handcraft factor hypotheses", "objective": "Generate first-principles crypto cross-sectional factors and specify deterministic evaluation plans.", "task_type": "factor_research", "priority": "P1"},
            {"id": "formula-alpha-mining", "title": "AlphaGPT-style symbolic formulas", "objective": "Explore formulaic alpha expression templates and propose bounded formula search/evaluation specs.", "task_type": "formula_alpha_mining", "priority": "P1"},
        ]
    goal = {
        "schema_version": "sisyfus.goal.v0.6",
        "id": args.id,
        "objective": args.objective,
        "task_type": args.task_type,
        "done_when": {"commands": args.command or []},
        "loop": {"max_rounds": args.max_rounds},
        "beam": {
            "enabled": True,
            "id": args.id,
            "width": args.width,
            "max_depth": args.max_depth,
            "max_children_per_node": args.max_children_per_node,
            "max_sessions_total": args.max_total_sessions,
            "selection_metric": "score",
            "directions": directions,
        },
    }
    out = Path(args.out) if args.out else root / ".sisyfus" / "goals" / f"{args.id}.beam.json"
    write_json(out, goal)
    print(f"Wrote Beam GoalSpec: {out}")
    if args.print_json:
        _print_json(goal)
    return 0


def cmd_review_list(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    items = ReviewStore(root).annotations()
    if args.target_type:
        items = [x for x in items if x.get("target_type") == args.target_type]
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("No human annotations recorded.")
        return 0
    for item in items[-args.limit:]:
        print(f"{item.get('verdict')}  {item.get('target_type')}:{item.get('target_id')}")
        if item.get("claim"):
            print(f"    claim: {item.get('claim')}")
        if item.get("note"):
            print(f"    note: {item.get('note')}")
        if item.get("next_action"):
            print(f"    next: {item.get('next_action')}")
    return 0


def cmd_review_claims(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    claims = ReviewStore(root).claims(limit_sessions=args.limit_sessions)
    if args.verdict:
        claims = [c for c in claims if c.get("human_verdict") == args.verdict]
    if args.beam_id:
        claims = [c for c in claims if c.get("beam_id") == args.beam_id]
    if args.json:
        _print_json(claims)
        return 0
    if not claims:
        print("No distill claims found. Run a goal first, or make sure sessions have distill.json artifacts.")
        return 0
    for item in claims[: args.limit]:
        verdict = item.get("human_verdict") or "unreviewed"
        beam = f" beam={item.get('beam_id')} node={item.get('beam_node_id')}" if item.get("beam_id") else ""
        print(f"{item.get('claim_id')}  [{verdict}]  {item.get('kind')}  {item.get('goal_id')}{beam}")
        print(f"    {item.get('claim')}")
        if item.get("human_note"):
            print(f"    human note: {item.get('human_note')}")
    return 0


def cmd_review_annotate(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    item = ReviewStore(root).annotate(
        target_id=args.target_id,
        verdict=args.verdict,
        note=args.note or "",
        target_type=args.target_type,
        run_id=args.run_id,
        goal_id=args.goal_id,
        claim=args.claim,
        next_action=args.next_action,
        created_by=args.created_by,
        create_task=args.create_task,
    )
    _print_json(item)
    return 0


def cmd_guidance_add(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    item = ReviewStore(root).add_guidance(args.text, scope=args.scope, goal_id=args.goal_id, run_id=args.run_id, priority=args.priority, tags=args.tag or [], create_task=args.create_task)
    _print_json(item)
    return 0


def cmd_guidance_list(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    items = ReviewStore(root).guidance(include_archived=args.include_archived)
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("No active guidance recorded.")
        return 0
    for item in items[: args.limit]:
        print(f"{item.get('guidance_id')}  {item.get('priority')}  scope={item.get('scope')}")
        print(f"    {item.get('text')}")
        if item.get("tags"):
            print(f"    tags: {', '.join(item.get('tags', []))}")
    return 0


def cmd_review_context(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    print(load_review_context(root, max_chars=args.max_chars))
    return 0


def cmd_rubric_list(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    items = list_rubrics(root)
    if args.json:
        _print_json(items)
        return 0
    for r in items:
        print(f"{r.get('id')}  threshold={r.get('pass_threshold')}  source={r.get('source')}")
        print(f"    {r.get('title') or r.get('description','')}")
    return 0


def cmd_rubric_show(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    _print_json(load_rubric(root, args.id))
    return 0


def cmd_rubric_install(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    paths = write_builtin_rubrics(root, force=args.force)
    for path in paths:
        print(path)
    return 0


def cmd_rubric_grade(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    rubric = load_rubric(root, args.id)
    result = grade_rubric(root=root, rubric=rubric, run_dir=args.run_dir)
    _print_json(result)
    return 0 if result["status"] == "PASSED" else 2


def cmd_outcome_grade(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    goal = load_goal(args.goal)
    result = grade_outcome(root=root, goal=goal, run_dir=args.run_dir)
    _print_json(result)
    return 0 if result["status"] == "PASSED" else 2


def cmd_outcome_list(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    items = list_outcomes(root, limit=args.limit)
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("No outcomes recorded.")
        return 0
    for item in items:
        print(f"{item.get('run_id')}  {item.get('status')}  score={item.get('score')}  rubric={item.get('rubric_id')}")
        print(f"    {item.get('feedback','').splitlines()[0] if item.get('feedback') else ''}")
    return 0


def cmd_outcome_show(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    _print_json(load_outcome(root, args.run_id))
    return 0


def cmd_experiment_list(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    items = list_experiments(root, limit=args.limit, status=args.status, beam_id=args.beam_id)
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("No experiments recorded.")
        return 0
    for item in items:
        score = item.get("metrics", {}).get("score", item.get("metrics", {}).get("rubric_score", "-"))
        print(f"{item.get('experiment_id')}  {item.get('status')}  {item.get('type')}  score={score}  run={item.get('run_id')}")
        print(f"    {item.get('hypothesis')}")
    return 0


def cmd_experiment_show(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    _print_json(load_experiment(root, args.experiment_id))
    return 0


def cmd_experiment_summary(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    _print_json(experiment_summary(root))
    return 0


def cmd_experiment_chart(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    data = experiment_chart_data(root, limit=args.limit)
    if args.out:
        write_json(Path(args.out), data)
        print(args.out)
    else:
        _print_json(data)
    return 0


def cmd_memory_fsm_list(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    items = MemoryFSMStore(root).list(state=args.state, limit=args.limit)
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("No memory FSM items recorded.")
        return 0
    for item in items:
        print(f"{item.get('memory_id')}  {item.get('state')}  conf={item.get('confidence')}  domain={item.get('domain')}")
        print(f"    {item.get('claim')}")
        if item.get('general_rule'):
            print(f"    rule: {item.get('general_rule')}")
    return 0


def cmd_memory_fsm_add(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    item = MemoryFSMStore(root).add(state=args.state, claim=args.claim, domain=args.domain, source="cli", confidence=args.confidence, general_rule=args.rule)
    _print_json(item)
    return 0


def cmd_memory_fsm_verify(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    result = MemoryFSMStore(root).verify(args.memory_id, command=args.command, workdir=args.workdir or root)
    _print_json(result)
    return 0 if result["status"] == "PASSED" else 2


def cmd_memory_fsm_promote(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    _print_json(MemoryFSMStore(root).promote(args.memory_id, rule=args.rule))
    return 0


def cmd_memory_fsm_coverage(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    _print_json(MemoryFSMStore(root).coverage())
    return 0


def cmd_provider_summary(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    _print_json(summarize_provider_usage(root))
    return 0


def cmd_eval_run(args: argparse.Namespace) -> int:
    root = find_project_root(args.root)
    ensure_layout(root)
    summary = run_builtin_evals(root)
    _print_json(summary)
    return 0 if summary["passed"] else 2



def _research_engine(args: argparse.Namespace, *, ensure_live: bool = True) -> ResearchEngine:
    engine = ResearchEngine.load(args.root, args.research_id)
    if ensure_live:
        ensure_observatory(engine.workspace.root, engine.workspace.research_id)
    return engine


def _research_summary(snapshot: dict[str, Any], engine: ResearchEngine | None = None) -> dict[str, Any]:
    result = {
        "research_id": snapshot.get("research_id"),
        "topic": snapshot.get("topic"),
        "run_status": snapshot.get("run_status"),
        "terminal_assessment": snapshot.get("terminal_assessment"),
        "goal_root_status": (snapshot.get("goal_evaluation") or {}).get("root_status"),
        "current_state_id": snapshot.get("current_state_id"),
        "progress": snapshot.get("progress"),
        "budget": snapshot.get("budget"),
        "frontier": [item.get("id") for item in snapshot.get("frontier") or []],
        "waiting": [
            item.get("experiment_id")
            for item in snapshot.get("waits") or []
            if item.get("status") == "PENDING"
        ],
        "next_wake_at": snapshot.get("next_wake_at"),
        "verifier_gaps": snapshot.get("verifier_gaps") or [],
        "contested_claims": snapshot.get("contested_claims") or [],
    }
    if engine is not None:
        result["report_path"] = str(engine.workspace.report_path)
        result["observatory_entry"] = str(observatory_entry_path(engine.workspace.root))
        live = live_observatory_url(engine.workspace.root)
        if live:
            result["observatory_url"] = live
    return result


def _research_brief(snapshot: dict[str, Any]) -> dict[str, Any]:
    budget = snapshot.get("budget") or {}
    return {
        "research_id": snapshot.get("research_id"),
        "run_status": snapshot.get("run_status"),
        "terminal_assessment": snapshot.get("terminal_assessment"),
        "goal_root_status": (snapshot.get("goal_evaluation") or {}).get("root_status"),
        "progress": snapshot.get("progress"),
        "attempts_remaining": budget.get("attempts_remaining"),
        "cost_units_remaining": budget.get("cost_units_remaining"),
        "frontier_size": len(snapshot.get("frontier") or []),
        "waiting_size": sum(1 for item in snapshot.get("waits") or [] if item.get("status") == "PENDING"),
        "next_wake_at": snapshot.get("next_wake_at"),
        "verifier_gaps": snapshot.get("verifier_gaps") or [],
        "contested_claims": snapshot.get("contested_claims") or [],
    }


def _verdict_brief(result: dict[str, Any]) -> dict[str, Any]:
    verdict = result.get("verdict") or {}
    snapshot = result.get("snapshot") or {}
    return {
        "verdict": verdict.get("status"),
        "reason_code": verdict.get("reason_code"),
        "claim_effects": [
            {"claim_id": effect.get("claim_id"), "status": effect.get("status"), "provisional": effect.get("provisional")}
            for effect in result.get("claim_effects") or []
        ],
        "run_status": snapshot.get("run_status"),
        "goal_root_status": (snapshot.get("goal_evaluation") or {}).get("root_status"),
        "contested_claims": snapshot.get("contested_claims") or [],
    }


def cmd_research_new(args: argparse.Namespace) -> int:
    engine = ResearchEngine.create(args.root, load_json_object(args.spec), actor=args.actor)
    ensure_observatory(engine.workspace.root, engine.workspace.research_id)
    snapshot = engine.snapshot()
    summary = _research_summary(snapshot, engine)
    hard_constraints = engine.task.get("hard_constraints") or []
    if hard_constraints:
        summary["warnings"] = [
            "hard_constraints are documentation only and are NOT machine-enforced; "
            "encode each one as a required claim or a verifier guardrail: "
            + "; ".join(str(x) for x in hard_constraints)
        ]
    _print_json(summary)
    return 0


def cmd_research_list(args: argparse.Namespace) -> int:
    items = ResearchWorkspace.list(args.root, limit=args.limit)
    if args.json:
        _print_json(items)
        return 0
    if not items:
        print("No Sisyfus research runs recorded.")
        return 0
    for item in items:
        print(
            f"{item.get('research_id')}  {item.get('status')}  "
            f"objective={item.get('objective_progress', '-')}  epistemic={item.get('epistemic_progress', '-')}"
        )
        print(f"    {item.get('topic')}")
        print(f"    {item.get('path')}")
    return 0


def cmd_research_status(args: argparse.Namespace) -> int:
    engine = _research_engine(args)
    snapshot = engine.refresh_waits(render=not args.no_report)
    if args.full:
        _print_json(snapshot)
    elif getattr(args, "brief", False):
        _print_json(_research_brief(snapshot))
    else:
        _print_json(_research_summary(snapshot, engine))
    return 0


def cmd_research_context(args: argparse.Namespace) -> int:
    _print_json(_research_engine(args).planner_context())
    return 0


def cmd_research_contract_add(args: argparse.Namespace) -> int:
    contract = _research_engine(args).add_contract(load_json_object(args.contract), actor=args.actor)
    _print_json(contract)
    return 0


def cmd_research_propose(args: argparse.Namespace) -> int:
    result = _research_engine(args).propose_experiment(
        load_json_object(args.experiment), actor=args.actor, auto_admit=not args.no_admit
    )
    if getattr(args, "brief", False):
        admission = result.get("admission") or {}
        _print_json(
            {
                "experiment_id": (result.get("experiment") or {}).get("id"),
                "accepted": admission.get("accepted"),
                "reason": admission.get("reason"),
            }
        )
    else:
        _print_json(result)
    return 0 if result["admission"].get("accepted") or args.no_admit else 3


def cmd_research_execute(args: argparse.Namespace) -> int:
    engine = _research_engine(args)
    result = engine.execute_experiment(args.experiment_id, workdir=args.workdir, actor=args.actor)
    if getattr(args, "brief", False):
        _print_json(_verdict_brief(result))
    else:
        _print_json(
            {
                "verdict": result["verdict"],
                "claim_effects": result["claim_effects"],
                "evidence": result["evidence"],
                "state": _research_summary(result["snapshot"], engine),
            }
        )
    return 0 if result["verdict"]["status"] == "PASS" else 2


def cmd_research_begin(args: argparse.Namespace) -> int:
    _print_json(_research_engine(args).begin_attempt(args.experiment_id, actor=args.actor))
    return 0


def cmd_research_settle(args: argparse.Namespace) -> int:
    engine = _research_engine(args)
    result = engine.settle_attempt(args.attempt_id, load_json_object(args.observation), actor=args.actor)
    if getattr(args, "brief", False):
        _print_json(_verdict_brief(result))
    else:
        _print_json(
            {
                "verdict": result["verdict"],
                "claim_effects": result["claim_effects"],
                "evidence": result["evidence"],
                "state": _research_summary(result["snapshot"], engine),
            }
        )
    return 0 if result["verdict"]["status"] == "PASS" else 2


def cmd_research_wake(args: argparse.Namespace) -> int:
    engine = _research_engine(args)
    waits_before = {
        item["experiment_id"]: item.get("status")
        for item in engine.snapshot().get("waits") or []
    }
    snapshot = engine.refresh_waits(now=args.now, actor=args.actor, render=not args.no_report)
    fired: list[str] = []
    expired: list[str] = []
    for item in snapshot.get("waits") or []:
        if waits_before.get(item["experiment_id"]) != "PENDING":
            continue
        if item.get("status") == "FIRED":
            fired.append(item["experiment_id"])
        elif item.get("status") == "EXPIRED":
            expired.append(item["experiment_id"])
    executed = []
    if args.execute:
        released = [item["experiment_id"] for item in snapshot.get("waits") or [] if item.get("released")]
        for experiment_id in fired + [item for item in released if item in expired]:
            experiment = snapshot["experiments"].get(experiment_id) or {}
            if experiment.get("status") != "ADMITTED" or (experiment.get("action") or {}).get("kind") != "command":
                continue
            result = engine.execute_experiment(experiment_id, actor=args.actor)
            executed.append(
                {
                    "experiment_id": experiment_id,
                    "verdict": result["verdict"]["status"],
                    "reason_code": result["verdict"].get("reason_code"),
                }
            )
        if executed:
            snapshot = engine.snapshot()
    _print_json(
        {
            "research_id": engine.workspace.research_id,
            "fired": fired,
            "expired": expired,
            "executed": executed,
            "next_wake_at": snapshot.get("next_wake_at"),
            "run_status": snapshot.get("run_status"),
            "terminal_assessment": snapshot.get("terminal_assessment"),
            "frontier": [item.get("id") for item in snapshot.get("frontier") or []],
        }
    )
    return 0


def cmd_research_recover(args: argparse.Namespace) -> int:
    engine = _research_engine(args)
    recovered = engine.recover_stranded(actor=args.actor)
    _print_json({"research_id": engine.workspace.research_id, "recovered_attempts": len(recovered), "state": _research_summary(engine.sync(), engine)})
    return 0


def cmd_research_prune(args: argparse.Namespace) -> int:
    engine = _research_engine(args)
    snapshot = engine.prune_experiment(args.experiment_id, reason=args.reason, actor=args.actor)
    _print_json(_research_summary(snapshot, engine))
    return 0


def cmd_research_report(args: argparse.Namespace) -> int:
    engine = _research_engine(args)
    path = engine.render_report(open_browser=args.open, log_event=args.log_event)
    print(path)
    return 0


def cmd_research_serve(args: argparse.Namespace) -> int:
    engine = _research_engine(args, ensure_live=False)
    root = engine.workspace.root
    try:
        port = resolve_serve_port(root, engine.workspace.research_id, args.port)
    except AlreadyServing as running:
        print(f"Sisyfus Research Observatory already live at {running.url}")
        return 0
    try:
        server, url = engine.serve_report(
            host=args.host, port=port, open_browser=args.open, verbose=args.verbose
        )
    except OSError:
        if args.port is not None:
            raise
        # Bind failure usually means a concurrent spawn won the stable port
        # between our resolve and bind — if its daemon serves this run, defer.
        state = read_live_state(root)
        rival = live_observatory_url(root)
        if rival is not None and (state or {}).get("research_id") == engine.workspace.research_id:
            print(f"Sisyfus Research Observatory already live at {rival}")
            return 0
        # Otherwise a foreign process holds the port; an ephemeral port still
        # gives a live page, and the entry page re-renders with the real port.
        server, url = engine.serve_report(
            host=args.host, port=0, open_browser=args.open, verbose=args.verbose
        )
    write_live_state(
        root,
        host=args.host,
        port=int(server.server_address[1]),
        research_id=engine.workspace.research_id,
    )
    engine.sync(render=True)
    print(f"Sisyfus Research Observatory listening on {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nResearch Observatory stopped.")
    finally:
        server.server_close()
        clear_live_state(root, pid=os.getpid())
    return 0


def cmd_research_replay(args: argparse.Namespace) -> int:
    result = _research_engine(args).verify_replay()
    _print_json(result)
    return 0 if result["deterministic"] else 2


def cmd_research_reproduce(args: argparse.Namespace) -> int:
    result = _research_engine(args).reproduce_evidence(
        args.evidence_id, workdir=args.workdir, actor=args.actor
    )
    _print_json(result)
    return 0 if result["code_intact"] and result["verdict_stable"] else 2


def cmd_research_lesson_add(args: argparse.Namespace) -> int:
    _print_json(_research_engine(args).add_lesson(load_json_object(args.lesson), actor=args.actor))
    return 0


def cmd_research_lesson_evidence_add(args: argparse.Namespace) -> int:
    _print_json(
        _research_engine(args).add_lesson_evidence(
            args.lesson_id, list(args.evidence_ids), actor=args.actor
        )
    )
    return 0


def cmd_research_lesson_promote(args: argparse.Namespace) -> int:
    _print_json(
        _research_engine(args).promote_lesson(
            args.lesson_id, actor=args.actor, min_independent_experiments=args.min_experiments
        )
    )
    return 0


def cmd_research_lesson_revoke(args: argparse.Namespace) -> int:
    _print_json(_research_engine(args).revoke_lesson(args.lesson_id, reason=args.reason, actor=args.actor))
    return 0


def cmd_research_lesson_stats(args: argparse.Namespace) -> int:
    engine = _research_engine(args)
    _print_json(
        {
            "efficacy": engine.lesson_efficacy(),
            "global_lessons": engine.global_lessons(exclude_current=False, with_efficacy=True),
        }
    )
    return 0


def cmd_research_pause(args: argparse.Namespace) -> int:
    engine = _research_engine(args)
    _print_json(_research_summary(engine.pause(actor=args.actor, reason=args.reason), engine))
    return 0


def cmd_research_resume(args: argparse.Namespace) -> int:
    engine = _research_engine(args)
    _print_json(_research_summary(engine.resume(actor=args.actor), engine))
    return 0


def cmd_research_finalize(args: argparse.Namespace) -> int:
    engine = _research_engine(args)
    snapshot = engine.finalize(status=args.status, actor=args.actor, reason=args.reason)
    _print_json(_research_summary(snapshot, engine))
    return 0 if snapshot["run_status"] == "SOLVED" else 2


def cmd_research_demo(args: argparse.Namespace) -> int:
    engine = build_demo(args.root)
    snapshot = engine.snapshot()
    _print_json(_research_summary(snapshot, engine))
    return 0 if snapshot["run_status"] == "SOLVED" else 2

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sisyfus", description="Local-first agent loop orchestrator")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("init", help="initialize .sisyfus layout")
    p.add_argument("--root", default=None)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p_goal = sub.add_parser("goal", help="goal operations")
    goal_sub = p_goal.add_subparsers(dest="goal_command", required=True)
    p_new = goal_sub.add_parser("new", help="create a GoalSpec template")
    p_new.add_argument("id")
    p_new.add_argument("--objective", required=True)
    p_new.add_argument("--command", action="append", help="deterministic done_when command; may be repeated")
    p_new.add_argument("--max-rounds", type=int, default=3)
    p_new.add_argument("--task-type", default="implementation")
    p_new.add_argument("--out")
    p_new.add_argument("--root")
    p_new.add_argument("--print-json", action="store_true")
    p_new.set_defaults(func=cmd_goal_new)

    p = sub.add_parser("run", help="run one GoalSpec as one compacted session")
    p.add_argument("goal")
    p.add_argument("--root")
    p.add_argument("--adapter", choices=["mock", "command"], default="mock")
    p.add_argument("--agent-command", help="shell command used by command adapter; may use {model}, {model_profile}, {reasoning}, {prompt_path}")
    p.add_argument("--apply-distill", action="store_true", help="promote distill candidates into canonical memory/tasks after session ends")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("verify", help="run deterministic verifier only")
    p.add_argument("goal")
    p.add_argument("--root")
    p.add_argument("--workdir")
    p.add_argument("--run-dir")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("distill", help="distill a run directory")
    p.add_argument("run_dir")
    p.add_argument("--root")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_distill)

    p = sub.add_parser("promote", help="promote repeated failures into skill candidates")
    p.add_argument("--root")
    p.add_argument("--threshold", type=int, default=2)
    p.set_defaults(func=cmd_promote)

    p = sub.add_parser("inbox", help="show open human-review tasks")
    p.add_argument("--root")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_inbox)

    p = sub.add_parser("memory", help="show memory files")
    mem_sub = p.add_subparsers(dest="memory_command", required=True)
    p_show = mem_sub.add_parser("show")
    p_show.add_argument("kind", choices=["facts", "failures", "hypotheses", "open-tasks"])
    p_show.add_argument("--root")
    p_show.add_argument("--json", action="store_true")
    p_show.set_defaults(func=cmd_memory)

    p_monitor = sub.add_parser("monitor", help="reusable deterministic monitor operations")
    mon_sub = p_monitor.add_subparsers(dest="monitor_command", required=True)
    p_list = mon_sub.add_parser("list", help="list builtin and custom monitors")
    p_list.add_argument("--root")
    p_list.add_argument("--json", action="store_true")
    p_list.add_argument("--custom-only", action="store_true")
    p_list.set_defaults(func=cmd_monitor_list)
    p_suggest = mon_sub.add_parser("suggest", help="suggest monitors for an ops task without calling a model")
    p_suggest.add_argument("task")
    p_suggest.add_argument("--root")
    p_suggest.add_argument("--top-k", type=int, default=5)
    p_suggest.set_defaults(func=cmd_monitor_suggest)
    p_run_mon = mon_sub.add_parser("run", help="run a monitor with KEY=VALUE params")
    p_run_mon.add_argument("id")
    p_run_mon.add_argument("--root")
    p_run_mon.add_argument("--workdir")
    p_run_mon.add_argument("--param", action="append")
    p_run_mon.set_defaults(func=cmd_monitor_run)
    p_add = mon_sub.add_parser("add", help="register a custom command monitor")
    p_add.add_argument("id")
    p_add.add_argument("--root")
    p_add.add_argument("--description", required=True)
    p_add.add_argument("--command", required=True)
    p_add.add_argument("--tag", action="append")
    p_add.set_defaults(func=cmd_monitor_add)

    p_ops = sub.add_parser("ops", help="route repeated agentops tasks to reusable monitors")
    ops_sub = p_ops.add_subparsers(dest="ops_command", required=True)
    p_route = ops_sub.add_parser("route", help="route and run an ops task if a monitor matches; otherwise create a write-monitor task")
    p_route.add_argument("task")
    p_route.add_argument("--root")
    p_route.add_argument("--workdir")
    p_route.add_argument("--threshold", type=float, default=2.0)
    p_route.add_argument("--param", action="append")
    p_route.set_defaults(func=cmd_ops_route)

    p_model = sub.add_parser("model", help="model routing policy operations")
    model_sub = p_model.add_subparsers(dest="model_command", required=True)
    p_policy = model_sub.add_parser("policy", help="show or initialize model policy")
    p_policy.add_argument("--root")
    p_policy.add_argument("--write-default", action="store_true")
    p_policy.add_argument("--force", action="store_true")
    p_policy.set_defaults(func=cmd_model_policy)
    p_route = model_sub.add_parser("route", help="resolve model profile for a task type / role")
    p_route.add_argument("--root")
    p_route.add_argument("--goal")
    p_route.add_argument("--task-type", default=None)
    p_route.add_argument("--role", default="implementer")
    p_route.add_argument("--profile")
    p_route.add_argument("--model")
    p_route.set_defaults(func=cmd_model_route)

    p_session = sub.add_parser("session", help="session compaction operations")
    sess_sub = p_session.add_subparsers(dest="session_command", required=True)
    p_list = sess_sub.add_parser("list", help="list recent one-task sessions")
    p_list.add_argument("--root")
    p_list.add_argument("--limit", type=int, default=10)
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_session_list)
    p_context = sess_sub.add_parser("context", help="print compact recent session context that future sessions read")
    p_context.add_argument("--root")
    p_context.add_argument("--limit", type=int, default=3)
    p_context.add_argument("--max-chars", type=int, default=12000)
    p_context.set_defaults(func=cmd_session_context)

    p_beam = sub.add_parser("beam", help="bounded beam-search / sub-session research operations")
    beam_sub = p_beam.add_subparsers(dest="beam_command", required=True)
    p_bt = beam_sub.add_parser("template", help="create a Beam GoalSpec template")
    p_bt.add_argument("id")
    p_bt.add_argument("--objective", required=True)
    p_bt.add_argument("--branch", action="append", help="seed branch direction; may be repeated")
    p_bt.add_argument("--width", type=int, default=3)
    p_bt.add_argument("--max-depth", type=int, default=1)
    p_bt.add_argument("--max-children-per-node", type=int, default=3)
    p_bt.add_argument("--max-total-sessions", type=int, default=9)
    p_bt.add_argument("--task-type", default="beam_research")
    p_bt.add_argument("--branch-task-type", default="factor_research")
    p_bt.add_argument("--command", action="append", help="deterministic command inherited by child branches")
    p_bt.add_argument("--max-rounds", type=int, default=1)
    p_bt.add_argument("--out")
    p_bt.add_argument("--root")
    p_bt.add_argument("--print-json", action="store_true")
    p_bt.set_defaults(func=cmd_beam_template)
    p_brun = beam_sub.add_parser("run", help="run a bounded beam search from a Beam GoalSpec")
    p_brun.add_argument("goal")
    p_brun.add_argument("--root")
    p_brun.add_argument("--adapter", choices=["mock", "command"], default="mock")
    p_brun.add_argument("--agent-command")
    p_brun.add_argument("--apply-distill", action="store_true")
    p_brun.set_defaults(func=cmd_beam_run)
    p_blist = beam_sub.add_parser("list", help="list recent beam runs")
    p_blist.add_argument("--root")
    p_blist.add_argument("--limit", type=int, default=20)
    p_blist.add_argument("--json", action="store_true")
    p_blist.set_defaults(func=cmd_beam_list)
    p_bstatus = beam_sub.add_parser("status", help="show one beam tree / scoreboard")
    p_bstatus.add_argument("beam_id")
    p_bstatus.add_argument("--root")
    p_bstatus.set_defaults(func=cmd_beam_status)
    p_bctx = beam_sub.add_parser("context", help="print compact beam context for a coordinator session")
    p_bctx.add_argument("beam_id")
    p_bctx.add_argument("--root")
    p_bctx.add_argument("--max-chars", type=int, default=30000)
    p_bctx.set_defaults(func=cmd_beam_context)

    p_review = sub.add_parser("review", help="human review annotations for sessions, claims, beams, and AI conclusions")
    review_sub = p_review.add_subparsers(dest="review_command", required=True)
    p_list = review_sub.add_parser("list", help="list human annotations")
    p_list.add_argument("--root")
    p_list.add_argument("--target-type")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_review_list)
    p_claims = review_sub.add_parser("claims", help="list claims extracted from session distills with human verdict overlay")
    p_claims.add_argument("--root")
    p_claims.add_argument("--limit", type=int, default=100)
    p_claims.add_argument("--limit-sessions", type=int, default=None)
    p_claims.add_argument("--beam-id")
    p_claims.add_argument("--verdict", choices=["correct", "wrong", "uncertain", "needs_followup", "accepted", "rejected", "stale", "direction"])
    p_claims.add_argument("--json", action="store_true")
    p_claims.set_defaults(func=cmd_review_claims)
    p_ann = review_sub.add_parser("annotate", help="mark a claim/session/beam/node/task as correct, wrong, uncertain, accepted, or needing follow-up")
    p_ann.add_argument("target_id")
    p_ann.add_argument("--root")
    p_ann.add_argument("--target-type", default="claim", choices=["claim", "session", "task", "goal", "run", "beam", "beam_node"])
    p_ann.add_argument("--verdict", required=True, choices=["correct", "wrong", "uncertain", "needs_followup", "accepted", "rejected", "stale", "direction"])
    p_ann.add_argument("--note", default="")
    p_ann.add_argument("--next-action")
    p_ann.add_argument("--claim")
    p_ann.add_argument("--run-id")
    p_ann.add_argument("--goal-id")
    p_ann.add_argument("--created-by", default="human")
    p_ann.add_argument("--create-task", action="store_true")
    p_ann.set_defaults(func=cmd_review_annotate)
    p_ctx = review_sub.add_parser("context", help="print human review context loaded into future sessions")
    p_ctx.add_argument("--root")
    p_ctx.add_argument("--max-chars", type=int, default=10000)
    p_ctx.set_defaults(func=cmd_review_context)

    p_guidance = sub.add_parser("guidance", help="human steering notes for future Sisyfus sessions")
    guidance_sub = p_guidance.add_subparsers(dest="guidance_command", required=True)
    p_add_g = guidance_sub.add_parser("add", help="add human guidance / next direction")
    p_add_g.add_argument("text")
    p_add_g.add_argument("--root")
    p_add_g.add_argument("--scope", default="project")
    p_add_g.add_argument("--goal-id")
    p_add_g.add_argument("--run-id")
    p_add_g.add_argument("--priority", default="P2")
    p_add_g.add_argument("--tag", action="append")
    p_add_g.add_argument("--create-task", action="store_true")
    p_add_g.set_defaults(func=cmd_guidance_add)
    p_list_g = guidance_sub.add_parser("list", help="list active human guidance")
    p_list_g.add_argument("--root")
    p_list_g.add_argument("--limit", type=int, default=50)
    p_list_g.add_argument("--include-archived", action="store_true")
    p_list_g.add_argument("--json", action="store_true")
    p_list_g.set_defaults(func=cmd_guidance_list)

    p_rubric = sub.add_parser("rubric", help="rubric / Outcomes grader operations")
    rubric_sub = p_rubric.add_subparsers(dest="rubric_command", required=True)
    p_rl = rubric_sub.add_parser("list", help="list built-in/project rubrics")
    p_rl.add_argument("--root")
    p_rl.add_argument("--json", action="store_true")
    p_rl.set_defaults(func=cmd_rubric_list)
    p_rs = rubric_sub.add_parser("show", help="show one rubric")
    p_rs.add_argument("id")
    p_rs.add_argument("--root")
    p_rs.set_defaults(func=cmd_rubric_show)
    p_ri = rubric_sub.add_parser("install", help="write built-in rubrics into .sisyfus/rubrics")
    p_ri.add_argument("--root")
    p_ri.add_argument("--force", action="store_true")
    p_ri.set_defaults(func=cmd_rubric_install)
    p_rg = rubric_sub.add_parser("grade", help="grade a run directory with a rubric")
    p_rg.add_argument("id")
    p_rg.add_argument("run_dir")
    p_rg.add_argument("--root")
    p_rg.set_defaults(func=cmd_rubric_grade)

    p_out = sub.add_parser("outcome", help="Outcomes-style rubric loop inspection")
    out_sub = p_out.add_subparsers(dest="outcome_command", required=True)
    p_og = out_sub.add_parser("grade", help="grade a run dir against a GoalSpec outcome/rubric")
    p_og.add_argument("goal")
    p_og.add_argument("run_dir")
    p_og.add_argument("--root")
    p_og.set_defaults(func=cmd_outcome_grade)
    p_ol = out_sub.add_parser("list", help="list recorded outcome grades")
    p_ol.add_argument("--root")
    p_ol.add_argument("--limit", type=int, default=100)
    p_ol.add_argument("--json", action="store_true")
    p_ol.set_defaults(func=cmd_outcome_list)
    p_os = out_sub.add_parser("show", help="show one run outcome")
    p_os.add_argument("run_id")
    p_os.add_argument("--root")
    p_os.set_defaults(func=cmd_outcome_show)

    p_exp = sub.add_parser("experiment", help="experiment-golf ledger operations")
    exp_sub = p_exp.add_subparsers(dest="experiment_command", required=True)
    p_el = exp_sub.add_parser("list", help="list recorded experiments")
    p_el.add_argument("--root")
    p_el.add_argument("--limit", type=int, default=100)
    p_el.add_argument("--status")
    p_el.add_argument("--beam-id")
    p_el.add_argument("--json", action="store_true")
    p_el.set_defaults(func=cmd_experiment_list)
    p_es = exp_sub.add_parser("show", help="show one experiment")
    p_es.add_argument("experiment_id")
    p_es.add_argument("--root")
    p_es.set_defaults(func=cmd_experiment_show)
    p_sum = exp_sub.add_parser("summary", help="summarize experiment ledger")
    p_sum.add_argument("--root")
    p_sum.set_defaults(func=cmd_experiment_summary)
    p_ch = exp_sub.add_parser("chart", help="export experiment-golf chart data")
    p_ch.add_argument("--root")
    p_ch.add_argument("--limit", type=int, default=500)
    p_ch.add_argument("--out")
    p_ch.set_defaults(func=cmd_experiment_chart)

    # Additional memory lifecycle commands are namespaced under `memory fsm-*`
    p_flist = mem_sub.add_parser("fsm-list", help="list fail->investigate->verify->rule memory items")
    p_flist.add_argument("--root")
    p_flist.add_argument("--state")
    p_flist.add_argument("--limit", type=int, default=100)
    p_flist.add_argument("--json", action="store_true")
    p_flist.set_defaults(func=cmd_memory_fsm_list)
    p_fadd = mem_sub.add_parser("fsm-add", help="add a memory FSM item")
    p_fadd.add_argument("claim")
    p_fadd.add_argument("--root")
    p_fadd.add_argument("--state", default="failure_note")
    p_fadd.add_argument("--domain", default="project")
    p_fadd.add_argument("--confidence", type=float, default=0.6)
    p_fadd.add_argument("--rule")
    p_fadd.set_defaults(func=cmd_memory_fsm_add)
    p_fver = mem_sub.add_parser("fsm-verify", help="verify a memory item with a command")
    p_fver.add_argument("memory_id")
    p_fver.add_argument("--command", required=True)
    p_fver.add_argument("--root")
    p_fver.add_argument("--workdir")
    p_fver.set_defaults(func=cmd_memory_fsm_verify)
    p_fprom = mem_sub.add_parser("fsm-promote", help="promote a verified memory item into a general rule")
    p_fprom.add_argument("memory_id")
    p_fprom.add_argument("--root")
    p_fprom.add_argument("--rule")
    p_fprom.set_defaults(func=cmd_memory_fsm_promote)
    p_fcov = mem_sub.add_parser("fsm-coverage", help="show memory lifecycle coverage metrics")
    p_fcov.add_argument("--root")
    p_fcov.set_defaults(func=cmd_memory_fsm_coverage)

    p_provider = sub.add_parser("provider", help="provider/model usage accounting")
    prov_sub = p_provider.add_subparsers(dest="provider_command", required=True)
    p_ps = prov_sub.add_parser("summary", help="summarize requested/actual model usage and cost estimates")
    p_ps.add_argument("--root")
    p_ps.set_defaults(func=cmd_provider_summary)

    p_research = sub.add_parser("research", help="event-sourced branching research skill")
    research_sub = p_research.add_subparsers(dest="research_command", required=True)

    p_rnew = research_sub.add_parser("new", help="create a research run from a TaskSpec JSON")
    p_rnew.add_argument("spec")
    p_rnew.add_argument("--root")
    p_rnew.add_argument("--actor", default="user")
    p_rnew.set_defaults(func=cmd_research_new)

    p_rlist = research_sub.add_parser("list", help="list research runs")
    p_rlist.add_argument("--root")
    p_rlist.add_argument("--limit", type=int, default=100)
    p_rlist.add_argument("--json", action="store_true")
    p_rlist.set_defaults(func=cmd_research_list)

    p_rstatus = research_sub.add_parser("status", help="show the current replayed research state")
    p_rstatus.add_argument("research_id", nargs="?", default="latest")
    p_rstatus.add_argument("--root")
    p_rstatus.add_argument("--full", action="store_true")
    p_rstatus.add_argument("--brief", action="store_true", help="compact agent-friendly summary")
    p_rstatus.add_argument("--no-report", action="store_true")
    p_rstatus.set_defaults(func=cmd_research_status)

    p_rctx = research_sub.add_parser("context", help="emit bounded planner context")
    p_rctx.add_argument("research_id", nargs="?", default="latest")
    p_rctx.add_argument("--root")
    p_rctx.set_defaults(func=cmd_research_context)

    p_rca = research_sub.add_parser("contract-add", help="append a versioned verifier contract")
    p_rca.add_argument("research_id")
    p_rca.add_argument("contract")
    p_rca.add_argument("--root")
    p_rca.add_argument("--actor", default="user")
    p_rca.set_defaults(func=cmd_research_contract_add)

    p_rprop = research_sub.add_parser("propose", help="propose and admission-check an experiment")
    p_rprop.add_argument("research_id")
    p_rprop.add_argument("experiment")
    p_rprop.add_argument("--root")
    p_rprop.add_argument("--actor", default="planner")
    p_rprop.add_argument("--no-admit", action="store_true")
    p_rprop.add_argument("--brief", action="store_true", help="compact agent-friendly summary")
    p_rprop.set_defaults(func=cmd_research_propose)

    p_rexec = research_sub.add_parser("execute", help="execute an admitted command experiment")
    p_rexec.add_argument("research_id")
    p_rexec.add_argument("experiment_id")
    p_rexec.add_argument("--root")
    p_rexec.add_argument("--workdir")
    p_rexec.add_argument("--actor", default="command-executor")
    p_rexec.add_argument("--brief", action="store_true", help="compact agent-friendly summary")
    p_rexec.set_defaults(func=cmd_research_execute)

    p_rbegin = research_sub.add_parser("begin", help="reserve/start an external or manual attempt")
    p_rbegin.add_argument("research_id")
    p_rbegin.add_argument("experiment_id")
    p_rbegin.add_argument("--root")
    p_rbegin.add_argument("--actor", default="executor")
    p_rbegin.set_defaults(func=cmd_research_begin)

    p_rsettle = research_sub.add_parser("settle", help="record an observation and issue a verifier verdict")
    p_rsettle.add_argument("research_id")
    p_rsettle.add_argument("attempt_id")
    p_rsettle.add_argument("observation")
    p_rsettle.add_argument("--root")
    p_rsettle.add_argument("--actor", default="verifier")
    p_rsettle.add_argument("--brief", action="store_true", help="compact agent-friendly summary")
    p_rsettle.set_defaults(func=cmd_research_settle)

    p_rwake = research_sub.add_parser("wake", help="settle due time waits and report next_wake_at")
    p_rwake.add_argument("research_id", nargs="?", default="latest")
    p_rwake.add_argument("--root")
    p_rwake.add_argument("--now", help="ISO timestamp override for deterministic wakes")
    p_rwake.add_argument("--execute", action="store_true", help="execute command experiments released by this wake")
    p_rwake.add_argument("--actor", default="wake")
    p_rwake.add_argument("--no-report", action="store_true")
    p_rwake.set_defaults(func=cmd_research_wake)

    p_rrecover = research_sub.add_parser("recover", help="mark stranded attempts ERROR and requeue")
    p_rrecover.add_argument("research_id", nargs="?", default="latest")
    p_rrecover.add_argument("--root")
    p_rrecover.add_argument("--actor", default="recovery")
    p_rrecover.set_defaults(func=cmd_research_recover)

    p_rprune = research_sub.add_parser("prune", help="prune a non-running experiment branch")
    p_rprune.add_argument("research_id")
    p_rprune.add_argument("experiment_id")
    p_rprune.add_argument("--reason", required=True)
    p_rprune.add_argument("--root")
    p_rprune.add_argument("--actor", default="user")
    p_rprune.set_defaults(func=cmd_research_prune)

    p_rreport = research_sub.add_parser("report", help="render/open the HTML Observatory")
    p_rreport.add_argument("research_id", nargs="?", default="latest")
    p_rreport.add_argument("--root")
    p_rreport.add_argument("--open", action="store_true")
    p_rreport.add_argument("--log-event", action="store_true")
    p_rreport.set_defaults(func=cmd_research_report)

    p_rserve = research_sub.add_parser("serve", help="serve a live-refreshing local HTML Observatory")
    p_rserve.add_argument("research_id", nargs="?", default="latest")
    p_rserve.add_argument("--root")
    p_rserve.add_argument("--host", default="127.0.0.1")
    p_rserve.add_argument(
        "--port", type=int, default=None,
        help="explicit port; default is a stable per-project port derived from the root path",
    )
    p_rserve.add_argument("--open", action="store_true")
    p_rserve.add_argument("--verbose", action="store_true")
    p_rserve.set_defaults(func=cmd_research_serve)

    p_rreplay = research_sub.add_parser("replay", help="verify the hash chain and deterministic replay")
    p_rreplay.add_argument("research_id", nargs="?", default="latest")
    p_rreplay.add_argument("--root")
    p_rreplay.set_defaults(func=cmd_research_replay)

    p_rrepro = research_sub.add_parser(
        "reproduce", help="re-run one command evidence's hashed measurement and compare verdicts"
    )
    p_rrepro.add_argument("research_id")
    p_rrepro.add_argument("evidence_id")
    p_rrepro.add_argument("--workdir")
    p_rrepro.add_argument("--root")
    p_rrepro.add_argument("--actor", default="reproducer")
    p_rrepro.set_defaults(func=cmd_research_reproduce)

    p_rla = research_sub.add_parser("lesson-add", help="create a scoped lesson candidate")
    p_rla.add_argument("research_id")
    p_rla.add_argument("lesson")
    p_rla.add_argument("--root")
    p_rla.add_argument("--actor", default="reviewer")
    p_rla.set_defaults(func=cmd_research_lesson_add)

    p_rlea = research_sub.add_parser("lesson-evidence-add", help="append later-earned evidence to an existing lesson")
    p_rlea.add_argument("research_id")
    p_rlea.add_argument("lesson_id")
    p_rlea.add_argument("evidence_ids", nargs="+")
    p_rlea.add_argument("--root")
    p_rlea.add_argument("--actor", default="reviewer")
    p_rlea.set_defaults(func=cmd_research_lesson_evidence_add)

    p_rlp = research_sub.add_parser("lesson-promote", help="promote a grounded lesson candidate")
    p_rlp.add_argument("research_id")
    p_rlp.add_argument("lesson_id")
    p_rlp.add_argument("--root")
    p_rlp.add_argument("--actor", default="human")
    p_rlp.add_argument("--min-experiments", type=int, default=2)
    p_rlp.set_defaults(func=cmd_research_lesson_promote)

    p_rlr = research_sub.add_parser("lesson-revoke", help="revoke a contradicted lesson")
    p_rlr.add_argument("research_id")
    p_rlr.add_argument("lesson_id")
    p_rlr.add_argument("--reason", required=True)
    p_rlr.add_argument("--root")
    p_rlr.add_argument("--actor", default="human")
    p_rlr.set_defaults(func=cmd_research_lesson_revoke)

    p_rls = research_sub.add_parser("lesson-stats", help="cross-run lesson citation and verdict statistics")
    p_rls.add_argument("research_id", nargs="?", default="latest")
    p_rls.add_argument("--root")
    p_rls.set_defaults(func=cmd_research_lesson_stats)

    p_rpause = research_sub.add_parser("pause", help="pause a research run")
    p_rpause.add_argument("research_id")
    p_rpause.add_argument("--reason", default="")
    p_rpause.add_argument("--root")
    p_rpause.add_argument("--actor", default="user")
    p_rpause.set_defaults(func=cmd_research_pause)

    p_rresume = research_sub.add_parser("resume", help="resume a paused research run")
    p_rresume.add_argument("research_id")
    p_rresume.add_argument("--root")
    p_rresume.add_argument("--actor", default="user")
    p_rresume.set_defaults(func=cmd_research_resume)

    p_rfinal = research_sub.add_parser("finalize", help="run terminal finalization")
    p_rfinal.add_argument("research_id")
    p_rfinal.add_argument("--status", default="auto", choices=["auto", "solved", "blocked", "exhausted", "budget_exhausted", "failed"])
    p_rfinal.add_argument("--reason", default="")
    p_rfinal.add_argument("--root")
    p_rfinal.add_argument("--actor", default="terminal-evaluator")
    p_rfinal.set_defaults(func=cmd_research_finalize)

    p_rdemo = research_sub.add_parser("demo", help="create a solved branch/repetition demo and HTML report")
    p_rdemo.add_argument("--root")
    p_rdemo.set_defaults(func=cmd_research_demo)

    p_eval = sub.add_parser("eval", help="eval operations")
    eval_sub = p_eval.add_subparsers(dest="eval_command", required=True)
    p_run = eval_sub.add_parser("run", help="run built-in evals")
    p_run.add_argument("--root")
    p_run.set_defaults(func=cmd_eval_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "version", False):
        from . import __version__
        print(__version__)
        return 0
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return int(args.func(args))
    except (ValueError, KeyError, RuntimeError, FileNotFoundError, json.JSONDecodeError) as exc:
        import os
        import sys

        if os.environ.get("SISYFUS_DEBUG"):
            raise
        message = str(exc) if not isinstance(exc, KeyError) else str(exc.args[0] if exc.args else exc)
        print(
            json.dumps({"error": {"type": type(exc).__name__, "message": message}}, indent=2),
            file=sys.stderr,
        )
        return 1
