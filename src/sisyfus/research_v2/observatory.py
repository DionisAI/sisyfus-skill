from __future__ import annotations

import html
import json
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from .workspace import ResearchWorkspace, atomic_write_json


def _json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).replace("</", "<\\/")


# Esports-broadcast Observatory ("Arena"): claims are bosses on a dependency map,
# the agent is the hero, verdicts land as hits/counter-kills, budget drains as HP.
# Every visual is a projection of persisted facts; replay frames are deterministic
# re-reductions of the event prefix — spectacle, never invention.
_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Sisyfus Arena · __TOPIC__</title>
<style>
:root {
  color-scheme: dark;
  --arena:oklch(0.17 0.018 75);           /* warm charcoal stadium */
  --arena-deep:oklch(0.13 0.015 75);
  --panel:oklch(0.21 0.02 80);
  --line:oklch(0.32 0.03 85);
  --ink:oklch(0.93 0.02 90);
  --muted:oklch(0.66 0.03 85);
  --radiant:oklch(0.78 0.17 150);         /* verified */
  --dire:oklch(0.62 0.21 25);             /* refuted */
  --gold:oklch(0.82 0.13 88);             /* loot / lessons */
  --amber:oklch(0.78 0.14 75);            /* open / inconclusive */
  --ghost:oklch(0.62 0.12 310);           /* invalid / error */
  --hp:oklch(0.66 0.19 30);
  --mana:oklch(0.7 0.1 230);
}
* { box-sizing:border-box; }
body { margin:0; background:var(--arena-deep); color:var(--ink);
  font-family:-apple-system,"Helvetica Neue","PingFang SC","Microsoft YaHei",sans-serif; }
.caps { text-transform:uppercase; letter-spacing:.14em; font-weight:800; }
.mono { font-family:ui-monospace,Menlo,Consolas,monospace; }

/* ---------- broadcast top bar ---------- */
.topbar { display:flex; align-items:stretch; gap:0; border-bottom:2px solid var(--line);
  background:linear-gradient(180deg, oklch(0.24 0.025 80), oklch(0.18 0.02 78)); }
.scorebox { display:flex; align-items:center; gap:14px; padding:10px 22px; }
.score { font-size:44px; font-weight:900; line-height:1; letter-spacing:-.03em; font-variant-numeric:tabular-nums; }
.score.radiant { color:var(--radiant); } .score.dire { color:var(--dire); }
.score-label { font-size:10px; color:var(--muted); }
.vs { align-self:center; font-size:13px; color:var(--muted); font-weight:900; padding:0 4px; }
.matchinfo { flex:1; min-width:0; padding:9px 18px; border-left:1px solid var(--line); }
.matchinfo h1 { margin:0; font-size:14px; font-weight:700; line-height:1.35; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
.matchinfo .sub { font-size:11px; color:var(--muted); margin-top:4px; display:flex; gap:14px; flex-wrap:wrap; }
.bars { width:280px; padding:10px 18px; border-left:1px solid var(--line); display:grid; gap:7px; align-content:center; }
.bar { position:relative; height:14px; background:oklch(0.13 0.01 75); border:1px solid var(--line); overflow:hidden; }
.bar > i { position:absolute; inset:0; transform-origin:left; transition:transform .5s cubic-bezier(.16,1,.3,1); }
.bar.hp > i { background:linear-gradient(90deg, var(--hp), oklch(0.72 0.17 55)); }
.bar.mana > i { background:var(--mana); }
.bar b { position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
  font-size:9px; letter-spacing:.12em; color:oklch(0.98 0 0 / .92); mix-blend-mode:plus-lighter; }
.livechip { display:flex; align-items:center; gap:8px; padding:0 20px; border-left:1px solid var(--line);
  font-size:11px; font-weight:900; letter-spacing:.14em; white-space:nowrap; }
.livechip .dot { width:9px; height:9px; border-radius:50%; background:var(--dire); box-shadow:0 0 10px var(--dire);
  animation:pulse 1.8s ease-in-out infinite; }
.livechip.replaying .dot { background:var(--gold); box-shadow:0 0 10px var(--gold); }
.livechip.ended .dot { background:var(--muted); box-shadow:none; animation:none; }
@keyframes pulse { 50% { opacity:.4 } }
.lang-btn { font:inherit; font-weight:900; font-size:11px; letter-spacing:.1em; border:none; border-left:1px solid var(--line);
  background:transparent; color:var(--muted); padding:0 18px; cursor:pointer; }
.lang-btn:hover { color:var(--gold); }

/* ---------- stage: arena + right column ---------- */
.stage { display:grid; grid-template-columns:1fr 336px; }
.arena-wrap { position:relative; overflow:hidden; border-right:2px solid var(--line); }
.arena-wrap { display:flex; }
#arena { display:block; width:100%; height:100%; min-height:520px; max-height:min(72vh, 700px); flex:1;
  background:
    radial-gradient(120% 90% at 50% -10%, oklch(0.24 0.03 90 / .55), transparent 55%),
    radial-gradient(90% 120% at 50% 115%, oklch(0.1 0.02 60), transparent 60%),
    var(--arena); }
.shake { animation:shake .5s linear; }
@keyframes shake { 10%{transform:translate(-7px,3px)} 30%{transform:translate(6px,-4px)}
  50%{transform:translate(-5px,-3px)} 70%{transform:translate(4px,3px)} 90%{transform:translate(-2px,1px)} }

.boss-name { font-size:15px; font-weight:800; fill:var(--ink); }
.boss-num { font-size:11px; font-weight:900; fill:oklch(0.14 0.015 75); }
#bosses g.claim-node { cursor:pointer; }
#bosses g.selected .sel-ring { display:block; }
.sel-ring { display:none; }
.hero-bob { animation:bob 2.6s ease-in-out infinite; }
@keyframes bob { 50% { transform:translateY(-5px) } }

/* hover tip + unit card */
.tip { position:absolute; z-index:6; pointer-events:none; max-width:300px; background:oklch(0.13 0.012 75/.96);
  border:1px solid var(--gold); padding:9px 12px; font-size:11.5px; line-height:1.55; display:none; }
.tip b { color:var(--gold); }
.unit-card { position:absolute; left:50%; bottom:14px; transform:translateX(-50%); z-index:5;
  width:min(430px, calc(100% - 28px)); background:oklch(0.14 0.014 75/.93); backdrop-filter:blur(10px);
  border:1px solid var(--line); border-top:3px solid var(--gold); display:none; box-shadow:0 18px 50px oklch(0 0 0/.55); }
.unit-card.on { display:block; animation:ucin .32s cubic-bezier(.16,1,.3,1); }
@keyframes ucin { from { opacity:0; transform:translate(-50%,12px) } }
.uc-head { display:flex; align-items:baseline; gap:9px; padding:10px 13px 7px; }
.uc-num { font-weight:900; color:var(--gold); }
.uc-label { font-size:16px; font-weight:900; }
.uc-id { font-size:10px; color:var(--muted); }
.uc-close { margin-left:auto; cursor:pointer; color:var(--muted); font-size:14px; padding:0 3px; background:none; border:none; font:inherit; }
.uc-body { padding:0 13px 11px; font-size:11.5px; line-height:1.6; max-height:34vh; overflow-y:auto; }
.uc-sec { margin-top:8px; padding-top:7px; border-top:1px solid oklch(0.24 0.02 80); }
.uc-sec .k { font-size:9px; letter-spacing:.12em; color:var(--muted); text-transform:uppercase; font-weight:800; }
.uc-exp { display:flex; gap:8px; justify-content:space-between; font-size:11px; margin-top:4px; }
.edge { stroke:var(--line); stroke-width:2.5; fill:none; transition:stroke .45s, stroke-width .45s; }
.edge.lit { stroke:oklch(0.52 0.08 120); stroke-width:3; }
.edge.hot { stroke:var(--gold); stroke-width:3.2; stroke-dasharray:8 7; animation:dashmove 1.1s linear infinite; }
@keyframes dashmove { to { stroke-dashoffset:-30 } }

/* floating combat text */
.fx-layer { position:absolute; inset:0; pointer-events:none; overflow:hidden; }
.dmg { position:absolute; transform:translate(-50%,-50%); font-weight:900; white-space:nowrap;
  animation:dmg 1.5s cubic-bezier(.2,.9,.3,1) forwards; text-shadow:0 2px 14px oklch(0 0 0/.8); }
@keyframes dmg { 0%{opacity:0; transform:translate(-50%,-30%) scale(.4)}
  14%{opacity:1; transform:translate(-50%,-70%) scale(1.25)}
  30%{transform:translate(-50%,-90%) scale(1)}
  100%{opacity:0; transform:translate(-50%,-190%) scale(.92)} }
.dmg.pass { color:var(--radiant); font-size:30px; }
.dmg.fail { color:var(--dire); font-size:34px; }
.dmg.miss { color:var(--ghost); font-size:20px; }
.dmg.soft { color:var(--amber); font-size:20px; }
.dmg.loot { color:var(--gold); font-size:22px; }

/* announcer slam */
.announcer { position:absolute; left:0; right:0; top:34%; display:flex; justify-content:center; pointer-events:none; }
.announcer span { font-size:clamp(30px,5vw,58px); font-weight:900; letter-spacing:.06em; font-style:italic;
  padding:6px 34px; color:var(--ink); background:linear-gradient(90deg, transparent, oklch(0.1 0.01 60/.92) 18%, oklch(0.1 0.01 60/.92) 82%, transparent);
  border-block:2px solid currentColor; animation:slam 1.6s cubic-bezier(.16,1,.3,1) forwards; }
.announcer .radiant { color:var(--radiant); } .announcer .dire { color:var(--dire); }
.announcer .gold { color:var(--gold); } .announcer .ghost { color:var(--ghost); }
@keyframes slam { 0%{opacity:0; transform:scale(2.1)} 12%{opacity:1; transform:scale(1)}
  80%{opacity:1} 100%{opacity:0; transform:scale(.96) translateY(-8px)} }

.combo { position:absolute; right:16px; top:14px; font-size:15px; font-weight:900; color:var(--gold);
  letter-spacing:.1em; opacity:0; transition:opacity .3s; }
.combo.on { opacity:1; }

/* budget drain floaters (anchored inside .bar) */
.bar-fx { position:absolute; right:5px; top:-2px; z-index:2; font-size:11px; font-weight:900; pointer-events:none;
  animation:barfx 1.1s ease-out forwards; text-shadow:0 1px 6px oklch(0 0 0/.8); }
.bar-fx.down { color:oklch(0.85 0.13 30); }
@keyframes barfx { 12% { opacity:1; transform:translateY(0) } 100% { opacity:0; transform:translateY(-13px) } }

/* right column: kill feed + quest log */
.rightcol { display:flex; flex-direction:column; background:var(--panel); min-height:0; height:min(72vh, 700px); }
.col-h { padding:8px 14px 6px; font-size:10px; color:var(--muted); border-bottom:1px solid var(--line);
  display:flex; justify-content:space-between; align-items:baseline; }
#feed { flex:1.2; overflow-y:auto; min-height:170px; padding:6px 0; }
.feed-row { display:flex; gap:9px; padding:5px 14px; font-size:12px; line-height:1.45; align-items:baseline;
  animation:feedin .35s cubic-bezier(.16,1,.3,1); }
@keyframes feedin { from{opacity:0; transform:translateX(26px)} }
.feed-row[data-seq] { cursor:pointer; }
.feed-row[data-seq]:hover { background:oklch(0.25 0.022 80); }
.feed-row .seq { color:var(--muted); font-size:10px; min-width:30px; }
.feed-row .ts { margin-left:auto; color:var(--muted); font-size:9.5px; white-space:nowrap; opacity:.8; }
.feed-row.pass { border-left:3px solid var(--radiant); } .feed-row.fail { border-left:3px solid var(--dire); }
.feed-row.loot { border-left:3px solid var(--gold); } .feed-row.miss { border-left:3px solid var(--ghost); }
.feed-row.info { border-left:3px solid transparent; color:var(--muted); }
#quest { flex:1; overflow-y:auto; border-top:2px solid var(--line); min-height:150px; }
.q-row { padding:8px 14px; border-bottom:1px solid oklch(0.26 0.02 80); }
.q-row .q-title { display:flex; gap:8px; align-items:baseline; font-size:12.5px; font-weight:700; }
.q-mark { font-size:14px; width:20px; text-align:center; }
.q-row .q-state { margin-left:auto; font-size:9px; letter-spacing:.1em; font-weight:900; }
.q-row .q-sub { font-size:10.5px; color:var(--muted); margin-top:3px; padding-left:28px; }
.q-SUPPORTED .q-state { color:var(--radiant); } .q-REFUTED .q-state { color:var(--dire); }
.q-OPEN .q-state,.q-INCONCLUSIVE .q-state { color:var(--amber); } .q-INVALIDATED .q-state { color:var(--ghost); }

/* ---------- timeline (replay deck) ---------- */
.deck { display:flex; align-items:center; gap:14px; padding:10px 18px; background:oklch(0.15 0.015 75);
  border-block:2px solid var(--line); }
.deck button { font:inherit; font-weight:900; border:1px solid var(--line); background:var(--panel); color:var(--ink);
  padding:7px 13px; cursor:pointer; letter-spacing:.06em; }
.deck button.active { background:var(--gold); color:oklch(0.16 0.02 80); border-color:var(--gold); }
.deck select { font:inherit; background:var(--panel); color:var(--ink); border:1px solid var(--line); padding:6px 8px; }
.timeline { position:relative; flex:1; height:46px; }
.timeline input[type=range] { position:absolute; inset:0; width:100%; margin:0; opacity:0; cursor:pointer; z-index:3; }
.tl-track { position:absolute; left:0; right:0; top:15px; height:5px; background:oklch(0.28 0.02 80); }
.tl-fill { position:absolute; left:0; top:15px; height:5px; background:var(--gold); }
.tl-cursor { position:absolute; top:7.5px; width:20px; height:20px; border-radius:50%; background:var(--gold);
  border:2.5px solid oklch(0.16 0.02 80); box-shadow:0 0 0 2.5px oklch(0.82 0.13 88/.4), 0 2px 9px oklch(0 0 0/.65);
  transform:translateX(-50%); z-index:2; pointer-events:none; }
.tl-mark { position:absolute; top:11px; width:7px; height:13px; transform:translateX(-50%) skewX(-14deg); z-index:1; }
.tl-mark.pass { background:var(--radiant); } .tl-mark.fail { background:var(--dire); height:17px; top:9px; }
.tl-mark.miss { background:var(--ghost); } .tl-mark.soft { background:var(--amber); }
.tl-mark.loot { background:var(--gold); } .tl-mark.flag { background:var(--ink); }
.tl-times { position:absolute; left:0; right:0; top:33px; display:flex; justify-content:space-between;
  font-size:9px; color:var(--muted); pointer-events:none; letter-spacing:.04em; }
.deck .stamp { min-width:250px; text-align:right; font-size:11px; color:var(--muted); }

/* caster bar */
.caster { display:flex; gap:12px; align-items:baseline; padding:10px 20px 12px; background:oklch(0.15 0.015 75); }
.caster .tag { font-size:10px; color:var(--gold); white-space:nowrap; }
#casterLine { font-size:14.5px; font-weight:600; line-height:1.5; }

/* ---------- detail tabs (audit layer, unchanged honesty) ---------- */
.tabs { position:sticky; top:0; z-index:20; display:flex; gap:6px; padding:14px 18px 0;
  background:var(--arena-deep); overflow-x:auto; scrollbar-width:none; }
.tabs::-webkit-scrollbar { display:none; }
.tab { flex:0 0 auto; font:inherit; border:1px solid var(--line); border-bottom:none; background:transparent;
  color:var(--muted); padding:8px 15px; cursor:pointer; font-size:12px; letter-spacing:.05em; }
.tab:hover { color:var(--ink); }
.tab.active { color:var(--ink); background:var(--panel); font-weight:800; }
.view { display:none; padding:16px 18px 28px; } .view.active { display:block; }
.grid { display:grid; grid-template-columns:repeat(12,1fr); gap:14px; }
.card { background:var(--panel); border:1px solid var(--line); }
.card-pad { padding:15px; }
.span-4{grid-column:span 4} .span-8{grid-column:span 8} .span-12{grid-column:span 12}
.section-title { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:10px; }
.section-title h2 { margin:0; font-size:13px; letter-spacing:.08em; text-transform:uppercase; }
.badge { font-size:10px; color:var(--muted); border:1px solid var(--line); padding:3px 8px; }
.list { display:grid; gap:8px; }
.item { border:1px solid var(--line); background:oklch(0.18 0.018 78); padding:10px 12px; }
.item-head { display:flex; gap:10px; justify-content:space-between; align-items:flex-start; }
.item-title { font-weight:700; font-size:13px; }
.item-meta { font-size:10.5px; color:var(--muted); margin-top:4px; }
.tiny { font-size:11px; color:var(--muted); }
.status { font-size:9px; font-weight:900; letter-spacing:.1em; padding:3px 7px; border:1px solid currentColor; white-space:nowrap; }
.PASS,.SUPPORTED,.SOLVED,.ACTIVE{color:var(--radiant)} .FAIL,.REFUTED,.FAILED{color:var(--dire)}
.INCONCLUSIVE,.OPEN,.BLOCKED,.EXHAUSTED,.BUDGET_EXHAUSTED,.WAITING,.CONTESTED{color:var(--amber)}
.INVALID,.INVALIDATED,.ERROR{color:var(--ghost)}
table { width:100%; border-collapse:collapse; font-size:11.5px; }
th,td { text-align:left; padding:8px 9px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:700; position:sticky; top:0; background:var(--panel); }
.table-wrap { overflow:auto; max-height:560px; }
.goal-tree{display:grid;gap:8px} .goal-node{border-left:3px solid var(--line);padding:8px 11px;background:oklch(0.18 0.018 78)}
.goal-node.pass{border-color:var(--radiant)} .goal-node.fail{border-color:var(--dire)} .goal-node.open{border-color:var(--amber)}
.indent-1{margin-left:22px} .indent-2{margin-left:44px} .indent-3{margin-left:66px}
.event-row{display:grid;grid-template-columns:52px 165px 110px 1fr;gap:10px;padding:8px 0;border-bottom:1px solid var(--line)}
.event-data{white-space:pre-wrap;word-break:break-word;color:var(--muted)}
.empty{padding:22px;text-align:center;color:var(--muted);border:1px dashed var(--line)}
.footer{color:var(--muted);font-size:10.5px;padding:8px 18px 20px}

/* evidence: inline metrics + artifact links */
.ev-metrics { display:flex; flex-wrap:wrap; gap:5px 8px; margin-top:7px; }
.ev-metrics .m { font-family:ui-monospace,Menlo,Consolas,monospace; font-size:10.5px; color:var(--ink);
  background:oklch(0.15 0.012 75); border:1px solid var(--line); padding:2px 7px; }
.ev-art { margin-top:6px; font-size:10.5px; color:var(--muted); }
.ev-art a { color:var(--gold); text-decoration:none; border-bottom:1px dotted var(--gold); }
.ev-art a:hover { filter:brightness(1.15); }

/* event stream: collapsible rows + filters */
.ev-filter { display:flex; gap:10px; margin-bottom:10px; flex-wrap:wrap; }
.ev-filter select,.ev-filter input { font:inherit; font-size:12px; background:oklch(0.18 0.018 78);
  color:var(--ink); border:1px solid var(--line); padding:6px 9px; }
.ev-filter input { flex:1; min-width:180px; }
.ev-details { border-bottom:1px solid var(--line); }
.ev-details summary { display:grid; grid-template-columns:48px 200px 110px 1fr; gap:10px; padding:7px 6px;
  cursor:pointer; list-style:none; align-items:baseline; }
.ev-details summary::-webkit-details-marker { display:none; }
.ev-details summary:hover,.ev-details[open] summary { background:oklch(0.18 0.018 78); }
.ev-type { font-weight:800; font-size:11px; }
.ev-type.pass{color:var(--radiant)} .ev-type.fail{color:var(--dire)} .ev-type.loot{color:var(--gold)}
.ev-type.miss{color:var(--ghost)} .ev-type.soft{color:var(--amber)} .ev-type.info{color:var(--ink)}
.ev-sum { color:var(--muted); font-size:11px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ev-json { white-space:pre-wrap; word-break:break-word; color:var(--muted); font-size:10.5px;
  padding:8px 12px 12px 64px; margin:0; }

/* conclusion one-liners */
.uc-conc { color:var(--gold); font-weight:700; font-size:12.5px; line-height:1.5; margin-bottom:4px; }
.q-row .q-sub.q-conc { color:oklch(0.78 0.06 90); }

/* ---------- final report (conclusion-first, printable) ---------- */
.rpt { display:grid; gap:14px; max-width:980px; margin:0 auto; }
.rpt-topic { font-size:13px; color:var(--muted); margin-top:6px; line-height:1.6; }
.rpt-take { margin:0 0 14px; padding-left:20px; display:grid; gap:7px; font-size:13px; line-height:1.55; }
.rpt-take li::marker { content:'💰 '; }
.rpt-claims { display:grid; gap:6px; }
.rpt-claim { display:flex; gap:9px; align-items:baseline; border:1px solid var(--line);
  background:oklch(0.18 0.018 78); padding:9px 12px; }
.rpt-claim .rpt-conc { color:var(--muted); font-size:11.5px; line-height:1.5; }
.rpt-claim .st { margin-left:auto; flex:0 0 auto; }
.rpt-cblock { border:1px solid var(--line); background:oklch(0.18 0.018 78); padding:12px 14px; margin-bottom:10px; }
.rpt-chead { display:flex; gap:9px; align-items:baseline; font-size:13.5px; }
.rpt-chead .status { margin-left:auto; }
.rpt-stmt { color:var(--muted); font-size:11.5px; margin:5px 0 9px; line-height:1.55; }
.rpt-conc-line { color:var(--gold); font-weight:700; font-size:12.5px; line-height:1.5; margin:2px 0 8px; }
.rpt-ev { border-top:1px solid oklch(0.24 0.02 80); padding:7px 0; display:flex; gap:10px;
  align-items:baseline; flex-wrap:wrap; }
.rpt-ev .ev-metrics,.rpt-ev .ev-art { margin-top:0; }
.rpt-answer { font-size:15px; line-height:1.65; font-weight:600; margin-top:12px; padding:11px 14px;
  border-left:3px solid var(--gold); background:oklch(0.19 0.02 80); }
.rpt-do { counter-reset:step; display:grid; gap:8px; }
.rpt-step { position:relative; border:1px solid var(--line); border-left:3px solid var(--radiant);
  background:oklch(0.18 0.018 78); padding:10px 13px 10px 42px; font-size:13px; line-height:1.55; }
.rpt-step::before { counter-increment:step; content:counter(step); position:absolute; left:14px; top:10px;
  font-weight:900; color:var(--radiant); }
.rpt-dont .rpt-step { border-left-color:var(--dire); padding-left:38px; }
.rpt-dont .rpt-step::before { content:'✕'; color:var(--dire); }
.rpt-fold > summary { cursor:pointer; list-style:none; }
.rpt-fold > summary::-webkit-details-marker { display:none; }
.rpt-fold > summary::after { content:'＋'; color:var(--muted); font-weight:900; }
.rpt-fold[open] > summary::after { content:'－'; }
.rpt-fold[open] > summary { margin-bottom:10px; }

/* ---------- end-game scoreboard ---------- */
.endboard { position:absolute; inset:0; z-index:8; display:none; align-items:center; justify-content:center;
  background:oklch(0.1 0.012 70/.8); backdrop-filter:blur(7px); }
.endboard.on { display:flex; animation:ebfade .35s ease-out; }
@keyframes ebfade { from { opacity:0 } }
.eb-panel { width:min(620px,92%); max-height:94%; overflow-y:auto; padding:24px 28px 20px;
  background:linear-gradient(180deg, oklch(0.2 0.02 80), oklch(0.15 0.015 75));
  border:1px solid var(--line); border-top:4px solid var(--gold); box-shadow:0 30px 90px oklch(0 0 0/.65);
  animation:ebup .5s cubic-bezier(.16,1,.3,1); }
@keyframes ebup { from { opacity:0; transform:translateY(26px) scale(.97) } }
.eb-kicker { font-size:10px; letter-spacing:.3em; color:var(--muted); font-weight:800; text-transform:uppercase; }
.eb-title { font-size:clamp(30px,4.6vw,46px); font-weight:900; font-style:italic; letter-spacing:.04em;
  line-height:1.05; margin:8px 0 2px; }
.eb-title.radiant { color:var(--radiant); } .eb-title.dire { color:var(--dire); } .eb-title.gold { color:var(--gold); }
.eb-sub { font-size:11.5px; color:var(--muted); margin-bottom:14px; overflow:hidden;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
.eb-score { display:flex; align-items:baseline; gap:12px; margin:6px 0 18px; }
.eb-score .n { font-size:40px; font-weight:900; font-variant-numeric:tabular-nums; line-height:1; }
.eb-score .n.radiant{color:var(--radiant)} .eb-score .n.dire{color:var(--dire)}
.eb-score .lbl { font-size:9px; color:var(--muted); letter-spacing:.14em; text-transform:uppercase; font-weight:800; }
.eb-score .vs2 { color:var(--muted); font-weight:900; font-size:13px; }
.eb-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:8px; margin-bottom:16px; }
.eb-stat { border:1px solid var(--line); background:oklch(0.17 0.015 78); padding:8px 11px; }
.eb-stat .k { font-size:9px; letter-spacing:.13em; color:var(--muted); text-transform:uppercase; font-weight:800; }
.eb-stat .v { font-size:16px; font-weight:800; margin-top:3px; font-variant-numeric:tabular-nums; }
.eb-claims { display:grid; gap:5px; margin-bottom:18px; }
.eb-claim { display:flex; gap:8px; align-items:baseline; font-size:11.5px; }
.eb-claim .eb-cn { color:var(--gold); font-weight:900; min-width:14px; }
.eb-claim .st { margin-left:auto; }
.eb-actions { display:flex; gap:10px; flex-wrap:wrap; }
.eb-actions button { font:inherit; font-weight:900; letter-spacing:.08em; padding:9px 16px; cursor:pointer;
  border:1px solid var(--line); background:var(--panel); color:var(--ink); }
.eb-actions button.primary { background:var(--gold); color:oklch(0.16 0.02 80); border-color:var(--gold); }
.eb-actions button:hover { filter:brightness(1.12); }
.endboard-btn { position:absolute; right:14px; bottom:14px; z-index:7; display:none; font:inherit; font-weight:900;
  font-size:11px; letter-spacing:.12em; padding:8px 14px; cursor:pointer; border:1px solid var(--gold);
  background:oklch(0.14 0.014 75/.92); color:var(--gold); }
.endboard-btn.on { display:block; animation:ebfade .3s; }
.endboard-btn:hover { background:var(--gold); color:oklch(0.16 0.02 80); }

@media (prefers-reduced-motion: reduce) { .shake,.announcer span,.dmg,.feed-row,.hero-bob,.bar-fx,
  .endboard.on,.eb-panel,.unit-card.on,.edge.hot{animation:none} .livechip .dot{animation:none} }
@media (max-width: 960px) {
  .stage{grid-template-columns:1fr}
  #arena{min-height:320px}
  .rightcol{border-top:2px solid var(--line); height:auto}
  #feed{min-height:130px; max-height:300px} #quest{max-height:340px}
  .topbar{flex-wrap:wrap}
  .scorebox{padding:8px 14px; gap:10px; flex:1}
  .score{font-size:30px}
  .livechip{padding:0 12px; border-left:1px solid var(--line)}
  .matchinfo{order:5; flex:1 1 100%; border-left:none; border-top:1px solid var(--line); padding:8px 14px}
  .matchinfo h1{white-space:normal; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical}
  .bars{order:6; flex:1 1 100%; width:auto; border-left:none; border-top:1px solid var(--line); padding:8px 14px}
  .deck{gap:8px; padding:8px 10px; flex-wrap:wrap}
  .timeline{flex:1 1 100%; order:5}
  .deck .stamp{display:none}
  .span-4,.span-8{grid-column:span 12}
  .ev-details summary{grid-template-columns:44px 1fr}
  .ev-sum{grid-column:2} .ev-json{padding-left:12px}
  .eb-panel{padding:18px 16px}
  .caster{padding:8px 14px 10px} #casterLine{font-size:13px}
}
@media print {
  .topbar,.stage,.deck,.caster,.tabs,.footer { display:none !important; }
  .view { display:none !important; padding:0; }
  #view-report { display:block !important; }
  body { background:#fff; color:#16130e; }
  .card,.rpt-claim,.rpt-cblock { background:#fff; border-color:#d8d2c4; }
  .eb-stat { background:#f5f2ea; border-color:#d8d2c4; }
  .eb-stat .v { color:#16130e; }
  .rpt-topic,.rpt-claim .rpt-conc,.rpt-stmt,.tiny,.item-meta,.badge,.rpt-take,.empty { color:#55503f; }
  .rpt-answer { background:#f5f2ea; color:#16130e; }
  .rpt-step { background:#fff; }
  .rpt-conc-line,.uc-conc { color:#8a6a12; }
  .eb-title.radiant { color:#1c7a46; } .eb-title.dire { color:#b03a2a; } .eb-title.gold { color:#8a6a12; }
  .ev-metrics .m { background:#f5f2ea; color:#16130e; border-color:#d8d2c4; }
  .ev-art a { color:#8a6a12; }
}
</style>
</head>
<body>
<header class="topbar">
  <div class="scorebox">
    <div><div class="score radiant" id="scoreV">0</div><div class="score-label caps" data-i18n="verified">已验证</div></div>
    <div class="vs">VS</div>
    <div><div class="score dire" id="scoreR">0</div><div class="score-label caps" data-i18n="refuted">已证伪</div></div>
  </div>
  <div class="matchinfo">
    <h1 id="topic"></h1>
    <div class="sub">
      <span class="caps" style="color:var(--gold)">Sisyfus Research Observatory · Arena</span>
      <span id="matchMeta" class="mono"></span>
      <span id="lootMeta"></span>
    </div>
  </div>
  <div class="bars">
    <div class="bar hp"><i id="hpFill"></i><b id="hpText"></b></div>
    <div class="bar mana"><i id="manaFill"></i><b id="manaText"></b></div>
  </div>
  <div class="livechip" id="liveChip"><span class="dot"></span><span id="liveText">LIVE</span></div>
  <button class="lang-btn" id="langBtn" title="切换语言 / switch language">EN</button>
</header>

<div class="stage">
  <div class="arena-wrap" id="arenaWrap">
    <svg id="arena" viewBox="0 0 1000 560" preserveAspectRatio="xMidYMid meet">
      <g id="edges"></g>
      <g id="bosses"></g>
      <g id="hero" style="transition:transform .8s cubic-bezier(.16,1,.3,1)">
       <g class="hero-bob">
        <circle r="26" cy="6" fill="oklch(0.85 0.05 90)" opacity="0.14"/>
        <circle class="stone" r="13" cx="15" cy="-2" fill="oklch(0.8 0.06 85)" stroke="oklch(0.95 0.04 90)" stroke-width="1.5"/>
        <g stroke="oklch(0.93 0.02 90)" stroke-width="3.4" stroke-linecap="round" fill="none">
          <circle cx="-6" cy="-14" r="5" fill="oklch(0.93 0.02 90)" stroke="none"/>
          <path d="M-6 -9 L-3 4 L-9 16 M-4 3 L6 13 M-5 -6 L8 -8 M-5 -5 L4 0"/>
        </g>
       </g>
      </g>
    </svg>
    <div class="fx-layer" id="fxLayer"></div>
    <div class="announcer" id="announcer"></div>
    <div class="combo" id="combo"></div>
    <div class="tip" id="tip"></div>
    <div class="unit-card" id="unitCard"></div>
    <div class="endboard" id="endboard"></div>
    <button class="endboard-btn" id="endboardBtn" type="button"></button>
  </div>
  <aside class="rightcol">
    <div class="col-h caps"><span data-i18n="killfeed">战况播报</span><span id="feedCount"></span></div>
    <div id="feed"></div>
    <div class="col-h caps"><span data-i18n="claims_panel">任务面板</span><span id="questCount"></span></div>
    <div id="quest"></div>
    <div class="col-h caps" id="respawnSec"><span data-i18n="respawn">待命区</span><span id="nextWake" class="mono"></span></div>
    <div id="waitingList" style="max-height:110px;overflow-y:auto"></div>
  </aside>
</div>

<div class="deck">
  <button id="playBtn" title="播放整场">▶</button>
  <div class="timeline" id="timelineBox">
    <div class="tl-track"></div><div class="tl-fill" id="tlFill"></div>
    <div id="tlMarks"></div><div class="tl-cursor" id="tlCursor"></div>
    <div class="tl-times mono"><span id="tlStart"></span><span id="tlEnd"></span></div>
    <input type="range" id="replaySlider" min="0" max="0" value="0" step="1" aria-label="replay timeline"/>
  </div>
  <select id="speedSel"><option value="0.5">0.5×</option><option value="1">1×</option><option value="2" selected>2×</option><option value="4">4×</option></select>
  <button id="liveBtn" data-i18n="live_btn">直播</button>
  <div class="stamp mono" id="frameLabel"></div>
</div>
<div class="caster"><span class="tag caps" data-i18n="caster">解说席</span><div id="casterLine"></div></div>

<nav class="tabs">
  <button class="tab active" data-view="none" data-i18n="tab_arena">观战</button>
  <button class="tab" data-view="report" data-i18n="tab_report">报告</button>
  <button class="tab" data-view="goals" data-i18n="tab_goals">目标图</button>
  <button class="tab" data-view="execution" data-i18n="tab_execution">执行图</button>
  <button class="tab" data-view="audit" data-i18n="tab_audit">审计</button>
  <button class="tab" data-view="events" data-i18n="tab_events">事件流</button>
</nav>
<section id="view-report" class="view"><div class="rpt" id="reportBody"></div></section>
<section id="view-goals" class="view"><div class="grid"><div class="card span-8 card-pad"><div class="section-title"><h2 data-i18n="sec_goal">目标图</h2><span class="badge" id="goalRoot"></span></div><div class="goal-tree" id="goalTree"></div></div><div class="card span-4 card-pad"><div class="section-title"><h2 data-i18n="sec_cov">裁判覆盖</h2></div><div id="verifierCoverage"></div></div></div></section>
<section id="view-execution" class="view"><div class="grid"><div class="card span-12 card-pad"><div class="section-title"><h2 data-i18n="sec_dag">状态图与实验</h2><span class="badge" id="currentState"></span></div><div class="list" id="executionList"></div></div></div></section>
<section id="view-audit" class="view"><div class="grid"><div class="card span-12 card-pad"><div class="section-title"><h2 data-i18n="sec_contracts">验证合约</h2></div><div class="table-wrap"><table><thead><tr><th>ID</th><th>Claim</th><th>Version</th><th>Repetition</th><th>Rules</th></tr></thead><tbody id="contractRows"></tbody></table></div></div><div class="card span-12 card-pad"><div class="section-title"><h2 data-i18n="sec_attempts">尝试与判定</h2></div><div class="table-wrap"><table><thead><tr><th>Attempt</th><th>Experiment</th><th>Context</th><th>Status</th><th>Verdict</th><th>Reason</th><th>State</th></tr></thead><tbody id="attemptRows"></tbody></table></div></div><div class="card span-12 card-pad"><div class="section-title"><h2 data-i18n="sec_evidence">证据</h2></div><div class="list" id="evidenceList"></div></div><div class="card span-12 card-pad"><div class="section-title"><h2 data-i18n="sec_lessons">战利品</h2></div><div class="list" id="lessonList"></div></div></div></section>
<section id="view-events" class="view"><div class="card card-pad"><div class="section-title"><h2 data-i18n="sec_events">只增事件流</h2><span class="badge" id="eventHead"></span></div><div class="ev-filter"><select id="evTypeFilter"></select><input id="evTextFilter" type="search" data-i18n-ph="ev_search" placeholder="过滤事件 JSON…"/></div><div id="eventList"></div></div></section>
<div class="footer" id="footerLine">一切画面均由 task.json + events.jsonl 的确定性投影生成;回放的每一帧都是事件前缀的重新归约,可被 sisyfus research replay 哈希验证。MISS 不构成伤害:INVALID/ERROR 是测量失败,不是命题反证。</div>
<div class="footer" id="legendLine" style="padding-top:0"></div>

<script id="sisyfus-data" type="application/json">__PAYLOAD__</script>
<script>
const DATA = JSON.parse(document.getElementById('sisyfus-data').textContent);
let S = DATA.snapshot, E = DATA.events || [], FRAMES = DATA.frames || [];
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const status = s => `<span class="status ${esc(s)}">${esc(s || 'MISSING')}</span>`;

/* ================= i18n ================= */
const LOCALES = {
  zh: {
    verified:'已验证', refuted:'已证伪', killfeed:'战况播报', claims_panel:'任务面板', respawn:'待命区',
    live_btn:'直播', caster:'解说席', tab_arena:'观战', tab_goals:'目标图', tab_execution:'执行图', tab_audit:'审计', tab_events:'事件流',
    sec_goal:'目标图', sec_cov:'裁判覆盖', sec_dag:'状态图与实验', sec_contracts:'验证合约', sec_attempts:'尝试与判定',
    sec_evidence:'证据', sec_lessons:'战利品', sec_events:'只增事件流',
    footer:'一切画面均由 task.json + events.jsonl 的确定性投影生成;回放的每一帧都是事件前缀的重新归约,可被 sisyfus research replay 哈希验证。MISS 不构成伤害:INVALID/ERROR 是测量失败,不是命题反证。',
    legend_line:'👑 命题被验证攻克(SUPPORTED) · ☠️ 命题被证伪(REFUTED)——也是花预算买到的知识 · ❌ INVALID/ERROR 是测量失败,不构成命题反证 · 💰 lesson 战利品,双实验门槛后晋升全局知识库 · ❤ attempts/cost 预算即血蓝条,打空即终局 · 🧍 推石头的英雄(agent)站在哪里,哪里就是当前进攻的命题',
    live:'直播', replay:'回放', attempts:'尝试', cost:'成本',
    events_n: n => `${n} 事件`, claims_n: n => `${n} 命题`, combo: n => `连击 ×${n}`,
    awaiting_evidence:'等证据', no_waiting:'无待命实验',
    wait_not_before: ts => `不早于 ${ts}`, wait_until: c => `等待 ${c} 出证据`,
    required:'必需', optional:'可选', critical:'关键',
    evidence_n: n => `证据 ${n}`, provisional_n: n => `临时通过 ${n}`, cited_n: n => `被引用 ×${n}`,
    uc_status:'状态', uc_contracts:'裁判合约', uc_engagements:'交战记录',
    uc_gate: (p, c) => `需 ${p} 次通过 / ${c} 个独立环境`, tip_click:'点击查看单位卡',
    uc_more: n => `+${n} 更多…`,
    cov_full:'必需命题全部有裁判合约', cov_missing:'以下必需命题缺少裁判', empty_evidence:'尚无证据', empty_lessons:'尚未拾取任何战利品', root:'根节点',
    ann_supported: c => `命题攻克 · ${c}`, ann_refuted: c => `命题被证伪 · ${c}`, ann_first:'首个证据!', ann_cascade:'连锁崩塌!',
    ann_loot:'战利品入库!', ann_victory:'大获全胜', ann_budget:'弹尽粮绝', ann_goal_refuted:'目标被证伪',
    n_run_created: t => ['比赛开始 — 目标锁定', `开赛!本场目标:${t}`],
    n_spec_locked: () => ['规则预注册并锁定', '规则锁定:所有判定阈值已预注册,赛后不可改。'],
    n_contract: id => [`裁判就位 ${id}`, `裁判合约 ${id} 上岗。`],
    n_proposed: (title, claim) => [`战术提出:${title}`, `选手提出战术「${title}」,目标命题 ${claim}。`],
    n_admitted: (e, claim) => [`进场:${e}`, `裁判放行,${e} 进场,兵锋直指 ${claim}!`],
    n_backlogged: (e, r) => [`战术被拒:${e}(${r})`, `裁判拒绝 ${e} 进场:${r || '不合规'}。`],
    n_pruned: e => [`战术放弃:${e}`, `${e} 被主动放弃。`],
    n_reserved: (e, claim) => [`开打:${e}`, `${e} 对 ${claim} 发起进攻,预算已扣押。`],
    n_started: e => [`交战中:${e}`, '交战进行中……'],
    n_observation: () => ['战场数据回传', '测量数据回传,等待裁判裁决……'],
    n_wait_fired: e => [`集结号:${e} 归队`, `等待条件满足,${e} 重新进场。`],
    n_wait_expired: (e, p) => [`等待超时:${e}`, `${e} 等待超时(${p})。`],
    n_pass_promoted: c => [`命题攻克!${c}`, `裁判判定 PASS——命题 ${c} 正式攻克!`],
    n_pass_provisional: (e, c) => [`有效一击:${c}(待重复验证)`, `PASS!${e} 对 ${c} 打出有效一击,重复门槛未满,继续输出。`],
    n_fail: (c, rb, r) => [`反杀!${c} 被证伪${rb ? ` · 连锁失效×${rb}` : ''}`, `FAIL!${c} 反杀成功——命题被证伪${rb ? `,${rb} 个下游命题连锁失效` : ''}!(${r || ''})`],
    n_invalid: (e, r) => [`MISS:${e} 测量无效`, `裁判判 INVALID——这一击无效,不构成伤害。(${r || ''})`],
    n_error: e => [`装备故障:${e}`, '基础设施故障,判 ERROR,不计入战果。'],
    n_inconclusive: c => [`战况不明:${c}`, `INCONCLUSIVE——${c} 战况不明,需要更锋利的实验。`],
    n_lesson_add: id => [`拾取战利品:${id}`, `战利品掉落:lesson「${id}」候选入包。`],
    n_lesson_evidence: id => [`战利品附魔:${id}`, `lesson ${id} 追加证据。`],
    n_lesson_promoted: id => [`战利品入库(全局):${id}`, `lesson「${id}」通过双实验门槛,晋升全局知识库——下一场比赛开局自带!`],
    n_lesson_revoked: id => [`战利品作废:${id}`, `lesson ${id} 被反例击碎,撤销。`],
    n_paused: () => ['暂停', '比赛暂停。'], n_resumed: () => ['继续', '比赛继续!'],
    n_run_failed: r => ['比赛异常终止', `比赛异常终止:${r || ''}`],
    n_final_solved: () => ['大获全胜 — 全部必需命题攻克', '比赛结束——大获全胜!Goal Graph 全线通过!'],
    n_final_refuted: () => ['目标被证伪 — 问题得到否定答案', '比赛结束:目标被证伪——这个问题的答案是否定的,而这个确定性正是这场比赛买到的东西。'],
    n_final_budget: () => ['弹尽粮绝 — 预算耗尽', '比赛结束:预算耗尽。地图上的每一条红色岔路都是花钱买来的知识。'],
    n_final_other: st => [`终局:${st}`, `比赛结束:${st}。`],
    n_report: () => ['转播画面更新', ''],
    ended:'已终局', eb_kicker:'赛后结算', eb_view_map:'查看地图', eb_replay:'回放整场', eb_show:'赛果',
    eb_attempts:'尝试消耗', eb_cost:'成本消耗', eb_duration:'比赛时长', eb_lessons:'战利品', eb_events:'总事件',
    obj_label:'目标', epi_label:'知识',
    meta_tip:'obj = 目标图客观完成度;epi = 认知覆盖度(有证据支撑的命题比例)',
    rs_ACTIVE:'进行中', rs_PAUSED:'已暂停', rs_SOLVED:'大获全胜', rs_BUDGET_EXHAUSTED:'预算耗尽',
    rs_FAILED:'异常终止', rs_BLOCKED:'受阻', rs_CONTESTED:'争议中',
    ev_all_types:'全部类型', ev_search:'过滤事件 JSON…', artifacts_label:'产物',
    play_all:'播放整场', feed_jump:'点击跳转到该事件',
    eb_dur: (h, m, s) => h ? `${h} 小时 ${m} 分` : `${m} 分 ${s} 秒`,
    rsn_pass_rule_matched:'观测满足预注册的 PASS 规则与全部护栏。',
    rsn_fail_rule_matched:'观测满足预注册的 FAIL 规则。',
    rsn_no_decisive_rule_matched:'实验有效,但 PASS 与 FAIL 规则均未决出。',
    rsn_invalid_rule_matched:'实验命中预注册的无效条件。',
    rsn_guardrail_failed:'实验有效,但触发硬性护栏失败。',
    rsn_precondition_failed:'实验不满足预注册的前置条件。',
    rsn_contradictory_contract:'PASS 与 FAIL 规则同时命中——该观测下验证合约自相矛盾。',
    rsn_execution_timeout:'实验执行超时,不允许对命题做任何推断。',
    rsn_execution_error:'实验执行出错,判为基础设施/执行故障。',
    rsn_command_nonzero_exit:'命令以非零码退出,判为基础设施/执行故障。',
    rsn_required_artifact_missing:'要求的产物文件缺失。',
    rsn_manual_verdict:'人工判定。',
    rsn_manual_verdict_missing:'人工合约未收到有效的 manual_verdict。',
    tab_report:'报告', sec_takeaways:'结论速览', sec_claim_evidence:'命题与证据', sec_loot_final:'战利品结论',
    rpt_no_lessons:'本场没有沉淀可执行结论。', rpt_verdicts:'判定统计', rpt_required_only:'仅必需命题',
    rpt_answer:'本场答案', rpt_do:'正确做法', rpt_dont:'不要这样做', rpt_details:'命题与证据明细',
  },
  en: {
    verified:'verified', refuted:'refuted', killfeed:'KILL FEED', claims_panel:'CLAIMS', respawn:'RESPAWN',
    live_btn:'LIVE', caster:'CASTER', tab_arena:'Arena', tab_goals:'Goal Graph', tab_execution:'Execution', tab_audit:'Audit', tab_events:'Events',
    sec_goal:'Goal Graph', sec_cov:'Verifier Coverage', sec_dag:'State DAG & Experiments', sec_contracts:'Verification Contracts', sec_attempts:'Attempts & Verdicts',
    sec_evidence:'Evidence', sec_lessons:'Lessons', sec_events:'Append-only Event Stream',
    footer:'Everything on screen is a deterministic projection of task.json + events.jsonl; every replay frame is a re-reduction of the event prefix, verifiable via sisyfus research replay. A MISS deals no damage: INVALID/ERROR are measurement failures, not refutations.',
    legend_line:'👑 claim verified (SUPPORTED) · ☠️ claim refuted (REFUTED) — knowledge bought with budget · ❌ INVALID/ERROR are measurement failures, not refutations · 💰 lessons join the global library after the two-experiment gate · ❤ attempts/cost budgets are your HP/mana — empty bars end the match · 🧍 the boulder-pushing hero (agent) stands at the claim under assault',
    live:'LIVE', replay:'REPLAY', attempts:'ATTEMPTS', cost:'COST',
    events_n: n => `${n} events`, claims_n: n => `${n} claims`, combo: n => `COMBO ×${n}`,
    awaiting_evidence:'awaiting evidence', no_waiting:'no waiting experiments',
    wait_not_before: ts => `not before ${ts}`, wait_until: c => `until evidence on ${c}`,
    required:'required', optional:'optional', critical:'critical',
    evidence_n: n => `evidence ${n}`, provisional_n: n => `provisional ${n}`, cited_n: n => `cited ×${n}`,
    uc_status:'STATUS', uc_contracts:'VERIFIER CONTRACTS', uc_engagements:'ENGAGEMENTS',
    uc_gate: (p, c) => `needs ${p} passes / ${c} independent contexts`, tip_click:'click for unit card',
    uc_more: n => `+${n} more…`,
    cov_full:'Full required-claim verifier coverage', cov_missing:'Required claims without a verifier', empty_evidence:'No evidence recorded.', empty_lessons:'No lessons looted yet.', root:'root',
    ann_supported: c => `CLAIM TAKEN · ${c}`, ann_refuted: c => `REFUTED · ${c}`, ann_first:'FIRST EVIDENCE!', ann_cascade:'CASCADE!',
    ann_loot:'LOOT SECURED!', ann_victory:'VICTORY', ann_budget:'OUT OF BUDGET', ann_goal_refuted:'GOAL REFUTED',
    n_run_created: t => ['Match start — objective locked', `Match on! Objective: ${t}`],
    n_spec_locked: () => ['Rules preregistered and locked', 'Rules locked: every verdict threshold is preregistered and immutable.'],
    n_contract: id => [`Referee ready: ${id}`, `Verification contract ${id} is on duty.`],
    n_proposed: (title, claim) => [`Tactic proposed: ${title}`, `The player proposes "${title}" targeting claim ${claim}.`],
    n_admitted: (e, claim) => [`Entering: ${e}`, `Admission granted — ${e} enters the field, heading for ${claim}!`],
    n_backlogged: (e, r) => [`Tactic rejected: ${e} (${r})`, `The referee rejects ${e}: ${r || 'not compliant'}.`],
    n_pruned: e => [`Tactic abandoned: ${e}`, `${e} was withdrawn.`],
    n_reserved: (e, claim) => [`Engaging: ${e}`, `${e} opens the assault on ${claim}; budget reserved.`],
    n_started: e => [`In combat: ${e}`, 'Engagement in progress…'],
    n_observation: () => ['Field telemetry received', 'Measurements are in — awaiting the referee…'],
    n_wait_fired: e => [`Rally: ${e} returns`, `Wait satisfied — ${e} re-enters the field.`],
    n_wait_expired: (e, p) => [`Wait expired: ${e}`, `${e} timed out (${p}).`],
    n_pass_promoted: c => [`CLAIM TAKEN! ${c}`, `Verdict PASS — claim ${c} officially supported!`],
    n_pass_provisional: (e, c) => [`Solid hit: ${c} (repetition pending)`, `PASS! ${e} lands a hit on ${c}; the repetition gate is not met yet — keep pushing.`],
    n_fail: (c, rb, r) => [`Counter-kill! ${c} refuted${rb ? ` · cascade ×${rb}` : ''}`, `FAIL! ${c} counter-kills — the claim is refuted${rb ? `, invalidating ${rb} downstream claims` : ''}! (${r || ''})`],
    n_invalid: (e, r) => [`MISS: ${e} invalid measurement`, `Referee calls INVALID — no damage dealt. (${r || ''})`],
    n_error: e => [`Gear failure: ${e}`, 'Infrastructure error — ruled ERROR, not counted as evidence.'],
    n_inconclusive: c => [`Unclear: ${c}`, `INCONCLUSIVE — ${c} remains unclear; a sharper experiment is needed.`],
    n_lesson_add: id => [`Loot picked up: ${id}`, `Loot drop: lesson "${id}" added as candidate.`],
    n_lesson_evidence: id => [`Loot enchanted: ${id}`, `Lesson ${id} gains new evidence.`],
    n_lesson_promoted: id => [`Loot secured (global): ${id}`, `Lesson "${id}" passes the two-experiment gate and joins the global library — the next match starts with it!`],
    n_lesson_revoked: id => [`Loot destroyed: ${id}`, `Lesson ${id} shattered by a counterexample; revoked.`],
    n_paused: () => ['Paused', 'Match paused.'], n_resumed: () => ['Resumed', 'Match resumes!'],
    n_run_failed: r => ['Match aborted', `Match aborted: ${r || ''}`],
    n_final_solved: () => ['VICTORY — all required claims taken', 'Match over — VICTORY! The Goal Graph passes end to end!'],
    n_final_refuted: () => ['GOAL REFUTED — the question answered no', 'Match over: the goal is refuted. A definitive negative answer is exactly what this match paid for.'],
    n_final_budget: () => ['OUT OF BUDGET', 'Match over: budget exhausted. Every red branch on the map is knowledge paid for in full.'],
    n_final_other: st => [`Final: ${st}`, `Match over: ${st}.`],
    n_report: () => ['Broadcast refreshed', ''],
    ended:'ENDED', eb_kicker:'Match result', eb_view_map:'View map', eb_replay:'Replay match', eb_show:'RESULT',
    eb_attempts:'Attempts used', eb_cost:'Cost spent', eb_duration:'Duration', eb_lessons:'Loot banked', eb_events:'Events',
    obj_label:'obj', epi_label:'epi',
    meta_tip:'obj = objective completion of the goal graph; epi = epistemic coverage (claims backed by evidence)',
    rs_ACTIVE:'live', rs_PAUSED:'paused', rs_SOLVED:'victory', rs_BUDGET_EXHAUSTED:'budget exhausted',
    rs_FAILED:'aborted', rs_BLOCKED:'blocked', rs_CONTESTED:'contested',
    ev_all_types:'all types', ev_search:'filter event JSON…', artifacts_label:'artifacts',
    play_all:'Play the full match', feed_jump:'Click to jump to this event',
    eb_dur: (h, m, s) => h ? `${h}h ${m}m` : `${m}m ${s}s`,
    rsn_pass_rule_matched:'The observation satisfied the preregistered PASS rule and all guardrails.',
    rsn_fail_rule_matched:'The observation satisfied the preregistered FAIL rule.',
    rsn_no_decisive_rule_matched:'The experiment was valid, but neither the PASS nor FAIL rule was decisive.',
    rsn_invalid_rule_matched:'The experiment matched a preregistered invalidity condition.',
    rsn_guardrail_failed:'The experiment was valid, but a hard guardrail failed.',
    rsn_precondition_failed:'The experiment did not satisfy the preregistered preconditions.',
    rsn_contradictory_contract:'Both PASS and FAIL rules matched; the verification contract is contradictory for this observation.',
    rsn_execution_timeout:'Experiment execution timed out; no claim inference is allowed.',
    rsn_execution_error:'Execution failed with an infrastructure/execution error.',
    rsn_command_nonzero_exit:'Command exited non-zero; treated as infrastructure/execution failure.',
    rsn_required_artifact_missing:'Required artifacts were missing.',
    rsn_manual_verdict:'Manual verdict.',
    rsn_manual_verdict_missing:'Manual contract did not receive a valid manual_verdict.',
    tab_report:'Report', sec_takeaways:'Key takeaways', sec_claim_evidence:'Claims & evidence', sec_loot_final:'Loot conclusions',
    rpt_no_lessons:'No actionable lessons banked this match.', rpt_verdicts:'Verdict tally', rpt_required_only:'required claims only',
    rpt_answer:'The answer', rpt_do:'How to do it right', rpt_dont:'What not to do', rpt_details:'Claims & evidence detail',
  },
};
let lang = localStorage.getItem('sisyfus_lang') || ((navigator.language || '').toLowerCase().startsWith('zh') ? 'zh' : 'en');
let L = LOCALES[lang] || LOCALES.zh;
function t(key) { const v = L[key]; return typeof v === 'string' ? v : key; }
function runStatusLabel(st) { return L['rs_' + st] || st || ''; }
/* data-layer translations: run sidecar (i18n.json) → TaskSpec i18n block → original text */
function trPart(kind, id, field, original) {
  const sidecar = (((DATA.translations || {})[lang] || {})[kind] || {})[id];
  const spec = (((S.i18n || {})[lang] || {})[kind] || {})[id];
  return (sidecar && sidecar[field]) || (spec && spec[field]) || original;
}
function trTopic() {
  return ((DATA.translations || {})[lang] || {}).topic || ((S.i18n || {})[lang] || {}).topic || S.topic;
}
function trClaimF(c, field) { return trPart('claims', c.id, field, c[field]); }
function trExpTitle(exp) { return trPart('experiments', exp.id, 'title', exp.title || exp.id); }
function trLessonF(l, field) { return trPart('lessons', l.id, field, l[field]); }
function trClaimConclusion(c) { return trPart('claims', c.id, 'conclusion', ''); }
const RSN_DYNAMIC = new Set(['execution_error', 'command_nonzero_exit', 'required_artifact_missing', 'manual_verdict']);
function reasonSummary(x) {
  const rc = (x && x.reason_code) || '';
  return (rc && L['rsn_' + rc]) || (x && x.summary) || '';
}
function reasonExtra(x) {
  // dynamic templates embed specifics (exit code, missing artifacts, error text) that only
  // exist in the persisted English summary — keep it as a secondary line under the localized one.
  return RSN_DYNAMIC.has((x && x.reason_code) || '') && x && x.summary ? x.summary : '';
}

function applyStaticI18n() {
  document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-ph]').forEach(el => { el.placeholder = t(el.dataset.i18nPh); });
  $('footerLine').textContent = t('footer');
  $('legendLine').textContent = t('legend_line');
  $('langBtn').textContent = lang === 'zh' ? 'EN' : '中文';
  $('topic').textContent = trTopic();
  $('topic').title = trTopic();
  $('matchMeta').title = t('meta_tip');
  $('playBtn').title = `${t('play_all')} (Space)`;
  $('endboardBtn').textContent = `🏁 ${t('eb_show')}`;
}
function setLang(next) {
  lang = next; L = LOCALES[lang] || LOCALES.zh;
  try { localStorage.setItem('sisyfus_lang', lang); } catch (_) {}
  applyStaticI18n(); renderDetailTabs(); renderWaiting();
  showIndex(Number($('replaySlider').value), { feedRebuild: true });
}

/* ================= derived match data ================= */
let CLAIM_POS = {}, TARGET_BY_SEQ = [], TOUCHED_BY_SEQ = [], COMBO_BY_SEQ = [], MARKERS = [], FIRST_PASS_SEQ = 0;

function shortClaim(id) { return id.length > 22 ? id.slice(0, 20) + '…' : id; }
function claimLabel(c) { return trClaimF(c, 'label') || (c.tags && c.tags[0]) || shortClaim(c.id); }
const CLAIM_INDEX = {};
Object.keys((DATA.snapshot || {}).claims || {}).forEach((id, i) => { CLAIM_INDEX[id] = i + 1; });
let SELECTED = null;
function expIdOf(d) {
  return d.experiment_id || (d.experiment && d.experiment.id) || (d.attempt && d.attempt.experiment_id)
    || (d.attempt_id && S.attempts[d.attempt_id] && S.attempts[d.attempt_id].experiment_id) || '';
}

function layoutClaims() {
  const claims = Object.values(S.claims);
  const depth = {};
  const depthOf = id => {
    if (depth[id] !== undefined) return depth[id];
    const deps = (S.claims[id] && S.claims[id].depends_on) || [];
    depth[id] = deps.length ? 1 + Math.max(...deps.map(depthOf)) : 0;
    return depth[id];
  };
  claims.forEach(c => depthOf(c.id));
  const cols = {};
  claims.forEach(c => (cols[depth[c.id]] = cols[depth[c.id]] || []).push(c));
  const nCols = Object.keys(cols).length;
  CLAIM_POS = {};
  Object.entries(cols).forEach(([d, list]) => {
    list.sort((a, b) => a.id.localeCompare(b.id));
    const baseX = nCols === 1 ? 500 : 130 + (740 * d) / Math.max(1, nCols - 1);
    list.forEach((c, i) => {
      const x = baseX + (list.length > 1 ? (i % 2 ? 64 : -64) : 0);
      const y = 76 + ((560 - 130) * (i + 1)) / (list.length + 1);
      CLAIM_POS[c.id] = { x, y, claim: c };
    });
  });
}

function verdictClass(st) {
  return st === 'PASS' ? 'pass' : st === 'FAIL' ? 'fail'
    : (st === 'INVALID' || st === 'ERROR') ? 'miss' : 'soft';
}

function deriveTimeline() {
  TARGET_BY_SEQ = []; TOUCHED_BY_SEQ = []; COMBO_BY_SEQ = []; MARKERS = []; FIRST_PASS_SEQ = 0;
  let current = null, combo = 0;
  const touched = new Set();
  E.forEach(ev => {
    const d = ev.data || {};
    const expId = expIdOf(d);
    const exp = expId && S.experiments[expId];
    if (exp && exp.target_claim_ids && exp.target_claim_ids[0]) current = exp.target_claim_ids[0];
    TARGET_BY_SEQ[ev.seq] = current;
    if (current) touched.add(current);
    TOUCHED_BY_SEQ[ev.seq] = new Set(touched);
    if (ev.event_type === 'VERDICT_ISSUED') {
      const st = (d.verdict || {}).status;
      MARKERS.push({ seq: ev.seq, cls: verdictClass(st), label: `${expId} → ${st}` });
      if (st === 'PASS' && !FIRST_PASS_SEQ) FIRST_PASS_SEQ = ev.seq;
      if (st === 'PASS') combo += 1; else if (st === 'FAIL' || st === 'INCONCLUSIVE') combo = 0;
    } else if (ev.event_type.startsWith('LESSON_')) {
      MARKERS.push({ seq: ev.seq, cls: 'loot', label: ev.event_type });
    } else if (ev.event_type === 'RUN_FINALIZED') {
      MARKERS.push({ seq: ev.seq, cls: 'flag', label: (d.status || '') });
    }
    COMBO_BY_SEQ[ev.seq] = combo;
  });
}

/* narrative translation of one event (kill feed + caster), via the active locale */
function narrate(ev) {
  const d = ev.data || {}, type = ev.event_type;
  const expId = expIdOf(d);
  const exp = S.experiments[expId] || {};
  const claim = (exp.target_claim_ids || [])[0] || '';
  const v = d.verdict || {};
  const out = (cls, icon, pair) => ({ cls, icon, feed: pair[0], caster: pair[1] });
  switch (type) {
    case 'RUN_CREATED': return out('info', '📯', L.n_run_created(S.topic));
    case 'SPEC_LOCKED': return out('info', '🔒', L.n_spec_locked());
    case 'CONTRACT_ADDED': return out('info', '📜', L.n_contract((d.contract && d.contract.id) || ''));
    case 'EXPERIMENT_PROPOSED': return out('info', '🧭', L.n_proposed(trExpTitle(exp) || expId, claim));
    case 'EXPERIMENT_ADMITTED': return out('info', '⚔️', L.n_admitted(expId, claim));
    case 'EXPERIMENT_BACKLOGGED': return out('miss', '🚫', L.n_backlogged(expId, d.reason || ''));
    case 'EXPERIMENT_PRUNED': return out('miss', '✂️', L.n_pruned(expId));
    case 'ATTEMPT_RESERVED': return out('info', '🎯', L.n_reserved(expId, claim));
    case 'ATTEMPT_STARTED': return out('info', '🔥', L.n_started(expId));
    case 'OBSERVATION_RECORDED': return out('info', '🔬', L.n_observation());
    case 'WAIT_FIRED': return out('info', '⏰', L.n_wait_fired(expId));
    case 'WAIT_EXPIRED': return out('miss', '⌛', L.n_wait_expired(expId, d.on_expire || ''));
    case 'VERDICT_ISSUED': {
      const effects = d.claim_effects || [];
      const supported = effects.some(x => x.status === 'SUPPORTED');
      const rollbacks = effects.filter(x => x.status === 'INVALIDATED').length;
      if (v.status === 'PASS') return supported
        ? out('pass', '👑', L.n_pass_promoted(claim))
        : out('pass', '💥', L.n_pass_provisional(expId, claim));
      if (v.status === 'FAIL') return out('fail', '☠️', L.n_fail(claim, rollbacks, v.reason_code));
      if (v.status === 'INVALID') return out('miss', '❌', L.n_invalid(expId, v.reason_code));
      if (v.status === 'ERROR') return out('miss', '💢', L.n_error(expId));
      return out('soft', '🌫️', L.n_inconclusive(claim));
    }
    case 'LESSON_CANDIDATE_CREATED': return out('loot', '💰', L.n_lesson_add((d.lesson && d.lesson.id) || ''));
    case 'LESSON_EVIDENCE_ADDED': return out('loot', '🧾', L.n_lesson_evidence(d.lesson_id));
    case 'LESSON_PROMOTED': return out('loot', '🏆', L.n_lesson_promoted(d.lesson_id));
    case 'LESSON_REVOKED': return out('miss', '🗑️', L.n_lesson_revoked(d.lesson_id));
    case 'RUN_PAUSED': return out('info', '⏸', L.n_paused());
    case 'RUN_RESUMED': return out('info', '▶️', L.n_resumed());
    case 'RUN_FAILED': return out('fail', '🛑', L.n_run_failed(d.reason));
    case 'RUN_FINALIZED': {
      const st = d.status || '';
      if (st === 'SOLVED') return out('pass', '🏅', L.n_final_solved());
      if (st === 'REFUTED') return out('fail', '⚖️', L.n_final_refuted());
      if (st === 'BUDGET_EXHAUSTED') return out('fail', '🪫', L.n_final_budget());
      return out('soft', '🏁', L.n_final_other(st));
    }
    case 'REPORT_RENDERED': return out('info', '📺', L.n_report());
  }
  return { cls:'info', icon:'·', feed:ev.event_type, caster:'' };
}

/* ================= arena rendering ================= */
function renderArenaStatic() {
  layoutClaims();
  const edges = $('edges'); edges.innerHTML = '';
  Object.values(CLAIM_POS).forEach(p => {
    (p.claim.depends_on || []).forEach(dep => {
      const q = CLAIM_POS[dep];
      if (q) edges.insertAdjacentHTML('beforeend',
        `<path class="edge" data-claim="${esc(p.claim.id)}" d="M${q.x} ${q.y} C ${(q.x+p.x)/2} ${q.y}, ${(q.x+p.x)/2} ${p.y}, ${p.x} ${p.y}"/>`);
    });
  });
}
function updateEdges(touchedSet, targetClaim) {
  document.querySelectorAll('#edges path').forEach(p => {
    const c = p.dataset.claim || '';
    p.classList.toggle('lit', touchedSet.has(c));
    p.classList.toggle('hot', !!targetClaim && c === targetClaim);
  });
}

function bossSkin(st, touched) {
  if (st === 'SUPPORTED') return { ring:'var(--radiant)', fill:'oklch(0.3 0.07 150)', mark:'👑', op:1 };
  if (st === 'REFUTED') return { ring:'var(--dire)', fill:'oklch(0.28 0.09 25)', mark:'☠️', op:1 };
  if (st === 'INVALIDATED') return { ring:'var(--ghost)', fill:'oklch(0.26 0.05 310)', mark:'🌀', op:1 };
  if (st === 'INCONCLUSIVE') return { ring:'var(--amber)', fill:'oklch(0.27 0.05 80)', mark:'', qmark:'?!', op:1 };
  return { ring:'var(--line)', fill:'oklch(0.22 0.02 80)', mark:'', op: touched ? 0.95 : 0.45, lock: !touched };
}

let bossSig = '';
function renderBosses(claimStatuses, targetClaim, touchedSet) {
  const sig = JSON.stringify(claimStatuses || {}) + '|' + (targetClaim || '') + '|' + [...touchedSet].sort().join(',') + '|' + (SELECTED || '') + '|' + lang;
  if (sig === bossSig) return;
  bossSig = sig;
  const g = $('bosses'); g.innerHTML = '';
  Object.values(CLAIM_POS).forEach(p => {
    const st = (claimStatuses || {})[p.claim.id] || 'OPEN';
    const skin = bossSkin(st, touchedSet.has(p.claim.id));
    const targeted = p.claim.id === targetClaim && st !== 'SUPPORTED' && st !== 'REFUTED';
    const num = CLAIM_INDEX[p.claim.id] || '·';
    g.insertAdjacentHTML('beforeend', `
      <g class="claim-node${SELECTED === p.claim.id ? ' selected' : ''}" data-claim="${esc(p.claim.id)}" opacity="${skin.op}" tabindex="0" role="button" aria-label="${esc(claimLabel(p.claim))}">
        ${targeted ? `<circle cx="${p.x}" cy="${p.y}" r="40" fill="none" stroke="${skin.ring}" stroke-width="2" opacity="0.7"><animate attributeName="r" values="34;44;34" dur="1.6s" repeatCount="indefinite"/><animate attributeName="opacity" values="0.8;0.15;0.8" dur="1.6s" repeatCount="indefinite"/></circle>` : ''}
        <circle class="sel-ring" cx="${p.x}" cy="${p.y}" r="39" fill="none" stroke="var(--gold)" stroke-width="2.5" stroke-dasharray="6 5"/>
        <circle cx="${p.x}" cy="${p.y}" r="30" fill="${skin.fill}" stroke="${skin.ring}" stroke-width="3.5"/>
        ${skin.mark ? `<text x="${p.x}" y="${p.y + 7}" text-anchor="middle" font-size="21">${skin.mark}</text>` : skin.qmark ? `<text x="${p.x}" y="${p.y + 7}" text-anchor="middle" font-size="18" font-weight="900" fill="var(--amber)">${skin.qmark}</text>` : skin.lock ? `<text x="${p.x}" y="${p.y + 5}" text-anchor="middle" font-size="13" opacity=".75">🔒</text>` : `<text x="${p.x}" y="${p.y + 5}" text-anchor="middle" font-size="12" fill="var(--muted)">?</text>`}
        <circle cx="${p.x - 26}" cy="${p.y - 25}" r="10" fill="var(--gold)"/>
        <text class="boss-num" x="${p.x - 26}" y="${p.y - 21}" text-anchor="middle">${num}</text>
        <text class="boss-name" x="${p.x + 6}" y="${p.y - 42}" text-anchor="middle">${esc(claimLabel(p.claim))}</text>
      </g>`);
  });
  updateEdges(touchedSet, targetClaim);
}

function tipHtml(claim, st) {
  return `<b>${CLAIM_INDEX[claim.id] || ''} ${esc(claimLabel(claim))}</b> · ${status(st)}<br>${esc(trClaimF(claim, 'statement') || '')}<div class="tiny" style="margin-top:4px">${esc(t('tip_click'))} · ${esc(claim.id)}</div>`;
}
function renderUnitCard(claimId, statuses) {
  const card = $('unitCard');
  if (!claimId) { card.classList.remove('on'); return; }
  const claim = S.claims[claimId]; if (!claim) { card.classList.remove('on'); return; }
  const st = (statuses || {})[claimId] || claim.status || 'OPEN';
  const contracts = Object.values(S.contracts).filter(c => c.target_claim_id === claimId);
  const exps = Object.values(S.experiments).filter(x => (x.target_claim_ids || []).includes(claimId));
  card.innerHTML = `
    <div class="uc-head"><span class="uc-num">${CLAIM_INDEX[claimId] || ''}</span><span class="uc-label">${esc(claimLabel(claim))}</span><span class="uc-id mono">${esc(claimId)}</span><button class="uc-close" id="ucClose" type="button" aria-label="close">✕</button></div>
    <div class="uc-body">
      ${trClaimConclusion(claim) ? `<div class="uc-conc">${esc(trClaimConclusion(claim))}</div>` : ''}
      <div${trClaimConclusion(claim) ? ' class="tiny"' : ''}>${esc(trClaimF(claim, 'statement') || '')}</div>
      <div class="uc-sec"><span class="k">${esc(t('uc_status'))}</span> ${status(st)} <span class="tiny">· ${esc(claim.required ? t('required') : t('optional'))}</span>${claim.critical ? `<span class="tiny" style="color:var(--dire)"> · ${esc(t('critical'))}</span>` : ''}
        <span class="tiny"> · ${esc(L.evidence_n((claim.evidence_ids || []).length))} · ${esc(L.provisional_n(claim.provisional_passes || 0))}</span></div>
      ${contracts.length ? `<div class="uc-sec"><span class="k">${esc(t('uc_contracts'))}</span>${contracts.map(c => `<div class="tiny mono">${esc(c.id)} v${esc(c.version)} · ${esc(L.uc_gate(c.repetition.min_passes, c.repetition.min_independent_contexts))}</div>`).join('')}</div>` : ''}
      ${exps.length ? `<div class="uc-sec"><span class="k">${esc(t('uc_engagements'))}</span>${exps.slice(0, 6).map(x => `<div class="uc-exp"><span>${esc(String(trExpTitle(x))).slice(0, 40)}</span>${status((x.last_verdict || {}).status || x.status)}</div>`).join('')}${exps.length > 6 ? `<div class="tiny" style="margin-top:4px">${esc(L.uc_more(exps.length - 6))}</div>` : ''}</div>` : ''}
    </div>`;
  card.classList.add('on');
  const close = $('ucClose');
  if (close) close.onclick = () => { SELECTED = null; card.classList.remove('on'); refreshSelection(); };
}
function refreshSelection() {
  document.querySelectorAll('#bosses g.claim-node').forEach(n => n.classList.toggle('selected', n.dataset.claim === SELECTED));
}
function selectClaim(id, statuses) {
  SELECTED = (SELECTED === id) ? null : id;
  renderUnitCard(SELECTED, statuses || currentStatuses());
  refreshSelection();
}
function currentStatuses() { const f = frameAt(Number($('replaySlider').value)); return (f && f.claim_statuses) || {}; }
function initArenaPointer() {
  const bossOf = t => { const n = t.closest && t.closest('g.claim-node'); return n && n.dataset.claim; };
  $('arena').addEventListener('click', e => { const id = bossOf(e.target); if (id) selectClaim(id); });
  $('arena').addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const id = bossOf(e.target);
    if (id) { e.preventDefault(); selectClaim(id); }
  });
  $('arena').addEventListener('mousemove', e => {
    const id = bossOf(e.target);
    const tip = $('tip');
    if (!id) { tip.style.display = 'none'; return; }
    const wrap = $('arenaWrap').getBoundingClientRect();
    tip.innerHTML = tipHtml(S.claims[id], currentStatuses()[id] || 'OPEN');
    tip.style.display = 'block';
    tip.style.left = Math.max(4, Math.min(e.clientX - wrap.left + 16, wrap.width - 310)) + 'px';
    tip.style.top = (e.clientY - wrap.top + 14) + 'px';
  });
  $('arena').addEventListener('mouseleave', () => { $('tip').style.display = 'none'; });
  $('quest').addEventListener('click', e => { const n = e.target.closest('.q-row'); if (n && n.dataset.claim) selectClaim(n.dataset.claim); });
}

function moveHero(claimId, instant) {
  const p = claimId && CLAIM_POS[claimId];
  const hero = $('hero');
  const x = p ? Math.max(34, p.x - 52) : 70, y = p ? p.y + 20 : 480;
  if (instant) hero.style.transition = 'none';
  hero.style.transform = `translate(${x}px, ${y}px)`;
  if (instant) { void hero.getBoundingClientRect(); hero.style.transition = ''; }
}

/* combat fx */
function svgToScreen(x, y) {
  const svg = $('arena'), rect = svg.getBoundingClientRect(), wrap = $('arenaWrap').getBoundingClientRect();
  const vb = svg.viewBox.baseVal;
  const scale = Math.min(rect.width / vb.width, rect.height / vb.height);
  const ox = rect.left - wrap.left + (rect.width - vb.width * scale) / 2;
  const oy = rect.top - wrap.top + (rect.height - vb.height * scale) / 2;
  return { x: ox + x * scale, y: oy + y * scale };
}
function damageNumber(claimId, text, cls) {
  const p = CLAIM_POS[claimId]; if (!p) return;
  const s = svgToScreen(p.x, p.y - 20);
  const el = document.createElement('div');
  el.className = `dmg ${cls}`; el.textContent = text;
  el.style.left = s.x + 'px'; el.style.top = s.y + 'px';
  $('fxLayer').appendChild(el);
  setTimeout(() => el.remove(), 1600);
}
let annBusy = Promise.resolve(), annPending = 0;
function announce(text, cls, force) {
  if (!force && annPending >= 2) return;  // cap backlog during fast playback; terminal slams pass force
  annPending += 1;
  annBusy = annBusy.then(() => new Promise(done => {
    $('announcer').innerHTML = `<span class="${cls}">${esc(text)}</span>`;
    setTimeout(() => { $('announcer').innerHTML = ''; annPending -= 1; done(); }, 1400);
  }));
}
function shake() { const w = $('arenaWrap'); w.classList.remove('shake'); void w.offsetWidth; w.classList.add('shake'); }

function fireFx(ev) {
  const d = ev.data || {}, v = d.verdict || {};
  const expId = expIdOf(d);
  const exp = S.experiments[expId] || {};
  const claim = (exp.target_claim_ids || [])[0];
  if (ev.event_type === 'VERDICT_ISSUED') {
    const effects = d.claim_effects || [];
    const supported = effects.some(x => x.status === 'SUPPORTED');
    const rollback = effects.some(x => x.status === 'INVALIDATED' || (x.previous_status === 'SUPPORTED'));
    if (v.status === 'PASS') {
      damageNumber(claim, supported ? 'SUPPORTED!' : 'HIT!', 'pass');
      if (supported) announce(L.ann_supported(claim), 'radiant');
      if (ev.seq === FIRST_PASS_SEQ) announce(t('ann_first'), 'gold');
    } else if (v.status === 'FAIL') {
      damageNumber(claim, 'REFUTED!', 'fail'); shake();
      announce(L.ann_refuted(claim), 'dire');
      if (rollback) announce(t('ann_cascade'), 'dire');
    } else if (v.status === 'INVALID' || v.status === 'ERROR') {
      damageNumber(claim, 'MISS', 'miss');
    } else {
      damageNumber(claim, '?', 'soft');
    }
  } else if (ev.event_type === 'LESSON_PROMOTED') {
    announce(t('ann_loot'), 'gold');
  } else if (ev.event_type === 'RUN_FINALIZED') {
    const st = (d.status || '');
    announce(st === 'SOLVED' ? t('ann_victory') : st === 'REFUTED' ? t('ann_goal_refuted') : st === 'BUDGET_EXHAUSTED' ? t('ann_budget') : st, st === 'SOLVED' ? 'radiant' : 'dire', true);
  }
}

/* ================= HUD / frame application ================= */
function frameAt(i) { return FRAMES[Math.max(0, Math.min(FRAMES.length - 1, i))]; }

let prevAtt = null, prevCost = null;
function barFloat(kind, text) {
  const bar = document.querySelector(kind === 'hp' ? '.bar.hp' : '.bar.mana');
  if (!bar) return;
  const el = document.createElement('span');
  el.className = 'bar-fx down';
  el.textContent = text;
  bar.appendChild(el);
  setTimeout(() => el.remove(), 1150);
}
function applyFrame(i, opts) {
  opts = opts || {};
  const f = frameAt(i); if (!f) return;
  const ev = E[f.seq - 1] || {};
  const statuses = f.claim_statuses || {};
  const verified = Object.values(statuses).filter(x => x === 'SUPPORTED').length;
  const refuted = Object.values(statuses).filter(x => x === 'REFUTED').length;
  $('scoreV').textContent = verified; $('scoreR').textContent = refuted;
  const attMax = S.budget.max_attempts, costMax = S.budget.max_cost_units;
  const att = f.attempts_remaining ?? S.budget.attempts_remaining;
  const cost = f.cost_units_remaining ?? S.budget.cost_units_remaining;
  if (opts.fx && prevAtt !== null && prevCost !== null && att != null && cost != null) {
    if (att < prevAtt) barFloat('hp', `−${prevAtt - att}`);
    if (cost < prevCost - 1e-9) barFloat('mana', `−${(prevCost - cost).toFixed(1)}`);
  }
  if (att != null) prevAtt = att;
  if (cost != null) prevCost = cost;
  if (attMax == null) {
    $('hpFill').style.transform = 'scaleX(1)';
    $('hpText').textContent = `${t('attempts')} ∞`;
  } else {
    $('hpFill').style.transform = `scaleX(${Math.max(0, (att ?? 0) / attMax)})`;
    $('hpText').textContent = `${t('attempts')} ${att}/${attMax}`;
  }
  if (costMax == null) {
    $('manaFill').style.transform = 'scaleX(1)';
    $('manaText').textContent = `${t('cost')} ∞`;
  } else {
    $('manaFill').style.transform = `scaleX(${Math.max(0, (cost ?? 0) / costMax)})`;
    $('manaText').textContent = `${t('cost')} ${Number(cost ?? 0).toFixed(1)}/${costMax}`;
  }
  $('matchMeta').textContent = `seq ${f.seq}/${E.length} · ${runStatusLabel(f.run_status)} · ${t('obj_label')} ${f.objective}% · ${t('epi_label')} ${f.epistemic}%`;
  $('lootMeta').textContent = f.n_lessons ? `💰×${f.n_lessons}` : '';
  const target = TARGET_BY_SEQ[f.seq];
  renderBosses(statuses, target, TOUCHED_BY_SEQ[f.seq] || new Set());
  moveHero(target, opts.instant);
  const combo = COMBO_BY_SEQ[f.seq] || 0;
  $('combo').textContent = combo >= 2 ? L.combo(combo) : '';
  $('combo').classList.toggle('on', combo >= 2);
  renderQuest(statuses);
  if (SELECTED) renderUnitCard(SELECTED, statuses);
  const n = narrate(ev);
  if (n.caster) $('casterLine').textContent = n.caster;
  $('frameLabel').textContent = `#${f.seq}/${E.length} · ${ev.event_type || ''} · ${ev.ts || ''}`;
  $('tlFill').style.width = pctOf(i) + '%';
  $('tlCursor').style.left = pctOf(i) + '%';
  $('replaySlider').value = i;
  if (opts.fx && ev.event_type) fireFx(ev);
  if (opts.feedRebuild) rebuildFeed(f.seq); else if (opts.fx) appendFeed(ev);
  updateEndboard(f);
  try { history.replaceState(null, '', '#seq=' + f.seq); } catch (_) {}
}

/* ---------- end-game scoreboard ---------- */
const FINAL_STATUSES = new Set(['SOLVED','BUDGET_EXHAUSTED','FAILED','CANCELLED','ABORTED','TIME_EXHAUSTED','MAX_STATES_EXHAUSTED','BLOCKED']);
function isFinalStatus(st) { return FINAL_STATUSES.has(st) || /_EXHAUSTED$/.test(st || ''); }
let ebDismissed = false;
function matchDuration() {
  if (!E.length) return '—';
  const t0 = Date.parse(E[0].ts || ''), t1 = Date.parse(E[E.length - 1].ts || '');
  if (!t0 || !t1 || t1 < t0) return '—';
  const s = Math.round((t1 - t0) / 1000);
  return L.eb_dur(Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60);
}
function claimMark(st, required) {
  return st === 'SUPPORTED' ? '👑' : st === 'REFUTED' ? '☠️' : st === 'INVALIDATED' ? '🌀' : required ? '⚔️' : '◇';
}
function updateEndboard(f) {
  const final = !!(f && isFinalStatus(f.run_status));
  const show = final && follow && !ebDismissed;
  if (show) renderEndboard(f);
  $('endboard').classList.toggle('on', show);
  $('endboardBtn').classList.toggle('on', final && follow && ebDismissed);
}
let ebSig = '';
function renderEndboard(f) {
  const sig = (f && f.seq) + '|' + lang;
  if (sig === ebSig) return;
  ebSig = sig;
  const statuses = f.claim_statuses || {};
  const verified = Object.values(statuses).filter(x => x === 'SUPPORTED').length;
  const refuted = Object.values(statuses).filter(x => x === 'REFUTED').length;
  const attMax = S.budget.max_attempts, costMax = S.budget.max_cost_units;
  const att = f.attempts_remaining ?? S.budget.attempts_remaining;
  const cost = f.cost_units_remaining ?? S.budget.cost_units_remaining;
  const st = f.run_status || '';
  const titleCls = st === 'SOLVED' ? 'radiant' : st === 'BUDGET_EXHAUSTED' ? 'dire' : 'gold';
  const titleTxt = st === 'SOLVED' ? t('ann_victory') : st === 'BUDGET_EXHAUSTED' ? t('ann_budget') : runStatusLabel(st);
  const attV = (attMax != null && att != null) ? `${attMax - att}/${attMax}` : '—';
  const costV = (costMax != null && cost != null) ? `${(costMax - cost).toFixed(1)}/${costMax}` : '—';
  const claims = Object.values(S.claims).map(c => {
    const cs = statuses[c.id] || c.status || 'OPEN';
    return `<div class="eb-claim"><span class="eb-cn">${CLAIM_INDEX[c.id] || ''}</span><span>${claimMark(cs, c.required)}</span><span>${esc(claimLabel(c))}</span><span class="st">${status(cs)}</span></div>`;
  }).join('');
  $('endboard').innerHTML = `<div class="eb-panel">
    <div class="eb-kicker">${esc(t('eb_kicker'))} · ${esc(runStatusLabel(st))}</div>
    <div class="eb-title ${titleCls}">${esc(titleTxt)}</div>
    <div class="eb-sub">${esc(trTopic())}</div>
    <div class="eb-score"><span class="n radiant">${verified}</span><span class="lbl">${esc(t('verified'))}</span><span class="vs2">VS</span><span class="n dire">${refuted}</span><span class="lbl">${esc(t('refuted'))}</span></div>
    <div class="eb-grid">
      <div class="eb-stat"><div class="k">${esc(t('eb_attempts'))}</div><div class="v">${esc(attV)}</div></div>
      <div class="eb-stat"><div class="k">${esc(t('eb_cost'))}</div><div class="v">${esc(costV)}</div></div>
      <div class="eb-stat"><div class="k">${esc(t('eb_duration'))}</div><div class="v">${esc(matchDuration())}</div></div>
      <div class="eb-stat"><div class="k">${esc(t('eb_lessons'))}</div><div class="v">💰 ${f.n_lessons || 0}</div></div>
      <div class="eb-stat"><div class="k">${esc(t('eb_events'))}</div><div class="v">${E.length}</div></div>
    </div>
    <div class="eb-claims">${claims}</div>
    <div class="eb-actions"><button class="primary" data-eb="replay">▶ ${esc(t('eb_replay'))}</button><button data-eb="map">${esc(t('eb_view_map'))}</button></div>
  </div>`;
}

function pctOf(i) { return FRAMES.length <= 1 ? 100 : (100 * i) / (FRAMES.length - 1); }

function rebuildFeed(uptoSeq) {
  const rows = [];
  for (let k = E.length - 1; k >= 0 && rows.length < 30; k--) {
    if (E[k].seq > uptoSeq) continue;
    rows.push(feedRowHtml(E[k]));
  }
  $('feed').innerHTML = rows.join('');
  $('feedCount').textContent = L.events_n(Math.min(uptoSeq, E.length));
}
function feedRowHtml(ev) {
  const n = narrate(ev);
  return `<div class="feed-row ${n.cls}" data-seq="${ev.seq}" title="${esc(t('feed_jump'))}"><span class="seq mono">#${ev.seq}</span><span>${n.icon}</span><span>${esc(n.feed)}</span><span class="ts mono">${esc((ev.ts || '').slice(11, 19))}</span></div>`;
}
function appendFeed(ev) {
  $('feed').insertAdjacentHTML('afterbegin', feedRowHtml(ev));
  while ($('feed').children.length > 30) $('feed').lastChild.remove();
  $('feedCount').textContent = L.events_n(ev.seq);
}

function renderWaiting() {
  const waits = (S.waits || []).filter(w => w.status === 'PENDING');
  const has = waits.length > 0;
  $('respawnSec').style.display = has ? '' : 'none';
  $('waitingList').style.display = has ? '' : 'none';
  if (!has) return;
  $('nextWake').textContent = S.next_wake_at ? `⏰ ${S.next_wake_at}` : t('awaiting_evidence');
  $('waitingList').innerHTML = waits.map(w => {
    const x = S.experiments[w.experiment_id] || {};
    const cond = w.kind === 'time' ? L.wait_not_before(w.not_before_ts || '—') : L.wait_until(((w.until_evidence || {}).claim_id) || '?');
    return `<div class="feed-row info"><span>⏳</span><span>${esc(trExpTitle(x) || w.experiment_id)}<span class="tiny"> · ${esc(cond)}</span></span></div>`;
  }).join('');
}
let questSig = '';
function renderQuest(statuses) {
  const sig = JSON.stringify(statuses || {}) + '|' + lang;
  if (sig === questSig) return;
  questSig = sig;
  const rows = Object.values(S.claims).map(c => {
    const st = (statuses || {})[c.id] || c.status || 'OPEN';
    const mark = st === 'SUPPORTED' ? '👑' : st === 'REFUTED' ? '☠️' : st === 'INVALIDATED' ? '🌀' : c.required ? '⚔️' : '◇';
    const conc = trClaimConclusion(c);
    const stmt = String(trClaimF(c, 'statement') || '');
    return `<div class="q-row q-${esc(st)}" data-claim="${esc(c.id)}" style="cursor:pointer"><div class="q-title"><span class="q-mark">${mark}</span><span style="color:var(--gold);font-weight:900">${CLAIM_INDEX[c.id] || ''}</span><span>${esc(claimLabel(c))}</span><span class="q-state">${esc(st)}</span></div><div class="q-sub${conc ? ' q-conc' : ''}" title="${esc(stmt)}">${esc(conc || stmt.slice(0, 72))}</div></div>`;
  });
  $('quest').innerHTML = rows.join('');
  $('questCount').textContent = L.claims_n(Object.keys(S.claims).length);
}

/* ================= playback deck ================= */
let follow = true, playTimer = null, speed = 2, liveChain = 0;
function setLiveChip() {
  const runFinal = isFinalStatus((FRAMES[FRAMES.length - 1] || {}).run_status);
  $('liveChip').classList.toggle('replaying', !follow);
  $('liveChip').classList.toggle('ended', runFinal);
  $('liveText').textContent = follow ? (runFinal ? t('ended') : t('live')) : t('replay');
  $('liveBtn').classList.toggle('active', follow);
}
function showIndex(i, opts) {
  if (!FRAMES.length) return;
  i = Math.max(0, Math.min(FRAMES.length - 1, i));
  follow = i === FRAMES.length - 1;
  setLiveChip();
  applyFrame(i, opts || { feedRebuild: true });
}
function stopPlay() { liveChain += 1; if (playTimer) { clearInterval(playTimer); playTimer = null; $('playBtn').textContent = '▶'; $('playBtn').classList.remove('active'); } }
function startPlay() {
  if (!FRAMES.length) return;
  stopPlay();
  let i = Number($('replaySlider').value);
  if (i >= FRAMES.length - 1) { i = -1; }
  $('playBtn').textContent = '⏸'; $('playBtn').classList.add('active');
  const stepMs = 1000 / speed;
  if (i === -1) { i = 0; showIndex(0, { feedRebuild: true, instant: true }); }
  playTimer = setInterval(() => {
    i += 1;
    if (i >= FRAMES.length) { stopPlay(); showIndex(FRAMES.length - 1, { feedRebuild: true }); return; }
    showIndex(i, { fx: true });
  }, stepMs);
}
function renderMarkers() {
  $('tlMarks').innerHTML = MARKERS.map(m => {
    const i = m.seq - 1;
    return `<div class="tl-mark ${m.cls}" style="left:${pctOf(i)}%" title="${esc(m.label)}"></div>`;
  }).join('');
  $('replaySlider').max = Math.max(0, FRAMES.length - 1);
  $('tlStart').textContent = E.length ? (E[0].ts || '').slice(5, 16).replace('T', ' ') : '';
  $('tlEnd').textContent = E.length ? (E[E.length - 1].ts || '').slice(5, 16).replace('T', ' ') : '';
}
function initDeck() {
  renderMarkers();
  $('replaySlider').addEventListener('input', () => { stopPlay(); showIndex(Number($('replaySlider').value), { feedRebuild: true }); });
  $('playBtn').addEventListener('click', e => { playTimer ? stopPlay() : startPlay(); e.currentTarget.blur(); });
  $('liveBtn').addEventListener('click', e => { stopPlay(); showIndex(FRAMES.length - 1, { feedRebuild: true }); e.currentTarget.blur(); });
  $('speedSel').addEventListener('change', () => { speed = Number($('speedSel').value) || 2; if (playTimer) startPlay(); });
  $('feed').addEventListener('click', e => {
    const row = e.target.closest('.feed-row[data-seq]');
    if (!row) return;
    stopPlay();
    showIndex(Number(row.dataset.seq) - 1, { feedRebuild: true });
  });
  $('endboard').addEventListener('click', e => {
    const b = e.target.closest('[data-eb]');
    if (!b) return;
    ebDismissed = true;
    updateEndboard(frameAt(Number($('replaySlider').value)));
    if (b.dataset.eb === 'replay') { showIndex(0, { feedRebuild: true, instant: true }); startPlay(); }
  });
  $('endboardBtn').addEventListener('click', () => { ebDismissed = false; updateEndboard(frameAt(Number($('replaySlider').value))); });
  window.addEventListener('keydown', e => {
    if (e.target.closest && e.target.closest('input,select,textarea')) return;
    if (e.code === 'Space') { e.preventDefault(); playTimer ? stopPlay() : startPlay(); }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault(); stopPlay();
      const d = (e.key === 'ArrowRight' ? 1 : -1) * (e.shiftKey ? 10 : 1);
      showIndex(Number($('replaySlider').value) + d, { feedRebuild: true });
    } else if (e.key === 'Home') { e.preventDefault(); stopPlay(); showIndex(0, { feedRebuild: true }); }
    else if (e.key === 'End') { e.preventDefault(); stopPlay(); showIndex(FRAMES.length - 1, { feedRebuild: true }); }
  });
}

/* ================= live broadcast polling ================= */
async function poll() {
  if (document.hidden) return;
  try {
    const r = await fetch(`snapshot.json?ts=${Date.now()}`, { cache: 'no-store' });
    const fresh = await r.json();
    if (!fresh?.snapshot?.snapshot_hash || fresh.snapshot.snapshot_hash === S.snapshot_hash) return;
    const oldLen = FRAMES.length;
    S = fresh.snapshot; E = fresh.events || []; FRAMES = fresh.frames || [];
    ebDismissed = false;
    deriveTimeline(); renderArenaStatic(); renderMarkers(); renderDetailTabs(); renderWaiting();
    if (follow && !playTimer) {
      const chain = ++liveChain;
      let i = Math.max(0, oldLen - 1);
      const step = () => {
        if (chain !== liveChain) return;
        i += 1;
        if (i >= FRAMES.length) { showIndex(FRAMES.length - 1, {}); return; }
        applyFrame(i, { fx: true });
        setTimeout(step, 650);
      };
      step();
    }
  } catch (_) { /* between writes; retry next tick */ }
}

/* ================= detail tabs (audit layer) ================= */
function initTabs() {
  document.querySelectorAll('.tab').forEach(btn => btn.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.view').forEach(x => x.classList.remove('active'));
    btn.classList.add('active');
    if (btn.dataset.view !== 'none') {
      const v = $('view-' + btn.dataset.view);
      v.classList.add('active');
      requestAnimationFrame(() => v.scrollIntoView({ behavior: 'smooth', block: 'start' }));
    } else {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }));
  $('evTypeFilter').addEventListener('change', renderEventList);
  let evDebounce = null;
  $('evTextFilter').addEventListener('input', () => { clearTimeout(evDebounce); evDebounce = setTimeout(renderEventList, 150); });
}
function graphDepth(nodes, root) { const map = Object.fromEntries(nodes.map(n => [n.id, n])); const depth = {}; const walk = (id, d) => { depth[id] = Math.max(depth[id] ?? 0, d); (map[id]?.children || []).forEach(c => walk(c, d + 1)); }; walk(root, 0); return depth; }
function fmtMetricVal(v) { let s = typeof v === 'number' ? (Number.isInteger(v) ? String(v) : String(Math.round(v * 10000) / 10000)) : (v !== null && typeof v === 'object') ? JSON.stringify(v) : String(v); return s.length > 64 ? s.slice(0, 61) + '…' : s; }
function evExtras(x) {
  const mets = x.metrics && typeof x.metrics === 'object' ? Object.entries(x.metrics).slice(0, 8) : [];
  const arts = x.artifact_refs || [];
  return `${mets.length ? `<div class="ev-metrics">${mets.map(([k, v]) => `<span class="m">${esc(k)}=${esc(fmtMetricVal(v))}</span>`).join('')}</div>` : ''}${arts.length ? `<div class="ev-art">${esc(t('artifacts_label'))}: ${arts.map(a => `<a href="artifact/${encodeURIComponent(a.path || '')}" target="_blank" rel="noopener" class="mono">${esc(a.path || '')}</a>`).join(' · ')}</div>` : ''}`;
}
function trReportBlock() {
  return (((DATA.translations || {})[lang] || {}).report) || (((S.i18n || {})[lang] || {}).report) || null;
}
function renderReport() {
  const f = frameAt(FRAMES.length - 1) || {};
  const statuses = f.claim_statuses || {};
  const st = f.run_status || S.run_status || '';
  const titleCls = st === 'SOLVED' ? 'radiant' : st === 'BUDGET_EXHAUSTED' ? 'dire' : 'gold';
  const titleTxt = st === 'SOLVED' ? t('ann_victory') : st === 'BUDGET_EXHAUSTED' ? t('ann_budget') : runStatusLabel(st);
  const attMax = S.budget.max_attempts, costMax = S.budget.max_cost_units;
  const att = f.attempts_remaining ?? S.budget.attempts_remaining;
  const cost = f.cost_units_remaining ?? S.budget.cost_units_remaining;
  const attV = (attMax != null && att != null) ? `${attMax - att}/${attMax}` : '—';
  const costV = (costMax != null && cost != null) ? `${(costMax - cost).toFixed(1)}/${costMax}` : '—';
  const tally = {};
  Object.values(S.attempts).forEach(a => { const v = (a.verdict || {}).status; if (v) tally[v] = (tally[v] || 0) + 1; });
  const evByClaim = {};
  Object.values(S.evidence).forEach(x => {
    const exp = S.experiments[x.experiment_id] || {};
    (exp.target_claim_ids || []).forEach(cid => { (evByClaim[cid] = evByClaim[cid] || []).push(x); });
  });
  const claims = Object.values(S.claims);
  const loot = Object.values(S.lessons);
  const activeLoot = loot.filter(x => x.status !== 'REVOKED');
  const revokedLoot = loot.filter(x => x.status === 'REVOKED');
  const verified = Object.values(statuses).filter(x => x === 'SUPPORTED').length;
  const refuted = Object.values(statuses).filter(x => x === 'REFUTED').length;
  const rb = trReportBlock() || {};
  const headline = rb.headline || `${titleTxt} · ${t('verified')} ${verified} · ${t('refuted')} ${refuted}`;
  const doItems = (rb.do && rb.do.length ? rb.do : activeLoot.map(x => trLessonF(x, 'recommendation'))).filter(Boolean);
  const dontItems = (rb.dont && rb.dont.length ? rb.dont : [
    ...revokedLoot.map(x => trLessonF(x, 'recommendation')),
    ...claims.filter(c => (evByClaim[c.id] || []).some(x => x.verdict_status === 'FAIL'))
      .map(c => `FAIL×${(evByClaim[c.id] || []).filter(x => x.verdict_status === 'FAIL').length} · ${claimLabel(c)}`),
  ]).filter(Boolean);
  $('reportBody').innerHTML = `
  <div class="card card-pad">
    <div class="eb-kicker">${esc(t('eb_kicker'))} · ${esc(runStatusLabel(st))}</div>
    <div class="eb-title ${titleCls}" style="font-size:clamp(26px,3.6vw,38px)">${esc(titleTxt)}</div>
    <div class="rpt-topic">${esc(trTopic())}</div>
    <div class="rpt-answer">${esc(headline)}</div>
    <div class="eb-grid" style="margin-top:14px;margin-bottom:10px">
      <div class="eb-stat"><div class="k">${esc(t('eb_attempts'))}</div><div class="v">${esc(attV)}</div></div>
      <div class="eb-stat"><div class="k">${esc(t('eb_cost'))}</div><div class="v">${esc(costV)}</div></div>
      <div class="eb-stat"><div class="k">${esc(t('eb_duration'))}</div><div class="v">${esc(matchDuration())}</div></div>
      <div class="eb-stat"><div class="k">${esc(t('eb_lessons'))}</div><div class="v">💰 ${f.n_lessons || 0}</div></div>
      <div class="eb-stat"><div class="k">${esc(t('eb_events'))}</div><div class="v">${E.length}</div></div>
    </div>
    <div class="tiny">${esc(t('rpt_verdicts'))}: ${Object.entries(tally).map(([k, n]) => `${k}×${n}`).join(' · ') || '—'}</div>
  </div>
  ${doItems.length ? `<div class="card card-pad"><div class="section-title"><h2>${esc(t('rpt_do'))}</h2></div><div class="rpt-do">${doItems.map(x => `<div class="rpt-step">${esc(x)}</div>`).join('')}</div></div>` : ''}
  ${dontItems.length ? `<div class="card card-pad"><div class="section-title"><h2>${esc(t('rpt_dont'))}</h2></div><div class="rpt-do rpt-dont">${dontItems.map(x => `<div class="rpt-step">${esc(x)}</div>`).join('')}</div></div>` : ''}
  <div class="card card-pad">
    <div class="section-title"><h2>${esc(t('sec_takeaways'))}</h2></div>
    <div class="rpt-claims">${claims.map(c => {
      const cs = statuses[c.id] || c.status || 'OPEN';
      const conc = trClaimConclusion(c) || trClaimF(c, 'statement') || '';
      return `<div class="rpt-claim"><span>${claimMark(cs, c.required)}</span><b>${CLAIM_INDEX[c.id] || ''} ${esc(claimLabel(c))}</b><span class="rpt-conc">${esc(conc)}</span><span class="st">${status(cs)}</span></div>`;
    }).join('')}</div>
  </div>
  <details class="card card-pad rpt-fold"><summary class="section-title"><h2>${esc(t('rpt_details'))}</h2></summary>
    ${claims.map(c => {
      const cs = statuses[c.id] || c.status || 'OPEN';
      const conc = trClaimConclusion(c);
      const evs = evByClaim[c.id] || [];
      return `<div class="rpt-cblock">
        <div class="rpt-chead"><span>${claimMark(cs, c.required)}</span><b>${CLAIM_INDEX[c.id] || ''} ${esc(claimLabel(c))}</b>${status(cs)}</div>
        ${conc ? `<div class="rpt-conc-line">${esc(conc)}</div>` : ''}
        <div class="rpt-stmt">${esc(trClaimF(c, 'statement') || '')}</div>
        ${evs.length ? evs.map(x => `<div class="rpt-ev">${status(x.verdict_status)}<span class="tiny">${esc(reasonSummary(x))}</span>${evExtras(x)}</div>`).join('') : `<div class="tiny">—</div>`}
      </div>`;
    }).join('')}
  </details>
  ${loot.length ? `<details class="card card-pad rpt-fold"><summary class="section-title"><h2>${esc(t('sec_loot_final'))}</h2></summary>
    ${loot.map(x => `<div class="rpt-cblock"><div class="rpt-chead"><b>💰 ${esc(trLessonF(x, 'recommendation'))}</b>${status(x.status)}</div><div class="rpt-stmt">${esc(trLessonF(x, 'observation'))}</div></div>`).join('')}
  </details>` : ''}`;
}
function renderDetailTabs() {
  $('goalRoot').innerHTML = `${esc(t('root'))} ${status(S.goal_evaluation.root_status)}`;
  const nodes = S.goal_evaluation.nodes, depths = graphDepth(nodes, S.goal_evaluation.root_id);
  $('goalTree').innerHTML = nodes.slice().sort((a, b) => (depths[a.id] ?? 0) - (depths[b.id] ?? 0)).map(n => { const title = n.claim_id && S.claims[n.claim_id] ? (trClaimF(S.claims[n.claim_id], 'statement') || n.title) : (n.title === S.topic ? trTopic() : n.title); return `<div class="goal-node ${n.status === 'PASS' ? 'pass' : n.status === 'FAIL' ? 'fail' : 'open'} indent-${Math.min(3, depths[n.id] ?? 0)}"><div class="item-head"><div><b>${esc(title)}</b><div class="item-meta mono">${esc(n.id)} · ${esc(n.kind)}${n.claim_id ? ' · ' + esc(n.claim_id) : ''}</div></div>${status(n.status)}</div></div>`; }).join('');
  const gaps = S.verifier_gaps;
  $('verifierCoverage').innerHTML = gaps.length ? `<div class="item"><b style="color:var(--amber)">${esc(t('cov_missing'))}</b><div class="mono tiny" style="margin-top:8px">${gaps.map(esc).join('<br>')}</div></div>` : `<div class="item"><b style="color:var(--radiant)">${esc(t('cov_full'))}</b></div>`;
  $('currentState').textContent = S.current_state_id;
  const states = Object.values(S.states).sort((a, b) => a.seq - b.seq);
  $('executionList').innerHTML = states.map(st => { const exp = st.experiment_id ? S.experiments[st.experiment_id] : null; const rb = st.rollback || []; return `<div class="item"><div class="item-head"><div><div class="item-title mono">${esc(st.id)}</div><div class="item-meta">parents: ${st.parent_state_ids.length ? st.parent_state_ids.map(esc).join(', ') : 'genesis'}</div></div>${st.id === S.current_state_id ? '<span class="status ACTIVE">CURRENT</span>' : ''}</div>${exp ? `<div style="margin-top:6px"><b>${esc(trExpTitle(exp))}</b> · ${status(exp.last_verdict?.status || exp.status)}<div class="tiny">${esc(exp.id)} → ${exp.target_claim_ids.map(esc).join(', ')}</div></div>` : ''}${rb.length ? `<div class="tiny" style="color:var(--ghost);margin-top:6px">rollback: ${rb.map(x => esc(x.claim_id) + ' ← ' + esc(x.source_claim_id || x.previous_status)).join('; ')}</div>` : ''}</div>`; }).join('');
  const ruleCount = c => ['preconditions','invalid_if','pass_if','fail_if','guardrails'].reduce((n, k) => n + (c[k]?.all?.length || 0) + (c[k]?.any?.length || 0), 0);
  $('contractRows').innerHTML = Object.values(S.contracts).map(c => `<tr><td class="mono">${esc(c.id)}</td><td>${esc(c.target_claim_id)}</td><td>${esc(c.version)}</td><td>${c.repetition.min_passes} pass / ${c.repetition.min_independent_contexts} ctx</td><td>${ruleCount(c)} checks · ${esc(c.kind)}</td></tr>`).join('');
  $('attemptRows').innerHTML = Object.values(S.attempts).sort((a, b) => String(a.id).localeCompare(String(b.id))).map(a => `<tr><td class="mono">${esc(a.id)}</td><td>${esc(a.experiment_id)}</td><td>${esc(a.context_id)}</td><td>${status(a.status)}</td><td>${status(a.verdict?.status || 'MISSING')}</td><td>${esc(a.verdict?.reason_code || '—')}</td><td class="mono">${esc(a.to_state_id || '—')}</td></tr>`).join('');
  const evidence = Object.values(S.evidence);
  $('evidenceList').innerHTML = evidence.length ? evidence.map(x => `<div class="item"><div class="item-head"><div><div class="item-title">${esc(reasonSummary(x))}</div><div class="item-meta mono">${esc(x.id)} · ${esc(x.contract_id)} · ${esc(x.context_id)} · ${esc(x.reason_code)}</div></div>${status(x.verdict_status)}</div>${reasonExtra(x) ? `<div class="tiny" style="margin-top:6px;opacity:.75">${esc(reasonExtra(x))}</div>` : ''}${evExtras(x)}</div>`).join('') : `<div class="empty">${esc(t('empty_evidence'))}</div>`;
  const lessons = Object.values(S.lessons); const usage = S.lesson_usage || {};
  $('lessonList').innerHTML = lessons.length ? lessons.map(x => { const u = usage[x.id]; return `<div class="item"><div class="item-head"><div><div class="item-title">💰 ${esc(trLessonF(x, 'recommendation'))}</div><div class="item-meta mono">${esc(x.id)} · ${esc(L.evidence_n((x.evidence_ids || []).length))}${u ? ` · ${esc(L.cited_n(u.experiment_ids.length))}` : ''}</div></div>${status(x.status)}</div><div class="tiny" style="margin-top:6px">${esc(trLessonF(x, 'observation'))}</div></div>`; }).join('') : `<div class="empty">${esc(t('empty_lessons'))}</div>`;
  $('eventHead').textContent = `head ${String(S.event_chain_head || '').slice(0, 20)}…`;
  renderEventList();
  renderReport();
}
let evSig = '';
function renderEventList() {
  const sel = $('evTypeFilter'), tf = $('evTextFilter');
  if (!sel || !tf) return;
  const cur = sel.value || '';
  const textF = (tf.value || '').toLowerCase();
  const sig = cur + '|' + textF + '|' + E.length + '|' + lang;
  if (sig === evSig) return;
  evSig = sig;
  const openSeqs = new Set([...document.querySelectorAll('#eventList .ev-details[open]')].map(d => d.dataset.seq));
  const types = [...new Set(E.map(ev => ev.event_type))].sort();
  sel.innerHTML = `<option value="">${esc(t('ev_all_types'))}</option>` + types.map(x => `<option value="${esc(x)}"${x === cur ? ' selected' : ''}>${esc(x)}</option>`).join('');
  const rows = [...E].reverse().filter(ev => (!cur || ev.event_type === cur) && (!textF || ev.event_type.toLowerCase().includes(textF) || JSON.stringify(ev.data).toLowerCase().includes(textF)));
  $('eventList').innerHTML = rows.length ? rows.map(ev => { const n = narrate(ev); return `<details class="ev-details" data-seq="${ev.seq}"${openSeqs.has(String(ev.seq)) ? ' open' : ''}><summary><span class="mono tiny">#${ev.seq}</span><span class="ev-type ${n.cls}">${esc(ev.event_type)}</span><span class="tiny">${esc(ev.actor)} · ${esc((ev.ts || '').slice(11, 19))}</span><span class="ev-sum">${esc(n.feed)}</span></summary><pre class="ev-json mono">${esc(JSON.stringify(ev.data, null, 2))}</pre></details>`; }).join('') : `<div class="empty">—</div>`;
}

/* ================= boot ================= */
applyStaticI18n();
$('langBtn').addEventListener('click', () => setLang(lang === 'zh' ? 'en' : 'zh'));
deriveTimeline(); renderArenaStatic(); initDeck(); initTabs(); initArenaPointer(); renderDetailTabs(); renderWaiting();
const hashSeq = (location.hash || '').match(/seq=([0-9]+)/);
showIndex(hashSeq ? Number(hashSeq[1]) - 1 : FRAMES.length - 1, { feedRebuild: true, instant: true });
window.addEventListener('beforeprint', () => document.querySelectorAll('details').forEach(d => { d.open = true; }));
if (location.protocol === 'http:' || location.protocol === 'https:') setInterval(poll, 2000);
</script>
</body>
</html>"""


def render_observatory(
    workspace: ResearchWorkspace,
    snapshot: dict[str, Any],
    *,
    events: list[dict[str, Any]],
    frames: list[dict[str, Any]] | None = None,
) -> Path:
    """Render a self-contained HTML projection from persisted facts only."""
    workspace.report_dir.mkdir(parents=True, exist_ok=True)
    translations: dict[str, Any] = {}
    if workspace.i18n_path.exists():
        try:
            loaded = json.loads(workspace.i18n_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                translations = loaded
        except (json.JSONDecodeError, OSError):
            translations = {}
    public_snapshot = {
        "snapshot": snapshot,
        "events": events,
        "frames": frames or [],
        "translations": translations,
    }
    atomic_write_json(workspace.report_snapshot_path, public_snapshot)
    topic = html.escape(str(snapshot.get("topic") or "Sisyfus Research"))
    payload = _json_for_script(public_snapshot)
    document = _TEMPLATE.replace("__TOPIC__", topic).replace("__PAYLOAD__", payload)
    workspace.report_path.write_text(document, encoding="utf-8")
    _render_stable_entry(workspace, document)
    return workspace.report_path


_ENTRY_BOOTSTRAP = """<script>
/* Stable entry page: hop to the live Observatory whenever the local daemon is up. */
(function () {
  if (location.protocol !== 'file:') return;
  var base = 'http://127.0.0.1:__PORT__';
  var probe = function () {
    fetch(base + '/snapshot.json', {mode: 'no-cors', cache: 'no-store'})
      .then(function () { location.replace(base + '/index.html'); })
      .catch(function () { setTimeout(probe, 3000); });
  };
  probe();
})();
</script>"""


def _render_stable_entry(workspace: ResearchWorkspace, document: str) -> None:
    """Refresh `<root>/.sisyfus/observatory.html` — the one bookmarkable entry.

    The copy shows the state as of the last engine operation even with no
    server running, and redirects to the live daemon the moment one answers
    on this project's port.
    """
    from .live import derived_port, observatory_entry_path, read_live_state

    state = read_live_state(workspace.root)
    port = int(state["port"]) if state else derived_port(workspace.root)
    bootstrap = _ENTRY_BOOTSTRAP.replace("__PORT__", str(port))
    entry = observatory_entry_path(workspace.root)
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(document.replace("</body>", bootstrap + "\n</body>"), encoding="utf-8")


class _ObservatoryHandler(SimpleHTTPRequestHandler):
    refresh_callback: Callable[[], None] | None = None
    artifact_root: str | None = None
    verbose: bool = False

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        path = self.path.split("?", 1)[0]
        if path.startswith("/artifact/"):
            self._serve_artifact(path[len("/artifact/"):])
            return
        if self.refresh_callback is not None and path in {"/", "/index.html", "/snapshot.json"}:
            self.refresh_callback()
        super().do_GET()

    def _serve_artifact(self, rel: str) -> None:
        """Serve a run artifact referenced by evidence, confined to the run dir."""
        from urllib.parse import unquote

        root = type(self).artifact_root
        if not root:
            self.send_error(404)
            return
        base = Path(root).resolve()
        candidate = (base / unquote(rel)).resolve()
        if candidate != base and base not in candidate.parents:
            self.send_error(403)
            return
        if not candidate.is_file():
            self.send_error(404)
            return
        try:
            data = candidate.read_bytes()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(str(candidate)))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        if self.verbose:
            super().log_message(format, *args)


def serve_observatory(
    workspace: ResearchWorkspace,
    *,
    refresh_callback: Callable[[], None],
    host: str = "127.0.0.1",
    port: int = 8787,
    open_browser: bool = False,
    verbose: bool = False,
) -> tuple[ThreadingHTTPServer, str]:
    """Serve a live-refreshing local Observatory.

    The callback replays events and regenerates projections before snapshot/index
    requests, allowing a browser to monitor a run being mutated by another process.
    """
    handler_cls = type(
        "SisyfusObservatoryHandler",
        (_ObservatoryHandler,),
        {
            "refresh_callback": staticmethod(refresh_callback),
            "artifact_root": str(workspace.path),
            "verbose": verbose,
        },
    )
    handler = partial(handler_cls, directory=str(workspace.report_dir))
    server = ThreadingHTTPServer((host, port), handler)
    actual_port = int(server.server_address[1])
    url = f"http://{host}:{actual_port}/index.html"
    if open_browser:
        threading.Timer(0.15, lambda: webbrowser.open(url)).start()
    return server, url
