#!/usr/bin/env python3
"""Deterministic example for the proposal-only planner protocol.

Replace this with a model/agent CLI adapter. The planner may only propose a
Decision; Sisyfus policy, capability execution, and verifier evidence remain
outside the planner's authority.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


context_path = Path(os.environ["SISYFUS_AUTONOMY_CONTEXT_PATH"])
response_path = Path(os.environ["SISYFUS_AUTONOMY_RESPONSE_PATH"])
payload = json.loads(context_path.read_text(encoding="utf-8"))
continuation = payload["continuation"]
context = payload["context"]
latest = context.get("latest_evidence")

if latest and latest.get("verdict") == "PASS":
    decision = {
        "kind": "FINISH",
        "evidence_id": latest["id"],
        "reason": "the independent verifier produced PASS evidence",
    }
else:
    continuation_id = continuation["id"]
    decision = {
        "kind": "EXECUTE",
        "capability": "workspace.write_text",
        "arguments": {
            "path": f"autonomy-results/{continuation_id}.txt",
            "content": continuation["objective"] + "\n",
        },
        "idempotency_key": f"write-objective:{continuation_id}",
        "reason": "produce one workspace artifact for exact read-back verification",
    }

response_path.write_text(
    json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
