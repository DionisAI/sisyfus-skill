from __future__ import annotations

from subprocess import TimeoutExpired
from typing import Any

from .protocol import ControlSource, EventSink, Receipt, Request, environment
from .transport import Process, ProtocolError, probe


class ClaudeCodeDriver:
    """Native Claude Code CLI, not a Messages API substitute.

    This bounded CLI adapter cannot steer a live turn. Interrupting its process
    without a native final receipt remains UNKNOWN, not a fabricated success.

    Identity comes only from this invocation's top-level assistant/message_start
    message.model (excluding Claude's <synthetic> error messages).
    Init/result configuration echoes and session-wide modelUsage
    are not turn attestation. Multiple execution models leave actual_model null;
    their native events and model_identity diagnostic retain the evidence.
    Claude has no native turn ID here: assistant message IDs are not turn IDs.
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
                "--setting-sources", "user,project,local"]
        if request.max_turns is not None:
            argv += ["--max-turns", str(request.max_turns)]
        if request.session_id:
            argv += ["--resume", request.session_id]
        proc = None
        session = None
        result = None
        usage: dict[str, Any] = {}
        models: set[str] = set()

        def receipt(status: str, **kwargs: Any) -> Receipt:
            actual = next(iter(models)) if len(models) == 1 else None
            emit("model_identity", {"requested_model": request.model, "actual_model": actual,
                                   "reported_models": sorted(models),
                                   "telemetry": "missing" if not models else "ambiguous" if len(models) > 1 else "reported"})
            return Receipt(status, session_id=session, usage=usage,
                           requested_model=request.model, actual_model=actual, **kwargs)

        try:
            proc = Process(argv, cwd=request.cwd, env=environment(self.env_names), timeout=request.timeout,
                           max_bytes=request.max_output_bytes)
            emit("process_started", {"pid": proc.process.pid, "driver": self.name})
            proc.send_bytes(request.prompt.encode(), close=True)
            while True:
                for control in controls():
                    emit("control_ack", {"command_id": control["id"], "accepted": control.get("action") == "interrupt"})
                    if control.get("action") == "interrupt":
                        return receipt("UNKNOWN", error="process interrupted without native final receipt")
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
                # Subagent telemetry does not attest the primary role's model.
                if message.get("parent_tool_use_id") is None:
                    assistant = None
                    if message.get("type") == "assistant":
                        assistant = message.get("message")
                    elif message.get("type") == "stream_event":
                        event = message.get("event") or {}
                        if not isinstance(event, dict):
                            raise ProtocolError("invalid native stream event")
                        if event.get("type") == "message_start":
                            assistant = event.get("message")
                    if assistant is not None:
                        if not isinstance(assistant, dict):
                            raise ProtocolError("invalid native assistant message")
                        model = assistant.get("model")
                        if model is not None:
                            if not isinstance(model, str) or not model.strip():
                                raise ProtocolError("invalid native assistant model telemetry")
                            if model != "<synthetic>":
                                models.add(model)
                        if assistant.get("usage") is not None:
                            usage["last_message_tokens"] = assistant["usage"]
                if message.get("type") == "result":
                    if result is not None:
                        raise ProtocolError("duplicate terminal result")
                    result = message
                    usage.update({"tokens": result.get("usage"), "model_usage": result.get("modelUsage"),
                                  "reported_total_cost_usd": result.get("total_cost_usd"),
                                  "cost_semantics": "provider_reported_session_total_not_settled_invoice"})
            code = proc.wait()
            if result is None or session is None:
                return receipt("UNKNOWN", exit_code=code, error="missing native final result/session")
            ok = code == 0 and result.get("subtype") == "success" and result.get("is_error") is False
            return receipt("COMPLETED" if ok else "ERROR", exit_code=code,
                           output=str(result.get("result", "")),
                           error=None if ok else "native execution failed")
        except (OSError, ValueError, ProtocolError, TimeoutError, TimeoutExpired) as exc:
            return receipt("UNKNOWN", exit_code=proc.process.poll() if proc else None,
                           error=f"{type(exc).__name__}: {exc}")
        finally:
            if proc:
                proc.close()
