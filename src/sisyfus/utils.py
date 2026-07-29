from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_id(prefix: str = "") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(f"{stamp}-{time.time_ns()}-{os.getpid()}".encode()).hexdigest()[:8]
    return f"{prefix}{stamp}-{digest}"


def slugify(value: str, *, default: str = "item") -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = value.strip("-._")
    return value or default


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, sort_keys=True, default=json_default) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL in {path}:{line_no}: {exc}") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"Invalid JSONL in {path}:{line_no}: expected object")
        items.append(obj)
    return items


def truncate_middle(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    keep = max_chars // 2
    return text[:keep] + "\n...[truncated]...\n" + text[-keep:]


def shell_join(args: Iterable[str]) -> str:
    return " ".join(shlex.quote(str(a)) for a in args)


def run_process(
    command: str | list[str],
    *,
    cwd: Path,
    timeout: int = 600,
    env: dict[str, str] | None = None,
    shell: bool | None = None,
) -> dict[str, Any]:
    start = time.monotonic()
    if shell is None:
        shell = isinstance(command, str)
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            shell=shell,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        elapsed = time.monotonic() - start
        return {
            "command": command if isinstance(command, str) else shell_join(command),
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "elapsed_seconds": round(elapsed, 3),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - start
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", errors="replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", errors="replace")
        return {
            "command": command if isinstance(command, str) else shell_join(command),
            "exit_code": 124,
            "stdout": stdout,
            "stderr": stderr + f"\n[TIMEOUT after {timeout}s]",
            "elapsed_seconds": round(elapsed, 3),
            "timed_out": True,
        }


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)
