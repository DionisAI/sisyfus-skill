"""Render canonical RSI receipts without invented savings or adoption."""
import json
import subprocess

from sisyfus.workers.lead_chat_page import PAGE


def test_rsi_is_conversational_not_a_configuration_form():
    assert 'RSI 对照与晋升' in PAGE
    assert 'RSI 编排准备' in PAGE
    assert 'id="rsi-enabled"' not in PAGE
    assert 'id="rsi-catalog"' not in PAGE
    assert "const rsi = state.chat.rsi_configuration" in PAGE


def test_rsi_evidence_requires_counts_and_current_adoption():
    script = PAGE.split('<script nonce="NONCE">', 1)[1].split('</script>', 1)[0]
    script = script.rsplit('render(); resizeComposer();', 1)[0]
    harness = r'''
const vm = require('node:vm'), assert = require('node:assert/strict');
const elements = new Map();
class Element {
 constructor(){this.children=[];this.dataset={};this.style={};this.value='';this._text='';this.classList={add(){},remove(){},toggle(){}};}
 get textContent(){return this._text + this.children.map(x=>x.textContent||'').join(' ');}
 set textContent(v){this._text=v;this.children=[];}
 append(...items){this.children.push(...items);}
 replaceChildren(...items){this._text='';this.children=items;}
 querySelectorAll(){return [];}
 querySelector(){return null;}
 addEventListener(){} setAttribute(){} removeAttribute(){} contains(){return false;}
}
const el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const context=vm.createContext({console,URLSearchParams,Map,Set,Date,JSON,Math,Array,String,Number,Object,
 location:{origin:'http://fixture.local',hash:'',pathname:'/',search:''},
 sessionStorage:{getItem(){return null;},setItem(){}},history:{replaceState(){}},
 document:{getElementById:el,createElement:()=>new Element(),querySelectorAll(){return [];},addEventListener(){}},
 window:{addEventListener(){}},requestAnimationFrame:fn=>fn(),setTimeout(){},clearTimeout(){},assert,el});
vm.runInContext(SOURCE,context);
vm.runInContext(`
const proof=n=>({invocations:n,cost_status:'UNMETERED',attestation:{lead:'ATTESTED',worker:'MISSING',reviewer:'ATTESTED'}});
const report={status:'NONPROMOTION',promoted:false,candidate_id:'candidate-one',arms:[
 {pair_id:'search',split:'search',arm:'baseline',proof:proof(6)},
 {pair_id:'search',split:'search',arm:'candidate',proof:proof(6)},
 {pair_id:'holdout',split:'holdout',arm:'baseline',proof:proof(6)},
 {pair_id:'holdout',split:'holdout',arm:'candidate',proof:proof(6)}
],error:{message:'no strictly measured invocation improvement'}};
const snap={procedure:{id:'initial',version:0},rsi:{active_id:'initial'},procedure_trials:{status:'IDLE',paired_trial_results:[{key:'one',data:report}]}};
renderRSI(snap);
assert.match(el('rsi-evidence').textContent,/baseline 6 次 → candidate 6 次；节省 0 次/);
assert.match(el('rsi-evidence').textContent,/holdout · 独立留出/);
assert.match(el('rsi-evidence').textContent,/未晋升，保留既有策略/);
assert.match(el('rsi-evidence').textContent,/费用计量不完整/);
assert.match(el('rsi-evidence').textContent,/运行模型证明不完整/);
assert.doesNotMatch(el('rsi-evidence').textContent,/已晋升并采用/);
report.status='ELIGIBLE';report.arms[1].proof=proof(4);renderRSI(snap);
assert.match(el('rsi-evidence').textContent,/节省 2 次/);
assert.match(el('rsi-evidence').textContent,/尚未晋升/);
report.status='PROMOTED';report.promoted=true;renderRSI(snap);
assert.doesNotMatch(el('rsi-evidence').textContent,/已晋升并采用/);
snap.rsi.active_id='candidate-one';renderRSI(snap);
assert.match(el('rsi-evidence').textContent,/已晋升并采用候选策略/);
report.status='FENCED';report.promoted=false;report.arms=[{arm:'baseline',split:'search',reservations:6}];renderRSI(snap);
assert.match(el('rsi-evidence').textContent,/调用与验收证据尚未齐备/);
assert.doesNotMatch(el('rsi-evidence').textContent,/节省 0 次/);
snap.procedure_trials={status:'RUNNING',paired_trial_results:[]};renderRSI(snap);
assert.match(el('rsi-evidence').textContent,/评估状态/);
assert.doesNotMatch(el('rsi-evidence').textContent,/已晋升并采用/);
snap.procedure_trials.trial_children=[{read_status:'OK',phase:'IMPLEMENTING',reservations:3,registrations:[{category:'paired_trial_children',data:{split:'search',arm:'baseline'}}]}];renderRSI(snap);
assert.match(el('rsi-evidence').textContent,/search · baseline/);
assert.match(el('rsi-evidence').textContent,/已记录 3 次调用/);
assert.match(el('rsi-evidence').textContent,/不是验收或晋升结论/);
snap.procedure_trials.trial_children[0].read_status='ERROR';snap.procedure_trials.trial_children[0].reservations=null;renderRSI(snap);
assert.match(el('rsi-evidence').textContent,/调用数未知/);
assert.doesNotMatch(el('rsi-evidence').textContent,/已记录 0 次调用/);
snap.procedure_trials={status:'IDLE',paired_trial_results:[{key:'multi',data:{status:'NONPROMOTION',candidate_id:'multi',arms:[
 {case_id:'first',split:'search',arm:'baseline',proof:proof(8)},
 {case_id:'first',split:'search',arm:'candidate',proof:proof(6)},
 {case_id:'second',split:'search',arm:'baseline',proof:proof(5)},
 {case_id:'second',split:'search',arm:'candidate',proof:proof(5)}
]}}]};renderRSI(snap);
assert.match(el('rsi-evidence').textContent,/baseline 8 次 → candidate 6 次/,'every case must remain visible');
assert.match(el('rsi-evidence').textContent,/baseline 5 次 → candidate 5 次/);
assert.equal(missionHeading('approved objective\\n\\nOperator-confirmed conversation plan:\\n实现 job.py，提供轮询接口。更多要求。\\nArchitecture:\\nmodule\\nTask outline:\\n[{"title":"task"}]'),'实现 job.py，提供轮询接口');
state.confirmFingerprint='old';state.confirmedApprovalHash='approved';el('announcement').textContent='';
renderProposal({proposal:null,mission_id:'new-mission',approval_hash:'approved',checks:[],readiness:{ready:true},source:'/project',spec_path:'/spec'});
assert.equal(el('announcement').textContent,'','successful Start does not announce withdrawn approval');
`,context);
'''
    result = subprocess.run(['node', '-e', harness.replace('SOURCE', json.dumps(script))], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
