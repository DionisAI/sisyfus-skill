"""Frozen page-v3 retry regressions against the shipped production script.

Static boundary: exact existing operator paths/bodies; NEW machine-retry button.
Use the immutable DOM/fetch harness, seeded before script evaluation for actual
pending hydration. All assertions are outside fetch callbacks. Every invocation
requires a completion marker, so an unresolved fixture Promise never passes.
Socket-free protocol evidence, not native/browser/device acceptance.
"""
import json
import subprocess

import pytest

from sisyfus.workers.lead_chat_page import PAGE
from test_chat_node_placement_page import HARNESS, Tags


MARKER = 'machine-retry-scenario-completed'


def run_case(case, *, seed=()):
    script = PAGE.split('<script nonce="NONCE">', 1)[1].split('</script>', 1)[0]
    script = script.rsplit('render(); resizeComposer();', 1)[0]
    harness = HARNESS.replace('vm.runInContext(SOURCE,context);',
        'for(const [key,value] of ' + json.dumps(seed) + ')storage.set(key,value);\nvm.runInContext(SOURCE,context);')
    result = subprocess.run(['node', '-e', harness.replace('SOURCE', json.dumps(script)).replace(
        'CASE', json.dumps(case + '\nconsole.log(' + json.dumps(MARKER) + ');'))],
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert MARKER in result.stdout, 'scenario exited before completion: ' + result.stdout + result.stderr
    return result.stdout


SETUP = r'''
const root='/api/missions/'+mid;
const nextNode={...registered,node_id:'node_'+'4'.repeat(32),request_id:'pending',name:'重试机器'};
let rows=[registered],chosen={kind:'local'},readMode='complete';
function getMachines(call){
 if(call.path==='/api/chats')return {chats:[],issues:[],auto_start:false};
 if(call.path===root+'/nodes'){
  if(readMode==='nodes-error')throw Error('retained inventory fixture failure');
  return {mission_id:mid,nodes:rows,execution_ready:false};}
 if(call.path===root+'/placements')return {mission_id:mid,placements:readMode==='partial-pins'?[]:[{task_id:task.id,placement:chosen}]};
 if(call.path==='/api/snapshot?mission_id='+other)return {snapshot:{...snapshot.snapshot,nodes:[]},controller:{running:false},controls:[]};
 return undefined;
}
setGet(getMachines);await selectMission(mid);
const checksBefore=JSON.stringify([task.acceptance,task.check,task.write_paths,snapshot.snapshot.all_verified,chat.checks]);
function candidate(call,kind){
 if(kind==='placement')return pin(call.body.request_id);
 if(kind==='enroll')return {...nextNode,request_id:call.body.request_id,name:call.body.name,secret,execution_ready:false};
 return {...registered,status:'REVOKED',revoked_at:'2026-10-06',execution_ready:false};
}
function commit(call,kind){
 const value=candidate(call,kind);
 if(kind==='placement')chosen=value;
 else if(kind==='enroll'){const {secret:ignored,...publicRow}=value;rows=[registered,publicRow];}
 else rows=[value];
 return value;
}
async function firstFailure(kind,failure='timeout',committed=false){
 let original;setPost(call=>{original={path:call.path,body:call.body};if(committed)commit(call,kind);
  if(failure==='503')return response({error:'retained service fixture failure'},503);
  throw Object.assign(Error('lost fixture response'),{name:'AbortError'});});
 if(kind==='placement')await findSelect().click();
 else if(kind==='enroll'){el('node-name').value=nextNode.name;await el('node-enroll').click();}
 else await all().find(item=>item.dataset.revokeNode===nid).click();
 return original;
}
function assertNoAuthorityChange(){
 assert.equal(JSON.stringify([task.acceptance,task.check,task.write_paths,snapshot.snapshot.all_verified,chat.checks]),checksBefore);
 assert.equal(el('mission-permission').checked,false);
 for(const call of calls.filter(call=>call.method==='POST')){
  assert.equal(call.options.headers.Authorization,'Bearer fixture-access');assert.equal(call.options.credentials,'same-origin');
  assert.equal(call.path.includes('/api/control'),false);assert.equal(call.path.includes('/api/chat/start'),false);}
}
function assertSecretPrivate(){
 assert.equal(JSON.stringify(state).includes(secret),false);
 assert.equal([...elements.values()].some(item=>item.textContent.includes(secret)),false);
 assert.equal([...storage.values()].some(value=>value.includes(secret)),false);
 assert.equal(JSON.stringify(state.traces).includes(secret),false);
}
'''


def test_retry_is_a_named_explicit_button_not_an_automatic_action():
    tags = Tags(); tags.feed(PAGE)
    assert 'machine-retry' in tags.ids
    assert tags.ids['machine-retry'][0] == 'button'
    assert tags.ids['machine-retry'][1].get('type') == 'button'
    run_case(SETUP + r'''
assert.equal(el('machine-retry').hidden,true);await el('machine-retry').click();
assert.equal(calls.filter(call=>call.method==='POST').length,0);assertNoAuthorityChange();
''')


@pytest.mark.parametrize('kind', ['placement', 'enroll', 'revoke'])
@pytest.mark.parametrize('failure', ['timeout', '503'])
def test_uncommitted_retry_reuses_exact_persisted_path_body_and_request(kind, failure):
    run_case(SETUP + r'''
const kind=KIND,original=await firstFailure(kind,FAILURE),pending=state.pending.get('machine:'+mid);
assert.ok(pending);assert.equal(pending.path,original.path);
assert.equal(JSON.stringify(pending.body),JSON.stringify(original.body));
assert.equal(el('mission-start').disabled,true);assert.equal(el('machine-retry').hidden,false);
assert.equal(el('machine-retry').disabled,false);assert.equal(typeof el('machine-retry').onclick,'function');
await readSelected();await readSelected();assert.equal(calls.filter(call=>call.method==='POST').length,1);
el('node-name').value='此输入不替换原请求';setPost(call=>response(commit(call,kind),kind==='enroll'?201:200));
await el('machine-retry').click();
const posted=calls.filter(call=>call.method==='POST');assert.equal(posted.length,2);
assert.equal(posted[1].path,original.path);assert.equal(JSON.stringify(posted[1].body),JSON.stringify(original.body));
if(kind==='revoke'){assert.equal(posted[1].path,root+'/nodes/'+nid+'/revoke');assert.equal(JSON.stringify(posted[1].body),'{}');}
else assert.equal(posted[1].body.request_id,original.body.request_id);
assert.equal(state.pending.has('machine:'+mid),false);assert.equal(el('machine-retry').hidden,true);
assert.equal(el('mission-start').disabled,false);assertNoAuthorityChange();assertSecretPrivate();
assert.equal(copies.length,0);assert.equal(downloads.length,0);
if(kind==='enroll'){
 el('node-gateway-url').value='http://127.0.0.1:23456';el('node-gateway-host').value='127.0.0.1:34567';
 await el('node-config-copy').click();assert.equal(copies.length,1);const config=JSON.parse(copies[0]);
 assert.equal(config.secret,secret);assert.equal(config.node_id,nextNode.node_id);assert.equal(config.controller_mission_id,mid);
 assert.deepEqual(Object.keys(config).sort(),['controller_mission_id','gateway_host','gateway_url','node_id','schema','secret']);assertSecretPrivate();}
'''.replace('KIND', json.dumps(kind)).replace('FAILURE', json.dumps(failure)))


@pytest.mark.parametrize('kind', ['placement', 'enroll', 'revoke'])
def test_committed_lost_reply_resolves_by_matching_get_and_never_reposts(kind):
    run_case(SETUP + r'''
const kind=KIND;await firstFailure(kind,'timeout',true);
assert.equal(state.pending.has('machine:'+mid),false);assert.equal(el('machine-retry').hidden,true);
await readSelected();await el('machine-retry').click();assert.equal(calls.filter(call=>call.method==='POST').length,1);
if(kind==='enroll'){await el('node-config-copy').click();assert.equal(copies.length,0);assert.match(el('machine-note').textContent,/首次|凭据|撤销/);}
assertSecretPrivate();assertNoAuthorityChange();
'''.replace('KIND', json.dumps(kind)))


@pytest.mark.parametrize('kind', ['placement', 'enroll', 'revoke'])
@pytest.mark.parametrize('read_failure', ['nodes-error', 'partial-pins'])
def test_failed_or_partial_readback_fences_retry_and_keeps_original_pending(kind, read_failure):
    run_case(SETUP + r'''
const original=await firstFailure(KIND);assert.equal(el('machine-retry').disabled,false);
const staleHandler=el('machine-retry').onclick;readMode=READ_FAILURE;await readSelected();
assert.equal(el('machine-retry').disabled,true);await el('machine-retry').click();await staleHandler();
assert.equal(calls.filter(call=>call.method==='POST').length,1);assert.equal(el('mission-start').disabled,true);
assert.equal(JSON.stringify(state.pending.get('machine:'+mid).body),JSON.stringify(original.body));
assert.match(el('machine-note').textContent,/失败|不完整|完整|核对|查询/);
readMode='complete';await readSelected();assert.equal(el('machine-retry').disabled,false);
assert.equal(calls.filter(call=>call.method==='POST').length,1);assertNoAuthorityChange();
'''.replace('KIND', json.dumps(kind)).replace('READ_FAILURE', json.dumps(read_failure)))


@pytest.mark.parametrize('kind', ['placement', 'enroll', 'revoke'])
def test_new_read_generation_invalidates_saved_retry_handler_until_complete_pair(kind):
    run_case(SETUP + r'''
await firstFailure(KIND);const staleHandler=el('machine-retry').onclick;let release;
setGet(call=>call.path===root+'/nodes'?new Promise(resolve=>{release=resolve;}):getMachines(call));
const reading=readSelected();for(let i=0;i<12;i++)await Promise.resolve();
const disabled=el('machine-retry').disabled;await staleHandler();
release({mission_id:mid,nodes:rows,execution_ready:false});await reading;
await staleHandler();assert.equal(disabled,true);assert.equal(calls.filter(call=>call.method==='POST').length,1);
assert.equal(el('machine-retry').disabled,false);assertNoAuthorityChange();
'''.replace('KIND', json.dumps(kind)))


@pytest.mark.parametrize('kind', ['placement', 'enroll', 'revoke'])
def test_selection_and_return_require_new_fresh_handler_for_original_mission(kind):
    run_case(SETUP + r'''
const kind=KIND,original=await firstFailure(kind),staleHandler=el('machine-retry').onclick;
await selectMission(other);await staleHandler();assert.equal(calls.filter(call=>call.method==='POST').length,1);
await selectMission(mid);await staleHandler();assert.equal(calls.filter(call=>call.method==='POST').length,1);
setPost(call=>response(commit(call,kind)));await el('machine-retry').click();
const posted=calls.filter(call=>call.method==='POST');assert.equal(posted.length,2);
assert.equal(posted[1].path,original.path);assert.equal(JSON.stringify(posted[1].body),JSON.stringify(original.body));
assert.equal(state.pending.has('machine:'+mid),false);assertNoAuthorityChange();
'''.replace('KIND', json.dumps(kind)))


@pytest.mark.parametrize('kind', ['placement', 'enroll'])
def test_late_retry_reply_is_owned_by_original_mission_not_current_selection(kind):
    run_case(SETUP + r'''
const kind=KIND,original=await firstFailure(kind);let release;
setPost(call=>new Promise(resolve=>{release=()=>resolve(response(commit(call,kind)));}));
const waiting=el('machine-retry').click();for(let i=0;i<12;i++)await Promise.resolve();
assert.equal(typeof release,'function');await selectMission(other);release();await waiting;
assert.equal(state.id,other);assert.equal(state.kind,'mission');assert.equal(el('machine-retry').hidden,true);
assert.equal(state.machines.get(other).placements.length,0);assertSecretPrivate();
await selectMission(mid);assert.equal(state.pending.has('machine:'+mid),false);
assert.equal(calls.filter(call=>call.method==='POST').length,2);assertNoAuthorityChange();
'''.replace('KIND', json.dumps(kind)))


@pytest.mark.parametrize('kind', ['placement', 'enroll'])
def test_late_retry_reply_never_clears_a_newer_pending_generation(kind):
    run_case(SETUP + r'''
const kind=KIND;await firstFailure(kind);let release;
setPost(call=>new Promise(resolve=>{release=()=>resolve(response(commit(call,kind)));}));
const waiting=el('machine-retry').click();for(let i=0;i<12;i++)await Promise.resolve();
const old=state.pending.get('machine:'+mid),nextId=old.request_id+'-next';
const newer={...old,request_id:nextId,body:{...old.body,request_id:nextId}};
setPending('machine:'+mid,newer);release();await waiting;
assert.equal(state.pending.get('machine:'+mid).request_id,nextId);
assert.equal(el('mission-start').disabled,true);assert.equal(calls.filter(call=>call.method==='POST').length,2);
if(kind==='enroll')assert.equal(nodeCredentials.has(mid+':'+nextNode.node_id),false);
assertSecretPrivate();assertNoAuthorityChange();
'''.replace('KIND', json.dumps(kind)))


@pytest.mark.parametrize('kind', ['placement', 'enroll', 'revoke'])
@pytest.mark.parametrize('legacy', [False, True])
def test_actual_script_reload_restores_original_intent_and_only_explicitly_retries(kind, legacy):
    output = run_case(SETUP + r'''
await firstFailure(KIND);console.log('saved-machine-storage:'+JSON.stringify([...storage]));assertSecretPrivate();
'''.replace('KIND', json.dumps(kind)))
    seed = json.loads(next(line.split(':', 1)[1] for line in output.splitlines() if line.startswith('saved-machine-storage:')))
    if legacy:
        # eee really persisted type/body/node_id but no path or mission_id.
        for pair in seed:
            if pair[0].endswith(':pending'):
                pending = json.loads(pair[1])
                for _, intent in pending:
                    intent.pop('path', None); intent.pop('mission_id', None)
                pair[1] = json.dumps(pending, ensure_ascii=False)
    run_case(SETUP + r'''
const kind=KIND,saved=state.pending.get('machine:'+mid),bodyWire=JSON.stringify(saved.body);
assert.ok(saved);assert.equal(calls.filter(call=>call.method==='POST').length,0);
assert.equal(el('machine-retry').disabled,false);assert.equal(el('mission-start').disabled,true);
for(let i=0;i<4;i++)crypto.randomUUID(); // A new id after reload must differ even in this deterministic fixture.
setPost(call=>response(commit(call,kind)));await el('machine-retry').click();
const posted=calls.filter(call=>call.method==='POST');assert.equal(posted.length,1);
assert.equal(JSON.stringify(posted[0].body),bodyWire);
assert.equal(posted[0].path,root+(kind==='placement'?'/placements':kind==='enroll'?'/nodes':'/nodes/'+nid+'/revoke'));
assert.equal(state.pending.has('machine:'+mid),false);assertSecretPrivate();assertNoAuthorityChange();
'''.replace('KIND', json.dumps(kind)), seed=seed)


@pytest.mark.parametrize('bad', ['foreign-path', 'unknown-field', 'foreign-mission', 'changed-request', 'credential-name'])
def test_restored_intent_never_grants_other_routes_or_changes_original_body_authority(bad):
    run_case(SETUP + r'''
const bad=BAD,kind=bad==='credential-name'?'enroll':'placement';await firstFailure(kind);
const saved=state.pending.get('machine:'+mid),staleHandler=el('machine-retry').onclick;
const changed={...saved,body:{...saved.body}};
if(bad==='foreign-path')changed.path='/api/control';
if(bad==='unknown-field')changed.body.acceptance='PASS';
if(bad==='foreign-mission')changed.mission_id=other;
if(bad==='changed-request')changed.body.request_id+='-different';
if(bad==='credential-name')changed.body.name='fixture-access';
setPending('machine:'+mid,changed);await readSelected();
assert.equal(el('machine-retry').disabled,true);await el('machine-retry').click();await staleHandler();
assert.equal(calls.filter(call=>call.method==='POST').length,1);assert.equal(el('mission-start').disabled,true);assertNoAuthorityChange();
'''.replace('BAD', json.dumps(bad)))


@pytest.mark.parametrize('kind', ['placement', 'enroll', 'revoke'])
def test_retry_response_alone_never_resolves_pending_without_matching_get(kind):
    run_case(SETUP + r'''
const kind=KIND,original=await firstFailure(kind);
setPost(call=>response(candidate(call,kind)));await el('machine-retry').click();
assert.equal(state.pending.has('machine:'+mid),true,'HTTP response is not the required matching GET pair');
assert.equal(el('mission-start').disabled,true);assert.equal(calls.filter(call=>call.method==='POST').length,2);
commit(original,kind);await readSelected();assert.equal(state.pending.has('machine:'+mid),false);
assert.equal(el('mission-start').disabled,false);assert.equal(calls.filter(call=>call.method==='POST').length,2);
assertSecretPrivate();assertNoAuthorityChange();
'''.replace('KIND', json.dumps(kind)))


def test_retry_busy_state_fences_double_clicks_and_retains_one_original_request():
    run_case(SETUP + r'''
const original=await firstFailure('placement');let release;
setPost(call=>new Promise(resolve=>{release=()=>resolve(response(commit(call,'placement')));}));
const waiting=el('machine-retry').click();for(let i=0;i<12;i++)await Promise.resolve();
assert.equal(el('machine-retry').disabled,true);await el('machine-retry').click();
assert.equal(calls.filter(call=>call.method==='POST').length,2);release();await waiting;
assert.equal(state.pending.has('machine:'+mid),false);assert.equal(calls.filter(call=>call.method==='POST').length,2);
assertNoAuthorityChange();
''')
