"""Frozen v1 P2 cause tests; distinct from ADDITIONAL_VERIFICATION and original116.

Real authenticated fixture gateway/injected AgentDriver; actual native APFS
case/normalization/firmlink identities, not mocked stat/path resolution. Retain
everything. No permanent deletion, model call, deployment or controller Start.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import unicodedata

import pytest

from sisyfus.workers.node_claims import _tree_payload
from sisyfus.workers.protocol import digest
from sisyfus.workers.remote_artifacts import full_tree_manifest
from test_node_agent import (AgentDriver, agent_env, agent_type, execute,
                             lose_response, publish, retained_bytes)


def _local(e):
    db = sqlite3.connect((e.state / 'agent.sqlite3').as_uri() + '?mode=ro', uri=True, timeout=.5)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        rows = db.execute('SELECT * FROM attempts').fetchall()
        assert len(rows) == 1
        row = dict(rows[0])
        for key in ('offer', 'tree', 'receipt', 'receipt_body'):
            row[key] = json.loads(row[key]) if row[key] else None
        return row
    finally:
        db.close()


@pytest.mark.parametrize('name', ['sk-learn-notebooks/run.txt', 'Bearer fixture-filename.txt'])
@pytest.mark.parametrize('drop_receipt', [False, True])
def test_canonical_redacted_tree_ack_preserves_raw_native_fact_and_replay(agent_env, monkeypatch, name, drop_receipt):
    e = agent_env
    original = publish(e)
    original_spec = digest(e.mission.spec)
    source_before = full_tree_manifest(e.source)
    snapshot_before = full_tree_manifest(e.snapshot)
    received = []
    receipt_method = e.claims.receipt

    def receipt(node, claim, epoch, native, manifest, *, tree, admit_response=None):
        answer = receipt_method(node, claim, epoch, native, manifest, tree=tree, admit_response=admit_response)
        received.append({'raw_native': json.loads(json.dumps(native)), 'raw_manifest': json.loads(json.dumps(manifest)),
                         'raw_tree': json.loads(json.dumps(tree)), 'wire': json.loads(json.dumps(answer))})
        return answer

    monkeypatch.setattr(e.claims, 'receipt', receipt)

    def native(request, emit, controls):
        assert asdict(request) | {'cwd': e.request.cwd} == asdict(e.request)
        path = Path(request.cwd) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'legitimate filename, not credential data')
        return None  # Same frozen protocol AgentDriver emits its original events/receipt.

    driver = AgentDriver(native)
    if drop_receipt:
        dropped = lose_response(e, monkeypatch, '/receipt')
        agent, _ = execute(e, driver)
        with pytest.raises(RuntimeError, match='RemoteDisconnected'):
            agent.run_once()
        assert len(dropped) == 1
    agent, _ = execute(e, driver)
    result = agent.run_once()
    assert result['status'] == 'RECEIPTED'
    attempt = _local(e)
    assert attempt['status'] == 'DONE' and len(driver.requests) == 1
    raw_tree = full_tree_manifest(driver.requests[0].cwd)
    assert attempt['tree'] == raw_tree and any(item['path'] == name for item in raw_tree['tree'])
    raw_hash, stored_tree = _tree_payload(raw_tree)
    canonical_tree = json.loads(stored_tree)
    assert canonical_tree != raw_tree
    wire = received[-1]['wire']
    assert wire == e.claims.status(e.node['node_id'], attempt['offer']['claim_id'], attempt['offer']['epoch'])
    assert wire['tree'] == canonical_tree and wire['receipt'] == attempt['receipt']
    assert wire['manifest'] == attempt['receipt_body']['manifest']
    assert wire['fingerprint'] == original['fingerprint']
    assert attempt['receipt_body']['tree'] == raw_tree
    assert all(item['raw_tree'] == raw_tree and item['raw_native'] == attempt['receipt']
               and item['raw_manifest'] == attempt['receipt_body']['manifest'] for item in received)
    assert attempt['receipt']['status'] == 'COMPLETED' and attempt['receipt']['actual_model'] is None
    assert wire['manifest'] == [{'path': 'result.txt', 'sha256': hashlib.sha256(b'42').hexdigest(), 'size': 2}]
    assert wire['uploads'] == [wire['manifest'][0] | {'status': 'STORED'}]
    assert (e.claims.artifact_root / wire['claim_id'] / 'result.txt').read_bytes() == b'42'
    assert all(item['path'] != name for item in wire['uploads'])
    with e.mission.store._transaction(immediate=False) as db:
        stored = db.execute('SELECT raw_digest,tree_json FROM remote_receipt_trees WHERE claim_id=?', (wire['claim_id'],)).fetchone()
    assert stored[0] == raw_hash and stored[1] == stored_tree
    fixed = json.dumps(attempt['receipt_body'], sort_keys=True)
    restarted, _ = execute(e, driver)
    assert restarted.run_once()['status'] == 'RECEIPTED'
    assert json.dumps(_local(e)['receipt_body'], sort_keys=True) == fixed and len(driver.requests) == 1
    assert full_tree_manifest(e.source) == source_before and full_tree_manifest(e.snapshot) == snapshot_before
    assert digest(e.mission.spec) == original_spec and not e.mission.snapshot()['all_verified']
    core = e.mission.journal.runs()[0]
    assert core['status'] == 'IN_FLIGHT' and core['receipt'] is None and core['verdict'] == 'UNVERIFIED'
    assert e.mission.store.verify_event_chain()['valid']
    assert e.node['secret'].encode() not in retained_bytes(e.state)
    (e.root / 'P2-canonical-ack.json').write_text(json.dumps({'classification': 'P2_MICRO', 'filename': name,
        'drop_receipt': drop_receipt, 'raw_tree': raw_tree, 'canonical_tree': canonical_tree,
        'raw_tree_hash': raw_hash, 'local_status': attempt['status'], 'native_call_count': len(driver.requests),
        'native_fact_and_manifest': 'UNCHANGED', 'core': 'IN_FLIGHT / UNVERIFIED / no receipt'}, indent=2))


def _identity(path):
    info = path.stat(follow_symlinks=False)
    return [info.st_dev, info.st_ino]


def _apfs(path):
    result = subprocess.run(['/sbin/mount'], timeout=3, capture_output=True, text=True)
    assert result.returncode == 0
    mounted = []
    for line in result.stdout.splitlines():
        if ' on ' not in line or ' (' not in line:
            continue
        location, flags = line.split(' on ', 1)[1].rsplit(' (', 1)
        root = Path(location)
        if path.is_relative_to(root):
            mounted.append((len(root.parts), flags.split(',', 1)[0], line))
    assert mounted and max(mounted)[1] == 'apfs', 'actual APFS fixture required, no mocked filesystem/skip'
    return max(mounted)[2]


def _credential(path):
    config = {'schema': 1, 'controller_mission_id': 'm_fixture', 'node_id': 'node_' + '1' * 32,
              'secret': '2' * 64, 'gateway_url': 'http://127.0.0.1:1', 'gateway_host': '127.0.0.1:1'}
    path.write_text(json.dumps(config)); path.chmod(0o600)
    return config


@pytest.mark.parametrize('alias', ['case', 'nested_workspace_case', 'normalization', 'firmlink'])
def test_actual_apfs_credential_ancestor_identity_rejects_state_alias(agent_type, tmp_path, alias):
    state = tmp_path / ('Státé' if alias == 'normalization' else 'STATE')
    state.mkdir(mode=0o700)
    parent = state
    if alias == 'nested_workspace_case':
        parent = state / 'WORKSPACES'
        parent.mkdir(mode=0o700)
    credential = parent / 'node-auth.json'
    _credential(credential)
    state_argument = state
    if alias in {'case', 'nested_workspace_case'}:
        state_argument = state.with_name(state.name.lower())
    elif alias == 'normalization':
        state_argument = state.with_name(unicodedata.normalize('NFD', state.name))
    else:
        # Darwin's Data firmlink is a real identity alias, not a followed symlink.
        credential = Path('/System/Volumes/Data') / str(credential).lstrip('/')
    assert not credential.is_relative_to(state_argument), 'must exercise text-relative bypass'
    assert _identity(state_argument) == _identity(state)
    assert _identity(credential.parent) == _identity(parent)
    mount = _apfs(state)
    driver = AgentDriver()
    (tmp_path / 'APFS-alias-before.json').write_text(json.dumps({'alias': alias, 'mount': mount,
        'state': str(state_argument), 'credential': str(credential), 'state_identity': _identity(state_argument),
        'credential_parent_identity': _identity(credential.parent), 'text_relative': False}, indent=2))
    with pytest.raises(ValueError, match='credential.*(outside|state|workspace)'):
        agent_type(credential, state_argument, driver=driver)
    assert not driver.requests and not (state / 'agent.sqlite3').exists()
    assert credential.exists() and credential.stat().st_uid == os.getuid()


@pytest.mark.parametrize('alias', ['case', 'normalization'])
def test_actual_apfs_external_credential_alias_stays_eligible_without_native(agent_type, tmp_path, alias):
    external = tmp_path / ('Créds' if alias == 'normalization' else 'CREDS')
    external.mkdir(mode=0o700)
    credential = external / 'node-auth.json'
    config = _credential(credential)
    spelling = external.with_name(unicodedata.normalize('NFD', external.name) if alias == 'normalization' else external.name.lower())
    assert _identity(spelling) == _identity(external)
    _apfs(tmp_path)
    state = tmp_path / 'state-external'
    driver = AgentDriver()
    agent = agent_type(spelling / credential.name, state, driver=driver)
    assert not driver.requests and agent.node_id == config['node_id']
    assert (state / 'agent.sqlite3').is_file() and credential.is_file()
    assert config['secret'].encode() not in retained_bytes(state)
