"""Private HTTP server for phone dispatch: page, JSON API and authenticated Observatory proxy."""
from __future__ import annotations

import json
import mimetypes
import secrets
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from ..research_v2.observatory import _finite
from . import research
from .auth import AuthError, LoginThrottle, SessionStore, load_verifier, verify_password
from .config import ConfigError, DispatchConfig
from .jobs import RUNNING, JobError, JobRunner, JobStore
from .page import ICON_SVG, MANIFEST, render_page, touch_icon

COOKIE = "sf_dispatch"
MAX_BODY = 64 * 1024
_JOB_ERRORS = {"NOT_FOUND": 404, "EMPTY": 400, "TOO_LONG": 413, "AGENT_UNAVAILABLE": 503}
_PAGE_CSP = ("default-src 'none'; script-src 'nonce-{n}'; style-src 'nonce-{n}'; img-src 'self' data:; "
             "connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
_OBS_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'")
# Run artifacts are produced by experiments, not by Sisyfus: never let them run script on this origin.
_ARTIFACT_CSP = "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"
_ACTIVE_TYPES = ("text/html", "image/svg+xml", "application/xhtml+xml", "text/xml", "application/xml",
                 "text/javascript", "application/javascript")


class DispatchServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64  # the stdlib default of 5 resets bursts of parallel requests

    def __init__(self, config: DispatchConfig, *, host: str, port: int, allowed_hosts: set[str]) -> None:
        self.config = config
        self.store = JobStore(config.jobs_dir)
        self.runner = JobRunner(config, self.store)
        self.sessions = SessionStore(config.sessions_path)
        self.throttle = LoginThrottle()
        super().__init__((host, port), DispatchHandler)
        bound = self.server_address[1]
        self.allowed_hosts = set(allowed_hosts) | {f"{host}:{bound}"}
        if host == "127.0.0.1":
            self.allowed_hosts.add(f"localhost:{bound}")

    def start(self) -> None:
        self.runner.recover()


def job_public(job: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
    keys = ["id", "project", "title", "status", "created_at", "updated_at", "turns", "error",
            "cost_usd_total", "research_ids", "model"]
    data = {key: job.get(key) for key in keys}
    text = job.get("last_text") or ""
    data["last_text"] = text if full else text[:600]
    if full:
        data["brief"] = job.get("brief")
        data["can_reply"] = job.get("status") != RUNNING and bool(job.get("session_id"))
        data["can_stop"] = job.get("status") == RUNNING
    return data


class DispatchHandler(BaseHTTPRequestHandler):
    server: DispatchServer
    protocol_version = "HTTP/1.1"
    server_version = "SisyfusDispatch"
    sys_version = ""
    timeout = 15  # idle or slow connections must not pin handler threads

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return

    # ---------- plumbing ----------
    def _headers(self, status: int, content_type: str, length: int, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def _json(self, value: Any, status: int = 200, extra: dict[str, str] | None = None) -> None:
        body = json.dumps(_finite(value), ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body), extra)
        self.wfile.write(body)

    def _error(self, status: int, code: str, message: str, extra: dict[str, str] | None = None) -> None:
        # An unread request body must never be parsed as a second request on this connection.
        self.close_connection = True
        self._json({"error": {"code": code, "message": message}}, status, {**(extra or {}), "Connection": "close"})

    def _bytes(self, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self._headers(200, content_type, len(body), extra)
        self.wfile.write(body)

    def _host_ok(self) -> bool:
        hosts = self.headers.get_all("Host") or []
        if len(hosts) != 1 or hosts[0] not in self.server.allowed_hosts:
            self._error(421, "HOST_REJECTED", "unrecognised host")
            return False
        return True

    def _token(self) -> str | None:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie") or "")
        except Exception:  # malformed cookie header is simply unauthenticated
            return None
        morsel = cookie.get(COOKIE)
        return morsel.value if morsel else None

    def _authed(self) -> bool:
        if self.server.sessions.valid(self._token()):
            return True
        self._error(401, "LOGIN_REQUIRED", "请先登录")
        return False

    def _secure(self) -> bool:
        return (self.headers.get("X-Forwarded-Proto") or "").lower() == "https"

    def _body(self) -> dict[str, Any] | None:
        if self.headers.get("Transfer-Encoding"):
            self._error(411, "LENGTH_REQUIRED", "chunked bodies are not accepted")
            return None
        origin = self.headers.get("Origin") or ""
        parts = urlsplit(origin)
        if parts.scheme not in {"http", "https"} or parts.netloc not in self.server.allowed_hosts:
            self._error(403, "ORIGIN_REJECTED", "request origin not allowed")
            return None
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            self._error(415, "JSON_REQUIRED", "JSON body required")
            return None
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self._error(413, "BODY_TOO_LARGE", "request too large")
            return None
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._error(400, "BAD_JSON", "invalid JSON")
            return None
        if not isinstance(data, dict):
            self._error(400, "BAD_JSON", "JSON object required")
            return None
        return data

    # ---------- routes ----------
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        if not self._host_ok():
            return
        if self.headers.get("Transfer-Encoding") or (self.headers.get("Content-Length") or "0") != "0":
            self._error(400, "UNEXPECTED_BODY", "GET requests must not carry a body")
            return
        path = urlsplit(self.path).path
        if path in {"/", "/index.html"}:
            nonce = secrets.token_urlsafe(18)
            self._bytes(render_page(nonce).encode("utf-8"), "text/html; charset=utf-8",
                        {"Content-Security-Policy": _PAGE_CSP.format(n=nonce), "X-Frame-Options": "DENY"})
        elif path == "/manifest.webmanifest":
            self._bytes(MANIFEST.encode("utf-8"), "application/manifest+json")
        elif path == "/icon.svg":
            self._bytes(ICON_SVG.encode("utf-8"), "image/svg+xml")
        elif path == "/apple-touch-icon.png":
            self._bytes(touch_icon(), "image/png")
        elif path == "/api/me":
            self._json({"authenticated": self.server.sessions.valid(self._token())})
        elif not self._authed():
            return
        elif path == "/api/state":
            self._json(self._state())
        elif path.startswith("/api/jobs/"):
            self._job(path[len("/api/jobs/"):])
        elif path.startswith("/api/runs/"):
            self._run(path[len("/api/runs/"):])
        elif path.startswith("/obs/"):
            self._observatory(path[len("/obs/"):])
        else:
            self._error(404, "NOT_FOUND", "not found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        if not self._host_ok():
            return
        path = urlsplit(self.path).path
        body = self._body()
        if body is None:
            return
        if path == "/api/login":
            self._login(body)
            return
        if path == "/api/logout":
            self.server.sessions.revoke(self._token())
            self._json({"ok": True}, extra={"Set-Cookie": f"{COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict"})
            return
        if not self._authed():
            return
        runner = self.server.runner
        try:
            if path == "/api/jobs":
                job = runner.start(str(body.get("project") or ""), str(body.get("brief") or ""))
                self._json({"job": job_public(job, full=True)}, 201)
            elif path.startswith("/api/jobs/") and path.endswith("/reply"):
                job = runner.reply(path.split("/")[3], str(body.get("text") or ""))
                self._json({"job": job_public(job, full=True)}, 202)
            elif path.startswith("/api/jobs/") and path.endswith("/stop"):
                job = runner.stop(path.split("/")[3])
                self._json({"job": job_public(job, full=True)}, 202)
            else:
                self._error(404, "NOT_FOUND", "not found")
        except JobError as exc:
            self._error(_JOB_ERRORS.get(exc.code, 409), exc.code, str(exc))
        except ConfigError:
            self._error(404, "UNKNOWN_PROJECT", "未知的工程")

    def _client_key(self) -> str:
        """Throttle key: behind a loopback proxy (`tailscale serve`) use the identity it forwards."""
        peer = self.client_address[0]
        if peer in {"127.0.0.1", "::1"}:
            forwarded = (self.headers.get("Tailscale-User-Login")
                         or (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip())
            if forwarded:
                return f"via:{forwarded}"
        return peer

    def _login(self, body: dict[str, Any]) -> None:
        throttle, client = self.server.throttle, self._client_key()
        try:
            verifier = load_verifier(self.server.config.password_path)
        except AuthError as exc:
            self._error(503, "NO_PASSWORD", str(exc))
            return
        with throttle.verify_lock:  # check and verify atomically: concurrent guesses queue here
            wait = throttle.blocked_for(client)
            if wait <= 0:
                ok = verify_password(verifier, str(body.get("password") or ""))
                (throttle.succeeded if ok else throttle.failed)(client)
        if wait > 0:
            self._error(429, "TOO_MANY_ATTEMPTS", f"尝试次数过多，请 {int(wait) + 1} 秒后再试",
                        {"Retry-After": str(int(wait) + 1)})
            return
        if not ok:
            time.sleep(0.4)
            self._error(401, "BAD_PASSWORD", "密码不正确")
            return
        token = self.server.sessions.create()
        cookie = f"{COOKIE}={token}; Max-Age={self.server.sessions.lifetime}; Path=/; HttpOnly; SameSite=Strict"
        self._json({"ok": True}, extra={"Set-Cookie": cookie + ("; Secure" if self._secure() else "")})

    def _state(self) -> dict[str, Any]:
        config = self.server.config
        projects = []
        for name in sorted(config.projects):
            path = Path(config.projects[name])
            projects.append({"name": name, "runs": research.list_runs(path, limit=8),
                             "activity": research.activity(path)})
        jobs = [job_public(job) for job in self.server.store.all()[:30]]
        return {"projects": projects, "jobs": jobs,
                "limits": {"max_budget_usd": config.max_budget_usd, "max_concurrent": config.max_concurrent},
                "agent": {"claude": "Claude Code", "codex": "Codex"}.get(Path(config.agent_command[0]).name,
                                                                         Path(config.agent_command[0]).name),
                "model": config.model}

    def _job(self, job_id: str) -> None:
        store = self.server.store
        try:
            job = store.load(job_id)
        except JobError:
            self._error(404, "NOT_FOUND", "unknown job")
            return
        try:
            project = self.server.config.project_path(job["project"])
        except ConfigError:
            self._json({"job": job_public(job, full=True), "events": store.events(job_id), "runs": [], "activity": None})
            return
        runs = []
        for rid in job.get("research_ids") or []:
            try:
                runs.append(research.run_summary(project, rid))
            except LookupError:
                continue
        live = research.activity(project) if job["status"] in {RUNNING, "NEEDS_REPLY"} else None
        self._json({"job": job_public(job, full=True), "events": store.events(job_id), "runs": runs,
                    "activity": live})

    def _split_run(self, rest: str) -> tuple[Path, str, str] | None:
        parts = rest.split("/", 2)
        if len(parts) < 2:
            self._error(404, "NOT_FOUND", "not found")
            return None
        try:
            project = self.server.config.project_path(unquote(parts[0]))
        except ConfigError:
            self._error(404, "UNKNOWN_PROJECT", "未知的工程")
            return None
        return project, unquote(parts[1]), unquote(parts[2]) if len(parts) == 3 else ""

    def _run(self, rest: str) -> None:
        split = self._split_run(rest)
        if split is None:
            return
        project, research_id, _ = split
        try:
            self._json({"run": research.run_detail(project, research_id)})
        except LookupError:
            self._error(404, "NOT_FOUND", "unknown research run")

    def _observatory(self, rest: str) -> None:
        split = self._split_run(rest)
        if split is None:
            return
        project, research_id, rel = split
        try:
            path, content_type = research.observatory_file(project, research_id, rel or "index.html")
            data = path.read_bytes()
        except (LookupError, OSError):
            self._error(404, "NOT_FOUND", "not found")
            return
        if content_type:
            self._bytes(data, content_type, {"Content-Security-Policy": _OBS_CSP})
            return
        guessed = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if guessed.startswith(_ACTIVE_TYPES):
            guessed = "text/plain; charset=utf-8"
        self._bytes(data, guessed, {"Content-Security-Policy": _ARTIFACT_CSP})


def make_server(config: DispatchConfig, *, host: str, port: int, allowed_hosts: set[str]) -> DispatchServer:
    server = DispatchServer(config, host=host, port=port, allowed_hosts=allowed_hosts)
    server.start()
    return server
