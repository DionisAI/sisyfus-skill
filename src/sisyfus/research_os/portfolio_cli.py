"""Opt-in portfolio commands. No live model calls or automatic approvals."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..research_v2.workspace import atomic_write_json
from .portfolio import Portfolio, SCHEMA


def demo(root: Path) -> dict:
    """Real local execution, artificial dependencies: tests coordination, not alpha."""
    from .controller import configure
    from .demo import create_demo
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    members = []
    for name, family in [('reference', 'square'), ('dependent', 'absolute'), ('independent', 'cube')]:
        e = create_demo(root / name, family)
        # One passing measurement in each workspace; keep the original evaluator.
        for eid in ('e0', 'e2'):
            e.prune_experiment(eid, reason='coordination fixture retains one measurement')
        configure(e)
        members.append({'id': name, 'root': str(e.workspace.root), 'weight': 1})
    members[1].update(weight=100, requires=[{'project': 'reference', 'claim': 'c1'}])
    members[2]['weight'] = .01
    spec = {'schema': SCHEMA, 'id': 'portfolio-demo', 'family': 'coordination-fixture',
            'projects': members, 'budget': {'max_attempts': 3, 'max_cost_units': 3}}
    atomic_write_json(root / 'portfolio-spec.json', spec)
    p = Portfolio.create(root / 'registry', spec, actor='demo-operator')
    before = p.status()
    first = p.run(max_steps=1, allow_local_commands=True)
    restarted = Portfolio(root / 'registry')
    final = restarted.run(max_steps=10, allow_local_commands=True)
    history = restarted.export()
    atomic_write_json(root / 'history.json', history)
    summary = {'scope': 'coordination fixture using real bounded arithmetic subprocesses; not a model effectiveness result',
               'initial_ready_projects': sorted({c['project'] for c in before['choices']}),
               'first_dispatch': first['outcomes'][0]['project'],
               'order_after_restart': [o['project'] for o in final['outcomes']],
               'verdicts': [o['verdict'] for o in final['outcomes']],
               'budget': final['budget'], 'unresolved': final['unresolved'],
               'replay_nodes': len(history['nodes']),
               'member_replay_valid': all(e.verify_replay()['deterministic'] for e in restarted.engines.values()),
               'real_llm_executed': False, 'live_jev_executed': False,
               'beats_gpt6_astra': None, 'automatic_policy_activation': False}
    atomic_write_json(root / 'summary.json', summary)
    return summary


def dispatch(args: argparse.Namespace) -> int:
    command, root = args.portfolio_command, Path(args.directory)
    if command == 'demo':
        result = demo(root)
    elif command == 'init':
        p = Portfolio.create(root, json.loads(Path(args.spec).read_text()), actor=args.actor)
        result = p.status()
    else:
        p = Portfolio(root)
        if command == 'run':
            result = p.run(max_steps=args.max_steps, max_seconds=args.max_seconds,
                           allow_local_commands=args.allow_local_commands)
        elif command == 'reconcile':
            result = p.reconcile()
        elif command == 'refresh':
            result = p.refresh_binding(args.project, actor=args.actor)
        elif command == 'cancel-unstarted':
            result = p.cancel_unstarted(args.operation, actor=args.actor)
        elif command == 'export':
            result = p.export()
            atomic_write_json(Path(args.output), result)
        else:
            result = p.status()
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


def populate(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest='portfolio_command', required=True)
    for name in ('init', 'status', 'run', 'reconcile', 'refresh', 'cancel-unstarted', 'export', 'demo'):
        p = sub.add_parser(name)
        p.add_argument('--directory', required=True)
        p.set_defaults(func=dispatch)
        if name == 'init':
            p.add_argument('--spec', required=True)
        if name in {'init', 'refresh', 'cancel-unstarted'}:
            p.add_argument('--actor', required=True)
        if name == 'run':
            p.add_argument('--max-steps', type=int, default=10)
            p.add_argument('--max-seconds', type=float, default=300)
            p.add_argument('--allow-local-commands', action='store_true')
        elif name == 'refresh':
            p.add_argument('--project', required=True)
        elif name == 'cancel-unstarted':
            p.add_argument('--operation', required=True)
        elif name == 'export':
            p.add_argument('--output', required=True)
