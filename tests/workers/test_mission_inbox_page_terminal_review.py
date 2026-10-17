"""Frozen v2 frontend regressions; synthetic receipts, no native calls or secrets.

Authoritative POST identity is request_id, not redacted/normalized display text.
NOT_APPLIED records a known terminal call without accepted-prompt evidence, while
BOUND remains appropriate for an unknown outcome. Query phase is mission-scoped.
"""
import importlib.util
import json
from pathlib import Path

import pytest


_spec = importlib.util.spec_from_file_location(
    'mission_inbox_terminal_fixture', Path(__file__).with_name('test_mission_inbox_page_review.py'),
)
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
run_js = _fixture.run_js


@pytest.mark.parametrize('submitted,display', [
    ('use Bearer FIXTURE_TOKEN_123', 'use Bearer [REDACTED]'),
    ('use sk-fixture-key-000000000000000000000000', 'use [REDACTED]'),
    *[(space + 'Python whitespace' + space, 'Python whitespace') for space in '\x1c\x1d\x1e\x1f\x85'],
])
def test_authoritative_redacted_or_python_stripped_post_needs_no_query_to_accept(submitted, display):
    run_js(r'''
await selectMission('receipt-mission');let sent;
setPost(body=>{sent=body;return record(1,{request_id:body.request_id,text:DISPLAY});});
setHistory(()=>{throw Error('readback unavailable');});
el('composer-input').value=SUBMITTED;await sendMessage();
assert.equal(sent.mission_id,'receipt-mission');assert.equal(sent.message,SUBMITTED.trim());
assert.equal(calls.filter(c=>c.method==='POST').length,1);
assert.equal(state.pending.has(missionMessageKey(state.id)),false,'HTTP 200 with the exact request_id is positive evidence');
assert.ok(row(1));assert.equal(missionInbox(state.id).messages[0].request_id,sent.request_id);
assert.equal(missionInbox(state.id).messages[0].text,DISPLAY);
assert.doesNotMatch(el('mission-inbox-note').textContent,/提交回执与原请求不匹配|提交结果待确认|消息的提交结果待确认/);
el('composer-input').value='/btw';renderAvailability();assert.equal(el('send').disabled,false);
'''.replace('SUBMITTED', json.dumps(submitted)).replace('DISPLAY', json.dumps(display)))


def test_wrong_post_request_identity_stays_unknown_despite_matching_text():
    run_js(r'''
await selectMission('receipt-mission');let sent;
setPost(body=>{sent=body;return record(1,{request_id:'different-request',text:body.message});});
el('composer-input').value='同样文字';await sendMessage();
assert.equal(state.pending.get(missionMessageKey(state.id)).request_id,sent.request_id);
assert.match(el('mission-inbox-note').textContent,/不匹配|待确认/);assert.equal(missionInbox(state.id).messages.length,0);
assert.equal(calls.filter(c=>c.method==='POST').length,1);
''')


@pytest.mark.parametrize('change', ['mission', 'epoch', 'version'])
def test_redacted_post_receipt_keeps_mission_epoch_and_version_guards(change):
    run_js(r'''
await selectMission('mission-a');let release,sent;
setPost(body=>{sent=body;return new Promise(resolve=>{release=()=>resolve(record(1,{request_id:body.request_id,text:'use Bearer [REDACTED]'}));});});
el('composer-input').value='use Bearer FIXTURE_TOKEN_123';const posting=sendMessage();await Promise.resolve();
if(CHANGE==='mission')await selectMission('mission-b');else if(CHANGE==='epoch')await selectMission('mission-a');else state.version++;
el('composer-input').value='保留当前草稿';release();await posting;
assert.equal(state.id,CHANGE==='mission'?'mission-b':'mission-a');assert.equal(el('composer-input').value,'保留当前草稿');
assert.equal(missionInbox(state.id).messages.length,0,'stale reply never replaces current projection');
assert.doesNotMatch(el('mission-message-thread').textContent,/use Bearer/);
assert.equal(state.pending.has(missionMessageKey('mission-a')),false,'accepted owner request is acknowledged only by its exact id');
assert.equal(calls.filter(c=>c.method==='POST').length,1);
'''.replace('CHANGE', json.dumps(change)))


def test_not_applied_terminal_application_has_honest_final_language():
    run_js(r'''
const records=[record(1,{applications:[{...receipt('NOT_APPLIED'),delivery:{status:'ERROR',reason:'ended before prompt acceptance'}}]})];
setHistory(p=>page(p,records));await selectMission('terminal-mission');
assert.equal(missionInbox(state.id).error,'');assert.ok(row(1));
assert.match(row(1).textContent,/调用已结束，未记录资料被接受/);
assert.doesNotMatch(row(1).textContent,/资料交付待核对|已绑定新调用|已应用到原生调用/);
assert.equal(state.mission.snapshot.all_verified,false);assert.doesNotMatch(el('mission-status').textContent,/验收与集成已通过/);
assert.match(row(1).textContent,/不代表.*验收/);
''')


def test_unknown_application_stays_bound_instead_of_inventing_terminal_evidence():
    run_js(r'''
setHistory(p=>page(p,[record(1,{applications:[{...receipt('BOUND'),delivery:{status:'UNKNOWN'}}]})]));
await selectMission('unknown-mission');assert.equal(missionInbox(state.id).error,'');
assert.match(row(1).textContent,/已绑定新调用，资料交付待核对/);
assert.doesNotMatch(row(1).textContent,/调用已结束|未记录资料被接受|已应用到原生调用/);
assert.equal(state.mission.snapshot.all_verified,false);
''')


def test_mixed_application_states_are_displayed_per_call_not_as_a_verdict():
    run_js(r'''
const apps=[receipt('NOT_APPLIED'),{...receipt('BOUND'),run_key:'unknown-run'},{...receipt('APPLIED'),run_key:'accepted-run'}];
setHistory(p=>page(p,[record(1,{status:'APPLIED',applications:apps})]));await selectMission('mixed-mission');
assert.equal(missionInbox(state.id).error,'');assert.match(row(1).textContent,/调用已结束，未记录资料被接受/);
assert.match(row(1).textContent,/已绑定新调用，资料交付待核对/);assert.match(row(1).textContent,/已应用到原生调用/);
assert.match(row(1).textContent,/unknown-run/);assert.match(row(1).textContent,/accepted-run/);
assert.equal(state.mission.snapshot.all_verified,false);
''')


def test_paginated_terminal_updates_advance_application_cursor_and_keep_unknown_bound():
    run_js(r'''
const records=Array.from({length:121},(_,i)=>record(i+1,{applications:[{...receipt('BOUND'),run_key:'run-'+(i+1)}]})),changes=[];
setHistory(p=>page(p,records,changes));await selectMission('terminal-stream');const unknownRow=row(121);
for(let i=0;i<120;i++)records[i]={...records[i],applications:[{...records[i].applications[0],status:'NOT_APPLIED',delivery:{status:'ERROR'}}]};
for(let seq=1;seq<=205;seq++)changes.push({seq,id:'msg-'+((seq-1)%120+1)});
const before=historyCalls().length;await readSelected();const reads=historyCalls().slice(before),inbox=missionInbox(state.id);
assert.equal(inbox.error,'');assert.equal(reads.length,3);assert.equal(inbox.cursor,121);assert.equal(inbox.application_cursor,205);
assert.equal(inbox.has_more_updates,false);assert.equal(inbox.messages.length,121);
assert.equal(params(reads[0]).get('application_cursor'),'0');assert.equal(params(reads[1]).get('application_cursor'),'100');assert.equal(params(reads[2]).get('application_cursor'),'200');
for(let seq=1;seq<=120;seq++){assert.match(row(seq).textContent,/调用已结束，未记录资料被接受/);assert.doesNotMatch(row(seq).textContent,/资料交付待核对/);}
assert.equal(row(121),unknownRow);assert.match(row(121).textContent,/资料交付待核对/);assert.doesNotMatch(row(121).textContent,/调用已结束/);
assert.equal(state.mission.snapshot.all_verified,false);assert.equal(calls.filter(c=>c.method==='POST').length,0);
''')


def test_terminal_application_cache_readback_survives_refresh():
    run_js(r'''
const records=[record(1,{applications:[receipt('NOT_APPLIED')]})];setHistory(p=>page(p,records));await selectMission('terminal-cache');
const next=restart();await next.run(`await restoreSelectedView();assert.equal(missionInbox(state.id).error,'');assert.match(row(1).textContent,/调用已结束，未记录资料被接受/);assert.equal(state.mission.snapshot.all_verified,false);`);
assert.equal(params(next.calls.find(c=>c.path.startsWith('/api/mission/messages?'))).get('cursor'),'1');
assert.equal(next.calls.filter(c=>c.method==='POST').length,0);
''')


def test_legacy_snapshot_accepts_terminal_application_without_changing_wire_mode():
    run_js(r'''
setHistory(()=>({messages:[record(1,{applications:[receipt('NOT_APPLIED')]})],cursor:1,has_more:false}));
await selectMission('terminal-legacy');assert.equal(missionInbox(state.id).error,'');
assert.match(row(1).textContent,/调用已结束，未记录资料被接受/);await readSelected();
assert.equal(historyCalls().filter(c=>params(c).get('cursor')==='0').length,2);
assert.equal(state.mission.snapshot.all_verified,false);
''')


@pytest.mark.parametrize('phase,verified,expected', [
    ('COMPLETED', True, '任务已完成'),
    ('COMPLETED', False, '整项验收尚未确认'),
    ('COMPLETED', 'true', '整项验收尚未确认'),
    ('PAUSED', False, '已暂停新工作派发'),
    ('STOPPED', False, '任务已停止'),
    ('UNKNOWN', False, '结果待确认'),
])
def test_query_phase_is_mission_aware_without_changing_native_completed_label(phase, verified, expected):
    run_js(r'''
const answer={phase:PHASE,summary:'查询时的控制器状态',blockers:[],latest_results:[],active_tasks:[],all_verified:VERIFIED,revision:2,observed_at:'2026-10-06',observed_event_cursor:17};
setHistory(p=>page(p,[record(1,{kind:'query',status:'ANSWERED',text:'/btw',answer})]));await selectMission('query-mission');
assert.equal(missionInbox(state.id).error,'');const phaseLine=row(1).children.find(child=>child.textContent.startsWith('查询时阶段：'));
assert.ok(phaseLine);assert.ok(phaseLine.textContent.includes(EXPECTED));
if(PHASE==='COMPLETED'){
 assert.doesNotMatch(phaseLine.textContent,/执行已返回，等待验收确认/);
 if(VERIFIED!==true)assert.doesNotMatch(phaseLine.textContent,/任务已完成/);
}
assert.equal(label('COMPLETED'),'执行已返回，等待验收确认','native receipt meaning remains unchanged');
assert.equal(state.mission.snapshot.all_verified,false,'historical query does not replace current mission truth');
'''.replace('PHASE', json.dumps(phase)).replace('VERIFIED', json.dumps(verified)).replace('EXPECTED', json.dumps(expected)))
