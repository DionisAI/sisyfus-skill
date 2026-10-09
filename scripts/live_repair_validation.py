#!/usr/bin/env python3
"""One controlled faulty worker, then real Opus diagnosis and native Sol repair.

The first worker is explicitly synthetic. It is never evidence of native Sol
execution or a native procedure benchmark. All later implementation/review calls
use the existing drivers. An exclusive output directory prevents blind replay.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from live_review_negative import SPECIMENS, SyntheticWorkerReceipt
from sisyfus.workers.lead_mission import LeadMission
from sisyfus.workers.mission import copy_candidate
from sisyfus.workers.protocol import redact


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(redact(value), stream, ensure_ascii=False, indent=2, allow_nan=False)
    path.chmod(0o600)


class FaultOnce:
    def __init__(self, delegate):
        self.delegate = delegate
        self.injected = False

    def probe(self):
        return self.delegate.probe()

    def run(self, request, emit, controls):
        if self.injected:
            return self.delegate.run(request, emit, controls)
        if request.mode != "workspace-write" or controls():
            raise ValueError("controlled specimen expects an uninterrupted implementation request")
        self.injected = True
        (Path(request.cwd) / "job.py").write_text(SPECIMENS["payload-logging"])
        emit("synthetic_worker_fixture", {
            "execution_kind": "CONTROLLED_SYNTHETIC_WORKER_NEGATIVE_VALIDATION",
            "native_worker_execution": False,
            "followup": "real native Codex driver, unchanged controller diagnosis"})
        return SyntheticWorkerReceipt("COMPLETED", requested_model=request.model,
            output="Explicitly synthetic initial fault; no native worker call occurred.")


def require_repaired(mission, outcome):
    runs = mission.journal.runs()
    synthetic = [r for r in runs if (r.get("receipt") or {}).get("native_worker_execution") is False]
    repaired = [r for r in runs if r["role"] == "worker" and r not in synthetic]
    diagnoses = mission.journal.records("diagnoses")
    reviews = mission.journal.records("reviews")
    negative = [r for r in reviews if r["data"].get("verdict") == "FAIL"]
    if not outcome["all_verified"] or len(synthetic) != 1 or not repaired or not diagnoses or not negative:
        raise ValueError("real autonomous repair acceptance was not established")
    if not any(d["data"].get("classification") == "implementation" and d["data"].get("action") == "repair" for d in diagnoses):
        raise ValueError("Lead must diagnose the planted implementation defect and issue repair")
    if any((r.get("receipt") or {}).get("status") != "COMPLETED" for r in runs):
        raise ValueError("all controlled/native requests must have known completed receipts")
    if any((r.get("receipt") or {}).get("actual_model") != "claude-opus-5-5" for r in runs if r["role"] != "worker"):
        raise ValueError("actual Opus identity was not established for planning/diagnosis/reviews")
    if any((r.get("receipt") or {}).get("requested_model") != "gpt-6.1-sol" for r in repaired):
        raise ValueError("repair worker did not request the approved Sol model")
    chain = mission.store.verify_event_chain()
    if not chain["valid"]:
        raise ValueError("event chain validation failed")
    return {"status": "AUTONOMOUS_REPAIR_VERIFIED", "initial_worker": "EXPLICITLY_SYNTHETIC",
            "canonical_reservations": len(runs), "real_native_calls": len(runs)-1,
            "native_worker_requested": "gpt-6.1-sol",
            "native_worker_actual": [(r.get("receipt") or {}).get("actual_model") for r in repaired],
            "opus_actual": "claude-opus-5-5", "diagnoses": diagnoses,
            "event_chain": chain, "snapshot": outcome,
            "claim": "controlled initial defect rejected; real Lead diagnosed and delegated accepted native repair; not an RSI benchmark"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-local-workers", action="store_true")
    args = parser.parse_args()
    if not args.allow_local_workers:
        raise PermissionError("--allow-local-workers is required")
    args.output.mkdir(parents=True, exist_ok=False)
    raw = json.loads(args.mission.read_text())
    source = args.output.resolve() / "source"
    copy_candidate(Path(raw["source"]), source)
    raw["source"] = str(source)
    raw.pop("tasks", None)
    raw["rsi"] = {"enabled": True, "auto_promote": False}
    raw["validation_kind"] = "CONTROLLED_INITIAL_FAULT_REAL_NATIVE_AUTONOMOUS_REPAIR"
    save(args.output / "mission.json", raw)
    save(args.output / "invocation.json", {"status": "STARTED_NOT_ACCEPTED",
        "initial_worker": "EXPLICITLY_SYNTHETIC", "subsequent_workers": "REAL_NATIVE_CODEX",
        "replay": "exclusive output directory; no automatic redispatch"})
    mission = LeadMission(args.output / "control", raw)
    mission.drivers["codex"] = FaultOnce(mission.drivers["codex"])
    outcome = mission.run()
    save(args.output / "snapshot.json", outcome)
    proof = require_repaired(mission, outcome)
    save(args.output / "validation.json", proof)
    print(json.dumps({k:proof[k] for k in ("status", "canonical_reservations", "real_native_calls", "native_worker_actual", "claim")},ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "VALIDATION_ERROR", "error":redact(f"{type(exc).__name__}: {exc}")}),file=sys.stderr)
        raise SystemExit(1)
