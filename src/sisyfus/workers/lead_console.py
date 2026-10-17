"""Local operator surface for LeadMission; never a second mission truth store.

MissionHub(directory) inventories fixed child control directories.  Use
MissionHub(directory, single=True) for an existing single mission. Constructors,
inventory and page loads do not dispatch work. Start/control('start',
allow_local_workers=True) grants worker execution. Explicit prepare_placement
admits only a planning thread, never workers. Core owns execution fencing,
acceptance, integration and restart reconciliation.

MissionHub.placements(ident) returns exactly {mission_id: ident, placements:
[{task_id: fixed_task_id, placement: exact_core_placement}]} for ALL immutable
plan task records, including historical tasks, in the core journal's record
order. Default placement is exactly {'kind':'local'}. Tasks and every pin share
one readonly snapshot of the original autonomy.sqlite3. Cached and cold/legacy
readers alike use URI mode=ro + BEGIN, never a read-write store connection, and
never initialize/reconcile a controller, registry, backend, schema or metadata.
Directory/database device+inode identities (no symlinks, single-link DB) fence
both opens and the completed read. The approved native specification is checked
again in that same task/pin snapshot, including the cached controller binding.
GET /api/missions/{id}/placements accepts no query and retains the original
operator boundary. This projection grants no readiness/online/heartbeat,
planning, execution, acceptance or integration authority; POST is unchanged.
"""
from __future__ import annotations

import hmac
import json
import re
import secrets
import sqlite3
import stat
import sys
import threading
import time
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import BaseServer
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlsplit

from .lead_contracts import SCHEMA, load_lead_spec
from .mission_inbox import MissionInbox, validate_cursor
from .protocol import redact

DEFAULT_PORT = 8781
MAX_JSON_BYTES = 200_000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_NODE_ROUTE = re.compile(r"/api/missions/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/(nodes|placements)"
                         r"(?:/(node_[0-9a-f]{32})/revoke)?\Z")
_PREPARATION_ROUTE = re.compile(r"/api/missions/([A-Za-z0-9][A-Za-z0-9_-]{0,63})/prepare-placement\Z")


def lead_mission(directory: Path, spec: dict[str, Any] | None = None) -> Any:
    """Lazy core boundary, also injectable through MissionHub.mission_factory."""
    from .lead_mission import LeadMission
    return LeadMission(directory, spec)


def safe_error(exc: Exception, *, token: str = "") -> dict[str, str]:
    message = str(redact(str(exc)))
    if token:
        message = message.replace(token, "[REDACTED]")
    return {"type": type(exc).__name__, "message": message[:4000]}


def _engineering_sidecar(cap: dict[str, Any], token: str) -> dict[str, Any]:
    """Optional pure presentation of this exact capture; never a truth update."""
    side = {"schema": "sisyfus.lead_console.engineering_result_sidecar.v1",
            "mission_id": cap["id"], "status": "FAILED", "result": None,
            "error": {"code": "PROJECTION_INTERNAL_ERROR"}}
    try:
        # Default reads do not import the projector. Import failures are local
        # presentation errors too, without formatting arbitrary exception text.
        from .lead_result import EngineeringResultInputError, project_engineering_result
        try:
            out = project_engineering_result(cap)
        except EngineeringResultInputError as exc:
            code = exc.code
            if type(code) is str and re.fullmatch(r"[A-Z][A-Z0-9_]{0,31}", code):
                side["status"] = "REJECTED"
                side["error"] = {"code": code}
            return side
        # Do not deliver a changed value with pointers into the unchanged cap.
        # Existing capture markers are inert; only an actual transform or the
        # literal operator token fences the new result. The base is untouched.
        if redact(out) != out or (token and token in json.dumps(out, ensure_ascii=False, allow_nan=False)):
            side["error"] = {"code": "REDACTION_ALTERED"}
            return side
        side.update(status="OK", result=out, error=None)
        return side
    except Exception:
        return side


def approved_spec(directory: Path) -> dict[str, Any]:
    """Read only: unknown/incomplete directories are never initialized here."""
    db_path = directory / "autonomy.sqlite3"
    if directory.is_symlink() or db_path.is_symlink() or not db_path.is_file():
        raise FileNotFoundError("no regular autonomy.sqlite3 in the selected control directory")
    db = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        row = db.execute("SELECT value FROM metadata WHERE key='native_worker_spec'").fetchone()
    finally:
        db.close()
    if not row:
        raise ValueError("no operator-approved bound mission specification")
    spec = json.loads(row[0])
    if not isinstance(spec, dict) or spec.get("schema_version") != SCHEMA:
        raise ValueError("control database is not a bound Tech Lead mission")
    if not isinstance(spec.get("source"), str) or not isinstance(spec.get("roles"), dict):
        raise ValueError("bound mission is missing source/explicit role models")
    source, control = Path(spec["source"]).expanduser().resolve(), directory.resolve()
    if source.is_relative_to(control) or control.is_relative_to(source):
        raise ValueError("source and control directories must be disjoint")
    return spec


def _placements_in(db: Any, ident: str) -> dict[str, Any]:
    """Use the caller's snapshot; same record/pin semantics as core, no writes."""
    from .lead_journal import LeadJournal
    prefix = LeadJournal.prefix
    plans = prefix + "plans:"
    rows = db.execute("SELECT value FROM metadata WHERE substr(key,1,?)=?",
                      (len(plans), plans)).fetchall()
    records = sorted((json.loads(row[0]) for row in rows),
                     key=lambda record: (record["created_at"], record["key"]))
    placements = []
    for record in records:
        for task in record["data"]["plan"]["tasks"]:
            row = db.execute("SELECT value FROM metadata WHERE key=?",
                             (prefix + "placement:" + task["id"],)).fetchone()
            placements.append({"task_id": task["id"],
                               "placement": json.loads(row[0]) if row else {"kind": "local"}})
    return {"mission_id": ident, "placements": placements}


def _placement_inode(path: Path, *, directory: bool = False) -> tuple[int, int]:
    """Match the gateway's nofollow, regular/single-link identity discipline."""
    info = path.lstat()
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise PermissionError("selected control directory must be non-symlink")
    elif not stat.S_ISREG(info.st_mode):
        # Preserve the existing initial missing/nonregular DB's 404 boundary.
        raise FileNotFoundError("no regular autonomy.sqlite3 in the selected control directory")
    elif info.st_nlink != 1:
        raise PermissionError("selected control database must have exactly one link")
    return info.st_dev, info.st_ino


def _placement_identity(control: Path) -> tuple[tuple[int, int], tuple[int, int]]:
    return (_placement_inode(control, directory=True),
            _placement_inode(control / "autonomy.sqlite3"))


def _check_placement_identity(control: Path, identity: Any, store: Any = None) -> None:
    try:
        selected = _placement_identity(control)
        owner = _placement_inode(Path(store.path)) if store is not None else identity[1]
    except OSError as exc:
        raise PermissionError("selected control identity changed during placement readback") from exc
    if selected != identity or owner != identity[1]:
        raise PermissionError("selected control/store identity changed during placement readback")


def _placement_binding_in(db: Any, control: Path, approved: dict[str, Any],
                          cached: dict[str, Any] | None = None) -> None:
    """Bind approval/schema/source/roles to the caller's task/pin snapshot."""
    row = db.execute("SELECT value FROM metadata WHERE key='native_worker_spec'").fetchone()
    spec = json.loads(row[0]) if row else None
    if (not isinstance(spec, dict) or spec.get("schema_version") != SCHEMA
            or not isinstance(spec.get("source"), str) or not isinstance(spec.get("roles"), dict)
            or spec != approved or (cached is not None and spec != cached)):
        raise PermissionError("selected mission binding changed during placement readback")
    source, directory = Path(spec["source"]).expanduser().resolve(), control.resolve()
    if source.is_relative_to(directory) or directory.is_relative_to(source):
        raise PermissionError("selected mission source/control binding changed during placement readback")


class _Session:
    def __init__(self, mission: Any):
        self.mission = mission
        self.inbox = getattr(mission, "inbox", None) or MissionInbox(mission.journal)
        self.lock = threading.RLock()
        self.thread: threading.Thread | None = None
        self.error: dict[str, str] | None = None
        self.result: Any = None
        self.permission = False


class _GatewayEntry:
    """Ephemeral loop observation, separate from permission publication.

    The witness runs only in the public service_actions hook. No frame, local
    dictionary or exception is retained, and readiness never invokes it.
    """
    def __init__(self, gateway: Any, thread: threading.Thread, generation: int):
        self.gateway, self.thread, self.generation = gateway, thread, generation
        self.socket = gateway.socket
        self.original = gateway.service_actions
        self.entered = False  # Cleanup fact, not normal-return permission.
        self.observed = False
        self.failed = False
        self.mismatch = False
        self.changed = threading.Event()
        self.url = gateway.url
        self.host = str(gateway.server_address[0]) + ":" + str(gateway.server_address[1])

        def actions() -> None:
            try:
                frame = sys._getframe(1)
                try:
                    direct = (frame.f_code is BaseServer.serve_forever.__code__
                              and frame.f_locals.get("self") is gateway
                              and threading.current_thread() is thread)
                finally:
                    del frame
                if direct:
                    self.entered = True
                self.original()
            except BaseException:
                self.failed = True
                self.changed.set()
                raise
            if direct:
                self.observed = True
            else:
                self.mismatch = True
            self.changed.set()

        self.hook = actions

    def live(self) -> bool:
        # Only local, nonblocking observations. Valid inside a core write TX.
        return (self.observed and not self.failed and not self.mismatch
                and self.gateway.service_actions is self.hook
                and self.gateway.socket is self.socket and self.socket.fileno() >= 0
                and self.thread.is_alive())

    def restore(self) -> None:
        if self.gateway.service_actions is self.hook:
            self.gateway.service_actions = self.original


class MissionHub:
    """Independent per-mission controllers with an in-memory discovery cache.

    No hub manifest or hub database. Approved specs and controls are bound in
    each core-created autonomy DB. Persisted controls are audit acknowledgements,
    never completion evidence, and are never automatically replayed.
    """
    def __init__(self, directory: Path, *, single: bool = False,
                 mission_factory: Callable[..., Any] | None = None):
        self.directory = Path(directory).expanduser().resolve()
        self.single = single
        self.mission_factory = mission_factory or lead_mission
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.RLock()
        self._closing = False
        self._closed = False
        self._close_done = threading.Event()
        self._close_error: BaseException | None = None
        self._close_owner: object | None = None
        self._close_active: list[tuple[_Session, threading.Thread]] | None = None
        self._close_changed = threading.Condition(self._lock)
        self._gateway_generation = 0
        self._gateway_entry: _GatewayEntry | None = None
        self._gateway_binding: _GatewayEntry | None = None
        self._gateway_observation: _GatewayEntry | None = None

    def _require_open(self) -> None:
        if self._closing or self._closed:
            raise RuntimeError("mission hub is closing or closed; new admission rejected")

    def _remote_execution_ready(self) -> bool:
        entry = self._gateway_binding
        return bool(not self._closing and not self._closed and entry is not None
                    and entry.generation == self._gateway_generation and entry.live())

    def attach_node_gateway(self, gateway: Any, *, serve_thread: threading.Thread) -> dict[str, Any]:
        # The optional backend is imported only at explicit host attachment.
        from .node_gateway import NodeGateway
        with self._lock:
            self._require_open()
            if self._gateway_entry is not None:
                raise RuntimeError("host gateway already attached or attachment pending")
            if not isinstance(gateway, NodeGateway) or gateway.hub is not self:
                raise ValueError("gateway must belong to this exact Hub")
            if not isinstance(serve_thread, threading.Thread) or not serve_thread.is_alive():
                raise ValueError("gateway requires an explicitly started live serving Thread")
            if (gateway.server_address[0] != "127.0.0.1"
                    or gateway.socket.fileno() < 0
                    or gateway.socket.getsockname() != gateway.server_address
                    or gateway.serve_forever.__func__ is not BaseServer.serve_forever):
                raise ValueError("gateway requires the actual bound loopback stdlib listener")
            self._gateway_generation += 1
            entry = _GatewayEntry(gateway, serve_thread, self._gateway_generation)
            self._gateway_entry = entry
            self._gateway_observation = entry  # Cleanup fact survives failed publication.
            gateway.service_actions = entry.hook
        try:
            # A started thread or a bound socket alone never proves loop entry.
            # No lifecycle/session lock is held during the finite handshake.
            deadline = time.monotonic() + 2.0
            while not entry.observed:
                if entry.failed or entry.mismatch or not serve_thread.is_alive():
                    raise RuntimeError("gateway loop entry failed or serving Thread did not match")
                if self._closing or entry.generation != self._gateway_generation:
                    raise RuntimeError("mission hub closing or attachment revoked during loop entry")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("gateway loop entry was not observed within the host deadline")
                entry.changed.wait(min(remaining, .02))
            with self._lock:
                self._require_open()
                if (self._gateway_entry is not entry
                        or entry.generation != self._gateway_generation or not entry.live()):
                    raise RuntimeError("gateway attachment changed before permission publication")
                self._gateway_binding = entry
            return self.node_gateway_state()
        except BaseException:
            with self._lock:
                if self._gateway_entry is entry:
                    self._gateway_entry = None
                    self._gateway_generation += 1
                entry.restore()
            raise

    def detach_node_gateway(self) -> None:
        with self._lock:
            self._gateway_generation += 1
            entry = self._gateway_entry
            self._gateway_binding = None
            self._gateway_entry = None
            if entry is not None:
                entry.restore()

    def node_gateway_state(self) -> dict[str, Any]:
        entry = self._gateway_binding
        ready = self._remote_execution_ready()
        return {"gateway": {"url": entry.url, "host": entry.host} if entry else None,
                "effective_ready": ready,
                "basis": "host loop entry verified; not node or model readiness" if ready
                         else "no current live host gateway permission"}

    def path(self, mission_id: str) -> Path:
        if not isinstance(mission_id, str) or not _ID.fullmatch(mission_id):
            raise ValueError("invalid mission id; select a fixed inventory child")
        if self.single:
            if mission_id != "mission":
                raise ValueError("single console mission id is 'mission'")
            return self.directory
        path = self.directory / mission_id
        if path.is_symlink() or path.resolve().parent != self.directory:
            raise ValueError("mission child must be a fixed non-symlink directory")
        return path

    def inventory(self) -> dict[str, Any]:
        entries, issues = [], []
        if self.single:
            candidates = [("mission", self.directory)]
        elif self.directory.is_dir():
            candidates = [(p.name, p) for p in sorted(self.directory.iterdir())
                          if _ID.fullmatch(p.name) and (p.is_dir() or p.is_symlink())]
        else:
            candidates = []
        for ident, path in candidates:
            try:
                self.path(ident)
                spec = approved_spec(path)
                with self._lock:
                    session = self._sessions.get(ident)
                entries.append({"id": ident, "directory": str(path),
                                "objective": spec.get("objective"), "source": spec["source"],
                                "roles": spec["roles"],
                                "controller_running": bool(session and session.thread and session.thread.is_alive())})
            except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as exc:
                issues.append({"id": ident, "error": safe_error(exc)})
        return {"missions": entries, "issues": issues, "single": self.single,
                "directory": str(self.directory), "auto_start": False}

    def create(self, spec: Path | Mapping[str, Any], *, directory: Path | None = None) -> dict[str, Any]:
        """Bind operator spec through core; no workers start. Explicit directory is
        only for CLI new/run/up on a single hub, never accepted by HTTP input.
        """
        normalized = load_lead_spec(spec)
        for check in normalized["checks"].values():
            if not check.get("contract", {}).get("fail_if"):
                raise ValueError("fixed check contract requires explicit pass_if and fail_if")
        with self._lock:
            self._require_open()
            if self.single:
                ident, control = "mission", self.directory
                if directory is not None and Path(directory).expanduser().resolve() != control:
                    raise ValueError("directory differs from the selected single control")
            else:
                if directory is not None:
                    raise ValueError("hub creations use generated fixed child paths")
                ident = "m_" + secrets.token_hex(16)
                control = self.path(ident)
                if control.exists():
                    raise FileExistsError("generated control directory already exists; retry creation")
            source = Path(normalized["source"]).resolve()
            if source.is_relative_to(control) or control.is_relative_to(source):
                raise ValueError("source and control directories must be disjoint")
            # Do not invalidate or replace a running cached controller on CLI rebinding.
            existing = self._sessions.get(ident)
            if existing and existing.thread and existing.thread.is_alive():
                raise RuntimeError("controller already running; select existing mission")
            mission = self.mission_factory(control, normalized)
            approved_spec(control)  # Binding, not a JSON file, is the inventory gate.
            mission.remote_execution_ready = self._remote_execution_ready
            self._sessions[ident] = _Session(mission)
        return {"id": ident, "directory": str(control), "status": "BOUND",
                "started": False, "snapshot": self.snapshot(ident)}

    def _session(self, ident: str) -> _Session:
        with self._lock:
            if ident not in self._sessions:
                self._require_open()
            control = self.path(ident)
            approved_spec(control)
            if ident not in self._sessions:
                self._sessions[ident] = _Session(self.mission_factory(control))
            self._sessions[ident].mission.remote_execution_ready = self._remote_execution_ready
            return self._sessions[ident]

    def _record(self, session: _Session, ident: str, action: str) -> None:
        store = session.mission.journal.store
        with store._transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS lead_console_controls ("
                       "id TEXT PRIMARY KEY, action TEXT NOT NULL, status TEXT NOT NULL, error_json TEXT)")
            db.execute("INSERT INTO lead_console_controls VALUES(?,?,'PENDING',NULL)", (ident, action))
            session.mission.journal._event(db, "lead_console_control", ident,
                                         {"action": action, "status": "PENDING", "terminal": False}, actor="operator")

    def _ack(self, session: _Session, ident: str, status: str,
             error: dict[str, str] | None = None) -> None:
        with session.mission.journal.store._transaction() as db:
            db.execute("UPDATE lead_console_controls SET status=?,error_json=? WHERE id=?",
                       (status, json.dumps(error) if error else None, ident))
            session.mission.journal._event(db, "lead_console_ack", ident,
                                         {"status": status, "error": error, "terminal": False}, actor="operator")

    def controls(self, ident: str) -> list[dict[str, Any]]:
        path = self.path(ident)
        approved_spec(path)
        db = sqlite3.connect((path / "autonomy.sqlite3").as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lead_console_controls'").fetchone():
                return []
            rows = db.execute("SELECT id,action,status,error_json FROM lead_console_controls ORDER BY rowid DESC LIMIT 100").fetchall()
            return [{"id": r[0], "action": r[1], "status": r[2],
                     "error": json.loads(r[3]) if r[3] else None, "terminal": False} for r in rows]
        finally:
            db.close()

    def snapshot(self, ident: str) -> dict[str, Any]:
        session = self._session(ident)
        with session.lock:
            running = bool(session.thread and session.thread.is_alive())
            # Preserve this conservative runtime sample if the controller
            # finishes during Core capture. Core still owns all task truth.
            snap = session.mission.snapshot()
            runtime = {"running": running, "local_workers_acknowledged": session.permission,
                       "error": session.error, "stop_requested": session.mission.stop.is_set(),
                       "auto_start": False}
        return {"id": ident, "snapshot": redact(snap), "controller": runtime,
                "controls": self.controls(ident)}

    def events(self, ident: str, cursor: int = 0) -> dict[str, Any]:
        validate_cursor(cursor)
        batch = self._session(ident).mission.journal.events(cursor)
        return {"events": redact(batch), "cursor": batch[-1]["seq"] if batch else cursor}

    def messages(self, ident: str, cursor: int = 0, *, application_cursor: int = 0) -> dict[str, Any]:
        validate_cursor(cursor)
        validate_cursor(application_cursor)
        return redact(self._session(ident).inbox.messages(cursor, application_cursor=application_cursor))

    def message(self, ident: str, message: str, request_id: str, *, task_id: str | None = None) -> dict[str, Any]:
        session = self._session(ident)
        view = self.snapshot(ident)
        return redact(session.inbox.submit(message, request_id, snapshot=view["snapshot"],
                                          controller=view["controller"], task_id=task_id))

    def nodes(self, ident: str) -> dict[str, Any]:
        registry = self._session(ident).mission.node_claims.registry
        return {"mission_id": ident, "nodes": registry.inventory(), "execution_ready": False}

    def placements(self, ident: str) -> dict[str, Any]:
        """Read all fixed task pins atomically; never load a cold controller."""
        control = self.path(ident)
        identity = _placement_identity(control)
        approved = approved_spec(control)
        with self._lock:
            session = self._sessions.get(ident)
        store = session.mission.journal.store if session is not None else None
        cached = session.mission.spec if session is not None else None
        _check_placement_identity(control, identity, store)
        # _session/mission_factory initialize metadata and may reconcile runs,
        # and a read-write store connection (even a cached one) can create or
        # convert a substituted database before any fence. Observe read-only.
        try:
            db = sqlite3.connect((control / "autonomy.sqlite3").as_uri() + "?mode=ro",
                                 uri=True, isolation_level=None, timeout=5)
        except sqlite3.Error:
            _check_placement_identity(control, identity, store)  # vanished: 403
            raise
        try:
            db.execute("BEGIN")
            _check_placement_identity(control, identity, store)
            _placement_binding_in(db, control, approved, cached)
            result = _placements_in(db, ident)
            _check_placement_identity(control, identity, store)
            db.execute("COMMIT")
        except Exception:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()
        _check_placement_identity(control, identity, store)
        return result

    def enroll_node(self, ident: str, request_id: str, name: str) -> dict[str, Any]:
        # No caller-selected driver/model/path/operator permissions.
        registry = self._session(ident).mission.node_claims.registry
        return registry.enroll(request_id, name, ["codex"], ["gpt-6.1-sol"]) | {"execution_ready": False}

    def revoke_node(self, ident: str, node_id: str) -> dict[str, Any]:
        return self._session(ident).mission.node_claims.registry.revoke(node_id) | {"execution_ready": False}

    def assign_placement(self, ident: str, task_id: str, node_id: str, request_id: str) -> dict[str, Any]:
        return self._session(ident).mission.assign_placement(task_id, node_id, request_id)

    def prepare_placement(self, ident: str, request_id: str, *, allow_planning: bool = False) -> dict[str, Any]:
        """Explicit planning-only request, sharing Start's session/thread fence.

        The core persists REQUESTED under its controller locks before any Hub
        thread is admitted. Controls acknowledge acceptance, not completion.
        Existing controls (including interrupted PENDING and ERROR) are only
        read back; reopening a Hub never relaunches their uncertain operation.
        """
        if allow_planning is not True:
            raise PermissionError("Preparation requires explicit planning permission")
        from .node_registry import validate_request_id
        validate_request_id(request_id)
        session = self._session(ident)
        cid = "prepare-placement:" + request_id
        response = {"id": cid, "mission_id": ident, "request_id": request_id,
                    "action": "prepare-placement", "status": "ACK", "accepted": True,
                    "terminal": False, "scope": "planning_only"}

        def recorded() -> bool:
            # Do not depend on controls()'s bounded newest-100 UI projection.
            with session.mission.journal.store._transaction(immediate=False) as db:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                  "AND name='lead_console_controls'").fetchone():
                    return False
                row = db.execute("SELECT action FROM lead_console_controls WHERE id=?", (cid,)).fetchone()
                if row and row[0] != "prepare-placement":
                    raise RuntimeError("preparation control identity conflicts with a different action")
                return row is not None

        with self._lock, session.lock:
            if recorded():
                return response
            self._require_open()
            if session.thread and session.thread.is_alive():
                raise RuntimeError("controller already running; preparation and Start are exclusive")
            if session.mission.stop.is_set() or session.mission.snapshot().get("stopped"):
                raise RuntimeError("mission is durably stopped; preparation does not clear Stop")
            preparation = session.mission._request_placement_preparation(request_id)
            try:
                self._record(session, cid, "prepare-placement")
            except sqlite3.IntegrityError:
                # A second Hub can observe REQUESTED before the first records
                # its control. The unique durable control still admits one thread.
                if recorded():
                    return response
                raise
            try:
                self._ack(session, cid, "ACK")
                session.permission = False
                session.error = None
                session.result = None
                if preparation["status"] == "REQUESTED":
                    def prepare() -> None:
                        try:
                            session.result = session.mission.prepare_for_placement(request_id)
                        except Exception as exc:
                            session.error = safe_error(exc)
                            try:
                                self._ack(session, cid, "ERROR", session.error)
                            except Exception as audit_exc:
                                session.error["audit_error"] = safe_error(audit_exc)["message"]

                    session.thread = threading.Thread(target=prepare, name="techlead-prepare-" + ident, daemon=False)
                    session.thread.start()
                else:
                    # A direct core request may already be completed/fenced.
                    # Recording operator acceptance adds no execution permission.
                    session.result = session.mission.snapshot()
            except Exception as exc:
                session.error = safe_error(exc)
                self._ack(session, cid, "ERROR", session.error)
                raise
            return response

    def control(self, ident: str, action: str, *, allow_local_workers: bool = False,
                max_cycles: int | None = None) -> dict[str, Any]:
        if action not in {"start", "pause", "resume", "stop"}:
            raise ValueError("action must be start, pause, resume or stop")
        if max_cycles is not None and (type(max_cycles) is not int or max_cycles < 1):
            raise ValueError("max_cycles must be a positive integer or null")
        if action == "start" and allow_local_workers is not True:
            raise PermissionError("Start requires explicit local-worker permission; CLI: --allow-local-workers")
        session = self._session(ident)
        with (self._lock if action == "start" else nullcontext()), session.lock:
            if action == "start":
                self._require_open()
            if action == "start" and session.thread and session.thread.is_alive():
                raise RuntimeError("controller already running; duplicate Start rejected")
            if action == "start" and (session.mission.stop.is_set() or session.mission.snapshot().get("stopped")):
                raise RuntimeError("mission is durably stopped; create a new mission or use a core-owned explicit clear-stop operation")
            cid = secrets.token_hex(16)
            self._record(session, cid, action)
            try:
                if action == "start":
                    # Never clear a durable stop from a console projection. Core
                    # owns stop truth and any future explicit clear-stop operation.
                    if session.mission.snapshot().get("phase") in {"WAITING_LEAD", "NEEDS_OPERATOR"}:
                        resume = getattr(session.mission, "request_resume", None)
                        if callable(resume):
                            resume()  # Explicit operator retry epoch, never an UNKNOWN replay.
                    session.permission = True
                    session.error = None
                    session.result = None

                    def run() -> None:
                        try:
                            session.result = session.mission.run(max_cycles=max_cycles)
                        except Exception as exc:
                            session.error = safe_error(exc)
                            try:
                                self._ack(session, cid, "ERROR", session.error)
                            except Exception as audit_exc:
                                session.error["audit_error"] = safe_error(audit_exc)["message"]

                    session.thread = threading.Thread(target=run, name="techlead-" + ident, daemon=False)
                    # Persist acknowledgement before dispatch so a fast worker
                    # failure cannot subsequently be overwritten with ACK.
                    self._ack(session, cid, "ACK")
                    session.thread.start()
                elif action in {"pause", "resume"}:
                    resume = getattr(session.mission, "request_resume", None)
                    if action == "resume" and callable(resume):
                        resume()
                    else:
                        session.mission.journal.pause(action == "pause")
                    self._ack(session, cid, "ACK")
                else:
                    session.mission.request_stop()
                    self._ack(session, cid, "ACK")
            except Exception as exc:
                session.error = safe_error(exc)
                self._ack(session, cid, "ERROR", session.error)
                raise
            return {"id": cid, "mission_id": ident, "action": action, "status": "ACK",
                    "accepted": True, "terminal": False,
                    "scope": "new_dispatch_only" if action in {"pause", "resume"} else "controller_request"}

    def start(self, ident: str, *, allow_local_workers: bool = False,
              max_cycles: int | None = None) -> dict[str, Any]:
        return self.control(ident, "start", allow_local_workers=allow_local_workers, max_cycles=max_cycles)

    def wait(self, ident: str, timeout: float | None = None) -> Any:
        session = self._session(ident)
        if session.thread:
            session.thread.join(timeout)
        if session.error:
            raise RuntimeError(json.dumps(session.error))
        return session.result

    def close(self) -> None:
        """Cooperative shutdown; no forced kills, deletions, or receipt invention."""
        errors: list[BaseException] = []
        interrupted = False
        owner = object()
        active = None
        try:
            retry = threading.Event()
            while True:
                with self._close_changed:
                    if self._closed:
                        # Repair an interrupted completion signal, not a
                        # missing drain. _closed requires the full capture dead.
                        self._close_done.set()
                        if self._close_error is not None:
                            raise self._close_error
                        if interrupted:
                            raise KeyboardInterrupt
                        return
                    if self._close_owner is None:
                        self._close_owner = owner
                        if not self._closing:
                            self._closing = True
                            self._gateway_generation += 1
                        if self._close_active is None:
                            self._close_active = [(s, s.thread) for s in self._sessions.values()
                                                  if s.thread and s.thread.is_alive()]
                        active = self._close_active
                        break
                    try:
                        # Public Condition wait releases the Hub lock. A timed
                        # recheck also covers an interrupted handoff notify.
                        self._close_changed.wait(.05)
                    except KeyboardInterrupt:
                        interrupted = True
            # Closing intent never resets. Only the drain lease is handed off;
            # stop requests and joins hold neither Hub nor Session locks.
            for session, _ in active:
                while True:
                    try:
                        session.mission.request_stop()
                        break
                    except KeyboardInterrupt:
                        interrupted = True
                    except BaseException as exc:
                        errors.append(exc)
                        break
            for _, thread in active:
                join_error = None
                while True:
                    try:
                        thread.join()
                        if not thread.is_alive():
                            break
                    except KeyboardInterrupt:
                        # An interrupt is not controller completion. Keep
                        # transport available until the captured Thread exits.
                        interrupted = True
                        continue
                    except BaseException as exc:
                        if join_error is None:
                            join_error = exc
                            errors.append(exc)
                        if not thread.is_alive():
                            break
                    try:
                        retry.wait(.05)
                    except KeyboardInterrupt:
                        interrupted = True
        except KeyboardInterrupt:
            raise
        except BaseException as exc:
            errors.append(exc)
            raise
        finally:
            while True:
                try:
                    with self._close_changed:
                        if self._close_owner is owner:
                            try:
                                if not self._closing:
                                    self._closing = True
                                    self._gateway_generation += 1
                                if errors:
                                    if self._close_error is None:
                                        self._close_error = errors[0]
                                    for extra in errors:
                                        if extra is not self._close_error:
                                            self._close_error.add_note("additional cooperative shutdown failure: " + type(extra).__name__)
                                if self._close_active is None:
                                    # None is an interrupted/incomplete capture,
                                    # never evidence of an empty controller set.
                                    self._close_active = [(s, s.thread) for s in self._sessions.values()
                                                          if s.thread and s.thread.is_alive()]
                                self._closed = all(not thread.is_alive() for _, thread in self._close_active)
                                if self._closed:
                                    self._close_done.set()
                            finally:
                                # Escaping capture/header/handler interruptions
                                # relinquish the lease without reopening Start.
                                self._close_owner = None
                                self._close_changed.notify_all()
                    break
                except KeyboardInterrupt:
                    interrupted = True
        if self._close_error is not None:
            raise self._close_error
        if interrupted:
            raise KeyboardInterrupt


PAGE = r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sisyfus · Tech Lead Mission Hub</title><style nonce="NONCE">
:root{color-scheme:light;--paper:#faf9f5;--card:#f6f3ed;--surface:#fdfcf8;--hover:#f0eee7;--ink:#302d29;--muted:#71695f;--line:#ded9cf;--line-strong:#c8b6a5;--accent:#995638;--accent-hover:#7c432b;--good:#486452;--bad:#a34335;--edge:#9c8a78;--font:"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif;--mono:ui-monospace,Menlo,monospace}*{box-sizing:border-box}body{margin:0;padding:24px;background:var(--paper);color:var(--ink);font:15px/1.6 var(--font)}header{display:flex;justify-content:space-between;flex-wrap:wrap;gap:12px}h1{margin:0;font:400 26px/1.4 "Songti SC",Georgia,serif}h2{font-size:16px;font-weight:600;color:var(--ink)}main{display:grid;grid-template-columns:minmax(280px,1fr) minmax(0,2fr);gap:20px;margin-top:20px}section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:16px}label{display:block;margin-top:10px}input,textarea,select,button{font:inherit;color:inherit;background:var(--surface);border:1px solid var(--line-strong);border-radius:8px;padding:8px}input:not([type=checkbox]),textarea,select{width:100%}textarea{min-height:90px;font-family:var(--mono)}button{cursor:pointer;margin:6px 5px 6px 0}button:hover:not(:disabled){background:var(--hover)}button:disabled{opacity:.48;cursor:default}a{color:var(--accent)}a:hover{color:var(--accent-hover)}:focus-visible{outline:2px solid var(--accent);outline-offset:2px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:400px;overflow:auto;font:12px/1.6 var(--mono)}.row{display:flex;gap:10px;flex-wrap:wrap}.row label{flex:1;min-width:140px}.muted{color:var(--muted)}.notice{border-left:2px solid var(--accent);padding-left:12px}.bad{color:var(--bad)}.ok{color:var(--good)}svg{width:100%;min-height:100px;max-height:550px}svg text{fill:var(--ink);font:12px var(--mono)}svg rect{fill:var(--surface);stroke:var(--line-strong)}svg path{stroke:var(--edge);fill:none}.caps label{min-width:130px}@media(max-width:850px){main{grid-template-columns:1fr}body{padding:12px}}
</style><header><div><h1>Tech Lead Mission Hub</h1><div class="muted">Opus Lead → Sol implementation → independent Opus review</div></div><div id="connection" role="status">Connecting…</div></header>
<p class="notice">No automatic dispatch. Start grants native local-worker execution with this user's access. Pause fences new dispatch; Stop is cooperative. PENDING / ACK controls and native completion are not acceptance or integration.</p>
<main><div><section><h2>Create an operator-owned mission</h2><form id="createform">
<label>Source / project directory<input id="source" required placeholder="/absolute/path/to/project"></label>
<label>Objective<textarea id="objective" required placeholder="Deliverables and mechanically testable objective"></textarea></label>
<label>Lead model<input id="lead" value="claude-opus-5-5" required></label>
<label>Worker model<input id="worker" value="gpt-6.1-sol" required></label>
<label>Independent reviewer model<input id="reviewer" value="claude-opus-5-5" required></label>
<details open><summary>Advanced · fixed acceptance checks JSON (required)</summary>
<p class="muted">Map check ids to argv with a separate {candidate}, external evaluator code_hashes, and contract pass_if / fail_if. Checks are frozen at binding; creating never runs a check.</p>
<textarea id="checks" required spellcheck="false" aria-label="Fixed acceptance checks JSON" placeholder='{"check_id":{"argv":["python3","/external/check.py","{candidate}"],"code_hashes":{"/external/check.py":"SHA256"},"contract":{"kind":"rules","pass_if":{},"fail_if":{}}}}'>{}</textarea>
<div class="row"><label>Parallelism<input id="parallelism" type="number" min="1" max="8" value="2" required></label><label>Invocation timeout (s)<input id="timeout" type="number" min="0.1" step="any" max="7200" value="900" required></label></div>
</details><details><summary>Optional aggregate caps · Unlimited by default</summary><div id="caps" class="row caps"></div></details>
<button id="create" type="submit">Create mission (no dispatch)</button></form><pre id="create-result" role="status"></pre></section>
<section><h2>Select existing mission</h2><select id="missions" aria-label="Mission selection"></select><button id="refresh">Refresh inventory</button><pre id="inventory-issues"></pre>
<label><input id="permission" type="checkbox"> I allow native local workers for the selected mission.</label>
<div id="permission-state" class="muted">Local-worker execution not acknowledged</div>
<div class="row"><button id="start">Start</button><button id="pause">Pause</button><button id="resume">Resume</button><button id="stop">Stop</button></div><pre id="control-result" role="status"></pre></section></div>
<div><section><h2>Controller & acceptance</h2><div id="summary" role="status">Select a bound mission.</div><pre id="state"></pre></section>
<section><h2>DAG / task evidence</h2><svg id="graph" role="img" aria-label="Task dependency graph"></svg><pre id="task-detail">Select a graph node.</pre><pre id="dag"></pre></section>
<section><h2>Attempts · diagnoses · independent reviews & deterministic tests</h2><pre id="attempts"></pre><pre id="diagnoses"></pre><pre id="reviews"></pre><pre id="tests"></pre></section>
<section><h2>Integration · RSI procedures & evaluation evidence</h2><pre id="integration"></pre><pre id="rsi"></pre></section>
<section><h2>Full core snapshot / persisted control audit</h2><pre id="snapshot"></pre><pre id="controls"></pre></section>
<section><h2>Persisted per-mission events</h2><pre id="events"></pre></section></div></main>
<script nonce="NONCE">
'use strict';const $=id=>document.getElementById(id),key='sisyfus-techlead:'+location.origin;
let token=new URLSearchParams(location.hash.slice(1)).get('token')||sessionStorage.getItem(key)||'';
if(token){sessionStorage.setItem(key,token)}history.replaceState(null,'',location.pathname);
let selected='',cursor=0,eventRows=[],single=false;
const caps=['max_calls','max_iterations','max_tokens','max_cost_usd','max_wall_minutes','max_turns'];
for(const name of caps){const l=document.createElement('label'),i=document.createElement('input');l.textContent=name;i.id=name;i.type='number';const fractional=name==='max_cost_usd'||name==='max_wall_minutes';i.min=fractional?'0':'1';i.step=fractional?'any':'1';i.placeholder='Unlimited';l.append(i);$('caps').append(l)}
function show(id,value){$(id).textContent=typeof value==='string'?value:JSON.stringify(value,null,2)}
async function api(path,body){const r=await fetch(path,{method:body===undefined?'GET':'POST',cache:'no-store',headers:{Authorization:'Bearer '+token,...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error((data.error?.type||r.status)+': '+(data.error?.message||data.error||'Request failed'));return data}
function choose(id){selected=id;cursor=0;eventRows=[];$('permission').checked=false;show('events','');show('task-detail','Select a graph node.');permissions()}
function permissions(){const granted=$('permission').checked;show('permission-state',granted?'Local-worker execution acknowledged for '+selected:'Local-worker execution not acknowledged');for(const name of ['start','pause','resume','stop'])$(name).disabled=!selected||(name==='start'&&!granted)}
$('permission').onchange=permissions;$('missions').onchange=()=>{choose($('missions').value);pollOnce()};
async function inventory(){const data=await api('/api/missions');single=data.single;$('create').disabled=single;show('create-result',single?'Single-mission console: create through CLI new, or use hub for new missions.':'');$('missions').replaceChildren();for(const m of data.missions){const o=document.createElement('option');o.value=m.id;o.textContent=m.id+' · '+m.objective;$('missions').append(o)}show('inventory-issues',data.issues);if(!data.missions.some(m=>m.id===selected))choose(data.missions[0]?.id||'');$('missions').value=selected;permissions()}
$('refresh').onclick=()=>inventory().then(pollOnce).catch(e=>show('connection',e.message));
$('createform').onsubmit=async e=>{e.preventDefault();try{const spec={source:$('source').value,objective:$('objective').value,roles:{lead:{model:$('lead').value},worker:{model:$('worker').value},reviewer:{model:$('reviewer').value}},checks:JSON.parse($('checks').value),parallelism:Number($('parallelism').value),timeout:Number($('timeout').value)};for(const name of caps)spec[name]=$(name).value===''?null:Number($(name).value);const result=await api('/api/missions',{spec});await inventory();choose(result.id);$('missions').value=selected;show('create-result',result);await pollOnce()}catch(err){show('create-result',err.message)}};
for(const action of ['start','pause','resume','stop'])$(action).onclick=async()=>{try{const data=await api('/api/control',{mission_id:selected,action,allow_local_workers:action==='start'&&$('permission').checked});show('control-result',data);await pollOnce()}catch(e){show('control-result',e.message)}};
function svg(tag,attrs){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);return e}
function graph(nodes){const g=$('graph');g.replaceChildren();const pos=new Map();nodes.forEach((n,i)=>pos.set(n.id,{x:25+(i%2)*320,y:20+Math.floor(i/2)*105}));g.setAttribute('viewBox',`0 0 670 ${Math.max(100,Math.ceil(nodes.length/2)*105)}`);for(const n of nodes)for(const dep of n.depends_on||[]){const a=pos.get(dep),b=pos.get(n.id);if(a&&b)g.append(svg('path',{d:`M${a.x+125},${a.y+65} L${b.x+125},${b.y}`}))}for(const n of nodes){const p=pos.get(n.id),group=svg('g',{});group.append(svg('rect',{x:p.x,y:p.y,width:270,height:68,rx:7}));for(const [i,line]of [n.id,(n.state||n.status||'PENDING')+' / '+(n.verdict||'UNVERIFIED')].entries()){const t=svg('text',{x:p.x+10,y:p.y+24+i*22});t.textContent=line;group.append(t)}group.onclick=()=>show('task-detail',n);g.append(group)}}
function render(data){const s=data.snapshot,c=data.controller,b=s.budgets||s;show('summary',(c.running?'Controller thread running':'Controller idle')+' · '+(s.phase||'BOUND')+(s.paused?' · Dispatch paused':'')+(s.stopped||c.stop_requested?' · Stop requested':'')+(s.all_verified===true?' · Core acceptance + integration verified':' · Acceptance / integration not established'));const limits={};for(const name of caps)limits[name]=b[name]??'Unlimited';show('state',{roles:s.roles,aggregate_caps:limits,counters:s.counters||{},unresolved:s.unresolved||[],reason:s.reason||'',controller:c});const nodes=s.nodes||s.tasks||s.plan?.tasks||s.graph?.tasks||[];graph(Array.isArray(nodes)?nodes:[]);show('dag',s.graph||s.plans||s.plan||nodes);show('attempts',s.attempts||s.runs||[]);show('diagnoses',s.diagnoses||[]);show('reviews',s.reviews||s.review_evidence||[]);const checks=Array.isArray(nodes)?nodes.flatMap(n=>n.verification?.checks||[]):[];show('tests',s.tests||s.test_evidence||s.evidence||checks);show('integration',s.integration||{status:'No integration evidence'});show('rsi',{current_procedure:s.procedure||null,rsi:s.rsi||null,procedures:s.procedures||[],improvements:s.improvements||[]});show('snapshot',s);show('controls',data.controls)}
async function pollOnce(){if(!selected)return;const id=selected;const data=await api('/api/snapshot?mission_id='+encodeURIComponent(id));if(id!==selected)return;render(data);const batch=await api('/api/events?mission_id='+encodeURIComponent(id)+'&cursor='+cursor);if(id!==selected)return;cursor=batch.cursor;eventRows.push(...batch.events);eventRows=eventRows.slice(-250);show('events',eventRows)}
async function poll(){try{if(!selected)await inventory();await pollOnce();show('connection','LIVE · persisted per-mission state · '+new Date().toLocaleTimeString());$('connection').className='ok'}catch(e){show('connection','STALE / ERROR · '+e.message);$('connection').className='bad'}setTimeout(poll,1500)}permissions();inventory().then(poll).catch(e=>{show('connection',e.message);setTimeout(poll,1500)});
</script></html>'''


class LeadConsole(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, hub: MissionHub, *, port: int = DEFAULT_PORT):
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("port must be an integer in [0,65535]")
        self.hub = hub
        self.token = secrets.token_urlsafe(32)
        self._chats = None
        self._chat_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"

    @property
    def chats(self):
        from .lead_chat import ChatSessions
        with self._chat_lock:
            if self._chats is None:
                self._chats = ChatSessions(self.hub)
            return self._chats

    def server_close(self):
        if self._chats is not None:
            self._chats.close()
        super().server_close()

    @property
    def url(self) -> str:
        return self.origin + "/#token=" + self.token


# Named alias for hosts that already use the worker Console naming convention.
Console = LeadConsole


class Handler(BaseHTTPRequestHandler):
    server: LeadConsole

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_args: Any) -> None:
        pass  # Bearer/query/body data must not enter access logs.

    def send(self, value: Any, status: int = 200, *, html: bool = False, nonce: str = "") -> None:
        raw = value.encode() if html else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        self.send_header("Content-Security-Policy", "default-src 'none'; connect-src 'self'; "
                         f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                         "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def fail(self, exc: Exception, status: int) -> None:
        self.send({"error": safe_error(exc, token=self.server.token)}, status)

    def boundary(self, *, auth: bool = True) -> bool:
        hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host_values = self.headers.get_all("Host", [])
        origins = self.headers.get_all("Origin", [])
        if len(host_values) != 1 or host_values[0] not in hosts:
            self.fail(PermissionError("invalid Host; use the printed loopback URL"), 403)
            return False
        if len(origins) > 1 or (origins and origins[0] != "http://" + host_values[0]):
            self.fail(PermissionError("cross-origin request rejected"), 403)
            return False
        if auth:
            values = self.headers.get_all("Authorization", [])
            if len(values) != 1 or not hmac.compare_digest(values[0].encode(), ("Bearer " + self.server.token).encode()):
                self.fail(PermissionError("bearer authorization required; open the printed token-fragment URL"), 401)
                return False
            if any(name.lower() == "x-sisyfus-node"
                   or name.lower().startswith(("x-node-", "x-sisyfus-node-")) for name in self.headers):
                self.fail(PermissionError("node identity headers do not grant operator access"), 403)
                return False
        return True

    def query(self, raw: str) -> dict[str, list[str]]:
        if len(raw.encode()) > 16_384 or re.search(r"%(?![0-9A-Fa-f]{2})", raw):
            raise ValueError("invalid or oversized URL query")
        return parse_qs(raw, keep_blank_values=True, strict_parsing=True,
                        errors="strict", max_num_fields=8)

    def cursor(self, value: str) -> int:
        if not re.fullmatch(r"[0-9]{1,19}", value):
            raise ValueError("cursor must be bounded unsigned decimal text")
        result = int(value)
        validate_cursor(result)
        return result

    def do_GET(self) -> None:
        if not self.boundary(auth=self.path.split("?", 1)[0] not in {"/", "/console"}):
            return
        try:
            route = urlsplit(self.path)
            node_route = _NODE_ROUTE.fullmatch(route.path)
            if route.path in {"/", "/console"}:
                nonce = secrets.token_urlsafe(18)
                if route.path == "/":
                    from .lead_chat_page import PAGE as CHAT_PAGE
                    page = CHAT_PAGE
                else:
                    page = PAGE
                self.send(page.replace("NONCE", nonce), html=True, nonce=nonce)
            elif route.path == "/api/chats":
                self.send(self.server.chats.inventory())
            elif route.path == "/api/chat":
                query = self.query(route.query)
                if set(query) != {"chat_id"} or len(query["chat_id"]) != 1:
                    raise ValueError("chat query requires exactly one chat_id")
                self.send(self.server.chats.get(query["chat_id"][0]))
            elif route.path == "/api/missions":
                self.send(self.server.hub.inventory())
            elif node_route and node_route[2] == "nodes" and node_route[3] is None:
                if route.query:
                    raise ValueError("node inventory accepts no query fields")
                self.send(self.server.hub.nodes(node_route[1]))
            elif node_route and node_route[2] == "placements" and node_route[3] is None:
                if route.query or "?" in self.path:
                    raise ValueError("placement readback accepts no query")
                self.send(self.server.hub.placements(node_route[1]))
            elif route.path == "/api/mission/messages":
                query = self.query(route.query)
                if set(query) - {"mission_id", "cursor", "application_cursor"} or any(len(v) != 1 for v in query.values()):
                    raise ValueError("invalid mission message query")
                ident = query.get("mission_id", ["mission" if self.server.hub.single else ""])[0]
                self.send(self.server.hub.messages(ident, self.cursor(query.get("cursor", ["0"])[0]),
                    application_cursor=self.cursor(query.get("application_cursor", ["0"])[0])))
            elif route.path in {"/api/snapshot", "/api/events"}:
                query = self.query(route.query)
                if set(query) - {"mission_id", "cursor"} or any(len(v) != 1 for v in query.values()):
                    raise ValueError("invalid query fields")
                ident = query.get("mission_id", ["mission" if self.server.hub.single else ""])[0]
                if route.path == "/api/snapshot":
                    requested = self.headers.get_all("X-Sisyfus-Engineering-Result", [])
                    if requested and (len(requested) != 1 or requested[0] != "1"):
                        raise ValueError("engineering result header must be exactly one value 1")
                    cap = self.server.hub.snapshot(ident)
                    if requested:
                        self.send({**cap, "engineering_result": _engineering_sidecar(cap, self.server.token)})
                    else:
                        self.send(cap)
                else:
                    self.send(self.server.hub.events(ident, self.cursor(query.get("cursor", ["0"])[0])))
            else:
                self.fail(ValueError("route not found"), 404)
        except PermissionError as exc:
            self.fail(exc, 403)
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError) as exc:
            self.fail(exc, 400)
        except FileNotFoundError as exc:
            self.fail(exc, 404)
        except Exception as exc:
            self.fail(exc, 500)

    def body(self) -> dict[str, Any]:
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
            raise ValueError("one Content-Length is required; streaming JSON is unsupported")
        if not re.fullmatch(r"[0-9]{1,6}", lengths[0]):
            raise ValueError("Content-Length must be bounded unsigned decimal text")
        length = int(lengths[0])
        if not 0 < length <= MAX_JSON_BYTES:
            raise ValueError(f"JSON body must be 1..{MAX_JSON_BYTES} bytes")
        if len(self.headers.get_all("Content-Type", [])) != 1 or self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError("incomplete JSON body")
        def constant(value: str) -> Any:
            raise ValueError("nonfinite JSON constant rejected: " + value)
        def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
            result = {}
            for key, value in values:
                if key in result:
                    raise ValueError("duplicate JSON field: " + key)
                result[key] = value
            return result
        body = json.loads(raw.decode("utf-8"), parse_constant=constant, object_pairs_hook=pairs)
        if not isinstance(body, dict):
            raise ValueError("request JSON must be an object")
        return body

    def do_POST(self) -> None:
        if not self.boundary():
            return
        try:
            route = urlsplit(self.path)
            node_route = _NODE_ROUTE.fullmatch(route.path)
            preparation_route = _PREPARATION_ROUTE.fullmatch(route.path)
            if node_route and node_route[2] == "placements" and node_route[3] is not None:
                node_route = None
            if self.path not in {"/api/missions", "/api/control", "/api/chats", "/api/chat/context", "/api/chat/message", "/api/chat/start", "/api/chat/attach_mission", "/api/chat/prepare_directory", "/api/chat/prepare-placement", "/api/mission/message"} and node_route is None and preparation_route is None:
                self.fail(ValueError("route not found"), 404)
                return
            if (node_route or preparation_route) and route.query:
                raise ValueError("node operator routes accept no query fields")
            body = self.body()
            if preparation_route:
                if set(body) != {"request_id", "allow_planning"}:
                    raise ValueError("preparation requires exactly request_id and allow_planning")
                if type(body["allow_planning"]) is not bool:
                    raise ValueError("allow_planning must be boolean")
                self.send(self.server.hub.prepare_placement(preparation_route[1], body["request_id"],
                          allow_planning=body["allow_planning"]), 202)
            elif node_route:
                ident, resource, node_id = node_route.groups()
                if resource == "placements":
                    if set(body) != {"request_id", "task_id", "node_id"}:
                        raise ValueError("placement requires exactly request_id, task_id and node_id")
                    self.send(self.server.hub.assign_placement(ident, body["task_id"], body["node_id"], body["request_id"]))
                elif node_id is not None:
                    if body:
                        raise ValueError("node revocation requires an empty object")
                    self.send(self.server.hub.revoke_node(ident, node_id))
                else:
                    if set(body) != {"request_id", "name"}:
                        raise ValueError("node enrollment requires exactly request_id and name")
                    result = self.server.hub.enroll_node(ident, body["request_id"], body["name"])
                    self.send(result, 201 if result["secret"] is not None else 200)
            elif self.path == "/api/mission/message":
                if set(body) - {"mission_id", "message", "request_id", "task_id"} or not {"mission_id", "message", "request_id"} <= set(body):
                    raise ValueError("mission message requires mission_id, message, request_id and optional task_id")
                self.send(self.server.hub.message(body["mission_id"], body["message"], body["request_id"],
                                                  task_id=body.get("task_id")))
            elif self.path == "/api/chats":
                if body:
                    raise ValueError("new conversation requires an empty object")
                self.send(self.server.chats.create(), 201)
            elif self.path.startswith("/api/chat/"):
                action = self.path.rsplit("/", 1)[1]
                fields = {"context": {"chat_id", "source", "spec_path"}, "message": {"chat_id", "message", "request_id"},
                          "start": {"chat_id", "allow_local_workers", "request_id", "approval_hash"},
                          "attach_mission": {"chat_id", "mission_id"},
                          "prepare_directory": {"chat_id", "request_id"},
                          "prepare-placement": {"chat_id", "allow_planning", "request_id", "approval_hash"}}[action]
                if set(body) != fields:
                    raise ValueError("invalid conversation fields for " + action)
                if action == "prepare-placement":
                    if type(body["allow_planning"]) is not bool:
                        raise ValueError("allow_planning must be boolean")
                    if not body["allow_planning"]:
                        raise PermissionError("explicit planning permission required")
                    result = self.server.chats.prepare_placement(body["chat_id"], body["allow_planning"],
                                                               body["request_id"], body["approval_hash"])
                elif action == "prepare_directory":
                    result = self.server.chats.prepare_directory(body["chat_id"], body["request_id"])
                elif action == "attach_mission":
                    result = self.server.chats.attach_mission(body["chat_id"], body["mission_id"])
                elif action == "context":
                    result = self.server.chats.context(body["chat_id"], body["source"], body["spec_path"])
                elif action == "message":
                    result = self.server.chats.message(body["chat_id"], body["message"], body["request_id"])
                else:
                    result = self.server.chats.start(body["chat_id"], body["allow_local_workers"], body["request_id"], body["approval_hash"])
                self.send(result, 202 if action in {"message", "start", "prepare-placement"} else 200)
            elif self.path == "/api/missions":
                if self.server.hub.single:
                    raise ValueError("single console is select-only; use hub or CLI new to create")
                if set(body) != {"spec"} or not isinstance(body["spec"], dict):
                    raise ValueError("create requires exactly {spec: object}; control paths are server-owned")
                self.send(self.server.hub.create(body["spec"]), 201)
            else:
                if set(body) - {"mission_id", "action", "allow_local_workers", "max_cycles"}:
                    raise ValueError("unknown control fields")
                if "allow_local_workers" in body and type(body["allow_local_workers"]) is not bool:
                    raise ValueError("allow_local_workers must be boolean")
                ident = body.get("mission_id", "mission" if self.server.hub.single else "")
                self.send(self.server.hub.control(ident, body.get("action"),
                          allow_local_workers=body.get("allow_local_workers", False),
                          max_cycles=body.get("max_cycles")), 202)
        except PermissionError as exc:
            self.fail(exc, 403)
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError, TimeoutError) as exc:
            self.fail(exc, 400)
        except FileNotFoundError as exc:
            self.fail(exc, 404)
        except RuntimeError as exc:
            self.fail(exc, 409)
        except Exception as exc:
            self.fail(exc, 500)
