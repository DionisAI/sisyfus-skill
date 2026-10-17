"""Chinese, capture-only share shell. No operator controls or external assets."""

PAGE = r"""<!doctype html>
<html lang="zh-CN" data-password-required="false"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Sisyfus · 临时分享</title>
<style nonce="NONCE">
:root{color-scheme:light;--paper:#faf8f3;--surface:#fffdf9;--ink:#302b24;--muted:#756c60;--line:#dfd7ca;--accent:#766044;--error:#943f34}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}button,input,textarea{font:inherit}button{border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--ink);padding:.5rem .85rem;cursor:pointer}button.primary{background:var(--accent);color:#fffdf9;border-color:var(--accent)}button:disabled{opacity:.55;cursor:default}:focus-visible{outline:3px solid #b18c56;outline-offset:3px}[hidden]{display:none!important}header{border-bottom:1px solid var(--line);padding:1rem max(1rem,calc((100vw - 960px)/2));display:flex;align-items:center;justify-content:space-between;gap:1rem}header strong{font-weight:650;letter-spacing:.02em}main{max-width:960px;margin:auto;padding:1.4rem 1rem 4rem;min-width:0}.eyebrow,.small,.muted{font-size:.875rem;color:var(--muted)}h1{font-size:clamp(1.45rem,4vw,2rem);line-height:1.35;font-weight:600;margin:.5rem 0 1rem}h2{font-size:1.25rem;font-weight:600;margin:1.6rem 0 .7rem}h3,h4{font-size:1rem;font-weight:650}p{margin:.5rem 0}.prose{white-space:pre-wrap;overflow-wrap:anywhere}.section{border-top:1px solid var(--line);margin-top:1.7rem;padding-top:.6rem;min-width:0}.actions{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}input,textarea{max-width:100%;border:1px solid var(--line);border-radius:8px;background:var(--surface);padding:.6rem .75rem;color:var(--ink)}#share-token{width:min(100%,29rem)}textarea{width:100%;min-height:7rem;resize:vertical}.error{color:var(--error)}.task-row{border-bottom:1px solid var(--line);padding:.65rem 0;min-width:0}summary{cursor:pointer;font-weight:550;overflow-wrap:anywhere}details>.prose{padding-left:.8rem}details details{margin-left:.75rem}.graph-scroll{overflow:auto;max-width:100%;border:1px solid var(--line);border-radius:9px;background:var(--surface)}#share-graph{display:block}.graph-edge{fill:none;stroke:#aa9b86;stroke-width:1.7}.graph-node rect{fill:#fffdf9;stroke:#b3a590;stroke-width:1.2}.graph-node text{fill:var(--ink);font-size:13px}.graph-node.history rect{fill:#efebe4;stroke-dasharray:4 3}.graph-node.failed rect{stroke:var(--error)}.graph-node:focus rect{stroke:#766044;stroke-width:3}.message{padding:.75rem 0;border-bottom:1px solid var(--line)}.engineering-evidence{overflow-wrap:anywhere;min-width:0}iframe{width:100%;height:72vh;border:1px solid var(--line);background:var(--surface);border-radius:8px}code{overflow-wrap:anywhere}.status-line{padding:.6rem 0;min-height:2rem}.login{padding:1rem 0 2rem;max-width:40rem}@media(max-width:520px){header{padding:.8rem 1rem;align-items:flex-start}main{padding:1rem .85rem 3rem}.actions button{min-height:44px}.task-row details{margin-left:.3rem}#share-enter{width:100%}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;animation:none!important;transition:none!important}}
.message .small{overflow-wrap:anywhere}
</style></head><body>
<header><strong>Sisyfus · 临时分享</strong><button id="share-logout" hidden>退出此页</button></header>
<main><p class="eyebrow">同一捕获 · 任务图 / 工程结果 / 消息回执</p><h1>查看一项正在推进的工程</h1><p class="muted">此页没有执行、规划或机器控制能力。已记录的执行结束、检查、独立审查与整体验收分别展示。</p>
<section id="share-login" class="login"><label for="share-token">临时访问令牌</label><div class="actions"><input id="share-token" type="password" autocomplete="off" spellcheck="false" placeholder="仅用于本页内存中的 Authorization"><button id="share-enter" class="primary">读取任务</button></div></section>
<p id="share-status" class="status-line" role="status" aria-live="polite">输入临时访问令牌后读取；匿名页面不包含任务数据。</p><p id="share-last-success" class="small"></p>
<p id="share-revocation-status" class="small prose" role="status" aria-live="polite" hidden></p>
<div id="share-live" hidden><div class="actions"><button id="share-refresh">刷新读回</button><span id="share-mode" class="small"></span></div><h2 id="share-objective" class="prose"></h2><p id="share-phase" class="prose"></p><p id="share-acceptance" class="prose"></p><details><summary>捕获来源与局限</summary><p id="share-capture-meta" class="small prose"></p></details>
<section class="section" aria-labelledby="share-graph-title"><h2 id="share-graph-title">任务依赖图</h2><p id="share-graph-note" class="small prose" role="status"></p><div class="graph-scroll"><svg id="share-graph" xmlns="http://www.w3.org/2000/svg" role="group" aria-label="捕获的 canonical 任务依赖；选择节点查看原任务详情"></svg></div><div id="share-task-list"></div></section>
<section id="engineeringResult" class="section" aria-labelledby="engineeringResultTitle"><h2 id="engineeringResultTitle">工程结果</h2><p id="engineeringResultStatus" class="small prose" role="status" aria-live="polite"></p><div id="engineeringResultBody"></div></section>
<section id="share-messages" class="section"><h2>任务对话与回执</h2><p class="small">收到资料、绑定到后续调用与原生提示接受是不同记录；任何回执都不是验收。</p><p id="share-message-error" class="error prose" role="status"></p><div id="share-message-list"></div><label for="share-compose">补充资料或 /btw 查询</label><textarea id="share-compose" maxlength="4000" placeholder="只提交补充信息，不会启动模型。"></textarea><div class="actions"><button id="share-message-send">提交信息</button><button id="share-message-readback">查询原请求回执</button></div><p id="share-message-status" class="small prose" role="status"></p></section>
<section id="share-report" class="section" hidden><h2>独立发布的报告</h2><p class="small">这是显式选择的固定公开 HTML，不是工程实时捕获，也不表示收益或研究验收。</p><p id="share-report-hash" class="small prose"></p><button id="share-report-open">认证读取固定报告</button><p id="share-report-status" class="small prose" role="status"></p><iframe id="share-report-frame" title="独立发布的固定报告（sandbox，无脚本或表单）" sandbox="" referrerpolicy="no-referrer" hidden></iframe></section>
</div></main><script nonce="NONCE">
'use strict';
const $ = id => document.getElementById(id);
const reportStyleNonce = 'NONCE';
// The gateway changes only this public mode flag and the anonymous login labels.
const passwordRequired = false;
let credential = '', timer = null, reportOwner = null, loadedReportHash = null, readOwner = null, loginOwner = null;
const requests = new Set();
// Public diagnostic counters only: no session, credential or mission identity.
const revocations = {pending:0, unconfirmed:false, confirmed:false};
const state = {epoch:0, envelope:null, missionId:null, lastSuccess:null, messages:new Map(), cursor:0, applicationCursor:0, pending:null, messageBusy:false, composing:false};
function clean(value) { const text = typeof value === 'string' ? value : String(value ?? ''); return credential ? text.split(credential).join('[已隐藏凭据]') : text; }
function text(value) { return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' ? String(value) : ''; }
function array(value) { return Array.isArray(value) ? value : []; }
function previewText(value, limit=110) { const chars = Array.from(clean(text(value)).trim().replace(/\s+/g,' ')); return chars.length > limit ? chars.slice(0,limit).join('') + '…' : chars.join(''); }
function node(tag, content, className) { const element=document.createElement(tag); if(content!==undefined)element.textContent=clean(String(content)); if(className)element.className=className; return element; }
class ShareRequestError extends Error { constructor(code,status=0) { super(code); this.code=code; this.status=status; } }
function failureText(error) { const code = error instanceof ShareRequestError && /^[A-Z][A-Z0-9_]{0,63}$/.test(error.code) ? error.code : 'LOCAL_READ_FAILED'; return '读取失败（' + code + '），未显示成功结果。'; }
async function api(path, body, options = {}) {
  const controller = options.controller || new AbortController(); requests.add(controller);
  const timeout = setTimeout(()=>controller.abort(),14000);
  try {
    const response=await fetch(path,{method:options.method || (body===undefined?'GET':'POST'),credentials:'omit',redirect:'error',cache:'no-store',signal:controller.signal,
      headers:{...(options.bearer===null?{}:{Authorization:'Bearer '+(options.bearer===undefined?credential:options.bearer)}),...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body)});
    let data; try{data=await response.json();}catch{throw new ShareRequestError('INVALID_JSON',response.status);}
    if(!response.ok){const code=data?.error?.code;throw new ShareRequestError(typeof code==='string'&&/^[A-Z][A-Z0-9_]{0,63}$/.test(code)?code:'HTTP_REJECTED',response.status);}
    return data;
  } catch(error) { if(error instanceof ShareRequestError)throw error;throw new ShareRequestError('CONNECTION_UNCERTAIN'); }
  finally{clearTimeout(timeout);requests.delete(controller);}
}
function clearReport() { if(reportOwner)reportOwner.controller.abort();reportOwner=null;loadedReportHash=null;$('share-report-frame').removeAttribute('src');$('share-report-frame').removeAttribute('srcdoc');$('share-report-frame').hidden=true;$('share-report-open').disabled=false;$('share-report-status').textContent=''; }
function clearCapture() { state.envelope=null;$('share-live').hidden=true;$('share-graph').replaceChildren();$('share-task-list').replaceChildren();$('engineeringResultBody').replaceChildren();for(const id of ['share-objective','share-phase','share-acceptance','share-capture-meta','share-mode','share-graph-note','share-report-hash','engineeringResultStatus'])$(id).textContent='';clearReport(); }
function clearAccess() {
  state.epoch++;credential='';clearTimeout(timer);timer=null;for(const request of requests)request.abort();readOwner=null;loginOwner=null;state.messageBusy=false;
  if(state.pending?.status==='SENDING')state.pending.status='UNKNOWN';
  if(passwordRequired){state.pending=null;state.lastSuccess=null;$('share-last-success').textContent='';}
  clearCapture();state.messages.clear();state.cursor=state.applicationCursor=0;state.missionId=null;
  $('share-message-list').replaceChildren();$('share-message-error').textContent='';$('share-message-status').textContent='';$('share-compose').value='';
  $('share-token').value='';$('share-enter').disabled=false;$('share-login').hidden=false;$('share-logout').hidden=true;$('share-status').textContent='已退出本页；已清除捕获及报告。未确认的提交不会自动重发。';
}
function renderRevocationStatus() {
  const element=$('share-revocation-status');
  element.textContent=revocations.unconfirmed?'存在服务器会话撤销未确认；不会自动重试。'+(revocations.pending?'仍有撤销请求待确认。':''):
    revocations.pending?'服务器会话撤销正在确认；私有内容已清除。':revocations.confirmed?'已收到服务器会话撤销确认。':'';
  element.hidden=!element.textContent;element.classList.toggle('error',revocations.unconfirmed);
}
async function logout() {
  const session=credential;clearAccess();
  if(!passwordRequired||!session)return;
  if(revocations.pending>=16){revocations.unconfirmed=true;renderRevocationStatus();return;}
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),14000);
  revocations.pending++;renderRevocationStatus();
  try{
    // This single finite request is not in requests: a new login must not abort
    // it. Completion changes ONLY public diagnostics, never epoch-owned state.
    const response=await fetch('/api/share/logout',{method:'POST',headers:{Authorization:'Bearer '+session},credentials:'omit',redirect:'error',cache:'no-store',signal:controller.signal});
    if(!response.ok)throw new ShareRequestError('SERVER_REVOCATION_UNCONFIRMED',response.status);
    const receipt=await response.json();
    if(!engineeringObject(receipt,['status'])||receipt.status!=='LOGGED_OUT')throw new ShareRequestError('INVALID_LOGOUT');
    revocations.confirmed=true;
  }catch{revocations.unconfirmed=true;}
  finally{clearTimeout(timeout);revocations.pending--;renderRevocationStatus();}
}
function authorityLost(error) { if(![401,403,410].includes(error.status))return false;clearAccess();$('share-status').textContent='STALE · '+failureText(error)+' 私有捕获已清除，请重新输入'+(passwordRequired?'访问密码。':'令牌。');return true; }
async function login(value) {
  if(passwordRequired&&loginOwner)return;
  clearAccess();
  if(!passwordRequired){
    if(typeof value!=='string'||!value||value.length>4096||/[\s\x00-\x1f\x7f]/.test(value)){$('share-status').textContent='请输入有效的临时访问令牌。';return;}
    credential=value;state.epoch++;$('share-login').hidden=true;$('share-logout').hidden=false;readSelected();return;
  }
  if(typeof value!=='string'){$('share-status').textContent='请输入访问密码。';return;}
  const ticket={epoch:state.epoch,controller:new AbortController()};loginOwner=ticket;
  $('share-enter').disabled=true;$('share-logout').hidden=false;$('share-status').textContent='正在验证访问密码…';
  try{
    const pending=api('/api/share/login',{password:value},{bearer:null,controller:ticket.controller});value='';
    const session=await pending;if(loginOwner!==ticket||ticket.epoch!==state.epoch)return;
    if(!engineeringObject(session,['schema','token','expires_in'])||session.schema!=='sisyfus.share.session.v1'||typeof session.token!=='string'||!/^[A-Za-z0-9_-]{43}$/.test(session.token)||session.expires_in!==28800)throw new ShareRequestError('INVALID_SESSION');
    credential=session.token;$('share-login').hidden=true;$('share-logout').hidden=false;readSelected();
  }catch(error){
    if(loginOwner===ticket&&ticket.epoch===state.epoch){
      $('share-login').hidden=false;$('share-logout').hidden=true;
      $('share-status').textContent=(error.status===401?'密码验证未通过；':error.status===429?'登录请求受限，请稍后再试；':'登录未成功；')+failureText(error);
    }
  }finally{if(loginOwner===ticket){loginOwner=null;$('share-enter').disabled=false;}}
}
function validateEnvelope(value) {
  if(!engineeringObject(value,['schema','mission_id','captured_at','capture_hash','capture','capabilities','report'])||value.schema!=='sisyfus.share.capture.v1'||
    typeof value.mission_id!=='string'||!value.mission_id||typeof value.captured_at!=='string'||!Number.isFinite(Date.parse(value.captured_at))||!/^[a-f0-9]{64}$/.test(value.capture_hash)||
    !engineeringObject(value.capture,['id','snapshot','controller','controls','engineering_result'])||value.capture.id!==value.mission_id||!value.capture.snapshot||typeof value.capture.snapshot!=='object'||Array.isArray(value.capture.snapshot)||
    !value.capture.controller||typeof value.capture.controller!=='object'||Array.isArray(value.capture.controller)||!Array.isArray(value.capture.controls)||
    !engineeringObject(value.capabilities,['messages','controls'])||typeof value.capabilities.messages!=='boolean'||value.capabilities.controls!==false||
    !engineeringObject(value.report,['available','sha256'])||typeof value.report.available!=='boolean'||(value.report.available?!/^[a-f0-9]{64}$/.test(value.report.sha256):value.report.sha256!==null))throw new ShareRequestError('INVALID_CAPTURE');
  if(state.missionId&&state.missionId!==value.mission_id)throw new ShareRequestError('MISSION_MISMATCH');
  return value;
}
function renderCore(value) {
  const snapshot=value.capture.snapshot,controller=value.capture.controller;
  $('engineeringResult').hidden=true;
  $('share-objective').textContent=clean(typeof snapshot.objective==='string'?snapshot.objective:'目标未记录');
  $('share-phase').textContent=clean('记录阶段：'+text(snapshot.phase)+'；捕获时 controller.running='+text(controller.running)+'。执行返回与验收分开。');
  $('share-acceptance').textContent=snapshot.all_verified===true?'原核心记录整项验收与集成已通过；仅 AS_CAPTURED，不重新验收。':'整项验收与集成尚未确认通过。';
  $('share-capture-meta').textContent=clean('mission_id='+value.mission_id+'\ncapture_hash='+value.capture_hash+'\ncaptured_at='+value.captured_at+'\n时间仅指读回；原 Core 仍是非原子捕获，不表示活动、模型在线或任务进展。');
  $('share-mode').textContent=value.capabilities.messages?'允许补充信息 · 没有控制权限':'只读分享 · 没有控制权限';
  $('share-live').hidden=false;drawTasks(array(snapshot.nodes));
  if(!value.report.available||(reportOwner&&reportOwner.hash!==value.report.sha256)||(loadedReportHash&&loadedReportHash!==value.report.sha256))clearReport();
  $('share-report').hidden=!value.report.available;$('share-report-hash').textContent=value.report.available?'固定发布 SHA256：'+value.report.sha256:'';
  renderMessages();
}
function svg(tag,attrs={},content) { const element=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value]of Object.entries(attrs))element.setAttribute(key,String(value));if(content!==undefined)element.textContent=clean(String(content));return element; }
function drawTasks(rows) {
  const graph=$('share-graph'),list=$('share-task-list');graph.replaceChildren();list.replaceChildren();
  const tasks=new Map(),diagnostics=[],cards=new Map();
  for(const task of rows){if(!task||typeof task.id!=='string'||!task.id||tasks.has(task.id)){diagnostics.push('任务身份缺失或重复');continue;}tasks.set(task.id,task);}
  const deps=new Map(),next=new Map(),remaining=new Map(),depth=new Map();for(const id of tasks.keys()){next.set(id,[]);depth.set(id,0);}
  for(const [id,task]of tasks){const valid=[];if(!Array.isArray(task.depends_on))diagnostics.push('依赖格式异常');else for(const dependency of task.depends_on){if(typeof dependency!=='string'||!tasks.has(dependency)){diagnostics.push('存在悬空依赖');continue;}valid.push(dependency);next.get(dependency).push(id);}deps.set(id,valid);remaining.set(id,valid.length);}
  const ready=[...tasks.keys()].filter(id=>remaining.get(id)===0);for(let index=0;index<ready.length;index++){const id=ready[index];for(const child of next.get(id)){depth.set(child,Math.max(depth.get(child),depth.get(id)+1));remaining.set(child,remaining.get(child)-1);if(remaining.get(child)===0)ready.push(child);}}
  if(ready.length!==tasks.size){diagnostics.push('依赖循环：图不是成功证明');const last=Math.max(0,...depth.values())+1;for(const id of tasks.keys())if(remaining.get(id)>0)depth.set(id,last);}
  const columns=new Map(),position=new Map();for(const [id,task]of tasks){const column=depth.get(id),row=columns.get(column)||0;columns.set(column,row+1);position.set(id,{x:12+column*252,y:12+row*142});
    const card=node('details',undefined,'task-row'),summary=node('summary',id+' · '+(typeof task.objective==='string'?previewText(task.objective,90):'目标未记录'));
    card.append(summary,node('p',typeof task.objective==='string'?task.objective:'目标未记录','prose'),node('p','执行='+text(task.state)+'；原裁决='+text(task.verdict)+'；active='+text(task.active)+'；stale='+text(task.stale)+'；superseded_by='+text(task.superseded_by),'small prose'));
    const checks=verificationChecks(task.verification),review=verificationReview(task.verification);card.append(node('p','检查记录：'+checks.map(check=>text(checkResult(check).status)).join('、')+'；独立审查记录：'+text(review.verdict)+'。历史或 stale 不升级整项验收。','small prose'));
    if(typeof task.acceptance==='string')card.append(node('p','原验收：'+task.acceptance,'prose'));list.append(card);cards.set(id,{card,summary});}
  const width=tasks.size?Math.max(...depth.values())*252+244:280,height=tasks.size?Math.max(...columns.values())*142+16:40;graph.setAttribute('viewBox',`0 0 ${width} ${height}`);graph.style.width=width+'px';graph.style.height=height+'px';
  for(const [id,dependencies]of deps)for(const dependency of dependencies){const a=position.get(dependency),b=position.get(id);graph.append(svg('path',{d:`M${a.x+220} ${a.y+50} L${b.x} ${b.y+50}`,class:'graph-edge','data-from':dependency,'data-to':id}));}
  for(const [id,task]of tasks){const p=position.get(id),group=svg('g',{role:'button',tabindex:0,class:'graph-node'+(task.stale||task.active===false?' history':task.verdict==='FAIL'?' failed':''),'data-task-id':id,'aria-label':clean(id+' '+text(task.objective)+'；查看原详情')});
    group.append(svg('rect',{x:p.x,y:p.y,width:220,height:116,rx:8}),svg('text',{x:p.x+10,y:p.y+23},previewText(id,26)),svg('text',{x:p.x+10,y:p.y+48},previewText(task.objective,17)),svg('text',{x:p.x+10,y:p.y+73},'执行 '+text(task.state)+' / 原裁决 '+text(task.verdict)),svg('text',{x:p.x+10,y:p.y+97},task.stale||task.active===false?'历史 / stale：不作当前成功':'检查、审查、整体验收分开'));
    const select=()=>{const target=cards.get(id);target.card.open=true;target.summary.focus({preventScroll:true});target.card.scrollIntoView({block:'nearest',behavior:'auto'});};group.onclick=select;group.onkeydown=event=>{if(!event.isComposing&&event.keyCode!==229&&(event.key==='Enter'||event.key===' ')){event.preventDefault();select();}};graph.append(group);}
  $('share-graph-note').textContent=diagnostics.length?[...new Set(diagnostics)].join('；'):tasks.size?'边只来自原 canonical depends_on；选择节点查看详情。':'本次捕获尚无任务。';
  $('share-graph-note').classList.toggle('error',diagnostics.length>0);
}
function recordData(record) { return record?.data&&typeof record.data==='object'&&!Array.isArray(record.data)?record.data:record||{}; }
function verificationChecks(verification) { return array(verification?.evidence?.checks||verification?.metrics?.checks||verification?.checks); }
function verificationReview(verification) { return recordData(verification?.evidence?.review||verification?.metrics?.review||verification?.review); }
function checkResult(check) { const data=recordData(check);return {status:data.classification?.status||data.verdict||data.status}; }
function renderResult(capture) {
  const owner=state.epoch,selected=classifyEngineering(capture,capture.id);$('engineeringResult').hidden=false;$('engineeringResultBody').replaceChildren();
  const notes={OK:'OK · 来自同一捕获，工程投影不是验收。',MISSING:'MISSING · 未记录工程结果。',INVALID:'INVALID · 工程结果格式异常，原图与进度保留。',REJECTED:'REJECTED · 工程投影输入未通过校验。',FAILED:'FAILED · 本次工程投影失败。'};
  $('engineeringResultStatus').textContent=clean(notes[selected.status]+(selected.code?'（'+selected.code+'）':''));
  try{if(selected.status==='OK'&&owner===state.epoch)$('engineeringResultBody').replaceChildren(...buildEngineeringResult(selected.result));}
  catch{$('engineeringResultBody').replaceChildren();$('engineeringResultStatus').textContent='RENDER_FAILED · 已清除局部结果；原图与进度保留。下一次读回重新绘制。';}
}
async function readMessages(epoch) {
  const value=await api('/api/share/messages?cursor='+state.cursor+'&application_cursor='+state.applicationCursor);
  if(epoch!==state.epoch||!credential)return;
  if(!value||!Array.isArray(value.messages)||!Array.isArray(value.updates)||!Number.isSafeInteger(value.cursor)||value.cursor<state.cursor||!Number.isSafeInteger(value.application_cursor)||value.application_cursor<state.applicationCursor||typeof value.has_more!=='boolean'||typeof value.has_more_updates!=='boolean')throw new ShareRequestError('INVALID_MESSAGES');
  for(const message of [...value.messages,...value.updates]){if(!message||typeof message.id!=='string'||typeof message.request_id!=='string'||typeof message.text!=='string'||!Array.isArray(message.applications))throw new ShareRequestError('INVALID_MESSAGE');}
  for(const message of [...value.messages,...value.updates]){state.messages.set(message.id,message);if(state.pending?.mission_id===state.missionId&&state.pending.request_id===message.request_id){state.pending.status=message.status;state.messageBusy=false;}}
  state.cursor=value.cursor;state.applicationCursor=value.application_cursor;
  while(state.messages.size>200)state.messages.delete(state.messages.keys().next().value);
  $('share-message-error').textContent=(value.has_more||value.has_more_updates)?'还有历史或应用更新待下一轮读取；本页仅显示最近200条。':'';renderMessages();
}
function renderMessages() {
  const root=$('share-message-list');root.replaceChildren();
  for(const message of state.messages.values()){const row=node('article',undefined,'message');row.append(node('p',text(message.status)+' · 原请求 '+message.request_id,'small'),node('p',message.text,'prose'));
    if(message.kind==='query'&&message.answer){const answer=message.answer;row.append(node('p',text(answer.summary),'prose'),node('p','/btw 原捕获：phase='+text(answer.phase)+'；all_verified='+text(answer.all_verified)+'；revision='+text(answer.revision)+'；observed_at='+text(answer.observed_at)+'。这是查询时的记录，不是当前验收。','small prose'));}
    if(!message.applications.length&&message.kind!=='query')row.append(node('p','仅收到，未记录绑定或原生接受。','small'));
    for(const application of message.applications){row.append(node('p','绑定 '+text(application.run_key)+' · '+text(application.status)+'；原提示接受 '+text(application.receipt_evidence?.recorded_prompt_acceptance)+'；原回执 '+text(application.receipt_status),'small prose'));}root.append(row);}
  const pending=state.pending,waiting=pending&&(pending.status==='UNKNOWN'||pending.status==='SENDING');
  const allowed=state.envelope?.capabilities.messages===true&&!!credential;
  $('share-message-send').disabled=!allowed||state.messageBusy||!!waiting;$('share-compose').disabled=!allowed||state.messageBusy;
  $('share-message-status').textContent=pending?clean('原请求 '+pending.request_id+' · '+pending.status+(waiting?'；结果待核对，仅 GET 查询，绝不自动重发。':'；收据不表示验收。')):(allowed?'可提交补充信息或 /btw；没有执行权限。':'此分享为只读，未获消息写入许可。');
}
async function readSelected() {
  if(!credential||readOwner)return;
  const ticket={epoch:state.epoch};readOwner=ticket;clearTimeout(timer);$('share-refresh').disabled=true;$('share-status').textContent='正在读取同一捕获…';
  try{
    const value=validateEnvelope(await api('/api/share/snapshot'));if(ticket.epoch!==state.epoch||!credential)return;
    state.envelope=value;state.missionId=value.mission_id;renderCore(value);
    try{await readMessages(ticket.epoch);}catch(error){if([401,403,410].includes(error.status))throw error;if(ticket.epoch===state.epoch)$('share-message-error').textContent=failureText(error)+' 图与工程捕获仍来自本轮 snapshot。';}
    if(ticket.epoch!==state.epoch||!credential)return;
    state.lastSuccess=value.captured_at;$('share-last-success').textContent='最近成功读回：'+new Date(value.captured_at).toLocaleString()+'（仅捕获时间，不是活动证明）';
    $('share-status').textContent='同一捕获已读回；工程结果、消息与独立报告各自显示状态。';renderResult(value.capture);
  }catch(error){if(ticket.epoch!==state.epoch)return;clearCapture();$('share-status').textContent='STALE · '+failureText(error);$('share-last-success').textContent=state.lastSuccess?'上次成功捕获：'+state.lastSuccess+'；当前成功内容已清除。':'尚无成功捕获。';authorityLost(error);}
  finally{if(readOwner===ticket){readOwner=null;$('share-refresh').disabled=false;if(credential)timer=setTimeout(readSelected,5000);}}
}
async function sendMessage() {
  if(!state.envelope?.capabilities.messages||state.messageBusy||state.pending&&(state.pending.status==='UNKNOWN'||state.pending.status==='SENDING'))return;
  const message=$('share-compose').value;if(!message.trim()||Array.from(message).length>4000){$('share-message-status').textContent='消息须为1至4000个字符。';return;}
  if(!globalThis.crypto?.randomUUID){$('share-message-status').textContent='浏览器缺少请求编号支持，未提交。';return;}
  const epoch=state.epoch,body={message,request_id:crypto.randomUUID()};state.pending={...body,status:'SENDING',mission_id:state.missionId};state.messageBusy=true;renderMessages();
  try{const receipt=await api('/api/share/message',body);if(epoch!==state.epoch)return;if(receipt?.request_id!==body.request_id||typeof receipt.id!=='string'||!Array.isArray(receipt.applications))throw new ShareRequestError('INVALID_RECEIPT');state.messages.set(receipt.id,receipt);state.pending.status=receipt.status;$('share-compose').value='';}
  catch(error){if(epoch===state.epoch){state.pending.status='UNKNOWN';authorityLost(error);}}
  finally{if(epoch===state.epoch){state.messageBusy=false;renderMessages();}}
}
async function openReport() {
  const metadata=state.envelope?.report;if(!credential||!metadata?.available||reportOwner)return;
  const controller=new AbortController(),ticket={epoch:state.epoch,hash:metadata.sha256,controller};reportOwner=ticket;$('share-report-open').disabled=true;$('share-report-status').textContent='正在认证读取固定发布内容…';
  requests.add(controller);const timeout=setTimeout(()=>controller.abort(),14000);
  try{
    const response=await fetch('/api/share/report',{headers:{Authorization:'Bearer '+credential},credentials:'omit',cache:'no-store',redirect:'error',signal:controller.signal});
    if(!response.ok)throw new ShareRequestError('REPORT_READ_FAILED',response.status);
    const data=await response.arrayBuffer();if(data.byteLength>4194304)throw new ShareRequestError('REPORT_TOO_LARGE');
    const digest=await crypto.subtle.digest('SHA-256',data),hash=[...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,'0')).join('');
    if(hash!==ticket.hash)throw new ShareRequestError('REPORT_HASH_CHANGED');
    if(ticket.epoch!==state.epoch||reportOwner!==ticket||state.envelope?.report.sha256!==ticket.hash)return;
    // Verify the fixed RAW publication first. Only its sandbox presentation copy
    // receives the parent style nonce; API bytes and the publication hash stay raw.
    const documentCopy=new DOMParser().parseFromString(new TextDecoder('utf-8',{fatal:true}).decode(data),'text/html');
    for(const style of documentCopy.querySelectorAll('style'))style.setAttribute('nonce',reportStyleNonce);
    const presentation='<!doctype html>'+documentCopy.documentElement.outerHTML;
    const frame=$('share-report-frame');frame.setAttribute('sandbox','');frame.removeAttribute('src');frame.srcdoc=presentation;loadedReportHash=hash;
    frame.hidden=false;$('share-report-status').textContent='固定发布内容已读回；SHA256='+hash+'。它独立于当前工程捕获。';
  }catch(error){if(ticket.epoch===state.epoch&&reportOwner===ticket){clearReport();if(!authorityLost(error))$('share-report-status').textContent=failureText(error)+' 发布内容未显示。';}}
  finally{clearTimeout(timeout);requests.delete(controller);if(reportOwner===ticket){$('share-report-open').disabled=false;reportOwner=null;}}
}
function engineeringObject(value, keys, optional = []) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== null && Object.getPrototypeOf(prototype) !== null) return false;
  const own = Object.keys(value);
  return keys.every(key => Object.prototype.hasOwnProperty.call(value,key)) && own.every(key => keys.includes(key) || optional.includes(key));
}
function engineeringText(value, cap = 8388608) {
  if (typeof value !== 'string' || value.length > cap) return false;
  let bytes = 0;
  for (const char of value) {
    const point = char.codePointAt(0);
    if (point >= 0xd800 && point <= 0xdfff) return false;
    bytes += point < 0x80 ? 1 : point < 0x800 ? 2 : point < 0x10000 ? 3 : 4;
    if (bytes > cap) return false;
  }
  return true;
}
function engineeringPointer(value) { return engineeringText(value) && value.startsWith('/'); }
function validEngineeringResult(result) {
  const object = engineeringObject, string = engineeringText;
  const integer = (v,max = 2 ** 63 - 1) => Number.isInteger(v) && v >= 0 && v <= max;
  const tri = v => v === null || typeof v === 'boolean';
  const list = (v,cap,check) => Array.isArray(v) && v.length <= cap && v.every(check);
  const hash = v => typeof v === 'string' && /^[0-9a-f]{64}$/.test(v);
  const tokenValue = v => typeof v === 'string' && /^[A-Z][A-Z0-9_]{0,31}$/.test(v);
  const labelValue = v => string(v) && /^[A-Z][A-Z0-9_]*$/.test(v);
  const identity = v => (string(v,256) && v.length > 0) || integer(v);
  const fact = (v,kind = 'text',objective = false) => {
    if (!object(v,['state','value','source'],['row_ordinal','utf8_bytes']) || !engineeringPointer(v.source) ||
        !['RECORDED','FILTERED','NOT_RECORDED','REDACTED_AT_CAPTURE','WITHHELD','MALFORMED'].includes(v.state)) return false;
    if ('row_ordinal' in v && !integer(v.row_ordinal)) return false;
    if ('utf8_bytes' in v && !integer(v.utf8_bytes)) return false;
    if (v.state !== 'RECORDED' && v.state !== 'FILTERED') return v.value === null;
    if (v.state === 'FILTERED') return kind === 'text' && string(v.value);
    if (kind === 'bool') return typeof v.value === 'boolean';
    if (kind === 'int') return integer(v.value);
    if (kind === 'hash') return hash(v.value);
    if (kind === 'identity') return identity(v.value);
    if (kind === 'token') return tokenValue(v.value);
    if (kind === 'id') return string(v.value,256) && v.value.length > 0;
    if (kind === 'paths' || kind === 'ids') return list(v.value,64,x => string(x,kind === 'paths' ? 1024 : 256) && x.length > 0);
    return string(v.value,objective ? 80000 : 16384) && (!objective || Array.from(v.value).length <= 20000);
  };
  const facts = (v,kinds) => Object.entries(kinds).every(([key,kind]) => fact(v[key],kind));
  let diagnosticCount = 0;
  const diagnostics = v => list(v,8192,x => {
    diagnosticCount++;
    return diagnosticCount <= 8192 && object(x,['code','section','source']) && labelValue(x.code) && string(x.section,32) && engineeringPointer(x.source);
  });
  const patch = v => object(v,['row_count','withheld_count','rows']) && integer(v.row_count,512) && integer(v.withheld_count,v.row_count) &&
    list(v.rows,512,x => object(x,['path','change_kind','before','after','source'],['row_ordinal']) &&
      (x.path === null || (string(x.path,1024) && x.path.length > 0)) &&
      ['ADDED','REMOVED','MODIFIED','REDACTED_AT_CAPTURE','WITHHELD','MALFORMED'].includes(x.change_kind) &&
      (x.before === null || hash(x.before)) && (x.after === null || hash(x.after)) && engineeringPointer(x.source) &&
      (!('row_ordinal' in x) || integer(x.row_ordinal,511))) && v.row_count === v.rows.length;
  const checkHashes = v => list(v,64,x => object(x,['check','check_hash']) && fact(x.check,'id') && fact(x.check_hash,'hash'));
  const dependencies = v => list(v,64,x => object(x,['task_id','evidence_id','matches_captured_upstream']) && fact(x.task_id,'id') && fact(x.evidence_id,'identity') && tri(x.matches_captured_upstream));
  const failure = v => object(v,['native_status','scope_error_recorded','integrity_error_recorded']) && fact(v.native_status,'token') && tri(v.scope_error_recorded) && tri(v.integrity_error_recorded);
  const deliverable = v => object(v,['candidate_location','candidate_hash','run_key','patch']) && v.candidate_location === 'WITHHELD_ABSOLUTE_LOCATOR' && fact(v.candidate_hash,'hash') && fact(v.run_key,'id') && patch(v.patch);
  const measurement = v => object(v,['scalars','execution_error_recorded','withheld_count','omitted_scalar_count','complete']) &&
    list(v.scalars,64,x => object(x,['name','value','source']) && string(x.name,1024) && engineeringPointer(x.source) &&
      (typeof x.value === 'boolean' || (typeof x.value === 'number' && Number.isFinite(x.value)))) &&
    tri(v.execution_error_recorded) && integer(v.withheld_count,4096) && integer(v.omitted_scalar_count,4096) && typeof v.complete === 'boolean';
  const checks = v => list(v,64,x => object(x,['id','check','candidate_hash','check_hash','status','summary','measurement']) &&
    facts(x,{id:'id',check:'id',candidate_hash:'hash',check_hash:'hash',status:'token',summary:'text'}) && measurement(x.measurement));
  const review = v => object(v,['recorded','verdict','reasons','candidate_hash','evidence_refs','run_key','references_cover_recorded_checks']) && typeof v.recorded === 'boolean' &&
    facts(v,{verdict:'token',candidate_hash:'hash',run_key:'id'}) && list(v.reasons,64,x => fact(x)) && list(v.evidence_refs,64,x => fact(x,'id')) && tri(v.references_cover_recorded_checks);
  const artifact = v => object(v,['deliverable','checks','review','acceptance_hash','check_hashes','dependencies','failure_indicators']) &&
    deliverable(v.deliverable) && checks(v.checks) && review(v.review) && fact(v.acceptance_hash,'hash') && checkHashes(v.check_hashes) && dependencies(v.dependencies) && failure(v.failure_indicators);
  const task = v => object(v,['task_id','objective','acceptance','check','write_paths','depends_on','workflow','currentness','deliverable','checks','review','acceptance_fingerprints','failure_indicators','uncertain_run_keys','stage','diagnostics']) &&
    facts(v,{task_id:'id',check:'id',write_paths:'paths',depends_on:'ids'}) && fact(v.objective,'text',true) && fact(v.acceptance,'text',true) && labelValue(v.stage) &&
    object(v.workflow,['state','recorded_verdict','payload_verdict','attempts','evidence_id','verification_summary']) && facts(v.workflow,{state:'token',recorded_verdict:'token',payload_verdict:'token',attempts:'int',evidence_id:'identity',verification_summary:'text'}) &&
    object(v.currentness,['active','stale','superseded_by','label']) && facts(v.currentness,{active:'bool',stale:'bool',superseded_by:'id'}) && labelValue(v.currentness.label) &&
    (v.deliverable === null || deliverable(v.deliverable)) && checks(v.checks) && review(v.review) &&
    object(v.acceptance_fingerprints,['acceptance_hash','task_hash','check_hashes','dependencies']) && facts(v.acceptance_fingerprints,{acceptance_hash:'hash',task_hash:'hash'}) && checkHashes(v.acceptance_fingerprints.check_hashes) && dependencies(v.acceptance_fingerprints.dependencies) &&
    failure(v.failure_indicators) && list(v.uncertain_run_keys,2048,x => string(x,256) && x.length > 0) && diagnostics(v.diagnostics);
  const attempt = v => object(v,['run_key','task_id','status','receipt_status','evidence_id','association','associated_task_id','unresolved','unverified_candidate','source']) &&
    facts(v,{run_key:'id',task_id:'id',status:'token',receipt_status:'token',evidence_id:'identity'}) && tokenValue(v.association) &&
    (v.associated_task_id === null || (string(v.associated_task_id,256) && v.associated_task_id.length > 0)) && typeof v.unresolved === 'boolean' && engineeringPointer(v.source) &&
    (v.unverified_candidate === null || (object(v.unverified_candidate,['candidate_hash','patch']) && fact(v.unverified_candidate.candidate_hash,'hash') && patch(v.unverified_candidate.patch)));
  const build = v => object(v,['key','created_at','status','run_key','candidate_hash','patch','dependencies','label','source']) &&
    facts(v,{key:'id',created_at:'id',status:'token',run_key:'id',candidate_hash:'hash'}) && patch(v.patch) && dependencies(v.dependencies) && v.label === 'CANDIDATE_ONLY_NOT_ACCEPTANCE' && engineeringPointer(v.source);
  if (!object(result,['schema','classification','question','conclusion','tasks','integration','attempts','control','provenance','limitations','diagnostics']) ||
      result.schema !== 'sisyfus.lead_result.engineering.s0.v1' || result.classification !== 'CAPTURED_ENGINEERING_PROJECTION_NOT_ACCEPTANCE' ||
      !engineeringText(JSON.stringify(result)) || !object(result.question,['mission_id','objective']) || !fact(result.question.mission_id,'id') || !fact(result.question.objective,'text',true) ||
      !object(result.conclusion,['stage','statements']) || !labelValue(result.conclusion.stage) || !list(result.conclusion.statements,4096,x => object(x,['template_id','text','sources']) && tokenValue(x.template_id) && string(x.text) && list(x.sources,64,engineeringPointer)) ||
      !list(result.tasks,256,task) || !list(result.attempts,2048,attempt)) return false;
  const integration = result.integration, control = result.control, provenance = result.provenance;
  return object(integration,['stage','continuation_id','continuation_state','lead_integration_revision','evidence_id','evidence_continuation_id','recorded_verdict','payload_verdict','current','result','builds','diagnostics']) && labelValue(integration.stage) &&
    facts(integration,{continuation_id:'identity',continuation_state:'token',lead_integration_revision:'int',evidence_id:'identity',evidence_continuation_id:'identity',recorded_verdict:'token',payload_verdict:'token',current:'bool'}) &&
    (integration.result === null || artifact(integration.result)) && list(integration.builds,256,build) && diagnostics(integration.diagnostics) &&
    object(control,['phase','paused','stopped','project_verified','all_verified','reason','unresolved','live_runtime']) && facts(control,{phase:'token',paused:'bool',stopped:'bool',project_verified:'bool',all_verified:'bool',reason:'text'}) && control.live_runtime === 'NOT_PROJECTED' &&
    list(control.unresolved,2048,x => object(x,['key','associated_task_id']) && fact(x.key,'id') && (x.associated_task_id === null || (string(x.associated_task_id,256) && x.associated_task_id.length > 0))) &&
    object(provenance,['capture_basis','captured_at','event_cursor','event_head_hash','pinned','bytes_reverified','projection_is_acceptance','redaction','mission_id_source','revision','resume_epoch','selected_source_fields']) &&
    provenance.capture_basis === 'CALLER_CAPTURED_NON_ATOMIC' && provenance.captured_at === null && provenance.event_cursor === null && provenance.event_head_hash === null &&
    provenance.pinned === false && provenance.bytes_reverified === false && provenance.projection_is_acceptance === false &&
    provenance.redaction === 'UPSTREAM_CONTROLLER_REDACT_ASSUMED_PLUS_S0_PATTERN_FILTER_NOT_DLP' && provenance.mission_id_source === '/id' && facts(provenance,{revision:'int',resume_epoch:'int'}) && list(provenance.selected_source_fields,128,engineeringPointer) &&
    list(result.limitations,9,x => object(x,['code','text']) && labelValue(x.code) && string(x.text)) && diagnostics(result.diagnostics);
}
function classifyEngineering(data, id) {
  if (!Object.prototype.hasOwnProperty.call(data,'engineering_result')) return {status:'MISSING',result:null,code:null};
  const invalid = {status:'INVALID',result:null,code:'INVALID_SIDECAR'};
  try {
    const side = data.engineering_result;
    if (!engineeringObject(side,['schema','mission_id','status','result','error']) || side.schema !== 'sisyfus.lead_console.engineering_result_sidecar.v1' || side.mission_id !== id) return invalid;
    if (side.status === 'OK') return side.error === null && validEngineeringResult(side.result) ? {status:'OK',result:side.result,code:null} : invalid;
    if (!['REJECTED','FAILED'].includes(side.status) || side.result !== null || !engineeringObject(side.error,['code']) || typeof side.error.code !== 'string' || !/^[A-Z][A-Z0-9_]{0,31}$/.test(side.error.code)) return invalid;
    if (side.status === 'FAILED' && !['PROJECTION_INTERNAL_ERROR','REDACTION_ALTERED'].includes(side.error.code)) return invalid;
    return {status:side.status,result:null,code:side.error.code};
  } catch (error) { return invalid; }
}
function engineeringFactText(fact) {
  if (fact.state === 'RECORDED' || fact.state === 'FILTERED') return Array.isArray(fact.value) ? fact.value.join('、') : String(fact.value);
  return ({NOT_RECORDED:'未记录',REDACTED_AT_CAPTURE:'捕获时已隐藏',WITHHELD:'已隐藏',MALFORMED:'记录格式异常'})[fact.state];
}
function buildEngineeringResult(result) {
  // Count element + possible text node before creation; reserve room for a fixed
  // truncation note. This budget never changes or crops the Core graph.
  let created = 0;
  const exhausted = {}, blocked = new Set();
  const make = (tag,content,className) => {
    const safe = content === undefined ? undefined : clean(String(content));
    const cost = safe ? 2 : 1;
    if (created + cost > 2960) throw exhausted;
    created += cost;
    return node(tag,safe,className);
  };
  const root = make('div',undefined,'engineering-evidence');
  const line = (parent,content,full = false) => {
    const safe = clean(String(content)), chars = Array.from(safe);
    parent.append(make('p',!full && chars.length > 300 ? chars.slice(0,300).join('') + '…（显示已截断）' : safe,'prose'));
  };
  const disclosure = (parent,title,key) => {
    const item = make('details',undefined,'task-row'), summary = make('summary',title);
    item.dataset.detail = 'engineering-' + key; summary.dataset.focus = 'engineering-' + key;
    item.append(summary); parent.append(item); return item;
  };
  const overflow = (parent,name,count,shown) => {
    if (count > shown) line(parent,name + '显示 ' + shown + ' / ' + count + '，省略 ' + (count - shown) + ' 项（仅展示截断）。');
  };
  const hidden = source => {
    let pointer = source;
    while (pointer) {
      if (blocked.has(pointer)) return true;
      pointer = pointer.slice(0,pointer.lastIndexOf('/'));
    }
    return false;
  };
  const restrictArtifact = (deliverable,checks,review) => {
    if (deliverable) {
      const visible = new Set(deliverable.patch.rows.slice(0,40).map(row => row.source));
      for (const row of deliverable.patch.rows.slice(40)) if (!visible.has(row.source)) blocked.add(row.source);
    }
    for (const check of checks.slice(24)) blocked.add(check.id.source.slice(0,check.id.source.lastIndexOf('/')));
    for (const check of checks.slice(0,24)) for (const scalar of check.measurement.scalars.slice(16)) blocked.add(scalar.source);
    for (const reason of review.reasons.slice(12)) blocked.add(reason.source);
  };
  for (let index = 0; index < result.tasks.length; index++) {
    if (index >= 64) blocked.add('/snapshot/nodes/' + index);
    else { const task = result.tasks[index]; restrictArtifact(task.deliverable,task.checks,task.review); }
  }
  if (result.integration.result) {
    const proof = result.integration.result;
    restrictArtifact(proof.deliverable,proof.checks,proof.review);
  }
  const artifact = (parent,deliverable,checks,review,key) => {
    const delta = disclosure(parent,'具体改动 · 记录的 hash 增量',key + '-patch');
    if (!deliverable) line(delta,'尚无记录的候选增量。');
    else {
      line(delta,'候选 hash：' + engineeringFactText(deliverable.candidate_hash),true);
      line(delta,'原调用编号：' + engineeringFactText(deliverable.run_key));
      line(delta,'源增量行数：' + deliverable.patch.row_count + '；已隐藏路径：' + deliverable.patch.withheld_count + '。');
      for (const row of deliverable.patch.rows.slice(0,40)) {
        line(delta,(row.path === null ? '已隐藏路径' : row.path) + ' · ' + row.change_kind);
        line(delta,'before=' + (row.before === null ? '未记录' : row.before) + ' → after=' + (row.after === null ? '未记录' : row.after),true);
        line(delta,'来源：' + row.source);
      }
      overflow(delta,'增量',deliverable.patch.rows.length,40);
    }
    const measured = disclosure(parent,'检查与测量 · 与独立审查分开',key + '-checks');
    if (!checks.length) line(measured,'尚无记录的检查明细。');
    for (const check of checks.slice(0,24)) {
      measured.append(make('h4',engineeringFactText(check.check) + ' · ' + engineeringFactText(check.status)));
      line(measured,'检查编号：' + engineeringFactText(check.id));
      line(measured,'评估器说明：' + engineeringFactText(check.summary));
      line(measured,'候选 hash：' + engineeringFactText(check.candidate_hash),true);
      line(measured,'检查 hash：' + engineeringFactText(check.check_hash),true);
      for (const scalar of check.measurement.scalars.slice(0,16)) {
        line(measured,scalar.name + '=' + String(scalar.value)); line(measured,'来源：' + scalar.source);
      }
      line(measured,'源测量未输出（withheld）：' + check.measurement.withheld_count + '；源 scalar 省略：' + check.measurement.omitted_scalar_count + '；complete=' + String(check.measurement.complete) + '。');
      line(measured,'执行错误是否记录：' + (check.measurement.execution_error_recorded === null ? '未记录' : String(check.measurement.execution_error_recorded)));
      overflow(measured,'测量',check.measurement.scalars.length,16);
    }
    overflow(measured,'检查',checks.length,24);
    const reviewed = disclosure(parent,'独立审查 · 记录的理由与引用',key + '-review');
    line(reviewed,'审查裁决：' + engineeringFactText(review.verdict) + '；recorded=' + String(review.recorded) + '。裁决记录不是本页重新验收。');
    for (const reason of review.reasons.slice(0,12)) line(reviewed,engineeringFactText(reason));
    overflow(reviewed,'审查理由',review.reasons.length,12);
    for (const reference of review.evidence_refs) line(reviewed,'记录引用：' + engineeringFactText(reference));
    line(reviewed,'引用是否覆盖已记录检查：' + (review.references_cover_recorded_checks === null ? '未记录' : String(review.references_cover_recorded_checks)));
  };
  try {
    const statements = result.conclusion.statements;
    root.append(make('h4','目标问题'));
    const question = statements.find(item => item.template_id === 'Q01');
    line(root,question ? question.text : engineeringFactText(result.question.objective));
    root.append(make('h4','已记录的工程结论'));
    const conclusion = statements.find(item => /^C0[1-6]$/.test(item.template_id));
    line(root,conclusion ? conclusion.text : result.conclusion.stage);
    line(root,'捕获结论阶段：' + result.conclusion.stage + '。这是非原子捕获投影，不是验收，也不是实时进程终止证明。');
    // Prioritize bounded failure signals before task details can exhaust the shared budget.
    // The 50-row cap covers result and integration diagnostics; task-level ones get their own 50.
    const diagnostic = disclosure(root,'投影诊断 · 不改变核心判定','diagnostics');
    const general = [...result.diagnostics,...result.integration.diagnostics];
    const taskLevel = result.tasks.flatMap(task => task.diagnostics);
    if (!general.length && !taskLevel.length) line(diagnostic,'本次投影没有记录诊断；这不表示验收通过。');
    for (const item of general.slice(0,50)) line(diagnostic,item.code + ' · ' + item.section + ' · ' + item.source);
    overflow(diagnostic,'诊断',general.length,50);
    for (const item of taskLevel.slice(0,50)) line(diagnostic,item.code + ' · ' + item.section + ' · ' + item.source);
    overflow(diagnostic,'子任务诊断',taskLevel.length,50);
    for (let index = 0; index < Math.min(64,result.tasks.length); index++) {
      const task = result.tasks[index];
      const entry = disclosure(root,'子任务 · ' + previewText(engineeringFactText(task.objective),80),'task-' + index);
      line(entry,'任务编号：' + engineeringFactText(task.task_id));
      line(entry,'目标：' + engineeringFactText(task.objective));
      line(entry,'原固定验收：' + engineeringFactText(task.acceptance));
      line(entry,'记录阶段：' + task.stage + '；当前性：' + task.currentness.label + '。');
      line(entry,'工作流：' + engineeringFactText(task.workflow.state) + '；记录裁决：' + engineeringFactText(task.workflow.recorded_verdict));
      line(entry,'active=' + engineeringFactText(task.currentness.active) + '；stale=' + engineeringFactText(task.currentness.stale) + '；superseded_by=' + engineeringFactText(task.currentness.superseded_by));
      artifact(entry,task.deliverable,task.checks,task.review,'task-' + index);
    }
    overflow(root,'子任务',result.tasks.length,64);
    const integration = result.integration, integrated = disclosure(root,'集成 · 当前、历史与候选分开','integration');
    line(integrated,'捕获集成阶段：' + integration.stage + '；current=' + engineeringFactText(integration.current));
    line(integrated,'记录 revision：' + engineeringFactText(integration.lead_integration_revision) + '；continuation=' + engineeringFactText(integration.continuation_id) + '；evidence=' + engineeringFactText(integration.evidence_id));
    line(integrated,'行裁决：' + engineeringFactText(integration.recorded_verdict) + '；payload 裁决：' + engineeringFactText(integration.payload_verdict));
    if (integration.result) artifact(integrated,integration.result.deliverable,integration.result.checks,integration.result.review,'integration');
    for (const build of integration.builds) {
      line(integrated,'集成候选 · 非验收：' + engineeringFactText(build.key) + ' · ' + engineeringFactText(build.status));
      line(integrated,'候选 hash：' + engineeringFactText(build.candidate_hash),true);
    }
    const provenance = disclosure(root,'来源与局限 · AS_CAPTURED','provenance');
    line(provenance,'capture_basis=' + result.provenance.capture_basis + '；非原子捕获，不重新验证字节，不是验收。');
    line(provenance,'captured_at/event_cursor/event_head_hash 均未记录；pinned=false；bytes_reverified=false；projection_is_acceptance=false。');
    line(provenance,'记录 revision=' + engineeringFactText(result.provenance.revision) + '；resume_epoch=' + engineeringFactText(result.provenance.resume_epoch));
    line(provenance,'控制器记录 phase=' + engineeringFactText(result.control.phase) + '；project_verified=' + engineeringFactText(result.control.project_verified) + '；all_verified=' + engineeringFactText(result.control.all_verified));
    line(provenance,'已记录调用：' + result.attempts.length + '；待核对调用：' + result.control.unresolved.length + '；live_runtime=' + result.control.live_runtime + '。调用结束、检查、独立审查和集成是不同记录。');
    for (const limitation of result.limitations) line(provenance,limitation.code + '：' + limitation.text);
    const evidence = disclosure(root,'依据陈述 · 有界展示，指针仅作文本','statements');
    // Secondary prose must not reintroduce records omitted by the concrete
    // task/patch/check/scalar/reason display bounds.
    const eligible = statements.filter(item => !item.sources.some(hidden));
    for (const statement of eligible.slice(0,200)) {
      line(evidence,statement.template_id + ' · ' + statement.text);
      for (const source of statement.sources) line(evidence,'来源：' + source);
    }
    line(evidence,'源陈述 ' + statements.length + ' 条；本次有界显示 ' + Math.min(200,eligible.length) + ' 条；省略 ' + (statements.length - Math.min(200,eligible.length)) + ' 条。');
  } catch (error) {
    if (error !== exhausted) throw error;
    root.append(node('p','内容过多，已截断显示；原捕获与任务图保持完整。','small muted'));
  }
  return [root];
}

$('share-enter').onclick=()=>{const value=$('share-token').value;$('share-token').value='';login(value);};
$('share-token').onkeydown=event=>{if(event.key==='Enter'&&!event.isComposing&&event.keyCode!==229){event.preventDefault();$('share-enter').click();}};
$('share-logout').onclick=logout;$('share-refresh').onclick=readSelected;$('share-message-readback').onclick=readSelected;$('share-message-send').onclick=sendMessage;$('share-report-open').onclick=openReport;
$('share-compose').addEventListener('compositionstart',()=>{state.composing=true;});$('share-compose').addEventListener('compositionend',()=>{state.composing=false;});
let initialCredential='';if(!passwordRequired)try{initialCredential=new URLSearchParams(location.hash.slice(1)).get('token')||'';}catch{}history.replaceState(null,'',location.pathname);
if(initialCredential){const value=initialCredential;initialCredential='';login(value);}
</script></body></html>
"""
