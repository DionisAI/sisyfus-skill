"""Deterministic protocol fixture. NEVER label this as a real LLM run."""
import json
import pathlib
import sys
import time

if "--version" in sys.argv:
    print("PROTOCOL-FIXTURE-ONLY 1.0")
    raise SystemExit
kind, behavior = sys.argv[1:3]


def send(value):
    print(json.dumps(value), flush=True)


def answer(prompt):
    if "Return ONLY a JSON object" in prompt:
        return json.dumps({"tasks": [
            {"id": "build", "objective": "Write answer.txt with 42", "driver": "codex", "check": "answer", "max_attempts": 2},
            {"id": "review", "objective": "Write answer.txt with 42 using verified inputs", "driver": "claude", "check": "answer", "depends_on": ["build"], "max_attempts": 2}]})
    content = "0" if behavior == "retry" and "Independent previous verification" not in prompt else "42"
    pathlib.Path("answer.txt").write_text(content)
    if behavior == "slow":
        time.sleep(.25)
    return "PASS! I have finished everything."  # Intentionally not evidence.


if kind == "claude":
    prompt = sys.stdin.read()
    send({"type": "system", "subtype": "init", "session_id": "claude-session"})
    if behavior == "hang":
        time.sleep(20)
    if behavior == "malformed":
        print("not-json", flush=True)
        raise SystemExit
    if behavior == "missing":
        raise SystemExit
    output = answer(prompt)
    send({"type": "assistant", "parent_tool_use_id": None,
          "message": {"content": [{"type": "text", "text": output}]}})
    terminal = {"type": "result", "subtype": "success", "is_error": False, "session_id": "claude-session",
                "result": output, "total_cost_usd": .001, "usage": {"input_tokens": 1}}
    send(terminal)
    if behavior == "duplicate":
        send(terminal)
    raise SystemExit(9 if behavior == "nonzero" else 0)

thread = "codex-session"
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    ident = message.get("id")
    params = message.get("params", {})
    if method == "initialize":
        send({"id": ident, "result": {"userAgent": "protocol-fixture"}})
    elif method in {"thread/start", "thread/resume"}:
        thread = params.get("threadId", thread)
        send({"id": ident, "result": {"thread": {"id": thread}}})
    elif method == "turn/start":
        send({"id": ident, "result": {"turn": {"id": "turn-1", "status": "inProgress"}}})
        if behavior == "hang":
            time.sleep(20)
        if behavior == "missing":
            raise SystemExit
        if behavior == "flood":
            print("x" * 1_100_000, flush=True)
            time.sleep(20)
        prompt = params["input"][0]["text"]
        output = answer(prompt)
        send({"method": "item/completed", "params": {"threadId": thread, "turnId": "turn-1",
            "item": {"id": "message-1", "type": "agentMessage", "text": output}}})
        if behavior == "control":
            continue
        if behavior == "approval":
            send({"id": 999, "method": "item/commandExecution/requestApproval", "params": {"threadId": thread}})
            continue
        send({"method": "turn/completed", "params": {"threadId": thread, "turn": {"id": "turn-1", "status": "completed"}}})
    elif method == "turn/steer":
        send({"id": ident, "result": {"turnId": "turn-1"}})
    elif method == "turn/interrupt":
        send({"id": ident, "result": {}})
        send({"method": "turn/completed", "params": {"threadId": thread, "turn": {"id": "turn-1", "status": "interrupted"}}})
    elif ident == 999:
        assert message["result"]["decision"] == "decline"
        send({"method": "turn/completed", "params": {"threadId": thread, "turn": {"id": "turn-1", "status": "completed"}}})
