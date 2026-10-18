"""Frozen v3 Trash receipt checks; retained local IO, not remote execution.

Each real readback is bound to this run by an exclusive UUID filename and
independent random bytes. An exit-zero/no-move receipt is a diagnosed failure.
"""
import hashlib
import os
from pathlib import Path
import secrets
import stat
import subprocess
import uuid

import pytest

from sisyfus.workers import remote_artifacts as module


def deletion_fixture(tmp_path):
    """Prepare independent originals and a uniquely identifiable deletion copy."""
    name = 'artifact-trash-' + uuid.uuid4().hex + '.txt'
    data = b'this-run-retained-original:' + secrets.token_bytes(48)
    source, snapshot, artifacts, envelope = [tmp_path / p for p in
                                           ('source', 'snapshot', 'uploads', 'envelope')]
    source.mkdir()
    (source / name).write_bytes(data)
    manifest = module.create_input_snapshot(source, snapshot, [name])
    claim = 'claim_' + uuid.uuid4().hex
    (artifacts / claim).mkdir(parents=True)
    final = {'schema': 1, 'files': [], 'tree': [], 'errors': [], 'complete': True}
    roots = (source, snapshot, artifacts)
    baseline = {str(root): module.full_tree_manifest(root) for root in roots}
    return dict(snapshot=snapshot, input_manifest=manifest, tree_manifest=final,
                uploads=[], deleted_paths=[name], artifact_root=artifacts,
                claim_id=claim, candidate_root=envelope), roots, baseline, name, data


def observe_staging(monkeypatch, args, name, data, action):
    """Check exact command and descriptor-relative staging at the IO boundary."""
    calls, renames = [], []
    rename = os.rename

    def move(src, dst, **kwargs):
        assert src == dst == name
        assert kwargs.get('src_dir_fd') is not None
        assert kwargs.get('dst_dir_fd') is not None
        assert kwargs['src_dir_fd'] != kwargs['dst_dir_fd']
        renames.append((src, dst))
        return rename(src, dst, **kwargs)

    def trash(argv, **kwargs):
        assert len(argv) == 2 and argv[0] == '/usr/bin/trash' and '--' not in argv
        staged = Path(argv[1])
        assert staged.is_absolute() and staged.name == name
        assert staged.parent.parent == args['candidate_root']
        assert staged.parent.name.startswith('trash-')
        assert not staged.is_relative_to(args['candidate_root'] / 'candidate')
        assert stat.S_IMODE(staged.parent.stat().st_mode) == 0o700
        assert staged.is_file() and not staged.is_symlink() and staged.stat().st_nlink == 1
        assert staged.read_bytes() == data
        assert kwargs.get('check') is True
        calls.append(argv.copy())
        return action(argv, **kwargs)

    monkeypatch.setattr(module.os, 'rename', move)
    monkeypatch.setattr(module.subprocess, 'run', trash)
    return calls, renames


def assert_originals(args, roots, baseline, name, data):
    """Read full original trees and the independent before bytes after mutation."""
    assert {str(root): module.full_tree_manifest(root) for root in roots} == baseline
    for root in (*roots[:2], args['candidate_root'] / 'before'):
        assert (root / name).read_bytes() == data
    assert module.full_tree_manifest(args['candidate_root'] / 'before') == baseline[str(roots[0])]
    assert not (args['candidate_root'] / 'candidate' / name).exists()


def test_exit_zero_without_move_reports_retained_staging_and_never_success(tmp_path, monkeypatch):
    args, roots, baseline, name, data = deletion_fixture(tmp_path)
    calls, renames = observe_staging(monkeypatch, args, name, data,
                                   lambda argv, **kw: subprocess.CompletedProcess(argv, 0))
    with pytest.raises(module.ArtifactError) as caught:
        module.materialize_candidate(**args)
    report = caught.value.report
    assert report['valid'] is False
    assert any(e['code'] == 'trash_failed' and e['path'] == name for e in report['errors'])
    assert len(calls) == len(renames) == 1
    staged = Path(calls[0][1])
    assert_originals(args, roots, baseline, name, data)
    assert staged.read_bytes() == data
    assert hashlib.sha256(staged.read_bytes()).hexdigest() == args['input_manifest']['files'][0]['sha256']
    assert report['retained_staging'] == {'root': str(staged.parent), 'object': str(staged)}


def test_real_trash_readback_is_bound_to_this_run_unique_name_and_bytes(tmp_path, monkeypatch):
    args, roots, baseline, name, data = deletion_fixture(tmp_path)
    recovered = Path.home() / '.Trash' / name
    assert not os.path.lexists(recovered)
    run = subprocess.run
    calls, renames = observe_staging(monkeypatch, args, name, data, run)
    result = module.materialize_candidate(**args)
    assert len(calls) == len(renames) == 1
    assert result['candidate'] == str(args['candidate_root'] / 'candidate')
    assert result['before'] == str(args['candidate_root'] / 'before')
    assert result['delta']['valid'] is True and result['delta']['deleted'] == [name]
    assert module.full_tree_manifest(Path(result['candidate'])) == args['tree_manifest']
    assert_originals(args, roots, baseline, name, data)
    assert not os.path.lexists(calls[0][1])
    assert recovered.is_file() and not recovered.is_symlink()
    assert recovered.read_bytes() == data
    assert hashlib.sha256(recovered.read_bytes()).hexdigest() == args['input_manifest']['files'][0]['sha256']
