from __future__ import annotations

from pathlib import Path
from typing import Any

from .paths import ensure_layout, find_project_root
from .utils import append_jsonl, read_json, read_jsonl, run_process, sha256_text, slugify, utc_now, write_json


MEMORY_STATES = [
    "failure_note",
    "investigation",
    "verified_fact",
    "general_rule",
    "consulted_rule",
    "retired",
    "stale",
    "contradicted",
]


class MemoryFSMStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = find_project_root(root)
        self.sf = ensure_layout(self.root)
        self.dir = self.sf / "memory_fsm"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "items.jsonl"
        self.events_path = self.dir / "events.jsonl"

    def list(self, *, state: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        items = read_jsonl(self.path)
        # latest state per memory_id
        latest: dict[str, dict[str, Any]] = {}
        for item in items:
            latest[str(item.get("memory_id"))] = item
        out = list(reversed(list(latest.values())))
        if state:
            out = [x for x in out if x.get("state") == state]
        return out[:limit]

    def get(self, memory_id: str) -> dict[str, Any]:
        for item in reversed(read_jsonl(self.path)):
            if item.get("memory_id") == memory_id:
                return item
        raise FileNotFoundError(f"Memory FSM item not found: {memory_id}")

    def add(self, *, state: str, claim: str, domain: str = "project", evidence: dict[str, Any] | None = None, source: str = "manual", confidence: float = 0.6, general_rule: str | None = None) -> dict[str, Any]:
        if state not in MEMORY_STATES:
            raise ValueError(f"invalid memory state {state!r}; expected one of {MEMORY_STATES}")
        mid = f"mem_{sha256_text(claim + domain)[-12:]}"
        item = {
            "schema_version": "sisyfus.memory_fsm.v0.6",
            "memory_id": mid,
            "state": state,
            "domain": domain,
            "claim": claim,
            "evidence": evidence or {},
            "general_rule": general_rule,
            "confidence": confidence,
            "source": source,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "consulted_by": [],
            "history": [{"state": state, "at": utc_now(), "source": source}],
        }
        append_jsonl(self.path, item)
        write_json(self.dir / f"{slugify(mid)}.json", item)
        append_jsonl(self.events_path, {"ts": utc_now(), "event": "memory.added", "memory_id": mid, "state": state, "source": source})
        return item

    def transition(self, memory_id: str, *, state: str, note: str = "", evidence: dict[str, Any] | None = None, general_rule: str | None = None, consulted_by: str | None = None) -> dict[str, Any]:
        if state not in MEMORY_STATES:
            raise ValueError(f"invalid memory state {state!r}; expected one of {MEMORY_STATES}")
        item = dict(self.get(memory_id))
        hist = list(item.get("history", []))
        hist.append({"state": state, "at": utc_now(), "note": note, "evidence": evidence or {}})
        item.update({"state": state, "updated_at": utc_now(), "history": hist})
        if evidence:
            old = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
            item["evidence"] = {**old, **evidence}
        if general_rule:
            item["general_rule"] = general_rule
        if consulted_by:
            consulted = list(item.get("consulted_by") or [])
            if consulted_by not in consulted:
                consulted.append(consulted_by)
            item["consulted_by"] = consulted
        append_jsonl(self.path, item)
        write_json(self.dir / f"{slugify(memory_id)}.json", item)
        append_jsonl(self.events_path, {"ts": utc_now(), "event": "memory.transition", "memory_id": memory_id, "state": state, "note": note})
        return item

    def ingest_distill(self, distill: dict[str, Any]) -> dict[str, Any]:
        counts = {"failure_note": 0, "verified_fact": 0, "investigation": 0}
        run_id = str(distill.get("run_id") or "")
        goal_id = str(distill.get("goal_id") or "")
        for f in distill.get("failures", []) or []:
            claim = str(f.get("claim") or "").strip()
            if claim:
                self.add(state="failure_note", claim=claim, domain=goal_id or "project", evidence={"run_id": run_id, "distill": f}, source="distill", confidence=float(f.get("confidence", 0.65) or 0.65))
                counts["failure_note"] += 1
        for fact in distill.get("facts", []) or []:
            claim = str(fact.get("claim") or "").strip()
            if claim:
                self.add(state="verified_fact", claim=claim, domain=goal_id or "project", evidence={"run_id": run_id, "distill": fact}, source="distill", confidence=float(fact.get("confidence", 0.8) or 0.8))
                counts["verified_fact"] += 1
        for h in distill.get("hypotheses", []) or []:
            claim = str(h.get("claim") or "").strip()
            if claim:
                self.add(state="investigation", claim=claim, domain=goal_id or "project", evidence={"run_id": run_id, "distill": h}, source="distill", confidence=float(h.get("confidence", 0.5) or 0.5))
                counts["investigation"] += 1
        return counts

    def verify(self, memory_id: str, *, command: str, workdir: str | Path | None = None, timeout: int = 600) -> dict[str, Any]:
        proc = run_process(command, cwd=Path(workdir or self.root).resolve(), timeout=timeout, shell=True)
        state = "verified_fact" if int(proc.get("exit_code", 1)) == 0 else "investigation"
        item = self.transition(memory_id, state=state, note=f"verification command {'passed' if state == 'verified_fact' else 'failed'}: {command}", evidence={"verification_command": command, "result": proc})
        return {"status": "PASSED" if state == "verified_fact" else "FAILED", "memory": item, "command_result": proc}

    def promote(self, memory_id: str, *, rule: str | None = None) -> dict[str, Any]:
        item = self.get(memory_id)
        general_rule = rule or item.get("general_rule") or item.get("claim")
        return self.transition(memory_id, state="general_rule", note="promoted to reusable general rule", general_rule=general_rule)

    def consult(self, memory_id: str, *, run_id: str) -> dict[str, Any]:
        return self.transition(memory_id, state="consulted_rule", note=f"consulted by {run_id}", consulted_by=run_id)

    def coverage(self) -> dict[str, Any]:
        items = self.list(limit=100000)
        by_state = {s: 0 for s in MEMORY_STATES}
        for item in items:
            by_state[str(item.get("state"))] = by_state.get(str(item.get("state")), 0) + 1
        total = len(items)
        verifiedish = by_state.get("verified_fact", 0) + by_state.get("general_rule", 0) + by_state.get("consulted_rule", 0)
        consulted = by_state.get("consulted_rule", 0)
        return {
            "schema_version": "sisyfus.memory_coverage.v0.6",
            "total": total,
            "by_state": by_state,
            "verified_memory_coverage": (verifiedish / total) if total else 0.0,
            "consult_rate": (consulted / total) if total else 0.0,
            "open_failure_notes": by_state.get("failure_note", 0) + by_state.get("investigation", 0),
        }


def memory_learning_context(root: str | Path | None = None, *, max_chars: int = 12000) -> str:
    store = MemoryFSMStore(root)
    items = store.list(limit=200)
    if not items:
        return ""
    lines = ["# Verified Sisyfus memory lifecycle context", "", "Prefer verified facts and general rules over raw failure notes.", ""]
    for item in items:
        if item.get("state") in {"verified_fact", "general_rule", "consulted_rule"}:
            lines.append(f"- [{item.get('state')}] {item.get('claim')}")
            if item.get("general_rule"):
                lines.append(f"  rule: {item.get('general_rule')}")
    text = "\n".join(lines)
    return text[:max_chars]
