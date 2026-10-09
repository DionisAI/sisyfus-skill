from __future__ import annotations

import html
import json
import math
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from ..ui_theme import ARENA_THEME_CSS, ARENA_THEME_ID

from ..activity import (
    activity_events_projection_path,
    activity_overlay_html,
    activity_state_path,
    ensure_activity,
)
from .workspace import ResearchWorkspace, atomic_write_json


def _finite(value: Any) -> Any:
    """Browser JSON has no NaN/Infinity: keep such metrics readable as text."""
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if value != value else ("Infinity" if value > 0 else "-Infinity")
    if isinstance(value, dict):
        return {key: _finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(item) for item in value]
    return value


def _json_for_script(value: Any) -> str:
    return json.dumps(
        _finite(value), ensure_ascii=False, sort_keys=True, default=str, allow_nan=False
    ).replace("</", "<\\/")


# Research workspace Observatory: a quiet, light workbench whose centre is the
# claim dependency graph (layered DAG, rectangular claim cards, text statuses),
# with a contextual inspector and a calm event rail. Every visual is a
# projection of persisted facts; replay frames are deterministic re-reductions
# of the event prefix — presentation only, never invention.
_TEMPLATE = """<!doctype html>
<html lang="zh-CN" data-sisyfus-theme="__SISYFUS_THEME_ID__">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="sisyfus-legacy-shell" content="Sisyfus Research Observatory · Arena" />
<meta name="sisyfus-legacy-title" content="Sisyfus Arena" />
<title>__TOPIC__ · Sisyfus 研究工作台</title>
<style>
__SISYFUS_THEME__

/* ---------- header ---------- */
.tally { display:inline-flex; flex-wrap:wrap; gap:2px 12px; }
#runState:empty { display:none; }

/* ---------- graph workspace ---------- */
.arena-wrap { min-height:var(--stage-height); }
.graph-head { display:flex; align-items:center; flex-wrap:wrap; gap:10px 16px; padding:12px 20px 11px;
  border-bottom:1px solid var(--line); background:var(--paper); }
.graph-heading { flex:1 1 220px; min-width:0; }
.graph-title { margin:0; font:500 15px/1.4 var(--font-serif); color:var(--ink); }
.graph-sub { margin-top:1px; font-size:12.5px; color:var(--muted); }
.graph-tools { display:flex; align-items:center; flex-wrap:wrap; gap:4px; }
.tool { height:30px; min-width:32px; padding:0 9px; border:1px solid var(--line); border-radius:8px;
  background:var(--surface); color:var(--ink-2); font-size:13px; line-height:1; }
.tool:hover { border-color:var(--line-strong); background:var(--surface-hover); color:var(--ink); }
.tool.summary { margin-right:8px; color:var(--accent-ink); border-color:var(--accent-line); background:var(--accent-soft); }
.zoom-read { min-width:46px; text-align:center; font-size:12px; color:var(--muted); font-variant-numeric:tabular-nums; }
.graph-note { display:grid; gap:4px; padding:9px 20px 10px; font-size:13px; line-height:1.65; color:var(--ink-2);
  background:var(--paper-raised); border-bottom:1px solid var(--line); }
.graph-note p { margin:0; }
.graph-note .unc-label { margin-right:6px; font-weight:600; color:var(--warn); }
.chip-btn { display:inline-flex; align-items:center; gap:6px; max-width:100%; margin:2px 6px 2px 0; padding:2px 4px 2px 9px;
  border:1px solid var(--line); border-radius:999px; background:var(--surface); color:var(--ink-2);
  font-size:12.5px; line-height:1.5; text-align:left; }
.chip-btn:hover { border-color:var(--line-strong); color:var(--ink); }
.chip-btn .mono { color:var(--muted); }
.chip-btn .status,.chip-btn .tag { height:19px; font-size:11.5px; }
.graph-viewport { position:relative; flex:1 1 0; min-height:300px; overflow:auto; cursor:grab;
  background-color:var(--paper);
  background-image:radial-gradient(circle, var(--line) 1px, transparent 1.3px); background-size:22px 22px; }
.graph-viewport.panning { cursor:grabbing; user-select:none; }
.graph-viewport:focus-visible { outline-offset:-3px; }
.graph-canvas { display:flex; min-width:100%; min-height:100%; }
#arena { display:block; flex:0 0 auto; margin:auto; overflow:visible; }
.graph-empty { position:absolute; inset:0; display:grid; place-items:center; padding:24px;
  color:var(--muted); font-size:14px; text-align:center; }
.graph-empty.error { color:var(--bad); line-height:1.7; }
.graph-legend { display:flex; flex-wrap:wrap; align-items:center; gap:6px 16px; padding:8px 20px 10px;
  font-size:12px; color:var(--muted); border-top:1px solid var(--line); background:var(--paper); }
.graph-legend .lg { display:inline-flex; flex-wrap:wrap; align-items:center; gap:5px; }
.graph-legend .status { height:20px; font-size:11.5px; }
.endboard { display:none !important; }

/* edges: direction = prerequisite → dependent claim */
.edge { fill:none; stroke:var(--edge); stroke-width:1.5; marker-end:url(#arrowHead); transition:opacity .2s, stroke .2s; }
.edge.lit { stroke:var(--edge-strong); }
.edge.hot { stroke:var(--accent); stroke-width:1.8; stroke-dasharray:6 5; marker-end:url(#arrowHeadAccent); }
.edge.focus { stroke:var(--accent); stroke-width:2.2; stroke-dasharray:none; marker-end:url(#arrowHeadAccent); }
.edge.dim { opacity:.25; }
#arrowHead path { fill:var(--edge-strong); }
#arrowHeadAccent path { fill:var(--accent); }

/* claim cards */
.claim-node { cursor:pointer; outline:none; }
.claim-node .node-shadow { fill:rgba(71,54,34,.06); }
.claim-node .node-box { fill:var(--surface); stroke:var(--line-strong); stroke-width:1; transition:stroke .15s; }
.claim-node:hover .node-box { stroke:var(--edge-strong); }
.claim-node .node-stripe { fill:var(--open); }
.claim-node .node-idx { font:600 11.5px var(--font-mono); fill:var(--muted); }
.claim-node .node-label { font:600 14px var(--font-sans); fill:var(--ink); }
.claim-node .node-stmt { font:400 12.5px var(--font-sans); fill:var(--muted); }
.claim-node .node-meta { font:400 12px var(--font-sans); fill:var(--muted); }
.claim-node .node-meta .warn { fill:var(--warn); font-weight:600; }
.claim-node .pill-bg { fill:var(--open-soft); }
.claim-node .pill-text { font:600 11.5px var(--font-sans); fill:var(--open); }
.claim-node.st-SUPPORTED .node-stripe,.claim-node.st-SUPPORTED .pill-text { fill:var(--ok); }
.claim-node.st-SUPPORTED .pill-bg { fill:var(--ok-soft); }
.claim-node.st-SUPPORTED .node-box { stroke:var(--ok-line); }
.claim-node.st-REFUTED .node-stripe,.claim-node.st-REFUTED .pill-text { fill:var(--bad); }
.claim-node.st-REFUTED .pill-bg { fill:var(--bad-soft); }
.claim-node.st-REFUTED .node-box { stroke:var(--bad-line); }
.claim-node.st-INCONCLUSIVE .node-stripe,.claim-node.st-INCONCLUSIVE .pill-text { fill:var(--warn); }
.claim-node.st-INCONCLUSIVE .pill-bg { fill:var(--warn-soft); }
.claim-node.st-INCONCLUSIVE .node-box { stroke:var(--warn-line); }
.claim-node.st-INVALIDATED .node-stripe,.claim-node.st-INVALIDATED .pill-text { fill:var(--void); }
.claim-node.st-INVALIDATED .pill-bg { fill:var(--void-soft); }
.claim-node.st-INVALIDATED .node-box { fill:#faf9fb; }
.claim-node.st-INVALIDATED .node-label { fill:var(--ink-2); }
.claim-node.optional .node-box { stroke-dasharray:5 4; }
.claim-node.untouched .node-box { fill:var(--paper-raised); }
.claim-node .node-ring { fill:none; stroke:transparent; stroke-width:1.5; }
.claim-node.target .node-ring { stroke:var(--accent); stroke-dasharray:4 4; }
.claim-node .target-tag { font:600 11.5px var(--font-sans); fill:var(--accent-ink); }
.claim-node.selected .node-box { stroke:var(--accent); stroke-width:2; }
.claim-node .node-focus { fill:none; stroke:transparent; stroke-width:2.5; }
.claim-node:focus-visible .node-focus { stroke:var(--focus); }

/* ---------- side column: inspector, claims, waits, event rail ---------- */
.inspector { padding:16px 20px 18px; border-bottom:1px solid var(--line); }
.inspector.on { background:var(--surface); }
.insp-kicker { margin:0 0 6px; font-size:12px; font-weight:600; color:var(--muted); }
.insp-empty { margin:0; font-size:13px; line-height:1.7; color:var(--muted); }
.insp-head { display:flex; align-items:flex-start; gap:10px; }
.insp-idx { flex:0 0 auto; margin-top:5px; font-size:12px; color:var(--muted); }
.insp-title { flex:1; min-width:0; margin:0; font:500 17px/1.5 var(--font-serif); color:var(--ink); overflow-wrap:anywhere; }
.insp-close { flex:0 0 auto; width:30px; height:30px; border:1px solid transparent; border-radius:7px;
  background:transparent; color:var(--muted); font-size:14px; }
.insp-close:hover { border-color:var(--line); color:var(--ink); }
.insp-tags { display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin-top:10px; }
.tag { display:inline-flex; align-items:center; height:22px; padding:0 8px; border:1px solid var(--line); border-radius:999px;
  background:var(--surface); color:var(--ink-2); font-size:12px; white-space:nowrap; }
.tag.dashed { border-style:dashed; }
.tag.crit { color:var(--bad); border-color:#e8c4ba; }
.tag.warn { color:var(--warn); border-color:#e8d4a4; background:var(--warn-soft); }
.insp-why { display:grid; gap:4px; margin:12px 0 0; padding:10px 12px; list-style:none; border:1px solid var(--line);
  border-radius:8px; background:var(--paper-raised); font-size:13px; line-height:1.7; color:var(--ink-2); }
.insp-sec { margin-top:16px; }
.insp-sec h3 { display:flex; align-items:baseline; gap:6px; margin:0 0 6px; font-size:12px; font-weight:600; color:var(--muted); }
.insp-sec h3 .n { font-weight:400; color:var(--muted); }
.insp-text { margin:0; font-size:14px; line-height:1.8; color:var(--ink); overflow-wrap:anywhere; }
.insp-conc { margin:0; padding-left:10px; border-left:2px solid var(--accent); font-size:14px; line-height:1.75; color:var(--ink); overflow-wrap:anywhere; }
.insp-id { margin-top:6px; font-size:11.5px; color:var(--muted); overflow-wrap:anywhere; }
.insp-list { display:grid; gap:6px; margin:0; padding:0; list-style:none; }
.insp-list li { padding:8px 10px; border:1px solid var(--line); border-radius:8px; background:var(--surface); font-size:13px; line-height:1.6; }
.insp-row { display:flex; align-items:flex-start; justify-content:space-between; gap:8px; }
.insp-row > span:first-child { min-width:0; overflow-wrap:anywhere; }
.insp-sub { margin-top:3px; font-size:12px; color:var(--muted); overflow-wrap:anywhere; }
.insp-note { margin:14px 0 0; font-size:12.5px; color:var(--warn); }
.insp-more { margin-top:4px; font-size:12px; color:var(--muted); }
#quest { display:grid; gap:2px; padding:0 10px 8px; }
.q-row { display:grid; gap:3px; width:100%; padding:9px 10px; border:1px solid transparent; border-radius:8px;
  background:transparent; color:var(--ink); text-align:left; }
.q-row:hover { border-color:var(--line); background:var(--surface); }
.q-row.selected { border-color:var(--accent); background:var(--surface); }
.q-top { display:flex; align-items:center; gap:8px; min-width:0; }
.q-idx { flex:0 0 auto; font-size:11.5px; color:var(--muted); }
.q-label { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:13.5px; font-weight:600; }
.q-sub { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; overflow-wrap:anywhere;
  font-size:12.5px; line-height:1.65; color:var(--muted); }
.q-tags { display:flex; flex-wrap:wrap; gap:6px; }
.q-tags .tag { height:20px; font-size:11.5px; }
#waitingList { padding-bottom:6px; }
#feed { padding:0 0 16px; }
.feed-row[data-seq] { cursor:pointer; }
.feed-row[data-seq]:hover { background:var(--surface); }
.feed-row .glyph { flex:0 0 12px; text-align:center; color:var(--faint); }
.feed-row .feed-text { min-width:0; overflow-wrap:anywhere; }
.feed-row.pass { border-left-color:var(--ok); } .feed-row.pass .glyph { color:var(--ok); }
.feed-row.fail { border-left-color:var(--bad); } .feed-row.fail .glyph { color:var(--bad); }
.feed-row.miss { border-left-color:var(--void); } .feed-row.miss .glyph { color:var(--void); }
.feed-row.soft { border-left-color:var(--warn); } .feed-row.soft .glyph { color:var(--warn); }
.feed-row.loot { border-left-color:var(--accent); } .feed-row.loot .glyph { color:var(--accent); }
.feed-row.info { border-left-color:transparent; }

/* ---------- replay deck ---------- */
.timeline input[type=range] { position:absolute; inset:0; width:100%; margin:0; opacity:0; cursor:pointer; z-index:3; }
.timeline:focus-within .tl-cursor { box-shadow:0 0 0 3px var(--accent-soft), 0 0 0 5px var(--focus); }
.tl-mark { position:absolute; top:9px; width:2px; height:10px; border-radius:1px; transform:translateX(-50%);
  background:var(--line-strong); z-index:1; }
.tl-mark.pass { background:var(--ok); } .tl-mark.fail { background:var(--bad); top:8px; height:12px; }
.tl-mark.miss { background:var(--void); } .tl-mark.soft { background:var(--warn); }
.tl-mark.loot { background:var(--accent); } .tl-mark.flag { background:var(--ink); top:7px; height:14px; }

/* ---------- detail tabs (audit layer) ---------- */
.view { display:none; padding:20px 24px 32px; } .view.active { display:block; }
.grid { display:grid; grid-template-columns:repeat(12,minmax(0,1fr)); gap:16px; max-width:1240px; }
.card { background:var(--surface); border:1px solid var(--line); border-radius:var(--radius); }
.card-pad { padding:18px 20px; }
.span-4{grid-column:span 4} .span-8{grid-column:span 8} .span-12{grid-column:span 12}
.section-title { display:flex; justify-content:space-between; align-items:baseline; gap:10px; margin-bottom:12px; }
.section-title h2 { margin:0; font:500 15px/1.4 var(--font-serif); color:var(--ink); }
.badge { display:inline-flex; align-items:center; gap:6px; padding:2px 9px; border:1px solid var(--line); border-radius:999px;
  font-size:12px; color:var(--muted); }
.list { display:grid; gap:8px; }
.item { padding:11px 13px; border:1px solid var(--line); border-radius:8px; background:var(--paper-raised); }
.item-head { display:flex; justify-content:space-between; align-items:flex-start; gap:10px; }
.item-head > div { min-width:0; }
.item-title { font-size:13.5px; font-weight:600; overflow-wrap:anywhere; }
.item-meta { margin-top:3px; font-size:12px; color:var(--muted); overflow-wrap:anywhere; }
.tiny { font-size:12px; color:var(--muted); }
table { width:100%; border-collapse:collapse; font-size:12.5px; }
th,td { padding:8px 10px; text-align:left; vertical-align:top; border-bottom:1px solid var(--line); }
th { position:sticky; top:0; background:var(--surface); color:var(--muted); font-weight:600; }
.table-wrap { overflow:auto; max-height:560px; }
.goal-tree { display:grid; gap:8px; }
.goal-node { padding:9px 12px; border:1px solid var(--line); border-left:3px solid var(--line-strong); border-radius:8px; background:var(--paper-raised); }
.goal-node.pass { border-left-color:var(--ok); } .goal-node.fail { border-left-color:var(--bad); } .goal-node.open { border-left-color:var(--warn); }
.indent-1{margin-left:22px} .indent-2{margin-left:44px} .indent-3{margin-left:66px}
.event-row { display:grid; grid-template-columns:52px 165px 110px 1fr; gap:10px; padding:8px 0; border-bottom:1px solid var(--line); }
.event-data { white-space:pre-wrap; word-break:break-word; color:var(--muted); }
.empty { padding:24px; text-align:center; color:var(--muted); border:1px dashed var(--line-strong); border-radius:8px; }
.footer { max-width:1100px; padding:10px 24px 22px; font-size:12px; line-height:1.75; color:var(--muted); }
.ev-metrics { display:flex; flex-wrap:wrap; gap:5px 6px; margin-top:7px; }
.ev-metrics .m { padding:1px 7px; border:1px solid var(--line); border-radius:6px; background:var(--paper-raised);
  font-family:var(--font-mono); font-size:11.5px; color:var(--ink-2); overflow-wrap:anywhere; }
.ev-art { margin-top:6px; font-size:12px; color:var(--muted); overflow-wrap:anywhere; }
.ev-art a { color:var(--accent); }
.ev-filter { display:flex; flex-wrap:wrap; gap:10px; margin-bottom:10px; }
.ev-filter select,.ev-filter input { padding:6px 10px; border:1px solid var(--line); border-radius:8px; background:var(--surface);
  color:var(--ink); font-size:13px; }
.ev-filter input { flex:1; min-width:180px; }
.ev-details { border-bottom:1px solid var(--line); }
.ev-details summary { display:grid; grid-template-columns:52px 210px 130px 1fr; gap:10px; align-items:baseline;
  padding:8px 6px; list-style:none; cursor:pointer; }
.ev-details summary::-webkit-details-marker { display:none; }
.ev-details summary:hover,.ev-details[open] summary { background:var(--paper-raised); }
.ev-type { font-size:12px; font-weight:600; overflow-wrap:anywhere; }
.ev-type.pass{color:var(--ok)} .ev-type.fail{color:var(--bad)} .ev-type.loot{color:var(--accent-ink)}
.ev-type.miss{color:var(--void)} .ev-type.soft{color:var(--warn)} .ev-type.info{color:var(--ink-2)}
.ev-sum { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:12.5px; color:var(--muted); }
.ev-json { margin:0; padding:8px 12px 12px 68px; white-space:pre-wrap; word-break:break-word; font-size:11.5px; color:var(--ink-2); }

/* ---------- report (conclusion-first, printable) ---------- */
.rpt { display:grid; gap:16px; max-width:880px; margin:0 auto; }
.rpt-kicker { font-size:12px; color:var(--muted); }
.rpt-title { margin:4px 0 2px; font:400 26px/1.35 var(--font-serif); color:var(--ink); }
.rpt-topic { font-size:14px; line-height:1.75; color:var(--ink-2); overflow-wrap:anywhere; }
.rpt-note { margin:10px 0 0; font-size:13px; line-height:1.7; color:var(--muted); }
.rpt-answer { margin-top:14px; padding:12px 16px; border-left:3px solid var(--accent); background:var(--paper-raised);
  font-size:15px; line-height:1.8; overflow-wrap:anywhere; }
.rpt-facts { display:flex; flex-wrap:wrap; gap:4px 18px; margin-top:14px; font-size:12.5px; color:var(--muted); }
.rpt-facts b { color:var(--ink); font-weight:600; font-variant-numeric:tabular-nums; }
.rpt-claims { display:grid; gap:8px; }
.rpt-claim { display:grid; grid-template-columns:auto minmax(0,1fr) auto; gap:4px 10px; align-items:baseline;
  padding:10px 12px; border:1px solid var(--line); border-radius:8px; background:var(--paper-raised); }
.rpt-claim .rpt-conc { grid-column:2 / -1; font-size:13px; line-height:1.7; color:var(--muted); overflow-wrap:anywhere; }
.rpt-mark { color:var(--muted); font-size:12px; }
.rpt-cblock { margin-bottom:10px; padding:12px 14px; border:1px solid var(--line); border-radius:8px; background:var(--paper-raised); }
.rpt-chead { display:flex; flex-wrap:wrap; align-items:baseline; gap:8px; font-size:14px; }
.rpt-chead .status { margin-left:auto; }
.rpt-stmt { margin:6px 0 9px; font-size:13px; line-height:1.75; color:var(--muted); overflow-wrap:anywhere; }
.rpt-conc-line { margin:4px 0 8px; font-size:13.5px; line-height:1.7; color:var(--ink); }
.rpt-ev { display:flex; flex-wrap:wrap; align-items:baseline; gap:8px 10px; padding:8px 0; border-top:1px solid var(--line); }
.rpt-ev .ev-metrics,.rpt-ev .ev-art { margin-top:0; }
.rpt-do { counter-reset:step; display:grid; gap:8px; }
.rpt-step { position:relative; padding:10px 13px 10px 40px; border:1px solid var(--line); border-radius:8px;
  background:var(--paper-raised); font-size:13.5px; line-height:1.7; overflow-wrap:anywhere; }
.rpt-step::before { counter-increment:step; content:counter(step); position:absolute; left:15px; top:10px;
  font-weight:600; color:var(--ok); }
.rpt-dont .rpt-step::before { content:'✕'; color:var(--bad); }
.rpt-fold > summary { cursor:pointer; list-style:none; }
.rpt-fold > summary::-webkit-details-marker { display:none; }
.rpt-fold > summary::after { content:'展开'; font-size:12px; color:var(--muted); }
.rpt-fold[open] > summary::after { content:'收起'; }
.rpt-fold[open] > summary { margin-bottom:12px; }
html[lang="en"] .rpt-fold > summary::after { content:'Show'; }
html[lang="en"] .rpt-fold[open] > summary::after { content:'Hide'; }

@media (max-width:960px) {
  .arena-wrap { min-height:0; }
  .graph-viewport { flex:none; height:min(64vh, 560px); min-height:320px; }
  .graph-head { padding:10px 14px; }
  .graph-note,.graph-legend { padding-left:14px; padding-right:14px; }
  .inspector { padding:14px 16px 16px; }
  .col-h { padding-left:16px; padding-right:16px; }
  .view { padding:14px 12px 26px; }
  .span-4,.span-8 { grid-column:span 12; }
  .ev-details summary { grid-template-columns:44px 1fr; }
  .ev-sum { grid-column:2; }
  .ev-json { padding-left:12px; }
  .footer { padding:10px 16px 20px; }
}
@media (max-width:540px) {
  .graph-tools { width:100%; }
  .tool.summary { margin-right:auto; }
  .rpt-title { font-size:22px; }
}
@media (prefers-reduced-motion:reduce) {
  .edge,.claim-node .node-box,.meter > i { transition:none; }
}
@media print {
  .topbar,.stage,.deck,.caster,.tabs,.footer,#sf-live-hud { display:none !important; }
  .view { display:none !important; padding:0; }
  #view-report { display:block !important; }
  html,body { background:#fff; }
  .card,.rpt-claim,.rpt-cblock,.rpt-step,.item { background:#fff; border-color:#d8d2c4; }
  .rpt-answer { background:#f7f4ee; }
  .rpt-fold > summary::after { content:''; }
}

/* Reader prose is editorial; machine records stay in disclosures. */
.reader-report { max-width:70ch; margin:12px auto 36px; padding:clamp(12px,3vw,32px); line-height:1.85; overflow-wrap:anywhere; }
.reader-report:lang(zh) { max-width:42em; }
.reader-report h1 { font-size:clamp(24px,3vw,34px); line-height:1.4; margin:12px 0 24px; }
.reader-question { font-weight:600; color:var(--muted); }
.reader-answer { font-size:1.12em; border-left:3px solid var(--accent); padding-left:18px; }
.reader-note,.reader-original { color:var(--muted); font-size:.92em; }
.reader-section { margin-top:36px; }
.reader-section h2 { font-size:1.3em; line-height:1.5; margin-bottom:16px; }
.reader-section h3 { font-size:1.06em; }
.reader-process { padding-left:24px; }
.reader-process li { margin-bottom:24px; padding-left:6px; }
.reader-process p { margin:8px 0; }
.reader-table-wrap { overflow-x:auto; max-width:100%; margin:20px 0; }
.reader-table-wrap table { width:100%; min-width:420px; border-collapse:collapse; font-size:.94em; }
.reader-table-wrap th,.reader-table-wrap td { padding:12px; text-align:left; border-bottom:1px solid var(--line); vertical-align:top; }
.reader-technical summary,#reportAuditSummary > summary { cursor:pointer; padding:12px 0; font-weight:600; }
@media print { .reader-report { max-width:none; padding:0; color:#222; } .reader-table-wrap { overflow:visible; } .reader-table-wrap table { min-width:0; } .reader-section h2 { break-after:avoid; } .reader-table-wrap tr { break-inside:avoid; } }
</style>
</head>
<body data-sisyfus-shell="broadcast">
<header class="topbar">
  <div class="brand"><span class="brand-mark" aria-hidden="true">✳</span><span data-i18n="brand">Sisyfus 研究工作台</span></div>
  <div class="headline matchinfo">
    <h1 id="topic"></h1>
    <div class="sub">
      <span id="runState" class="status"></span>
      <span class="tally">
        <span><b id="scoreV">0</b> <span data-i18n="verified">已支持</span></span>
        <span><b id="scoreR">0</b> <span data-i18n="refuted">已证伪</span></span>
        <span><b id="scoreU">0</b> <span data-i18n="inconclusive_n">未定</span></span>
        <span><b id="scoreO">0</b> <span data-i18n="open_n">待研究</span></span>
        <span id="scoreXWrap" hidden><b id="scoreX">0</b> <span data-i18n="invalidated_n">已失效</span></span>
      </span>
      <span id="matchMeta"></span>
      <span id="lootMeta"></span>
    </div>
  </div>
  <div class="budget bars">
    <div class="budget-row"><span id="hpText"></span><span class="meter" aria-hidden="true"><i id="hpFill"></i></span></div>
    <div class="budget-row"><span id="manaText"></span><span class="meter" aria-hidden="true"><i id="manaFill"></i></span></div>
  </div>
  <div class="top-actions">
    <div class="livechip" id="liveChip" role="status"><span class="dot" aria-hidden="true"></span><span id="liveText"></span></div>
    <button class="lang-btn" id="langBtn" type="button" title="切换语言 / switch language">EN</button>
  </div>
</header>

<div class="stage">
  <div class="arena-wrap" id="arenaWrap">
    <div class="graph-head">
      <div class="graph-heading">
        <h2 class="graph-title" data-i18n="graph_title">命题依赖图</h2>
        <div class="graph-sub" id="graphSub"></div>
      </div>
      <div class="graph-tools" role="toolbar" id="graphTools">
        <button class="tool summary" id="endboardBtn" type="button" hidden></button>
        <button class="tool" id="graphZoomOut" type="button" data-i18n-aria="zoom_out">−</button>
        <span class="zoom-read" id="zoomRead" aria-live="polite">100%</span>
        <button class="tool" id="graphZoomIn" type="button" data-i18n-aria="zoom_in">+</button>
        <button class="tool" id="graphFit" type="button" data-i18n="fit" data-i18n-aria="fit_aria">适配</button>
        <button class="tool" id="graphReset" type="button" data-i18n="reset" data-i18n-aria="reset_aria">重置</button>
      </div>
    </div>
    <div class="graph-note" id="uncertainNote" hidden></div>
    <div class="graph-viewport" id="graphViewport" tabindex="0" data-i18n-aria="viewport_aria">
      <div class="graph-canvas">
        <svg id="arena" xmlns="http://www.w3.org/2000/svg" width="320" height="200" viewBox="0 0 320 200" role="group">
          <defs>
            <marker id="arrowHead" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto"><path d="M0 0 L10 5 L0 10 z"/></marker>
            <marker id="arrowHeadAccent" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto"><path d="M0 0 L10 5 L0 10 z"/></marker>
          </defs>
          <g id="edges"></g>
          <g id="bosses"></g>
        </svg>
      </div>
      <div class="graph-empty" id="graphEmpty" hidden></div>
    </div>
    <div class="graph-legend" id="graphLegend"></div>
    <div class="endboard" id="endboard" hidden></div>
  </div>
  <aside class="rightcol">
    <section class="inspector" id="unitCard"></section>
    <div class="col-h"><span data-i18n="claims_panel">命题</span><span id="questCount"></span></div>
    <div id="quest"></div>
    <div class="col-h" id="respawnSec"><span data-i18n="respawn">等待中的实验</span><span id="nextWake" class="mono"></span></div>
    <div id="waitingList"></div>
    <div class="col-h"><span data-i18n="killfeed">事件</span><span id="feedCount"></span></div>
    <div id="feed"></div>
  </aside>
</div>

<div class="deck">
  <button id="playBtn" type="button" data-i18n-aria="play">▶</button>
  <div class="timeline" id="timelineBox">
    <div class="tl-track"></div><div class="tl-fill" id="tlFill"></div>
    <div id="tlMarks"></div><div class="tl-cursor" id="tlCursor"></div>
    <div class="tl-times mono"><span id="tlStart"></span><span id="tlEnd"></span></div>
    <input type="range" id="replaySlider" min="0" max="0" value="0" step="1" aria-label="replay timeline" data-i18n-aria="replay_aria"/>
  </div>
  <select id="speedSel" data-i18n-aria="speed"><option value="0.5">0.5×</option><option value="1">1×</option><option value="2" selected>2×</option><option value="4">4×</option></select>
  <button id="liveBtn" type="button" data-i18n="live_btn">最新</button>
  <div class="stamp mono" id="frameLabel"></div>
</div>
<div class="caster"><span class="tag" data-i18n="caster">最新动态</span><div id="casterLine"></div></div>

<nav class="tabs">
  <button class="tab active" type="button" data-view="none" data-i18n="tab_arena">图谱</button>
  <button class="tab" type="button" data-view="report" data-i18n="tab_report">报告</button>
  <button class="tab" type="button" data-view="goals" data-i18n="tab_goals">目标图</button>
  <button class="tab" type="button" data-view="execution" data-i18n="tab_execution">执行图</button>
  <button class="tab" type="button" data-view="audit" data-i18n="tab_audit">审计</button>
  <button class="tab" type="button" data-view="events" data-i18n="tab_events">事件流</button>
</nav>
<section id="view-report" class="view"><div class="rpt" id="reportBody"></div></section>
<section id="view-goals" class="view"><div class="grid"><div class="card span-8 card-pad"><div class="section-title"><h2 data-i18n="sec_goal">目标图</h2><span class="badge" id="goalRoot"></span></div><div class="goal-tree" id="goalTree"></div></div><div class="card span-4 card-pad"><div class="section-title"><h2 data-i18n="sec_cov">判定覆盖</h2></div><div id="verifierCoverage"></div></div></div></section>
<section id="view-execution" class="view"><div class="grid"><div class="card span-12 card-pad"><div class="section-title"><h2 data-i18n="sec_dag">状态图与实验</h2><span class="badge mono" id="currentState"></span></div><div class="list" id="executionList"></div></div></div></section>
<section id="view-audit" class="view"><div class="grid"><div class="card span-12 card-pad"><div class="section-title"><h2 data-i18n="sec_contracts">判定合约</h2></div><div class="table-wrap"><table><thead><tr><th>ID</th><th>Claim</th><th>Version</th><th>Repetition</th><th>Rules</th></tr></thead><tbody id="contractRows"></tbody></table></div></div><div class="card span-12 card-pad"><div class="section-title"><h2 data-i18n="sec_attempts">尝试与判定</h2></div><div class="table-wrap"><table><thead><tr><th>Attempt</th><th>Experiment</th><th>Context</th><th>Status</th><th>Verdict</th><th>Reason</th><th>State</th></tr></thead><tbody id="attemptRows"></tbody></table></div></div><div class="card span-12 card-pad"><div class="section-title"><h2 data-i18n="sec_evidence">证据</h2></div><div class="list" id="evidenceList"></div></div><div class="card span-12 card-pad"><div class="section-title"><h2 data-i18n="sec_lessons">经验</h2></div><div class="list" id="lessonList"></div></div></div></section>
<section id="view-events" class="view"><div class="card card-pad"><div class="section-title"><h2 data-i18n="sec_events">只增事件流</h2><span class="badge mono" id="eventHead"></span></div><div class="ev-filter"><select id="evTypeFilter"></select><input id="evTextFilter" type="search" data-i18n-ph="ev_search" placeholder="过滤事件 JSON…"/></div><div id="eventList"></div></div></section>
<div class="footer" id="footerLine"></div>
<div class="footer" id="legendLine" style="padding-top:0"></div>

<script id="sisyfus-data" type="application/json">__PAYLOAD__</script>
<script>
/* Python's json.dumps emits bare NaN / Infinity for non-finite metrics, which
   JSON.parse rejects. Retry once with those tokens (outside string literals)
   quoted, so one odd metric never blanks the whole workbench. */
function parseLenient(text) {
  try { return JSON.parse(text); } catch (_) {
    return JSON.parse(String(text).replace(/"(?:[^"\\\\]|\\\\.)*"|-?\\bInfinity\\b|\\bNaN\\b/g, m => m[0] === '"' ? m : `"${m}"`));
  }
}
let DATA, BOOT_ERROR = null;
try { DATA = parseLenient(document.getElementById('sisyfus-data').textContent); }
catch (error) { BOOT_ERROR = error; DATA = { snapshot: {}, events: [], frames: [], translations: {} }; }
let S = DATA.snapshot || {}, E = DATA.events || [], FRAMES = DATA.frames || [];
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const GLYPH = { SUPPORTED:'✓', PASS:'✓', SOLVED:'✓', PROMOTED:'✓', REFUTED:'✕', FAIL:'✕', FAILED:'✕', REVOKED:'✕',
  INCONCLUSIVE:'?', OPEN:'○', INVALIDATED:'⊘', INVALID:'⊘', ERROR:'!' };
function stLabel(s) { return L['st_' + s] || s || 'MISSING'; }
const status = s => `<span class="status ${esc(s)}" title="${esc(s || 'MISSING')}">${GLYPH[s] ? `<span class="g" aria-hidden="true">${GLYPH[s]}</span>` : ''}${esc(stLabel(s || 'MISSING'))}</span>`;
const REDUCED = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
const NARROW = window.matchMedia ? window.matchMedia('(max-width: 960px)') : { matches: false };

/* ================= i18n ================= */
const LOCALES = {
  zh: {
    brand:'Sisyfus 研究工作台',
    verified:'已支持', refuted:'已证伪', inconclusive_n:'未定', open_n:'待研究', invalidated_n:'已失效',
    killfeed:'事件', claims_panel:'命题', respawn:'等待中的实验', inspector:'命题详情',
    live_btn:'最新', caster:'最新动态', tab_arena:'图谱', tab_report:'报告', tab_goals:'目标图', tab_execution:'执行图', tab_audit:'审计', tab_events:'事件流',
    sec_goal:'目标图', sec_cov:'判定覆盖', sec_dag:'状态图与实验', sec_contracts:'判定合约', sec_attempts:'尝试与判定',
    sec_evidence:'证据', sec_lessons:'经验', sec_events:'只增事件流',
    footer:'执行状态与判定由 task.json 和 events.jsonl 确定性生成；回放帧可用 sisyfus research replay 校验。报告正文是绑定当前证据版本的解释，不是新的测量或判定。INVALID / ERROR 表示测量失败；临时通过不等于已支持。',
    legend_line:'已支持（SUPPORTED）：满足预注册门槛 · 已证伪（REFUTED）：同样是确定的结论 · 未定（INCONCLUSIVE）：仍存在的不确定性 · 已失效（INVALIDATED）：前提被推翻 · 研究已完成（SOLVED）表示研究流程结束，不代表盈利被证明 · 预算为尝试次数与成本单位',
    live:'最新', replay:'回放中', ended:'已结束',
    budget_attempts:'剩余尝试', budget_cost:'剩余成本', unlimited:'不限',
    events_n: n => `${n} 个事件`, claims_n: n => `${n} 个命题`,
    awaiting_evidence:'等待证据', next_wake:'下次唤醒', no_waiting:'没有等待中的实验',
    wait_not_before: ts => `不早于 ${ts}`, wait_until: c => `等待 ${c} 的证据`,
    required:'必需', optional:'可选', critical:'关键',
    evidence_n: n => `证据 ${n}`, provisional_n: n => `临时通过 ${n}`, prov_short: n => `临时通过 ${n}，未达门槛`, cited_n: n => `被引用 ×${n}`,
    uc_contracts:'判定合约', uc_engagements:'实验', uc_evidence:'证据', uc_statement:'陈述', uc_conclusion:'结论',
    uc_depends:'依赖的前提', uc_dependents:'被这些命题依赖', uc_snapshot_note:'回放中：合约、实验与证据取自最新快照，可能晚于当前帧。',
    uc_gate: (p, c) => `需 ${p ?? '—'} 次通过 / ${c ?? '—'} 个独立环境`, uc_more: n => `另有 ${n} 项…`,
    close:'关闭', inspector_empty:'在图中选择一个命题（点击，或用 Tab 聚焦后按 Enter / 空格），这里会显示它的陈述、判定合约、实验与证据。',
    cov_full:'所有必需命题都有判定合约', cov_missing:'以下必需命题缺少判定合约', empty_evidence:'尚无证据', empty_lessons:'尚未记录经验', root:'根节点',
    graph_title:'命题依赖图', graph_sub: (n, l) => `${n} 个命题 · ${l} 层依赖`, graph_hint_large:'图较大：拖动或滚动平移，「适配」查看全貌',
    graph_empty:'尚无命题。任务规格锁定后，命题会出现在这里。',
    zoom_in:'放大', zoom_out:'缩小', fit:'适配', fit_aria:'适配全图', reset:'重置', reset_aria:'重置视图',
    viewport_aria:'命题依赖图视口：可滚动或拖动平移，Ctrl / ⌘ + 滚轮缩放',
    legend_optional:'虚线框 = 可选命题', legend_arrow:'箭头：前提 → 依赖它的命题',
    summary_btn:'研究摘要', target_tag:'当前实验目标',
    solved_note:'研究已完成：必需命题均已按预注册合约得到判定。这表示研究流程结束，不代表收益或盈利已被证明。',
    final_note: st => `研究已结束（${st}）。未判定的命题保持未定，不能视为已支持。`,
    uncertain_lead:'仍有不确定：',
    st_SUPPORTED:'已支持', st_REFUTED:'已证伪', st_INCONCLUSIVE:'未定', st_OPEN:'待研究', st_INVALIDATED:'已失效',
    st_PASS:'通过', st_FAIL:'未通过', st_INVALID:'无效', st_ERROR:'错误', st_MISSING:'缺失',
    st_SOLVED:'研究已完成', st_ACTIVE:'进行中', st_PAUSED:'已暂停', st_BUDGET_EXHAUSTED:'预算耗尽', st_FAILED:'异常终止',
    st_BLOCKED:'受阻', st_CONTESTED:'存在争议', st_PROMOTED:'已晋升', st_REVOKED:'已撤销', st_CANDIDATE:'候选',
    why_SUPPORTED:'已满足预注册合约的通过门槛（包括重复与独立环境要求）。',
    why_REFUTED:'命中了预注册的 FAIL 规则：这是被确认的否定结论，同样是有价值的知识。',
    why_INCONCLUSIVE:'实验有效，但证据不足以支持或否定——这是仍然存在的不确定性。',
    why_OPEN:'尚未得到合约判定。',
    why_INVALIDATED:'它依赖的前提被推翻，原有结论已失效。',
    why_provisional: n => `已有 ${n} 次临时通过，但重复 / 独立环境门槛尚未满足——临时通过不等于已支持。`,
    why_optional:'可选命题：不阻断研究完成，但它的结论需要单独看待。',
    n_run_created: t => ['研究开始', `研究开始：${t}`],
    n_spec_locked: () => ['规格已锁定', '任务规格与判定阈值已预注册并锁定，之后不可更改。'],
    n_contract: id => [`登记判定合约 ${id}`, `判定合约 ${id} 已登记。`],
    n_proposed: (title, claim) => [`提出实验：${title}`, `提出实验「${title}」，针对命题 ${claim}。`],
    n_admitted: (e, claim) => [`实验准入：${e}`, `实验 ${e} 通过准入，针对命题 ${claim}。`],
    n_backlogged: (e, r) => [`实验暂缓：${e}（${r}）`, `实验 ${e} 未获准入：${r || '不符合要求'}。`],
    n_pruned: e => [`实验撤回：${e}`, `实验 ${e} 已撤回。`],
    n_reserved: (e, claim) => [`预留预算：${e}`, `为 ${e}（命题 ${claim}）预留预算。`],
    n_started: e => [`运行中：${e}`, `实验 ${e} 正在运行。`],
    n_observation: () => ['记录观测', '观测已记录，等待按合约判定。'],
    n_wait_fired: e => [`等待结束：${e}`, `等待条件已满足，${e} 继续。`],
    n_wait_expired: (e, p) => [`等待超时：${e}`, `${e} 等待超时（${p}）。`],
    n_pass_promoted: c => [`命题已支持：${c}`, `判定 PASS 且满足门槛——命题 ${c} 已支持。`],
    n_pass_provisional: (e, c) => [`临时通过：${c}（未达门槛）`, `${e} 对命题 ${c} 判定 PASS，但重复 / 独立环境门槛尚未满足，命题仍未被支持。`],
    n_fail: (c, rb, r) => [`命题被证伪：${c}${rb ? ` · ${rb} 个下游失效` : ''}`, `判定 FAIL——命题 ${c} 被证伪${rb ? `，${rb} 个下游命题随之失效` : ''}。（${r || ''}）`],
    n_invalid: (e, r) => [`测量无效：${e}`, `判定 INVALID：本次测量无效，不构成对命题的证据。（${r || ''}）`],
    n_error: e => [`执行错误：${e}`, '基础设施或执行错误（ERROR），不计为证据。'],
    n_inconclusive: c => [`未定：${c}`, `判定 INCONCLUSIVE——命题 ${c} 的证据不足以支持或否定。`],
    n_lesson_add: id => [`记录经验候选：${id}`, `记录经验候选「${id}」。`],
    n_lesson_evidence: id => [`经验补充证据：${id}`, `经验 ${id} 新增证据。`],
    n_lesson_promoted: id => [`经验晋升：${id}`, `经验「${id}」通过双实验门槛，晋升到全局知识库。`],
    n_lesson_revoked: id => [`经验撤销：${id}`, `经验 ${id} 被反例推翻，已撤销。`],
    n_paused: () => ['已暂停', '研究已暂停。'], n_resumed: () => ['已继续', '研究继续。'],
    n_run_failed: r => ['运行异常终止', `运行异常终止：${r || ''}`],
    n_final_solved: () => ['研究完成', '研究已完成：必需命题均已判定。完成不代表收益被证明。'],
    n_final_refuted: () => ['目标被否定', '研究结束：目标被证伪，得到了明确的否定答案。'],
    n_final_budget: () => ['预算耗尽', '研究结束：预算耗尽，未判定的命题保持未定。'],
    n_final_other: st => [`研究结束：${st}`, `研究结束：${st}。`],
    n_report: () => ['页面已更新', ''],
    no_events:'尚无事件。',
    eb_kicker:'研究摘要', eb_attempts:'已用尝试', eb_cost:'已用成本', eb_duration:'用时', eb_lessons:'经验', eb_events:'事件',
    obj_label:'目标完成度', epi_label:'证据覆盖',
    meta_tip:'目标完成度 = 目标图的客观完成比例；证据覆盖 = 有证据支撑的命题比例',
    rs_ACTIVE:'进行中', rs_PAUSED:'已暂停', rs_SOLVED:'研究已完成', rs_BUDGET_EXHAUSTED:'预算耗尽',
    rs_FAILED:'异常终止', rs_BLOCKED:'受阻', rs_CONTESTED:'存在争议', rs_REFUTED:'目标被否定', rs_EXHAUSTED:'实验已穷尽',
    st_EXHAUSTED:'实验已穷尽', reconnecting:'连接中断', load_failed:'加载失败',
    boot_error:'研究数据无法读取，页面没有加载出来。请检查本次研究的 events.jsonl 与快照文件，或重新生成报告。',
    ev_all_types:'全部类型', ev_search:'过滤事件 JSON…', artifacts_label:'产物',
    play_all:'从头播放', play:'播放回放', pause:'暂停回放', speed:'回放速度', replay_aria:'回放时间轴', feed_jump:'跳转到该事件',
    eb_dur: (h, m, s) => h ? `${h} 小时 ${m} 分` : `${m} 分 ${s} 秒`,
    rsn_pass_rule_matched:'观测满足预注册的 PASS 规则与全部护栏。',
    rsn_fail_rule_matched:'观测满足预注册的 FAIL 规则。',
    rsn_no_decisive_rule_matched:'实验有效，但 PASS 与 FAIL 规则均未决出。',
    rsn_invalid_rule_matched:'实验命中预注册的无效条件。',
    rsn_guardrail_failed:'实验有效，但触发硬性护栏失败。',
    rsn_precondition_failed:'实验不满足预注册的前置条件。',
    rsn_contradictory_contract:'PASS 与 FAIL 规则同时命中——该观测下判定合约自相矛盾。',
    rsn_execution_timeout:'实验执行超时，不允许对命题做任何推断。',
    rsn_execution_error:'实验执行出错，判为基础设施 / 执行故障。',
    rsn_command_nonzero_exit:'命令以非零码退出，判为基础设施 / 执行故障。',
    rsn_required_artifact_missing:'要求的产物文件缺失。',
    rsn_manual_verdict:'人工判定。',
    rsn_manual_verdict_missing:'人工合约未收到有效的 manual_verdict。',
    tab_report:'报告', sec_takeaways:'命题结论', sec_claim_evidence:'命题与证据', sec_loot_final:'经验结论',
    rpt_no_lessons:'本次研究没有沉淀可执行的经验。', rpt_verdicts:'判定统计', rpt_required_only:'仅必需命题',
    rd_missing:'研究正文尚未提供；技术记录不代表收益结论。', rd_stale:'研究正文与当前证据版本不一致；请查看技术记录。', rd_invalid:'研究正文格式无效；请查看技术记录。', reader_claim:'这对研究问题说明了什么', reader_original:'原文语言：中文', reader_audit:'技术记录与核验', reader_legacy:'旧版摘要（非研究问题的答案）', rpt_answer:'结论', rpt_do:'建议做法', rpt_dont:'应避免', rpt_details:'命题与证据明细',
  },
  en: {
    rd_missing:'Research prose is missing; technical records do not establish returns.', rd_stale:'Research prose does not match the current evidence version.', rd_invalid:'Research prose has an invalid format; consult technical records.', reader_claim:'What this says about the question', reader_original:'Original language: Chinese', reader_audit:'Technical records and verification', reader_legacy:'Legacy summary (not an answer to the research question)',
    brand:'Sisyfus Research Workspace',
    verified:'supported', refuted:'refuted', inconclusive_n:'inconclusive', open_n:'open', invalidated_n:'invalidated',
    killfeed:'Events', claims_panel:'Claims', respawn:'Waiting experiments', inspector:'Claim details',
    live_btn:'Latest', caster:'Latest', tab_arena:'Graph', tab_report:'Report', tab_goals:'Goal Graph', tab_execution:'Execution', tab_audit:'Audit', tab_events:'Events',
    sec_goal:'Goal Graph', sec_cov:'Verifier coverage', sec_dag:'State DAG & experiments', sec_contracts:'Verification contracts', sec_attempts:'Attempts & verdicts',
    sec_evidence:'Evidence', sec_lessons:'Lessons', sec_events:'Append-only event stream',
    footer:'Execution state and verdicts are deterministic projections of task.json + events.jsonl; replay frames are verifiable via sisyfus research replay. Report prose explains the pinned evidence version; it is not a new measurement or verdict. INVALID / ERROR are measurement failures; a provisional pass is not support.',
    legend_line:'Supported: preregistered gate met · Refuted: an equally definite finding · Inconclusive: remaining uncertainty · Invalidated: a prerequisite was overturned · SOLVED means the study completed, not that profit was proven · Budget = attempts and cost units',
    live:'Latest', replay:'Replaying', ended:'Ended',
    budget_attempts:'Attempts left', budget_cost:'Cost left', unlimited:'unlimited',
    events_n: n => `${n} events`, claims_n: n => `${n} claims`,
    awaiting_evidence:'awaiting evidence', next_wake:'next wake', no_waiting:'no waiting experiments',
    wait_not_before: ts => `not before ${ts}`, wait_until: c => `until evidence on ${c}`,
    required:'required', optional:'optional', critical:'critical',
    evidence_n: n => `evidence ${n}`, provisional_n: n => `provisional ×${n}`, prov_short: n => `provisional ×${n} · gate not met`, cited_n: n => `cited ×${n}`,
    uc_contracts:'Verification contracts', uc_engagements:'Experiments', uc_evidence:'Evidence', uc_statement:'Statement', uc_conclusion:'Conclusion',
    uc_depends:'Depends on', uc_dependents:'Required by', uc_snapshot_note:'Replaying: contracts, experiments and evidence come from the latest snapshot and may post-date this frame.',
    uc_gate: (p, c) => `needs ${p ?? '—'} passes / ${c ?? '—'} independent contexts`, uc_more: n => `${n} more…`,
    close:'Close', inspector_empty:'Select a claim in the graph (click, or Tab to it and press Enter / Space) to see its statement, contracts, experiments and evidence.',
    cov_full:'Every required claim has a verifier', cov_missing:'Required claims without a verifier', empty_evidence:'No evidence recorded.', empty_lessons:'No lessons recorded yet.', root:'root',
    graph_title:'Claim dependency graph', graph_sub: (n, l) => `${n} claims · ${l} levels`, graph_hint_large:'Large graph: drag or scroll to pan, Fit for the overview',
    graph_empty:'No claims yet. They appear here once the task specification is locked.',
    zoom_in:'Zoom in', zoom_out:'Zoom out', fit:'Fit', fit_aria:'Fit whole graph', reset:'Reset', reset_aria:'Reset view',
    viewport_aria:'Claim graph viewport: scroll or drag to pan, Ctrl / ⌘ + wheel to zoom',
    legend_optional:'dashed card = optional claim', legend_arrow:'arrow: prerequisite → dependent claim',
    summary_btn:'Study summary', target_tag:'Current experiment target',
    solved_note:'Study complete: every required claim was decided under its preregistered contract. Completion ends the study; it does not prove returns or profit.',
    final_note: st => `The study has ended (${st}). Undecided claims remain undecided and must not be read as supported.`,
    uncertain_lead:'Still uncertain:',
    st_SUPPORTED:'Supported', st_REFUTED:'Refuted', st_INCONCLUSIVE:'Inconclusive', st_OPEN:'Open', st_INVALIDATED:'Invalidated',
    st_PASS:'Pass', st_FAIL:'Fail', st_INVALID:'Invalid', st_ERROR:'Error', st_MISSING:'Missing',
    st_SOLVED:'Study complete', st_ACTIVE:'Active', st_PAUSED:'Paused', st_BUDGET_EXHAUSTED:'Budget exhausted', st_FAILED:'Aborted',
    st_BLOCKED:'Blocked', st_CONTESTED:'Contested', st_PROMOTED:'Promoted', st_REVOKED:'Revoked', st_CANDIDATE:'Candidate',
    why_SUPPORTED:'The preregistered pass gate is met, including repetition and independent-context requirements.',
    why_REFUTED:'A preregistered FAIL rule matched: this is a confirmed negative finding, which is knowledge too.',
    why_INCONCLUSIVE:'The experiment was valid but the evidence neither supports nor refutes the claim — this is remaining uncertainty.',
    why_OPEN:'No contract verdict yet.',
    why_INVALIDATED:'A prerequisite was overturned, so the earlier conclusion no longer holds.',
    why_provisional: n => `${n} provisional pass(es), but the repetition / independent-context gate is not met — a provisional pass is not support.`,
    why_optional:'Optional claim: it does not block study completion, but its result should be read on its own.',
    n_run_created: t => ['Study started', `Study started: ${t}`],
    n_spec_locked: () => ['Specification locked', 'The task specification and verdict thresholds are preregistered and locked.'],
    n_contract: id => [`Contract registered: ${id}`, `Verification contract ${id} registered.`],
    n_proposed: (title, claim) => [`Experiment proposed: ${title}`, `Experiment "${title}" proposed for claim ${claim}.`],
    n_admitted: (e, claim) => [`Experiment admitted: ${e}`, `Experiment ${e} admitted for claim ${claim}.`],
    n_backlogged: (e, r) => [`Experiment deferred: ${e} (${r})`, `Experiment ${e} was not admitted: ${r || 'not compliant'}.`],
    n_pruned: e => [`Experiment withdrawn: ${e}`, `Experiment ${e} was withdrawn.`],
    n_reserved: (e, claim) => [`Budget reserved: ${e}`, `Budget reserved for ${e} (claim ${claim}).`],
    n_started: e => [`Running: ${e}`, `Experiment ${e} is running.`],
    n_observation: () => ['Observation recorded', 'Observation recorded; awaiting the contract verdict.'],
    n_wait_fired: e => [`Wait satisfied: ${e}`, `Wait condition met; ${e} continues.`],
    n_wait_expired: (e, p) => [`Wait expired: ${e}`, `${e} timed out (${p}).`],
    n_pass_promoted: c => [`Claim supported: ${c}`, `Verdict PASS with the gate met — claim ${c} is supported.`],
    n_pass_provisional: (e, c) => [`Provisional pass: ${c} (gate not met)`, `${e} passed for claim ${c}, but the repetition / independent-context gate is not met; the claim is not yet supported.`],
    n_fail: (c, rb, r) => [`Claim refuted: ${c}${rb ? ` · ${rb} downstream invalidated` : ''}`, `Verdict FAIL — claim ${c} is refuted${rb ? `, invalidating ${rb} downstream claims` : ''}. (${r || ''})`],
    n_invalid: (e, r) => [`Invalid measurement: ${e}`, `Verdict INVALID: the measurement is not evidence about the claim. (${r || ''})`],
    n_error: e => [`Execution error: ${e}`, 'Infrastructure or execution error (ERROR); not counted as evidence.'],
    n_inconclusive: c => [`Inconclusive: ${c}`, `Verdict INCONCLUSIVE — the evidence on claim ${c} neither supports nor refutes it.`],
    n_lesson_add: id => [`Lesson candidate: ${id}`, `Lesson candidate "${id}" recorded.`],
    n_lesson_evidence: id => [`Lesson evidence: ${id}`, `Lesson ${id} gained evidence.`],
    n_lesson_promoted: id => [`Lesson promoted: ${id}`, `Lesson "${id}" passed the two-experiment gate and joined the global library.`],
    n_lesson_revoked: id => [`Lesson revoked: ${id}`, `Lesson ${id} was overturned by a counterexample and revoked.`],
    n_paused: () => ['Paused', 'The study is paused.'], n_resumed: () => ['Resumed', 'The study resumed.'],
    n_run_failed: r => ['Run aborted', `Run aborted: ${r || ''}`],
    n_final_solved: () => ['Study complete', 'Study complete: every required claim was decided. Completion does not prove returns.'],
    n_final_refuted: () => ['Goal refuted', 'Study ended: the goal is refuted — a definite negative answer.'],
    n_final_budget: () => ['Budget exhausted', 'Study ended: budget exhausted; undecided claims remain undecided.'],
    n_final_other: st => [`Study ended: ${st}`, `Study ended: ${st}.`],
    n_report: () => ['Page refreshed', ''],
    no_events:'No events yet.',
    eb_kicker:'Study summary', eb_attempts:'Attempts used', eb_cost:'Cost used', eb_duration:'Duration', eb_lessons:'Lessons', eb_events:'Events',
    obj_label:'objective', epi_label:'evidence coverage',
    meta_tip:'objective = completion of the goal graph; evidence coverage = share of claims backed by evidence',
    rs_ACTIVE:'Active', rs_PAUSED:'Paused', rs_SOLVED:'Study complete', rs_BUDGET_EXHAUSTED:'Budget exhausted',
    rs_FAILED:'Aborted', rs_BLOCKED:'Blocked', rs_CONTESTED:'Contested', rs_REFUTED:'Goal refuted', rs_EXHAUSTED:'Experiments exhausted',
    st_EXHAUSTED:'Experiments exhausted', reconnecting:'Reconnecting', load_failed:'Failed to load',
    boot_error:'The research data could not be read, so this page did not load. Check events.jsonl and the snapshot for this run, or regenerate the report.',
    ev_all_types:'all types', ev_search:'filter event JSON…', artifacts_label:'artifacts',
    play_all:'Play from the start', play:'Play replay', pause:'Pause replay', speed:'Replay speed', replay_aria:'Replay timeline', feed_jump:'Jump to this event',
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
    tab_report:'Report', sec_takeaways:'Claim conclusions', sec_claim_evidence:'Claims & evidence', sec_loot_final:'Lesson conclusions',
    rpt_no_lessons:'No actionable lessons were recorded.', rpt_verdicts:'Verdict tally', rpt_required_only:'required claims only',
    rpt_answer:'Answer', rpt_do:'Recommended', rpt_dont:'Avoid', rpt_details:'Claims & evidence detail',
  },
};
let lang = 'zh';
try {
  // canonical key first, legacy bootstrap key as read fallback; only en/zh are honoured
  const saved = [localStorage.getItem('sisyfus_lang'), localStorage.getItem('sisyfus-lang')].find(v => v === 'en' || v === 'zh');
  if (saved) lang = saved;
} catch (_) {}
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
  document.querySelectorAll('[data-i18n-aria]').forEach(el => { const v = t(el.dataset.i18nAria); el.setAttribute('aria-label', v); el.title = v; });
  $('footerLine').textContent = t('footer');
  $('legendLine').textContent = t('legend_line');
  $('langBtn').textContent = lang === 'zh' ? 'EN' : '中文';
  $('topic').textContent = trTopic();
  $('topic').title = trTopic();
  $('matchMeta').title = t('meta_tip');
  $('playBtn').title = `${t('play_all')} (Space)`;
  $('endboardBtn').textContent = t('summary_btn');
  $('arena').setAttribute('aria-label', t('graph_title'));
  renderLegend(); renderGraphSub();
}
function setLang(next) {
  lang = next; L = LOCALES[lang] || LOCALES.zh;
  try { localStorage.setItem('sisyfus_lang', lang); localStorage.setItem('sisyfus-lang', lang); } catch (_) {}
  applyStaticI18n();
  if (BOOT_ERROR) { showBootError(BOOT_ERROR); return; }  /* re-translate the failure only */
  renderDetailTabs(); renderWaiting();
  unitSig = ''; noteSig = '';
  if (FRAMES.length) showIndex(Number($('replaySlider').value), { feedRebuild: true });
  else renderSnapshotOnly();
  renderUnitCard(SELECTED, currentStatuses());
}
function renderLegend() {
  const items = ['SUPPORTED', 'REFUTED', 'INCONCLUSIVE', 'OPEN', 'INVALIDATED'].map(s => status(s)).join('');
  $('graphLegend').innerHTML = `<span class="lg">${items}</span><span class="lg">${esc(t('legend_optional'))}</span><span class="lg">${esc(t('legend_arrow'))}</span>`;
}

/* ================= derived data ================= */
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
function claimNo(id) { return `C${CLAIM_INDEX[id] || '·'}`; }

/* ---------- text measurement for SVG cards (CJK-aware wrapping) ---------- */
function charUnits(ch) {
  if (ch.codePointAt(0) >= 0x2E80) return 1;
  if (ch === ' ') return 0.3;
  if ("ilj.,:;|!()'".includes(ch)) return 0.3;
  if ("mwMW@%&".includes(ch)) return 0.84;
  if (ch >= 'A' && ch <= 'Z') return 0.66;
  return 0.56;
}
function textUnits(s) { let u = 0; for (const ch of String(s)) u += charUnits(ch); return u; }
const NO_LINE_START = '，。、；：！？）》」』〉】,.;:!?)';
function wrapText(text, maxPx, size, maxLines) {
  const max = maxPx / size;
  const tokens = []; let word = '';
  for (const ch of String(text || '')) {
    const cjk = ch.codePointAt(0) >= 0x2E80, space = ch.trim() === '';
    if (cjk || space) { if (word) { tokens.push(word); word = ''; } tokens.push(space ? ' ' : ch); }
    else word += ch;
  }
  if (word) tokens.push(word);
  const lines = []; let cur = '', w = 0;
  const flush = () => { lines.push(cur.trim()); cur = ''; w = 0; };
  for (const tok of tokens) {
    if (tok === ' ') { if (cur) { cur += ' '; w += 0.3; } continue; }
    const tw = textUnits(tok);
    if (w + tw <= max) { cur += tok; w += tw; continue; }
    if (cur && tok.length === 1 && NO_LINE_START.includes(tok)) { cur += tok; w += tw; continue; }
    if (cur.trim()) flush(); else { cur = ''; w = 0; }
    if (tw <= max) { cur = tok; w = tw; continue; }
    for (const ch of tok) { const cw = charUnits(ch); if (w + cw > max && cur) flush(); cur += ch; w += cw; }
  }
  if (cur.trim()) flush();
  if (lines.length <= maxLines) return lines;
  const kept = lines.slice(0, maxLines);
  let last = Array.from(kept[maxLines - 1]);
  while (last.length && textUnits(last.join('')) + 1 > max) last.pop();
  kept[maxLines - 1] = last.join('').trimEnd() + '…';
  return kept;
}

/* ---------- layered DAG layout (Sugiyama-lite: layers, dummy nodes, barycentre ordering) ---------- */
const NODE_DIM = { LR: { w: 252, h: 118, gapMain: 96, gapCross: 26 }, TB: { w: 212, h: 118, gapMain: 72, gapCross: 18 } };
const GRAPH_PAD = 36, DUMMY_SPAN = 14;
let GRAPH_W = 320, GRAPH_H = 200, ORIENT = 'LR', EDGE_ROUTES = [], LAYER_COUNT = 0;

function claimDepths() {
  const depth = {}, visiting = new Set();
  const depthOf = id => {
    if (depth[id] !== undefined) return depth[id];
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const deps = ((S.claims[id] || {}).depends_on || []).filter(d => S.claims[d] && d !== id);
    const v = deps.length ? 1 + Math.max(...deps.map(depthOf)) : 0;
    visiting.delete(id);
    depth[id] = v;
    return v;
  };
  Object.keys(S.claims || {}).forEach(depthOf);
  return depth;
}
function layoutClaims() {
  const vp = $('graphViewport');
  ORIENT = vp && vp.clientWidth && vp.clientWidth < 640 ? 'TB' : 'LR';
  const dim = NODE_DIM[ORIENT], LR = ORIENT === 'LR';
  const depth = claimDepths();
  const ids = Object.keys(S.claims || {}).sort((a, b) => (CLAIM_INDEX[a] || 1e9) - (CLAIM_INDEX[b] || 1e9) || a.localeCompare(b));
  const nLayers = ids.length ? 1 + Math.max(...ids.map(id => depth[id])) : 0;
  LAYER_COUNT = nLayers;
  const layers = Array.from({ length: nLayers }, () => []);
  const dummy = {}, preds = {}, succs = {}, edges = [];
  const link = (a, b) => { (succs[a] = succs[a] || []).push(b); (preds[b] = preds[b] || []).push(a); };
  ids.forEach(id => layers[depth[id]].push(id));
  ids.forEach(id => {
    const deps = [...new Set((S.claims[id].depends_on || []).filter(d => S.claims[d] && d !== id))];
    deps.forEach(dep => {
      const chain = [dep];
      for (let l = depth[dep] + 1; l < depth[id]; l++) {
        const key = `~${dep}>${id}#${l}`;
        dummy[key] = true; layers[l].push(key); chain.push(key);
      }
      chain.push(id);
      for (let k = 0; k + 1 < chain.length; k++) link(chain[k], chain[k + 1]);
      edges.push({ from: dep, to: id, chain });
    });
  });
  const pos = {};
  layers.forEach(layer => layer.forEach((k, i) => { pos[k] = i; }));
  const bary = (k, nb) => { const list = nb[k] || []; return list.length ? list.reduce((s, x) => s + pos[x], 0) / list.length : pos[k]; };
  const sweep = (l, nb) => {
    const b = {}; layers[l].forEach(k => { b[k] = bary(k, nb); });
    layers[l].sort((x, y) => (b[x] - b[y]) || (pos[x] - pos[y]));
    layers[l].forEach((k, i) => { pos[k] = i; });
  };
  for (let it = 0; it < 4; it++) {
    for (let l = 1; l < nLayers; l++) sweep(l, preds);
    for (let l = nLayers - 2; l >= 0; l--) sweep(l, succs);
  }
  const slot = k => dummy[k] ? DUMMY_SPAN : (LR ? dim.h : dim.w);
  const extent = layer => layer.reduce((s, k) => s + slot(k), 0) + Math.max(0, layer.length - 1) * dim.gapCross;
  const maxExtent = Math.max(0, ...layers.map(extent));
  const mainSize = LR ? dim.w : dim.h;
  const P = {};
  CLAIM_POS = {};
  layers.forEach((layer, l) => {
    let cross = GRAPH_PAD + (maxExtent - extent(layer)) / 2;
    const main = GRAPH_PAD + l * (mainSize + dim.gapMain);
    layer.forEach(k => {
      const s = slot(k);
      const box = LR ? { x: main, y: cross, w: dim.w, h: dummy[k] ? s : dim.h } : { x: cross, y: main, w: dummy[k] ? s : dim.w, h: dim.h };
      P[k] = box;
      if (!dummy[k]) CLAIM_POS[k] = { ...box, layer: l, claim: S.claims[k] };
      cross += s + dim.gapCross;
    });
  });
  const mainTotal = nLayers ? nLayers * mainSize + (nLayers - 1) * dim.gapMain : 0;
  GRAPH_W = Math.max(320, Math.ceil(2 * GRAPH_PAD + (LR ? mainTotal : maxExtent)));
  GRAPH_H = Math.max(200, Math.ceil(2 * GRAPH_PAD + (LR ? maxExtent : mainTotal)));
  /* ports: spread several edges along a card side so arrows never stack */
  const mid = k => LR ? P[k].y + P[k].h / 2 : P[k].x + P[k].w / 2;
  const outs = {}, ins = {};
  edges.forEach(e => {
    (outs[e.chain[0]] = outs[e.chain[0]] || []).push(e);
    (ins[e.chain[e.chain.length - 1]] = ins[e.chain[e.chain.length - 1]] || []).push(e);
  });
  const spread = (list, key, prop) => {
    list.sort((a, b) => mid(key(a)) - mid(key(b)));
    const n = list.length, size = LR ? dim.h : dim.w;
    const step = n > 1 ? Math.min(16, (size * 0.6) / (n - 1)) : 0;
    list.forEach((e, i) => { e[prop] = (i - (n - 1) / 2) * step; });
  };
  Object.values(outs).forEach(list => spread(list, e => e.chain[1], 'outOff'));
  Object.values(ins).forEach(list => spread(list, e => e.chain[e.chain.length - 2], 'inOff'));
  const outPort = (k, off) => LR ? { x: P[k].x + P[k].w, y: mid(k) + off } : { x: mid(k) + off, y: P[k].y + P[k].h };
  const inPort = (k, off) => LR ? { x: P[k].x, y: mid(k) + off } : { x: mid(k) + off, y: P[k].y };
  EDGE_ROUTES = edges.map(e => {
    const pts = [outPort(e.chain[0], e.outOff || 0)];
    e.chain.slice(1, -1).forEach(k => { pts.push(inPort(k, 0)); pts.push(outPort(k, 0)); });
    pts.push(inPort(e.chain[e.chain.length - 1], e.inOff || 0));
    return { from: e.from, to: e.to, d: routePath(pts) };
  });
}
function routePath(pts) {
  const r = v => Math.round(v * 10) / 10;
  let d = `M${r(pts[0].x)} ${r(pts[0].y)}`;
  for (let j = 1; j < pts.length; j++) {
    const a = pts[j - 1], b = pts[j];
    if (j % 2 === 0) { d += ` L${r(b.x)} ${r(b.y)}`; continue; }
    if (ORIENT === 'LR') { const m = (a.x + b.x) / 2; d += ` C${r(m)} ${r(a.y)} ${r(m)} ${r(b.y)} ${r(b.x)} ${r(b.y)}`; }
    else { const m = (a.y + b.y) / 2; d += ` C${r(a.x)} ${r(m)} ${r(b.x)} ${r(m)} ${r(b.x)} ${r(b.y)}`; }
  }
  return d;
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

/* narrative line for one event (event rail + latest line), via the active locale */
function narrate(ev, raw = false) {
  const d = ev.data || {}, type = ev.event_type;
  const expId = expIdOf(d);
  const exp = S.experiments[expId] || {};
  const claimId = (exp.target_claim_ids || [])[0] || '';
  const claim = !raw && S.claims[claimId] ? claimLabel(S.claims[claimId]) : claimId;
  const expName = raw ? expId : (trExpTitle(exp) || expId);
  const note = raw ? null : readerEventNote(readerReportState().report, ev);
  const v = d.verdict || {};
  const out = (cls, icon, pair) => ({ cls, icon, feed: note ? note.feed : pair[0], caster: note ? note.caster : pair[1] });
  switch (type) {
    case 'RUN_CREATED': return out('info', '·', L.n_run_created(S.topic));
    case 'SPEC_LOCKED': return out('info', '·', L.n_spec_locked());
    case 'CONTRACT_ADDED': return out('info', '·', L.n_contract((d.contract && d.contract.id) || ''));
    case 'EXPERIMENT_PROPOSED': return out('info', '·', L.n_proposed(trExpTitle(exp) || expId, claim));
    case 'EXPERIMENT_ADMITTED': return out('info', '·', L.n_admitted(expName, claim));
    case 'EXPERIMENT_BACKLOGGED': return out('miss', '–', L.n_backlogged(expName, d.reason || ''));
    case 'EXPERIMENT_PRUNED': return out('miss', '–', L.n_pruned(expName));
    case 'ATTEMPT_RESERVED': return out('info', '·', L.n_reserved(expName, claim));
    case 'ATTEMPT_STARTED': return out('info', '·', L.n_started(expName));
    case 'OBSERVATION_RECORDED': return out('info', '·', L.n_observation());
    case 'WAIT_FIRED': return out('info', '·', L.n_wait_fired(expName));
    case 'WAIT_EXPIRED': return out('miss', '–', L.n_wait_expired(expName, d.on_expire || ''));
    case 'VERDICT_ISSUED': {
      const effects = d.claim_effects || [];
      const supported = effects.some(x => x.status === 'SUPPORTED');
      const rollbacks = effects.filter(x => x.status === 'INVALIDATED').length;
      if (v.status === 'PASS') return supported
        ? out('pass', '✓', L.n_pass_promoted(claim))
        : out('soft', '◐', L.n_pass_provisional(expName, claim));
      if (v.status === 'FAIL') return out('fail', '✕', L.n_fail(claim, rollbacks, v.reason_code));
      if (v.status === 'INVALID') return out('miss', '⊘', L.n_invalid(expName, v.reason_code));
      if (v.status === 'ERROR') return out('miss', '!', L.n_error(expName));
      return out('soft', '?', L.n_inconclusive(claim));
    }
    case 'LESSON_CANDIDATE_CREATED': return out('loot', '◇', L.n_lesson_add((d.lesson && d.lesson.id) || ''));
    case 'LESSON_EVIDENCE_ADDED': return out('loot', '◇', L.n_lesson_evidence(d.lesson_id));
    case 'LESSON_PROMOTED': return out('loot', '◆', L.n_lesson_promoted(d.lesson_id));
    case 'LESSON_REVOKED': return out('miss', '✕', L.n_lesson_revoked(d.lesson_id));
    case 'RUN_PAUSED': return out('info', '‖', L.n_paused());
    case 'RUN_RESUMED': return out('info', '›', L.n_resumed());
    case 'RUN_FAILED': return out('fail', '✕', L.n_run_failed(d.reason));
    case 'RUN_FINALIZED': {
      const st = d.status || '';
      if (st === 'SOLVED') return out('pass', '■', L.n_final_solved());
      if (st === 'REFUTED') return out('fail', '■', L.n_final_refuted());
      if (st === 'BUDGET_EXHAUSTED') return out('soft', '■', L.n_final_budget());
      return out('soft', '■', L.n_final_other(runStatusLabel(st)));
    }
    case 'REPORT_RENDERED': return out('info', '·', L.n_report());
  }
  return { cls:'info', icon:'·', feed:ev.event_type, caster:'' };
}

/* ================= graph rendering ================= */
function renderGraphSub() {
  const n = Object.keys(S.claims || {}).length;
  const parts = [L.graph_sub(n, LAYER_COUNT)];
  if (n && fitScale() < READABLE_SCALE) parts.push(t('graph_hint_large'));
  $('graphSub').textContent = parts.join(' · ');
  if (BOOT_ERROR) { $('graphEmpty').textContent = t('boot_error'); $('graphEmpty').hidden = false; return; }
  $('graphEmpty').textContent = t('graph_empty');
  $('graphEmpty').hidden = n > 0;
}
let LAYOUT_KEY = '';
function renderArenaStatic() {
  layoutClaims();
  $('edges').innerHTML = EDGE_ROUTES.map(e =>
    `<path class="edge" data-claim="${esc(e.to)}" data-dep="${esc(e.from)}" d="${e.d}"/>`).join('');
  bossSig = '';
  const key = `${ORIENT}|${GRAPH_W}x${GRAPH_H}`;
  if (key !== LAYOUT_KEY) { LAYOUT_KEY = key; applyViewMode(); } else sizeGraph();
  renderGraphSub();
}
function updateEdges(touchedSet, targetClaim) {
  document.querySelectorAll('#edges path').forEach(p => {
    const c = p.dataset.claim || '';
    p.classList.toggle('lit', touchedSet.has(c));
    p.classList.toggle('hot', !!targetClaim && c === targetClaim);
  });
  updateEdgeSelection();
}
function updateEdgeSelection() {
  document.querySelectorAll('#edges path').forEach(p => {
    const linked = !!SELECTED && (p.dataset.claim === SELECTED || p.dataset.dep === SELECTED);
    p.classList.toggle('focus', linked);
    p.classList.toggle('dim', !!SELECTED && !linked);
  });
}
function svgLines(lines, cls, x, y0, lh) {
  if (!lines.length) return '';
  return `<text class="${cls}" x="${x}" y="${y0}">${lines.map((s, i) => `<tspan x="${x}"${i ? ` dy="${lh}"` : ''}>${esc(s)}</tspan>`).join('')}</text>`;
}
function nodeSvg(p, st, target, touched, latest) {
  const c = p.claim, id = c.id, w = p.w, h = p.h, padX = 16, inner = w - padX * 2;
  const label = claimLabel(c);
  const takeaway = readerTakeaway(readerReportState().report,id,st,latest);
  const stmt = takeaway || String(trClaimF(c, 'statement') || '');
  const pillText = `${GLYPH[st] || '•'} ${stLabel(st)}`;
  const pillW = Math.ceil(textUnits(pillText) * 11.5) + 18;
  const labelLines = wrapText(label, inner, 14, takeaway ? 1 : 2);
  const stmtLines = labelLines.length < 2 && stmt && stmt !== label ? wrapText(stmt, inner, 12.5, 2) : [];
  const prov = latest && (st === 'OPEN' || st === 'INCONCLUSIVE') && (c.provisional_passes || 0) > 0;
  const base =[c.required ? t('required') : t('optional')];
  if (c.critical) base.push(t('critical'));
  if (latest && !prov) base.push(L.evidence_n((c.evidence_ids || []).length));
  const baseText = base.join(' · ');
  const metaHtml = prov
    ? `${esc(baseText)} · <tspan class="warn">${esc(wrapText(L.prov_short(c.provisional_passes), inner - textUnits(baseText + ' · ') * 12, 12, 1)[0] || '')}</tspan>`
    : esc(wrapText(baseText, inner, 12, 1)[0] || '');
  const sel = SELECTED === id;
  const aria = `${claimNo(id)} ${label} — ${stLabel(st)} · ${c.required ? t('required') : t('optional')}${prov ? ' · ' + L.prov_short(c.provisional_passes) : ''}`;
  const cls = ['claim-node', `st-${st}`, c.required ? '' : 'optional', touched ? '' : 'untouched', target ? 'target' : '', sel ? 'selected' : '', prov ? 'provisional' : ''].filter(Boolean).join(' ');
  return `<g class="${esc(cls)}" data-claim="${esc(id)}" transform="translate(${p.x} ${p.y})" tabindex="0" role="button" aria-pressed="${sel}" aria-label="${esc(aria)}">
    <title>${esc(stmt || label)}</title>
    ${target ? `<text class="target-tag" x="2" y="-10">▸ ${esc(t('target_tag'))}</text>` : ''}
    <rect class="node-ring" x="-5" y="-5" width="${w + 10}" height="${h + 10}" rx="14"/>
    <rect class="node-shadow" x="0" y="2" width="${w}" height="${h}" rx="10"/>
    <rect class="node-box" width="${w}" height="${h}" rx="10"/>
    <rect class="node-stripe" x="0.5" y="14" width="3.5" height="${h - 28}" rx="1.75"/>
    <text class="node-idx" x="${padX}" y="25">${esc(claimNo(id))}</text>
    <g transform="translate(${w - 12 - pillW} 9)"><rect class="pill-bg" width="${pillW}" height="22" rx="11"/><text class="pill-text" x="${pillW / 2}" y="15" text-anchor="middle">${esc(pillText)}</text></g>
    ${svgLines(labelLines, 'node-label', padX, 52, 20)}
    ${svgLines(stmtLines, 'node-stmt', padX, 72, 18)}
    <text class="node-meta" x="${padX}" y="${h - 13}">${metaHtml}</text>
    <rect class="node-focus" x="-4" y="-4" width="${w + 8}" height="${h + 8}" rx="13"/>
  </g>`;
}
function nodeEl(id) { return [...document.querySelectorAll('#bosses g.claim-node')].find(n => n.dataset.claim === id) || null; }

let bossSig = '';
function renderBosses(claimStatuses, targetClaim, touchedSet, latest) {
  const sig = JSON.stringify(claimStatuses || {}) + '|' + (targetClaim || '') + '|' + [...touchedSet].sort().join(',') + '|' + (SELECTED || '') + '|' + lang + '|' + (latest ? 1 : 0);
  if (sig === bossSig) return;
  bossSig = sig;
  const active = document.activeElement;
  const focused = active && active.closest ? active.closest('#bosses g.claim-node') : null;
  const focusId = focused ? focused.dataset.claim : null;
  $('bosses').innerHTML = Object.values(CLAIM_POS).map(p => {
    const st = (claimStatuses || {})[p.claim.id] || 'OPEN';
    return nodeSvg(p, st, p.claim.id === targetClaim, touchedSet.has(p.claim.id), latest);
  }).join('');
  updateEdges(touchedSet, targetClaim);
  if (focusId) { const n = nodeEl(focusId); if (n) n.focus({ preventScroll: true }); }
}

/* ---------- viewport: native scroll for pan, explicit zoom controls ---------- */
const READABLE_SCALE = 0.8, START_SCALE = 0.92;
let ZOOM = 1, VIEW_MODE = 'auto';
function fitScale() {
  const vp = $('graphViewport');
  if (!vp || !vp.clientWidth || !vp.clientHeight) return 1;
  return Math.min((vp.clientWidth - 24) / GRAPH_W, (vp.clientHeight - 24) / GRAPH_H);
}
function sizeGraph() {
  const svg = $('arena');
  svg.setAttribute('viewBox', `0 0 ${GRAPH_W} ${GRAPH_H}`);
  svg.setAttribute('width', String(Math.round(GRAPH_W * ZOOM)));
  svg.setAttribute('height', String(Math.round(GRAPH_H * ZOOM)));
  $('zoomRead').textContent = `${Math.round(ZOOM * 100)}%`;
}
function setZoom(k, anchor) {
  const vp = $('graphViewport'), svg = $('arena');
  k = Math.max(0.2, Math.min(2.5, k));
  const vr = vp.getBoundingClientRect();
  const ax = anchor ? anchor.x : vr.left + vp.clientWidth / 2;
  const ay = anchor ? anchor.y : vr.top + vp.clientHeight / 2;
  const before = svg.getBoundingClientRect();
  const cx = (ax - before.left) / ZOOM, cy = (ay - before.top) / ZOOM;
  ZOOM = k; sizeGraph();
  const after = svg.getBoundingClientRect();
  vp.scrollLeft += after.left + cx * k - ax;
  vp.scrollTop += after.top + cy * k - ay;
}
function fitGraph() {
  VIEW_MODE = 'fit';
  ZOOM = Math.max(0.2, Math.min(1.25, fitScale()));
  sizeGraph();
  const vp = $('graphViewport'); vp.scrollLeft = 0; vp.scrollTop = 0;
}
function initialView() {
  VIEW_MODE = 'auto';
  const k = fitScale();
  ZOOM = k >= READABLE_SCALE ? Math.min(k, 1.1) : START_SCALE;
  sizeGraph();
  const vp = $('graphViewport'); vp.scrollLeft = 0; vp.scrollTop = 0;
}
function applyViewMode() { if (VIEW_MODE === 'fit') fitGraph(); else if (VIEW_MODE === 'auto') initialView(); else sizeGraph(); }
function ensureVisible(id) {
  const p = CLAIM_POS[id], vp = $('graphViewport'), svg = $('arena');
  if (!p || !vp) return;
  const sr = svg.getBoundingClientRect(), vr = vp.getBoundingClientRect();
  const left = sr.left - vr.left + p.x * ZOOM, top = sr.top - vr.top + p.y * ZOOM;
  const w = p.w * ZOOM, h = p.h * ZOOM, m = 16;
  if (left < m) vp.scrollLeft += left - m;
  else if (left + w > vp.clientWidth - m) vp.scrollLeft += Math.min(left - m, left + w - vp.clientWidth + m);
  if (top < m + 14) vp.scrollTop += top - m - 14;
  else if (top + h > vp.clientHeight - m) vp.scrollTop += Math.min(top - m - 14, top + h - vp.clientHeight + m);
}
function initGraphViewport() {
  const vp = $('graphViewport');
  let drag = null;
  vp.addEventListener('pointerdown', e => {
    if (e.pointerType !== 'mouse' || e.button !== 0 || (e.target.closest && e.target.closest('.claim-node'))) return;
    drag = { x: e.clientX, y: e.clientY, l: vp.scrollLeft, t: vp.scrollTop };
    try { vp.setPointerCapture(e.pointerId); } catch (_) {}
    vp.classList.add('panning');
  });
  vp.addEventListener('pointermove', e => {
    if (!drag) return;
    vp.scrollLeft = drag.l - (e.clientX - drag.x);
    vp.scrollTop = drag.t - (e.clientY - drag.y);
  });
  const end = () => { drag = null; vp.classList.remove('panning'); };
  vp.addEventListener('pointerup', end);
  vp.addEventListener('pointercancel', end);
  vp.addEventListener('wheel', e => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    VIEW_MODE = 'manual';
    setZoom(ZOOM * Math.exp(-e.deltaY * 0.0025), { x: e.clientX, y: e.clientY });
  }, { passive: false });
  vp.addEventListener('keydown', e => {
    if (e.target.closest && e.target.closest('.claim-node')) return;
    if (e.key === '+' || e.key === '=') { e.preventDefault(); VIEW_MODE = 'manual'; setZoom(ZOOM * 1.2); }
    else if (e.key === '-' || e.key === '_') { e.preventDefault(); VIEW_MODE = 'manual'; setZoom(ZOOM / 1.2); }
    else if (e.key === '0') { e.preventDefault(); initialView(); }
  });
  $('graphZoomIn').addEventListener('click', () => { VIEW_MODE = 'manual'; setZoom(ZOOM * 1.2); });
  $('graphZoomOut').addEventListener('click', () => { VIEW_MODE = 'manual'; setZoom(ZOOM / 1.2); });
  $('graphFit').addEventListener('click', fitGraph);
  $('graphReset').addEventListener('click', initialView);
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      const orient = vp.clientWidth && vp.clientWidth < 640 ? 'TB' : 'LR';
      if (orient !== ORIENT) rerenderGraph();
      else { applyViewMode(); renderGraphSub(); }
    }, 160);
  });
}
function rerenderGraph() {
  renderArenaStatic();
  if (FRAMES.length) applyFrame(Number($('replaySlider').value), {});
  else renderSnapshotOnly();
}

/* ---------- inspector ---------- */
function claimEvidence(claim) {
  const ids = new Set(claim.evidence_ids || []);
  return Object.values(S.evidence || {}).filter(x => ids.has(x.id)
    || (((S.experiments || {})[x.experiment_id] || {}).target_claim_ids || []).includes(claim.id));
}
let unitSig = '';
function renderUnitCard(claimId, statuses) {
  const card = $('unitCard');
  const claim = claimId ? (S.claims || {})[claimId] : null;
  const st = claim ? ((statuses || {})[claimId] || claim.status || 'OPEN') : '';
  const latest = isLatestFrame();
  const sig = [claim ? claimId : '', st, lang, latest ? 1 : 0, S.snapshot_hash || ''].join('|');
  if (sig === unitSig) return;
  unitSig = sig;
  if (!claim) {
    card.classList.remove('on');
    card.innerHTML = `<h2 class="insp-kicker">${esc(t('inspector'))}</h2><p class="insp-empty">${esc(t('inspector_empty'))}</p>`;
    return;
  }
  const contracts = Object.values(S.contracts || {}).filter(c => c.target_claim_id === claimId);
  const exps = Object.values(S.experiments || {}).filter(x => (x.target_claim_ids || []).includes(claimId));
  const evs = claimEvidence(claim);
  const deps = (claim.depends_on || []).filter(d => S.claims[d]);
  const dependents = Object.values(S.claims).filter(c => (c.depends_on || []).includes(claimId)).map(c => c.id);
  const takeaway = readerTakeaway(readerReportState().report,claimId,st,latest);
  const conc = latest ? trClaimConclusion(claim) : '';
  const stmt = trClaimF(claim, 'statement') || '';
  const prov = latest && (st === 'OPEN' || st === 'INCONCLUSIVE') && (claim.provisional_passes || 0) > 0;
  const why = [L['why_' + st] || '', prov ? L.why_provisional(claim.provisional_passes) : '', claim.required ? '' : t('why_optional')].filter(Boolean);
  const chip = id => `<button type="button" class="chip-btn" data-claim="${esc(id)}"><span class="mono">${esc(claimNo(id))}</span>${esc(claimLabel(S.claims[id]))}</button>`;
  const sec = (title, n, body) => `<section class="insp-sec"><h3>${esc(title)}${n != null ? ` <span class="n">${n}</span>` : ''}</h3>${body}</section>`;
  const none = '<p class="insp-empty">—</p>';
  card.innerHTML = `
    <div class="insp-head"><span class="insp-idx mono">${esc(claimNo(claimId))}</span><h2 class="insp-title">${esc(claimLabel(claim))}</h2><button class="insp-close" id="ucClose" type="button" aria-label="${esc(t('close'))}" title="${esc(t('close'))}">✕</button></div>
    <div class="insp-tags">${status(st)}<span class="tag${claim.required ? '' : ' dashed'}">${esc(claim.required ? t('required') : t('optional'))}</span>${claim.critical ? `<span class="tag crit">${esc(t('critical'))}</span>` : ''}${prov ? `<span class="tag warn">${esc(L.provisional_n(claim.provisional_passes))}</span>` : ''}</div>
    ${takeaway ? sec(t('reader_claim'), null, `<p class="insp-conc">${esc(takeaway)}</p>`) : ''}
    <details class="reader-technical"><summary>${esc(t('reader_audit'))}</summary>
    ${why.length ? `<ul class="insp-why">${why.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
    ${conc ? sec(t('uc_conclusion'), null, `<p class="insp-conc">${esc(conc)}</p>`) : ''}
    ${sec(t('uc_statement'), null, `<p class="insp-text">${esc(stmt || '—')}</p><div class="insp-id mono">${esc(claimId)}</div>`)}
    ${deps.length ? sec(t('uc_depends'), deps.length, `<div>${deps.map(chip).join('')}</div>`) : ''}
    ${dependents.length ? sec(t('uc_dependents'), dependents.length, `<div>${dependents.map(chip).join('')}</div>`) : ''}
    ${latest ? '' : `<p class="insp-note">${esc(t('uc_snapshot_note'))}</p>`}
    ${sec(t('uc_contracts'), contracts.length, contracts.length ? `<ul class="insp-list">${contracts.map(c => `<li><div class="insp-row"><span class="mono">${esc(c.id)} · v${esc(c.version)}</span><span class="tiny">${esc(c.kind || '')}</span></div><div class="insp-sub">${esc(L.uc_gate((c.repetition || {}).min_passes, (c.repetition || {}).min_independent_contexts))}</div></li>`).join('')}</ul>` : none)}
    ${sec(t('uc_engagements'), exps.length, exps.length ? `<ul class="insp-list">${exps.slice(0, 12).map(x => `<li><div class="insp-row"><span>${esc(trExpTitle(x))}</span>${status((x.last_verdict || {}).status || x.status)}</div><div class="insp-sub mono">${esc(x.id)}</div></li>`).join('')}</ul>${exps.length > 12 ? `<div class="insp-more">${esc(L.uc_more(exps.length - 12))}</div>` : ''}` : none)}
    ${sec(t('uc_evidence'), evs.length, evs.length ? `<ul class="insp-list">${evs.map(x => `<li><div class="insp-row"><span>${esc(reasonSummary(x) || x.id)}</span>${status(x.verdict_status)}</div>${reasonExtra(x) ? `<div class="insp-sub">${esc(reasonExtra(x))}</div>` : ''}<div class="insp-sub mono">${esc(x.id)}${x.context_id ? ' · ' + esc(x.context_id) : ''}</div>${evExtras(x)}</li>`).join('')}</ul>` : `<p class="insp-empty">${esc(t('empty_evidence'))}</p>`)}</details>`;
  card.classList.add('on');
}
function refreshSelection() {
  document.querySelectorAll('#bosses g.claim-node, #quest .q-row').forEach(n => {
    const on = n.dataset.claim === SELECTED;
    n.classList.toggle('selected', on);
    n.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
  updateEdgeSelection();
}
function selectClaim(id, opts) {
  opts = opts || {};
  SELECTED = (SELECTED === id && !opts.keep) ? null : id;
  renderUnitCard(SELECTED, currentStatuses());
  refreshSelection();
  if (!SELECTED) return;
  if (opts.from !== 'graph') ensureVisible(SELECTED);
  else if (NARROW.matches) $('unitCard').scrollIntoView({ block: 'nearest', behavior: REDUCED.matches ? 'auto' : 'smooth' });
}
function closeInspector(returnFocus) {
  const prev = SELECTED;
  SELECTED = null;
  renderUnitCard(null);
  refreshSelection();
  if (returnFocus && prev) { const n = nodeEl(prev); if (n) n.focus(); }
}
function snapshotStatuses() { const o = {}; Object.values(S.claims || {}).forEach(c => { o[c.id] = c.status || 'OPEN'; }); return o; }
function currentStatuses() { const f = frameAt(Number($('replaySlider').value)); return (f && f.claim_statuses) || snapshotStatuses(); }
function initArenaPointer() {
  const claimOf = el => { const n = el && el.closest ? el.closest('[data-claim]') : null; return n ? n.dataset.claim : null; };
  $('bosses').addEventListener('click', e => { const id = claimOf(e.target); if (id) selectClaim(id, { from: 'graph' }); });
  $('bosses').addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
    const id = claimOf(e.target);
    if (id) { e.preventDefault(); selectClaim(id, { from: 'graph' }); }
  });
  $('quest').addEventListener('click', e => { const id = claimOf(e.target); if (id) selectClaim(id, { from: 'list' }); });
  $('uncertainNote').addEventListener('click', e => { const id = claimOf(e.target); if (id) selectClaim(id, { from: 'list', keep: true }); });
  $('unitCard').addEventListener('click', e => {
    if (e.target.closest('#ucClose')) { closeInspector(true); return; }
    const chipEl = e.target.closest('.chip-btn[data-claim]');
    if (chipEl) selectClaim(chipEl.dataset.claim, { from: 'list', keep: true });
  });
}

/* ================= frame application ================= */
function frameAt(i) { return FRAMES[Math.max(0, Math.min(FRAMES.length - 1, i))]; }

let CURRENT_INDEX = 0;
function isLatestFrame() { return !FRAMES.length || CURRENT_INDEX >= FRAMES.length - 1; }
function tallyStatuses(statuses) {
  const n = { SUPPORTED: 0, REFUTED: 0, INCONCLUSIVE: 0, OPEN: 0, INVALIDATED: 0 };
  const ids = new Set([...Object.keys(S.claims || {}), ...Object.keys(statuses || {})]);
  ids.forEach(id => { const st = (statuses || {})[id] || 'OPEN'; n[st] = (n[st] || 0) + 1; });
  return n;
}
function renderTally(statuses) {
  const n = tallyStatuses(statuses);
  $('scoreV').textContent = n.SUPPORTED; $('scoreR').textContent = n.REFUTED;
  $('scoreU').textContent = n.INCONCLUSIVE; $('scoreO').textContent = n.OPEN;
  $('scoreX').textContent = n.INVALIDATED; $('scoreXWrap').hidden = !n.INVALIDATED;
}
function renderBudget(f) {
  const B = S.budget || {};
  const attMax = B.max_attempts, costMax = B.max_cost_units;
  const att = f.attempts_remaining ?? B.attempts_remaining;
  const cost = f.cost_units_remaining ?? B.cost_units_remaining;
  if (attMax == null) {
    $('hpFill').style.transform = 'scaleX(1)';
    $('hpText').textContent = `${t('budget_attempts')} · ${t('unlimited')}`;
  } else {
    $('hpFill').style.transform = `scaleX(${Math.max(0, Math.min(1, (att ?? 0) / attMax))})`;
    $('hpText').textContent = `${t('budget_attempts')} ${att}/${attMax}`;
  }
  if (costMax == null) {
    $('manaFill').style.transform = 'scaleX(1)';
    $('manaText').textContent = `${t('budget_cost')} · ${t('unlimited')}`;
  } else {
    $('manaFill').style.transform = `scaleX(${Math.max(0, Math.min(1, (cost ?? 0) / costMax))})`;
    $('manaText').textContent = `${t('budget_cost')} ${Number(cost ?? 0).toFixed(1)}/${costMax}`;
  }
}
function renderRunState(st) {
  const el = $('runState');
  el.className = 'status ' + (st || '');
  el.textContent = st ? runStatusLabel(st) : '';
}
let noteSig = '';
function renderGraphNote(runStatus, statuses) {
  const final = isFinalStatus(runStatus);
  const unsettled = Object.values(S.claims || {}).filter(c => {
    const s = (statuses || {})[c.id] || 'OPEN';
    return s === 'INCONCLUSIVE' || s === 'INVALIDATED' || (final && s === 'OPEN');
  });
  const sig = [runStatus || '', final ? 1 : 0, lang, isLatestFrame() ? 1 : 0, unsettled.map(c => c.id + ':' + ((statuses || {})[c.id] || 'OPEN')).join(',')].join('|');
  if (sig === noteSig) return;
  noteSig = sig;
  const parts = [];
  const reader = isLatestFrame() ? readerReportState().report : null;
  if (reader) parts.push(`<p class="reader-graph-answer">${esc(reader.answer)}</p>`);
  if (runStatus === 'SOLVED') parts.push(`<details><summary>${esc(t('reader_audit'))}</summary><p>${esc(t('solved_note'))}</p></details>`);
  else if (final) parts.push(`<details><summary>${esc(t('reader_audit'))}</summary><p>${esc(L.final_note(runStatusLabel(runStatus)))}</p></details>`);
  if (unsettled.length) parts.push(`<p><span class="unc-label">${esc(t('uncertain_lead'))}</span>${unsettled.map(c => {
    const s = (statuses || {})[c.id] || 'OPEN';
    return `<button type="button" class="chip-btn" data-claim="${esc(c.id)}"><span class="mono">${esc(claimNo(c.id))}</span>${esc(claimLabel(c))}${status(s)}${c.required ? '' : `<span class="tag dashed">${esc(t('optional'))}</span>`}</button>`;
  }).join('')}</p>`);
  $('uncertainNote').innerHTML = parts.join('');
  $('uncertainNote').hidden = !parts.length;
}
function applyFrame(i, opts) {
  opts = opts || {};
  const f = frameAt(i); if (!f) return;
  CURRENT_INDEX = Math.max(0, Math.min(FRAMES.length - 1, i));
  const latest = isLatestFrame();
  const ev = E[f.seq - 1] || {};
  const statuses = f.claim_statuses || {};
  renderTally(statuses);
  renderBudget(f);
  renderRunState(f.run_status);
  $('matchMeta').textContent = `#${f.seq}/${E.length} · ${t('obj_label')} ${f.objective}% · ${t('epi_label')} ${f.epistemic}%`;
  $('lootMeta').textContent = f.n_lessons ? `${t('eb_lessons')} ${f.n_lessons}` : '';
  const target = isFinalStatus(f.run_status) ? null : TARGET_BY_SEQ[f.seq];
  renderBosses(statuses, target, TOUCHED_BY_SEQ[f.seq] || new Set(), latest);
  renderQuest(statuses);
  renderGraphNote(f.run_status, statuses);
  if (SELECTED) renderUnitCard(SELECTED, statuses);
  const n = narrate(ev);
  $('casterLine').textContent = n.caster || t('no_events');
  $('frameLabel').textContent = `#${f.seq}/${E.length} · ${(ev.ts || '').slice(5, 16).replace('T', ' ')}`;
  $('tlFill').style.width = pctOf(i) + '%';
  $('tlCursor').style.left = pctOf(i) + '%';
  $('replaySlider').value = i;
  if (opts.feedRebuild) rebuildFeed(f.seq); else if (opts.fx) appendFeed(ev);
  try { history.replaceState(null, '', '#seq=' + f.seq); } catch (_) {}
}
function renderSnapshotOnly() {
  const statuses = snapshotStatuses();
  renderTally(statuses);
  renderBudget({});
  renderRunState(S.run_status);
  renderBosses(statuses, null, new Set(Object.keys(statuses)), true);
  renderQuest(statuses);
  renderGraphNote(S.run_status, statuses);
  renderUnitCard(SELECTED, statuses);
  if (!$('casterLine').textContent) $('casterLine').textContent = t('no_events');
  rebuildFeed(E.length);
  setLiveChip();
}

const FINAL_STATUSES = new Set(['SOLVED','REFUTED','EXHAUSTED','BUDGET_EXHAUSTED','FAILED','CANCELLED','ABORTED','TIME_EXHAUSTED','MAX_STATES_EXHAUSTED','BLOCKED']);
function isFinalStatus(st) { return FINAL_STATUSES.has(st) || /_EXHAUSTED$/.test(st || ''); }
function matchDuration() {
  if (!E.length) return '—';
  const t0 = Date.parse(E[0].ts || ''), t1 = Date.parse(E[E.length - 1].ts || '');
  if (!t0 || !t1 || t1 < t0) return '—';
  const s = Math.round((t1 - t0) / 1000);
  return L.eb_dur(Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60);
}
function claimMark(st) { return GLYPH[st] || '○'; }

function pctOf(i) { return FRAMES.length <= 1 ? 100 : (100 * i) / (FRAMES.length - 1); }

function rebuildFeed(uptoSeq) {
  const rows = [];
  for (let k = E.length - 1; k >= 0 && rows.length < 30; k--) {
    if (E[k].seq > uptoSeq) continue;
    rows.push(feedRowHtml(E[k], false));
  }
  $('feed').innerHTML = rows.join('') || `<div class="feed-row info"><span class="feed-text">${esc(t('no_events'))}</span></div>`;
  $('feedCount').textContent = L.events_n(Math.min(uptoSeq, E.length));
}
function feedRowHtml(ev, fresh) {
  const n = narrate(ev);
  return `<button type="button" class="feed-row ${n.cls}${fresh ? ' feed-new' : ''}" data-seq="${ev.seq}" title="${esc(t('feed_jump'))}"><span class="seq">#${ev.seq}</span><span class="glyph" aria-hidden="true">${esc(n.icon)}</span><span class="feed-text">${esc(n.feed)}</span><span class="ts">${esc((ev.ts || '').slice(11, 19))}</span></button>`;
}
function appendFeed(ev) {
  const feed = $('feed');
  if (!feed.querySelector('.feed-row[data-seq]')) feed.innerHTML = '';
  feed.insertAdjacentHTML('afterbegin', feedRowHtml(ev, true));
  while (feed.children.length > 30) feed.lastChild.remove();
  $('feedCount').textContent = L.events_n(ev.seq);
}

function renderWaiting() {
  const waits = (S.waits || []).filter(w => w.status === 'PENDING');
  const has = waits.length > 0;
  $('respawnSec').style.display = has ? '' : 'none';
  $('waitingList').style.display = has ? '' : 'none';
  if (!has) return;
  $('nextWake').textContent = S.next_wake_at ? `${t('next_wake')} ${S.next_wake_at}` : t('awaiting_evidence');
  $('waitingList').innerHTML = waits.map(w => {
    const x = S.experiments[w.experiment_id] || {};
    const cond = w.kind === 'time' ? L.wait_not_before(w.not_before_ts || '—') : L.wait_until(((w.until_evidence || {}).claim_id) || '?');
    return `<div class="feed-row soft"><span class="glyph" aria-hidden="true">◷</span><span class="feed-text">${esc(trExpTitle(x) || w.experiment_id)}<span class="tiny"> · ${esc(cond)}</span></span></div>`;
  }).join('');
}
let questSig = '';
function renderQuest(statuses) {
  const latest = isLatestFrame();
  const sig = JSON.stringify(statuses || {}) + '|' + lang + '|' + (latest ? 1 : 0) + '|' + Object.keys(S.claims || {}).join(',') + '|' + (S.snapshot_hash || '');
  if (sig === questSig) return;
  questSig = sig;
  const rows = Object.values(S.claims || {}).map(c => {
    const st = (statuses || {})[c.id] || 'OPEN';
    const conc = readerTakeaway(readerReportState().report,c.id,st,latest) || (latest ? trClaimConclusion(c) : '');
    const stmt = String(trClaimF(c, 'statement') || '');
    const prov = latest && (st === 'OPEN' || st === 'INCONCLUSIVE') && (c.provisional_passes || 0) > 0;
    const tags = (c.required ? '' : `<span class="tag dashed">${esc(t('optional'))}</span>`)
      + (c.critical ? `<span class="tag crit">${esc(t('critical'))}</span>` : '')
      + (prov ? `<span class="tag warn">${esc(L.prov_short(c.provisional_passes))}</span>` : '');
    const sel = SELECTED === c.id;
    return `<button type="button" class="q-row q-${esc(st)}${sel ? ' selected' : ''}" data-claim="${esc(c.id)}" aria-pressed="${sel}"><span class="q-top"><span class="q-idx mono">${esc(claimNo(c.id))}</span><span class="q-label">${esc(claimLabel(c))}</span>${status(st)}</span>${conc || stmt ? `<span class="q-sub" title="${esc(stmt)}">${esc(conc || stmt)}</span>` : ''}${tags ? `<span class="q-tags">${tags}</span>` : ''}</button>`;
  });
  $('quest').innerHTML = rows.join('') || `<p class="insp-empty" style="padding:4px 10px">${esc(t('graph_empty'))}</p>`;
  $('questCount').textContent = L.claims_n(Object.keys(S.claims || {}).length);
}

/* ================= playback deck ================= */
let follow = true, playTimer = null, speed = 2, liveChain = 0;
function setLiveChip() {
  if (BOOT_ERROR) { $('liveChip').className = 'livechip stale'; $('liveText').textContent = t('load_failed'); return; }
  const runFinal = isFinalStatus((FRAMES[FRAMES.length - 1] || {}).run_status || (FRAMES.length ? '' : S.run_status));
  const lost = pollMisses >= 3 && !runFinal;
  $('liveChip').classList.toggle('replaying', !follow);
  $('liveChip').classList.toggle('ended', runFinal);
  $('liveChip').classList.toggle('stale', lost);
  $('liveText').textContent = lost ? t('reconnecting') : follow ? (runFinal ? t('ended') : t('live')) : t('replay');
  $('liveBtn').classList.toggle('active', follow);
  $('endboardBtn').hidden = !runFinal;
}
function showIndex(i, opts) {
  if (!FRAMES.length) return;
  i = Math.max(0, Math.min(FRAMES.length - 1, i));
  follow = i === FRAMES.length - 1;
  setLiveChip();
  applyFrame(i, opts || { feedRebuild: true });
}
function setPlayButton(playing) {
  const b = $('playBtn');
  b.textContent = playing ? '❚❚' : '▶';
  b.classList.toggle('active', playing);
  b.setAttribute('aria-label', t(playing ? 'pause' : 'play'));
}
function stopPlay() { liveChain += 1; if (playTimer) { clearInterval(playTimer); playTimer = null; setPlayButton(false); } }
function startPlay() {
  if (!FRAMES.length) return;
  stopPlay();
  let i = Number($('replaySlider').value);
  if (i >= FRAMES.length - 1) { i = -1; }
  setPlayButton(true);
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
function openView(name) { const btn = document.querySelector(`.tab[data-view="${name}"]`); if (btn) btn.click(); }
function initDeck() {
  renderMarkers();
  $('replaySlider').addEventListener('input', () => { stopPlay(); showIndex(Number($('replaySlider').value), { feedRebuild: true }); });
  $('playBtn').addEventListener('click', () => { playTimer ? stopPlay() : startPlay(); });
  $('liveBtn').addEventListener('click', () => { stopPlay(); showIndex(FRAMES.length - 1, { feedRebuild: true }); });
  $('speedSel').addEventListener('change', () => { speed = Number($('speedSel').value) || 2; if (playTimer) startPlay(); });
  $('feed').addEventListener('click', e => {
    const row = e.target.closest('.feed-row[data-seq]');
    if (!row) return;
    stopPlay();
    showIndex(Number(row.dataset.seq) - 1, { feedRebuild: true });
  });
  $('endboardBtn').addEventListener('click', () => openView('report'));
  window.addEventListener('keydown', e => {
    if (e.key === 'Escape' && SELECTED) { closeInspector(true); return; }
    if (e.defaultPrevented) return;
    if (e.target.closest && e.target.closest('input,select,textarea,button,a,summary,[role="button"],[contenteditable],#graphViewport')) return;
    if (e.code === 'Space') { e.preventDefault(); playTimer ? stopPlay() : startPlay(); }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault(); stopPlay();
      const d = (e.key === 'ArrowRight' ? 1 : -1) * (e.shiftKey ? 10 : 1);
      showIndex(Number($('replaySlider').value) + d, { feedRebuild: true });
    } else if (e.key === 'Home') { e.preventDefault(); stopPlay(); showIndex(0, { feedRebuild: true }); }
    else if (e.key === 'End') { e.preventDefault(); stopPlay(); showIndex(FRAMES.length - 1, { feedRebuild: true }); }
  });
}

/* ================= live polling ================= */
let pollMisses = 0;
async function poll() {
  if (document.hidden) return;
  try {
    /* A daemon that accepts but never answers must still count as a miss. */
    const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 5000);
    let body;
    try {
      const r = await fetch(`snapshot.json?ts=${Date.now()}`, { cache: 'no-store', signal: ctl.signal });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      body = await r.text();
    } finally { clearTimeout(timer); }
    const fresh = parseLenient(body);
    if (!fresh?.snapshot?.snapshot_hash) throw new Error('Snapshot hash missing');
    if (pollMisses) { pollMisses = 0; setLiveChip(); }
    const sameSnapshot = fresh.snapshot.snapshot_hash === S.snapshot_hash;
    const translationsChanged = JSON.stringify(fresh.translations || {}) !== JSON.stringify(DATA.translations || {})
      || JSON.stringify(fresh.snapshot.i18n || {}) !== JSON.stringify(S.i18n || {});
    if (sameSnapshot && !translationsChanged) return;
    DATA.translations = fresh.translations || {};
    bossSig = ''; questSig = ''; unitSig = ''; noteSig = '';
    if (sameSnapshot) {
      // Same deterministic snapshot: refresh presentation only, not frames or state.
      S.i18n = fresh.snapshot.i18n || {};
      applyStaticI18n(); renderReport(); renderWaiting();
      if (FRAMES.length) applyFrame(CURRENT_INDEX, {feedRebuild:true}); else renderSnapshotOnly();
      return;
    }
    const oldLen = FRAMES.length;
    S = fresh.snapshot; E = fresh.events || []; FRAMES = fresh.frames || [];
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
    } else if (!playTimer && FRAMES.length) {
      applyFrame(Number($('replaySlider').value), {});
    }
  } catch (error) {
    pollMisses += 1;
    setLiveChip();
    console.warn('Observatory poll failed; retrying next tick', error);
  }
}

/* ================= detail tabs (audit layer) ================= */
function initTabs() {
  document.querySelectorAll('.tab').forEach(btn => btn.addEventListener('click', () => {
    const behavior = REDUCED.matches ? 'auto' : 'smooth';
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.view').forEach(x => x.classList.remove('active'));
    btn.classList.add('active');
    if (btn.dataset.view !== 'none') {
      const v = $('view-' + btn.dataset.view);
      v.classList.add('active');
      requestAnimationFrame(() => v.scrollIntoView({ behavior, block: 'start' }));
    } else {
      window.scrollTo({ top: 0, behavior });
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
/* READER_PURE_START */
function validateReaderReport(r, snapshotHash, eventCount) {
  const result = diagnostic => ({report:null, diagnostic});
  if (r == null) return result('missing');
  const rec = x => x !== null && typeof x === 'object' && !Array.isArray(x);
  const str = (x, max=20000) => typeof x === 'string' && x.length <= max;
  const list = (x, max, check) => Array.isArray(x) && x.length <= max && x.every(check);
  const note = x => x === undefined || str(x);
  const count = x => Number.isSafeInteger(x) && x >= 0 && x <= 100000000;
  const record = (x, check) => rec(x) && Object.keys(x).length <= 10000 && Object.entries(x).every(([k,v]) => str(k,256) && k.length > 0 && check(v,k));
  const table = x => rec(x) && note(x.label) && note(x.caption) && list(x.columns,50,v=>str(v,2000)) && x.columns.length > 0
    && list(x.rows,1000,row=>list(row,50,v=>str(v,20000)) && row.length === x.columns.length);
  if (!rec(r) || r.schema_version !== 'sisyfus.reader-report.v1' || !rec(r.basis)
    || !str(r.basis.snapshot_hash,256) || !r.basis.snapshot_hash.length || !count(r.basis.event_count)
    || !['zh','en'].includes(r.language) || !['title','question','answer','scope_note'].every(k=>str(r[k]))
    || !r.title.trim() || !r.question.trim() || !r.answer.trim() || !r.scope_note.trim()
    || !list(r.sections,100,s=>rec(s) && str(s.heading,2000) && list(s.paragraphs,200,v=>str(v)) && note(s.note)
      && (s.notes === undefined || list(s.notes,100,v=>str(v))) && (s.table === undefined || table(s.table)))
    || !list(r.process,100,s=>rec(s) && ['title','what','finding','meaning'].every(k=>str(s[k])))
    || !record(r.claim_takeaways,v=>rec(v) && ['OPEN','SUPPORTED','REFUTED','INCONCLUSIVE','INVALIDATED'].includes(v.status) && str(v.text))
    || !record(r.event_notes,(v,k)=>/^[1-9][0-9]{0,8}$/.test(k) && count(Number(k)) && rec(v) && str(v.event_type,256) && v.event_type.length > 0 && str(v.feed) && str(v.caster))
    || !list(r.sources,200,s=>rec(s) && str(s.label,2000) && str(s.href,4096)) || !note(r.note)
    || (r.notes !== undefined && !list(r.notes,100,v=>str(v)))) return result('invalid');
  if (r.basis.snapshot_hash !== snapshotHash || r.basis.event_count !== eventCount) return result('stale');
  return {report:r,diagnostic:''};
}
function safeReaderHref(h) {
  if (typeof h !== 'string' || !h || h.length > 4096 || h.trim() !== h) return '';
  let decoded = h;
  try {
    for (let i=0;i<12;i++) {
      const next = decodeURIComponent(decoded);
      if (next === decoded) break;
      decoded = next;
      if (i === 11) return '';
    }
  } catch (error) { return ''; } // malformed URI is an explicitly disabled link
  if (/[\\\\\\s\\u0000-\\u001f\\u007f]/.test(decoded) || decoded.startsWith('//')
    || decoded.split(/[/?#]/).some(x=>x === '..')) return '';
  if (h.startsWith('https://')) {
    try { const u = new URL(h); return u.protocol === 'https:' && u.hostname && !u.username && !u.password ? h : ''; }
    catch (error) { return ''; }
  }
  if (decoded.startsWith('/') || /[:]/.test(decoded) || /^[?#]/.test(decoded)) return '';
  return h;
}
function readerProseHtml(r) {
  const zh = r.language === 'zh';
  const para = s => `<p>${esc(s)}</p>`;
  const notes = x => (x.note === undefined ? '' : `<p class="reader-note">${esc(x.note)}</p>`)
    + (x.notes || []).map(s=>`<p class="reader-note">${esc(s)}</p>`).join('');
  return r.sections.map(s=>`<section class="reader-section"><h2>${esc(s.heading)}</h2>${s.paragraphs.map(para).join('')}${s.table ? `<div class="reader-table-wrap" tabindex="0" role="region" aria-label="${esc(s.table.label || s.heading)}"><table>${s.table.label || s.table.caption ? `<caption>${esc(s.table.label || s.table.caption)}</caption>` : ''}<thead><tr>${s.table.columns.map(c=>`<th scope="col">${esc(c)}</th>`).join('')}</tr></thead><tbody>${s.table.rows.map(row=>`<tr>${row.map(c=>`<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : ''}${notes(s)}</section>`).join('')
    + notes(r) + `<section class="reader-section"><h2>${zh ? '这轮研究是怎样做的' : 'How the research was done'}</h2><ol class="reader-process">${r.process.map(s=>`<li><h3>${esc(s.title)}</h3><p><b>${zh ? '做了什么' : 'What was done'}：</b>${esc(s.what)}</p><p><b>${zh ? '发现' : 'Finding'}：</b>${esc(s.finding)}</p><p><b>${zh ? '意义' : 'Meaning'}：</b>${esc(s.meaning)}</p></li>`).join('')}</ol></section>`
    + `<section class="reader-section"><h2>${zh ? '证据与来源' : 'Evidence and sources'}</h2><ul>${r.sources.map(s=>{ const h=safeReaderHref(s.href); return `<li>${h ? `<a href="${esc(h)}" target="_blank" rel="noopener noreferrer">${esc(s.label)}</a>` : `<span>${esc(s.label)} (${zh ? '链接已禁用' : 'link disabled'})</span>`}</li>`; }).join('')}</ul></section>`;
}
function readerTakeaway(r,id,status,latest) {
  const v = r && r.claim_takeaways && Object.prototype.hasOwnProperty.call(r.claim_takeaways,id) ? r.claim_takeaways[id] : null;
  return latest === true && v && v.status === status && typeof v.text === 'string' ? v.text : '';
}
function readerEventNote(r,ev) {
  const key = String(ev && ev.seq);
  const v = r && r.event_notes && Object.prototype.hasOwnProperty.call(r.event_notes,key) ? r.event_notes[key] : null;
  return v && ev && v.event_type === ev.event_type ? v : null;
}
/* READER_PURE_END */
function readerReportState() {
  const select = language => {
    const side = (((DATA.translations || {})[language] || {}).report || {});
    const spec = (((S.i18n || {})[language] || {}).report || {});
    return Object.prototype.hasOwnProperty.call(side,'reader') ? side.reader : spec.reader;
  };
  let candidate = select(lang);
  let original = false;
  if (candidate === undefined && lang === 'en') { candidate = select('zh'); original = candidate !== undefined; }
  const state = validateReaderReport(candidate,S.snapshot_hash,E.length);
  return {...state,original};
}

function trReportBlock() {
  return (((DATA.translations || {})[lang] || {}).report) || (((S.i18n || {})[lang] || {}).report) || null;
}
function renderReport() {
  const f = frameAt(FRAMES.length - 1) || {};
  const statuses = f.claim_statuses || snapshotStatuses();
  const st = f.run_status || S.run_status || '';
  const B = S.budget || {};
  const attMax = B.max_attempts, costMax = B.max_cost_units;
  const att = f.attempts_remaining ?? B.attempts_remaining;
  const cost = f.cost_units_remaining ?? B.cost_units_remaining;
  const attV = (attMax != null && att != null) ? `${attMax - att}/${attMax}` : '—';
  const costV = (costMax != null && cost != null) ? `${(costMax - cost).toFixed(1)}/${costMax}` : '—';
  const tally = {};
  Object.values(S.attempts || {}).forEach(a => { const v = (a.verdict || {}).status; if (v) tally[v] = (tally[v] || 0) + 1; });
  const evByClaim = {};
  Object.values(S.evidence || {}).forEach(x => {
    const exp = S.experiments[x.experiment_id] || {};
    (exp.target_claim_ids || []).forEach(cid => { (evByClaim[cid] = evByClaim[cid] || []).push(x); });
  });
  const claims = Object.values(S.claims || {});
  const loot = Object.values(S.lessons || {});
  const activeLoot = loot.filter(x => x.status !== 'REVOKED');
  const revokedLoot = loot.filter(x => x.status === 'REVOKED');
  const n = tallyStatuses(statuses);
  const rb = trReportBlock() || {};
  const readerState = readerReportState();
  const reader = readerState.report;
  const headline = readerState.diagnostic === 'missing' ? (rb.headline || '') : '';
  const doItems = (rb.do && rb.do.length ? rb.do : activeLoot.map(x => trLessonF(x, 'recommendation'))).filter(Boolean);
  const dontItems = (rb.dont && rb.dont.length ? rb.dont : [
    ...revokedLoot.map(x => trLessonF(x, 'recommendation')),
    ...claims.filter(c => (evByClaim[c.id] || []).some(x => x.verdict_status === 'FAIL'))
      .map(c => `FAIL×${(evByClaim[c.id] || []).filter(x => x.verdict_status === 'FAIL').length} · ${claimLabel(c)}`),
  ]).filter(Boolean);
  const reqTag = c => `<span class="tag${c.required ? '' : ' dashed'}">${esc(c.required ? t('required') : t('optional'))}</span>`;
  $('reportBody').innerHTML = `
  <article class="reader-report" lang="${reader ? reader.language : lang}">
    ${reader ? `${readerState.original ? `<p class="reader-original">${esc(t('reader_original'))}</p>` : ''}<p class="reader-question">${esc(reader.question)}</p><h1>${esc(reader.title)}</h1><p class="reader-answer">${esc(reader.answer)}</p><p class="reader-note">${esc(reader.scope_note)}</p>${readerProseHtml(reader)}` : `<p class="reader-diagnostic" role="status">${esc(t('rd_' + readerState.diagnostic))}</p>${headline ? `<h2>${esc(t('reader_legacy'))}</h2><p>${esc(headline)}</p>` : ''}`}
  </article>
  <details class="card card-pad rpt-fold" id="reportAuditSummary"><summary>${esc(t('reader_audit'))}</summary>
  <div class="card card-pad">
    <div class="rpt-kicker">${esc(t('eb_kicker'))}</div>
    <h2 class="rpt-title">${esc(runStatusLabel(st) || '—')}</h2>
    <div class="rpt-topic">${esc(trTopic())}</div>
    ${st === 'SOLVED' ? `<p class="rpt-note">${esc(t('solved_note'))}</p>` : isFinalStatus(st) ? `<p class="rpt-note">${esc(L.final_note(runStatusLabel(st)))}</p>` : ''}

    <div class="rpt-facts">
      <span>${esc(t('eb_attempts'))} <b>${esc(attV)}</b></span>
      <span>${esc(t('eb_cost'))} <b>${esc(costV)}</b></span>
      <span>${esc(t('eb_duration'))} <b>${esc(matchDuration())}</b></span>
      <span>${esc(t('eb_lessons'))} <b>${f.n_lessons || 0}</b></span>
      <span>${esc(t('eb_events'))} <b>${E.length}</b></span>
    </div>
    <div class="tiny" style="margin-top:8px">${esc(t('rpt_verdicts'))}: ${Object.entries(tally).map(([k, v]) => `${esc(k)}×${v}`).join(' · ') || '—'}</div>
  </div>
  ${doItems.length ? `<div class="card card-pad"><div class="section-title"><h2>${esc(t('rpt_do'))}</h2></div><div class="rpt-do">${doItems.map(x => `<div class="rpt-step">${esc(x)}</div>`).join('')}</div></div>` : ''}
  ${dontItems.length ? `<div class="card card-pad"><div class="section-title"><h2>${esc(t('rpt_dont'))}</h2></div><div class="rpt-do rpt-dont">${dontItems.map(x => `<div class="rpt-step">${esc(x)}</div>`).join('')}</div></div>` : ''}
  <div class="card card-pad">
    <div class="section-title"><h2>${esc(t('sec_takeaways'))}</h2></div>
    <div class="rpt-claims">${claims.map(c => {
      const cs = statuses[c.id] || c.status || 'OPEN';
      const conc = trClaimConclusion(c) || trClaimF(c, 'statement') || '';
      return `<div class="rpt-claim"><span class="rpt-mark mono">${esc(claimNo(c.id))}</span><b>${esc(claimLabel(c))} ${reqTag(c)}</b><span>${status(cs)}</span><span class="rpt-conc">${esc(conc)}</span></div>`;
    }).join('')}</div>
  </div>
  <details class="card card-pad rpt-fold"><summary class="section-title"><h2>${esc(t('rpt_details'))}</h2></summary>
    ${claims.map(c => {
      const cs = statuses[c.id] || c.status || 'OPEN';
      const conc = trClaimConclusion(c);
      const evs = evByClaim[c.id] || [];
      return `<div class="rpt-cblock">
        <div class="rpt-chead"><span class="rpt-mark mono">${esc(claimNo(c.id))}</span><b>${esc(claimLabel(c))}</b>${reqTag(c)}${status(cs)}</div>
        ${conc ? `<div class="rpt-conc-line">${esc(conc)}</div>` : ''}
        <div class="rpt-stmt">${esc(trClaimF(c, 'statement') || '')}</div>
        ${evs.length ? evs.map(x => `<div class="rpt-ev">${status(x.verdict_status)}<span class="tiny">${esc(reasonSummary(x))}</span>${evExtras(x)}</div>`).join('') : `<div class="tiny">—</div>`}
      </div>`;
    }).join('')}
  </details>
  ${loot.length ? `<details class="card card-pad rpt-fold"><summary class="section-title"><h2>${esc(t('sec_loot_final'))}</h2></summary>
    ${loot.map(x => `<div class="rpt-cblock"><div class="rpt-chead"><b>${esc(trLessonF(x, 'recommendation'))}</b>${status(x.status)}</div><div class="rpt-stmt">${esc(trLessonF(x, 'observation'))}</div></div>`).join('')}
  </details>` : ''}</details>`;
}
function renderDetailTabs() {
  $('goalRoot').innerHTML = `${esc(t('root'))} ${status(S.goal_evaluation.root_status)}`;
  const nodes = S.goal_evaluation.nodes, depths = graphDepth(nodes, S.goal_evaluation.root_id);
  $('goalTree').innerHTML = nodes.slice().sort((a, b) => (depths[a.id] ?? 0) - (depths[b.id] ?? 0)).map(n => { const title = n.claim_id && S.claims[n.claim_id] ? (trClaimF(S.claims[n.claim_id], 'statement') || n.title) : (n.title === S.topic ? trTopic() : n.title); return `<div class="goal-node ${n.status === 'PASS' ? 'pass' : n.status === 'FAIL' ? 'fail' : 'open'} indent-${Math.min(3, depths[n.id] ?? 0)}"><div class="item-head"><div><b>${esc(title)}</b><div class="item-meta mono">${esc(n.id)} · ${esc(n.kind)}${n.claim_id ? ' · ' + esc(n.claim_id) : ''}</div></div>${status(n.status)}</div></div>`; }).join('');
  const gaps = S.verifier_gaps;
  $('verifierCoverage').innerHTML = gaps.length ? `<div class="item"><b style="color:var(--warn)">${esc(t('cov_missing'))}</b><div class="mono tiny" style="margin-top:8px">${gaps.map(esc).join('<br>')}</div></div>` : `<div class="item"><b style="color:var(--ok)">${esc(t('cov_full'))}</b></div>`;
  $('currentState').textContent = S.current_state_id;
  const states = Object.values(S.states).sort((a, b) => a.seq - b.seq);
  $('executionList').innerHTML = states.map(st => { const exp = st.experiment_id ? S.experiments[st.experiment_id] : null; const rb = st.rollback || []; return `<div class="item"><div class="item-head"><div><div class="item-title mono">${esc(st.id)}</div><div class="item-meta">parents: ${st.parent_state_ids.length ? st.parent_state_ids.map(esc).join(', ') : 'genesis'}</div></div>${st.id === S.current_state_id ? '<span class="status ACTIVE">CURRENT</span>' : ''}</div>${exp ? `<div style="margin-top:6px"><b>${esc(trExpTitle(exp))}</b> · ${status(exp.last_verdict?.status || exp.status)}<div class="tiny">${esc(exp.id)} → ${exp.target_claim_ids.map(esc).join(', ')}</div></div>` : ''}${rb.length ? `<div class="tiny" style="color:var(--void);margin-top:6px">rollback: ${rb.map(x => esc(x.claim_id) + ' ← ' + esc(x.source_claim_id || x.previous_status)).join('; ')}</div>` : ''}</div>`; }).join('');
  const ruleCount = c => ['preconditions','invalid_if','pass_if','fail_if','guardrails'].reduce((n, k) => n + (c[k]?.all?.length || 0) + (c[k]?.any?.length || 0), 0);
  $('contractRows').innerHTML = Object.values(S.contracts).map(c => `<tr><td class="mono">${esc(c.id)}</td><td>${esc(c.target_claim_id)}</td><td>${esc(c.version)}</td><td>${c.repetition.min_passes} pass / ${c.repetition.min_independent_contexts} ctx</td><td>${ruleCount(c)} checks · ${esc(c.kind)}</td></tr>`).join('');
  $('attemptRows').innerHTML = Object.values(S.attempts).sort((a, b) => String(a.id).localeCompare(String(b.id))).map(a => `<tr><td class="mono">${esc(a.id)}</td><td>${esc(a.experiment_id)}</td><td>${esc(a.context_id)}</td><td>${status(a.status)}</td><td>${status(a.verdict?.status || 'MISSING')}</td><td>${esc(a.verdict?.reason_code || '—')}</td><td class="mono">${esc(a.to_state_id || '—')}</td></tr>`).join('');
  const evidence = Object.values(S.evidence);
  $('evidenceList').innerHTML = evidence.length ? evidence.map(x => `<div class="item"><div class="item-head"><div><div class="item-title">${esc(reasonSummary(x))}</div><div class="item-meta mono">${esc(x.id)} · ${esc(x.contract_id)} · ${esc(x.context_id)} · ${esc(x.reason_code)}</div></div>${status(x.verdict_status)}</div>${reasonExtra(x) ? `<div class="tiny" style="margin-top:6px">${esc(reasonExtra(x))}</div>` : ''}${evExtras(x)}</div>`).join('') : `<div class="empty">${esc(t('empty_evidence'))}</div>`;
  const lessons = Object.values(S.lessons); const usage = S.lesson_usage || {};
  $('lessonList').innerHTML = lessons.length ? lessons.map(x => { const u = usage[x.id]; return `<div class="item"><div class="item-head"><div><div class="item-title">${esc(trLessonF(x, 'recommendation'))}</div><div class="item-meta mono">${esc(x.id)} · ${esc(L.evidence_n((x.evidence_ids || []).length))}${u ? ` · ${esc(L.cited_n(u.experiment_ids.length))}` : ''}</div></div>${status(x.status)}</div><div class="tiny" style="margin-top:6px">${esc(trLessonF(x, 'observation'))}</div></div>`; }).join('') : `<div class="empty">${esc(t('empty_lessons'))}</div>`;
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
  $('eventList').innerHTML = rows.length ? rows.map(ev => { const n = narrate(ev, true); return `<details class="ev-details" data-seq="${ev.seq}"${openSeqs.has(String(ev.seq)) ? ' open' : ''}><summary><span class="mono tiny">#${ev.seq}</span><span class="ev-type ${n.cls}">${esc(ev.event_type)}</span><span class="tiny">${esc(ev.actor)} · ${esc((ev.ts || '').slice(11, 19))}</span><span class="ev-sum">${esc(n.feed)}</span></summary><pre class="ev-json mono">${esc(JSON.stringify(ev.data, null, 2))}</pre></details>`; }).join('') : `<div class="empty">—</div>`;
}

/* ================= boot ================= */
/* A render failure must be visible: say so in the graph area and mark the
   status chip, instead of leaving an empty workbench that still looks live. */
let BOOT_SHOWN = false;
function showBootError(error) {
  if (!BOOT_SHOWN) console.error('Observatory failed to render', error);
  BOOT_SHOWN = true;
  BOOT_ERROR = error;  /* sticky: later resizes, keys and language changes keep this state */
  const box = $('graphEmpty');
  box.textContent = t('boot_error');
  box.classList.add('error');
  box.hidden = false;
  $('liveChip').className = 'livechip stale';
  $('liveText').textContent = t('load_failed');
}
applyStaticI18n();
$('langBtn').addEventListener('click', () => setLang(lang === 'zh' ? 'en' : 'zh'));
if (BOOT_ERROR) showBootError(BOOT_ERROR);
else {
  try {
    deriveTimeline(); renderArenaStatic(); initDeck(); initTabs(); initArenaPointer(); initGraphViewport(); renderDetailTabs(); renderWaiting();
    renderUnitCard(null);
    setPlayButton(false);
    const hashSeq = (location.hash || '').match(/seq=([0-9]+)/);
    if (FRAMES.length) showIndex(hashSeq ? Number(hashSeq[1]) - 1 : FRAMES.length - 1, { feedRebuild: true, instant: true });
    else renderSnapshotOnly();
    if (new URLSearchParams(location.search).get('view') === 'report') openView('report');
    if (location.protocol === 'http:' || location.protocol === 'https:') setInterval(poll, 2000);
  } catch (error) { showBootError(error); }
}
window.addEventListener('beforeprint', () => document.querySelectorAll('details').forEach(d => { d.open = true; }));
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
    atomic_write_json(workspace.report_snapshot_path, _finite(public_snapshot))
    topic = html.escape(str(snapshot.get("topic") or "Sisyfus Research"))
    payload = _json_for_script(public_snapshot)
    document = (
        _TEMPLATE
        .replace("__SISYFUS_THEME_ID__", ARENA_THEME_ID)
        .replace("__SISYFUS_THEME__", ARENA_THEME_CSS)
        .replace("__TOPIC__", topic)
        .replace("__PAYLOAD__", payload)
    )
    activity = ensure_activity(
        workspace.root,
        title=str(snapshot.get("topic") or "Sisyfus Research"),
    )
    document = document.replace(
        "</body>",
        activity_overlay_html(activity) + "\n</body>",
    )
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
    activity_root: str | None = None
    verbose: bool = False

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        path = self.path.split("?", 1)[0]
        if path in {"/activity.json", "/activity-events.json"}:
            self._serve_activity_projection(path)
            return
        if path.startswith("/artifact/"):
            self._serve_artifact(path[len("/artifact/"):])
            return
        if self.refresh_callback is not None and path in {"/", "/index.html", "/snapshot.json"}:
            self.refresh_callback()
        super().do_GET()

    def _serve_activity_projection(self, request_path: str) -> None:
        root = type(self).activity_root
        if not root:
            self.send_error(404)
            return
        source = (
            activity_state_path(root)
            if request_path == "/activity.json"
            else activity_events_projection_path(root)
        )
        try:
            data = source.read_bytes()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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
            "activity_root": str(workspace.root),
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
