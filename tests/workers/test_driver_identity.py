"""Native protocol fixtures only: these tests do not attest a live provider run."""
from __future__ import annotations

import copy
from subprocess import TimeoutExpired
from types import SimpleNamespace

import pytest

from sisyfus.workers import claude_code, codex
from sisyfus.workers.protocol import Receipt, Request
from sisyfus.workers.transport import ProtocolError


REQUESTED = "requested-role-model"
ACTUAL = "native-execution-model"
SESSION = "native-session"
TURN = "native-turn"
TOKENS = {"input_tokens": 7, "output_tokens": 11}


class ScriptedProcess:
    """Exercise the real adapters, with no shell, credentials or provider calls."""

    def __init__(self, messages, *, exit_code=0, wait_error=None):
        self.messages = iter(copy.deepcopy(messages))
        self.exit_code = exit_code
        self.wait_error = wait_error
        self.process = SimpleNamespace(pid=123, poll=lambda: self.exit_code)
        self.sent = []
        self.closed = False

    def send_bytes(self, value, *, close=False):
        self.sent.append((value, close))

    def send(self, value):
        self.sent.append(copy.deepcopy(value))

    def receive(self):
        try:
            value = next(self.messages)
        except StopIteration:
            raise EOFError("fixture stream ended")
        if isinstance(value, Exception):
            raise value
        return value

    def wait(self):
        if self.wait_error:
            raise self.wait_error
        return self.exit_code

    def close(self):
        self.closed = True


def launch(monkeypatch, tmp_path, kind, messages, *, controls=lambda: [],
           exit_code=0, wait_error=None, **request_kwargs):
    module, cls = (claude_code, claude_code.ClaudeCodeDriver) if kind == "claude" else (codex, codex.CodexDriver)
    proc = ScriptedProcess(messages, exit_code=exit_code, wait_error=wait_error)
    calls, events = [], []

    def create(argv, **kwargs):
        calls.append((argv, kwargs))
        return proc

    monkeypatch.setattr(module, "Process", create)
    request = Request("task", "inspect the project", str(tmp_path), REQUESTED, **request_kwargs)
    result = cls().run(request, lambda kind, data: events.append((kind, data)), controls)
    assert proc.closed
    assert result.requested_model == REQUESTED
    assert result.as_dict()["actual_model"] == result.actual_model
    return result, proc, calls[0], events


def assistant(model=ACTUAL, *, stream=False, parent=None):
    message = {"id": "assistant-message", "model": model, "usage": TOKENS}
    event = {"type": "stream_event", "event": {"type": "message_start", "message": message}} if stream else {
        "type": "assistant", "message": message}
    return {**event, "session_id": SESSION, "parent_tool_use_id": parent}


def claude_messages(*events, error=False):
    return [{"type": "system", "subtype": "init", "session_id": SESSION, "model": REQUESTED},
            *events, {"type": "result", "session_id": SESSION, "subtype": "error_during_execution" if error else "success",
                      "is_error": error, "result": "native result", "usage": TOKENS,
                      "modelUsage": {ACTUAL: {"inputTokens": 7, "outputTokens": 11}},
                      "total_cost_usd": .01, "model": "contradictory-config-echo"}]


def codex_messages(*events, status="completed"):
    return [{"id": 1, "result": {}},
            {"id": 2, "result": {"thread": {"id": SESSION}, "model": REQUESTED}},
            {"id": 3, "result": {"turn": {"id": TURN, "status": "inProgress", "model": REQUESTED}}},
            {"method": "thread/tokenUsage/updated", "params": {"threadId": SESSION, "turnId": TURN,
                "tokenUsage": {"total": TOKENS, "last": TOKENS}}},
            *events,
            {"method": "turn/completed", "params": {"threadId": SESSION,
                "turn": {"id": TURN, "status": status, "error": {"message": "native failure"} if status == "failed" else None}}}]


def test_receipt_fields_preserve_positional_compatibility():
    old = Receipt("ERROR", SESSION, TURN, 9, "output", TOKENS, "failure")
    assert old.as_dict() == {"status": "ERROR", "session_id": SESSION, "turn_id": TURN,
        "exit_code": 9, "output": "output", "usage": TOKENS, "error": "failure",
        "requested_model": None, "actual_model": None}


@pytest.mark.parametrize("limit", [None, 1, 8, 100])
def test_request_supports_optional_cap(tmp_path, limit):
    request = Request("task", "work", str(tmp_path), REQUESTED, max_turns=limit)
    assert request.max_turns == limit
    assert request.mode == "read-only"
    assert request.timeout == 300 and request.max_output_bytes == 8_000_000


@pytest.mark.parametrize("limit", [0, 101, -1, True, False, 1.0, "8"])
def test_request_rejects_invalid_turn_caps(tmp_path, limit):
    with pytest.raises(ValueError):
        Request("task", "work", str(tmp_path), REQUESTED, max_turns=limit)


@pytest.mark.parametrize("kwargs", [{"timeout": None}, {"timeout": 0}, {"timeout": float("inf")},
    {"max_output_bytes": None}, {"max_output_bytes": True}, {"max_output_bytes": 1023}])
def test_null_turn_cap_keeps_single_call_bounds(tmp_path, kwargs):
    with pytest.raises(ValueError):
        Request("task", "work", str(tmp_path), REQUESTED, max_turns=None, **kwargs)


@pytest.mark.parametrize("mode,tools", [("read-only", "Read,Glob,Grep"),
                                      ("workspace-write", "Read,Glob,Grep,Write,Edit")])
@pytest.mark.parametrize("limit", [None, 1, 8, 100])
def test_claude_launch_keeps_settings_and_restricted_role(monkeypatch, tmp_path, mode, tools, limit):
    result, _, (argv, kwargs), _ = launch(monkeypatch, tmp_path, "claude", claude_messages(),
        mode=mode, max_turns=limit, timeout=12, max_output_bytes=4096, session_id=SESSION)
    assert result.status == "COMPLETED"
    for flag, value in [("--setting-sources", "user,project,local"), ("--permission-mode", "dontAsk"),
        ("--tools", tools), ("--allowedTools", tools), ("--mcp-config", '{"mcpServers":{}}'),
        ("--resume", SESSION), ("--model", REQUESTED)]:
        assert argv[argv.index(flag) + 1] == value
    assert "--strict-mcp-config" in argv
    assert not {"--restricted", "--safe-mode", "--dangerously-skip-permissions"}.intersection(argv)
    if limit is None:
        assert "--max-turns" not in argv
    else:
        assert argv[argv.index("--max-turns") + 1] == str(limit)
    assert kwargs["timeout"] == 12 and kwargs["max_bytes"] == 4096


@pytest.mark.parametrize("stream", [False, True])
def test_claude_attests_returned_execution_not_requested_model(monkeypatch, tmp_path, stream):
    result, _, _, events = launch(monkeypatch, tmp_path, "claude", claude_messages(assistant(stream=stream)))
    assert result.status == "COMPLETED" and result.actual_model == ACTUAL
    assert result.session_id == SESSION and result.turn_id is None
    assert result.usage["tokens"] == TOKENS and result.usage["last_message_tokens"] == TOKENS
    assert result.usage["model_usage"] == {ACTUAL: {"inputTokens": 7, "outputTokens": 11}}
    assert result.usage["reported_total_cost_usd"] == .01
    assert next(data for kind, data in events if kind == "model_identity")["telemetry"] == "reported"


@pytest.mark.parametrize("event", [None, assistant(None), assistant("<synthetic>"),
                                  assistant(parent="child-tool"), assistant(stream=True, parent="child-tool")])
def test_claude_missing_telemetry_ignores_echoes_and_session_model_usage(monkeypatch, tmp_path, event):
    result, _, _, events = launch(monkeypatch, tmp_path, "claude", claude_messages(*([] if event is None else [event])))
    assert result.status == "COMPLETED" and result.actual_model is None
    assert result.session_id == SESSION and result.usage["tokens"] == TOKENS
    assert next(data for kind, data in events if kind == "model_identity")["telemetry"] == "missing"


def test_claude_contradictory_execution_models_are_not_silently_overwritten(monkeypatch, tmp_path):
    result, _, _, events = launch(monkeypatch, tmp_path, "claude",
        claude_messages(assistant(stream=True), assistant("another-execution-model")))
    assert result.status == "COMPLETED" and result.actual_model is None
    assert next(data for kind, data in events if kind == "model_identity") == {
        "requested_model": REQUESTED, "actual_model": None,
        "reported_models": sorted([ACTUAL, "another-execution-model"]), "telemetry": "ambiguous"}
    assert len([1 for kind, data in events if kind == "native_event" and data["type"] in {"assistant", "stream_event"}]) == 2


@pytest.mark.parametrize("model", ["", " ", 123, {}, []])
def test_claude_malformed_model_telemetry_is_explicit_error(monkeypatch, tmp_path, model):
    result, _, _, _ = launch(monkeypatch, tmp_path, "claude", claude_messages(assistant(model)))
    assert result.status == "UNKNOWN" and result.actual_model is None
    assert result.session_id == SESSION
    assert "invalid native assistant model telemetry" in result.error


@pytest.mark.parametrize("error,code", [(True, 0), (False, 9)])
def test_claude_native_failures_keep_telemetry(monkeypatch, tmp_path, error, code):
    result, _, _, _ = launch(monkeypatch, tmp_path, "claude", claude_messages(assistant(), error=error), exit_code=code)
    assert result.status == "ERROR" and result.error
    assert result.actual_model == ACTUAL and result.session_id == SESSION
    assert result.exit_code == code and result.usage["tokens"] == TOKENS


@pytest.mark.parametrize("fault", [EOFError("lost final"), TimeoutError("deadline"), ProtocolError("bad stream")])
def test_claude_incomplete_run_keeps_observed_identity_and_usage(monkeypatch, tmp_path, fault):
    result, _, _, _ = launch(monkeypatch, tmp_path, "claude", [assistant(), fault])
    assert result.status == "UNKNOWN" and result.error
    assert result.actual_model == ACTUAL and result.session_id == SESSION
    assert result.usage["last_message_tokens"] == TOKENS


def test_claude_wait_timeout_preserves_terminal_usage_without_success(monkeypatch, tmp_path):
    result, _, _, _ = launch(monkeypatch, tmp_path, "claude", claude_messages(assistant()),
        wait_error=TimeoutExpired("fixture", 1))
    assert result.status == "UNKNOWN" and "TimeoutExpired" in result.error
    assert result.actual_model == ACTUAL and result.usage["tokens"] == TOKENS


def test_claude_interrupt_keeps_observed_identity(monkeypatch, tmp_path):
    calls = 0

    def controls():
        nonlocal calls
        calls += 1
        return [] if calls == 1 else [{"id": "stop", "action": "interrupt"}]

    result, _, _, _ = launch(monkeypatch, tmp_path, "claude", [assistant()], controls=controls)
    assert result.status == "UNKNOWN" and "interrupted" in result.error
    assert result.session_id == SESSION and result.actual_model == ACTUAL


@pytest.mark.parametrize("limit", [None, 8])
@pytest.mark.parametrize("status", ["completed", "failed", "interrupted"])
def test_codex_keeps_native_identity_usage_without_echo_attestation(monkeypatch, tmp_path, limit, status):
    events = [{"method": "model/rerouted", "params": {"threadId": SESSION, "turnId": TURN,
               "fromModel": REQUESTED, "toModel": ACTUAL, "reason": "fixture routing"}},
              {"method": "item/completed", "params": {"threadId": SESSION, "turnId": TURN,
               "item": {"type": "agentMessage", "id": "output", "text": "native output", "model": ACTUAL}}}]
    result, proc, (_, kwargs), emitted = launch(monkeypatch, tmp_path, "codex",
        codex_messages(*events, status=status), max_turns=limit)
    assert result.status == {"completed": "COMPLETED", "failed": "ERROR", "interrupted": "INTERRUPTED"}[status]
    assert result.actual_model is None
    assert result.session_id == SESSION and result.turn_id == TURN
    assert result.usage == {"total": TOKENS, "last": TOKENS} and result.output == "native output"
    assert bool(result.error) == (status == "failed")
    requests = {value["method"]: value["params"] for value in proc.sent if isinstance(value, dict) and "id" in value}
    assert requests["thread/start"]["sandbox"] == "read-only"
    assert requests["turn/start"]["sandboxPolicy"] == {"type": "readOnly"}
    for method in ("thread/start", "turn/start"):
        assert requests[method]["approvalPolicy"] == "never" and requests[method]["model"] == REQUESTED
        assert "maxTurns" not in requests[method] and "max_turns" not in requests[method]
    assert kwargs["timeout"] == 300 and kwargs["max_bytes"] == 8_000_000
    assert any(kind == "native_event" and data["method"] == "model/rerouted" for kind, data in emitted)


@pytest.mark.parametrize("fault", [EOFError("lost final"), TimeoutError("deadline"), ProtocolError("bad stream")])
def test_codex_incomplete_run_retains_thread_turn_and_usage(monkeypatch, tmp_path, fault):
    result, _, _, _ = launch(monkeypatch, tmp_path, "codex", [*codex_messages()[:-1], fault])
    assert result.status == "UNKNOWN" and result.error
    assert result.session_id == SESSION and result.turn_id == TURN
    assert result.actual_model is None and result.usage["total"] == TOKENS


@pytest.mark.parametrize("kind", ["claude", "codex"])
def test_spawn_failure_returns_requested_identity_and_explicit_error(monkeypatch, tmp_path, kind):
    module, cls = (claude_code, claude_code.ClaudeCodeDriver) if kind == "claude" else (codex, codex.CodexDriver)

    def fail(*args, **kwargs):
        raise FileNotFoundError("fixture executable missing")

    monkeypatch.setattr(module, "Process", fail)
    result = cls().run(Request("task", "work", str(tmp_path), REQUESTED), lambda *_: None)
    assert result.status == "UNKNOWN" and result.requested_model == REQUESTED and result.actual_model is None
    assert result.session_id is None and result.turn_id is None
    assert "FileNotFoundError" in result.error
