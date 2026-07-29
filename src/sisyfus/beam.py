from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .distill import make_distill
from .goal import deep_merge, load_goal
from .orchestrator import SisyfusRunner
from .paths import ensure_layout, find_project_root
from .review import ReviewStore
from .utils import append_jsonl, read_json, read_jsonl, run_id as make_run_id, slugify, truncate_middle, utc_now, write_json


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _resolve(root: Path, rel_or_abs: str | Path) -> Path:
    p = Path(rel_or_abs)
    return (root / p).resolve() if not p.is_absolute() else p.resolve()


def _directions(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        inner = value.get("directions") or value.get("children") or value.get("branches")
        return _directions(inner)
    return []


def _priority_key(d: dict[str, Any]) -> tuple[int, str]:
    rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}.get(str(d.get("priority") or "P2").upper(), 5)
    return (rank, str(d.get("id") or d.get("title") or d.get("objective") or ""))


def _score(final: dict[str, Any], distill: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    explicit = run_dir / "score.json"
    if explicit.exists():
        try:
            raw = read_json(explicit)
            if isinstance(raw, dict):
                return {"score": float(raw.get("score", 0.0)), "source": "score.json", "detail": raw}
        except Exception as exc:  # noqa: BLE001
            return {"score": -0.25, "source": "score.json_error", "detail": {"error": str(exc)}}
    status = str(final.get("status") or distill.get("status") or "UNKNOWN")
    base = {"PASSED": 1.0, "UNCERTAIN": 0.1, "NEEDS_HUMAN": -0.1, "FAILED": -1.0}.get(status, -0.25)
    facts, fails, hyps, tasks = (len(distill.get(k, []) or []) for k in ["facts", "failures", "hypotheses", "tasks"])
    val = base + 0.05 * facts + 0.02 * hyps - 0.12 * fails - 0.02 * tasks
    return {"score": round(val, 6), "source": "default_status_distill_score", "detail": {"status": status, "facts": facts, "failures": fails, "hypotheses": hyps, "tasks": tasks}}


def _distill_summary(distill: dict[str, Any]) -> str:
    out: list[str] = []
    for key in ["facts", "failures", "hypotheses", "tasks"]:
        items = distill.get(key, []) or []
        if not items:
            continue
        first = items[0]
        text = first.get("claim") or first.get("title") or first.get("reason") or ""
        out.append(f"{key}={len(items)} first={truncate_middle(str(text), 180)}")
    return "; ".join(out)


def _normalize_direction(raw: dict[str, Any], *, index: int, depth: int, parent: str) -> dict[str, Any]:
    title = str(raw.get("title") or raw.get("name") or raw.get("id") or f"branch-{index}").strip()
    objective = str(raw.get("objective") or raw.get("prompt") or raw.get("direction") or title).strip()
    did = slugify(str(raw.get("id") or title), default=f"branch-{index}")
    return {"id": did, "title": title, "objective": objective, "task_type": raw.get("task_type"), "priority": raw.get("priority", "P2"), "depth": depth, "parent_node_id": parent, "raw": raw}


def _child_goal(base: dict[str, Any], direction: dict[str, Any], *, beam_id: str, node_id: str, parent: str, depth: int, path: list[str]) -> dict[str, Any]:
    raw = copy.deepcopy(direction.get("raw") or {})
    override = {k: raw[k] for k in ["context", "session_policy", "constraints", "done_when", "monitors", "loop", "worktree", "model_policy", "agents", "outputs"] if k in raw}
    goal = deep_merge(copy.deepcopy(base), override)
    goal["id"] = slugify(str(raw.get("goal_id") or f"{base.get('id', 'beam')}-{node_id}"), default=node_id)
    goal["objective"] = f"[Beam branch {node_id}; depth {depth}; direction {direction['id']}]\n{direction['objective']}\n\nStay inside this branch. If new research directions appear, write them to `beam_result.json` as `next_directions` or to `beam.children.json` in the run directory instead of doing them in this session."
    if raw.get("task_type") or direction.get("task_type"):
        goal["task_type"] = raw.get("task_type") or direction.get("task_type")
    goal["beam"] = {"enabled": False}
    goal["beam_node"] = {"schema_version": "sisyfus.beam_node.v0.6", "beam_id": beam_id, "node_id": node_id, "parent_node_id": parent, "depth": depth, "direction_id": direction["id"], "title": direction["title"], "branch_path": path}
    return goal


def _load_child_directions(run_dir: Path) -> list[dict[str, Any]]:
    for name in ["beam_result.json", "beam.children.json", "beam_children.json", "children.json"]:
        p = run_dir / name
        if p.exists():
            try:
                data = read_json(p)
                if name == "beam_result.json" and isinstance(data, dict):
                    data = data.get("next_directions") or data.get("directions") or data.get("children") or data.get("branches") or []
                return sorted(_directions(data), key=_priority_key)
            except Exception:
                return []
    return []


class BeamStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = find_project_root(root)
        self.sf = ensure_layout(self.root)
        self.beams_dir.mkdir(parents=True, exist_ok=True)

    @property
    def beams_dir(self) -> Path:
        return self.sf / "beams"

    def beam_dir(self, beam_id: str) -> Path:
        return self.beams_dir / beam_id

    def append_index(self, item: dict[str, Any]) -> None:
        append_jsonl(self.beams_dir / "index.jsonl", item)
        write_json(self.beams_dir / "latest.json", item)

    def list_beams(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        items = list(reversed(read_jsonl(self.beams_dir / "index.jsonl")))
        return items[:limit] if limit is not None else items

    def load_beam(self, beam_id: str) -> dict[str, Any]:
        bdir = self.beam_dir(beam_id)
        if not bdir.exists():
            # Allow lookup by index selector if a caller passes a stale/generated id.
            for item in self.list_beams(limit=None):
                if item.get("beam_id") == beam_id:
                    bdir = self.root / str(item.get("beam_dir"))
                    break
        if not bdir.exists():
            raise FileNotFoundError(f"No beam found: {beam_id}")
        meta = read_json(bdir / "beam.json") if (bdir / "beam.json").exists() else {"beam_id": beam_id}
        nodes = read_jsonl(bdir / "nodes.jsonl")
        edges = read_jsonl(bdir / "edges.jsonl")
        events = read_jsonl(bdir / "events.jsonl")
        summary = read_json(bdir / "summary.json") if (bdir / "summary.json").exists() else {}
        annotations = ReviewStore(self.root).latest_annotations_by_target()
        enriched: list[dict[str, Any]] = []
        for node in nodes:
            n = dict(node)
            ann = annotations.get(str(n.get("node_id") or "")) or annotations.get(str(n.get("run_id") or ""))
            n["human_verdict"] = ann.get("verdict") if ann else "unreviewed"
            n["human_note"] = ann.get("note") if ann else ""
            enriched.append(n)
        return {"schema_version": "sisyfus.beam_detail.v0.6", "beam": meta, "summary": summary, "nodes": enriched, "edges": edges, "events": events, "beam_dir": _rel(self.root, bdir)}

    def build_context(self, beam_id: str, *, max_chars: int = 30000) -> str:
        detail = self.load_beam(beam_id)
        beam = detail.get("beam", {})
        nodes = detail.get("nodes", [])
        lines = ["# Sisyfus Beam Context", "", f"Beam: `{beam.get('beam_id') or beam_id}`", f"Goal: `{beam.get('goal_id', '-')}`", f"Objective: {beam.get('objective', '-')}", f"Status: **{detail.get('summary', {}).get('status', beam.get('status', 'UNKNOWN'))}**", "", "## Branch scoreboard"]
        for node in sorted(nodes, key=lambda n: (int(n.get("depth") or 0), -float((n.get("score") or {}).get("score", 0.0) if isinstance(n.get("score"), dict) else n.get("score", 0.0) or 0.0)))[:80]:
            val = (node.get("score") or {}).get("score") if isinstance(node.get("score"), dict) else node.get("score")
            lines.append(f"- depth `{node.get('depth')}` node `{node.get('node_id')}` status `{node.get('status')}` score `{val}` human `{node.get('human_verdict', 'unreviewed')}`: {node.get('title') or node.get('objective')}")
            if node.get("distill_summary"):
                lines.append(f"  - distill: {node.get('distill_summary')}")
        lines += ["", "## Compact branch summaries"]
        for node in nodes[:60]:
            cp = node.get("compact_path")
            if cp:
                p = _resolve(self.root, cp)
                if p.exists():
                    lines.append(f"\n### Node `{node.get('node_id')}` / run `{node.get('run_id')}`")
                    lines.append(truncate_middle(p.read_text(encoding="utf-8", errors="replace"), 3000))
        return truncate_middle("\n".join(lines) + "\n", max_chars)


class BeamRunner:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = find_project_root(root)
        self.sf = ensure_layout(self.root)
        self.store = BeamStore(self.root)

    def run(self, goal_path: str | Path, *, adapter_name: str = "mock", agent_command: str | None = None, apply_distill: bool = False) -> dict[str, Any]:
        goal = load_goal(goal_path)
        cfg = dict(goal.get("beam") or {})
        if cfg.get("enabled") is False:
            raise ValueError("GoalSpec beam.enabled is false. Use `sisyfus run` for a normal single-session goal.")
        base_beam_id = slugify(str(cfg.get("id") or make_run_id("beam-")), default=make_run_id("beam-"))
        beam_id = base_beam_id
        bdir = self.store.beam_dir(beam_id)
        if bdir.exists():
            beam_id = slugify(f"{base_beam_id}-{make_run_id()}", default=make_run_id("beam-"))
            bdir = self.store.beam_dir(beam_id)
        bdir.mkdir(parents=True, exist_ok=False)
        (bdir / "goals").mkdir(exist_ok=True)
        max_depth = max(1, int(cfg.get("max_depth", 1) or 1))
        width = max(1, int(cfg.get("width", 3) or 3))
        max_children = max(1, int(cfg.get("max_children_per_node", width) or width))
        max_sessions = max(1, int(cfg.get("max_sessions_total", cfg.get("max_total_sessions", width * max_depth)) or width * max_depth))
        seed_dirs = sorted(_directions(cfg.get("directions") or cfg.get("branches")), key=_priority_key)
        if not seed_dirs:
            raise ValueError("Beam GoalSpec requires beam.directions with at least one branch direction.")

        meta = {"schema_version": "sisyfus.beam.v0.6", "created_at": utc_now(), "beam_id": beam_id, "goal_id": goal["id"], "objective": goal.get("objective"), "goal_path": str(goal_path), "beam_dir": _rel(self.root, bdir), "status": "RUNNING", "budget": {"max_depth": max_depth, "width": width, "max_children_per_node": max_children, "max_sessions_total": max_sessions}, "adapter": adapter_name, "apply_distill": apply_distill}
        write_json(bdir / "beam.json", meta)
        write_json(bdir / "goal.normalized.json", goal)
        append_jsonl(bdir / "events.jsonl", {"ts": utc_now(), "event": "beam.started", "beam_id": beam_id, "status": "RUNNING", "data": meta})
        root = {"schema_version": "sisyfus.beam_node.v0.6", "created_at": utc_now(), "beam_id": beam_id, "node_id": "root", "parent_node_id": None, "depth": 0, "direction_id": "root", "title": "root coordinator", "objective": goal.get("objective"), "status": "ROOT", "score": {"score": 0.0, "source": "root"}, "branch_path": ["root"]}
        append_jsonl(bdir / "nodes.jsonl", root)
        all_nodes = [root]
        active = [root]
        dirs_by_parent: dict[str, list[dict[str, Any]]] = {"root": seed_dirs}
        session_count = 0
        reason = "completed max depth or exhausted branches"

        for depth in range(1, max_depth + 1):
            specs: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for parent in active:
                pid = str(parent.get("node_id"))
                for i, raw in enumerate(dirs_by_parent.get(pid, [])[:max_children], start=1):
                    specs.append((parent, _normalize_direction(raw, index=i, depth=depth, parent=pid)))
            specs = specs[: min(width, max_sessions - session_count)]
            if not specs:
                reason = "no child directions available"
                break
            layer: list[dict[str, Any]] = []
            append_jsonl(bdir / "events.jsonl", {"ts": utc_now(), "event": "beam.depth_started", "beam_id": beam_id, "status": "RUNNING", "depth": depth, "data": {"candidate_count": len(specs)}})
            for local_i, (parent, direction) in enumerate(specs, start=1):
                parent_id = str(parent.get("node_id"))
                node_id = slugify(f"d{depth}-{parent_id}-{direction['id']}-{local_i}", default=f"d{depth}-{local_i}")
                path = list(parent.get("branch_path") or [parent_id]) + [node_id]
                child = _child_goal(goal, direction, beam_id=beam_id, node_id=node_id, parent=parent_id, depth=depth, path=path)
                child_path = bdir / "goals" / f"{node_id}.json"
                write_json(child_path, child)
                append_jsonl(bdir / "edges.jsonl", {"schema_version": "sisyfus.beam_edge.v0.6", "created_at": utc_now(), "beam_id": beam_id, "parent_node_id": parent_id, "child_node_id": node_id, "depth": depth, "direction_id": direction["id"]})
                append_jsonl(bdir / "events.jsonl", {"ts": utc_now(), "event": "beam.branch_started", "beam_id": beam_id, "node_id": node_id, "parent_node_id": parent_id, "depth": depth, "status": "RUNNING", "data": {"title": direction["title"]}})
                final = SisyfusRunner(self.root).run(child_path, adapter_name=adapter_name, agent_command=agent_command, apply_distill=apply_distill)
                run_dir = Path(final["run_dir"])
                distill = make_distill(run_dir)
                sc = _score(final, distill, run_dir)
                node = {"schema_version": "sisyfus.beam_node.v0.6", "created_at": utc_now(), "beam_id": beam_id, "node_id": node_id, "parent_node_id": parent_id, "depth": depth, "direction_id": direction["id"], "title": direction["title"], "objective": direction["objective"], "task_type": final.get("task_type") or child.get("task_type"), "status": final.get("status"), "reason": final.get("reason"), "score": sc, "run_id": final.get("run_id"), "run_dir": _rel(self.root, run_dir), "goal_path": _rel(self.root, child_path), "compact_path": _rel(self.root, run_dir / "session.compact.md"), "distill_path": _rel(self.root, run_dir / "distill.json"), "model_routes": final.get("model_routes", {}), "usage": (final.get("session_record") or {}).get("usage", {}), "distill_summary": _distill_summary(distill), "branch_path": path}
                append_jsonl(bdir / "nodes.jsonl", node)
                all_nodes.append(node); layer.append(node); session_count += 1
                children = _load_child_directions(run_dir)
                if children:
                    dirs_by_parent[node_id] = children
                append_jsonl(bdir / "events.jsonl", {"ts": utc_now(), "event": "beam.branch_finished", "beam_id": beam_id, "node_id": node_id, "depth": depth, "status": node["status"], "data": {"score": sc, "child_direction_count": len(children)}})
                if session_count >= max_sessions:
                    reason = "max_sessions_total reached"
                    break
            active = sorted(layer, key=lambda n: float((n.get("score") or {}).get("score", 0.0)), reverse=True)[:width]
            append_jsonl(bdir / "events.jsonl", {"ts": utc_now(), "event": "beam.depth_finished", "beam_id": beam_id, "status": "RUNNING", "depth": depth, "data": {"survivors": [n["node_id"] for n in active]}})
            if session_count >= max_sessions:
                break

        non_root = [n for n in all_nodes if n.get("node_id") != "root"]
        best = sorted(non_root, key=lambda n: float((n.get("score") or {}).get("score", 0.0)), reverse=True)[: min(width, len(non_root))]
        status = "COMPLETED" if non_root else "EMPTY"
        summary = {"schema_version": "sisyfus.beam_summary.v0.6", "created_at": utc_now(), "finished_at": utc_now(), "beam_id": beam_id, "goal_id": goal["id"], "status": status, "reason": reason, "session_count": session_count, "node_count": len(all_nodes), "edge_count": len(read_jsonl(bdir / "edges.jsonl")), "best_nodes": best, "best_node_ids": [n.get("node_id") for n in best], "beam_dir": _rel(self.root, bdir)}
        meta["status"] = status; meta["finished_at"] = summary["finished_at"]; meta["session_count"] = session_count
        write_json(bdir / "beam.json", meta)
        write_json(bdir / "summary.json", summary)
        (bdir / "beam.context.md").write_text(self.store.build_context(beam_id), encoding="utf-8")
        self.store.append_index({"schema_version": "sisyfus.beam_index.v0.6", "created_at": meta["created_at"], "finished_at": summary["finished_at"], "beam_id": beam_id, "goal_id": goal["id"], "objective": goal.get("objective"), "status": status, "reason": reason, "session_count": session_count, "node_count": len(all_nodes), "beam_dir": _rel(self.root, bdir), "best_node_ids": summary["best_node_ids"]})
        append_jsonl(bdir / "events.jsonl", {"ts": utc_now(), "event": "beam.finished", "beam_id": beam_id, "status": status, "data": summary})
        return summary
