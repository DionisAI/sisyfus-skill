"""Frozen S1 HTTP DI fixtures; no native, provider or publication."""
import copy
import hashlib
import importlib
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from http.client import HTTPConnection
import pytest
from sisyfus.workers.protocol import digest

CHAT='c_'+'a'*32
MISSION='m_fixture_portal'
NODE='node_'+'b'*32
HASH='c'*64

def feature(name='portal_gateway'):
    target='sisyfus.workers.'+name
    try: return importlib.import_module(target)
    except ModuleNotFoundError as exc:
        if exc.name!=target: raise
        pytest.fail('missing frozen phone portal public behavior: '+target,pytrace=False)

class MemoryStore:
    def __init__(self): self.binding={'status':'NEW'}; self.events=[]; self.requests={}
    def write(self,value): self.binding=copy.deepcopy(value)
    def read(self): return copy.deepcopy(self.binding)
    def append(self,value): self.events.append(copy.deepcopy(value))
    def reserve(self,rid,fingerprint):
        old=self.requests.get(rid)
        if old:
            if old['fingerprint']!=fingerprint: raise ValueError('request conflict')
            return False
        self.requests[rid]={'fingerprint':fingerprint,'outcome':'SENT'};return True
    def outcome(self,rid,outcome): self.requests[rid]['outcome']=outcome

@pytest.fixture(scope='session')
def verifier():
    from sisyfus.workers.share_password import create_verifier
    return create_verifier('synthetic-portal-password')

@contextmanager
def serve(server):
    thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
    try: yield server
    finally: server.shutdown();thread.join(3);server.server_close()

def call(server,path,body=None,token=None,headers=None,method=None):
    conn=HTTPConnection('127.0.0.1',server.server_port,timeout=15)
    h={'Origin':server.origin,**(headers or {})}
    if token: h['Authorization']='Bearer '+token
    raw=None if body is None else json.dumps(body).encode()
    if raw is not None:h['Content-Type']='application/json'
    try:
        conn.request(method or ('POST' if body is not None else 'GET'),path,raw,h)
        r=conn.getresponse();data=r.read();return r.status,dict(r.getheaders()),data
    finally:conn.close()

def data(reply): return json.loads(reply[2])

@pytest.fixture
def gateway(tmp_path,verifier):
    m=feature(); spec=tmp_path/'spec.json';spec.write_text(json.dumps({'source':str(tmp_path),'rsi':None}))
    store=MemoryStore(); cfg=m.PortalConfig(spec,hashlib.sha256(spec.read_bytes()).hexdigest(),None,(NODE,),store)
    class FixtureGateway(m.OperatorPortalGateway):
        def _upstream(self,method,path,body=None,**kw):
            self.calls.append((method,path,copy.deepcopy(body)))
            if self.fail and method=='POST':raise m._ShareError('UPSTREAM_TIMEOUT',504)
            if path=='/api/chats':
                assert store.read()['status']=='CREATING';return copy.deepcopy(self.chat)
            if path=='/api/chat/context':
                self.chat.update(source=str(tmp_path),spec_path=str(spec));return copy.deepcopy(self.chat)
            if path.startswith('/api/chat?'):return copy.deepcopy(self.chat)
            if path=='/api/chat/prepare-placement':
                self.chat.update(mission_id=MISSION,placement_preparation={'status':'ACK','request_id':body['request_id'],'approval_hash':HASH,'scope':'planning_only'});return copy.deepcopy(self.chat)
            if path=='/api/chat/start':
                self.chat['placement_start']={'request_id':body['request_id'],'status':'ACK'};return copy.deepcopy(self.chat)
            if path=='/api/chat/message':return copy.deepcopy(self.chat)
            if path.endswith('/placements'):return {'mission_id':MISSION,'tasks':[{'task_id':'task_1','title':'Fixture task','placement':{'kind':'local'}}]}
            if path.endswith('/nodes'):return {'mission_id':MISSION,'nodes':[{'mission_id':'mission_node_namespace','node_id':NODE,'name':'Fixture host','status':'ACTIVE','secret':'node-secret-should-not-pass'},{'node_id':'node_'+'d'*32,'name':'hidden','status':'ACTIVE'}],'execution_ready':False}
            pytest.fail('unexpected upstream '+path)
    g=FixtureGateway('http://127.0.0.1:9999','fixture-operator-secret-long','portal',password_verifier=verifier,portal=cfg)
    g.calls=[];g.fail=False;g.chat={'id':CHAT,'title':'fixture','status':'IDLE','source':'','spec_path':'','rsi_configuration':None,'messages':[],'proposal':{'objective':'fixed'},'approval_hash':HASH,'readiness':{'ready':True},'checks':[{'id':'x','pass_if':{},'fail_if':{},'argv':['leak']}],'mission_id':None,'placement_preparation':None,'placement_start':None}
    g.chat['approval_hash']=digest({'source':str(tmp_path),'spec':json.loads(spec.read_text()),'proposal':g.chat['proposal']})
    with serve(g):yield g

def login(g):
    r=call(g,'/api/portal/login',{'password':'synthetic-portal-password'});assert r[0]==200
    return data(r)['token']

def bound(g):
    token=login(g);assert call(g,'/api/portal/chat',{'request_id':'create_0001'},token)[0]==200;return token

def test_password_required_and_private_state_authenticated(gateway):
    assert call(gateway,'/api/portal/state')[0]==401
    token=login(gateway);assert data(call(gateway,'/api/portal/state',token=token))['binding']['status']=='NEW'
    assert call(gateway,'/api/portal/logout',token=token,method='POST')[0]==200
    assert call(gateway,'/api/portal/state',token=token)[0]==401

@pytest.mark.parametrize('path',['/api/chats','/api/missions','/api/control','/console','/api/portal/state?mission_id=other','/api/portal/nodes/enroll'])
def test_no_inventory_or_authority_routes(gateway,path):
    token=login(gateway);assert call(gateway,path,token=token)[0]>=400;assert gateway.calls==[]

@pytest.mark.parametrize('key',['source','spec_path','checks','argv','chat_id','mission_id','model'])
def test_extra_create_fields_never_forward(gateway,key):
    token=login(gateway);assert call(gateway,'/api/portal/chat',{'request_id':'create_0001',key:'x'},token)[0]==400;assert gateway.calls==[]

def test_create_before_context_once_and_projection(gateway):
    token=bound(gateway);n=len(gateway.calls)
    assert call(gateway,'/api/portal/chat',{'request_id':'create_0001'},token)[0]==200;assert [x[0] for x in gateway.calls[n:]]==['GET']
    assert call(gateway,'/api/portal/chat',{'request_id':'create_0002'},token)[0]==409
    r=call(gateway,'/api/portal/chat',token=token)
    assert r[0]==200 and b'argv' not in r[2] and b'spec_path' not in r[2]
    assert data(r)['proposal']['objective']=='fixed'

def test_create_timeout_unknown_never_recreates(gateway):
    token=login(gateway);gateway.fail=True
    assert call(gateway,'/api/portal/chat',{'request_id':'create_0001'},token)[0]==504
    n=len(gateway.calls);gateway.fail=False
    assert call(gateway,'/api/portal/chat',{'request_id':'create_0002'},token)[0]==409
    assert len(gateway.calls)==n and gateway.portal.store.read()['status']=='UNKNOWN'

@pytest.mark.parametrize('message',['帮我创建工程目录 ~/new-project','开启 RSI，评估集目录 /tmp/catalog'])
def test_chat_directives_rejected_before_side_effect(gateway,message):
    token=bound(gateway);n=len(gateway.calls)
    assert call(gateway,'/api/portal/chat/message',{'request_id':'message_0001','message':message},token)[0]==403
    assert not any(x[0]=='POST' for x in gateway.calls[n:])

@pytest.mark.parametrize('field,value',[('source','/elsewhere'),('spec_path','/elsewhere.json'),('rsi_configuration',{'enabled':True})])
def test_actual_binding_drift_blocks_mutations(gateway,field,value):
    token=bound(gateway);gateway.chat[field]=value
    r=call(gateway,'/api/portal/chat/message',{'request_id':'message_0001','message':'正常讨论'},token)
    assert r[0]==409

def test_spec_sha_drift_blocks_mutation(gateway):
    token=bound(gateway);gateway.portal.spec_path.write_text('{}')
    assert call(gateway,'/api/portal/chat/message',{'request_id':'message_0001','message':'讨论'},token)[0]==409

@pytest.mark.parametrize('permission',[False,1,'true',None])
def test_planning_literal_permission_required(gateway,permission):
    token=bound(gateway)
    assert call(gateway,'/api/portal/chat/prepare-placement',{'request_id':'prepare_001','approval_hash':gateway.chat['approval_hash'],'allow_planning':permission},token)[0]>=400
    assert not any(x[1]=='/api/chat/prepare-placement' for x in gateway.calls)

def test_start_requires_ack_separate_permission_and_matching_hash(gateway):
    token=bound(gateway);body={'request_id':'start_0001','approval_hash':HASH,'allow_local_workers':True}
    assert call(gateway,'/api/portal/chat/start',body,token)[0]==409
    assert call(gateway,'/api/portal/chat/prepare-placement',{'request_id':'prepare_001','approval_hash':gateway.chat['approval_hash'],'allow_planning':True},token)[0]==202
    assert call(gateway,'/api/portal/chat/start',{**body,'allow_local_workers':False},token)[0]>=400
    assert call(gateway,'/api/portal/chat/start',{**body,'approval_hash':'d'*64},token)[0]==409
    assert call(gateway,'/api/portal/chat/start',body,token)[0]==202
    n=len(gateway.calls);assert call(gateway,'/api/portal/chat/start',body,token)[0]==200;assert not any(x[0]=='POST' for x in gateway.calls[n:])

def test_nodes_allowlist_public_rows_not_namespace_or_secret(gateway):
    token=bound(gateway);gateway.chat.update(mission_id=MISSION)
    r=call(gateway,'/api/portal/nodes',token=token);assert r[0]==200
    assert data(r)['nodes']==[{'node_id':NODE,'name':'Fixture host','status':'ACTIVE'}]
    assert b'namespace' not in r[2] and b'secret' not in r[2]

def test_host_origin_csp_and_unsupported_method(gateway):
    token=login(gateway)
    assert call(gateway,'/api/portal/state',token=token,headers={'Host':'evil.invalid'})[0]==403
    assert call(gateway,'/api/portal/chat',{'request_id':'create_0001'},token,{'Origin':'https://evil.invalid'})[0]==403
    page=call(gateway,'/');assert page[0]==200 and "script-src 'nonce-" in page[1]['Content-Security-Policy']
    assert call(gateway,'/api/portal/state',token=token,method='DELETE')[0]==405

def test_busy_rejects_without_upstream(gateway):
    token=bound(gateway);n=len(gateway.calls);gateway._mutation_lock.acquire()
    try:assert call(gateway,'/api/portal/chat/message',{'request_id':'message_0001','message':'hello'},token)[0]==409
    finally:gateway._mutation_lock.release()
    assert len(gateway.calls)==n

def test_mutation_unknown_persisted_no_resend(gateway):
    token=bound(gateway);gateway.fail=True
    body={'request_id':'message_0001','message':'hello'}
    assert call(gateway,'/api/portal/chat/message',body,token)[0]==504
    gateway.fail=False;n=len(gateway.calls)
    assert call(gateway,'/api/portal/chat/message',body,token)[0]==200
    assert not any(x[0]=='POST' for x in gateway.calls[n:])

# v2 supplementary tests: v1 assertions above remain byte-identical.
def test_actual_console_placements_wire_shape_and_allowlist(gateway):
    token=bound(gateway);gateway.chat.update(mission_id=MISSION,placement_preparation={'status':'ACK','approval_hash':HASH})
    old=gateway._upstream
    def up(method,path,body=None,**kw):
        if path.endswith('/placements') and method=='GET':return {'mission_id':MISSION,'placements':[{'task_id':'task_1','placement':{'kind':'local'}}]}
        if path.endswith('/placements') and method=='POST':return {'kind':'remote','mission_id':MISSION,'task_id':'task_1','node_id':NODE,'request_id':body['request_id']}
        return old(method,path,body,**kw)
    gateway._upstream=up
    assert call(gateway,'/api/portal/placements',token=token)[0]==200
    assert call(gateway,'/api/portal/placement',{'request_id':'placement_001','task_id':'task_1','node_id':NODE},token)[0]==200
    assert call(gateway,'/api/portal/placement',{'request_id':'placement_002','task_id':'task_1','node_id':'node_'+'e'*32},token)[0]==403
    assert call(gateway,'/api/portal/placement',{'request_id':'placement_003','task_id':'invented','node_id':NODE},token)[0]==400


def test_single_capture_hash_and_inbox_receipt(gateway):
    token=bound(gateway);gateway.chat['mission_id']=MISSION;old=gateway._upstream;reads=[]
    def up(method,path,body=None,**kw):
        if path.startswith('/api/snapshot?'):
            reads.append(kw)
            return {'id':MISSION,'snapshot':{'nodes':[{'id':'x','verdict':'UNVERIFIED'}],'argv':['private argv']},'controller':{},'controls':[],'engineering_result':{'schema':'sisyfus.lead_console.engineering_result_sidecar.v1','mission_id':MISSION,'status':'OK','result':{'answer':'fixture human answer'},'error':None}}
        if path=='/api/mission/message':return {'request_id':body['request_id'],'id':'i_fixture','status':'RECEIVED'}
        if path.startswith('/api/mission/messages?'):return {'messages':[],'updates':[],'cursor':0,'application_cursor':0,'has_more':False,'has_more_updates':False}
        return old(method,path,body,**kw)
    gateway._upstream=up
    r=call(gateway,'/api/portal/snapshot',token=token);assert r[0]==200,r[2];v=data(r)
    assert len(reads)==1 and reads[0]['engineering'] is True
    from sisyfus.workers.share_gateway import _canonical
    assert v['capture_hash']==hashlib.sha256(_canonical(v['capture'])).hexdigest()
    assert b'private argv' not in r[2] and v['capture']['engineering_result']['result']['answer']=='fixture human answer'
    assert call(gateway,'/api/portal/message',{'request_id':'inbox_0001','message':'/btw'},token)[0]==200
    assert call(gateway,'/api/portal/messages?cursor=0&application_cursor=0',token=token)[0]==200
    assert call(gateway,'/api/portal/messages?cursor=0&cursor=1',token=token)[0]==400
    assert call(gateway,'/api/portal/messages?cursor=-1',token=token)[0]==400


def test_unknown_blocks_new_request_not_just_same_id(gateway):
    token=bound(gateway);gateway.fail=True
    assert call(gateway,'/api/portal/chat/message',{'request_id':'message_0001','message':'hello'},token)[0]==504
    gateway.fail=False;n=len(gateway.calls)
    assert call(gateway,'/api/portal/chat/message',{'request_id':'message_0002','message':'hello'},token)[0]==409
    assert len(gateway.calls)==n


def test_mission_mapping_drift_readback_never_controls_other_mission(gateway):
    token=bound(gateway);gateway.chat['mission_id']=MISSION
    assert call(gateway,'/api/portal/chat',token=token)[0]==200
    assert call(gateway,'/api/portal/chat/message',{'request_id':'message_0001','message':'hello'},token)[0]==202
    gateway.chat['mission_id']='m_another'
    assert call(gateway,'/api/portal/chat',token=token)[0]==409


def test_create_context_timeout_preserves_existing_chat_id(gateway):
    token=login(gateway);old=gateway._upstream
    def up(method,path,body=None,**kw):
        if path=='/api/chat/context':raise feature()._ShareError('UPSTREAM_TIMEOUT',504)
        return old(method,path,body,**kw)
    gateway._upstream=up
    assert call(gateway,'/api/portal/chat',{'request_id':'create_0001'},token)[0]==504
    assert gateway.portal.store.read()['chat_id']==CHAT and gateway.portal.store.read()['status']=='UNKNOWN'
    assert call(gateway,'/api/portal/chat',{'request_id':'create_0002'},token)[0]==409

# v3 safety gaps: new assertions, old frozen prefix preserved.
def test_unknown_creation_blocks_all_followup_mutations(gateway):
    token=login(gateway);old=gateway._upstream
    def up(method,path,body=None,**kw):
        if path=='/api/chat/context':
            old(method,path,body,**kw)
            raise feature()._ShareError('UPSTREAM_TIMEOUT',504)
        return old(method,path,body,**kw)
    gateway._upstream=up
    assert call(gateway,'/api/portal/chat',{'request_id':'create_0001'},token)[0]==504
    n=len(gateway.calls)
    assert call(gateway,'/api/portal/chat/message',{'request_id':'message_0001','message':'hello'},token)[0]==409
    assert not any(x[0]=='POST' for x in gateway.calls[n:])


def test_creation_audited_no_cross_route_request_id_reuse(gateway):
    token=bound(gateway);events=gateway.portal.store.events
    assert any(e['request_id']=='create_0001' and e['outcome']=='SENT' for e in events)
    assert any(e['request_id']=='create_0001' and e['outcome']=='RECEIPT' for e in events)
    n=len(gateway.calls)
    assert call(gateway,'/api/portal/chat/message',{'request_id':'create_0001','message':'hello'},token)[0]==409
    assert not any(x[0]=='POST' for x in gateway.calls[n:])


def test_unknown_readback_receipt_visible_after_new_login(gateway):
    token=bound(gateway);gateway.fail=True
    assert call(gateway,'/api/portal/chat/message',{'request_id':'message_0001','message':'hello'},token)[0]==504
    gateway.fail=False;newtoken=login(gateway)
    state=data(call(gateway,'/api/portal/state',token=newtoken))
    assert state['mutation_status']=='UNKNOWN'
    assert {'request_id':'message_0001','outcome':'UNKNOWN'} in state['receipts']


def test_redaction_removes_nested_prompt_output_raw_and_credentials(gateway):
    token=bound(gateway);gateway.chat['proposal'].update(prompt='private raw spec argv',output='node raw secret',secret='node-secret',rawspec={'argv':['private']})
    gateway.chat['approval_hash']=digest({'source':gateway.chat['source'],'spec':json.loads(gateway.portal.spec_path.read_text()),'proposal':gateway.chat['proposal']})
    r=call(gateway,'/api/portal/chat',token=token)
    assert r[0]==200 and all(x not in r[2] for x in (b'private raw spec',b'node raw secret',b'node-secret'))
