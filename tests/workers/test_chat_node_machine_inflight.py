"""Frozen Page-v4 transport/readback races against the production script.

The declared bounded contract lives in the retained freeze packet, not an edit
to fixed contracts. Real deferred POST/JSON/GET Promises are released and awaited;
every script must emit its completion marker. Protocol VM, not browser/device.
"""
import json
import subprocess

import pytest

from sisyfus.workers.lead_chat_page import PAGE
from test_chat_node_placement_page import HARNESS
from test_chat_node_machine_retry import SETUP


MARKER = 'machine-inflight-scenario-completed'


def run_case(case, *, seed=()):
    script = PAGE.split('<script nonce="NONCE">', 1)[1].split('</script>', 1)[0]
    script = script.rsplit('render(); resizeComposer();', 1)[0]
    harness = HARNESS.replace('calls=[],copies=[],downloads=[];', 'calls=[],copies=[],downloads=[],windowCallbacks=new Map();')
    harness = harness.replace('window:{addEventListener(){}},',
                              'window:{addEventListener:(name,handler)=>windowCallbacks.set(name,handler)},')
    harness = harness.replace('assert,el,all,findSelect,', 'windowCallbacks,assert,el,all,findSelect,')
    harness = harness.replace('vm.runInContext(SOURCE,context);',
        'for(const [key,value] of ' + json.dumps(seed) + ')storage.set(key,value);\nvm.runInContext(SOURCE,context);')
    assert 'windowCallbacks.set(name,handler)' in harness
    result = subprocess.run(['node', '-'], input=harness.replace('SOURCE', json.dumps(script)).replace(
        'CASE', json.dumps(case + '\nconsole.log(' + json.dumps(MARKER) + ');')),
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert MARKER in result.stdout, 'deferred scenario did not complete: ' + result.stdout + result.stderr
    return result.stdout


HELPERS = r'''
async function waitUntil(condition){
 for(let i=0;i<160;i++){if(condition())return;await Promise.resolve();}
 throw Error('deferred fixture boundary was not reached');
}
async function startOriginal(kind){
 if(kind==='placement')return findSelect().click();
 if(kind==='enroll'){el('node-name').value=nextNode.name;return el('node-enroll').click();}
 return all().find(item=>item.dataset.revokeNode===nid).click();
}
async function begin(kind,phase,committed=true,jsonHeld=false){
 if(phase==='retry'&&!state.pending.has('machine:'+mid))await firstFailure(kind);
 let resolve,reject,wire,reply,entered=false;
 const deferred=new Promise((yes,no)=>{resolve=yes;reject=no;});
 setPost(call=>{
  wire={path:call.path,body:call.body};reply=committed?commit(call,kind):candidate(call,kind);entered=true;
  return jsonHeld?{ok:true,status:201,json:()=>deferred}:deferred;
 });
 const waiting=phase==='retry'?el('machine-retry').click():startOriginal(kind);
 await waitUntil(()=>entered);const intent=state.pending.get('machine:'+mid);
 assert.ok(intent);assert.equal(JSON.stringify(intent.body),JSON.stringify(wire.body));
 return {waiting,wire,intent,release(outcome='success'){
  if(outcome==='timeout')reject(Object.assign(Error('fixture transport loss'),{name:'AbortError'}));
  else if(outcome==='503')resolve(response({error:'retained fixture service failure'},503));
  else if(outcome==='wrong-reply')resolve(response({...reply,request_id:'different_original_request_01'}));
  else resolve(jsonHeld?reply:response(reply,kind==='enroll'?201:200));
 }};
}
async function onlineRead(){
 const serial=state.machines.get(mid).serial;
 windowCallbacks.get('online')();
 await waitUntil(()=>state.machines.get(mid).serial>serial &&
  state.machines.get(mid).fresh?.serial===state.machines.get(mid).serial);
 for(let i=0;i<32;i++)await Promise.resolve();
}
function publicPendingOnly(intent){
 const keys=Object.keys(intent).sort();
 assert.equal(JSON.stringify(keys),JSON.stringify((intent.type==='node-revoke'?
  ['type','node_id','body','path','mission_id','at']:['type','request_id','body','path','mission_id','at']).sort()));
 assertSecretPrivate();
}
function assertDelivered(kind){
 assert.equal(state.pending.has('machine:'+mid),false);
 if(kind==='enroll'){
  assert.equal(nodeCredentials.get(mid+':'+nextNode.node_id),secret);
  el('node-gateway-url').value='http://127.0.0.1:23456';el('node-gateway-host').value='127.0.0.1:34567';
 }
 assertSecretPrivate();assertNoAuthorityChange();
}
'''


@pytest.mark.parametrize('kind', ['placement', 'enroll', 'revoke'])
@pytest.mark.parametrize('phase', ['initial', 'retry'])
def test_all_refresh_paths_wait_for_original_transport_before_resolving(kind, phase):
    run_case(SETUP + HELPERS + r'''
const kind=KIND,phase=PHASE,held=await begin(kind,phase),observations=[];
const count=calls.filter(call=>call.method==='POST').length;
for(const id of ['mission-refresh','load-retry','uncertain-refresh']){
 await el(id).click();observations.push(state.pending.get('machine:'+mid)===held.intent);
}
await onlineRead();observations.push(state.pending.get('machine:'+mid)===held.intent);
const prematureNotice=el('machine-note').textContent.includes('请撤销后重新明确登记');
const prematureSecret=nodeCredentials.has(mid+':'+nextNode.node_id);
publicPendingOnly(held.intent);held.release();await held.waiting;
assert.equal(observations.every(Boolean),true,'GET may project rows, never resolve an in-flight operation');
assert.equal(prematureNotice,false);assert.equal(prematureSecret,false);assertDelivered(kind);
assert.equal(calls.filter(call=>call.method==='POST').length,count);
assert.equal(el('mission-start').disabled,false);assert.equal(copies.length,0);assert.equal(downloads.length,0);
if(kind==='enroll'){await el('node-config-copy').click();assert.equal(copies.length,1);
 const config=JSON.parse(copies[0]);assert.equal(config.secret,secret);assert.equal(config.controller_mission_id,mid);
 assert.equal(JSON.stringify(Object.keys(config).sort()),JSON.stringify(['schema','controller_mission_id','node_id','secret','gateway_url','gateway_host'].sort()));assertSecretPrivate();}
'''.replace('KIND', json.dumps(kind)).replace('PHASE', json.dumps(phase)))


@pytest.mark.parametrize('phase', ['initial', 'retry'])
def test_delayed_first_secret_json_body_is_still_inflight_after_http_headers(phase):
    run_case(SETUP + HELPERS + r'''
const held=await begin('enroll',PHASE,true,true);await onlineRead();await el('mission-refresh').click();
const same=state.pending.get('machine:'+mid)===held.intent;
const before=nodeCredentials.has(mid+':'+nextNode.node_id);held.release();await held.waiting;
assert.equal(same,true);assert.equal(before,false);assertDelivered('enroll');
assert.equal(copies.length,0);assert.equal(downloads.length,0);
'''.replace('PHASE', json.dumps(phase)))


@pytest.mark.parametrize('phase', ['initial', 'retry'])
@pytest.mark.parametrize('outcome', ['timeout', '503', 'wrong-reply'])
def test_terminal_error_retires_marker_before_matching_own_get_without_storing_bad_secret(phase, outcome):
    run_case(SETUP + HELPERS + r'''
const held=await begin('enroll',PHASE);await readSelected();const same=state.pending.get('machine:'+mid)===held.intent;
held.release(OUTCOME);await held.waiting;
assert.equal(same,true);assert.equal(state.pending.has('machine:'+mid),false,'after original failure, matching GET may resolve uncertainty');
assert.equal(nodeCredentials.has(mid+':'+nextNode.node_id),false);assert.equal(el('mission-start').disabled,false);
assert.match(el('machine-note').textContent,/首次|凭据|撤销/);assertSecretPrivate();assertNoAuthorityChange();
await readSelected();assert.equal(calls.filter(call=>call.method==='POST').length,PHASE==='retry'?2:1);
'''.replace('PHASE', json.dumps(phase)).replace('OUTCOME', json.dumps(outcome)))


@pytest.mark.parametrize('kind', ['placement', 'enroll', 'revoke'])
@pytest.mark.parametrize('phase', ['initial', 'retry'])
def test_deferred_old_mission_get_and_reply_never_mix_into_new_selection(kind, phase):
    run_case(SETUP + HELPERS + r'''
const kind=KIND,held=await begin(kind,PHASE);let release;
setGet(call=>call.path===root+'/nodes'?new Promise(resolve=>{release=()=>resolve(getMachines(call));}):getMachines(call));
const reading=readSelected();await waitUntil(()=>typeof release==='function');await selectMission(other);
release();await reading;const kept=state.pending.get('machine:'+mid)===held.intent;
held.release();await held.waiting;
assert.equal(kept,true);assert.equal(state.id,other);assert.equal(state.machines.get(other).placements.length,0);
assert.equal(el('machine-retry').hidden,true);assertSecretPrivate();
if(kind==='enroll')assert.equal(nodeCredentials.get(mid+':'+nextNode.node_id),secret);
setGet(getMachines);await selectMission(mid);assertDelivered(kind);
assert.equal(copies.length,0);assert.equal(downloads.length,0);
'''.replace('KIND', json.dumps(kind)).replace('PHASE', json.dumps(phase)))


@pytest.mark.parametrize('kind', ['placement', 'enroll', 'revoke'])
@pytest.mark.parametrize('phase', ['initial', 'retry'])
def test_stale_generation_reply_cleans_only_its_transport_then_new_intent_can_retry(kind, phase):
    run_case(SETUP + HELPERS + r'''
const kind=KIND,held=await begin(kind,PHASE),old=held.intent;
let newer;
if(kind==='revoke'){
 rows=[...rows,{...nextNode,request_id:'retained_extra_node_001'}];newer={...old,node_id:nextNode.node_id,path:root+'/nodes/'+nextNode.node_id+'/revoke',body:{}};
}else{const id=old.request_id+'-next';newer={...old,request_id:id,body:{...old.body,request_id:id}};}
setPending('machine:'+mid,newer);await readSelected();held.release();await held.waiting;
assert.equal(state.pending.get('machine:'+mid),newer);assert.equal(el('machine-retry').disabled,false,'stale transport marker must retire on early return');
assert.equal(nodeCredentials.has(mid+':'+nextNode.node_id),false);
setPost(call=>{if(kind!=='revoke')return response(commit(call,kind));
 const result={...nextNode,request_id:'retained_extra_node_001',status:'REVOKED',revoked_at:'2026-10-06'};rows=rows.map(item=>item.node_id===nextNode.node_id?result:item);return response(result);});
await el('machine-retry').click();assert.equal(state.pending.has('machine:'+mid),false);
const last=calls.filter(call=>call.method==='POST').at(-1);assert.equal(last.path,newer.path);
assert.equal(JSON.stringify(last.body),JSON.stringify(newer.body));assertSecretPrivate();assertNoAuthorityChange();
'''.replace('KIND', json.dumps(kind)).replace('PHASE', json.dumps(phase)))


@pytest.mark.parametrize('phase', ['initial', 'retry'])
def test_inflight_key_is_not_global_busy_and_other_mission_readback_remains_independent(phase):
    run_case(SETUP + HELPERS + r'''
const held=await begin('enroll',PHASE);const otherRow={...nextNode,request_id:'other_readback_001',name:'另一任务机器'};
setPending('machine:'+other,{type:'node-enroll',request_id:otherRow.request_id,body:{request_id:otherRow.request_id,name:otherRow.name},
 mission_id:other,path:'/api/missions/'+other+'/nodes',at:Date.now()});
setGet(call=>call.path==='/api/missions/'+other+'/nodes'?{mission_id:other,nodes:[otherRow],execution_ready:false}:getMachines(call));
await selectMission(other);const otherResolved=!state.pending.has('machine:'+other);
await selectMission(mid);const same=state.pending.get('machine:'+mid)===held.intent;
held.release();await held.waiting;await readSelected();
assert.equal(otherResolved,true,'an unrelated mission POST does not fence this completed readback');
assert.equal(same,true);assertDelivered('enroll');assert.equal(nodeCredentials.has(other+':'+nextNode.node_id),false);
'''.replace('PHASE', json.dumps(phase)))


@pytest.mark.parametrize('phase', ['initial', 'retry'])
def test_transport_fence_survives_unrelated_busy_owner_and_retires_after_unknown(phase):
    run_case(SETUP + HELPERS + r'''
const held=await begin('enroll',PHASE);state.busy={type:'message',id:other};await readSelected();
const same=state.pending.get('machine:'+mid)===held.intent;held.release('timeout');await held.waiting;
state.busy=null;await readSelected();assert.equal(same,true);assert.equal(state.pending.has('machine:'+mid),false);
assert.equal(nodeCredentials.has(mid+':'+nextNode.node_id),false);assertSecretPrivate();assertNoAuthorityChange();
'''.replace('PHASE', json.dumps(phase)))


@pytest.mark.parametrize('kind', ['placement', 'enroll', 'revoke'])
@pytest.mark.parametrize('phase', ['initial', 'retry'])
def test_full_script_restart_keeps_only_original_durable_intent_no_transport_hold(kind, phase):
    output = run_case(SETUP + HELPERS + r'''
const held=await begin(KIND,PHASE,false);publicPendingOnly(held.intent);
console.log('saved-inflight-storage:'+JSON.stringify([...storage]));held.release('timeout');await held.waiting;
assert.equal(state.pending.get('machine:'+mid),held.intent);assert.equal(el('machine-retry').disabled,false);
assertSecretPrivate();assertNoAuthorityChange();
'''.replace('KIND', json.dumps(kind)).replace('PHASE', json.dumps(phase)))
    seed = json.loads(next(line.split(':', 1)[1] for line in output.splitlines() if line.startswith('saved-inflight-storage:')))
    run_case(SETUP + HELPERS + r'''
const stored=state.pending.get('machine:'+mid),body=JSON.stringify(stored.body);
assert.equal(calls.filter(call=>call.method==='POST').length,0);assert.equal(el('machine-retry').disabled,false);
const held=await begin(KIND,'retry');await readSelected();const same=state.pending.get('machine:'+mid)===held.intent;
held.release();await held.waiting;assert.equal(same,true);assertDelivered(KIND);
const posted=calls.filter(call=>call.method==='POST');assert.equal(posted.length,1);
assert.equal(posted[0].path,stored.path);assert.equal(JSON.stringify(posted[0].body),body);
'''.replace('KIND', json.dumps(kind)), seed=seed)
