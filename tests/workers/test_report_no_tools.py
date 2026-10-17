"""Transport flags for inline, tool-free report roles; no external calls here."""
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from sisyfus.workers import claude_code, codex
from sisyfus.workers.protocol import Request


def test_no_tools_disables_native_tools_settings_hooks_and_skills(monkeypatch):
    root = Path(__file__).resolve().parents[2] / "artifacts/techlead/report-no-tools-tests" / uuid.uuid4().hex
    root.mkdir(parents=True)
    calls = []
    messages = iter([{"type": "system", "subtype": "init", "session_id": "probe", "tools": []},
                     {"type": "assistant", "session_id": "probe", "message": {"model": "claude-opus-5-5"}},
                     {"type": "result", "session_id": "probe", "subtype": "success", "is_error": False, "result": "{}"}])
    class Process:
        def __init__(self, argv, **kw):
            calls.append(argv)
            self.process = SimpleNamespace(pid=1, poll=lambda: 0)
        def send_bytes(self, *a, **kw): pass
        def receive(self):
            try: return next(messages)
            except StopIteration: raise EOFError()
        def wait(self): return 0
        def close(self): pass
    monkeypatch.setattr(claude_code, "Process", Process)
    receipt = claude_code.ClaudeCodeDriver().run(Request("report", "inline evidence", str(root), "claude-opus-5-5", mode="no-tools"), lambda *a: None)
    assert receipt.status == "COMPLETED"
    argv = calls[0]
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert "--bare" in argv and "--disable-slash-commands" in argv
    assert "--resume" not in argv


def test_codex_no_tools_mode_fails_explicitly_without_launch(monkeypatch):
    root = Path(__file__).resolve().parents[2] / "artifacts/techlead/report-no-tools-tests" / uuid.uuid4().hex
    root.mkdir(parents=True)
    monkeypatch.setattr(codex, "Process", lambda *a, **kw: pytest.fail("no-tools is a Claude report-role mode"))
    with pytest.raises(ValueError, match="no-tools"):
        codex.CodexDriver().run(Request("report", "inline", str(root), "gpt-6.1-sol", mode="no-tools"), lambda *a: None)
