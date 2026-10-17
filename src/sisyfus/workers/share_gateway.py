"""Opt-in, fixed-mission HTTP adapter. This module owns no controller or DB."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import stat
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

MAX_BODY_BYTES = 16_384
MAX_MESSAGE_CHARS = 4_000
MAX_UPSTREAM_BYTES = 8_388_608
UPSTREAM_SECONDS = 10.0
MAX_REPORT_BYTES = 4_194_304
MAX_HANDLERS = 16
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 60.0
MAX_SESSIONS = 64
SESSION_SECONDS = 28_800
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_PUBLIC_HOST = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.trycloudflare\.com\Z")
_API = {"/api/share/snapshot", "/api/share/messages", "/api/share/message", "/api/share/report"}
_AUTH_API = {"/api/share/login", "/api/share/logout"}


class _ShareError(Exception):
    def __init__(self, code: str, status: int = 502):
        self.code, self.status = code, status
        super().__init__(code)


def _strict_json(raw: bytes) -> Any:
    def constant(_value):
        raise ValueError("nonfinite JSON")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(raw.decode("utf-8"), parse_constant=constant, object_pairs_hook=pairs)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


class _Deadline:
    def __init__(self):
        self.end = time.monotonic() + UPSTREAM_SECONDS

    def remaining(self) -> float:
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise _ShareError("UPSTREAM_TIMEOUT", 504)
        return remaining


class _DeadlineReader(io.RawIOBase):
    """Apply the SAME deadline to each raw recv, including drip-fed headers."""
    def __init__(self, raw, sock, deadline):
        super().__init__()
        self.raw, self.sock, self.deadline = raw, sock, deadline

    def readable(self):
        return True

    def readinto(self, buffer):
        self.sock.settimeout(self.deadline.remaining())
        count = self.raw.readinto(buffer)
        self.deadline.remaining()
        return count

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


class _DeadlineSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def __getattr__(self, name):
        return getattr(self.sock, name)

    def sendall(self, data, *args):
        self.sock.settimeout(self.deadline.remaining())
        self.sock.sendall(data, *args)
        self.deadline.remaining()

    def makefile(self, mode, *args, **kwargs):
        if mode != "rb":
            raise _ShareError("UPSTREAM_IO_ERROR")
        # SocketIO retains the fd if HTTPConnection closes a will-close socket
        # before the response body is read. Its close releases that exact ref.
        raw = self.sock.makefile("rb", buffering=0)
        return io.BufferedReader(_DeadlineReader(raw, self.sock, self.deadline))


class _Report:
    """Pin every path component and the selected regular file, never follow links."""
    def __init__(self, path):
        candidate = Path(path)
        if ".." in candidate.parts:
            raise ValueError("report path must be normalized")
        self.path = candidate.absolute()
        try:
            data, identity = self._read()
            data.decode("utf-8")
        except (OSError, ValueError, UnicodeError):
            raise ValueError("report requires bounded regular UTF-8 HTML with no symlink components") from None
        self.identity, self.sha256 = identity, hashlib.sha256(data).hexdigest()

    def _read(self):
        fds = []
        try:
            directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            fds.append(directory)
            identity = [(os.fstat(directory).st_dev, os.fstat(directory).st_ino)]
            for part in self.path.parts[1:-1]:
                directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                    dir_fd=directory)
                fds.append(directory)
                entry = os.fstat(directory)
                identity.append((entry.st_dev, entry.st_ino))
            fd = os.open(self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                         dir_fd=directory)
            fds.append(fd)
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_REPORT_BYTES:
                raise ValueError("invalid report file")
            data = bytearray()
            while True:
                chunk = os.read(fd, min(65_536, MAX_REPORT_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > MAX_REPORT_BYTES:
                    raise ValueError("report byte bound")
            after = os.fstat(fd)
            leaf = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            if leaf(before) != leaf(after) or len(data) != after.st_size:
                raise ValueError("report changed during read")
            identity.append(leaf(after))
            return bytes(data), tuple(identity)
        finally:
            for fd in reversed(fds):
                os.close(fd)

    def read(self):
        try:
            data, identity = self._read()
        except (OSError, ValueError):
            raise _ShareError("REPORT_CHANGED", 409) from None
        if identity != self.identity or hashlib.sha256(data).hexdigest() != self.sha256:
            raise _ShareError("REPORT_CHANGED", 409)
        return data


class ShareGateway(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True
    request_queue_size = 64  # Listen backlog above MAX_HANDLERS: a 16-client burst must reach admission.

    def __init__(self, upstream_origin, operator_token, mission_id, *, port=0,
                 allow_messages=False, report_path=None, password_verifier=None):
        if not isinstance(upstream_origin, str):
            raise ValueError("numeric loopback HTTP console origin required")
        try:
            upstream = urlsplit(upstream_origin)
            upstream_port = upstream.port
        except ValueError:
            raise ValueError("numeric loopback HTTP console origin required") from None
        if (upstream.scheme != "http" or upstream.hostname != "127.0.0.1"
                or upstream_port is None or not 1 <= upstream_port <= 65535
                or upstream.netloc != f"127.0.0.1:{upstream_port}"
                or upstream.path or upstream.query or upstream.fragment
                or "?" in upstream_origin or "#" in upstream_origin):
            raise ValueError("numeric loopback HTTP console origin required")
        if not isinstance(operator_token, str) or not re.fullmatch(r"[\x21-\x7e]{1,4096}", operator_token):
            raise ValueError("bounded operator bearer required")
        if not isinstance(mission_id, str) or not _ID.fullmatch(mission_id):
            raise ValueError("bounded mission identifier required")
        if type(port) is not int or not 0 <= port <= 65535 or type(allow_messages) is not bool:
            raise ValueError("invalid share port or message permission")
        self._password_verifier, self._verify_password = None, None
        if password_verifier is not None:
            # The helper owns strict validation/costs. Default token mode has no
            # helper dependency; validation and the independent copy precede bind.
            from .share_password import validate_verifier, verify_password
            self._password_verifier = validate_verifier(password_verifier)
            self._verify_password = verify_password
        token = secrets.token_urlsafe(32)
        if (hmac.compare_digest(token, operator_token)
                or self.password_required and token == self._password_verifier["digest"]):
            raise ValueError("share credential generation collision")
        self._operator_token, self.token = operator_token, token
        self._upstream_origin, self._upstream_port = upstream_origin, upstream_port
        self.mission_id, self.allow_messages = mission_id, allow_messages
        self._gate_lock = threading.Lock()
        self._kdf_lock = threading.Lock()
        self._login_attempts = deque()
        self._sessions = {}
        self._public_origin = None
        self._revoked = False
        self._slots = threading.BoundedSemaphore(MAX_HANDLERS)
        self._report = _Report(report_path) if report_path is not None else None
        if self._report and self._has_secret(self._report.read().decode("utf-8")):
            raise ValueError("selected report contains a credential")
        super().__init__(("127.0.0.1", port), _Handler)

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server_port}"

    @property
    def url(self):
        return self.origin + "/"

    @property
    def password_required(self):
        return self._password_verifier is not None

    def set_public_origin(self, url):
        if not isinstance(url, str):
            raise ValueError("root HTTPS trycloudflare origin required")
        try:
            parsed = urlsplit(url)
            host = parsed.hostname
            valid = (parsed.scheme == "https" and isinstance(host, str) and _PUBLIC_HOST.fullmatch(host)
                     and parsed.netloc == host and parsed.path in {"", "/"}
                     and not parsed.query and not parsed.fragment and "?" not in url and "#" not in url)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("root HTTPS trycloudflare origin required")
        with self._gate_lock:
            if self._public_origin is not None or self._revoked:
                raise RuntimeError("public origin is already fixed or share is revoked")
            self._public_origin = "https://" + host

    def revoke(self):
        with self._gate_lock:
            self._revoked = True
            self._sessions.clear()

    def server_close(self):
        self.revoke()
        super().server_close()

    def _active(self):
        with self._gate_lock:
            if self._revoked:
                raise _ShareError("SHARE_REVOKED", 410)

    def _prune_sessions(self, now):
        # Caller holds _gate_lock; expiry is absolute and never refreshed by IO.
        for token, expires in tuple(self._sessions.items()):
            if expires <= now:
                del self._sessions[token]

    def _authorize(self, token):
        with self._gate_lock:
            if self._revoked:
                raise _ShareError("SHARE_REVOKED", 410)
            if self.password_required:
                self._prune_sessions(time.monotonic())
                accepted = token in self._sessions
            else:
                accepted = hmac.compare_digest(token.encode("utf-8"), self.token.encode())
            if not accepted:
                raise _ShareError("SHARE_AUTH_REQUIRED", 401)

    def _login(self, password):
        with self._gate_lock:
            if self._revoked:
                raise _ShareError("SHARE_REVOKED", 410)
            now = time.monotonic()
            while self._login_attempts and self._login_attempts[0] <= now - LOGIN_WINDOW_SECONDS:
                self._login_attempts.popleft()
            if len(self._login_attempts) >= MAX_LOGIN_ATTEMPTS:
                raise _ShareError("LOGIN_RATE_LIMITED", 429)
            self._login_attempts.append(now)
            if not self._kdf_lock.acquire(blocking=False):
                raise _ShareError("LOGIN_BUSY", 429)
        try:
            try:
                matched = self._verify_password(password, self._password_verifier)
            except (ValueError, UnicodeError):
                raise _ShareError("PASSWORD_REJECTED", 401) from None
            except Exception:
                raise _ShareError("AUTHENTICATION_FAILED", 500) from None
            if type(matched) is not bool:
                raise _ShareError("AUTHENTICATION_FAILED", 500)
            if not matched:
                raise _ShareError("PASSWORD_REJECTED", 401)
            with self._gate_lock:
                if self._revoked:
                    raise _ShareError("SHARE_REVOKED", 410)
                now = time.monotonic()
                self._prune_sessions(now)
                if len(self._sessions) >= MAX_SESSIONS:
                    raise _ShareError("SESSION_CAPACITY", 503)
                for _ in range(3):
                    token = secrets.token_urlsafe(32)
                    if (token not in self._sessions and token != self.token
                            and token != self._operator_token and token != self._password_verifier["digest"]):
                        break
                else:
                    raise _ShareError("AUTHENTICATION_FAILED", 500)
                self._sessions[token] = now + SESSION_SECONDS
                return {"schema": "sisyfus.share.session.v1", "token": token,
                        "expires_in": SESSION_SECONDS}
        finally:
            self._kdf_lock.release()

    def _logout(self, token):
        with self._gate_lock:
            if self._revoked:
                raise _ShareError("SHARE_REVOKED", 410)
            self._prune_sessions(time.monotonic())
            if token not in self._sessions:
                raise _ShareError("SHARE_AUTH_REQUIRED", 401)
            del self._sessions[token]

    def process_request(self, request, client_address):
        # Admit BEFORE ThreadingMixIn allocates/starts a handler thread.
        if not self._slots.acquire(blocking=False):
            raw = b'{"error":{"code":"SHARE_BUSY"}}'
            try:
                request.settimeout(1)
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n"
                                b"Content-Type: application/json\r\nCache-Control: no-store\r\n"
                                b"X-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\n"
                                b"Content-Security-Policy: default-src 'none'; frame-ancestors 'none'\r\n"
                                + f"Content-Length: {len(raw)}\r\n\r\n".encode() + raw)
            except OSError:
                pass  # A disconnected rejected peer receives no successful response.
            finally:
                self.shutdown_request(request)
            return
        try:
            thread = threading.Thread(target=self.process_request_thread,
                                      args=(request, client_address), daemon=self.daemon_threads)
        except BaseException:
            self._slots.release()
            raise
        # After start is called, its outcome may be uncertain. Only the exact
        # handler's finally releases its slot, even if start raises after spawn.
        # A never-entered uncertain launch keeps its reservation, not extra room.
        thread.start()

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address):
        logging.getLogger(__name__).error("share gateway handler failed")  # No exception/path/header text.

    def _has_secret(self, value):
        with self._gate_lock:
            self._prune_sessions(time.monotonic())
            credentials = (self.token, self._operator_token, *self._sessions)
            if self.password_required:
                credentials += (self._password_verifier["digest"],)
        pending = [iter((value,))]
        ended = object()
        while pending:
            item = next(pending[-1], ended)
            if item is ended:
                pending.pop()
            elif isinstance(item, str):
                if any(token in item for token in credentials):
                    return True
            elif isinstance(item, dict):
                pending.append(iter(item.items()))
            elif isinstance(item, (list, tuple)):
                pending.append(iter(item))
        return False

    def _upstream(self, method, path, body=None, *, engineering=False):
        self._active()
        deadline = _Deadline()
        connection = HTTPConnection("127.0.0.1", self._upstream_port, timeout=deadline.remaining())
        response = None
        try:
            connection.connect()
            connection.sock = _DeadlineSocket(connection.sock, deadline)
            headers = {"Authorization": "Bearer " + self._operator_token,
                       "Host": f"127.0.0.1:{self._upstream_port}",
                       "Origin": self._upstream_origin, "Connection": "close"}
            if engineering:
                headers["X-Sisyfus-Engineering-Result"] = "1"
            raw_body = _canonical(body) if body is not None else None
            if raw_body is not None:
                headers["Content-Type"] = "application/json"
            self._active()
            connection.request(method, path, body=raw_body, headers=headers)
            response = connection.getresponse()
            deadline.remaining()
            if 300 <= response.status < 400:
                raise _ShareError("UPSTREAM_REDIRECT_REJECTED")
            data = bytearray()
            while True:
                chunk = response.read(min(65_536, MAX_UPSTREAM_BYTES + 1 - len(data)))
                deadline.remaining()
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > MAX_UPSTREAM_BYTES:
                    raise _ShareError("UPSTREAM_BODY_TOO_LARGE")
            if response.status != 200:
                status = response.status if response.status in {400, 404, 409, 410, 413, 429} else 502
                raise _ShareError("UPSTREAM_REJECTED", status)
            types = response.headers.get_all("Content-Type", [])
            if len(types) != 1 or types[0].split(";", 1)[0].strip().lower() != "application/json":
                raise _ShareError("UPSTREAM_CONTENT_TYPE")
            result = _strict_json(bytes(data))
            if not isinstance(result, dict):
                raise _ShareError("UPSTREAM_JSON_SHAPE")
            _canonical(result)  # Also rejects overflowing/nonfinite parsed floats.
            if self._has_secret(result):
                raise _ShareError("UPSTREAM_CREDENTIAL_REJECTED")
            deadline.remaining()
            self._active()
            return result
        except _ShareError:
            raise
        except TimeoutError:
            raise _ShareError("UPSTREAM_TIMEOUT", 504) from None
        except (ValueError, UnicodeError, RecursionError, OverflowError):
            raise _ShareError("UPSTREAM_JSON_INVALID") from None
        except Exception:
            raise _ShareError("UPSTREAM_IO_ERROR") from None
        finally:
            if response is not None:
                response.close()
            connection.close()

    def _snapshot(self):
        capture = self._upstream("GET", "/api/snapshot?mission_id=" + self.mission_id, engineering=True)
        if (set(capture) != {"id", "snapshot", "controller", "controls", "engineering_result"}
                or capture["id"] != self.mission_id or not isinstance(capture["snapshot"], dict)
                or not isinstance(capture["controller"], dict) or not isinstance(capture["controls"], list)):
            raise _ShareError("UPSTREAM_CAPTURE_INVALID")
        side = capture["engineering_result"]
        if (not isinstance(side, dict) or set(side) != {"schema", "mission_id", "status", "result", "error"}
                or side["schema"] != "sisyfus.lead_console.engineering_result_sidecar.v1"
                or side["mission_id"] != self.mission_id or not isinstance(side["status"], str)
                or side["status"] not in {"OK", "REJECTED", "FAILED"}):
            raise _ShareError("UPSTREAM_CAPTURE_INVALID")
        if side["status"] == "OK":
            if not isinstance(side["result"], dict) or side["error"] is not None:
                raise _ShareError("UPSTREAM_CAPTURE_INVALID")
        elif (side["result"] is not None or not isinstance(side["error"], dict)
              or set(side["error"]) != {"code"} or not isinstance(side["error"]["code"], str)
              or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,31}", side["error"]["code"])):
            raise _ShareError("UPSTREAM_CAPTURE_INVALID")
        return {"schema": "sisyfus.share.capture.v1", "mission_id": self.mission_id,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "capture_hash": hashlib.sha256(_canonical(capture)).hexdigest(), "capture": capture,
                "capabilities": {"messages": self.allow_messages, "controls": False},
                "report": {"available": self._report is not None,
                           "sha256": self._report.sha256 if self._report else None}}


class _Handler(BaseHTTPRequestHandler):
    server: ShareGateway

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_args):
        pass  # Request targets, bearer and bodies never enter an access log.

    def _send(self, raw, status=200, *, content_type="application/json; charset=utf-8", nonce="", report=False,
              protected=False, session=False):
        if protected:
            # Check AFTER IO and serialization, immediately before private bytes.
            if not session and self.server._has_secret(raw.decode("utf-8")):
                raise _ShareError("SHARE_CREDENTIAL_REJECTED")
            self._authorize()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        policy = ("default-src 'none'; connect-src 'self'; "
                  f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; frame-src 'self' blob:; "
                  "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        if report:
            policy = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        self.send_header("Content-Security-Policy", policy)
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def _json(self, value, status=200, *, protected=False, session=False):
        raw = _canonical(value)
        if len(raw) > MAX_UPSTREAM_BYTES:
            raise _ShareError("SHARE_RESPONSE_TOO_LARGE")
        self._send(raw, status, protected=protected, session=session)

    def _fail(self, code, status):
        self._json({"error": {"code": code}}, status)

    def send_error(self, code, message=None, explain=None):
        self._fail("HTTP_REQUEST_REJECTED", code)

    def _authorize(self):
        self.server._authorize(self._credential)

    def _boundary(self, *, auth, post=False):
        with self.server._gate_lock:
            public = self.server._public_origin
        origins = {f"127.0.0.1:{self.server.server_port}": self.server.origin}
        if public:
            origins[public.removeprefix("https://")] = public
        hosts, origin = self.headers.get_all("Host", []), self.headers.get_all("Origin", [])
        if len(hosts) != 1 or hosts[0] not in origins:
            raise _ShareError("HOST_REJECTED", 403)
        if len(origin) > 1 or (origin and origin[0] != origins[hosts[0]]) or (post and not origin):
            raise _ShareError("ORIGIN_REJECTED", 403)
        if auth:
            self.server._active()
            values = self.headers.get_all("Authorization", [])
            if len(values) != 1 or not values[0].startswith("Bearer "):
                raise _ShareError("SHARE_AUTH_REQUIRED", 401)
            self._credential = values[0][7:]
            self._authorize()
        if auth or post:
            if any(name.lower() == "x-sisyfus-node" or name.lower().startswith(("x-node-", "x-sisyfus-node-")) for name in self.headers):
                raise _ShareError("NODE_IDENTITY_REJECTED", 403)

    def _route(self):
        if len(self.path) > 4096:
            raise _ShareError("QUERY_REJECTED", 400)
        route = urlsplit(self.path)
        allowed = _API | {"/"} | (_AUTH_API if self.server.password_required else set())
        if route.scheme or route.netloc or route.fragment or route.path not in allowed:
            raise _ShareError("ROUTE_NOT_FOUND", 404)
        if route.path != "/api/share/messages" and "?" in self.path:
            raise _ShareError("QUERY_REJECTED", 400)
        return route

    def _cursor(self, value):
        if not re.fullmatch(r"[0-9]{1,19}", value) or int(value) > 2**63 - 1:
            raise _ShareError("CURSOR_REJECTED", 400)
        return int(value)

    def do_GET(self):
        try:
            self._boundary(auth=self.path.split("?", 1)[0] != "/")
            route = self._route()
            if route.path == "/":
                from .share_page import PAGE
                nonce = secrets.token_urlsafe(18)
                page = PAGE
                if self.server.password_required:
                    page = (page.replace('data-password-required="false"', 'data-password-required="true"')
                            .replace("const passwordRequired = false;", "const passwordRequired = true;")
                            .replace('<label for="share-token">临时访问令牌</label>', '<label for="share-token">访问密码</label>')
                            .replace('autocomplete="off"', 'autocomplete="current-password"', 1)
                            .replace('placeholder="仅用于本页内存中的 Authorization"', 'placeholder="仅发送至本站登录接口，不保存"')
                            .replace('class="primary">读取任务</button>', 'class="primary">登录查看</button>')
                            .replace("输入临时访问令牌后读取；匿名页面不包含任务数据。", "输入访问密码后登录；匿名页面不包含任务数据。"))
                self._send(page.replace("NONCE", nonce).encode(), content_type="text/html; charset=utf-8", nonce=nonce)
            elif route.path == "/api/share/snapshot":
                self._authorize()
                value = self.server._snapshot()
                self._json(value, protected=True)
            elif route.path == "/api/share/messages":
                if re.search(r"%(?![0-9A-Fa-f]{2})", route.query):
                    raise _ShareError("QUERY_REJECTED", 400)
                query = parse_qs(route.query, keep_blank_values=True, strict_parsing=True, errors="strict", max_num_fields=2)
                if set(query) - {"cursor", "application_cursor"} or any(len(values) != 1 for values in query.values()):
                    raise _ShareError("QUERY_REJECTED", 400)
                cursor = self._cursor(query.get("cursor", ["0"])[0])
                application = self._cursor(query.get("application_cursor", ["0"])[0])
                self._authorize()
                value = self.server._upstream("GET", f"/api/mission/messages?mission_id={self.server.mission_id}&cursor={cursor}&application_cursor={application}")
                if (not isinstance(value.get("messages"), list) or not isinstance(value.get("updates"), list)
                        or type(value.get("cursor")) is not int or value["cursor"] < cursor
                        or type(value.get("application_cursor")) is not int or value["application_cursor"] < application
                        or type(value.get("has_more")) is not bool or type(value.get("has_more_updates")) is not bool):
                    raise _ShareError("UPSTREAM_MESSAGES_INVALID")
                self._json(value, protected=True)
            elif route.path == "/api/share/report":
                if self.server._report is None:
                    raise _ShareError("REPORT_ABSENT", 404)
                self._authorize()
                data = self.server._report.read()
                if self.server._has_secret(data.decode("utf-8")):
                    raise _ShareError("REPORT_CREDENTIAL_REJECTED")
                self._send(data, content_type="text/html; charset=utf-8", report=True, protected=True)
            else:
                raise _ShareError("METHOD_NOT_ALLOWED", 405)
        except _ShareError as exc:
            self._fail(exc.code, exc.status)
        except (ValueError, UnicodeError, TypeError, RecursionError, OverflowError):
            self._fail("REQUEST_REJECTED", 400)
        except Exception:
            self._fail("SHARE_INTERNAL_ERROR", 500)

    def _json_body(self):
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or self.headers.get_all("Transfer-Encoding", []):
            raise _ShareError("BODY_FRAMING_REJECTED", 400)
        if not re.fullmatch(r"[0-9]{1,5}", lengths[0]) or not 0 < int(lengths[0]) <= MAX_BODY_BYTES:
            raise _ShareError("BODY_SIZE_REJECTED", 413)
        if len(self.headers.get_all("Content-Type", [])) != 1 or self.headers.get_content_type() != "application/json":
            raise _ShareError("BODY_TYPE_REJECTED", 400)
        raw = self.rfile.read(int(lengths[0]))
        if len(raw) != int(lengths[0]):
            raise _ShareError("BODY_INCOMPLETE", 400)
        return _strict_json(raw)

    def _body(self):
        value = self._json_body()
        if (not isinstance(value, dict) or set(value) - {"message", "request_id", "task_id"}
                or not {"message", "request_id"} <= set(value)):
            raise _ShareError("MESSAGE_FIELDS_REJECTED", 400)
        if (not isinstance(value["message"], str) or not value["message"].strip()
                or len(value["message"]) > MAX_MESSAGE_CHARS):
            raise _ShareError("MESSAGE_SIZE_REJECTED", 400)
        if not isinstance(value["request_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", value["request_id"]):
            raise _ShareError("REQUEST_ID_REJECTED", 400)
        if "task_id" in value and (not isinstance(value["task_id"], str) or not value["task_id"] or len(value["task_id"].encode()) > 100):
            raise _ShareError("TASK_ID_REJECTED", 400)
        return value

    def _no_body(self):
        lengths = self.headers.get_all("Content-Length", [])
        if (self.headers.get_all("Transfer-Encoding", []) or len(lengths) > 1
                or lengths and lengths != ["0"]):
            raise _ShareError("BODY_FRAMING_REJECTED", 400)

    def do_POST(self):
        try:
            self._boundary(auth=self.path.split("?", 1)[0] != "/api/share/login", post=True)
            route = self._route()
            if route.path == "/api/share/login":
                self.server._active()
                body = self._json_body()
                if not isinstance(body, dict) or set(body) != {"password"} or not isinstance(body["password"], str):
                    raise _ShareError("PASSWORD_FIELDS_REJECTED", 400)
                value = self.server._login(body["password"])
                self._credential = value["token"]
                self._json(value, protected=True, session=True)
                return
            if route.path == "/api/share/logout":
                self._no_body()
                self.server._logout(self._credential)
                self._json({"status": "LOGGED_OUT"})
                return
            if route.path != "/api/share/message":
                raise _ShareError("METHOD_NOT_ALLOWED", 405)
            if not self.server.allow_messages:
                raise _ShareError("SHARE_READ_ONLY", 403)
            body = self._body()
            self._authorize()
            value = self.server._upstream("POST", "/api/mission/message", {**body, "mission_id": self.server.mission_id})
            if (value.get("request_id") != body["request_id"] or not isinstance(value.get("id"), str)
                    or not isinstance(value.get("status"), str) or value["status"] not in {"RECEIVED", "ANSWERED", "APPLIED"}):
                raise _ShareError("UPSTREAM_RECEIPT_INVALID")
            self._json(value, protected=True)
        except _ShareError as exc:
            self._fail(exc.code, exc.status)
        except TimeoutError:
            self._fail("BODY_TIMEOUT", 408)
        except (ValueError, UnicodeError, TypeError, RecursionError, OverflowError):
            self._fail("REQUEST_REJECTED", 400)
        except Exception:
            self._fail("SHARE_INTERNAL_ERROR", 500)

    def _unsupported(self):
        self._fail("METHOD_NOT_ALLOWED", 405)

    do_HEAD = do_OPTIONS = do_PUT = do_DELETE = do_PATCH = do_TRACE = do_CONNECT = _unsupported
