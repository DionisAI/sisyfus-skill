"""ADDITIONAL_VERIFICATION: one real public worker/transport/materialization flow.

Only NodeAgent's driver is a named protocol fixture, never a native provider.
Actual HTTP loss occurs after a real service commit at the original send seam.
Fresh Agent objects read the same durable state; this is not process/host/device
acceptance. No original tests/helpers, service wrappers or driver aliases used.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import sqlite3
import stat
import sys
import threading
import time

import pytest

from sisyfus.autonomy.policy import LeaseLost
from sisyfus.workers.lead_console import MissionHub
from sisyfus.workers.lead_mission import LeadMission
from sisyfus.workers.node_agent import NodeAgent
from sisyfus.workers import node_gateway
from sisyfus.workers.protocol import Receipt, digest, environment
from sisyfus.workers.remote_artifacts import full_tree_manifest
from sisyfus.workers.remote_driver import RemoteCodexDriver


INPUTS = {'README.md': b'fixed protocol project\n', 'result.bin': b'old\x00\xff',
          'nested/input.bin': b'fixed\x00\xfe\n'}
OUTPUTS = {'nested/new.bin': b'added\x00\xff\n', 'result.bin': b'changed\x00\xfe\n'}


def _put(root, path, data):
    target = Path(root) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as file:
        file.write(data)


def _read_db(path, tables):
    db = sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True, timeout=.5)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        return {table: [dict(row) for row in db.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]
                for table in tables}
    finally:
        db.close()


def _local(e):
    return _read_db(e.state / 'agent.sqlite3', ('attempts', 'outbox', 'uploads', 'controls', 'diagnostics'))


def _attempt(e):
    rows = _local(e)['attempts']
    assert len(rows) == 1
    return rows[0]


def _status(e):
    basic = e.claims.get(e.key)
    assert basic is not None and basic['claim_id'] and 'tree' not in basic
    return e.claims.status(e.node['node_id'], basic['claim_id'], basic['epoch'])


def _wait(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('bounded public pipeline condition not observed')


class ScriptedDriver:
    """The sole injected driver: protocol run count, not an OS/native spawn."""
    def __init__(self, e, mode='normal'):
        self.e, self.mode, self.requests = e, mode, []
        self.inputs = None

    def run(self, request, emit, controls):
        e = self.e
        self.requests.append(request)
        assert len(self.requests) == 1, 'fixture driver invoked more than once'
        attempt = _attempt(e)
        assert attempt['status'] == 'IN_FLIGHT', 'durable reservation must precede driver'
        offer = json.loads(attempt['offer'])
        assert asdict(request) | {'cwd': offer['request']['cwd']} == offer['request']
        assert offer['request']['model'] == 'gpt-6.1-sol'
        assert offer['request']['mode'] == 'workspace-write' and offer['request']['session_id'] is None
        assert request.cwd == attempt['workspace'] and Path(request.cwd).is_relative_to(e.state)
        assert not Path(request.cwd).is_relative_to(e.m.directory)
        self.inputs = {path: Path(request.cwd, path).read_bytes() for path in INPUTS}
        assert self.inputs == INPUTS
        assert e.node['secret'] not in json.dumps(asdict(request)) + json.dumps(environment())
        emit('process_started', {'pid': os.getpid(), 'driver': 'codex'})
        emit('session_bound', {'session_id': 'fixture-pipeline-session'})
        emit('turn_bound', {'session_id': 'fixture-pipeline-session', 'turn_id': 'fixture-pipeline-turn'})
        emit('model_identity', {'requested_model': request.model, 'actual_model': None, 'telemetry': 'missing'})
        emit('native_event', {'method': 'protocol-fixture', 'params': {'message': 'fixed fixture bytes only'}})
        for path, data in OUTPUTS.items():
            Path(request.cwd, path).write_bytes(data)
        if self.mode == 'scope':
            _put(request.cwd, 'outside.bin', b'visible unowned protocol bytes')
        if self.mode == 'crash':
            raise KeyboardInterrupt('protocol fixture interrupted; native outcome unknown')
        assert controls() == []
        return Receipt('COMPLETED', session_id='fixture-pipeline-session', turn_id='fixture-pipeline-turn',
                       exit_code=0, output='protocol fixture terminal, not acceptance', requested_model=request.model)


class Pipeline:
    def __init__(self, root, monkeypatch):
        self.root, self.key = root, 'coupled-worker-0001'
        self.state, self.auth = root / 'agent-state', root / 'node-auth.json'
        self.flight = None
        self.remote, self.result, self.error = [], None, None
        self.trace, self.dropped, self.drop_stage = [], [], None
        source = root / 'source'
        source.mkdir()
        for path, data in INPUTS.items():
            _put(source, path, data)
        evaluator = root / 'frozen-check.py'
        evaluator.write_text('raise AssertionError("checker is not part of this protocol slice")\n')
        self.task = {'id': 'build', 'objective': 'fixed binary change and addition', 'depends_on': [],
                     'write_paths': list(OUTPUTS), 'check': 'bytes', 'acceptance': 'fixed binary acceptance'}
        check = {'argv': [sys.executable, '-I', '-S', str(evaluator), '{candidate}'],
                 'code_hashes': {str(evaluator): hashlib.sha256(evaluator.read_bytes()).hexdigest()},
                 'contract': {'kind': 'rules', 'pass_if': {'all': [{'path': 'ok', 'op': 'eq', 'value': True}]},
                              'fail_if': {'all': [{'path': 'ok', 'op': 'eq', 'value': False}]}}}
        spec = {'objective': 'Protocol pipeline only; independent acceptance stays separate', 'source': str(source),
                'checks': {'bytes': check}, 'required_checks': ['bytes'], 'integration_checks': ['bytes'],
                'tasks': [self.task], 'timeout': 5, 'parallelism': 1,
                'validation_kind': 'OFFLINE_PROTOCOL_FIXTURE_NOT_NATIVE'}
        made = []

        def real_mission(directory, specification=None):
            mission = LeadMission(directory, specification)
            made.append(mission)
            return mission

        self.hub = MissionHub(root / 'hub', mission_factory=real_mission)
        self.ident = self.hub.create(spec)['id']
        assert len(made) == 1 and type(made[0]) is LeadMission
        self.m = made[0]
        self.m.admit_plan({'architecture': 'fixed fixture input, isolated output', 'interfaces': [],
                           'tasks': [self.task]}, 'coupled-fixed-plan')
        self.claims = self.m.node_claims
        self.node = self.claims.registry.enroll('coupled_enroll_0001', 'protocol node', ['codex'], ['gpt-6.1-sol'])
        self.placement = self.m.assign_placement('build', self.node['node_id'], 'coupled_placement_0001')
        assert self.placement['execution_ready'] is False and self.m.remote_execution_ready() is False
        self.m.remote_execution_ready = lambda: True  # existing explicit host-only seam, never persisted
        self.acceptance = digest(self.m.spec)
        self.original_source = full_tree_manifest(source)
        self.gateway = node_gateway.NodeGateway(self.hub, port=0)
        self.server = threading.Thread(target=self.gateway.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.server.start()
        config = {'schema': 1, 'controller_mission_id': self.ident, 'node_id': self.node['node_id'],
                  'secret': self.node['secret'], 'gateway_url': self.gateway.url,
                  'gateway_host': '127.0.0.1:' + str(self.gateway.server_port)}
        auth_fd = os.open(self.auth, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(auth_fd, 'w') as file:
            json.dump(config, file)
        self.auth_hash = hashlib.sha256(self.auth.read_bytes()).hexdigest()
        original_send = node_gateway._Handler._send
        send_lock = threading.Lock()

        def send(handler, value, status=200, *, binary=False):
            # Service methods/signatures/transactions and the detached wire body
            # are untouched. Only the actual socket ACK is lost after real IO.
            operation = handler.path.split('/')[4].split('?')[0]
            raw = value if binary else value.raw if isinstance(value, node_gateway._Response) else json.dumps(value).encode()
            item = {'operation': operation, 'status': status, 'path': handler.path,
                    'actual_Node_auth': handler.headers.get('Authorization') == 'Node ' + self.node['secret'],
                    'actual_Host': handler.headers.get('Host') == config['gateway_host'],
                    'raw_bytes': len(raw), 'raw_sha256': hashlib.sha256(raw).hexdigest()}
            if isinstance(value, node_gateway._Response):
                item['envelope'] = json.loads(value.raw)
            with send_lock:
                self.trace.append(item)
                drop = status == 200 and operation == self.drop_stage and not self.dropped
                if drop:
                    self.dropped.append(item)
            if drop:
                handler.close_connection = True
                handler.connection.shutdown(socket.SHUT_RDWR)
                handler.connection.close()
                return
            return original_send(handler, value, status, binary=binary)

        monkeypatch.setattr(node_gateway._Handler, '_send', send)

    def start(self, *, mode='normal', lease_seconds=60, supplement=False):
        if supplement:
            self.message = self.hub.message(self.ident, 'fixed supplementary protocol note', 'coupled_message_0001', task_id='build')
            assert self.message['status'] == 'RECEIVED' and self.message['applications'] == []
            assert not self.m.journal.runs()
        self.cont = self.m.store.claim_due_continuation('coupled-controller', lease_seconds=lease_seconds)
        assert self.cont and self.cont['context']['native_task'] == 'build'
        decision = self.m.planner(self.cont, self.m.runtime.planner_context(self.cont))
        assert decision.capability == 'workers.execute'
        self.capability = self.m.registry.get('workers.execute').capability
        self.arguments = decision.arguments
        self.driver = ScriptedDriver(self, mode)
        self.agent = NodeAgent(self.auth, self.state, driver=self.driver)

        def observe(frame, event, arg):
            if event == 'call' and frame.f_code is RemoteCodexDriver.run.__code__:
                instance = frame.f_locals['self']
                assert type(instance) is RemoteCodexDriver
                self.remote.append(instance)

        def execute():
            sys.setprofile(observe)  # read-only real code/instance identity, no replacement
            try:
                self.result = self.capability.execute(self.arguments, idempotency_key=self.key)
            except BaseException as exc:
                self.error = exc
            finally:
                sys.setprofile(None)

        self.flight = threading.Thread(target=execute, name='real-coupled-controller', daemon=True)
        self.flight.start()
        _wait(lambda: self.claims.get(self.key) is not None or not self.flight.is_alive())
        assert self.claims.get(self.key) is not None, 'real public controller did not publish an offer'
        assert len(self.remote) == 1 and self.remote[0].claims is self.claims
        self.original_offer = self.claims.get(self.key)
        self.original_request = self.original_offer['request']
        assert self.original_offer['status'] == 'OFFERED'
        assert self.m.inbox.for_run(self.key)['prompt_hash'] == digest(self.original_request['prompt'])

    def restarted(self):
        return NodeAgent(self.auth, self.state, driver=self.driver)

    def joined(self):
        self.flight.join(8)
        assert not self.flight.is_alive(), 'finite real Driver wait did not terminate'

    def public_status_http(self):
        local = json.loads(_attempt(self)['offer'])
        connection = http.client.HTTPConnection('127.0.0.1', self.gateway.server_port, timeout=2)
        try:
            connection.request('POST', '/node/v1/' + self.ident + '/status',
                body=json.dumps({'claim_id': local['claim_id'], 'epoch': local['epoch']}),
                headers={'Host': '127.0.0.1:' + str(self.gateway.server_port),
                         'Authorization': 'Node ' + self.node['secret'], 'X-Sisyfus-Node': self.node['node_id'],
                         'Content-Type': 'application/json'})
            response = connection.getresponse()
            body = response.read(4_000_001)
            assert response.status == 200 and len(body) <= 4_000_000
            wrapper = json.loads(body)
            assert set(wrapper) == {'controller_mission_id', 'result'} and wrapper['controller_mission_id'] == self.ident
            assert wrapper['result'] == _status(self)
            return wrapper['result']
        finally:
            connection.close()

    def independent_truth(self):
        assert digest(self.m.spec) == self.acceptance
        assert self.m.placement('build') == self.placement and self.placement['execution_ready'] is False
        assert full_tree_manifest(self.m.spec['source']) == self.original_source
        for path, data in INPUTS.items():
            assert Path(self.m.spec['source'], path).read_bytes() == data
        assert self.m.store.get_continuation(self.cont['id'])['lease_token'] == self.cont['lease_token']
        assert len(self.m.journal.runs()) == 1 and self.m.journal.runs()[0]['verdict'] == 'UNVERIFIED'
        snapshot = self.m.snapshot()
        assert snapshot['all_verified'] is False and snapshot['nodes'][0]['verdict'] == 'UNVERIFIED'
        assert snapshot['integration']['continuation'] is None and snapshot['integration']['evidence'] is None
        assert not snapshot['reviews'] and not self.m.journal.records('measurements')
        assert not self.m.journal.records('integrations') and self.m.store.verify_event_chain()['valid']
        wrapper = self.hub.snapshot(self.ident)
        assert set(wrapper) == {'id', 'snapshot', 'controller', 'controls'}
        # Whole snapshots include newly sampled wall_minutes. Compare original
        # deterministic truth fields, not independently sampled elapsed time.
        for field in ('objective', 'phase', 'nodes', 'plans', 'reviews', 'integration', 'roles',
                      'project_verified', 'all_verified', 'budgets', 'native_call_reservations'):
            assert wrapper['snapshot'][field] == snapshot[field]
        fixed = self.m.journal.get('run_placements', self.key)
        roles = self.m.journal.get('roles', self.key)
        assert roles['role'] == fixed['role'] == 'worker' and roles['model'] == 'gpt-6.1-sol'
        assert roles['mode'] == 'workspace-write' and fixed['placement'] == self.placement
        for root in (roles['cwd'], fixed['input_snapshot']):
            assert full_tree_manifest(root) == self.original_source
            for path, data in INPUTS.items():
                assert Path(root, path).read_bytes() == data
        current = self.claims.get(self.key)
        for key in ('mission_id', 'run_key', 'node_id', 'task_id', 'fingerprint', 'request',
                    'prompt_hash', 'input_manifest', 'input_manifest_hash'):
            assert current[key] == self.original_offer[key]
        assert current['mission_id'] == self.claims.registry.mission_id != self.ident
        assert len(self.remote) == len(self.driver.requests) == 1
        assert all(item['actual_Node_auth'] and item['actual_Host'] for item in self.trace)
        assert hashlib.sha256(self.auth.read_bytes()).hexdigest() == self.auth_hash
        info = self.auth.stat(follow_symlinks=False)
        assert stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
        assert stat.S_IMODE(info.st_mode) == 0o600 and stat.S_IMODE(self.state.stat().st_mode) == 0o700
        assert not self.auth.is_relative_to(self.state)
        assert self.node['secret'] not in json.dumps(self.trace)
        for path in self.state.rglob('*'):
            if path.is_file() and not path.is_symlink():
                assert self.node['secret'].encode() not in path.read_bytes()

    def successful(self):
        self.joined()
        assert self.error is None and self.result.status == 'COMPLETED'
        assert not self.result.observation.get('integrity_error') and not self.result.observation.get('scope_error')
        assert self.result.observation['actual_model'] is None
        view = self.public_status_http()
        assert view['status'] == 'RECEIPTED' and view['receipt']['status'] == 'COMPLETED'
        assert view['receipt']['requested_model'] == 'gpt-6.1-sol' and view['receipt']['actual_model'] is None
        assert set(view['tree']) == {'schema', 'files', 'tree', 'errors', 'complete'}
        assert view['tree']['complete'] is True and view['tree']['errors'] == []
        assert view['tree'] == full_tree_manifest(self.driver.requests[0].cwd)
        entries = [{'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                   for path, data in sorted(OUTPUTS.items())]
        assert view['manifest'] == entries and view['uploads'] == [entry | {'status': 'STORED'} for entry in entries]
        materialization = self.remote[0].materialization
        assert set(materialization) == {'candidate', 'before', 'delta'} and materialization['delta']['valid'] is True
        assert full_tree_manifest(materialization['before']) == self.original_source
        for root in (materialization['candidate'], self.result.observation['candidate'], self.driver.requests[0].cwd):
            assert full_tree_manifest(root) == view['tree']
            for path, data in (INPUTS | OUTPUTS).items():
                assert Path(root, path).read_bytes() == data
        for path, data in OUTPUTS.items():
            assert Path(self.claims.artifact_root, view['claim_id'], path).read_bytes() == data
        local = _local(self)
        assert local['attempts'][0]['status'] == 'DONE' and local['attempts'][0]['ack'] == len(local['outbox'])
        assert json.loads(local['attempts'][0]['tree']) == view['tree']
        synced = _read_db(self.m.store.path, ('remote_event_sync',))['remote_event_sync']
        assert [row['seq'] for row in synced] == list(range(1, len(local['outbox']) + 1))
        assert [row['raw_digest'] for row in synced] == [digest(json.loads(row['event'])) for row in local['outbox']]
        self.independent_truth()
        core = self.m.journal.runs()[0]
        assert core['status'] == 'RECEIPTED' and core['receipt']['status'] == 'COMPLETED'
        before = self.m.store.verify_event_chain()
        replay = self.capability.execute(self.arguments, idempotency_key=self.key)
        assert replay.observation == self.result.observation and self.m.store.verify_event_chain() == before
        assert len(self.remote) == len(self.driver.requests) == 1

    def evidence(self):
        def encode(value):
            if isinstance(value, bytes):
                return {'bytes_hex': value.hex(), 'sha256': hashlib.sha256(value).hexdigest(), 'size': len(value)}
            if isinstance(value, dict):
                return {key: digest(item) if key == 'lease_token' else encode(item) for key, item in value.items()}
            if isinstance(value, list):
                return [encode(item) for item in value]
            return value
        evidence = {'classification': 'ADDITIONAL_VERIFICATION_PROTOCOL_NOT_NATIVE',
                    'actual_coupled_RemoteCodexDriver_run_count': len(self.remote),
                    'injected_protocol_driver_run_count': len(self.driver.requests), 'HTTP_trace': self.trace,
                    'dropped_ACK_count': len(self.dropped), 'source_before': self.original_source,
                    'source_after': full_tree_manifest(self.m.spec['source']), 'acceptance_hash': self.acceptance,
                    'auth_mode': oct(stat.S_IMODE(self.auth.stat().st_mode)), 'auth_file_sha256': self.auth_hash,
                    'controller_snapshot': self.m.snapshot(), 'local_state': _local(self),
                    'controller_transport_tables': _read_db(self.m.store.path, ('remote_offers', 'remote_claim_requests',
                        'remote_event_sync', 'remote_uploads', 'remote_receipt_trees', 'remote_input_snapshots',
                        'lead_mission_contexts')), 'event_chain': self.m.store.verify_event_chain(),
                    'requests': [asdict(request) for request in self.driver.requests],
                    'result': self.result.observation if self.result else None,
                    'controller_exception_type': type(self.error).__name__ if self.error else None,
                    'materialization': self.remote[0].materialization if self.remote else None}
        encoded = json.dumps(encode(evidence), ensure_ascii=False, sort_keys=True, indent=2)
        assert self.node['secret'] not in encoded
        (self.root / 'pipeline-evidence.json').write_text(encoded)

    def close(self):
        if self.flight:
            self.flight.join(8)
        try:
            if self.flight:
                self.evidence()
        finally:
            self.gateway.shutdown()
            self.gateway.server_close()
            self.server.join(3)
            self.hub.close()
        assert not self.server.is_alive() and (not self.flight or not self.flight.is_alive())


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    assert os.environ.get('SISYFUS_TEST_LOOPBACK') == '1', 'explicit isolated fixture loopback opt-in required'
    e = Pipeline(tmp_path, monkeypatch)
    try:
        yield e
    finally:
        e.close()


def test_real_coupled_public_pipeline_materializes_bytes_and_keeps_context_not_acceptance(pipeline):
    e = pipeline
    e.hub.attach_node_gateway(e.gateway, serve_thread=e.server)
    e.start(supplement=True)
    assert e.m.inbox.messages()['messages'][0]['applications'][0]['status'] == 'BOUND'
    assert e.agent.run_once()['status'] == 'RECEIPTED'
    e.successful()
    message = e.hub.messages(e.ident)['messages'][0]
    assert message['status'] == 'APPLIED' and message['applications'][0]['status'] == 'APPLIED'
    assert message['applications'][0]['delivery']['native_boundary'] == 'turn_bound'
    assert 'fixed supplementary protocol note' in e.driver.requests[0].prompt
    assert e.result.observation['context_binding_hash'] == digest(e.m.inbox.for_run(e.key))


@pytest.mark.parametrize('stage', ['claim', 'sync', 'uploads', 'receipt'])
def test_actual_lost_http_ack_fresh_agent_replays_original_identity_without_driver_respawn(pipeline, stage):
    e = pipeline
    e.drop_stage = stage
    e.start()
    with pytest.raises(RuntimeError):
        e.agent.run_once()
    before = _local(e)
    assert len(e.dropped) == 1
    claim_rows = _read_db(e.m.store.path, ('remote_claim_requests',))['remote_claim_requests']
    assert len(claim_rows) == 1 and claim_rows[0]['request_id'] == before['attempts'][0]['request_id']
    assert len(e.driver.requests) == (0 if stage == 'claim' else 1)
    assert e.restarted().run_once()['status'] == 'RECEIPTED'
    after = _local(e)
    assert after['attempts'][0]['request_id'] == before['attempts'][0]['request_id']
    for key in ('offer', 'workspace', 'receipt', 'tree', 'receipt_body'):
        if before['attempts'][0][key] is not None:
            assert before['attempts'][0][key] == after['attempts'][0][key]
    if before['outbox']:
        assert before['outbox'] == after['outbox']
    for upload in before['uploads']:
        same = next(item for item in after['uploads'] if item['path'] == upload['path'])
        assert (same['metadata'], same['bytes']) == (upload['metadata'], upload['bytes'])
    assert len(_read_db(e.m.store.path, ('remote_claim_requests',))['remote_claim_requests']) == 1
    repeated = [item for item in e.trace if item['path'] == e.dropped[0]['path'] and item['status'] == 200]
    assert len(repeated) >= 2
    if stage == 'sync':
        # Duplicate sync reads the current controller heartbeat deadline, while
        # retaining the original owner and event watermark/digests unchanged.
        first, second = (item['envelope']['result'] for item in repeated[:2])
        assert {key: value for key, value in first.items() if key != 'lease_expires_at'} == {
            key: value for key, value in second.items() if key != 'lease_expires_at'}
        assert second['lease_expires_at'] >= first['lease_expires_at']
    else:
        assert repeated[0]['raw_sha256'] == repeated[1]['raw_sha256']
    e.successful()


def test_interrupted_protocol_driver_unknown_restart_syncs_original_outbox_no_candidate(pipeline):
    e = pipeline
    e.start(mode='crash')
    with pytest.raises(KeyboardInterrupt):
        e.agent.run_once()
    before = _local(e)
    assert before['attempts'][0]['status'] == 'UNKNOWN' and before['attempts'][0]['receipt'] is None
    original = e.restarted().run_once()
    assert original == {'request_id': before['attempts'][0]['request_id'], 'status': 'UNKNOWN'}
    assert _local(e)['outbox'] == before['outbox'] and _attempt(e)['ack'] == len(before['outbox'])
    e.joined()
    assert e.error is None and e.result.status == 'UNKNOWN' and 'candidate' not in e.result.observation
    assert e.m.journal.runs()[0]['status'] == 'UNKNOWN'
    assert e.remote[0].materialization['status'] == 'UNKNOWN' and 'candidate' not in e.remote[0].materialization
    for path, data in OUTPUTS.items():
        assert Path(e.driver.requests[0].cwd, path).read_bytes() == data
    assert e.restarted().run_once() == original
    assert e.public_status_http()['receipt'] is None
    synced = _read_db(e.m.store.path, ('remote_event_sync',))['remote_event_sync']
    assert [item['raw_digest'] for item in synced] == [digest(json.loads(item['event'])) for item in before['outbox']]
    e.independent_truth()


def test_full_tree_exposes_unowned_bytes_terminal_is_retained_without_candidate_or_pass(pipeline):
    e = pipeline
    e.start(mode='scope')
    assert e.agent.run_once()['status'] == 'RECEIPTED'
    e.joined()
    assert e.error is None and e.result.status == 'COMPLETED'
    assert e.result.observation.get('integrity_error') and 'candidate' not in e.result.observation
    assert e.remote[0].materialization['status'] == 'INVALID'
    assert e.remote[0].materialization['report']['valid'] is False
    view = e.public_status_http()
    assert view['receipt']['status'] == 'COMPLETED' and view['tree']['complete'] is True
    assert 'outside.bin' in {item['path'] for item in view['tree']['files']}
    assert 'outside.bin' not in {item['path'] for item in view['uploads']}
    assert view['tree'] == full_tree_manifest(e.driver.requests[0].cwd)
    for path, data in OUTPUTS.items():
        assert Path(e.claims.artifact_root, view['claim_id'], path).read_bytes() == data
    assert json.loads(_attempt(e)['receipt'])['status'] == 'COMPLETED'
    assert not Path(e.m.journal.get('run_placements', e.key)['candidate_root']).exists()
    e.independent_truth()


def test_real_expired_controller_lease_keeps_original_stored_subset_and_known_native_terminal(pipeline):
    e = pipeline
    e.drop_stage = 'uploads'
    e.start(lease_seconds=2)
    with pytest.raises(RuntimeError):
        e.agent.run_once()
    before = _local(e)
    assert len(e.driver.requests) == 1 and json.loads(before['attempts'][0]['receipt'])['status'] == 'COMPLETED'
    stored = [item for item in _status(e)['uploads'] if item['status'] == 'STORED']
    assert len(stored) == 1
    expiry = datetime.fromisoformat(e.cont['lease_expires_at'].replace('Z', '+00:00'))
    _wait(lambda: datetime.now(timezone.utc) > expiry, seconds=3)
    e.joined()
    assert isinstance(e.error, LeaseLost) and e.result is None
    assert e.restarted().run_once()['status'] == 'RECONCILIATION_CANDIDATE'
    view = e.public_status_http()
    assert view['status'] == 'RECONCILIATION_CANDIDATE' and view['receipt']['status'] == 'COMPLETED'
    assert view['manifest'] == [{key: item[key] for key in ('path', 'size', 'sha256')} for item in stored]
    assert view['tree'] == full_tree_manifest(e.driver.requests[0].cwd)
    after = _local(e)
    assert before['outbox'] == after['outbox']
    for key in ('request_id', 'offer', 'workspace', 'receipt', 'tree'):
        assert before['attempts'][0][key] == after['attempts'][0][key]
    assert after['attempts'][0]['lease_lost'] == 1
    for item in stored:
        assert Path(e.claims.artifact_root, view['claim_id'], item['path']).read_bytes() == OUTPUTS[item['path']]
    for upload in after['uploads']:
        assert upload['bytes'] == OUTPUTS[upload['path']]
    assert e.remote[0].materialization['status'] == 'UNKNOWN' and 'candidate' not in e.remote[0].materialization
    assert not Path(e.m.journal.get('run_placements', e.key)['candidate_root']).exists()
    assert e.m.journal.runs()[0]['receipt'] is None
    e.independent_truth()
