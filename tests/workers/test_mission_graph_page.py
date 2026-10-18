"""Frozen same-page graph protocol checks, not native/browser/phone acceptance.

Reuse the original placement DOM/VM HARNESS byte-for-byte. New fixture support
only models standard SVG/DOM operations; it never creates a graph, rewrites page
functions, aliases public fields, or fabricates a successful backend response.
Freeze before the sole retained RED. Production and inherited tests stay HOLD.
"""
from __future__ import annotations

import json
import re
import subprocess
from html.parser import HTMLParser

import pytest

from sisyfus.workers.lead_chat_page import PAGE
from test_chat_node_placement_page import HARNESS


class _Markup(HTMLParser):
    void = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
            'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self):
        super().__init__()
        self.stack, self.ids = [], {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            assert attrs['id'] not in self.ids, 'duplicate actual HTML id'
            self.ids[attrs['id']] = {
                'tag': tag, 'attrs': attrs,
                'ancestors': [item[1] for item in self.stack if item[1]],
                'svg': tag == 'svg' or any(item[0] == 'svg' for item in self.stack),
            }
        if tag not in self.void:
            self.stack.append((tag, attrs.get('id')))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                self.stack = self.stack[:index]
                break

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.void:
            self.handle_endtag(tag)


def _markup():
    parsed = _Markup()
    parsed.feed(PAGE)
    return parsed.ids


# The original tiny harness lacks createElementNS, attribute readback and real
# descendant/event operations. These are explicit fixture capabilities, not a
# page implementation or a substitute graph. No prototype/realm comparisons.
_DOM_SUPPORT = r'''
const graphDeclared = GRAPH_MARKUP;
const SVG_NS='http://www.w3.org/2000/svg';
function graphWalk(root){const rows=[];const seen=new Set();function walk(x){if(!x||seen.has(x))return;seen.add(x);rows.push(x);for(const child of x.children||[])walk(child);}walk(root);return rows;}
function graphAttribute(item,key){if(key.startsWith('data-')){const name=key.slice(5).replace(/-([a-z])/g,(_,x)=>x.toUpperCase());if(item.dataset[name]!==undefined)return String(item.dataset[name]);}return item.attributes[key]??(key==='id'?item.id:null)??null;}
function graphMatches(item,selector){const tag=selector.match(/^[a-z][\w-]*/i)?.[0];if(tag&&item.tagName.toLowerCase()!==tag.toLowerCase())return false;
 for(const match of selector.matchAll(/\[([^\]=]+)(?:=["']?([^"'\]]+)["']?)?\]/g)){if(match[1]==='open'){if(!item.open)return false;}else if(graphAttribute(item,match[1])===null||match[2]!==undefined&&graphAttribute(item,match[1])!==match[2])return false;}return true;}
const graphSupported=new Set();
function graphSupport(item){if(graphSupported.has(item))return item;graphSupported.add(item);
 item.namespaceURI??='http://www.w3.org/1999/xhtml';
 item.getAttribute=key=>graphAttribute(item,key);item.hasAttribute=key=>graphAttribute(item,key)!==null;
 const set=item.setAttribute.bind(item);item.setAttribute=(key,value)=>{set(key,value);if(key==='id')item.id=String(value);if(key==='class')item.className=String(value);if(key.startsWith('data-'))item.dataset[key.slice(5).replace(/-([a-z])/g,(_,x)=>x.toUpperCase())]=String(value);};
 const append=item.append.bind(item);item.append=(...items)=>{for(const child of items)if(child&&typeof child==='object')child.parentNode=item;append(...items);};
 const replace=item.replaceChildren.bind(item);item.replaceChildren=(...items)=>{for(const old of item.children||[])if(old&&typeof old==='object')old.parentNode=null;replace(...items);for(const child of items)if(child&&typeof child==='object')child.parentNode=item;};
 item.querySelectorAll=selector=>graphWalk(item).slice(1).filter(x=>selector.split(',').some(s=>graphMatches(x,s.trim())));
 item.querySelector=selector=>item.querySelectorAll(selector)[0]||null;
 item.contains=other=>graphWalk(item).includes(other);
 item.closest=selector=>{for(let x=item;x;x=x.parentNode)if(graphMatches(x,selector))return x;return null;};
 item.focus=()=>{item.focused=true;document.activeElement=item;};
 Object.defineProperty(item,'innerHTML',{set(value){if(value)throw Error('GRAPH_FIXTURE_UNSAFE_HTML_WRITE');item.replaceChildren();},get(){return '';}});
 return item;
}
const graphCreate=document.createElement.bind(document);
document.createElement=tag=>graphSupport(graphCreate(tag));
document.createElementNS=(namespace,tag)=>{const item=document.createElement(tag);item.namespaceURI=namespace;return item;};
for(const [id,definition] of Object.entries(graphDeclared)){const item=graphSupport(el(id));item.id=id;item.tagName=definition.tag;item.namespaceURI=definition.svg?SVG_NS:'http://www.w3.org/1999/xhtml';for(const [name,value]of Object.entries(definition.attrs))item.setAttribute(name,value??'');}
async function graphFire(target,type,key){let stopped=false;const event={type,key,target,button:0,preventDefault(){this.defaultPrevented=true;},stopPropagation(){stopped=true;}};
 for(let item=target;item;item=item.parentNode){event.currentTarget=item;const handler=item['on'+type]||item.listeners[type];if(handler)await handler(event);if(stopped)break;}}
'''


_SETUP = r'''
function graphTask(id,depends_on=[],overrides={}){return {id,objective:'固定目标 '+id,depends_on,acceptance:'原固定验收 '+id,check:'check-'+id,write_paths:[id+'.txt'],state:'READY',attempts:0,verdict:'UNVERIFIED',stale:false,active:true,superseded_by:null,verification:null,...overrides};}
function graphVerification(id){return {evidence:{checks:[{check:'check-'+id,classification:{status:'PASS',summary:'固定协议夹具检查'}}],review:{verdict:'PASS',reasons:['独立协议夹具记录'],run_key:'review:'+id}}};}
function graphView(id,nodes,revision=1){return {id,snapshot:{objective:'固定图协议夹具 '+id,phase:'IMPLEMENTING',nodes,revision,all_verified:false,project_verified:false,runs:[],unresolved:[],reviews:[],diagnoses:[],integration:{continuation:null,evidence:null,current:false,builds:[]}},controller:{running:false,local_workers_acknowledged:false,error:null,stop_requested:false,auto_start:false},controls:[]};}
const graphBase=[graphTask('root',[],{state:'SUCCEEDED',verdict:'PASS',verification:graphVerification('root')}),graphTask('analyse',['root']),graphTask('inspect',['root']),graphTask('report',['analyse','inspect'])];
const graphViews=new Map([[mid,graphView(mid,graphBase)],[other,graphView(other,[graphTask('other-task')])]]);
const graphMessage={id:'msg-graph-original',seq:1,request_id:'graph-context-original-01',kind:'context',text:'图协议夹具：同页任务资料',status:'RECEIVED',answer:null,applications:[]};
let graphSnapshotHook=null;
setGet(async call=>{if(call.path.startsWith('/api/snapshot?')){const id=new URLSearchParams(call.path.split('?')[1]).get('mission_id');const value=await (graphSnapshotHook?graphSnapshotHook(id):graphViews.get(id));return JSON.parse(JSON.stringify(value));}
 if(call.path.startsWith('/api/mission/messages?')){const cursor=Number(new URLSearchParams(call.path.split('?')[1]).get('cursor')||0);return JSON.parse(JSON.stringify({messages:cursor===0?[graphMessage]:[],updates:[],cursor:1,application_cursor:0,has_more:false,has_more_updates:false}));}
 if(call.path.endsWith('/placements')){const id=call.path.split('/')[3];return {mission_id:id,placements:graphViews.get(id).snapshot.nodes.filter(item=>item.active!==false).map(item=>({task_id:item.id,placement:{kind:'local'}}))};}});
state.missions=[{id:mid,objective:graphViews.get(mid).snapshot.objective,source:chat.source},{id:other,objective:graphViews.get(other).snapshot.objective,source:chat.source}];
function graphReady(id,marker){assert.equal(state.kind,'mission','FIXTURE_SETUP_ERROR kind');assert.equal(state.id,id,'FIXTURE_SETUP_ERROR selected id');assert.equal(state.loadError,'','FIXTURE_SETUP_ERROR snapshot load');
 assert.equal(JSON.stringify(state.mission.snapshot.nodes),JSON.stringify(graphViews.get(id).snapshot.nodes),'FIXTURE_SETUP_ERROR canonical nodes');
 assert.ok(!el('mission-view').hidden,'FIXTURE_SETUP_ERROR mission view');assert.match(el('mission-message-thread').textContent,/同页任务资料/,'FIXTURE_SETUP_ERROR message stream');
 const cards=graphWalk(el('task-list')).filter(item=>item.dataset?.detail).map(item=>item.dataset.detail).sort();
 assert.equal(JSON.stringify(cards),JSON.stringify(state.mission.snapshot.nodes.map(item=>item.id).sort()),'FIXTURE_SETUP_ERROR original task cards');
 assert.equal(calls.filter(call=>call.method!=='GET').length,0,'FIXTURE_SETUP_ERROR unexpected mutation');
 console.log('FIXTURE_READY '+marker+' canonical snapshot + original cards + message-thread; readonly GETs='+calls.length);}
async function graphMount(id=mid,marker='graph'){await selectMission(id);graphReady(id,marker);}
function graphRequired(){assert.ok(graphDeclared['mission-graph']?.tag==='svg','GRAPH_MISSING: no actual same-page SVG declaration');const svg=el('mission-graph');assert.equal(svg.namespaceURI,SVG_NS,'GRAPH_MISSING: actual SVG namespace');return svg;}
function graphNodes(svg=graphRequired()){return graphWalk(svg).filter(item=>item.dataset?.taskId);}
function graphNode(id){const node=graphNodes().find(item=>item.dataset.taskId===id);assert.ok(node,'GRAPH_NODE_MISSING '+id);return node;}
function graphLabel(item){return item.textContent+' '+(item.getAttribute('aria-label')||'');}
function graphCard(id){const card=graphWalk(el('task-list')).find(item=>item.dataset?.detail===id);assert.ok(card,'ORIGINAL_DETAIL_MISSING '+id);return card;}
'''


def _run_js(tmp_path, case):
    markup = _markup()
    assert 'mission-view' in markup and 'mission-message-thread' in markup
    script = PAGE.split('<script nonce="NONCE">', 1)[1].split('</script>', 1)[0]
    script = script.rsplit('render(); resizeComposer();', 1)[0]
    support = _DOM_SUPPORT.replace('GRAPH_MARKUP', json.dumps(markup, ensure_ascii=False))
    harness = HARNESS.replace('SOURCE', json.dumps(support + script)).replace(
        'CASE', json.dumps(_SETUP + case))
    fixture = tmp_path / 'graph-case.js'
    fixture.write_text(harness)
    result = subprocess.run(['node', str(fixture)], capture_output=True, text=True, timeout=15)
    (tmp_path / 'graph-stdout.log').write_text(result.stdout)
    (tmp_path / 'graph-stderr.log').write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr


def test_graph_is_accessible_svg_in_the_same_mission_message_page():
    ids = _markup()
    assert ids['mission-message-thread']['attrs']['role'] == 'log'
    assert 'mission-view' in ids['mission-message-thread']['ancestors']
    print('FIXTURE_READY static original same-page message-thread declaration')
    assert 'mission-graph' in ids, 'GRAPH_MISSING: no actual same-page SVG declaration'
    graph = ids['mission-graph']
    assert graph['tag'] == 'svg' and 'mission-view' in graph['ancestors']
    assert graph['attrs'].get('role') == 'img'
    assert graph['attrs'].get('aria-label') or graph['attrs'].get('aria-labelledby')
    assert 'mission-graph-scroll' in ids and 'mission-graph-scroll' in graph['ancestors']
    assert 'mission-graph-note' in ids
    assert ids['mission-graph-note']['attrs'].get('role') in {'status', 'alert'}
    assert not re.search(r'<iframe\b', PAGE, re.I)
    if graph['attrs'].get('aria-labelledby'):
        assert all(name in ids for name in graph['attrs']['aria-labelledby'].split())


def test_only_exact_canonical_nodes_and_depends_on_edges_are_drawn(tmp_path):
    _run_js(tmp_path, r'''
await graphMount(mid,'exact-edges');const svg=graphRequired();
const actual=graphNodes(svg).map(item=>item.dataset.taskId).sort();
assert.equal(JSON.stringify(actual),JSON.stringify(graphBase.map(item=>item.id).sort()));
const edges=graphWalk(svg).filter(item=>item.dataset?.from!==undefined||item.dataset?.to!==undefined);
const expected=graphBase.flatMap(item=>item.depends_on.map(dep=>dep+'>'+item.id)).sort();
assert.equal(JSON.stringify(edges.map(item=>item.dataset.from+'>'+item.dataset.to).sort()),JSON.stringify(expected));
assert.ok(edges.every(item=>['path','line','polyline'].includes(item.tagName.toLowerCase())),'edges carry exact trace identities');
for(const item of graphWalk(svg).filter(item=>['path','line','polyline'].includes(item.tagName.toLowerCase()))){
 if(item.closest('defs')||item.closest('[data-task-id]'))continue;
 assert.ok(edges.includes(item),'no unlabeled/noncanonical visible dependency edge');}
assert.equal(calls.filter(call=>call.method==='POST').length,0);
''')


def test_native_completion_check_evidence_and_whole_acceptance_stay_distinct(tmp_path):
    _run_js(tmp_path, r'''
const current=graphViews.get(mid);current.snapshot.nodes[1]={...current.snapshot.nodes[1],state:'RUNNING'};
current.snapshot.runs=[{key:'worker:analyse:fixture',task_id:'analyse',role:'worker',status:'COMPLETED',receipt:{status:'COMPLETED',session_id:'fixture-native-record',turn_id:null,exit_code:0,output:'retained protocol fixture, not a native execution',usage:{},error:null,requested_model:'gpt-6.1-sol',actual_model:null}}];
await graphMount(mid,'truth-separation');graphRequired();
assert.match(graphLabel(graphNode('analyse')),/尚未验收|待检查|UNVERIFIED/);
assert.doesNotMatch(graphLabel(graphNode('analyse')),/检查通过|整项.*通过|集成.*通过/);
assert.match(graphLabel(graphNode('root')),/检查通过|固定检查.*通过/);
assert.match(el('progress-thread').textContent,/调用结束不等于验收通过/);
assert.match(el('acceptance-status').textContent,/尚未确认通过验收/);assert.equal(state.mission.snapshot.all_verified,false);
current.snapshot.nodes=current.snapshot.nodes.map(item=>({...item,state:'SUCCEEDED',verdict:'PASS',verification:graphVerification(item.id)}));
current.snapshot.runs=[];current.snapshot.all_verified=true;current.snapshot.project_verified=true;current.snapshot.phase='COMPLETED';
current.snapshot.integration={continuation:{state:'SUCCEEDED'},evidence:{verdict:'PASS',payload:{evidence:{checks:[],review:{verdict:'PASS',reasons:['fixed protocol proof']}}}},current:true,builds:[]};
await readSelected();assert.match(el('acceptance-status').textContent,/核心快照已确认/);graphRequired();
''')


def test_stale_and_superseded_tasks_remain_identifiable_historical_evidence(tmp_path):
    _run_js(tmp_path, r'''
graphViews.get(mid).snapshot.nodes.push(graphTask('legacy',[],{state:'SUCCEEDED',verdict:'PASS',stale:true,active:false,superseded_by:'root',verification:graphVerification('legacy')}));
await graphMount(mid,'historical-stale');graphRequired();const old=graphNode('legacy');
assert.match(graphLabel(old),/过期|stale/i);assert.match(graphLabel(old),/历史|替代|superseded/i);
assert.match(graphLabel(old),/root/);assert.doesNotMatch(graphLabel(old),/当前.*检查通过/);
await graphFire(old,'click');const card=graphCard('legacy');assert.equal(card.open,true);
assert.match(card.textContent,/原固定验收 legacy/);assert.match(card.textContent,/历史|替代|过期/);
assert.equal(state.mission.snapshot.all_verified,false);assert.equal(calls.filter(call=>call.method==='POST').length,0);
''')


def test_mouse_enter_and_space_select_original_details_without_any_io(tmp_path):
    _run_js(tmp_path, r'''
await graphMount(mid,'readonly-selection');graphRequired();const before=calls.length,canonical=JSON.stringify(state.mission.snapshot);
for(const [id,event,key]of [['root','click',undefined],['analyse','keydown','Enter'],['inspect','keydown',' ']]){
 const target=graphNode(id);assert.equal(target.getAttribute('role'),'button');assert.equal(target.getAttribute('tabindex'),'0');
 assert.ok(target.getAttribute('aria-label')||target.getAttribute('aria-labelledby'),'accessible task name');
 target.focus();await graphFire(target,event,key);const card=graphCard(id);assert.equal(card.open,true,'original fixed detail selected');
 assert.match(card.textContent,new RegExp('原固定验收 '+id));assert.match(card.textContent,new RegExp('check-'+id));
 assert.match(card.textContent,new RegExp(id+'\\.txt'));assert.equal(calls.length,before,'selection has no additional fetch or POST');}
assert.equal(JSON.stringify(state.mission.snapshot),canonical,'UI selection never alters fixed controller facts');
''')


def test_mission_switch_and_refresh_replace_graph_and_selection(tmp_path):
    _run_js(tmp_path, r'''
await graphMount(mid,'switch-refresh');graphRequired();await graphFire(graphNode('root'),'click');
await graphMount(other,'switch-second');assert.equal(JSON.stringify(graphNodes().map(item=>item.dataset.taskId)),JSON.stringify(['other-task']));
assert.ok(!graphNodes().some(item=>item.dataset.taskId==='root'),'old mission graph is retired');
graphViews.set(other,graphView(other,[graphTask('fresh-task',[],{objective:'刷新后的固定目标'})],2));
await el('mission-refresh').onclick();graphReady(other,'refresh-new-revision');
assert.equal(state.mission.snapshot.revision,2);assert.equal(JSON.stringify(graphNodes().map(item=>item.dataset.taskId)),JSON.stringify(['fresh-task']));
assert.match(graphLabel(graphNode('fresh-task')),/刷新后的固定目标/);assert.ok(!graphCard('fresh-task').open,'old task selection never migrates');
assert.equal(calls.filter(call=>call.method==='POST').length,0);
''')


def test_late_old_snapshot_never_overwrites_the_new_mission_graph(tmp_path):
    _run_js(tmp_path, r'''
let releaseOld,started=0;const held=new Promise(resolve=>releaseOld=resolve);
graphSnapshotHook=id=>id===mid?(started++,held):graphViews.get(id);
const oldRead=selectMission(mid);for(let n=0;n<8&&!started;n++)await Promise.resolve();
assert.equal(started,1,'FIXTURE_SETUP_ERROR held original snapshot route');
await selectMission(other);releaseOld(graphViews.get(mid));await oldRead;graphReady(other,'late-old-snapshot');
graphRequired();assert.equal(JSON.stringify(graphNodes().map(item=>item.dataset.taskId)),JSON.stringify(['other-task']));
assert.ok(!graphNodes().some(item=>item.dataset.taskId==='root'));assert.equal(calls.filter(call=>call.method==='POST').length,0);
''')


def test_empty_graph_has_an_explicit_non_success_readback(tmp_path):
    _run_js(tmp_path, r'''
graphViews.set(mid,graphView(mid,[]));await graphMount(mid,'empty');graphRequired();
assert.equal(graphNodes().length,0);assert.ok(graphDeclared['mission-graph-note'],'declared graph diagnostic');
assert.match(el('mission-graph-note').textContent,/尚无|没有|未绑定|空图/);
assert.doesNotMatch(el('mission-graph-note').textContent,/验收.*通过|集成.*通过/);assert.equal(state.mission.snapshot.all_verified,false);
''')


@pytest.mark.parametrize('invalid', ['bad-type', 'dangling'])
def test_malformed_or_dangling_dependencies_are_explicit_not_invented(tmp_path, invalid):
    _run_js(tmp_path, r'''
const invalid=INVALID;graphViews.get(mid).snapshot.nodes[1].depends_on=invalid==='bad-type'?'root':['missing-stage'];
await graphMount(mid,'dependency-'+invalid);const svg=graphRequired();
assert.ok(graphDeclared['mission-graph-note']);const note=el('mission-graph-note').textContent;
assert.match(note,/依赖.*(异常|格式|缺失|不存在|悬空)|图.*(异常|无效)/);
if(invalid==='dangling')assert.match(note,/missing-stage/);
assert.ok(!graphNodes(svg).some(item=>item.dataset.taskId==='missing-stage'),'no phantom task');
assert.ok(!graphWalk(svg).some(item=>item.dataset?.from==='missing-stage'||item.dataset?.to==='missing-stage'),'no fabricated edge');
assert.equal(state.mission.snapshot.all_verified,false);assert.equal(calls.filter(call=>call.method==='POST').length,0);
'''.replace('INVALID', json.dumps(invalid)))


def test_untrusted_task_labels_are_literal_clean_text_not_markup(tmp_path):
    _run_js(tmp_path, r'''
globalThis.graphFixtureExecuted=false;
graphViews.get(mid).snapshot.nodes[1].objective='<img src=x onerror="graphFixtureExecuted=true"> literal fixture-access Node '+secret;
await graphMount(mid,'clean-text');const svg=graphRequired();const label=graphLabel(graphNode('analyse'));
assert.match(label,/<img src=x/,'untrusted angle-bracket text remains literal');assert.match(label,/已隐藏凭据/);
assert.ok(!label.includes('fixture-access')&&!label.includes(secret),'clean masks known operator/Node credentials');
assert.equal(globalThis.graphFixtureExecuted,false);assert.ok(!graphWalk(svg).some(item=>['img','image','script','iframe'].includes(item.tagName.toLowerCase())));
assert.ok(graphWalk(svg).every(item=>Object.keys(item.attributes).every(key=>!/^on/i.test(key))));
assert.equal(calls.filter(call=>call.method==='POST').length,0);
''')


def test_narrow_screen_policy_contains_scroll_inside_graph_not_whole_page():
    ids = _markup()
    assert 'mission-view' in ids and 'mission-message-thread' in ids
    assert 'name="viewport"' in PAGE
    print('FIXTURE_READY static viewport/message page; CSS protocol, not layout/device proof')
    assert 'mission-graph-scroll' in ids, 'GRAPH_MISSING: no graph-local scroll region'
    assert 'mission-view' in ids['mission-graph-scroll']['ancestors']
    css = PAGE.split('<style nonce="NONCE">', 1)[1].split('</style>', 1)[0]
    classes = ids['mission-graph-scroll']['attrs'].get('class', '').split()
    selectors = {'#mission-graph-scroll', *('.' + name for name in classes)}
    declarations = {}
    for group, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        if selectors.intersection(part.strip() for part in group.split(',')):
            for declaration in body.split(';'):
                if ':' in declaration:
                    key, value = declaration.split(':', 1)
                    declarations[key.strip()] = value.strip()
    assert declarations.get('overflow-x', declarations.get('overflow')) in {'auto', 'scroll'}
    assert declarations.get('max-width') == '100%'
    assert declarations.get('min-width') in {'0', '0px'}
    assert '.workspace{min-width:0' in css, 'existing page flex containment retained'
