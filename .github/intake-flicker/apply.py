from __future__ import annotations

import re
from pathlib import Path


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"unexpected {label} marker count: {count}")
    return text.replace(old, new, 1)


activity_path = Path("src/sisyfus/activity.py")
activity = activity_path.read_text(encoding="utf-8")

activity = replace_once(
    activity,
    ".feed-row { display:flex; gap:9px; padding:5px 14px; font-size:12px; line-height:1.45;\n"
    "  align-items:baseline; animation:feedin .35s var(--ease-out); border-left:3px solid transparent; }\n"
    "@keyframes feedin { from { opacity:0; transform:translateX(26px); } }",
    ".feed-row { display:flex; gap:9px; padding:5px 14px; font-size:12px; line-height:1.45;\n"
    "  align-items:baseline; border-left:3px solid transparent; }\n"
    ".feed-row.feed-new { animation:feedin .35s var(--ease-out); }\n"
    "@keyframes feedin { from { opacity:0; transform:translateX(26px); } }",
    label="feed animation CSS",
)

activity = replace_once(
    activity,
    "let A = {}, events = [], misses = 0, lang = localStorage.getItem('sisyfus-lang') || 'zh';",
    "let A = {}, events = [], misses = 0, lang = localStorage.getItem('sisyfus-lang') || 'zh';\n"
    "let mapRenderKey = null, feedRenderKey = null, waitingRenderKey = null;\n"
    "let feedInitialized = false, renderedFeedKeys = new Set();",
    label="render cache declaration",
)

activity = replace_once(
    activity,
    "function renderMap(){\n"
    " const active=gateIndex(), states=GATES.map((g,i)=>stateFor(g,i,active));\n",
    "function renderMap(){\n"
    " const active=gateIndex(), states=GATES.map((g,i)=>stateFor(g,i,active));\n"
    " const nextKey=JSON.stringify([lang,active,states,String(A.status||''),A.message||'']);\n"
    " if(nextKey===mapRenderKey)return;\n"
    " mapRenderKey=nextKey;\n",
    label="map render cache",
)

feed_pattern = re.compile(
    r"function renderFeed\(\)\{\n.*?\n\}\nfunction renderWaiting\(\)\{",
    re.DOTALL,
)
feed_replacement = """function feedEventKey(x){
 return JSON.stringify([
  x.seq||'',x.ts||'',x.phase||'',x.status||'',x.operation||'',x.error||x.message||''
 ]);
}
function renderFeed(){
 const source=[...events].reverse();
 const fallback=events.length?'':String(A.message||'Mission Control is online.');
 const nextKey=JSON.stringify([source.map(feedEventKey),fallback]);
 $('feedCount').textContent=`${events.length}`;
 if(nextKey===feedRenderKey)return;
 const nextKeys=new Set(source.map(feedEventKey));
 const animateNew=feedInitialized;
 $('feed').innerHTML=source.map(x=>{
  const st=String(x.status||'').toUpperCase(), cls=st==='ERROR'?'miss':st==='NEEDS_USER'?'soft':st==='COMPLETED'||st==='READY'?'pass':'info';
  const key=feedEventKey(x), isNew=animateNew&&!renderedFeedKeys.has(key);
  return `<div class="feed-row ${cls}${isNew?' feed-new':''}"><span class="seq">#${esc(x.seq||'')}</span><span><b>${esc(x.phase||'')} · ${esc(x.operation||'')}</b><br>${esc(x.error||x.message||'')}</span><span class="ts">${esc((x.ts||'').slice(11,19))}</span></div>`;
 }).join('')||`<div class="feed-row info"><span class="seq">#0</span><span>${esc(fallback)}</span></div>`;
 renderedFeedKeys=nextKeys;
 feedRenderKey=nextKey;
 feedInitialized=true;
}
function renderWaiting(){"""
activity, count = feed_pattern.subn(lambda _match: feed_replacement, activity, count=1)
if count != 1:
    raise SystemExit(f"unexpected renderFeed function count: {count}")

activity = replace_once(
    activity,
    "function renderWaiting(){\n"
    " const questions=((A.metadata||{}).clarification_questions||[]).map(String);\n"
    " const waiting=String(A.status||'').toUpperCase()==='NEEDS_USER';\n"
    " $('waitState').textContent=waiting?'NEEDS_USER':'READY';",
    "function renderWaiting(){\n"
    " const questions=((A.metadata||{}).clarification_questions||[]).map(String);\n"
    " const waiting=String(A.status||'').toUpperCase()==='NEEDS_USER';\n"
    " const nextKey=JSON.stringify([lang,waiting,questions,A.detail||'']);\n"
    " if(nextKey===waitingRenderKey)return;\n"
    " waitingRenderKey=nextKey;\n"
    " $('waitState').textContent=waiting?'NEEDS_USER':'READY';",
    label="waiting render cache",
)

activity_path.write_text(activity, encoding="utf-8")

Path("tests/test_intake_frontend_stability.py").write_text(
    '''from __future__ import annotations

import re
from pathlib import Path

from sisyfus.activity import render_activity_monitor


def test_intake_monitor_does_not_restart_feed_animation_on_clock_ticks(
    tmp_path: Path,
) -> None:
    html = render_activity_monitor(tmp_path).read_text(encoding="utf-8")

    base_rule = re.search(r"\\.feed-row \\{(?P<body>.*?)\\}", html, re.DOTALL)
    assert base_rule is not None
    assert "animation:" not in base_rule.group("body")
    assert ".feed-row.feed-new { animation:feedin" in html

    assert "let feedInitialized = false, renderedFeedKeys = new Set();" in html
    assert "if(nextKey===feedRenderKey)return;" in html
    assert "isNew=animateNew&&!renderedFeedKeys.has(key)" in html


def test_intake_monitor_keys_structural_dom_renders(tmp_path: Path) -> None:
    html = render_activity_monitor(tmp_path).read_text(encoding="utf-8")

    # The 500 ms clock refresh may update elapsed/heartbeat text, but it must
    # not reconstruct the SVG map, Match Feed, or waiting panel when their
    # underlying data has not changed.
    assert "if(nextKey===mapRenderKey)return;" in html
    assert "if(nextKey===feedRenderKey)return;" in html
    assert "if(nextKey===waitingRenderKey)return;" in html
    assert "setInterval(render,500);" in html
''',
    encoding="utf-8",
)

notes_path = Path("RELEASE_NOTES_v0.8.1.md")
notes = notes_path.read_text(encoding="utf-8")
section = """

## Mission Control frontend stability

- Fixed the Intake Match Feed repeatedly replaying its entry animation on every
  500 ms heartbeat/clock render.
- Preflight map, feed, and waiting-panel DOM are now keyed and only rebuilt when
  their underlying state changes.
- The initial feed is stable; only genuinely new activity events receive the
  one-shot `feedin` animation.
"""
if "## Mission Control frontend stability" not in notes:
    notes = notes.rstrip() + section + "\n"
notes_path.write_text(notes, encoding="utf-8")
