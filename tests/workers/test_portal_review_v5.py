"""Frozen v5 review repair tests: offline DI and actual ChatSessions public proof.

No password setup, sockets, native/provider/CF/SSH, or permanent deletion.
These do not substitute for Main's fresh independent review or real browser gates.
"""
from __future__ import annotations

import copy
from email.message import Message
import hashlib
import io
import json
import os
import socket
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from sisyfus.workers.portal_gateway import OperatorPortalGateway, PortalConfig, _PortalHandler, _ShareError
from sisyfus.workers.protocol import digest
from test_portal_gateway import MemoryStore, CHAT, MISSION, NODE, HASH

HIDDEN='node_'+'e'*32

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('v5 offline repair attempted network/process/password setup')
    monkeypatch.setattr(socket.socket,'bind',forbidden)
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    monkeypatch.setattr(subprocess,'Popen',forbidden)
    from sisyfus.workers import share_password
    monkeypatch.setattr(share_password,'create_verifier',forbidden)
    monkeypatch.setattr(share_password,'load_verifier',forbidden)


def bare(spec,chat,*,adopt=False,store=None):
    g=object.__new__(OperatorPortalGateway)
    g.portal=PortalConfig(spec,hashlib.sha256(spec.read_bytes()).hexdigest(),chat['id'] if adopt else None,(NODE,),store or MemoryStore())
    g._mutation_lock=threading.Lock();g._store_failed=False;g._requests={};g._receipts={};g._uncertain=False
    binding={'status':'CREATED' if adopt else 'CONTEXT_BOUND','chat_id':chat['id'],'adopted':adopt}
    if not adopt:binding.update({k:copy.deepcopy(chat.get(k)) for k in ('source','spec_path','rsi_configuration','mission_id')})
    g.portal.store.write(binding);g.chat=copy.deepcopy(chat);g.calls=[];g.faults={};g.after_post=None
    g.placements={'mission_id':MISSION,'placements':[{'task_id':'task_1','placement':{'kind':'local'}}]}
    g.nodes={'mission_id':MISSION,'nodes':[{'node_id':NODE,'name':'fixture node','status':'ACTIVE'}]}
    def upstream(method,path,body=None,**kwargs):
        g.calls.append((method,path,copy.deepcopy(body)))
        fault=g.faults.get((method,path))
        if fault:raise fault
        if method=='GET':
            if path.startswith('/api/chat?'):return copy.deepcopy(g.chat)
            if path.endswith('/placements'):return copy.deepcopy(g.placements)
            if path.endswith('/nodes'):return copy.deepcopy(g.nodes)
            raise AssertionError('unexpected fixture GET')
        if g.after_post:return g.after_post(path,body)
        value=copy.deepcopy(g.chat)
        if path.endswith('prepare-placement'):
            value.update(mission_id=MISSION,placement_preparation={'request_id':body['request_id'],'approval_hash':HASH,'scope':'planning_only','status':'ACK'})
        if path=='/api/chat/start':value['placement_start']={'request_id':body['request_id'],'status':'ACK'}
        g.chat=copy.deepcopy(value);return value
    g._upstream=upstream
    return g

@pytest.fixture
def gateway(tmp_path):
    spec=tmp_path/'spec.json';spec.write_text(json.dumps({'source':str(tmp_path),'objective':'frozen v5 fixture'}))
    chat={'id':CHAT,'source':str(tmp_path),'spec_path':str(spec),'rsi_configuration':None,'messages':[],'status':'IDLE',
          'proposal':{'objective':'fixture'},'approval_hash':HASH,'readiness':{'ready':True},'mission_id':None,'placement_preparation':None,'placement_start':None}
    chat['approval_hash']=digest({'source':chat['source'],'spec':json.loads(spec.read_text()),'proposal':chat['proposal']})
    return bare(spec,chat)


def operation(g,kind,rid='review_req_0001'):
    if kind=='message':return '/api/portal/chat/message',{'request_id':rid,'message':'normal discussion'}
    if kind=='prepare':return '/api/portal/chat/prepare-placement',{'request_id':rid,'approval_hash':HASH,'allow_planning':True}
    g.chat.update(mission_id=MISSION,placement_preparation={'status':'ACK','approval_hash':HASH})
    if kind=='start':return '/api/portal/chat/start',{'request_id':rid,'approval_hash':HASH,'allow_local_workers':True}
    return '/api/portal/placement',{'request_id':rid,'task_id':'task_1','node_id':NODE}


def response(g,route,body):
    """Actual Portal Handler error mapping with an in-memory authenticated boundary."""
    h=object.__new__(_PortalHandler);h.server=g;h.path=route;h.headers=Message()
    raw=json.dumps(body).encode();h.headers['Content-Length']=str(len(raw));h.headers['Content-Type']='application/json';h.rfile=io.BytesIO(raw)
    h._boundary=lambda **kwargs:None;h._authorize=lambda:None
    out={};h._json=lambda value,status=200,**kwargs:out.update(status=status,value=value)
    h.do_POST();return out

@pytest.mark.parametrize('kind',['message','prepare','start'])
@pytest.mark.parametrize('drift',['source','spec_content'])
def test_post_success_then_local_409_is_unknown_on_wire_and_fenced(gateway,kind,drift):
    g=gateway;route,body=operation(g,kind)
    if kind=='prepare':body['approval_hash']=g.chat['approval_hash']
    def after(path,payload):
        v=copy.deepcopy(g.chat)
        if drift=='source':v['source']='/different'
        else:g.portal.spec_path.write_text(json.dumps({'source':g.chat['source'],'objective':'changed'}))
        return v
    g.after_post=after;reply=response(g,route,body)
    assert reply['status']>=500,'a post-send validation 409 must not look like proven rejection'
    assert g._uncertain and g.portal.store.requests[body['request_id']]['outcome']=='UNKNOWN'
    assert g.portal.store.events[-1]['outcome']=='UNKNOWN'
    assert any(e['kind']=='request' and e['outcome']=='SENT' for e in g.portal.store.events)
    posts=sum(m=='POST' for m,_,_ in g.calls)
    reply=response(g,route,{**body,'request_id':'review_req_0002'})
    assert reply['status']==409 and sum(m=='POST' for m,_,_ in g.calls)==posts

@pytest.mark.parametrize('code',['UPSTREAM_TIMEOUT','UPSTREAM_IO_ERROR','UPSTREAM_CHAT_INVALID'])
def test_presend_chat_read_failure_known_no_post_and_same_id_retryable(gateway,code):
    g=gateway;route,body=operation(g,'message');key=('GET','/api/chat?chat_id='+CHAT)
    g.faults[key]=_ShareError(code,504 if code=='UPSTREAM_TIMEOUT' else 502)
    reply=response(g,route,body)
    assert 400<=reply['status']<500,'presend failure must not claim a possibly sent mutation'
    assert not g._uncertain and not g._store_failed and body['request_id'] not in g.portal.store.requests
    assert g.portal.store.events[-1]['outcome']=='REJECTED'
    assert g.portal.store.events[-1]['code']==code
    assert all(m=='GET' for m,_,_ in g.calls)
    g.faults.clear();assert response(g,route,body)['status']==202

@pytest.mark.parametrize('resource',['placements','nodes'])
def test_presend_placement_read_failure_does_not_burn_request(gateway,resource):
    g=gateway;route,body=operation(g,'placement')
    g.faults[('GET',f'/api/missions/{MISSION}/{resource}')]=_ShareError('UPSTREAM_TIMEOUT',504)
    reply=response(g,route,body)
    assert 400<=reply['status']<500
    assert not g._uncertain and body['request_id'] not in g.portal.store.requests
    assert not any(m=='POST' for m,_,_ in g.calls)


def test_actual_upstream_4xx_is_known_rejection_not_unknown(gateway):
    g=gateway;route,body=operation(g,'message');g.faults[('POST','/api/chat/message')]=_ShareError('UPSTREAM_REJECTED',409)
    assert response(g,route,body)['status']==409
    assert not g._uncertain and g.portal.store.requests[body['request_id']]['outcome']=='REJECTED'
    g.faults.clear();assert response(g,route,{**body,'request_id':'review_req_0002'})['status']==202


def test_post_timeout_is_unknown_exact_replay_get_only(gateway):
    g=gateway;route,body=operation(g,'message');g.faults[('POST','/api/chat/message')]=_ShareError('UPSTREAM_TIMEOUT',504)
    assert response(g,route,body)['status']>=500
    assert g._uncertain and g.portal.store.requests[body['request_id']]['outcome']=='UNKNOWN'
    g.faults.clear();n=len(g.calls);assert response(g,route,body)['status']==200
    assert all(m=='GET' for m,_,_ in g.calls[n:])


def test_post_success_then_audit_write_failure_is_unknown(gateway):
    g=gateway;route,body=operation(g,'message');append=g.portal.store.append
    def fail(e):
        if e['outcome']=='RECEIPT':raise OSError('fixture fsync failure')
        append(e)
    g.portal.store.append=fail
    assert response(g,route,body)['status']>=500
    assert g._uncertain and g.portal.store.requests[body['request_id']]['outcome']=='UNKNOWN'

@pytest.fixture
def actual_chat(tmp_path):
    from sisyfus.workers.lead_console import MissionHub
    from sisyfus.workers.lead_chat import ChatSessions
    from test_lead_mission import make_spec
    class NoNative:
        def run(self,*args):raise AssertionError('adoption dispatched native chat')
    hub=MissionHub(tmp_path/'hub',single=False,mission_factory=lambda *args,**kwargs:pytest.fail('adoption created mission'))
    chats=ChatSessions(hub,driver=NoNative());raw=make_spec(tmp_path)
    spec=tmp_path/'fixed.json';spec.write_text(json.dumps(raw));chat=chats.create();chats.context(chat['id'],'',str(spec))
    proposal={'objective':'fixed fixture proposal','architecture':'bound checks','constraints':['retain'],'deliverables':['fixture'],
              'tasks':[{'title':'fixture','acceptance':'fixed check','depends_on':[]}]}
    state=chats._read(chat['id']);state['proposal']=proposal;chats._save(state)
    try:yield SimpleNamespace(spec=spec,raw=raw,chats=chats,chat=chats.get(chat['id']))
    finally:chats.close();hub.close()


@pytest.mark.parametrize('changed',['objective','constraints','checks'])
def test_same_path_new_spec_old_bound_spec_adoption_fails_closed(actual_chat,changed):
    env=actual_chat;raw=copy.deepcopy(env.raw)
    if changed=='objective':raw['objective']='NEW objective not bound to OLD chat'
    elif changed=='constraints':raw['constraints']=['NEW constraint']
    else:raw['checks']['a']['contract']['pass_if']['all'][0]['value']=False
    env.spec.write_text(json.dumps(raw));g=bare(env.spec,env.chats.get(env.chat['id']),adopt=True)
    with pytest.raises(_ShareError) as err:g._chat()
    assert err.value.status==409 and err.value.code=='PORTAL_BINDING_DRIFT'
    assert g.portal.store.read()['status']=='CREATED' and not any(m=='POST' for m,_,_ in g.calls)
    route,body=operation(g,'prepare');body['approval_hash']=env.chat['approval_hash']
    assert response(g,route,body)['status']==409
    assert not any(m=='POST' for m,_,_ in g.calls)

@pytest.mark.parametrize('kind',['message','prepare','start','placement'])
def test_adoption_without_proposal_remains_pending_readonly_no_rebind(gateway,kind):
    gateway.chat['proposal']=None;gateway.chat['approval_hash']=None
    g=bare(gateway.portal.spec_path,gateway.chat,adopt=True)
    assert g._chat()['proposal'] is None
    assert g.portal.store.read()['status']=='CREATED'
    assert g._state()['spec']['status']=='PENDING'
    route,body=operation(g,kind);assert response(g,route,body)['status']==409
    assert not any(m=='POST' for m,_,_ in g.calls)


def test_placements_exact_projection_masks_hidden_remote_not_local(gateway):
    g=gateway;g.placements={'mission_id':MISSION,'nodes':[{'node_id':HIDDEN,'name':'do not expose'}],'inventory_note':'leak',
        'placements':[{'task_id':'local','node_name':'leak','placement':{'kind':'local','node_id':HIDDEN}},
                      {'task_id':'allowed','extra':'leak','placement':{'kind':'remote','node_id':NODE,'mission_id':'mission_node_namespace','task_hash':'a'*64,'node_name':'leak'}},
                      {'task_id':'hidden','placement':{'kind':'remote','node_id':HIDDEN,'node_name':'do not expose','secret':'synthetic secret'}}]}
    value=g._placements(MISSION)
    assert value=={'mission_id':MISSION,'placements':[{'task_id':'local','placement':{'kind':'local'}},
          {'task_id':'allowed','placement':{'kind':'remote','node_id':NODE}},
          {'task_id':'hidden','placement':{'kind':'remote','node_id':'UNEXPOSED'}}]}
    assert HIDDEN not in json.dumps(value) and 'inventory' not in json.dumps(value) and 'namespace' not in json.dumps(value)

@pytest.mark.parametrize('bad',[{'tasks':[]},{'placements':[{'task_id':'x','placement':{'kind':'mystery'}}]},
                                {'placements':[{'task_id':'x','placement':{'kind':'remote','node_id':'arbitrary'}}]},
                                {'placements':[{'task_id':12,'placement':{'kind':'local'}}]}])
def test_malformed_actual_placements_wire_fails_explicitly(gateway,bad):
    gateway.placements={'mission_id':MISSION,**bad}
    with pytest.raises(_ShareError) as err:gateway._placements(MISSION)
    assert err.value.code=='UPSTREAM_PLACEMENTS_INVALID'


def test_placement_post_projects_receipt_not_inventory_or_node_namespace(gateway):
    g=gateway;route,body=operation(g,'placement')
    def accepted(path,payload):return {'kind':'remote','task_id':'task_1','node_id':NODE,'request_id':payload['request_id'],
                                      'mission_id':'mission_node_namespace','task_hash':'a'*64,'nodes':[{'node_id':HIDDEN}]}
    g.after_post=accepted;reply=response(g,route,body)
    assert reply['status']==200
    assert reply['value']=={'mission_id':MISSION,'task_id':'task_1','request_id':body['request_id'],'placement':{'kind':'remote','node_id':NODE}}


def test_actual_private_store_unknown_persisted_and_message_not_stored(tmp_path,gateway):
    from sisyfus.workers.share_runtime import ShareRuntime
    from sisyfus.workers.portal_runtime import PortalStore
    root=tmp_path/'owned';root.mkdir(mode=0o700)
    owner=ShareRuntime('http://127.0.0.1:9999',tmp_path/'unused-token','portal',root,local_only=True)
    owner._root_fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);s=os.fstat(owner._root_fd);owner._root_id=(s.st_dev,s.st_ino)
    try:
        store=PortalStore(owner);g=bare(gateway.portal.spec_path,gateway.chat,store=store);route,body=operation(g,'message')
        g.after_post=lambda path,payload:{**copy.deepcopy(g.chat),'source':'/different'}
        assert response(g,route,body)['status']>=500
        state=json.loads((root/'portal.json').read_text());assert state['requests'][body['request_id']]['outcome']=='UNKNOWN'
        assert json.loads((root/'portal.jsonl').read_text().splitlines()[-1])['outcome']=='UNKNOWN'
        assert body['message'] not in (root/'portal.jsonl').read_text()
    finally:owner.close()


def test_actual_cli_once_nargs_zero_and_public_transport_seams():
    from sisyfus.workers import portal_cli,share_cli
    argv=['--console-origin','http://127.0.0.1:9999','--operator-token-file','/fixture/token','--runtime-directory','/fixture/runtime',
          '--password-file','/fixture/verifier','--spec-file','/fixture/spec','--local-only']
    assert portal_cli._parse(argv).local_only is True
    value={'schema':'sisyfus.portal.runtime.v1','state':'LOCAL_ONLY','permissions':{'view':True,'messages':True,'chat':True,'planning':True,'start':True,'placement':False,'controls':False,'inventory':False},
           'local_origin':'http://127.0.0.1:9999','public_origin':None,'access_file':'/fixture/runtime/access.json','resources_closed':False,'process_returncode':None,'diagnostics':[],'token':'must not project'}
    assert 'token' not in portal_cli._public(value)
    with pytest.raises(ValueError):share_cli._public(value)
