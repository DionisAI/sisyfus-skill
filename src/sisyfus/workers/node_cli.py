"""Standalone NodeAgent transport CLI; receipts are not task acceptance.

Only operator-supplied paths enter the public Agent constructor. Parsing/help
does not import the Agent, touch files, or probe a provider. The Agent owns its
durable identities, permissions and replay; this module has no cleanup/close
or private-state interface.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time


_REQUEST_ID = re.compile(r"agent_[0-9a-f]{32}\Z")
_EXIT_CODES = {"NO_WORK": 0, "RECEIPTED": 0, "UNKNOWN": 2,
               "RECONCILIATION_CANDIDATE": 2}
# Exact trusted built-in types only: custom class names/messages may be secret.
_ERROR_NAMES = {kind: kind.__name__ for kind in (
    Exception, ValueError, TypeError, RuntimeError, AssertionError, OSError,
    FileNotFoundError, FileExistsError, PermissionError, IsADirectoryError,
    NotADirectoryError, TimeoutError, ConnectionError, ConnectionRefusedError,
    ConnectionResetError, ConnectionAbortedError, BrokenPipeError,
    ImportError, ModuleNotFoundError, AttributeError, KeyError, IndexError,
    OverflowError, MemoryError, UnicodeError, UnicodeEncodeError,
    UnicodeDecodeError, UnicodeTranslateError, SystemExit, GeneratorExit,
)}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        """Discard argparse prose/argv; main emits the fixed parse diagnostic."""
        raise ValueError("invalid CLI arguments")


class _Once(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        """Single-valued flags never silently take a later duplicate value."""
        if hasattr(namespace, self.dest):
            raise ValueError("duplicate CLI option")
        setattr(namespace, self.dest, values)


def _idle_count(value):
    if re.fullmatch(r"[0-9]+", value) is None:
        raise ValueError("invalid idle poll count")
    count = int(value)
    if not 1 <= count <= 100:
        raise ValueError("idle poll count outside bounds")
    return count


def _poll_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or not 0.01 <= seconds <= 30:
        raise ValueError("poll interval outside bounds")
    return seconds


def _parse(argv):
    """Validate all flags locally; None is help, not permission to construct."""
    parser = _Parser(
        prog="python -m sisyfus.workers.node_cli",
        usage="%(prog)s --credential-file PATH --state-directory PATH "
              "[--idle-polls N] [--poll-seconds S]",
        description="NodeAgent transport only; default is exactly one run_once.",
        allow_abbrev=False, add_help=False,
    )
    parser.add_argument("-h", "--help", action="store_true", help="show local help and exit")
    single = {"action": _Once, "default": argparse.SUPPRESS}
    parser.add_argument("--credential-file", metavar="PATH", help="required operator credential file", **single)
    parser.add_argument("--state-directory", metavar="PATH", help="required persistent Agent state directory", **single)
    parser.add_argument("--idle-polls", metavar="N", type=_idle_count,
                        help="1..100 additional NO_WORK polls; default is none", **single)
    parser.add_argument("--poll-seconds", metavar="S", type=_poll_seconds,
                        help="finite 0.01..30 seconds; default 0.2; does not enable polling", **single)
    args = parser.parse_args(argv)
    if args.help:
        parser.print_help()
        return None
    if not getattr(args, "credential_file", None) or not getattr(args, "state_directory", None):
        raise ValueError("both operator paths are required")
    args.idle_polls = getattr(args, "idle_polls", 0)
    args.poll_seconds = getattr(args, "poll_seconds", 0.2)
    return args


def _result(value):
    """Validate the public transport identity/shape, without native aliases."""
    if type(value) is not dict or set(value) != {"request_id", "status"}:
        raise ValueError("invalid public Agent result")
    request_id, status = value["request_id"], value["status"]
    if (type(request_id) is not str or _REQUEST_ID.fullmatch(request_id) is None
            or type(status) is not str or status not in _EXIT_CODES):
        raise ValueError("invalid public Agent identity or status")
    return {"request_id": request_id, "status": status}


def _failure(stage, exc):
    """A failure emits only a fixed stage and a trusted type, never prose."""
    interrupted = isinstance(exc, KeyboardInterrupt)
    print(json.dumps({"status": "INTERRUPTED" if interrupted else "ERROR",
                      "stage": stage,
                      "error_type": "KeyboardInterrupt" if interrupted else
                                    _ERROR_NAMES.get(type(exc), "Exception")}),
          file=sys.stderr, flush=True)
    return 130 if interrupted else 1


def main(argv=None, *, agent_factory=None, sleep=None) -> int:
    """Run one Agent, with finite extra calls only after a NO_WORK result.

    Factory/sleep injection is a public fixture seam, not a CLI authority flag.
    Even a persisted UNKNOWN gets one public run_once, never an idle retry.
    """
    stage = "parse"
    try:
        args = _parse(argv)
        if args is None:
            return 0
        stage = "construct"
        if agent_factory is None:
            from .node_agent import NodeAgent
            agent_factory = NodeAgent
        agent = agent_factory(args.credential_file, args.state_directory)
        wait = time.sleep if sleep is None else sleep
        remaining = args.idle_polls
        while True:
            stage = "run_once"
            value = agent.run_once()
            stage = "result"
            result = _result(value)
            if result["status"] != "NO_WORK" or remaining == 0:
                print(json.dumps(result), flush=True)
                return _EXIT_CODES[result["status"]]
            remaining -= 1
            stage = "poll"
            wait(args.poll_seconds)
    except BaseException as exc:
        return _failure(stage, exc)


if __name__ == "__main__":
    raise SystemExit(main())
