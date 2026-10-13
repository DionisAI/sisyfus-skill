"""Exercise real Sol native transport; preserve missing model identity as missing."""
from __future__ import annotations
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sisyfus.workers.codex import CodexDriver
from sisyfus.workers.protocol import Request, redact

def main():
    directory = ROOT / "artifacts/techlead/sol-native-probe"
    directory.mkdir(exist_ok=False)
    with (directory / "events.jsonl").open("x") as log:
        def emit(kind, data):
            log.write(json.dumps({"kind":kind,"data":redact(data)},ensure_ascii=False)+"\n")
            log.flush()
        result = CodexDriver().run(Request("sol-native-probe",
            'Return exactly the JSON object {"ready":true}. Do not run tools or modify files.',
            str(directory), "gpt-6.1-sol", timeout=900, max_turns=None), emit)
    (directory / "receipt.json").write_text(json.dumps(result.as_dict(),ensure_ascii=False,indent=2))
    print(json.dumps({"status":result.status,"requested_model":result.requested_model,
                      "actual_model":result.actual_model,"session_id":result.session_id,
                      "turn_id":result.turn_id,"error":result.error,
                      "receipt":str(directory / "receipt.json")},ensure_ascii=False))
    if result.status != "COMPLETED": raise SystemExit(1)
if __name__ == "__main__": main()
