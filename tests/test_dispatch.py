"""Phone dispatch: auth, job lifecycle with a fake headless agent, run status and Observatory proxy."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from sisyfus.dispatch.auth import AuthError, SessionStore, load_verifier, verify_password, write_password
from sisyfus.dispatch.cli import main as dispatch_main
from sisyfus.dispatch.config import DispatchConfig, save_config
from sisyfus.dispatch.jobs import JobRunner, JobStore
from sisyfus.dispatch.server import make_server
from sisyfus.research_v2.engine import ResearchEngine

PASSWORD = "correct horse battery"
FAKE_AGENT = r'''
import json, os, sys, time
args = sys.argv[1:]
prompt = sys.stdin.read()
session = args[args.index("--resume") + 1] if "--resume" in args else "sess-1"
log = os.environ.get("FAKE_AGENT_LOG")
if log:
    with open(log, "a") as handle:
        handle.write(json.dumps({"argv": args, "prompt": prompt, "cwd": os.getcwd()}) + "\n")
mode = os.environ.get("FAKE_AGENT_MODE", "ok")
def out(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)  # raw U+2028 like JSON.stringify
out({"type": "system", "subtype": "init", "session_id": session, "model": "fake-model"})
if mode == "sleep":
    time.sleep(60)
if mode == "crash":
    print("boom token=abc123", file=sys.stderr)
    sys.exit(3)
if mode == "needs_user":
    live = os.path.join(os.getcwd(), ".sisyfus", "live")
    os.makedirs(live, exist_ok=True)
    with open(os.path.join(live, "activity.json"), "w") as handle:
        json.dump({"status": "NEEDS_USER", "phase": "CLARIFYING",
                   "metadata": {"clarification_questions": ["样本外窗口用哪几年？"]}}, handle)
out({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "Bash", "input": {"command": "sisyfus research status --brief"}},
    {"type": "text", "text": "已收到：" + prompt.strip()[:40] + " 第二行"}]}})
# Like Claude Code, total_cost_usd is cumulative for the session: each turn adds 0.5.
out({"type": "result", "subtype": "success", "is_error": False, "result": "本轮完成：" + prompt.strip()[:20] + "\u2028",
     "session_id": session, "total_cost_usd": 0.5 * (2 if "--resume" in args else 1), "num_turns": 2,
     "duration_ms": 10})
'''


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str = "ok") -> tuple[DispatchConfig, Path, Path]:
    project = tmp_path / "proj"
    project.mkdir()
    agent = tmp_path / "fake_agent.py"
    agent.write_text(FAKE_AGENT, encoding="utf-8")
    log = tmp_path / "agent-log.jsonl"
    monkeypatch.setenv("FAKE_AGENT_MODE", mode)
    monkeypatch.setenv("FAKE_AGENT_LOG", str(log))
    config = DispatchConfig(home=tmp_path / "home", projects={"proj": str(project.resolve())},
                            agent_command=[sys.executable, str(agent)], max_budget_usd=5)
    save_config(config)
    write_password(config.password_path, PASSWORD)
    return config, project, log


class Client:
    def __init__(self, config: DispatchConfig) -> None:
        self.server = make_server(config, host="127.0.0.1", port=0, allowed_hosts=set())
        self.server.runner.poll_interval = 0.05
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.cookie = ""
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def request(self, method: str, path: str, body: dict | None = None, *, host: str | None = None,
                origin: str | None = "default") -> tuple[int, dict, dict]:
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        data = None
        if method == "POST":
            data = json.dumps(body or {}).encode()
            headers["Content-Type"] = "application/json"
            if origin == "default":
                headers["Origin"] = self.base
            elif origin:
                headers["Origin"] = origin
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                raw, status, hdrs = response.read(), response.status, dict(response.headers)
        except urllib.error.HTTPError as exc:
            raw, status, hdrs = exc.read(), exc.code, dict(exc.headers)
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            payload = {"raw": raw.decode("utf-8", "replace")}
        return status, payload, hdrs

    def login(self) -> str:
        status, _, headers = self.request("POST", "/api/login", {"password": PASSWORD})
        assert status == 200
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        return headers["Set-Cookie"]

    def wait_job(self, job_id: str, until: set[str], timeout: float = 15) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status, data, _ = self.request("GET", f"/api/jobs/{job_id}")
            assert status == 200
            if data["job"]["status"] in until:
                return data
            time.sleep(0.05)
        raise AssertionError(f"job stayed {data['job']['status']}")

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def test_password_verifier_and_sessions_persist(tmp_path: Path) -> None:
    path = tmp_path / "pw.json"
    with pytest.raises(AuthError):
        write_password(path, "short")
    write_password(path, PASSWORD)
    verifier = load_verifier(path)
    assert verify_password(verifier, PASSWORD) and not verify_password(verifier, PASSWORD + "x")
    assert PASSWORD not in path.read_text()
    store = SessionStore(tmp_path / "sessions.json")
    token = store.create()
    assert token not in (tmp_path / "sessions.json").read_text()
    assert SessionStore(tmp_path / "sessions.json").valid(token)
    store.revoke_all()
    assert not SessionStore(tmp_path / "sessions.json").valid(token)


def test_login_host_and_origin_are_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, _, _ = _setup(tmp_path, monkeypatch)
    client = Client(config)
    try:
        assert client.request("GET", "/api/state")[0] == 401
        assert client.request("GET", "/api/me", host="evil.example:80")[0] == 421
        assert client.request("POST", "/api/login", {"password": PASSWORD}, origin=None)[0] == 403
        assert client.request("POST", "/api/login", {"password": PASSWORD}, origin="http://evil.example")[0] == 403
        assert client.request("POST", "/api/login", {"password": "wrong password!"})[0] == 401
        cookie = client.login()
        assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Secure" not in cookie
        status, state, _ = client.request("GET", "/api/state")
        assert status == 200 and state["projects"][0]["name"] == "proj"
        assert client.request("POST", "/api/logout", {})[0] == 200
        assert client.request("GET", "/api/state")[0] == 401
    finally:
        client.close()


def test_login_throttle_blocks_after_repeated_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, _, _ = _setup(tmp_path, monkeypatch)
    client = Client(config)
    try:
        codes = [client.request("POST", "/api/login", {"password": f"wrong-{i}-xxxxxx"})[0] for i in range(6)]
        assert codes[:5] == [401] * 5 and codes[5] == 429
        assert client.request("POST", "/api/login", {"password": PASSWORD})[0] == 429
    finally:
        client.close()


def test_dispatch_runs_agent_turns_and_resumes_the_same_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, project, log = _setup(tmp_path, monkeypatch)
    client = Client(config)
    try:
        client.login()
        status, created, _ = client.request("POST", "/api/jobs", {"project": "proj", "brief": "红利低波是否跑赢等权？"})
        assert status == 201 and created["job"]["status"] == "RUNNING"
        job_id = created["job"]["id"]
        done = client.wait_job(job_id, {"IDLE"})
        assert done["job"]["last_text"].startswith("本轮完成") and done["job"]["can_reply"]
        assert done["job"]["cost_usd_total"] == 0.5
        kinds = [e["kind"] for e in done["events"]]
        assert kinds[:1] == ["user"] and "tool" in kinds and "result" in kinds
        first = json.loads(log.read_text().splitlines()[0])
        assert "红利低波是否跑赢等权" in first["prompt"] and "--resume" not in first["argv"]
        assert Path(first["cwd"]).resolve() == project.resolve()
        assert "红利低波" not in " ".join(first["argv"]), "the brief must travel on stdin, not argv"

        assert client.request("POST", f"/api/jobs/{job_id}/reply", {"text": "用 2021-2024"})[0] == 202
        again = client.wait_job(job_id, {"IDLE"})
        second = json.loads(log.read_text().splitlines()[1])
        assert second["argv"][second["argv"].index("--resume") + 1] == "sess-1"
        assert again["job"]["turns"] == 2 and again["job"]["cost_usd_total"] == 1.0
    finally:
        client.close()


def test_clarification_turn_needs_reply_and_shows_questions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, _, _ = _setup(tmp_path, monkeypatch, mode="needs_user")
    client = Client(config)
    try:
        client.login()
        job_id = client.request("POST", "/api/jobs", {"project": "proj", "brief": "研究 A"})[1]["job"]["id"]
        data = client.wait_job(job_id, {"NEEDS_REPLY"})
        assert data["activity"]["clarification_questions"] == ["样本外窗口用哪几年？"]
    finally:
        client.close()


def test_stop_and_one_job_per_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, _, _ = _setup(tmp_path, monkeypatch, mode="sleep")
    client = Client(config)
    try:
        client.login()
        job_id = client.request("POST", "/api/jobs", {"project": "proj", "brief": "长时间研究"})[1]["job"]["id"]
        status, busy, _ = client.request("POST", "/api/jobs", {"project": "proj", "brief": "第二个"})
        assert status == 409 and busy["error"]["code"] == "PROJECT_BUSY"
        assert client.request("POST", f"/api/jobs/{job_id}/reply", {"text": "x"})[0] == 409
        deadline = time.monotonic() + 10
        while client.request("GET", f"/api/jobs/{job_id}")[1]["job"]["model"] != "fake-model":
            assert time.monotonic() < deadline, "agent session never started"
            time.sleep(0.05)
        assert client.request("POST", f"/api/jobs/{job_id}/stop", {})[0] == 202
        stopped = client.wait_job(job_id, {"STOPPED"}, timeout=20)
        assert stopped["job"]["can_reply"]
    finally:
        client.close()


def test_failures_are_explicit_and_redacted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, _, _ = _setup(tmp_path, monkeypatch, mode="crash")
    client = Client(config)
    try:
        client.login()
        assert client.request("POST", "/api/jobs", {"project": "nope", "brief": "x"})[0] == 404
        assert client.request("POST", "/api/jobs", {"project": "proj", "brief": "  "})[0] == 400
        job_id = client.request("POST", "/api/jobs", {"project": "proj", "brief": "会失败"})[1]["job"]["id"]
        failed = client.wait_job(job_id, {"FAILED"})
        assert "abc123" not in failed["job"]["error"] and "boom" in failed["job"]["error"]
    finally:
        client.close()


def test_missing_agent_fails_the_job_instead_of_leaving_it_created(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    config, _, _ = _setup(tmp_path, monkeypatch)
    config.agent_command = [str(tmp_path / "no-such-agent")]
    store = JobStore(config.jobs_dir)
    runner = JobRunner(config, store)
    with pytest.raises(Exception) as caught:
        runner.start("proj", "需要代理")
    assert getattr(caught.value, "code", "") == "AGENT_UNAVAILABLE"
    [job] = store.all()
    assert job["status"] == "FAILED" and "无法启动" in job["error"]


def test_redaction_masks_common_secret_forms_but_not_prose() -> None:
    from sisyfus.dispatch.agent import redact
    assert redact('curl -H "Authorization: Bearer abcdefghij0123456789"') == 'curl -H "Authorization: Bearer <redacted>"'
    assert redact("export TUSHARE_TOKEN=abc123") == "export TUSHARE_TOKEN=<redacted>"
    assert redact('{"api_key": "sk-xyz", "password": "my secret pass"}') == '{"api_key": "<redacted>", "password": "<redacted>"}'
    for prose in ("样本外 token 数量很多; secrets are fine here", "use basic momentum and basic value factors",
                  "the bearer of bad news", "Max tokens: 4096"):
        assert redact(prose) == prose


def test_raw_socket_smuggling_and_bodies_are_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import socket
    config, _, _ = _setup(tmp_path, monkeypatch)
    client = Client(config)
    host = f"127.0.0.1:{client.port}"

    def exchange(raw: bytes) -> bytes:
        with socket.create_connection(("127.0.0.1", client.port), timeout=5) as sock:
            sock.sendall(raw)
            chunks = []
            while True:
                try:
                    data = sock.recv(65536)
                except socket.timeout:
                    break
                if not data:
                    break
                chunks.append(data)
            return b"".join(chunks)
    try:
        inner = (f"POST /api/login HTTP/1.1\r\nHost: {host}\r\nOrigin: http://{host}\r\n"
                 f"Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{{}}").encode()
        smuggle = (f"POST /api/login HTTP/1.1\r\nHost: {host}\r\nContent-Type: text/plain\r\n"
                   f"Content-Length: {len(inner)}\r\n\r\n").encode() + inner
        reply = exchange(smuggle)
        assert reply.count(b"HTTP/1.1 ") == 1 and b"ORIGIN_REJECTED" in reply
        chunked = f"POST /api/login HTTP/1.1\r\nHost: {host}\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n".encode()
        assert exchange(chunked).startswith(b"HTTP/1.1 411")
        get_body = f"GET /api/me HTTP/1.1\r\nHost: {host}\r\nContent-Length: 5\r\n\r\nhello".encode()
        assert exchange(get_body).startswith(b"HTTP/1.1 400")
    finally:
        client.close()


def test_concurrent_wrong_passwords_cannot_bypass_the_throttle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, _, _ = _setup(tmp_path, monkeypatch)
    client = Client(config)
    codes: list[int] = []
    try:
        threads = [threading.Thread(target=lambda i=i: codes.append(
            client.request("POST", "/api/login", {"password": f"wrong-guess-{i:03d}"})[0])) for i in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(codes).count(401) == 5 and sorted(codes).count(429) == 7
    finally:
        client.close()


def test_missing_project_dir_and_failed_reply_leave_clean_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sisyfus.dispatch.config import load_config
    config, project, _ = _setup(tmp_path, monkeypatch)
    store = JobStore(config.jobs_dir)
    runner = JobRunner(config, store, poll_interval=0.05)
    job = runner.start("proj", "first turn")
    deadline = time.monotonic() + 10
    while store.load(job["id"])["status"] == "RUNNING" and time.monotonic() < deadline:
        time.sleep(0.05)
    before = len(store.events(job["id"]))
    runner.config.agent_command = [str(tmp_path / "missing-agent")]
    with pytest.raises(Exception):
        runner.reply(job["id"], "continue")
    assert len(store.events(job["id"])) == before, "a reply that never launched must not be recorded"
    project.rename(tmp_path / "moved")
    assert load_config(config.home).projects == {"proj": str(project.resolve())}
    with pytest.raises(Exception) as caught:
        runner.start("proj", "again")
    assert getattr(caught.value, "code", "") == "PROJECT_MISSING"


def test_cost_counter_reset_is_counted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, _, _ = _setup(tmp_path, monkeypatch)
    store = JobStore(config.jobs_dir)
    runner = JobRunner(config, store)
    job = store.create("proj", "cost")
    store.update(job["id"], lambda j: j.update({"session_id": "s1"}))
    runner._close(job["id"], "IDLE", None, {"cost_usd": 2.0})
    runner._close(job["id"], "IDLE", None, {"cost_usd": 3.0})
    runner._close(job["id"], "IDLE", None, {"cost_usd": 0.4})  # counter restarted for the same session
    assert store.load(job["id"])["cost_usd_total"] == 3.4


def test_runs_status_and_observatory_proxy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, project, _ = _setup(tmp_path, monkeypatch)
    engine = ResearchEngine.create(project, {
        "id": "phone-study", "topic": "手机派发的研究", "action_space": ["experiment"],
        "claims": [{"id": "a", "statement": "Claim A holds", "label": "A"}],
        "verification_contracts": [{"id": "va", "target_claim_id": "a",
                                    "pass_if": [{"path": "metrics.ok", "op": "==", "value": True}],
                                    "fail_if": [{"path": "metrics.ok", "op": "==", "value": False}]}]})
    rid = engine.workspace.research_id
    client = Client(config)
    try:
        client.login()
        state = client.request("GET", "/api/state")[1]
        assert state["projects"][0]["runs"][0]["research_id"] == rid
        status, detail, _ = client.request("GET", f"/api/runs/proj/{rid}")
        assert status == 200 and detail["run"]["claims"][0]["label"] == "A"
        status, page, headers = client.request("GET", f"/obs/proj/{rid}/index.html")
        assert status == 200 and "frame-ancestors 'self'" in headers["Content-Security-Policy"]
        assert client.request("GET", f"/obs/proj/{rid}/snapshot.json")[0] == 200
        assert client.request("GET", f"/obs/proj/{rid}/artifact/..%2F..%2F..%2Fhome%2Fconfig.json")[0] == 404
        assert client.request("GET", f"/obs/proj/{rid}/task.json")[0] == 404
        assert client.request("GET", "/obs/proj/..%2F..%2Fhome/index.html")[0] == 404
        assert client.request("GET", f"/api/runs/other/{rid}")[0] == 404
    finally:
        client.close()


def test_cli_revocation_reaches_a_running_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, _, _ = _setup(tmp_path, monkeypatch)
    client = Client(config)
    try:
        client.login()
        assert client.request("GET", "/api/state")[0] == 200
        SessionStore(config.sessions_path).revoke_all()  # what `sisyfus dispatch logout-all` does
        assert client.request("GET", "/api/state")[0] == 401
        stolen = client.cookie
        client.login()  # a new login must not write the revoked session back
        client.cookie = stolen
        assert client.request("GET", "/api/state")[0] == 401
    finally:
        client.close()


def test_artifacts_cannot_script_the_dispatch_origin_and_errors_close(tmp_path: Path,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    config, project, _ = _setup(tmp_path, monkeypatch)
    run = project / ".sisyfus" / "research" / "runs" / "research-x"
    (run / "report").mkdir(parents=True)
    (run / "snapshot.json").write_text("{}")
    (run / "evil.html").write_text("<script>fetch('/api/state')</script>")
    client = Client(config)
    try:
        client.login()
        status, body, headers = client.request("GET", "/obs/proj/research-x/artifact/evil.html")
        assert status == 200 and headers["Content-Type"].startswith("text/plain")
        assert headers["Content-Security-Policy"].startswith("sandbox")
        status, _, headers = client.request("POST", "/api/login", {"password": "x"}, origin="http://evil.example")
        assert status == 403 and headers.get("Connection") == "close"
    finally:
        client.close()


def test_page_is_installable_and_locked_down(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, _, _ = _setup(tmp_path, monkeypatch)
    client = Client(config)
    try:
        req = urllib.request.Request(client.base + "/", headers={"Host": f"127.0.0.1:{client.port}"})
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode()
            csp = response.headers["Content-Security-Policy"]
        nonce = csp.split("'nonce-", 1)[1].split("'", 1)[0]
        assert f'<script nonce="{nonce}">' in html and "frame-ancestors 'none'" in csp
        assert 'rel="manifest"' in html and 'rel="apple-touch-icon"' in html and "apple-mobile-web-app-capable" in html
        assert "http://" not in html and "https://" not in html.split("<script", 1)[0]
        icon = urllib.request.urlopen(urllib.request.Request(client.base + "/apple-touch-icon.png",
                                                             headers={"Host": f"127.0.0.1:{client.port}"}), timeout=5)
        assert icon.headers["Content-Type"] == "image/png" and icon.read()[:4] == b"\x89PNG"
    finally:
        client.close()


def test_recover_reattaches_or_closes_out_turns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, _, _ = _setup(tmp_path, monkeypatch)
    store = JobStore(config.jobs_dir)
    runner = JobRunner(config, store, poll_interval=0.05)
    lost = store.create("proj", "lost turn")
    store.update(lost["id"], lambda j: j.update({"status": "RUNNING", "pid": 999999, "turns": 1,
                                                  "turn_output": "turn-1.jsonl", "turn_started_at": j["created_at"]}))
    store.path(lost["id"], "turn-1.jsonl").write_text('{"type":"system","subtype":"init","session_id":"s9"}\n')
    finished = store.create("proj", "finished turn")
    store.update(finished["id"], lambda j: j.update({"status": "RUNNING", "pid": 999998, "turns": 1,
                                                      "turn_output": "turn-1.jsonl", "turn_started_at": j["created_at"]}))
    store.path(finished["id"], "turn-1.jsonl").write_text(
        '{"type":"result","subtype":"success","is_error":false,"result":"done","session_id":"s8","total_cost_usd":0.1}\n')
    # A live PID that is not our agent (PID reuse after a restart): never adopted or waited on.
    reused = store.create("proj", "reused pid")
    store.update(reused["id"], lambda j: j.update({"status": "RUNNING", "pid": os.getpid(), "pid_started": "Mon Jan  1 00:00:00 2001",
                                                    "turns": 1, "turn_output": "turn-1.jsonl", "turn_started_at": j["created_at"]}))
    store.path(reused["id"], "turn-1.jsonl").write_text("")
    started = time.monotonic()
    runner.recover()
    assert time.monotonic() - started < 5, "recover() must not wait on a process that is not ours"
    deadline = time.monotonic() + 5
    jobs = (lost, finished, reused)
    while time.monotonic() < deadline and any(store.load(j["id"])["status"] == "RUNNING" for j in jobs):
        time.sleep(0.05)
    assert store.load(lost["id"])["status"] == "INTERRUPTED"
    assert store.load(lost["id"])["session_id"] == "s9"
    assert store.load(finished["id"])["status"] == "IDLE"
    assert store.load(reused["id"])["status"] == "INTERRUPTED"


def test_cli_configures_projects_password_and_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    home = tmp_path / "home"
    project = tmp_path / "AlphaGPT"
    project.mkdir()
    assert dispatch_main(["--home", str(home), "init"]) == 0
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(PASSWORD + "\n"))
    assert dispatch_main(["--home", str(home), "password", "--password-stdin"]) == 0
    assert dispatch_main(["--home", str(home), "project", "add", "AlphaGPT", str(project)]) == 0
    assert dispatch_main(["--home", str(home), "project", "add", "home", str(Path.home())]) == 2
    assert dispatch_main(["--home", str(home), "config", "--max-budget-usd", "12", "--model", "claude-opus-5-5"]) == 0
    saved = json.loads((home / "config.json").read_text())
    assert saved["projects"] == {"AlphaGPT": str(project.resolve())} and saved["max_budget_usd"] == 12
    assert oct(os.stat(home / "password.json").st_mode & 0o777) == "0o600"
