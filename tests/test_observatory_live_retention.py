"""Frozen public-clear acceptance; fake Trash retains every fixture by rename."""
from __future__ import annotations

import ast
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from sisyfus import cli
from sisyfus.research_v2 import live


FAKE_TRASH = '''#!{python}
import hashlib, json, os, sys
from pathlib import Path
base = Path(__file__).parent.resolve()
source = Path(sys.argv[1])
assert len(sys.argv) == 2 and source.is_absolute()
assert source.parent == base / "-project with spaces" / ".sisyfus"
assert source.name.startswith(".observatory-retire-")
control = json.loads((base / "control.json").read_text())
entry = {{"argv": sys.argv, "directory": [source.stat().st_dev, source.stat().st_ino],
         "state": [source.joinpath("observatory.json").stat().st_dev,
                   source.joinpath("observatory.json").stat().st_ino],
         "sha256": hashlib.sha256(source.joinpath("observatory.json").read_bytes()).hexdigest()}}
with (base / "calls.jsonl").open("a") as log:
    log.write(json.dumps(entry) + "\\n")
if control["mode"] == "fail":
    print("PRIVATE-STDERR-STATE-BODY", file=sys.stderr)
    sys.exit(9)
if control["mode"] == "noop":
    sys.exit(0)
destination = base / "fake-trash" / source.name
assert destination.parent.is_dir() and not destination.exists()
os.rename(source, destination)
'''


def identity(path: Path) -> tuple[int, int]:
    item = path.stat(follow_symlinks=False)
    return item.st_dev, item.st_ino


def publish(path: Path, data: bytes) -> None:
    """Cooperating writer protocol without the unchanged writer's cleanup call."""
    staged = path.parent / ("writer-" + os.urandom(8).hex())
    with staged.open("xb") as handle:
        handle.write(data)
    os.replace(staged, path)


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "-project with spaces"
    root.mkdir()
    (root / ".sisyfus").mkdir()
    sink = tmp_path / "fake-trash"
    sink.mkdir()
    binary = tmp_path / "fake trash executable"
    binary.write_text(FAKE_TRASH.format(python=sys.executable))
    binary.chmod(0o700)
    control = tmp_path / "control.json"
    control.write_text(json.dumps({"mode": "move"}))
    log = tmp_path / "calls.jsonl"
    path = root / ".sisyfus" / "observatory.json"
    state = {"root": str(root.resolve()), "port": 61234, "pid": os.getpid(),
             "research_id": "retention-fixture", "schema_version": "sisyfus.observatory.v2"}
    calls = []
    real_run = subprocess.run

    def run(argv, **kwargs):
        assert len(argv) == 2 and argv[0] == str(binary)
        resource = Path(argv[1])
        assert resource.is_absolute() and resource.parent == path.parent
        assert resource.name.startswith(".observatory-retire-")
        assert kwargs == {"stdin": subprocess.DEVNULL, "capture_output": True,
                          "check": False, "timeout": 30}
        assert resource.stat().st_mode & 0o777 == 0o700
        assert resource.stat().st_uid == os.geteuid()
        assert resource.stat().st_dev == path.parent.stat().st_dev
        calls.append(list(argv))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(live, "_TRASH_BIN", str(binary), raising=False)
    monkeypatch.setattr(live.subprocess, "run", run)

    def seed(value=None, raw=None):
        data = raw if raw is not None else json.dumps(state if value is None else value).encode()
        with path.open("xb") as handle:
            handle.write(data)
        return data

    def mode(value):
        control.write_text(json.dumps({"mode": value}))

    def stages():
        return list(path.parent.glob(".observatory-retire-*"))

    def receipts():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    (tmp_path / "case-manifest.json").write_text(json.dumps({"root": str(root), "sink": str(sink),
        "binary": str(binary), "retained": True}, indent=2))
    return SimpleNamespace(root=root, path=path, state=state, seed=seed, mode=mode,
                           stages=stages, receipts=receipts, calls=calls, sink=sink,
                           binary=binary, base=tmp_path, monkeypatch=monkeypatch)


@pytest.fixture(autouse=True)
def deletion_tripwire(monkeypatch: pytest.MonkeyPatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Permanent deletion or implicit parent cleanup attempted")
    for owner, name in [(Path, "unlink"), (os, "unlink"), (os, "remove"),
                        (os, "rmdir"), (os, "renames"), (shutil, "rmtree")]:
        monkeypatch.setattr(owner, name, forbidden)


@pytest.fixture(autouse=True)
def descriptor_tripwire(monkeypatch: pytest.MonkeyPatch):
    real_open, real_close = os.open, os.close
    held = set()

    def tracked_open(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        held.add(fd)
        return fd

    def tracked_close(fd):
        real_close(fd)
        held.discard(fd)

    support = set(os.supports_dir_fd)
    if real_open in support:
        support.add(tracked_open)
    monkeypatch.setattr(os, "supports_dir_fd", support)
    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "close", tracked_close)
    yield held
    assert not held, "Clear leaked an explicitly opened descriptor"


def retained(h, reason, path=None, *, error_type=None, returncode=None):
    with pytest.raises(RuntimeError) as caught:
        live.clear_live_state(h.root, pid=os.getpid())
    error = caught.value
    assert type(error).__name__ == "LiveStateRetained"
    assert error.reason == reason
    assert error.path == (h.path if path is None else path)
    assert set(error.detail) == {"type", "returncode"}
    assert error.detail["returncode"] == returncode
    if error_type is not None:
        assert error.detail["type"] == error_type
    assert "PRIVATE-STDERR-STATE-BODY" not in str(error)
    assert "PRIVATE-STDERR-STATE-BODY" not in repr(error.detail)
    return error


def test_signature_unchanged():
    signature = inspect.signature(live.clear_live_state)
    assert list(signature.parameters) == ["root", "pid"]
    assert signature.parameters["pid"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["pid"].default is None
    assert signature.return_annotation in (None, "None")


@pytest.mark.parametrize("scoped", [True, False])
def test_owned_state_retired_exact_bytes_identity_resource_and_argv(harness, scoped):
    h = harness
    data = h.seed()
    pin = identity(h.path)
    extras = {}
    for name in ["observatory-open.json", "observatory.html", "observatory.log", "unrelated.json"]:
        item = h.path.parent / name
        item.write_bytes(name.encode())
        extras[item] = (item.read_bytes(), identity(item))
    result = live.clear_live_state(h.root, **({"pid": os.getpid()} if scoped else {}))
    assert result is None and not h.path.exists() and not h.stages()
    assert len(h.calls) == len(h.receipts()) == 1
    receipt = h.receipts()[0]
    resource = Path(h.calls[0][1])
    assert receipt["argv"] == h.calls[0]
    moved = h.sink / resource.name
    assert moved.joinpath("observatory.json").read_bytes() == data
    assert identity(moved / "observatory.json") == pin == tuple(receipt["state"])
    assert identity(moved) == tuple(receipt["directory"])
    assert all((p.read_bytes(), identity(p)) == expected for p, expected in extras.items())


def test_foreign_owner_silent_unchanged(harness):
    h = harness
    data = h.seed()
    pin = identity(h.path)
    assert live.clear_live_state(h.root, pid=os.getpid() + 1) is None
    assert (h.path.read_bytes(), identity(h.path)) == (data, pin)
    assert not h.calls and not h.stages()


@pytest.mark.parametrize("missing", ["root", "parent", "state"])
def test_missing_resource_benign(harness, missing):
    h = harness
    root = h.base / "missing-root" if missing == "root" else h.root
    if missing == "parent":
        os.rename(h.path.parent, h.root / "retained-parent")
    assert live.clear_live_state(root, pid=os.getpid()) is None
    assert not h.calls


@pytest.mark.parametrize("invalid", ["json", "utf8", "list", "port", "root", "no-root",
    "no-pid", "str-pid", "bool-pid", "oversize", "private-body"])
def test_unadmitted_preserved_without_stage(harness, invalid):
    h = harness
    state = dict(h.state)
    if invalid == "json": raw = b"{"
    elif invalid == "utf8": raw = b"\xff"
    elif invalid == "list": raw = b"[]"
    elif invalid == "oversize": raw = b" " * 65537
    elif invalid == "private-body": raw = b"PRIVATE-STDERR-STATE-BODY"
    else:
        if invalid == "port": state["port"] = 0
        elif invalid == "root": state["root"] = str(h.base / "copied-source")
        elif invalid == "no-root": state.pop("root")
        elif invalid == "no-pid": state.pop("pid")
        elif invalid == "str-pid": state["pid"] = "x"
        elif invalid == "bool-pid": state["pid"] = True
        raw = json.dumps(state).encode()
    h.seed(raw=raw)
    pin = identity(h.path)
    retained(h, "state_unadmitted")
    assert (h.path.read_bytes(), identity(h.path)) == (raw, pin)
    assert not h.calls and not h.stages()


@pytest.mark.parametrize("shape", ["symlink", "dangling", "parent-symlink", "hardlink", "fifo", "directory"])
def test_alias_and_shape_fail_closed(harness, shape):
    h = harness
    if shape in {"symlink", "dangling"}:
        target = h.base / "target"
        if shape == "symlink": target.write_bytes(b"referent")
        h.path.symlink_to(target)
        expected_reason = "state_symlink"
    elif shape == "parent-symlink":
        target = h.root / "retained-parent"
        os.rename(h.path.parent, target)
        h.path.parent.symlink_to(target, target_is_directory=True)
        expected_reason = "parent_alias"
    elif shape == "hardlink":
        h.seed()
        target = h.base / "other-link"
        os.link(h.path, target)
        expected_reason = "state_unadmitted"
    elif shape == "fifo":
        os.mkfifo(h.path)
        expected_reason = "state_unadmitted"
    else:
        h.path.mkdir()
        expected_reason = "state_unadmitted"
    pin = identity(h.path.parent if shape == "parent-symlink" else h.path)
    retained(h, expected_reason)
    assert identity(h.path.parent if shape == "parent-symlink" else h.path) == pin
    if shape == "symlink": assert target.read_bytes() == b"referent"
    if shape == "hardlink": assert identity(target) == pin
    assert not h.calls and not h.stages()


def test_trash_missing_before_stage(harness):
    h = harness
    data = h.seed()
    h.monkeypatch.setattr(live, "_TRASH_BIN", str(h.base / "missing-binary"))
    retained(h, "trash_missing")
    assert h.path.read_bytes() == data and not h.calls and not h.stages()


def test_no_dir_fd_before_open(harness, descriptor_tripwire):
    h = harness
    data = h.seed()
    h.monkeypatch.setattr(os, "supports_dir_fd", set())
    retained(h, "no_dir_fd")
    assert h.path.read_bytes() == data and not h.calls and not descriptor_tripwire


@pytest.mark.parametrize("mode,code", [("fail", 9), ("noop", 0)])
def test_trash_failure_keeps_stage_and_sanitizes_diagnostics(harness, mode, code):
    h = harness
    data = h.seed()
    pin = identity(h.path)
    h.mode(mode)
    with pytest.raises(RuntimeError) as caught:
        live.clear_live_state(h.root, pid=os.getpid())
    error = caught.value
    assert type(error).__name__ == "LiveStateRetained"
    assert error.reason == "trash_failed" and error.detail == {"type": "TrashResult", "returncode": code}
    assert error.path in h.stages() and not h.path.exists()
    assert (error.path / "observatory.json").read_bytes() == data
    assert identity(error.path / "observatory.json") == pin
    assert len(h.calls) == 1
    assert "PRIVATE-STDERR-STATE-BODY" not in str(error) + repr(error.detail)


@pytest.mark.parametrize("failure", ["timeout", "missing-exec", "permission"])
def test_exec_failure_retains_stage_fixed_type(harness, failure):
    h = harness
    data = h.seed()
    def broken(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args[0], 30, stderr=b"PRIVATE-STDERR-STATE-BODY")
        if failure == "missing-exec": raise FileNotFoundError("PRIVATE-STDERR-STATE-BODY")
        raise PermissionError("PRIVATE-STDERR-STATE-BODY")
    h.monkeypatch.setattr(live.subprocess, "run", broken)
    with pytest.raises(RuntimeError) as caught:
        live.clear_live_state(h.root)
    error = caught.value
    assert type(error).__name__ == "LiveStateRetained" and error.reason == "trash_failed"
    expected = "TimeoutExpired" if failure == "timeout" else "OSError"
    assert error.detail == {"type": expected, "returncode": None}
    assert error.path in h.stages() and (error.path / "observatory.json").read_bytes() == data
    assert "PRIVATE-STDERR-STATE-BODY" not in str(error) + repr(error.detail)
    assert error.__suppress_context__


def test_swap_at_rename_detected_retained_not_restored_or_trashed(harness):
    h = harness
    original = h.seed()
    original_pin = identity(h.path)
    new = dict(h.state, pid=os.getpid() + 1)
    new_bytes = json.dumps(new).encode()
    later_bytes = json.dumps(dict(h.state, pid=os.getpid() + 2)).encode()
    real_stage = live._stage_state
    captures = {}
    def racing(dfd, stfd):
        os.link(h.path, h.base / "retained-original-inode")
        publish(h.path, new_bytes)
        captures["displaced"] = identity(h.path)
        real_stage(dfd, stfd)
        publish(h.path, later_bytes)
        captures["later"] = identity(h.path)
    h.monkeypatch.setattr(live, "_stage_state", racing)
    with pytest.raises(RuntimeError) as caught:
        live.clear_live_state(h.root, pid=os.getpid())
    error = caught.value
    assert type(error).__name__ == "LiveStateRetained" and error.reason == "staged_mismatch"
    assert (error.path / "observatory.json").read_bytes() == new_bytes
    assert identity(error.path / "observatory.json") == captures["displaced"]
    assert (h.path.read_bytes(), identity(h.path)) == (later_bytes, captures["later"])
    assert (h.base / "retained-original-inode").read_bytes() == original
    assert identity(h.base / "retained-original-inode") == original_pin
    assert not h.calls


def test_new_state_after_rename_survives_success(harness):
    h = harness
    old = h.seed()
    new = json.dumps(dict(h.state, pid=os.getpid() + 1)).encode()
    real_stage = live._stage_state
    def publish_after(dfd, stfd):
        real_stage(dfd, stfd)
        publish(h.path, new)
    h.monkeypatch.setattr(live, "_stage_state", publish_after)
    assert live.clear_live_state(h.root, pid=os.getpid()) is None
    assert h.path.read_bytes() == new and len(h.calls) == 1
    assert (h.sink / Path(h.calls[0][1]).name / "observatory.json").read_bytes() == old


def test_pre_rename_inode_change_fenced(harness):
    h = harness
    old = h.seed()
    new = json.dumps(dict(h.state, pid=os.getpid() + 1)).encode()
    real_stat = os.stat
    seen = False
    def racing_stat(path, *args, **kwargs):
        nonlocal seen
        if path == "observatory.json" and kwargs.get("dir_fd") is not None and not seen:
            seen = True
            os.link(h.path, h.base / "original-pin")
            publish(h.path, new)
        return real_stat(path, *args, **kwargs)
    support = set(os.supports_dir_fd) | {racing_stat}
    h.monkeypatch.setattr(os, "supports_dir_fd", support)
    h.monkeypatch.setattr(os, "stat", racing_stat)
    retained(h, "state_changed")
    assert h.path.read_bytes() == new and (h.base / "original-pin").read_bytes() == old
    assert not h.calls and not h.stages()


def test_same_inode_staged_bytes_change_detected(harness):
    h = harness
    h.seed()
    new = json.dumps(dict(h.state, pid=os.getpid() + 1)).encode()
    real_stage = live._stage_state
    def mutate(dfd, stfd):
        real_stage(dfd, stfd)
        stage = h.stages()[0] / "observatory.json"
        stage.write_bytes(new)
    h.monkeypatch.setattr(live, "_stage_state", mutate)
    with pytest.raises(RuntimeError) as caught:
        live.clear_live_state(h.root)
    error = caught.value
    assert type(error).__name__ == "LiveStateRetained" and error.reason == "staged_mismatch"
    assert (error.path / "observatory.json").read_bytes() == new and not h.calls


def test_parent_path_retarget_after_stage_retained(harness):
    h = harness
    old = h.seed()
    other = h.root / "original-parent"
    real_stage = live._stage_state
    def retarget(dfd, stfd):
        real_stage(dfd, stfd)
        os.rename(h.path.parent, other)
        h.path.parent.mkdir()
        h.path.write_bytes(b"replacement-owner")
    h.monkeypatch.setattr(live, "_stage_state", retarget)
    with pytest.raises(RuntimeError) as caught:
        live.clear_live_state(h.root)
    assert type(caught.value).__name__ == "LiveStateRetained"
    assert caught.value.reason == "staged_mismatch" and not h.calls
    assert h.path.read_bytes() == b"replacement-owner"
    stages = list(other.glob(".observatory-retire-*"))
    assert len(stages) == 1 and (stages[0] / "observatory.json").read_bytes() == old


def test_root_identity_mismatch_before_admission(harness):
    h = harness
    old = h.seed()
    real_stat = os.stat
    def mismatched(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if path == h.root and kwargs.get("follow_symlinks") is False:
            return SimpleNamespace(st_dev=result.st_dev, st_ino=result.st_ino + 1)
        return result
    h.monkeypatch.setattr(os, "supports_dir_fd", set(os.supports_dir_fd) | {mismatched})
    h.monkeypatch.setattr(os, "stat", mismatched)
    retained(h, "root_alias")
    assert h.path.read_bytes() == old and not h.calls and not h.stages()


def test_shutdown_propagates_retention_and_cli_reports_exit_one(harness, monkeypatch, capsys):
    h = harness
    h.mode("fail")
    class Server:
        server_address = ("127.0.0.1", 61234)
        def serve_forever(self): raise KeyboardInterrupt
        def server_close(self): pass
    attempts = []
    def serve_report(**kwargs):
        attempts.append(kwargs["port"])
        if len(attempts) % 2 == 1: raise OSError("fixture bind contention")
        return Server(), "http://127.0.0.1:61234/index.html"
    engine = SimpleNamespace(workspace=SimpleNamespace(root=h.root, research_id="fixture"),
                             serve_report=serve_report, sync=lambda **kwargs: None)
    monkeypatch.setattr(cli, "_research_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(cli, "resolve_serve_port", lambda *args: 8787)
    monkeypatch.setattr(cli, "live_observatory_url", lambda *args: None)
    monkeypatch.setattr(cli, "write_live_state", lambda *args, **kwargs: h.seed())
    args = SimpleNamespace(port=None, host="127.0.0.1", open=False, verbose=False)
    with pytest.raises(RuntimeError) as caught:
        cli.cmd_research_serve(args)
    assert type(caught.value).__name__ == "LiveStateRetained"
    assert caught.value.reason == "trash_failed" and attempts == [8787, 0]
    monkeypatch.delenv("SISYFUS_DEBUG", raising=False)
    assert cli.main(["research", "serve", "latest", "--root", str(h.root)]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert error["type"] == "LiveStateRetained" and "trash_failed" in error["message"]
    assert "PRIVATE-STDERR-STATE-BODY" not in error["message"]


def test_clear_region_and_fake_have_no_permanent_deletion_calls():
    tree = ast.parse(inspect.getsource(live))
    names = {"clear_live_state", "_stage_state"}
    regions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
               and (node.name in names or node.name.startswith("_retire_"))]
    assert any(getattr(node, "name", None) == "_stage_state" for node in regions)
    forbidden = {"unlink", "remove", "rmdir", "rmtree", "renames"}
    for region in regions + [ast.parse(FAKE_TRASH.format(python=sys.executable))]:
        for node in ast.walk(region):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                assert name not in forbidden
