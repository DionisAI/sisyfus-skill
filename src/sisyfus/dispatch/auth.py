"""Password verifier, persistent cookie sessions and login throttling for dispatch."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from .config import write_private_json

VERIFIER_SCHEMA = "sisyfus.dispatch.password.v1"
MIN_PASSWORD_LENGTH = 12
SESSION_SECONDS = 30 * 24 * 3600
MAX_SESSIONS = 32
_SCRYPT = {"n": 2**15, "r": 8, "p": 1}


class AuthError(ValueError):
    """Password or session problem; messages are safe to show to the operator."""


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _scrypt(password: str, salt: bytes, params: dict[str, int]) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=params["n"], r=params["r"],
                          p=params["p"], maxmem=128 * 1024 * 1024, dklen=32)


def write_password(path: Path, password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    salt = secrets.token_bytes(16)
    write_private_json(path, {"schema_version": VERIFIER_SCHEMA, "salt": _b64(salt),
                              "hash": _b64(_scrypt(password, salt, _SCRYPT)), **_SCRYPT})


def load_verifier(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthError("no dispatch password is set; run `sisyfus dispatch password`") from exc
    if raw.get("schema_version") != VERIFIER_SCHEMA:
        raise AuthError("unsupported password verifier")
    if path.stat().st_mode & 0o077:
        raise AuthError(f"password verifier must not be readable by others: {path}")
    return raw


def verify_password(verifier: dict[str, Any], candidate: str) -> bool:
    params = {key: int(verifier[key]) for key in ("n", "r", "p")}
    expected = base64.b64decode(verifier["hash"])
    actual = _scrypt(candidate, base64.b64decode(verifier["salt"]), params)
    return hmac.compare_digest(expected, actual)


class SessionStore:
    """Server-side sessions keyed by token digest; tokens themselves are never stored.

    The file is the source of truth: another process (`sisyfus dispatch password`,
    `logout-all`) may rewrite it, so every operation reloads it when it changed.
    """

    def __init__(self, path: Path, *, lifetime: int = SESSION_SECONDS) -> None:
        self.path = path
        self.lifetime = lifetime
        self._lock = threading.Lock()
        self._sessions: dict[str, float] = {}
        self._stamp: tuple[int, int] | None = None
        self._reload()

    def _file_stamp(self) -> tuple[int, int] | None:
        try:
            info = self.path.stat()
        except OSError:
            return None
        return (info.st_ino, info.st_mtime_ns)

    def _reload(self) -> None:
        stamp = self._file_stamp()
        if stamp == self._stamp and stamp is not None:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._sessions = {str(k): float(v) for k, v in (raw.get("sessions") or {}).items()}
        except (OSError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
            self._sessions = {}
        self._stamp = stamp

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _persist(self) -> None:
        write_private_json(self.path, {"sessions": self._sessions})
        self._stamp = self._file_stamp()

    def create(self) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._reload()
            self._sessions = {k: v for k, v in self._sessions.items() if v > now}
            while len(self._sessions) >= MAX_SESSIONS:
                self._sessions.pop(min(self._sessions, key=self._sessions.get))
            self._sessions[self._digest(token)] = now + self.lifetime
            self._persist()
        return token

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        with self._lock:
            self._reload()
            expiry = self._sessions.get(self._digest(token))
        return expiry is not None and expiry > time.time()

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._reload()
            if self._sessions.pop(self._digest(token), None) is not None:
                self._persist()

    def revoke_all(self) -> None:
        with self._lock:
            self._sessions = {}
            self._persist()


class LoginThrottle:
    """Failed-login limits per client address plus a higher global ceiling.

    Callers check and verify while holding `verify_lock`, so concurrent attempts
    cannot all pass the check before any failure is recorded.
    """

    def __init__(self, *, limit: int = 5, global_limit: int = 30, window: float = 300.0) -> None:
        self.limit = limit
        self.global_limit = global_limit
        self.window = window
        self._failures: list[tuple[float, str]] = []
        self.verify_lock = threading.Lock()

    def blocked_for(self, client: str) -> float:
        now = time.monotonic()
        self._failures = [(t, c) for t, c in self._failures if now - t < self.window]
        mine = [t for t, c in self._failures if c == client]
        if len(mine) >= self.limit:
            return self.window - (now - mine[0])
        if len(self._failures) >= self.global_limit:
            return self.window - (now - self._failures[0][0])
        return 0.0

    def failed(self, client: str) -> None:
        self._failures.append((time.monotonic(), client))

    def succeeded(self, client: str) -> None:
        self._failures = [(t, c) for t, c in self._failures if c != client]
