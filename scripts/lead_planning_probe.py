"""Real Opus planning receipt, with inherited user settings and retained events."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sisyfus.workers.transport import Process
from sisyfus.workers.protocol import environment, redact

def main():
    output = ROOT / "artifacts/techlead/initial-opus-plan.jsonl"
    prompt = """You are the continuous engineering Tech Lead for Sisyfus. Read AGENTS.md,
docs/TECHLEAD-ACCEPTANCE.md and the relevant src/sisyfus/workers files. Design an
incremental implementation of every acceptance requirement. Lead/reviewer are
claude-opus-5-5; implementers are gpt-6.1-sol. Total budgets are unlimited by
default; single-call timeout/output, unknown execution fencing and operator
stop remain. Preserve the existing autonomy store/hash chain and deterministic
verifier, no second truth database. Include versioned replanning/repair,
parallel scoped implementation and integration, isolated independent review,
evidence-backed recursive improvement of Lead procedures across tasks,
and a usable browser mission-creation/control UI. Do not edit any file or run
commands. Return one JSON object with keys architecture, modules, interfaces,
implementation_tasks, risks, acceptance_tests. Propose concrete disjoint
write sets for parallel implementers. Explain how recursive improvement is
measured using frozen baseline/candidate execution and held-out evidence,
not fabricated telemetry or a model's own assertion of improvement.
"""
    argv = ["claude", "-p", "--model", "claude-opus-5-5", "--effort", "xhigh",
            "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            "--permission-mode", "dontAsk", "--tools", "Read,Glob,Grep",
            "--allowedTools", "Read,Glob,Grep", "--strict-mcp-config", "--mcp-config",
            '{"mcpServers":{}}', "--setting-sources", "user,project,local"]
    process = Process(argv, cwd=str(ROOT), env=environment(("ANTHROPIC_API_KEY",)),
                      timeout=1200, max_bytes=16_000_000)
    result = None
    try:
        process.send_bytes(prompt.encode(), close=True)
        with output.open("x") as log:
            while True:
                try: event = process.receive()
                except EOFError: break
                if event is not None:
                    log.write(json.dumps(redact(event), ensure_ascii=False)+"\n")
                    log.flush()
                    if event.get("type") == "result": result = event
        code = process.wait()
        if code or result is None or result.get("is_error"):
            raise RuntimeError(f"Opus planning did not succeed: exit={code}, result={bool(result)}")
        (output.parent / "initial-opus-plan-result.json").write_text(
            json.dumps(redact(result), ensure_ascii=False, indent=2))
        print(json.dumps({"requested_model":"claude-opus-5-5", "model_usage":result.get("modelUsage"),
                          "status":result.get("subtype"), "receipt":str(output),
                          "result_chars":len(result.get("result", ""))}, ensure_ascii=False))
    finally: process.close()

if __name__ == "__main__": main()
