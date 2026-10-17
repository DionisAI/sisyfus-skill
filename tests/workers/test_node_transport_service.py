"""Frozen transport service: controller-owned local fixtures, not native acceptance.

Binding: {mission_id,run_key,root,manifest,manifest_hash,reservation_fingerprint}.
status/withdraw return old views, plus tree only for stored new tree evidence.
post_controls: [{id,action,text,status}]; pending: [{id,action,text}].
Bounds: 100 controls, 200 UTF-8 bytes/id, 32_000 bytes/list; reason 2000 bytes.
Tree: 128 files, 4096 nodes/errors, path 1000 bytes, kind/code 128 bytes, hash
64 bytes, 1_000_000 normalized bytes. Diagnostic paths need not be transferable.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading

import pytest

from sisyfus.autonomy.models import OpportunitySignal, canonical_json
from sisyfus.autonomy.policy import IdempotencyConflictError, LeaseLost
from sisyfus.autonomy.store import AutonomyStore
import sisyfus.workers.journal as journal_module
from sisyfus.workers.journal import Journal
from sisyfus.workers.lead_journal import LeadJournal
import sisyfus.workers.node_claims as module
from sisyfus.workers.node_claims import NodeClaims
from sisyfus.workers.node_registry import NodeRegistry
from sisyfus.workers.protocol import Receipt, Request, digest, redact


class Clock:
    def __init__(self): self.value = 1000.0
    def __call__(self): return self.value
    def advance(self, seconds): self.value += seconds
    def utc(self):
        return datetime.fromtimestamp(self.value, timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def meta(path, data):
    return {'path':path, 'sha256':hashlib.sha256(data).hexdigest(), 'size':len(data)}


def put(root, path, data):
    target=root/path
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as stream: stream.write(data)
    return target


@dataclass
class Fixture:
    journal: Journal
    registry: NodeRegistry
    claims: NodeClaims
    node: str
    foreign: str
    clock: Clock
    continuation: dict
    request: Request
    root: Path
    manifest: dict
    claim: dict | None = None


@pytest.fixture
def env(tmp_path,monkeypatch):
    clock=Clock()
    monkeypatch.setattr(journal_module,'utc_now',clock.utc)
    journal=Journal(AutonomyStore(tmp_path/'autonomy.sqlite3'))
    journal.bind({'parallelism':10,'max_calls':None,'acceptance_hash':'immutable',
                  'checks':{'fixed':{'sha':'unchanged'}},'tasks':[{'id':'build','driver':'codex'}]})
    opp,_=journal.store.submit_opportunity(OpportunitySignal('transport-fixture','input','fixed task'),now=clock.utc())
    journal.store.admit_opportunity(opp['id'],now=clock.utc())
    continuation=journal.store.claim_due_continuation('controller',lease_seconds=60,now=clock.utc())
    registry=NodeRegistry(journal)
    node=registry.enroll('enroll_transport_a','A',['codex'],['gpt-6.1-sol'])['node_id']
    foreign=registry.enroll('enroll_transport_b','B',['codex'],['gpt-6.1-sol'])['node_id']
    cwd,root=tmp_path/'workspace',tmp_path/'snapshot'
    for folder in [cwd,root]:
        put(folder,'a.txt',b'alpha');put(folder,'sub/b.txt',b'beta')
    request=Request('build','Fixed task.',str(cwd),'gpt-6.1-sol',mode='workspace-write')
    journal.reserve('run-a','build',digest(asdict(request)),continuation_id=continuation['id'],lease_token=continuation['lease_token'])
    claims=NodeClaims(journal,registry,tmp_path/'retained-artifacts',clock=clock)
    manifest={'files':[meta('a.txt',b'alpha'),meta('sub/b.txt',b'beta')],'output_paths':['partial.txt','result.txt']}
    return Fixture(journal,registry,claims,node,foreign,clock,continuation,request,root,manifest)


def dump(env):
    with env.journal.store._transaction(immediate=False) as db: return '\n'.join(db.iterdump())


def unchanged(env,before):
    assert dump(env)==before
    assert env.journal.store.verify_event_chain()['valid']


def bind(env): return env.claims.bind_input_snapshot('run-a',env.root,env.manifest)
def offer(env,bound=True):
    if bound: bind(env)
    return env.claims.offer('run-a',env.node,env.request,env.manifest)
def claimed(env,bound=True):
    offer(env,bound)
    env.claim=env.claims.claim(env.node,'claim_transport_a')['claim']
    return env.claim
def owner(env,**changes):
    return {'node_id':env.node,'claim_id':env.claim['claim_id'],'epoch':env.claim['epoch']}|changes
def status(env,**changes): return env.claims.status(**owner(env,**changes))
def pending(env,**changes): return env.claims.pending_controls(**owner(env,**changes))
def read(env,path='a.txt',**changes): return env.claims.read_input(path=path,**owner(env,**changes))
def receive(env,report,native='COMPLETED',files=None):
    return env.claims.receipt(**owner(env),receipt=Receipt(native),manifest=[] if files is None else files,tree=report)
def tree(files=None,nodes=None,errors=None,complete=True):
    files=[] if files is None else files
    return {'schema':1,'files':files,'tree':[dict(f,kind='file') for f in files] if nodes is None else nodes,
            'errors':[] if errors is None else errors,'complete':complete}
def control(ident='interrupt-1'): return {'id':ident,'action':'interrupt','text':''}
def ack(seq,ident,accepted=True):
    return {'seq':seq,'kind':'control_ack','data':{'command_id':ident,'accepted':accepted}}
def upload(env,path='result.txt',data=b'result'):
    return env.claims.upload(**owner(env),path=path,sha256=hashlib.sha256(data).hexdigest(),data=data)
def reboot(env,cls=Journal):
    journal=cls(AutonomyStore(env.journal.store.path));registry=NodeRegistry(journal)
    env.claims=NodeClaims(journal,registry,env.claims.artifact_root,clock=env.clock)
    env.journal,env.registry=journal,registry


def test_pin_run_manifest_snapshot_and_replay_not_mutable_cwd(env):
    pinned=bind(env)
    assert pinned=={'mission_id':env.registry.mission_id,'run_key':'run-a','root':str(env.root),
                    'manifest':env.manifest,'manifest_hash':digest(env.manifest),
                    'reservation_fingerprint':digest(asdict(env.request))}
    before=dump(env);assert bind(env)==pinned;unchanged(env,before)
    Path(env.request.cwd,'a.txt').write_bytes(b'changed source')
    offered=env.claims.offer('run-a',env.node,env.request,env.manifest)
    assert offered['input_manifest_hash']==pinned['manifest_hash']
    env.claim=env.claims.claim(env.node,'claim_transport_a')['claim']
    before=dump(env)
    assert read(env)==b'alpha' and read(env,'sub/b.txt')==b'beta'
    unchanged(env,before)
    (env.root/'sub/b.txt').write_bytes(b'corrupt other package member')
    with pytest.raises(ValueError): read(env)
    unchanged(env,before)


@pytest.mark.parametrize('cls',[Journal,LeadJournal])
def test_restart_read_status_controls_and_cached_identity(env,cls):
    pin=bind(env);claimed(env);env.claims.post_controls('run-a',[control()])
    reboot(env,cls);before=dump(env)
    assert bind(env)==pin and read(env)==b'alpha'
    assert pending(env)==[control()] and status(env)==env.claims.get('run-a')
    unchanged(env,before)
    env.clock.advance(30);before=dump(env)
    assert status(env)['status']=='CLAIMED';unchanged(env,before)
    assert env.claims.claim(env.node,'claim_transport_a')['claim']==env.claim
    assert status(env)['status']=='UNKNOWN' and env.journal.runs()[0]['status']=='IN_FLIGHT'


@pytest.mark.parametrize('change',['root','manifest','historical'])
def test_binding_conflicts_and_no_backfill(env,tmp_path,change):
    if change=='historical': offer(env,False)
    else: bind(env)
    root,manifest=env.root,json.loads(canonical_json(env.manifest))
    if change=='root':
        root=tmp_path/'other';put(root,'a.txt',b'alpha');put(root,'sub/b.txt',b'beta')
    elif change=='manifest': manifest['output_paths']=['different.txt']
    before=dump(env)
    with pytest.raises(IdempotencyConflictError): env.claims.bind_input_snapshot('run-a',root,manifest)
    unchanged(env,before)


def test_bound_offer_pin_and_unprepared_snapshot_reject_without_offer(env):
    bind(env);before=dump(env)
    with pytest.raises(IdempotencyConflictError):
        env.claims.offer('run-a',env.node,env.request,dict(env.manifest,output_paths=['different.txt']))
    unchanged(env,before)
    (env.root/'a.txt').write_bytes(b'corrupt')
    with pytest.raises(ValueError): env.claims.offer('run-a',env.node,env.request,env.manifest)
    unchanged(env,before)


@pytest.mark.parametrize('loss',['missing','terminal','token','expiry'])
def test_first_binding_requires_real_live_run(env,loss):
    key='absent' if loss=='missing' else 'run-a'
    if loss=='terminal': env.journal.complete('run-a',{'status':'UNKNOWN'})
    elif loss in {'token','expiry'}:
        with env.journal.store._transaction() as db:
            if loss=='token': db.execute("UPDATE continuations SET lease_token='other'")
            else: db.execute('UPDATE continuations SET lease_expires_at=?',(env.clock.utc(),))
    before=dump(env)
    with pytest.raises(LeaseLost): env.claims.bind_input_snapshot(key,env.root,env.manifest)
    unchanged(env,before)


@pytest.mark.parametrize('bad',['../parent','/absolute','a//b',r'a\b','a/./b','.hidden',
                               'a/auth.json','credentials.json','a\x00b','a\nb',None,3])
def test_binding_paths_are_strict(env,bad):
    before=dump(env)
    with pytest.raises(ValueError):
        env.claims.bind_input_snapshot('run-a',env.root,dict(env.manifest,output_paths=[bad]))
    unchanged(env,before)


@pytest.mark.parametrize('manifest',[None,[],{},dict(files=[],output_paths=[],argv=[]),
    dict(files=None,output_paths=[]),dict(files=[],output_paths=None),
    dict(files=[],output_paths=['A/x','a/y']),dict(files=[],output_paths=['x','x']),
    dict(files=[{'path':'a.txt','sha256':'0'*64,'size':True}],output_paths=[]),
    dict(files=[{'path':'a.txt','sha256':'0'*64,'size':8_000_001}],output_paths=[]),
    dict(files=[meta(f'f{i}',b'') for i in range(129)],output_paths=[]),
    dict(files=[{'path':f'f{i}','sha256':'0'*64,'size':8_000_000} for i in range(5)],output_paths=[])])
def test_binding_manifest_types_counts_total_bounds(env,manifest):
    before=dump(env)
    with pytest.raises(ValueError): env.claims.bind_input_snapshot('run-a',env.root,manifest)
    unchanged(env,before)


@pytest.mark.parametrize('root',['relative','/private/tmp/../x',None,5,'/private/tmp/x\x00y'])
def test_root_only_fixed_absolute_controller_path(env,root):
    before=dump(env)
    with pytest.raises(ValueError): env.claims.bind_input_snapshot('run-a',root,env.manifest)
    unchanged(env,before)


@pytest.mark.parametrize('kind',['root-link','ancestor-link','leaf-link','hardlink','fifo','directory','corrupt'])
def test_binding_no_follow_single_link_regular_and_hash(env,tmp_path,kind):
    leaf=env.root/'a.txt'
    if kind in {'root-link','ancestor-link'}:
        link=tmp_path/'link'
        link.symlink_to(env.root if kind=='root-link' else env.root.parent,target_is_directory=True)
        env.root=link if kind=='root-link' else link/env.root.name
    elif kind=='hardlink': os.link(leaf,tmp_path/'retained-hardlink')
    elif kind=='corrupt': leaf.write_bytes(b'bad')
    else:
        leaf.rename(env.root/'retained-original.txt')
        if kind=='leaf-link': leaf.symlink_to(tmp_path/'unread-private-fixture')
        elif kind=='fifo': os.mkfifo(leaf)
        else: leaf.mkdir()
    before=dump(env)
    with pytest.raises((OSError,ValueError)): bind(env)
    unchanged(env,before)


@pytest.mark.parametrize('operation',['bind','offer'])
def test_binding_or_bound_offer_rechecks_core_after_io(env,monkeypatch,operation):
    if operation=='offer': bind(env)
    original=module.os.read;acted=[]
    def crossing(fd,length):
        data=original(fd,length)
        if data and not acted: acted.append(True);env.clock.advance(60)
        return data
    before=dump(env)
    with monkeypatch.context() as patch:
        patch.setattr(module.os,'read',crossing)
        with pytest.raises(LeaseLost):
            if operation=='bind': bind(env)
            else: env.claims.offer('run-a',env.node,env.request,env.manifest)
    unchanged(env,before)


def test_legacy_unbound_claim_same_projection_and_no_input_grant(env):
    claimed(env,False);before=dump(env)
    assert status(env)==env.claim and 'tree' not in status(env)
    with pytest.raises(FileNotFoundError): read(env)
    with pytest.raises(IdempotencyConflictError): bind(env)
    unchanged(env,before)


@pytest.mark.parametrize('path',['not-bound.txt','result.txt','../a.txt','/a.txt',r'sub\b.txt','x\x00y'])
def test_read_whitelist(env,path):
    claimed(env);before=dump(env)
    with pytest.raises(FileNotFoundError if path in {'not-bound.txt','result.txt'} else ValueError): read(env,path)
    unchanged(env,before)


@pytest.mark.parametrize('action',['node-time','core-time','node-revoke','core-token','core-terminal'])
def test_after_io_checks_use_fresh_database_not_old_read_snapshot(env,monkeypatch,action):
    claimed(env);original=module.os.read;acted=[]
    def crossing(fd,length):
        data=original(fd,length)
        if data and not acted:
            acted.append(True)
            if action=='node-time': env.clock.advance(30)
            elif action=='core-time':
                with env.journal.store._transaction() as db: db.execute('UPDATE continuations SET lease_expires_at=?',(env.clock.utc(),))
            elif action=='node-revoke': env.registry.revoke(env.node)
            elif action=='core-token':
                with env.journal.store._transaction() as db: db.execute("UPDATE continuations SET lease_token='other'")
            else: env.journal.complete('run-a',{'status':'UNKNOWN'})
        return data
    with monkeypatch.context() as patch:
        patch.setattr(module.os,'read',crossing)
        with pytest.raises(PermissionError if action=='node-revoke' else LeaseLost): read(env)
    assert acted==[True] and env.claims.get('run-a')['status']=='CLAIMED'
    assert env.claims.get('run-a')['lease_expires_at']==1030
    assert env.journal.store.verify_event_chain()['valid']


@pytest.mark.parametrize('swap',['leaf','parent','root'])
def test_snapshot_replacement_during_read_fenced_without_removing_files(env,monkeypatch,tmp_path,swap):
    claimed(env);original=module.os.read;acted=[]
    def crossing(fd,length):
        data=original(fd,length)
        if data and not acted:
            acted.append(True)
            if swap=='leaf':
                (env.root/'a.txt').rename(env.root/'retained-a.txt');put(env.root,'a.txt',b'alpha')
            elif swap=='parent':
                (env.root/'sub').rename(env.root/'retained-sub')
                (env.root/'sub').symlink_to(tmp_path/'private-fixture',target_is_directory=True)
            else:
                env.root.rename(tmp_path/'retained-snapshot')
                env.root.mkdir();put(env.root,'a.txt',b'alpha');put(env.root,'sub/b.txt',b'beta')
        return data
    before=dump(env)
    with monkeypatch.context() as patch:
        patch.setattr(module.os,'read',crossing)
        with pytest.raises((OSError,ValueError)): read(env)
    assert acted==[True];unchanged(env,before)


@pytest.mark.parametrize('api',['read','pending'])
@pytest.mark.parametrize('loss',['foreign','missing','epoch','bool-epoch','revoked','expired','core-expired','core-token','terminal'])
def test_live_query_ownership_and_two_leases(env,api,loss):
    claimed(env);changes={}
    if loss=='foreign': changes['node_id']=env.foreign
    elif loss=='missing': changes['claim_id']='absent'
    elif loss=='epoch': changes['epoch']=2
    elif loss=='bool-epoch': changes['epoch']=True
    elif loss=='revoked': env.registry.revoke(env.node)
    elif loss=='expired': env.clock.advance(30)
    elif loss in {'core-expired','core-token'}:
        with env.journal.store._transaction() as db:
            if loss=='core-expired': db.execute('UPDATE continuations SET lease_expires_at=?',(env.clock.utc(),))
            else: db.execute("UPDATE continuations SET lease_token='other'")
    else: env.claims.receipt(**owner(env),receipt=Receipt('COMPLETED'),manifest=[])
    before=dump(env)
    with pytest.raises(PermissionError if loss in {'foreign','missing','revoked'} else LeaseLost):
        (read if api=='read' else pending)(env,**changes)
    unchanged(env,before)


@pytest.mark.parametrize('loss',['expired','revoked','core-expired','unknown','candidate','receipted'])
def test_status_reads_historical_own_identity_never_renews_or_expires(env,loss):
    claimed(env)
    if loss=='expired': env.clock.advance(30)
    elif loss=='revoked': env.registry.revoke(env.node)
    elif loss=='core-expired': env.clock.advance(60)
    elif loss=='unknown': env.claims.receipt(**owner(env),receipt=Receipt('UNKNOWN'),manifest=[])
    elif loss=='candidate': env.clock.advance(30);env.claims.receipt(**owner(env),receipt=Receipt('ERROR'),manifest=[])
    else: env.claims.receipt(**owner(env),receipt=Receipt('COMPLETED'),manifest=[])
    reboot(env);before=dump(env)
    assert status(env)==env.claims.get('run-a')
    for changes,error in [({'node_id':env.foreign},PermissionError),({'epoch':2},LeaseLost),({'epoch':True},LeaseLost),({'node_id':None},ValueError)]:
        with pytest.raises(error): status(env,**changes)
    unchanged(env,before);assert env.journal.runs()[0]['status']=='IN_FLIGHT'


def test_withdraw_only_unclaimed_is_retained_idempotent_and_not_core_settlement(env):
    prior=offer(env)
    result=env.claims.withdraw('run-a','controller cancelled')
    assert result==prior|{'status':'WITHDRAWN'}
    before=dump(env)
    assert env.claims.withdraw('run-a','controller cancelled')==result
    with pytest.raises(IdempotencyConflictError): env.claims.withdraw('run-a','different reason')
    unchanged(env,before)
    assert env.claims.claim(env.node,'claim_transport_a')['status']=='NO_WORK' and env.claims.expire()==[]
    assert env.journal.runs()[0]['status']=='IN_FLIGHT' and env.journal.runs()[0]['receipt'] is None
    assert sum(e['type']=='WORKER_NODE_WITHDRAWN' for e in env.journal.events(0,1000))==1


@pytest.mark.parametrize('reason',[None,4,'',' ','x'*2001,'\ud800'])
def test_withdraw_reason_errors(env,reason):
    offer(env);before=dump(env)
    with pytest.raises(ValueError): env.claims.withdraw('run-a',reason)
    unchanged(env,before)


@pytest.mark.parametrize('state',['claimed','unknown','candidate','receipted'])
def test_withdraw_never_relabels_claimed_unknown_or_terminal(env,state):
    claimed(env)
    if state=='unknown': env.clock.advance(30);env.claims.expire()
    elif state=='candidate': env.clock.advance(30);receive(env,tree(),native='ERROR')
    elif state=='receipted': receive(env,tree())
    prior=status(env);before=dump(env)
    assert env.claims.withdraw('run-a','stop')==prior
    unchanged(env,before)


@pytest.mark.parametrize('attempt',range(4))
def test_claim_withdraw_race_single_transaction_winner(env,attempt):
    offer(env);gate=threading.Barrier(2)
    def claim(): gate.wait();return env.claims.claim(env.node,'claim_transport_a')
    def withdraw(): gate.wait();return env.claims.withdraw('run-a','cancel')
    with ThreadPoolExecutor(max_workers=2) as pool:
        one,two=pool.submit(claim),pool.submit(withdraw)
        result,withdrawn=one.result(timeout=10),two.result(timeout=10)
    current=env.claims.get('run-a')
    if result['status']=='CLAIMED':
        assert withdrawn['status']==current['status']=='CLAIMED' and current['epoch']==1
    else:
        assert result['status']=='NO_WORK' and withdrawn['status']==current['status']=='WITHDRAWN'
        assert current['epoch']==0 and current['claim_id'] is None
    assert env.journal.runs()[0]['status']=='IN_FLIGHT'
    assert env.journal.store.verify_event_chain()['valid']


def test_controls_read_only_delivery_retry_restart_separate_ack(env):
    claimed(env)
    result=env.claims.post_controls('run-a',[control(),control(),control('interrupt-2')])
    assert result==[control()|{'status':'PENDING'},control('interrupt-2')|{'status':'PENDING'}]
    before=dump(env)
    assert env.claims.post_controls('run-a',[control(),control('interrupt-2')])==result
    assert pending(env)==[control(),control('interrupt-2')] and pending(env)==[control(),control('interrupt-2')]
    unchanged(env,before);reboot(env);before=dump(env)
    assert pending(env)==[control(),control('interrupt-2')];unchanged(env,before)
    env.claims.sync(**owner(env),events=[ack(1,'interrupt-1')])
    assert pending(env)==[control('interrupt-2')]
    assert env.claims.post_controls('run-a',[control()])==[control()|{'status':'ACK'}]
    before=dump(env);env.claims.sync(**owner(env),events=[ack(1,'interrupt-1')]);unchanged(env,before)


def test_transport_and_journal_ack_callback_rollback_and_rejection(env):
    claimed(env);command=env.journal.command('run-a','interrupt');env.journal.controls('run-a')
    env.claims.post_controls('run-a',[control(command)])
    before=dump(env)
    def broken(db,key,kind,data):
        assert key=='run-a' and kind=='control_ack'
        assert db.execute('SELECT status FROM native_worker_commands WHERE id=?',(command,)).fetchone()[0]=='SENT'
        raise ValueError('fixture ACK hook rollback')
    env.journal.after_event=broken
    with pytest.raises(ValueError,match='ACK hook rollback'): env.claims.sync(**owner(env),events=[ack(1,command)])
    unchanged(env,before);assert pending(env)==[control(command)]
    env.journal.after_event=None
    env.claims.sync(**owner(env),events=[ack(1,command,False)])
    assert pending(env)==[] and env.claims.post_controls('run-a',[control(command)])[0]['status']=='REJECTED'
    with env.journal.store._transaction(immediate=False) as db:
        assert db.execute('SELECT status FROM native_worker_commands WHERE id=?',(command,)).fetchone()[0]=='REJECTED'


def test_global_control_id_conflict_and_foreign_unknown_ack_no_authority(env):
    claimed(env);env.journal.reserve('run-b','build',digest('B'))
    env.claims.offer('run-b',env.foreign,env.request,env.manifest)
    env.claims.post_controls('run-b',[control('foreign-interrupt')])
    before=dump(env)
    with pytest.raises(IdempotencyConflictError): env.claims.post_controls('run-a',[control('foreign-interrupt')])
    unchanged(env,before)
    env.claims.sync(**owner(env),events=[ack(1,'foreign-interrupt'),ack(2,'unknown-interrupt')])
    assert env.claims.post_controls('run-b',[control('foreign-interrupt')])[0]['status']=='PENDING'
    assert pending(env)==[] and env.journal.runs()[0]['status']=='IN_FLIGHT'


@pytest.mark.parametrize('controls',[None,{},(),[None],[{}],[{'id':'x','action':'interrupt'}],
    [dict(control(),argv=['sh'])],[dict(control(),action='steer')],[dict(control(),text='run')],
    [dict(control(),text=None)],[dict(control(),id=True)],[dict(control(),id='')],
    [dict(control(),id='x'*201)],[dict(control(),id='Bearer FIXTURE_SECRET')],
    [control(str(i)) for i in range(101)]])
def test_interrupt_fixed_fields_types_and_bounds(env,controls):
    claimed(env);before=dump(env)
    with pytest.raises(ValueError): env.claims.post_controls('run-a',controls)
    unchanged(env,before)


def test_empty_controls_read_only_and_exact_100_limit(env):
    claimed(env);before=dump(env)
    assert env.claims.post_controls('run-a',[])==[] and pending(env)==[]
    unchanged(env,before)
    values=[control(str(i)) for i in range(100)]
    assert len(env.claims.post_controls('run-a',values))==100 and pending(env)==values


def test_tree_receipt_replay_redaction_conditional_projection_no_core_settlement(env):
    claimed(env);upload(env);files=[meta('result.txt',b'result')]
    evidence=tree(files,errors=[{'code':'diagnostic','path':'Bearer FIXTURE_SECRET'}],complete=False)
    result=receive(env,evidence,files=files)
    assert result['tree']==redact(evidence) and result['status']=='RECEIPTED' and status(env)==result
    assert env.claims.get('run-a')=={k:v for k,v in result.items() if k!='tree'}
    assert env.journal.runs()[0]['status']=='IN_FLIGHT' and env.journal.runs()[0]['receipt'] is None
    assert env.journal.runs()[0]['verdict']=='UNVERIFIED'
    assert 'FIXTURE_SECRET' not in dump(env) and digest(evidence) in dump(env)
    reboot(env);before=dump(env)
    assert receive(env,json.loads(canonical_json(evidence)),files=files)==result
    assert env.claims.receipt(**owner(env),receipt=Receipt('COMPLETED'),manifest=files)==env.claims.get('run-a')
    unchanged(env,before)
    changed=json.loads(canonical_json(evidence));changed['errors'][0]['path']='Bearer FIXTURE_OTHER_SECRET'
    assert redact(changed)==redact(evidence)
    with pytest.raises(IdempotencyConflictError): receive(env,changed,files=files)
    unchanged(env,before)


def test_legacy_receipt_no_tree_backfill(env):
    claimed(env,False);prior=env.claims.receipt(**owner(env),receipt=Receipt('ERROR'),manifest=[])
    assert 'tree' not in prior and status(env)==prior
    before=dump(env)
    with pytest.raises(IdempotencyConflictError): receive(env,tree(),native='ERROR')
    unchanged(env,before)


DIAGNOSTICS=[
    tree(nodes=[{'path':'.git/config','kind':'file','size':4096}],errors=[{'code':'unsafe_path','path':'.git/config'}]),
    tree(nodes=[{'path':'link','kind':'symlink'},{'path':'pipe','kind':'fifo'}],
         errors=[{'code':'symlink','path':'link'},{'code':'non_regular','path':'pipe'}]),
    tree(nodes=[{'path':'auth.json','kind':'file','size':8_000_001}],
         errors=[{'code':'unsafe_path','path':'auth.json'},{'code':'file_size','path':'auth.json'}]),
    tree(nodes=[{'path':'/unsafe','kind':'file','size':1},{'path':'bad\x00path','kind':'device'}],complete=False),
    tree(files=[{'path':'unbacked.txt','sha256':'invalid-hash','size':1}],nodes=[]),
    tree(errors=[{'code':'root','path':''}],complete=False)]


@pytest.mark.parametrize('native',['COMPLETED','ERROR','UNKNOWN'])
@pytest.mark.parametrize('report',DIAGNOSTICS)
def test_semantic_tree_diagnostics_keep_known_terminal_fact_not_success_evidence(env,native,report):
    claimed(env);result=receive(env,report,native=native)
    assert result['receipt']['status']==native and result['tree']==report
    assert result['status']==('UNKNOWN' if native=='UNKNOWN' else 'RECEIPTED')
    assert env.journal.runs()[0]['status']=='IN_FLIGHT' and env.journal.runs()[0]['verdict']=='UNVERIFIED'
    assert env.journal.store.verify_event_chain()['valid']


@pytest.mark.parametrize('cause',['expired','revoked','core-lost'])
@pytest.mark.parametrize('native',['ERROR','UNKNOWN'])
@pytest.mark.parametrize('stored',[False,True],ids=['empty-stored-subset','stored-and-preparing'])
def test_late_tree_stored_subset_preparing_retained_without_settlement(env,monkeypatch,cause,native,stored):
    claimed(env)
    if stored: upload(env)
    original=module.os.write;wrote=[]
    def interrupted(fd,data):
        if wrote: raise OSError('fixture interrupted upload')
        wrote.append(True);return original(fd,data[:2])
    with monkeypatch.context() as patch:
        patch.setattr(module.os,'write',interrupted)
        with pytest.raises(OSError): upload(env,'partial.txt',b'partial-data')
    partial=env.claims.artifact_root/env.claim['claim_id']/'partial.txt'
    original_file=partial.stat().st_ino,partial.stat().st_mtime_ns,partial.read_bytes()
    if cause=='expired': env.clock.advance(30)
    elif cause=='revoked': env.registry.revoke(env.node)
    else:
        with env.journal.store._transaction() as db: db.execute("UPDATE continuations SET lease_token='other'")
    files=[meta('result.txt',b'result')] if stored else []
    report=tree(files,nodes=[*[dict(f,kind='file') for f in files],{'path':'partial.txt','kind':'file','size':2}],
                errors=[{'code':'tree_changed','path':'partial.txt'}],complete=False)
    result=receive(env,report,native=native,files=files)
    assert result['status']=='RECONCILIATION_CANDIDATE' and result['tree']==report
    assert result['manifest']==files and result['receipt']['status']==native
    assert (partial.stat().st_ino,partial.stat().st_mtime_ns,partial.read_bytes())==original_file
    assert next(u for u in result['uploads'] if u['path']=='partial.txt')['status']=='PREPARING'
    event=next(e for e in reversed(env.journal.events(0,1000)) if e['type']=='WORKER_NODE_RECEIPT')
    assert event['data']['incomplete_paths']==['partial.txt'] and env.journal.runs()[0]['status']=='IN_FLIGHT'
    before=dump(env);assert receive(env,report,native=native,files=files)==result;unchanged(env,before)


def test_tree_receipt_event_failure_rolls_back_and_retry(env,monkeypatch):
    claimed(env);upload(env);files=[meta('result.txt',b'result')];report=tree(files)
    original=env.claims._event;before=dump(env)
    def broken(db,kind,key,data):
        if kind=='receipt': raise ValueError('fixture tree/receipt failure')
        return original(db,kind,key,data)
    with monkeypatch.context() as patch:
        patch.setattr(env.claims,'_event',broken)
        with pytest.raises(ValueError,match='tree/receipt failure'): receive(env,report,files=files)
    unchanged(env,before)
    assert status(env)['receipt'] is None and 'tree' not in status(env)
    assert receive(env,report,files=files)['tree']==report


BAD_TREE=[None,[],{},dict(tree(),schema=True),dict(tree(),schema=2),dict(tree(),complete=1),
    dict(tree(),complete=None),dict(tree(),files=None),dict(tree(),tree={}),dict(tree(),errors={}),dict(tree(),extra='authority'),
    tree(nodes=[{}]),tree(nodes=[{'path':None,'kind':'file'}]),tree(nodes=[{'path':'x','kind':False}]),
    tree(nodes=[{'path':'x','kind':'file','size':True}]),tree(nodes=[{'path':'x','kind':'file','size':-1}]),
    tree(nodes=[{'path':'x','kind':'file','sha256':None}]),tree(nodes=[{'path':'x','kind':'file','content':'private'}]),
    tree(nodes=[{'path':'x'*1001,'kind':'directory'}]),tree(nodes=[{'path':'x','kind':'k'*129}]),
    tree(nodes=[{'path':'x','kind':'file','sha256':'h'*65}]),tree(errors=[{'code':'x','path':[]}]),
    tree(errors=[{'code':False,'path':'x'}]),tree(errors=[{'code':'x','path':'x','more':[]}]),
    tree(errors=[{'code':'c'*129,'path':'x'}]),tree(nodes=[{'path':'\ud800','kind':'file'}]),
    tree(nodes=[{'path':'x','kind':'file','size':float('nan')}]),
    tree(files=[{'path':'x','sha256':'0'*64,'size':False}]),tree(files=[{'path':'x','size':1}]),
    tree(nodes=[{'path':f'd{i}','kind':'directory'} for i in range(4097)]),
    tree(errors=[{'code':'x','path':''} for _ in range(4097)]),
    tree(files=[meta(f'f{i}',b'') for i in range(129)]),
    tree(nodes=[{'path':'x'*700+str(i),'kind':'directory'} for i in range(1500)])]


@pytest.mark.parametrize('report',BAD_TREE)
def test_tree_schema_types_json_encoding_and_bounds_fail_before_expire(env,report):
    claimed(env);env.clock.advance(30);before=dump(env)
    with pytest.raises(ValueError): receive(env,report)
    unchanged(env,before);assert env.claims.get('run-a')['status']=='CLAIMED'


def test_exact_4096_tree_nodes_retained_never_auto_verified(env):
    claimed(env);report=tree(nodes=[{'path':f'd{i}','kind':'directory'} for i in range(4096)])
    result=receive(env,report)
    assert result['tree']==report and result['status']=='RECEIPTED'
    assert env.journal.runs()[0]['status']=='IN_FLIGHT' and env.journal.runs()[0]['verdict']=='UNVERIFIED'


def test_tree_receipt_foreign_epoch_and_bool_epoch_no_evidence_write(env):
    claimed(env);before=dump(env)
    for changes,error in [({'node_id':env.foreign},PermissionError),({'epoch':2},LeaseLost),({'epoch':True},LeaseLost)]:
        with pytest.raises(error):
            env.claims.receipt(**owner(env,**changes),receipt=Receipt('ERROR'),manifest=[],tree=tree())
    unchanged(env,before)
