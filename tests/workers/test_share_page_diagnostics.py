"""p16 on the public share page (user, 2026-10-17: "continue fix").

The share page carries its own copy of the engineering-result renderer. Under
the p16 ruling its 50-row diagnostics cap covers result and integration
diagnostics only; task-level diagnostics get their own bounded list. Fixtures
are genuine projections shared with the web page test; the renderer is called
directly with the share page's own helper definitions, without its boot code.
"""
from __future__ import annotations

import json
import subprocess

from sisyfus.workers.share_page import PAGE
from test_chat_node_placement_page import HARNESS
from test_lead_engineering_result_web import MID, _typed
from test_lead_result import _envelope
from test_lead_result_page_diagnostics import _flood


def _row(diagnostic):
    return diagnostic['code'] + ' · ' + diagnostic['section'] + ' · ' + diagnostic['source']


def _library():
    script = PAGE.split('<script nonce="NONCE">', 1)[1].split('</script>', 1)[0]
    library, boot = script.split("\n$('share-enter').onclick=", 1)
    assert 'function buildEngineeringResult(' in library and 'login(' in boot
    return library


def _build(tmp_path, result, case, marker):
    body = ('const root=document.createElement("div");root.append(...buildEngineeringResult('
            + json.dumps(result, ensure_ascii=False) + '));const text=root.textContent;'
            'const walk=x=>[x,...(x.children||[]).flatMap(walk)];\n' + case
            + '\nconsole.log(' + json.dumps('SHARE_CASE_FINISHED ' + marker) + ');')
    path = tmp_path / 'case.js'
    path.write_text(HARNESS.replace('SOURCE', json.dumps(_library())).replace('CASE', json.dumps(body)), encoding='utf-8')
    completed = subprocess.run(['node', str(path)], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0 and 'SHARE_CASE_FINISHED ' + marker in completed.stdout, completed.stdout[-3000:] + completed.stderr[-3000:]


def test_task_diagnostics_do_not_crowd_out_integration_diagnostics(tmp_path):
    result = _flood(_typed(), tasks=60, integration=True)
    assert sum(len(task['diagnostics']) for task in result['tasks']) > 50
    _build(tmp_path, result, r'''
assert.ok(text.includes('CURRENT_FLAG_SHAPE · integration'),'integration diagnostics stay visible beside a task-level flood');
assert.ok(walk(root).length<=3000,'share result DOM bounded');
''', 'task-flood')


def test_result_diagnostics_do_not_hide_task_diagnostics(tmp_path):
    result = _flood(_typed(), tasks=1, runs=64)
    assert len(result['diagnostics']) > 50
    _build(tmp_path, result, r'''
assert.ok(text.includes('DEPENDENCY_GRAPH_INVALID · task'),'task-level diagnostics are outside the result 50-row cap');
''', 'result-flood')


def test_both_diagnostic_lists_stay_bounded_with_explicit_truncation(tmp_path):
    result = _flood(_typed(), tasks=60, runs=64, integration=True)
    general_rows = [_row(d) for d in result['diagnostics'] + result['integration']['diagnostics']]
    task_rows = [_row(d) for task in result['tasks'] for d in task['diagnostics']]
    general, task_level = len(general_rows), len(task_rows)
    assert len(result['diagnostics']) > 50 and task_level > 50
    _build(tmp_path, result, r'''
const runs=new Set([...text.matchAll(/ · \/snapshot\/runs\/[0-9]+/g)].map(m=>m[0]));
const tasks=new Set([...text.matchAll(/DEPENDENCY_GRAPH_INVALID · task · \/snapshot\/nodes\/[0-9]+/g)].map(m=>m[0]));
assert.equal(runs.size,50,'result diagnostics capped at exactly 50');
assert.equal(tasks.size,50,'task-level diagnostics capped at exactly 50');
for(const row of GENERAL_SHOWN)assert.ok(text.includes(row),'first 50 result and integration rows shown in order: '+row);
for(const row of TASK_SHOWN)assert.ok(text.includes(row),'first 50 task-level rows shown in order: '+row);
const generalNote=text.search(/(^|[^子任务])诊断显示 50 \/ GENERAL_TOTAL，/),taskNote=text.indexOf('子任务诊断显示 50 / TASK_TOTAL，');
assert.ok(generalNote>=0,'explicit truncation of the result and integration list');
assert.ok(taskNote>=0,'explicit truncation of the task-level list');
assert.ok(generalNote<taskNote,'result and integration diagnostics are listed before task-level ones');
assert.ok(walk(root).length<=3000,'share result DOM bounded');
'''.replace('GENERAL_TOTAL', str(general)).replace('TASK_TOTAL', str(task_level))
    .replace('GENERAL_SHOWN', json.dumps(general_rows[:50], ensure_ascii=False)).replace('TASK_SHOWN', json.dumps(task_rows[:50], ensure_ascii=False)), 'both-floods')


def test_empty_state_only_when_both_lists_are_empty(tmp_path):
    result = _flood(_typed())
    assert not result['diagnostics'] and not result['integration']['diagnostics']
    assert not any(task['diagnostics'] for task in result['tasks'])
    _build(tmp_path, result, r'''
assert.ok(text.includes('本次投影没有记录诊断'),'empty state shown when nothing was recorded');
''', 'empty')


def test_task_only_diagnostics_are_not_reported_as_empty(tmp_path):
    value = _envelope(verified=True)
    value['id'] = MID
    result = _flood(value, tasks=1)
    assert not result['diagnostics'] and not result['integration']['diagnostics']
    _build(tmp_path, result, r'''
assert.ok(text.includes('DEPENDENCY_GRAPH_INVALID · task'));
assert.ok(!text.includes('本次投影没有记录诊断'),'task-level diagnostics alone are not an empty projection');
''', 'task-only')


def test_general_only_diagnostics_are_not_reported_as_empty(tmp_path):
    result = _flood(_typed(), runs=1)
    assert result['diagnostics'] and not any(task['diagnostics'] for task in result['tasks'])
    _build(tmp_path, result, r'''
assert.ok(!text.includes('本次投影没有记录诊断'));
assert.ok(text.includes(ROW),'the single result diagnostic is shown');
'''.replace('ROW', json.dumps(_row(result['diagnostics'][0]), ensure_ascii=False)), 'general-only')


def test_diagnostics_disclosure_precedes_task_disclosures(tmp_path):
    result = _flood(_typed(), tasks=2, runs=2)
    _build(tmp_path, result, r'''
const order=walk(root).map(x=>x.dataset?.detail).filter(Boolean);
const diagnostics=order.indexOf('engineering-diagnostics'),firstTask=order.indexOf('engineering-task-0');
assert.ok(diagnostics>=0&&firstTask>=0&&diagnostics<firstTask,'bounded failure signals render before task details: '+order.join(','));
''', 'order')
