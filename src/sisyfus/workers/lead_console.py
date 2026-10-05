"""Local operator surface for LeadMission; never a second mission truth store.

MissionHub(directory) inventories fixed child control directories.  Use
MissionHub(directory, single=True) for an existing single mission. Constructors,
inventory and page loads do not dispatch work. Only start/control('start',
allow_local_workers=True) admits a controller thread. Core owns execution
fencing, acceptance, integration and restart reconciliation.
"""
from __future__ import annotations

import hmac
import json
import re
import secrets
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlsplit

from .lead_contracts import SCHEMA, load_lead_spec
from .protocol import redact

DEFAULT_PORT = 8781
MAX_JSON_BYTES = 200_000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def lead_mission(directory: Path, spec: dict[str, Any] | None = None) -> Any:
    """Lazy core boundary, also injectable through MissionHub.mission_factory."""
    from .lead_mission import LeadMission
    return LeadMission(directory, spec)


def safe_error(exc: Exception, *, token: str = "") -> dict[str, str]:
    message = str(redact(str(exc)))
    if token:
        message = message.replace(token, "[REDACTED]")
    return {"type": type(exc).__name__, "message": message[:4000]}


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


class _Session:
    def __init__(self, mission: Any):
        self.mission = mission
        self.lock = threading.RLock()
        self.thread: threading.Thread | None = None
        self.error: dict[str, str] | None = None
        self.result: Any = None
        self.permission = False


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
            self._sessions[ident] = _Session(mission)
        return {"id": ident, "directory": str(control), "status": "BOUND",
                "started": False, "snapshot": self.snapshot(ident)}

    def _session(self, ident: str) -> _Session:
        with self._lock:
            control = self.path(ident)
            approved_spec(control)
            if ident not in self._sessions:
                self._sessions[ident] = _Session(self.mission_factory(control))
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
        # Core snapshot is the only task/integration/RSI truth projection.
        snap = session.mission.snapshot()
        with session.lock:
            running = bool(session.thread and session.thread.is_alive())
            runtime = {"running": running, "local_workers_acknowledged": session.permission,
                       "error": session.error, "stop_requested": session.mission.stop.is_set(),
                       "auto_start": False}
        return {"id": ident, "snapshot": redact(snap), "controller": runtime,
                "controls": self.controls(ident)}

    def events(self, ident: str, cursor: int = 0) -> dict[str, Any]:
        if type(cursor) is not int or cursor < 0:
            raise ValueError("cursor must be a nonnegative integer")
        batch = self._session(ident).mission.journal.events(cursor)
        return {"events": redact(batch), "cursor": batch[-1]["seq"] if batch else cursor}

    def control(self, ident: str, action: str, *, allow_local_workers: bool = False,
                max_cycles: int | None = None) -> dict[str, Any]:
        if action not in {"start", "pause", "resume", "stop"}:
            raise ValueError("action must be start, pause, resume or stop")
        if max_cycles is not None and (type(max_cycles) is not int or max_cycles < 1):
            raise ValueError("max_cycles must be a positive integer or null")
        if action == "start" and allow_local_workers is not True:
            raise PermissionError("Start requires explicit local-worker permission; CLI: --allow-local-workers")
        session = self._session(ident)
        with session.lock:
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
        with self._lock:
            active = [s for s in self._sessions.values() if s.thread and s.thread.is_alive()]
        for session in active:
            session.mission.request_stop()
        for session in active:
            session.thread.join()


PAGE = r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sisyfus · Tech Lead Mission Hub</title><style nonce="NONCE">
*{box-sizing:border-box}body{margin:0;padding:24px;background:#0f1420;color:#e6eaf2;font:15px/1.5 system-ui}header{display:flex;justify-content:space-between;flex-wrap:wrap;gap:12px}h1{margin:0;font-size:26px}h2{font-size:17px;color:#dfba73}main{display:grid;grid-template-columns:minmax(280px,1fr) minmax(0,2fr);gap:20px;margin-top:20px}section{background:#192131;border:1px solid #34435b;border-radius:10px;padding:18px;margin-bottom:16px}label{display:block;margin-top:10px}input,textarea,select,button{font:inherit;color:inherit;background:#101827;border:1px solid #536582;border-radius:5px;padding:8px}input:not([type=checkbox]),textarea,select{width:100%}textarea{min-height:90px;font-family:monospace}button{cursor:pointer;margin:6px 5px 6px 0}button:disabled{opacity:.4;cursor:default}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:400px;overflow:auto;font-size:12px}.row{display:flex;gap:10px;flex-wrap:wrap}.row label{flex:1;min-width:140px}.muted{color:#adbed5}.notice{border-left:3px solid #dfba73;padding-left:12px}.bad{color:#ffb0b0}.ok{color:#a5ebbf}svg{width:100%;min-height:100px;max-height:550px}svg text{fill:#e6eaf2;font:12px monospace}svg rect{fill:#243249;stroke:#829abf}svg path{stroke:#adbed5;fill:none}.caps label{min-width:130px}@media(max-width:850px){main{grid-template-columns:1fr}body{padding:12px}}
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
        return True

    def do_GET(self) -> None:
        route = urlsplit(self.path)
        if not self.boundary(auth=route.path not in {"/", "/console"}):
            return
        try:
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
                query = parse_qs(route.query, keep_blank_values=True)
                if set(query) != {"chat_id"} or len(query["chat_id"]) != 1:
                    raise ValueError("chat query requires exactly one chat_id")
                self.send(self.server.chats.get(query["chat_id"][0]))
            elif route.path == "/api/missions":
                self.send(self.server.hub.inventory())
            elif route.path in {"/api/snapshot", "/api/events"}:
                query = parse_qs(route.query, keep_blank_values=True)
                if set(query) - {"mission_id", "cursor"} or any(len(v) != 1 for v in query.values()):
                    raise ValueError("invalid query fields")
                ident = query.get("mission_id", ["mission" if self.server.hub.single else ""])[0]
                if route.path == "/api/snapshot":
                    self.send(self.server.hub.snapshot(ident))
                else:
                    self.send(self.server.hub.events(ident, int(query.get("cursor", ["0"])[0])))
            else:
                self.fail(ValueError("route not found"), 404)
        except (ValueError, TypeError, KeyError) as exc:
            self.fail(exc, 400)
        except FileNotFoundError as exc:
            self.fail(exc, 404)
        except Exception as exc:
            self.fail(exc, 500)

    def body(self) -> dict[str, Any]:
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
            raise ValueError("one Content-Length is required; streaming JSON is unsupported")
        length = int(lengths[0])
        if not 0 < length <= MAX_JSON_BYTES:
            raise ValueError(f"JSON body must be 1..{MAX_JSON_BYTES} bytes")
        if self.headers.get_content_type() != "application/json":
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
            if self.path not in {"/api/missions", "/api/control", "/api/chats", "/api/chat/context", "/api/chat/message", "/api/chat/start", "/api/chat/attach_mission"}:
                self.fail(ValueError("route not found"), 404)
                return
            body = self.body()
            if self.path == "/api/chats":
                if body:
                    raise ValueError("new conversation requires an empty object")
                self.send(self.server.chats.create(), 201)
            elif self.path.startswith("/api/chat/"):
                action = self.path.rsplit("/", 1)[1]
                fields = {"context": {"chat_id", "source", "spec_path"}, "message": {"chat_id", "message", "request_id"},
                          "start": {"chat_id", "allow_local_workers", "request_id", "approval_hash"},
                          "attach_mission": {"chat_id", "mission_id"}}[action]
                if set(body) != fields:
                    raise ValueError("invalid conversation fields for " + action)
                if action == "attach_mission":
                    result = self.server.chats.attach_mission(body["chat_id"], body["mission_id"])
                elif action == "context":
                    result = self.server.chats.context(body["chat_id"], body["source"], body["spec_path"])
                elif action == "message":
                    result = self.server.chats.message(body["chat_id"], body["message"], body["request_id"])
                else:
                    result = self.server.chats.start(body["chat_id"], body["allow_local_workers"], body["request_id"], body["approval_hash"])
                self.send(result, 202 if action in {"message", "start"} else 200)
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
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
            self.fail(exc, 400)
        except FileNotFoundError as exc:
            self.fail(exc, 404)
        except RuntimeError as exc:
            self.fail(exc, 409)
        except Exception as exc:
            self.fail(exc, 500)
