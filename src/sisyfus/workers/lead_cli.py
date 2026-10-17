"""Tech Lead CLI. Routing from `sisyfus techlead` belongs to entrypoint.py.

Standalone: python -m sisyfus.workers.lead_cli <command> ...
No command activates the installed release or automatically resumes a mission.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

from .lead_console import DEFAULT_PORT, LeadConsole, MissionHub, _GatewayEntry, safe_error
from .protocol import redact


def _gateway_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("node gateway port must be an integer in [0,65535]") from None
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("node gateway port must be an integer in [0,65535]")
    return port


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sisyfus techlead")
    sub = p.add_subparsers(dest="command", required=True)
    share = sub.add_parser("share", add_help=False, help="Share an existing Console without worker/control permissions")
    share.add_argument("--password-file", type=Path, default=argparse.SUPPRESS,
                       help="Use a private password verifier file for this share")
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
            command.add_argument("--node-gateway-port", type=_gateway_port, default=None,
                                 help="Explicitly host the separate loopback node gateway")
    return p


def emit(value: Any, *, error: bool = False) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
          file=sys.stderr if error else sys.stdout, flush=True)


def _entry_observed(hub: MissionHub, gateway: Any, thread: Any, *,
                    start_called: bool = False, finished: Any = None) -> bool:
    observation = getattr(hub, "_gateway_observation", None)
    if (isinstance(observation, _GatewayEntry) and observation.gateway is gateway
            and observation.thread is thread and observation.entered):
        return True
    if thread is None or (not start_called and not thread.is_alive()):
        return False
    # start() may have spawned this exact Thread before raising/interruption.
    # Observe only the public direct loop hook; never attach or publish readiness.
    entry = _GatewayEntry(gateway, thread, hub._gateway_generation)
    gateway.service_actions = entry.hook
    try:
        deadline = time.monotonic() + 2.0
        while not entry.entered:
            if entry.failed or entry.mismatch:
                return False
            if ((finished is not None and finished.is_set())
                    or (thread.ident is not None and not thread.is_alive())):
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if start_called and thread.ident is None and not thread.is_alive():
                    raise TimeoutError("owned gateway start outcome unresolved after 2 seconds")
                raise RuntimeError("owned gateway loop entry was not observed for cleanup")
            entry.changed.wait(min(remaining, .02))
        return True
    finally:
        entry.restore()


def _stage_error(exc: BaseException, stage: str | None) -> dict[str, str]:
    error = safe_error(exc)
    if stage is None:
        return error
    # Resource exceptions may contain private filenames, not just Bearer text.
    # Preserve ordinary, clean CLI diagnostics. A filename-bearing exception,
    # any relative/absolute/UNC path or credential redaction requires the fixed
    # stage message instead; never echo the private residue of partial redaction.
    text = str(exc)
    if (getattr(exc, "filename", None) is not None
            or getattr(exc, "filename2", None) is not None
            or redact(text) != text
            or re.search(r"[/\\]", text)):
        return {"type": type(exc).__name__, "message": "host lifecycle failure during " + stage}
    return error


def _shutdown_owned(gateway: Any) -> tuple[bool, dict[str, str] | None]:
    """Observe one owned public shutdown for two seconds; no private flags."""
    finished = threading.Event()
    failures: list[dict[str, str]] = []
    interrupted = False

    def shutdown() -> None:
        try:
            gateway.shutdown()
        except BaseException as exc:
            try:
                failure = _stage_error(exc, "gateway.shutdown")
            except BaseException:
                failure = {"type": type(exc).__name__,
                           "message": "host lifecycle failure during gateway.shutdown"}
            failures.append(failure)
        finally:
            finished.set()

    helper = threading.Thread(target=shutdown, name="techlead-node-gateway-shutdown", daemon=True)
    deadline = time.monotonic() + 2.0
    try:
        helper.start()
    except KeyboardInterrupt:
        # start() can already have spawned the helper. Observe this same
        # attempt, rather than starting another shutdown after the signal.
        interrupted = True
    while True:
        try:
            complete = finished.wait(max(0, deadline - time.monotonic()))
            break
        except KeyboardInterrupt:
            interrupted = True
    if not complete:
        raise TimeoutError("owned gateway shutdown timed out; completion not observed")
    return interrupted, failures[0] if failures else None


def _main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    hub = MissionHub(args.directory, single=args.command != "hub")
    server = None
    gateway = thread = None
    entered = False
    start_called = False
    loop_finished = threading.Event()
    loop_error: dict[str, Any] = {}
    stage = None
    errors: list[tuple[dict[str, str], str | None]] = []
    result = 0
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
        elif args.command == "status":
            emit(hub.snapshot("mission"))
        elif args.command == "run":
            hub.start("mission", allow_local_workers=True, max_cycles=args.max_cycles)
            result = hub.wait("mission")
            emit({"result": result, **hub.snapshot("mission")})
            result = 0 if isinstance(result, dict) and result.get("all_verified") is True else 2
        else:
            if args.command == "serve" and not hub.inventory()["missions"]:
                raise ValueError("serve requires an existing approved Tech Lead mission; use new first")
            # Both listeners, actual loop entry and host attachment precede Start.
            stage = "console.bind"
            server = LeadConsole(hub, port=args.port)
            if args.node_gateway_port is not None:
                stage = "gateway.import"
                from .node_gateway import NodeGateway
                stage = "gateway.bind"
                gateway = NodeGateway(hub, port=args.node_gateway_port)
                stage = "gateway.thread.construct"
                def serve_owned() -> None:
                    # Only this CLI-owned loop is caught, never another Thread
                    # or global excepthook. Late start failures stay observable.
                    try:
                        gateway.serve_forever()
                    except BaseException as exc:
                        record = {"error": {"type": type(exc).__name__,
                                  "message": "host lifecycle failure during gateway.serve"},
                                  "operation": "gateway.serve"}
                        loop_error["record"] = record
                        try:
                            emit(record, error=True)
                            loop_error["published"] = True
                        except BaseException as publication:
                            loop_error["publication"] = _stage_error(publication, "gateway.serve.publish")
                    finally:
                        loop_finished.set()

                thread = threading.Thread(target=serve_owned, name="techlead-node-gateway", daemon=True)
                stage = "gateway.thread.start"
                start_called = True
                thread.start()
                stage = "gateway.attach"
                hub.attach_node_gateway(gateway, serve_thread=thread)
                # A successful public attachment is a verified host entry receipt.
                # Failed publication is handled by the independent observation.
                entered = True
            stage = None
            if args.command == "up":
                hub.start("mission", allow_local_workers=True, max_cycles=args.max_cycles)
            stage = "console.publish"
            output = {"console": server.url, "directory": str(hub.directory),
                      "auto_start": False, "started_by_operator": args.command == "up",
                      "warning": "Keep the token URL private. UI Start acknowledges local-worker execution."}
            if gateway is not None:
                output["node_gateway"] = hub.node_gateway_state()["gateway"]
            emit(output)
            if args.open:
                stage = "browser.open"
                if not webbrowser.open(server.url):
                    emit({"warning": "Browser did not report opening; use the printed URL."}, error=True)
            stage = "console.serve"
            server.serve_forever()
    except KeyboardInterrupt:
        result = 130
        try:
            emit({"status": "shutdown requested; waiting for cooperative controller stop", "terminal": False})
        except BaseException as exc:
            errors.append((_stage_error(exc, "console.interrupt.publish"), "console.interrupt.publish"))
    except Exception as exc:
        errors.append((_stage_error(exc, stage), stage))
    finally:
        def cleanup(operation: str, action: Any, *, retry_interrupt: bool = True) -> Any:
            nonlocal result
            while True:
                try:
                    return action()
                except KeyboardInterrupt:
                    result = 130
                    if not retry_interrupt:
                        errors.append(({"type": "KeyboardInterrupt",
                                        "message": "host lifecycle failure during " + operation}, operation))
                        return None
                except BaseException as exc:
                    errors.append((_stage_error(exc, operation), operation))
                    return None

        # Exhaust all owned stages even when another stage fails. No cleanup
        # wait holds a lifecycle/session lock. The gateway keeps serving drain.
        cleanup("hub.close", hub.close)
        if gateway is not None:
            entered = entered or cleanup("gateway.entry.observe", lambda: _entry_observed(
                hub, gateway, thread, start_called=start_called, finished=loop_finished))
            cleanup("hub.detach", hub.detach_node_gateway)
            if entered:
                shutdown = cleanup("gateway.shutdown", lambda: _shutdown_owned(gateway), retry_interrupt=False)
                if shutdown is not None:
                    interrupted, failure = shutdown
                    if interrupted:
                        result = 130
                    if failure is not None:
                        errors.append((failure, "gateway.shutdown"))
                cleanup("gateway.thread.join", lambda: thread.join(timeout=2))
                if thread.is_alive():
                    errors.append(({"type": "RuntimeError", "message": "owned gateway Thread did not finish"},
                                   "gateway.thread.join"))
            cleanup("gateway.close", gateway.server_close)
        if server is not None:
            cleanup("console.close", server.server_close)
    if loop_error.get("record") and not loop_error.get("published"):
        emit(loop_error["record"], error=True)
    if loop_error.get("publication"):
        emit({"error": loop_error["publication"], "operation": "gateway.serve.publish"}, error=True)
    for error, operation in errors:
        record = {"error": error}
        if operation is not None:
            record["operation"] = operation
        emit(record, error=True)
    return 1 if errors or loop_error else result


def main(argv: list[str] | None = None) -> int:
    # Cleanup failures propagate here rather than overriding returns inside a
    # finally block or leaking an unredacted traceback to a CLI operator.
    try:
        arguments = sys.argv[1:] if argv is None else argv
        if arguments and arguments[0] == "share":
            from .share_cli import main as share_main
            return share_main(arguments[1:])
        return _main(argv)
    except Exception as exc:
        emit({"error": safe_error(exc), "operation": "dispatch_or_cooperative_shutdown"}, error=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
