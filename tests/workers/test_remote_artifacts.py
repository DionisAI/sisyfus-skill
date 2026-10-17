"""Frozen N3 substrate contracts; retained local fixtures, NOT native/A7/A8.

The caller owns task/node identity, fixed roots, pinned manifests and lease/receipt
fences. These tests fix byte, complete-tree, exact-delta and materialization
expectations before implementation. No old fixture or test is changed.
"""
import copy
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from sisyfus.workers import remote_artifacts as module
from sisyfus.workers.node_claims import _entries, _paths


CLAIM = 'claim_' + 'a' * 32


def meta(path, data):
    return {'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}


def tree(contents):
    files = [meta(p, b) for p, b in sorted(contents.items())]
    dirs = set()
    for path in contents:
        parts = path.split('/')
        dirs.update('/'.join(parts[:i]) for i in range(1, len(parts)))
    nodes = [{'path': p, 'kind': 'directory'} for p in dirs]
    nodes.extend(item | {'kind': 'file'} for item in files)
    return {'schema': 1, 'files': files, 'tree': sorted(nodes, key=lambda n: n['path']), 'errors': [], 'complete': True}


def put(root, path, data):
    dest = root / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def codes(report):
    return {item['code'] for item in report['errors']}


@pytest.fixture
def prepared(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    put(source, 'src/main.py', b'old')
    put(source, 'keep.txt', b'keep')
    snapshot = tmp_path / 'snapshot'
    manifest = module.create_input_snapshot(source, snapshot, ['src/main.py', 'out/result.txt'])
    artifact_root = tmp_path / 'uploads'
    claim = artifact_root / CLAIM
    put(claim, 'src/main.py', b'new')
    put(claim, 'out/result.txt', b'result')
    uploads = [meta('src/main.py', b'new') | {'status': 'STORED'}, meta('out/result.txt', b'result') | {'status': 'STORED'}]
    final = tree({'src/main.py': b'new', 'keep.txt': b'keep', 'out/result.txt': b'result'})
    return source, snapshot, manifest, artifact_root, uploads, final, tmp_path / 'candidate-envelope'


def materialize(env, **changes):
    _, snapshot, manifest, artifacts, uploads, final, candidate = env
    args = {'snapshot': snapshot, 'input_manifest': manifest, 'tree_manifest': final, 'uploads': uploads,
            'deleted_paths': [], 'artifact_root': artifacts, 'claim_id': CLAIM, 'candidate_root': candidate}
    args.update(changes)
    return module.materialize_candidate(**args)


def test_public_contracts_documented_and_bounds_match_node_protocol():
    for name in ('full_tree_manifest', 'create_input_snapshot', 'exact_delta', 'materialize_candidate'):
        assert getattr(module, name).__doc__
    assert module.ArtifactError.__doc__
    assert (module.MAX_FILES, module.MAX_FILE_BYTES, module.MAX_TOTAL_BYTES) == (128, 8_000_000, 32_000_000)
    assert module.MAX_TREE_ENTRIES == 4096


def test_full_tree_regular_nested_files_has_fixed_metadata(tmp_path):
    put(tmp_path, 'src/a.txt', b'alpha')
    put(tmp_path, 'zero.txt', b'')
    assert module.full_tree_manifest(tmp_path) == tree({'src/a.txt': b'alpha', 'zero.txt': b''})


def test_full_tree_reports_every_hidden_control_symlink_fifo_without_reading_them(tmp_path, monkeypatch):
    put(tmp_path, 'good.txt', b'good')
    for name in ('.git/config', '.sisyfus/state', 'credentials.json', 'sub/auth.json'):
        put(tmp_path, name, b'synthetic private bytes')
    (tmp_path / 'empty').mkdir()
    (tmp_path / 'link').symlink_to(tmp_path / 'good.txt')
    (tmp_path / 'dir-link').symlink_to(tmp_path / 'sub', target_is_directory=True)
    os.mkfifo(tmp_path / 'pipe')
    opened = []
    original = os.open

    def no_private_leaf(path, flags, *args, **kwargs):
        if not flags & os.O_DIRECTORY:
            opened.append(str(path))
            assert str(path) not in {'config', 'state', 'credentials.json', 'auth.json', 'link', 'dir-link', 'pipe'}
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, 'open', no_private_leaf)
    report = module.full_tree_manifest(tmp_path)
    assert report['complete'] is True
    actual = {n['path']: n['kind'] for n in report['tree']}
    assert actual == {'.git': 'directory', '.git/config': 'file', '.sisyfus': 'directory', '.sisyfus/state': 'file',
                      'credentials.json': 'file', 'sub': 'directory', 'sub/auth.json': 'file',
                      'good.txt': 'file', 'empty': 'directory', 'link': 'symlink', 'dir-link': 'symlink', 'pipe': 'fifo'}
    diagnosed = {e['path'] for e in report['errors']}
    assert {'.git', '.git/config', '.sisyfus', '.sisyfus/state', 'credentials.json', 'sub/auth.json', 'link', 'dir-link', 'pipe'} <= diagnosed
    assert {'unsafe_path', 'symlink', 'non_regular'} <= codes(report)
    assert report['files'] == [meta('good.txt', b'good')]
    assert opened and 'synthetic private bytes' not in repr(report)


@pytest.mark.parametrize('kind', ['missing', 'file', 'symlink', 'ancestor_symlink'])
def test_full_tree_missing_or_non_directory_root_is_explicit(tmp_path, kind):
    root = tmp_path / 'target'
    if kind == 'file':
        root.write_bytes(b'not a directory')
    elif kind in {'symlink', 'ancestor_symlink'}:
        real = tmp_path / 'real'
        put(real, 'inside/value.txt', b'not followed')
        root.symlink_to(real, target_is_directory=True)
        if kind == 'ancestor_symlink':
            root = root / 'inside'
    report = module.full_tree_manifest(root)
    assert report['complete'] is False and report['files'] == [] and report['tree'] == []
    assert 'root' in codes(report)


def test_full_tree_hardlinks_are_not_transferable_regular_files(tmp_path):
    put(tmp_path, 'a.txt', b'linked')
    os.link(tmp_path / 'a.txt', tmp_path / 'b.txt')
    report = module.full_tree_manifest(tmp_path)
    assert 'hardlink' in codes(report) and report['files'] == []
    assert {n['path'] for n in report['tree']} == {'a.txt', 'b.txt'}


@pytest.mark.parametrize('bound,expected', [('count', 'file_count'), ('single', 'file_size'), ('total', 'total_size')])
def test_full_tree_limits_are_diagnostics_not_silent_omissions(tmp_path, bound, expected):
    if bound == 'count':
        for i in range(129):
            put(tmp_path, f'f{i:03}.txt', b'')
    else:
        sizes = [8_000_001] if bound == 'single' else [6_500_000] * 5
        for i, size in enumerate(sizes):
            with (tmp_path / f'f{i}.bin').open('xb') as stream:
                stream.truncate(size)
    report = module.full_tree_manifest(tmp_path)
    assert expected in codes(report) and report['complete'] is True
    assert len(report['files']) <= 128
    assert sum(f['size'] for f in report['files']) <= 32_000_000
    assert len(report['tree']) == (129 if bound == 'count' else 1 if bound == 'single' else 5)


def test_full_tree_entry_bound_explicitly_marks_enumeration_incomplete(tmp_path):
    for i in range(4097):
        (tmp_path / f'd{i:04}').mkdir()
    report = module.full_tree_manifest(tmp_path)
    assert len(report['tree']) <= 4096 and report['complete'] is False
    assert 'tree_limit' in codes(report)


def test_snapshot_freezes_bytes_exclusively_and_preserves_input_originals(tmp_path):
    source = tmp_path / 'source'
    put(source, 'src/a.py', b'original')
    snapshot = tmp_path / 'snapshot'
    result = module.create_input_snapshot(source, snapshot, ['out.txt', 'src/a.py'])
    assert result == {'files': [meta('src/a.py', b'original')], 'output_paths': ['out.txt', 'src/a.py']}
    assert _entries(result['files']) == result['files']
    _paths([f['path'] for f in result['files']] + result['output_paths'])
    put(source, 'src/a.py', b'later source version')
    assert (snapshot / 'src/a.py').read_bytes() == b'original'
    with pytest.raises(module.ArtifactError):
        module.create_input_snapshot(source, snapshot, result['output_paths'])
    assert (snapshot / 'src/a.py').read_bytes() == b'original'
    assert (source / 'src/a.py').read_bytes() == b'later source version'


@pytest.mark.parametrize('bad', ['/absolute', '../parent', 'a//b', 'a/./b', 'a/.hidden', r'a\b', 'a:b', 'a/credentials.json',
                                  'autonomy.sqlite3', 'config.toml', 'id_ed25519', 'bad\x00name', 'bad\nname', 'x' * 256])
def test_snapshot_rejects_unsafe_output_paths_before_creation(tmp_path, bad):
    source = tmp_path / 'source'
    put(source, 'good.txt', b'good')
    with pytest.raises(module.ArtifactError):
        module.create_input_snapshot(source, tmp_path / 'snapshot', [bad])
    assert not (tmp_path / 'snapshot').exists()
    assert (source / 'good.txt').read_bytes() == b'good'


@pytest.mark.parametrize('outputs', [['A/x', 'a/y'], ['one', 'one/two'], ['x', 'x'], ['good.txt/child']])
def test_snapshot_rejects_casefold_duplicates_and_parent_collisions(tmp_path, outputs):
    source = tmp_path / 'source'
    put(source, 'good.txt', b'good')
    with pytest.raises(module.ArtifactError):
        module.create_input_snapshot(source, tmp_path / 'snapshot', outputs)
    assert not (tmp_path / 'snapshot').exists()


def test_snapshot_rejects_hidden_and_unrepresentable_empty_directory(tmp_path):
    source = tmp_path / 'source'
    put(source, '.hidden', b'private')
    (source / 'empty').mkdir()
    with pytest.raises(module.ArtifactError) as caught:
        module.create_input_snapshot(source, tmp_path / 'snapshot', [])
    assert {'unsafe_path', 'empty_directory'} <= codes(caught.value.report)
    assert not (tmp_path / 'snapshot').exists()


def test_snapshot_source_change_during_write_fails_and_retains_fixed_bytes(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    put(source, 'a.txt', b'before')
    write = module._write_file

    def change_source(*args, **kwargs):
        write(*args, **kwargs)
        put(source, 'a.txt', b'concurrent change')

    monkeypatch.setattr(module, '_write_file', change_source)
    with pytest.raises(module.ArtifactError) as caught:
        module.create_input_snapshot(source, tmp_path / 'snapshot', ['a.txt'])
    assert 'input_changed' in codes(caught.value.report)
    assert (tmp_path / 'snapshot/a.txt').read_bytes() == b'before'
    assert (source / 'a.txt').read_bytes() == b'concurrent change'


def test_snapshot_write_failure_retains_partial_snapshot_and_original(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    put(source, 'a.txt', b'before')
    write = module._write_file

    def interrupted(*args, **kwargs):
        write(*args, **kwargs)
        raise OSError('synthetic interrupted snapshot')

    monkeypatch.setattr(module, '_write_file', interrupted)
    with pytest.raises(module.ArtifactError) as caught:
        module.create_input_snapshot(source, tmp_path / 'snapshot', ['a.txt'])
    assert 'io_error' in codes(caught.value.report)
    assert (tmp_path / 'snapshot/a.txt').read_bytes() == b'before'
    assert (source / 'a.txt').read_bytes() == b'before'


def test_exact_delta_accounts_for_add_modify_delete_and_stored_bytes():
    before = {'files': [meta('a.txt', b'old'), meta('gone.txt', b'gone'), meta('keep.txt', b'keep')],
              'output_paths': ['a.txt', 'gone.txt', 'new/out.txt']}
    final = tree({'a.txt': b'new', 'keep.txt': b'keep', 'new/out.txt': b'created'})
    uploads = [meta('a.txt', b'new') | {'status': 'STORED'}, meta('new/out.txt', b'created') | {'status': 'STORED'}]
    result = module.exact_delta(before, final, uploads, ['gone.txt'])
    assert result == {'added': ['new/out.txt'], 'modified': ['a.txt'], 'deleted': ['gone.txt'],
                      'added_directories': ['new'], 'deleted_directories': [], 'errors': [], 'valid': True}
    assert before['files'][0] == meta('a.txt', b'old') and final == tree({'a.txt': b'new', 'keep.txt': b'keep', 'new/out.txt': b'created'})


@pytest.mark.parametrize('bad,expected', [('missing_upload', 'missing_upload'), ('wrong_hash', 'upload_mismatch'),
                                         ('wrong_size', 'upload_mismatch'), ('preparing', 'upload_manifest'),
                                         ('absolute_upload', 'upload_manifest'), ('extra_field', 'upload_manifest'),
                                         ('duplicate_upload', 'upload_manifest'), ('missing_deletion', 'deletion_mismatch'),
                                         ('false_deletion', 'deletion_mismatch'), ('incomplete', 'tree_incomplete'),
                                         ('omitted_file_table', 'tree_files_mismatch')])
def test_exact_delta_rejects_hash_size_missing_omitted_or_unstored_claims(bad, expected):
    before = {'files': [meta('a.txt', b'old'), meta('gone.txt', b'gone')], 'output_paths': ['a.txt', 'gone.txt']}
    final = tree({'a.txt': b'new'})
    uploads = [meta('a.txt', b'new') | {'status': 'STORED'}]
    deleted = ['gone.txt']
    if bad == 'missing_upload': uploads = []
    if bad == 'wrong_hash': uploads[0]['sha256'] = '0' * 64
    if bad == 'wrong_size': uploads[0]['size'] = 2
    if bad == 'preparing': uploads[0]['status'] = 'PREPARING'
    if bad == 'absolute_upload': uploads[0]['path'] = '/a.txt'
    if bad == 'extra_field': uploads[0]['source_path'] = '/other-claim/a.txt'
    if bad == 'duplicate_upload': uploads.append(dict(uploads[0]))
    if bad == 'missing_deletion': deleted = []
    if bad == 'false_deletion': deleted.append('other.txt')
    if bad == 'incomplete': final['complete'] = False
    if bad == 'omitted_file_table': final['files'] = []
    result = module.exact_delta(before, final, uploads, deleted)
    assert result['valid'] is False and expected in codes(result)
    assert result['modified'] == ['a.txt'] and result['deleted'] == ['gone.txt']


@pytest.mark.parametrize('kind', ['new', 'modified', 'deleted', 'empty_directory'])
def test_full_tree_scope_catches_changes_hidden_by_allowlisted_uploads(kind):
    before = {'files': [meta('keep.txt', b'keep')], 'output_paths': ['allowed.txt']}
    contents = {'keep.txt': b'keep', 'allowed.txt': b'allowed'}
    if kind == 'new': contents['rogue.txt'] = b'out of scope'
    if kind == 'modified': contents['keep.txt'] = b'out of scope'
    if kind == 'deleted': contents.pop('keep.txt')
    final = tree(contents)
    if kind == 'empty_directory': final['tree'].append({'path': 'rogue', 'kind': 'directory'})
    result = module.exact_delta(before, final, [meta('allowed.txt', b'allowed') | {'status': 'STORED'}], ['keep.txt'] if kind == 'deleted' else [])
    assert result['valid'] is False and 'scope' in codes(result)
    if kind == 'new': assert 'rogue.txt' in result['added']
    if kind == 'modified': assert 'keep.txt' in result['modified']
    if kind == 'deleted': assert result['deleted'] == ['keep.txt']
    if kind == 'empty_directory': assert 'rogue' in result['added_directories']


@pytest.mark.parametrize('bad', ['hidden', 'control', 'symlink', 'fifo', 'casefold', 'parentcollision'])
def test_untrusted_full_tree_is_revalidated_for_unsupported_paths_and_types(bad):
    final = tree({'good.txt': b'good'})
    if bad in {'hidden', 'control', 'casefold', 'parentcollision'}:
        path = {'hidden': '.git/state', 'control': 'autonomy.sqlite3', 'casefold': 'GOOD.txt', 'parentcollision': 'good.txt/child'}[bad]
        item = meta(path, b'bad')
        final['tree'].append(item | {'kind': 'file'}); final['files'].append(item)
    else:
        final['tree'].append({'path': 'bad', 'kind': bad})
    result = module.exact_delta({'files': [], 'output_paths': ['good.txt']}, final,
                                [meta('good.txt', b'good') | {'status': 'STORED'}], [])
    assert result['valid'] is False and result['errors']
    assert 'scope' in codes(result)


def test_legal_materialization_uses_verified_uploads_and_independent_before_snapshot(prepared):
    source, snapshot, manifest, artifacts, uploads, final, candidate = prepared
    original = module.full_tree_manifest(source)
    result = materialize(prepared)
    assert result['candidate'] == str(candidate / 'candidate') and result['before'] == str(candidate / 'before')
    assert result['delta']['added'] == ['out/result.txt'] and result['delta']['modified'] == ['src/main.py']
    assert result['delta']['valid'] is True
    assert module.full_tree_manifest(candidate / 'candidate') == final
    assert module.full_tree_manifest(candidate / 'before') == original
    assert module.full_tree_manifest(source) == original and module.full_tree_manifest(snapshot) == original
    assert (artifacts / CLAIM / 'src/main.py').read_bytes() == b'new'
    with pytest.raises(module.ArtifactError):
        materialize(prepared)
    assert (candidate / 'candidate/src/main.py').read_bytes() == b'new'


@pytest.mark.parametrize('bad', ['snapshot_hash', 'snapshot_hidden', 'upload_hash', 'upload_size', 'missing_upload', 'claim_symlink', 'upload_symlink'])
def test_materialization_validation_precedes_any_candidate_mutation(prepared, bad, tmp_path):
    source, snapshot, manifest, artifacts, uploads, final, candidate = prepared
    changes = {}
    if bad == 'snapshot_hash': put(snapshot, 'src/main.py', b'changed snapshot')
    if bad == 'snapshot_hidden': put(snapshot, '.hidden', b'hidden')
    if bad == 'upload_hash': put(artifacts / CLAIM, 'src/main.py', b'bad')
    if bad == 'upload_size': put(artifacts / CLAIM, 'src/main.py', b'new-extra')
    if bad == 'missing_upload': changes['uploads'] = uploads[:1]
    if bad == 'claim_symlink':
        other = tmp_path / 'other-artifacts'
        other.mkdir(); (other / CLAIM).symlink_to(artifacts / CLAIM, target_is_directory=True)
        changes['artifact_root'] = other
    if bad == 'upload_symlink':
        other = tmp_path / 'other-artifacts'
        put(other / CLAIM, 'out/result.txt', b'result')
        (other / CLAIM / 'src').mkdir(); (other / CLAIM / 'src/main.py').symlink_to(artifacts / CLAIM / 'src/main.py')
        changes['artifact_root'] = other
    with pytest.raises(module.ArtifactError) as caught:
        materialize(prepared, **changes)
    assert caught.value.report['errors'] and not candidate.exists()
    assert (source / 'src/main.py').read_bytes() == b'old'
    assert (artifacts / CLAIM / 'out/result.txt').read_bytes() == b'result'


@pytest.mark.parametrize('claim', ['../other', '/absolute', 'claim_bad/child', '', 'claim_' + 'a' * 31, 'claim_' + 'A' * 32])
def test_materialization_claim_namespace_is_fixed_not_an_arbitrary_path(prepared, claim):
    with pytest.raises(module.ArtifactError) as caught:
        materialize(prepared, claim_id=claim)
    assert 'namespace' in codes(caught.value.report) and not prepared[-1].exists()


@pytest.mark.parametrize('target', ['snapshot', 'snapshot_child', 'uploads', 'claim', 'relative'])
def test_materialization_rejects_original_or_upload_root_overlap(prepared, target):
    _, snapshot, _, artifacts, _, _, _ = prepared
    candidate = {'snapshot': snapshot, 'snapshot_child': snapshot / 'new', 'uploads': artifacts,
                 'claim': artifacts / CLAIM, 'relative': Path('relative-candidate')}[target]
    with pytest.raises(module.ArtifactError):
        materialize(prepared, candidate_root=candidate)
    assert (snapshot / 'src/main.py').read_bytes() == b'old'
    assert (artifacts / CLAIM / 'src/main.py').read_bytes() == b'new'


def test_materialization_retains_partial_failure_before_originals_and_uploads(prepared, monkeypatch):
    write = module._write_file
    count = 0

    def interrupted(*args, **kwargs):
        nonlocal count
        write(*args, **kwargs); count += 1
        if count == 3:
            raise OSError('synthetic candidate interruption')

    monkeypatch.setattr(module, '_write_file', interrupted)
    with pytest.raises(module.ArtifactError) as caught:
        materialize(prepared)
    assert 'io_error' in codes(caught.value.report) and prepared[-1].is_dir()
    assert (prepared[-1] / 'before/src/main.py').read_bytes() == b'old'
    assert (prepared[0] / 'src/main.py').read_bytes() == b'old'
    assert (prepared[1] / 'src/main.py').read_bytes() == b'old'
    assert (prepared[3] / CLAIM / 'src/main.py').read_bytes() == b'new'


def deletion_env(tmp_path):
    source = tmp_path / 'source'
    path = 'deleted-' + tmp_path.name + '.txt'
    put(source, path, b'recoverable original')
    snapshot = tmp_path / 'snapshot'
    manifest = module.create_input_snapshot(source, snapshot, [path])
    artifacts = tmp_path / 'uploads'
    (artifacts / CLAIM).mkdir(parents=True)
    return (source, snapshot, manifest, artifacts, [], tree({}), tmp_path / 'candidate-envelope'), path


def test_real_deletion_uses_exact_trash_argv_and_is_recoverable(tmp_path, monkeypatch):
    env, path = deletion_env(tmp_path)
    calls = []
    run = subprocess.run

    def observe(argv, **kwargs):
        assert argv == ['/usr/bin/trash', str(env[-1] / 'candidate' / path)]
        assert kwargs.get('check') is True
        calls.append(argv)
        return run(argv, **kwargs)

    monkeypatch.setattr(module.subprocess, 'run', observe)
    result = materialize(env, deleted_paths=[path])
    assert calls and result['delta']['deleted'] == [path]
    assert not (env[-1] / 'candidate' / path).exists()
    assert (env[-1] / 'before' / path).read_bytes() == b'recoverable original'
    assert (env[0] / path).read_bytes() == (env[1] / path).read_bytes() == b'recoverable original'
    assert (Path.home() / '.Trash' / path).read_bytes() == b'recoverable original'


def test_failed_trash_explicitly_retains_candidate_before_and_originals(tmp_path, monkeypatch):
    env, path = deletion_env(tmp_path)

    def fail(argv, **kwargs):
        assert argv == ['/usr/bin/trash', str(env[-1] / 'candidate' / path)]
        raise subprocess.CalledProcessError(1, argv, stderr='synthetic trash failure')

    monkeypatch.setattr(module.subprocess, 'run', fail)
    with pytest.raises(module.ArtifactError) as caught:
        materialize(env, deleted_paths=[path])
    assert 'trash_failed' in codes(caught.value.report)
    for root in (env[0], env[1], env[-1] / 'before', env[-1] / 'candidate'):
        assert (root / path).read_bytes() == b'recoverable original'


def test_unavailable_trash_fails_before_candidate_creation(tmp_path, monkeypatch):
    env, path = deletion_env(tmp_path)
    access = os.access
    monkeypatch.setattr(module.os, 'access', lambda p, mode, **kw: False if str(p) == '/usr/bin/trash' else access(p, mode, **kw))
    with pytest.raises(module.ArtifactError) as caught:
        materialize(env, deleted_paths=[path])
    assert 'trash_unavailable' in codes(caught.value.report) and not env[-1].exists()
    assert (env[1] / path).read_bytes() == b'recoverable original'


def test_materialization_never_treats_declared_metadata_as_verified_bytes(prepared, monkeypatch):
    write = module._write_file

    def corrupt_final(root, path, data, **kwargs):
        write(root, path, data, **kwargs)
        if root.name == 'candidate' and path == 'out/result.txt':
            put(root, path, b'changed after write')

    monkeypatch.setattr(module, '_write_file', corrupt_final)
    with pytest.raises(module.ArtifactError) as caught:
        materialize(prepared)
    assert 'materialized_mismatch' in codes(caught.value.report)
    assert (prepared[-1] / 'candidate/out/result.txt').read_bytes() == b'changed after write'
    assert (prepared[-1] / 'before/src/main.py').read_bytes() == b'old'
    assert (prepared[3] / CLAIM / 'out/result.txt').read_bytes() == b'result'
