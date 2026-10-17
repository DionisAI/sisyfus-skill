"""v6 frozen repairs; offline DI + actual ChatSessions public envelope, not native/device acceptance."""
import copy
import hashlib
import json

import pytest
from sisyfus.workers import portal_gateway as module
from sisyfus.workers.portal_gateway import _ShareError
from sisyfus.workers.protocol import digest
from test_portal_gateway import CHAT, MISSION
from test_portal_review_v5 import offline, actual_chat, bare, response

CREATE='/api/portal/chat'
MESSAGE='/api/portal/chat/message'
RID='v6_request_0001'

@pytest.fixture
def gateway(tmp_path):
    raw={'source':str(tmp_path),'objective':'v6 frozen fixture'}
    spec=tmp_path/'spec.json';spec.write_text(json.dumps(raw))
    chat={'id':CHAT,'source':str(tmp_path),'spec_path':str(spec),'rsi_configuration':None,'messages':[],
          'status':'IDLE','proposal':{'objective':'fixture'},'readiness':{'ready':True},'mission_id':None,
          'placement_preparation':None,'placement_start':None}
    chat['approval_hash']=digest({'source':chat['source'],'spec':raw,'proposal':chat['proposal']})
    return bare(spec,chat)


def new(g):
    g.portal.store.write({'status':'NEW'});g.chat['proposal']=None;g.chat['approval_hash']=None
    return g

@pytest.mark.parametrize('failure',['context_400','context_409','local_drift','spec_drift'])
def test_partial_create_any_later_error_unknown_wire_audit_and_fence(gateway,failure):
    g=new(gateway)
    if failure.startswith('context_'):
        original_status=int(failure.split('_')[1]);original_code='UPSTREAM_REJECTED'
        g.faults[('POST','/api/chat/context')]=_ShareError(original_code,original_status)
    else:
        original_status=409;original_code='PORTAL_BINDING_DRIFT' if failure=='local_drift' else 'SPEC_CHANGED'
        def after(path,body):
            value=copy.deepcopy(g.chat)
            if path=='/api/chat/context':
                if failure=='local_drift':value['source']='/changed'
                else:g.portal.spec_path.write_text('{}')
            return value
        g.after_post=after
    reply=response(g,CREATE,{'request_id':RID})
    assert reply['status']>=500,'a chat was created: later 4xx is UNKNOWN, never definite wire rejection'
    assert g._uncertain and g.portal.store.read()['status']=='UNKNOWN'
    assert g.portal.store.requests[RID]['outcome']=='UNKNOWN'
    event=g.portal.store.events[-1]
    assert event['outcome']=='UNKNOWN' and event['code']==original_code
    assert event['http_status']==original_status,'audit retains upstream/local original status, separate from wire 502'
    n=len(g.calls);assert response(g,CREATE,{'request_id':'v6_request_0002'})['status']==409
    assert len(g.calls)==n

@pytest.mark.parametrize('status',[400,409])
def test_first_create_post_proven_4xx_is_known_rejected_not_uncertain(gateway,status):
    g=new(gateway);g.faults[('POST','/api/chats')]=_ShareError('UPSTREAM_REJECTED',status)
    assert response(g,CREATE,{'request_id':RID})['status']==status
    assert not g._uncertain and not g._store_failed
    assert g.portal.store.requests[RID]['outcome']=='REJECTED'
    assert g.portal.store.read()['status']=='NEW'
    n=len(g.calls);assert response(g,CREATE,{'request_id':RID})['status']==200
    assert len(g.calls)==n,'exact known rejection replay remains readback, not resend'
    g.faults.clear();assert response(g,CREATE,{'request_id':'v6_request_0002'})['status']==200


def test_first_create_timeout_unknown_not_proven_rejection(gateway):
    g=new(gateway);g.faults[('POST','/api/chats')]=_ShareError('UPSTREAM_TIMEOUT',504)
    assert response(g,CREATE,{'request_id':RID})['status']==504
    assert g._uncertain and g.portal.store.requests[RID]['outcome']=='UNKNOWN'

@pytest.mark.parametrize('route',[CREATE,MESSAGE])
@pytest.mark.parametrize('error',[OSError('fixture transient read'),ValueError('input changed')])
def test_presend_spec_reader_error_409_not_store_failure_retryable(gateway,monkeypatch,route,error):
    g=new(gateway) if route==CREATE else gateway
    original=module._regular
    def read(*args,**kwargs):raise error
    monkeypatch.setattr(module,'_regular',read)
    body={'request_id':RID,**({'message':'normal discussion'} if route==MESSAGE else {})}
    reply=response(g,route,body)
    assert reply['status']==409 and reply['value']['error']['code']=='PORTAL_PRESEND_READ_FAILED'
    assert not g._store_failed and not g._uncertain and RID not in g.portal.store.requests
    assert not any(m=='POST' for m,_,_ in g.calls)
    monkeypatch.setattr(module,'_regular',original)
    assert response(g,route,body)['status'] in (200,202)


def test_invalid_pinned_source_presend_known_no_post(gateway):
    g=gateway;g.portal.spec_path.write_text(json.dumps({'source':42}))
    object.__setattr__(g.portal,'spec_sha256',hashlib.sha256(g.portal.spec_path.read_bytes()).hexdigest())
    reply=response(g,MESSAGE,{'request_id':RID,'message':'normal discussion'})
    assert reply['status']==409 and reply['value']['error']['code']=='PORTAL_PRESEND_READ_FAILED'
    assert not g._store_failed and not g._uncertain and not any(m=='POST' for m,_,_ in g.calls)

@pytest.mark.parametrize('route',[CREATE,MESSAGE])
@pytest.mark.parametrize('failure',['reserve','append'])
def test_actual_store_boundary_failure_still_fences(gateway,route,failure):
    g=new(gateway) if route==CREATE else gateway
    def fail(*args,**kwargs):raise OSError('fixture private store fsync failure')
    setattr(g.portal.store,failure,fail)
    assert response(g,route,{'request_id':RID,**({'message':'normal discussion'} if route==MESSAGE else {})})['status']>=500
    assert g._store_failed
    n=len(g.calls);assert response(g,route,{'request_id':'v6_request_0002',**({'message':'normal discussion'} if route==MESSAGE else {})})['status']>=500
    assert len(g.calls)==n

@pytest.mark.parametrize('adopt',[False,True])
def test_actual_envelope_all_chat_origins_verified_only_by_current_read(actual_chat,adopt):
    env=actual_chat;g=bare(env.spec,env.chat,adopt=adopt)
    before=g.portal.store.read();events=copy.deepcopy(g.portal.store.events)
    assert g._state()['spec']['status']=='VERIFIED'
    assert any(m=='GET' and '/api/chat?' in p for m,p,_ in g.calls)
    assert g.portal.store.read()==before and g.portal.store.events==events
    assert all(m=='GET' for m,_,_ in g.calls)
    env.spec.write_text(json.dumps({**env.raw,'objective':'current file changed'}))
    assert g._state()['spec']['status']=='PENDING','state cannot repeat VERIFIED after current pin drift'

@pytest.mark.parametrize('adopt',[False,True])
def test_actual_old_bound_new_display_pin_pending_and_mutation_rejected(actual_chat,adopt):
    env=actual_chat;env.spec.write_text(json.dumps({**env.raw,'objective':'new unbound objective'}))
    g=bare(env.spec,env.chat,adopt=adopt)
    assert g._state()['spec']['status']=='PENDING'
    reply=response(g,MESSAGE,{'request_id':RID,'message':'normal discussion'})
    assert reply['status']==409 and reply['value']['error']['code']=='PORTAL_BINDING_DRIFT'
    assert not any(m=='POST' for m,_,_ in g.calls) and not g._uncertain

@pytest.mark.parametrize('error',[_ShareError('UPSTREAM_TIMEOUT',504),_ShareError('UPSTREAM_CHAT_INVALID',502)])
def test_state_unavailable_actual_chat_does_not_claim_verified_or_fence(gateway,error):
    g=gateway;g.faults[('GET','/api/chat?chat_id='+CHAT)]=error
    assert g._state()['spec']['status']=='PENDING'
    assert not g._uncertain and not g._store_failed


def test_portal_created_no_proposal_pending_can_obtain_first_proposal(gateway):
    g=new(gateway);assert response(g,CREATE,{'request_id':RID})['status']==200
    assert g.portal.store.read()['status']=='CONTEXT_BOUND' and g._state()['spec']['status']=='PENDING'
    def after(path,body):
        assert path=='/api/chat/message'
        value=copy.deepcopy(g.chat);value['proposal']={'objective':'first proposal'}
        value['approval_hash']=digest({'source':value['source'],'spec':g._spec(),'proposal':value['proposal']})
        g.chat=copy.deepcopy(value);return value
    g.after_post=after
    assert response(g,MESSAGE,{'request_id':'v6_request_0002','message':'normal discussion'})['status']==202
    assert g._state()['spec']['status']=='VERIFIED'

@pytest.mark.parametrize('route',['prepare-placement','start'])
def test_no_proposal_cannot_prepare_or_start_even_with_fake_readiness(gateway,route):
    g=gateway;g.chat['proposal']=None;g.chat['approval_hash']='c'*64
    if route=='start':g.chat.update(mission_id=MISSION,placement_preparation={'status':'ACK','approval_hash':'c'*64})
    body={'request_id':RID,'approval_hash':'c'*64,('allow_planning' if route=='prepare-placement' else 'allow_local_workers'):True}
    reply=response(g,'/api/portal/chat/'+route,body)
    assert reply['status']==409 and reply['value']['error']['code']=='PORTAL_SPEC_UNVERIFIED'
    assert not any(m=='POST' for m,_,_ in g.calls)


def test_adopted_no_proposal_readonly_pending_no_store_sideeffects(gateway):
    gateway.chat['proposal']=None;gateway.chat['approval_hash']=None
    g=bare(gateway.portal.spec_path,gateway.chat,adopt=True);before=g.portal.store.read()
    assert g._state()['spec']['status']=='PENDING';assert g._chat()['proposal'] is None
    assert g.portal.store.read()==before
    assert response(g,MESSAGE,{'request_id':RID,'message':'normal discussion'})['status']==409
    assert not any(m=='POST' for m,_,_ in g.calls)


def test_verified_adopted_get_stays_readonly_explicit_mutation_can_bind(actual_chat):
    g=bare(actual_chat.spec,actual_chat.chat,adopt=True);before=g.portal.store.read()
    assert g._chat()['approval_hash']==actual_chat.chat['approval_hash']
    assert g._state()['spec']['status']=='VERIFIED' and g.portal.store.read()==before
    assert response(g,MESSAGE,{'request_id':RID,'message':'normal discussion'})['status']==202
    assert g.portal.store.read()['status']=='CONTEXT_BOUND'


# Append-only v2 wire-oracle correction. Frozen original 27 remain above unchanged.
@pytest.mark.parametrize('route',[CREATE,MESSAGE])
@pytest.mark.parametrize('error',[OSError('fixture transient read'),ValueError('input changed')])
def test_presend_spec_reader_error_409_not_store_failure_retryable_wire_v2(gateway,monkeypatch,route,error):
    g=new(gateway) if route==CREATE else gateway
    original=module._regular
    def read(*args,**kwargs):raise error
    monkeypatch.setattr(module,'_regular',read)
    body={'request_id':RID,**({'message':'normal discussion'} if route==MESSAGE else {})}
    reply=response(g,route,body)
    assert reply['status']==409 and reply['value']['error']['code']=='PORTAL_PRESEND_READ_FAILED'
    assert not g._store_failed and not g._uncertain and RID not in g.portal.store.requests
    assert not any(m=='POST' for m,_,_ in g.calls)
    monkeypatch.setattr(module,'_regular',original)
    assert response(g,route,body)['status'] in (200,202)


def test_invalid_pinned_source_presend_known_no_post_wire_v2(gateway):
    g=gateway;g.portal.spec_path.write_text(json.dumps({'source':42}))
    object.__setattr__(g.portal,'spec_sha256',hashlib.sha256(g.portal.spec_path.read_bytes()).hexdigest())
    reply=response(g,MESSAGE,{'request_id':RID,'message':'normal discussion'})
    assert reply['status']==409 and reply['value']['error']['code']=='PORTAL_PRESEND_READ_FAILED'
    assert not g._store_failed and not g._uncertain and not any(m=='POST' for m,_,_ in g.calls)


@pytest.mark.parametrize('adopt',[False,True])
def test_actual_old_bound_new_display_pin_pending_and_mutation_rejected_wire_v2(actual_chat,adopt):
    env=actual_chat;env.spec.write_text(json.dumps({**env.raw,'objective':'new unbound objective'}))
    g=bare(env.spec,env.chat,adopt=adopt)
    assert g._state()['spec']['status']=='PENDING'
    reply=response(g,MESSAGE,{'request_id':RID,'message':'normal discussion'})
    assert reply['status']==409 and reply['value']['error']['code']=='PORTAL_BINDING_DRIFT'
    assert not any(m=='POST' for m,_,_ in g.calls) and not g._uncertain


@pytest.mark.parametrize('route',['prepare-placement','start'])
def test_no_proposal_cannot_prepare_or_start_even_with_fake_readiness_wire_v2(gateway,route):
    g=gateway;g.chat['proposal']=None;g.chat['approval_hash']='c'*64
    if route=='start':g.chat.update(mission_id=MISSION,placement_preparation={'status':'ACK','approval_hash':'c'*64})
    body={'request_id':RID,'approval_hash':'c'*64,('allow_planning' if route=='prepare-placement' else 'allow_local_workers'):True}
    reply=response(g,'/api/portal/chat/'+route,body)
    assert reply['status']==409 and reply['value']['error']['code']=='PORTAL_SPEC_UNVERIFIED'
    assert not any(m=='POST' for m,_,_ in g.calls)

