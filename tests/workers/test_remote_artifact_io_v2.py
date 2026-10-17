"""User-confirmed artifact IO v2. The two legacy tests stay byte-identical.

Frozen before the new v2 deterministic/native source gate. Only the Trash
target changes to a descriptor-relative private staging copy; original trees,
failure retention, exact Trash argv and actual recoverability remain required.
"""
import os
from pathlib import Path
import stat
import subprocess

import pytest

from sisyfus.workers import remote_artifacts as module
from test_remote_artifacts import codes, deletion_env, materialize


def originals(env):
    return {str(root): module.full_tree_manifest(root) for root in env[:2]}


def test_v2_real_deletion_uses_exact_staging_trash_argv_and_is_recoverable(tmp_path, monkeypatch):
    env, path = deletion_env(tmp_path)
    baseline = originals(env)
    calls, renames = [], []
    run, rename = subprocess.run, os.rename

    def move(src, dst, **kwargs):
        assert kwargs.get('src_dir_fd') is not None and kwargs.get('dst_dir_fd') is not None
        renames.append((src, dst, kwargs))
        return rename(src, dst, **kwargs)

    def observe(argv, **kwargs):
        assert len(argv) == 2 and argv[0] == '/usr/bin/trash' and '--' not in argv
        target = Path(argv[1])
        assert target.is_absolute() and target.name == path
        assert target.is_relative_to(env[-1]) and not target.is_relative_to(env[-1] / 'candidate')
        assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(env[-1].stat().st_mode) == 0o700
        assert target.is_file() and not target.is_symlink() and target.stat().st_nlink == 1
        assert target.read_bytes() == b'recoverable original'
        assert kwargs.get('check') is True
        calls.append(argv)
        return run(argv, **kwargs)

    monkeypatch.setattr(module.os, 'rename', move)
    monkeypatch.setattr(module.subprocess, 'run', observe)
    result = materialize(env, deleted_paths=[path])
    assert len(calls) == 1 and len(renames) == 1
    assert result['delta']['deleted'] == [path]
    assert originals(env) == baseline
    assert (env[-1] / 'before' / path).read_bytes() == b'recoverable original'
    assert not (env[-1] / 'candidate' / path).exists()
    assert module.full_tree_manifest(env[-1] / 'candidate') == env[5]
    assert (Path.home() / '.Trash' / path).read_bytes() == b'recoverable original'


def test_v2_failed_trash_retains_staged_copy_before_and_originals(tmp_path, monkeypatch):
    env, path = deletion_env(tmp_path)
    baseline = originals(env)
    calls, renames = [], []
    rename = os.rename

    def move(src, dst, **kwargs):
        assert kwargs.get('src_dir_fd') is not None and kwargs.get('dst_dir_fd') is not None
        renames.append((src, dst, kwargs))
        return rename(src, dst, **kwargs)

    def fail(argv, **kwargs):
        assert len(argv) == 2 and argv[0] == '/usr/bin/trash' and '--' not in argv
        target = Path(argv[1])
        assert target.is_absolute() and target.name == path
        assert target.is_relative_to(env[-1]) and not target.is_relative_to(env[-1] / 'candidate')
        assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
        assert target.read_bytes() == b'recoverable original'
        assert kwargs.get('check') is True
        calls.append(argv)
        raise subprocess.CalledProcessError(9, argv, stderr='known v2 fixture failure')

    monkeypatch.setattr(module.os, 'rename', move)
    monkeypatch.setattr(module.subprocess, 'run', fail)
    with pytest.raises(module.ArtifactError) as caught:
        materialize(env, deleted_paths=[path])
    assert 'trash_failed' in codes(caught.value.report)
    assert len(calls) == 1 and len(renames) == 1
    staged = Path(calls[0][1])
    assert caught.value.report['retained_staging'] == {'root': str(staged.parent), 'object': str(staged)}
    assert staged.read_bytes() == b'recoverable original'
    assert originals(env) == baseline
    assert (env[-1] / 'before' / path).read_bytes() == b'recoverable original'
    assert not (env[-1] / 'candidate' / path).exists()
