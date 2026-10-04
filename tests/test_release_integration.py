"""Regressions for the #2 updater + #3 Research OS + #4 workers integration."""
from __future__ import annotations

import hashlib
import io
import subprocess
import tarfile
import urllib.request
from pathlib import Path

import pytest

from sisyfus import __version__
from sisyfus.updater import (
    ActiveWorkError, Candidate, CredentialSafeRedirect, GitHubClient, InstallLayout,
    IntegrityError, _activate_release, _build_release, _safe_extract,
    _verify_release, active_work, bootstrap_from_source, register_project, update_lock,
)
from sisyfus.workers.cli import demo_spec
from sisyfus.workers.installation_guard import running_installation
from sisyfus.workers.mission import Mission, load_spec, validate_tasks

ROOT = Path(__file__).resolve().parents[1]


def layout(tmp_path: Path) -> InstallLayout:
    home = tmp_path / 'engine'
    return InstallLayout(home, tmp_path / 'bin', home / 'releases', home / 'current',
                         home / 'previous', home / 'update-state.json', home / 'projects.json',
                         home / 'update.lock', (tmp_path / 'skills',))


def build(target: InstallLayout, release_id: str, sha: str = 'a') -> Path:
    return _build_release(ROOT, Candidate(__version__, f'v{__version__}', 'stable',
                          str(ROOT), release_id), target,
                          archive_sha256=sha * 64, remote_manifest=None)


def test_stdlib_install_routes_workers_os_and_update_without_content_drift(tmp_path):
    target = layout(tmp_path)
    release = build(target, 'install-test')
    exe = release / 'bin' / 'sisyfus'
    for command in (['workers', '--help'], ['os', '--help'], ['update', '--help']):
        result = subprocess.run([str(exe), *command], text=True, capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr
    demo = subprocess.run([str(exe), 'workers', 'demo', '--directory', str(tmp_path / 'demo')],
                          text=True, capture_output=True, timeout=60)
    assert demo.returncode == 0, demo.stderr
    assert _verify_release(release)['version'] == __version__
    assert not list((release / 'lib').rglob('*.pyc'))


@pytest.mark.parametrize('which', ['current', 'previous'])
def test_updater_cannot_destroy_activated_release_on_identity_conflict(tmp_path, which):
    target = layout(tmp_path)
    old = build(target, 'protected')
    _activate_release(old, target)
    if which == 'previous':
        _activate_release(build(target, 'new', 'b'), target)
    before = (old / 'install-manifest.json').read_bytes()
    with pytest.raises(IntegrityError, match='replace a current/previous'):
        build(target, 'protected', 'c')
    assert (old / 'install-manifest.json').read_bytes() == before
    assert _verify_release(old)['complete']


@pytest.mark.parametrize('status', ['IN_FLIGHT', 'UNKNOWN'])
def test_native_planner_receipt_blocks_update_in_separate_control_directory(tmp_path, status):
    spec_path = demo_spec(tmp_path / 'fixture')
    mission = Mission(tmp_path / 'control', load_spec(spec_path))
    mission.journal.reserve('planner', 'planner', 'request-fingerprint')
    if status == 'UNKNOWN':
        mission.journal.complete('planner', {'status': 'UNKNOWN', 'error': 'lost final response'})
    target = layout(tmp_path)
    register_project(mission.directory, layout=target)
    assert any(a['kind'] == 'native_worker' and a['status'] == status for a in active_work(target))
    with pytest.raises(ActiveWorkError):
        bootstrap_from_source(ROOT, layout=target)
    assert not target.current_link.exists()


def test_unreadable_native_database_is_not_treated_as_idle(tmp_path):
    target = layout(tmp_path)
    project = tmp_path / 'control'
    project.mkdir()
    (project / 'autonomy.sqlite3').write_bytes(b'corrupt database')
    register_project(project, layout=target)
    assert any(a['kind'] == 'unreadable_state' for a in active_work(target))


def test_running_controller_fences_activation_and_allows_registry_updates(tmp_path):
    target = layout(tmp_path)
    with running_installation(target):
        register_project(tmp_path, layout=target)  # Separate registry lock: no deadlock.
        with running_installation(target):  # Independent controllers may coexist.
            with pytest.raises(ActiveWorkError):
                with update_lock(target):
                    pytest.fail('updater acquired an exclusive lock while mission ran')
    with update_lock(target):
        pass


def test_api_token_is_not_attached_to_release_asset_origin():
    client = GitHubClient(token='private-test-token')
    assert client._request('https://api.github.com/repos/x/y').get_header('Authorization')
    for url in ('https://github.com/x/y/releases/download/v1/asset', 'https://example.org/asset'):
        assert client._request(url).get_header('Authorization') is None


def test_cross_origin_redirect_strips_authorization():
    request = urllib.request.Request('https://api.github.com/repos/x/y/zipball',
                                     headers={'Authorization': 'Bearer private'})
    redirect = CredentialSafeRedirect().redirect_request(
        request, None, 302, 'found', {}, 'https://codeload.github.com/x/y/archive')
    assert redirect.get_header('Authorization') is None
    same = CredentialSafeRedirect().redirect_request(
        request, None, 302, 'found', {}, 'https://api.github.com/next')
    assert same.get_header('Authorization') == 'Bearer private'


def test_extraction_limit_precedes_payload_extraction(tmp_path):
    # An oversized sparse/truncated member must be rejected by declared size,
    # before extraction can allocate its payload.
    archive = tmp_path / 'oversized.tar'
    header = tarfile.TarInfo('bundle/large.bin')
    header.size = 513 * 1024 * 1024
    archive.write_bytes(header.tobuf() + bytes(1024))
    # getmembers may reject the truncated member first; either outcome is safe.
    with pytest.raises((IntegrityError, tarfile.ReadError)):
        _safe_extract(archive, tmp_path / 'output')
    assert not (tmp_path / 'output' / 'bundle' / 'large.bin').exists()


def test_reserved_planner_task_id_is_rejected(tmp_path):
    spec = load_spec(demo_spec(tmp_path / 'fixture'))
    with pytest.raises(ValueError, match='task id'):
        validate_tasks([{'id':'planner', 'objective':'x', 'driver':'codex', 'check':'answer'}], spec)
