"""Frozen Gateway response-admission protocol tests; NOT a source/native PASS.

Real isolated loopback and public NodeClaims only. Required opt-in, retained
runner/guard, and readonly byte-pinned 8302 for the old-capability control.
Halley owns direct Core callback tests. These observe Gateway's real dispatch,
rollback, complete wire and replay; wrappers only delegate/count, never ACK.
"""
from __future__ import annotations

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
FIXTURE_KEY = 'gateway_response_fixture_provider_key_abcdef'
ROUTES = [('claim', 'POST'), ('sync', 'POST'), ('heartbeat', 'POST'),
          ('status', 'POST'), ('receipt', 'POST'), ('inputs', 'GET'), ('uploads', 'PUT')]


@pytest.fixture(autouse=True)
def only_fixture_provider_values(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', FIXTURE_KEY)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'gateway_response_fixture_anthropic_abcdef')


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def count(value):
    # Exactly Gateway's nodes: dict KEYS are not items; each container counts.
    return 1 + (sum(count(child) for child in value.values()) if isinstance(value, dict)
                else sum(count(child) for child in value) if isinstance(value, list) else 0)


def depth(value):
    children = list(value.values()) if isinstance(value, dict) else value if isinstance(value, list) else []
    return 1 + max(map(depth, children)) if children else 0


def normalized_receipt(raw):
    return redact(asdict(Receipt(**raw)))


def floor(body):
    return (3 + count(normalized_receipt(body['receipt'])) + count(body['manifest'])
            + 1 + 5 * len(body['manifest']) + count(redact(body['tree'])))


def body(c, *, usage=None, output='', status='COMPLETED', manifest=None, tree=None):
    return fields(c) | {'receipt': {'status': status, 'usage': usage or {}, 'output': output},
                       'manifest': manifest or [],
                       'tree': tree or {'schema': 1, 'files': [], 'tree': [], 'errors': [], 'complete': True}}


def nested_usage(body_depth):
    value = 0
    for _ in range(body_depth - 3):
        value = [value]
    return {'datum': value}


def expected(e, wire):
    # Oracle from the real immutable PRE-call view and original public Receipt
    # defaults/redact. No post-outcome golden or fabricated backend response.
    view = e.claims.status(e.node['node_id'], wire['claim_id'], wire['epoch'])
    late = view['status'] != 'CLAIMED' or view['lease_expires_at'] <= e.clock()
    terminal = 'RECONCILIATION_CANDIDATE' if late else 'UNKNOWN' if wire['receipt']['status'] == 'UNKNOWN' else 'RECEIPTED'
    return {'controller_mission_id': e.ident, 'result': view | {
        'status': terminal, 'receipt': normalized_receipt(wire['receipt']),
        'manifest': sorted(wire['manifest'], key=lambda item: item['path']), 'tree': redact(wire['tree'])}}


def prepare(e, *, inputs=1, outputs=('result.txt',), prompt='Fixed response fixture', direct_claim=False):
    e.claims = NodeClaims(e.mission.journal, e.registry,
                         e.mission.directory / 'remote' / 'artifacts', clock=e.clock)
    e.mission._node_claims = e.claims
    source = e.root / 'response-input-source'; source.mkdir()
    for index in range(inputs):
        (source / f'input_{index:03}.txt').write_bytes(b'fixed input')
    e.snapshot = e.root / 'response-input-snapshot'
    e.manifest = create_input_snapshot(source, e.snapshot, list(outputs))
    request = Request('build', prompt, str(e.snapshot), 'gpt-6.1-sol', mode='workspace-write')
    e.key = 'response-admission-run'
    e.mission.journal.reserve(e.key, 'build', digest(asdict(request)))
    e.claims.bind_input_snapshot(e.key, e.snapshot, e.manifest)
    e.claims.offer(e.key, e.node['node_id'], request, e.manifest)
    if direct_claim:
        # Real controller-side public service fixture, never a fake HTTP ACK.
        c = e.claims.claim(e.node['node_id'], 'response_admission_claim_01')['claim']
    else:
        code, reply = call(e, body={'request_id': 'response_admission_claim_01'})
        assert code == 200
        c = reply['result']['claim']
    assert c['status'] == 'CLAIMED'
    return c


def stored_output(e, c):
    raw = b'fixed stored output'
    entry = {'path': 'result.txt', 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    code, reply = call(e, 'uploads/' + c['claim_id'] + '/1', method='PUT', raw=raw,
                       query={key: entry[key] for key in ('path', 'sha256')})
    assert (code, reply) == (200, {'controller_mission_id': e.ident, 'result': entry | {'status': 'STORED'}})
    worktree = e.root / 'response-native-tree'; worktree.mkdir()
    (worktree / entry['path']).write_bytes(raw)
    return [entry], full_tree_manifest(worktree)


def facts(e):
    with e.mission.store._transaction(immediate=False) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        receipt_rows = [dict(row) for row in db.execute('SELECT run_key,status,claim_id,epoch,lease_expires_at,receipt_json,manifest_json FROM remote_offers ORDER BY run_key')] if 'remote_offers' in tables else []
        trees = [dict(row) for row in db.execute('SELECT * FROM remote_receipt_trees ORDER BY claim_id')] if 'remote_receipt_trees' in tables else []
        uploads = [dict(row) for row in db.execute('SELECT * FROM remote_uploads ORDER BY claim_id,path')] if 'remote_uploads' in tables else []
        events = [dict(row) for row in db.execute('SELECT seq,event_type,entity_id,data_json,prev_hash,event_hash FROM events ORDER BY seq')]
    root = e.mission.directory / 'remote'
    artifact_bytes = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in root.rglob('*') if path.is_file()} if root.exists() else {}
    return {'rows': receipt_rows, 'trees': trees, 'uploads': uploads, 'events': events,
            'artifact_hashes': artifact_bytes, 'logical_state': state(e),
            'filesystem_names_including_aux': sorted(str(p.relative_to(e.hub.directory)) for p in e.hub.directory.rglob('*'))}


def receipt_unchanged(before, after):
    for name in ('rows', 'trees', 'uploads', 'events', 'artifact_hashes', 'logical_state'):
        assert after[name] == before[name], name
    # Physical WAL auxiliary-file policy remains a separate Main/human oracle.


def trace_dispatch(e, monkeypatch):
    counts = {'sessions': 0, 'dispatches': 0, 'callbacks': 0, 'callback_failures': 0}
    original_session = e.hub._session
    original_receipt = e.claims.receipt

    def session(ident):
        counts['sessions'] += 1
        return original_session(ident)

    @wraps(original_receipt)
    def receipt(*args, **kwargs):
        counts['dispatches'] += 1
        admitted = kwargs.get('admit_response')
        if admitted is not None:
            def track(view):
                counts['callbacks'] += 1
                try:
                    return admitted(view)
                except Exception:
                    counts['callback_failures'] += 1
                    raise
            kwargs = kwargs | {'admit_response': track}
        return original_receipt(*args, **kwargs)

    monkeypatch.setattr(e.hub, '_session', session)
    monkeypatch.setattr(e.claims, 'receipt', receipt)
    return counts


def private_diagnostics(e, replies, caplog, capsys, forbidden=()):
    observed = json.dumps(replies, ensure_ascii=False) + caplog.text + capsys.readouterr().err
    assert e.node['secret'] not in observed
    assert all(text not in observed for text in forbidden)


def assert_core_fenced(e):
    assert e.mission.journal.runs()[0]['status'] == 'IN_FLIGHT'
    assert e.mission.store.verify_event_chain()['valid']


@pytest.mark.parametrize('status', ['COMPLETED', 'ERROR', 'INTERRUPTED', 'UNKNOWN'])
def test_static_response_depth_rejects_before_lazy_dispatch_then_deliverable_depth_replays(env, monkeypatch, status, caplog, capsys):
    e = env; c = prepare(e); manifest, tree = stored_output(e, c)
    bad = body(c, usage=nested_usage(64), status=status, manifest=manifest, tree=tree)
    assert depth(bad) == 64 and depth(expected(e, bad)) == 65
    counts = trace_dispatch(e, monkeypatch); before = facts(e)
    replies = [call(e, 'receipt', body=bad) for _ in range(2)]
    print(json.dumps({'case': 'depth64', 'http': [r[0] for r in replies], 'counts': counts,
                      'row_status_after': facts(e)['rows'][0]['status']}))
    assert [r[0] for r in replies] == [400, 400]
    assert counts == {'sessions': 0, 'dispatches': 0, 'callbacks': 0, 'callback_failures': 0}
    receipt_unchanged(before, facts(e)); private_diagnostics(e, replies, caplog, capsys)
    good = body(c, usage=nested_usage(63), status=status, manifest=manifest, tree=tree)
    oracle = expected(e, good); assert depth(oracle) == 64
    assert call(e, 'receipt', body=good) == (200, oracle)
    assert counts['dispatches'] == counts['callbacks'] == 1 and counts['callback_failures'] == 0
    committed = facts(e)
    assert call(e, 'receipt', body=good) == (200, oracle)
    assert call(e, 'status', body=fields(c)) == (200, oracle)
    receipt_unchanged(committed, facts(e)); assert_core_fenced(e)


def test_depth_under_redacted_value_is_admitted_without_overrejecting_raw_subtree(env, monkeypatch):
    e = env; c = prepare(e)
    wire = body(c, usage={'api_key': nested_usage(64)['datum']})
    assert depth(wire) == 64 and normalized_receipt(wire['receipt'])['usage'] == {'api_key': '[REDACTED]'}
    oracle = expected(e, wire); counts = trace_dispatch(e, monkeypatch)
    assert call(e, 'receipt', body=wire) == (200, oracle)
    assert counts['callbacks'] == 1 and counts['callback_failures'] == 0
    before = facts(e)
    assert call(e, 'receipt', body=wire) == (200, oracle)
    assert call(e, 'status', body=fields(c)) == (200, oracle)
    receipt_unchanged(before, facts(e)); assert_core_fenced(e)


@pytest.mark.parametrize('bad_key', ['sk-abcdefghijklmnop', FIXTURE_KEY])
def test_redact_changing_receipt_key_rejected_before_session_without_echo(env, monkeypatch, bad_key, caplog, capsys):
    e = env; c = prepare(e)
    wire = body(c, usage={bad_key: 1})
    r = normalized_receipt(wire['receipt'])
    assert gateway._clean(r, e.node['secret']) != r
    counts = trace_dispatch(e, monkeypatch); before = facts(e)
    replies = [call(e, 'receipt', body=wire) for _ in range(2)]
    assert [r[0] for r in replies] == [400, 400]
    assert counts['sessions'] == counts['dispatches'] == 0
    receipt_unchanged(before, facts(e)); private_diagnostics(e, replies, caplog, capsys, [bad_key])
    good = body(c, usage={'SK-abcdefghijklmnop': 1})
    oracle = expected(e, good)
    assert call(e, 'receipt', body=good) == (200, oracle)
    assert call(e, 'receipt', body=good) == (200, oracle); assert_core_fenced(e)


def test_normalized_strict_count_floor_rejected_before_lazy_backend(env, monkeypatch):
    e = env; c = prepare(e); manifest, tree = stored_output(e, c)
    wire = body(c, usage={'datum': []}, manifest=manifest, tree=tree)
    wire['receipt']['usage']['datum'] = [0] * (50001 - floor(wire))
    assert floor(wire) == 50001 and count(wire) <= 50000 and len(encode(wire)) <= 1500000
    gateway._json_limits(wire)
    counts = trace_dispatch(e, monkeypatch); before = facts(e)
    replies = [call(e, 'receipt', body=wire) for _ in range(2)]
    assert [r[0] for r in replies] == [400, 400]
    assert counts['sessions'] == counts['dispatches'] == 0
    receipt_unchanged(before, facts(e)); assert_core_fenced(e)


@pytest.mark.parametrize('late', [False, True])
def test_exact_items_callback_rolls_back_receipt_but_independent_expire_stays_attributed(env, monkeypatch, late, caplog, capsys):
    e = env; c = prepare(e, inputs=128, outputs=('result.txt', 'partial.txt')); manifest, tree = stored_output(e, c)
    if late:
        # Existing PREPARING upload is separately committed, never erased by a
        # failed receipt. The partial retained file is deliberate known DATA.
        with e.mission.store._transaction() as db:
            db.execute('INSERT INTO remote_uploads VALUES(?,?,?,?,?)',
                       (c['claim_id'], 'partial.txt', 'a' * 64, 7, 'PREPARING'))
        (e.claims.artifact_root / c['claim_id'] / 'partial.txt').write_bytes(b'partial')
        e.clock.advance(31)
    wire = body(c, usage={'datum': []}, manifest=manifest, tree=tree)
    wire['receipt']['usage']['datum'] = [0] * (50001 - count(expected(e, wire)))
    oracle_bad = expected(e, wire)
    assert count(oracle_bad) == 50001 and floor(wire) <= 50000 < count(oracle_bad)
    assert count(wire) <= 50000 and len(encode(wire)) <= 1500000
    gateway._json_limits(wire)
    counts = trace_dispatch(e, monkeypatch); before = facts(e)
    replies = [call(e, 'receipt', body=wire) for _ in range(2)]
    after = facts(e)
    print(json.dumps({'case': 'items50001', 'late': late, 'http': [r[0] for r in replies], 'counts': counts,
                      'events_before': len(before['events']), 'events_after': len(after['events']), 'status_after': after['rows'][0]['status']}))
    assert [r[0] for r in replies] == [400, 400]
    assert counts == {'sessions': 2, 'dispatches': 2, 'callbacks': 2, 'callback_failures': 2}
    if late:
        assert after['rows'][0]['status'] == 'UNKNOWN'
        assert after['rows'][0]['receipt_json'] is after['rows'][0]['manifest_json'] is None
        assert after['rows'][0]['lease_expires_at'] == before['rows'][0]['lease_expires_at']
        assert after['trees'] == before['trees'] and after['uploads'] == before['uploads']
        assert after['artifact_hashes'] == before['artifact_hashes']
        new_events = after['events'][len(before['events']):]
        assert len(new_events) == 1 and new_events[0]['event_type'] == 'WORKER_NODE_CLAIM_UNKNOWN'
    else:
        receipt_unchanged(before, after)
    private_diagnostics(e, replies, caplog, capsys); assert_core_fenced(e)
    wire['receipt']['usage']['datum'].pop()
    oracle = expected(e, wire); assert count(oracle) == 50000
    assert call(e, 'receipt', body=wire) == (200, oracle)
    assert counts['callbacks'] == 3 and counts['callback_failures'] == 2
    committed = facts(e)
    assert call(e, 'receipt', body=wire) == (200, oracle)
    assert call(e, 'status', body=fields(c)) == (200, oracle)
    receipt_unchanged(committed, facts(e)); assert_core_fenced(e)


def test_byte_bound_is_reachable_under_original_input_caps_and_rolls_back(env, monkeypatch):
    e = env; c = prepare(e, prompt='p' + '\x00' * 199999)
    tree = {'schema': 1, 'files': [], 'tree': [], 'complete': False,
            'errors': [{'code': 'fixture', 'path': 'Bearer x ' * 111} for _ in range(430)]}
    wire = body(c, output='Bearer x ' * 109000, tree=tree)
    assert len(encode(wire)) <= 1500000 and len(encode(wire['receipt'])) <= 1000000
    assert len(encode(tree)) <= 1000000 and len(tree['errors']) <= 4096
    assert all(len(issue['path'].encode()) <= 1000 for issue in tree['errors'])
    gateway._json_limits(wire); gateway._body_schema('receipt', wire)
    oracle = expected(e, wire)
    assert count(oracle) <= 50000 and depth(oracle) <= 64
    assert floor(wire) <= count(oracle) and len(encode(oracle)) > 4000000
    counts = trace_dispatch(e, monkeypatch); before = facts(e)
    replies = [call(e, 'receipt', body=wire) for _ in range(2)]
    print(json.dumps({'case': 'bytes', 'body_bytes': len(encode(wire)), 'full_response_bytes': len(encode(oracle)),
                      'http': [r[0] for r in replies], 'counts': counts}))
    assert [r[0] for r in replies] == [400, 400]
    assert counts == {'sessions': 2, 'dispatches': 2, 'callbacks': 2, 'callback_failures': 2}
    receipt_unchanged(before, facts(e)); assert_core_fenced(e)


def select_named_child(e, ident):
    # Retained move of a real bound fixture DB with valid registered credentials.
    # No replacement of auth/backend result, native session or immutable spec.
    target = e.hub.directory / ident
    e.mission.directory.rename(target)
    e.hub = MissionHub(e.hub.directory)
    e.ident = ident; e.gateway.hub = e.hub
    e.mission = e.hub._session(ident).mission
    e.registry = NodeRegistry(e.mission.journal)


@pytest.mark.parametrize('identity', ['sk-learn-baseline', 'provider', 'literal_node_secret'])
@pytest.mark.parametrize('stage', ['cold', 'offered'])
@pytest.mark.parametrize('operation,method', ROUTES)
def test_unclean_mission_id_404_before_auth_hub_or_dispatch(env, monkeypatch, identity, stage, operation, method, caplog, capsys):
    e = env
    ident = FIXTURE_KEY if identity == 'provider' else e.node['secret'] if identity == 'literal_node_secret' else identity
    assert gateway._clean(ident, e.node['secret']) != ident
    select_named_child(e, ident)
    if stage == 'offered':
        prepare(e, direct_claim=True)
    before = facts(e); calls = {'auth': 0, 'path': 0, 'session': 0}
    auth, path, session = gateway._auth, e.hub.path, e.hub._session
    def observe_auth(*args):
        calls['auth'] += 1
        return auth(*args)
    def observe_path(value):
        calls['path'] += 1
        return path(value)
    def observe_session(value):
        calls['session'] += 1
        return session(value)
    monkeypatch.setattr(gateway, '_auth', observe_auth)
    monkeypatch.setattr(e.hub, 'path', observe_path)
    monkeypatch.setattr(e.hub, '_session', observe_session)
    fake_c = {'claim_id': 'claim_' + 'a' * 32, 'epoch': 1}
    payload = {'request_id': 'response_identity_claim_01'} if operation == 'claim' else fields(fake_c)
    if operation == 'sync': payload |= {'events': []}
    if operation == 'receipt': payload = body(fake_c)
    query, raw, route = None, None, operation
    if operation in {'inputs', 'uploads'}:
        route += '/' + fake_c['claim_id'] + '/1'; payload = None
        query = {'path': 'input_000.txt' if operation == 'inputs' else 'result.txt'}
        if operation == 'uploads':
            raw = b'fixed'; query['sha256'] = hashlib.sha256(raw).hexdigest()
    replies = [call(e, route, method=method, body=payload, query=query, raw=raw) for _ in range(2)]
    print(json.dumps({'case': 'mission_identity', 'kind': identity, 'stage': stage,
                      'operation': operation, 'http': [r[0] for r in replies], 'calls': calls}))
    assert [r[0] for r in replies] == [404, 404]
    assert calls == {'auth': 0, 'path': 0, 'session': 0}
    receipt_unchanged(before, facts(e))
    private_diagnostics(e, replies, caplog, capsys, [ident])
    if stage == 'cold':
        assert not (e.mission.directory / 'remote').exists() and e.mission._node_claims is None
    e.hub.close()


@pytest.mark.parametrize('ident', ['SK-learn-baseline', 'learn-baseline'])
def test_ordinary_named_child_retains_claim_wire_and_replay(env, ident):
    e = env; select_named_child(e, ident)
    wire = {'request_id': 'response_identity_control_01'}
    oracle = {'controller_mission_id': ident, 'result': {'mission_id': e.registry.mission_id,
        'node_id': e.node['node_id'], 'request_id': wire['request_id'], 'status': 'NO_WORK', 'claim': None}}
    assert call(e, body=wire) == (200, oracle)
    before = facts(e)
    assert call(e, body=wire) == (200, oracle)
    receipt_unchanged(before, facts(e)); e.hub.close()


def test_missing_named_public_admission_is_dependency500_before_dispatch_real_8302(env, monkeypatch):
    e = env; c = prepare(e)
    path = Path(os.environ['SISYFUS_GATEWAY_RESPONSE_CLAIMS_BASELINE'])
    assert path.is_absolute() and path.stat().st_mode & 0o222 == 0
    assert hashlib.sha256(path.read_bytes()).hexdigest() == OLD_SHA
    spec = importlib.util.spec_from_file_location('sisyfus.workers._response_admission_8302', path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module); spec.loader.exec_module(module)
    e.claims = module.NodeClaims(e.mission.journal, e.registry, e.mission.directory / 'remote' / 'artifacts', clock=e.clock)
    e.mission._node_claims = e.claims
    assert 'admit_response' not in inspect.signature(e.claims.receipt).parameters
    counts = trace_dispatch(e, monkeypatch); before = facts(e)
    code, reply = call(e, 'receipt', body=body(c))
    assert code == 500 and 'receipt response admission' in reply['error']['message']
    assert counts == {'sessions': 1, 'dispatches': 0, 'callbacks': 0, 'callback_failures': 0}
    receipt_unchanged(before, facts(e))
    assert call(e, 'sync', body=fields(c) | {'events': []})[0] == 200
    assert call(e, 'status', body=fields(c))[1]['result'] == e.claims.status(e.node['node_id'], c['claim_id'], 1)
    assert_core_fenced(e)


def test_ordinary_real_roundtrip_controls_conflict_and_restart_preserve_full_wire(env, monkeypatch):
    e = env; c = prepare(e); manifest, tree = stored_output(e, c)
    assert call(e, 'inputs/' + c['claim_id'] + '/1', method='GET', query={'path': 'input_000.txt'}) == (200, b'fixed input')
    event = [{'seq': 1, 'kind': 'session_bound', 'data': {'session_id': 'fixture-session'}}]
    sync = call(e, 'sync', body=fields(c) | {'events': event})
    assert sync[0] == 200 and set(sync[1]['result']) == {'mission_id', 'run_key', 'node_id', 'claim_id', 'epoch', 'last_seq', 'lease_expires_at'}
    assert call(e, 'sync', body=fields(c) | {'events': event}) == sync
    e.claims.post_controls(e.key, [{'id': 'response_fixture_interrupt', 'action': 'interrupt', 'text': ''}])
    heartbeat = call(e, 'heartbeat', body=fields(c))
    assert heartbeat[0] == 200 and heartbeat[1]['controls'] == e.claims.pending_controls(e.node['node_id'], c['claim_id'], 1)
    wire = body(c, usage={'ordinary': 7}, manifest=manifest, tree=tree)
    oracle = expected(e, wire); counts = trace_dispatch(e, monkeypatch)
    assert call(e, 'receipt', body=wire) == (200, oracle)
    assert counts['callbacks'] == 1 and counts['callback_failures'] == 0
    assert call(e, 'receipt', body=wire) == (200, oracle)
    before = facts(e)
    assert call(e, 'receipt', body=wire | {'receipt': wire['receipt'] | {'output': 'changed'}})[0] == 409
    receipt_unchanged(before, facts(e))
    new_hub = MissionHub(e.hub.directory)
    e.gateway.hub = new_hub
    assert call(e, 'receipt', body=wire) == (200, oracle)
    assert call(e, 'status', body=fields(c)) == (200, oracle)
    receipt_unchanged(before, facts(e)); assert_core_fenced(e); new_hub.close()


def finalizer():
    function = getattr(gateway, '_finalize_envelope', None)
    assert callable(function), 'shared complete envelope finalizer is required'
    return function


@pytest.mark.parametrize('delta', [-1, 0, 1])
def test_pure_finalizer_exact_byte_limit_without_branch_based_http_oracle(delta):
    function = finalizer(); result = {'datum': ''}; ident = 'mission_fixture'
    framing = len(encode({'controller_mission_id': ident, 'result': result}))
    result['datum'] = 'x' * (4000000 + delta - framing)
    envelope = {'controller_mission_id': ident, 'result': result}
    assert len(encode(envelope)) == 4000000 + delta
    if delta <= 0:
        assert function(ident, result, '') == envelope
    else:
        with pytest.raises(RuntimeError): function(ident, result, '')


@pytest.mark.parametrize('limit,delta', [('depth', 0), ('depth', 1), ('items', 0), ('items', 1)])
def test_pure_finalizer_fixed_structural_boundary(limit, delta):
    function = finalizer(); result = {'datum': []}
    if limit == 'depth':
        value = 0
        for _ in range(62 + delta): value = [value]
        result['datum'] = value
    else:
        result['datum'] = [0] * (49996 + delta)
    envelope = {'controller_mission_id': 'mission_fixture', 'result': result}
    assert (depth(envelope) if limit == 'depth' else count(envelope)) == (64 if limit == 'depth' else 50000) + delta
    if delta == 0:
        assert function('mission_fixture', result, '') == envelope
    else:
        with pytest.raises(RuntimeError): function('mission_fixture', result, '')


def test_pure_finalizer_counter_excludes_dictionary_keys():
    result = {f'key_{index}': 0 for index in range(25000)}
    envelope = {'controller_mission_id': 'mission_fixture', 'result': result}
    assert count(envelope) == 25003
    gateway._json_limits(envelope)
    assert finalizer()('mission_fixture', result, '') == envelope


def test_actual_other_route_depth_and_public_request_byte_bound_gap_are_explicit():
    request = asdict(Request('t' * 2000000, 'fixture', str(Path(__file__).resolve().parents[2]),
                             'gpt-6.1-sol', mode='workspace-write'))
    # Static schema witness, not a fake service response or gateway PASS. The
    # source-only requirement cannot infer a global byte bound from prompt alone.
    view = {'task_id': request['task_id'], 'request': request,
            'input_manifest': {'files': [{'path': 'a', 'sha256': 'b' * 64, 'size': 0}], 'output_paths': []}}
    envelope = {'controller_mission_id': 'mission_fixture', 'result': {'claim': view}}
    assert depth(envelope) == 6 and count(envelope) < 50000
    assert len(encode(envelope)) > 4000000
    assert (gateway.MAX_JSON_DEPTH, gateway.MAX_JSON_ITEMS, gateway.MAX_RESPONSE_BYTES,
            gateway.MAX_JSON_BYTES, gateway.MAX_UPLOAD_BYTES) == (64, 50000, 4000000, 1500000, 8000000)
