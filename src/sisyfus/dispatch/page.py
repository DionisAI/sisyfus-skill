"""Phone page for dispatch: one-column Chinese UI in the shared warm-paper theme, installable to the home screen."""
from __future__ import annotations

import json
import math
import struct
import zlib
from functools import lru_cache

from ..activity import _ACTIVITY_LABELS_JS
from ..ui_theme import ARENA_THEME_CSS

MANIFEST = json.dumps({
    "name": "Sisyfus 研究调度", "short_name": "研究调度", "start_url": "/", "scope": "/",
    "display": "standalone", "background_color": "#faf9f5", "theme_color": "#faf9f5", "lang": "zh-CN",
    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"},
              {"src": "/apple-touch-icon.png", "sizes": "180x180", "type": "image/png"}],
}, ensure_ascii=False)

ICON_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" '
            'fill="#faf9f5"/><g stroke="#995638" stroke-width="6" stroke-linecap="round">'
            '<line x1="32" y1="14" x2="32" y2="50"/><line x1="16.4" y1="23" x2="47.6" y2="41"/>'
            '<line x1="16.4" y1="41" x2="47.6" y2="23"/></g></svg>')


@lru_cache(maxsize=1)
def touch_icon() -> bytes:
    """180x180 PNG of the ✳ mark (iOS home screens need PNG, not SVG); stdlib only."""
    size, half, reach, width = 180, 90.0, 52.0, 8.0
    paper, accent = (0xFA, 0xF9, 0xF5), (0x99, 0x56, 0x38)
    angles = [math.radians(a) for a in (90, 30, 150)]
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            hits = 0
            for sy in (0.25, 0.75):
                for sx in (0.25, 0.75):
                    px, py = x + sx - half, y + sy - half
                    for angle in angles:
                        dx, dy = math.cos(angle), math.sin(angle)
                        along = px * dx + py * dy
                        across = abs(px * dy - py * dx)
                        if abs(along) <= reach and across <= width:
                            hits += 1
                            break
            t = hits / 4
            row += bytes(round(p + (a - p) * t) for p, a in zip(paper, accent))
        rows.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
            + chunk(b"IEND", b""))



_PAGE_CSS = r"""
body { min-height:100vh; min-height:100dvh; }
.app { max-width:640px; margin:0 auto; padding:0 16px max(28px, env(safe-area-inset-bottom)); }
.bar { position:sticky; top:0; z-index:5; display:flex; align-items:center; gap:10px; margin:0 -16px;
  padding:max(12px, env(safe-area-inset-top)) 16px 10px; background:var(--paper); border-bottom:1px solid var(--line); }
.bar .mark { font:24px/1 Georgia,serif; color:var(--accent); }
.bar .name { font:400 18px/1.3 var(--font-serif); color:var(--ink); }
.bar .conn { margin-left:auto; display:flex; align-items:center; gap:6px; font-size:12px; color:var(--muted); }
.bar .conn i { width:7px; height:7px; border-radius:50%; background:var(--ok); }
.bar .conn.lost i { background:var(--warn); }
.bar .out { border:0; background:none; color:var(--muted); font-size:12px; padding:4px 0 4px 8px; }
h1.page { margin:18px 0 6px; font:400 22px/1.45 var(--font-serif); color:var(--ink); overflow-wrap:anywhere; }
.sub { font-size:12.5px; color:var(--muted); }
.section { margin-top:26px; }
.section > h2 { margin:0 0 8px; font-size:13px; font-weight:600; color:var(--muted); }
.card { display:block; width:100%; margin:0 0 10px; padding:13px 14px; text-align:left; color:inherit;
  text-decoration:none; background:var(--surface); border:1px solid var(--line); border-radius:12px; }
button.card:active,a.card:active { background:var(--surface-hover); }
.card .top { display:flex; align-items:flex-start; gap:10px; }
.card .ttl { flex:1; min-width:0; font-size:15px; font-weight:600; color:var(--ink); line-height:1.45;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; overflow-wrap:anywhere; }
.card .meta { margin-top:4px; font-size:12px; color:var(--muted); }
.card .snip { margin-top:6px; font-size:13px; color:var(--ink-2); line-height:1.55;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; overflow-wrap:anywhere; }
.pill { --tone:var(--open); --tone-bg:var(--open-soft); flex:0 0 auto; display:inline-flex; align-items:center; gap:5px;
  height:24px; padding:0 9px; border-radius:999px; font-size:12px; font-weight:600; color:var(--tone); background:var(--tone-bg); white-space:nowrap; }
.pill::before { content:''; width:6px; height:6px; border-radius:50%; background:currentColor; }
.pill.run { --tone:var(--accent-ink); --tone-bg:var(--accent-soft); }
.pill.ok { --tone:var(--ok); --tone-bg:var(--ok-soft); }
.pill.bad { --tone:var(--bad); --tone-bg:var(--bad-soft); }
.pill.warn { --tone:var(--warn); --tone-bg:var(--warn-soft); }
.pill.void { --tone:var(--void); --tone-bg:var(--void-soft); }
.primary { display:block; width:100%; height:48px; border:0; border-radius:12px; background:var(--accent); color:#fffaf6;
  font-size:16px; font-weight:600; }
.primary:active { background:var(--accent-ink); }
.primary[disabled] { opacity:.5; }
.secondary { height:40px; padding:0 16px; border:1px solid var(--line-strong); border-radius:10px; background:var(--surface);
  color:var(--ink); font-size:14px; }
.secondary.danger { color:var(--bad); border-color:var(--bad-line); }
label.field { display:block; margin:16px 0 6px; font-size:13px; font-weight:600; color:var(--ink-2); }
select,textarea,input[type=password] { width:100%; padding:12px; font-family:inherit; border:1px solid var(--line-strong); border-radius:10px;
  background:var(--surface); color:var(--ink); font-size:16px; line-height:1.5; }
textarea { min-height:140px; resize:vertical; }
.note { margin:12px 0; padding:10px 12px; border-left:2px solid var(--accent-line); background:var(--paper-raised);
  font-size:13px; color:var(--ink-2); line-height:1.6; border-radius:0 8px 8px 0; }
.check { display:flex; gap:10px; align-items:flex-start; margin:14px 0; font-size:14px; color:var(--ink-2); }
.check input { width:20px; height:20px; margin:2px 0 0; accent-color:var(--accent); }
.err { margin:10px 0; color:var(--bad); font-size:13.5px; }
.err:empty { display:none; }
.back { display:inline-block; margin-top:14px; color:var(--accent); font-size:14px; text-decoration:none; }
.reply { margin-top:18px; }
.msg { margin-top:10px; padding:14px; background:var(--surface); border:1px solid var(--line); border-radius:12px;
  font-size:14.5px; line-height:1.7; color:var(--ink); overflow-wrap:anywhere; }
.msg p { margin:0 0 10px; }
.msg p:last-child { margin-bottom:0; }
.msg h4 { margin:14px 0 6px; font-size:14.5px; font-weight:600; }
.msg ul,.msg ol { margin:0 0 10px; padding-left:20px; }
.msg li { margin:3px 0; }
.msg code { font-family:var(--font-mono); font-size:.88em; padding:1px 5px; border-radius:5px; background:var(--sunk); }
.msg .tbl { margin:0 0 10px; overflow-x:auto; }
.msg table { border-collapse:collapse; font-size:13px; min-width:100%; }
.msg th,.msg td { padding:6px 8px; border-bottom:1px solid var(--line); text-align:left; white-space:nowrap; }
.msg th { color:var(--muted); font-weight:600; }
.live { margin-top:12px; padding:12px 14px; border-radius:12px; background:var(--accent-soft); color:var(--accent-ink); font-size:13.5px; }
.live .bar2 { height:4px; margin-top:8px; border-radius:2px; background:rgba(153,86,56,.18); overflow:hidden; }
.live .bar2 i { display:block; height:100%; width:0; background:var(--accent); transition:width .4s var(--ease-out); }
.questions { margin:10px 0 0; padding-left:20px; font-size:14px; color:var(--ink); line-height:1.7; }
.claims { margin:8px 0 0; padding:0; list-style:none; }
.claims li { display:flex; align-items:flex-start; gap:10px; padding:10px 0; border-top:1px solid var(--line); }
.claims li:first-child { border-top:0; }
.claims .lbl { flex:1; min-width:0; font-size:14px; color:var(--ink); }
.claims .stm { margin-top:2px; font-size:12.5px; color:var(--muted); overflow-wrap:anywhere; }
.nums { display:flex; flex-wrap:wrap; gap:6px 16px; margin-top:8px; font-size:13px; color:var(--ink-2); font-variant-numeric:tabular-nums; }
.row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:12px; }
details.trace { margin-top:22px; font-size:13px; color:var(--ink-2); }
details.trace summary { cursor:pointer; color:var(--muted); font-weight:600; }
.ev { padding:8px 0; border-top:1px solid var(--line); overflow-wrap:anywhere; white-space:pre-wrap; }
.ev b { color:var(--ink); font-weight:600; }
.ev .t { color:var(--muted); font-size:11.5px; margin-right:6px; font-variant-numeric:tabular-nums; }
.empty { padding:14px; color:var(--muted); font-size:13.5px; text-align:center; }
.login { padding-top:16vh; text-align:center; }
.login .mark { font:44px/1 Georgia,serif; color:var(--accent); }
.login h1 { margin:14px 0 4px; font:400 24px/1.4 var(--font-serif); }
.login form { margin:26px auto 0; max-width:340px; text-align:left; }
.login .primary { margin-top:16px; }
.open { display:block; margin-top:14px; text-align:center; text-decoration:none; line-height:40px; }
"""

_PAGE_JS = r"""
__SF_LABELS__
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const JOB = {CREATED:['准备中',''], RUNNING:['运行中','run'], NEEDS_REPLY:['等你回复','warn'], IDLE:['本轮完成',''],
  DONE:['研究已结束','ok'], FAILED:['失败','bad'], STOPPED:['已停止','void'], INTERRUPTED:['结果未知','warn']};
const RUN = {ACTIVE:['进行中','run'], PAUSED:['已暂停','warn'], SOLVED:['研究已完成','ok'], REFUTED:['目标被否定','bad'],
  EXHAUSTED:['实验已穷尽','warn'], BUDGET_EXHAUSTED:['预算耗尽','warn'], FAILED:['异常终止','bad'], BLOCKED:['受阻','warn'],
  CONTESTED:['存在争议','warn'], UNKNOWN:['未知','']};
const CLAIM = {SUPPORTED:['已支持','ok'], REFUTED:['已证伪','bad'], INCONCLUSIVE:['未定','warn'], OPEN:['待研究',''], INVALIDATED:['已失效','void']};
const pill = (map, key) => { const [t, c] = map[key] || [key || '—', '']; return `<span class="pill ${c}">${esc(t)}</span>`; };
const ago = ts => { const s = sfAge(ts); return s == null ? '' : sfL().ago(s); };
/* Agent replies are Markdown. Escape first, then add only fixed tags: bold, code,
   headings, lists and tables. Nothing from the text can become markup or a URL. */
const inline = s => esc(s).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
const plain = s => String(s || '').replace(/[*`#|]/g, '').replace(/^\s*[-–]+\s*$/gm, '').replace(/\s+/g, ' ').trim();
function md(text) {
  const out = []; let para = [], list = null, table = [];
  const flush = () => {
    if (para.length) { out.push(`<p>${para.map(inline).join('<br>')}</p>`); para = []; }
    if (list) { out.push(`<${list.tag}>${list.items.map(i => `<li>${inline(i)}</li>`).join('')}</${list.tag}>`); list = null; }
    if (table.length) {
      const rows = table.filter(r => !/^\|?[\s:|-]+\|?$/.test(r)).map(r => r.replace(/^\||\|$/g, '').split('|').map(c => c.trim()));
      out.push(`<div class="tbl"><table>${rows.map((cells, i) => `<tr>${cells.map(c => i ? `<td>${inline(c)}</td>` : `<th>${inline(c)}</th>`).join('')}</tr>`).join('')}</table></div>`);
      table = [];
    }
  };
  for (const raw of String(text || '').replace(/\r/g, '').split('\n')) {
    const line = raw.trimEnd(); let m;
    if (/^\s*\|/.test(line)) { if (!table.length) flush(); table.push(line.trim()); continue; }
    if (table.length) flush();
    if (!line.trim()) { flush(); continue; }
    if ((m = line.match(/^#{1,6}\s+(.*)$/))) { flush(); out.push(`<h4>${inline(m[1])}</h4>`); continue; }
    if ((m = line.match(/^\s*[-*]\s+(.*)$/)) || (m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
      const tag = /^\s*\d/.test(line) ? 'ol' : 'ul';
      if (para.length) { const keep = list; list = null; flush(); list = keep; }
      if (!list || list.tag !== tag) { flush(); list = {tag, items: []}; }
      list.items.push(m[1]); continue;
    }
    if (list) flush();
    para.push(line.trim());
  }
  flush();
  return out.join('');
}
let state = null, timer = null, lost = false;

async function api(path, body) {
  const options = body === undefined ? {cache:'no-store'} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)};
  let response;
  try { response = await fetch(path, options); } catch (_) { setLost(true); throw new Error('网络连接中断'); }
  setLost(false);
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 && data.error && data.error.code === 'LOGIN_REQUIRED') { showLogin(); throw AUTH; }
  if (!response.ok) throw new Error((data.error && data.error.message) || `请求失败（${response.status}）`);
  return data;
}
/* Views ignore results that arrive after the operator has moved on, and keep
   what is on screen when a poll fails (the connection dot already says so). */
const AUTH = new Error('请先登录');
let routeGen = 0;
const stale = gen => gen !== routeGen;
function failed(error, gen, retry, first) {
  if (error === AUTH || stale(gen)) return;
  if (first) setMain(`<a class="back" href="#/">‹ 返回</a><div class="err">${esc(error.message)}</div>`);
  schedule(retry, 5000);
}
function setLost(value) { lost = value; $('conn').classList.toggle('lost', value); $('connText').textContent = value ? '连接中断' : '已连接'; }
function schedule(fn, ms) { clearTimeout(timer); timer = setTimeout(() => { if (!document.hidden) fn(); else schedule(fn, ms); }, ms); }
function setMain(html) { $('main').innerHTML = html; }

function showLogin(message) {
  clearTimeout(timer); $('bar').hidden = true; routeGen++; shown = 'login';
  setMain(`<div class="login"><div class="mark" aria-hidden="true">✳</div><h1>Sisyfus 研究调度</h1>
    <div class="sub">在手机上派发研究、查看进度</div>
    <form id="loginForm"><label class="field" for="pw">密码</label>
    <input id="pw" type="password" autocomplete="current-password" required>
    <div class="err" id="loginErr">${esc(message || '')}</div>
    <button class="primary" type="submit">登录</button></form></div>`);
  $('loginForm').addEventListener('submit', async event => {
    event.preventDefault();
    try { await api('/api/login', {password: $('pw').value}); $('pw').value = ''; route(); }
    catch (error) { $('loginErr').textContent = error.message; }
  });
}

function jobCard(job) {
  return `<a class="card" href="#/job/${esc(job.id)}"><div class="top"><div class="ttl">${esc(job.title)}</div>${pill(JOB, job.status)}</div>
    <div class="meta">${esc(job.project)} · ${esc(ago(job.updated_at))}</div>
    ${job.last_text ? `<div class="snip">${esc(plain(job.last_text))}</div>` : ''}</a>`;
}
function claimCounts(claims) {
  const n = {}; (claims || []).forEach(c => { n[c.status] = (n[c.status] || 0) + 1; });
  return ['SUPPORTED','REFUTED','INCONCLUSIVE','INVALIDATED','OPEN'].filter(k => n[k]).map(k => `${n[k]} ${CLAIM[k][0]}`).join(' · ');
}
function runCard(project, run) {
  return `<a class="card" href="#/run/${encodeURIComponent(project)}/${encodeURIComponent(run.research_id)}">
    <div class="top"><div class="ttl">${esc(run.topic)}</div>${pill(RUN, run.run_status)}</div>
    <div class="meta">${esc(claimCounts(run.claims) || '尚无命题')} · ${esc(ago(run.updated_at))}</div></a>`;
}
function liveLine(activity) {
  if (!activity || String(activity.status || '').toUpperCase() !== 'RUNNING') return '';
  const p = sfProgress(activity.progress);
  return `<div class="live"><b>${esc(sfPhase(activity.phase))}</b>${p ? ' · ' + esc(p.text) : ''}
    ${activity.message ? `<div>${esc(activity.message)}</div>` : ''}<div class="bar2"><i data-w="${p ? p.pct : 8}"></i></div></div>`;
}
function sizeBars() { document.querySelectorAll('.bar2 i').forEach(i => { i.style.width = (Number(i.dataset.w) || 0) + '%'; }); }

let shown = '';
async function home(gen = routeGen) {
  $('bar').hidden = false;
  try { state = await api('/api/state'); } catch (error) { failed(error, gen, () => home(gen), shown !== 'home'); return; }
  if (stale(gen)) return;
  shown = 'home';
  const jobs = state.jobs.length ? state.jobs.map(jobCard).join('') : '<div class="empty">还没有派发过研究</div>';
  const projects = state.projects.map(p => `<div class="section"><h2>${esc(p.name)}</h2>${liveLine(p.activity)}
    ${p.runs.length ? p.runs.map(r => runCard(p.name, r)).join('') : '<div class="empty">这个工程还没有研究记录</div>'}</div>`).join('');
  setMain(`<h1 class="page">研究调度</h1><div class="sub">在这台 Mac 上运行 Sisyfus 研究，结果按证据判定</div>
    <div class="section"><button class="primary" id="newBtn" type="button">＋ 派发新研究</button></div>
    <div class="section"><h2>研究任务</h2>${jobs}</div>${projects || '<div class="empty">还没有允许的工程，请在 Mac 上运行 sisyfus dispatch project add</div>'}`);
  $('newBtn').addEventListener('click', () => { location.hash = '#/new'; });
  sizeBars(); schedule(() => home(gen), 8000);
}

async function newJob(gen = routeGen) {
  $('bar').hidden = false; clearTimeout(timer);
  if (!state) { try { state = await api('/api/state'); } catch (error) { failed(error, gen, () => newJob(gen), true); return; } }
  if (stale(gen)) return;
  shown = 'new';
  const options = state.projects.map(p => `<option value="${esc(p.name)}">${esc(p.name)}</option>`).join('');
  setMain(`<a class="back" href="#/">‹ 返回</a><h1 class="page">派发新研究</h1>
    <form id="newForm"><label class="field" for="project">工程</label><select id="project" required>${options}</select>
    <label class="field" for="brief">研究问题</label>
    <textarea id="brief" required maxlength="8000" placeholder="例如：中证800 红利低波组合在 2020–2024 锁定样本外，扣成本后能否跑赢等权对照？"></textarea>
    <div class="note">将在这台 Mac 上用 ${esc(state.agent)} 无人值守运行 sisyfus-research skill：它会读写该工程、运行回测命令。每轮最多花费 $${esc(state.limits.max_budget_usd)}，同一工程一次只运行一个任务。需要你回答的问题会出现在任务页。</div>
    <label class="check"><input type="checkbox" id="confirm" required><span>我确认在这台 Mac 上运行这项研究</span></label>
    <div class="err" id="newErr"></div><button class="primary" type="submit" id="send">派发</button></form>`);
  $('newForm').addEventListener('submit', async event => {
    event.preventDefault(); $('send').disabled = true; $('newErr').textContent = '';
    try { const data = await api('/api/jobs', {project: $('project').value, brief: $('brief').value}); location.hash = '#/job/' + data.job.id; }
    catch (error) { if (error !== AUTH) { $('newErr').textContent = error.message; $('send').disabled = false; } }
  });
}

function eventLine(ev) {
  const when = new Date(ev.ts || '');
  const hm = isNaN(when) ? '' : when.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit', hour12: false});
  const t = `<span class="t">${esc(hm)}</span>`;
  if (ev.kind === 'user') return `<div class="ev">${t}<b>你</b>　${esc(ev.text)}</div>`;
  if (ev.kind === 'text') return `<div class="ev">${t}<b>代理</b>　${esc(plain(ev.text))}</div>`;
  if (ev.kind === 'tool') return `<div class="ev">${t}${esc(ev.name)}${ev.summary ? ' · ' + esc(ev.summary) : ''}</div>`;
  if (ev.kind === 'result') return `<div class="ev">${t}<b>本轮结束</b>${ev.cost_usd != null ? ` · $${esc(Number(ev.cost_usd).toFixed(2))}` : ''}${ev.turns ? ` · ${esc(ev.turns)} 步` : ''}</div>`;
  if (ev.kind === 'status') return `<div class="ev">${t}${esc((JOB[ev.status] || [ev.status])[0])}${ev.error ? ' · ' + esc(ev.error) : ''}</div>`;
  return '';
}

async function jobView(id, gen = routeGen) {
  $('bar').hidden = false;
  let data;
  try { data = await api('/api/jobs/' + encodeURIComponent(id)); } catch (error) { failed(error, gen, () => jobView(id, gen), shown !== 'job:' + id); return; }
  if (stale(gen)) return;
  shown = 'job:' + id;
  const job = data.job, keep = $('replyText') ? $('replyText').value : '';
  const questions = (data.activity && data.activity.clarification_questions) || [];
  const runs = data.runs.map(r => runCard(job.project, r)).join('');
  setMain(`<a class="back" href="#/">‹ 返回</a><h1 class="page">${esc(job.title)}</h1>
    <div class="row">${pill(JOB, job.status)}<span class="sub">${esc(job.project)} · 第 ${esc(job.turns)} 轮${job.cost_usd_total ? ` · 已花费 $${esc(Number(job.cost_usd_total).toFixed(2))}` : ''}</span></div>
    ${job.status === 'RUNNING' ? liveLine(data.activity) : ''}
    ${job.error ? `<div class="err">${esc(job.error)}</div>` : ''}
    ${job.last_text ? `<div class="section"><h2>代理的最新回复</h2><div class="msg">${md(job.last_text)}</div></div>` : ''}
    ${questions.length ? `<div class="section"><h2>需要你回答</h2><ol class="questions">${questions.map(q => `<li>${esc(String(q).replace(/^\s*\d+\s*[).、．.]\s*/, ''))}</li>`).join('')}</ol></div>` : ''}
    ${job.can_reply ? `<form class="reply section" id="replyForm"><label class="field" for="replyText">回复代理（会在同一会话中继续）</label>
      <textarea id="replyText" maxlength="8000" placeholder="回答问题，或告诉它下一步做什么"></textarea>
      <div class="err" id="replyErr"></div><button class="primary" type="submit" id="replyBtn">发送并继续</button></form>` : ''}
    ${job.can_stop ? `<div class="row"><button class="secondary danger" type="button" id="stopBtn">停止这一轮</button></div>` : ''}
    ${runs ? `<div class="section"><h2>产生的研究</h2>${runs}</div>` : ''}
    <details class="trace" id="trace"${$('trace') && $('trace').open ? ' open' : ''}><summary>过程记录（${data.events.length}）</summary>${data.events.slice().reverse().map(eventLine).join('')}</details>`);
  if ($('replyText')) $('replyText').value = keep;
  if ($('replyForm')) $('replyForm').addEventListener('submit', async event => {
    event.preventDefault(); $('replyBtn').disabled = true; $('replyErr').textContent = '';
    try { await api(`/api/jobs/${encodeURIComponent(id)}/reply`, {text: $('replyText').value}); $('replyText').value = ''; jobView(id); }
    catch (error) { if (error !== AUTH) { $('replyErr').textContent = error.message; $('replyBtn').disabled = false; } }
  });
  if ($('stopBtn')) $('stopBtn').addEventListener('click', async () => {
    if (!confirm('停止正在运行的这一轮？已完成的实验和证据会保留。')) return;
    try { await api(`/api/jobs/${encodeURIComponent(id)}/stop`, {}); jobView(id); } catch (error) { if (error !== AUTH) alert(error.message); }
  });
  sizeBars();
  // Never re-render under the operator's thumbs: wait while a reply is being written.
  const refresh = () => {
    const box = $('replyText');
    if (box && (box.value || document.activeElement === box)) schedule(refresh, 4000); else jobView(id, gen);
  };
  schedule(refresh, job.status === 'RUNNING' ? 3000 : 10000);
}

async function runView(project, rid, gen = routeGen) {
  $('bar').hidden = false;
  let data;
  const key = `run:${project}/${rid}`;
  try { data = await api(`/api/runs/${encodeURIComponent(project)}/${encodeURIComponent(rid)}`); } catch (error) { failed(error, gen, () => runView(project, rid, gen), shown !== key); return; }
  if (stale(gen)) return;
  shown = key;
  const run = data.run, b = run.budget || {}, p = run.progress || {};
  const claims = run.claims.map(c => `<li><div class="lbl">${esc(c.label)}${c.statement ? `<div class="stm">${esc(c.statement)}</div>` : ''}</div>${pill(CLAIM, c.status)}</li>`).join('');
  setMain(`<a class="back" href="#/">‹ 返回</a><h1 class="page">${esc(run.topic)}</h1>
    <div class="row">${pill(RUN, run.run_status)}<span class="sub">${esc(project)} · 更新于 ${esc(ago(run.updated_at))}</span></div>
    ${liveLine(run.activity)}
    <div class="nums"><span>目标完成度 ${esc(Math.round(p.objective || 0))}%</span><span>证据覆盖 ${esc(Math.round(p.epistemic || 0))}%</span>
      ${b.max_attempts != null ? `<span>尝试 ${esc(b.attempts_committed ?? 0)}/${esc(b.max_attempts)}</span>` : ''}
      ${b.max_cost_units != null ? `<span>成本 ${esc(b.cost_units_used ?? 0)}/${esc(b.max_cost_units)}</span>` : ''}</div>
    <div class="section"><h2>命题</h2>${claims ? `<ul class="claims">${claims}</ul>` : '<div class="empty">尚无命题</div>'}</div>
    ${run.has_report ? `<a class="secondary open" href="/obs/${encodeURIComponent(project)}/${encodeURIComponent(rid)}/index.html" target="_blank" rel="noopener">打开完整研究工作台</a>` : ''}`);
  sizeBars(); schedule(() => runView(project, rid, gen), run.final ? 20000 : 6000);
}

function route(navigated) {
  const parts = (location.hash || '#/').slice(2).split('/').map(decodeURIComponent);
  const gen = ++routeGen;
  if (navigated) { window.scrollTo(0, 0); shown = ''; }
  if (parts[0] === 'new') newJob(gen);
  else if (parts[0] === 'job' && parts[1]) jobView(parts[1], gen);
  else if (parts[0] === 'run' && parts[2]) runView(parts[1], parts[2], gen);
  else home(gen);
}
window.addEventListener('hashchange', () => route(true));
// Coming back to the app refreshes data in place; forms being written are left untouched.
document.addEventListener('visibilitychange', () => {
  const box = $('replyText');
  const writing = box && (box.value || document.activeElement === box);
  if (!document.hidden && $('bar') && !$('bar').hidden && shown !== 'new' && !writing) route(false);
});
$('logout').addEventListener('click', async () => { try { await api('/api/logout', {}); } catch (_) {} showLogin(); });
api('/api/me').then(me => me.authenticated ? route() : showLogin()).catch(error => showLogin(error.message));
"""


def render_page(nonce: str) -> str:
    script = _PAGE_JS.replace("__SF_LABELS__", _ACTIVITY_LABELS_JS.strip())
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light">
<meta name="theme-color" content="#faf9f5">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="研究调度">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<title>Sisyfus 研究调度</title>
<style nonce="{nonce}">{ARENA_THEME_CSS}{_PAGE_CSS}</style>
</head>
<body>
<div class="app">
<header class="bar" id="bar" hidden><span class="mark" aria-hidden="true">✳</span><span class="name">研究调度</span>
<span class="conn" id="conn" role="status"><i aria-hidden="true"></i><span id="connText">已连接</span></span>
<button class="out" id="logout" type="button">退出</button></header>
<main id="main"></main>
</div>
<script nonce="{nonce}">{script}</script>
</body>
</html>"""
