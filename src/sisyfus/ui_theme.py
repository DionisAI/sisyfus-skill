"""Shared visual language for bootstrap Mission Control and the full research workspace."""

from __future__ import annotations

ARENA_THEME_ID = "sisyfus-research-workspace-v2"

# Single source of truth for palette, typography, the page shell (top bar,
# stage, side column, replay deck, latest line, tabs) and motion. It is injected
# verbatim into both the bootstrap page and the full claim graph so the two
# documents read as one quiet, warm-paper research workbench. Token values
# follow the Tech Lead chat page (workers/lead_chat_page.py) so research and
# chat read as one product: same paper, ink, line, accent and success green.
ARENA_THEME_CSS = r"""
:root {
  color-scheme: light;
  --paper:#faf9f5;          /* chat --paper */
  --paper-raised:#f6f3ed;   /* chat proposal / card band */
  --surface:#fdfcf8;        /* chat composer & inputs */
  --surface-hover:#f0eee7;  /* chat --side, secondary hover */
  --sunk:#e8e3d9;           /* chat nav hover */
  --line:#ded9cf;           /* chat --line */
  --line-strong:#c8b6a5;    /* chat strong border */
  --ink:#302d29;            /* chat --ink */
  --ink-2:#63584c;          /* chat secondary text */
  --muted:#71695f;          /* chat --muted */
  --faint:#8b8174;          /* chat placeholder: decorative glyphs only, text uses --muted */
  --accent:#995638;         /* chat --accent */
  --accent-ink:#7c432b;     /* chat --accent-hover */
  --accent-soft:#f4e9df;    /* chat --wash */
  --accent-line:#e2c9b7;
  --ok-line:#b7c6b3;
  --bad-line:#dcb3a8;
  --warn-line:#d9c28c;
  --ok:#486452;             /* chat --good */
  --ok-soft:#eef2e9;        /* chat checked task */
  --bad:#a34335;            /* chat --bad */
  --bad-soft:#f6e4df;
  --warn:#8a5f12;
  --warn-soft:#f5ecd8;
  --void:#655f78;
  --void-soft:#ece9f0;
  --open:#6b635a;
  --open-soft:#eee9df;      /* chat user message */
  --edge:#9c8a78;           /* graph edge, shared with chat; 3.1:1 on paper */
  --edge-strong:#7d6e60;    /* highlighted edges and arrowheads */
  --focus:#995638;
  /* legacy token names kept so older consumers resolve to the light palette */
  --arena:var(--paper);
  --arena-deep:var(--paper);
  --panel:var(--paper-raised);
  --panel-strong:var(--surface);
  --radiant:var(--ok);
  --dire:var(--bad);
  --gold:var(--accent);
  --amber:var(--warn);
  --ghost:var(--void);
  --hp:var(--accent);
  --mana:var(--open);
  --stage-height:min(76vh, 780px);
  --right-column:368px;
  --radius:10px;
  --shadow-soft:0 1px 2px rgba(48,45,41,.04), 0 6px 18px rgba(71,54,34,.06);
  --shadow-deep:0 10px 32px rgba(48,45,41,.12);
  --font-sans:"PingFang SC","Microsoft YaHei","Noto Sans CJK SC","Hiragino Sans GB","Source Han Sans SC",-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,sans-serif;
  --font-serif:"Songti SC","STSong","Noto Serif CJK SC","Source Han Serif SC",Georgia,serif;
  --font-mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --ease-out:cubic-bezier(.16,1,.3,1);
}
* { box-sizing:border-box; }
html { min-height:100%; background:var(--paper); -webkit-text-size-adjust:100%; }
body {
  min-height:100vh;
  margin:0;
  background:var(--paper);
  color:var(--ink);
  font-family:var(--font-sans);
  font-size:14px;
  line-height:1.65;
  -webkit-font-smoothing:antialiased;
}
button,input,select { font:inherit; color:inherit; }
button { cursor:pointer; }
a { color:var(--accent); text-underline-offset:2px; }
a:hover { color:var(--accent-ink); }
[hidden] { display:none !important; }
.caps { font-size:12px; font-weight:600; letter-spacing:.02em; color:var(--muted); }
.mono { font-family:var(--font-mono); font-size:.92em; }
:focus:not(:focus-visible) { outline:none; }
:focus-visible { outline:2px solid var(--focus); outline-offset:2px; border-radius:4px; }

/* ---------- page shell ---------- */
.topbar { display:flex; align-items:center; flex-wrap:wrap; gap:12px 22px; padding:14px 24px;
  background:var(--paper-raised); border-bottom:1px solid var(--line); }
.brand { display:flex; align-items:center; gap:8px; font-size:12.5px; color:var(--muted); white-space:nowrap; }
.brand-mark { flex:0 0 auto; font:22px/1 Georgia,serif; color:var(--accent); }  /* chat's ✳ mark */
.headline { flex:1 1 380px; min-width:0; }
.headline h1 { margin:0; font-family:var(--font-serif); font-size:20px; font-weight:400; line-height:1.45;
  color:var(--ink); overflow-wrap:anywhere; display:-webkit-box; -webkit-line-clamp:2;
  -webkit-box-orient:vertical; overflow:hidden; }
.headline .sub { margin-top:5px; display:flex; flex-wrap:wrap; align-items:center; gap:4px 14px;
  font-size:12.5px; color:var(--muted); }
.tally b { color:var(--ink); font-weight:600; font-variant-numeric:tabular-nums; }
.budget { display:grid; gap:6px; min-width:200px; font-size:12px; color:var(--muted); }
.budget-row { display:grid; grid-template-columns:1fr 64px; align-items:center; gap:10px; white-space:nowrap; }
.meter { position:relative; height:3px; border-radius:2px; background:var(--sunk); overflow:hidden; }
.meter > i { position:absolute; inset:0; transform-origin:left; background:var(--line-strong);
  transition:transform .4s var(--ease-out); }
.top-actions { display:flex; align-items:center; gap:8px; margin-left:auto; }
.livechip { display:inline-flex; align-items:center; gap:7px; height:30px; padding:0 12px;
  border:1px solid var(--line); border-radius:999px; background:var(--surface);
  font-size:12.5px; color:var(--ink-2); white-space:nowrap; }
.livechip .dot { width:7px; height:7px; border-radius:50%; background:var(--ok); flex:0 0 auto; }
.livechip.replaying .dot,.livechip.waiting .dot { background:var(--warn); }
.livechip.stale .dot { background:var(--void); }
.livechip.ended .dot { background:var(--open); }
.lang-btn,.btn { height:30px; padding:0 12px; border:1px solid var(--line); border-radius:8px;
  background:var(--surface); color:var(--ink-2); font-size:12.5px; white-space:nowrap; }
.lang-btn:hover,.btn:hover { border-color:var(--line-strong); background:var(--surface-hover); color:var(--ink); }
.btn[disabled] { opacity:.5; cursor:not-allowed; }

.stage { display:grid; grid-template-columns:minmax(0,1fr) var(--right-column); min-height:0; }
.arena-wrap { position:relative; min-width:0; display:flex; flex-direction:column;
  background:var(--paper); border-right:1px solid var(--line); }
.rightcol { display:flex; flex-direction:column; min-height:0; height:var(--stage-height);
  background:var(--paper-raised); overflow-y:auto; overscroll-behavior:contain; }
.col-h { display:flex; justify-content:space-between; align-items:baseline; gap:8px;
  padding:14px 20px 6px; font-size:12px; font-weight:600; color:var(--muted); }
.col-h + * { flex:0 0 auto; }
.feed-row { display:flex; gap:10px; align-items:baseline; width:100%; padding:7px 20px 7px 18px;
  font-size:13px; line-height:1.55; color:var(--ink-2); text-align:left;
  background:transparent; border:0; border-left:2px solid transparent; }

/* Live projections may refresh their structural DOM on heartbeat ticks. An
   entry animation on the base row would therefore restart forever even when
   no event changed. Feed entry motion must be explicitly opt-in for a newly
   inserted event; stable rows never animate merely because polling occurred. */
.feed-row { animation:none !important; }
.feed-row.feed-new { animation:feedin .35s var(--ease-out) !important; }
@keyframes feedin { from { opacity:0; transform:translateY(-3px); } }

.feed-row .seq { flex:0 0 34px; color:var(--muted); font-size:11px; font-family:var(--font-mono); }
.feed-row .ts { margin-left:auto; padding-left:8px; color:var(--muted); font-size:11px;
  font-family:var(--font-mono); white-space:nowrap; }

.deck { display:flex; align-items:center; gap:10px; padding:10px 24px;
  background:var(--paper-raised); border-top:1px solid var(--line); border-bottom:1px solid var(--line); }
.deck button,.deck select { height:30px; min-width:34px; padding:0 10px; border:1px solid var(--line);
  border-radius:8px; background:var(--surface); color:var(--ink-2); font-size:12.5px; }
.deck button:hover:not([disabled]) { border-color:var(--line-strong); color:var(--ink); }
.deck button.active { background:var(--accent-soft); border-color:var(--accent-line); color:var(--accent-ink); }
.deck button[disabled] { opacity:.5; cursor:not-allowed; }
.timeline { position:relative; flex:1; min-width:120px; height:36px; }
.tl-track { position:absolute; left:0; right:0; top:12px; height:4px; border-radius:2px; background:var(--sunk); }
.tl-fill { position:absolute; left:0; top:12px; height:4px; width:0; border-radius:2px; background:var(--accent); }
.tl-cursor { position:absolute; top:7px; left:0; width:14px; height:14px; border-radius:50%;
  background:var(--surface); border:2px solid var(--accent); transform:translateX(-50%);
  pointer-events:none; z-index:2; }
.tl-times { position:absolute; left:0; right:0; top:22px; display:flex; justify-content:space-between;
  font-size:10.5px; color:var(--muted); pointer-events:none; }
.deck .stamp { flex:0 1 300px; min-width:0; text-align:right; font-size:11.5px; color:var(--muted);
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.caster { display:flex; gap:12px; align-items:baseline; padding:10px 24px 12px;
  background:var(--paper); border-bottom:1px solid var(--line); }
.caster .tag { flex:0 0 auto; font-size:12px; font-weight:600; color:var(--muted); }
#casterLine { font-size:14px; line-height:1.65; color:var(--ink); overflow-wrap:anywhere; }
.tabs { display:flex; gap:2px; padding:8px 24px 0; overflow-x:auto; scrollbar-width:none;
  background:var(--paper); border-bottom:1px solid var(--line); }
.tabs::-webkit-scrollbar { display:none; }
.tab { flex:0 0 auto; padding:8px 14px 9px; border:0; border-bottom:2px solid transparent;
  background:transparent; color:var(--muted); font-size:13.5px; }
.tab:hover:not([disabled]) { color:var(--ink); }
.tab.active { color:var(--ink); font-weight:600; border-bottom-color:var(--accent); }
.tab[disabled] { opacity:.45; cursor:not-allowed; }

/* ---------- status tags: always text + glyph, never colour alone ---------- */
.status { --tone:var(--open); --tone-bg:var(--open-soft);
  display:inline-flex; align-items:center; gap:4px; height:22px; padding:0 8px; border-radius:999px;
  font-size:12px; font-weight:600; line-height:1; white-space:nowrap;
  color:var(--tone); background:var(--tone-bg); }
.status .g { font-size:11px; }
.status.SUPPORTED,.status.PASS,.status.SOLVED,.status.DONE,.status.PROMOTED,.status.COMPLETED,.status.READY { --tone:var(--ok); --tone-bg:var(--ok-soft); }
.status.REFUTED,.status.FAIL,.status.FAILED,.status.REVOKED { --tone:var(--bad); --tone-bg:var(--bad-soft); }
.status.INCONCLUSIVE,.status.BLOCKED,.status.EXHAUSTED,.status.BUDGET_EXHAUSTED,.status.WAITING,.status.CONTESTED,.status.NEEDS_USER,.status.PAUSED { --tone:var(--warn); --tone-bg:var(--warn-soft); }
.status.INVALID,.status.INVALIDATED,.status.ERROR { --tone:var(--void); --tone-bg:var(--void-soft); }
.status.ACTIVE,.status.RUNNING { --tone:var(--accent-ink); --tone-bg:var(--accent-soft); }

@media (max-width:960px) {
  .stage { grid-template-columns:1fr; }
  .arena-wrap { border-right:0; }
  .rightcol { height:auto; overflow:visible; border-top:1px solid var(--line); }
  .topbar { padding:12px 16px; }
  .budget { flex:1 1 100%; order:4; grid-template-columns:1fr 1fr; gap:6px 18px; }
  .deck { flex-wrap:wrap; padding:10px 16px; }
  .timeline { order:5; flex:1 1 100%; }
  .deck .stamp { display:none; }
  .caster { padding:10px 16px; }
  .tabs { padding:4px 10px 0; }
}
@media (max-width:540px) {
  .headline { flex-basis:100%; }
  .headline h1 { font-size:17px; }
  .budget { grid-template-columns:1fr; }
  .top-actions { margin-left:0; }
  .brand > span:last-child { display:none; }
}
@media (prefers-reduced-motion:reduce) {
  *,*::before,*::after { animation-duration:.001ms !important; animation-iteration-count:1 !important;
    transition-duration:.001ms !important; scroll-behavior:auto !important; }
  .feed-row.feed-new { animation:none !important; }
}
"""
