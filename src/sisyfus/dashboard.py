from __future__ import annotations

import json
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .beam import BeamStore
from .paths import ensure_layout, find_project_root
from .experiment_ledger import experiment_chart_data, experiment_summary, list_experiments
from .memory_fsm import MemoryFSMStore
from .outcome import list_outcomes
from .provider import summarize_provider_usage
from .review import ReviewStore, load_review_context
from .storage import MemoryBroker
from .utils import utc_now

STATIC_DIR = Path(__file__).with_name("dashboard_static")


def _usage_totals(sessions: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"agent_calls": 0, "approx_prompt_tokens": 0, "approx_output_tokens": 0}
    for s in sessions:
        usage = s.get("usage") or {}
        totals["agent_calls"] += int(usage.get("agent_calls", 0) or 0)
        totals["approx_prompt_tokens"] += int(usage.get("approx_prompt_tokens", 0) or 0)
        totals["approx_output_tokens"] += int(usage.get("approx_output_tokens", 0) or 0)
    return totals


def dashboard_state(root: str | Path | None = None, *, session_limit: int = 200) -> dict[str, Any]:
    root_path = find_project_root(root)
    ensure_layout(root_path)
    store = ReviewStore(root_path)
    broker = MemoryBroker(root_path)
    sessions = store.sessions_with_review(limit=session_limit)
    conclusions = store.claims(limit_sessions=session_limit)
    annotations = store.annotations()
    directions = store.guidance(include_archived=True)
    open_tasks = broker.read_open_tasks()
    beam_store = BeamStore(root_path)
    beams = beam_store.list_beams(limit=100)
    outcomes = list_outcomes(root_path, limit=200)
    experiments = list_experiments(root_path, limit=200)
    exp_summary = experiment_summary(root_path)
    memory_store = MemoryFSMStore(root_path)
    memory_items = memory_store.list(limit=200)
    memory_coverage = memory_store.coverage()
    provider_summary = summarize_provider_usage(root_path)
    beam_details = []
    beam_nodes = []
    beam_edges = []
    for b in beams[:30]:
        try:
            detail = beam_store.load_beam(str(b.get("beam_id")))
            beam_details.append(detail)
            beam_nodes.extend(detail.get("nodes", []))
            beam_edges.extend(detail.get("edges", []))
        except Exception:
            continue
    status_counts: dict[str, int] = {}
    for s in sessions:
        status = str(s.get("status") or "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
    claim_verdict_counts: dict[str, int] = {}
    for c in conclusions:
        verdict = str(c.get("human_verdict") or c.get("human_status") or "unreviewed")
        claim_verdict_counts[verdict] = claim_verdict_counts.get(verdict, 0) + 1

    stats = {
        "session_count": len(sessions),
        "claim_count": len(conclusions),
        "active_guidance_count": len([g for g in directions if g.get("status", "active") == "active"]),
        "open_task_count": len(open_tasks),
        "beam_count": len(beams),
        "beam_node_count": len(beam_nodes),
        "feedback_count": len(annotations),
        "unreviewed_conclusion_count": claim_verdict_counts.get("unreviewed", 0),
        "status_counts": status_counts,
        "claim_verdict_counts": claim_verdict_counts,
        "usage_totals": _usage_totals(sessions),
        "active_beam_count": len([b for b in beams if b.get("status") == "RUNNING"]),
        "outcome_count": len(outcomes),
        "experiment_count": len(experiments),
        "memory_fsm_count": len(memory_items),
        "provider_estimated_usd": provider_summary.get("estimated_usd", 0),
    }
    human_context = load_review_context(root_path, max_chars=40000)
    return {
        "schema_version": "sisyfus.dashboard_state.v0.6",
        "created_at": utc_now(),
        "generated_at": utc_now(),
        "root": str(root_path),
        "stats": stats,
        "summary": stats,
        "annotation_count": len(annotations),
        "open_task_count": len(open_tasks),
        "session_count": len(sessions),
        "claim_count": len(conclusions),
        "sessions": sessions,
        "beams": beams,
        "outcomes": outcomes,
        "experiments": experiments,
        "experiment_summary": exp_summary,
        "experiment_chart": experiment_chart_data(root_path, limit=200),
        "memory_fsm": memory_items,
        "memory_coverage": memory_coverage,
        "provider_summary": provider_summary,
        "beam_details": beam_details,
        "beam_nodes": beam_nodes,
        "beam_edges": beam_edges,
        "claims": conclusions,
        "conclusions": conclusions,
        "guidance": directions,
        "directions": directions,
        "tasks": open_tasks,
        "open_tasks": open_tasks,
        "annotations": annotations,
        "beams": beams,
        "beam_nodes": beam_nodes,
        "human_context": human_context,
    }


# Backwards-compatible name used by early v0.4 CLI.
def build_dashboard_state(root: str | Path | None = None, *, session_limit: int = 200) -> dict[str, Any]:
    return dashboard_state(root, session_limit=session_limit)


def export_dashboard_snapshot(root: str | Path | None = None, *, out: str | Path | None = None, session_limit: int = 200) -> Path:
    root_path = find_project_root(root)
    path = Path(out) if out else ensure_layout(root_path) / "dashboard" / "snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dashboard_state(root_path, session_limit=session_limit), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server_version = "SisyfusDashboard/0.6"

    @property
    def root(self) -> Path:
        return self.server.root  # type: ignore[attr-defined]

    @property
    def store(self) -> ReviewStore:
        return self.server.store  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        if getattr(self.server, "verbose", False):  # type: ignore[attr-defined]
            super().log_message(fmt, *args)

    def _send(self, status: int, body: bytes, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: Any, status: int = 200) -> None:
        self._send(status, json.dumps(data, indent=2, sort_keys=True, default=str).encode("utf-8"))

    def _error(self, status: int, message: str) -> None:
        self._json({"status": status, "error": message}, status=status)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        payload = json.loads(self.rfile.read(length).decode("utf-8", errors="replace") or "{}")
        if not isinstance(payload, dict):
            raise ValueError("expected JSON object")
        return payload

    def _static(self, rel: str, content_type: str) -> bool:
        path = STATIC_DIR / rel
        if not path.exists() or not path.is_file():
            return False
        self._send(200, path.read_bytes(), content_type)
        return True

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, b"")

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            if path in {"/", "/index.html"}:
                if not self._static("index.html", "text/html; charset=utf-8"):
                    self._send(200, b"<h1>Sisyfus dashboard static assets missing</h1>", "text/html; charset=utf-8")
                return
            if path == "/style.css":
                if not self._static("style.css", "text/css; charset=utf-8"):
                    self._error(404, "style.css not found")
                return
            if path == "/app.js":
                if not self._static("app.js", "application/javascript; charset=utf-8"):
                    self._error(404, "app.js not found")
                return
            if path in {"/api/state", "/api/dashboard-state"}:
                self._json(dashboard_state(self.root, session_limit=int(query.get("session_limit", ["200"])[0])))
                return
            if path == "/api/overview":
                state = dashboard_state(self.root, session_limit=0)
                self._json({k: state[k] for k in ["schema_version", "created_at", "generated_at", "root", "stats", "summary"]})
                return
            if path == "/api/sessions":
                self._json(self.store.sessions_with_review(limit=int(query.get("limit", ["100"])[0])))
                return
            if path in {"/api/claims", "/api/conclusions"}:
                claims = self.store.claims()
                verdict = query.get("verdict", [None])[0]
                if verdict:
                    claims = [c for c in claims if c.get("human_verdict") == verdict]
                self._json(claims)
                return
            if path in {"/api/guidance", "/api/directions"}:
                self._json(self.store.guidance(include_archived=True))
                return
            if path == "/api/beams":
                self._json(BeamStore(self.root).list_beams(limit=int(query.get("limit", ["100"])[0])))
                return
            if path == "/api/beam":
                beam_id = query.get("beam_id", [""])[0]
                if not beam_id:
                    self._error(400, "beam_id is required")
                    return
                self._json(BeamStore(self.root).load_beam(beam_id))
                return
            if path == "/api/beam-context":
                beam_id = query.get("beam_id", [""])[0]
                if not beam_id:
                    self._error(400, "beam_id is required")
                    return
                self._send(200, BeamStore(self.root).build_context(beam_id, max_chars=40000).encode("utf-8"), "text/markdown; charset=utf-8")
                return
            if path.startswith("/api/beams/"):
                self._json(BeamStore(self.root).load_beam(urllib.parse.unquote(path.removeprefix("/api/beams/"))))
                return
            if path == "/api/outcomes":
                self._json(list_outcomes(self.root, limit=int(query.get("limit", ["100"])[0])))
                return
            if path == "/api/experiments":
                self._json(list_experiments(self.root, limit=int(query.get("limit", ["100"])[0]), status=query.get("status", [None])[0], beam_id=query.get("beam_id", [None])[0]))
                return
            if path == "/api/experiment-chart":
                self._json(experiment_chart_data(self.root, limit=int(query.get("limit", ["500"])[0])))
                return
            if path == "/api/memory-fsm":
                self._json(MemoryFSMStore(self.root).list(state=query.get("state", [None])[0], limit=int(query.get("limit", ["200"])[0])))
                return
            if path == "/api/memory-coverage":
                self._json(MemoryFSMStore(self.root).coverage())
                return
            if path == "/api/provider-summary":
                self._json(summarize_provider_usage(self.root))
                return
            if path == "/api/tasks":
                self._json(MemoryBroker(self.root).read_open_tasks())
                return
            if path == "/api/human-context":
                self._send(200, load_review_context(self.root, max_chars=40000).encode("utf-8"), "text/markdown; charset=utf-8")
                return
            if path == "/api/session":
                run_id = query.get("run_id", [""])[0]
                if not run_id:
                    self._error(400, "run_id is required")
                    return
                self._json(self.store.load_run_detail(run_id))
                return
            if path.startswith("/api/runs/"):
                self._json(self.store.load_run_detail(urllib.parse.unquote(path.removeprefix("/api/runs/"))))
                return
            self._error(404, f"Not found: {path}")
        except Exception as exc:  # noqa: BLE001
            self._error(500, f"{type(exc).__name__}: {exc}")

    def do_POST(self) -> None:  # noqa: N802
        try:
            path = urllib.parse.urlparse(self.path).path
            data = self._read_json_body()
            if path in {"/api/feedback", "/api/annotations"}:
                verdict = str(data.get("verdict") or "").lower()
                verdict_aliases = {"pass": "correct", "fail": "wrong", "ok": "correct", "bad": "wrong"}
                verdict = verdict_aliases.get(verdict, verdict)
                item = self.store.annotate(
                    target_id=str(data.get("target_id") or ""),
                    target_type=str(data.get("target_type") or "claim"),
                    verdict=verdict,
                    note=str(data.get("note") or ""),
                    run_id=data.get("run_id") or (data.get("metadata") or {}).get("run_id") if isinstance(data.get("metadata"), dict) else data.get("run_id"),
                    goal_id=data.get("goal_id"),
                    claim=data.get("claim"),
                    next_action=data.get("next_action"),
                    create_task=bool(data.get("create_task", False)),
                )
                self._json(item, status=201)
                return
            if path in {"/api/direction", "/api/guidance"}:
                tags = data.get("tags") or []
                if isinstance(tags, str):
                    tags = [x.strip() for x in tags.split(",") if x.strip()]
                item = self.store.add_guidance(
                    str(data.get("text") or ""),
                    scope=str(data.get("scope") or "project"),
                    goal_id=data.get("goal_id"),
                    run_id=data.get("run_id"),
                    priority=str(data.get("priority") or "P2"),
                    tags=tags,
                    create_task=bool(data.get("create_task", False)),
                )
                self._json(item, status=201)
                return
            self._error(404, f"Not found: {path}")
        except Exception as exc:  # noqa: BLE001
            self._error(400, f"{type(exc).__name__}: {exc}")


class SisyfusDashboardServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], root: Path, *, verbose: bool = False) -> None:
        super().__init__(server_address, DashboardRequestHandler)
        self.root = root.resolve()
        ensure_layout(self.root)
        self.store = ReviewStore(self.root)
        self.verbose = verbose


def serve_dashboard(
    root: str | Path | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    verbose: bool = False,
    open_browser: bool = False,
) -> tuple[SisyfusDashboardServer, str]:
    root_path = find_project_root(root)
    server = SisyfusDashboardServer((host, port), root_path, verbose=verbose)
    url = f"http://{host}:{server.server_port}/"
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    return server, url


def start_dashboard_in_thread(root: str | Path, *, host: str = "127.0.0.1", port: int = 0) -> tuple[SisyfusDashboardServer, threading.Thread]:
    server, _url = serve_dashboard(root, host=host, port=port, verbose=False, open_browser=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
