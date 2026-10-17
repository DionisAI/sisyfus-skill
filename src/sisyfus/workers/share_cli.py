"""Foreground opt-in share CLI; parse/help have no runtime IO or child start."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from urllib.parse import urlsplit

_STATES = {"NEW", "STARTING", "LOCAL_ONLY", "HOST_ASSIGNED", "CONNECTED", "FAILED", "CLOSED"}
_TYPES = {c: c.__name__ for c in (
    Exception, RuntimeError, ValueError, TypeError, OSError, PermissionError,
    FileNotFoundError, FileExistsError, TimeoutError, KeyboardInterrupt,
)}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("parse")


class _Once(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        seen = getattr(namespace, "_seen", set())
        if self.dest in seen:
            raise ValueError("duplicate flag")
        seen.add(self.dest)
        namespace._seen = seen
        setattr(namespace, self.dest, True if self.nargs == 0 else values)


def _origin(value, *, public=False):
    if not isinstance(value, str):
        raise ValueError("origin")
    uri = urlsplit(value)
    if public:
        valid = (uri.scheme == "https" and uri.hostname is not None
                 and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.trycloudflare\.com", uri.hostname)
                 and uri.netloc == uri.hostname and not uri.path and not uri.query and not uri.fragment)
    else:
        valid = (uri.scheme == "http" and uri.hostname == "127.0.0.1"
                 and not uri.username and not uri.password and not uri.path and not uri.query and not uri.fragment
                 and uri.port is not None and 1 <= uri.port <= 65535 and value == f"http://127.0.0.1:{uri.port}")
    if not valid:
        raise ValueError("origin")
    return value


def _parse(argv):
    parser = _Parser(prog="sisyfus techlead share", allow_abbrev=False, add_help=False,
                     description="仅分享既有Console；无Start/control/worker权限。--password-file启用访问密码；省略时为兼容Bearer令牌模式。私密链接仅写access文件。")
    parser.add_argument("-h", "--help", action="store_true")
    single = {"action": _Once, "default": argparse.SUPPRESS}
    for flag in ("console-origin", "operator-token-file", "mission-id", "runtime-directory",
                 "report", "cloudflared", "startup-timeout", "password-file"):
        parser.add_argument("--" + flag, **single)
    for flag in ("allow-messages", "local-only"):
        parser.add_argument("--" + flag, nargs=0, **single)
    args = parser.parse_args(argv)
    if args.help:
        parser.print_help()
        return None
    for name in ("console_origin", "operator_token_file", "mission_id", "runtime_directory"):
        if not getattr(args, name, None):
            raise ValueError("required flags")
    _origin(args.console_origin)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", args.mission_id):
        raise ValueError("mission")
    if (not os.path.isabs(args.runtime_directory) or "\0" in args.runtime_directory
            or any(x in (".", "..") for x in args.runtime_directory.split("/"))):
        raise ValueError("absolute runtime directory")
    args.startup_timeout = float(getattr(args, "startup_timeout", 30.0))
    if not math.isfinite(args.startup_timeout) or args.startup_timeout <= 0:
        raise ValueError("finite startup timeout")
    args.local_only = getattr(args, "local_only", False)
    args.allow_messages = getattr(args, "allow_messages", False)
    args.report = getattr(args, "report", None)
    args.cloudflared = getattr(args, "cloudflared", "cloudflared")
    args.password_file = getattr(args, "password_file", None)
    if args.password_file is not None and (
            not args.password_file or not os.path.isabs(args.password_file)
            or args.password_file.startswith("//") or "\0" in args.password_file
            or any(x in (".", "..") for x in args.password_file.split("/"))):
        raise ValueError("absolute password verifier file")
    return args


def _public(value):
    """Keep only validated transport metadata; tokens/private links never pass."""
    if not isinstance(value, dict) or value.get("schema") != "sisyfus.share.runtime.v1":
        raise ValueError("metadata")
    state = value.get("state")
    if state not in _STATES:
        raise ValueError("state")
    permissions = value.get("permissions")
    if (not isinstance(permissions, dict) or type(permissions.get("messages")) is not bool
            or permissions.get("controls") is not False):
        raise ValueError("permissions")
    result = {"schema": "sisyfus.share.runtime.v1", "state": state,
              "permissions": {"messages": permissions["messages"], "controls": False}}
    for key in ("local_origin", "public_origin"):
        origin = value.get(key)
        result[key] = None if origin is None else _origin(origin, public=key == "public_origin")
    path = value.get("access_file")
    if path is not None and (not isinstance(path, str) or not os.path.isabs(path)
                             or not path.endswith("/access.json") or "#" in path or "\0" in path):
        raise ValueError("access pointer")
    result["access_file"] = path
    closed = value.get("resources_closed")
    if type(closed) is not bool:
        raise ValueError("closed")
    result["resources_closed"] = closed
    returncode = value.get("process_returncode")
    if returncode is not None and type(returncode) is not int:
        raise ValueError("child returncode")
    result["process_returncode"] = returncode
    diagnostics = value.get("diagnostics")
    if not isinstance(diagnostics, list) or len(diagnostics) > 64:
        raise ValueError("diagnostics")
    result["diagnostics"] = []
    for item in diagnostics:
        if not isinstance(item, dict):
            raise ValueError("diagnostic")
        stage = item.get("stage")
        kind = item.get("error_type")
        result["diagnostics"].append({
            "stage": stage if isinstance(stage, str) and re.fullmatch(r"[a-z][a-z_.]{0,40}", stage) else "runtime",
            "error_type": kind if kind in set(_TYPES.values()) | {"UnicodeDecodeError", "NotADirectoryError", "IsADirectoryError", "TimeoutExpired"} else "Exception",
        })
    return result


def _failure(stage, exc):
    """Fixed stage/trusted type only; no exception string or environment reads."""
    print(json.dumps({"status": "INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "ERROR",
                      "stage": stage, "error_type": _TYPES.get(type(exc), "Exception")}),
          file=sys.stderr, flush=True)


def _emit(value):
    meta = _public(value)
    print(json.dumps(meta, ensure_ascii=False), flush=True)
    return meta


def main(argv=None, *, runtime_factory=None, sleep=None):
    """Foreground lifecycle via public methods; fixtures inject only Python DI."""
    stage = "parse"
    owned = None
    result = 0
    try:
        args = _parse(argv)
        if args is None:
            return 0
        stage = "construct"
        if runtime_factory is None:
            from .share_runtime import ShareRuntime
            runtime_factory = ShareRuntime
        password_options = {} if args.password_file is None else {"password_file": args.password_file}
        owned = runtime_factory(
            args.console_origin, args.operator_token_file, args.mission_id, args.runtime_directory,
            allow_messages=args.allow_messages, report_path=args.report, local_only=args.local_only,
            cloudflared=args.cloudflared, startup_timeout=args.startup_timeout,
            **password_options,
        )
        stage = "start"
        last = _emit(owned.start())
        pause = time.sleep if sleep is None else sleep
        while last["state"] not in {"FAILED", "CLOSED"}:
            stage = "status"
            current = _public(owned.status())
            if current != last:
                last = _emit(current)
            if last["state"] in {"FAILED", "CLOSED"}:
                break
            stage = "sleep"
            pause(0.2)
        if last["state"] == "FAILED":
            result = 1
    except BaseException as exc:
        _failure(stage, exc)
        result = 130 if isinstance(exc, KeyboardInterrupt) else 1
    finally:
        if owned is not None:
            try:
                _emit(owned.close())
            except BaseException as exc:
                _failure("close", exc)
                if isinstance(exc, KeyboardInterrupt):
                    result = 130
                elif result != 130:
                    result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())

