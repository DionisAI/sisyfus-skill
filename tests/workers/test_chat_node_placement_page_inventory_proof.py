"""Frozen page-v2 regressions against the production script and real wire shapes.

The immutable DOM/fetch harness supplies existing public APIs. Assertions stay
outside fetch callbacks; no cross-realm object-equality or success adapters.
Inventory read failure/partial issues never prove that a mission is unlinked.
"""
import json

import pytest

from test_chat_node_placement_page import run_js


BLOCKED = r'''
const disabled=el('mission-start').disabled;
setPost(()=>response({accepted:true}));await el('mission-start').click();
el('mission-permission').checked=true;await el('mission-confirm').onsubmit({preventDefault(){}});
assert.equal(calls.filter(call=>call.method==='POST').length,0,'missing mapping evidence grants no generic Start');
assert.equal(disabled,true,'Start must visibly remain disabled');
assert.match(el('control-note').textContent,/对话|库存|关联/);
assert.match(el('control-note').textContent,/查询|核对/);
assert.equal(snapshot.snapshot.all_verified,false);
'''


def test_initial_mission_snapshot_without_chat_inventory_proof_is_not_unlinked():
    run_js(r'''
state.kind='mission';state.id=mid;state.mission=snapshot;state.connected=true;state.loading=false;
state.chats=[];state.missions=[{id:mid,source:chat.source}];render();
assert.equal(calls.filter(call=>call.path==='/api/chats').length,0);
''' + BLOCKED)


@pytest.mark.parametrize('selection', ['selected', 'restored'])
@pytest.mark.parametrize('failure', ['network', 'issues'])
def test_failed_or_partial_inventory_never_allows_generic_start_for_selected_or_restored_mission(selection, failure):
    run_js(r'''
state.chats=[];state.missions=[{id:mid,source:chat.source}];
setGet(call=>{if(call.path==='/api/chats'){
 if(FAILURE==='network')throw Error('chat inventory fixture unavailable');
 return {chats:[],issues:[{id:cid,error:'retained chat read error'}],auto_start:false};}return undefined;});
await inventory();
if(SELECTION==='restored'){storage.set(storageKey+':view',JSON.stringify({kind:'mission',id:mid}));await restoreSelectedView();}
else await selectMission(mid);
''' .replace('FAILURE', json.dumps(failure)).replace('SELECTION', json.dumps(selection)) + BLOCKED)


@pytest.mark.parametrize('failure', ['network', 'malformed-chats', 'issues', 'malformed-issues'])
def test_new_inventory_failure_invalidates_prior_complete_unlinked_proof(failure):
    run_js(r'''
setGet(call=>call.path==='/api/chats'?{chats:[],issues:[],auto_start:false}:undefined);
await inventory();await selectMission(mid);assert.equal(el('mission-start').disabled,false);
setGet(call=>{if(call.path==='/api/chats'){
 if(FAILURE==='network')throw Error('new inventory fixture failure');
 if(FAILURE==='malformed-chats')return {chats:null,issues:[],auto_start:false};
 if(FAILURE==='malformed-issues')return {chats:[],issues:{id:cid},auto_start:false};
 return {chats:[],issues:[{id:cid,error:'new retained read error'}],auto_start:false};}return undefined;});
await inventory();await readSelected();
''' .replace('FAILURE', json.dumps(failure)) + BLOCKED)


def test_inflight_inventory_refresh_fences_start_until_full_readback_without_auto_post():
    run_js(r'''
setGet(call=>call.path==='/api/chats'?{chats:[],issues:[],auto_start:false}:undefined);
await inventory();await selectMission(mid);assert.equal(el('mission-start').disabled,false);
let release;setGet(call=>call.path==='/api/chats'?new Promise(resolve=>{release=resolve;}):undefined);
const refreshing=inventory();for(let i=0;i<8;i++)await Promise.resolve();render();
const disabled=el('mission-start').disabled;
setPost(()=>response({accepted:true}));await el('mission-start').click();
el('mission-permission').checked=true;const submitting=el('mission-confirm').onsubmit({preventDefault(){}});
for(let i=0;i<8;i++)await Promise.resolve();
const posted=calls.filter(call=>call.method==='POST').length;
release({chats:[],issues:[],auto_start:false});await refreshing;await submitting;await readSelected();
assert.equal(disabled,true);assert.equal(posted,0);assert.equal(calls.filter(call=>call.method==='POST').length,0);
assert.equal(el('mission-start').disabled,false);assert.equal(snapshot.snapshot.all_verified,false);
''')


def test_explicit_successful_inventory_retry_proves_legacy_route_and_keeps_worker_confirmation_separate():
    run_js(r'''
setGet(call=>{if(call.path==='/api/chats')throw Error('initial inventory fixture failure');return undefined;});
await inventory();await selectMission(mid);const failedDisabled=el('mission-start').disabled;
setGet(call=>call.path==='/api/chats'?{chats:[],issues:[],auto_start:false}:undefined);
await el('inventory-retry').click();await readSelected();
assert.equal(failedDisabled,true);assert.equal(el('mission-start').disabled,false);
assert.equal(calls.filter(call=>call.method==='POST').length,0);setPost(()=>response({accepted:true}));
await el('mission-start').click();assert.equal(el('mission-permission').checked,false);
await el('mission-confirm').onsubmit({preventDefault(){}});assert.equal(calls.filter(call=>call.method==='POST').length,0);
el('mission-permission').checked=true;await el('mission-confirm').onsubmit({preventDefault(){}});
const posted=calls.filter(call=>call.method==='POST');assert.equal(posted.length,1);assert.equal(posted[0].path,'/api/control');
assert.deepEqual(Object.keys(posted[0].body).sort(),['action','allow_local_workers','mission_id']);
assert.equal(posted[0].body.action,'start');assert.equal(posted[0].body.mission_id,mid);
assert.equal(posted[0].body.allow_local_workers,true);assert.equal(snapshot.snapshot.all_verified,false);
''')


def test_issue_recovery_discovers_prepared_chat_and_keeps_original_chat_start_identity():
    run_js(r'''
const prepared=bound('inventory-proof-preparation-original');
setGet(call=>call.path==='/api/chats'?{chats:[],issues:[{id:cid,error:'retained chat issue'}],auto_start:false}:undefined);
await inventory();await selectMission(mid);const failedDisabled=el('mission-start').disabled;
setGet(call=>call.path==='/api/chats'?{chats:[{id:cid,title:chat.title,status:'IDLE',mission_id:mid}],issues:[],auto_start:false}:
 call.path.startsWith('/api/chat?')?prepared:undefined);
await el('inventory-retry').click();await readSelected();assert.equal(failedDisabled,true);
assert.equal(calls.filter(call=>call.method==='POST').length,0);assert.equal(el('mission-start').disabled,false);
setPost(call=>response({...prepared,placement_start:{request_id:call.body.request_id,
 approval_hash:call.body.approval_hash,status:'ACK'}}));
await el('mission-start').click();el('mission-permission').checked=true;
await el('mission-confirm').onsubmit({preventDefault(){}});
const posted=calls.filter(call=>call.method==='POST');assert.equal(posted.length,1);assert.equal(posted[0].path,'/api/chat/start');
assert.deepEqual(Object.keys(posted[0].body).sort(),['allow_local_workers','approval_hash','chat_id','request_id']);
assert.equal(posted[0].body.chat_id,cid);assert.equal(posted[0].body.allow_local_workers,true);
assert.equal(posted[0].body.approval_hash,prepared.placement_preparation.approval_hash);
assert.notEqual(posted[0].body.request_id,prepared.placement_preparation.request_id);
assert.equal(state.pending.has('mission:'+mid),false);assert.equal(snapshot.snapshot.all_verified,false);
''')


def test_known_prepared_identity_still_uses_fresh_chat_proof_despite_inventory_failure():
    run_js(r'''
const prepared=bound('inventory-proof-known-original');
state.chats=[{id:cid,title:chat.title,status:'IDLE',mission_id:mid}];
setGet(call=>{if(call.path==='/api/chats')throw Error('inventory fixture unavailable');
 return call.path.startsWith('/api/chat?')?prepared:undefined;});
await inventory();await selectMission(mid);assert.equal(el('mission-start').disabled,false);
assert.ok(calls.some(call=>call.path==='/api/chat?chat_id='+cid));
setPost(call=>response({...prepared,placement_start:{request_id:call.body.request_id,
 approval_hash:call.body.approval_hash,status:'ACK'}}));
await el('mission-start').click();el('mission-permission').checked=true;
await el('mission-confirm').onsubmit({preventDefault(){}});
const posted=calls.filter(call=>call.method==='POST');assert.equal(posted.length,1);assert.equal(posted[0].path,'/api/chat/start');
assert.equal(posted[0].body.approval_hash,prepared.placement_preparation.approval_hash);
assert.equal(state.pending.has('mission:'+mid),false);assert.equal(snapshot.snapshot.all_verified,false);
''')
