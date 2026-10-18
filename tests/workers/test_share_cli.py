"""Frozen share CLI: no IO on help/parse, public Runtime-only lifecycle and owned close."""
import importlib
import json
import sys

import pytest

OPERATOR = "operator-fixture-56c2fbb1de694fe79b223a1805db453a"
SHARE = "share-fixture-a89ce329bd19413aa4841a015560c12c"


def cli():
    return importlib.import_module("sisyfus.workers.share_cli")


def args(tmp_path):
    return ["--console-origin", "http://127.0.0.1:59575",
            "--operator-token-file", str(tmp_path / "not-read.token"),
            "--mission-id", "mission-fixture", "--runtime-directory", str(tmp_path / "new")]


def metadata(state):
    return {"schema": "sisyfus.share.runtime.v1", "state": state,
            "local_origin": "http://127.0.0.1:1234", "public_origin": None,
            "access_file": "/private/tmp/share-fixture/access.json",
            "permissions": {"messages": False, "controls": False},
            "diagnostics": [], "resources_closed": state == "CLOSED", "process_returncode": None}


class FixtureRuntime:
    def __init__(self, *a, **kw):
        self.arguments = a, kw
        self.closed = 0
    def start(self):
        return metadata("LOCAL_ONLY")
    def status(self):
        return metadata("CLOSED")
    def close(self):
        self.closed += 1
        return metadata("CLOSED")


@pytest.mark.parametrize("argv", [["--help"], ["-h"]])
def test_help_zero_factory_or_default_runtime_import(tmp_path, capsys, monkeypatch, argv):
    module = cli()
    calls = []
    def forbidden(*a, **kw):
        calls.append((a, kw))
        raise AssertionError("factory must not run")
    original = importlib.import_module
    monkeypatch.setattr(importlib, "import_module", lambda name, *a, **kw: (_ for _ in ()).throw(AssertionError(name)) if name.endswith("share_runtime") else original(name, *a, **kw))
    assert module.main(argv, runtime_factory=forbidden) == 0
    assert not calls
    assert "--console-origin" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("tail", [
    [], ["--unknown", OPERATOR], ["--console-origin", "http://127.0.0.1:8/#token=" + SHARE],
    ["--secret", OPERATOR], ["--startup-timeout", "nan"], ["--startup-timeout", "inf"],
    ["--startup-timeout", "0"], ["--startup-timeout", "-1"],
    ["--runtime-directory", "relative"], ["--console-origin", "https://127.0.0.1:8"],
    ["--console-origin", "http://localhost:8"], ["--mission-id", "../escape"],
    ["--operator-token-file"], ["--allow-messages=oops"],
])
def test_parse_error_one_before_factory_no_raw_echo(tmp_path, capsys, tail):
    module = cli()
    calls = []
    def forbidden(*a, **kw):
        calls.append(1)
        raise AssertionError
    argv = [] if not tail else args(tmp_path) + tail
    assert module.main(argv, runtime_factory=forbidden) == 1
    assert not calls and not list(tmp_path.iterdir())
    output = capsys.readouterr()
    error = json.loads(output.err)
    assert error["stage"] == "parse" and error["status"] == "ERROR"
    assert OPERATOR not in output.err and SHARE not in output.err and "../escape" not in output.err


def test_normal_public_methods_exact_arguments_and_metadata_no_link(tmp_path, capsys):
    module = cli()
    made = []
    def factory(*a, **kw):
        obj = FixtureRuntime(*a, **kw)
        made.append(obj)
        return obj
    code = module.main(args(tmp_path) + ["--local-only", "--allow-messages", "--report", str(tmp_path / "report.html"), "--cloudflared", "/fixture/exe", "--startup-timeout", "1.5"], runtime_factory=factory, sleep=lambda x: None)
    assert code == 0 and len(made) == 1 and made[0].closed == 1
    a, kw = made[0].arguments
    assert tuple(map(str, a)) == ("http://127.0.0.1:59575", str(tmp_path / "not-read.token"), "mission-fixture", str(tmp_path / "new"))
    assert kw["local_only"] and kw["allow_messages"] and kw["startup_timeout"] == 1.5
    assert str(kw["report_path"]) == str(tmp_path / "report.html") and str(kw["cloudflared"]) == "/fixture/exe"
    output = capsys.readouterr()
    rows = [json.loads(s) for s in output.out.splitlines()]
    assert rows[0]["state"] == "LOCAL_ONLY" and rows[-1]["state"] == "CLOSED"
    assert all("#token" not in json.dumps(x) and "token" not in x for x in rows)
    assert not output.err and not list(tmp_path.iterdir())


@pytest.mark.parametrize("stage", ["construct", "start", "status", "sleep"])
@pytest.mark.parametrize("kind,exit_code", [(ValueError, 1), (KeyboardInterrupt, 130)])
def test_all_failure_boundaries_explicit_and_only_owned_close(tmp_path, capsys, stage, kind, exit_code):
    module = cli()
    made = []
    def fail(*_):
        raise kind(OPERATOR + " /private/secret-path #token=" + SHARE)
    class Runtime(FixtureRuntime):
        def start(self):
            if stage == "start":
                fail()
            return metadata("LOCAL_ONLY")
        def status(self):
            if stage == "status":
                fail()
            return metadata("LOCAL_ONLY" if stage == "sleep" else "CLOSED")
    def factory(*a, **kw):
        if stage == "construct":
            fail()
        obj = Runtime(*a, **kw)
        made.append(obj)
        return obj
    assert module.main(args(tmp_path), runtime_factory=factory, sleep=fail if stage == "sleep" else lambda x: None) == exit_code
    assert len(made) == (0 if stage == "construct" else 1)
    assert not made or made[0].closed == 1
    output = capsys.readouterr()
    assert OPERATOR not in output.err + output.out and SHARE not in output.err + output.out
    assert "/private/secret-path" not in output.err + output.out
    errors = [json.loads(s) for s in output.err.splitlines()]
    assert errors[0]["stage"] == stage and errors[0]["error_type"] == kind.__name__


def test_primary_and_cleanup_failures_both_retained_redacted(tmp_path, capsys):
    module = cli()
    class Runtime(FixtureRuntime):
        def start(self):
            raise ValueError(OPERATOR)
        def close(self):
            raise OSError(SHARE)
    assert module.main(args(tmp_path), runtime_factory=Runtime) == 1
    output = capsys.readouterr()
    records = [json.loads(s) for s in output.err.splitlines()]
    assert [(x["stage"], x["error_type"]) for x in records] == [("start", "ValueError"), ("close", "OSError")]
    assert OPERATOR not in output.err and SHARE not in output.err


def test_failed_status_returns_one_and_closes(tmp_path, capsys):
    module = cli()
    made = []
    class Runtime(FixtureRuntime):
        def status(self):
            return metadata("FAILED")
    def factory(*a, **kw):
        obj = Runtime(*a, **kw)
        made.append(obj)
        return obj
    assert module.main(args(tmp_path), runtime_factory=factory, sleep=lambda x: None) == 1
    assert made[0].closed == 1
    assert "FAILED" in capsys.readouterr().out


def test_result_whitelist_discards_extra_secret_keys(tmp_path, capsys):
    module = cli()
    class Runtime(FixtureRuntime):
        def start(self):
            x = metadata("LOCAL_ONLY")
            x["token"] = SHARE
            x["private_url"] = "https://fixture.trycloudflare.com/#token=" + SHARE
            return x
    assert module.main(args(tmp_path), runtime_factory=Runtime, sleep=lambda x: None) == 0
    output = capsys.readouterr()
    assert SHARE not in output.out + output.err and "#token=" not in output.out


def test_lead_share_lazy_dispatch_and_discoverable_help(tmp_path, capsys, monkeypatch):
    module = cli()
    lead = importlib.import_module("sisyfus.workers.lead_cli")
    calls = []
    monkeypatch.setattr(module, "main", lambda argv: calls.append(argv) or 23)
    monkeypatch.setattr(lead, "MissionHub", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no Hub")))
    assert lead.main(["share", "--help"]) == 23 and calls == [["--help"]]
    with pytest.raises(SystemExit) as exc:
        lead.main(["--help"])
    assert exc.value.code == 0 and "share" in capsys.readouterr().out

