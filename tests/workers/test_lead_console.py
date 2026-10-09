"""Retained protocol/core-boundary tests; these do not attest native models."""
from __future__ import annotations

import hashlib
import http.client
import json
import sqlite3
import threading
from pathlib import Path

import pytest

from sisyfus.autonomy.store import AutonomyStore
from sisyfus.workers import lead_cli
from sisyfus.workers.journal import Journal
from sisyfus.workers.lead_console import (DEFAULT_PORT, MAX_JSON_BYTES, PAGE, LeadConsole,
                                         MissionHub, approved_spec, safe_error)


def make_spec(root: Path) -> dict:
    project = root / "project"
    project.mkdir()
    (project / "README.md").write_text("Immutable source fixture\n")
    check = root / "fixed_check.py"
    check.write_text("import json; print(json.dumps({'ok': True}))\n")
    return {"source": str(project), "objective": "Build a usable console <script>not HTML</script>",
            "checks": {"fixed": {"argv": ["python3", str(check), "{candidate}"],
                                 "code_hashes": {str(check): hashlib.sha256(check.read_bytes()).hexdigest()},
                                 "contract": {"kind": "rules",
                                              "pass_if": {"all": [{"path": "ok", "op": "eq", "value": True}]},
                                              "fail_if": {"all": [{"path": "ok", "op": "eq", "value": False}]}}}}}


class StubMission:
    """Matches exactly the advertised LeadMission surface, using the real DB.
    No code path starts native CLI processes. False verification is deliberate:
    neither a successful run return nor an ACK can change acceptance truth.
    """
    created: list = []
    block = True
    failure: Exception | None = None

    def __init__(self, directory, spec=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.store = AutonomyStore(self.directory / "autonomy.sqlite3")
        self.journal = Journal(self.store)
        if spec is not None:
            self.journal.bind(spec)
        self.spec = self.journal.spec()
        self.stop = threading.Event()
        self.started = threading.Event()
        self.calls = 0
        self.last_cycles = "not invoked"
        type(self).created.append(self)

    def snapshot(self):
        with self.store._transaction(immediate=False) as db:
            r = db.execute("SELECT value FROM metadata WHERE key='fixture_stop'").fetchone()
        return {"objective": self.spec["objective"], "roles": self.spec["roles"],
                **{k: self.spec[k] for k in ("max_calls", "max_iterations", "max_tokens", "max_cost_usd", "max_wall_minutes")},
                "paused": self.journal.paused(), "stopped": bool(r and r[0] == "1"),
                "all_verified": False, "nodes": [{"id": "build", "depends_on": [], "verdict": "UNVERIFIED"}],
                "attempts": [{"receipt": {"status": "COMPLETED", "requested_model": "gpt-6.1-sol", "actual_model": None}}],
                "diagnoses": [{"category": "implementation"}], "reviews": [{"verdict": "FAIL"}],
                "tests": [{"verdict": "FAIL"}], "integration": {"status": "PENDING"},
                "rsi": {"procedure_version": 1, "promoted": False}}

    def run(self, max_cycles=None):
        self.calls += 1
        self.last_cycles = max_cycles
        self.started.set()
        if type(self).failure:
            raise type(self).failure
        if type(self).block:
            assert self.stop.wait(10), "fixture stop timed out"
        return {"all_verified": False}

    def request_stop(self):
        with self.store._transaction() as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES('fixture_stop','1')")
            self.journal._event(db, "fixture_stop", "mission", {}, actor="operator")
        self.stop.set()


@pytest.fixture(autouse=True)
def reset_stub(monkeypatch):
    monkeypatch.setattr(StubMission, "created", [])
    monkeypatch.setattr(StubMission, "block", True)
    monkeypatch.setattr(StubMission, "failure", None)


@pytest.fixture
def hub(tmp_path):
    value = MissionHub(tmp_path / "hub", mission_factory=StubMission)
    yield value
    value.close()


@pytest.fixture
def server(hub):
    value = LeadConsole(hub, port=0)
    thread = threading.Thread(target=value.serve_forever, daemon=True)
    thread.start()
    yield value
    value.shutdown()
    value.server_close()
    thread.join()


def request(server, path, *, body=None, auth=True, headers=None, raw=None, method=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=6)
    h = {"Authorization": "Bearer " + server.token} if auth else {}
    if body is not None:
        raw = json.dumps(body)
    if raw is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    conn.request(method or ("POST" if raw is not None else "GET"), path, body=raw, headers=h)
    response = conn.getresponse()
    data = response.read()
    result = response.status, data, dict(response.getheaders())
    conn.close()
    return result


def test_create_defaults_bound_to_canonical_db_no_dispatch(hub, tmp_path):
    spec = make_spec(tmp_path)
    created = hub.create(spec)
    ident = created["id"]
    assert ident.startswith("m_") and len(ident) == 34
    assert Path(created["directory"]).parent == hub.directory
    bound = approved_spec(Path(created["directory"]))
    assert bound["roles"]["lead"]["model"] == "claude-opus-5-5"
    assert bound["roles"]["worker"]["model"] == "gpt-6.1-sol"
    assert bound["roles"]["reviewer"]["model"] == "claude-opus-5-5"
    assert bound["parallelism"] == 2 and bound["timeout"] == 900
    assert all(bound[k] is None for k in ("max_calls", "max_iterations", "max_tokens", "max_cost_usd", "max_wall_minutes"))
    assert created["started"] is False and StubMission.created[0].calls == 0
    assert list(hub.directory.glob("*.sqlite3")) == []
    assert hub.inventory()["missions"][0]["id"] == ident
    assert StubMission.created[0].store.verify_event_chain()["valid"]


def test_inventory_and_serve_do_not_initialize_unknown_or_incomplete(hub, tmp_path):
    hub.directory.mkdir()
    (hub.directory / "unknown").mkdir()
    partial = hub.directory / "incomplete"
    partial.mkdir()
    AutonomyStore(partial / "autonomy.sqlite3")
    inventory = hub.inventory()
    assert inventory["missions"] == []
    assert len(inventory["issues"]) == 2
    assert not StubMission.created
    with pytest.raises(ValueError, match="approved"):
        hub.start("incomplete", allow_local_workers=True)
    with pytest.raises(FileNotFoundError):
        hub.start("unknown", allow_local_workers=True)
    assert not (hub.directory / "unknown" / "autonomy.sqlite3").exists()
    assert not StubMission.created


def test_restart_inventory_does_not_dispatch_or_replay_pending_controls(hub, tmp_path):
    ident = hub.create(make_spec(tmp_path))["id"]
    session = hub._session(ident)
    hub._record(session, "pending-fixture", "start")
    restarted = MissionHub(hub.directory, mission_factory=StubMission)
    assert restarted.inventory()["missions"][0]["id"] == ident
    assert len(StubMission.created) == 1  # Inventory doesn't even instantiate core.
    state = restarted.snapshot(ident)
    assert state["controls"][0]["status"] == "PENDING"
    assert state["controls"][0]["terminal"] is False
    assert state["snapshot"]["all_verified"] is False
    assert not state["controller"]["running"]
    assert StubMission.created[-1].calls == 0
    restarted.close()


@pytest.mark.parametrize("phase", ["WAITING_LEAD", "NEEDS_OPERATOR"])
def test_operator_start_and_resume_delegate_wait_epoch_to_core(tmp_path, monkeypatch, phase):
    class ResumableMission(StubMission):
        block = False

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.resume_calls = 0
            self.phase = phase

        def snapshot(self):
            return {**super().snapshot(), "phase": self.phase}

        def request_resume(self):
            self.resume_calls += 1
            self.journal.pause(False)
            self.phase = "PLANNING"

    hub = MissionHub(tmp_path / "resumable-hub", mission_factory=ResumableMission)
    try:
        ident = hub.create(make_spec(tmp_path))["id"]
        mission = hub._session(ident).mission
        hub.start(ident, allow_local_workers=True)
        hub.wait(ident, timeout=2)
        assert mission.resume_calls == 1 and mission.calls == 1
        mission.journal.pause(True)
        hub.control(ident, "resume")
        assert mission.resume_calls == 2 and not mission.journal.paused()
        assert not mission.stop.is_set()
        assert hub.snapshot(ident)["snapshot"]["all_verified"] is False
    finally:
        hub.close()


def test_real_controller_boundary_only_explicit_start_and_duplicate_guard(hub, tmp_path):
    ident = hub.create(make_spec(tmp_path))["id"]
    mission = hub._session(ident).mission
    with pytest.raises(PermissionError):
        hub.start(ident)
    assert hub.controls(ident) == [] and mission.calls == 0
    ack = hub.start(ident, allow_local_workers=True)
    assert ack["terminal"] is False and ack["status"] == "ACK"
    assert mission.started.wait(2) and mission.last_cycles is None
    assert hub.snapshot(ident)["controller"]["local_workers_acknowledged"] is True
    with pytest.raises(RuntimeError, match="already running"):
        hub.start(ident, allow_local_workers=True)
    assert mission.calls == 1
    assert hub.control(ident, "pause")["scope"] == "new_dispatch_only"
    assert mission.journal.paused()
    hub.control(ident, "resume")
    assert not mission.journal.paused()
    hub.control(ident, "stop")
    assert mission.stop.is_set()
    assert hub.wait(ident, 2) == {"all_verified": False}
    reopened = MissionHub(hub.directory, mission_factory=StubMission)
    assert reopened.snapshot(ident)["snapshot"]["stopped"] is True
    assert reopened.snapshot(ident)["snapshot"]["all_verified"] is False
    with pytest.raises(RuntimeError, match="durably stopped"):
        reopened.start(ident, allow_local_workers=True)
    assert StubMission.created[-1].calls == 0
    assert mission.store.verify_event_chain()["valid"]


def test_independent_mission_threads_and_controls(hub, tmp_path):
    spec = make_spec(tmp_path)
    left, right = hub.create(spec)["id"], hub.create(spec)["id"]
    hub.start(left, allow_local_workers=True, max_cycles=4)
    hub.start(right, allow_local_workers=True, max_cycles=5)
    lm, rm = hub._session(left).mission, hub._session(right).mission
    assert lm.started.wait(2) and rm.started.wait(2)
    assert lm.last_cycles == 4 and rm.last_cycles == 5
    hub.control(left, "pause")
    assert lm.journal.paused() and not rm.journal.paused()
    hub.control(left, "stop")
    hub.wait(left, 2)
    assert hub.snapshot(right)["controller"]["running"]
    assert lm.directory != rm.directory
    assert lm.store.verify_event_chain()["valid"] and rm.store.verify_event_chain()["valid"]


@pytest.mark.parametrize("ident", ["../elsewhere", "..", ".", "/tmp", "a/b", "a%2Fb", "a\\b", "", "x" * 65, None])
def test_fixed_child_path_validation(hub, ident):
    with pytest.raises(ValueError):
        hub.path(ident)


def test_symlink_children_and_database_rejected(hub, tmp_path):
    ident = hub.create(make_spec(tmp_path))["id"]
    (hub.directory / "redirect").symlink_to(hub.path(ident), target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        hub.path("redirect")
    fake = hub.directory / "linked_db"
    fake.mkdir()
    (fake / "autonomy.sqlite3").symlink_to(hub.path(ident) / "autonomy.sqlite3")
    assert {i["id"] for i in hub.inventory()["issues"]} == {"redirect", "linked_db"}
    with pytest.raises(FileNotFoundError):
        hub.snapshot("linked_db")


def test_disjoint_source_check_before_database_creation(tmp_path):
    spec = make_spec(tmp_path)
    control = Path(spec["source"]) / "control"
    h = MissionHub(control, single=True, mission_factory=StubMission)
    with pytest.raises(ValueError, match="disjoint"):
        h.create(spec)
    assert not control.exists() and not StubMission.created
    h = MissionHub(tmp_path, single=True, mission_factory=StubMission)
    with pytest.raises(ValueError, match="disjoint"):
        h.create(spec)
    assert not (tmp_path / "autonomy.sqlite3").exists()


def test_fixed_hashes_and_both_contract_branches_required(hub, tmp_path):
    spec = make_spec(tmp_path)
    spec["checks"]["fixed"]["contract"].pop("fail_if")
    with pytest.raises(ValueError, match="fail_if"):
        hub.create(spec)
    spec["checks"]["fixed"]["contract"]["fail_if"] = {"all": [{"path": "ok", "op": "eq", "value": False}]}
    code = Path(next(iter(spec["checks"]["fixed"]["code_hashes"])))
    code.write_text("print('changed')\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        hub.create(spec)
    assert not StubMission.created


def test_worker_exceptions_persist_explicit_error_not_success(hub, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-credential-123456789")
    StubMission.failure = RuntimeError("transport rejected fixture-credential-123456789 Bearer top-secret-token")
    ident = hub.create(make_spec(tmp_path))["id"]
    hub.start(ident, allow_local_workers=True)
    with pytest.raises(RuntimeError, match="transport rejected"):
        hub.wait(ident, 2)
    state = hub.snapshot(ident)
    assert not state["controller"]["running"]
    assert state["controls"][0]["status"] == "ERROR"
    raw = json.dumps(state)
    assert "fixture-credential" not in raw and "top-secret-token" not in raw
    assert state["snapshot"]["all_verified"] is False
    assert hub._session(ident).mission.store.verify_event_chain()["valid"]
    assert MissionHub(hub.directory, mission_factory=StubMission).controls(ident)[0]["status"] == "ERROR"


@pytest.mark.parametrize("path", ["/", "/api/missions", "/api/snapshot", "/api/events"])
def test_host_origin_checks_cover_html_and_api(server, path):
    assert request(server, path, headers={"Host": "attacker.test"})[0] == 403
    assert request(server, path, headers={"Origin": "https://attacker.test"})[0] == 403
    assert request(server, path, headers={"Origin": "null"})[0] == 403
    assert request(server, path, headers={"Origin": f"http://localhost:{server.server_port}"})[0] == 403
    good = f"http://127.0.0.1:{server.server_port}"
    assert request(server, "/api/missions", headers={"Origin": good})[0] == 200


def test_page_fragment_csp_no_store_no_token_injection(server):
    assert server.server_address[0] == "127.0.0.1" and DEFAULT_PORT == 8781
    status, raw, headers = request(server, "/", auth=False)
    assert status == 200 and headers["Cache-Control"] == "no-store"
    assert server.token.encode() not in raw
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    nonce = headers["Content-Security-Policy"].split("script-src 'nonce-", 1)[1].split("'", 1)[0]
    assert raw.count(('nonce="' + nonce + '"').encode()) == 2
    assert b"innerHTML" not in raw and b"unsafeHTML" not in raw and b"textContent" in raw
    assert b"history.replaceState" in raw and b"location.hash" in raw
    assert b"Unlimited" in raw and b"claude-opus-5-5" in raw and b"gpt-6.1-sol" in raw
    for path in ("/api/missions", "/api/control", "/api/snapshot", "/api/events"):
        assert request(server, path, auth=False)[0] == 401
    assert "token=" in server.url and server.url.startswith("http://127.0.0.1:")
    assert not StubMission.created


def test_http_create_select_evidence_controls_and_replay(server, tmp_path):
    status, raw, _ = request(server, "/api/missions", body={"spec": make_spec(tmp_path)})
    assert status == 201
    ident = json.loads(raw)["id"]
    status, raw, _ = request(server, "/api/snapshot?mission_id=" + ident)
    s = json.loads(raw)["snapshot"]
    assert status == 200 and not s["all_verified"]
    assert s["attempts"][0]["receipt"]["actual_model"] is None
    assert all(k in s for k in ("nodes", "attempts", "diagnoses", "reviews", "tests", "integration", "rsi"))
    assert request(server, "/api/control", body={"mission_id": ident, "action": "start"})[0] == 403
    assert request(server, "/api/control", body={"mission_id": ident, "action": "start", "allow_local_workers": True})[0] == 202
    assert StubMission.created[0].started.wait(2)
    for action in ("pause", "resume", "stop"):
        status, raw, _ = request(server, "/api/control", body={"mission_id": ident, "action": action})
        assert status == 202 and json.loads(raw)["terminal"] is False
    server.hub.wait(ident, 2)
    events = json.loads(request(server, "/api/events?mission_id=" + ident)[1])
    assert events["events"] and events["cursor"] > 0
    later = json.loads(request(server, f"/api/events?mission_id={ident}&cursor={events['cursor']}")[1])
    assert later["events"] == [] and later["cursor"] == events["cursor"]
    assert StubMission.created[0].store.verify_event_chain()["valid"]


@pytest.mark.parametrize("raw,headers", [
    ("{}", {"Content-Length": str(MAX_JSON_BYTES + 1)}),
    ("{}", {"Content-Type": "text/plain"}),
    ("{}", {"Transfer-Encoding": "chunked"}),
    ("[]", {}), ("{", {}), ('{"spec":NaN}', {}),
    ('{"action":"start","action":"stop"}', {}),
    (b'\xff', {}),
])
def test_bounded_strict_json_errors_are_detailed(server, raw, headers):
    status, data, h = request(server, "/api/control", raw=raw, headers=headers)
    assert status == 400
    error = json.loads(data)["error"]
    assert error["type"] and error["message"]
    assert h["Cache-Control"] == "no-store"
    assert not StubMission.created


@pytest.mark.parametrize("body", [
    {"mission_id": "../escape", "action": "pause"},
    {"mission_id": "fake", "action": "approve", "verdict": "PASS"},
    {"mission_id": "fake", "action": "start", "allow_local_workers": "true"},
    {"mission_id": "fake", "action": "start", "allow_local_workers": True, "max_cycles": 0},
])
def test_no_gate_mutation_arbitrary_controls_or_paths(server, body):
    assert request(server, "/api/control", body=body)[0] == 400
    assert request(server, "/api/promote", body={})[0] == 404
    assert request(server, "/api/evaluate", body={})[0] == 404
    assert not StubMission.created


def test_single_console_binds_nothing_unknown_and_cannot_create(tmp_path):
    h = MissionHub(tmp_path / "missing", single=True, mission_factory=StubMission)
    assert not h.directory.exists()
    assert h.inventory()["missions"] == []
    with pytest.raises(FileNotFoundError):
        h.snapshot("mission")
    assert not h.directory.exists()
    with pytest.raises(ValueError):
        h.path("other")


def test_cli_new_status_and_permission_fail_fast(tmp_path, monkeypatch, capsys):
    from sisyfus.workers import lead_console
    monkeypatch.setattr(lead_console, "lead_mission", StubMission)
    spec = make_spec(tmp_path)
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    control = tmp_path / "control"
    for name in ("run", "up"):
        assert lead_cli.main([name, str(path), "--directory", str(control)]) == 1
        assert "--allow-local-workers" in capsys.readouterr().err
    assert not control.exists()
    assert lead_cli.main(["new", str(path), "--directory", str(control)]) == 0
    assert json.loads(capsys.readouterr().out)["started"] is False
    assert lead_cli.main(["status", "--directory", str(control)]) == 0
    state = json.loads(capsys.readouterr().out)
    assert not state["controller"]["running"] and not state["snapshot"]["all_verified"]
    assert not any(m.calls for m in StubMission.created)


def test_cli_run_calls_core_on_thread_unlimited_and_not_false_success(tmp_path, monkeypatch, capsys):
    from sisyfus.workers import lead_console
    monkeypatch.setattr(lead_console, "lead_mission", StubMission)
    monkeypatch.setattr(StubMission, "block", False)
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(make_spec(tmp_path)))
    assert lead_cli.main(["run", str(path), "--directory", str(tmp_path / "control"), "--allow-local-workers"]) == 2
    state = json.loads(capsys.readouterr().out)
    assert state["result"]["all_verified"] is False
    assert StubMission.created[0].calls == 1 and StubMission.created[0].last_cycles is None


@pytest.mark.parametrize("command", ["hub", "serve", "up"])
def test_cli_hosting_start_semantics_and_browser_open(command, tmp_path, monkeypatch, capsys):
    from sisyfus.workers import lead_console
    monkeypatch.setattr(lead_console, "lead_mission", StubMission)
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(make_spec(tmp_path)))
    control = tmp_path / "control"
    if command == "serve":
        assert lead_cli.main(["new", str(path), "--directory", str(control)]) == 0
        capsys.readouterr()
    opened, listeners = [], []

    class StubServer:
        def __init__(self, hub, *, port):
            assert port == 8781
            self.hub = hub
            self.url = "http://127.0.0.1:8781/#token=fixture-only"
            listeners.append(self)
        def serve_forever(self):
            if command == "up":
                assert StubMission.created[-1].started.wait(2)
                assert self.hub.snapshot("mission")["controller"]["running"]
            else:
                assert not any(m.calls for m in StubMission.created)
            raise KeyboardInterrupt
        def server_close(self):
            self.closed = True

    monkeypatch.setattr(lead_cli, "LeadConsole", StubServer)
    monkeypatch.setattr(lead_cli.webbrowser, "open", lambda url: opened.append(url) or True)
    argv = [command, "--directory", str(control), "--open"]
    if command == "up":
        argv += [str(path), "--allow-local-workers"]
    assert lead_cli.main(argv) == 130
    assert opened == [listeners[0].url] and listeners[0].closed
    assert all(not s.thread or not s.thread.is_alive() for s in listeners[0].hub._sessions.values())


def test_cli_bind_failure_listen_failure_status_dont_create_false_success(tmp_path, monkeypatch, capsys):
    from sisyfus.workers import lead_console
    monkeypatch.setattr(lead_console, "lead_mission", StubMission)
    control = tmp_path / "missing"
    assert lead_cli.main(["status", "--directory", str(control)]) == 1
    capsys.readouterr()
    assert lead_cli.main(["serve", "--directory", str(control)]) == 1
    capsys.readouterr()
    assert not control.exists()
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(make_spec(tmp_path)))
    def occupied(*args, **kwargs):
        raise OSError("port already occupied")
    monkeypatch.setattr(lead_cli, "LeadConsole", occupied)
    assert lead_cli.main(["up", str(spec), "--directory", str(control), "--allow-local-workers"]) == 1
    assert "port already occupied" in capsys.readouterr().err
    assert StubMission.created[0].calls == 0


def test_no_second_truth_db_and_preserved_source(hub, tmp_path):
    spec = make_spec(tmp_path)
    source = Path(spec["source"])
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    ident = hub.create(spec)["id"]
    hub.control(ident, "pause")
    hub.control(ident, "resume")
    db = sqlite3.connect(hub.path(ident) / "autonomy.sqlite3")
    try:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"evidence", "events", "decisions", "continuations", "lead_console_controls"} <= tables
        assert db.execute("SELECT count(*) FROM evidence").fetchone()[0] == 0
    finally:
        db.close()
    assert [p.name for p in hub.path(ident).glob("*.sqlite3")] == ["autonomy.sqlite3"]
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}


def test_errors_redact_provider_bearer_and_server_token(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-api-key-long123")
    err = safe_error(ValueError("bad fixture-api-key-long123 Bearer abc123 token fixture-hub-token"), token="fixture-hub-token")
    assert "fixture-api-key" not in err["message"] and "abc123" not in err["message"]
    assert "fixture-hub-token" not in err["message"] and err["type"] == "ValueError"


def test_optional_caps_and_custom_models_survive_binding(hub, tmp_path):
    spec = make_spec(tmp_path)
    spec.update(max_calls=20, max_iterations=6, max_tokens=8000, max_cost_usd=2.5, max_wall_minutes=50)
    spec["roles"] = {"lead": {"model": "operator-lead"}, "worker": {"model": "operator-worker"},
                     "reviewer": {"model": "operator-review"}}
    bound = approved_spec(Path(hub.create(spec)["directory"]))
    assert all(bound[k] == spec[k] for k in ("max_calls", "max_iterations", "max_tokens", "max_cost_usd", "max_wall_minutes"))
    assert bound["roles"]["reviewer"]["model"] == "operator-review"


def test_invalid_json_query_and_unknown_routes(server):
    assert request(server, "/api/events?mission_id=one&mission_id=two")[0] == 400
    assert request(server, "/api/events?mission_id=one&other=1")[0] == 400
    assert request(server, "/api/events?mission_id=one&cursor=-1")[0] == 400
    assert request(server, "/api/events?mission_id=one&cursor=NaN")[0] == 400
    assert request(server, "/missing")[0] == 404
    assert request(server, "/api/missions", body={"spec": {}, "directory": "../outside"})[0] == 400


def test_cli_cycle_caps_parse_without_implicit_limit():
    for command in ("run", "up"):
        args = lead_cli.parser().parse_args([command, "spec.json", "--directory", "/tmp/control"])
        assert args.max_cycles is None
    assert "Unlimited" in PAGE
    # min=0.1 with HTML's default step=1 invalidates the default 900; exercise
    # the actual markup contract exposed by the CUA create workflow.
    assert 'min="0.1" step="any" max="7200" value="900"' in PAGE


def test_actual_core_binding_snapshot_stop_and_chain_without_native_calls(tmp_path):
    """No stub if core is available; binding and operator stop never call models."""
    pytest.importorskip("sisyfus.workers.lead_mission")
    h = MissionHub(tmp_path / "real_core_hub")
    spec = make_spec(tmp_path)
    spec["max_calls"] = 15
    created = h.create(spec)
    ident = created["id"]
    snapshot = h.snapshot(ident)["snapshot"]
    assert snapshot["budgets"]["max_calls"] == 15
    assert snapshot["native_call_reservations"] == 0
    assert not snapshot["all_verified"] and snapshot["phase"] == "PLANNING"
    assert snapshot["procedure"]["version"] == 1
    h.control(ident, "pause")
    h.control(ident, "resume")
    h.control(ident, "stop")
    reopened = MissionHub(h.directory)
    assert reopened.snapshot(ident)["snapshot"]["stopped"] is True
    assert reopened.snapshot(ident)["snapshot"]["native_call_reservations"] == 0
    with pytest.raises(RuntimeError, match="durably stopped"):
        reopened.start(ident, allow_local_workers=True)
    assert h._session(ident).mission.store.verify_event_chain()["valid"]
    h.close()
    reopened.close()


def test_cli_cleanup_failure_is_structured_error(tmp_path, monkeypatch, capsys):
    def failure(_self):
        raise RuntimeError("cooperative stop persistence failed")
    monkeypatch.setattr(MissionHub, "close", failure)
    assert lead_cli.main(["status", "--directory", str(tmp_path / "missing")]) == 1
    err = capsys.readouterr().err
    assert "cooperative stop persistence failed" in err
    assert "Traceback" not in err
