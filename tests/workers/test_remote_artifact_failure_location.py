"""Frozen v4 error-location facts: advertise only verified present owned copies.

Mocks never remove originals. Moving a fixture to a retained delivery directory
simulates Trash's ambiguous nonzero exit, not a real Trash recovery locator.
"""
import os
from pathlib import Path
import subprocess

import pytest

from sisyfus.workers import remote_artifacts as module
from test_remote_artifact_trash_receipt import deletion_fixture


def unchanged(args, roots, baseline, name, data):
    assert {str(root): module.full_tree_manifest(root) for root in roots} == baseline
    assert module.full_tree_manifest(args['candidate_root'] / 'before') == baseline[str(roots[0])]
    for root in (*roots[:2], args['candidate_root'] / 'before'):
        assert (root / name).read_bytes() == data


def failed(caught):
    report = caught.value.report
    assert report['valid'] is False and any(e['code'] == 'trash_failed' for e in report['errors'])
    return report


def test_stage_created_but_prerename_boundary_failure_reports_actual_candidate_copy(tmp_path, monkeypatch):
    args, roots, baseline, name, data = deletion_fixture(tmp_path)
    create, check = module._IOBoundary.create, module._IOBoundary.check
    armed, moves, calls = [], [], []
    rename = os.rename

    def exclusive(self, parent, child):
        pin = create(self, parent, child)
        if child.startswith('trash-'): armed.append(pin)
        return pin

    def boundary(self):
        if armed:
            raise ValueError('fixed prerename boundary error')
        return check(self)

    def move(*a, **kw):
        moves.append(a); return rename(*a, **kw)

    monkeypatch.setattr(module._IOBoundary, 'create', exclusive)
    monkeypatch.setattr(module._IOBoundary, 'check', boundary)
    monkeypatch.setattr(module.os, 'rename', move)
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **kw: calls.append(a))
    with pytest.raises(module.ArtifactError) as caught:
        module.materialize_candidate(**args)
    report = failed(caught)
    unchanged(args, roots, baseline, name, data)
    candidate = args['candidate_root'] / 'candidate' / name
    assert candidate.read_bytes() == data
    assert armed and list(armed[0].path.iterdir()) == [] and moves == calls == []
    assert 'retained_staging' not in report
    assert report['retained_candidate'] == {'root': str(candidate.parent), 'object': str(candidate)}
    assert report['failure_location']['candidate'] == 'PRESENT'
    assert report['failure_location']['staging'] == 'ABSENT'
    assert report['failure_location']['moved'] is False


def test_trash_moves_object_then_nonzero_reports_observed_absence_not_fake_locator(tmp_path, monkeypatch):
    args, roots, baseline, name, data = deletion_fixture(tmp_path)
    delivery = tmp_path / 'retained-mock-delivery'
    delivery.mkdir()
    calls = []

    def ambiguous(argv, **kwargs):
        assert len(argv) == 2 and argv[0] == '/usr/bin/trash' and Path(argv[1]).is_absolute()
        assert Path(argv[1]).read_bytes() == data and kwargs['check'] is True
        calls.append(argv)
        os.rename(argv[1], delivery / name)
        raise subprocess.CalledProcessError(7, argv, stderr='fixed postmove error')

    monkeypatch.setattr(module.subprocess, 'run', ambiguous)
    with pytest.raises(module.ArtifactError) as caught:
        module.materialize_candidate(**args)
    report = failed(caught)
    unchanged(args, roots, baseline, name, data)
    staged = Path(calls[0][1])
    assert not os.path.lexists(staged) and (delivery / name).read_bytes() == data
    assert not (args['candidate_root'] / 'candidate' / name).exists()
    assert 'retained_staging' not in report and 'retained_candidate' not in report
    assert report['failure_location']['staging'] == 'ABSENT'
    assert report['failure_location']['moved'] is True
    assert report['failure_location']['trash_attempted'] is True
    assert report['trash_outcome'] == 'UNKNOWN'
    assert 'retained_trash' not in report and 'recovered' not in report


def test_known_nonzero_without_move_reports_verified_staging_and_originals(tmp_path, monkeypatch):
    args, roots, baseline, name, data = deletion_fixture(tmp_path)
    calls = []
    def retained(argv, **kwargs):
        calls.append(argv)
        raise subprocess.CalledProcessError(9, argv, stderr='fixed retained object error')
    monkeypatch.setattr(module.subprocess, 'run', retained)
    with pytest.raises(module.ArtifactError) as caught:
        module.materialize_candidate(**args)
    report = failed(caught)
    unchanged(args, roots, baseline, name, data)
    staged = Path(calls[0][1]); assert staged.read_bytes() == data
    assert report['retained_staging'] == {'root': str(staged.parent), 'object': str(staged)}
    assert 'retained_candidate' not in report
    assert report['failure_location']['staging'] == 'PRESENT'


@pytest.mark.parametrize('race', ['changed-bytes', 'symlink', 'renamed-stage', 'inspection-error'])
def test_diagnostic_races_never_claim_unverified_location_or_hide_original_error(tmp_path, monkeypatch, race):
    args, roots, baseline, name, data = deletion_fixture(tmp_path)
    calls, retained = [], []
    directory = module._directory
    def error(argv, **kwargs):
        staged = Path(argv[1]); calls.append(argv)
        if race == 'changed-bytes': staged.write_bytes(b'changed independent copy')
        elif race == 'symlink':
            moved = staged.with_name('retained-original-copy')
            os.rename(staged, moved); retained.append(moved)
            staged.symlink_to(moved)
        elif race == 'renamed-stage':
            moved = staged.parent.with_name('retained-stage-moved')
            os.rename(staged.parent, moved); retained.append(moved / name)
        else:
            def broken(path, *a, **kw):
                if Path(path) == staged.parent: raise PermissionError('fixed diagnostic probe error')
                return directory(path, *a, **kw)
            monkeypatch.setattr(module, '_directory', broken)
        raise subprocess.CalledProcessError(11, argv, stderr='original fixed failure')
    monkeypatch.setattr(module.subprocess, 'run', error)
    with pytest.raises(module.ArtifactError) as caught:
        module.materialize_candidate(**args)
    report = failed(caught)
    unchanged(args, roots, baseline, name, data)
    assert calls and 'retained_staging' not in report and 'retained_candidate' not in report
    assert report['failure_location']['staging'] in {'UNKNOWN', 'UNVERIFIED'}
    assert report['failure_location']['failure_type'] == 'CalledProcessError'
    assert report['trash_outcome'] == 'UNKNOWN'
    for copy in retained: assert copy.read_bytes() == data
