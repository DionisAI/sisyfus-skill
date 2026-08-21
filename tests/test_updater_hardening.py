from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from sisyfus import __version__
from sisyfus.updater import (
    ActiveWorkError,
    Candidate,
    InstallLayout,
    IntegrityError,
    UpdateManager,
    _activate_release,
    _build_release,
    _release_manifest,
    active_work,
    bootstrap_from_source,
    register_project,
)

ROOT = Path(__file__).resolve().parents[1]


def layout(tmp_path: Path) -> InstallLayout:
    home = tmp_path / "engine"
    return InstallLayout(
        engine_home=home,
        bin_dir=tmp_path / "bin",
        releases_dir=home / "releases",
        current_link=home / "current",
        previous_link=home / "previous",
        state_path=home / "update-state.json",
        project_registry_path=home / "projects.json",
        lock_path=home / "update.lock",
        skill_dirs=(tmp_path / "skills",),
    )


def candidate(release_id: str) -> Candidate:
    return Candidate(
        version=__version__,
        tag=f"v{__version__}",
        channel="stable",
        source_url=str(ROOT),
        release_id=release_id,
        verification="local_source",
    )


def test_engine_and_skill_share_one_atomic_current_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SISYFUS_UPDATE_FORCE_STDLIB", "1")
    target = layout(tmp_path)
    first = _build_release(
        ROOT,
        candidate("first"),
        target,
        archive_sha256="a" * 64,
        remote_manifest=None,
    )
    _activate_release(first, target)
    skill = tmp_path / "skills" / "sisyfus-research"
    assert skill.is_symlink()
    assert skill.resolve() == first / "skill" / "sisyfus-research"

    second = _build_release(
        ROOT,
        candidate("second"),
        target,
        archive_sha256="b" * 64,
        remote_manifest=None,
    )
    _activate_release(second, target)
    assert target.current_link.resolve() == second
    assert skill.resolve() == second / "skill" / "sisyfus-research"
    assert target.previous_link.resolve() == first


def test_release_reuse_checks_identity_and_content_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SISYFUS_UPDATE_FORCE_STDLIB", "1")
    target = layout(tmp_path)
    item = candidate("same")
    release = _build_release(
        ROOT,
        item,
        target,
        archive_sha256="a" * 64,
        remote_manifest=None,
    )
    manifest = _release_manifest(release)
    assert manifest["archive_sha256"] == "a" * 64
    (release / "lib" / "sisyfus" / "__init__.py").write_text(
        "__version__ = 'tampered'\n", encoding="utf-8"
    )
    with pytest.raises(IntegrityError, match="content hash mismatch"):
        _build_release(
            ROOT,
            item,
            target,
            archive_sha256="a" * 64,
            remote_manifest=None,
        )


def test_nonterminal_research_run_blocks_activation(tmp_path: Path) -> None:
    target = layout(tmp_path)
    project = tmp_path / "project"
    run = project / ".sisyfus" / "research" / "runs" / "research-open"
    run.mkdir(parents=True)
    (run / "snapshot.json").write_text(
        json.dumps({"run_status": "ACTIVE", "attempts": {}}),
        encoding="utf-8",
    )
    register_project(project, layout=target)
    found = active_work(target)
    assert any(item["kind"] == "research_run" for item in found)
    with pytest.raises(ActiveWorkError):
        bootstrap_from_source(ROOT, layout=target)


def test_auto_install_is_stable_only_and_notify_keeps_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = layout(tmp_path)
    manager = UpdateManager(layout=target, installed_version=__version__)
    monkeypatch.setattr("sisyfus.updater.platform.system", lambda: "Linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SISYFUS_UPDATE_SKIP_SCHEDULER_ACTIVATION", "1")
    with pytest.raises(ValueError, match="restricted to the stable"):
        manager.configure_auto(enabled=True, mode="auto", channel="beta")
    manager.configure_auto(enabled=True, mode="notify", channel="beta")
    service = (
        tmp_path
        / "config"
        / "systemd"
        / "user"
        / "sisyfus-update.service"
    ).read_text(encoding="utf-8")
    assert "--check" in service
    assert "--channel beta" in service


def test_local_installer_end_to_end(tmp_path: Path) -> None:
    home = tmp_path / "home"
    env = {
        **os.environ,
        "HOME": str(home),
        "SISYFUS_ENGINE_HOME": str(tmp_path / "engine"),
        "SISYFUS_BIN_DIR": str(tmp_path / "bin"),
        "SISYFUS_SKILL_DIRS": str(tmp_path / "skills"),
        "SISYFUS_UPDATE_FORCE_STDLIB": "1",
        "SISYFUS_AUTO_SERVE": "0",
        "SISYFUS_AUTO_OPEN": "0",
    }
    completed = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--allow-active"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    version = subprocess.check_output(
        [str(tmp_path / "bin" / "sisyfus"), "--version"],
        env=env,
        text=True,
    ).strip()
    assert version == __version__
    assert (tmp_path / "skills" / "sisyfus-research").is_symlink()
