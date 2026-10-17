"""Frozen Orchestra frontend checks: local JS/DOM protocol fixtures, no providers.

These assert the requested wire contract and observable UI, independently of the
controller inbox implementation. All subprocess output/artifacts are retained.
"""
import json
import subprocess

import pytest

from sisyfus.workers.lead_chat_page import PAGE


HARNESS = r'''
const vm = require('node:vm'), assert = require('node:assert/strict');
const storage = new Map(), elements = new Map(), calls = [];
class Element {
 constructor(tag='div') { this.tagName=tag;this.children=[];this.dataset={};this.style={};this.value='';this._text='';this.hidden=false;this.checked=false;this.disabled=false;this.listeners={};this.scrollHeight=100;this.scrollTop=0;this.clientHeight=100;this.classList={add(){},remove(){},toggle(){}}; }
 get textContent(){return this._text+this.children.map(x=>x.textContent||'').join(' ');}
 set textContent(v){this._text=String(v);this.children=[];}
 append(...items){this.children.push(...items);}
 replaceChildren(...items){this._text='';this.children=items;}
 querySelectorAll(){return [];} querySelector(){return null;}
 addEventListener(name,fn){this.listeners[name]=fn;} setAttribute(){} removeAttribute(){}
 contains(){return false;} closest(){return null;} focus(){} scrollIntoView(){}
}
const el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const snapshot={snapshot:{phase:'IMPLEMENTING',nodes:[],all_verified:false},controller:{running:true},controls:[]};
let historyHook=()=>({messages:[],cursor:0,has_more:false}), postHook;
const message=(request_id='receipt-one',overrides={})=>({id:'msg-'+request_id,seq:1,request_id,kind:'context',text:'中文补充资料',status:'RECEIVED',answer:null,applications:[],...overrides});
let serial=0;
const context=vm.createContext({console,URLSearchParams,Map,Set,Date,JSON,Math,Array,String,Number,AbortController,
 crypto:{randomUUID:()=> 'request-fixture-'+(++serial)},
 location:{origin:'http://fixture.local',hash:'#token=fixture-token',pathname:'/',search:''},
 sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},history:{replaceState(){}},
 document:{getElementById:el,createElement:tag=>new Element(tag),querySelectorAll(){return [];},addEventListener(){},activeElement:null},
 window:{addEventListener(){}},requestAnimationFrame:fn=>fn(),setTimeout(){return 1;},clearTimeout(){},
 fetch:async (path,options)=>{
  const call={path,method:options.method,body:options.body&&JSON.parse(options.body),options};calls.push(call);
  assert.equal(options.headers.Authorization,'Bearer fixture-token');assert.equal(options.credentials,'same-origin');
  let data;
  if(options.method==='POST'){
   assert.equal(path,'/api/mission/message','runtime composer must never dispatch/chat/control');
   data=await postHook(call.body);
  }else if(path.startsWith('/api/mission/messages?')) data=await historyHook(new URLSearchParams(path.split('?')[1]));
  else if(path.startsWith('/api/snapshot?'))data=snapshot;
  else if(path.startsWith('/api/events?'))data={events:[],cursor:0};
  else if(path==='/api/chats')data={chats:[]};
  else if(path==='/api/missions')data={missions:[]};
  else throw Error('unexpected endpoint '+path);
  return {ok:true,status:200,json:async()=>data};
 },assert,el,message,calls,storage,
 setHistory:fn=>{historyHook=fn;},setPost:fn=>{postHook=fn;},snapshot,
});
vm.runInContext(SOURCE,context);
Promise.resolve(vm.runInContext('(async()=>{'+CASE+'})()',context)).catch(error=>{console.error(error);process.exitCode=1;});
'''


def run_js(case):
    script = PAGE.split('<script nonce="NONCE">', 1)[1].split('</script>', 1)[0]
    script = script.rsplit('render(); resizeComposer();', 1)[0]
    result = subprocess.run(
        ['node', '-'], input=HARNESS.replace('SOURCE', json.dumps(script)).replace('CASE', json.dumps(case)),
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('phase', ['IMPLEMENTING', 'PAUSED', 'STOPPED', 'UNKNOWN', 'COMPLETED'])
def test_runtime_composer_and_exact_wire_payload(phase):
    run_js(r'''
snapshot.snapshot.phase=PHASE;
await selectMission('mission-a');
assert.equal(el('composer-wrap').hidden,false);
assert.equal(el('composer-input').readOnly,false);
assert.match(el('composer-help').textContent,/\/btw/);
el('composer-input').value='/btw 现在进度如何？';renderAvailability();assert.equal(el('send').disabled,false);
setPost(body=>{assert.deepEqual(Object.keys(body).sort(),['message','mission_id','request_id']);assert.equal(body.mission_id,'mission-a');assert.equal(body.message,'/btw 现在进度如何？');return message(body.request_id,{kind:'query',text:body.message,status:'ANSWERED',answer:{phase:PHASE,summary:'当前进度快照',blockers:['等待核对'],latest_results:[],active_tasks:[],all_verified:false,revision:2,observed_at:'2026-10-06',observed_event_cursor:17}});});
await sendMessage();
assert.equal(calls.filter(c=>c.method==='POST').length,1);
assert.match(el('mission-message-thread').textContent,/当前进度快照/);
assert.match(el('mission-message-thread').textContent,/等待核对/);
assert.match(el('mission-message-thread').textContent,/17/);
assert.equal(snapshot.snapshot.all_verified,false);
'''.replace('PHASE', json.dumps(phase)))


def test_bound_planning_chat_is_frozen_with_task_link():
    run_js(r'''
state.kind='chat';state.id='plan-a';state.connected=true;
state.chat={id:state.id,mission_id:'mission-a',status:'IDLE',messages:[],checks:[]};
render();el('composer-input').value='新补充';await sendMessage();
assert.equal(el('composer-input').readOnly,true);assert.equal(el('send').disabled,true);
assert.equal(el('linked-mission').hidden,false);
assert.match(el('chat-note-text').textContent,/任务/);
assert.equal(calls.length,0);
await el('linked-mission').onclick();assert.equal(state.kind,'mission');assert.equal(state.id,'mission-a');
''')


def test_old_application_states_refresh_with_complete_paged_history():
    run_js(r'''
let applied=false;
setHistory(params=>{assert.equal(params.get('mission_id'),'mission-a');const cursor=Number(params.get('cursor'));
 if(cursor===0)return {messages:[message('first',{applications:[{run_key:'run-one',role:'worker',task_id:'task-one',status:applied?'APPLIED':'BOUND',delivery:null}]})],cursor:1,has_more:true};
 assert.equal(cursor,1);return {messages:[message('second',{seq:2})],cursor:2,has_more:false};});
await selectMission('mission-a');
assert.match(el('mission-message-thread').textContent,/已收到/);
assert.match(el('mission-message-thread').textContent,/已绑定/);
assert.match(el('mission-message-thread').textContent,/run-one/);
assert.match(el('mission-message-thread').textContent,/task-one/);
assert.match(el('mission-message-thread').textContent,/first/);assert.match(el('mission-message-thread').textContent,/second/);
applied=true;await readSelected();
assert.match(el('mission-message-thread').textContent,/已应用到原生调用/);
assert.match(el('mission-message-thread').textContent,/提示词/);
assert.match(el('mission-message-thread').textContent,/不代表.*验收/);
assert.equal(calls.filter(c=>c.path.includes('/api/mission/messages?')&&c.path.endsWith('cursor=0')).length,2);
assert.equal(el('mission-status').textContent.includes('验收与集成已通过'),false);
''')


def test_unknown_post_uses_exact_request_readback_not_arbitrary_receipts():
    run_js(r'''
await selectMission('mission-a');let request;
setPost(body=>{request=body;throw Object.assign(Error('lost reply'),{name:'AbortError'});});
setHistory(()=>({messages:[message('unrelated')],cursor:1,has_more:false}));
el('composer-input').value='补充信息';await sendMessage();
assert.equal(calls.filter(c=>c.method==='POST').length,1);
assert.match(el('mission-inbox-note').textContent,/待确认/);
assert.ok([...state.pending.values()].some(p=>p.request_id===request.request_id));
el('composer-input').value='another';renderAvailability();assert.equal(el('send').disabled,true);
setHistory(()=>({messages:[message(request.request_id,{text:request.message})],cursor:1,has_more:false}));
await readSelected();
assert.equal([...state.pending.values()].some(p=>p.request_id===request.request_id),false);
assert.equal(el('send').disabled,false);
assert.equal(calls.filter(c=>c.method==='POST').length,1,'readback never resends');
''')


def test_explicit_retry_reuses_the_original_request_identity_and_text():
    run_js(r'''
await selectMission('mission-a');let original;
setPost(body=>{original=body;throw Object.assign(Error('timeout'),{name:'AbortError'});});
el('composer-input').value='原始补充';await sendMessage();
assert.equal(el('mission-inbox-retry').hidden,false);
el('composer-input').value='尚未发送的新草稿';
setPost(body=>{assert.deepEqual(body,original);return message(body.request_id,{text:body.message});});
await el('mission-inbox-retry').onclick();
assert.equal(calls.filter(c=>c.method==='POST').length,2);
assert.equal(el('composer-input').value,'尚未发送的新草稿');
assert.equal([...state.pending.values()].some(p=>p.request_id===original.request_id),false);
''')


@pytest.mark.parametrize('bad_page', ['nonadvancing', 'endless', 'malformed', 'late_failure'])
def test_history_failure_is_explicit_bounded_and_retains_prior_rows(bad_page):
    run_js(r'''
setHistory(()=>({messages:[message('retained')],cursor:1,has_more:false}));await selectMission('mission-a');
let count=0;
setHistory(params=>{count++;const cursor=Number(params.get('cursor'));
 if(BAD==='nonadvancing')return {messages:[],cursor,has_more:true};
 if(BAD==='endless')return {messages:[message('p'+count,{seq:cursor+1})],cursor:cursor+1,has_more:true};
 if(BAD==='malformed')return {messages:[{id:'bad'}],cursor:1,has_more:false};
 if(count===1)return {messages:[message('partial')],cursor:1,has_more:true};throw Error('history page disconnected');});
await readSelected();
assert.ok(count<=64,'bounded page count');
assert.match(el('mission-inbox-note').textContent,/失败|异常|上限|不完整|中断/);
assert.match(el('mission-message-thread').textContent,/retained/);
assert.doesNotMatch(el('mission-message-thread').textContent,/partial/,'incomplete fetch is not committed as complete history');
assert.equal(el('mission-inbox-refresh').hidden,false);
assert.equal(calls.filter(c=>c.method==='POST').length,0);
'''.replace('BAD', json.dumps(bad_page)))


def test_multi_mission_drafts_history_and_pending_do_not_cross():
    run_js(r'''
setHistory(params=>({messages:[message(params.get('mission_id'))],cursor:1,has_more:false}));
await selectMission('mission-a');el('composer-input').value='A 草稿';
await selectMission('mission-b');assert.equal(el('composer-input').value,'');
assert.match(el('mission-message-thread').textContent,/mission-b/);assert.doesNotMatch(el('mission-message-thread').textContent,/mission-a/);
el('composer-input').value='B 草稿';await selectMission('mission-a');assert.equal(el('composer-input').value,'A 草稿');
assert.doesNotMatch(el('mission-message-thread').textContent,/mission-b/);
setPost(()=>{throw Object.assign(Error('lost'),{name:'AbortError'});});await sendMessage();
await selectMission('mission-b');renderAvailability();assert.equal(el('composer-input').value,'B 草稿');assert.equal(el('send').disabled,false);
assert.doesNotMatch(el('mission-inbox-note').textContent,/待确认/);
''')


def test_stale_read_and_post_cannot_overwrite_new_view_or_newer_version():
    run_js(r'''
await selectMission('mission-a');let release;
setHistory(()=>new Promise(resolve=>{release=resolve;}));const oldRead=readSelected();
await Promise.resolve();await Promise.resolve();await Promise.resolve();
assert.equal(typeof release,'function');state.version++;
release({messages:[message('stale-version')],cursor:1,has_more:false});await oldRead;
assert.doesNotMatch(el('mission-message-thread').textContent,/stale-version/);
setHistory(()=>({messages:[],cursor:0,has_more:false}));await readSelected();
let releasePost;setPost(body=>new Promise(resolve=>{releasePost=()=>resolve(message(body.request_id,{text:'A private text'}));}));
el('composer-input').value='A private text';const sending=sendMessage();await Promise.resolve();
await selectMission('mission-b');releasePost();await sending;
assert.equal(state.id,'mission-b');assert.doesNotMatch(el('mission-message-thread').textContent,/A private text/);
assert.equal(el('composer-input').value,'');
''')


def test_refresh_restores_selection_pending_and_reads_without_posting():
    run_js(r'''
await selectMission('mission-a');let request;
setPost(body=>{request=body;throw Object.assign(Error('lost'),{name:'AbortError'});});
el('composer-input').value='刷新前补充';await sendMessage();
assert.ok([...storage.values()].some(value=>value.includes(request.request_id)));
state.kind='welcome';state.id='';state.mission=null;
setHistory(()=>({messages:[message(request.request_id,{text:request.message})],cursor:1,has_more:false}));
const posts=calls.filter(c=>c.method==='POST').length;
await restoreSelectedView();
assert.equal(state.kind,'mission');assert.equal(state.id,'mission-a');
assert.equal(calls.filter(c=>c.method==='POST').length,posts);
assert.equal([...state.pending.values()].some(p=>p.request_id===request.request_id),false);
assert.match(el('mission-message-thread').textContent,/刷新前补充/);
''')


def test_ime_and_untrusted_text_stay_text_and_never_dispatch():
    run_js(r'''
setHistory(()=>({messages:[message('untrusted',{text:'<img src=x onerror=alert(1)>',applications:[]})],cursor:1,has_more:false}));
await selectMission('mission-a');el('composer-input').value='中文';
const key=(extra)=>el('composer-input').listeners.keydown({key:'Enter',shiftKey:false,isComposing:false,keyCode:13,preventDefault(){throw Error('IME should not be consumed');},...extra});
el('composer-input').listeners.compositionstart();key({});el('composer-input').listeners.compositionend();key({isComposing:true});key({keyCode:229});key({shiftKey:true});
await Promise.resolve();assert.equal(calls.filter(c=>c.method==='POST').length,0);
assert.match(el('mission-message-thread').textContent,/<img src=x onerror=alert\(1\)>/);
const tags=root=>[root.tagName,...root.children.flatMap(tags)];assert.equal(tags(el('mission-message-thread')).includes('img'),false);
''')


def test_task_conversation_is_in_same_page_with_mobile_and_existing_evidence():
    assert 'id="mission-message-thread"' in PAGE
    assert 'id="mission-inbox-note"' in PAGE
    assert 'id="mission-inbox-refresh"' in PAGE
    assert '@media(max-width:700px)' in PAGE
    assert 'env(safe-area-inset-bottom)' in PAGE
    assert 'overflow-wrap:anywhere' in PAGE
    for marker in ['id="task-list"', 'id="progress-thread"', 'id="rsi-evidence"',
                   'id="mission-resume"', 'id="mission-stop"']:
        assert marker in PAGE
