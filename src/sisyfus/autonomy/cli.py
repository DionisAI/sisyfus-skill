from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from .adapters import CommandPlanner, JsonInboxSensor
from .discovery import DiscoveryPolicy, OpportunityDiscovery
from .models import OpportunitySignal
from .policy import AutonomyError, AutonomyPolicy, CapabilityRegistry
from .runtime import AutonomousRuntime, register_safe_builtins
from .store import AutonomyStore
from .supervisor import AutonomousSupervisor, SupervisorConfig


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=str,
        allow_nan=False,
    )


def _root(value: str | None) -> Path:
    return Path(value or os.getcwd()).expanduser().resolve()


def _db_path(root: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else root / ".sisyfus" / "autonomy.sqlite3"


def _load_json_argument(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    raw = Path(value[1:]).expanduser().read_text(encoding="utf-8") if value.startswith("@") else value
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ValueError("JSON argument must decode to an object")
    return decoded


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sisyfus-autonomy",
        description="Verifier-gated autonomous continuation runtime.",
    )
    parser.add_argument("--root", help="Project root. Defaults to current directory.")
    parser.add_argument("--db", help="SQLite path. Defaults to <root>/.sisyfus/autonomy.sqlite3.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize the canonical SQLite-WAL database.")
    sub.add_parser(
        "migrate-legacy",
        help="Back up an unreleased legacy database and create a clean v2 database.",
    )

    submit = sub.add_parser("submit", help="Submit and optionally admit one opportunity.")
    submit.add_argument("--source", required=True)
    submit.add_argument("--kind", default="research_need")
    submit.add_argument("--title", required=True)
    submit.add_argument("--objective", required=True)
    submit.add_argument("--payload-json", default="{}")
    submit.add_argument("--context-json", default="{}")
    submit.add_argument("--priority", type=float, default=0.0)
    submit.add_argument("--confidence", type=float, default=0.5)
    submit.add_argument("--dedupe-key")
    submit.add_argument("--max-attempts", type=int, default=8)
    submit.add_argument("--no-admit", action="store_true")

    status = sub.add_parser("status", help="Show durable state and health.")
    status.add_argument("--continuation-state")
    status.add_argument("--opportunity-status")
    status.add_argument("--experience-status")

    recover = sub.add_parser("recover", help="Recover expired worker leases.")
    recover.add_argument("--now")

    sub.add_parser("verify-chain", help="Verify the autonomy event hash chain.")

    run = sub.add_parser("run", help="Run one or many supervisor cycles.")
    run.add_argument("--planner-command", required=True)
    run.add_argument("--planner-timeout", type=float, default=300.0)
    run.add_argument("--planner-max-response-bytes", type=int, default=1_000_000)
    run.add_argument("--worker-id", default=f"worker-{os.getpid()}")
    run.add_argument("--lease-seconds", type=float, default=60.0)
    run.add_argument("--idle-sleep", type=float, default=1.0)
    run.add_argument("--error-sleep", type=float, default=5.0)
    run.add_argument("--once", action="store_true")
    run.add_argument("--max-cycles", type=int)
    run.add_argument("--heartbeat")
    run.add_argument("--inbox", action="append", default=[])
    run.add_argument("--quarantine-dir")
    run.add_argument("--discovery-every-cycles", type=int, default=1)
    run.add_argument("--min-priority", type=float, default=0.0)
    run.add_argument("--default-max-attempts", type=int, default=8)
    run.add_argument("--max-unattended-risk", type=int, default=1, choices=range(0, 5))
    run.add_argument("--allow-capability", action="append", default=[])
    run.add_argument("--deny-capability", action="append", default=[])
    run.add_argument(
        "--allow-unsandboxed-planner",
        action="store_true",
        help="Required for continuous host-process planner execution.",
    )
    return parser


def _install_signal_handlers(stop: threading.Event) -> None:
    def handler(_signum: int, _frame: Any) -> None:
        stop.set()

    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, handler)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = _root(args.root)
    root.mkdir(parents=True, exist_ok=True)
    database = _db_path(root, args.db)
    try:
        if args.command == "migrate-legacy":
            backup = AutonomyStore.migrate_legacy(database)
            store = AutonomyStore(database)
            print(
                _json(
                    {
                        "status": "MIGRATED",
                        "database": str(database),
                        "legacy_backup": str(backup),
                        "event_chain": store.verify_event_chain(),
                    }
                )
            )
            return 0

        store = AutonomyStore(database)
        if args.command == "init":
            print(
                _json(
                    {
                        "status": "INITIALIZED",
                        "root": str(root),
                        "database": str(store.path),
                        "schema_version": store.SCHEMA_VERSION,
                        "event_chain": store.verify_event_chain(),
                    }
                )
            )
            return 0

        if args.command == "submit":
            signal_item = OpportunitySignal(
                source=args.source,
                kind=args.kind,
                title=args.title,
                objective=args.objective,
                payload=_load_json_argument(args.payload_json),
                priority=args.priority,
                confidence=args.confidence,
                dedupe_key=args.dedupe_key,
                max_attempts=args.max_attempts,
                context=_load_json_argument(args.context_json),
            )
            opportunity, created = store.submit_opportunity(signal_item)
            continuation = None
            admitted = False
            if not args.no_admit:
                continuation, admitted = store.admit_opportunity(
                    opportunity["id"],
                    max_attempts=args.max_attempts,
                    context=signal_item.context,
                )
            print(
                _json(
                    {
                        "status": "CREATED" if created else "DEDUPED",
                        "opportunity": opportunity,
                        "continuation": continuation,
                        "admitted": admitted,
                    }
                )
            )
            return 0

        if args.command == "status":
            heartbeat_path = root / ".sisyfus" / "autonomy-heartbeat.json"
            heartbeat = None
            if heartbeat_path.exists():
                try:
                    heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    heartbeat = {"status": "UNREADABLE", "path": str(heartbeat_path)}
            print(
                _json(
                    {
                        "database": str(store.path),
                        "schema_version": store.SCHEMA_VERSION,
                        "opportunities": store.list_opportunities(status=args.opportunity_status),
                        "continuations": store.list_continuations(state=args.continuation_state),
                        "experiences": store.list_experiences(status=args.experience_status),
                        "event_chain": store.verify_event_chain(),
                        "heartbeat": heartbeat,
                    }
                )
            )
            return 0

        if args.command == "recover":
            recovered = store.recover_expired_leases(now=args.now)
            print(
                _json(
                    {
                        "status": "RECOVERED",
                        "count": len(recovered),
                        "continuation_ids": recovered,
                    }
                )
            )
            return 0

        if args.command == "verify-chain":
            print(_json(store.verify_event_chain()))
            return 0

        if args.command == "run":
            if not args.once and not args.allow_unsandboxed_planner:
                raise ValueError(
                    "CommandPlanner is not OS-sandboxed; pass --allow-unsandboxed-planner "
                    "only after placing the service in an external sandbox"
                )
            registry = CapabilityRegistry()
            register_safe_builtins(registry, workspace=root)
            policy = AutonomyPolicy(
                max_unattended_risk=args.max_unattended_risk,
                allowed_capabilities=(
                    frozenset(args.allow_capability) if args.allow_capability else None
                ),
                denied_capabilities=frozenset(args.deny_capability),
            )
            runtime = AutonomousRuntime(store, registry, workspace=root, policy=policy)
            planner = CommandPlanner(
                args.planner_command,
                workspace=root,
                timeout_seconds=args.planner_timeout,
                max_response_bytes=args.planner_max_response_bytes,
            )
            sensors = [
                JsonInboxSensor(
                    inbox,
                    name=f"json-inbox-{index + 1}",
                    quarantine_dir=args.quarantine_dir,
                )
                for index, inbox in enumerate(args.inbox)
            ]
            discovery = (
                OpportunityDiscovery(
                    store,
                    policy=DiscoveryPolicy(
                        min_priority=args.min_priority,
                        default_max_attempts=args.default_max_attempts,
                    ),
                )
                if sensors
                else None
            )
            supervisor = AutonomousSupervisor(
                runtime,
                planner=planner,
                config=SupervisorConfig(
                    worker_id=args.worker_id,
                    lease_seconds=args.lease_seconds,
                    idle_sleep_seconds=args.idle_sleep,
                    error_sleep_seconds=args.error_sleep,
                    discovery_every_cycles=args.discovery_every_cycles,
                    heartbeat_path=(
                        args.heartbeat
                        or str(root / ".sisyfus" / "autonomy-heartbeat.json")
                    ),
                ),
                discovery=discovery,
                sensors=sensors,
            )
            if args.once:
                print(_json(supervisor.cycle()))
                return 0
            stop = threading.Event()
            _install_signal_handlers(stop)
            stats = supervisor.run_forever(stop_event=stop, max_cycles=args.max_cycles)
            print(_json({"status": "STOPPED", "stats": asdict(stats)}))
            return 0

        parser.error(f"unhandled command: {args.command}")
        return 2
    except (AutonomyError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(
            _json({"status": "ERROR", "type": type(exc).__name__, "error": str(exc)}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
