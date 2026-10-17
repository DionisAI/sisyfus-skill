"""Frozen frontend P2 regression goals; JS/DOM fixtures, not native acceptance.

Message and application-update streams have independent durable cursors. History
size bounds a catch-up round, not the mission or the ability to submit. Cache
restoration must include its records, never just a cursor that skips history.
"""
import json
import subprocess

import pytest

from sisyfus.workers.lead_chat_page import PAGE


HARNESS = r'''
const vm=require('node:vm'), assert=require('node:assert/strict');
const storage=new Map();let failStorage=false;
const hooks={history:()=>({messages:[],cursor:0,has_more:false,updates:[],application_cursor:0,has_more_updates:false}),post:null};
let uuid=0;
function createApp(){
 const elements=new Map(),calls=[];let created=0;
 class Element{
  constructor(tag='div'){created++;this.tagName=tag;this.children=[];this.dataset={};this.style={};this.value='';this._text='';this.hidden=false;this.checked=false;this.disabled=false;this.listeners={};this.scrollHeight=100;this.scrollTop=0;this.clientHeight=100;this.classList={add(){},remove(){},toggle(){}};}
  get textContent(){return this._text+this.children.map(x=>x.textContent||'').join(' ');}
  set textContent(v){this._text=String(v);this.children=[];}
  append(...items){this.children.push(...items);}replaceChildren(...items){this._text='';this.children=items;}
  querySelectorAll(){return [];}querySelector(){return null;}addEventListener(name,fn){this.listeners[name]=fn;}
  setAttribute(){}removeAttribute(){}contains(){return false;}closest(){return null;}focus(){}scrollIntoView(){}
 }
 const el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const context=vm.createContext({console,URLSearchParams,Map,Set,Date,JSON,Math,Array,String,Number,AbortController,
  crypto:{randomUUID:()=> 'request-review-'+(++uuid)},
  location:{origin:'http://fixture.local',hash:'#token=fixture-token',pathname:'/',search:''},
  sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>{if(failStorage&&key.includes(':inbox'))throw Error('cache quota fixture');storage.set(key,value);}},history:{replaceState(){}},
  document:{getElementById:el,createElement:tag=>new Element(tag),querySelectorAll(){return [];},addEventListener(){},activeElement:null},
  window:{addEventListener(){}},requestAnimationFrame:fn=>fn(),setTimeout(){return 1;},clearTimeout(){},
  fetch:async(path,options)=>{
   calls.push({path,method:options.method,body:options.body&&JSON.parse(options.body)});
   assert.equal(options.headers.Authorization,'Bearer fixture-token');assert.equal(options.credentials,'same-origin');assert.equal(options.cache,'no-store');
   let data;
   if(options.method==='POST'){assert.equal(path,'/api/mission/message','no worker dispatch, planning chat or control');data=await hooks.post(JSON.parse(options.body));}
   else if(path.startsWith('/api/mission/messages?'))data=await hooks.history(new URLSearchParams(path.split('?')[1]));
   else if(path.startsWith('/api/snapshot?'))data={snapshot:{phase:'IMPLEMENTING',nodes:[],all_verified:false},controller:{running:true},controls:[]};
   else if(path.startsWith('/api/events?'))data={events:[],cursor:0};
   else if(path==='/api/chats')data={chats:[]};else if(path==='/api/missions')data={missions:[]};
   else throw Error('unexpected endpoint '+path);
   return {ok:true,status:200,json:async()=>data};
  },assert,el,calls,storage,
  setHistory:fn=>{hooks.history=fn;},setPost:fn=>{hooks.post=fn;},setCacheFailure:flag=>{failStorage=flag;},
  creationCount:()=>created,restart:()=>{const next=createApp();return {run:code=>vm.runInContext('(async()=>{'+code+'})()',next.context),el:next.el,calls:next.calls};},
 });
 vm.runInContext(__PAGE_SCRIPT__,context);
 vm.runInContext(`
 const record=(seq,extra={})=>({id:'msg-'+seq,seq,request_id:'receipt-'+seq,kind:'context',text:'消息 '+seq,status:'RECEIVED',answer:null,applications:[],...extra});
 const receipt=(status)=>({run_key:'run-one',role:'worker',task_id:'task-one',status,delivery:null});
 function page(params,records,changes=[]){
  assert.ok(params.has('application_cursor'),'every read carries both cursors');
  const cursor=Number(params.get('cursor')),app=Number(params.get('application_cursor'));
  const next=records.filter(r=>r.seq>cursor).slice(0,100),events=changes.filter(c=>c.seq>app).slice(0,100);
  const ids=new Set(events.map(c=>c.id));
  return {messages:next,cursor:next.length?next.at(-1).seq:cursor,has_more:records.some(r=>r.seq>(next.at(-1)?.seq??cursor)),
   updates:records.filter(r=>r.seq<=cursor&&ids.has(r.id)),application_cursor:events.length?events.at(-1).seq:app,has_more_updates:changes.some(c=>c.seq>(events.at(-1)?.seq??app))};
 }
 const historyCalls=()=>calls.filter(c=>c.path.startsWith('/api/mission/messages?'));
 const params=call=>new URLSearchParams(call.path.split('?')[1]);
 const row=seq=>el('mission-message-thread').children.find(child=>child.textContent.includes('消息 msg-'+seq+' ·'));
 async function catchUp(max=30){for(let i=0;i<max&&(missionInbox(state.id).has_more||missionInbox(state.id).has_more_updates);i++)await readSelected();assert.equal(missionInbox(state.id).has_more,false);assert.equal(missionInbox(state.id).has_more_updates,false);}
 `,context);
 return {context,el,calls};
}
const app=createApp();
Promise.resolve(vm.runInContext('(async()=>{'+__CASE__+'})()',app.context)).catch(error=>{console.error(error);process.exitCode=1;});
'''


def run_js(case):
    script = PAGE.split('<script nonce="NONCE">', 1)[1].split('</script>', 1)[0]
    script = script.rsplit('render(); resizeComposer();', 1)[0]
    harness = HARNESS.replace('__PAGE_SCRIPT__', json.dumps(script)).replace('__CASE__', json.dumps(case))
    result = subprocess.run(['node', '-e', harness], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_more_than_4000_messages_continue_across_bounded_rounds_without_lockout():
    run_js(r'''
const records=Array.from({length:4505},(_,i)=>record(i+1));setHistory(p=>page(p,records));
await selectMission('large-mission');const inbox=missionInbox(state.id);
assert.ok(historyCalls().length<=10,'one round is bounded');assert.ok(inbox.cursor>0&&inbox.cursor<4505);
assert.equal(inbox.has_more,true);assert.equal(inbox.error,'');assert.match(el('mission-inbox-note').textContent,/继续|追赶|尚未|加载/);
el('composer-input').value='/btw';renderAvailability();assert.equal(el('send').disabled,false,'catch-up must not fence the composer');
await catchUp();assert.equal(inbox.cursor,4505);assert.equal(inbox.messages.length,4505);
assert.equal(new Set(inbox.messages.map(m=>m.seq)).size,4505);assert.ok(row(1));assert.ok(row(4505));
assert.equal(historyCalls().filter(c=>params(c).get('cursor')==='0').length,1,'no repeated full scans');
const before=historyCalls().length;await readSelected();assert.equal(historyCalls().length,before+1);assert.equal(params(historyCalls().at(-1)).get('cursor'),'4505');
setPost(body=>{const m=record(4506,{request_id:body.request_id,text:body.message});records.push(m);return m;});
await sendMessage();assert.equal(calls.filter(c=>c.method==='POST').length,1);assert.equal(inbox.cursor,4506);assert.equal(inbox.messages.length,4506);
assert.equal([...state.pending.values()].length,0);assert.equal(el('send').disabled,true,'empty input remains disabled');
''')


def test_post_receipt_never_skips_unread_history_or_duplicates_records():
    run_js(r'''
const records=Array.from({length:5001},(_,i)=>record(i+1));setHistory(p=>page(p,records));await selectMission('large-mission');
setPost(body=>{const m=record(5002,{request_id:body.request_id,text:body.message});records.push(m);return m;});
el('composer-input').value='新补充';await sendMessage();const inbox=missionInbox(state.id);
assert.ok(inbox.cursor<5002,'POST seq is not a history cursor');assert.equal(inbox.has_more,true);assert.ok(inbox.messages.some(m=>m.seq===5002));
await catchUp();assert.equal(inbox.messages.length,5002);assert.equal(new Set(inbox.messages.map(m=>m.id)).size,5002);assert.equal(inbox.cursor,5002);
for(let seq=1;seq<=5002;seq++)assert.equal(inbox.messages[seq-1].seq,seq);
''')


def test_application_cursor_refreshes_old_messages_and_preserves_untouched_dom():
    run_js(r'''
const records=[record(1,{applications:[receipt('BOUND')]}),record(2),record(3)],changes=[];
setHistory(p=>page(p,records,changes));await selectMission('application-mission');const untouched=row(3),first=row(1);
records[0]={...records[0],status:'APPLIED',applications:[receipt('APPLIED')]};changes.push({seq:1,id:'msg-1'});
await readSelected();assert.equal(params(historyCalls().at(-1)).get('cursor'),'3');assert.equal(params(historyCalls().at(-1)).get('application_cursor'),'0');
assert.equal(missionInbox(state.id).cursor,3);assert.equal(missionInbox(state.id).application_cursor,1);
assert.equal(row(3),untouched,'unaffected conversation rows are reused');assert.equal(row(1),first,'updated row keeps its identity');
assert.match(row(1).textContent,/已应用到原生调用/);assert.match(row(1).textContent,/不代表.*验收/);
records.push(record(4));changes.push({seq:2,id:'msg-2'});records[1]={...records[1],applications:[receipt('BOUND')]};
await readSelected();assert.equal(missionInbox(state.id).cursor,4);assert.equal(missionInbox(state.id).application_cursor,2);
assert.match(row(2).textContent,/已绑定/);assert.ok(row(4));assert.equal(state.mission.snapshot.all_verified,false);
const count=creationCount();await readSelected();assert.ok(creationCount()-count<40,'an empty incremental poll does not rebuild the full thread');
assert.equal(params(historyCalls().at(-1)).get('application_cursor'),'2');
''')


def test_more_than_4000_application_events_catch_up_without_reloading_messages():
    run_js(r'''
const records=[record(1),record(2)],changes=[];setHistory(p=>page(p,records,changes));await selectMission('application-mission');
records[0]={...records[0],status:'APPLIED',applications:[receipt('APPLIED')]};
for(let seq=1;seq<=4201;seq++)changes.push({seq,id:seq%2?'msg-1':'msg-2'});
const before=historyCalls().length;await readSelected();const inbox=missionInbox(state.id);
assert.ok(historyCalls().length-before<=10);assert.ok(inbox.application_cursor>0&&inbox.application_cursor<4201);assert.equal(inbox.has_more_updates,true);
assert.equal(inbox.error,'');assert.match(el('mission-inbox-note').textContent,/继续|追赶|尚未|加载/);
await catchUp();assert.equal(inbox.application_cursor,4201);assert.equal(inbox.cursor,2);assert.equal(inbox.messages.length,2);
assert.match(row(1).textContent,/已应用到原生调用/);
assert.equal(historyCalls().filter(c=>params(c).get('cursor')==='0').length,1);
''')


@pytest.mark.parametrize('initial_failure', [False, True])
def test_transient_history_failure_never_locks_a_loaded_mission(initial_failure):
    run_js(r'''
const records=[record(1)];setHistory(p=>page(p,records));
if(INITIAL)setHistory(()=>{throw Error('history disconnected');});
await selectMission('available-mission');setHistory(()=>{throw Error('history disconnected');});await readSelected();
assert.match(el('mission-inbox-note').textContent,/失败|中断/);assert.equal(el('composer-wrap').hidden,false);
el('composer-input').value='补充信息';renderAvailability();assert.equal(el('send').disabled,false);
setPost(body=>record(2,{request_id:body.request_id,text:body.message}));await sendMessage();
assert.equal(calls.filter(c=>c.method==='POST').length,1);assert.equal(state.pending.has(missionMessageKey(state.id)),false);
el('composer-input').value='/btw';renderAvailability();assert.equal(el('send').disabled,false);
'''.replace('INITIAL', json.dumps(initial_failure)))


def test_valid_pages_survive_a_later_failure_and_resume_from_their_checkpoint():
    run_js(r'''
const records=[record(1),record(2),record(3)];setHistory(p=>page(p,records));await selectMission('checkpoint-mission');
for(let seq=4;seq<=203;seq++)records.push(record(seq));let rounds=0;
setHistory(p=>{if(++rounds===2)throw Error('page disconnected');return page(p,records);});await readSelected();
const inbox=missionInbox(state.id);assert.equal(inbox.cursor,103);assert.equal(inbox.messages.length,103);assert.equal(inbox.has_more,true);
assert.match(el('mission-inbox-note').textContent,/失败|中断/);assert.doesNotMatch(el('mission-inbox-note').textContent,/历史已完整/);
el('composer-input').value='/btw';renderAvailability();assert.equal(el('send').disabled,false);
setHistory(p=>page(p,records));const before=historyCalls().length;await readSelected();
assert.equal(params(historyCalls()[before]).get('cursor'),'103');assert.equal(inbox.cursor,203);assert.equal(inbox.messages.length,203);assert.equal(inbox.has_more,false);
''')


def test_unknown_submission_is_fenced_through_errors_and_unfinished_catchup():
    run_js(r'''
const records=[record(1)];setHistory(p=>page(p,records));await selectMission('pending-mission');let sent;
setPost(body=>{sent=body;throw Object.assign(Error('post timeout'),{name:'AbortError'});});
setHistory(()=>{throw Error('read timeout');});el('composer-input').value='待核对';await sendMessage();
assert.equal(state.pending.get(missionMessageKey(state.id)).request_id,sent.request_id);
el('composer-input').value='下一条';renderAvailability();assert.equal(el('send').disabled,true);assert.equal(el('mission-inbox-retry').hidden,true);
for(let seq=2;seq<=1800;seq++)records.push(record(seq));setHistory(p=>page(p,records));await readSelected();
assert.equal(missionInbox(state.id).has_more,true);assert.equal(el('mission-inbox-retry').hidden,true,'absence is not established by an unfinished stream');
assert.equal(el('send').disabled,true);assert.equal(calls.filter(c=>c.method==='POST').length,1);
await catchUp();assert.equal(el('mission-inbox-retry').hidden,false);
setPost(body=>{assert.equal(JSON.stringify(body),JSON.stringify(sent));const m=record(1801,{request_id:body.request_id,text:body.message});records.push(m);return m;});
await el('mission-inbox-retry').onclick();assert.equal(calls.filter(c=>c.method==='POST').length,2);assert.equal(state.pending.has(missionMessageKey(state.id)),false);
assert.equal(el('composer-input').value,'下一条');
''')


def test_exact_pending_receipt_clears_during_catchup_without_automatic_resend():
    run_js(r'''
const records=[record(1)];setHistory(p=>page(p,records));await selectMission('pending-mission');let sent;
setPost(body=>{sent=body;const own=record(2,{request_id:body.request_id,text:body.message});records.push(own);for(let seq=3;seq<=1600;seq++)records.push(record(seq));throw Object.assign(Error('post timeout'),{name:'AbortError'});});
el('composer-input').value='自己的消息';await sendMessage();
assert.equal(missionInbox(state.id).has_more,true);assert.equal(state.pending.has(missionMessageKey(state.id)),false,'positive exact evidence need not wait for the tail');
assert.ok(missionInbox(state.id).messages.some(m=>m.request_id===sent.request_id));assert.equal(calls.filter(c=>c.method==='POST').length,1);
el('composer-input').value='/btw';renderAvailability();assert.equal(el('send').disabled,false);
''')


def test_reload_restores_records_both_cursors_and_pending_then_only_reads_tail():
    run_js(r'''
const records=[record(1),record(2)],changes=[];setHistory(p=>page(p,records,changes));await selectMission('reload-mission');
records[0]={...records[0],status:'APPLIED',applications:[receipt('APPLIED')]};changes.push({seq:1,id:'msg-1'});await readSelected();
let sent;setPost(body=>{sent=body;records.push(record(3,{request_id:body.request_id,text:body.message}));throw Object.assign(Error('lost ack'),{name:'AbortError'});});
setHistory(()=>{throw Error('offline');});el('composer-input').value='重载前信息';await sendMessage();
setHistory(p=>page(p,records,changes));const next=restart();
await next.run(`await restoreSelectedView();assert.equal(state.id,'reload-mission');const inbox=missionInbox(state.id);assert.equal(inbox.cursor,3);assert.equal(inbox.application_cursor,1);assert.equal(inbox.messages.length,3);assert.match(row(1).textContent,/已应用到原生调用/);assert.equal(state.pending.has(missionMessageKey(state.id)),false);`);
const reads=next.calls.filter(c=>c.path.startsWith('/api/mission/messages?'));
assert.equal(params(reads[0]).get('cursor'),'2');assert.equal(params(reads[0]).get('application_cursor'),'1');assert.equal(next.calls.filter(c=>c.method==='POST').length,0);
assert.match(next.el('mission-message-thread').textContent,/重载前信息/);
''')


def test_reload_resumes_partial_history_without_claiming_it_complete():
    run_js(r'''
const records=Array.from({length:4501},(_,i)=>record(i+1));setHistory(p=>page(p,records));await selectMission('partial-mission');
const saved=missionInbox(state.id).cursor;assert.ok(saved>0&&saved<4501);const next=restart();
await next.run(`await restoreSelectedView();assert.equal(missionInbox(state.id).has_more,true);assert.match(el('mission-inbox-note').textContent,/继续|追赶|尚未|加载/);await catchUp();assert.equal(missionInbox(state.id).messages.length,4501);assert.ok(row(1));assert.ok(row(4501));`);
assert.equal(params(next.calls.find(c=>c.path.startsWith('/api/mission/messages?'))).get('cursor'),String(saved));
''')


def test_cache_quota_failure_keeps_current_history_and_replays_from_zero_on_reload():
    run_js(r'''
setCacheFailure(true);const records=[record(1),record(2)];setHistory(p=>page(p,records));await selectMission('quota-mission');
assert.equal(missionInbox(state.id).messages.length,2);assert.match(el('mission-inbox-note').textContent,/本页|缓存|存储/);
el('composer-input').value='/btw';renderAvailability();assert.equal(el('send').disabled,false);
setCacheFailure(false);const next=restart();await next.run(`await restoreSelectedView();assert.equal(missionInbox(state.id).messages.length,2);assert.ok(row(1));`);
assert.equal(params(next.calls.find(c=>c.path.startsWith('/api/mission/messages?'))).get('cursor'),'0');
''')


@pytest.mark.parametrize('bad', ['regression', 'stalled_updates', 'partial_update_contract', 'orphan_update', 'invalid_message', 'changed_identity'])
def test_invalid_incremental_page_preserves_both_cursors_without_disabling_composer(bad):
    run_js(r'''
const records=[record(1),record(2)];setHistory(p=>page(p,records));await selectMission('invalid-mission');
setHistory(p=>{const b=page(p,records);
 if(BAD==='regression')b.cursor=1;
 if(BAD==='stalled_updates')b.has_more_updates=true;
 if(BAD==='partial_update_contract')delete b.application_cursor;
 if(BAD==='orphan_update'){b.updates=[record(1,{id:'orphan'})];b.application_cursor=1;}
 if(BAD==='invalid_message'){b.messages=[{id:'bad'}];b.cursor=3;}
 if(BAD==='changed_identity'){b.updates=[record(1,{request_id:'changed'})];b.application_cursor=1;}
 return b;});await readSelected();
const inbox=missionInbox(state.id);assert.equal(inbox.cursor,2);assert.equal(inbox.application_cursor,0);assert.equal(inbox.messages.length,2);
assert.match(el('mission-inbox-note').textContent,/失败|异常|不完整/);
el('composer-input').value='/btw';renderAvailability();assert.equal(el('send').disabled,false);assert.equal(calls.filter(c=>c.method==='POST').length,0);
'''.replace('BAD', json.dumps(bad)))


def test_stale_versions_and_foreign_missions_never_commit_cursors_or_updates():
    run_js(r'''
const records=[record(1)];setHistory(p=>page(p,records));await selectMission('mission-a');let release;
setHistory(()=>new Promise(resolve=>{release=resolve;}));const old=readSelected();state.version++;
release({messages:[record(2)],cursor:2,has_more:false,updates:[],application_cursor:7,has_more_updates:false});await old;
assert.equal(missionInbox('mission-a').cursor,1);assert.equal(missionInbox('mission-a').application_cursor,0);assert.equal(missionInbox('mission-a').messages.length,1);
setHistory(p=>page(p,[record(10,{id:'mission-b-only',request_id:'b-only',text:'B 信息'})]));await selectMission('mission-b');
assert.equal(params(historyCalls().at(-1)).get('cursor'),'0');assert.equal(missionInbox('mission-b').cursor,10);assert.doesNotMatch(el('mission-message-thread').textContent,/消息 msg-1 ·/);
setHistory(p=>page(p,records));await selectMission('mission-a');assert.equal(params(historyCalls().at(-1)).get('cursor'),'1');assert.ok(row(1));assert.doesNotMatch(el('mission-message-thread').textContent,/B 信息/);
''')
