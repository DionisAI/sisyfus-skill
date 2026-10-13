"""Tech Lead CLI. Routing from `sisyfus techlead` belongs to entrypoint.py.

Standalone: python -m sisyfus.workers.lead_cli <command> ...
No command activates the installed release or automatically resumes a mission.
"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path
from typing import Any

from .lead_console import DEFAULT_PORT, LeadConsole, MissionHub, safe_error


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sisyfus techlead")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("new", "run", "up", "status", "hub", "serve"):
        command = sub.add_parser(name)
        command.add_argument("--directory", type=Path, required=True)
        if name in {"new", "run", "up"}:
            command.add_argument("spec", type=Path)
        if name in {"run", "up"}:
            command.add_argument("--allow-local-workers", action="store_true",
                                 help="Acknowledge native same-user execution, not OS isolation")
            command.add_argument("--max-cycles", type=int, default=None,
                                 help="Optional controller-cycle cap; omitted means unlimited")
        if name in {"up", "hub", "serve"}:
            command.add_argument("--port", type=int, default=DEFAULT_PORT)
            command.add_argument("--open", action="store_true")
    return p


def emit(value: Any, *, error: bool = False) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
          file=sys.stderr if error else sys.stdout, flush=True)


def _main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    hub = MissionHub(args.directory, single=args.command != "hub")
    server = None
    try:
        if args.command in {"run", "up"}:
            if not args.allow_local_workers:
                raise PermissionError("requires --allow-local-workers before binding/starting native workers")
            if args.max_cycles is not None and args.max_cycles < 1:
                raise ValueError("max-cycles must be a positive integer or omitted (Unlimited)")
        if args.command in {"new", "run", "up"}:
            created = hub.create(args.spec)
            if args.command == "new":
                emit(created)
                return 0
        elif args.command == "status":
            emit(hub.snapshot("mission"))
            return 0
        elif args.command == "serve":
            # Validate binding before listening, but do not initialize a controller.
            if not hub.inventory()["missions"]:
                raise ValueError("serve requires an existing approved Tech Lead mission; use new first")
        if args.command == "run":
            hub.start("mission", allow_local_workers=True, max_cycles=args.max_cycles)
            result = hub.wait("mission")
            emit({"result": result, **hub.snapshot("mission")})
            return 0 if isinstance(result, dict) and result.get("all_verified") is True else 2
        # Bind listener before starting workers: an occupied port is a clean failure.
        server = LeadConsole(hub, port=args.port)
        if args.command == "up":
            hub.start("mission", allow_local_workers=True, max_cycles=args.max_cycles)
        emit({"console": server.url, "directory": str(hub.directory),
              "auto_start": False, "started_by_operator": args.command == "up",
              "warning": "Keep the token URL private. UI Start acknowledges local-worker execution."})
        if args.open:
            if not webbrowser.open(server.url):
                emit({"warning": "Browser did not report opening; use the printed URL."}, error=True)
        server.serve_forever()
        return 0
    except KeyboardInterrupt:
        emit({"status": "shutdown requested; waiting for cooperative controller stop", "terminal": False})
        return 130
    except Exception as exc:
        emit({"error": safe_error(exc)}, error=True)
        return 1
    finally:
        if server is not None:
            server.server_close()
        hub.close()


def main(argv: list[str] | None = None) -> int:
    # Cleanup failures propagate here rather than overriding returns inside a
    # finally block or leaking an unredacted traceback to a CLI operator.
    try:
        return _main(argv)
    except Exception as exc:
        emit({"error": safe_error(exc), "operation": "dispatch_or_cooperative_shutdown"}, error=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
