"""Frozen vertical Runtime cases from share contract 2cfd3969; DI is not public CF evidence."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import sys
import threading
import time
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

OPERATOR = "operator-fixture-56c2fbb1de694fe79b223a1805db453a"
SHARE = "share-fixture-a89ce329bd19413aa4841a015560c12c"


def runtime_module():
    return importlib.import_module("sisyfus.workers.share_runtime")


class FixtureGateway(ThreadingHTTPServer):
    """Owned real local HTTP loop; only public frozen Gateway members are used."""
    def __init__(self, origin, token, mission_id, *, port=0, allow_messages=False, report_path=None):
        self.arguments = (origin, token, mission_id, port, allow_messages, report_path)
        self.token = SHARE
        self.revoked = False
        self.assigned = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(inner):
                body = b"fixture inert page"
                inner.send_response(410 if self.revoked else 200)
                inner.send_header("Content-Length", str(len(body)))
                inner.end_headers()
                inner.wfile.write(body)
            def log_message(inner, *args):
                pass
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = "http://127.0.0.1:" + str(self.server_port)
        self.url = self.origin + "/"

    def set_public_origin(self, url):
        assert not self.assigned
        self.assigned.append(url)

    def revoke(self):
        self.revoked = True


def inputs(tmp_path):
    token = tmp_path / "operator.token"
    fd = os.open(token, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, (OPERATOR + "\n").encode())
    finally:
        os.close(fd)
    return token, tmp_path / "runtime"


def make(tmp_path, **kwargs):
    token, root = inputs(tmp_path)
    options = {"local_only": True, "gateway_factory": FixtureGateway}
    options.update(kwargs)
    return runtime_module().ShareRuntime("http://127.0.0.1:59575", token, "mission-fixture", root, **options), token, root


def public_only(meta):
    assert meta["schema"] == "sisyfus.share.runtime.v1"
    assert meta["permissions"]["controls"] is False
    serial = json.dumps(meta)
    assert OPERATOR not in serial and SHARE not in serial and "#token=" not in serial
    return meta


def fixture_executable(tmp_path, mode):
    path = tmp_path / "fixture-cloudflared"
    body = r'''
import json, os, sys, time
from pathlib import Path
p=Path.cwd()
(p/'child-fixture.json').write_text(json.dumps({'argv':sys.argv,'env':dict(os.environ),'cwd':str(p),'pid':os.getpid(),'pgid':os.getpgrp()}))
mode=MODE
if mode=='exit':
    print('operator-fixture-56c2fbb1de694fe79b223a1805db453a secret error',flush=True)
    raise SystemExit(7)
if mode=='large':
    print('X'*1100000,flush=True)
else:
    print(json.dumps({'message':'Your quick Tunnel has been created! https://fixture-run.trycloudflare.com'}),flush=True)
    if mode=='connected':
        print(json.dumps({'message':'Registered tunnel connection','connIndex':0,'protocol':'quic'}),flush=True)
    if mode=='wrong-host':
        print(json.dumps({'message':'https://other-run.trycloudflare.com'}),flush=True)
    while mode=='gated' and not (p/'connect.release').exists():
        time.sleep(.01)
    if mode=='gated':
        print(json.dumps({'message':'Registered tunnel connection','connIndex':0,'protocol':'quic'}),flush=True)
while True:
    time.sleep(.03)
'''.replace("MODE", repr(mode))
    source = "#!" + sys.executable + " -B\n" + body
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o700)
    try:
        os.write(fd, source.encode())
    finally:
        os.close(fd)
    return path


def await_state(run, states, seconds=2):
    deadline = time.monotonic() + seconds
    meta = None
    while time.monotonic() < deadline:
        meta = public_only(run.status())
        if meta["state"] in states:
            return meta
        time.sleep(.01)
    raise AssertionError(meta)


def test_constructor_is_inert_and_close_before_start(tmp_path):
    run, token, root = make(tmp_path)
    assert not root.exists()
    assert public_only(run.status())["state"] == "NEW"
    assert not root.exists()
    assert public_only(run.close())["state"] == "CLOSED"
    with pytest.raises(Exception):
        run.start()
    assert not root.exists()


def test_local_only_private_link_original_preserved_and_public_close(tmp_path):
    seen = []
    def factory(*args, **kwargs):
        obj = FixtureGateway(*args, **kwargs)
        seen.append(obj)
        return obj
    run, token, root = make(tmp_path, allow_messages=True, gateway_factory=factory)
    before = (token.read_bytes(), token.stat().st_ino, token.stat().st_mtime_ns)
    try:
        meta = public_only(run.start())
        assert meta["state"] == "LOCAL_ONLY"
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        access = Path(meta["access_file"])
        assert stat.S_IMODE(access.stat().st_mode) == 0o600
        link = json.loads(access.read_text())["private_url"]
        assert parse_qs(urlsplit(link).fragment)["token"] == [SHARE]
        assert OPERATOR not in link and link.startswith(seen[0].url)
        assert seen[0].arguments == ("http://127.0.0.1:59575", OPERATOR, "mission-fixture", 0, True, None)
        assert seen[0].url == seen[0].origin + "/" and "#" not in seen[0].url
        assert meta["process_returncode"] is None
    finally:
        closed = public_only(run.close())
    assert closed["state"] == "CLOSED" and closed["resources_closed"]
    assert seen[0].revoked
    assert run.close() == closed
    assert (token.read_bytes(), token.stat().st_ino, token.stat().st_mtime_ns) == before
    assert access.exists()
    assert not any(t.name.startswith("sisyfus-share-") and t.is_alive() for t in threading.enumerate())


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o400, 0o666])
def test_operator_mode_exact_600(tmp_path, mode):
    run, token, root = make(tmp_path)
    token.chmod(mode)
    with pytest.raises(Exception):
        run.start()
    assert not root.exists()
    assert public_only(run.status())["state"] == "FAILED"
    run.close()


@pytest.mark.parametrize("content", [b"", b"Bearer x", b" https://x/#token=y", b"a\nb", b"x\r\nInjected: y", b"x" * 4097, b"\xff", b" leading"])
def test_operator_token_rejected_without_original_changes(tmp_path, content):
    run, token, root = make(tmp_path)
    token.write_bytes(content)
    before = token.read_bytes()
    with pytest.raises(Exception):
        run.start()
    assert token.read_bytes() == before and not root.exists()
    run.close()


def test_symlink_hardlink_and_fifo_operator_admission(tmp_path):
    module = runtime_module()
    original, root = inputs(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(original)
    hard = tmp_path / "hard"
    os.link(original, hard)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo, 0o600)
    for p in [link, hard, fifo]:
        run = module.ShareRuntime("http://127.0.0.1:59575", p, "m", root, local_only=True, gateway_factory=FixtureGateway)
        with pytest.raises(Exception):
            run.start()
        assert not root.exists()
        run.close()
    assert original.read_text() == OPERATOR + "\n"


def test_runtime_existing_root_and_link_parent_not_overwritten(tmp_path):
    module = runtime_module()
    token, root = inputs(tmp_path)
    root.mkdir(mode=0o700)
    marker = root / "original"
    marker.write_bytes(b"KEEP")
    run = module.ShareRuntime("http://127.0.0.1:59575", token, "m", root, local_only=True, gateway_factory=FixtureGateway)
    with pytest.raises(Exception):
        run.start()
    run.close()
    assert marker.read_bytes() == b"KEEP"
    parent = tmp_path / "alias"
    parent.symlink_to(root, target_is_directory=True)
    run2 = module.ShareRuntime("http://127.0.0.1:59575", token, "m", parent / "new", local_only=True, gateway_factory=FixtureGateway)
    with pytest.raises(Exception):
        run2.start()
    assert not (root / "new").exists()
    run2.close()


@pytest.mark.parametrize("origin", ["https://127.0.0.1:8", "http://localhost:8", "http://127.0.0.1", "http://127.0.0.1:8/#token=x", "http://x:8", "http://u:p@127.0.0.1:8", "http://127.0.0.1:8/path", "http://127.0.0.1:8?q=1"])
def test_origin_exact_numeric_loopback_only(tmp_path, origin):
    module = runtime_module()
    token, root = inputs(tmp_path)
    with pytest.raises(Exception):
        module.ShareRuntime(origin, token, "m", root, local_only=True, gateway_factory=FixtureGateway)
    assert not root.exists()


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True])
def test_startup_timeout_pure_finite_positive(tmp_path, timeout):
    module = runtime_module()
    token, root = inputs(tmp_path)
    with pytest.raises(Exception):
        module.ShareRuntime("http://127.0.0.1:8", token, "m", root, startup_timeout=timeout)
    assert not root.exists()


def test_collision_rejected_no_private_link_and_retained_failure(tmp_path):
    seen = []
    def collision(*args, **kwargs):
        obj = FixtureGateway(*args, **kwargs)
        obj.token = OPERATOR
        seen.append(obj)
        return obj
    run, token, root = make(tmp_path, gateway_factory=collision)
    with pytest.raises(Exception):
        run.start()
    assert public_only(run.status())["state"] == "FAILED"
    assert not (root / "access.json").exists()
    run.close()
    assert seen[0].revoked and root.exists()
    assert token.read_text() == OPERATOR + "\n"


def test_root_replaced_during_owned_factory_never_writes_replacement(tmp_path):
    token, root = inputs(tmp_path)
    protected = tmp_path / "protected"
    protected.mkdir()
    marker = protected / "original"
    marker.write_bytes(b"ORIGINAL")
    retained = tmp_path / "retained-runtime"
    seen = []
    def factory(*args, **kwargs):
        obj = FixtureGateway(*args, **kwargs)
        seen.append(obj)
        os.rename(root, retained)
        os.rename(protected, root)
        return obj
    run = runtime_module().ShareRuntime("http://127.0.0.1:59575", token, "m", root,
                                       local_only=True, gateway_factory=factory)
    with pytest.raises(Exception):
        run.start()
    run.close()
    assert {p.name for p in root.iterdir()} == {"original"}
    assert (root / "original").read_bytes() == b"ORIGINAL"
    assert retained.exists() and seen[0].revoked
    assert token.read_text() == OPERATOR + "\n"


def test_owned_loop_escape_is_typed_and_no_raw_thread_traceback(tmp_path, capsys):
    class Escaping(FixtureGateway):
        def serve_forever(self, **kwargs):
            raise ValueError(OPERATOR + " /private/secret-path #token=" + SHARE)
    run, token, root = make(tmp_path, gateway_factory=Escaping)
    try:
        try:
            run.start()
        except Exception:
            pass
        assert await_state(run, {"FAILED"})["diagnostics"]
    finally:
        run.close()
    output = capsys.readouterr()
    assert "Traceback" not in output.err and OPERATOR not in output.err and SHARE not in output.err


def test_owned_literal_child_strict_argv_env_connected_and_cleanup(tmp_path, monkeypatch):
    exe = fixture_executable(tmp_path, "connected")
    monkeypatch.setenv("TUNNEL_TOKEN", OPERATOR)
    monkeypatch.setenv("HTTP_PROXY", "http://forbidden.invalid")
    run, token, root = make(tmp_path, local_only=False, cloudflared=exe, startup_timeout=2)
    try:
        public_only(run.start())
        meta = await_state(run, {"CONNECTED"})
        child = json.loads((root / "home" / "child-fixture.json").read_text())
        argv = child["argv"]
        assert argv[1] == "tunnel" and "--url" in argv and "--no-autoupdate" in argv
        assert argv[argv.index("--url") + 1] == meta["local_origin"]
        assert "--allowed-mail" not in argv and "--no-tls-verify" not in argv
        assert OPERATOR not in json.dumps(argv) and SHARE not in json.dumps(argv)
        assert child["pgid"] == child["pid"] and child["pgid"] != os.getpgrp()
        assert child["cwd"] == str(root / "home") and child["env"]["HOME"] == str(root / "home")
        assert "TUNNEL_TOKEN" not in child["env"] and "HTTP_PROXY" not in child["env"]
        assert argv[argv.index("--config") + 1].startswith(str(root / "home") + "/")
        assert meta["public_origin"] == "https://fixture-run.trycloudflare.com"
    finally:
        closed = public_only(run.close())
    assert closed["resources_closed"] and isinstance(closed["process_returncode"], int)
    with pytest.raises(ProcessLookupError):
        os.getpgid(child["pid"])


def test_url_assignment_is_not_connection_and_no_second_binding(tmp_path):
    exe = fixture_executable(tmp_path, "gated")
    seen = []
    def factory(*args, **kwargs):
        obj = FixtureGateway(*args, **kwargs)
        seen.append(obj)
        return obj
    run, token, root = make(tmp_path, local_only=False, cloudflared=exe, startup_timeout=2, gateway_factory=factory)
    try:
        meta = public_only(run.start())
        assert meta["state"] == "HOST_ASSIGNED"
        assert seen[0].assigned == ["https://fixture-run.trycloudflare.com"]
        (root / "home" / "connect.release").write_text("owned fixture")
        assert await_state(run, {"CONNECTED"})["state"] == "CONNECTED"
        assert seen[0].assigned == ["https://fixture-run.trycloudflare.com"]
        with pytest.raises(Exception):
            run.start()
    finally:
        run.close()


@pytest.mark.parametrize("mode", ["exit", "large", "wrong-host", "waiting"])
def test_failed_child_timeout_output_or_reassignment_explicit_no_respawn(tmp_path, mode):
    exe = fixture_executable(tmp_path, mode)
    run, token, root = make(tmp_path, local_only=False, cloudflared=exe, startup_timeout=.35)
    try:
        try:
            run.start()
        except Exception:
            pass
        meta = await_state(run, {"FAILED"})
        assert meta["diagnostics"] and root.exists()
        assert (root / "runtime.log").stat().st_size <= 1048576
        for p in root.rglob("*"):
            if p.is_file() and p.name != "access.json":
                assert OPERATOR.encode() not in p.read_bytes() and SHARE.encode() not in p.read_bytes()
        with pytest.raises(Exception):
            run.start()
    finally:
        closed = run.close()
    assert closed["resources_closed"]
    assert token.read_text() == OPERATOR + "\n"


def test_real_gateway_local_only_one_upstream_capture_and_original_survives(tmp_path):
    module = runtime_module()
    capture = {"id": "m", "snapshot": {"phase": "COMPLETED", "tasks": []},
               "controller": {"running": False}, "controls": [], "engineering_result": {"schema": "sisyfus.lead_console.engineering_result_sidecar.v1", "mission_id": "m", "status": "REJECTED", "result": None, "error": {"code": "SNAPSHOT_REQUIRED_FIELD"}}}
    calls = []
    class Upstream(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.path, self.headers.get("Authorization"), self.headers.get("X-Sisyfus-Engineering")))
            body = json.dumps(capture).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    token, root = inputs(tmp_path)
    run = module.ShareRuntime("http://127.0.0.1:" + str(server.server_port), token, "m", root, local_only=True)
    try:
        meta = run.start()
        private = json.loads(Path(meta["access_file"]).read_text())["private_url"]
        bearer = parse_qs(urlsplit(private).fragment)["token"][0]
        origin = urlsplit(meta["local_origin"])
        conn = HTTPConnection(origin.hostname, origin.port, timeout=2)
        try:
            conn.request("GET", "/api/share/snapshot", headers={"Authorization": "Bearer " + bearer})
            response = conn.getresponse()
            assert response.status == 200
            body = json.loads(response.read())
        finally:
            conn.close()
        assert body["capture"] == capture
        expected = hashlib.sha256(json.dumps(capture, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        assert body["capture_hash"] == expected
        assert len(calls) == 1 and calls[0][0] == "/api/snapshot?mission_id=m"
        assert calls[0][1] == "Bearer " + OPERATOR
        run.close()
        assert thread.is_alive()
    finally:
        run.close()
        server.shutdown()
        thread.join(2)
        server.server_close()
