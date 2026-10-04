from __future__ import annotations

from typing import Any

from .protocol import ControlSource, EventSink, Receipt, Request, environment
from .transport import Process, ProtocolError, probe


class ClaudeCodeDriver:
    """Native Claude Code CLI, not a Messages API substitute.

    This bounded CLI adapter cannot steer a live turn. Interrupting its process
    without a native final receipt remains UNKNOWN, not a fabricated success.
    """
    name = "claude"
    controls = ("interrupt",)

    def __init__(self, command: tuple[str, ...] = ("claude",), *, env_names: tuple[str, ...] = ()):
        self.command, self.env_names = command, env_names

    def probe(self) -> dict[str, Any]:
        return {**probe(self.command), "driver": self.name, "controls": self.controls}

    def run(self, request: Request, emit: EventSink, controls: ControlSource = lambda: []) -> Receipt:
        tools = "Read,Glob,Grep" + (",Write,Edit" if request.mode == "workspace-write" else "")
        argv = [*self.command, "-p", "--output-format", "stream-json", "--verbose",
                "--include-partial-messages", "--model", request.model,
                "--permission-mode", "dontAsk", "--tools", tools, "--allowedTools", tools,
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--setting-sources", "", "--max-turns", str(request.max_turns)]
        if request.session_id:
            argv += ["--resume", request.session_id]
        proc = Process(argv, cwd=request.cwd, env=environment(self.env_names), timeout=request.timeout,
                       max_bytes=request.max_output_bytes)
        session = None
        result = None
        try:
            emit("process_started", {"pid": proc.process.pid, "driver": self.name})
            proc.send_bytes(request.prompt.encode(), close=True)
            while True:
                for control in controls():
                    emit("control_ack", {"command_id": control["id"], "accepted": control.get("action") == "interrupt"})
                    if control.get("action") == "interrupt":
                        return Receipt("UNKNOWN", session, error="process interrupted without native final receipt")
                try:
                    message = proc.receive()
                except EOFError:
                    break
                if message is None:
                    continue
                native_session = message.get("session_id")
                if native_session:
                    if session and native_session != session:
                        raise ProtocolError("mixed native session IDs")
                    if request.session_id and native_session != request.session_id:
                        raise ProtocolError("native resumed a different session")
                    if session is None:
                        session = str(native_session)
                        emit("session_bound", {"session_id": session})
                emit("native_event", message)
                if message.get("type") == "result":
                    if result is not None:
                        raise ProtocolError("duplicate terminal result")
                    result = message
            code = proc.wait()
            if result is None or session is None:
                return Receipt("UNKNOWN", session, exit_code=code, error="missing native final result/session")
            ok = code == 0 and result.get("subtype") == "success" and result.get("is_error") is False
            return Receipt("COMPLETED" if ok else "ERROR", session, exit_code=code,
                           output=str(result.get("result", "")),
                           usage={"tokens": result.get("usage"), "reported_total_cost_usd": result.get("total_cost_usd"),
                                  "cost_semantics": "provider_reported_session_total_not_settled_invoice"},
                           error=None if ok else "native execution failed")
        except (OSError, ValueError, ProtocolError, TimeoutError) as exc:
            return Receipt("UNKNOWN", session, exit_code=proc.process.poll(), error=f"{type(exc).__name__}: {exc}")
        finally:
            proc.close()
