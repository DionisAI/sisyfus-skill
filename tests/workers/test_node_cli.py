"""Frozen W4 CLI contract: absent-module RED, not native/remote acceptance.

Only this NEW file and its NEW contract are authored before source release.
Public NodeAgent shapes were inspected first. Scripted DI is control-flow-only;
real NO_WORK/UNKNOWN use authenticated isolated loopback and forbidden native.
No public NodeAgent.close, model/env/host flag, permanent deletion or task PASS.
"""
from __future__ import annotations

import copy
from dataclasses import asdict
import importlib
import inspect
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import threading
from types import SimpleNamespace
import uuid

import pytest

from sisyfus.workers.codex import CodexDriver
from sisyfus.workers.claude_code import ClaudeCodeDriver
from sisyfus.workers.lead_console import MissionHub
from sisyfus.workers.node_agent import NodeAgent
from sisyfus.workers.node_claims import NodeClaims
from sisyfus.workers.node_gateway import NodeGateway
from sisyfus.workers.node_registry import NodeRegistry
from sisyfus.workers.protocol import Request, digest
from sisyfus.workers.remote_artifacts import create_input_snapshot, full_tree_manifest
from test_lead_mission import make_spec


MODULE = "sisyfus.workers.node_cli"
ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC_SECRET = "c1" * 32


@pytest.fixture
def cli():
    # Dependency import first: absent source remains an explicit RED, rather
    # than being obscured by a later fixture's socket or constructor setup.
    return importlib.import_module(MODULE)


def outcome(status="NO_WORK", serial=1):
    return {"request_id": "agent_" + format(serial, "032x"), "status": status}


def paths(tmp_path):
    """DI-only operator paths: not a fake successful credential validation."""
    auth = tmp_path / "operator-fixture.json"
    with auth.open("xb") as stream:
        stream.write(b'{"fixture":"control-flow-only, not credential validation"}')
    auth.chmod(0o600)
    state = tmp_path / "agent-state"
    return auth, state, ["--credential-file", str(auth), "--state-directory", str(state)]


class ScriptedFactory:
    """Only public factory/Agent interfaces; no network, native, or state truth."""
    def __init__(self, sequence):
        self.sequence = sequence
        self.constructs, self.calls = [], 0
        owner = self

        class Agent:
            def run_once(self):
                owner.calls += 1
                assert owner.calls <= len(owner.sequence), "unexpected extra run_once"
                value = owner.sequence[owner.calls - 1]
                if isinstance(value, BaseException):
                    raise value
                return copy.deepcopy(value)

            @property
            def close(self):
                raise AssertionError("NodeAgent has no required public close interface")

        self.agent = Agent()

    def __call__(self, *args, **kwargs):
        assert len(args) == 2 and not kwargs, "factory accepts only the two paths"
        self.constructs.append(tuple(Path(arg) for arg in args))
        return self.agent


def diagnostic(captured, *, stage, error_type, status="ERROR"):
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 1
    value = json.loads(captured.err)
    assert value == {"status": status, "stage": stage, "error_type": error_type}
    assert SYNTHETIC_SECRET not in captured.err
    assert "Traceback" not in captured.err
    return value


def final_result(captured, expected):
    assert captured.err == "" and len(captured.out.splitlines()) == 1
    value = json.loads(captured.out)
    assert value == expected and set(value) == {"request_id", "status"}
    assert "PASS" not in captured.out and SYNTHETIC_SECRET not in captured.out
    return value


def test_static_public_agent_interfaces_match_the_frozen_cli_dependencies():
    ctor = inspect.signature(NodeAgent)
    assert list(ctor.parameters) == ["credential_file", "state_directory", "driver"]
    assert ctor.parameters["driver"].kind is inspect.Parameter.KEYWORD_ONLY
    assert ctor.parameters["driver"].default is None
    assert list(inspect.signature(NodeAgent.run_once).parameters) == ["self"]


def test_default_is_exactly_one_run_once_no_close_or_implicit_poll(cli, tmp_path, capsys):
    auth, state, argv = paths(tmp_path)
    before = auth.read_bytes()
    factory = ScriptedFactory([outcome(), AssertionError("default must not poll")])
    sleeps = []
    code = cli.main(argv, agent_factory=factory, sleep=sleeps.append)
    assert code == 0 and factory.calls == 1 and factory.constructs == [(auth, state)]
    assert sleeps == [] and auth.read_bytes() == before and not state.exists()
    final_result(capsys.readouterr(), outcome())


def test_poll_seconds_alone_does_not_enable_extra_queries(cli, tmp_path, capsys):
    _, _, argv = paths(tmp_path)
    factory = ScriptedFactory([outcome(), AssertionError("interval is not permission to poll")])
    sleeps = []
    assert cli.main(argv + ["--poll-seconds", "0.05"], agent_factory=factory, sleep=sleeps.append) == 0
    assert factory.calls == 1 and sleeps == []
    final_result(capsys.readouterr(), outcome())


@pytest.mark.parametrize("extra,interval", [(1, "0.01"), (2, "0.02"), (100, "30")])
def test_idle_count_is_additional_finite_only_no_work_with_no_last_sleep(cli, tmp_path, capsys, extra, interval):
    auth, state, argv = paths(tmp_path)
    rows = [outcome(serial=n) for n in range(1, extra + 2)]
    factory, sleeps = ScriptedFactory(rows), []
    assert cli.main(argv + ["--idle-polls", str(extra), "--poll-seconds", interval],
                    agent_factory=factory, sleep=sleeps.append) == 0
    assert factory.constructs == [(auth, state)] and factory.calls == 1 + extra
    assert sleeps == [float(interval)] * extra
    final_result(capsys.readouterr(), rows[-1])


def test_idle_poll_uses_default_interval_without_becoming_unlimited(cli, tmp_path, capsys):
    _, _, argv = paths(tmp_path)
    factory, sleeps = ScriptedFactory([outcome(serial=1), outcome(serial=2)]), []
    assert cli.main(argv + ["--idle-polls", "1"], agent_factory=factory, sleep=sleeps.append) == 0
    assert factory.calls == 2 and sleeps == [0.2]
    final_result(capsys.readouterr(), outcome(serial=2))


@pytest.mark.parametrize("status,code", [("RECEIPTED", 0), ("UNKNOWN", 2), ("RECONCILIATION_CANDIDATE", 2)])
@pytest.mark.parametrize("initial_idle", [False, True])
def test_every_non_no_work_transport_outcome_stops_immediately(cli, tmp_path, capsys, status, code, initial_idle):
    _, _, argv = paths(tmp_path)
    sequence = ([outcome(serial=1)] if initial_idle else []) + [outcome(status, 2)]
    factory, sleeps = ScriptedFactory(sequence), []
    assert cli.main(argv + ["--idle-polls", "100"], agent_factory=factory, sleep=sleeps.append) == code
    assert factory.calls == len(sequence) and sleeps == ([0.2] if initial_idle else [])
    final_result(capsys.readouterr(), sequence[-1])


BAD_ARGUMENTS = [
    [], ["--credential-file", "only-auth"], ["--state-directory", "only-state"],
    ["--secret", SYNTHETIC_SECRET], ["--model", "gpt-6.1-sol"], ["--host", "example.invalid"],
    ["--gateway-url", "http://example.invalid"], ["--env-copy"], ["run"], ["--forever"],
    ["--cred", "auth"], ["--state-dir", "state"],
    ["--credential-file", "first", "--credential-file", "second", "--state-directory", "state"],
    ["--credential-file=first", "--credential-file=second", "--state-directory=state"],
    ["--credential-file", "auth", "--state-directory", "first", "--state-directory", "second"],
    ["--credential-file", "auth", "--state-directory", "state", "--idle-polls", "1", "--idle-polls", "2"],
    ["--credential-file", "auth", "--state-directory", "state", "--poll-seconds", "0.1", "--poll-seconds", "0.2"],
]


@pytest.mark.parametrize("argv", BAD_ARGUMENTS)
def test_parser_errors_precede_factory_and_network_without_echoing_values(cli, tmp_path, capsys, monkeypatch, argv):
    called = []
    def forbidden(*args, **kwargs):
        called.append(True)
        raise AssertionError("parser must finish before any agent/network")
    monkeypatch.setattr(socket, "socket", forbidden)
    assert cli.main(argv, agent_factory=forbidden, sleep=forbidden) == 1
    assert called == [] and list(tmp_path.iterdir()) == []
    captured = capsys.readouterr()
    diagnostic(captured, stage="parse", error_type="ValueError")


@pytest.mark.parametrize("flag,bad", [
    *[("--idle-polls", value) for value in ("0", "-1", "101", "1000", "1.0", "True", "nan", "inf", "", "+1")],
    *[("--poll-seconds", value) for value in ("0", "-0", "-1", "0.009", "30.001", "nan", "inf", "-inf", "1e999", "True", "")],
])
def test_poll_limits_are_strict_before_construction(cli, tmp_path, capsys, flag, bad):
    auth, state, argv = paths(tmp_path)
    before = auth.read_bytes()
    factory = ScriptedFactory([AssertionError("bad polling flags must not construct")])
    assert cli.main(argv + [flag, bad], agent_factory=factory) == 1
    assert factory.constructs == [] and factory.calls == 0 and auth.read_bytes() == before
    assert not state.exists()
    diagnostic(capsys.readouterr(), stage="parse", error_type="ValueError")


def test_help_has_only_the_standalone_flags_and_zero_agent_or_network(cli, capsys, monkeypatch):
    called = []
    def forbidden(*args, **kwargs):
        called.append(True)
        raise AssertionError("help must be local only")
    monkeypatch.setattr(socket, "socket", forbidden)
    assert cli.main(["--help"], agent_factory=forbidden, sleep=forbidden) == 0
    captured = capsys.readouterr()
    assert captured.err == "" and called == []
    for flag in ("--credential-file", "--state-directory", "--idle-polls", "--poll-seconds", "--help"):
        assert flag in captured.out
    for flag in ("--secret", "--model", "--host", "--gateway-url", "--env-copy", "--node-gateway-port"):
        assert flag not in captured.out


BAD_RESULTS = [None, [], "NO_WORK", True, {"status": "NO_WORK"},
    outcome() | {"request_id": None}, outcome() | {"request_id": True},
    outcome() | {"request_id": "Node " + SYNTHETIC_SECRET},
    outcome() | {"request_id": "agent_" + "A" * 32},
    outcome() | {"status": None}, outcome() | {"status": True},
    outcome() | {"secret": SYNTHETIC_SECRET}, outcome() | {"verdict": "PASS"},
    outcome() | {"all_verified": True}, outcome() | {"candidate": "/untrusted/candidate"}]


@pytest.mark.parametrize("value", BAD_RESULTS)
def test_malformed_public_result_has_no_stdout_no_poll_and_no_secret_echo(cli, tmp_path, capsys, value):
    _, _, argv = paths(tmp_path)
    factory, sleeps = ScriptedFactory([value]), []
    assert cli.main(argv + ["--idle-polls", "100"], agent_factory=factory, sleep=sleeps.append) == 1
    assert factory.calls == 1 and sleeps == []
    diagnostic(capsys.readouterr(), stage="result", error_type="ValueError")


@pytest.mark.parametrize("status", ["CLAIMED", "IN_FLIGHT", "OFFERED", "WITHDRAWN", "DONE", "COMPLETED", "ERROR", "INTERRUPTED", "PASS"])
def test_native_or_internal_states_are_not_success_or_retry_aliases(cli, tmp_path, capsys, status):
    _, _, argv = paths(tmp_path)
    factory, sleeps = ScriptedFactory([outcome(status)]), []
    assert cli.main(argv + ["--idle-polls", "100"], agent_factory=factory, sleep=sleeps.append) == 1
    assert factory.calls == 1 and sleeps == []
    diagnostic(capsys.readouterr(), stage="result", error_type="ValueError")


@pytest.mark.parametrize("stage", ["construct", "run_once", "poll"])
@pytest.mark.parametrize("interrupt", [False, True])
def test_exceptions_expose_only_stage_and_type_and_never_retry(cli, tmp_path, capsys, stage, interrupt):
    _, _, argv = paths(tmp_path)
    exc = KeyboardInterrupt("Node " + SYNTHETIC_SECRET) if interrupt else RuntimeError("Node " + SYNTHETIC_SECRET)
    factory, sleeps, constructs = ScriptedFactory([outcome()]), [], []
    def construct(*args):
        constructs.append(args)
        if stage == "construct": raise exc
        return factory(*args)
    if stage == "run_once": factory.sequence = [exc]
    def sleep(seconds):
        sleeps.append(seconds)
        if stage == "poll": raise exc
        raise AssertionError("unexpected extra sleep")
    assert cli.main(argv + ["--idle-polls", "1"], agent_factory=construct, sleep=sleep) == (130 if interrupt else 1)
    assert len(constructs) == 1
    assert factory.calls == (0 if stage == "construct" else 1)
    assert sleeps == ([0.2] if stage == "poll" else [])
    diagnostic(capsys.readouterr(), stage=stage, error_type="KeyboardInterrupt" if interrupt else "RuntimeError",
               status="INTERRUPTED" if interrupt else "ERROR")


def test_custom_exception_class_name_is_not_a_secret_output_channel(cli, tmp_path, capsys):
    _, _, argv = paths(tmp_path)
    secret_named_error = type(SYNTHETIC_SECRET, (Exception,), {})
    def construct(*args):
        raise secret_named_error(SYNTHETIC_SECRET)
    assert cli.main(argv, agent_factory=construct) == 1
    diagnostic(capsys.readouterr(), stage="construct", error_type="Exception")


def attempts(state):
    """Readonly fixture readback only; production CLI uses public run_once."""
    with sqlite3.connect((state / "agent.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        return db.execute("SELECT request_id,status FROM attempts ORDER BY rowid").fetchall()


@pytest.fixture
def loopback(tmp_path, monkeypatch):
    assert os.environ.get("SISYFUS_TEST_LOOPBACK") == "1", "explicit isolated loopback fixture opt-in required"
    native_calls = []
    def forbidden(*args, **kwargs):
        native_calls.append(True)
        raise AssertionError("fixture forbids native/provider/controller dispatch")
    for driver in (CodexDriver, ClaudeCodeDriver):
        monkeypatch.setattr(driver, "run", forbidden)
        monkeypatch.setattr(driver, "probe", forbidden)
    controller = tmp_path / "controller"
    controller.mkdir()
    hub = MissionHub(controller / "hub")
    ident = hub.create(make_spec(controller))["id"]
    mission = hub._session(ident).mission
    mission._initial_plan()
    monkeypatch.setattr(hub, "start", forbidden)
    registry = NodeRegistry(mission.journal)
    node = registry.enroll("cli_fixture_enroll_0001", "W4 isolated fixture", ["codex"], ["gpt-6.1-sol"])
    claims = NodeClaims(mission.journal, registry, mission.directory / "remote/artifacts", lease_seconds=30)
    mission._node_claims = claims
    gateway = NodeGateway(hub, port=0)
    thread = threading.Thread(target=gateway.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    auth = tmp_path / "node-credential.json"
    data = {"schema": 1, "controller_mission_id": ident, "node_id": node["node_id"], "secret": node["secret"],
            "gateway_url": gateway.url, "gateway_host": "127.0.0.1:" + str(gateway.server_port)}
    with auth.open("x") as stream:
        json.dump(data, stream)
    auth.chmod(0o600)
    env = SimpleNamespace(root=tmp_path, hub=hub, mission=mission, node=node, claims=claims, gateway=gateway,
                          auth=auth, state=tmp_path / "agent-state", native_calls=native_calls)
    try:
        yield env
    finally:
        gateway.shutdown()
        gateway.server_close()
        thread.join(5)
        assert not thread.is_alive()
        hub.close()


def test_public_real_agent_no_work_shape_proof_without_cli(loopback):
    e = loopback
    original = e.auth.read_bytes()
    agent = NodeAgent(e.auth, e.state)
    result = agent.run_once()
    assert set(result) == {"request_id", "status"} and result["status"] == "NO_WORK"
    assert len(result["request_id"]) == 38 and result["request_id"].startswith("agent_")
    assert attempts(e.state) == [(result["request_id"], "NO_WORK")]
    assert e.auth.read_bytes() == original and e.auth.stat().st_mode & 0o777 == 0o600
    assert e.state.stat().st_mode & 0o777 == 0o700 and e.native_calls == []
    assert not e.mission.journal.runs() and not e.mission.snapshot()["all_verified"]


def test_default_real_no_work_gateway_uses_one_public_call_zero_native(cli, loopback, monkeypatch, capsys):
    e = loopback
    original, source = e.auth.read_bytes(), full_tree_manifest(e.mission.spec["source"])
    calls, real_once = [], NodeAgent.run_once
    def once(self):
        calls.append(True)
        return real_once(self)
    monkeypatch.setattr(NodeAgent, "run_once", once)
    assert cli.main(["--credential-file", str(e.auth), "--state-directory", str(e.state)]) == 0
    captured = capsys.readouterr()
    assert captured.err == "" and len(captured.out.splitlines()) == 1
    result = json.loads(captured.out)
    assert set(result) == {"request_id", "status"} and result["status"] == "NO_WORK"
    assert calls == [True] and e.native_calls == [] and attempts(e.state) == [(result["request_id"], "NO_WORK")]
    assert e.auth.read_bytes() == original and full_tree_manifest(e.mission.spec["source"]) == source
    assert not e.mission.journal.runs() and not e.mission.snapshot()["all_verified"]


@pytest.mark.parametrize("fault", ["credential-mode", "credential-link", "state-mode", "missing-parent"])
def test_real_agent_path_failures_stay_explicit_without_permission_repair_or_native(cli, loopback, capsys, fault):
    e = loopback
    original, auth, state = e.auth.read_bytes(), e.auth, e.state
    if fault == "credential-mode": auth.chmod(0o644)
    elif fault == "credential-link":
        auth = e.root / "alias-credential.json"
        auth.symlink_to(e.auth)
    elif fault == "state-mode":
        state.mkdir(mode=0o755)
        state.chmod(0o755)  # Freeze the invalid permission independently of umask.
    else: state = e.root / "absent-parent" / "agent-state"
    assert cli.main(["--credential-file", str(auth), "--state-directory", str(state)]) == 1
    diagnostic(capsys.readouterr(), stage="construct", error_type="FileNotFoundError" if fault == "missing-parent" else "ValueError")
    assert e.native_calls == [] and e.auth.read_bytes() == original and not e.mission.journal.runs()
    if fault == "credential-mode": assert e.auth.stat().st_mode & 0o777 == 0o644
    elif fault == "credential-link": assert auth.is_symlink()
    elif fault == "state-mode": assert state.stat().st_mode & 0o777 == 0o755
    else: assert not state.parent.exists()


def module_process(argv, root, *, gateway_port=None):
    """Actual python -m with fixture-only startup guard, retained unique marker.

    Child gets no provider/node-secret env; guard blocks native process and all
    socket connects except the one explicitly owned loopback gateway. No stub
    main, argv/status rewrite, success alias or production source is injected.
    """
    guard = root / ("cli-child-guard-" + uuid.uuid4().hex)
    guard.mkdir(mode=0o700)
    marker = guard / "guard-installed.json"
    source = (
        "import sys,json,socket\nfrom pathlib import Path\n"
        "from scripts.test_retained import guard_deletion\n"
        "sys.addaudithook(guard_deletion)\n"
        f"allowed_port={gateway_port!r}\n"
        "def boundary(event,args):\n"
        " if event in {'subprocess.Popen','os.system','os.posix_spawn','os.posix_spawnp'}:\n"
        "  raise AssertionError('fixture forbids native/provider/SSH process')\n"
        " if event=='socket.connect':\n"
        "  address=args[1]\n"
        "  if allowed_port is None or not isinstance(address,tuple) or address[:2]!=('127.0.0.1',allowed_port):\n"
        "   raise AssertionError('fixture forbids non-gateway connection')\n"
        "sys.addaudithook(boundary)\n"
        "from sisyfus.workers.codex import CodexDriver\n"
        "from sisyfus.workers.claude_code import ClaudeCodeDriver\n"
        "def forbidden(*args,**kwargs):\n"
        " raise AssertionError('fixture forbids native/probe')\n"
        "CodexDriver.run=CodexDriver.probe=forbidden\n"
        "ClaudeCodeDriver.run=ClaudeCodeDriver.probe=forbidden\n"
        f"with Path({str(marker)!r}).open('x') as f: json.dump({{'guard':'active','run':{guard.name!r}}},f)\n"
    )
    with (guard / "sitecustomize.py").open("x") as stream:
        stream.write(source)
    child_env = {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1", "SISYFUS_TEST_LOOPBACK": "1",
                 "PYTHONPATH": os.pathsep.join((str(guard), str(ROOT / "src"), str(ROOT)))}
    result = subprocess.run([sys.executable, "-m", MODULE, *argv], cwd=ROOT, env=child_env,
                            text=True, capture_output=True, timeout=12)
    assert json.loads(marker.read_text()) == {"guard": "active", "run": guard.name}
    assert "sitecustomize" not in result.stderr
    return result


def test_actual_module_help_is_local_and_has_no_agent_side_effect(cli, tmp_path):
    result = module_process(["--help"], tmp_path)
    assert result.returncode == 0 and result.stderr == ""
    assert "--credential-file" in result.stdout and "--idle-polls" in result.stdout
    assert not (tmp_path / "agent-state").exists()


def test_actual_module_default_no_work_gateway_private_paths_and_retained_state(cli, loopback):
    e = loopback
    original, source = e.auth.read_bytes(), full_tree_manifest(e.mission.spec["source"])
    result = module_process(["--credential-file", str(e.auth), "--state-directory", str(e.state)],
                            e.root, gateway_port=e.gateway.server_port)
    assert result.returncode == 0 and result.stderr == "" and len(result.stdout.splitlines()) == 1
    value = json.loads(result.stdout)
    assert set(value) == {"request_id", "status"} and value["status"] == "NO_WORK"
    assert attempts(e.state) == [(value["request_id"], "NO_WORK")]
    assert e.native_calls == [] and e.state.stat().st_mode & 0o777 == 0o700
    assert e.auth.read_bytes() == original and full_tree_manifest(e.mission.spec["source"]) == source
    assert e.node["secret"] not in result.stdout + result.stderr and not e.mission.journal.runs()


def persist_unknown(e):
    """Create unknown ONLY by public real Agent's persisted pre-spawn boundary."""
    prepared = e.root / "prepared-input"
    prepared.mkdir()
    (prepared / "input.txt").write_bytes(b"fixed isolated fixture bytes")
    snapshot = e.root / "input-snapshot"
    manifest = create_input_snapshot(prepared, snapshot, ["input.txt", "result.txt"])
    request = Request("build", "W4 protocol fixture, never task acceptance.", str(snapshot), "gpt-6.1-sol",
                      mode="workspace-write", timeout=4)
    key = "cli_unknown_fixture_0001"
    e.mission.journal.record("roles", key, {"role": "worker", "driver": "codex", "model": request.model,
                                          "mode": request.mode, "cwd": request.cwd})
    e.mission.journal.reserve(key, "build", digest(asdict(request)))
    e.claims.bind_input_snapshot(key, snapshot, manifest)
    e.claims.offer(key, e.node["node_id"], request, manifest)
    class BeforeSpawn:
        @property
        def run(self):
            raise KeyboardInterrupt("isolated persisted reservation-before-spawn fixture")
    agent = NodeAgent(e.auth, e.state, driver=BeforeSpawn())
    with pytest.raises(KeyboardInterrupt): agent.run_once()
    rows = attempts(e.state)
    assert len(rows) == 1 and rows[0][1] == "UNKNOWN" and e.native_calls == []
    return key, snapshot, rows[0][0]


@pytest.mark.parametrize("subprocess_entry", [False, True])
def test_persisted_unknown_replay_zero_native_one_readback_no_idle_respawn(cli, loopback, monkeypatch, capsys, subprocess_entry):
    e = loopback
    key, snapshot, request_id = persist_unknown(e)
    auth_bytes, input_tree = e.auth.read_bytes(), full_tree_manifest(snapshot)
    original_offer = e.claims.get(key)
    argv = ["--credential-file", str(e.auth), "--state-directory", str(e.state), "--idle-polls", "100", "--poll-seconds", "0.01"]
    if subprocess_entry:
        result = module_process(argv, e.root, gateway_port=e.gateway.server_port)
        assert result.returncode == 2 and result.stderr == ""
        assert json.loads(result.stdout) == {"request_id": request_id, "status": "UNKNOWN"}
        assert len(result.stdout.splitlines()) == 1
    else:
        calls, real_once = [], NodeAgent.run_once
        def once(self):
            calls.append(True)
            return real_once(self)
        def forbidden_sleep(*args):
            raise AssertionError("UNKNOWN must not poll again")
        monkeypatch.setattr(NodeAgent, "run_once", once)
        assert cli.main(argv, sleep=forbidden_sleep) == 2 and calls == [True]
        final_result(capsys.readouterr(), {"request_id": request_id, "status": "UNKNOWN"})
    assert attempts(e.state) == [(request_id, "UNKNOWN")] and e.native_calls == []
    assert e.auth.read_bytes() == auth_bytes and full_tree_manifest(snapshot) == input_tree
    assert e.claims.get(key) == original_offer  # Status-only, no node renewal/new claim.
    assert len(e.mission.journal.runs()) == 1 and e.mission.journal.runs()[0]["status"] == "IN_FLIGHT"
    assert not e.mission.snapshot()["all_verified"] and not e.mission.journal.records("reviews")
