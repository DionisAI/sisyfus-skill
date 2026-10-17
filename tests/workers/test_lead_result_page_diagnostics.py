"""p16 ruling (user, 2026-10-13): the page's diagnostics50 cap does not cover
task-level diagnostics.

Result and integration diagnostics share one 50-row list. Task-level
diagnostics get their own bounded list, so neither kind can crowd the other
out. Fixtures are genuine projections (unknown dependencies, malformed run and
integration fields), evaluated with the frozen web VM helpers but without the
gated web guard.
"""
from __future__ import annotations

import json
import subprocess

from sisyfus.workers.lead_chat_page import PAGE
from test_chat_node_placement_page import HARNESS
from test_lead_engineering_result_web import MID, OTHER, _VM, _calibrate, _side, _typed, _wire
from test_lead_result import _envelope, _node
from test_mission_graph_page import _DOM_SUPPORT, _SETUP, _markup


def _row(diagnostic):
    return diagnostic['code'] + ' · ' + diagnostic['section'] + ' · ' + diagnostic['source']


def _run(tmp_path, case, value, marker):
    values = {MID: value, OTHER: _wire(OTHER)}
    for item in values.values():
        _calibrate(item)
    script = PAGE.split('<script nonce="NONCE">', 1)[1].split('</script>', 1)[0]
    script = script.rsplit('render(); resizeComposer();', 1)[0]
    support = _DOM_SUPPORT.replace('GRAPH_MARKUP', json.dumps(_markup(), ensure_ascii=False))
    body = _SETUP + _VM.replace('WEB_FIXTURES', json.dumps(values, ensure_ascii=False)) + case
    body += '\nwebNoMutation();console.log(' + json.dumps('WEB_CASE_FINISHED ' + marker) + ');'
    path = tmp_path / 'case.js'
    path.write_text(HARNESS.replace('SOURCE', json.dumps(support + script)).replace('CASE', json.dumps(body)), encoding='utf-8')
    result = subprocess.run(['node', str(path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and 'WEB_CASE_FINISHED ' + marker in result.stdout, result.stdout[-3000:] + result.stderr[-3000:]


def _flood(value, *, tasks=0, runs=0, integration=False):
    snapshot = value['snapshot']
    snapshot['nodes'] += [_node(f'flood-task-{i:02}', depends=('missing-dependency',)) for i in range(tasks)]
    snapshot['runs'] += [{'status': 'malformed-but-recorded-fixture'} for _ in range(runs)]
    if integration:
        snapshot['integration']['current'] = 'not-a-bool'
    value['engineering_result'] = _side(value)
    return value['engineering_result']['result']


def test_task_diagnostics_do_not_crowd_out_integration_diagnostics(tmp_path):
    value = _typed()
    result = _flood(value, tasks=60, integration=True)
    assert sum(len(task['diagnostics']) for task in result['tasks']) > 50
    assert any(d['code'] == 'CURRENT_FLAG_SHAPE' for d in result['integration']['diagnostics'])
    _run(tmp_path, r'''
await webMount('task-flood');const root=webRequired(),text=webText();
assert.ok(text.includes('CURRENT_FLAG_SHAPE · integration'),'integration diagnostics stay visible beside a task-level flood');
assert.ok(graphWalk(root).length<=3000,'total newly created result DOM nodes bounded');
''', value, 'task-flood')


def test_result_diagnostics_do_not_hide_task_diagnostics(tmp_path):
    value = _typed()
    result = _flood(value, tasks=1, runs=64)
    assert len(result['diagnostics']) > 50
    assert any(d['code'] == 'DEPENDENCY_GRAPH_INVALID' for task in result['tasks'] for d in task['diagnostics'])
    _run(tmp_path, r'''
await webMount('result-flood');const text=webText();
assert.ok(text.includes('DEPENDENCY_GRAPH_INVALID · task'),'task-level diagnostics are outside the result 50-row cap');
''', value, 'result-flood')


def test_both_diagnostic_lists_stay_bounded_with_explicit_truncation(tmp_path):
    value = _typed()
    result = _flood(value, tasks=60, runs=64, integration=True)
    general_rows = [_row(d) for d in result['diagnostics'] + result['integration']['diagnostics']]
    task_rows = [_row(d) for task in result['tasks'] for d in task['diagnostics']]
    general, task_level = len(general_rows), len(task_rows)
    assert len(result['diagnostics']) > 50 and task_level > 50
    _run(tmp_path, r'''
await webMount('both-floods');const root=webRequired(),text=webText();
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
assert.ok(graphWalk(root).length<=3000,'total newly created result DOM nodes bounded');
'''.replace('GENERAL_TOTAL', str(general)).replace('TASK_TOTAL', str(task_level))
    .replace('GENERAL_SHOWN', json.dumps(general_rows[:50], ensure_ascii=False)).replace('TASK_SHOWN', json.dumps(task_rows[:50], ensure_ascii=False)), value, 'both-floods')


def test_empty_state_only_when_both_lists_are_empty(tmp_path):
    value = _typed()
    result = _flood(value)
    assert not result['diagnostics'] and not result['integration']['diagnostics']
    assert not any(task['diagnostics'] for task in result['tasks'])
    _run(tmp_path, r"""
await webMount('empty');assert.ok(webText().includes('本次投影没有记录诊断'),'empty state shown when nothing was recorded');
""", value, 'empty')


def test_task_only_diagnostics_are_not_reported_as_empty(tmp_path):
    value = _envelope(verified=True)
    value['id'] = MID
    result = _flood(value, tasks=1)
    assert not result['diagnostics'] and not result['integration']['diagnostics']
    _run(tmp_path, r"""
await webMount('task-only');const text=webText();
assert.ok(text.includes('DEPENDENCY_GRAPH_INVALID · task'));
assert.ok(!text.includes('本次投影没有记录诊断'),'task-level diagnostics alone are not an empty projection');
""", value, 'task-only')


def test_general_only_diagnostics_are_not_reported_as_empty(tmp_path):
    value = _typed()
    result = _flood(value, runs=1)
    assert result['diagnostics'] and not any(task['diagnostics'] for task in result['tasks'])
    _run(tmp_path, r"""
await webMount('general-only');assert.ok(!webText().includes('本次投影没有记录诊断'));
assert.ok(webText().includes(ROW),'the single result diagnostic is shown');
""".replace('ROW', json.dumps(_row(result['diagnostics'][0]), ensure_ascii=False)), value, 'general-only')


def test_diagnostics_disclosure_precedes_task_disclosures(tmp_path):
    value = _typed()
    _flood(value, tasks=2, runs=2)
    _run(tmp_path, r"""
await webMount('order');const order=graphWalk(webRequired()).map(x=>x.dataset?.detail).filter(Boolean);
const diagnostics=order.indexOf('engineering-diagnostics'),firstTask=order.indexOf('engineering-task-0');
assert.ok(diagnostics>=0&&firstTask>=0&&diagnostics<firstTask,'bounded failure signals render before task details: '+order.join(','));
""", value, 'order')
