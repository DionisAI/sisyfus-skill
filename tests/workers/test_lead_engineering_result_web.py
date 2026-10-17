"""Frozen W01-W14: header-opted same-capture web consumer, not device acceptance.

No inherited helpers, producer interfaces, production functions or truth are
rewritten. Real HTTP uses an isolated Hub + the original real-store Stub surface;
page protocol cases evaluate the shipped script in the unchanged old VM harness.
The sole outcome requires the exclusive runner, Main gate and retained guard.
"""
from __future__ import annotations

import builtins
import copy
import http.client
import importlib
import json
import os
from pathlib import Path
import re
import sys
import threading

import pytest

from sisyfus.workers.lead_chat_page import PAGE
from sisyfus.workers.lead_console import LeadConsole, MissionHub
from test_lead_console import StubMission, make_spec
from test_lead_result import (_envelope, _node, _data, _assert_closed_schema,
                              _pure_traps, SHA_A, SHA_B, SHA_C, SHA_D, SHA_E, SHA_F)
from test_chat_node_placement_page import HARNESS
from test_mission_graph_page import _DOM_SUPPORT, _SETUP, _markup

REPO = Path(__file__).resolve().parents[2]
PROOF = REPO/'artifacts/techlead/frozen-test-corrections-20261013/web-guard-v2'
HEADER = 'X-Sisyfus-Engineering-Result'
SIDECAR_SCHEMA = 'sisyfus.lead_console.engineering_result_sidecar.v1'
SIDE_KEYS = {'schema','mission_id','status','result','error'}
BASE_KEYS = {'id','snapshot','controller','controls'}
MID = 'm_'+'1'*32
OTHER = 'm_'+'2'*32


def _guard():
    module = sys.modules.get('web_guard')
    assert module is not None and module.INSTALLED, 'exclusive Main-gated retained runner is required'
    assert Path(module.__file__).resolve() == PROOF/'web_guard.py'
    return module


def _public():
    return importlib.import_module('sisyfus.workers.lead_result')


def _project(value):
    public = _public()
    with _pure_traps():
        result = public.project_engineering_result(value)
    _assert_closed_schema(result)
    return result


def _typed(ident=MID, *, mode='integrated'):
    value = _envelope(integrated=True)
    value['id'] = ident
    if mode == 'historical':
        value['snapshot']['integration']['current'] = False
        value['snapshot']['all_verified'] = value['snapshot']['project_verified'] = False
        value['snapshot']['phase'] = 'INTEGRATING'
    if mode == 'conflict':
        _data(value)['checks'][0]['candidate_hash'] = SHA_E
    return value


def _side(value):
    return {'schema':SIDECAR_SCHEMA,'mission_id':value['id'],'status':'OK',
            'result':_project(value),'error':None}


def _wire(ident=MID, *, mode='integrated'):
    value = _typed(ident, mode=mode)
    value['engineering_result'] = _side(value)
    return value


def _resolve(value, pointer):
    for segment in pointer.removeprefix('/').split('/'):
        key = segment.replace('~1','/').replace('~0','~')
        value = value[int(key)] if type(value) is list else value[key]
    return value


def _walk(value):
    yield value
    if type(value) is dict:
        for item in value.values():
            yield from _walk(item)
    elif type(value) is list:
        for item in value:
            yield from _walk(item)


# Literal R08 primitives from the frozen S0 contract, not a production alias.
def _literal_r08(text):
    if re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY", text): return None
    for pattern,replacement in ((r"\bsk-[A-Za-z0-9_-]{12,}","[REDACTED]"),
        (r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+","Bearer [REDACTED]"),
        (r"\bAKIA[0-9A-Z]{16}\b","[REDACTED]"),(r"\bgh[pousr]_[A-Za-z0-9]{36,}","[REDACTED]"),
        (r"\bxox[abprs]-[A-Za-z0-9-]{10,}","[REDACTED]"),
        (r"(?i)\b(api[_-]?key|password|passwd|secret|token)(\s*[:=]\s*)\S+",r"\1\2[REDACTED]")):
        text=re.sub(pattern,replacement,text)
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]", "\ufffd",text)


def _calibrate(value):
    result = value['engineering_result']['result']
    _assert_closed_schema(result)
    assert result['question']['objective']['value'] == _literal_r08(value['snapshot']['objective'])
    assert result['provenance']['capture_basis'] == 'CALLER_CAPTURED_NON_ATOMIC'
    assert result['provenance']['projection_is_acceptance'] is False
    task = result['tasks'][0]
    assert 'title' not in value['snapshot']['nodes'][0]
    raw=value['snapshot']['nodes'][0]; recorded=raw['verification']['evidence']
    assert task['objective']['value'] == raw['objective']
    assert task['deliverable']['candidate_hash']['value'] == recorded['candidate_hash']
    assert task['deliverable']['patch']['row_count'] == len(recorded['patch'])
    assert len(task['checks']) == len(recorded['checks'])
    assert [reason['value'] for reason in task['review']['reasons']] == recorded['review']['reasons']
    assert [ref['value'] for ref in task['review']['evidence_refs']] == recorded['review']['evidence']
    assert all(type(scalar['value']) in (int,float,bool) for check in task['checks'] for scalar in check['measurement']['scalars'])
    for fact in _walk(result):
        if type(fact) is dict and {'state','value','source'} <= fact.keys() and fact['state']=='RECORDED':
            assert _resolve(value, fact['source']) == fact['value']
    return result


class _HTTP:
    def __init__(self, server, hub, mission, trace):
        self.server, self.hub, self.mission, self.trace = server, hub, mission, trace

    def get(self, path=None, *, headers=(), token=True, host=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            connection.putrequest('GET', path or '/api/snapshot?mission_id='+self.ident, skip_host=True)
            connection.putheader('Host', host or '127.0.0.1:'+str(self.server.server_port))
            if token:
                connection.putheader('Authorization','Bearer '+self.server.token)
            for name,value in headers:
                connection.putheader(name,value)
            connection.endheaders()
            response = connection.getresponse()
            raw = response.read()
            return response.status, dict(response.getheaders()), raw
        finally:
            connection.close()

    def opted(self):
        status, headers, raw = self.get(headers=[(HEADER,'1')])
        return status, headers, json.loads(raw)


@pytest.fixture
def http_fixture(tmp_path, monkeypatch):
    guard = _guard()
    assert os.environ.get('SISYFUS_TEST_LOOPBACK') == '1', 'loopback outcome needs scoped Main approval'
    assert not any(key in os.environ for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','CODEX_HOME','CLAUDE_CONFIG_DIR')), 'fixture launcher must exclude provider credentials'

    class TypedMission(StubMission):
        created = []
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self.captured = _typed()
            self.snapshot_calls = 0
        def snapshot(self):
            self.snapshot_calls += 1
            return copy.deepcopy(self.captured['snapshot'])
        def run(self,*args,**kwargs):
            raise AssertionError('WEB_GET_DISPATCHED_A_WORKER')

    hub = MissionHub(tmp_path/'hub', mission_factory=TypedMission)
    ident = hub.create(make_spec(tmp_path))['id']
    mission = hub._session(ident).mission
    mission.snapshot_calls = 0  # hub.create() legitimately captured one summary snapshot.
    trace = []
    original = hub.snapshot
    def capture(selected):
        result = original(selected)
        trace.append({'object':result,'bytes':json.dumps(result,ensure_ascii=False,allow_nan=False)})
        return result
    monkeypatch.setattr(hub,'snapshot',capture)  # Delegate genuine public capture, not fake output.
    entered = threading.Event()
    class OwnedConsole(LeadConsole):
        def service_actions(self):
            super().service_actions()
            entered.set()
    guard.arm_bind(True)
    try:
        server = OwnedConsole(hub,port=0)
        guard.register_port(server.server_port)
    finally:
        guard.arm_bind(False)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval':0.01},daemon=True)
    thread.start()
    assert entered.wait(2), 'owned listener must enter stdlib loop before cleanup'
    value = _HTTP(server,hub,mission,trace); value.ident = ident
    try:
        yield value
        assert mission.calls == 0 and not mission.started.is_set(), 'read-only route dispatched native work'
        assert hub.controls(ident) == [], 'read-only route changed controller permissions'
    finally:
        server.shutdown(); server.server_close(); thread.join(2)
        guard.drop_port(server.server_port)
        hub.close()
        assert not thread.is_alive(), 'owned HTTP listener not drained'


def _spy_project(monkeypatch):
    public = _public(); original = public.project_engineering_result
    trace = []
    def observed(value):
        before = json.dumps(value,ensure_ascii=False,allow_nan=False)
        with _pure_traps():
            result = original(value)
        trace.append({'object':value,'before':before,'after':json.dumps(value,ensure_ascii=False,allow_nan=False),'result':copy.deepcopy(result)})
        return result
    monkeypatch.setattr(public,'project_engineering_result',observed)
    return trace


def _assert_side(body, ident, status, code=None):
    assert set(body) == BASE_KEYS|{'engineering_result'}
    side = body['engineering_result']; assert set(side)==SIDE_KEYS
    assert side['schema']==SIDECAR_SCHEMA and side['mission_id']==ident and side['status']==status
    if status=='OK':
        assert type(side['result']) is dict and side['error'] is None
        _assert_closed_schema(side['result'])
    else:
        assert side['result'] is None and side['error']=={'code':code}
        assert re.fullmatch(r'[A-Z][A-Z0-9_]{0,31}',code)


def test_w01_default_exact_four_no_projection_or_import(http_fixture, monkeypatch):
    public = sys.modules.get('sisyfus.workers.lead_result')
    def blocked(*args,**kwargs):
        raise AssertionError('DEFAULT_SNAPSHOT_TOUCHED_S0')
    if public is not None:
        monkeypatch.setattr(public,'project_engineering_result',blocked)
    original_import = builtins.__import__; original_dynamic = importlib.import_module
    def guarded_import(name,*args,**kwargs):
        if name in {'sisyfus.workers.lead_result','lead_result'} or 'lead_result' in kwargs.get('fromlist',()) or len(args)>2 and 'lead_result' in (args[2] or ()):
            blocked()
        return original_import(name,*args,**kwargs)
    def guarded_dynamic(name,*args,**kwargs):
        if name.endswith('lead_result'): blocked()
        return original_dynamic(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',guarded_import)
    monkeypatch.setattr(importlib,'import_module',guarded_dynamic)
    status, headers, raw = http_fixture.get()
    assert status==200 and set(json.loads(raw))==BASE_KEYS
    assert len(http_fixture.trace)==1 and http_fixture.mission.snapshot_calls==1
    assert json.loads(raw)==http_fixture.trace[0]['object']
    assert headers['Cache-Control']=='no-store' and headers['X-Content-Type-Options']=='nosniff'


def test_w02_opted_once_exact_capture_pointer_root(http_fixture, monkeypatch):
    http_fixture.mission.captured['snapshot']['objective']='upstream fixture Bearer synthetic-upstream-marker'
    trace = _spy_project(monkeypatch)
    status, _, body = http_fixture.opted()
    assert status==200; _assert_side(body,http_fixture.ident,'OK')
    assert len(http_fixture.trace)==len(trace)==http_fixture.mission.snapshot_calls==1
    assert trace[0]['object'] is http_fixture.trace[0]['object']
    assert trace[0]['before']==trace[0]['after']==http_fixture.trace[0]['bytes']
    cap = {key:body[key] for key in BASE_KEYS}
    assert cap==trace[0]['object']
    assert cap['snapshot']['objective']=='upstream fixture Bearer [REDACTED]'
    assert cap['snapshot']['objective']!=http_fixture.mission.captured['snapshot']['objective']
    result=body['engineering_result']['result']; assert result==trace[0]['result']
    for fact in _walk(result):
        if type(fact) is dict and {'state','value','source'} <= fact.keys() and fact['state']=='RECORDED':
            assert _resolve(body,fact['source'])==fact['value']
    assert result['tasks'][0]['deliverable']['patch']['rows'][0]['source'].startswith('/snapshot/nodes/0/')


@pytest.mark.parametrize('case',['empty','zero','duplicate','host','origin','auth','node','query'])
def test_w03_header_security_query_admission_and_other_route(http_fixture, case):
    headers=[(HEADER,'1')]; kwargs={}; expected=400
    if case=='empty': headers=[(HEADER,'')]
    if case=='zero': headers=[(HEADER,'0')]
    if case=='duplicate': headers=[(HEADER,'1'),(HEADER,'1')]
    if case=='host': kwargs['host']='wrong.example'; expected=403; headers=[(HEADER,'0')]
    if case=='origin': headers += [('Origin','https://wrong.example')]; expected=403
    if case=='auth': kwargs['token']=False; expected=401
    if case=='node': headers += [('X-Sisyfus-Node','synthetic-identity')]; expected=403
    if case=='query': kwargs['path']='/api/snapshot?mission_id='+http_fixture.ident+'&engineering_result=1'
    status,_,raw=http_fixture.get(headers=headers,**kwargs)
    assert status==expected and 'error' in json.loads(raw)
    assert http_fixture.trace==[] and http_fixture.mission.snapshot_calls==0
    # Unknown opt-in is inert on another existing route; no snapshot query alias.
    status,_,raw=http_fixture.get('/api/missions',headers=[(HEADER,'0'),(HEADER,'1')])
    assert status==200 and 'missions' in json.loads(raw) and http_fixture.trace==[]


@pytest.mark.parametrize('shape',['missing','wrong-type'])
def test_w04_genuine_public_typed_rejection(http_fixture, shape):
    snap=http_fixture.mission.captured['snapshot']
    if shape=='missing': del snap['runs']
    else: snap['runs']={}
    cap=copy.deepcopy(http_fixture.mission.captured)
    with pytest.raises(_public().EngineeringResultInputError) as found:
        _project(cap)
    assert type(found.value) is _public().EngineeringResultInputError
    assert found.value.code=='SNAPSHOT_REQUIRED_FIELD'
    status,_,body=http_fixture.opted(); assert status==200
    _assert_side(body,http_fixture.ident,'REJECTED','SNAPSHOT_REQUIRED_FIELD')
    assert len(http_fixture.trace)==http_fixture.mission.snapshot_calls==1
    assert {key:body[key] for key in BASE_KEYS}==http_fixture.trace[0]['object']


@pytest.mark.parametrize('fault',['absent','bad-id','internal','base-exception'])
def test_w05_capture_errors_internal_failure_and_base_exception(http_fixture, monkeypatch, fault):
    if fault in {'absent','bad-id'}:
        ident='m_'+'f'*32 if fault=='absent' else '../synthetic'
        status,_,raw=http_fixture.get('/api/snapshot?mission_id='+ident,headers=[(HEADER,'1')])
        assert status==(404 if fault=='absent' else 400)
        assert set(json.loads(raw))=={'error'} and http_fixture.trace==[]
        return
    public=_public(); reached=threading.Event(); uncaught=threading.Event(); observed=[]
    def fail(value):
        reached.set()
        if fault=='base-exception': raise KeyboardInterrupt('SYNTHETIC_PRIVATE_BASE_EXCEPTION')
        raise RuntimeError('SYNTHETIC_PRIVATE_ERROR_TYPE '+http_fixture.server.token)
    monkeypatch.setattr(public,'project_engineering_result',fail)
    if fault=='base-exception':
        def hook(args):
            observed.append(type(args.exc_value)); uncaught.set()
        monkeypatch.setattr(threading,'excepthook',hook)
        with pytest.raises(http.client.RemoteDisconnected): http_fixture.opted()
        assert reached.wait(1) and uncaught.wait(1) and observed==[KeyboardInterrupt]
    else:
        status,_,body=http_fixture.opted(); assert reached.wait(1) and status==200
        _assert_side(body,http_fixture.ident,'FAILED','PROJECTION_INTERNAL_ERROR')
        encoded=json.dumps(body['engineering_result'])
        assert 'SYNTHETIC_PRIVATE' not in encoded and http_fixture.server.token not in encoded


@pytest.mark.parametrize('predicate',['redact-changes','literal-token','already-redacted'])
def test_w06_real_sidecar_secrecy_predicate_not_full_wrapper(http_fixture, monkeypatch, predicate):
    from sisyfus.workers.protocol import redact
    objective='guard-projection-predicate-fixture'
    if predicate=='redact-changes':
        # Entire finished Q01 is a synthetic slot value; raw objective is not.
        monkeypatch.setenv('OPENAI_API_KEY','目标问题：'+objective+'。')
    elif predicate=='literal-token': objective += ' '+http_fixture.server.token
    else: objective='[REDACTED]'
    http_fixture.mission.captured['snapshot']['objective']=objective
    calibrated=_project(http_fixture.mission.captured)
    if predicate=='redact-changes': assert redact(calibrated)!=calibrated
    if predicate=='literal-token': assert http_fixture.server.token in json.dumps(calibrated,ensure_ascii=False)
    if predicate=='already-redacted': assert redact(calibrated)==calibrated
    status,_,body=http_fixture.opted(); assert status==200
    if predicate=='already-redacted': _assert_side(body,http_fixture.ident,'OK')
    else:
        _assert_side(body,http_fixture.ident,'FAILED','REDACTION_ALTERED')
        assert http_fixture.server.token not in json.dumps(body['engineering_result'])
    assert {k:body[k] for k in BASE_KEYS}==http_fixture.trace[0]['object']
    if predicate=='literal-token': assert http_fixture.server.token in body['snapshot']['objective']


_VM = r'''
const webFixtures=WEB_FIXTURES;
for(const [id,value] of Object.entries(webFixtures))graphViews.set(id,value);
// Link only elements declared by the real HTML, using its nearest declared
// ancestor. This adds standard parentage, never missing result markup.
for(const [id,definition] of Object.entries(graphDeclared)){
 const parent=[...definition.ancestors].reverse().find(name=>graphDeclared[name]);
 if(parent&&!el(parent).contains(el(id)))el(parent).append(el(id));
}
function webRequired(){for(const id of ['engineeringResult','engineeringResultStatus','engineeringResultBody'])
 assert.ok(graphDeclared[id],'WEB_RESULT_MISSING actual HTML '+id);return el('engineeringResultBody');}
function webText(){return webRequired().textContent;}
function webStatus(pattern){webRequired();assert.match(el('engineeringResultStatus').textContent,pattern);}
function webNoMutation(){assert.equal(calls.filter(c=>c.method!=='GET').length,0);assert.equal(el('mission-permission').checked,false);}
function webCore(id=mid){assert.equal(state.id,id);assert.equal(JSON.stringify(state.mission.snapshot),JSON.stringify(graphViews.get(id).snapshot));
 assert.match(el('mission-message-thread').textContent,/同页任务资料/);assert.equal(state.loadError,'');webNoMutation();}
function webPositive(){webRequired();assert.match(webText(),/Implement an isolated fixture/);assert.match(webText(),/Implement the fixture delta/);
 assert.match(webText(),/Reviewer inspected fixture receipts/);assert.ok(graphWalk(webRequired()).some(x=>x.tagName.toLowerCase()==='details'),'progressive disclosure');}
function webNoPositive(){assert.ok(!webText().includes('Reviewer inspected fixture receipts'),'old positive result cleared');}
function webReceipt(marker){console.log('WEB_FIXTURE_READY '+marker+' actual shipped script / real public S0 data / original Core cards and inbox');}
async function webMount(marker){await graphMount(mid,marker);webCore();webReceipt(marker);webRequired();}
function webDeferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
async function webStarted(count,read){for(let step=0;step<40&&read()<count;step++)await Promise.resolve();assert.equal(read(),count,'fixture deferred request reached');}
'''


def _run_vm(tmp_path, case, *, fixtures=None, marker='web'):
    _guard()
    markup=_markup()
    assert 'mission-view' in markup and markup['mission-message-thread']['attrs']['role']=='log'
    values=fixtures if fixtures is not None else {MID:_wire(),OTHER:_wire(OTHER)}
    for value in values.values():
        if value.get('engineering_result',{}).get('status')=='OK': _calibrate(value)
    script=PAGE.split('<script nonce="NONCE">',1)[1].split('</script>',1)[0]
    script=script.rsplit('render(); resizeComposer();',1)[0]
    support=_DOM_SUPPORT.replace('GRAPH_MARKUP',json.dumps(markup,ensure_ascii=False))
    body=_SETUP+_VM.replace('WEB_FIXTURES',json.dumps(values,ensure_ascii=False))+case
    body += '\nwebNoMutation();console.log('+json.dumps('WEB_CASE_FINISHED '+marker)+');'
    payload=HARNESS.replace('SOURCE',json.dumps(support+script)).replace('CASE',json.dumps(body))
    directory=tmp_path/'node'; directory.mkdir()
    _guard().run_node(directory,payload,marker)


@pytest.mark.parametrize('outer',['missing','present'])
def test_w07_legacy_sparse_view_is_not_fabricated_s0(tmp_path, outer):
    # Reuse exactly the sparse original graph wire; no normalization to S0.
    _run_vm(tmp_path, r'''
const legacy=graphView(mid,graphBase);if(OUTER==='missing')delete legacy.id;
graphViews.set(mid,legacy);await webMount('legacy');webStatus(/MISSING|未提供|暂无.*工程结果|工程结果.*缺失/);
assert.ok(!webText().includes('Reviewer inspected fixture receipts'));assert.equal(state.mission.snapshot.resume_epoch,undefined);
const reads=calls.filter(c=>c.path.startsWith('/api/snapshot?'));assert.equal(reads.length,1);
assert.equal(reads[0].options.headers['X-Sisyfus-Engineering-Result'],'1');
assert.ok(!calls.some(c=>/engineering.result|lead.result/i.test(c.path)));
'''.replace('OUTER',json.dumps(outer)),fixtures={},marker='legacy-'+outer)


@pytest.mark.parametrize('invalid',['outer-missing','outer-wrong','side-id','side-schema','side-extra','status','error','groups','provenance','nested-shape','oversize','rejected','failed'])
def test_w08_identity_and_closed_sidecar_admission(tmp_path, invalid):
    _run_vm(tmp_path,r'''
await webMount('admission-calibration');webPositive();const prior=JSON.stringify(state.mission);
const changed=JSON.parse(JSON.stringify(graphViews.get(mid)));changed.snapshot.reason='new valid Core marker';const side=changed.engineering_result;
if(INVALID==='outer-missing')delete changed.id;if(INVALID==='outer-wrong')changed.id=other;
if(INVALID==='side-id')side.mission_id=other;if(INVALID==='side-schema')side.schema='wrong.schema';if(INVALID==='side-extra')side.extra=true;
if(INVALID==='status')side.status='PASS';if(INVALID==='error')side.error={code:'bad code',message:'PRIVATE'};
if(INVALID==='groups')side.result.new_group=true;
if(INVALID==='nested-shape')side.result.tasks[0].checks={};
if(INVALID==='oversize')side.result.tasks=Array.from({length:257},()=>side.result.tasks[0]);
if(INVALID==='rejected'||INVALID==='failed'){side.status=INVALID.toUpperCase();side.result=null;side.error={code:INVALID==='rejected'?'SNAPSHOT_REQUIRED_FIELD':'PROJECTION_INTERNAL_ERROR'};}
if(INVALID==='provenance'){side.result.provenance.projection_is_acceptance=true;side.result.provenance.captured_at='invented';}
graphViews.set(mid,changed);await readSelected();
if(INVALID.startsWith('outer-')){assert.equal(JSON.stringify(state.mission),prior,'foreign or unidentified Core not assigned');assert.ok(state.loadError);}
else{webCore();webNoPositive();webStatus(/INVALID|REJECTED|FAILED|格式|异常|无效|拒绝|失败/);}
'''.replace('INVALID',json.dumps(invalid)),marker='admission-'+invalid)


@pytest.mark.parametrize('race',['newer-before-older','switch-a-b-a','network-error'])
def test_w09_complete_deferred_order_switch_and_stale(tmp_path, race):
    fresh=_typed(); fresh['snapshot']['reason']='newest-capture-marker'
    fresh['engineering_result']=_side(fresh)
    _run_vm(tmp_path,r'''
await webMount('race-calibration');webPositive();
const original=JSON.parse(JSON.stringify(graphViews.get(mid)));let started=0;const held=webDeferred();
graphSnapshotHook=id=>{if(id===mid&&started++===0)return held.promise;return graphViews.get(id);};
const pending=readSelected();await webStarted(1,()=>started);
if(RACE==='network-error'){
 held.reject(Error('synthetic offline'));await pending;webStatus(/STALE|过期|上次.*(记录|结果)|旧.*(记录|结果)/);webPositive();assert.ok(state.loadError);
 graphSnapshotHook=null;await readSelected();webCore();webPositive();assert.ok(!/STALE|上次|过期/.test(el('engineeringResultStatus').textContent));
}else{
 if(RACE==='switch-a-b-a'){
  const b=webDeferred();let bStarted=0;graphSnapshotHook=id=>id===other?(bStarted++,b.promise):graphViews.get(id);
  const switchRead=selectMission(other);await webStarted(1,()=>bStarted);
  assert.equal(state.id,other);webNoPositive();b.resolve(graphViews.get(other));await switchRead;
  await selectMission(mid);
 }else{
  graphViews.set(mid,FRESH);await readSelected();
 }
 const accepted=JSON.stringify(state.mission),rendered=webText();held.resolve(original);await pending;
 assert.equal(JSON.stringify(state.mission),accepted);assert.equal(webText(),rendered);webCore();webPositive();
}
console.log('WEB_ALL_DEFERRED_PROMISES_COMPLETED');
'''.replace('RACE',json.dumps(race)).replace('FRESH',json.dumps(fresh,ensure_ascii=False)),marker='race-'+race)


def test_w10_same_revision_counts_content_changes_repaint(tmp_path):
    first=_wire(); changed=_typed()
    data=_data(changed); data['patch']['modified.txt']['after']=SHA_F
    data['checks'][0]['measurement']['score']=0.75
    data['review']['reasons']=['Reviewer revised meaningful fixture rationale']
    second={**changed,'engineering_result':_side(changed)}
    assert first['snapshot']['revision']==second['snapshot']['revision']
    assert len(first['engineering_result']['result']['conclusion']['statements'])==len(second['engineering_result']['result']['conclusion']['statements'])
    _run_vm(tmp_path,r'''
await webMount('content-calibration');webPositive();const old=webText();
graphViews.set(mid,SECOND);await readSelected();webCore();
assert.notEqual(webText(),old);assert.match(webText(),/0\.75/);assert.match(webText(),/Reviewer revised meaningful fixture rationale/);
assert.ok(webText().includes(NEW_HASH),'expanded evidence retains changed full hash');
'''.replace('SECOND',json.dumps(second,ensure_ascii=False)).replace('NEW_HASH',json.dumps(SHA_F)),marker='content')


@pytest.mark.parametrize('mode',['integrated','historical','conflict'])
def test_w11_human_question_conclusion_concrete_evidence(tmp_path, mode):
    value=_wire(mode=mode); result=_calibrate(value)
    expected={'integrated':'PROJECT_VERIFIED_AS_CAPTURED','historical':'CANDIDATES_RECORDED','conflict':'CAPTURE_CONFLICT'}
    # Historical task evidence can remain recorded: derive its selected conclusion
    # from fixed control/task stages, rather than forcing raw integration PASS.
    if mode=='historical':
        assert result['integration']['stage']=='HISTORICAL_RESULT'
        assert result['conclusion']['stage']=='TASK_EVIDENCE_RECORDED_INTEGRATION_PENDING'
    else: assert result['conclusion']['stage']==expected[mode]
    statements=result['conclusion']['statements']
    assert statements[0]=={'template_id':'Q01','text':'目标问题：Implement an isolated fixture。','sources':['/snapshot/objective']}
    _run_vm(tmp_path,r'''
await webMount('human-evidence');webPositive();const text=webText();
for(const literal of ['added.txt','modified.txt','removed.txt','unit','execution.exit_code','execution.timed_out','0','false','check:unit'])assert.ok(text.includes(literal),'meaningful evidence '+literal);
for(const hash of HASHES)assert.ok(text.includes(hash),'expanded full recorded hash');
assert.match(text,/非原子|NON_ATOMIC/);assert.match(text,/不是验收|不表示.*验收|NOT_ACCEPTANCE/);
assert.ok(!text.trim().startsWith('{'),'not a raw JSON-only answer');
const statement=EXPECTED_STATEMENT;assert.ok(text.includes(statement),'recorded conclusion, not transport PASS');
assert.ok(!text.includes('/private/fixture/candidate-withheld'),'absolute location withheld');webCore();
'''.replace('HASHES',json.dumps([SHA_A,SHA_B,SHA_C,SHA_D,SHA_E])).replace('EXPECTED_STATEMENT',json.dumps(statements[1]['text'],ensure_ascii=False)),fixtures={MID:value,OTHER:_wire(OTHER)},marker='human-'+mode)


@pytest.mark.parametrize('case',['budgets','text-data','csp'])
def test_w12_bounded_text_only_security_and_wire_csp(tmp_path, request, case):
    if case=='csp':
        h=request.getfixturevalue('http_fixture'); status,headers,raw=h.get('/',token=False)
        assert status==200 and 'text/html' in headers['Content-Type']
        csp=headers['Content-Security-Policy']
        for literal in ("default-src 'none'","connect-src 'self'","object-src 'none'","frame-ancestors 'none'","base-uri 'none'"):
            assert literal in csp
        assert re.search(r"script-src 'nonce-[A-Za-z0-9_-]+'",csp)
        assert headers['Cache-Control']=='no-store'; assert b'engineeringResult' in raw
        return
    if case=='text-data':
        value=_typed(); value['snapshot']['objective']='Synthetic password: synthetic-noncredential-suffix ; Literal <img src=x onerror="webExecuted=true"> & 公开问题'
        data=_data(value); data['patch']['folder~name/<literal>.txt']={'before':None,'after':SHA_F}
        data['checks'][0]['measurement']['ratio.value']=0
        value['engineering_result']=_side(value)
        assert value['engineering_result']['result']['question']['objective']['value']==_literal_r08(value['snapshot']['objective'])
        _run_vm(tmp_path,r'''
globalThis.webExecuted=false;await webMount('text-data');const root=webRequired();
assert.ok(webText().includes('<img src=x onerror="webExecuted=true">'));
assert.ok(webText().includes('password: [REDACTED]'));assert.ok(!el('engineeringResult').textContent.includes('synthetic-noncredential-suffix'));
assert.ok(webText().includes('folder~name/<literal>.txt'));assert.ok(webText().includes('ratio.value'));
assert.equal(globalThis.webExecuted,false);assert.ok(!graphWalk(root).some(x=>['img','script','iframe'].includes(x.tagName.toLowerCase())));
assert.ok(!graphWalk(root).some(x=>Object.keys(x.attributes).some(k=>/^(?:on|href$|src$)/i.test(k))));
assert.ok(webText().includes('folder~0name~1<literal>.txt'),'RFC6901 pointer is data, not a link or normalized path');
const saved=[...storage.values()].join('\n');assert.ok(!saved.includes('ratio.value')&&!saved.includes('<literal>.txt'),'result not persisted in Storage');
''',fixtures={MID:value,OTHER:_wire(OTHER)},marker='text-data')
        return
    value=_typed(); snapshot=value['snapshot']; data=_data(value)
    data['patch']={f'bounded-patch-{n:03}.txt':{'before':None,'after':SHA_B} for n in range(41)}
    data['checks']=[copy.deepcopy(data['checks'][0]) for _ in range(25)]
    for n,check in enumerate(data['checks']):
        check['id']=f'check:bounded-{n:03}'; check['check']=f'bounded-check-{n:03}'
        check['measurement']={f'bounded-scalar-{i:03}':i for i in range(17)}
        check['measurement']['password']=1234  # Synthetic denied root; no credential value.
    data['check_hashes']={c['check']:SHA_F for c in data['checks']}
    snapshot['nodes'][0]['check']=data['checks'][0]['check']
    data['review']['evidence']=[c['id'] for c in data['checks']]
    data['review']['reasons']=[f'bounded-review-{i:03}' for i in range(13)]
    snapshot['nodes'] += [_node('bounded-task-'+str(i),verified=False) for i in range(64)]
    # Genuine public result includes >200 statements and >50 diagnostics within
    # its existing caps; no hand-written fake OK sidecar or 300-task input.
    for node in snapshot['nodes'][1:]: node['attempts']='malformed-but-recorded-fixture'
    snapshot['runs'] += [{'status':'malformed-but-recorded-fixture'} for _ in range(64)]  # Non-task (attempt) diagnostics.
    value['engineering_result']=_side(value)
    result=value['engineering_result']['result']
    assert len(result['tasks'])==65 and len(result['tasks'][0]['deliverable']['patch']['rows'])==41
    assert len(result['tasks'][0]['checks'])==25 and len(result['tasks'][0]['checks'][0]['measurement']['scalars'])==17
    assert len(result['tasks'][0]['review']['reasons'])==13
    assert result['tasks'][0]['checks'][0]['measurement']['withheld_count']==1
    assert len(result['conclusion']['statements'])>200 and len(result['diagnostics'])>50
    _run_vm(tmp_path,r'''
await webMount('bounded');const root=webRequired(),text=webText();
assert.ok(graphWalk(root).length<=3000,'total newly created result DOM nodes bounded');
assert.match(el('engineeringResult').textContent,/截断|省略|未显示|有界/,'explicit render truncation');
assert.match(el('engineeringResult').textContent,/withheld|隐藏|过滤|未输出/i,'honest source withheld counter');
assert.ok(text.includes('bounded-patch-000.txt')&&text.includes('bounded-check-000')&&text.includes('bounded-review-000'),'bounded concrete evidence still meaningful');
// Count distinct displayed record labels (including any duplicate prose); a raw
// second JSON wall must not bypass the selected display caps.
for(const [prefix,limit]of [['bounded-task-',63],['bounded-patch-',40],['bounded-check-',24],['bounded-scalar-',16],['bounded-review-',12]]){
 const matches=new Set([...text.matchAll(new RegExp(prefix+'[0-9]+','g'))].map(m=>m[0]));assert.ok(matches.size<=limit,'selected render cap '+prefix);}
assert.equal(state.mission.snapshot.nodes.length,65,'Core graph not cropped with optional result');
webCore();
''',fixtures={MID:value,OTHER:_wire(OTHER)},marker='budgets')


@pytest.mark.parametrize('after',[1,3])
def test_w13_result_local_standard_dom_failure_and_identical_retry(tmp_path, after):
    changed=_typed(); changed['snapshot']['reason']='force new same-capture result'
    changed['engineering_result']=_side(changed)
    _run_vm(tmp_path,r'''
await webMount('healthy-before-fault');webPositive();const previous=webText(),beforePosts=calls.filter(x=>x.method==='POST').length;
const originalCreate=document.createElement.bind(document),originalGet=document.getElementById.bind(document);
let armed=true,inside=false,created=0,faults=0;
document.getElementById=id=>{if(armed&&id==='engineeringResultBody')inside=true;return originalGet(id);};
document.createElement=tag=>{if(armed&&inside&&++created>=AFTER){faults++;throw Error('PRIVATE_RESULT_RENDER fixture-access <img src=x>');}return originalCreate(tag);};
graphViews.set(mid,CHANGED);
const pending=readSelected();await pending;assert.ok(faults>0,'controlled standard DOM exception reached');
webCore();webNoPositive();webStatus(/RENDER|渲染|展示.*(异常|失败)|结果.*(异常|失败)/);
assert.ok(!el('engineeringResult').textContent.includes('PRIVATE_RESULT_RENDER')&&!el('engineeringResult').textContent.includes('fixture-access'));
assert.equal(calls.filter(x=>x.method==='POST').length,beforePosts);
armed=false;inside=false;await readSelected();webCore();webPositive();assert.ok(webText().includes('Reviewer inspected fixture receipts'));
console.log('WEB_IDENTICAL_PAYLOAD_RECOVERED');
'''.replace('AFTER',str(after)).replace('CHANGED',json.dumps(changed,ensure_ascii=False)),marker='render-fault-'+str(after))


def test_w14_actual_markup_accessibility_ime_disclosure_and_authority(tmp_path):
    ids=_markup()
    for ident in ('engineeringResult','engineeringResultStatus','engineeringResultBody'):
        assert ident in ids, 'WEB_RESULT_MISSING actual HTML '+ident
        assert 'mission-view' in ids[ident]['ancestors']
    status=ids['engineeringResultStatus']['attrs']
    assert status.get('role')=='status' and status.get('aria-live','polite')=='polite'
    assert 'prefers-reduced-motion' in PAGE and 'viewport-fit=cover' in PAGE
    _run_vm(tmp_path,r'''
await webMount('accessible');webPositive();const details=graphWalk(webRequired()).filter(x=>x.tagName.toLowerCase()==='details');
assert.ok(details.length&&details.every(d=>d.children.some(x=>x.tagName.toLowerCase()==='summary')),'native keyboard disclosure');
const readonly=JSON.stringify(state.mission.snapshot),saved=JSON.stringify([...storage]);
for(const disclosure of details){disclosure.open=true;disclosure.focus();assert.equal(document.activeElement,disclosure);}
el('composer-input').value='未提交的中文草稿';el('composer-input').listeners.compositionstart();
el('composer-input').listeners.keydown({key:'Enter',shiftKey:false,isComposing:true,keyCode:229,preventDefault(){throw Error('IME enter intercepted');}});
assert.equal(state.composing,true);el('composer-input').listeners.compositionend();assert.equal(state.composing,false);
assert.equal(el('composer-input').value,'未提交的中文草稿');assert.equal(JSON.stringify(state.mission.snapshot),readonly);assert.equal(JSON.stringify([...storage]),saved);
setPending('mission:'+mid,{type:'control',action:'start',request_id:'fixed-unknown-start',status:'UNKNOWN'});render();
assert.equal(el('mission-permission').checked,false);assert.equal(el('mission-start-confirm').disabled,true);webNoMutation();
''',marker='accessibility')
