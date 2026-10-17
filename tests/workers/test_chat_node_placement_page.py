"""Frozen production-page protocol tests, not native/device acceptance.

Static checked shapes: ChatSessions public chat+planning_only ACK; core snapshot
wrapper; distinct registry namespace vs Hub id; exact pin; NodeAgent six fields.
New DOM IDs are declared in TECHLEAD-NODE-WEB-PLACEMENT-PAGE before freeze.
No inherited tests edited. All subprocess outputs and test directories retained.
"""
import json
import subprocess
from html.parser import HTMLParser

import pytest

from sisyfus.workers.lead_chat_page import PAGE


HARNESS = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
const elements=new Map(),storage=new Map(),calls=[],copies=[],downloads=[];
class Element {
 constructor(tag='div'){this.tagName=tag;this.children=[];this.dataset={};this.style={};this.value='';this._text='';this.hidden=false;this.disabled=false;this.checked=false;this.readOnly=false;this.listeners={};this.attributes={};this.scrollHeight=100;this.scrollTop=0;this.clientHeight=100;this.classList={add(){},remove(){},toggle(){}};}
 get textContent(){return this._text+this.children.map(x=>x.textContent||'').join(' ');}
 set textContent(v){this._text=String(v);this.children=[];}
 append(...items){this.children.push(...items);} replaceChildren(...items){this.children=items;this._text='';}
 querySelectorAll(){return [];} querySelector(){return null;}
 addEventListener(name,fn){this.listeners[name]=fn;} setAttribute(k,v){this.attributes[k]=String(v);} removeAttribute(k){delete this.attributes[k];}
 contains(){return false;} closest(){return null;} focus(){this.focused=true;} scrollIntoView(){} remove(){this.hidden=true;}
 click(){return this.onclick?.({preventDefault(){},target:this});}
}
const el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const mid='m_'+'1'.repeat(32),other='m_'+'2'.repeat(32),cid='c_'+'a'.repeat(32),nid='node_'+'3'.repeat(32),ns='mission_'+'b'.repeat(32),secret='d'.repeat(64);
const chat={id:cid,title:'研究工程',status:'IDLE',messages:[],source:'/synthetic/source',spec_path:'/synthetic/checks.json',approval_hash:'a'.repeat(64),
 proposal:{objective:'研究是否盈利',architecture:'固定验证后独立复核',deliverables:['报告'],constraints:['两家交易所'],tasks:[{title:'固定子任务'}]},
 checks:[{id:'fixed-check',contract:{pass_if:{op:'eq',value:true},fail_if:{op:'eq',value:false}}}],readiness:{ready:true,can_prepare:true,requirements:[]}};
const task={id:'task-one',title:'公开数据比较',objective:'比较价差',acceptance:'固定检查',check:'fixed-check',write_paths:['result.txt'],depends_on:[],active:true,state:'READY',verdict:'UNVERIFIED',attempts:0};
const snapshot={snapshot:{phase:'WAITING_PLACEMENT',nodes:[task],all_verified:false,revision:1,placement_preparation:{request_id:'prepare-original-0001',status:'COMPLETED',known_nonexecuted:false}},controller:{running:false},controls:[]};
const registered={mission_id:ns,node_id:nid,request_id:'node-original-0001',name:'远端 Mac',drivers:['codex'],models:['gpt-6.1-sol'],status:'ACTIVE',created_at:'2026-10-06',revoked_at:null};
const inventory={mission_id:mid,nodes:[registered],execution_ready:false};
const placements={mission_id:mid,placements:[{task_id:task.id,placement:{kind:'local'}}]};
const pin=request_id=>({kind:'remote',mission_id:ns,task_id:task.id,node_id:nid,task_hash:'9'.repeat(64),revision:1,request_id,execution_ready:false,created_at:'2026-10-06'});
let getHook=null,postHook=null,serial=0;
function all(){const seen=new Set();function walk(x){if(!x||seen.has(x))return;seen.add(x);for(const c of x.children||[])walk(c);}for(const x of elements.values())walk(x);return [...seen];}
function findSelect(){return all().find(x=>x.dataset.taskId===task.id&&x.dataset.nodeId===nid);}
function bound(request_id){const control={id:'prepare-placement:'+request_id,mission_id:mid,request_id,action:'prepare-placement',status:'ACK',accepted:true,terminal:false,scope:'planning_only'};
 return {...chat,mission_id:mid,placement_preparation:{request_id,approval_hash:chat.approval_hash,scope:'planning_only',spec_hash:'8'.repeat(64),mission_id:mid,status:'ACK',control}};}
function response(data,status=200){return {ok:status>=200&&status<300,status,json:async()=>data};}
const context=vm.createContext({console,URLSearchParams,Map,Set,Date,JSON,Math,Array,String,Number,AbortController,Blob,
 URL:Object.assign(class {},{createObjectURL:blob=>{downloads.push(blob);return 'blob:synthetic';},revokeObjectURL(){}}),
 crypto:{randomUUID:()=> 'request-fixture-'+(++serial)},navigator:{clipboard:{writeText:async data=>copies.push(data)}},
 location:{origin:'http://fixture.local',hash:'#token=fixture-access',pathname:'/',search:''},
 sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},localStorage:{getItem(){return null;},setItem(){throw Error('unexpected local storage');}},
 history:{replaceState(){}},document:{getElementById:el,createElement:tag=>new Element(tag),querySelectorAll(){return [];},addEventListener(){},activeElement:null,body:new Element('body')},
 window:{addEventListener(){}},requestAnimationFrame:fn=>fn(),setTimeout(){return 1;},clearTimeout(){},
 fetch:async(path,options)=>{const call={path,method:options.method,body:options.body&&JSON.parse(options.body),options};calls.push(call);
 assert.equal(options.headers.Authorization,'Bearer fixture-access');assert.equal(options.credentials,'same-origin');
 if(options.method==='POST'){assert.ok(postHook,'unexpected mutating request '+path);return await postHook(call);}
 let data=getHook?await getHook(call):undefined;
 if(data===undefined){if(path.startsWith('/api/chat?'))data=chat;else if(path.startsWith('/api/snapshot?'))data=snapshot;
 else if(path.startsWith('/api/mission/messages?'))data={messages:[],updates:[],cursor:0,application_cursor:0,has_more:false,has_more_updates:false};
 else if(path.startsWith('/api/events?'))data={events:[],cursor:0};else if(path==='/api/chats')data={chats:[chat]};
 else if(path==='/api/missions')data={missions:[{id:mid,objective:chat.proposal.objective,source:chat.source},{id:other,objective:'另一项任务'}]};
 else if(path===`/api/missions/${mid}/nodes`)data=inventory;else if(path===`/api/missions/${mid}/placements`)data=placements;
 else if(path===`/api/missions/${other}/nodes`)data={...inventory,mission_id:other,nodes:[]};
 else if(path===`/api/missions/${other}/placements`)data={mission_id:other,placements:[]};else throw Error('unexpected GET '+path);}
 return response(data);},
 assert,el,all,findSelect,elements,mid,other,cid,nid,ns,secret,chat,snapshot,task,registered,inventory,placements,pin,bound,response,calls,copies,downloads,storage,
 setGet:fn=>getHook=fn,setPost:fn=>postHook=fn,
});
vm.runInContext(SOURCE,context);
Promise.resolve(vm.runInContext('(async()=>{'+CASE+'})()',context)).catch(error=>{console.error(error);process.exitCode=1;});
'''


READY = r'''
state.kind='chat';state.id=cid;state.chat=chat;state.connected=true;state.loading=false;
state.chats=[chat];state.missions=[{id:mid,source:chat.source,objective:chat.proposal.objective}];
render();await el('review-plan').onclick();
'''


def run_js(case):
    script = PAGE.split('<script nonce="NONCE">', 1)[1].split('</script>', 1)[0]
    script = script.rsplit('render(); resizeComposer();', 1)[0]
    result = subprocess.run(['node', '-e', HARNESS.replace('SOURCE', json.dumps(script)).replace('CASE', json.dumps(case))],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


class Tags(HTMLParser):
    def __init__(self):
        super().__init__(); self.ids = {}
    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if 'id' in data:
            assert data['id'] not in self.ids
            self.ids[data['id']] = (tag, data)


def test_accessible_public_controls_and_unchecked_planning_permission():
    tags = Tags(); tags.feed(PAGE)
    for name in ('chat-planning-permission', 'chat-prepare-placement', 'chat-placement-retry',
                 'machine-panel', 'machine-note', 'machine-list', 'placement-list', 'node-name', 'node-enroll',
                 'node-config-copy', 'node-config-download', 'node-gateway-url', 'node-gateway-host'):
        assert name in tags.ids, name
    assert tags.ids['chat-planning-permission'][1].get('type') == 'checkbox'
    assert 'checked' not in tags.ids['chat-planning-permission'][1]
    assert 'viewport-fit=cover' in PAGE and 'prefers-reduced-motion' in PAGE


def test_read_and_review_never_dispatch_and_permissions_are_separate():
    run_js(READY + r'''
assert.equal(el('chat-planning-permission').checked,false);assert.equal(el('chat-permission').checked,false);
assert.equal(typeof el('chat-prepare-placement').onclick,'function');
await el('chat-prepare-placement').click();assert.equal(calls.filter(x=>x.method==='POST').length,0);
el('chat-permission').checked=true;await el('chat-prepare-placement').click();
assert.equal(calls.filter(x=>x.method==='POST').length,0,'old worker permission is not planning permission');
''')


@pytest.mark.parametrize('condition', ['disconnected', 'unready', 'busy', 'bound', 'changed-hash'])
def test_planning_admission_requires_current_ready_unbound_confirmation(condition):
    run_js(READY + r'''
el('chat-planning-permission').checked=true;
if(COND==='disconnected')state.connected=false;if(COND==='unready')chat.readiness.ready=false;
if(COND==='busy')state.busy={type:'message'};if(COND==='bound')chat.mission_id=mid;
if(COND==='changed-hash')chat.approval_hash='f'.repeat(64);
assert.equal(typeof el('chat-prepare-placement').onclick,'function');await el('chat-prepare-placement').click();
assert.equal(calls.filter(x=>x.method==='POST').length,0);
'''.replace('COND', json.dumps(condition)))


def test_explicit_prepare_exact_wire_enters_same_mission_without_start():
    run_js(READY + r'''
el('chat-planning-permission').checked=true;
setPost(call=>{assert.equal(call.path,'/api/chat/prepare-placement');assert.deepEqual(Object.keys(call.body).sort(),['allow_planning','approval_hash','chat_id','request_id']);
 assert.equal(call.body.allow_planning,true);assert.equal(call.body.chat_id,cid);assert.equal(call.body.approval_hash,chat.approval_hash);return response(bound(call.body.request_id),202);});
await el('chat-prepare-placement').click();assert.equal(state.kind,'mission');assert.equal(state.id,mid);
assert.equal(calls.filter(x=>x.method==='POST').length,1);assert.equal(snapshot.snapshot.all_verified,false);
assert.match(el('mission-status').textContent,/等待.*机器|等待.*选择|子任务已准备/);
assert.equal(el('mission-permission').checked,false);
''')


def test_unknown_preparation_readonly_reconciliation_and_exact_retry():
    run_js(READY + r'''
el('chat-planning-permission').checked=true;let original;
setPost(call=>{original=call.body;throw Object.assign(Error('lost reply'),{name:'AbortError'});});
await el('chat-prepare-placement').click();assert.equal(calls.filter(x=>x.method==='POST').length,1);
assert.ok([...state.pending.values()].some(x=>x.request_id===original.request_id));
setGet(call=>call.path.startsWith('/api/chat?')?bound('unrelated-request-0001'):undefined);
await readSelected();assert.equal(calls.filter(x=>x.method==='POST').length,1);
assert.ok([...state.pending.values()].some(x=>x.request_id===original.request_id),'another mapped request is not proof');
setGet(call=>call.path.startsWith('/api/chat?')?chat:undefined);
await readSelected();
setPost(call=>{assert.deepEqual(call.body,original);return response(bound(original.request_id),202);});
assert.equal(typeof el('chat-placement-retry').onclick,'function');await el('chat-placement-retry').click();
assert.equal(calls.filter(x=>x.method==='POST').length,2);assert.equal(state.id,mid);
''')


def test_prepare_error_and_changed_draft_do_not_synthesize_completion():
    run_js(READY + r'''
el('chat-planning-permission').checked=true;setPost(()=>response({error:'fixed conflict'},409));
await el('chat-prepare-placement').click();assert.equal(state.id,cid);assert.equal(state.kind,'chat');
assert.equal(chat.mission_id,undefined);assert.equal(el('chat-planning-permission').checked,false);
assert.equal(calls.filter(x=>x.method==='POST').length,1);assert.equal(snapshot.snapshot.all_verified,false);
assert.match(el('chat-note-text').textContent+' '+el('global-text').textContent+' '+state.chatNotice,/未成功|冲突|fixed conflict/);
''')


def test_late_prepare_reply_does_not_navigate_or_overwrite_other_mission():
    run_js(READY + r'''
el('chat-planning-permission').checked=true;let release;
setPost(call=>new Promise(resolve=>{release=()=>resolve(response(bound(call.body.request_id),202));}));
const waiting=el('chat-prepare-placement').click();await Promise.resolve();await selectMission(other);release();await waiting;
assert.equal(state.id,other);assert.equal(state.kind,'mission');assert.equal(calls.filter(x=>x.method==='POST').length,1);
''')


def test_mission_refresh_reads_persisted_placements_and_never_equates_active_with_online():
    run_js(r'''
placements.placements[0].placement=pin('old-selection-0001');await selectMission(mid);
assert.ok(calls.some(x=>x.path===`/api/missions/${mid}/nodes`));assert.ok(calls.some(x=>x.path===`/api/missions/${mid}/placements`));
assert.equal(el('machine-panel').hidden,false);const view=el('machine-list').textContent+' '+el('placement-list').textContent+' '+el('machine-note').textContent;
assert.match(view,/远端 Mac/);assert.match(view,/已登记|传输.*待|未.*接通|未.*就绪/);
assert.doesNotMatch(view,/已在线|原生登录已确认|验收已通过/);
assert.equal(calls.filter(x=>x.method==='POST').length,0);
''')


def test_explicit_assignment_uses_fixed_task_and_node_not_native_authority():
    run_js(r'''
await selectMission(mid);let sent;
setPost(call=>{sent=call.body;assert.equal(call.path,`/api/missions/${mid}/placements`);assert.deepEqual(Object.keys(sent).sort(),['node_id','request_id','task_id']);
 assert.equal(sent.node_id,nid);assert.equal(sent.task_id,task.id);placements.placements[0].placement=pin(sent.request_id);return response(pin(sent.request_id));});
const button=findSelect();assert.ok(button,'explicit task/node button');await button.click();
assert.equal(calls.filter(x=>x.method==='POST').length,1);assert.match(el('placement-list').textContent,/远端 Mac/);
assert.equal(task.verdict,'UNVERIFIED');assert.equal(snapshot.snapshot.all_verified,false);
''')


def test_lost_assignment_is_resolved_only_by_matching_persisted_pin_no_repost():
    run_js(r'''
await selectMission(mid);let sent;
setPost(call=>{sent=call.body;throw Object.assign(Error('lost'),{name:'AbortError'});});
const button=findSelect();assert.ok(button);await button.click();
assert.ok([...state.pending.values()].some(x=>x.request_id===sent.request_id));
placements.placements[0].placement=pin('different-selection-0001');await readSelected();
assert.ok([...state.pending.values()].some(x=>x.request_id===sent.request_id));
placements.placements[0].placement=pin(sent.request_id);await readSelected();
assert.equal([...state.pending.values()].some(x=>x.request_id===sent.request_id),false);
assert.equal(calls.filter(x=>x.method==='POST').length,1);
''')


@pytest.mark.parametrize('bad', ['wrong-mission', 'duplicate-task', 'missing-array'])
def test_malformed_readback_preserves_visible_pin_and_explicit_diagnostic(bad):
    run_js(r'''
placements.placements[0].placement=pin('kept-selection-0001');await selectMission(mid);
setGet(call=>{if(!call.path.endsWith('/placements'))return;
 if(BAD==='wrong-mission')return {...placements,mission_id:other};
 if(BAD==='duplicate-task')return {...placements,placements:[...placements.placements,...placements.placements]};return {mission_id:mid};});
await readSelected();assert.match(el('placement-list').textContent,/远端 Mac/);
assert.match(el('machine-note').textContent,/异常|失败|待核对|未.*读|不完整/);assert.equal(calls.filter(x=>x.method==='POST').length,0);
'''.replace('BAD', json.dumps(bad)))


def test_node_enrollment_first_secret_private_until_explicit_copy():
    run_js(r'''
await selectMission(mid);el('node-name').value='远端 Mac';el('node-gateway-url').value='http://127.0.0.1:23456';el('node-gateway-host').value='127.0.0.1:34567';
setPost(call=>{assert.equal(call.path,`/api/missions/${mid}/nodes`);assert.deepEqual(Object.keys(call.body).sort(),['name','request_id']);
 assert.equal(call.body.name,'远端 Mac');return response({...registered,request_id:call.body.request_id,secret,execution_ready:false},201);});
assert.equal(typeof el('node-enroll').onclick,'function');await el('node-enroll').click();
assert.equal(calls.filter(x=>x.method==='POST').length,1);assert.equal(copies.length,0);assert.equal(downloads.length,0);
assert.equal([...elements.values()].some(x=>x.textContent.includes(secret)),false);
assert.equal([...storage.values()].some(x=>x.includes(secret)),false);assert.equal(JSON.stringify(state.traces).includes(secret),false);
assert.equal(typeof el('node-config-copy').onclick,'function');await el('node-config-copy').click();assert.equal(copies.length,1);
const config=JSON.parse(copies[0]);assert.deepEqual(Object.keys(config).sort(),['controller_mission_id','gateway_host','gateway_url','node_id','schema','secret']);
assert.equal(config.schema,1);assert.equal(config.controller_mission_id,mid);assert.notEqual(config.controller_mission_id,ns);
assert.equal(config.secret,secret);assert.equal(config.node_id,nid);assert.equal(config.gateway_url,'http://127.0.0.1:23456');assert.equal(config.gateway_host,'127.0.0.1:34567');
''')


def test_node_replay_missing_secret_does_not_fabricate_export_or_native_login():
    run_js(r'''
await selectMission(mid);el('node-name').value='远端 Mac';setPost(call=>response({...registered,request_id:call.body.request_id,secret:null,execution_ready:false}));
assert.equal(typeof el('node-enroll').onclick,'function');await el('node-enroll').click();
await el('node-config-copy').click();assert.equal(copies.length,0);assert.equal(downloads.length,0);
assert.match(el('machine-note').textContent,/凭据|首次|撤销|重新登记/);assert.equal(calls.filter(x=>x.method==='POST').length,1);
''')


def test_explicit_revoke_uses_separate_operator_empty_body_without_dispatch():
    run_js(r'''
await selectMission(mid);setPost(call=>{assert.equal(call.path,`/api/missions/${mid}/nodes/${nid}`);assert.deepEqual(call.body,{});registered.status='REVOKED';return response({...registered,execution_ready:false});});
const button=all().find(x=>x.dataset.revokeNode===nid);assert.ok(button);await button.click();
assert.equal(calls.filter(x=>x.method==='POST').length,1);assert.equal(snapshot.snapshot.all_verified,false);
''')
