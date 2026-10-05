"""Execute the shipped UI logic against a minimal DOM, never a live provider."""
import json
import shutil
import subprocess

from sisyfus.workers.lead_chat_page import PAGE


def test_preparation_and_dispatch_have_separate_ui_gates():
    script = PAGE.split('<script nonce="NONCE">', 1)[1].split('</script>', 1)[0]
    script = script.rsplit('render(); resizeComposer();', 1)[0]
    harness = r'''const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
class Element {
  constructor(tag='div') { this.tagName=tag; this.children=[]; this.dataset={}; this.style={}; this.value=''; this.hidden=false; this.checked=false; this.disabled=false; this._text=''; this.classList={add(){},remove(){}}; }
  get textContent() { return this._text + this.children.map(x=>x.textContent||'').join(' '); }
  set textContent(value) { this._text=value; this.children=[]; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this._text=''; this.children=items; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  addEventListener() {}
  setAttribute() {}
  removeAttribute() {}
  contains() { return false; }
  closest() { return null; }
  scrollIntoView() {}
  focus() { this.focused=true; }
}
const el=id=>{ if(!elements.has(id)) elements.set(id,new Element()); return elements.get(id); };
let fetches=0;
const context = vm.createContext({console,URLSearchParams,Map,Set,Date,JSON,Math,Array,String,Number,
 location:{origin:'http://fixture.local',hash:'',pathname:'/',search:''},
 sessionStorage:{getItem(){return null;},setItem(){}}, history:{replaceState(){}},
 document:{getElementById:el,createElement:tag=>new Element(tag),querySelectorAll(){return [];},addEventListener(){},activeElement:null},
 window:{addEventListener(){}}, requestAnimationFrame:fn=>fn(),
 fetch(){fetches++; throw Error('preflight dispatched a request');}, setTimeout(){}, clearTimeout(){},
 assert,el});
vm.runInContext(SOURCE,context);
vm.runInContext(`
const gaps = [
 {id:'proposal',label:'方案草案',ready:true,detail:'已整理 13 项工作。'},
 {id:'source',label:'工程目录',ready:false,detail:'聊天中的路径不会自动绑定。'},
 {id:'acceptance',label:'固定验收检查',ready:false,detail:'文字验收尚未落实为固定检查。'},
 {id:'native',label:'调用状态',ready:true,detail:'没有在途调用。'}
];
state.kind='chat'; state.id='fixture-chat'; state.connected=true;
state.chat={id:state.id,status:'IDLE',source:'',spec_path:'',approval_hash:'hash-one',mission_id:null,
 proposal:{objective:'test',architecture:'test',tasks:[{title:'create project',acceptance:'six tests'}]},
 checks:[],readiness:{ready:false,can_prepare:true,requirements:gaps,reason:'开工前还需准备：工程目录、固定验收检查。'}};
el('chat-confirm').hidden=true; el('preflight').hidden=true;
renderProposal(state.chat); renderAvailability();
assert.equal(el('review-plan').disabled,false,'missing context must not disable inspection');
el('review-plan').onclick();
assert.equal(el('preflight').hidden,false);
assert.equal(el('chat-confirm').hidden,true);
assert.equal(el('chat-start').disabled,true);
assert.equal(state.confirmedApprovalHash,null);
assert.match(el('preflight-requirements').textContent,/工程目录/);
assert.match(el('preflight-requirements').textContent,/固定验收检查/);
assert.match(el('preflight-summary').textContent,/2/);

// Read-only inspection remains useful even when a request is unresolved.
state.chat.status='UNKNOWN'; renderAvailability();
assert.equal(el('review-plan').disabled,false); el('review-plan').onclick();
assert.equal(el('chat-start').disabled,true); assert.equal(state.confirmedApprovalHash,null);
state.chat.status='IDLE';
state.chat.source='/fixture/project'; state.chat.spec_path='/fixture/approved.json';
state.chat.readiness={ready:true,can_prepare:true,requirements:gaps.map(r=>({...r,ready:true})),reason:'已就绪'};
state.chat.checks=[{id:'independent-check'}];
renderProposal(state.chat); renderAvailability(); el('review-plan').onclick();
assert.equal(el('chat-confirm').hidden,false);
assert.equal(el('chat-start').disabled,true,'permission remains explicit');
el('chat-permission').checked=true; renderAvailability();
assert.equal(el('chat-start').disabled,false);
state.chat.approval_hash='hash-two'; renderProposal(state.chat); renderAvailability();
assert.equal(el('chat-confirm').hidden,true); assert.equal(el('chat-permission').checked,false);
assert.match(el('announcement').textContent,/重新审阅/);

// Ordinary conversation changes do not pretend an approval was withdrawn.
el('announcement').textContent=''; state.chat.approval_hash='hash-three'; renderProposal(state.chat);
assert.equal(el('announcement').textContent,'');
state.connected=false; renderAvailability();
assert.equal(el('review-plan').disabled,false); el('review-plan').onclick();
assert.equal(el('chat-confirm').hidden,true); assert.equal(el('chat-start').disabled,true);
assert.match(el('preflight-note').textContent,/连接/);
state.connected=true; state.pending.set(pendingKey(),{type:'start'}); renderAvailability(); el('review-plan').onclick();
assert.equal(el('chat-confirm').hidden,true); assert.match(el('preflight-note').textContent,/结果/);
state.pending.clear(); state.busy={type:'message'}; renderAvailability();
assert.equal(el('review-plan').disabled,true);
state.busy=null; state.loading=true; renderAvailability(); assert.equal(el('review-plan').disabled,true);
state.loading=false; state.chat.proposal=null; renderAvailability(); assert.equal(el('review-plan').disabled,true);
`,context);
assert.equal(fetches,0,'inspection never dispatches or creates files');
console.log('preflight UI gates, exact confirmation, no automatic requests: PASS');
'''
    node = shutil.which("node")
    assert node, "Node is required for the shipped UI regression check"
    result = subprocess.run([node, "-e", harness.replace("SOURCE", json.dumps(script))],
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
