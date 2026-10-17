"""Owned temporary share publication runtime; no controller or orchestration state.

Only numeric loopback Console HTTP is exposed by the separately owned Gateway.
Constructor/start/status/close are the public lifecycle; metadata never contains
either bearer or the private fragment URL. All created/failed artifacts remain.
"""
from __future__ import annotations

import http.client
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import threading
import time
from urllib.parse import quote, urlsplit

LOG_LIMIT = 1048576
TOKEN_LIMIT = 4096
REPORT_LIMIT = 4194304
LINE_LIMIT = 65536
_ERROR_TYPES = {c: c.__name__ for c in (
    Exception, RuntimeError, ValueError, TypeError, OSError, PermissionError,
    FileNotFoundError, FileExistsError, NotADirectoryError, IsADirectoryError,
    TimeoutError, UnicodeError, UnicodeDecodeError, KeyboardInterrupt,
    subprocess.TimeoutExpired,
)}


def _error_type(exc):
    return _ERROR_TYPES.get(type(exc), "Exception")


def validate_origin(value):
    """Pure admission: one exact numeric 127.0.0.1 HTTP authority with a port."""
    if not isinstance(value, str):
        raise ValueError("console origin")
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.username or parsed.password or parsed.path
            or parsed.query or parsed.fragment or not parsed.port
            or not 1 <= parsed.port <= 65535
            or value != f"http://127.0.0.1:{parsed.port}"):
        raise ValueError("console origin")
    return value


def validate_mission(value):
    """Pure bounded existing-style ASCII mission identifier, not a path."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError("mission identifier")
    return value


def validate_timeout(value):
    """Positive finite caller timeout; booleans are not durations."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("startup timeout")
    return float(value)


def _path(value, *, absolute=False):
    text = os.fspath(value)
    if not isinstance(text, str) or not text or "\0" in text or any(p in (".", "..") for p in text.split("/")):
        raise ValueError("path")
    if absolute and not os.path.isabs(text):
        raise ValueError("absolute runtime directory")
    return Path(os.path.abspath(text))


def _parent(path):
    """Pin an existing parent by NOFOLLOW descriptors; never create a chain."""
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _regular(path, limit, *, operator=False):
    """Read bounded bytes without links/FIFO blocking; validate both fstat views."""
    parent = _parent(path)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError("bounded regular input")
        if operator and (before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1):
            raise PermissionError("private operator file")
        parts = []
        remaining = before.st_size + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 65536))
            if not chunk:
                break
            parts.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(parts)
        after = os.fstat(fd)
        if (len(raw) != before.st_size or
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_nlink)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_nlink)):
            raise ValueError("input changed")
        return raw
    finally:
        os.close(fd)


class ShareRuntimeError(RuntimeError):
    """Fixed lifecycle failure; prose/secret/path of its cause is never copied."""
    def __init__(self, stage, error_type):
        super().__init__("share runtime failed")
        self.stage = stage
        self.error_type = error_type


class ShareRuntime:
    """Once-only Gateway/child ownership, independent of the original Console."""
    def __init__(self, console_origin, operator_token_file, mission_id, runtime_directory, *,
                 allow_messages=False, report_path=None, local_only=False,
                 cloudflared="cloudflared", startup_timeout=30.0, gateway_factory=None,
                 password_file=None):
        self.console_origin = validate_origin(console_origin)
        self.mission_id = validate_mission(mission_id)
        self.runtime_directory = _path(runtime_directory, absolute=True)
        self.operator_token_file = _path(operator_token_file)
        self.report_path = None if report_path is None else _path(report_path)
        self.password_file = None if password_file is None else _path(password_file, absolute=True)
        self.startup_timeout = validate_timeout(startup_timeout)
        if type(allow_messages) is not bool or type(local_only) is not bool:
            raise ValueError("boolean capability")
        self.allow_messages, self.local_only = allow_messages, local_only
        self.cloudflared = os.fspath(cloudflared)
        self._factory = gateway_factory
        self._state = "NEW"
        self._diagnostics = []
        self._operator = self._share = ""
        self._root_fd = None
        self._root_id = None
        self._files = {}
        self._gateway = self._thread = self._process = None
        self._loop_started = threading.Event()
        self._loop_done = threading.Event()
        self._loop_error = None
        self._start_called = False
        self._thread_start_called = False
        self._spawn_thread = None
        self._spawn_done = threading.Event()
        self._spawn_error = None
        self._shutdown_thread = None
        self._shutdown_done = threading.Event()
        self._shutdown_error = None
        self._selector = None
        self._buffers = {}
        self._output_bytes = self._log_bytes = 0
        self._deadline = None
        self._local_origin = self._public_origin = None
        self._access_file = None
        self._assigned = False
        self._announcement = False
        self._resources_closed = False
        self._returncode = None
        self._drain_lock = threading.Lock()

    def _mask(self, text):
        for token in (self._operator, self._share):
            if token:
                text = text.replace(token, "[REDACTED]")
        return text

    def _metadata(self):
        return {
            "schema": "sisyfus.share.runtime.v1", "state": self._state,
            "local_origin": self._local_origin, "public_origin": self._public_origin,
            "access_file": self._mask(str(self._access_file)) if self._access_file else None,
            "permissions": {"messages": self.allow_messages, "controls": False},
            "diagnostics": [dict(x) for x in self._diagnostics],
            "resources_closed": self._resources_closed, "process_returncode": self._returncode,
        }

    def _check_root(self):
        pinned = os.fstat(self._root_fd)
        current = os.stat(self.runtime_directory, follow_symlinks=False)
        if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != self._root_id or (pinned.st_dev, pinned.st_ino) != self._root_id:
            raise RuntimeError("runtime directory replaced")

    def _new_file(self, name):
        self._check_root()
        fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=self._root_fd)
        self._files[name] = fd
        return fd

    def _checked_file(self, name):
        self._check_root()
        fd = self._files[name]
        pinned = os.fstat(fd)
        current = os.stat(name, dir_fd=self._root_fd, follow_symlinks=False)
        if ((pinned.st_dev, pinned.st_ino) != (current.st_dev, current.st_ino)
                or not stat.S_ISREG(pinned.st_mode) or pinned.st_nlink != 1
                or pinned.st_uid != os.getuid() or stat.S_IMODE(pinned.st_mode) != 0o600):
            raise RuntimeError("private artifact replaced")
        return fd

    def _write(self, name, payload):
        fd = self._checked_file(name)
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        view = memoryview(payload)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError("artifact write")
            view = view[count:]
        os.fsync(fd)

    def _persist(self):
        if "state.json" not in self._files:
            return
        self._write("state.json", (json.dumps(self._metadata(), ensure_ascii=True) + "\n").encode())

    def _log(self, event, **fields):
        payload = (json.dumps({"event": event, **fields}, ensure_ascii=True) + "\n").encode()
        if self._log_bytes + len(payload) > LOG_LIMIT:
            raise ValueError("retained log limit")
        fd = self._checked_file("runtime.log")
        view = memoryview(payload)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError("log write")
            view = view[count:]
        self._log_bytes += len(payload)

    def _diagnose(self, stage, exc):
        item = {"stage": stage, "error_type": _error_type(exc)}
        if item not in self._diagnostics:
            self._diagnostics.append(item)
        self._state = "FAILED"
        if self._gateway is not None:
            try:
                self._gateway.revoke()
            except BaseException as failure:
                extra = {"stage": "gateway.revoke", "error_type": _error_type(failure)}
                if extra not in self._diagnostics:
                    self._diagnostics.append(extra)
        if self._root_fd is not None:
            try:
                self._log("failure", **item)
                self._persist()
            except Exception as failure:
                extra = {"stage": "retained.diagnostic", "error_type": _error_type(failure)}
                if extra not in self._diagnostics:
                    self._diagnostics.append(extra)

    def _access(self, origin):
        private_url = origin + "/"
        if self.password_file is None:
            private_url += "#token=" + quote(self._share, safe="")
        payload = {"schema": "sisyfus.share.access.v1", "mission_id": self.mission_id,
                   "permissions": {"messages": self.allow_messages, "controls": False},
                   "private_url": private_url}
        self._write("access.json", (json.dumps(payload) + "\n").encode())

    def _serve(self):
        self._loop_started.set()
        try:
            self._gateway.serve_forever(poll_interval=0.05)
        except BaseException as exc:
            self._loop_error = _error_type(exc)
        finally:
            self._loop_done.set()

    def _spawn(self, argv, env, home):
        try:
            self._process = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=str(home), env=env, shell=False, start_new_session=True, bufsize=0,
            )
            self._process.stdin.close()
        except BaseException as exc:
            self._spawn_error = _error_type(exc)
        finally:
            self._spawn_done.set()

    def start(self):
        """Start once; retain failures. URL assignment is not a connection proof."""
        if self._start_called or self._state != "NEW":
            raise ShareRuntimeError("start.once", "RuntimeError")
        self._start_called = True
        self._state = "STARTING"
        self._deadline = time.monotonic() + self.startup_timeout
        stage = "password.read" if self.password_file is not None else "operator.read"
        try:
            password_verifier = None
            if self.password_file is not None:
                from .share_password import load_verifier
                password_verifier = load_verifier(self.password_file)
            stage = "operator.read"
            raw = _regular(self.operator_token_file, TOKEN_LIMIT, operator=True)
            self._operator = raw.decode("ascii").removesuffix("\n")
            if not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", self._operator):
                raise ValueError("plain operator token")
            stage = "report.admission"
            if self.report_path is not None:
                _regular(self.report_path, REPORT_LIMIT)
            stage = "runtime.create"
            parent = _parent(self.runtime_directory)
            try:
                os.mkdir(self.runtime_directory.name, 0o700, dir_fd=parent)
                self._root_fd = os.open(self.runtime_directory.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            finally:
                os.close(parent)
            info = os.fstat(self._root_fd)
            self._root_id = info.st_dev, info.st_ino
            self._check_root()
            self._new_file("runtime.log")
            self._new_file("state.json")
            self._persist()
            stage = "gateway.construct"
            factory = self._factory
            if factory is None:
                from .share_gateway import ShareGateway
                factory = ShareGateway
            password_options = {} if self.password_file is None else {"password_verifier": password_verifier}
            self._gateway = factory(self.console_origin, self._operator, self.mission_id,
                                    port=0, allow_messages=self.allow_messages, report_path=self.report_path,
                                    **password_options)
            self._check_root()
            self._share = self._gateway.token
            if (not isinstance(self._share, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{16,4096}", self._share)
                    or self._share == self._operator):
                raise ValueError("distinct share credential")
            self._local_origin = validate_origin(self._gateway.origin)
            if self._gateway.url != self._local_origin + "/":
                raise ValueError("credential-free gateway URL")
            self._new_file("access.json")
            self._access_file = self.runtime_directory / "access.json"
            self._access(self._local_origin)
            stage = "gateway.start"
            self._thread = threading.Thread(target=self._serve, name="sisyfus-share-gateway", daemon=True)
            self._thread_start_called = True
            self._thread.start()
            remaining = self._deadline - time.monotonic()
            if remaining <= 0 or not self._loop_started.wait(remaining):
                raise TimeoutError("gateway start deadline")
            if self.local_only:
                self._state = "LOCAL_ONLY"
                self._persist()
                return self.status()
            stage = "child.prepare"
            self._check_root()
            os.mkdir("home", 0o700, dir_fd=self._root_fd)
            os.mkdir("tmp", 0o700, dir_fd=self._root_fd)
            home_fd = os.open("home", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self._root_fd)
            try:
                config_fd = os.open("isolated.yml", os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=home_fd)
                try:
                    os.write(config_fd, b"{}\n")
                    os.fsync(config_fd)
                finally:
                    os.close(config_fd)
            finally:
                os.close(home_fd)
            home = self.runtime_directory / "home"
            self._check_root()
            executable = self.cloudflared if os.path.isabs(self.cloudflared) else shutil.which(self.cloudflared)
            if not executable:
                raise FileNotFoundError("cloudflared executable")
            argv = [executable, "tunnel", "--config", str(home / "isolated.yml"),
                    "--no-autoupdate", "--url", self._local_origin, "--metrics", "127.0.0.1:0",
                    "--output", "json", "--loglevel", "info", "--management-diagnostics=false"]
            env = {"HOME": str(home), "XDG_CONFIG_HOME": str(home), "TMPDIR": str(self.runtime_directory / "tmp"),
                   "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
            stage = "child.spawn"
            self._spawn_thread = threading.Thread(target=self._spawn, args=(argv, env, home),
                                                   name="sisyfus-share-spawn", daemon=True)
            self._spawn_thread.start()
            remaining = self._deadline - time.monotonic()
            if remaining <= 0 or not self._spawn_done.wait(remaining):
                raise TimeoutError("child spawn deadline")
            if self._spawn_error is not None:
                raise ShareRuntimeError(stage, self._spawn_error)
            self._selector = selectors.DefaultSelector()
            for stream in (self._process.stdout, self._process.stderr):
                os.set_blocking(stream.fileno(), False)
                self._selector.register(stream, selectors.EVENT_READ)
                self._buffers[stream.fileno()] = b""
            stage = "child.startup"
            while True:
                meta = self.status()
                if meta["state"] == "FAILED":
                    failure = self._diagnostics[0]
                    raise ShareRuntimeError(failure["stage"], failure["error_type"])
                if meta["state"] in {"HOST_ASSIGNED", "CONNECTED"}:
                    return meta
                remaining = self._deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("startup deadline")
                time.sleep(min(0.01, remaining))
        except BaseException as exc:
            self._diagnose(stage, exc)
            if isinstance(exc, KeyboardInterrupt):
                raise
            if isinstance(exc, ShareRuntimeError):
                raise
            raise ShareRuntimeError(stage, _error_type(exc)) from None

    def _event(self, raw):
        line = raw.decode("utf-8")
        if "Your quick Tunnel has been created" in line:
            self._announcement = True
        if self._announcement:
            for candidate in re.findall(r'https://[^\s"\'<>|]+', line):
                uri = urlsplit(candidate)
                valid = (uri.scheme == "https" and not uri.username and not uri.password
                         and not uri.query and not uri.fragment and uri.path in {"", "/"}
                         and uri.netloc == uri.hostname and uri.hostname is not None
                         and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.trycloudflare\.com", uri.hostname))
                if not valid:
                    continue
                origin = "https://" + uri.hostname
                if self._operator in origin or self._share in origin:
                    raise ValueError("secret in assigned origin")
                if self._public_origin is not None:
                    if origin != self._public_origin:
                        raise ValueError("public origin changed")
                    continue
                self._assigned = True
                self._gateway.set_public_origin(origin)
                self._public_origin = origin
                self._state = "HOST_ASSIGNED"
                self._access(origin)
                self._log("host_assigned")
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            event = None
        if (isinstance(event, dict) and event.get("message") == "Registered tunnel connection"
                and type(event.get("connIndex")) is int and event["connIndex"] >= 0
                and self._public_origin is not None):
            if self._state != "CONNECTED" and time.monotonic() > self._deadline:
                raise TimeoutError("late connection")
            self._state = "CONNECTED"
            self._log("registered_connection")
        else:
            self._log("child_event")

    def _consume(self):
        for _ in range(8):
            events = self._selector.select(0)
            if not events:
                break
            for key, _mask in events:
                stream = key.fileobj
                fd = stream.fileno()
                try:
                    chunk = os.read(fd, 16384)
                except BlockingIOError:
                    continue
                if not chunk:
                    self._selector.unregister(stream)
                    continue
                self._output_bytes += len(chunk)
                if self._output_bytes > LOG_LIMIT:
                    raise ValueError("child output limit")
                buf = self._buffers[fd] + chunk
                while b"\n" in buf:
                    line, _, buf = buf.partition(b"\n")
                    if len(line) > LINE_LIMIT:
                        raise ValueError("child line limit")
                    self._event(line)
                if len(buf) > LINE_LIMIT:
                    raise ValueError("child buffer limit")
                self._buffers[fd] = buf

    def status(self):
        """Safe finite supervision; no restart, new controller, or remote probe."""
        # Keep poll/reaping outside the owned close check-to-signal interval.
        with self._drain_lock:
            if self._state in {"NEW", "CLOSED", "FAILED"}:
                return self._metadata()
            try:
                self._check_root()
                if self._loop_done.is_set():
                    self._diagnose("gateway.loop", RuntimeError())
                    if self._loop_error is not None:
                        self._diagnostics[-1] = {"stage": "gateway.loop", "error_type": self._loop_error}
                elif self._process is not None:
                    if self._selector is not None:
                        self._consume()
                    self._returncode = self._process.poll()
                    if self._returncode is not None:
                        self._diagnose("child.exit", RuntimeError())
                    elif self._state != "CONNECTED" and time.monotonic() >= self._deadline:
                        self._diagnose("child.startup", TimeoutError())
                if self._state != "FAILED":
                    self._persist()
            except BaseException as exc:
                self._diagnose("runtime.observe", exc)
                if isinstance(exc, KeyboardInterrupt):
                    raise
            return self._metadata()

    def _shutdown(self):
        try:
            self._gateway.shutdown()
        except BaseException as exc:
            self._shutdown_error = _error_type(exc)
        finally:
            self._shutdown_done.set()

    def close(self):
        """Revoke and drain only owned resources; errors never fabricate CLOSED."""
        with self._drain_lock:
            if self._resources_closed:
                return self._metadata()
            stage = "gateway.revoke"
            try:
                if self._gateway is not None:
                    self._gateway.revoke()
                    if self._thread_start_called and not self._loop_started.is_set() and self._thread.ident is None:
                        self._loop_started.wait(2)
                    if self._thread is not None and self._thread.is_alive():
                        stage = "gateway.shutdown"
                        if self._shutdown_thread is None:
                            self._shutdown_thread = threading.Thread(target=self._shutdown, name="sisyfus-share-shutdown", daemon=True)
                            self._shutdown_thread.start()
                        self._shutdown_thread.join(2)
                        if not self._shutdown_done.is_set() or self._shutdown_error is not None:
                            raise ShareRuntimeError(stage, self._shutdown_error or "TimeoutError")
                        self._thread.join(2)
                        if self._thread.is_alive():
                            raise TimeoutError("gateway loop drain")
                    self._gateway.server_close()
                stage = "child.close"
                if self._spawn_thread is not None:
                    self._spawn_thread.join(2)
                    if self._spawn_thread.is_alive() or not self._spawn_done.is_set():
                        raise TimeoutError("child spawn unresolved")
                if self._process is not None:
                    if self._process.returncode is None:
                        try:
                            os.killpg(self._process.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass  # Already gone is a known normal process boundary.
                        try:
                            self._returncode = self._process.wait(timeout=1)
                        except subprocess.TimeoutExpired:
                            if self._process.returncode is None:
                                os.killpg(self._process.pid, signal.SIGKILL)
                                self._returncode = self._process.wait(timeout=1)
                            else:
                                self._returncode = self._process.returncode
                    else:
                        self._returncode = self._process.returncode
                    for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
                        if stream is not None:
                            stream.close()
                if self._selector is not None:
                    self._selector.close()
                self._resources_closed = True
                self._state = "CLOSED"
                if self._root_fd is not None:
                    try:
                        self._persist()
                    except Exception as exc:
                        item = {"stage": "retained.close", "error_type": _error_type(exc)}
                        if item not in self._diagnostics:
                            self._diagnostics.append(item)
                for fd in self._files.values():
                    os.close(fd)
                self._files.clear()
                if self._root_fd is not None:
                    os.close(self._root_fd)
                    self._root_fd = None
                return self._metadata()
            except BaseException as exc:
                self._diagnose(stage, exc)
                raise

