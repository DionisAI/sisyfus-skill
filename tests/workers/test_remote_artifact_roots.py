"""Frozen N3 P2 real-root isolation goals, before the identity fix.

Portable alias simulation changes only descriptor lookup, not stat/fstat or
readback: returned descriptors are real fixture directories. Separate local
APFS case/firmlink cases assert actual same-inode aliases without mocks/skips.
Every red/green before/after readback and polluted red fixture is retained.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path

import pytest

from sisyfus.workers import remote_artifacts as module
from sisyfus.workers.node_claims import _directory


CLAIM = 'claim_' + 'b' * 32


def identity(path):
    fd = _directory(path)
    try:
        info = os.fstat(fd)
        return info.st_dev, info.st_ino
    finally:
        os.close(fd)


def meta(path, data):
    return {'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def tree(contents):
    files = [meta(p, b) for p, b in sorted(contents.items())]
    directories = {str(parent) for path in contents for parent in Path(path).parents if str(parent) != '.'}
    nodes = [dict(f, kind='file') for f in files] + [{'path': p, 'kind': 'directory'} for p in directories]
    return {'schema': 1, 'files': files, 'tree': sorted(nodes, key=lambda n: n['path']), 'errors': [], 'complete': True}


def put(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def source_fixture(tmp_path):
    source = tmp_path / 'source'
    put(source, 'main.txt', b'original task input')
    put(source, 'interior/value.txt', b'interior input')
    return source


def materialization_fixture(tmp_path):
    source = source_fixture(tmp_path)
    snapshot = tmp_path / 'snapshot'
    manifest = module.create_input_snapshot(source, snapshot, ['result.txt'])
    artifacts = tmp_path / 'uploads'
    put(artifacts / CLAIM, 'result.txt', b'stored result')
    final = tree({'main.txt': b'original task input', 'interior/value.txt': b'interior input', 'result.txt': b'stored result'})
    uploads = [meta('result.txt', b'stored result') | {'status': 'STORED'}]
    return {'source': source, 'snapshot': snapshot, 'input_manifest': manifest,
            'artifact_root': artifacts, 'claim': artifacts / CLAIM, 'uploads': uploads, 'tree_manifest': final}


def materialize(env, target, **changes):
    args = {k: env[k] for k in ('snapshot', 'input_manifest', 'artifact_root', 'uploads', 'tree_manifest')}
    args.update(claim_id=CLAIM, deleted_paths=[], candidate_root=target)
    args.update(changes)
    return module.materialize_candidate(**args)


@contextmanager
def descriptor_alias(monkeypatch, alias, actual):
    """Model a case/firmlink component using real fd identity and NOFOLLOW flags."""
    parent_id, target_id = identity(alias.parent), identity(actual)
    original_open = os.open
    with monkeypatch.context() as patch:
        def open_alias(path, flags, mode=0o777, *, dir_fd=None):
            if dir_fd is not None and str(path) == alias.name and flags & os.O_DIRECTORY:
                info = os.fstat(dir_fd)
                if (info.st_dev, info.st_ino) == parent_id:
                    assert flags & os.O_NOFOLLOW
                    return original_open(actual, flags, mode)
            return original_open(path, flags, mode, dir_fd=dir_fd)
        patch.setattr(module.os, 'open', open_alias)
        assert identity(alias) == target_id, 'alias is backed by a real directory descriptor'
        yield


def alias_path(tmp_path, actual, style):
    if style == 'case':
        return actual.parent / actual.name.upper()
    portal = tmp_path / 'portal'
    portal.mkdir(exist_ok=True)
    return portal / 'mounted-alias'


def assert_rejected_without_mutation(tmp_path, monkeypatch, action, originals, new_paths=(), code='root_overlap'):
    before = {str(p): module.full_tree_manifest(p) for p in originals}
    calls = []
    mkdir, write, run = os.mkdir, module._write_file, module.subprocess.run

    def observe_mkdir(*args, **kwargs):
        calls.append({'operation': 'mkdir', 'path': str(args[0])})
        return mkdir(*args, **kwargs)

    def observe_write(*args, **kwargs):
        calls.append({'operation': 'write', 'path': str(args[0] / args[1])})
        return write(*args, **kwargs)

    def observe_run(*args, **kwargs):
        calls.append({'operation': 'subprocess', 'argv': args[0]})
        return run(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(module.os, 'mkdir', observe_mkdir)
        patch.setattr(module, '_write_file', observe_write)
        patch.setattr(module.subprocess, 'run', observe_run)
        try:
            with pytest.raises(module.ArtifactError) as caught:
                action()
            assert code in {e['code'] for e in caught.value.report['errors']}
        finally:
            after = {str(p): module.full_tree_manifest(p) for p in originals}
            receipt = {'before': before, 'after': after, 'unchanged': before == after, 'mutation_calls': calls,
                       'new_paths': {str(p): p.exists() for p in new_paths}}
            with (tmp_path / 'root-isolation-readback.json').open('x') as stream:
                json.dump(receipt, stream, indent=2)
    assert after == before, 'original source/snapshot/uploads must remain byte-for-byte and tree-identical'
    assert calls == [], 'even attempted mkdir/write/trash is after the root boundary'
    assert all(not p.exists() for p in new_paths)


@pytest.mark.parametrize('style', ['case', 'firmlink'])
@pytest.mark.parametrize('relation', ['nested', 'equal', 'reverse', 'missing_chain'])
def test_snapshot_real_alias_overlap_is_rejected_before_any_creation(tmp_path, monkeypatch, style, relation):
    source = source_fixture(tmp_path)
    actual = source.parent if relation == 'reverse' else source / 'interior' if style == 'firmlink' and relation != 'equal' else source
    alias = alias_path(tmp_path, actual, style)
    suffix = 'new-snapshot' if relation == 'nested' else 'missing/deeper/new-snapshot' if relation == 'missing_chain' else ''
    target = alias / suffix if suffix else alias
    real_target = actual / suffix if suffix else actual

    def action():
        with descriptor_alias(monkeypatch, alias, actual):
            module.create_input_snapshot(source, target, ['main.txt'])

    assert_rejected_without_mutation(tmp_path, monkeypatch, action, [source], [real_target] if suffix else [])


@pytest.mark.parametrize('style', ['case', 'firmlink'])
@pytest.mark.parametrize('protected', ['snapshot', 'artifact_root', 'claim'])
@pytest.mark.parametrize('relation', ['nested', 'equal', 'reverse', 'missing_chain'])
def test_candidate_real_snapshot_artifact_and_claim_aliases_are_fenced(tmp_path, monkeypatch, style, protected, relation):
    env = materialization_fixture(tmp_path)
    root = env[protected]
    actual = root.parent if relation == 'reverse' else root
    # This firmlink's real parent is the protected root, not the lexical portal.
    if style == 'firmlink' and relation in {'nested', 'missing_chain'} and protected == 'artifact_root':
        actual = env['claim']
    if style == 'firmlink' and relation in {'nested', 'missing_chain'} and protected == 'snapshot':
        actual = root / 'interior'
    alias = alias_path(tmp_path, actual, style)
    suffix = 'new-envelope' if relation == 'nested' else 'missing/deeper/new-envelope' if relation == 'missing_chain' else ''
    target = alias / suffix if suffix else alias
    real_target = actual / suffix if suffix else actual

    def action():
        with descriptor_alias(monkeypatch, alias, actual):
            materialize(env, target)

    originals = [env[k] for k in ('source', 'snapshot', 'artifact_root', 'claim')]
    assert_rejected_without_mutation(tmp_path, monkeypatch, action, originals, [real_target] if suffix else [])


@pytest.mark.parametrize('style', ['case', 'firmlink'])
@pytest.mark.parametrize('relation', ['equal', 'nested', 'reverse'])
def test_input_and_artifact_root_physical_overlap_is_not_hidden_by_alias(tmp_path, monkeypatch, style, relation):
    env = materialization_fixture(tmp_path)
    actual = env['snapshot'] if relation == 'equal' else env['snapshot'] / 'interior' if relation == 'nested' else env['snapshot'].parent
    alias = alias_path(tmp_path, actual, style)

    def action():
        with descriptor_alias(monkeypatch, alias, actual):
            materialize(env, tmp_path / 'independent-envelope', artifact_root=alias)

    assert_rejected_without_mutation(tmp_path, monkeypatch, action,
                                    [env[k] for k in ('source', 'snapshot', 'artifact_root', 'claim')], [tmp_path / 'independent-envelope'])


def test_claim_firmlink_identity_cannot_overlap_input_even_with_disjoint_artifact_parent(tmp_path, monkeypatch):
    env = materialization_fixture(tmp_path)

    def action():
        with descriptor_alias(monkeypatch, env['claim'], env['snapshot']):
            materialize(env, tmp_path / 'independent-envelope')

    assert_rejected_without_mutation(tmp_path, monkeypatch, action,
                                    [env[k] for k in ('source', 'snapshot', 'artifact_root', 'claim')], [tmp_path / 'independent-envelope'])


@pytest.mark.parametrize('operation', ['snapshot', 'candidate'])
@pytest.mark.parametrize('style', ['case', 'firmlink'])
def test_disjoint_multi_missing_parent_chain_fails_explicitly_without_preparing_it(tmp_path, monkeypatch, operation, style):
    env = materialization_fixture(tmp_path)
    staging = tmp_path / 'staging'
    staging.mkdir()
    alias = alias_path(tmp_path, staging, style)
    target = alias / 'missing' / 'deeper' / 'target'

    def action():
        with descriptor_alias(monkeypatch, alias, staging):
            if operation == 'snapshot':
                module.create_input_snapshot(env['source'], target, ['main.txt'])
            else:
                materialize(env, target)

    originals = [env[k] for k in ('source', 'snapshot', 'artifact_root', 'claim')] + [staging]
    assert_rejected_without_mutation(tmp_path, monkeypatch, action, originals, [staging / 'missing'], 'missing_parent')


@pytest.mark.parametrize('operation', ['snapshot', 'candidate'])
def test_disjoint_alias_shared_ancestor_is_not_misclassified_as_overlap(tmp_path, monkeypatch, operation):
    env = materialization_fixture(tmp_path)
    alias = alias_path(tmp_path, tmp_path, 'firmlink')
    before = {k: module.full_tree_manifest(env[k]) for k in ('source', 'snapshot', 'artifact_root', 'claim')}
    with descriptor_alias(monkeypatch, alias, tmp_path):
        if operation == 'snapshot':
            result = module.create_input_snapshot(env['source'], alias / 'disjoint-snapshot', ['result.txt'])
            assert result == env['input_manifest']
        else:
            result = materialize(env, alias / 'disjoint-envelope')
            assert result['delta']['valid'] is True
    assert all(module.full_tree_manifest(env[k]) == v for k, v in before.items())
    if operation == 'snapshot':
        assert module.full_tree_manifest(tmp_path / 'disjoint-snapshot') == before['source']
    else:
        assert module.full_tree_manifest(tmp_path / 'disjoint-envelope/before') == before['snapshot']
        assert module.full_tree_manifest(tmp_path / 'disjoint-envelope/candidate') == env['tree_manifest']


@pytest.mark.parametrize('alias_kind', ['case', 'data_firmlink'])
@pytest.mark.parametrize('protected', ['source', 'snapshot', 'artifact_root', 'claim'])
def test_actual_local_apfs_case_and_data_firmlink_do_not_pollute_retained_roots(tmp_path, monkeypatch, alias_kind, protected):
    env = materialization_fixture(tmp_path)
    actual = env[protected]
    alias = actual.parent / actual.name.upper() if alias_kind == 'case' else Path('/System/Volumes/Data') / actual.relative_to('/')
    assert alias != actual and identity(alias) == identity(actual), 'actual local volume aliases, not a fixture substitution'
    target = alias / 'new-root'
    real_target = actual / 'new-root'

    def action():
        if protected == 'source':
            module.create_input_snapshot(actual, target, ['main.txt'])
        else:
            materialize(env, target)

    assert_rejected_without_mutation(tmp_path, monkeypatch, action,
                                    [env[k] for k in ('source', 'snapshot', 'artifact_root', 'claim')], [real_target])
