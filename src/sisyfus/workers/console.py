from __future__ import annotations

import hmac
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ..ui_theme import ARENA_THEME_CSS
from .mission import Mission

PAGE = r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sisyfus · Native Mission Control</title><style nonce="NONCE">THEME
body{padding:28px;max-width:1680px;margin:auto}header{display:flex;align-items:center;justify-content:space-between;gap:20px}h1{font-size:27px;margin:8px 0}h2{font-size:15px;color:var(--gold)}button{background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:9px 15px;cursor:pointer}button:hover{border-color:var(--gold)}.eyebrow{color:var(--gold);font-size:12px;letter-spacing:.15em}.muted{color:var(--muted)}#objective{max-width:900px;line-height:1.5}.bar{display:flex;gap:20px;flex-wrap:wrap;padding:18px 0;margin:18px 0;border-block:1px solid var(--line)}.layout{display:grid;grid-template-columns:1.7fr 1fr;gap:20px}section{background:var(--panel);border:1px solid var(--line);padding:18px;border-radius:12px;overflow:auto}svg{min-width:500px;width:100%}.node{cursor:pointer}.node rect{fill:var(--surface);stroke:var(--line);stroke-width:2}.node text{fill:var(--ink);font:12px var(--font-mono)}.node .title{font-size:14px;font-weight:700}.node.pass rect{stroke:var(--radiant)}.node.fail rect{stroke:var(--dire)}.node.wait rect{stroke:var(--amber)}.edge{stroke:var(--muted);stroke-width:1.5;fill:none}.attemptsection{margin-top:20px}.attempt{display:block;width:100%;text-align:left;margin:8px 0}.attempt.fail{border-color:var(--dire)}.attempt.pass{border-color:var(--radiant)}.attempt small{display:block;color:var(--muted);margin-top:5px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.6 var(--font-mono);max-height:500px;overflow:auto}#feed{font:12px/1.6 var(--font-mono);max-height:220px;overflow:auto;margin-top:20px}.ok{color:var(--radiant)}.bad{color:var(--dire)}#control{display:flex;gap:8px;margin:12px 0}input{padding:9px;background:var(--surface);border:1px solid var(--line);color:var(--ink);border-radius:6px;max-width:100%}.notice{border-left:3px solid var(--gold);padding-left:14px;font-size:13px;line-height:1.6}@media(max-width:850px){body{padding:14px}.layout{grid-template-columns:1fr}header{align-items:flex-start;flex-direction:column}}
</style><header><div><div class="eyebrow">SISYFUS / NATIVE WORKERS</div><h1>Mission Control</h1><div id="connection" class="muted">Connecting…</div></div><div><button id="pause">Pause dispatch</button> <button id="resume">Resume dispatch</button></div></header>
<p id="objective"></p><div class="bar"><span id="calls"></span><span id="verification"></span><span id="unresolved"></span><span id="kind" class="muted"></span></div>
<div class="layout"><div><section><h2>01 / Task dependencies</h2><svg id="graph" role="img" aria-label="Task dependency graph"></svg><p class="muted">Execution status and verification verdict are separate. Click a node for evidence.</p></section><section class="attemptsection"><h2>02 / Agent attempts · retries preserved</h2><div id="attempts"></div></section></div><section><h2>03 / Inspector</h2><div id="control"></div><pre id="detail">Select a task or attempt.</pre></section></div>
<section id="feed"><h2>04 / Persisted event stream</h2><div id="eventrows"></div></section><p class="notice">UNKNOWN blocks spending; it is not a failed hypothesis. Pause stops new dispatch, not running tools. Reported provider cost is not an invoice. This pilot requires trusted local workers or external OS isolation.</p>
<script nonce="NONCE">
let token=new URLSearchParams(location.hash.slice(1)).get('token')||sessionStorage.getItem('sisyfus-token')||'';
if(token){sessionStorage.setItem('sisyfus-token',token);history.replaceState(null,'',location.pathname)}
let cursor=0,last=0,selection=null,snapshot=null,signature='';const $=id=>document.getElementById(id),ns='http://www.w3.org/2000/svg';
async function api(path,body){let r=await fetch(path,{method:body?'POST':'GET',headers:{Authorization:'Bearer '+token,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});let data=await r.json();if(!r.ok)throw Error(data.error||r.status);return data}
function text(tag,value){let e=document.createElement(tag);e.textContent=value;return e}
async function action(body){try{const r=await api('/api/control',body);$('detail').textContent=JSON.stringify(r,null,2)}catch(e){$('detail').textContent=e.message}}
$('pause').onclick=()=>action({action:'pause'});$('resume').onclick=()=>action({action:'resume'});
function inspect(value){selection=value;$('detail').textContent=JSON.stringify(value,null,2);$('control').replaceChildren();if(value.key&&value.status==='IN_FLIGHT'){let b=text('button','Interrupt attempt');b.onclick=()=>action({action:'interrupt',run_key:value.key});$('control').append(b);if((value.controls||[]).includes('steer')){let input=document.createElement('input');input.placeholder='Additional instruction';let send=text('button','Send');send.onclick=()=>action({action:'steer',run_key:value.key,text:input.value});$('control').append(input,send)}}}
function svg(tag,attrs){let e=document.createElementNS(ns,tag);for(let [k,v] of Object.entries(attrs))e.setAttribute(k,v);return e}
function render(s){$('objective').textContent=s.objective;$('calls').textContent=`Reserved native calls: ${s.native_call_reservations} / ${s.max_calls}`;$('verification').textContent=s.all_verified?'All tasks verified':'Acceptance not yet established';$('verification').className=s.all_verified?'ok':'muted';$('unresolved').textContent=`Unresolved: ${s.unresolved.length}`;$('kind').textContent=s.validation_kind+(s.paused?' · DISPATCH PAUSED':'');
let sig=JSON.stringify([s.nodes,s.runs]);if(sig===signature)return;signature=sig;const graph=$('graph');graph.replaceChildren();let depths={},positions={},counts={};function depth(n){if(depths[n.id]!==undefined)return depths[n.id];return depths[n.id]=n.depends_on.length?1+Math.max(...n.depends_on.map(id=>depth(s.nodes.find(x=>x.id===id)||{id,depends_on:[]}))):0}
for(let n of s.nodes){let d=depth(n),row=counts[d]||0;counts[d]=row+1;positions[n.id]={x:20+d*235,y:20+row*115}}let width=255+Math.max(0,...Object.values(depths))*235,height=130*Math.max(1,...Object.values(counts));graph.setAttribute('viewBox',`0 0 ${width} ${height}`);
for(let n of s.nodes)for(let id of n.depends_on){let a=positions[id],b=positions[n.id];if(a&&b)graph.append(svg('path',{class:'edge',d:`M${a.x+205},${a.y+42} L${b.x},${b.y+42}`}))}
for(let n of s.nodes){let p=positions[n.id],g=svg('g',{class:'node '+(n.stale||n.verdict==='FAIL'?'fail':n.verdict==='PASS'?'pass':'wait'),transform:`translate(${p.x},${p.y})`});g.append(svg('rect',{width:205,height:88,rx:8}));for(let [i,line]of [n.id,n.state+' / '+n.verdict,n.stale?'STALE EVIDENCE':n.driver+' · attempts '+n.attempts].entries()){let t=svg('text',{x:12,y:24+i*23,class:i===0?'title':''});t.textContent=line;g.append(t)}g.onclick=()=>inspect(n);graph.append(g)}
$('attempts').replaceChildren();let previous={};for(let r of s.runs){let b=text('button',r.task_id+' · '+(r.receipt?r.receipt.status:r.status)+' / '+r.verdict);b.className='attempt '+(r.verdict==='FAIL'?'fail':r.verdict==='PASS'?'pass':'');b.append(text('small',r.key+(previous[r.task_id]?' · retry of '+previous[r.task_id]:'')));previous[r.task_id]=r.key;b.onclick=()=>inspect(r);$('attempts').append(b)}if(selection&&selection.key){let updated=s.runs.find(r=>r.key===selection.key);if(updated)inspect(updated)}}
async function poll(){try{snapshot=await api('/api/snapshot');render(snapshot);let batch=await api('/api/events?cursor='+cursor);for(let e of batch.events){cursor=e.seq;let row=text('div',`${e.seq} · ${e.type} · ${e.run_key}`);row.onclick=()=>inspect(e);$('eventrows').append(row)}while($('eventrows').children.length>250)$('eventrows').firstChild.remove();last=Date.now();$('connection').textContent='LIVE · persisted state · '+new Date(last).toLocaleTimeString();$('connection').className='ok'}catch(e){$('connection').textContent='STALE / DISCONNECTED · '+e.message;$('connection').className='bad'}setTimeout(poll,1000)}poll();
</script></html>'''


class Console(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, mission: Mission, *, port: int = 8780):
        self.mission = mission
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"

    @property
    def url(self) -> str:
        return self.origin + "/#token=" + self.token


class Handler(BaseHTTPRequestHandler):
    server: Console

    def log_message(self, *_args: Any) -> None:
        pass  # Never write bearer credentials or prompt text to access logs.

    def send(self, value: Any, status: int = 200, *, html: bool = False, nonce: str = "") -> None:
        raw = value.encode() if html else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if html:
            self.send_header("Content-Security-Policy", f"default-src 'self'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self) -> bool:
        allowed_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in allowed_hosts:
            self.send({"error": "invalid Host"}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + h for h in allowed_hosts}:
            self.send({"error": "cross-origin request rejected"}, 403)
            return False
        authorization = self.headers.get("Authorization", "")
        if not hmac.compare_digest(authorization, "Bearer " + self.server.token):
            self.send({"error": "authorization required; open the URL printed by the local server"}, 401)
            return False
        return True

    def do_GET(self) -> None:
        from urllib.parse import parse_qs, urlsplit
        route = urlsplit(self.path)
        if route.path == "/":
            nonce = secrets.token_urlsafe(16)
            self.send(PAGE.replace("THEME", ARENA_THEME_CSS).replace("NONCE", nonce), html=True, nonce=nonce)
            return
        if not self.authorized():
            return
        try:
            if route.path == "/api/snapshot":
                self.send(self.server.mission.snapshot())
            elif route.path == "/api/events":
                cursor = int(parse_qs(route.query).get("cursor", ["0"])[0])
                events = self.server.mission.journal.events(cursor)
                self.send({"events": events, "cursor": events[-1]["seq"] if events else cursor})
            else:
                self.send({"error": "not found"}, 404)
        except (ValueError, KeyError) as exc:
            self.send({"error": str(exc)}, 400)

    def do_POST(self) -> None:
        if not self.authorized():
            return
        if self.path != "/api/control":
            self.send({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 32_000:
                raise ValueError("control request too large or empty")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or set(body) - {"action", "run_key", "text"}:
                raise ValueError("invalid control fields")
            action = body.get("action")
            if action in {"pause", "resume"}:
                self.server.mission.journal.pause(action == "pause")
                result = {"accepted": True, "action": action, "scope": "new_dispatch_only"}
            else:
                ident = self.server.mission.journal.command(body["run_key"], action, body.get("text", ""))
                result = {"accepted": True, "id": ident, "status": "PENDING", "terminal": False}
            self.send(result, 202)
        except (ValueError, KeyError, TypeError, RuntimeError) as exc:
            self.send({"error": str(exc)}, 400)
