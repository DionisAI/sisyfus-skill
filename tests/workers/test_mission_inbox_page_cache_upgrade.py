"""Frozen schema-upgrade regressions; local JS fixtures, no native invocations.

Schema 1 can contain BOUND past both cursors without a terminal update event.
Replay both streams on upgrade, retain canonical anti-downgrade and exact pending
identity, and checkpoint bounded catch-up without claiming history is complete.
"""
import importlib.util
import json
from pathlib import Path

import pytest


_spec = importlib.util.spec_from_file_location(
    'mission_inbox_upgrade_fixture', Path(__file__).with_name('test_mission_inbox_page_review.py'),
)
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
run_js = _fixture.run_js


@pytest.mark.parametrize('explicit_mode', [True, False])
def test_prior_schema_replays_both_streams_then_checkpoints_large_history(explicit_mode):
    run_js(r'''
const id='upgrade-large',key=storageKey+':inbox:'+encodeURIComponent(id);
const stale=Array.from({length:4505},(_,i)=>record(i+1));
stale[0]={...stale[0],applications:[{...receipt('BOUND'),delivery:{status:'ERROR'}}]};
const saved={schema:1,mission_id:id,messages:stale,cursor:4505,application_cursor:9,loaded:true,has_more:false,has_more_updates:false};
if(EXPLICIT)saved.wire_mode='canonical';storage.set(key,JSON.stringify(saved));
const records=stale.map(r=>({...r}));records[0]={...records[0],applications:[{...receipt('NOT_APPLIED'),delivery:{status:'ERROR'}}]};
const changes=[{seq:9,id:'msg-2'}]; // No terminal update event exists for msg-1.
setHistory(p=>page(p,records,changes));await selectMission(id);const inbox=missionInbox(id);
assert.equal(params(historyCalls()[0]).get('cursor'),'0');assert.equal(params(historyCalls()[0]).get('application_cursor'),'0');
assert.equal(inbox.wireMode,'canonical');assert.equal(inbox.error,'');assert.ok(historyCalls().length<=10);
assert.ok(inbox.cursor>0&&inbox.cursor<4505);assert.equal(inbox.has_more,true);assert.ok(inbox.messages.length<4505);
assert.match(row(1).textContent,/调用已结束，未记录资料被接受/);assert.doesNotMatch(row(1).textContent,/资料交付待核对/);
el('composer-input').value='/btw';renderAvailability();assert.equal(el('send').disabled,false);
await catchUp();assert.equal(inbox.messages.length,4505);assert.equal(inbox.cursor,4505);assert.equal(inbox.application_cursor,9);
assert.ok(row(4505));assert.equal(new Set(inbox.messages.map(m=>m.id)).size,4505);
const migrated=JSON.parse(storage.get(key));assert.equal(migrated.schema,2);assert.equal(migrated.wire_mode,'canonical');
const next=restart();await next.run(`await restoreSelectedView();assert.equal(missionInbox(state.id).messages.length,4505);assert.match(row(1).textContent,/调用已结束，未记录资料被接受/);`);
const resumed=next.calls.find(c=>c.path.startsWith('/api/mission/messages?'));
assert.equal(params(resumed).get('cursor'),'4505');assert.equal(params(resumed).get('application_cursor'),'9');
assert.equal(next.calls.filter(c=>c.method==='POST').length,0);
'''.replace('EXPLICIT', json.dumps(explicit_mode)))


@pytest.mark.parametrize('explicit_mode', [True, False])
def test_prior_canonical_schema_never_downgrades_to_fieldless_snapshot(explicit_mode):
    run_js(r'''
const id='upgrade-canonical',key=storageKey+':inbox:'+encodeURIComponent(id);
const saved={schema:1,mission_id:id,messages:[record(1,{applications:[receipt('BOUND')]})],cursor:1,application_cursor:7,loaded:true,has_more:false,has_more_updates:false};
if(EXPLICIT)saved.wire_mode='canonical';storage.set(key,JSON.stringify(saved));
setHistory(()=>({messages:[record(1)],cursor:1,has_more:false}));await selectMission(id);
const inbox=missionInbox(id);assert.equal(inbox.wireMode,'canonical');assert.equal(inbox.cursor,0);assert.equal(inbox.application_cursor,0);
assert.equal(inbox.loaded,false);assert.equal(inbox.has_more,true);assert.equal(inbox.has_more_updates,true);
assert.match(inbox.error,/未切换旧协议/);assert.equal(inbox.messages.length,0,'invalidated cache is not a fresh application projection');
for(const call of historyCalls()){assert.equal(params(call).get('cursor'),'0');assert.equal(params(call).get('application_cursor'),'0');}
el('composer-input').value='/btw';renderAvailability();assert.equal(el('send').disabled,false);
const next=restart();await next.run(`await restoreSelectedView();assert.equal(missionInbox(state.id).wireMode,'canonical');assert.match(missionInbox(state.id).error,/未切换旧协议/);`);
assert.equal(next.calls.filter(c=>c.method==='POST').length,0);
'''.replace('EXPLICIT', json.dumps(explicit_mode)))


def test_upgrade_exposes_transient_replay_failure_and_recovers_without_stale_bound():
    run_js(r'''
const id='upgrade-offline',key=storageKey+':inbox:'+encodeURIComponent(id);
storage.set(key,JSON.stringify({schema:1,mission_id:id,wire_mode:'canonical',messages:[record(1,{applications:[receipt('BOUND')]})],cursor:1,application_cursor:11,loaded:true,has_more:false,has_more_updates:false}));
setHistory(()=>{throw Error('upgrade history offline');});await selectMission(id);const inbox=missionInbox(id);
assert.equal(inbox.cursor,0);assert.equal(inbox.application_cursor,0);assert.equal(inbox.loaded,false);assert.equal(inbox.messages.length,0);
assert.equal(inbox.wireMode,'canonical');assert.match(el('mission-inbox-note').textContent,/升级/);assert.match(inbox.error,/失败/);
assert.equal(inbox.has_more,true);assert.equal(inbox.has_more_updates,true);
el('composer-input').value='补充资料';renderAvailability();assert.equal(el('send').disabled,false,'history migration does not fence a loaded mission');
const records=[record(1,{applications:[receipt('NOT_APPLIED')]})];setHistory(p=>page(p,records));const before=historyCalls().length;
await readSelected();assert.equal(params(historyCalls()[before]).get('cursor'),'0');assert.equal(params(historyCalls()[before]).get('application_cursor'),'0');
assert.equal(inbox.error,'');assert.equal(inbox.has_more,false);assert.equal(inbox.has_more_updates,false);
assert.match(row(1).textContent,/调用已结束，未记录资料被接受/);assert.equal(JSON.parse(storage.get(key)).schema,2);
assert.equal(calls.filter(c=>c.method==='POST').length,0);
''')


def test_upgrade_keeps_exact_pending_fenced_across_bounded_replay_and_reload():
    run_js(r'''
const id='upgrade-pending',key=storageKey+':inbox:'+encodeURIComponent(id),request='upgrade-exact-request';
const records=Array.from({length:1805},(_,i)=>record(i+1));records[0]={...records[0],text:'待确认文字'};
records[1500]={...records[1500],text:'待确认文字',request_id:request};
storage.set(key,JSON.stringify({schema:1,mission_id:id,wire_mode:'canonical',messages:records.slice(0,1400),cursor:1400,application_cursor:19,loaded:true,has_more:true,has_more_updates:false}));
setPending(missionMessageKey(id),{type:'mission-message',request_id:request,body:{mission_id:id,request_id:request,message:'待确认文字'},at:Date.now()});
setHistory(p=>page(p,records));await selectMission(id);const inbox=missionInbox(id);
assert.equal(params(historyCalls()[0]).get('cursor'),'0');assert.equal(params(historyCalls()[0]).get('application_cursor'),'0');
assert.ok(inbox.cursor<1501);assert.equal(inbox.has_more,true);assert.equal(state.pending.get(missionMessageKey(id)).request_id,request);
el('composer-input').value='下一条';renderAvailability();assert.equal(el('send').disabled,true);assert.equal(el('mission-inbox-retry').hidden,true);
const checkpoint=inbox.cursor;assert.equal(JSON.parse(storage.get(key)).schema,2);
const next=restart();await next.run(`await restoreSelectedView();assert.equal(state.pending.get(missionMessageKey(state.id)).request_id,'upgrade-exact-request');assert.equal(el('mission-inbox-retry').hidden,true);await catchUp();assert.equal(state.pending.has(missionMessageKey(state.id)),false);assert.equal(missionInbox(state.id).messages.length,1805);assert.ok(row(1));assert.ok(row(1805));`);
const resumed=next.calls.find(c=>c.path.startsWith('/api/mission/messages?'));assert.equal(params(resumed).get('cursor'),String(checkpoint));
assert.equal(next.calls.filter(c=>c.method==='POST').length,0);
''')


def test_prior_explicit_legacy_cache_replays_complete_snapshot_after_upgrade():
    run_js(r'''
const id='upgrade-legacy',key=storageKey+':inbox:'+encodeURIComponent(id);
storage.set(key,JSON.stringify({schema:1,mission_id:id,wire_mode:'legacy',messages:[record(1,{applications:[receipt('BOUND')]})],cursor:1,application_cursor:0,loaded:true,has_more:false,has_more_updates:false}));
setHistory(p=>{assert.equal(p.get('cursor'),'0');assert.equal(p.has('application_cursor'),false);return {messages:[record(1,{applications:[receipt('NOT_APPLIED')]})],cursor:1,has_more:false};});
await selectMission(id);assert.equal(missionInbox(id).wireMode,'legacy');assert.equal(missionInbox(id).error,'');
assert.match(row(1).textContent,/调用已结束，未记录资料被接受/);assert.equal(JSON.parse(storage.get(key)).schema,2);
assert.equal(calls.filter(c=>c.method==='POST').length,0);
''')
