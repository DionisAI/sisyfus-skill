from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import webbrowser
from pathlib import Path

from .claude_code import ClaudeCodeDriver
from .codex import CodexDriver
from .console import Console
from .mission import Mission, load_spec


def demo_spec(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=False)
    project = directory / "project"
    project.mkdir()
    (project / "README.md").write_text("Offline protocol fixture; not an LLM benchmark.\n")
    evaluator = directory / "check.py"
    evaluator.write_text("import json,pathlib,sys\np=pathlib.Path(sys.argv[1])/'answer.txt'\nprint(json.dumps({'answer':int(p.read_text()) if p.exists() else -1}))\n")
    fixture = str(Path(__file__).with_name("demo_agent.py"))
    spec = {"objective": "Offline fixture: plan → implement → FAIL → repair → PASS → dependent review",
            "source": str(project), "planner": "claude", "max_calls": 6, "parallelism": 2, "timeout": 10,
            "validation_kind": "OFFLINE_PROTOCOL_FIXTURE_NOT_REAL_LLM",
            "drivers": {name: {"model": "protocol-fixture-only", "command": [sys.executable, fixture, name, behavior]}
                        for name, behavior in (("codex", "retry"), ("claude", "success"))},
            "checks": {"answer": {"argv": [sys.executable, "-I", "-S", str(evaluator), "{candidate}"],
                "code_hashes": {str(evaluator): hashlib.sha256(evaluator.read_bytes()).hexdigest()},
                "contract": {"kind": "rules", "pass_if": {"all": [{"path": "answer", "op": "eq", "value": 42}]},
                             "fail_if": {"all": [{"path": "answer", "op": "ne", "value": 42}]}}}}}
    path = directory / "mission.json"
    path.write_text(json.dumps(spec, indent=2))
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sisyfus workers")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Probe native binaries without starting model calls")
    for name in ("run", "up"):
        p = sub.add_parser(name)
        p.add_argument("spec", type=Path)
        p.add_argument("--directory", type=Path, required=True)
        p.add_argument("--allow-local-workers", action="store_true")
        p.add_argument("--max-cycles", type=int, default=10000)
        if name == "up":
            p.add_argument("--port", type=int, default=8780)
            p.add_argument("--open", action="store_true")
    for name in ("status", "export", "serve"):
        p = sub.add_parser(name)
        p.add_argument("--directory", type=Path, required=True)
        if name == "export": p.add_argument("--output", type=Path, required=True)
        if name == "serve":
            p.add_argument("--port", type=int, default=8780)
            p.add_argument("--open", action="store_true")
    p = sub.add_parser("demo")
    p.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = {d.name: d.probe() for d in (CodexDriver(), ClaudeCodeDriver())}
            print(json.dumps(result, indent=2))
            return 0 if all(r["available"] for r in result.values()) else 2
        if args.command == "demo":
            root = args.directory.resolve()
            spec = demo_spec(root)
            m = Mission(root / "control", load_spec(spec))
            result = m.run()
        elif args.command in {"run", "up"}:
            if not args.allow_local_workers:
                raise PermissionError("requires --allow-local-workers; same-user snapshots are not an OS sandbox")
            if not 1 <= args.max_cycles <= 1_000_000:
                raise ValueError("max-cycles must be in [1,1000000]")
            m = Mission(args.directory, load_spec(args.spec))
            if args.command == "run":
                result = m.run(max_cycles=args.max_cycles)
            else:
                server = Console(m, port=args.port)
                def run() -> None:
                    try:
                        print(json.dumps(m.run(max_cycles=args.max_cycles), ensure_ascii=False), flush=True)
                    except Exception as exc:
                        print(json.dumps({"error": str(exc)}), file=sys.stderr, flush=True)
                thread = threading.Thread(target=run, daemon=False)
                thread.start()
                print(json.dumps({"console": server.url, "warning": "keep this token URL private"}), flush=True)
                if args.open: webbrowser.open(server.url)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    m.stop.set()
                finally:
                    server.server_close()
                    thread.join()
                return 0
        else:
            if not (args.directory / "autonomy.sqlite3").is_file():
                raise FileNotFoundError("no mission database in the selected directory")
            m = Mission(args.directory)
            if args.command == "serve":
                server = Console(m, port=args.port)
                print(json.dumps({"console": server.url, "warning": "keep this token URL private"}), flush=True)
                if args.open: webbrowser.open(server.url)
                try: server.serve_forever()
                except KeyboardInterrupt: pass
                finally: server.server_close()
                return 0
            result = m.snapshot()
            if args.command == "export":
                events, cursor = [], 0
                while batch := m.journal.events(cursor, 1000):
                    events.extend(batch)
                    cursor = batch[-1]["seq"]
                result = {"snapshot": result, "events": events, "chain": m.store.verify_event_chain(),
                          "automatic_policy_activation": False, "performance_gain_established": False}
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if args.command in {"status", "export"} or result.get("all_verified") else 2
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(json.dumps({"error": {"type": type(exc).__name__, "message": str(exc)}}), file=sys.stderr)
        return 1
