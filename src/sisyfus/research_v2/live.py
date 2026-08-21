"""Self-healing live Observatory.

One daemon per project root serves either the bootstrap Mission Control page or
the Arena page for the research run most recently worked on. Coordinates
persist in ``<root>/.sisyfus/observatory.json`` and the port is derived
deterministically from the project root, so one browser tab survives daemon
restarts and the bootstrap-to-research handoff.

``ensure_activity_observatory`` is used before TaskSpec compilation.
``ensure_observatory`` is called by every research CLI command after a run
exists. Both are idempotent, self-heal stale state, and open the browser once
per task by default.

Set ``SISYFUS_AUTO_SERVE=0`` to disable respawning and
``SISYFUS_AUTO_OPEN=0`` to disable browser opening (tests/headless CI).
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
import webbrowser
from pathlib import Path
from typing import Any

from ..activity import read_activity
from .workspace import atomic_write_json, utc_now

_PORT_BASE = 8700
_PORT_SPAN = 200


def observatory_state_path(root: Path) -> Path:
    return Path(root) / ".sisyfus" / "observatory.json"


def observatory_entry_path(root: Path) -> Path:
    return Path(root) / ".sisyfus" / "observatory.html"


def observatory_log_path(root: Path) -> Path:
    return Path(root) / ".sisyfus" / "observatory.log"


def observatory_open_state_path(root: Path) -> Path:
    return Path(root) / ".sisyfus" / "observatory-open.json"


def derived_port(root: Path) -> int:
    """Stable per-project port so the live URL survives daemon restarts."""
    digest = hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).digest()
    return _PORT_BASE + int.from_bytes(digest[:2], "big") % _PORT_SPAN


def auto_serve_enabled() -> bool:
    return os.environ.get("SISYFUS_AUTO_SERVE", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def auto_open_enabled() -> bool:
    return os.environ.get("SISYFUS_AUTO_OPEN", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def read_live_state(root: Path) -> dict[str, Any] | None:
    path = observatory_state_path(root)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict) or not state.get("port"):
        return None
    if state.get("root") and str(state["root"]) != str(Path(root).resolve()):
        return None
    return state


def write_live_state(
    root: Path,
    *,
    host: str,
    port: int,
    research_id: str,
) -> dict[str, Any]:
    state = {
        "schema_version": "sisyfus.observatory.v2",
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
    """URL of the running daemon for this root, or ``None``."""
    state = read_live_state(root)
    if not state:
        return None
    host, port = str(state.get("host") or "127.0.0.1"), int(state["port"])
    if not server_alive(host, port):
        return None
    return str(state.get("url") or f"http://{host}:{port}/index.html")


def _open_key(root: Path, fallback: str) -> str:
    activity = read_activity(root)
    return str(activity.get("task_id") or fallback)


def maybe_open_observatory(
    root: Path,
    url: str,
    *,
    open_key: str,
    force: bool = False,
) -> bool:
    """Open the stable monitor URL once per logical task.

    The marker is written before invoking the browser so concurrent CLI
    processes cannot open duplicate tabs. A failed browser launch is recorded
    and the URL remains available in command output.
    """
    if not auto_open_enabled():
        return False
    root = Path(root).resolve()
    marker_path = observatory_open_state_path(root)
    marker: dict[str, Any] = {}
    try:
        loaded = json.loads(marker_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            marker = loaded
    except (OSError, json.JSONDecodeError):
        marker = {}
    if (
        not force
        and marker.get("open_key") == open_key
        and marker.get("url") == url
    ):
        return False
    attempt = {
        "schema_version": "sisyfus.observatory-open.v1",
        "root": str(root),
        "url": url,
        "open_key": open_key,
        "attempted_at": utc_now(),
        "opened": None,
        "pid": os.getpid(),
    }
    atomic_write_json(marker_path, attempt)
    opened = False
    try:
        opened = bool(webbrowser.open(url, new=2, autoraise=True))
    except Exception:
        opened = False
    atomic_write_json(marker_path, {**attempt, "opened": opened})
    return opened


def _terminate(
    pid: int,
    host: str,
    port: int,
    *,
    timeout: float = 2.0,
) -> bool:
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


def _alive_url_for(root: Path, expected_id: str) -> str | None:
    state = read_live_state(root)
    if state is None:
        return None
    host, port = str(state.get("host") or "127.0.0.1"), int(state["port"])
    if not server_alive(host, port) or state.get("research_id") != expected_id:
        return None
    return str(state.get("url") or f"http://{host}:{port}/index.html")


def ensure_observatory(
    root: Path,
    research_id: str,
    *,
    spawn_timeout: float = 3.0,
    open_browser: bool = True,
) -> str | None:
    """Guarantee a live Arena daemon for a research run and open it once."""
    root = Path(root).resolve()
    state = read_live_state(root)
    if state is not None:
        host, port = str(state.get("host") or "127.0.0.1"), int(state["port"])
        if server_alive(host, port):
            url = str(state.get("url") or f"http://{host}:{port}/index.html")
            if state.get("research_id") == research_id:
                if open_browser:
                    maybe_open_observatory(
                        root,
                        url,
                        open_key=_open_key(root, research_id),
                    )
                return url
            if not auto_serve_enabled():
                return url
            if not _terminate(int(state.get("pid") or 0), host, port):
                return url
    if not auto_serve_enabled():
        return None
    _spawn_daemon(root, research_id)
    deadline = time.monotonic() + spawn_timeout
    while time.monotonic() < deadline:
        url = _alive_url_for(root, research_id)
        if url is not None:
            if open_browser:
                maybe_open_observatory(
                    root,
                    url,
                    open_key=_open_key(root, research_id),
                )
            return url
        time.sleep(0.1)
    return None


def ensure_activity_observatory(
    root: Path,
    task_id: str,
    *,
    spawn_timeout: float = 3.0,
    open_browser: bool = True,
) -> str | None:
    """Host and open the bootstrap Mission Control before a TaskSpec exists."""
    root = Path(root).resolve()
    monitor_id = f"activity:{task_id}"
    state = read_live_state(root)
    if state is not None:
        host, port = str(state.get("host") or "127.0.0.1"), int(state["port"])
        if server_alive(host, port):
            url = str(state.get("url") or f"http://{host}:{port}/index.html")
            if state.get("research_id") == monitor_id:
                if open_browser:
                    maybe_open_observatory(root, url, open_key=task_id)
                return url
            if not auto_serve_enabled():
                return url
            if not _terminate(int(state.get("pid") or 0), host, port):
                return url
    if not auto_serve_enabled():
        return None
    _spawn_activity_daemon(root, task_id)
    deadline = time.monotonic() + spawn_timeout
    while time.monotonic() < deadline:
        url = _alive_url_for(root, monitor_id)
        if url is not None:
            if open_browser:
                maybe_open_observatory(root, url, open_key=task_id)
            return url
        time.sleep(0.1)
    return None


def _spawn_daemon(root: Path, research_id: str) -> None:
    log_path = observatory_log_path(root)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "sisyfus",
                "research",
                "serve",
                research_id,
                "--root",
                str(root),
            ],
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(root),
        )


def _spawn_activity_daemon(root: Path, task_id: str) -> None:
    log_path = observatory_log_path(root)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "sisyfus",
                "research",
                "monitor-serve",
                "--task-id",
                task_id,
                "--root",
                str(root),
            ],
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(root),
        )


def resolve_serve_port(
    root: Path,
    research_id: str,
    requested: int | None,
) -> int:
    """Pick the stable port and make an unqualified serve idempotent."""
    if requested is not None:
        return int(requested)
    state = read_live_state(root)
    if state is not None:
        host, port = str(state.get("host") or "127.0.0.1"), int(state["port"])
        if server_alive(host, port):
            if state.get("research_id") == research_id:
                raise AlreadyServing(
                    str(state.get("url") or f"http://{host}:{port}/index.html")
                )
            _terminate(int(state.get("pid") or 0), host, port)
    return derived_port(root)


class AlreadyServing(RuntimeError):
    """An alive daemon already serves this run; its URL is the message."""

    @property
    def url(self) -> str:
        return str(self.args[0])
