#!/usr/bin/env python3
"""Run the real Lead improvement proposal and an operator-frozen paired pilot.

This is retained engineering verification, not synthetic benchmark evidence.
All authoritative reservations, reviews, verdicts and policy history remain in
the existing mission databases. An output marker prevents accidental replay.
"""
from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sisyfus.workers.lead_mission import LeadMission
from sisyfus.workers.lead_trials import run_trials
from sisyfus.workers.protocol import redact


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(redact(value), stream, ensure_ascii=False, indent=2, allow_nan=False)
    path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-local-workers", action="store_true")
    args = parser.parse_args()
    if not args.allow_local_workers:
        raise PermissionError("--allow-local-workers is required for native proposal and paired execution")
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output / "invocation.json", {"origin": str(args.origin.resolve()),
        "catalog": str(args.catalog.resolve()), "kind": "REAL_NATIVE_PAIRED_PROCEDURE_PILOT",
        "status": "STARTED_NOT_ACCEPTED", "replay": "no automatic redispatch"})
    mission = LeadMission(args.origin)
    with (mission.directory / "lead-controller.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        snapshot = mission.snapshot()
        if not snapshot["all_verified"] or snapshot["stopped"] or snapshot["paused"]:
            raise ValueError("origin must have current accepted integration and no stop/pause")
        save(args.output / "origin-before.json", snapshot)
        candidate = mission._propose_from_completed_evidence()
        if not candidate:
            raise ValueError("native Lead proposal lacks canonical grounding")
        save(args.output / "candidate.json", mission.learning.validate_candidate(candidate))
        print(json.dumps({"phase": "PROPOSED", "candidate_id": candidate,
                          "output": str(args.output)}, ensure_ascii=False), flush=True)
        report = run_trials(mission, candidate, args.catalog)
        save(args.output / "paired-report.json", report)
        save(args.output / "origin-after.json", mission.snapshot())
        print(json.dumps({"phase": report["status"], "promoted": report.get("promoted", False),
                          "claim": report.get("claim"), "output": str(args.output)}, ensure_ascii=False), flush=True)
        return 0 if report["status"] in {"PROMOTED", "ELIGIBLE", "NONPROMOTION"} else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "VALIDATION_ERROR", "error": redact(f"{type(exc).__name__}: {exc}")}), file=sys.stderr)
        raise SystemExit(1)
