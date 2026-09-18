from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from ..research_v2.engine import ResearchEngine
from ..research_v2.workspace import atomic_write_json
from .controller import ResearchOS, configuration, configure, export_history
from .demo import run_demo
from .judgments import JevJudge
from .lab import optimize, promote, record_candidate, validate_fresh_trials
from .proposals import propose_next
from .models import SOP
from .policy import SchedulingPolicy


def load(path: str) -> Any:
    return json.loads(Path(path).read_text())


def dispatch(args: argparse.Namespace) -> int:
    if args.os_command == "demo":
        result = run_demo(Path(args.workspace))
    elif args.os_command == "optimize":
        result = optimize([load(p) for p in args.train], [load(p) for p in args.search], [load(p) for p in args.holdout], budget=args.budget)
        atomic_write_json(Path(args.output), result)
    else:
        engine = ResearchEngine.load(args.root, args.research)
        if args.os_command == "frontier":
            result = ResearchOS(engine).frontier()
        elif args.os_command == "approve":
            if not args.allow_local_commands:
                raise ValueError("review commands/code_paths and supply --allow-local-commands to approve")
            policy = SchedulingPolicy.load(load(args.policy)) if args.policy else SchedulingPolicy()
            if args.judgment_weight is not None:
                policy = replace(policy, judgment_weight=args.judgment_weight)
            result = configure(engine, policy=policy, sop=SOP(), replay_mode=args.replay_mode)
        elif args.os_command == "run":
            if args.judge == "jev":
                if not configuration(engine)["policy"]["judgment_weight"]:
                    raise ValueError("approve a positive --judgment-weight before using the paid Jev adapter")
                # Install the optional SDK and configure its retry/timeouts for your deployment.
                from typesafe_sdk import TypeSafeClient
                with TypeSafeClient() as client:
                    result = asdict(ResearchOS(engine, judge=JevJudge(client)).run(max_steps=args.max_steps, allow_local_commands=args.allow_local_commands))
            else:
                result = asdict(ResearchOS(engine).run(max_steps=args.max_steps, allow_local_commands=args.allow_local_commands))
        elif args.os_command == "export":
            result = export_history(engine)
            atomic_write_json(Path(args.output), result)
        elif args.os_command == "propose":
            if not args.allow_local_planner:
                raise PermissionError("local proposal worker requires --allow-local-planner")
            from ..autonomy.adapters import CommandPlanner
            planner = CommandPlanner(args.planner_command, workspace=engine.workspace.root, timeout_seconds=args.timeout_seconds)
            result = propose_next(engine, planner, limit=args.limit)
        elif args.os_command in {"validate-policy", "promote"}:
            report = load(args.report)
            baseline = [ResearchEngine.load(p) for p in args.baseline_roots]
            challenger = [ResearchEngine.load(p) for p in args.challenger_roots]
            if args.os_command == "promote":
                result = promote(engine, report, baseline, challenger, approver=args.approver)
            else:
                result = validate_fresh_trials(report, baseline, challenger)
        elif args.os_command == "stage":
            result = {"event_hash": record_candidate(engine, load(args.report)), "status": "REPLAY_ONLY"}
        else:
            raise ValueError("unknown Research OS command")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


def populate(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="os_command", required=True)
    demo = sub.add_parser("demo", help="run real bounded arithmetic evaluations and replay policy fitting")
    demo.add_argument("--workspace", required=True)
    demo.set_defaults(func=dispatch)
    opt = sub.add_parser("optimize", help="train/search/holdout replay; output an advisory candidate only")
    for split in ("train", "search", "holdout"):
        opt.add_argument("--" + split, required=True, nargs="+")
    opt.add_argument("--budget", type=float, required=True)
    opt.add_argument("--output", required=True)
    opt.set_defaults(func=dispatch)
    for name in ("frontier", "approve", "run", "propose", "export", "stage", "validate-policy", "promote"):
        p = sub.add_parser(name)
        p.add_argument("--root")
        p.add_argument("--research", default="latest")
        p.set_defaults(func=dispatch)
        if name in {"approve", "run"}:
            p.add_argument("--allow-local-commands", action="store_true", help="explicit local execution permission; not OS isolation")
        if name == "approve":
            p.add_argument("--judgment-weight", type=float, help="explicit advisory judge weight; default disabled")
            p.add_argument("--policy", help="SchedulingPolicy JSON for an operator-authorized trial")
            p.add_argument("--replay-mode", choices=("prefix", "independent"), default="prefix")
        elif name == "run":
            p.add_argument("--max-steps", type=int, default=10)
            p.add_argument("--judge", choices=("none", "jev"), default="none")
        elif name == "export":
            p.add_argument("--output", required=True)
        elif name == "propose":
            p.add_argument("--planner-command", required=True)
            p.add_argument("--allow-local-planner", action="store_true")
            p.add_argument("--limit", type=int, default=4)
            p.add_argument("--timeout-seconds", type=float, default=120)
        elif name in {"stage", "validate-policy", "promote"}:
            p.add_argument("--report", required=True)
            if name != "stage":
                p.add_argument("--baseline-roots", nargs="+", required=True)
                p.add_argument("--challenger-roots", nargs="+", required=True)
            if name == "promote":
                p.add_argument("--approver", required=True)


def add_parser(sub: Any) -> None:
    populate(sub.add_parser("os", help="closed-loop research frontier, approved SOP execution and replay policy lab"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sisyfus os")
    populate(parser)
    try:
        return dispatch(parser.parse_args(argv))
    except (ValueError, RuntimeError, OSError, KeyError, ImportError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
