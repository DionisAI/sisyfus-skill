from __future__ import annotations

from pathlib import Path
from typing import Any

from .utils import read_json, read_jsonl, sha256_text, truncate_middle, utc_now, write_json


def _load_final(run_dir: Path) -> dict[str, Any]:
    final_path = run_dir / "final.json"
    return read_json(final_path) if final_path.exists() else {}


def _latest_verifier(run_dir: Path) -> dict[str, Any] | None:
    reports = sorted(run_dir.glob("verifier-round-*.json")) + sorted(run_dir.glob("verifier.json"))
    if not reports:
        return None
    return read_json(reports[-1])


def make_distill(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    events = read_jsonl(run_dir / "events.jsonl")
    final = _load_final(run_dir)
    verifier = _latest_verifier(run_dir)
    goal = read_json(run_dir / "goal.normalized.json") if (run_dir / "goal.normalized.json").exists() else {}
    run_id = final.get("run_id") or run_dir.name
    goal_id = final.get("goal_id") or goal.get("id") or "unknown-goal"
    status = final.get("status") or (verifier or {}).get("status") or "UNKNOWN"

    facts: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    hypotheses: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []

    beam_node = final.get("beam") or final.get("beam_node") or goal.get("beam_node") or {}
    beam_result: dict[str, Any] = {}
    beam_result_path = run_dir / "beam_result.json"
    if beam_result_path.exists():
        try:
            raw_beam_result = read_json(beam_result_path)
            if isinstance(raw_beam_result, dict):
                beam_result = raw_beam_result
        except Exception as exc:
            hypotheses.append({
                "claim": f"Goal {goal_id} wrote an unreadable beam_result.json: {exc}",
                "evidence": {"run_id": run_id, "run_dir": str(run_dir), "path": str(beam_result_path)},
                "scope": [goal_id, "beam"],
                "confidence": 0.5,
            })
    if isinstance(beam_node, dict) and beam_node:
        verdict = str(beam_result.get("verdict") or "").lower()
        summary = str(beam_result.get("summary") or "").strip()
        score = beam_result.get("score")
        if summary:
            target = failures if verdict in {"wrong", "dead_end", "rejected"} else hypotheses
            target.append({
                "claim": f"Beam node {beam_node.get('node_id')} reported: {summary}",
                "evidence": {"run_id": run_id, "run_dir": str(run_dir), "beam_node": beam_node, "beam_result": beam_result},
                "scope": [goal_id, "beam", str(beam_node.get("beam_id"))],
                "confidence": float(score) if isinstance(score, (int, float)) else 0.65,
            })
        for idx, claim in enumerate(beam_result.get("claims", []) or []):
            if isinstance(claim, str):
                item = {"claim": claim}
            elif isinstance(claim, dict):
                item = dict(claim)
            else:
                continue
            text = str(item.get("claim") or item.get("title") or "").strip()
            if not text:
                continue
            kind = str(item.get("kind") or item.get("type") or "hypothesis").lower()
            target = facts if kind == "fact" else failures if kind == "failure" else hypotheses
            item.setdefault("evidence", {"run_id": run_id, "run_dir": str(run_dir), "beam_node": beam_node, "beam_result_index": idx})
            item.setdefault("scope", [goal_id, "beam", str(beam_node.get("beam_id"))])
            item.setdefault("confidence", 0.7)
            target.append(item)
        for idx, child in enumerate(beam_result.get("next_directions", []) or []):
            title = child.get("title") if isinstance(child, dict) else str(child)
            if title:
                tasks.append({
                    "task_id": f"beam-next-{goal_id}-{run_id}-{idx}",
                    "source": "beam-result",
                    "goal_id": goal_id,
                    "title": f"Beam next direction: {title}",
                    "reason": "A beam sub-session proposed this next branch direction.",
                    "run_id": run_id,
                    "run_dir": str(run_dir),
                    "priority": "P2",
                })

    if status == "PASSED":
        facts.append(
            {
                "claim": f"Goal {goal_id} passed deterministic verification.",
                "evidence": {
                    "run_id": run_id,
                    "run_dir": str(run_dir),
                    "commands": [c.get("command") for c in (verifier or {}).get("commands", [])],
                    "monitors": [m.get("monitor_id") for m in (verifier or {}).get("monitors", [])],
                },
                "scope": [goal_id],
                "confidence": 0.95,
            }
        )
    elif status in {"FAILED", "NEEDS_HUMAN", "UNCERTAIN"}:
        if verifier:
            failed = [c for c in verifier.get("commands", []) if c.get("exit_code") != 0]
            if failed:
                for cmd in failed:
                    sig_text = cmd.get("command", "") + "\n" + truncate_middle(cmd.get("stderr", "") + cmd.get("stdout", ""), 2000)
                    failures.append(
                        {
                            "claim": f"Goal {goal_id} failed command: {cmd.get('command')}",
                            "signature": sha256_text(sig_text),
                            "evidence": {
                                "run_id": run_id,
                                "run_dir": str(run_dir),
                                "round": verifier.get("round"),
                                "command": cmd.get("command"),
                                "exit_code": cmd.get("exit_code"),
                                "stdout_tail": truncate_middle(cmd.get("stdout", ""), 1200),
                                "stderr_tail": truncate_middle(cmd.get("stderr", ""), 1200),
                            },
                            "scope": [goal_id],
                            "confidence": 0.85,
                        }
                    )
            for mon in verifier.get("monitors", []):
                if mon.get("status") != "PASSED":
                    failures.append(
                        {
                            "claim": f"Goal {goal_id} monitor {mon.get('monitor_id')} returned {mon.get('status')}",
                            "signature": mon.get("signature") or sha256_text(str(mon)),
                            "evidence": {
                                "run_id": run_id,
                                "run_dir": str(run_dir),
                                "round": verifier.get("round"),
                                "monitor_id": mon.get("monitor_id"),
                                "status": mon.get("status"),
                                "summary": mon.get("summary"),
                                "metrics": mon.get("metrics"),
                                "mismatches_sample": mon.get("mismatches", [])[:10],
                            },
                            "scope": [goal_id, str(mon.get("monitor_id"))],
                            "confidence": 0.9,
                        }
                    )
            if verifier.get("violations"):
                for violation in verifier["violations"]:
                    failures.append(
                        {
                            "claim": f"Goal {goal_id} violated verifier constraint: {violation.get('type')}",
                            "signature": sha256_text(str(violation)),
                            "evidence": {"run_id": run_id, "run_dir": str(run_dir), "violation": violation},
                            "scope": [goal_id],
                            "confidence": 0.9,
                        }
                    )
            if status == "UNCERTAIN":
                hypotheses.append(
                    {
                        "claim": f"Goal {goal_id} requires human judgment because deterministic verification was uncertain.",
                        "evidence": {"run_id": run_id, "run_dir": str(run_dir), "warnings": verifier.get("warnings", [])},
                        "scope": [goal_id],
                        "confidence": 0.6,
                    }
                )
        tasks.append(
            {
                "task_id": f"human-review-{goal_id}-{run_id}",
                "source": "sisyfus-distill",
                "goal_id": goal_id,
                "title": f"Human review needed for {goal_id}: {status}",
                "reason": final.get("reason") or f"Run ended with status {status}",
                "run_id": run_id,
                "run_dir": str(run_dir),
                "priority": "P2" if status == "FAILED" else "P1",
            }
        )

    distill = {
        "schema_version": "sisyfus.distill.v0.6",
        "created_at": utc_now(),
        "run_id": run_id,
        "goal_id": goal_id,
        "status": status,
        "facts": facts,
        "failures": failures,
        "hypotheses": hypotheses,
        "tasks": tasks,
        "event_count": len(events),
        "model_routes": final.get("model_routes", {}),
        "beam": beam_node if isinstance(beam_node, dict) else {},
        "beam_result": beam_result,
        "task_type": final.get("task_type") or goal.get("task_type"),
        "session_id": final.get("session_id") or run_id,
        "beam_node": final.get("beam_node"),
        "beam_id": (final.get("beam_node") or {}).get("beam_id") if final.get("beam_node") else None,
        "beam_node_id": (final.get("beam_node") or {}).get("node_id") if final.get("beam_node") else None,
    }
    write_json(run_dir / "distill.json", distill)
    return distill
