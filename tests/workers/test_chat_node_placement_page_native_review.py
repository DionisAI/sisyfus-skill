"""Frozen UI review-v1 regressions against the production page script.

Use the immutable public-shape DOM/fetch harness, not a compatibility adapter.
Wire assertions happen outside fetch callbacks so API error handling cannot
turn a wrong route or payload assertion into a false passing test.
"""
import json

import pytest

from test_chat_node_placement_page import READY, run_js


@pytest.mark.parametrize('status', ['CREATING', 'MAPPED', 'PLANNING', 'UNKNOWN'])
@pytest.mark.parametrize('channel', ['post', 'get'])
def test_non_ack_preparation_never_clears_original_pending_or_navigates(status, channel):
    run_js(READY + r'''
el('chat-planning-permission').checked=true;let original;
function uncertain(){const value=bound(original.request_id);value.status='UNKNOWN';value.placement_preparation.status=STATUS;
 value.placement_preparation.control=null;if(STATUS==='CREATING'){value.mission_id=null;value.placement_preparation.mission_id=null;}return value;}
setPost(call=>{original=call.body;if(CHANNEL==='post')return response(uncertain(),202);throw Object.assign(Error('lost reply'),{name:'AbortError'});});
await el('chat-prepare-placement').click();
if(CHANNEL==='get'){setGet(call=>call.path.startsWith('/api/chat?')?uncertain():undefined);await readSelected();}
assert.equal(state.kind,'chat');assert.equal(state.id,cid);
assert.ok([...state.pending.values()].some(value=>value.request_id===original.request_id));
assert.equal(calls.filter(call=>call.method==='POST').length,1);
assert.match(el('chat-note-text').textContent,/尚未确认|待核对|待确认/);
assert.doesNotMatch(state.chatNotice,/已受理/);assert.equal(snapshot.snapshot.all_verified,false);
'''.replace('STATUS', json.dumps(status)).replace('CHANNEL', json.dumps(channel)))


@pytest.mark.parametrize('bad', ['missing', 'extra', 'id', 'mission_id', 'request_id', 'action', 'status', 'accepted', 'terminal', 'scope'])
def test_ack_requires_exact_planning_only_control(bad):
    run_js(READY + r'''
el('chat-planning-permission').checked=true;let original;
setPost(call=>{original=call.body;const value=bound(original.request_id),control=value.placement_preparation.control;
 if(BAD==='missing')value.placement_preparation.control=null;else if(BAD==='extra')control.worker_permission=true;
 else if(BAD==='accepted')control.accepted=1;else if(BAD==='terminal')control.terminal=true;
 else control[BAD]=BAD==='mission_id'?other:'not-the-exact-ack';return response(value,202);});
await el('chat-prepare-placement').click();assert.equal(state.kind,'chat');assert.equal(state.id,cid);
assert.ok([...state.pending.values()].some(value=>value.request_id===original.request_id));
assert.equal(calls.filter(call=>call.method==='POST').length,1);assert.doesNotMatch(state.chatNotice,/已受理/);
'''.replace('BAD', json.dumps(bad)))


PREPARED = r'''
const prepared=bound('review-preparation-original');
state.chats=[{id:cid,title:chat.title,status:'IDLE',mission_id:mid}];
setGet(call=>call.path.startsWith('/api/chat?')?prepared:undefined);
await selectMission(mid);
'''


def test_prepared_start_rechecks_linked_chat_and_uses_exact_original_approval_wire():
    run_js(PREPARED + r'''
assert.ok(calls.some(call=>call.path==='/api/chat?chat_id='+cid),'summary is not the preparation proof');
setPost(call=>response({...prepared,placement_start:{request_id:call.body.request_id,
 approval_hash:prepared.placement_preparation.approval_hash,status:'ACK'}}));
await el('mission-start').click();assert.equal(el('mission-permission').checked,false);
await el('mission-confirm').onsubmit({preventDefault(){}});assert.equal(calls.filter(call=>call.method==='POST').length,0);
el('mission-permission').checked=true;await el('mission-confirm').onsubmit({preventDefault(){}});
const posted=calls.filter(call=>call.method==='POST');assert.equal(posted.length,1);assert.equal(posted[0].path,'/api/chat/start');
assert.deepEqual(Object.keys(posted[0].body).sort(),['allow_local_workers','approval_hash','chat_id','request_id']);
assert.equal(posted[0].body.chat_id,cid);assert.equal(posted[0].body.allow_local_workers,true);
assert.equal(posted[0].body.approval_hash,prepared.placement_preparation.approval_hash);
assert.notEqual(posted[0].body.request_id,prepared.placement_preparation.request_id);
assert.equal(state.id,mid);assert.equal(state.kind,'mission');assert.equal(snapshot.snapshot.all_verified,false);
assert.equal(el('mission-permission').checked,false);
''')


@pytest.mark.parametrize('status', ['MAPPED', 'PLANNING', 'UNKNOWN'])
def test_linked_uncertain_preparation_never_falls_back_to_control_start(status):
    run_js(PREPARED.replace("const prepared=bound('review-preparation-original');",
        "const prepared=bound('review-preparation-original');prepared.status='UNKNOWN';prepared.placement_preparation.status=" + json.dumps(status) + ";prepared.placement_preparation.control=null;") + r'''
setPost(()=>response({accepted:true}));await el('mission-start').click();el('mission-permission').checked=true;
await el('mission-confirm').onsubmit({preventDefault(){}});
assert.equal(calls.filter(call=>call.method==='POST').length,0,'unknown preparation has no fresh Start permission');
''')


def test_prepared_start_unknown_is_query_only_until_explicit_same_request_retry():
    run_js(PREPARED + r'''
let original;setPost(call=>{original=call.body;throw Object.assign(Error('lost Start reply'),{name:'AbortError'});});
await el('mission-start').click();el('mission-permission').checked=true;
await el('mission-confirm').onsubmit({preventDefault(){}});
assert.ok([...state.pending.values()].some(value=>value.request_id===original.request_id));
snapshot.controller.running=true;
prepared.placement_start={request_id:'unrelated-start-request',approval_hash:original.approval_hash,status:'ACK'};
await readSelected();assert.ok([...state.pending.values()].some(value=>value.request_id===original.request_id),'controller running is not this request proof');
prepared.placement_start={request_id:original.request_id,approval_hash:original.approval_hash,status:'UNKNOWN'};
await readSelected();assert.ok([...state.pending.values()].some(value=>value.request_id===original.request_id));
assert.equal(calls.filter(call=>call.method==='POST').length,1);
snapshot.controller.running=false;prepared.status='UNKNOWN';
setPost(call=>response({...prepared,status:'IDLE',placement_start:{request_id:call.body.request_id,
 approval_hash:call.body.approval_hash,status:'ACK'}}));
await el('mission-start').click();el('mission-permission').checked=true;
await el('mission-confirm').onsubmit({preventDefault(){}});
const posted=calls.filter(call=>call.method==='POST');assert.equal(posted.length,2);
assert.equal(posted[0].path,'/api/chat/start');assert.equal(posted[1].path,'/api/chat/start');
assert.equal(JSON.stringify(posted[1].body),JSON.stringify(original),'explicit retry preserves original request and approval');
assert.equal([...state.pending.values()].some(value=>value.request_id===original.request_id),false);
assert.equal(snapshot.snapshot.all_verified,false);
''')


@pytest.mark.parametrize('wrong', ['request_id', 'approval_hash', 'mission_id', 'status'])
def test_prepared_start_reply_needs_same_canonical_identity_and_ack(wrong):
    run_js(PREPARED + r'''
let original;setPost(call=>{original=call.body;const value={...prepared,placement_start:{request_id:original.request_id,
 approval_hash:original.approval_hash,status:'ACK'}};
 if(WRONG==='mission_id')value.mission_id=other;else value.placement_start[WRONG]=WRONG==='status'?'UNKNOWN':'different-value';return response(value);});
await el('mission-start').click();el('mission-permission').checked=true;
await el('mission-confirm').onsubmit({preventDefault(){}});
assert.ok([...state.pending.values()].some(value=>value.request_id===original.request_id));
assert.equal(state.id,mid);assert.equal(calls.filter(call=>call.method==='POST').length,1);assert.equal(snapshot.snapshot.all_verified,false);
'''.replace('WRONG', json.dumps(wrong)))


def test_unlinked_legacy_mission_keeps_original_control_start_payload():
    run_js(r'''
state.chats=[];await selectMission(mid);setPost(()=>response({accepted:true}));
await el('mission-start').click();el('mission-permission').checked=true;
await el('mission-confirm').onsubmit({preventDefault(){}});
const posted=calls.filter(call=>call.method==='POST');assert.equal(posted.length,1);assert.equal(posted[0].path,'/api/control');
assert.deepEqual(Object.keys(posted[0].body).sort(),['action','allow_local_workers','mission_id']);
assert.equal(posted[0].body.action,'start');assert.equal(posted[0].body.mission_id,mid);assert.equal(posted[0].body.allow_local_workers,true);
assert.equal(snapshot.snapshot.all_verified,false);
''')


@pytest.mark.parametrize('credential', ['retained', 'revoked', 'operator'])
@pytest.mark.parametrize('field', ['request_id', 'created_at'])
def test_pin_credentials_never_replace_safe_cache_or_reach_dom(credential, field):
    run_js(r'''
placements.placements[0].placement=pin('kept-safe-selection');await selectMission(mid);
if(CREDENTIAL!=='operator'){
 el('node-name').value='远端 Mac';setPost(call=>response({...registered,request_id:call.body.request_id,secret,execution_ready:false},201));
 await el('node-enroll').click();
 if(CREDENTIAL==='revoked'){setPost(()=>{registered.status='REVOKED';return response({...registered,execution_ready:false});});
  await all().find(item=>item.dataset.revokeNode===nid).click();}
}
const sensitive=CREDENTIAL==='operator'?'fixture-access':secret;
const bad={...pin('new-untrusted-selection'),[FIELD]:'echo-'+sensitive};
setGet(call=>call.path.endsWith('/placements')?{mission_id:mid,placements:[{task_id:task.id,placement:bad}]}:undefined);
await readSelected();
assert.equal(state.machines.get(mid).placements[0].placement.request_id,'kept-safe-selection','credential readback never commits to public state');
assert.equal(el('placement-list').textContent.includes(sensitive),false);
assert.equal(JSON.stringify(state.machines.get(mid).placements).includes(sensitive),false);
assert.match(el('machine-note').textContent,/失败|异常|凭据|核对/);
'''.replace('CREDENTIAL', json.dumps(credential)).replace('FIELD', json.dumps(field)))


def test_newly_retained_secret_is_scrubbed_when_rendering_older_untrusted_pin():
    run_js(r'''
placements.placements[0].placement=pin('older-opaque-'+secret);await selectMission(mid);
el('node-name').value='远端 Mac';setPost(call=>response({...registered,request_id:call.body.request_id,secret,execution_ready:false},201));
await el('node-enroll').click();assert.equal(el('placement-list').textContent.includes(secret),false);
assert.equal(JSON.stringify(state.traces).includes(secret),false);
''')
