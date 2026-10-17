"""Frozen N3 v2 IO goals: real retained directory races, never native execution.

Faults rename fixture directories or move them out of their namespace; nothing
is permanently removed. Error assertions are paired with real full-tree/byte
readbacks, zero mutation after broken write bindings, and descriptor closure.
Trash races use a recoverable rename-backed fixture; one case uses real Trash.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from sisyfus.workers import remote_artifacts as module


CLAIM = 'claim_' + 'c' * 32


def meta(path, data):
    return {'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def tree(contents):
    files = [meta(p, b) for p, b in sorted(contents.items())]
    dirs = {str(parent) for p in contents for parent in Path(p).parents if str(parent) != '.'}
    nodes = [dict(f, kind='file') for f in files] + [{'path': p, 'kind': 'directory'} for p in dirs]
    return {'schema': 1, 'files': files, 'tree': sorted(nodes, key=lambda n: n['path']), 'errors': [], 'complete': True}


def put(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def prepared(tmp_path, deletion=False):
    source, snapshot, artifacts = (tmp_path / name for name in ('source', 'snapshot', 'uploads'))
    gone_dir = 'gone-dir-' + tmp_path.name
    inner = 'inner-' + tmp_path.name
    gone_file = 'gone-file-' + tmp_path.name + '.txt'
    removed = f'{gone_dir}/{inner}/{gone_file}'
    contents = {'keep.txt': b'unchanged original', removed: b'recoverable deletion'} if deletion else {
        'keep.txt': b'unchanged original', 'src/change.txt': b'original input'}
    for name, data in contents.items():
        put(source, name, data)
    outputs = [removed] if deletion else ['src/change.txt', 'out/result.txt']
    manifest = module.create_input_snapshot(source, snapshot, outputs)
    (artifacts / CLAIM).mkdir(parents=True)
    uploads = []
    final = {'keep.txt': contents['keep.txt']} if deletion else {
        'keep.txt': contents['keep.txt'], 'src/change.txt': b'accepted upload', 'out/result.txt': b'result upload'}
    if not deletion:
        for name in outputs:
            put(artifacts / CLAIM, name, final[name])
            uploads.append(meta(name, final[name]) | {'status': 'STORED'})
    parent = tmp_path / 'checked-parent'
    parent.mkdir()
    return {'source': source, 'snapshot': snapshot, 'artifact_root': artifacts, 'claim': artifacts / CLAIM,
            'input_manifest': manifest, 'tree_manifest': tree(final), 'uploads': uploads,
            'deleted_paths': [removed] if deletion else [], 'candidate_root': parent / 'envelope',
            'removed': removed, 'gone_dir': gone_dir, 'inner': inner, 'gone_file': gone_file}


def materialize(env):
    return module.materialize_candidate(**{k: env[k] for k in (
        'snapshot', 'input_manifest', 'tree_manifest', 'uploads', 'deleted_paths', 'artifact_root', 'candidate_root')},
        claim_id=CLAIM)


def readbacks(paths):
    return {str(p): module.full_tree_manifest(p) for p in paths}


class Trace:
    """Observe actual syscalls; fixture fault injection is explicitly separate."""
    def __init__(self):
        self.attacked = False
        self.injecting = False
        self.mutations = []
        self.live_fds = set()
        self.renames = []

    @contextmanager
    def fixture_fault(self):
        self.injecting = True
        try:
            yield
        finally:
            self.injecting = False
            self.attacked = True

    @contextmanager
    def observe(self, monkeypatch):
        opened, dup, close = os.open, os.dup, os.close
        mkdir, write, truncate, rename = os.mkdir, os.write, os.ftruncate, os.rename

        def mutation(kind, args):
            if self.attacked and not self.injecting:
                self.mutations.append({'kind': kind, 'args': [str(a) for a in args]})

        def open_fd(path, flags, *args, **kwargs):
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                mutation('open_write', (path,))
            fd = opened(path, flags, *args, **kwargs)
            self.live_fds.add(fd)
            return fd

        def dup_fd(fd):
            result = dup(fd)
            self.live_fds.add(result)
            return result

        def close_fd(fd):
            close(fd)
            self.live_fds.discard(fd)

        def make(*args, **kwargs):
            mutation('mkdir', args)
            return mkdir(*args, **kwargs)

        def write_fd(*args, **kwargs):
            mutation('write', args[:1])
            return write(*args, **kwargs)

        def truncate_fd(*args, **kwargs):
            mutation('truncate', args)
            return truncate(*args, **kwargs)

        def move(*args, **kwargs):
            mutation('rename', args)
            if not self.injecting:
                self.renames.append({'src': str(args[0]), 'dst': str(args[1]),
                                     'src_dir_fd': kwargs.get('src_dir_fd'), 'dst_dir_fd': kwargs.get('dst_dir_fd')})
            return rename(*args, **kwargs)

        with monkeypatch.context() as patch:
            for name, fn in (('open', open_fd), ('dup', dup_fd), ('close', close_fd), ('mkdir', make),
                             ('write', write_fd), ('ftruncate', truncate_fd), ('rename', move)):
                patch.setattr(module.os, name, fn)
            yield


def retained_attempt(tmp_path, trace, action, expected):
    """Always retain proof, including changed originals and still-live red fds."""
    errors, result = None, None
    try:
        result = action()
    except module.ArtifactError as caught:
        errors = sorted({e['code'] for e in caught.report['errors']})
    finally:
        after = {root: module.full_tree_manifest(root) for root in expected}
        receipt = {'expected': dict(expected), 'after': after, 'originals_unchanged': after == expected,
                   'errors': errors, 'returned_success': result is not None, 'post_fault_mutations': trace.mutations,
                   'live_fds': sorted(trace.live_fds), 'renames': trace.renames}
        with (tmp_path / 'pinned-io-readback.json').open('x') as stream:
            json.dump(receipt, stream, indent=2)
    assert errors and {'io_error', 'trash_failed'} & set(errors), receipt
    assert after == expected, 'fixture fault must never become original-byte or tree mutation'
    assert trace.live_fds == set(), 'all opened/duplicated descriptors must close even on failure'
    return receipt


@pytest.mark.parametrize('operation', ['snapshot', 'materialize'])
@pytest.mark.parametrize('fault', ['root_moved', 'parent_moved', 'root_replaced', 'parent_replaced'])
def test_first_write_rejects_moved_missing_or_replaced_binding_without_rebuilding(tmp_path, monkeypatch, operation, fault):
    env = prepared(tmp_path)
    target = env['candidate_root'] if operation == 'materialize' else env['candidate_root'].parent / 'another-snapshot'
    originals = [env[k] for k in ('source', 'snapshot', 'artifact_root', 'claim')]
    expected = readbacks(originals)
    trace, write = Trace(), module._write_file
    retained = tmp_path / 'retained-moved-directory'
    triggered = False

    def fault_before_first_write(*args, **kwargs):
        nonlocal triggered
        if not triggered:
            triggered = True
            moved = target.parent if fault.startswith('parent') else target
            with trace.fixture_fault():
                os.rename(moved, retained)
                if fault.endswith('replaced'):
                    moved.mkdir()
                expected.update(readbacks([retained, moved]))
        return write(*args, **kwargs)

    with trace.observe(monkeypatch):
        monkeypatch.setattr(module, '_write_file', fault_before_first_write)
        action = lambda: materialize(env) if operation == 'materialize' else module.create_input_snapshot(env['source'], target, ['keep.txt'])
        retained_attempt(tmp_path, trace, action, expected)
    assert triggered and trace.mutations == [], 'a broken binding must fail before even attempting mkdir/open-for-write'


@pytest.mark.parametrize('protected', ['source', 'snapshot', 'claim'])
@pytest.mark.parametrize('component', ['candidate_root', 'candidate_child'])
def test_ordinary_protected_directory_swap_precedes_first_replacement_write(tmp_path, monkeypatch, protected, component):
    env = prepared(tmp_path)
    original = env[protected] if component == 'candidate_root' else env[protected] / 'src'
    pristine = module.full_tree_manifest(original)
    expected = readbacks([env[k] for k in ('source', 'snapshot', 'artifact_root', 'claim')])
    trace, write = Trace(), module._write_file
    triggered = False
    replacement = env['candidate_root'] / 'candidate'
    if component == 'candidate_child':
        replacement /= 'src'

    def swap_before_replacement(root, path, data, **kwargs):
        nonlocal triggered
        if not triggered and root.name == 'candidate' and kwargs.get('replace'):
            triggered = True
            with trace.fixture_fault():
                os.rename(replacement, env['candidate_root'] / 'retained-original-candidate')
                os.rename(original, replacement)
                expected.clear()
                expected.update(readbacks([env[k] for k in ('source', 'snapshot', 'artifact_root', 'claim')]))
                expected[str(replacement)] = pristine
        return write(root, path, data, **kwargs)

    with trace.observe(monkeypatch):
        monkeypatch.setattr(module, '_write_file', swap_before_replacement)
        retained_attempt(tmp_path, trace, lambda: materialize(env), expected)
    assert triggered and trace.mutations == [], 'NOFOLLOW alone does not protect against ordinary-directory replacement'
    assert module.full_tree_manifest(replacement) == pristine


def mock_trash(tmp_path, trace, calls):
    retained = tmp_path / 'recoverable-fixture-trash'
    retained.mkdir()

    def run(argv, **kwargs):
        assert len(argv) == 2 and argv[0] == '/usr/bin/trash' and Path(argv[1]).is_absolute()
        assert kwargs.get('check') is True
        calls.append(argv)
        with trace.fixture_fault():
            os.rename(argv[1], retained / (str(len(calls)) + '-' + Path(argv[1]).name))
        return subprocess.CompletedProcess(argv, 0)
    return run


@pytest.mark.parametrize('when', ['file', 'empty_directory'])
@pytest.mark.parametrize('protected', ['source', 'snapshot', 'claim'])
@pytest.mark.parametrize('component', ['candidate_root', 'intermediate'])
def test_subprocess_interposition_symlink_never_trashes_original_file_or_directory(tmp_path, monkeypatch, when, protected, component):
    env = prepared(tmp_path, deletion=True)
    # The upload namespace contains an independent same-shaped retained tree.
    put(env['claim'], env['removed'], b'upload namespace original')
    expected = readbacks([env[k] for k in ('source', 'snapshot', 'artifact_root', 'claim')])
    trace, calls = Trace(), []
    run = mock_trash(tmp_path, trace, calls)
    triggered = False
    candidate = env['candidate_root'] / 'candidate'

    def interpose(argv, **kwargs):
        nonlocal triggered
        is_directory = Path(argv[1]).is_dir()
        if not triggered and is_directory == (when == 'empty_directory'):
            triggered = True
            attacked = candidate if component == 'candidate_root' else candidate / env['gone_dir']
            original = env[protected] if component == 'candidate_root' else env[protected] / env['gone_dir']
            with trace.fixture_fault():
                os.rename(attacked, env['candidate_root'] / 'retained-candidate-component')
                attacked.symlink_to(original, target_is_directory=True)
        return run(argv, **kwargs)

    with trace.observe(monkeypatch):
        monkeypatch.setattr(module.subprocess, 'run', interpose)
        retained_attempt(tmp_path, trace, lambda: materialize(env), expected)
    assert triggered and calls
    assert all(not Path(argv[1]).is_relative_to(candidate) for argv in calls), 'Trash must receive private staging objects, never candidate paths'
    assert trace.renames and all(r['src_dir_fd'] is not None and r['dst_dir_fd'] is not None for r in trace.renames)


def test_failed_trash_retains_staged_copy_before_and_all_originals(tmp_path, monkeypatch):
    env = prepared(tmp_path, deletion=True)
    expected = readbacks([env[k] for k in ('source', 'snapshot', 'artifact_root', 'claim')])
    trace, calls = Trace(), []

    def fail(argv, **kwargs):
        calls.append(argv)
        raise subprocess.CalledProcessError(9, argv, stderr='synthetic retained Trash failure')

    with trace.observe(monkeypatch):
        monkeypatch.setattr(module.subprocess, 'run', fail)
        retained_attempt(tmp_path, trace, lambda: materialize(env), expected)
    assert len(calls) == 1 and calls[0][0] == '/usr/bin/trash'
    staged = Path(calls[0][1])
    assert staged.is_relative_to(env['candidate_root']) and not staged.is_relative_to(env['candidate_root'] / 'candidate')
    assert staged.read_bytes() == b'recoverable deletion'
    assert (env['candidate_root'] / 'before' / env['removed']).read_bytes() == b'recoverable deletion'
    assert all(r['src_dir_fd'] is not None and r['dst_dir_fd'] is not None for r in trace.renames)


def test_nonempty_new_staging_is_rejected_without_overwriting_retained_data(tmp_path, monkeypatch):
    env = prepared(tmp_path, deletion=True)
    expected = readbacks([env[k] for k in ('source', 'snapshot', 'artifact_root', 'claim')])
    trace, calls = Trace(), []
    mkdir = os.mkdir
    injected = []
    run = mock_trash(tmp_path, trace, calls)

    def collide(name, *args, **kwargs):
        result = mkdir(name, *args, **kwargs)
        parent = kwargs.get('dir_fd')
        if parent is not None and env['candidate_root'].exists() and str(name) not in {'before', 'candidate'}:
            pin, actual = os.fstat(parent), os.stat(env['candidate_root'])
            if (pin.st_dev, pin.st_ino) == (actual.st_dev, actual.st_ino):
                with trace.fixture_fault():
                    path = env['candidate_root'] / str(name) / 'retained-existing.txt'
                    path.write_bytes(b'never overwrite existing staged data')
                    injected.append(path)
                    expected[str(path.parent)] = module.full_tree_manifest(path.parent)
        return result

    with trace.observe(monkeypatch):
        monkeypatch.setattr(module.os, 'mkdir', collide)
        monkeypatch.setattr(module.subprocess, 'run', run)
        retained_attempt(tmp_path, trace, lambda: materialize(env), expected)
    assert len(injected) == 1 and injected[0].read_bytes() == b'never overwrite existing staged data'
    assert calls == [] and trace.renames == []


def test_real_trash_staging_file_and_empty_directories_remain_recoverable(tmp_path, monkeypatch):
    env = prepared(tmp_path, deletion=True)
    expected = readbacks([env[k] for k in ('source', 'snapshot', 'artifact_root', 'claim')])
    run, calls, trace = subprocess.run, [], Trace()

    def observe(argv, **kwargs):
        assert len(argv) == 2 and argv[0] == '/usr/bin/trash' and Path(argv[1]).is_absolute()
        assert kwargs.get('check') is True and '--' not in argv
        target = Path(argv[1])
        assert target.is_relative_to(env['candidate_root']) and not target.is_relative_to(env['candidate_root'] / 'candidate')
        calls.append((argv, module.full_tree_manifest(target) if target.is_dir() else target.read_bytes()))
        return run(argv, **kwargs)

    with trace.observe(monkeypatch):
        monkeypatch.setattr(module.subprocess, 'run', observe)
        result = materialize(env)
    assert result['delta']['deleted'] == [env['removed']] and len(calls) == 3
    assert readbacks([Path(root) for root in expected]) == expected
    assert module.full_tree_manifest(env['candidate_root'] / 'candidate') == env['tree_manifest']
    assert module.full_tree_manifest(env['candidate_root'] / 'before') == tree({
        'keep.txt': b'unchanged original', env['removed']: b'recoverable deletion'})
    assert (Path.home() / '.Trash' / env['gone_file']).read_bytes() == b'recoverable deletion'
    for dirname in (env['inner'], env['gone_dir']):
        assert list((Path.home() / '.Trash' / dirname).iterdir()) == []
    assert trace.live_fds == set()
    assert trace.renames and all(r['src_dir_fd'] is not None and r['dst_dir_fd'] is not None for r in trace.renames)
    with (tmp_path / 'real-trash-readback.json').open('x') as stream:
        json.dump({'originals_unchanged': True, 'calls': [argv for argv, _ in calls], 'renames': trace.renames,
                   'candidate': result, 'all_descriptors_closed': True}, stream, indent=2)
