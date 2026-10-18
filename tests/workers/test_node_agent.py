"""Frozen N5 NodeAgent v1: real authenticated loopback + injected protocol drivers.

No native model, deployment, SSH, user mission Start, permanent deletion or gate
promotion. Assertions/public wires freeze before the new module is created.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import http.client
import importlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from sisyfus.workers.lead_console import MissionHub
from sisyfus.workers.node_claims import NodeClaims
from sisyfus.workers.node_registry import NodeRegistry
from sisyfus.workers.protocol import Receipt, Request, digest, environment
from sisyfus.workers.remote_artifacts import create_input_snapshot, full_tree_manifest
from test_lead_mission import make_spec


@pytest.fixture
def agent_type():
    return importlib.import_module('sisyfus.workers.node_agent').NodeAgent


class AgentDriver:
    """Protocol fixture, not a model or verifier. Native interface is unchanged."""
    def __init__(self, callback=None):
        self.requests = []
        self.callback = callback
        self.controls_seen = []
    def run(self, request, emit, controls):
        self.requests.append(request)
        if self.callback:
            result = self.callback(request, emit, controls)
            if result is not None:
                return result
        emit('process_started', {'pid': os.getpid(), 'driver': 'codex'})
        emit('session_bound', {'session_id': 'fixture-session'})
        emit('turn_bound', {'session_id': 'fixture-session', 'turn_id': 'fixture-turn'})
        emit('model_identity', {'requested_model': request.model, 'actual_model': None, 'telemetry': 'missing'})
        Path(request.cwd, 'result.txt').write_bytes(b'42')
        return Receipt('COMPLETED', session_id='fixture-session', turn_id='fixture-turn',
                       output='protocol fixture result, not PASS', requested_model=request.model)


def local_dump(state):
    chunks = []
    for path in state.rglob('*') if state.exists() else []:
        if path.is_file() and not path.is_symlink() and path.suffix in {'.sqlite3', '.sqlite', '.db'}:
            db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)
            try: chunks.append('\n'.join(db.iterdump()))
            finally: db.close()
    return '\n'.join(chunks)


def retained_bytes(state):
    return b'\n'.join(p.read_bytes() for p in state.rglob('*')
                      if p.is_file() and not p.is_symlink()) if state.exists() else b''


def run_observe(agent):
    """Failures stay explicit; this helper never rewrites status or assertions."""
    try:
        return agent.run_once()
    except (ValueError, PermissionError, OSError, RuntimeError) as exc:
        return {'retained_failure': str(exc)}


@pytest.fixture
def agent_env(tmp_path, monkeypatch, agent_type):
    assert os.environ.get('SISYFUS_TEST_LOOPBACK') == '1', 'explicit isolated fixture loopback opt-in required'
    gateway_type = importlib.import_module('sisyfus.workers.node_gateway').NodeGateway
    controller = tmp_path / 'controller'
    controller.mkdir()
    hub = MissionHub(controller / 'hub')
    ident = hub.create(make_spec(controller))['id']
    mission = hub._session(ident).mission
    mission._initial_plan()
    def forbidden(*args, **kwargs):
        raise AssertionError('node substrate must never start native/controller/check/review')
    for native in mission.drivers.values():
        monkeypatch.setattr(native, 'run', forbidden)
    monkeypatch.setattr(hub, 'start', forbidden)
    registry = NodeRegistry(mission.journal)
    node = registry.enroll('agent_enroll_0001', 'N5 fixture node', ['codex'], ['gpt-6.1-sol'])
    claims = NodeClaims(mission.journal, registry, mission.directory / 'remote/artifacts', lease_seconds=30)
    mission._node_claims = claims
    source = controller / 'prepared'
    source.mkdir()
    (source / 'input.txt').write_bytes(b'fixed input')
    (source / 'sub').mkdir()
    (source / 'sub/data.txt').write_bytes(b'fixed nested input')
    snapshot = controller / 'snapshot'
    manifest = create_input_snapshot(source, snapshot, ['input.txt', 'partial.txt', 'result.txt'])
    request = Request('build', 'Implement fixed fixture task.', str(snapshot), 'gpt-6.1-sol',
                      mode='workspace-write', timeout=4, max_turns=None)
    gateway = gateway_type(hub, port=0)
    thread = threading.Thread(target=gateway.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    auth = tmp_path / 'node-auth.json'
    credentials = {'schema': 1, 'controller_mission_id': ident, 'node_id': node['node_id'], 'secret': node['secret'],
                   'gateway_url': gateway.url, 'gateway_host': '127.0.0.1:' + str(gateway.server_port)}
    auth.write_text(json.dumps(credentials)); auth.chmod(0o600)
    env = SimpleNamespace(root=tmp_path, hub=hub, ident=ident, mission=mission, registry=registry, node=node,
        claims=claims, source=source, snapshot=snapshot, manifest=manifest, request=request, gateway=gateway,
        auth=auth, credentials=credentials, state=tmp_path/'agent-state', key='agent-run-0001', agent_type=agent_type)
    try: yield env
    finally:
        gateway.shutdown(); gateway.server_close(); thread.join(5)
        assert not thread.is_alive()
        hub.close()


def publish(e, *, supplement=False):
    prompt = e.request.prompt
    if supplement:
        e.mission.inbox.submit('node-agent frozen supplement', 'agent_message_0001',
                              snapshot=e.mission.snapshot(), controller={})
    e.mission.journal.record('roles', e.key, {'role': 'worker', 'driver': 'codex', 'model': 'gpt-6.1-sol',
        'mode': 'workspace-write', 'cwd': e.request.cwd})
    e.mission.journal.reserve(e.key, 'build', digest(asdict(e.request)), on_reserved=(
        lambda db: e.mission.inbox.bind(db, e.key, role='worker', task_id='build', prompt=prompt)))
    bound = e.mission.inbox.for_run(e.key)
    if bound:
        e.request = Request(**(asdict(e.request) | {'prompt': bound['prompt']}))
    e.claims.bind_input_snapshot(e.key, e.snapshot, e.manifest)
    return e.claims.offer(e.key, e.node['node_id'], e.request, e.manifest)


def execute(e, driver=None):
    driver = driver or AgentDriver()
    agent = e.agent_type(e.auth, e.state, driver=driver)
    return agent, driver


def assert_controller_unsettled(e):
    assert e.mission.journal.runs()[0]['status'] == 'IN_FLIGHT'
    assert not e.mission.snapshot()['all_verified']
    assert not e.mission.journal.records('reviews') and e.mission.integration_continuation() is None
    assert e.mission.store.verify_event_chain()['valid']


def wire_trace(e, monkeypatch):
    seen = []
    original = e.claims.claim
    def claim(node_id, request_id, *, admit_response=None):
        assert request_id in local_dump(e.state), 'claim request must commit before POST'
        value = original(node_id, request_id, admit_response=admit_response)
        seen.append((request_id, json.loads(json.dumps(value))))
        return value
    monkeypatch.setattr(e.claims, 'claim', claim)
    return seen


def lose_response(e, monkeypatch, operation, *, after=None):
    import sisyfus.workers.node_gateway as gateway_module
    original = gateway_module._Handler._send
    dropped = []
    def send(self, value, status=200, **kwargs):
        if status == 200 and operation in self.path and not dropped:
            dropped.append((self.path, value))
            if after: after()
            self.close_connection = True
            self.connection.shutdown(2)
            self.connection.close()
            return
        return original(self, value, status, **kwargs)
    monkeypatch.setattr(gateway_module._Handler, '_send', send)
    return dropped


def test_authenticated_gateway_full_positive_original_request_source_and_namespace(agent_env):
    e = agent_env
    original = publish(e, supplement=True)
    source_before = full_tree_manifest(e.source)
    def observe(request, emit, controls):
        assert 'IN_FLIGHT' in local_dump(e.state), 'local native reservation must precede driver call'
        assert request.cwd != e.request.cwd and Path(request.cwd).is_relative_to(e.state)
        assert Path(request.cwd, 'input.txt').read_bytes() == b'fixed input'
        assert Path(request.cwd, 'sub/data.txt').read_bytes() == b'fixed nested input'
        assert asdict(request) | {'cwd': e.request.cwd} == asdict(e.request)
        assert e.credentials['secret'] not in json.dumps(asdict(request))
    agent, driver = execute(e, AgentDriver(observe))
    agent.run_once()
    value = e.claims.get(e.key)
    value = e.claims.status(e.node['node_id'], value['claim_id'], value['epoch'])
    assert value['mission_id'] == e.registry.mission_id != e.ident
    assert value['node_id'] == e.node['node_id'] and value['fingerprint'] == original['fingerprint']
    assert value['status'] == 'RECEIPTED' and value['receipt']['status'] == 'COMPLETED'
    assert value['receipt']['requested_model'] == 'gpt-6.1-sol' and value['receipt']['actual_model'] is None
    assert value['manifest'] == [{'path':'result.txt','sha256':hashlib.sha256(b'42').hexdigest(),'size':2}]
    assert value['tree'] == full_tree_manifest(driver.requests[0].cwd)
    assert set(value['tree']) == {'schema','files','tree','errors','complete'}
    assert 'deleted_paths' not in value['tree']
    assert full_tree_manifest(e.source) == source_before
    messages = e.mission.inbox.messages()['messages']
    assert messages[0]['applications'][0]['status'] == 'APPLIED'
    assert_controller_unsettled(e)
    assert e.node['secret'].encode() not in retained_bytes(e.state)


def test_no_work_is_committed_then_next_explicit_call_uses_new_claim_id(agent_env, monkeypatch):
    e = agent_env; trace = wire_trace(e, monkeypatch)
    agent, driver = execute(e)
    agent.run_once()
    first = trace[0][0]
    assert first in local_dump(e.state) and 'NO_WORK' in local_dump(e.state)
    publish(e)
    restarted, _ = execute(e, driver)
    restarted.run_once()
    assert trace[-1][0] != first and len(driver.requests) == 1
    assert e.claims.get(e.key)['status'] == 'RECEIPTED'


@pytest.mark.parametrize('operation', ['/claim', '/sync', '/uploads/', '/receipt'])
def test_dropped_response_reuses_original_request_events_upload_and_receipt(agent_env, monkeypatch, operation):
    e = agent_env; publish(e); trace = wire_trace(e, monkeypatch)
    dropped = lose_response(e, monkeypatch, operation)
    agent, driver = execute(e)
    run_observe(agent)
    for _ in range(3):
        restarted, _ = execute(e, driver)
        run_observe(restarted)
        if e.claims.get(e.key)['status'] == 'RECEIPTED': break
    assert dropped and len({r[0] for r in trace}) == 1
    assert len(driver.requests) == 1
    result = e.claims.get(e.key)
    result = e.claims.status(e.node['node_id'], result['claim_id'], result['epoch'])
    assert result['status'] == 'RECEIPTED' and result['receipt']['status'] == 'COMPLETED'
    assert result['tree'] == full_tree_manifest(driver.requests[0].cwd)
    with e.mission.store._transaction(immediate=False) as db:
        events = db.execute('SELECT seq,raw_digest FROM remote_event_sync ORDER BY seq').fetchall()
    assert [r[0] for r in events] == [1,2,3,4]
    assert len({r[1] for r in events}) == 4
    assert_controller_unsettled(e)


@pytest.mark.parametrize('outcome', ['UNKNOWN', 'ERROR', 'COMPLETED'])
def test_native_outcome_and_restart_never_relaunch(agent_env, outcome):
    e = agent_env; publish(e)
    driver = AgentDriver(lambda request,*_: Receipt(outcome, requested_model=request.model,
                                                    actual_model=None, error='fixture outcome'))
    agent, _ = execute(e, driver)
    run_observe(agent)
    for _ in range(2):
        restarted, _ = execute(e, driver); run_observe(restarted)
    assert len(driver.requests) == 1
    value = e.claims.get(e.key)
    assert value['receipt']['status'] == outcome
    assert value['status'] == ('UNKNOWN' if outcome == 'UNKNOWN' else 'RECEIPTED')
    assert_controller_unsettled(e)


def test_reservation_before_spawn_property_crash_and_restart_zero_native(agent_env):
    e = agent_env; publish(e)
    class BeforeSpawnCrash:
        @property
        def run(self):
            assert 'IN_FLIGHT' in local_dump(e.state)
            raise KeyboardInterrupt('fixture crash in reservation-to-spawn gap')
    agent, _ = execute(e, BeforeSpawnCrash())
    with pytest.raises(KeyboardInterrupt): agent.run_once()
    driver = AgentDriver(); restarted, _ = execute(e, driver)
    run_observe(restarted)
    assert not driver.requests
    assert 'UNKNOWN' in local_dump(e.state) or 'IN_FLIGHT' in local_dump(e.state)
    assert_controller_unsettled(e)


def test_process_exit_in_reservation_spawn_gap_preserves_unknown_and_no_relaunch(agent_env):
    e = agent_env; publish(e)
    script = '''import os,sys,sqlite3\nfrom pathlib import Path\nfrom scripts.test_retained import guard_deletion\nsys.addaudithook(guard_deletion)\nfrom sisyfus.workers.node_agent import NodeAgent\nclass Gap:\n @property\n def run(self):\n  dumps=[]\n  for p in Path(sys.argv[2]).rglob('*'):\n   if p.is_file() and p.suffix in {'.sqlite3','.sqlite','.db'}:\n    db=sqlite3.connect(p); dumps.append('\\n'.join(db.iterdump())); db.close()\n  os._exit(73 if 'IN_FLIGHT' in '\\n'.join(dumps) else 74)\nNodeAgent(sys.argv[1],sys.argv[2],driver=Gap()).run_once()\n'''
    completed = subprocess.run([sys.executable,'-c',script,str(e.auth),str(e.state)],
        cwd=Path(__file__).resolve().parents[2], env=os.environ.copy(), timeout=12, capture_output=True)
    assert completed.returncode == 73, completed.stderr.decode(errors='replace')
    driver = AgentDriver(); agent, _ = execute(e, driver)
    run_observe(agent)
    assert not driver.requests
    assert 'UNKNOWN' in local_dump(e.state) or 'IN_FLIGHT' in local_dump(e.state)


def test_quiet_native_has_independent_heartbeat_and_finite_original_timeout(agent_env, monkeypatch):
    e = agent_env; e.claims.lease_seconds = .5; publish(e)
    beats = []
    original = e.claims.heartbeat
    def heartbeat(node_id, claim_id, epoch, *, admit_response=None):
        beats.append(time.monotonic()); return original(node_id, claim_id, epoch, admit_response=admit_response)
    monkeypatch.setattr(e.claims, 'heartbeat', heartbeat)
    driver = AgentDriver(lambda *_: (time.sleep(1.3), Receipt('COMPLETED',requested_model='gpt-6.1-sol'))[1])
    agent, _ = execute(e, driver); agent.run_once()
    assert len(beats) >= 3
    assert max(b-a for a,b in zip(beats,beats[1:])) < .5
    assert e.claims.get(e.key)['status'] == 'RECEIPTED'
    assert driver.requests[0].timeout == e.request.timeout


@pytest.mark.parametrize('accepted', [None, True, False])
def test_interrupt_durable_delivery_at_most_once_native_ack_is_only_truth(agent_env, accepted):
    e = agent_env; publish(e)
    command = {'id':'agent-interrupt-0001','action':'interrupt','text':''}
    e.claims.post_controls(e.key,[command])
    observed = []
    def native(request, emit, controls):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline and not observed:
            for control in controls():
                assert control['id'] in local_dump(e.state)
                observed.append(control)
                if accepted is not None: emit('control_ack', {'command_id':control['id'],'accepted':accepted,'error':None})
            time.sleep(.02)
        assert observed == [command]
        assert controls() == [] and controls() == []
        return Receipt('INTERRUPTED',requested_model=request.model)
    agent, driver = execute(e, AgentDriver(native)); agent.run_once()
    restarted, _=execute(e,driver); run_observe(restarted)
    assert len(driver.requests)==1 and len(observed)==1
    with e.mission.store._transaction(immediate=False) as db:
        status=db.execute('SELECT status FROM remote_transport_controls WHERE id=?',(command['id'],)).fetchone()[0]
    assert status == ('PENDING' if accepted is None else 'ACK' if accepted else 'REJECTED')


@pytest.mark.parametrize('kind,data', [
    ('unknown_native_kind', {'text':'retained invalid native kind'}),
    ('native_event', {'method':'fixture','params':{'text':'x'*64_001}}),
    ('control_ack', {'command_id':'x','accepted':'yes'}),
    ('turn_bound', {'session_id':'s','turn_id':'t','arbitrary':True}),
    ('process_started', {'pid':True,'driver':'codex'}),
])
def test_native_event_invalid_n1_limits_are_explicit_and_not_silently_dropped(agent_env, kind, data):
    e=agent_env; publish(e)
    def native(request,emit,controls):
        with pytest.raises((ValueError, RuntimeError)):
            emit(kind,data)
        return Receipt('UNKNOWN', requested_model=request.model, error='fixture rejected invalid event')
    agent, driver=execute(e,AgentDriver(native)); result=run_observe(agent)
    assert len(driver.requests)==1
    local=local_dump(e.state)
    assert kind in local and any(word in local.lower() for word in ['error','invalid','unknown','bound'])
    with e.mission.store._transaction(immediate=False) as db:
        assert db.execute('SELECT count(*) FROM remote_event_sync').fetchone()[0] == 0
    assert e.claims.get(e.key)['receipt'] is None or e.claims.get(e.key)['receipt']['status']!='COMPLETED'


def test_outbox_events_commit_before_sync_and_sequences_remain_contiguous(agent_env, monkeypatch):
    e=agent_env; publish(e); original=e.claims.sync; received=[]
    def sync(node,claim,epoch,events,*,admit_response=None):
        local=local_dump(e.state)
        for event in events: assert event['kind'] in local
        received.extend(json.loads(json.dumps(events)))
        return original(node,claim,epoch,events,admit_response=admit_response)
    monkeypatch.setattr(e.claims,'sync',sync)
    agent,_=execute(e); agent.run_once()
    assert [v['seq'] for v in received] == [1,2,3,4]
    assert e.claims.get(e.key)['status']=='RECEIPTED'


@pytest.mark.parametrize('identity', ['controller','namespace','node','claim','epoch','run','watermark'])
def test_corrupt_sync_ack_identity_or_highwater_never_acknowledges_local_events(agent_env, monkeypatch, identity):
    e=agent_env; publish(e)
    original=e.claims.sync
    def sync(node_id,claim_id,epoch,events,*,admit_response=None):
        admit=None if admit_response is None else lambda result,controls: admit_response(corrupted(result),controls)
        return corrupted(original(node_id,claim_id,epoch,events,admit_response=admit))
    def corrupted(value):
        key={'namespace':'mission_id','node':'node_id','claim':'claim_id','epoch':'epoch','run':'run_key','watermark':'last_seq'}.get(identity)
        if key: value[key]=9999 if key in {'epoch','last_seq'} else 'other-identity'
        return value
    monkeypatch.setattr(e.claims,'sync',sync)
    if identity=='controller':
        import sisyfus.workers.node_gateway as gm
        send=gm._Handler._send
        def corrupt(self,value,status=200,**kwargs):
            if self.path.endswith('/sync') and status==200: value=value.envelope|{'controller_mission_id':'m_wrong'}
            return send(self,value,status,**kwargs)
        monkeypatch.setattr(gm._Handler,'_send',corrupt)
    agent,driver=execute(e); run_observe(agent)
    assert len(driver.requests)==1
    local=local_dump(e.state).lower()
    assert any(w in local for w in ['invalid','mismatch','error','unknown','identity','watermark'])
    db=sqlite3.connect((e.state/'agent.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=1)
    try: assert db.execute('SELECT ack FROM attempts').fetchall()==[(0,)], 'corrupt sync ACK must leave the outbox unacknowledged'
    finally: db.close()
    assert all(kind in local_dump(e.state) for kind in ['process_started','session_bound','turn_bound','model_identity'])
    monkeypatch.setattr(e.claims,'sync',original)
    if identity=='controller': monkeypatch.setattr(gm._Handler,'_send',send)
    restarted,_=execute(e,driver); run_observe(restarted)
    assert len(driver.requests)==1 and e.claims.get(e.key)['receipt']['status']=='COMPLETED'


@pytest.mark.parametrize('tamper', ['fingerprint','prompt','input_hash','model','mode','task','node','namespace','epoch','request_fields','file_path','file_hash','file_size'])
def test_tampered_claim_offer_or_input_never_grants_native(agent_env, monkeypatch, tamper):
    e=agent_env; publish(e); original=e.claims.claim
    def claim(node_id,request_id,*,admit_response=None):
        admit=None if admit_response is None else lambda result,controls: admit_response(tampered(result),controls)
        return tampered(original(node_id,request_id,admit_response=admit))
    def tampered(value):
        value=json.loads(json.dumps(value)); offered=value['claim']
        if tamper=='fingerprint': offered['fingerprint']='0'*64
        elif tamper=='prompt': offered['request']['prompt']+=' drift'
        elif tamper=='input_hash': offered['input_manifest_hash']='0'*64
        elif tamper=='model': offered['request']['model']='other-model'
        elif tamper=='mode': offered['request']['mode']='read-only'
        elif tamper=='task': offered['task_id']='other'
        elif tamper=='node': offered['node_id']='node_'+'0'*32
        elif tamper=='namespace': offered['mission_id']='mission_'+'0'*32
        elif tamper=='epoch': offered['epoch']=True
        elif tamper=='request_fields': offered['request']['argv']=['arbitrary']
        elif tamper=='file_path': offered['input_manifest']['files'][0]['path']='../parent'
        elif tamper=='file_hash': offered['input_manifest']['files'][0]['sha256']='0'*64
        elif tamper=='file_size': offered['input_manifest']['files'][0]['size']=True
        return value
    monkeypatch.setattr(e.claims,'claim',claim)
    agent,driver=execute(e); result=run_observe(agent)
    assert not driver.requests and e.claims.get(e.key)['receipt'] is None
    assert 'retained_failure' in (result or {}) or any(w in local_dump(e.state).lower() for w in ['invalid','error','mismatch'])


def test_input_hash_or_special_download_loss_never_grants_native(agent_env):
    e=agent_env; publish(e)
    (e.snapshot/'sub/data.txt').write_bytes(b'corrupted after frozen offer')
    agent,driver=execute(e); run_observe(agent)
    assert not driver.requests and e.claims.get(e.key)['receipt'] is None


@pytest.mark.parametrize('mutation', ['hidden','control','symlink','fifo','scope','deletion'])
def test_complete_tree_retains_diagnostics_and_uploads_only_exact_allowlist(agent_env, mutation):
    e=agent_env; publish(e)
    def native(request,emit,controls):
        cwd=Path(request.cwd); (cwd/'result.txt').write_bytes(b'42')
        if mutation=='hidden': (cwd/'.hidden').write_bytes(b'hidden diagnostic')
        elif mutation=='control': (cwd/'auth.json').write_bytes(b'control diagnostic')
        elif mutation=='symlink': (cwd/'linked').symlink_to(e.source/'input.txt')
        elif mutation=='fifo': os.mkfifo(cwd/'pipe')
        elif mutation=='scope': (cwd/'out-of-scope.txt').write_bytes(b'outside scope')
        elif mutation=='deletion': (cwd/'input.txt').rename(e.state/'retained-deleted-input.txt')
        return Receipt('COMPLETED',requested_model=request.model)
    agent,driver=execute(e,AgentDriver(native)); run_observe(agent)
    value=e.claims.get(e.key)
    value=e.claims.status(e.node['node_id'],value['claim_id'],value['epoch'])
    assert value['receipt']['status']=='COMPLETED'
    assert value['tree']==full_tree_manifest(driver.requests[0].cwd)
    assert set(value['tree'])=={'schema','files','tree','errors','complete'}
    assert [p['path'] for p in value['uploads']]==['result.txt']
    if mutation not in {'scope','deletion'}: assert value['tree']['errors']
    if mutation=='scope': assert any(n['path']=='out-of-scope.txt' for n in value['tree']['tree'])
    if mutation=='deletion': assert not any(n['path']=='input.txt' for n in value['tree']['tree'])
    assert_controller_unsettled(e)


def test_terminal_fact_commits_before_upload_and_fixed_bytes_survive_response_loss(agent_env, monkeypatch):
    e=agent_env; publish(e); upload=e.claims.upload; observed=[]
    def verify_upload(node,claim,epoch,path,sha,data,*,admit_response=None):
        local=local_dump(e.state)
        assert 'COMPLETED' in local and 'fixture-session' in local
        assert data==b'42' and sha==hashlib.sha256(b'42').hexdigest()
        observed.append((path,sha,data)); return upload(node,claim,epoch,path,sha,data,admit_response=admit_response)
    monkeypatch.setattr(e.claims,'upload',verify_upload)
    agent,driver=execute(e)
    lose_response(e,monkeypatch,'/uploads/',after=lambda: Path(driver.requests[0].cwd,'result.txt').write_bytes(b'changed after native terminal'))
    run_observe(agent)
    restarted,_=execute(e,driver); run_observe(restarted)
    assert len(driver.requests)==1 and observed
    value=e.claims.get(e.key)
    value=e.claims.status(e.node['node_id'],value['claim_id'],value['epoch'])
    assert value['receipt']['status']=='COMPLETED'
    assert next(f for f in value['tree']['files'] if f['path']=='result.txt')['sha256']==hashlib.sha256(b'42').hexdigest()
    assert value['manifest']==[{'path':'result.txt','sha256':hashlib.sha256(b'42').hexdigest(),'size':2}]


def test_lease_loss_preserves_confirmed_stored_subset_and_late_original_result(agent_env, monkeypatch):
    e=agent_env; publish(e); upload=e.claims.upload
    def stop_second(node,claim,epoch,path,sha,data,*,admit_response=None):
        if path=='result.txt':
            with e.mission.store._transaction() as db:
                db.execute('UPDATE remote_offers SET lease_expires_at=0 WHERE claim_id=?',(claim,))
        return upload(node,claim,epoch,path,sha,data,admit_response=admit_response)
    monkeypatch.setattr(e.claims,'upload',stop_second)
    def native(request,*_):
        Path(request.cwd,'partial.txt').write_bytes(b'partial')
        Path(request.cwd,'result.txt').write_bytes(b'42')
        return Receipt('COMPLETED',requested_model=request.model)
    agent,driver=execute(e,AgentDriver(native)); run_observe(agent)
    restarted,_=execute(e,driver); run_observe(restarted)
    value=e.claims.get(e.key)
    value=e.claims.status(e.node['node_id'],value['claim_id'],value['epoch'])
    assert len(driver.requests)==1 and value['status']=='RECONCILIATION_CANDIDATE'
    assert value['manifest']==[{'path':'partial.txt','sha256':hashlib.sha256(b'partial').hexdigest(),'size':7}]
    assert value['tree']==full_tree_manifest(driver.requests[0].cwd)
    assert value['receipt']['status']=='COMPLETED'
    assert_controller_unsettled(e)


def test_revocation_during_native_cooperative_stop_has_no_new_native_or_claim(agent_env):
    e=agent_env; publish(e); observed=[]
    def native(request,emit,controls):
        e.registry.revoke(e.node['node_id'])
        deadline=time.monotonic()+3
        while time.monotonic()<deadline and not observed:
            observed.extend(controls()); time.sleep(.02)
        assert observed and all(c['action']=='interrupt' for c in observed)
        assert controls()==[]
        return Receipt('INTERRUPTED',requested_model=request.model)
    agent,driver=execute(e,AgentDriver(native)); run_observe(agent)
    restarted,_=execute(e,driver); run_observe(restarted)
    assert len(driver.requests)==1 and 'INTERRUPTED' in local_dump(e.state)
    assert e.claims.get(e.key)['receipt'] is None


def test_node_secret_never_enters_requests_env_workspace_events_receipt_or_diagnostics(agent_env, caplog, capsys):
    e=agent_env; publish(e); secret=e.node['secret']
    def native(request,emit,controls):
        assert secret not in json.dumps(asdict(request))
        assert secret not in json.dumps(environment())
        assert secret.encode() not in retained_bytes(Path(request.cwd))
        emit('native_event',{'method':'fixture','params':{'text':'Node '+secret,'ordinary':secret}})
        return Receipt('ERROR',output=secret,error='Node '+secret,requested_model=request.model)
    agent,driver=execute(e,AgentDriver(native)); result=run_observe(agent)
    assert secret.encode() not in retained_bytes(e.state)
    assert secret not in str(result)+caplog.text+str(capsys.readouterr())
    assert secret not in json.dumps(e.claims.get(e.key))+str(e.mission.journal.events())
    assert len(driver.requests)==1


def test_default_production_driver_uses_node_own_environment_without_native_execution(agent_env, monkeypatch):
    from sisyfus.workers.codex import CodexDriver
    e=agent_env; publish(e); own_home=str(e.root/'node-owned-home'); seen=[]
    monkeypatch.setenv('HOME',own_home)
    monkeypatch.setenv('UNRELATED_SECRET','not-forwarded')
    def fake_native(self,request,emit,controls):
        seen.append((request,environment(self.env_names)))
        return Receipt('COMPLETED',requested_model=request.model,actual_model=None)
    monkeypatch.setattr(CodexDriver,'run',fake_native)
    agent=e.agent_type(e.auth,e.state); agent.run_once()
    assert len(seen)==1 and seen[0][1]['HOME']==own_home
    assert 'UNRELATED_SECRET' not in seen[0][1]
    assert e.node['secret'] not in json.dumps(asdict(seen[0][0]))+json.dumps(seen[0][1])
    assert e.claims.get(e.key)['receipt']['actual_model'] is None


def test_same_state_concurrent_agent_and_snapshot_identity_are_exclusive(agent_env):
    e=agent_env; publish(e); entered=threading.Event(); release=threading.Event()
    def native(*_):
        entered.set(); assert release.wait(4)
        return Receipt('COMPLETED',requested_model='gpt-6.1-sol')
    agent,driver=execute(e,AgentDriver(native)); failures=[]
    def run():
        try: agent.run_once()
        except Exception as exc: failures.append(exc)
    thread=threading.Thread(target=run); thread.start()
    try:
        assert entered.wait(3)
        started=time.monotonic()
        try:
            other,_=execute(e,driver); result=run_observe(other)
            assert not other is agent
        except (RuntimeError,OSError,ValueError): pass
        assert time.monotonic()-started<3 and len(driver.requests)==1
    finally: release.set(); thread.join(5)
    assert not failures and not thread.is_alive()


def test_actual_gateway_host_is_forwarded_port_independent_and_redirect_is_rejected(agent_env, monkeypatch):
    e=agent_env; publish(e)
    # localhost is accepted actual-server Host even when the chosen connect URL
    # uses 127.0.0.1. Forwarded port selection belongs to operator configuration.
    credentials=e.credentials|{'gateway_host':'localhost:'+str(e.gateway.server_port)}
    e.auth.write_text(json.dumps(credentials)); e.auth.chmod(0o600)
    agent,driver=execute(e); agent.run_once()
    assert len(driver.requests)==1 and e.claims.get(e.key)['status']=='RECEIPTED'


def test_redirect_missing_length_or_oversized_response_never_grants_native(agent_env, monkeypatch):
    e=agent_env; publish(e)
    import sisyfus.workers.node_gateway as gm
    original=gm._Handler._send
    def redirect(self,value,status=200,**kwargs):
        if self.path.endswith('/claim'):
            self.send_response(302); self.send_header('Location',e.gateway.url+'/operator'); self.send_header('Content-Length','0'); self.end_headers(); return
        return original(self,value,status,**kwargs)
    monkeypatch.setattr(gm._Handler,'_send',redirect)
    agent,driver=execute(e); result=run_observe(agent)
    assert not driver.requests and e.claims.get(e.key)['receipt'] is None
    assert 'retained_failure' in (result or {}) or any(w in local_dump(e.state).lower() for w in ['error','redirect','302'])


"""N5 constructor-only draft: concatenate before the main test freeze/RED.

The main module supplies agent_type, importing the public NodeAgent class.
No native execution, network, run_once contract, or private state assumptions.
"""

import json
import os
import socket
import subprocess

import pytest


_AGENT_AUTH_SECRET = "a3" * 32
_AGENT_AUTH_NODE_ID = "node_" + "32" * 16


def auth_file(tmp_path, changes=None):
    """Operator-prepared credential file, separate from state/workspaces."""
    credentials = tmp_path / "operator-credentials"
    credentials.mkdir(mode=0o700, exist_ok=True)
    path = credentials / "node.json"
    data = {
        "schema": 1,
        "controller_mission_id": "m_fixed",
        "node_id": _AGENT_AUTH_NODE_ID,
        "secret": _AGENT_AUTH_SECRET,
        "gateway_url": "http://127.0.0.1:8781",
        "gateway_host": "127.0.0.1:8781",
    }
    if changes is not None:
        data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")
    path.chmod(0o600)
    return path


class _AgentAuthConstructorDriver:
    """Injected protocol fixture; constructing the agent grants no execution."""
    name = "codex"
    controls = ("interrupt",)

    def probe(self):
        pytest.fail("constructor called the injected driver probe")

    def run(self, *args, **kwargs):
        pytest.fail("constructor called the injected native driver")


@pytest.fixture
def _agent_auth_guard(monkeypatch, caplog, capsys):
    from sisyfus.workers.codex import CodexDriver

    def forbidden(*args, **kwargs):
        pytest.fail("constructor attempted native probing/execution or network")

    monkeypatch.setattr(CodexDriver, "probe", forbidden)
    monkeypatch.setattr(CodexDriver, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    yield
    captured = capsys.readouterr()
    for text in (caplog.text, captured.out, captured.err):
        assert _AGENT_AUTH_SECRET not in text
        assert "Node " + _AGENT_AUTH_SECRET not in text


def _agent_auth_rejected(agent_type, credential, state):
    with pytest.raises((ValueError, OSError, RuntimeError)) as caught:
        agent_type(credential, state, driver=_AgentAuthConstructorDriver())
    message = str(caught.value)
    assert message.strip(), "configuration rejection needs a diagnostic"
    assert len(message.encode("utf-8")) <= 4096, "unbounded error diagnostic"
    assert _AGENT_AUTH_SECRET not in message
    assert "Node " + _AGENT_AUTH_SECRET not in message
    assert _AGENT_AUTH_SECRET not in repr(caught.value)


def test_agent_auth_valid_fixture_constructor_only(
    agent_type, tmp_path, _agent_auth_guard
):
    credential = auth_file(tmp_path)
    state = tmp_path / "agent-state"
    agent = agent_type(credential, state, driver=_AgentAuthConstructorDriver())
    assert agent is not None
    assert state.is_dir() and not state.is_symlink()
    assert state.stat().st_mode & 0o777 == 0o700
    assert credential.read_text(encoding="utf-8").find(_AGENT_AUTH_SECRET) >= 0
    assert credential.stat().st_mode & 0o777 == 0o600


def test_agent_auth_default_constructs_existing_codex_without_probe(
    agent_type, tmp_path, monkeypatch, _agent_auth_guard
):
    from sisyfus.workers.codex import CodexDriver

    constructions = []
    original = CodexDriver.__init__

    def record(self, *args, **kwargs):
        constructions.append((args, kwargs))
        original(self, *args, **kwargs)

    monkeypatch.setattr(CodexDriver, "__init__", record)
    agent = agent_type(auth_file(tmp_path), tmp_path / "agent-state")
    assert agent is not None
    assert len(constructions) == 1
    assert _AGENT_AUTH_SECRET not in repr(constructions)


def test_agent_auth_accepts_localhost_forward_with_distinct_actual_host_port(
    agent_type, tmp_path, _agent_auth_guard
):
    credential = auth_file(
        tmp_path,
        {
            "gateway_url": "http://localhost:18781",
            "gateway_host": "127.0.0.1:8781",
        },
    )
    agent = agent_type(credential, tmp_path / "agent-state", driver=_AgentAuthConstructorDriver())
    assert agent is not None


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"gateway_url": None}, id="url-null"),
        pytest.param({"schema": 2}, id="schema-unknown"),
        pytest.param({"schema": True}, id="schema-bool"),
        pytest.param({"schema": "1"}, id="schema-string"),
        pytest.param({"schema": None}, id="schema-null"),
        pytest.param({"controller_mission_id": None}, id="mission-null"),
        pytest.param({"controller_mission_id": 7}, id="mission-number"),
        pytest.param({"controller_mission_id": ""}, id="mission-empty"),
        pytest.param({"controller_mission_id": "../m_fixed"}, id="mission-path"),
        pytest.param({"node_id": None}, id="node-null"),
        pytest.param({"node_id": "node_32"}, id="node-short"),
        pytest.param({"node_id": 7}, id="node-number"),
        pytest.param({"secret": None}, id="secret-null"),
        pytest.param({"secret": "a3"}, id="secret-short"),
        pytest.param({"secret": 7}, id="secret-number"),
        pytest.param({"gateway_url": "https://127.0.0.1:8781"}, id="url-tls"),
        pytest.param({"gateway_url": "http://192.0.2.1:8781"}, id="url-nonloopback"),
        pytest.param({"gateway_url": "http://127.0.0.1:8781/node/v1"}, id="url-path"),
        pytest.param({"gateway_url": "http://127.0.0.1:8781?x=1"}, id="url-query"),
        pytest.param({"gateway_url": "http://127.0.0.1:8781#x"}, id="url-fragment"),
        pytest.param({"gateway_url": "http://127.0.0.1"}, id="url-missing-port"),
        pytest.param({"gateway_url": "http://127.0.0.1:0"}, id="url-zero-port"),
        pytest.param({"gateway_url": "http://127.0.0.1:65536"}, id="url-port-overflow"),
        pytest.param({"gateway_url": "http://u@127.0.0.1:8781"}, id="url-userinfo"),
        pytest.param({"gateway_url": "http://127.0.0.1:8781/"}, id="url-slash-path"),
        pytest.param({"gateway_host": "192.0.2.1:8781"}, id="host-nonloopback"),
        pytest.param({"gateway_host": "127.0.0.1:8781/path"}, id="host-path"),
        pytest.param({"gateway_host": "127.0.0.1"}, id="host-missing-port"),
        pytest.param({"gateway_host": "127.0.0.1:0"}, id="host-zero-port"),
        pytest.param({"gateway_host": "127.0.0.1:65536"}, id="host-port-overflow"),
        pytest.param({"gateway_host": "u@127.0.0.1:8781"}, id="host-userinfo"),
        pytest.param({"gateway_host": None}, id="host-null"),
        pytest.param({"workspace": _AGENT_AUTH_SECRET}, id="unknown-field-secret-scrub"),
    ],
)
def test_agent_auth_rejects_strict_configuration(
    agent_type, tmp_path, _agent_auth_guard, changes
):
    _agent_auth_rejected(agent_type, auth_file(tmp_path, changes), tmp_path / "agent-state")


@pytest.mark.parametrize(
    "case",
    [
        "root-list", "root-null", "root-string", "malformed", "duplicate-schema",
        "duplicate-secret", "nan", "infinity", "negative-infinity", "missing-secret",
    ],
)
def test_agent_auth_rejects_strict_json(
    agent_type, tmp_path, _agent_auth_guard, case
):
    credential = auth_file(tmp_path)
    data = json.loads(credential.read_text(encoding="utf-8"))
    if case == "root-list":
        text = json.dumps([data])
    elif case == "root-null":
        text = "null"
    elif case == "root-string":
        text = json.dumps("Node " + _AGENT_AUTH_SECRET)
    elif case == "malformed":
        text = '{"secret":"' + _AGENT_AUTH_SECRET + '",'
    elif case == "duplicate-schema":
        text = json.dumps(data)[:-1] + ',"schema":1}'
    elif case == "duplicate-secret":
        text = json.dumps(data)[:-1] + ',"secret":"' + _AGENT_AUTH_SECRET + '"}'
    elif case in {"nan", "infinity", "negative-infinity"}:
        token = {"nan": "NaN", "infinity": "Infinity", "negative-infinity": "-Infinity"}[case]
        text = json.dumps(data).replace('"schema": 1', '"schema": ' + token)
    else:
        data.pop("secret")
        text = json.dumps(data)
    credential.write_text(text, encoding="utf-8")
    _agent_auth_rejected(agent_type, credential, tmp_path / "agent-state")


@pytest.mark.parametrize("mode", [0o400, 0o640, 0o644], ids=["0400", "0640", "0644"])
def test_agent_auth_requires_exact_credential_0600(
    agent_type, tmp_path, _agent_auth_guard, mode
):
    credential = auth_file(tmp_path)
    credential.chmod(mode)
    _agent_auth_rejected(agent_type, credential, tmp_path / "agent-state")


def test_agent_auth_requires_current_owner(
    agent_type, tmp_path, monkeypatch, _agent_auth_guard
):
    credential = auth_file(tmp_path)
    other_uid = credential.stat().st_uid + 1
    monkeypatch.setattr(os, "getuid", lambda: other_uid)
    monkeypatch.setattr(os, "geteuid", lambda: other_uid)
    _agent_auth_rejected(agent_type, credential, tmp_path / "agent-state")


def test_agent_auth_rejects_directory_credential(
    agent_type, tmp_path, _agent_auth_guard
):
    credential = tmp_path / "credential-directory"
    credential.mkdir(mode=0o700)
    _agent_auth_rejected(agent_type, credential, tmp_path / "agent-state")


def test_agent_auth_rejects_final_credential_symlink(
    agent_type, tmp_path, _agent_auth_guard
):
    credential = auth_file(tmp_path)
    link = credential.parent / "node-link.json"
    link.symlink_to(credential)
    _agent_auth_rejected(agent_type, link, tmp_path / "agent-state")
    assert link.is_symlink()
    assert credential.exists()


def test_agent_auth_rejects_credential_multiple_links(
    agent_type, tmp_path, _agent_auth_guard
):
    credential = auth_file(tmp_path)
    second = credential.parent / "node-hardlink.json"
    os.link(credential, second)
    assert credential.stat().st_nlink == 2
    _agent_auth_rejected(agent_type, credential, tmp_path / "agent-state")
    assert second.exists()


@pytest.mark.parametrize("case", ["0755", "0777", "regular-file", "root-link"])
def test_agent_auth_rejects_unsafe_existing_state_root(
    agent_type, tmp_path, _agent_auth_guard, case
):
    credential = auth_file(tmp_path)
    state = tmp_path / "agent-state"
    if case in {"0755", "0777"}:
        state.mkdir()
        state.chmod(int(case, 8))
    elif case == "regular-file":
        state.write_text("retained-marker", encoding="utf-8")
    else:
        target = tmp_path / "retained-state-target"
        target.mkdir(mode=0o700)
        state.symlink_to(target, target_is_directory=True)
    original_mode = state.lstat().st_mode
    _agent_auth_rejected(agent_type, credential, state)
    assert state.lstat().st_mode == original_mode, "unsafe root must not be silently repaired"
    if case == "regular-file":
        assert state.read_text(encoding="utf-8") == "retained-marker"
    if case == "root-link":
        assert state.is_symlink() and target.exists()


def test_agent_auth_rejects_credential_nested_in_state(
    agent_type, tmp_path, _agent_auth_guard
):
    state = tmp_path / "agent-state"
    state.mkdir(mode=0o700)
    credential = auth_file(state)
    _agent_auth_rejected(agent_type, credential, state)
    assert credential.exists()


def test_agent_auth_rejects_oversized_credential_with_bounded_scrubbed_error(
    agent_type, tmp_path, _agent_auth_guard
):
    credential = auth_file(tmp_path)
    # Keep every field valid: only the total credential-file size is excessive.
    credential.write_text(
        credential.read_text(encoding="utf-8") + " " * (2 * 1024 * 1024),
        encoding="utf-8",
    )
    _agent_auth_rejected(agent_type, credential, tmp_path / "agent-state")


def test_agent_auth_rejects_missing_credential_with_diagnostic(
    agent_type, tmp_path, _agent_auth_guard
):
    _agent_auth_rejected(agent_type, tmp_path / "not-prepared.json", tmp_path / "agent-state")
