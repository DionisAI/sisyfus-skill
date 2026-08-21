from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str, mode: int | None = None) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    if mode is not None:
        target.chmod(mode)


def replace_top(text: str, name: str, replacement: str) -> str:
    pattern = re.compile(
        rf"(?ms)^def {re.escape(name)}\(.*?(?=^def |^class |\Z)"
    )
    updated, count = pattern.subn(replacement.rstrip() + "\n\n", text, count=1)
    if count != 1:
        raise SystemExit(f"could not replace top-level function {name}: {count}")
    return updated


def replace_method(text: str, name: str, replacement: str) -> str:
    pattern = re.compile(
        rf"(?ms)^    def {re.escape(name)}\(.*?(?=^    def |^def |\Z)"
    )
    updated, count = pattern.subn(replacement.rstrip() + "\n", text, count=1)
    if count != 1:
        raise SystemExit(f"could not replace method {name}: {count}")
    return updated


updater = read("src/sisyfus/updater.py")

updater = replace_top(
    updater,
    "_candidate_from_release",
    '''def _candidate_from_release(
    release: Mapping[str, Any], channel: str
) -> Candidate:
    tag = str(release.get("tag_name") or "")
    version = normalize_version(tag)
    archive_name = f"sisyfus-{version}.tar.gz"
    manifest_url = _release_asset(
        release,
        ("release-manifest.json", f"sisyfus-{version}-manifest.json"),
    )
    asset_url = _release_asset(release, (archive_name,))
    source_url = asset_url or str(
        release.get("tarball_url")
        or f"{WEB_BASE}/{REPOSITORY}/archive/refs/tags/v{version}.tar.gz"
    )
    target = str(release.get("target_commitish") or "")
    commit_sha = target if re.fullmatch(r"[0-9a-f]{40}", target) else None
    return Candidate(
        version=version,
        tag=tag or f"v{version}",
        channel=channel,
        source_url=source_url,
        release_id=version,
        commit_sha=commit_sha,
        manifest_url=manifest_url,
        verification=(
            "manifest_sha256" if manifest_url and asset_url else "tag_only"
        ),
        prerelease=bool(release.get("prerelease")),
        published_at=str(release.get("published_at") or "") or None,
    )''',
)

updater = replace_top(
    updater,
    "resolve_candidate",
    '''def resolve_candidate(
    *,
    channel: str = "stable",
    version: str | None = None,
    client: GitHubClient | Any | None = None,
) -> Candidate:
    client = client or GitHubClient()
    channel = str(channel or "stable").lower()
    if channel not in {"stable", "beta", "edge"}:
        raise ValueError(f"unsupported update channel: {channel}")

    if version:
        normalized = normalize_version(version)
        tag = f"v{normalized}"
        try:
            release = client.json(
                f"{API_BASE}/repos/{REPOSITORY}/releases/tags/{tag}"
            )
            return _candidate_from_release(release, channel)
        except UpdateError:
            return Candidate(
                version=normalized,
                tag=tag,
                channel=channel,
                source_url=(
                    f"{WEB_BASE}/{REPOSITORY}/archive/refs/tags/{tag}.tar.gz"
                ),
                release_id=normalized,
                verification="tag_only",
                prerelease=bool(SemVer.parse(normalized).prerelease),
            )

    if channel == "stable":
        try:
            return _candidate_from_release(
                client.json(
                    f"{API_BASE}/repos/{REPOSITORY}/releases/latest"
                ),
                channel,
            )
        except UpdateError:
            tags = client.json(
                f"{API_BASE}/repos/{REPOSITORY}/tags?per_page=100"
            )
            versioned: list[tuple[SemVer, str, str | None]] = []
            for item in tags or []:
                name = str(item.get("name") or "")
                try:
                    parsed = SemVer.parse(name)
                except ValueError:
                    continue
                if parsed.prerelease:
                    continue
                sha = str((item.get("commit") or {}).get("sha") or "")
                versioned.append((parsed, name, sha or None))
            if not versioned:
                raise UpdateUnavailable(
                    "no stable Sisyfus release or semantic tag found"
                )
            parsed, tag, sha = max(
                versioned, key=lambda item: item[0].sort_key()
            )
            return Candidate(
                version=str(parsed),
                tag=tag,
                channel="stable",
                source_url=(
                    f"{WEB_BASE}/{REPOSITORY}/archive/refs/tags/{tag}.tar.gz"
                ),
                release_id=str(parsed),
                commit_sha=sha,
                verification="tag_only",
            )

    if channel == "beta":
        releases = client.json(
            f"{API_BASE}/repos/{REPOSITORY}/releases?per_page=100"
        )
        candidates: list[tuple[SemVer, Mapping[str, Any]]] = []
        for item in releases or []:
            if item.get("draft") or not item.get("tag_name"):
                continue
            try:
                parsed = SemVer.parse(str(item["tag_name"]))
            except ValueError:
                continue
            candidates.append((parsed, item))
        if not candidates:
            raise UpdateUnavailable("no semantic Sisyfus releases found")
        _, release = max(candidates, key=lambda item: item[0].sort_key())
        return _candidate_from_release(release, channel)

    branch = client.json(
        f"{API_BASE}/repos/{REPOSITORY}/branches/main"
    )
    sha = str((branch.get("commit") or {}).get("sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise UpdateError("main branch response did not contain a commit SHA")
    from . import __version__ as base_version

    return Candidate(
        version=f"{normalize_version(base_version)}+edge.{sha[:12]}",
        tag=sha,
        channel="edge",
        source_url=f"{WEB_BASE}/{REPOSITORY}/archive/{sha}.tar.gz",
        release_id=f"edge-{sha[:12]}",
        commit_sha=sha,
        verification="commit_sha",
    )''',
)

updater = replace_top(
    updater,
    "_load_manifest",
    '''def _load_manifest(
    candidate: Candidate, client: GitHubClient | Any
) -> dict[str, Any] | None:
    if not candidate.manifest_url:
        return None
    manifest = client.json(candidate.manifest_url)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != RELEASE_MANIFEST_SCHEMA
    ):
        raise IntegrityError("unsupported release manifest schema")
    if normalize_version(str(manifest.get("version"))) != normalize_version(
        candidate.version.split("+", 1)[0]
    ):
        raise IntegrityError("release manifest version mismatch")
    if (
        str(manifest.get("tag")) != candidate.tag
        or str(manifest.get("repository") or REPOSITORY) != REPOSITORY
    ):
        raise IntegrityError("release manifest identity mismatch")

    digest = str(manifest.get("archive_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise IntegrityError("release manifest has no valid archive_sha256")

    archive_name = str(manifest.get("archive_name") or "")
    if archive_name and not candidate.source_url.split("?", 1)[0].endswith(
        "/" + archive_name
    ):
        raise IntegrityError("release manifest archive name mismatch")

    manifest_commit = str(manifest.get("commit_sha") or "")
    if (
        candidate.commit_sha
        and re.fullmatch(r"[0-9a-f]{40}", candidate.commit_sha)
        and manifest_commit
        and candidate.commit_sha != manifest_commit
    ):
        raise IntegrityError("release manifest commit mismatch")

    minimum_python = str(manifest.get("minimum_python") or "")
    if minimum_python:
        match = re.fullmatch(r"(\d+)\.(\d+)", minimum_python)
        if not match:
            raise IntegrityError("release manifest minimum_python is invalid")
        required = (int(match.group(1)), int(match.group(2)))
        if sys.version_info[:2] < required:
            raise IntegrityError(
                f"release requires Python {minimum_python} or newer"
            )
    return manifest''',
)

updater = replace_top(
    updater,
    "_active_research",
    '''def _active_research(root: Path) -> list[dict[str, Any]]:
    runs = root / ".sisyfus" / "research" / "runs"
    if not runs.exists():
        return []
    active: list[dict[str, Any]] = []
    for snapshot_path in runs.glob("*/snapshot.json"):
        snapshot = _read_json(snapshot_path, {})
        run_status = str(snapshot.get("run_status") or "").upper()
        if not run_status or run_status in TERMINAL_RESEARCH_STATUSES:
            continue
        research_id = snapshot_path.parent.name
        active.append(
            {
                "kind": "research_run",
                "project": str(root),
                "id": research_id,
                "status": run_status,
                "summary": (
                    f"{root}: research run {research_id} is {run_status}"
                ),
            }
        )
        attempts = snapshot.get("attempts") or {}
        for attempt in attempts.values() if isinstance(attempts, dict) else []:
            status = str((attempt or {}).get("status") or "").upper()
            if status in {"RESERVED", "RUNNING"}:
                active.append(
                    {
                        "kind": "research_attempt",
                        "project": str(root),
                        "id": (attempt or {}).get("id"),
                        "status": status,
                        "summary": (
                            f"{root}: research attempt "
                            f"{(attempt or {}).get('id')} is {status}"
                        ),
                    }
                )
    return active''',
)

marker = '''def _atomic_symlink(target: Path, link: Path) -> None:
    link.parent.mkdir(parents=True,exist_ok=True); temporary=link.with_name(f".{link.name}.{os.getpid()}.{time.time_ns()}")
    os.symlink(os.path.relpath(target,start=link.parent),temporary); os.replace(temporary,link)
'''
addition = marker + '''

def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _atomic_directory_symlink(target: Path, link: Path) -> None:
    """Replace a copied Skill directory with a stable symlink atomically."""
    link.parent.mkdir(parents=True, exist_ok=True)
    temporary = link.with_name(
        f".{link.name}.{os.getpid()}.{time.time_ns()}.new"
    )
    backup = link.with_name(
        f".{link.name}.{os.getpid()}.{time.time_ns()}.old"
    )
    os.symlink(os.path.relpath(target, start=link.parent), temporary)
    moved_old = False
    try:
        if link.exists() or link.is_symlink():
            os.replace(link, backup)
            moved_old = True
        os.replace(temporary, link)
    except Exception:
        temporary.unlink(missing_ok=True)
        if moved_old and not link.exists() and not link.is_symlink():
            os.replace(backup, link)
        raise
    else:
        if moved_old:
            _remove_path(backup)
'''
if addition not in updater:
    if updater.count(marker) != 1:
        raise SystemExit("could not locate _atomic_symlink insertion point")
    updater = updater.replace(marker, addition, 1)

build_helpers = '''def _release_content_hash(release_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(release_dir.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(release_dir).as_posix()
        if relative == "install-manifest.json" or path.is_dir():
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"link\0")
            digest.update(os.readlink(path).encode("utf-8"))
        else:
            digest.update(b"file\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _verify_release(release_dir: Path, expected_version: str | None = None) -> dict[str, Any]:
    manifest = _release_manifest(release_dir)
    if not manifest.get("complete"):
        raise IntegrityError(f"release is incomplete: {release_dir}")
    version = str(manifest.get("version") or "")
    if expected_version and version != expected_version:
        raise IntegrityError(
            f"release version {version!r} does not match {expected_version!r}"
        )
    expected_hash = str(manifest.get("content_sha256") or "")
    actual_hash = _release_content_hash(release_dir)
    if not expected_hash or expected_hash != actual_hash:
        raise IntegrityError(
            f"installed release content hash mismatch: {release_dir}"
        )
    _smoke_release(release_dir, version)
    return manifest


'''
if build_helpers not in updater:
    insertion = "def _build_release("
    if updater.count(insertion) != 1:
        raise SystemExit("could not locate build helper insertion point")
    updater = updater.replace(insertion, build_helpers + insertion, 1)

updater = replace_top(
    updater,
    "_build_release",
    '''def _build_release(
    source: Path,
    candidate: Candidate,
    layout: InstallLayout,
    *,
    archive_sha256: str | None,
    remote_manifest: Mapping[str, Any] | None,
) -> Path:
    if (
        not candidate.release_id
        or Path(candidate.release_id).name != candidate.release_id
        or candidate.release_id in {".", ".."}
    ):
        raise IntegrityError("unsafe release identifier")

    release_dir = layout.releases_dir / candidate.release_id
    expected_version = _source_version(source)
    existing = _release_manifest(release_dir)
    identity_matches = bool(
        existing.get("complete")
        and existing.get("version") == expected_version
        and existing.get("display_version") == candidate.version
        and existing.get("tag") == candidate.tag
        and existing.get("release_id") == candidate.release_id
        and (
            archive_sha256 is None
            or existing.get("archive_sha256") == archive_sha256
        )
        and (
            candidate.commit_sha is None
            or existing.get("source_commit") == candidate.commit_sha
        )
    )
    if identity_matches:
        _verify_release(release_dir, expected_version)
        return release_dir

    shutil.rmtree(release_dir, ignore_errors=True)
    release_dir.mkdir(parents=True)
    # Sisyfus has no runtime dependencies. A source-copy release avoids running
    # arbitrary build backends during an update and makes rollback hashable.
    _install_stdlib(source, release_dir)
    _copy_skill(source, release_dir / "skill" / "sisyfus-research")
    _smoke_release(release_dir, expected_version)

    payload = {
        "schema_version": "sisyfus.install.v1",
        "complete": True,
        "version": expected_version,
        "display_version": candidate.version,
        "tag": candidate.tag,
        "channel": candidate.channel,
        "release_id": candidate.release_id,
        "source_url": candidate.source_url,
        "source_commit": candidate.commit_sha,
        "archive_sha256": archive_sha256,
        "verification": candidate.verification,
        "install_method": "stdlib-source-copy",
        "installed_at": utc_now(),
        "remote_manifest": dict(remote_manifest or {}),
    }
    payload["content_sha256"] = _release_content_hash(release_dir)
    _atomic_json(release_dir / "install-manifest.json", payload)
    _verify_release(release_dir, expected_version)
    return release_dir''',
)

updater = replace_top(
    updater,
    "_activate_release",
    '''def _activate_release(
    release_dir: Path,
    layout: InstallLayout,
    *,
    candidate: Candidate | None = None,
    preserve_previous: bool = True,
) -> dict[str, Any]:
    manifest = _verify_release(release_dir)
    old_current = _symlink_target(layout.current_link)

    # Stable launchers and Skill directories all resolve through `current`.
    # Preparing those links before the single current-link swap makes Engine
    # and Skill activation one compatibility-unit transition.
    for command in ("sisyfus", "sisyfus-autonomy"):
        _atomic_symlink(
            layout.current_link / "bin" / command,
            layout.bin_dir / command,
        )
    for root in layout.skill_dirs:
        root.mkdir(parents=True, exist_ok=True)
        _atomic_directory_symlink(
            layout.current_link / "skill" / "sisyfus-research",
            root / "sisyfus-research",
        )

    if preserve_previous and old_current and old_current != release_dir:
        _atomic_symlink(old_current, layout.previous_link)
    _atomic_symlink(release_dir, layout.current_link)

    state = _read_json(layout.state_path, {})
    previous = _symlink_target(layout.previous_link)
    state.update(
        {
            "schema_version": UPDATE_STATE_SCHEMA,
            "current_release": str(release_dir),
            "current_version": manifest.get("version"),
            "display_version": manifest.get("display_version"),
            "previous_release": str(previous) if previous else None,
            "channel": (
                candidate.channel
                if candidate
                else manifest.get("channel")
                or state.get("channel")
                or "stable"
            ),
            "activated_at": utc_now(),
            "last_result": "updated" if candidate else "activated",
            "restart_agent_session": True,
        }
    )
    _atomic_json(layout.state_path, state)
    return state''',
)

updater = replace_method(
    updater,
    "check",
    '''    def _candidate_available(
        self, candidate: Candidate, *, exact: bool = False
    ) -> bool:
        current = _release_manifest(_symlink_target(self.layout.current_link))
        if candidate.channel == "edge":
            return current.get("source_commit") != candidate.commit_sha
        current_version = str(current.get("version") or self.installed_version)
        if exact:
            return normalize_version(current_version) != normalize_version(
                candidate.version
            )
        return SemVer.parse(current_version) < SemVer.parse(candidate.version)

    def _record_check(
        self, candidate: Candidate, *, available: bool
    ) -> dict[str, Any]:
        state = _read_json(self.layout.state_path, {})
        state.update(
            {
                "schema_version": UPDATE_STATE_SCHEMA,
                "last_check_at": utc_now(),
                "channel": candidate.channel,
                "latest_version": candidate.version,
                "latest_candidate": candidate.as_dict(),
                "update_available": bool(available),
                "last_result": (
                    "update_available" if available else "up_to_date"
                ),
            }
        )
        _atomic_json(self.layout.state_path, state)
        return {
            "status": "UPDATE_AVAILABLE" if available else "UP_TO_DATE",
            "installed_version": str(
                (_release_manifest(_symlink_target(self.layout.current_link))).get(
                    "version"
                )
                or self.installed_version
            ),
            "candidate": candidate.as_dict(),
            "update_available": bool(available),
        }

    def check(
        self, *, channel: str = "stable", version: str | None = None
    ) -> dict[str, Any]:
        candidate = resolve_candidate(
            channel=channel, version=version, client=self.client
        )
        available = self._candidate_available(
            candidate, exact=version is not None
        )
        return self._record_check(candidate, available=available)
''',
)

updater = replace_method(
    updater,
    "apply",
    '''    def apply(
        self,
        *,
        channel: str = "stable",
        version: str | None = None,
        force: bool = False,
        allow_active: bool = False,
        require_verified: bool = False,
    ) -> dict[str, Any]:
        candidate = resolve_candidate(
            channel=channel, version=version, client=self.client
        )
        available = self._candidate_available(
            candidate, exact=version is not None
        )
        check = self._record_check(candidate, available=available)
        if not force and not available:
            return check

        with update_lock(self.layout):
            if not allow_active:
                active = active_work(self.layout)
                if active:
                    state = _read_json(self.layout.state_path, {})
                    state.update(
                        {
                            "schema_version": UPDATE_STATE_SCHEMA,
                            "last_result": "deferred_active_work",
                            "deferred_at": utc_now(),
                            "active_work": active,
                        }
                    )
                    _atomic_json(self.layout.state_path, state)
                    raise ActiveWorkError(active)

            with tempfile.TemporaryDirectory(
                prefix="sisyfus-update-", dir=self.layout.engine_home
            ) as temporary:
                temporary_path = Path(temporary)
                archive = temporary_path / "release.tar.gz"
                remote_manifest = _load_manifest(candidate, self.client)
                expected_hash = (
                    str(remote_manifest.get("archive_sha256"))
                    if remote_manifest
                    else candidate.archive_sha256
                )
                if require_verified and not expected_hash:
                    state = _read_json(self.layout.state_path, {})
                    state.update(
                        {
                            "last_result": "deferred_unverified_release",
                            "deferred_at": utc_now(),
                            "latest_candidate": candidate.as_dict(),
                        }
                    )
                    _atomic_json(self.layout.state_path, state)
                    raise IntegrityError(
                        "scheduled installation requires a SHA-256 release manifest"
                    )

                actual_hash = self.client.download(
                    candidate.source_url, archive
                )
                if expected_hash and actual_hash != expected_hash:
                    raise IntegrityError(
                        "archive SHA-256 mismatch: "
                        f"expected {expected_hash}, got {actual_hash}"
                    )
                extracted = _safe_extract(
                    archive, temporary_path / "source"
                )
                source_version = _source_version(extracted)
                expected_version = candidate.version.split("+", 1)[0]
                if normalize_version(source_version) != normalize_version(
                    expected_version
                ):
                    raise IntegrityError(
                        f"archive version {source_version} does not match "
                        f"{expected_version}"
                    )
                release_dir = _build_release(
                    extracted,
                    candidate,
                    self.layout,
                    archive_sha256=actual_hash,
                    remote_manifest=remote_manifest,
                )
            state = _activate_release(
                release_dir, self.layout, candidate=candidate
            )
        return {
            "status": "UPDATED",
            "from_version": self.installed_version,
            "to_version": candidate.version,
            "release": str(release_dir),
            "verification": (
                "manifest_sha256" if expected_hash else candidate.verification
            ),
            "restart_agent_session": True,
            "state": state,
        }
''',
)

updater = replace_method(
    updater,
    "rollback",
    '''    def rollback(self, *, allow_active: bool = False) -> dict[str, Any]:
        with update_lock(self.layout):
            if not allow_active:
                active = active_work(self.layout)
                if active:
                    raise ActiveWorkError(active)
            current = _symlink_target(self.layout.current_link)
            previous = _symlink_target(self.layout.previous_link)
            if previous is None or not previous.exists():
                raise UpdateUnavailable(
                    "no previous versioned release is available"
                )
            previous_manifest = _verify_release(previous)
            _activate_release(
                previous,
                self.layout,
                candidate=None,
                preserve_previous=False,
            )
            if current and current.exists():
                _atomic_symlink(current, self.layout.previous_link)
            state = _read_json(self.layout.state_path, {})
            state.update(
                {
                    "last_result": "rolled_back",
                    "rolled_back_at": utc_now(),
                    "previous_release": str(current) if current else None,
                }
            )
            _atomic_json(self.layout.state_path, state)
        return {
            "status": "ROLLED_BACK",
            "current_version": previous_manifest.get("version"),
            "current_release": str(previous),
            "previous_release": str(current) if current else None,
            "restart_agent_session": True,
        }
''',
)

updater = replace_method(
    updater,
    "configure_auto",
    '''    def configure_auto(
        self,
        *,
        enabled: bool,
        mode: str = "notify",
        channel: str = "stable",
        interval_hours: float = 24.0,
        activate: bool = True,
    ) -> dict[str, Any]:
        if mode not in {"notify", "auto"}:
            raise ValueError("auto-update mode must be notify or auto")
        if channel not in {"stable", "beta", "edge"}:
            raise ValueError(
                "auto-update channel must be stable, beta, or edge"
            )
        if enabled and mode == "auto" and channel != "stable":
            raise ValueError(
                "automatic installation is restricted to the stable channel; "
                "use notify mode for beta or edge"
            )

        interval_seconds = max(900, int(float(interval_hours) * 3600))
        system = platform.system().lower()
        command = self.layout.bin_dir / "sisyfus"
        log_dir = self.layout.engine_home / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        installed_paths: list[str] = []
        scheduled_args = [
            str(command),
            "update",
            "--channel",
            channel,
            "--scheduled",
            "--json",
        ]
        if mode == "notify":
            scheduled_args.insert(2, "--check")
        else:
            scheduled_args.insert(2, "--yes")

        if system == "linux":
            user_config = Path(
                os.environ.get(
                    "XDG_CONFIG_HOME", str(Path.home() / ".config")
                )
            ).expanduser() / "systemd" / "user"
            service = user_config / "sisyfus-update.service"
            timer = user_config / "sisyfus-update.timer"
            if enabled:
                _atomic_text(
                    service,
                    "[Unit]\nDescription=Check or apply Sisyfus updates\n\n"
                    "[Service]\nType=oneshot\n"
                    f"ExecStart={shlex.join(scheduled_args)}\n"
                    f"StandardOutput=append:{log_dir / 'update.log'}\n"
                    f"StandardError=append:{log_dir / 'update.log'}\n",
                )
                _atomic_text(
                    timer,
                    "[Unit]\nDescription=Periodic Sisyfus update check\n\n"
                    "[Timer]\nOnBootSec=5m\n"
                    f"OnUnitActiveSec={interval_seconds}s\n"
                    "RandomizedDelaySec=30m\nPersistent=true\n\n"
                    "[Install]\nWantedBy=timers.target\n",
                )
                installed_paths = [str(service), str(timer)]
                if (
                    activate
                    and os.environ.get(
                        "SISYFUS_UPDATE_SKIP_SCHEDULER_ACTIVATION"
                    )
                    != "1"
                ):
                    subprocess.run(
                        ["systemctl", "--user", "daemon-reload"],
                        check=True,
                    )
                    subprocess.run(
                        ["systemctl", "--user", "enable", "--now", timer.name],
                        check=True,
                    )
            else:
                if activate and shutil.which("systemctl"):
                    subprocess.run(
                        ["systemctl", "--user", "disable", "--now", timer.name],
                        check=False,
                    )
                    subprocess.run(
                        ["systemctl", "--user", "daemon-reload"],
                        check=False,
                    )
                service.unlink(missing_ok=True)
                timer.unlink(missing_ok=True)
        elif system == "darwin":
            import plistlib

            plist = (
                Path.home()
                / "Library"
                / "LaunchAgents"
                / "ai.dionis.sisyfus-update.plist"
            )
            if enabled:
                plist.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "Label": "ai.dionis.sisyfus-update",
                    "ProgramArguments": scheduled_args,
                    "StartInterval": interval_seconds,
                    "RunAtLoad": True,
                    "StandardOutPath": str(log_dir / "update.log"),
                    "StandardErrorPath": str(log_dir / "update.log"),
                }
                temporary = plist.with_name(
                    f".{plist.name}.{os.getpid()}"
                )
                with temporary.open("wb") as handle:
                    plistlib.dump(payload, handle)
                os.replace(temporary, plist)
                installed_paths = [str(plist)]
                if (
                    activate
                    and os.environ.get(
                        "SISYFUS_UPDATE_SKIP_SCHEDULER_ACTIVATION"
                    )
                    != "1"
                ):
                    subprocess.run(
                        ["launchctl", "unload", str(plist)], check=False
                    )
                    subprocess.run(
                        ["launchctl", "load", str(plist)], check=True
                    )
            else:
                if activate and plist.exists():
                    subprocess.run(
                        ["launchctl", "unload", str(plist)], check=False
                    )
                plist.unlink(missing_ok=True)
        else:
            raise SchedulerError(
                f"automatic scheduling is not supported on {platform.system()}"
            )

        state = _read_json(self.layout.state_path, {})
        state.update(
            {
                "schema_version": UPDATE_STATE_SCHEMA,
                "auto_update": {
                    "enabled": bool(enabled),
                    "mode": mode,
                    "channel": channel,
                    "interval_hours": interval_seconds / 3600,
                    "scheduler": system,
                    "paths": installed_paths,
                    "configured_at": utc_now(),
                },
            }
        )
        _atomic_json(self.layout.state_path, state)
        return {"status": "AUTO_UPDATE_CONFIGURED", **state["auto_update"]}
''',
)

write("src/sisyfus/updater.py", updater)

cli = read("src/sisyfus/cli.py")
old = "allow_active=args.allow_active)"
new = "allow_active=args.allow_active, require_verified=args.scheduled)"
count = cli.count(old)
if count != 2:
    raise SystemExit(f"unexpected UpdateManager.apply call count: {count}")
write("src/sisyfus/cli.py", cli.replace(old, new))

INSTALLER = r'''#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${SISYFUS_REPO_URL:-https://github.com/DionisAI/sisyfus-skill}"
REPOSITORY="${SISYFUS_UPDATE_REPOSITORY:-DionisAI/sisyfus-skill}"
ENGINE_HOME="${SISYFUS_ENGINE_HOME:-${HOME}/.local/share/sisyfus}"
BIN_DIR="${SISYFUS_BIN_DIR:-${HOME}/.local/bin}"
CHANNEL="stable"
TARGET_VERSION=""
ACTION="install"
ALLOW_ACTIVE=0
ENABLE_AUTO=0
AUTO_MODE="notify"
AUTO_INTERVAL=24

say()  { printf '\033[1;32m[sisyfus]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[sisyfus]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[sisyfus]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: install.sh [options]
  --version X.Y.Z             Install one exact release
  --channel stable|beta|edge  Select update channel (default: stable)
  --check                     Check only; never install
  --allow-active              Override active-work protection
  --enable-auto               Configure scheduled checks after install
  --auto-mode notify|auto     Notify only or install stable automatically
  --interval-hours N          Scheduled interval (minimum 15 minutes)
  --uninstall                 Remove engine and installed Skill files
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version) TARGET_VERSION="${2:?missing version}"; shift 2 ;;
    --channel) CHANNEL="${2:?missing channel}"; shift 2 ;;
    --check) ACTION="check"; shift ;;
    --allow-active) ALLOW_ACTIVE=1; shift ;;
    --enable-auto) ENABLE_AUTO=1; shift ;;
    --auto-mode) AUTO_MODE="${2:?missing mode}"; shift 2 ;;
    --interval-hours) AUTO_INTERVAL="${2:?missing interval}"; shift 2 ;;
    --uninstall) ACTION="uninstall"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

case "$CHANNEL" in stable|beta|edge) ;; *) die "invalid channel: $CHANNEL" ;; esac
case "$AUTO_MODE" in notify|auto) ;; *) die "invalid auto mode: $AUTO_MODE" ;; esac
if [ "$AUTO_MODE" = auto ] && [ "$CHANNEL" != stable ]; then
  die "automatic installation is restricted to the stable channel"
fi

skill_dirs() {
  if [ -n "${SISYFUS_SKILL_DIRS:-}" ]; then
    printf '%s' "$SISYFUS_SKILL_DIRS" | tr ':' '\n'
    return
  fi
  local found=0
  for directory in "$HOME/.claude/skills" "$HOME/.agents/skills"; do
    if [ -d "$directory" ]; then
      printf '%s\n' "$directory"
      found=1
    fi
  done
  [ "$found" -eq 0 ] && printf '%s\n' "$HOME/.claude/skills"
}

if [ "$ACTION" = uninstall ]; then
  if [ -x "$BIN_DIR/sisyfus" ]; then
    "$BIN_DIR/sisyfus" update --disable-auto --yes >/dev/null 2>&1 || true
  fi
  while IFS= read -r directory; do
    rm -rf "$directory/sisyfus-research"
  done < <(skill_dirs)
  rm -rf "$ENGINE_HOME"
  rm -f "$BIN_DIR/sisyfus" "$BIN_DIR/sisyfus-autonomy"
  say "uninstalled; project .sisyfus state is untouched"
  exit 0
fi

PYTHON="$(command -v python3 || true)"
[ -n "$PYTHON" ] || die "python3 >= 3.11 is required"
"$PYTHON" - <<'PY' || die "python3 >= 3.11 is required"
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY

resolve_ref() {
  "$PYTHON" - "$CHANNEL" "$TARGET_VERSION" "$REPOSITORY" <<'PY'
import json
import re
import sys
import urllib.error
import urllib.request

channel, requested, repository = sys.argv[1:]
api = "https://api.github.com"

def get(url):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "sisyfus-installer",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))

def semver(value):
    match = re.fullmatch(
        r"v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?", value
    )
    if not match:
        return None
    prerelease = match.group(4)
    pre_key = (1,) if prerelease is None else (0, prerelease)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)), pre_key)

if requested:
    print("v" + requested.lstrip("v"))
    raise SystemExit(0)
if channel == "edge":
    print("main")
    raise SystemExit(0)

if channel == "stable":
    try:
        release = get(f"{api}/repos/{repository}/releases/latest")
        print(release["tag_name"])
        raise SystemExit(0)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    tags = get(f"{api}/repos/{repository}/tags?per_page=100")
    candidates = []
    for item in tags:
        parsed = semver(str(item.get("name") or ""))
        if parsed and parsed[3] == (1,):
            candidates.append((parsed, item["name"]))
    if not candidates:
        raise SystemExit("no stable semantic release found")
    print(max(candidates)[1])
    raise SystemExit(0)

releases = get(f"{api}/repos/{repository}/releases?per_page=100")
candidates = []
for release in releases:
    if release.get("draft"):
        continue
    parsed = semver(str(release.get("tag_name") or ""))
    if parsed:
        candidates.append((parsed, release["tag_name"]))
if not candidates:
    raise SystemExit("no semantic beta/stable release found")
print(max(candidates)[1])
PY
}

if [ "$ACTION" = check ] && [ -x "$BIN_DIR/sisyfus" ]; then
  args=(update --check --channel "$CHANNEL")
  [ -n "$TARGET_VERSION" ] && args+=(--version "$TARGET_VERSION")
  exec "$BIN_DIR/sisyfus" "${args[@]}"
fi
if [ "$ACTION" = check ]; then
  REF="$(resolve_ref)" || die "unable to resolve requested release"
  say "Sisyfus is not installed; selected release is $REF"
  exit 0
fi

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
SOURCE=""
CLEANUP=""
USE_LOCAL=0
if [ -n "$SCRIPT_SOURCE" ] && [ -f "$SCRIPT_SOURCE" ] && [ -z "$TARGET_VERSION" ]; then
  SOURCE="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
  if [ -f "$SOURCE/SKILL.md" ] && [ -d "$SOURCE/src/sisyfus" ]; then
    USE_LOCAL=1
  fi
fi

if [ "$USE_LOCAL" -eq 0 ]; then
  command -v git >/dev/null || die "git is required"
  REF="$(resolve_ref)" || die "unable to resolve requested release"
  SOURCE="$(mktemp -d "${TMPDIR:-/tmp}/sisyfus-skill.XXXXXX")"
  CLEANUP="$SOURCE"
  say "fetching $REPOSITORY@$REF"
  git clone --quiet --depth 1 --branch "$REF" "$REPO_URL" "$SOURCE" \
    || die "failed to fetch $REF"
  if [ ! -f "$SOURCE/src/sisyfus/updater.py" ]; then
    die "$REF predates the versioned updater; install v0.8.1 or newer"
  fi
else
  REF="local"
fi
trap '[ -n "$CLEANUP" ] && rm -rf "$CLEANUP"' EXIT

export SISYFUS_ENGINE_HOME="$ENGINE_HOME"
export SISYFUS_BIN_DIR="$BIN_DIR"
if [ -z "${SISYFUS_SKILL_DIRS:-}" ]; then
  directories=()
  while IFS= read -r directory; do directories+=("$directory"); done < <(skill_dirs)
  export SISYFUS_SKILL_DIRS="$(IFS=:; printf '%s' "${directories[*]}")"
fi

ALLOW="False"
[ "$ALLOW_ACTIVE" -eq 1 ] && ALLOW="True"
PYTHONPATH="$SOURCE/src" "$PYTHON" - "$SOURCE" "$CHANNEL" "$REF" "$ALLOW" <<'PY'
import json
import sys
from sisyfus.updater import bootstrap_from_source

source, channel, ref, allow = sys.argv[1:]
result = bootstrap_from_source(
    source,
    channel=channel,
    tag=ref if ref.startswith("v") else None,
    allow_active=allow == "True",
)
print(json.dumps(result, sort_keys=True))
PY

VERSION="$($BIN_DIR/sisyfus --version)"
say "engine and Skill ready: Sisyfus $VERSION"
say "restart the coding-agent session so it reloads the Skill"
if [ "$ENABLE_AUTO" -eq 1 ]; then
  "$BIN_DIR/sisyfus" update \
    --enable-auto \
    --mode "$AUTO_MODE" \
    --channel "$CHANNEL" \
    --interval-hours "$AUTO_INTERVAL" \
    --yes
fi
'''
write("install.sh", INSTALLER, 0o755)

# Update documentation to describe the one-time bootstrap from v0.8.0 and the
# stable-only automatic-install rule.
for path in ("README.md", "README.zh-CN.md"):
    text = read(path)
    if path.endswith("README.md"):
        anchor = "Sisyfus updates the **engine and installed Skill together**."
        note = (
            "Existing v0.8.0 installations need one bootstrap refresh before "
            "the `update` command exists:\n\n"
            "```bash\n"
            "curl -fsSL https://raw.githubusercontent.com/"
            "DionisAI/sisyfus-skill/main/install.sh | bash\n"
            "```\n\n"
        )
        text = text.replace(anchor, note + anchor, 1)
        text = text.replace(
            "`--mode auto` installs Stable only while all registered projects are idle.",
            "`--mode auto` is restricted to Stable and installs only while all registered projects are idle.",
        )
        text = text.replace(
            "preferring a dedicated venv, and falling back to a\n   pure-stdlib source install",
            "using a versioned pure-standard-library source release",
        )
    else:
        anchor = "Sisyfus 会把 **Engine 与已安装 Skill 一起更新**。"
        note = (
            "已经安装 v0.8.0 的用户需要先运行一次新版安装器，以获得 `update` 命令：\n\n"
            "```bash\n"
            "curl -fsSL https://raw.githubusercontent.com/"
            "DionisAI/sisyfus-skill/main/install.sh | bash\n"
            "```\n\n"
        )
        text = text.replace(anchor, note + anchor, 1)
        text = text.replace(
            "自动安装只会在所有登记项目空闲时执行；",
            "自动安装仅允许 Stable 通道，并且只会在所有登记项目空闲时执行；",
        )
        text = text.replace(
            "优先使用专用 venv;在缺少 `python3-venv`/`ensurepip`/pip 的机器上自动降级为\n   纯标准库源码安装(sisyfus 零运行时依赖,因此永远不需要 sudo);",
            "使用可回滚的版本化纯标准库源码安装(sisyfus 零运行时依赖,因此永远不需要 sudo);",
        )
    write(path, text)

notes = read("RELEASE_NOTES_v0.8.1.md")
if "Engine and Skill resolve through one `current` symlink" not in notes:
    notes += '''

## Integrity and activation details

- Engine and Skill resolve through one `current` symlink, so activation is one
  compatibility-unit switch rather than two sequential copies.
- Installed release contents carry a local SHA-256 tree hash and are verified
  before reuse or rollback.
- Scheduled automatic installation requires a SHA-256 Release Manifest and is
  restricted to the Stable channel; Beta and Edge can be monitored in Notify mode.
- Any non-terminal research run, active attempt, verifier operation,
  Continuation, Decision, or unknown commit defers activation.
'''
write("RELEASE_NOTES_v0.8.1.md", notes)

TESTS = '''from __future__ import annotations

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
'''
write("tests/test_updater_hardening.py", TESTS)
