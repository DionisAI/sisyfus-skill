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

from contextlib import ExitStack
import errno
import hashlib
import json
import os
import secrets
import signal
import socket
import stat
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
_TRASH_BIN = "/usr/bin/trash"


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


class LiveStateRetained(RuntimeError):
    """Explicit, sanitized failure with the intended retained resource location."""

    def __init__(
        self, *, reason: str, path: Path, error_type: str = "Validation",
        returncode: int | None = None,
    ) -> None:
        self.reason = reason
        self.path = path
        self.detail = {"type": error_type, "returncode": returncode}
        super().__init__(
            f"Live state retained: reason={reason}; path={path}; "
            f"type={error_type}; returncode={returncode}"
        )


def _retire_identity(item: os.stat_result) -> tuple[int, int]:
    return item.st_dev, item.st_ino


def _retire_state_pin(item: os.stat_result) -> tuple[int, int, int, int]:
    return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns


def _retire_open(stack: ExitStack, path: str | Path, flags: int, **kwargs: Any) -> int:
    descriptor = os.open(path, flags, **kwargs)
    stack.callback(os.close, descriptor)
    return descriptor


def _retire_bytes(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, min(8192, 65537 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > 65536:
            raise ValueError("state size limit")


def _stage_state(dfd: int, stfd: int) -> None:
    os.rename("observatory.json", "observatory.json", src_dir_fd=dfd, dst_dir_fd=stfd)


def clear_live_state(root: Path, *, pid: int | None = None) -> None:
    """Retire admitted state recoverably; detect races and retain mismatches."""
    retained_path = observatory_state_path(Path(root).absolute())
    if not all(operation in os.supports_dir_fd for operation in
               (os.open, os.mkdir, os.rename, os.stat)) or not all(
        hasattr(os, flag) for flag in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC", "O_NONBLOCK")
    ):
        raise LiveStateRetained(reason="no_dir_fd", path=retained_path)
    reason = "root_alias"
    try:
        rp = Path(root).resolve()
    except (OSError, RuntimeError):
        raise LiveStateRetained(reason=reason, path=retained_path, error_type="OSError") from None
    retained_path = observatory_state_path(rp)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    state_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        with ExitStack() as descriptors:
            try:
                rfd = _retire_open(descriptors, rp, directory_flags)
            except FileNotFoundError:
                return
            if _retire_identity(os.stat(rp, follow_symlinks=False)) != _retire_identity(os.fstat(rfd)):
                raise LiveStateRetained(reason=reason, path=retained_path)

            reason = "parent_alias"
            try:
                dfd = _retire_open(descriptors, ".sisyfus", directory_flags, dir_fd=rfd)
            except FileNotFoundError:
                return
            parent_pin = os.fstat(dfd)
            if not stat.S_ISDIR(parent_pin.st_mode) or parent_pin.st_uid != os.geteuid():
                raise LiveStateRetained(reason=reason, path=retained_path)

            reason = "state_unadmitted"
            try:
                sfd = _retire_open(descriptors, "observatory.json", state_flags, dir_fd=dfd)
            except FileNotFoundError:
                return
            except OSError as error:
                if error.errno == errno.ELOOP:
                    raise LiveStateRetained(reason="state_symlink", path=retained_path) from None
                raise
            admitted = os.fstat(sfd)
            if (not stat.S_ISREG(admitted.st_mode) or admitted.st_nlink != 1
                    or admitted.st_uid != os.geteuid() or admitted.st_size > 65536):
                raise LiveStateRetained(reason=reason, path=retained_path)
            try:
                original = _retire_bytes(sfd)
                state = json.loads(original)
            except (ValueError, UnicodeDecodeError, RecursionError):
                raise LiveStateRetained(reason=reason, path=retained_path, error_type="InvalidState") from None
            if (not isinstance(state, dict) or not state.get("port")
                    or state.get("root") != str(rp) or not isinstance(state.get("pid"), int)
                    or isinstance(state.get("pid"), bool)):
                raise LiveStateRetained(reason=reason, path=retained_path)
            if pid is not None and state["pid"] != pid:
                return

            if not os.path.isabs(_TRASH_BIN) or not os.access(_TRASH_BIN, os.X_OK):
                raise LiveStateRetained(reason="trash_missing", path=retained_path)
            reason = "state_changed"
            pinned = _retire_state_pin(admitted)
            current = os.stat("observatory.json", dir_fd=dfd, follow_symlinks=False)
            if _retire_state_pin(current) != pinned or _retire_state_pin(os.fstat(sfd)) != pinned:
                raise LiveStateRetained(reason=reason, path=retained_path)

            reason = "stage_failed"
            name = f".observatory-retire-{os.getpid()}-{secrets.token_hex(8)}"
            os.mkdir(name, 0o700, dir_fd=dfd)
            stfd = _retire_open(descriptors, name, directory_flags, dir_fd=dfd)
            stage_pin = os.fstat(stfd)
            if (not stat.S_ISDIR(stage_pin.st_mode) or stat.S_IMODE(stage_pin.st_mode) != 0o700
                    or stage_pin.st_uid != os.geteuid() or stage_pin.st_dev != parent_pin.st_dev):
                raise LiveStateRetained(reason=reason, path=retained_path)
            _stage_state(dfd, stfd)
            # A concurrent publication may have been displaced. Never restore it.
            retained_path = rp / ".sisyfus" / name
            reason = "staged_mismatch"
            staged = os.stat("observatory.json", dir_fd=stfd, follow_symlinks=False)
            if _retire_state_pin(staged) != pinned or staged.st_nlink != 1:
                raise LiveStateRetained(reason=reason, path=retained_path)
            with ExitStack() as staged_descriptors:
                checkfd = _retire_open(staged_descriptors, "observatory.json", state_flags, dir_fd=stfd)
                try:
                    identical = _retire_bytes(checkfd) == original
                except ValueError:
                    identical = False
                checked = os.fstat(checkfd)
            if (not identical or _retire_state_pin(checked) != pinned or checked.st_nlink != 1
                    or _retire_state_pin(os.stat("observatory.json", dir_fd=stfd, follow_symlinks=False)) != pinned):
                raise LiveStateRetained(reason=reason, path=retained_path)
            if (_retire_identity(os.stat(rp / ".sisyfus", follow_symlinks=False)) != _retire_identity(parent_pin)
                    or _retire_identity(os.stat(retained_path, follow_symlinks=False)) != _retire_identity(stage_pin)):
                raise LiveStateRetained(reason=reason, path=retained_path)

            reason = "trash_failed"
            try:
                outcome = subprocess.run(
                    [_TRASH_BIN, str(retained_path)], stdin=subprocess.DEVNULL,
                    capture_output=True, check=False, timeout=30,
                )
            except subprocess.TimeoutExpired:
                raise LiveStateRetained(reason=reason, path=retained_path, error_type="TimeoutExpired") from None
            if outcome.returncode != 0:
                raise LiveStateRetained(reason=reason, path=retained_path,
                                        error_type="TrashResult", returncode=outcome.returncode)
            try:
                os.stat(name, dir_fd=dfd, follow_symlinks=False)
            except FileNotFoundError:
                return
            raise LiveStateRetained(reason=reason, path=retained_path,
                                    error_type="TrashResult", returncode=outcome.returncode)
    except OSError:
        raise LiveStateRetained(reason=reason, path=retained_path, error_type="OSError") from None


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
