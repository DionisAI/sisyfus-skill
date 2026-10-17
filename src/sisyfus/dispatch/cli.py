"""`sisyfus dispatch`: configure and serve the private phone dispatch site."""
from __future__ import annotations

import argparse
import getpass
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .auth import AuthError, SessionStore, write_password
from .config import (DEFAULT_PORT, ConfigError, DispatchConfig, ensure_home, load_config, resolve_home,
                     save_config, validate_project)

_TAILSCALE_APP = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)


def tailscale_identity() -> tuple[str, str]:
    """(IPv4, MagicDNS name) of this machine on the tailnet."""
    binary = shutil.which("tailscale") or (_TAILSCALE_APP if Path(_TAILSCALE_APP).exists() else None)
    if not binary:
        raise ConfigError("Tailscale is not installed")
    try:
        raw = subprocess.run([binary, "status", "--json"], capture_output=True, text=True, timeout=10, check=True).stdout
        status = json.loads(raw)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ConfigError(f"could not read Tailscale status: {exc}") from exc
    me = status.get("Self") or {}
    ipv4 = next((ip for ip in me.get("TailscaleIPs") or [] if ":" not in ip), None)
    if not ipv4 or status.get("BackendState") not in (None, "Running"):
        raise ConfigError("Tailscale is not connected on this Mac")
    return ipv4, str(me.get("DNSName") or "").rstrip(".")


def cmd_init(args: argparse.Namespace) -> int:
    home = resolve_home(args.home)
    if (home / "config.json").exists():
        emit({"home": str(home), "created": False})
        return 0
    ensure_home(home)
    save_config(DispatchConfig(home=home))
    emit({"home": str(home), "created": True,
          "next": ["sisyfus dispatch password", "sisyfus dispatch project add NAME /path/to/project",
                   "sisyfus dispatch serve --tailscale"]})
    return 0


def cmd_password(args: argparse.Namespace) -> int:
    config = load_config(args.home)
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("新的调度密码（至少 12 位）: ")
        if password != getpass.getpass("再输入一次: "):
            print("两次输入不一致", file=sys.stderr)
            return 2
    write_password(config.password_path, password)
    SessionStore(config.sessions_path).revoke_all()
    emit({"password_set": True, "sessions_revoked": True})
    return 0


def cmd_project(args: argparse.Namespace) -> int:
    config = load_config(args.home)
    if args.project_command == "add":
        config.projects[args.name] = str(validate_project(args.name, Path(args.path)))
        save_config(config)
    elif args.project_command == "remove":
        config.projects.pop(args.name, None)
        save_config(config)
    emit({"projects": config.projects})
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    config = load_config(args.home)
    if args.model is not None:
        config.model = args.model or None
    if args.max_budget_usd is not None:
        config.max_budget_usd = max(0.5, float(args.max_budget_usd))
    if args.max_concurrent is not None:
        config.max_concurrent = max(1, int(args.max_concurrent))
    if args.allow_web is not None:
        config.allow_web = args.allow_web
    if args.agent_command:
        config.agent_command = list(args.agent_command)
    save_config(config)
    emit(config.to_json())
    return 0


def cmd_logout_all(args: argparse.Namespace) -> int:
    config = load_config(args.home)
    SessionStore(config.sessions_path).revoke_all()
    emit({"sessions_revoked": True})
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import make_server

    config = load_config(args.home)
    if not config.password_path.exists():
        raise ConfigError("set a password first: sisyfus dispatch password")
    host, allowed, urls = args.host, set(args.allow_host or []), []
    if args.tailscale:
        host, dns = tailscale_identity()
        allowed |= {f"{host}:{args.port}"} | ({f"{dns}:{args.port}", dns} if dns else set())
        urls.append(f"http://{dns or host}:{args.port}/")
    server = make_server(config, host=host, port=args.port, allowed_hosts=allowed)
    port = server.server_address[1]
    urls.append(f"http://{host}:{port}/")
    emit({"listening": urls, "projects": sorted(config.projects), "agent": config.agent_command[0],
          "note": "Private by default: only this Mac or your tailnet devices can reach it."})
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sisyfus dispatch",
                                description="Dispatch Sisyfus research from your phone and read status.")
    p.add_argument("--home", help="dispatch state directory (default ~/.sisyfus/dispatch)")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create the dispatch configuration").set_defaults(func=cmd_init)
    pw = sub.add_parser("password", help="set the login password (revokes all phone sessions)")
    pw.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    pw.set_defaults(func=cmd_password)
    project = sub.add_parser("project", help="manage the allowlisted project directories")
    psub = project.add_subparsers(dest="project_command", required=True)
    add = psub.add_parser("add")
    add.add_argument("name")
    add.add_argument("path")
    remove = psub.add_parser("remove")
    remove.add_argument("name")
    psub.add_parser("list")
    project.set_defaults(func=cmd_project)
    cfg = sub.add_parser("config", help="agent model, budget and concurrency")
    cfg.add_argument("--model")
    cfg.add_argument("--max-budget-usd", type=float)
    cfg.add_argument("--max-concurrent", type=int)
    cfg.add_argument("--allow-web", dest="allow_web", action="store_true", default=None)
    cfg.add_argument("--no-web", dest="allow_web", action="store_false")
    cfg.add_argument("--agent-command", nargs="+", help="agent executable and fixed leading arguments")
    cfg.set_defaults(func=cmd_config)
    sub.add_parser("logout-all", help="revoke every phone session").set_defaults(func=cmd_logout_all)
    serve = sub.add_parser("serve", help="run the dispatch site")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--tailscale", action="store_true", help="listen on this Mac's tailnet address")
    serve.add_argument("--allow-host", action="append", help="extra accepted Host, e.g. for `tailscale serve`")
    serve.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (ConfigError, AuthError) as exc:
        print(f"sisyfus dispatch: {exc}", file=sys.stderr)
        return 2
