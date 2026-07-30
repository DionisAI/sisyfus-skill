"""Self-healing live Observatory.

One daemon per project root serves the Arena page for the run most recently
worked on. Its coordinates persist in `<root>/.sisyfus/observatory.json`, its
port is derived deterministically from the root path (so the URL survives
restarts and can be bookmarked), and `ensure_observatory` — called by every
research CLI command — respawns it whenever it is found dead. Liveness is
always established by connecting to the recorded port, never by trusting the
state file alone, so a stale file left by a killed daemon heals itself.

Set SISYFUS_AUTO_SERVE=0 to disable respawning (tests, CI, one-shot runs).
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .workspace import atomic_write_json, utc_now

_PORT_BASE = 8700
_PORT_SPAN = 200


def observatory_state_path(root: Path) -> Path:
    return Path(root) / ".sisyfus" / "observatory.json"


def observatory_entry_path(root: Path) -> Path:
    return Path(root) / ".sisyfus" / "observatory.html"


def observatory_log_path(root: Path) -> Path:
    return Path(root) / ".sisyfus" / "observatory.log"


def derived_port(root: Path) -> int:
    """Stable per-project port so the live URL survives daemon restarts."""
    digest = hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).digest()
    return _PORT_BASE + int.from_bytes(digest[:2], "big") % _PORT_SPAN


def auto_serve_enabled() -> bool:
    return os.environ.get("SISYFUS_AUTO_SERVE", "1").strip().lower() not in {"0", "false", "no", "off"}


def read_live_state(root: Path) -> dict[str, Any] | None:
    path = observatory_state_path(root)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return state if isinstance(state, dict) and state.get("port") else None


def write_live_state(root: Path, *, host: str, port: int, research_id: str) -> dict[str, Any]:
    state = {
        "schema_version": "sisyfus.observatory.v1",
        "pid": os.getpid(),
        "host": host,
        "port": int(port),
        "url": f"http://{host}:{port}/index.html",
        "research_id": research_id,
        "root": str(Path(root).resolve()),
        "started_at": utc_now(),
    }
    atomic_write_json(observatory_state_path(root), state)
    return state


def clear_live_state(root: Path, *, pid: int | None = None) -> None:
    """Remove the state file, but never one that a newer daemon has claimed."""
    state = read_live_state(root)
    if pid is not None and state is not None and state.get("pid") not in (None, pid):
        return
    try:
        observatory_state_path(root).unlink(missing_ok=True)
    except OSError:
        pass


def server_alive(host: str, port: int, *, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def live_observatory_url(root: Path) -> str | None:
    """URL of the running daemon for this root, or None. Probes; never trusts the file."""
    state = read_live_state(root)
    if not state:
        return None
    host, port = str(state.get("host") or "127.0.0.1"), int(state["port"])
    if not server_alive(host, port):
        return None
    return str(state.get("url") or f"http://{host}:{port}/index.html")


def _terminate(pid: int, host: str, port: int, *, timeout: float = 2.0) -> bool:
    try:
        os.kill(int(pid), signal.SIGTERM)
    except (OSError, ValueError):
        return not server_alive(host, port)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not server_alive(host, port):
            return True
        time.sleep(0.05)
    return False


def ensure_observatory(root: Path, research_id: str, *, spawn_timeout: float = 3.0) -> str | None:
    """Guarantee a live Observatory daemon for this root; return its URL.

    Idempotent and safe on every CLI invocation: an alive daemon already
    serving `research_id` is left untouched; one serving another run is
    retargeted; a dead or missing one is respawned detached.
    """
    root = Path(root).resolve()
    state = read_live_state(root)
    if state is not None:
        host, port = str(state.get("host") or "127.0.0.1"), int(state["port"])
        if server_alive(host, port):
            if state.get("research_id") == research_id:
                return str(state.get("url") or f"http://{host}:{port}/index.html")
            if not auto_serve_enabled():
                return str(state.get("url") or f"http://{host}:{port}/index.html")
            if not _terminate(int(state.get("pid") or 0), host, port):
                # Could not free the port; a live page beats a dead one.
                return str(state.get("url") or f"http://{host}:{port}/index.html")
    if not auto_serve_enabled():
        return None
    _spawn_daemon(root, research_id)
    deadline = time.monotonic() + spawn_timeout
    while time.monotonic() < deadline:
        url = live_observatory_url(root)
        if url is not None:
            return url
        time.sleep(0.1)
    return None


def _spawn_daemon(root: Path, research_id: str) -> None:
    log_path = observatory_log_path(root)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log:
        subprocess.Popen(
            [sys.executable, "-m", "sisyfus", "research", "serve", research_id, "--root", str(root)],
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(root),
        )


def resolve_serve_port(root: Path, research_id: str, requested: int | None) -> int:
    """Pick the port for a serve process; make an unqualified serve idempotent.

    An explicit request is honored verbatim. Otherwise: an alive daemon for the
    same run means nothing to do (signalled via AlreadyServing); one for another
    run is terminated so the stable derived port can be reclaimed.
    """
    if requested is not None:
        return int(requested)
    state = read_live_state(root)
    if state is not None:
        host, port = str(state.get("host") or "127.0.0.1"), int(state["port"])
        if server_alive(host, port):
            if state.get("research_id") == research_id:
                raise AlreadyServing(str(state.get("url") or f"http://{host}:{port}/index.html"))
            _terminate(int(state.get("pid") or 0), host, port)
    return derived_port(root)


class AlreadyServing(RuntimeError):
    """An alive daemon already serves this run; its URL is the message."""

    @property
    def url(self) -> str:
        return str(self.args[0])
