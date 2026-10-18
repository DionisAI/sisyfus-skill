"""Actual Console HTTP + ChatSessions, injected driver; not native/phone/A7."""
import json
import time
from test_portal_gateway import feature,serve,call,data,verifier


def test_real_console_create_context_message_and_adoption(tmp_path,verifier):
    m=feature();from sisyfus.workers.lead_console import LeadConsole,MissionHub
    from sisyfus.workers.lead_chat import ChatSessions,MODEL
    from sisyfus.workers.protocol import Receipt
    from test_lead_mission import make_spec
    from test_portal_gateway import MemoryStore
    import hashlib
    source=tmp_path/'source';source.mkdir();hub=MissionHub(tmp_path/'hub',single=False)
    class Driver:
        def run(self,request,emit):
            return Receipt('COMPLETED',output=json.dumps({'reply':'真实HTTP fixture回复','proposal':None}),requested_model=MODEL,actual_model=MODEL,exit_code=0)
    spec=tmp_path/'spec.json';spec.write_text(json.dumps(make_spec(source)));console=LeadConsole(hub,port=0);console._chats=ChatSessions(hub,driver=Driver())
    config=m.PortalConfig(spec,hashlib.sha256(spec.read_bytes()).hexdigest(),None,(),MemoryStore())
    with serve(console),serve(m.OperatorPortalGateway(console.origin,console.token,'portal',password_verifier=verifier,portal=config)) as portal:
        t=data(call(portal,'/api/portal/login',{'password':'synthetic-portal-password'}))['token']
        r=call(portal,'/api/portal/chat',{'request_id':'create_0001'},t);assert r[0]==200,r[2]
        assert config.store.read()['status']=='CONTEXT_BOUND'
        r=call(portal,'/api/portal/chat/message',{'request_id':'message_0001','message':'解释固定任务'},t);assert r[0]==202,r[2]
        for _ in range(200):
            chat=data(call(portal,'/api/portal/chat',token=t))
            if chat['status']!='RUNNING':break
            time.sleep(.01)
        assert any('fixture回复' in x['text'] for x in chat['messages'])
        adopted=m.PortalConfig(spec,config.spec_sha256,chat['id'],(),MemoryStore())
        with serve(m.OperatorPortalGateway(console.origin,console.token,'portal',password_verifier=verifier,portal=adopted)) as p2:
            t2=data(call(p2,'/api/portal/login',{'password':'synthetic-portal-password'}))['token']
            assert call(p2,'/api/portal/chat',token=t2)[0]==200
            assert adopted.store.read()['status']=='CREATED' and data(call(p2,'/api/portal/state',token=t2))['spec']['status']=='PENDING'
    hub.close()

# v2 actual Console + real controller DB, fixture missionFactory only.
def test_actual_console_prepare_placement_start_snapshot_inbox_no_native(tmp_path,verifier,monkeypatch):
    m=feature();from sisyfus.workers.lead_console import LeadConsole,MissionHub
    from sisyfus.workers.lead_chat import ChatSessions,MODEL
    from sisyfus.workers.lead_mission import LeadMission
    from sisyfus.workers.protocol import Receipt
    from test_lead_mission import make_spec
    from test_portal_gateway import MemoryStore
    import hashlib
    import subprocess
    def no_native(*args,**kwargs):raise AssertionError('fixture reached native/process')
    monkeypatch.setattr(subprocess,'Popen',no_native)
    runs=[]
    class FixtureMission(LeadMission):
        def run(self,max_cycles=None):runs.append(str(self.directory));return self.snapshot()
    hub=MissionHub(tmp_path/'hub',single=False,mission_factory=FixtureMission)
    plan={'objective':'Fixture fixed task','architecture':'Fixed checks, plan then execute','constraints':['Keep checks'],'deliverables':['fixture'],'tasks':[{'title':'Fixture','acceptance':'Fixed check','depends_on':[]}]}
    class Driver:
        def run(self,request,emit):return Receipt('COMPLETED',output=json.dumps({'reply':'fixture plan','proposal':plan}),requested_model=MODEL,actual_model=MODEL,exit_code=0)
    spec=tmp_path/'spec.json';spec.write_text(json.dumps(make_spec(tmp_path)))
    console=LeadConsole(hub,port=0);console._chats=ChatSessions(hub,driver=Driver())
    config=m.PortalConfig(spec,hashlib.sha256(spec.read_bytes()).hexdigest(),None,(),MemoryStore())
    try:
        with serve(console),serve(m.OperatorPortalGateway(console.origin,console.token,'portal',password_verifier=verifier,portal=config)) as portal:
            t=data(call(portal,'/api/portal/login',{'password':'synthetic-portal-password'}))['token']
            assert call(portal,'/api/portal/chat',{'request_id':'create_0001'},t)[0]==200
            assert call(portal,'/api/portal/chat/message',{'request_id':'message_0001','message':'固定方案'},t)[0]==202
            for _ in range(200):
                chat=data(call(portal,'/api/portal/chat',token=t))
                if chat['status']!='RUNNING':break
                time.sleep(.01)
            approval=chat['approval_hash'];assert chat['readiness']['ready'],chat
            r=call(portal,'/api/portal/chat/prepare-placement',{'request_id':'prepare_0001','approval_hash':approval,'allow_planning':True},t)
            assert r[0]==202,r[2];chat=data(r);mid=chat['mission_id'];hub.wait(mid,5)
            assert runs==[]
            r=call(portal,'/api/portal/placements',token=t);assert r[0]==200,r[2]
            assert data(r)['placements'][0]['placement']=={'kind':'local'}
            assert call(portal,'/api/portal/nodes',token=t)[0]==200
            r=call(portal,'/api/portal/snapshot',token=t);assert r[0]==200,r[2]
            assert data(r)['capture']['snapshot']['all_verified'] is False
            assert call(portal,'/api/portal/message',{'request_id':'inbox_0001','message':'/btw'},t)[0]==200
            assert call(portal,'/api/portal/messages?cursor=0&application_cursor=0',token=t)[0]==200
            r=call(portal,'/api/portal/chat/start',{'request_id':'start_0001','approval_hash':approval,'allow_local_workers':True},t);assert r[0]==202,r[2];hub.wait(mid,5)
            assert len(runs)==1
            r=call(portal,'/api/portal/chat/start',{'request_id':'start_0001','approval_hash':approval,'allow_local_workers':True},t);assert r[0]==200
            assert len(runs)==1 and hub._session(mid).mission.store.verify_event_chain()['valid']
    finally:hub.close()
