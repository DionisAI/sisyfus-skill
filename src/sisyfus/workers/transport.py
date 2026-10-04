from __future__ import annotations

import json
import os
import queue
import select
import shutil
import signal
import subprocess
import threading
import time
from typing import Any, Sequence


class ProtocolError(RuntimeError):
    pass


class Process:
    """Bounded JSONL transport. Never uses a shell or waits for an unbounded line."""

    def __init__(self, argv: Sequence[str], *, cwd: str, env: dict[str, str], timeout: float,
                 max_bytes: int = 8_000_000):
        self.deadline = time.monotonic() + timeout
        self.max_bytes = max_bytes
        self.bytes = 0
        self.error: Exception | None = None
        self.queue: queue.Queue[Any] = queue.Queue(maxsize=512)
        self.lock = threading.Lock()
        self.closed = threading.Event()
        self.eof = False
        self.process = subprocess.Popen(list(argv), cwd=cwd, env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        shell=False, start_new_session=(os.name == "posix"))
        self.threads = [threading.Thread(target=self._read, args=(self.process.stdout, True), daemon=True),
                        threading.Thread(target=self._read, args=(self.process.stderr, False), daemon=True)]
        for thread in self.threads:
            thread.start()

    def _read(self, stream: Any, stdout: bool) -> None:
        try:
            while not self.closed.is_set():
                raw = stream.readline(min(self.max_bytes, 1_000_000) + 1)
                if not raw:
                    if stdout:
                        self.eof = True
                    return
                with self.lock:
                    self.bytes += len(raw)
                    if self.bytes > self.max_bytes or len(raw) > 1_000_000:
                        raise ProtocolError("worker output limit exceeded")
                if stdout:
                    try:
                        value = json.loads(raw)
                    except (ValueError, UnicodeError) as exc:
                        raise ProtocolError("worker emitted invalid JSONL") from exc
                    if not isinstance(value, dict):
                        raise ProtocolError("worker event must be an object")
                    while not self.closed.is_set():
                        try:
                            self.queue.put(value, timeout=.05)
                            break
                        except queue.Full:
                            continue
        except Exception as exc:
            self.error = exc
        finally:
            stream.close()

    def send(self, value: dict[str, Any]) -> None:
        self.send_bytes((json.dumps(value, allow_nan=False) + "\n").encode())

    def send_bytes(self, value: bytes, *, close: bool = False) -> None:
        if self.process.stdin is None:
            raise ProtocolError("worker stdin unavailable")
        fd = self.process.stdin.fileno()
        if os.name == "posix":
            os.set_blocking(fd, False)
            offset = 0
            while offset < len(value):
                if time.monotonic() >= self.deadline:
                    raise TimeoutError("worker input deadline exceeded")
                if self.error:
                    raise self.error
                if select.select([], [fd], [], .05)[1]:
                    try:
                        offset += os.write(fd, value[offset:offset + 8192])
                    except BlockingIOError:
                        pass
        else:
            raise OSError("native worker transport currently requires POSIX")
        if close:
            self.process.stdin.close()

    def receive(self, interval: float = .05) -> dict[str, Any] | None:
        if self.error:
            raise self.error
        if time.monotonic() >= self.deadline:
            raise TimeoutError("worker deadline exceeded")
        try:
            return self.queue.get(timeout=interval)
        except queue.Empty:
            if self.eof:
                raise EOFError("worker stream ended")
            return None

    def wait(self) -> int:
        remaining = max(.01, self.deadline - time.monotonic())
        code = self.process.wait(timeout=remaining)
        if self.error:
            raise self.error
        return code

    def close(self) -> None:
        self.closed.set()
        # Kill the process group even if the group leader already exited.
        try:
            if os.name == "posix":
                os.killpg(self.process.pid, signal.SIGKILL)
            elif self.process.poll() is None:
                self.process.kill()
        except ProcessLookupError:
            pass
        try:
            self.process.wait(timeout=3)
        finally:
            if self.process.stdin is not None and not self.process.stdin.closed:
                self.process.stdin.close()
            for thread in self.threads:
                thread.join(timeout=1)


def probe(command: Sequence[str]) -> dict[str, Any]:
    if not command or not shutil.which(command[0]):
        return {"available": False, "version": None, "authenticated": None, "reason": "executable not found"}
    try:
        from .protocol import environment
        proc = subprocess.run([*command, "--version"], capture_output=True, timeout=10, shell=False, env=environment())
        return {"available": proc.returncode == 0, "version": proc.stdout[:500].decode(errors="replace").strip(),
                "authenticated": None, "reason": None if proc.returncode == 0 else "version probe failed"}
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "version": None, "authenticated": None, "reason": "version probe failed"}
