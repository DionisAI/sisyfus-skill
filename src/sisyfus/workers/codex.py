from __future__ import annotations

from typing import Any

from .. import __version__
from .protocol import ControlSource, EventSink, Receipt, Request, environment
from .transport import Process, ProtocolError, probe


class CodexDriver:
    """Codex app-server over stdio; native requests never grant elevated authority.

    The current app-server protocol returns configured model selection, not a
    per-generation model attestation. Even a reroute describes routing, not all
    inference in this turn. Retain native events but leave actual_model null.
    Never promote thread/start or turn/start model echoes into runtime identity.
    max_turns is not an app-server parameter: this adapter starts one native turn.
    """
    name = "codex"
    controls = ("interrupt", "steer")

    def __init__(self, command: tuple[str, ...] = ("codex",), *, env_names: tuple[str, ...] = ()):
        self.command, self.env_names = command, env_names

    def probe(self) -> dict[str, Any]:
        return {**probe(self.command), "driver": self.name, "controls": self.controls}

    def run(self, request: Request, emit: EventSink, controls: ControlSource = lambda: []) -> Receipt:
        proc = None
        thread_id = turn_id = None
        output: dict[str, str] = {}
        terminal: dict[str, Any] | None = None
        usage: dict[str, Any] = {}
        serial = 0
        control_ids: dict[int, str] = {}
        control_sent: set[str] = set()

        def receipt(status: str, **kwargs: Any) -> Receipt:
            emit("model_identity", {"requested_model": request.model, "actual_model": None,
                                   "telemetry": "missing"})
            return Receipt(status, session_id=thread_id, turn_id=turn_id, usage=usage,
                           requested_model=request.model, actual_model=None, **kwargs)

        def on_message(message: dict[str, Any]) -> None:
            nonlocal terminal, usage
            method = message.get("method")
            params = message.get("params") or {}
            if not isinstance(params, dict):
                raise ProtocolError("invalid native event params")
            if method and "id" in message:
                # Even a malicious planner cannot approve tool escalation.
                emit("approval_denied", {"method": method, "request_id": message["id"]})
                if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
                    proc.send({"id": message["id"], "result": {"decision": "decline"}})
                else:
                    proc.send({"id": message["id"], "error": {"code": -32601, "message": "unsupported host request"}})
                return
            if "id" in message and message["id"] in control_ids:
                emit("control_ack", {"command_id": control_ids.pop(message["id"]),
                                     "accepted": "error" not in message, "error": message.get("error")})
                return
            if not method:
                return
            # Responses from unrelated native threads cannot complete this run.
            if params.get("threadId") and thread_id and params["threadId"] != thread_id:
                return
            if params.get("turnId") and turn_id and params["turnId"] != turn_id:
                return
            emit("native_event", {"method": method, "params": params})
            if method == "item/completed":
                item = params.get("item") or {}
                if item.get("type") == "agentMessage":
                    output[str(item.get("id", "final"))] = str(item.get("text", ""))
            if method == "thread/tokenUsage/updated":
                usage = params.get("tokenUsage") or {}
            if method == "turn/completed":
                candidate = params.get("turn") or {}
                if turn_id is None or candidate.get("id") == turn_id:
                    terminal = candidate

        def rpc(method: str, params: dict[str, Any]) -> dict[str, Any]:
            nonlocal serial
            serial += 1
            ident = serial
            proc.send({"id": ident, "method": method, "params": params})
            while True:
                message = proc.receive()
                if message is None:
                    continue
                if message.get("id") == ident and not message.get("method"):
                    if "error" in message:
                        raise ProtocolError(f"Codex rejected {method}: {message['error']}")
                    result = message.get("result")
                    if not isinstance(result, dict):
                        raise ProtocolError("invalid RPC result")
                    return result
                on_message(message)

        try:
            proc = Process([*self.command, "app-server"], cwd=request.cwd, env=environment(self.env_names),
                           timeout=request.timeout, max_bytes=request.max_output_bytes)
            emit("process_started", {"pid": proc.process.pid, "driver": self.name})
            rpc("initialize", {"clientInfo": {"name": "sisyfus", "version": __version__}})
            proc.send({"method": "initialized", "params": {}})
            params: dict[str, Any] = {"model": request.model, "cwd": request.cwd,
                                      "approvalPolicy": "never", "sandbox": request.mode}
            if request.session_id:
                params["threadId"] = request.session_id
            result = rpc("thread/resume" if request.session_id else "thread/start", params)
            thread_id = result["thread"]["id"]
            if request.session_id and thread_id != request.session_id:
                raise ProtocolError("native resumed a different session")
            emit("session_bound", {"session_id": thread_id})
            sandbox = ({"type": "readOnly"} if request.mode == "read-only" else
                       {"type": "workspaceWrite", "writableRoots": [request.cwd], "networkAccess": False})
            turn = rpc("turn/start", {"threadId": thread_id, "cwd": request.cwd, "model": request.model,
                       "approvalPolicy": "never", "sandboxPolicy": sandbox,
                       "input": [{"type": "text", "text": request.prompt}]})
            turn_id = turn["turn"]["id"]
            emit("turn_bound", {"session_id": thread_id, "turn_id": turn_id})
            if terminal and terminal.get("id") != turn_id:
                terminal = None
            while terminal is None:
                for control in controls():
                    cid = str(control["id"])
                    if cid in control_sent:
                        continue
                    control_sent.add(cid)
                    action = control.get("action")
                    if action not in self.controls:
                        emit("control_ack", {"command_id": cid, "accepted": False})
                        continue
                    serial += 1
                    control_ids[serial] = cid
                    payload = {"threadId": thread_id, "turnId": turn_id} if action == "interrupt" else {
                        "threadId": thread_id, "expectedTurnId": turn_id,
                        "input": [{"type": "text", "text": str(control.get("text", ""))}]}
                    proc.send({"id": serial, "method": f"turn/{action}", "params": payload})
                message = proc.receive()
                if message:
                    on_message(message)
            status = {"completed": "COMPLETED", "failed": "ERROR", "interrupted": "INTERRUPTED"}.get(
                terminal.get("status"), "UNKNOWN")
            return receipt(status, output="\n".join(output.values()),
                           error=str(terminal["error"]) if terminal.get("error") else None)
        except (OSError, ValueError, KeyError, ProtocolError, EOFError, TimeoutError) as exc:
            # A missing terminal response never authorizes resending turn/start.
            return receipt("UNKNOWN", exit_code=proc.process.poll() if proc else None,
                           error=f"{type(exc).__name__}: {exc}")
        finally:
            if proc:
                proc.close()
