"""Controller-selected v2 response admission; TEST-ONLY, not a source PASS.

Real retained loopback/public reserve -> snapshot -> offer -> HTTP. No native
execution, replacement service results, forged reservations, limit changes or
legacy contract aliases. The frozen preliminary66 is a separate version.
Halley owns direct NodeClaims callback/default/SQL-chain tests; here the real
service is observed at Gateway ingress, dispatch, transaction and full wire.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict
from functools import wraps
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import sys

import pytest

from sisyfus.workers import node_gateway as gateway
from sisyfus.workers.lead_console import MissionHub
from sisyfus.workers.node_claims import NodeClaims
from sisyfus.workers.node_registry import NodeRegistry
from sisyfus.workers.protocol import Receipt, Request, digest, redact
from sisyfus.workers.remote_artifacts import create_input_snapshot, full_tree_manifest
from test_node_gateway import call, env, fields, gateway_type, state


OLD_SHA = '8302cf50c05bf37434c92c0ea580093d6f169a5525310a24cb8bee98ecee99ca'
FIXTURE_KEY = 'gateway_response_v2_fixture_provider_key_abcdef'
MUTATING = ('claim', 'heartbeat', 'sync', 'upload', 'receipt')
ROUTES = (('claim', 'POST'), ('heartbeat', 'POST'), ('sync', 'POST'),
          ('status', 'POST'), ('receipt', 'POST'), ('inputs', 'GET'), ('uploads', 'PUT'))
DYNAMIC_MESSAGE = 'transport response is not representable'


@pytest.fixture(autouse=True)
def isolated_provider_values(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', FIXTURE_KEY)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'gateway_response_v2_fixture_anthropic_abcdef')


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def items(value):
    # Containers and values count; dictionary KEYS do not count as items.
    children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
    return 1 + sum(items(child) for child in children)


def depth(value):
    children = list(value.values()) if isinstance(value, dict) else value if isinstance(value, list) else []
    return 1 + max(map(depth, children)) if children else 0


def normalized(raw):
    return redact(asdict(Receipt(**raw)))


def item_floor(wire):
    return (3 + items(normalized(wire['receipt'])) + items(wire['manifest'])
            + 1 + 5 * len(wire['manifest']) + items(redact(wire['tree'])))


def receipt_body(c, *, status='COMPLETED', usage=None, output='', manifest=None, tree=None):
    return fields(c) | {'receipt': {'status': status, 'usage': {} if usage is None else usage, 'output': output},
                       'manifest': [] if manifest is None else manifest,
                       'tree': {'schema': 1, 'files': [], 'tree': [], 'errors': [], 'complete': True}
                       if tree is None else tree}


def nested_usage(body_depth):
    value = 0
    for _ in range(body_depth - 3):
        value = [value]
    return {'datum': value}


def expected_receipt(e, wire):
    # BEFORE-call real public view + original Receipt normalization. No golden
    # inferred from HTTP outcomes and no fabricated backend replacement result.
    view = e.claims.status(e.node['node_id'], wire['claim_id'], wire['epoch'])
    late = view['status'] != 'CLAIMED' or view['lease_expires_at'] <= e.clock()
    terminal = ('RECONCILIATION_CANDIDATE' if late else
                'UNKNOWN' if wire['receipt']['status'] == 'UNKNOWN' else 'RECEIPTED')
    return {'controller_mission_id': e.ident, 'result': view | {
        'status': terminal, 'receipt': normalized(wire['receipt']),
        'manifest': sorted(wire['manifest'], key=lambda entry: entry['path']), 'tree': redact(wire['tree'])}}


def prepare(e, *, inputs=1, outputs=('result.txt',), prompt='Fixed v2 response fixture',
            task_id='build', cwd_padding=0, claim=True):
    assert e.gateway.server_address[0] == '127.0.0.1' and e.gateway.server_port > 0
    e.claims = NodeClaims(e.mission.journal, e.registry,
                         e.mission.directory / 'remote' / 'artifacts', clock=e.clock)
    e.mission._node_claims = e.claims
    source = e.root / 'response-v2-input-source'; source.mkdir()
    for index in range(inputs):
        (source / f'input_{index:03}.txt').write_bytes(b'fixed input')
    e.snapshot = e.root / 'response-v2-input-snapshot'
    e.manifest = create_input_snapshot(source, e.snapshot, list(outputs))
    # PosixPath normalizes redundant trailing separators. This is an existing
    # genuine snapshot, not a fictitious huge pathname or a patched Request.
    cwd = str(e.snapshot) + '/' * cwd_padding
    assert Path(cwd) == e.snapshot and Path(cwd).is_dir()
    request = Request(task_id, prompt, cwd, 'gpt-6.1-sol', mode='workspace-write')
    e.key = 'response-v2-admission-run'; e.request = request
    assert e.mission.journal.reserve(e.key, task_id, digest(asdict(request))) is None
    e.claims.bind_input_snapshot(e.key, e.snapshot, e.manifest)
    view = e.claims.offer(e.key, e.node['node_id'], request, e.manifest)
    assert view['status'] == 'OFFERED' and view['epoch'] == 0 and view['claim_id'] is None
    assert view['request'] == asdict(request) and view['task_id'] == task_id
    assert view['input_manifest'] == e.manifest and view['input_manifest_hash'] == digest(e.manifest)
    reserved = next(row for row in e.mission.journal.runs() if row['key'] == e.key)
    assert reserved['task_id'] == task_id and reserved['fingerprint'] == digest(asdict(request))
    assert reserved['status'] == 'IN_FLIGHT' and reserved['receipt_json'] is None
    assert e.mission.store.verify_event_chain()['valid']
    # Setup uses the actual public default API, never a fake HTTP success or
    # callback adapter. Gateway-positive behavior is tested separately below.
    if not claim:
        return view
    result = e.claims.claim(e.node['node_id'], 'response_v2_fixture_claim_01')
    assert result['status'] == 'CLAIMED'
    return result['claim']


def output_fixture(e, c):
    raw = b'fixed stored output'
    entry = {'path': 'result.txt', 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    assert e.claims.upload(e.node['node_id'], c['claim_id'], c['epoch'],
                           entry['path'], entry['sha256'], raw) == entry | {'status': 'STORED'}
    worktree = e.root / 'response-v2-native-tree'; worktree.mkdir()
    (worktree / entry['path']).write_bytes(raw)
    return [entry], full_tree_manifest(worktree)


def preparing_fixture(e, c, monkeypatch):
    # Real public PREPARING transaction + real partial file, retained on error.
    # No manual canonical/transport-row insertion and no deletion/recovery trick.
    original = os.write; writes = []
    def partial(fd, data):
        if not writes:
            writes.append(True)
            return original(fd, data[:3])
        raise OSError('fixed retained partial upload fixture')
    with monkeypatch.context() as patch:
        patch.setattr(os, 'write', partial)
        with pytest.raises(OSError, match='fixed retained partial upload fixture'):
            e.claims.upload(e.node['node_id'], c['claim_id'], c['epoch'], 'partial.txt',
                            hashlib.sha256(b'partial').hexdigest(), b'partial')
    assert (e.claims.artifact_root / c['claim_id'] / 'partial.txt').read_bytes() == b'par'


def facts(e):
    with e.mission.store._transaction(immediate=False) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        statements = {
            'rows': 'SELECT run_key,status,claim_id,epoch,lease_expires_at,receipt_json,manifest_json FROM remote_offers ORDER BY run_key',
            'requests': 'SELECT node_id,request_id,response_json FROM remote_claim_requests ORDER BY node_id,request_id',
            'trees': 'SELECT * FROM remote_receipt_trees ORDER BY claim_id',
            'uploads': 'SELECT * FROM remote_uploads ORDER BY claim_id,path',
            'sync': 'SELECT * FROM remote_event_sync ORDER BY claim_id,epoch,seq',
            'controls': 'SELECT * FROM remote_transport_controls ORDER BY rowid',
        }
        result = {name: [dict(row) for row in db.execute(sql)] if sql.split(' FROM ')[1].split()[0] in tables else []
                  for name, sql in statements.items()}
        result['events'] = [dict(row) for row in db.execute(
            'SELECT seq,event_type,entity_id,data_json,prev_hash,event_hash FROM events ORDER BY seq')]
    root = e.mission.directory / 'remote'
    result['artifact_hashes'] = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in root.rglob('*') if path.is_file()} if root.exists() else {}
    result['logical_state'] = state(e)
    result['physical_names_including_aux'] = sorted(str(path.relative_to(e.hub.directory))
                                                   for path in e.hub.directory.rglob('*'))
    return result


def unchanged(before, after):
    for name in ('rows', 'requests', 'trees', 'uploads', 'sync', 'controls', 'events',
                 'artifact_hashes', 'logical_state'):
        assert after[name] == before[name], name
    # The undecided physical WAL/shm oracle is recorded, not called zero writes.


def fenced(e):
    assert all(row['status'] == 'IN_FLIGHT' and row['receipt_json'] is None
               for row in e.mission.journal.runs())
    assert e.mission.store.verify_event_chain()['valid']


def trace(e, monkeypatch, method, *, after_admit=None, after_return=None):
    observed = {'sessions': 0, 'dispatches': 0, 'callbacks': 0, 'rejections': 0,
                'rejection_types': [], 'captures': []}
    original_session, original_method = e.hub._session, getattr(e.claims, method)
    def session(ident):
        observed['sessions'] += 1
        return original_session(ident)
    @wraps(original_method)
    def dispatch(*args, **kwargs):
        observed['dispatches'] += 1
        admitted = kwargs.get('admit_response')
        if admitted is not None:
            def checked(detached_result, detached_controls):
                observed['callbacks'] += 1
                assert (isinstance(detached_controls, list) if method == 'heartbeat'
                        else detached_controls is None)
                observed['captures'].append((deepcopy(detached_result), deepcopy(detached_controls)))
                try:
                    returned = admitted(detached_result, detached_controls)
                except Exception as exc:
                    observed['rejections'] += 1
                    observed['rejection_types'].append(type(exc).__name__)
                    raise
                if after_admit is not None:
                    after_admit(detached_result, detached_controls)
                return returned
            kwargs = kwargs | {'admit_response': checked}
        result = original_method(*args, **kwargs)
        if after_return is not None:
            after_return()
        return result
    # wraps preserves the ACTUAL public signature. No __signature__ forgery,
    # arity alias or kwargs-based fake capability; all results are the real API.
    monkeypatch.setattr(e.hub, '_session', session)
    monkeypatch.setattr(e.claims, method, dispatch)
    return observed


def summary(observed):
    return {name: value for name, value in observed.items() if name != 'captures'}


def diagnostics(e, replies, caplog, capsys, forbidden=()):
    observed = json.dumps(replies, ensure_ascii=False) + caplog.text + capsys.readouterr().err
    assert e.node['secret'] not in observed
    assert all(text not in observed for text in forbidden)


def dynamic_error(reply):
    code, value = reply
    assert code == 500
    assert value['error']['type'] == 'RuntimeError'
    assert value['error']['message'] == DYNAMIC_MESSAGE
    assert value['error']['diagnostic_id'].startswith('ng_')


@pytest.fixture
def pinned_8302(monkeypatch):
    path = Path(os.environ['SISYFUS_GATEWAY_RESPONSE_CLAIMS_BASELINE'])
    assert path.is_absolute() and path.stat().st_mode & 0o222 == 0
    assert hashlib.sha256(path.read_bytes()).hexdigest() == OLD_SHA
    spec = importlib.util.spec_from_file_location('sisyfus.workers._gateway_response_v2_8302', path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module); spec.loader.exec_module(module)
    return module.NodeClaims


@pytest.mark.parametrize('method', MUTATING)
def test_current_real_public_capability_is_named_keyword_only_with_none_default(method):
    parameter = inspect.signature(getattr(NodeClaims, method)).parameters.get('admit_response')
    assert parameter is not None, method + ' requires the selected public dependency'
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.default is None


def test_exact_caps_value_only_item_count_and_conservative_floor_are_static():
    assert (gateway.MAX_JSON_DEPTH, gateway.MAX_JSON_ITEMS, gateway.MAX_JSON_BYTES,
            gateway.MAX_RESPONSE_BYTES, gateway.MAX_UPLOAD_BYTES) == (64, 50000, 1500000, 4000000, 8000000)
    dictionary = {f'key_{index}': 0 for index in range(25000)}
    envelope = {'controller_mission_id': 'mission_fixture', 'result': dictionary}
    assert items(envelope) == 25003
    gateway._json_limits(envelope)
    c = {'claim_id': 'claim_' + 'a' * 32, 'epoch': 1}
    for status in ('COMPLETED', 'ERROR', 'INTERRUPTED', 'UNKNOWN'):
        for number in (0, 1, 128):
            manifest = [{'path': f'out_{index}.txt', 'sha256': 'a' * 64, 'size': 0} for index in range(number)]
            wire = receipt_body(c, status=status, usage={'values': [0, {'nested': [1]}]}, manifest=manifest)
            uploads = [entry | {'status': 'STORED'} for entry in manifest]
            # Disjoint minimum structure. Full real _view has EXTRA fields;
            # this establishes the floor, not a fake public-service success.
            minimum = {'controller_mission_id': 'mission_fixture', 'result': {
                'receipt': normalized(wire['receipt']), 'manifest': manifest,
                'uploads': uploads, 'tree': redact(wire['tree'])}}
            assert item_floor(wire) == items(minimum)
            assert depth({'result': {'receipt': normalized(wire['receipt'])}}) == 2 + depth(normalized(wire['receipt']))


def select_child(e, ident):
    # Retained move of the real bound controller DB; authentication would succeed
    # without the NEW early target guard. No forged DB/auth or path backend.
    target = e.hub.directory / ident
    e.mission.directory.rename(target)
    e.hub = MissionHub(e.hub.directory); e.gateway.hub = e.hub; e.ident = ident
    e.mission = e.hub._session(ident).mission
    e.registry = NodeRegistry(e.mission.journal)


def route_arguments(operation, c):
    if operation == 'claim':
        return operation, {'body': {'request_id': 'response_v2_http_claim_01'}}
    if operation == 'receipt':
        return operation, {'body': receipt_body(c)}
    if operation == 'sync':
        return operation, {'body': fields(c) | {'events': []}}
    if operation in ('inputs', 'uploads'):
        query = {'path': 'input_000.txt' if operation == 'inputs' else 'result.txt'}
        extras = {}
        if operation == 'uploads':
            extras['raw'] = b'fixed output'; query['sha256'] = hashlib.sha256(extras['raw']).hexdigest()
        return operation + '/' + c['claim_id'] + '/1', {'query': query} | extras
    return operation, {'body': fields(c)}


@pytest.mark.parametrize('operation,http_method', ROUTES)
@pytest.mark.parametrize('identity', ['sk-learn-baseline', 'provider', 'literal_node_secret'])
@pytest.mark.parametrize('stage', ['cold', 'offered'])
def test_changed_target404_before_auth_hub_path_lazy_on_all_routes(
        env, monkeypatch, operation, http_method, identity, stage, caplog, capsys):
    e = env
    ident = FIXTURE_KEY if identity == 'provider' else e.node['secret'] if identity == 'literal_node_secret' else identity
    assert gateway._clean(ident, e.node['secret']) != ident
    select_child(e, ident)
    c = prepare(e) if stage == 'offered' else {'claim_id': 'claim_' + 'a' * 32, 'epoch': 1}
    before = facts(e); called = {'auth': 0, 'path': 0, 'session': 0}
    auth, path, session = gateway._auth, e.hub.path, e.hub._session
    def auth_spy(*args):
        called['auth'] += 1; return auth(*args)
    def path_spy(ident):
        called['path'] += 1; return path(ident)
    def session_spy(ident):
        called['session'] += 1; return session(ident)
    monkeypatch.setattr(gateway, '_auth', auth_spy)
    monkeypatch.setattr(e.hub, 'path', path_spy)
    monkeypatch.setattr(e.hub, '_session', session_spy)
    route, arguments = route_arguments(operation, c)
    replies = [call(e, route, method=http_method, **arguments) for _ in range(2)]
    print(json.dumps({'case': 'target', 'kind': identity, 'stage': stage, 'route': operation,
                      'http': [reply[0] for reply in replies], 'called': called}))
    diagnostics(e, replies, caplog, capsys, [ident])
    assert [reply[0] for reply in replies] == [404, 404] and called == {'auth': 0, 'path': 0, 'session': 0}
    unchanged(before, facts(e))
    if stage == 'cold':
        assert e.mission._node_claims is None and not (e.mission.directory / 'remote').exists()
    e.hub.close()


@pytest.mark.parametrize('ident', ['SK-learn-baseline', 'learn-baseline'])
def test_clean_target_retains_original_namespace_and_cached_no_work(env, monkeypatch, ident):
    e = env; select_child(e, ident)
    e.claims = NodeClaims(e.mission.journal, e.registry, e.mission.directory / 'remote' / 'artifacts', clock=e.clock)
    e.mission._node_claims = e.claims
    observed = trace(e, monkeypatch, 'claim')
    wire = {'request_id': 'response_v2_empty_claim_01'}
    oracle = {'controller_mission_id': ident, 'result': {'mission_id': e.registry.mission_id,
        'node_id': e.node['node_id'], 'request_id': wire['request_id'], 'status': 'NO_WORK', 'claim': None}}
    assert call(e, body=wire) == (200, oracle)
    before = facts(e)
    assert call(e, body=wire) == (200, oracle)
    assert observed['callbacks'] == 1 and observed['dispatches'] == 2
    unchanged(before, facts(e)); e.hub.close()


@pytest.mark.parametrize('method', MUTATING)
def test_real_readonly8302_missing_named_capability500_zero_dispatch(env, monkeypatch, pinned_8302, method, caplog, capsys):
    e = env; c = prepare(e, claim=method != 'claim')
    e.claims = pinned_8302(e.mission.journal, e.registry, e.mission.directory / 'remote' / 'artifacts', clock=e.clock)
    e.mission._node_claims = e.claims
    assert 'admit_response' not in inspect.signature(getattr(e.claims, method)).parameters
    observed = trace(e, monkeypatch, method)
    before = facts(e)
    operation = 'uploads' if method == 'upload' else method
    route, arguments = route_arguments(operation, c)
    if method == 'sync':
        arguments['body']['events'] = [{'seq': 1, 'kind': 'session_bound', 'data': {'session_id': 'fixture-session'}}]
    replies = [call(e, route, method='PUT' if method == 'upload' else 'POST', **arguments) for _ in range(2)]
    print(json.dumps({'case': 'old8302', 'method': method, 'http': [r[0] for r in replies], 'trace': summary(observed)}))
    diagnostics(e, replies, caplog, capsys)
    assert [reply[0] for reply in replies] == [500, 500]
    assert all('admit_response' in reply[1]['error']['message'] and method in reply[1]['error']['message'] for reply in replies)
    assert observed['sessions'] == 2 and observed['dispatches'] == observed['callbacks'] == 0
    unchanged(before, facts(e)); fenced(e)


@pytest.mark.parametrize('operation', ['claim', 'heartbeat', 'sync', 'receipt', 'status'])
def test_http_json_cannot_supply_executable_callback_before_lazy(env, monkeypatch, operation):
    e = env; c = prepare(e)
    observed = trace(e, monkeypatch, 'claim' if operation == 'status' else operation)
    route, arguments = route_arguments(operation, c)
    arguments['body']['admit_response'] = {'code': 'NODE_CALLBACK_MUST_REMAIN_DATA'}
    before = facts(e)
    assert call(e, route, **arguments)[0] == 400
    assert observed['sessions'] == observed['dispatches'] == 0
    unchanged(before, facts(e)); fenced(e)


@pytest.mark.parametrize('name', ['output', 'usage'])
def test_explicit_none_receipt_fields_remain_static_error_not_missing_defaults(env, monkeypatch, name):
    e = env; c = prepare(e); wire = receipt_body(c)
    wire['receipt'][name] = None
    observed = trace(e, monkeypatch, 'receipt'); before = facts(e)
    assert call(e, 'receipt', body=wire)[0] == 400
    assert observed['sessions'] == observed['dispatches'] == observed['callbacks'] == 0
    unchanged(before, facts(e)); fenced(e)


def test_nine_missing_receipt_defaults_do_not_invent_runtime_model_attestation(env, monkeypatch):
    e = env; c = prepare(e); wire = receipt_body(c)
    wire['receipt'] = {'status': 'COMPLETED'}
    oracle = expected_receipt(e, wire)
    assert len(oracle['result']['receipt']) == 9
    assert oracle['result']['receipt']['output'] == '' and oracle['result']['receipt']['usage'] == {}
    assert oracle['result']['receipt']['actual_model'] is None
    assert oracle['result']['receipt']['requested_model'] is None
    observed = trace(e, monkeypatch, 'receipt')
    assert call(e, 'receipt', body=wire) == (200, oracle)
    assert observed['callbacks'] == 1 and observed['rejections'] == 0
    before = facts(e)
    assert call(e, 'receipt', body=wire) == (200, oracle)
    unchanged(before, facts(e)); fenced(e)


@pytest.mark.parametrize('status', ['COMPLETED', 'ERROR', 'INTERRUPTED', 'UNKNOWN'])
def test_static_normalized_receipt_depth64_to65_400_pre_lazy_and_63_exact_replay(
        env, monkeypatch, status, caplog, capsys):
    e = env; c = prepare(e); manifest, tree = output_fixture(e, c)
    bad = receipt_body(c, status=status, usage=nested_usage(64), manifest=manifest, tree=tree)
    good = receipt_body(c, status=status, usage=nested_usage(63), manifest=manifest, tree=tree)
    oracle = expected_receipt(e, good)
    assert depth(bad) == 64 and depth(expected_receipt(e, bad)) == 65 and depth(oracle) == 64
    observed = trace(e, monkeypatch, 'receipt'); before = facts(e)
    replies = [call(e, 'receipt', body=bad) for _ in range(2)]
    print(json.dumps({'case': 'static-depth', 'http': [r[0] for r in replies], 'trace': summary(observed)}))
    diagnostics(e, replies, caplog, capsys)
    assert [r[0] for r in replies] == [400, 400]
    assert observed['sessions'] == observed['dispatches'] == 0
    unchanged(before, facts(e))
    assert call(e, 'receipt', body=good) == (200, oracle)
    committed = facts(e)
    assert call(e, 'receipt', body=good) == (200, oracle)
    assert call(e, 'status', body=fields(c)) == (200, oracle)
    assert observed['callbacks'] == 1 and observed['rejections'] == 0
    unchanged(committed, facts(e)); fenced(e)


def test_normalized_redacted_subtree_not_raw_depth_overrejection(env, monkeypatch):
    e = env; c = prepare(e)
    wire = receipt_body(c, usage={'api_key': nested_usage(64)['datum']})
    assert depth(wire) == 64 and normalized(wire['receipt'])['usage'] == {'api_key': '[REDACTED]'}
    observed = trace(e, monkeypatch, 'receipt'); oracle = expected_receipt(e, wire)
    assert call(e, 'receipt', body=wire) == (200, oracle)
    assert observed['callbacks'] == 1 and observed['rejections'] == 0
    before = facts(e)
    assert call(e, 'receipt', body=wire) == (200, oracle)
    unchanged(before, facts(e)); fenced(e)


@pytest.mark.parametrize('bad_key', ['sk-abcdefghijklmnop', FIXTURE_KEY])
def test_clean_changing_key400_before_lazy_without_echo(env, monkeypatch, bad_key, caplog, capsys):
    e = env; c = prepare(e); wire = receipt_body(c, usage={bad_key: 1})
    assert gateway._clean(normalized(wire['receipt']), e.node['secret']) != normalized(wire['receipt'])
    observed = trace(e, monkeypatch, 'receipt'); before = facts(e)
    replies = [call(e, 'receipt', body=wire) for _ in range(2)]
    diagnostics(e, replies, caplog, capsys, [bad_key])
    assert [reply[0] for reply in replies] == [400, 400]
    assert observed['sessions'] == observed['dispatches'] == 0
    unchanged(before, facts(e)); fenced(e)


def test_strict_normalized_floor_not_guessed_view_overhead400_pre_lazy(env, monkeypatch):
    e = env; c = prepare(e); manifest, tree = output_fixture(e, c)
    wire = receipt_body(c, usage={'datum': []}, manifest=manifest, tree=tree)
    wire['receipt']['usage']['datum'] = [0] * (50001 - item_floor(wire))
    assert item_floor(wire) == 50001 and items(wire) <= 50000 and len(encode(wire)) <= 1500000
    gateway._json_limits(wire)
    observed = trace(e, monkeypatch, 'receipt'); before = facts(e)
    replies = [call(e, 'receipt', body=wire) for _ in range(2)]
    assert [reply[0] for reply in replies] == [400, 400]
    assert observed['sessions'] == observed['dispatches'] == 0
    unchanged(before, facts(e)); fenced(e)


@pytest.mark.parametrize('late', [False, True])
def test_complete_items50001_dynamic500_rolls_back_associated_receipt_only(env, monkeypatch, late, caplog, capsys):
    e = env; c = prepare(e, inputs=128, outputs=('result.txt', 'partial.txt'))
    manifest, tree = output_fixture(e, c)
    if late:
        preparing_fixture(e, c, monkeypatch); e.clock.advance(31)
    bad = receipt_body(c, usage={'datum': []}, manifest=manifest, tree=tree)
    bad['receipt']['usage']['datum'] = [0] * (50001 - items(expected_receipt(e, bad)))
    good = deepcopy(bad); good['receipt']['usage']['datum'].pop()
    assert items(expected_receipt(e, bad)) == 50001 and item_floor(bad) <= 50000
    assert items(expected_receipt(e, good)) == 50000 and len(encode(bad)) <= 1500000
    gateway._json_limits(bad); gateway._body_schema('receipt', bad)
    observed = trace(e, monkeypatch, 'receipt'); before = facts(e)
    replies = [call(e, 'receipt', body=bad) for _ in range(2)]; after = facts(e)
    print(json.dumps({'case': 'dynamic-items', 'late': late, 'http': [r[0] for r in replies],
                      'trace': summary(observed), 'status_after': after['rows'][0]['status']}))
    diagnostics(e, replies, caplog, capsys)
    for reply in replies: dynamic_error(reply)
    assert observed['sessions'] == observed['dispatches'] == observed['callbacks'] == observed['rejections'] == 2
    assert observed['rejection_types'] == ['RuntimeError', 'RuntimeError']
    if late:
        # Independent expire is retained. PREPARING intent/partial bytes are
        # prior effects, not falsely included in receipt rollback/zero writes.
        assert after['rows'][0]['status'] == 'UNKNOWN'
        assert after['rows'][0]['receipt_json'] is after['rows'][0]['manifest_json'] is None
        assert after['rows'][0]['lease_expires_at'] == before['rows'][0]['lease_expires_at']
        for name in ('requests', 'trees', 'uploads', 'sync', 'controls', 'artifact_hashes'):
            assert after[name] == before[name]
        new = after['events'][len(before['events']):]
        assert len(new) == 1 and new[0]['event_type'] == 'WORKER_NODE_CLAIM_UNKNOWN'
    else:
        unchanged(before, after)
    oracle = expected_receipt(e, good)
    assert call(e, 'receipt', body=good) == (200, oracle)
    assert observed['callbacks'] == 3 and observed['rejections'] == 2
    committed = facts(e)
    assert call(e, 'receipt', body=good) == (200, oracle)
    assert call(e, 'status', body=fields(c)) == (200, oracle)
    unchanged(committed, facts(e)); fenced(e)


@pytest.mark.parametrize('delta', [-1, 0, 1])
def test_genuine_complete_bytes_boundary_without_lifting_input_caps(env, monkeypatch, delta, caplog, capsys):
    e = env; c = prepare(e, prompt='p' + '\x00' * 199999)
    tree = {'schema': 1, 'files': [], 'tree': [], 'complete': False,
            'errors': [{'code': 'fixture', 'path': 'Bearer x ' * 111} for _ in range(430)]}
    wire = receipt_body(c, tree=tree)
    # Pure BEFORE-call encoding computes the chosen boundary. No outcome
    # conditional, bare-Request proxy, fake view, or post-outcome adjustment.
    empty_length = len(encode(expected_receipt(e, wire)))
    chunk = 'Bearer x '; width = len(redact(chunk).encode())
    repetitions, remainder = divmod(4000000 + delta - empty_length, width)
    assert repetitions > 0
    wire['receipt']['output'] = chunk * repetitions + 'x' * remainder
    oracle = expected_receipt(e, wire)
    assert len(encode(oracle)) == 4000000 + delta
    assert len(e.request.prompt.encode()) == 200000
    assert len(encode(wire)) <= 1500000 and len(encode(wire['receipt'])) <= 1000000
    assert len(encode(tree)) <= 1000000 and all(len(issue['path'].encode()) <= 1000 for issue in tree['errors'])
    assert items(oracle) <= 50000 and depth(oracle) <= 64 and item_floor(wire) <= 50000
    # Body-only disjoint normalized fragments fit. The stored genuine Request
    # makes the FULL envelope overflow; this is dynamic500, not static400.
    assert len(encode(normalized(wire['receipt']))) + len(encode(redact(tree))) + len(encode(wire['manifest'])) < 4000000
    gateway._json_limits(wire); gateway._body_schema('receipt', wire)
    observed = trace(e, monkeypatch, 'receipt'); before = facts(e)
    replies = [call(e, 'receipt', body=wire) for _ in range(2)]
    print(json.dumps({'case': 'exact-bytes', 'delta': delta, 'body_bytes': len(encode(wire)),
                      'response_bytes': len(encode(oracle)), 'http': [r[0] for r in replies], 'trace': summary(observed)}))
    diagnostics(e, replies, caplog, capsys)
    if delta == 1:
        for reply in replies: dynamic_error(reply)
        assert observed['callbacks'] == observed['rejections'] == 2
        assert observed['rejection_types'] == ['RuntimeError', 'RuntimeError']
        unchanged(before, facts(e))
    else:
        assert replies == [(200, oracle), (200, oracle)]
        assert observed['callbacks'] == 1 and observed['rejections'] == 0
        committed = facts(e)
        assert call(e, 'status', body=fields(c)) == (200, oracle)
        unchanged(committed, facts(e))
    fenced(e)


@pytest.mark.parametrize('padding', ['task', 'cwd'])
def test_genuine_reserve_snapshot_offer_giant_claim_dynamic500_before_claim_commit(env, monkeypatch, padding, caplog, capsys):
    e = env
    view = prepare(e, task_id='t' * 2000001 if padding == 'task' else 'build',
                   cwd_padding=4000001 if padding == 'cwd' else 0, claim=False)
    # Actual public result with all real reservation/auth/role-if-present/input
    # NOFOLLOW/hash fences, not the earlier bare-constructor counterexample.
    assert len(encode(view)) > 4000000 and depth(view) == 4
    wire = {'request_id': 'response_v2_large_claim_01'}
    observed = trace(e, monkeypatch, 'claim'); before = facts(e)
    replies = [call(e, body=wire) for _ in range(2)]
    print(json.dumps({'case': 'public-giant-claim', 'padding': padding, 'offer_bytes': len(encode(view)),
                      'http': [r[0] for r in replies], 'trace': summary(observed),
                      'status_after': facts(e)['rows'][0]['status']}))
    diagnostics(e, replies, caplog, capsys)
    for reply in replies: dynamic_error(reply)
    assert observed['dispatches'] == observed['callbacks'] == observed['rejections'] == 2
    assert observed['rejection_types'] == ['RuntimeError', 'RuntimeError']
    unchanged(before, facts(e))
    assert e.claims.get(e.key)['status'] == 'OFFERED' and not facts(e)['requests']
    fenced(e)


@pytest.mark.parametrize('padding', ['task', 'cwd'])
def test_giant_default_claim_heartbeat500_does_not_renew_and_cached_publish500_never_rebinds(env, monkeypatch, padding):
    e = env
    c = prepare(e, task_id='t' * 2000001 if padding == 'task' else 'build',
                cwd_padding=4000001 if padding == 'cwd' else 0)
    # Default/no-hook compatibility intentionally retains this genuine legacy
    # CLAIMED fact/cache. A fresh heartbeat still gets admission before renewal.
    assert len(encode(c)) > 4000000
    e.clock.advance(5)
    observed = trace(e, monkeypatch, 'heartbeat'); before = facts(e)
    replies = [call(e, 'heartbeat', body=fields(c)) for _ in range(2)]
    print(json.dumps({'case': 'public-giant-heartbeat', 'padding': padding,
                      'http': [r[0] for r in replies], 'trace': summary(observed),
                      'lease_before': before['rows'][0]['lease_expires_at'],
                      'lease_after': facts(e)['rows'][0]['lease_expires_at']}))
    for reply in replies: dynamic_error(reply)
    assert observed['callbacks'] == observed['rejections'] == 2
    unchanged(before, facts(e))
    cached = trace(e, monkeypatch, 'claim')
    for _ in range(2):
        assert call(e, body={'request_id': 'response_v2_fixture_claim_01'})[0] == 500
        assert call(e, 'status', body=fields(c))[0] == 500
    assert cached['dispatches'] == 2 and cached['callbacks'] == 0
    unchanged(before, facts(e)); fenced(e)


@pytest.mark.parametrize('padding', ['ordinary', 'task', 'cwd'])
def test_actual_concurrent_same_request_claim_admission_and_identity_are_atomic(env, monkeypatch, padding):
    e = env
    prepare(e, task_id='t' * 2000001 if padding == 'task' else 'build',
            cwd_padding=4000001 if padding == 'cwd' else 0, claim=False)
    observed = trace(e, monkeypatch, 'claim'); before = facts(e)
    wire = {'request_id': 'response_v2_concurrent_claim_01'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: call(e, body=wire), range(2)))
    print(json.dumps({'case': 'concurrent-same-id', 'padding': padding,
                      'http': [r[0] for r in replies], 'trace': summary(observed)}))
    assert observed['dispatches'] == 2
    if padding == 'ordinary':
        assert replies[0] == replies[1] and replies[0][0] == 200
        assert replies[0][1]['result']['status'] == 'CLAIMED'
        assert observed['callbacks'] == 1 and observed['rejections'] == 0
        after = facts(e)
        assert len(after['requests']) == 1 and after['rows'][0]['status'] == 'CLAIMED'
        fresh = after['events'][len(before['events']):]
        assert len(fresh) == 1 and fresh[0]['event_type'] == 'WORKER_NODE_CLAIMED'
        committed = facts(e)
        assert call(e, body=wire) == replies[0]
        assert observed['callbacks'] == 1
        unchanged(committed, facts(e))
    else:
        for reply in replies: dynamic_error(reply)
        assert observed['callbacks'] == observed['rejections'] == 2
        unchanged(before, facts(e))
    fenced(e)


def test_heartbeat_publishes_only_same_tx_controls_snapshot_no_second_pending_read(env, monkeypatch):
    e = env; c = prepare(e)
    first = {'id': 'response_v2_interrupt_first', 'action': 'interrupt', 'text': ''}
    later = {'id': 'response_v2_interrupt_after_commit', 'action': 'interrupt', 'text': ''}
    e.claims.post_controls(e.key, [first]); e.clock.advance(5)
    expected = e.claims.status(e.node['node_id'], c['claim_id'], c['epoch']) | {'lease_expires_at': e.clock() + 30}
    observed = trace(e, monkeypatch, 'heartbeat', after_return=lambda: e.claims.post_controls(e.key, [later]))
    pending_reads = []; original = e.claims.pending_controls
    def pending(*args):
        pending_reads.append(True); return original(*args)
    monkeypatch.setattr(e.claims, 'pending_controls', pending)
    reply = call(e, 'heartbeat', body=fields(c))
    assert reply == (200, {'controller_mission_id': e.ident, 'result': expected, 'controls': [first]})
    assert pending_reads == [] and observed['callbacks'] == 1 and observed['rejections'] == 0
    assert observed['captures'] == [(expected, [first])]
    assert original(e.node['node_id'], c['claim_id'], c['epoch']) == [first, later]
    assert all(row['status'] == 'PENDING' for row in facts(e)['controls'])
    fenced(e)


@pytest.mark.parametrize('method', ['heartbeat', 'sync'])
def test_original_node_deadline_after_two_arg_validator_is_not_rescued_by_renewal(env, monkeypatch, method):
    e = env; c = prepare(e); e.clock.advance(5)
    # Renewal would be 1035, ORIGINAL deadline 1030. At callback return 1031
    # remains below the new deadline but beyond the old: do not rescue the call.
    observed = trace(e, monkeypatch, method, after_admit=lambda _result, _controls: e.clock.advance(26))
    wire = fields(c)
    if method == 'sync':
        wire |= {'events': [{'seq': 1, 'kind': 'session_bound', 'data': {'session_id': 'fixture-session'}}]}
    before = facts(e)
    code, reply = call(e, method, body=wire)
    assert code == 409 and reply['error']['type'] == 'LeaseLost'
    assert observed['callbacks'] == 1 and observed['rejections'] == 0
    assert c['lease_expires_at'] < e.clock() < 1035
    unchanged(before, facts(e)); fenced(e)
    # Historical status remains readonly; no implicit expire or new reservation.
    assert call(e, 'status', body=fields(c)) == (200, {'controller_mission_id': e.ident, 'result': c})
    unchanged(before, facts(e))


@pytest.mark.parametrize('method', MUTATING)
def test_detached_callback_mutation_cannot_change_canonical_result_or_validated_wire(env, monkeypatch, method):
    e = env; c = prepare(e, claim=method != 'claim')
    def mutate(result, controls):
        result['fixture_callback_mutation'] = 'not part of the canonical result'
        if controls is not None:
            controls.append({'id': 'fixture_injected_control', 'action': 'interrupt', 'text': ''})
    observed = trace(e, monkeypatch, method, after_admit=mutate)
    operation = 'uploads' if method == 'upload' else method
    route, arguments = route_arguments(operation, c)
    if method == 'sync':
        arguments['body']['events'] = [{'seq': 1, 'kind': 'session_bound', 'data': {'session_id': 'fixture-session'}}]
    reply = call(e, route, method='PUT' if method == 'upload' else 'POST', **arguments)
    assert reply[0] == 200 and observed['callbacks'] == 1 and observed['rejections'] == 0
    original_result, original_controls = observed['captures'][0]
    oracle = {'controller_mission_id': e.ident, 'result': original_result}
    if method == 'heartbeat': oracle['controls'] = original_controls
    assert reply[1] == oracle and 'fixture_callback_mutation' not in encode(reply[1]).decode()
    assert gateway._clean(oracle, e.node['secret']) == oracle
    assert method != 'heartbeat' or original_controls == []
    assert 'fixture_callback_mutation' not in facts(e)['logical_state'][0]
    fenced(e)


def test_full_actual_roundtrip_raw_sync_ack_and_restart_keep_original_complete_wire(env, monkeypatch):
    e = env; prepare(e, claim=False)
    observed = trace(e, monkeypatch, 'claim')
    claim_reply = call(e, body={'request_id': 'response_v2_positive_claim_01'})
    assert claim_reply[0] == 200 and claim_reply[1]['result']['status'] == 'CLAIMED'
    assert observed['callbacks'] == 1
    c = claim_reply[1]['result']['claim']; original_claim = deepcopy(claim_reply)
    assert call(e, body={'request_id': 'response_v2_positive_claim_01'}) == original_claim
    assert observed['callbacks'] == 1
    assert call(e, 'inputs/' + c['claim_id'] + '/1', method='GET', query={'path': 'input_000.txt'}) == (200, b'fixed input')
    control = {'id': 'response_v2_positive_interrupt', 'action': 'interrupt', 'text': ''}
    e.claims.post_controls(e.key, [control])
    heartbeat = trace(e, monkeypatch, 'heartbeat')
    assert call(e, 'heartbeat', body=fields(c))[1]['controls'] == [control]
    assert heartbeat['callbacks'] == 1 and facts(e)['controls'][0]['status'] == 'PENDING'
    synced = trace(e, monkeypatch, 'sync')
    events = [{'seq': 1, 'kind': 'control_ack', 'data': {'command_id': control['id'], 'accepted': True}}]
    first_sync = call(e, 'sync', body=fields(c) | {'events': events})
    assert first_sync[0] == 200 and set(first_sync[1]['result']) == {
        'mission_id', 'run_key', 'node_id', 'claim_id', 'epoch', 'last_seq', 'lease_expires_at'}
    assert first_sync[1]['result']['last_seq'] == 1 and synced['callbacks'] == 1
    stable = facts(e)
    assert call(e, 'sync', body=fields(c) | {'events': events}) == first_sync
    assert call(e, 'sync', body=fields(c) | {'events': []}) == first_sync
    assert synced['callbacks'] == 1 and facts(e)['controls'][0]['status'] == 'ACK'
    unchanged(stable, facts(e))
    uploads = trace(e, monkeypatch, 'upload'); raw = b'fixed stored output'
    entry = {'path': 'result.txt', 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    arguments = {'method': 'PUT', 'raw': raw, 'query': {'path': entry['path'], 'sha256': entry['sha256']}}
    upload_reply = (200, {'controller_mission_id': e.ident, 'result': entry | {'status': 'STORED'}})
    assert call(e, 'uploads/' + c['claim_id'] + '/1', **arguments) == upload_reply
    uploaded = facts(e)
    assert call(e, 'uploads/' + c['claim_id'] + '/1', **arguments) == upload_reply
    assert uploads['callbacks'] == 1
    unchanged(uploaded, facts(e))
    tree_root = e.root / 'roundtrip-v2-tree'; tree_root.mkdir()
    (tree_root / 'result.txt').write_bytes(raw)
    wire = receipt_body(c, usage={'ordinary': 7}, manifest=[entry], tree=full_tree_manifest(tree_root))
    oracle = expected_receipt(e, wire); receipts = trace(e, monkeypatch, 'receipt')
    assert call(e, 'receipt', body=wire) == (200, oracle) and receipts['callbacks'] == 1
    committed = facts(e)
    assert call(e, 'receipt', body=wire) == (200, oracle) and receipts['callbacks'] == 1
    changed = deepcopy(wire); changed['receipt']['output'] = 'explicit conflict'
    assert call(e, 'receipt', body=changed)[0] == 409
    unchanged(committed, facts(e))
    # Genuine full Hub/LeadMission reopen, not a fake cached HTTP response.
    reopened = MissionHub(e.hub.directory); e.gateway.hub = reopened
    assert call(e, 'receipt', body=wire) == (200, oracle)
    assert call(e, 'status', body=fields(c)) == (200, oracle)
    unchanged(committed, facts(e)); fenced(e); reopened.close()
