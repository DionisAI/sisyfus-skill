"""Frozen wire compatibility goals; reuse the unchanged dual-stream JS fixture."""
import importlib.util
from pathlib import Path

import pytest


_spec = importlib.util.spec_from_file_location(
    'mission_inbox_review_fixture', Path(__file__).with_name('test_mission_inbox_page_review.py'),
)
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
run_js = _fixture.run_js


def test_legacy_refresh_is_complete_cursor_zero_snapshot_replacement():
    run_js(r'''
let replacement=false;
setHistory(p=>{const cursor=Number(p.get('cursor'));assert.ok(historyCalls().at(-1).path.endsWith('&cursor='+cursor));
 if(cursor===0)return {messages:[record(1,{id:replacement?'new-first':'old-first',request_id:replacement?'new-request':'old-request',text:replacement?'替换后的历史':'旧历史'})],cursor:1,has_more:true};
 assert.equal(cursor,1);return {messages:[record(2)],cursor:2,has_more:false};});
await selectMission('legacy-mission');replacement=true;await readSelected();
assert.equal(historyCalls().filter(c=>params(c).get('cursor')==='0').length,2);
assert.equal(missionInbox(state.id).messages.length,2);assert.match(el('mission-message-thread').textContent,/替换后的历史/);
assert.doesNotMatch(el('mission-message-thread').textContent,/旧历史/);assert.equal(missionInbox(state.id).error,'');
''')


def test_legacy_partial_failure_retains_prior_projection_and_pending_identity():
    run_js(r'''
setHistory(()=>({messages:[record(1,{text:'完整旧投影'})],cursor:1,has_more:false}));await selectMission('legacy-mission');
const request={type:'mission-message',request_id:'pending-exact',body:{mission_id:state.id,message:'待确认',request_id:'pending-exact'}};
setPending(missionMessageKey(state.id),request);
setHistory(p=>{if(Number(p.get('cursor'))===0)return {messages:[record(1,{request_id:'pending-exact',text:'尚未完整的页面'})],cursor:1,has_more:true};throw Error('second page disconnected');});
await readSelected();const inbox=missionInbox(state.id);
assert.match(el('mission-message-thread').textContent,/完整旧投影/);assert.doesNotMatch(el('mission-message-thread').textContent,/尚未完整的页面/);
assert.equal(inbox.cursor,1);assert.equal(inbox.messages.length,1);assert.match(inbox.error,/失败/);
assert.equal(state.pending.get(missionMessageKey(state.id)).request_id,'pending-exact');assert.equal(el('mission-inbox-retry').hidden,true);
clearPending(missionMessageKey(state.id));el('composer-input').value='/btw';renderAvailability();assert.equal(el('send').disabled,false);
''')


def test_legacy_full_read_cap_reports_error_without_partial_commit_or_lockout():
    run_js(r'''
setHistory(()=>({messages:[record(1,{text:'保留的投影'})],cursor:1,has_more:false}));await selectMission('legacy-mission');
let count=0;
setHistory(p=>{count++;const cursor=Number(p.get('cursor'));const rows=Array.from({length:100},(_,i)=>record(cursor+i+1));return {messages:rows,cursor:cursor+100,has_more:true};});
await readSelected();assert.ok(count<=64);assert.match(missionInbox(state.id).error,/上限/);
assert.equal(missionInbox(state.id).messages.length,1);assert.match(el('mission-message-thread').textContent,/保留的投影/);
el('composer-input').value='新补充';renderAvailability();assert.equal(el('send').disabled,false);assert.equal(calls.filter(c=>c.method==='POST').length,0);
''')


@pytest.mark.parametrize('fields', [['updates'], ['application_cursor'], ['has_more_updates'], ['updates', 'application_cursor']])
def test_partial_dual_contract_never_enables_legacy_snapshot_mode(fields):
    run_js(r'''
let first=true;
setHistory(()=>{const b={messages:[record(1)],cursor:1,has_more:false};if(first){for(const key of FIELDS)b[key]=key==='updates'?[]:key==='application_cursor'?0:false;first=false;}return b;});
await selectMission('partial-wire');assert.match(missionInbox(state.id).error,/失败|异常/);assert.equal(missionInbox(state.id).messages.length,0);
await readSelected();assert.match(missionInbox(state.id).error,/失败|异常/);assert.equal(missionInbox(state.id).messages.length,0,'a broken dual contract is not downgraded');
'''.replace('FIELDS', __import__('json').dumps(fields)))


def test_known_canonical_session_rejects_fieldless_downgrade_even_after_reload():
    run_js(r'''
const records=[record(1)];setHistory(p=>page(p,records));await selectMission('canonical-mission');
setHistory(()=>({messages:[record(1,{request_id:'different',text:'wrong identity'})],cursor:1,has_more:false}));
await readSelected();assert.match(missionInbox(state.id).error,/失败|异常/);assert.equal(missionInbox(state.id).messages[0].request_id,'receipt-1');
const next=restart();await next.run(`await restoreSelectedView();assert.match(missionInbox(state.id).error,/失败|异常/);assert.equal(missionInbox(state.id).messages[0].request_id,'receipt-1');`);
assert.equal(params(next.calls.find(c=>c.path.startsWith('/api/mission/messages?'))).get('cursor'),'1');
''')


def test_legacy_projection_and_wire_selection_survive_refresh():
    run_js(r'''
setHistory(p=>{const cursor=Number(p.get('cursor'));return cursor===0?{messages:[record(1)],cursor:1,has_more:true}:{messages:[record(2)],cursor:2,has_more:false};});
await selectMission('legacy-mission');const next=restart();await next.run(`await restoreSelectedView();assert.equal(missionInbox(state.id).messages.length,2);assert.ok(row(1));assert.ok(row(2));`);
assert.equal(params(next.calls.find(c=>c.path.startsWith('/api/mission/messages?'))).get('cursor'),'0');
assert.equal(next.calls.filter(c=>c.method==='POST').length,0);
''')


def test_legacy_query_ack_survives_a_lagging_empty_history_without_resend():
    run_js(r'''
setHistory(()=>({messages:[],cursor:0,has_more:false}));await selectMission('legacy-mission');
setPost(body=>record(1,{request_id:body.request_id,text:body.message,kind:'query',status:'ANSWERED',answer:{phase:'IMPLEMENTING',summary:'持久状态快照',blockers:[],latest_results:[],active_tasks:[],all_verified:false}}));
el('composer-input').value='/btw';await sendMessage();assert.match(el('mission-message-thread').textContent,/持久状态快照/);
assert.equal(calls.filter(c=>c.method==='POST').length,1);assert.equal(state.pending.has(missionMessageKey(state.id)),false);
const next=restart();await next.run(`await restoreSelectedView();assert.match(el('mission-message-thread').textContent,/持久状态快照/);`);
assert.equal(next.calls.filter(c=>c.method==='POST').length,0);
''')
