"""Frozen optional-graph error boundary checks; no production/device acceptance.

Use the original graph12 standard SVG/DOM support and canonical wire setup
unchanged. The standard namespace function exists and works: only a controlled
creation exception is injected. No missing-method shim, page-function replacement,
permission alias, source edit or native/provider/network operation.
"""
from __future__ import annotations

import json
import subprocess

from sisyfus.workers.lead_chat_page import PAGE
from test_chat_node_placement_page import HARNESS
from test_mission_graph_page import _DOM_SUPPORT, _SETUP, _markup


_BOUNDARY = r'''
const boundaryCreateSVG=document.createElementNS.bind(document);
let boundaryFault={armed:false,throws:0,created:[],matches:0};
document.createElementNS=(namespace,tag)=>{
 if(boundaryFault.armed&&namespace===SVG_NS&&(boundaryFault.tag===null||boundaryFault.tag===tag)){
  boundaryFault.matches++;
  if(boundaryFault.matches>=boundaryFault.after){
   boundaryFault.throws++;
   console.log('BOUNDARY_CREATION_FAULT '+JSON.stringify({tag,matches:boundaryFault.matches,throws:boundaryFault.throws,created:boundaryFault.created}));
   const error=new TypeError(boundaryFault.message);error.name=boundaryFault.name;throw error;
  }
 }
 const created=boundaryCreateSVG(namespace,tag);
 if(boundaryFault.armed)boundaryFault.created.push(tag);
 return created;
};
function boundaryArm({tag=null,after=1,message='CONTROLLED_GRAPH_CREATE_FAILURE',name='TypeError'}={}){
 boundaryFault={armed:true,tag,after,message,name,throws:0,created:[],matches:0};
}
function boundaryCalibrate(marker){
 assert.equal(typeof document.createElementNS,'function','FIXTURE_SETUP_ERROR standard namespace API');
 const actual=boundaryCreateSVG(SVG_NS,'g');
 assert.equal(actual.namespaceURI,SVG_NS,'FIXTURE_SETUP_ERROR standard SVG creation');
 assert.equal(graphRequired().namespaceURI,SVG_NS,'FIXTURE_SETUP_ERROR actual declared SVG');
 for(const view of graphViews.values()){
  assert.equal(JSON.stringify(Object.keys(view).sort()),JSON.stringify(['controller','controls','id','snapshot']),'FIXTURE_SETUP_ERROR Hub wrapper');
  assert.ok(Array.isArray(view.snapshot.nodes)&&Array.isArray(view.controls),'FIXTURE_SETUP_ERROR canonical producer');
  assert.ok(view.snapshot.nodes.every(task=>typeof task.id==='string'&&Array.isArray(task.depends_on)),'FIXTURE_SETUP_ERROR fixed task shape');
 }
 console.log('BOUNDARY_FIXTURE_READY '+marker+' actual SVG + working standard createElementNS + exact canonical producer');
}
function boundaryAuthority(){
 const task=state.mission?.snapshot.nodes.find(task=>task.id==='analyse');
 const root=state.mission?.snapshot.nodes.find(task=>task.id==='root');
 return {machines:machineOperationAllowed(mid),assignReady:!!task&&assignmentAllowed(task,nid),
  assignAccepted:!!root&&assignmentAllowed(root,nid),composer:canSend(),stop:missionControlAllowed('stop'),
  uncheckedStartDisabled:el('mission-start-confirm').disabled};
}
async function boundaryRead(operation,marker){
 let rejected=null;
 try{await operation();}catch(error){rejected={name:String(error.name),message:String(error.message)};}
 // The independent existing inbox/machine/chat reads also settle after a failed
 // optional paint. This finite microtask drain sends no extra request itself.
 for(let count=0;count<16;count++)await Promise.resolve();
 console.log('BOUNDARY_READ '+marker+' '+JSON.stringify({rejected,creationFaults:boundaryFault.throws,
  loadError:state.loadError,networkError:state.networkError,connected:state.connected,
  phase:state.mission?.snapshot.phase,revision:state.mission?.snapshot.revision,
  graphNote:el('mission-graph-note').textContent,graphIds:graphNodes().map(item=>item.dataset.taskId),
  authority:boundaryAuthority(),postCount:calls.filter(call=>call.method==='POST').length}));
 return rejected;
}
function boundaryInputReady(marker){
 assert.equal(state.kind,'mission','BOUNDARY_CANONICAL_VIEW_LOST');assert.equal(state.id,mid,'BOUNDARY_MISSION_ID_CHANGED');
 assert.equal(JSON.stringify(state.mission),JSON.stringify(graphViews.get(mid)),'BOUNDARY_CANONICAL_SNAPSHOT_CHANGED');
 assert.equal(JSON.stringify(graphWalk(el('task-list')).filter(item=>item.dataset.detail).map(item=>item.dataset.detail).sort()),
  JSON.stringify(graphViews.get(mid).snapshot.nodes.map(item=>item.id).sort()),'BOUNDARY_ORIGINAL_CARDS_LOST');
 assert.match(el('mission-message-thread').textContent,/同页任务资料/,'BOUNDARY_ORIGINAL_MESSAGE_LOST');
 assert.equal(calls.filter(call=>call.method!=='GET').length,0,'BOUNDARY_UNEXPECTED_DISPATCH');
 assert.ok(boundaryFault.throws>0,'FIXTURE_SETUP_ERROR controlled exception not reached');
 assert.equal(typeof document.createElementNS,'function','FIXTURE_SETUP_ERROR namespace function removed');
 console.log('BOUNDARY_INPUT_READY '+marker+' real snapshot/cards/messages retained; controlled creation exception reached; zero POST');
}
function boundaryErrorNote(){
 const note=el('mission-graph-note');
 assert.ok(!note.hidden,'BOUNDARY_ERROR_DIAGNOSTIC_HIDDEN');
 assert.match(note.textContent,/图.*(失败|异常|出错)/,'BOUNDARY_ERROR_DIAGNOSTIC_MISSING');
 assert.doesNotMatch(note.textContent,/绘制成功|图已更新|图.*验收通过/,'BOUNDARY_FALSE_GRAPH_SUCCESS');
}
function boundaryEmptyDiagram(){
 const svg=graphRequired();
 assert.equal(graphNodes(svg).length,0,'BOUNDARY_STALE_TASK_GRAPH_RETAINED');
 const visible=graphWalk(svg).filter(item=>!item.closest('defs')&&
  ['text','rect','path','line','polyline','polygon','circle','ellipse','image'].includes(item.tagName.toLowerCase()));
 assert.equal(visible.length,0,'BOUNDARY_PARTIAL_GRAPH_RETAINED');
 assert.ok(!graphWalk(svg).some(item=>item.dataset.from!==undefined||item.dataset.to!==undefined),'BOUNDARY_STALE_EDGE_RETAINED');
}
function boundaryAcceptance(){return JSON.stringify(graphViews.get(mid).snapshot.nodes.map(task=>({
 id:task.id,acceptance:task.acceptance,check:task.check,write_paths:task.write_paths,depends_on:task.depends_on,
 verdict:task.verdict,verification:task.verification,stale:task.stale,active:task.active,superseded_by:task.superseded_by})));}
'''


def _run_boundary(tmp_path, case):
    markup = _markup()
    assert markup['mission-graph']['tag'] == 'svg'
    assert markup['mission-message-thread']['attrs']['role'] == 'log'
    script = PAGE.split('<script nonce="NONCE">', 1)[1].split('</script>', 1)[0]
    script = script.rsplit('render(); resizeComposer();', 1)[0]
    support = _DOM_SUPPORT.replace('GRAPH_MARKUP', json.dumps(markup, ensure_ascii=False))
    payload = HARNESS.replace('SOURCE', json.dumps(support + script)).replace(
        'CASE', json.dumps(_SETUP + _BOUNDARY + case))
    fixture = tmp_path / 'boundary-case.js'
    fixture.write_text(payload)
    result = subprocess.run(['node', str(fixture)], capture_output=True, text=True, timeout=15)
    (tmp_path / 'boundary-stdout.log').write_text(result.stdout)
    (tmp_path / 'boundary-stderr.log').write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr


def test_mount_graph_exception_keeps_valid_core_cards_messages_and_connection(tmp_path):
    _run_boundary(tmp_path, r'''
boundaryCalibrate('mount');const accepted=boundaryAcceptance();boundaryArm();
const rejected=await boundaryRead(()=>selectMission(mid),'mount-failure');boundaryInputReady('mount');
assert.equal(rejected,null,'BOUNDARY_GRAPH_EXCEPTION_PROPAGATED');
assert.equal(state.loadError,'','BOUNDARY_VALID_SNAPSHOT_MARKED_LOAD_ERROR');
assert.equal(state.networkError,'','BOUNDARY_GRAPH_ERROR_MARKED_NETWORK_FAILURE');assert.equal(state.connected,true);
assert.equal(boundaryAcceptance(),accepted);assert.equal(state.mission.snapshot.all_verified,false);
assert.match(el('acceptance-status').textContent,/尚未确认通过验收/);
boundaryErrorNote();boundaryEmptyDiagram();
''')


def test_creation_failure_is_explicit_in_graph_note_without_fake_success(tmp_path):
    _run_boundary(tmp_path, r'''
boundaryCalibrate('diagnostic');boundaryArm();
const rejected=await boundaryRead(()=>selectMission(mid),'diagnostic-failure');boundaryInputReady('diagnostic');
assert.equal(rejected,null,'BOUNDARY_GRAPH_EXCEPTION_PROPAGATED');boundaryErrorNote();boundaryEmptyDiagram();
assert.equal(state.mission.snapshot.all_verified,false);assert.equal(state.pending.size,0);
''')


def test_refresh_partial_creation_clears_previous_graph_and_preserves_new_cards(tmp_path):
    _run_boundary(tmp_path, r'''
boundaryCalibrate('partial-refresh');await graphMount(mid,'healthy-before-partial');
assert.equal(graphNodes().length,4,'FIXTURE_SETUP_ERROR initial real graph');
graphViews.get(mid).snapshot.nodes.push(graphTask('new-dependent',['root']));graphViews.get(mid).snapshot.revision++;
const accepted=boundaryAcceptance();boundaryArm({tag:'text',after:2});
const rejected=await boundaryRead(()=>el('mission-refresh').onclick(),'partial-refresh-failure');boundaryInputReady('partial-refresh');
assert.ok(boundaryFault.created.includes('text'),'FIXTURE_SETUP_ERROR no partial drawable creation');
assert.equal(rejected,null,'BOUNDARY_GRAPH_EXCEPTION_PROPAGATED');boundaryEmptyDiagram();boundaryErrorNote();
assert.equal(state.loadError,'');assert.equal(state.mission.snapshot.revision,2);assert.equal(boundaryAcceptance(),accepted);
''')


def test_same_payload_explicit_reread_recovers_after_failed_graph_signature(tmp_path):
    _run_boundary(tmp_path, r'''
boundaryCalibrate('recovery');await graphMount(mid,'healthy-before-recovery');
graphViews.get(mid).snapshot.nodes.push(graphTask('recovered-dependent',['root']));graphViews.get(mid).snapshot.revision++;
const canonical=JSON.stringify(graphViews.get(mid));boundaryArm();
const failed=await boundaryRead(()=>readSelected(),'before-recovery');boundaryInputReady('before-recovery');
assert.equal(failed,null,'BOUNDARY_GRAPH_EXCEPTION_PROPAGATED');boundaryFault.armed=false;
const recovered=await boundaryRead(()=>el('mission-refresh').onclick(),'same-payload-recovery');
assert.equal(recovered,null);assert.equal(JSON.stringify(state.mission),canonical,'BOUNDARY_RECOVERY_CHANGED_CORE');
assert.equal(state.loadError,'');assert.equal(state.networkError,'');assert.equal(state.connected,true);
assert.equal(JSON.stringify(graphNodes().map(item=>item.dataset.taskId).sort()),
 JSON.stringify(graphViews.get(mid).snapshot.nodes.map(task=>task.id).sort()),'BOUNDARY_FAILED_SIGNATURE_PREVENTS_REDRAW');
const edges=graphWalk(graphRequired()).filter(item=>item.dataset.from!==undefined||item.dataset.to!==undefined);
assert.equal(JSON.stringify(edges.map(item=>item.dataset.from+'>'+item.dataset.to).sort()),
 JSON.stringify(graphViews.get(mid).snapshot.nodes.flatMap(task=>task.depends_on.map(dep=>dep+'>'+task.id)).sort()));
assert.equal(el('mission-graph-note').textContent,'');assert.equal(calls.filter(call=>call.method==='POST').length,0);
''')


def test_graph_exception_diagnostic_hides_sensitive_message_and_type(tmp_path):
    _run_boundary(tmp_path, r'''
boundaryCalibrate('sensitive-error');const storageBefore=new Map(storage);globalThis.boundaryExecuted=false;
boundaryArm({message:'PRIVATE_RENDER_BODY fixture-access Node '+secret+' <img src=x onerror="boundaryExecuted=true">',
 name:'PRIVATE_GRAPH_TYPE fixture-access '+secret});
const rejected=await boundaryRead(()=>selectMission(mid),'sensitive-error');boundaryInputReady('sensitive-error');
assert.equal(rejected,null,'BOUNDARY_GRAPH_EXCEPTION_PROPAGATED');
const surfaces=[...elements.values()].flatMap(item=>graphWalk(item));
const displayed=surfaces.map(item=>item.textContent+' '+Object.values(item.attributes).join(' ')).join('\n')+
 JSON.stringify({loadError:state.loadError,networkError:state.networkError,traces:state.traces});
assert.ok(!displayed.includes('fixture-access')&&!displayed.includes(secret),'BOUNDARY_RENDER_ERROR_CREDENTIAL_LEAK');
assert.doesNotMatch(displayed,/PRIVATE_RENDER_BODY|PRIVATE_GRAPH_TYPE/,'BOUNDARY_RAW_EXCEPTION_DIAGNOSTIC_LEAK');
const changedStorage=[...storage].filter(([key,value])=>storageBefore.get(key)!==value).map(([,value])=>value).join('\n');
assert.doesNotMatch(changedStorage,/PRIVATE_RENDER_BODY|PRIVATE_GRAPH_TYPE|fixture-access/);
assert.ok(!changedStorage.includes(secret));assert.equal(globalThis.boundaryExecuted,false);
assert.ok(!surfaces.some(item=>['img','image','script','iframe'].includes(item.tagName.toLowerCase())));
boundaryErrorNote();boundaryEmptyDiagram();assert.equal(calls.filter(call=>call.method==='POST').length,0);
''')


def test_graph_error_preserves_original_authority_gates_without_dispatch(tmp_path):
    _run_boundary(tmp_path, r'''
boundaryCalibrate('authority');await graphMount(mid,'healthy-authority-control');
const original=boundaryAuthority();assert.equal(original.machines,true,'FIXTURE_SETUP_ERROR machine authority control');
assert.equal(original.assignReady,true,'FIXTURE_SETUP_ERROR fixed READY task control');
assert.equal(original.assignAccepted,false,'FIXTURE_SETUP_ERROR accepted task fence');assert.equal(original.composer,true);
assert.equal(original.stop,true);assert.equal(original.uncheckedStartDisabled,true,'FIXTURE_SETUP_ERROR unchecked worker permission');
const accepted=boundaryAcceptance(),pending=JSON.stringify([...state.pending]);graphViews.get(mid).snapshot.revision++;
boundaryArm();const rejected=await boundaryRead(()=>readSelected(),'authority-failure');boundaryInputReady('authority');
assert.equal(rejected,null,'BOUNDARY_GRAPH_EXCEPTION_PROPAGATED');
assert.equal(JSON.stringify(boundaryAuthority()),JSON.stringify(original),'BOUNDARY_UNRELATED_AUTHORITY_CHANGED');
assert.equal(boundaryAcceptance(),accepted);assert.equal(JSON.stringify([...state.pending]),pending);
assert.equal(el('mission-permission').checked,false);assert.equal(state.mission.snapshot.all_verified,false);
assert.equal(calls.filter(call=>call.method==='POST').length,0);boundaryErrorNote();boundaryEmptyDiagram();
''')
