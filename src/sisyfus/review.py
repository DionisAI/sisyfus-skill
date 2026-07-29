from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .paths import ensure_layout
from .session import list_sessions
from .utils import append_jsonl, read_json, read_jsonl, truncate_middle, utc_now, write_json

ALLOWED_VERDICTS = {"correct", "wrong", "uncertain", "needs_followup", "accepted", "rejected", "stale", "direction"}


def stable_id(prefix: str, *parts: Any, length: int = 16) -> str:
    raw = "\u241f".join(str(p) for p in parts)
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:length]
    return f"{prefix}_{digest}"


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _resolve_under_root(root: Path, rel_or_abs: str | Path) -> Path:
    path = Path(rel_or_abs)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


class ReviewStore:
    """Append-only human review and guidance layer for Sisyfus."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.sf = ensure_layout(self.root)
        self.review_dir.mkdir(parents=True, exist_ok=True)
        for name in ["annotations.jsonl", "guidance.jsonl"]:
            path = self.review_dir / name
            if not path.exists():
                path.write_text("", encoding="utf-8")

    @property
    def review_dir(self) -> Path:
        return self.sf / "reviews"

    @property
    def annotations_path(self) -> Path:
        return self.review_dir / "annotations.jsonl"

    @property
    def guidance_path(self) -> Path:
        return self.review_dir / "guidance.jsonl"

    def annotations(self) -> list[dict[str, Any]]:
        return read_jsonl(self.annotations_path)

    def guidance(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        items = read_jsonl(self.guidance_path)
        if not include_archived:
            items = [x for x in items if x.get("status", "active") == "active"]
        return list(reversed(items))

    def latest_annotations_by_target(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for item in self.annotations():
            target_id = str(item.get("target_id") or "")
            if target_id:
                latest[target_id] = item
        return latest

    def annotate(self, *, target_id: str, verdict: str, note: str = "", target_type: str = "claim", run_id: str | None = None, goal_id: str | None = None, claim: str | None = None, next_action: str | None = None, created_by: str = "human", create_task: bool = False) -> dict[str, Any]:
        target_id = target_id.strip()
        if not target_id:
            raise ValueError("target_id cannot be empty")
        verdict = verdict.strip().lower()
        if verdict not in ALLOWED_VERDICTS:
            raise ValueError(f"Invalid verdict {verdict!r}. Allowed: {sorted(ALLOWED_VERDICTS)}")
        item = {
            "schema_version": "sisyfus.annotation.v0.6",
            "annotation_id": stable_id("ann", utc_now(), target_id, verdict, note, length=20),
            "created_at": utc_now(),
            "created_by": created_by,
            "target_type": target_type,
            "target_id": target_id,
            "run_id": run_id,
            "goal_id": goal_id,
            "claim": claim,
            "verdict": verdict,
            "note": note,
            "next_action": next_action,
        }
        append_jsonl(self.annotations_path, item)
        write_json(self.review_dir / "latest_annotation.json", item)
        if create_task or verdict in {"wrong", "uncertain", "needs_followup", "stale"}:
            if next_action or create_task:
                from .storage import MemoryBroker
                MemoryBroker(self.root).append_open_task({
                    "task_id": f"human-review-{item['annotation_id']}",
                    "source": "human-review",
                    "title": truncate_middle(next_action or note or claim or f"Review {target_type} {target_id}", 140),
                    "reason": "Human review marked an AI conclusion/session as needing action.",
                    "priority": "P1" if verdict in {"wrong", "stale"} else "P2",
                    "goal_id": goal_id,
                    "run_id": run_id,
                    "target_type": target_type,
                    "target_id": target_id,
                    "verdict": verdict,
                    "annotation_id": item["annotation_id"],
                })
        return item

    def add_guidance(self, text: str, *, scope: str = "project", goal_id: str | None = None, run_id: str | None = None, priority: str = "P2", tags: list[str] | None = None, created_by: str = "human", create_task: bool = False) -> dict[str, Any]:
        text = text.strip()
        if not text:
            raise ValueError("guidance text cannot be empty")
        item = {
            "schema_version": "sisyfus.guidance.v0.6",
            "guidance_id": stable_id("gdn", utc_now(), scope, goal_id or "", run_id or "", text, length=20),
            "created_at": utc_now(),
            "created_by": created_by,
            "status": "active",
            "scope": scope,
            "goal_id": goal_id,
            "run_id": run_id,
            "priority": priority,
            "tags": tags or [],
            "text": text,
        }
        append_jsonl(self.guidance_path, item)
        write_json(self.review_dir / "latest_guidance.json", item)
        if create_task:
            from .storage import MemoryBroker
            MemoryBroker(self.root).append_open_task({"task_id": f"human-guidance-{item['guidance_id']}", "source": "human-guidance", "title": truncate_middle(text, 140), "reason": "Human supplied guidance for a future Sisyfus session.", "priority": priority, "goal_id": goal_id, "run_id": run_id, "guidance_id": item["guidance_id"]})
        return item

    def claims(self, *, limit_sessions: int | None = None) -> list[dict[str, Any]]:
        annotations = self.latest_annotations_by_target()
        claims: list[dict[str, Any]] = []
        for session in reversed(list_sessions(self.root, limit=limit_sessions)):
            distill_path = _resolve_under_root(self.root, str(session.get("distill_path", "")))
            if not distill_path.exists():
                continue
            try:
                distill = read_json(distill_path)
            except Exception:
                continue
            run_id = str(distill.get("run_id") or session.get("run_id") or "")
            goal_id = str(distill.get("goal_id") or session.get("goal_id") or "")
            task_type = distill.get("task_type") or session.get("task_type")
            for key, singular in [("facts", "fact"), ("failures", "failure"), ("hypotheses", "hypothesis"), ("tasks", "task")]:
                for idx, item in enumerate(distill.get(key, []) or []):
                    if not isinstance(item, dict):
                        continue
                    claim_text = str(item.get("claim") or item.get("title") or item.get("reason") or "").strip()
                    if not claim_text:
                        continue
                    claim_id = stable_id("clm", run_id, goal_id, singular, idx, claim_text)
                    ann = annotations.get(claim_id)
                    claims.append({"schema_version": "sisyfus.claim.v0.6", "claim_id": claim_id, "target_id": claim_id, "kind": singular, "claim": claim_text, "run_id": run_id, "goal_id": goal_id, "task_type": task_type, "session_status": distill.get("status") or session.get("status"), "confidence": item.get("confidence"), "scope": item.get("scope", []), "evidence": item.get("evidence", {}), "beam": distill.get("beam") or session.get("beam"), "beam_id": (distill.get("beam") or session.get("beam") or {}).get("beam_id") if isinstance(distill.get("beam") or session.get("beam"), dict) else None, "beam_node_id": (distill.get("beam") or session.get("beam") or {}).get("node_id") if isinstance(distill.get("beam") or session.get("beam"), dict) else None, "source_distill_path": _rel(self.root, distill_path), "beam_id": distill.get("beam_id") or session.get("beam_id"), "beam_node_id": distill.get("beam_node_id") or session.get("beam_node_id"), "beam_node": distill.get("beam_node") or session.get("beam_node"), "created_at": distill.get("created_at") or session.get("created_at"), "human_verdict": ann.get("verdict") if ann else "unreviewed", "human_note": ann.get("note") if ann else "", "latest_annotation": ann})
        return list(reversed(claims))

    def sessions_with_review(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        annotations = self.latest_annotations_by_target()
        out: list[dict[str, Any]] = []
        for item in list_sessions(self.root, limit=limit):
            run_id = str(item.get("run_id") or item.get("session_id") or "")
            ann = annotations.get(run_id)
            enriched = dict(item)
            enriched["human_verdict"] = ann.get("verdict") if ann else "unreviewed"
            enriched["human_note"] = ann.get("note") if ann else ""
            enriched["latest_annotation"] = ann
            out.append(enriched)
        return out

    def load_run_detail(self, run_id: str) -> dict[str, Any]:
        sessions = [s for s in list_sessions(self.root, limit=None) if s.get("run_id") == run_id or s.get("session_id") == run_id]
        if not sessions:
            direct = self.sf / "runs" / run_id
            if not direct.exists():
                raise FileNotFoundError(f"No session/run found for {run_id}")
            sessions = [{"run_id": run_id, "run_dir": _rel(self.root, direct)}]
        session = sessions[0]
        run_dir = _resolve_under_root(self.root, str(session.get("run_dir", "")))
        detail: dict[str, Any] = {"session": session, "run_id": run_id, "run_dir": _rel(self.root, run_dir)}
        for name in ["final.json", "distill.json", "session.index_item.json", "model_routes.json", "session_policy.json"]:
            path = run_dir / name
            if path.exists():
                try:
                    detail[name.replace(".json", "").replace(".", "_")] = read_json(path)
                except Exception as exc:
                    detail[name] = {"error": str(exc)}
        for name in ["report.md", "session.compact.md", "loaded-context.txt"]:
            path = run_dir / name
            if path.exists():
                detail[name.replace(".", "_")] = truncate_middle(path.read_text(encoding="utf-8", errors="replace"), 40000)
        detail["events"] = read_jsonl(run_dir / "events.jsonl")[-300:]
        detail["claims"] = [c for c in self.claims(limit_sessions=None) if c.get("run_id") == run_id]
        detail["human_session_annotation"] = self.latest_annotations_by_target().get(run_id)
        # UI-friendly aliases.
        detail["compact"] = detail.get("session_compact_md", "")
        detail["report"] = detail.get("report_md", "")
        detail["human_feedback"] = detail.get("human_session_annotation")
        return detail

    def summary(self) -> dict[str, Any]:
        sessions = self.sessions_with_review(limit=None)
        claims = self.claims(limit_sessions=None)
        guidance = self.guidance()
        verdict_counts: dict[str, int] = {}
        for claim in claims:
            verdict = str(claim.get("human_verdict") or "unreviewed")
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        session_status_counts: dict[str, int] = {}
        for session in sessions:
            status = str(session.get("status") or "UNKNOWN")
            session_status_counts[status] = session_status_counts.get(status, 0) + 1
        return {"schema_version": "sisyfus.review_summary.v0.6", "created_at": utc_now(), "session_count": len(sessions), "claim_count": len(claims), "active_guidance_count": len(guidance), "claim_verdict_counts": verdict_counts, "session_status_counts": session_status_counts}


def load_review_context(root: str | Path, *, max_chars: int = 10000) -> str:
    store = ReviewStore(root)
    guidance = store.guidance()[:20]
    correct = [c for c in store.claims() if c.get("human_verdict") in {"correct", "accepted"}][:20]
    wrong = [c for c in store.claims() if c.get("human_verdict") in {"wrong", "rejected", "stale"}][:20]
    uncertain = [c for c in store.claims() if c.get("human_verdict") in {"uncertain", "needs_followup"}][:12]
    lines = ["# Human Review Context", "", "Human judgments override agent self-assessments when relevant. Wrong conclusions are constraints, not reusable context.", "", "## Active human guidance"]
    if guidance:
        for g in guidance:
            prefix = f"[{g.get('priority')}] {g.get('scope')}"
            if g.get("goal_id"):
                prefix += f" goal={g.get('goal_id')}"
            lines.append(f"- {prefix}: {g.get('text')}")
    else:
        lines.append("- none")
    lines += ["", "## Human-confirmed correct conclusions"]
    lines += [f"- `{c.get('goal_id')}` {c.get('kind')}: {c.get('claim')} NOTE: {c.get('human_note') or ''}" for c in correct] or ["- none"]
    lines += ["", "## Human-rejected wrong conclusions"]
    lines += [f"- `{c.get('goal_id')}` {c.get('kind')}: {c.get('claim')} NOTE: {c.get('human_note') or ''}" for c in wrong] or ["- none"]
    lines += ["", "## Human-marked uncertain / follow-up conclusions"]
    lines += [f"- `{c.get('goal_id')}` {c.get('kind')}: {c.get('claim')} NOTE: {c.get('human_note') or ''}" for c in uncertain] or ["- none"]
    return truncate_middle("\n".join(lines) + "\n", max_chars)
