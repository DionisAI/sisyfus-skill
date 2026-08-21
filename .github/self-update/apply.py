from __future__ import annotations

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


def replace_once(path: str, before: str, after: str) -> None:
    text = read(path)
    if after in text and before not in text:
        return
    count = text.count(before)
    if count != 1:
        raise SystemExit(
            f"unexpected replacement count in {path}: {count} for {before[:120]!r}"
        )
    write(path, text.replace(before, after, 1))

UPDATER = '''"""Versioned, atomic and rollback-safe Sisyfus updater.

The updater deliberately lives in the main CLI instead of a separate bootstrap
binary. Existing installs need one installer refresh to acquire it; afterwards
``sisyfus update`` updates the engine and the installed Skill together.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as _dt
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

try:
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore

REPOSITORY = os.environ.get("SISYFUS_UPDATE_REPOSITORY", "DionisAI/sisyfus-skill")
API_BASE = os.environ.get("SISYFUS_UPDATE_API_BASE", "https://api.github.com")
WEB_BASE = os.environ.get("SISYFUS_UPDATE_WEB_BASE", "https://github.com")
UPDATE_STATE_SCHEMA = "sisyfus.update-state.v1"
PROJECT_REGISTRY_SCHEMA = "sisyfus.project-registry.v1"
RELEASE_MANIFEST_SCHEMA = "sisyfus.release.v1"
DEFAULT_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
ACTIVE_ACTIVITY_STATUSES = {"RUNNING", "EXECUTING", "VERIFYING", "PLANNING", "RECOVERING"}
ACTIVE_CONTINUATION_STATES = {"RUNNING", "VERIFYING"}
ACTIVE_DECISION_STATES = {"RESERVED", "EXECUTED"}
TERMINAL_RESEARCH_STATUSES = {"SOLVED", "REFUTED", "FAILED", "BLOCKED", "EXHAUSTED", "BUDGET_EXHAUSTED", "CANCELLED"}

class UpdateError(RuntimeError):
    pass

class UpdateUnavailable(UpdateError):
    pass

class ActiveWorkError(UpdateError):
    def __init__(self, active: Sequence[Mapping[str, Any]]) -> None:
        self.active = [dict(item) for item in active]
        super().__init__("refusing to switch Sisyfus while active work exists: " + "; ".join(str(item.get("summary") or item) for item in self.active[:8]))

class IntegrityError(UpdateError):
    pass

class SchedulerError(UpdateError):
    pass

def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def _parse_iso(value: str | None) -> _dt.datetime | None:
    if not value:
        return None
    try:
        parsed = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)

def _atomic_text(path: Path, text: str, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)

def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str, allow_nan=False) + "\\n")

def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default

@dataclasses.dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    @classmethod
    def parse(cls, value: str) -> "SemVer":
        match = re.fullmatch(r"v?(\\d+)\\.(\\d+)\\.(\\d+)(?:-([0-9A-Za-z.-]+))?(?:\\+[0-9A-Za-z.-]+)?", str(value).strip())
        if not match:
            raise ValueError(f"invalid semantic version: {value!r}")
        pre = tuple((match.group(4) or "").split(".")) if match.group(4) else ()
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)), pre)
    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return base + (f"-{'.'.join(self.prerelease)}" if self.prerelease else "")
    def _pre_key(self) -> tuple[Any, ...]:
        if not self.prerelease:
            return (1,)
        items = []
        for item in self.prerelease:
            items.append((0, int(item)) if item.isdigit() else (1, item))
        return (0, *items)
    def sort_key(self) -> tuple[Any, ...]:
        return self.major, self.minor, self.patch, self._pre_key()
    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self.sort_key() < other.sort_key()

def normalize_version(value: str) -> str:
    return str(SemVer.parse(value))

@dataclasses.dataclass(frozen=True)
class Candidate:
    version: str
    tag: str
    channel: str
    source_url: str
    release_id: str
    commit_sha: str | None = None
    archive_sha256: str | None = None
    manifest_url: str | None = None
    verification: str = "tag_only"
    prerelease: bool = False
    published_at: str | None = None
    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

@dataclasses.dataclass(frozen=True)
class InstallLayout:
    engine_home: Path
    bin_dir: Path
    releases_dir: Path
    current_link: Path
    previous_link: Path
    state_path: Path
    project_registry_path: Path
    lock_path: Path
    skill_dirs: tuple[Path, ...]
    @classmethod
    def discover(cls) -> "InstallLayout":
        home = Path(os.environ.get("SISYFUS_ENGINE_HOME", str(Path.home()/".local"/"share"/"sisyfus"))).expanduser().resolve()
        bin_dir = Path(os.environ.get("SISYFUS_BIN_DIR", str(Path.home()/".local"/"bin"))).expanduser().resolve()
        explicit = os.environ.get("SISYFUS_SKILL_DIRS")
        if explicit:
            skill_dirs = tuple(Path(item).expanduser().resolve() for item in explicit.split(os.pathsep) if item.strip())
        else:
            candidates = [Path.home()/".claude"/"skills", Path.home()/".agents"/"skills"]
            existing = [p.resolve() for p in candidates if p.exists()]
            skill_dirs = tuple(existing or [candidates[0].resolve()])
        return cls(home, bin_dir, home/"releases", home/"current", home/"previous", home/"update-state.json", home/"projects.json", home/"update.lock", skill_dirs)
    def ensure(self) -> None:
        self.engine_home.mkdir(parents=True, exist_ok=True)
        self.releases_dir.mkdir(parents=True, exist_ok=True)
        self.bin_dir.mkdir(parents=True, exist_ok=True)

class GitHubClient:
    def __init__(self, *, token: str | None = None, timeout: float = 30.0) -> None:
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.timeout = float(timeout)
    def _request(self, url: str) -> urllib.request.Request:
        headers = {"Accept":"application/vnd.github+json", "User-Agent":"sisyfus-updater", "X-GitHub-Api-Version":"2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return urllib.request.Request(url, headers=headers)
    def json(self, url: str) -> Any:
        try:
            with urllib.request.urlopen(self._request(url), timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1000]
            raise UpdateError(f"GitHub request failed ({exc.code}) for {url}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise UpdateError(f"GitHub request failed for {url}: {exc}") from exc
    def download(self, url: str, destination: Path, *, max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES) -> str:
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(); total = 0
        try:
            with urllib.request.urlopen(self._request(url), timeout=self.timeout) as response, destination.open("wb") as output:
                while True:
                    chunk = response.read(1024*1024)
                    if not chunk: break
                    total += len(chunk)
                    if total > max_bytes:
                        raise IntegrityError(f"download exceeds {max_bytes} bytes: {url}")
                    output.write(chunk); digest.update(chunk)
        except Exception:
            destination.unlink(missing_ok=True); raise
        return digest.hexdigest()

def _release_asset(release: Mapping[str, Any], names: Iterable[str]) -> str | None:
    wanted = set(names)
    for asset in release.get("assets") or []:
        if str(asset.get("name")) in wanted:
            return str(asset.get("browser_download_url") or "") or None
    return None

def _candidate_from_release(release: Mapping[str, Any], channel: str) -> Candidate:
    tag = str(release.get("tag_name") or ""); version = normalize_version(tag)
    archive_name = f"sisyfus-{version}.tar.gz"
    manifest_url = _release_asset(release, ("release-manifest.json", f"sisyfus-{version}-manifest.json"))
    source_url = _release_asset(release, (archive_name,)) or str(release.get("tarball_url") or f"{WEB_BASE}/{REPOSITORY}/archive/refs/tags/v{version}.tar.gz")
    return Candidate(version, tag or f"v{version}", channel, source_url, version, str(release.get("target_commitish") or "") or None, None, manifest_url, "manifest_sha256" if manifest_url and archive_name in source_url else "tag_only", bool(release.get("prerelease")), str(release.get("published_at") or "") or None)

def resolve_candidate(*, channel: str = "stable", version: str | None = None, client: GitHubClient | Any | None = None) -> Candidate:
    client = client or GitHubClient(); channel = str(channel or "stable").lower()
    if channel not in {"stable","beta","edge"}: raise ValueError(f"unsupported update channel: {channel}")
    if version:
        normalized = normalize_version(version); tag = f"v{normalized}"
        try: return _candidate_from_release(client.json(f"{API_BASE}/repos/{REPOSITORY}/releases/tags/{tag}"), channel)
        except UpdateError: return Candidate(normalized, tag, channel, f"{WEB_BASE}/{REPOSITORY}/archive/refs/tags/{tag}.tar.gz", normalized, verification="tag_only", prerelease=bool(SemVer.parse(normalized).prerelease))
    if channel == "stable":
        try: return _candidate_from_release(client.json(f"{API_BASE}/repos/{REPOSITORY}/releases/latest"), channel)
        except UpdateError:
            tags = client.json(f"{API_BASE}/repos/{REPOSITORY}/tags?per_page=100"); versioned=[]
            for item in tags or []:
                name = str(item.get("name") or "")
                try: parsed = SemVer.parse(name)
                except ValueError: continue
                if parsed.prerelease: continue
                versioned.append((parsed,name,str((item.get("commit") or {}).get("sha") or "") or None))
            if not versioned: raise UpdateUnavailable("no stable Sisyfus release or semantic tag found")
            parsed, tag, sha = max(versioned, key=lambda item:item[0].sort_key())
            return Candidate(str(parsed), tag, "stable", f"{WEB_BASE}/{REPOSITORY}/archive/refs/tags/{tag}.tar.gz", str(parsed), sha, verification="tag_only")
    if channel == "beta":
        releases = client.json(f"{API_BASE}/repos/{REPOSITORY}/releases?per_page=100")
        candidates = [item for item in releases if not item.get("draft") and item.get("tag_name")]
        if not candidates: raise UpdateUnavailable("no published Sisyfus releases found")
        candidates.sort(key=lambda item:SemVer.parse(str(item["tag_name"])).sort_key(), reverse=True)
        return _candidate_from_release(candidates[0], channel)
    branch = client.json(f"{API_BASE}/repos/{REPOSITORY}/branches/main")
    sha = str((branch.get("commit") or {}).get("sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha): raise UpdateError("main branch response did not contain a commit SHA")
    from . import __version__ as base_version
    return Candidate(f"{normalize_version(base_version)}+edge.{sha[:12]}", sha, "edge", f"{WEB_BASE}/{REPOSITORY}/archive/{sha}.tar.gz", f"edge-{sha[:12]}", sha, verification="commit_sha")

def _load_manifest(candidate: Candidate, client: GitHubClient | Any) -> dict[str, Any] | None:
    if not candidate.manifest_url: return None
    manifest = client.json(candidate.manifest_url)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != RELEASE_MANIFEST_SCHEMA: raise IntegrityError("unsupported release manifest schema")
    if normalize_version(str(manifest.get("version"))) != normalize_version(candidate.version.split("+",1)[0]): raise IntegrityError("release manifest version mismatch")
    if str(manifest.get("tag")) != candidate.tag or str(manifest.get("repository") or REPOSITORY) != REPOSITORY: raise IntegrityError("release manifest identity mismatch")
    digest = str(manifest.get("archive_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest): raise IntegrityError("release manifest has no valid archive_sha256")
    return manifest

def _safe_extract(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as bundle:
        members = bundle.getmembers()
        if not members: raise IntegrityError("release archive is empty")
        top_levels=set()
        for member in members:
            pure=Path(member.name.replace("\\\\","/"))
            if pure.is_absolute() or ".." in pure.parts: raise IntegrityError(f"unsafe archive path: {member.name}")
            if member.issym() or member.islnk() or member.isdev(): raise IntegrityError(f"unsupported archive entry: {member.name}")
            if pure.parts: top_levels.add(pure.parts[0])
            target=(destination/pure).resolve()
            if destination.resolve() not in {target,*target.parents}: raise IntegrityError(f"archive path escapes destination: {member.name}")
        bundle.extractall(destination)
    if len(top_levels)==1:
        candidate=destination/next(iter(top_levels))
        if candidate.is_dir(): return candidate
    return destination

def _source_version(source: Path) -> str:
    pyproject=(source/"pyproject.toml").read_text(encoding="utf-8")
    match=re.search(r'(?m)^version\\s*=\\s*"([^"]+)"\\s*$',pyproject)
    if not match: raise IntegrityError("release pyproject.toml has no project version")
    package_init=(source/"src"/"sisyfus"/"__init__.py").read_text(encoding="utf-8")
    init_match=re.search(r'__version__\\s*=\\s*"([^"]+)"',package_init)
    if not init_match or init_match.group(1)!=match.group(1): raise IntegrityError("package version and runtime __version__ disagree")
    for required in ("SKILL.md","references","templates","src/sisyfus"):
        if not (source/required).exists(): raise IntegrityError(f"release source is missing {required}")
    return match.group(1)

def _process_alive(pid: Any) -> bool:
    try:
        numeric=int(pid)
        if numeric<=0:return False
        os.kill(numeric,0);return True
    except (TypeError,ValueError,OSError):return False

@contextlib.contextmanager
def update_lock(layout: InstallLayout) -> Iterator[None]:
    layout.ensure()
    with layout.lock_path.open("a+b") as handle:
        if fcntl is not None: fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try: yield
        finally:
            if fcntl is not None: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

def register_project(root: str | Path, *, layout: InstallLayout | None = None) -> None:
    layout=layout or InstallLayout.discover(); layout.ensure(); canonical=str(Path(root).expanduser().resolve())
    with update_lock(layout):
        data=_read_json(layout.project_registry_path,{"schema_version":PROJECT_REGISTRY_SCHEMA,"projects":[]})
        projects={str(item.get("path")):dict(item) for item in data.get("projects") or [] if isinstance(item,dict) and item.get("path")}
        projects[canonical]={"path":canonical,"last_seen_at":utc_now()}
        _atomic_json(layout.project_registry_path,{"schema_version":PROJECT_REGISTRY_SCHEMA,"projects":sorted(projects.values(),key=lambda item:item["path"])})

def _registered_projects(layout: InstallLayout) -> list[Path]:
    data=_read_json(layout.project_registry_path,{})
    roots={Path(item["path"]).expanduser().resolve() for item in data.get("projects") or [] if isinstance(item,dict) and item.get("path")}
    cwd=Path.cwd().resolve()
    for candidate in [cwd,*cwd.parents]:
        if (candidate/".sisyfus").exists(): roots.add(candidate); break
    return sorted(path for path in roots if path.exists())

def _active_activity(root: Path) -> dict[str, Any] | None:
    activity=_read_json(root/".sisyfus"/"live"/"activity.json",{}); status=str(activity.get("status") or "").upper()
    if status not in ACTIVE_ACTIVITY_STATUSES:return None
    heartbeat=_parse_iso(str(activity.get("heartbeat_at") or "")); recent=bool(heartbeat and (_dt.datetime.now(_dt.timezone.utc)-heartbeat).total_seconds()<180)
    if not recent and not _process_alive(activity.get("pid")):return None
    return {"kind":"activity","project":str(root),"status":status,"operation":activity.get("operation"),"summary":f"{root}: live activity {status} ({activity.get('operation') or 'unknown'})"}

def _active_autonomy(root: Path) -> list[dict[str, Any]]:
    database=root/".sisyfus"/"autonomy.sqlite3"
    if not database.exists():return []
    active=[]; connection=None
    try:
        connection=sqlite3.connect(f"file:{database}?mode=ro",uri=True,timeout=1.0); connection.row_factory=sqlite3.Row
        tables={str(row["name"]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "continuations" in tables:
            ph=",".join("?" for _ in ACTIVE_CONTINUATION_STATES)
            for row in connection.execute(f"SELECT id,state FROM continuations WHERE state IN ({ph})",tuple(sorted(ACTIVE_CONTINUATION_STATES))).fetchall(): active.append({"kind":"continuation","project":str(root),"id":row["id"],"status":row["state"],"summary":f"{root}: continuation {row['id']} is {row['state']}"})
        if "decisions" in tables:
            ph=",".join("?" for _ in ACTIVE_DECISION_STATES)
            for row in connection.execute(f"SELECT id,status,recovery_required FROM decisions WHERE status IN ({ph}) OR recovery_required=1",tuple(sorted(ACTIVE_DECISION_STATES))).fetchall(): active.append({"kind":"decision","project":str(root),"id":row["id"],"status":row["status"],"summary":f"{root}: decision {row['id']} is {row['status']}"})
    except sqlite3.Error:return []
    finally:
        if connection is not None: connection.close()
    return active

def _active_research(root: Path) -> list[dict[str, Any]]:
    runs=root/".sisyfus"/"research"/"runs"
    if not runs.exists():return []
    active=[]
    for snapshot_path in runs.glob("*/snapshot.json"):
        snapshot=_read_json(snapshot_path,{})
        if str(snapshot.get("run_status") or "") in TERMINAL_RESEARCH_STATUSES:continue
        attempts=snapshot.get("attempts") or {}
        for attempt in attempts.values() if isinstance(attempts,dict) else []:
            status=str((attempt or {}).get("status") or "").upper()
            if status in {"RESERVED","RUNNING"}:active.append({"kind":"research_attempt","project":str(root),"id":(attempt or {}).get("id"),"status":status,"summary":f"{root}: research attempt {(attempt or {}).get('id')} is {status}"})
    return active

def active_work(layout: InstallLayout | None = None) -> list[dict[str, Any]]:
    layout=layout or InstallLayout.discover(); active=[]
    for root in _registered_projects(layout):
        item=_active_activity(root)
        if item:active.append(item)
        active.extend(_active_autonomy(root)); active.extend(_active_research(root))
    return list({json.dumps(item,sort_keys=True,default=str):item for item in active}.values())

def _symlink_target(link: Path) -> Path | None:
    if not link.is_symlink():return None
    target=Path(os.readlink(link)); return ((link.parent/target) if not target.is_absolute() else target).resolve()

def _atomic_symlink(target: Path, link: Path) -> None:
    link.parent.mkdir(parents=True,exist_ok=True); temporary=link.with_name(f".{link.name}.{os.getpid()}.{time.time_ns()}")
    os.symlink(os.path.relpath(target,start=link.parent),temporary); os.replace(temporary,link)

def _copy_skill(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True,exist_ok=True); temporary=destination.with_name(f".{destination.name}.{os.getpid()}.{time.time_ns()}")
    shutil.rmtree(temporary,ignore_errors=True); temporary.mkdir(parents=True)
    shutil.copy2(source/"SKILL.md",temporary/"SKILL.md"); shutil.copytree(source/"references",temporary/"references"); shutil.copytree(source/"templates",temporary/"templates")
    if destination.exists() or destination.is_symlink():
        backup=destination.with_name(f".{destination.name}.old.{time.time_ns()}"); os.replace(destination,backup); os.replace(temporary,destination); shutil.rmtree(backup,ignore_errors=True)
    else: os.replace(temporary,destination)

def _write_launcher(path: Path, package_dir: Path, module: str) -> None:
    _atomic_text(path,"#!/usr/bin/env python3\\nimport sys\\n"+f"sys.path.insert(0, {str(package_dir)!r})\\nfrom {module} import main\\nraise SystemExit(main())\\n",mode=0o755)

def _install_stdlib(source: Path, release_dir: Path) -> None:
    lib=release_dir/"lib"; bin_dir=release_dir/"bin"; shutil.rmtree(lib,ignore_errors=True); shutil.copytree(source/"src"/"sisyfus",lib/"sisyfus"); bin_dir.mkdir(parents=True,exist_ok=True)
    _write_launcher(bin_dir/"sisyfus",lib,"sisyfus.cli"); _write_launcher(bin_dir/"sisyfus-autonomy",lib,"sisyfus.autonomy.cli")

def _install_venv(source: Path, release_dir: Path) -> None:
    venv=release_dir/"venv"; subprocess.run([sys.executable,"-m","venv",str(venv)],check=True)
    python=venv/("Scripts/python.exe" if os.name=="nt" else "bin/python")
    subprocess.run([str(python),"-m","pip","install","--quiet","--no-deps","--no-build-isolation","--force-reinstall",str(source)],check=True)
    scripts=venv/("Scripts" if os.name=="nt" else "bin"); bin_dir=release_dir/"bin"; bin_dir.mkdir(parents=True,exist_ok=True)
    for name in ("sisyfus","sisyfus-autonomy"):
        target=scripts/(f"{name}.exe" if os.name=="nt" else name)
        if not target.exists():raise UpdateError(f"installed release did not create {target}")
        _atomic_symlink(target,bin_dir/name)

def _smoke_release(release_dir: Path, expected_version: str) -> None:
    executable=release_dir/"bin"/"sisyfus"; autonomy=release_dir/"bin"/"sisyfus-autonomy"
    completed=subprocess.run([str(executable),"--version"],check=True,text=True,capture_output=True,timeout=30)
    if completed.stdout.strip()!=expected_version:raise IntegrityError(f"staged CLI reports {completed.stdout.strip()!r}, expected {expected_version!r}")
    subprocess.run([str(executable),"--help"],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
    subprocess.run([str(autonomy),"--help"],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)

def _release_manifest(release_dir: Path | None) -> dict[str, Any]:
    if release_dir is None:return {}
    manifest=_read_json(release_dir/"install-manifest.json",{}); return manifest if isinstance(manifest,dict) else {}

def _build_release(source: Path,candidate: Candidate,layout: InstallLayout,*,archive_sha256: str | None,remote_manifest: Mapping[str,Any] | None) -> Path:
    release_dir=layout.releases_dir/candidate.release_id; existing=_release_manifest(release_dir); expected_version=_source_version(source)
    if existing.get("complete") and existing.get("version")==expected_version:return release_dir
    shutil.rmtree(release_dir,ignore_errors=True); release_dir.mkdir(parents=True); method="stdlib"
    if os.environ.get("SISYFUS_UPDATE_FORCE_STDLIB")!="1":
        try:_install_venv(source,release_dir);method="venv"
        except Exception:shutil.rmtree(release_dir,ignore_errors=True);release_dir.mkdir(parents=True);_install_stdlib(source,release_dir)
    else:_install_stdlib(source,release_dir)
    _copy_skill(source,release_dir/"skill"/"sisyfus-research");_smoke_release(release_dir,expected_version)
    _atomic_json(release_dir/"install-manifest.json",{"schema_version":"sisyfus.install.v1","complete":True,"version":expected_version,"display_version":candidate.version,"tag":candidate.tag,"channel":candidate.channel,"release_id":candidate.release_id,"source_url":candidate.source_url,"source_commit":candidate.commit_sha,"archive_sha256":archive_sha256,"verification":candidate.verification,"install_method":method,"installed_at":utc_now(),"remote_manifest":dict(remote_manifest or {})})
    return release_dir

def _activate_release(release_dir: Path,layout: InstallLayout,*,candidate: Candidate | None=None,preserve_previous: bool=True) -> dict[str,Any]:
    manifest=_release_manifest(release_dir)
    if not manifest.get("complete"):raise IntegrityError(f"release is incomplete: {release_dir}")
    old_current=_symlink_target(layout.current_link)
    if preserve_previous and old_current and old_current!=release_dir:_atomic_symlink(old_current,layout.previous_link)
    _atomic_symlink(release_dir,layout.current_link)
    for command in ("sisyfus","sisyfus-autonomy"):_atomic_symlink(layout.current_link/"bin"/command,layout.bin_dir/command)
    skill_source=release_dir/"skill"/"sisyfus-research"
    for root in layout.skill_dirs:root.mkdir(parents=True,exist_ok=True);_copy_skill(skill_source,root/"sisyfus-research")
    state=_read_json(layout.state_path,{})
    state.update({"schema_version":UPDATE_STATE_SCHEMA,"current_release":str(release_dir),"current_version":manifest.get("version"),"display_version":manifest.get("display_version"),"previous_release":str(_symlink_target(layout.previous_link)) if _symlink_target(layout.previous_link) else None,"channel":candidate.channel if candidate else manifest.get("channel") or state.get("channel") or "stable","activated_at":utc_now(),"last_result":"updated" if candidate else "activated","restart_agent_session":True})
    _atomic_json(layout.state_path,state);return state

def bootstrap_from_source(source: str | Path,*,channel: str="stable",tag: str | None=None,layout: InstallLayout | None=None,allow_active: bool=False) -> dict[str,Any]:
    layout=layout or InstallLayout.discover();layout.ensure();source_path=Path(source).expanduser().resolve();version=_source_version(source_path)
    candidate=Candidate(version,tag or f"v{version}",channel,str(source_path),version if channel!="edge" else f"edge-local-{version}",verification="local_source")
    with update_lock(layout):
        if not allow_active:
            active=active_work(layout)
            if active:raise ActiveWorkError(active)
        release_dir=_build_release(source_path,candidate,layout,archive_sha256=None,remote_manifest=None);state=_activate_release(release_dir,layout,candidate=candidate)
    return {"status":"UPDATED","version":version,"release":str(release_dir),"state":state}

class UpdateManager:
    def __init__(self,*,layout: InstallLayout | None=None,client: GitHubClient | Any | None=None,installed_version: str | None=None) -> None:
        self.layout=layout or InstallLayout.discover();self.client=client or GitHubClient()
        if installed_version is None:
            from . import __version__; installed_version=__version__
        self.installed_version=str(installed_version);self.layout.ensure()
    def status(self) -> dict[str,Any]:
        state=_read_json(self.layout.state_path,{});current=_symlink_target(self.layout.current_link);previous=_symlink_target(self.layout.previous_link)
        return {"schema_version":UPDATE_STATE_SCHEMA,"installed_version":self.installed_version,"current_release":str(current) if current else None,"current_manifest":_release_manifest(current),"previous_release":str(previous) if previous else None,"previous_manifest":_release_manifest(previous),"channel":state.get("channel") or "stable","last_check_at":state.get("last_check_at"),"latest_version":state.get("latest_version"),"update_available":state.get("update_available"),"auto_update":state.get("auto_update") or {"enabled":False},"active_work":active_work(self.layout)}
    def check(self,*,channel: str="stable",version: str | None=None) -> dict[str,Any]:
        candidate=resolve_candidate(channel=channel,version=version,client=self.client)
        if candidate.channel=="edge":available=(self.status().get("current_manifest") or {}).get("source_commit")!=candidate.commit_sha
        else:
            available=SemVer.parse(self.installed_version)<SemVer.parse(candidate.version)
            if version and normalize_version(self.installed_version)!=normalize_version(candidate.version):available=True
        state=_read_json(self.layout.state_path,{});state.update({"schema_version":UPDATE_STATE_SCHEMA,"last_check_at":utc_now(),"channel":channel,"latest_version":candidate.version,"latest_candidate":candidate.as_dict(),"update_available":bool(available),"last_result":"update_available" if available else "up_to_date"});_atomic_json(self.layout.state_path,state)
        return {"status":"UPDATE_AVAILABLE" if available else "UP_TO_DATE","installed_version":self.installed_version,"candidate":candidate.as_dict(),"update_available":bool(available)}
    def apply(self,*,channel: str="stable",version: str | None=None,force: bool=False,allow_active: bool=False) -> dict[str,Any]:
        candidate=resolve_candidate(channel=channel,version=version,client=self.client);check=self.check(channel=channel,version=version)
        if not force and not check["update_available"]:return check
        with update_lock(self.layout):
            if not allow_active:
                active=active_work(self.layout)
                if active:
                    state=_read_json(self.layout.state_path,{});state.update({"schema_version":UPDATE_STATE_SCHEMA,"last_result":"deferred_active_work","deferred_at":utc_now(),"active_work":active});_atomic_json(self.layout.state_path,state);raise ActiveWorkError(active)
            with tempfile.TemporaryDirectory(prefix="sisyfus-update-",dir=self.layout.engine_home) as temporary:
                temporary_path=Path(temporary);archive=temporary_path/"release.tar.gz";remote_manifest=_load_manifest(candidate,self.client);expected_hash=str(remote_manifest.get("archive_sha256")) if remote_manifest else candidate.archive_sha256;actual_hash=self.client.download(candidate.source_url,archive)
                if expected_hash and actual_hash!=expected_hash:raise IntegrityError(f"archive SHA-256 mismatch: expected {expected_hash}, got {actual_hash}")
                extracted=_safe_extract(archive,temporary_path/"source");source_version=_source_version(extracted);expected_version=candidate.version.split("+",1)[0]
                if normalize_version(source_version)!=normalize_version(expected_version):raise IntegrityError(f"archive version {source_version} does not match {expected_version}")
                release_dir=_build_release(extracted,candidate,self.layout,archive_sha256=actual_hash,remote_manifest=remote_manifest)
            state=_activate_release(release_dir,self.layout,candidate=candidate)
        return {"status":"UPDATED","from_version":self.installed_version,"to_version":candidate.version,"release":str(release_dir),"verification":"manifest_sha256" if expected_hash else candidate.verification,"restart_agent_session":True,"state":state}
    def rollback(self,*,allow_active: bool=False) -> dict[str,Any]:
        with update_lock(self.layout):
            if not allow_active:
                active=active_work(self.layout)
                if active:raise ActiveWorkError(active)
            current=_symlink_target(self.layout.current_link);previous=_symlink_target(self.layout.previous_link)
            if previous is None or not previous.exists():raise UpdateUnavailable("no previous versioned release is available")
            _smoke_release(previous,str(_release_manifest(previous).get("version")));_activate_release(previous,self.layout,candidate=None,preserve_previous=False)
            if current and current.exists():_atomic_symlink(current,self.layout.previous_link)
            state=_read_json(self.layout.state_path,{});state.update({"last_result":"rolled_back","rolled_back_at":utc_now(),"previous_release":str(current) if current else None});_atomic_json(self.layout.state_path,state)
        return {"status":"ROLLED_BACK","current_version":_release_manifest(previous).get("version"),"current_release":str(previous),"previous_release":str(current) if current else None,"restart_agent_session":True}
    def configure_auto(self,*,enabled: bool,mode: str="notify",channel: str="stable",interval_hours: float=24.0,activate: bool=True) -> dict[str,Any]:
        if mode not in {"notify","auto"}:raise ValueError("auto-update mode must be notify or auto")
        if channel not in {"stable","beta","edge"}:raise ValueError("auto-update channel must be stable, beta, or edge")
        interval_seconds=max(900,int(float(interval_hours)*3600));system=platform.system().lower();command=self.layout.bin_dir/"sisyfus";log_dir=self.layout.engine_home/"logs";log_dir.mkdir(parents=True,exist_ok=True);installed_paths=[]
        if system=="linux":
            user_config=Path(os.environ.get("XDG_CONFIG_HOME",str(Path.home()/".config"))).expanduser()/"systemd"/"user";service=user_config/"sisyfus-update.service";timer=user_config/"sisyfus-update.timer"
            if enabled:
                args=[str(command),"update","--check","--scheduled","--json"] if mode=="notify" else [str(command),"update","--yes","--scheduled","--channel",channel,"--json"]
                _atomic_text(service,"[Unit]\\nDescription=Check or apply Sisyfus updates\\n\\n[Service]\\nType=oneshot\\n"+f"ExecStart={shlex.join(args)}\\nStandardOutput=append:{log_dir/'update.log'}\\nStandardError=append:{log_dir/'update.log'}\\n")
                _atomic_text(timer,"[Unit]\\nDescription=Periodic Sisyfus update check\\n\\n[Timer]\\nOnBootSec=5m\\n"+f"OnUnitActiveSec={interval_seconds}s\\nRandomizedDelaySec=30m\\nPersistent=true\\n\\n[Install]\\nWantedBy=timers.target\\n");installed_paths=[str(service),str(timer)]
                if activate and os.environ.get("SISYFUS_UPDATE_SKIP_SCHEDULER_ACTIVATION")!="1":subprocess.run(["systemctl","--user","daemon-reload"],check=True);subprocess.run(["systemctl","--user","enable","--now",timer.name],check=True)
            else:
                if activate and shutil.which("systemctl"):subprocess.run(["systemctl","--user","disable","--now",timer.name],check=False);subprocess.run(["systemctl","--user","daemon-reload"],check=False)
                service.unlink(missing_ok=True);timer.unlink(missing_ok=True)
        elif system=="darwin":
            import plistlib
            plist=Path.home()/"Library"/"LaunchAgents"/"ai.dionis.sisyfus-update.plist"
            if enabled:
                args=[str(command),"update","--check","--scheduled","--json"] if mode=="notify" else [str(command),"update","--yes","--scheduled","--channel",channel,"--json"]
                plist.parent.mkdir(parents=True,exist_ok=True);payload={"Label":"ai.dionis.sisyfus-update","ProgramArguments":args,"StartInterval":interval_seconds,"RunAtLoad":True,"StandardOutPath":str(log_dir/"update.log"),"StandardErrorPath":str(log_dir/"update.log")};temporary=plist.with_name(f".{plist.name}.{os.getpid()}")
                with temporary.open("wb") as handle:plistlib.dump(payload,handle)
                os.replace(temporary,plist);installed_paths=[str(plist)]
                if activate and os.environ.get("SISYFUS_UPDATE_SKIP_SCHEDULER_ACTIVATION")!="1":subprocess.run(["launchctl","unload",str(plist)],check=False);subprocess.run(["launchctl","load",str(plist)],check=True)
            else:
                if activate and plist.exists():subprocess.run(["launchctl","unload",str(plist)],check=False)
                plist.unlink(missing_ok=True)
        else:raise SchedulerError(f"automatic scheduling is not supported on {platform.system()}")
        state=_read_json(self.layout.state_path,{});state.update({"schema_version":UPDATE_STATE_SCHEMA,"auto_update":{"enabled":bool(enabled),"mode":mode,"channel":channel,"interval_hours":interval_seconds/3600,"scheduler":system,"paths":installed_paths,"configured_at":utc_now()}});_atomic_json(self.layout.state_path,state)
        return {"status":"AUTO_UPDATE_CONFIGURED",**state["auto_update"]}

def format_result(result: Mapping[str,Any]) -> str:
    status=str(result.get("status") or "UNKNOWN")
    if status=="UPDATE_AVAILABLE":
        candidate=result.get("candidate") or {};return f"Sisyfus update available: {result.get('installed_version')} -> {candidate.get('version')} ({candidate.get('channel')})"
    if status=="UP_TO_DATE":return f"Sisyfus {result.get('installed_version')} is up to date."
    if status=="UPDATED":return f"Sisyfus updated to {result.get('to_version') or result.get('version')}. Restart the coding-agent session so it reloads the installed Skill."
    if status=="ROLLED_BACK":return f"Sisyfus rolled back to {result.get('current_version')}. Restart the coding-agent session."
    if status=="AUTO_UPDATE_CONFIGURED":return "Sisyfus automatic update schedule "+("enabled" if result.get("enabled") else "disabled")+"."
    return json.dumps(dict(result),sort_keys=True,default=str)
'''
INSTALLER = '''#!/usr/bin/env bash
set -euo pipefail
REPO_URL="https://github.com/DionisAI/sisyfus-skill"
REPOSITORY="DionisAI/sisyfus-skill"
SKILL_NAME="sisyfus-research"
ENGINE_HOME="${SISYFUS_ENGINE_HOME:-${HOME}/.local/share/sisyfus}"
BIN_DIR="${SISYFUS_BIN_DIR:-${HOME}/.local/bin}"
CHANNEL="stable"; TARGET_VERSION=""; ACTION="install"; ALLOW_ACTIVE=0; ENABLE_AUTO=0; AUTO_MODE="notify"; AUTO_INTERVAL=24
say(){ printf '\033[1;32m[sisyfus]\033[0m %s\n' "$*"; }
warn(){ printf '\033[1;33m[sisyfus]\033[0m %s\n' "$*" >&2; }
die(){ printf '\033[1;31m[sisyfus]\033[0m %s\n' "$*" >&2; exit 1; }
usage(){ cat <<'EOF'
Usage: install.sh [options]
  --version X.Y.Z
  --channel stable|beta|edge
  --check
  --allow-active
  --enable-auto
  --auto-mode notify|auto
  --interval-hours N
  --uninstall
EOF
}
while [ "$#" -gt 0 ]; do case "$1" in --version) TARGET_VERSION="${2:?}";shift 2;;--channel) CHANNEL="${2:?}";shift 2;;--check)ACTION="check";shift;;--allow-active)ALLOW_ACTIVE=1;shift;;--enable-auto)ENABLE_AUTO=1;shift;;--auto-mode)AUTO_MODE="${2:?}";shift 2;;--interval-hours)AUTO_INTERVAL="${2:?}";shift 2;;--uninstall)ACTION="uninstall";shift;;-h|--help)usage;exit 0;;*)die "unknown option: $1";;esac;done
case "$CHANNEL" in stable|beta|edge);;*)die "invalid channel";;esac
skill_dirs(){ if [ -n "${SISYFUS_SKILL_DIRS:-}" ];then printf '%s' "$SISYFUS_SKILL_DIRS"|tr ':' '\n';return;fi;local found=0;for dir in "$HOME/.claude/skills" "$HOME/.agents/skills";do if [ -d "$dir" ];then printf '%s\n' "$dir";found=1;fi;done;[ "$found" -eq 0 ]&&printf '%s\n' "$HOME/.claude/skills"; }
if [ "$ACTION" = uninstall ];then if [ -x "$BIN_DIR/sisyfus" ];then "$BIN_DIR/sisyfus" update --disable-auto --yes >/dev/null 2>&1||true;fi;while IFS= read -r dir;do rm -rf "$dir/$SKILL_NAME";done < <(skill_dirs);rm -rf "$ENGINE_HOME";rm -f "$BIN_DIR/sisyfus" "$BIN_DIR/sisyfus-autonomy";say "uninstalled; project state untouched";exit 0;fi
if [ "$ACTION" = check ]&&[ -x "$BIN_DIR/sisyfus" ];then args=(update --check --channel "$CHANNEL");[ -n "$TARGET_VERSION" ]&&args+=(--version "$TARGET_VERSION");exec "$BIN_DIR/sisyfus" "${args[@]}";fi
PY="$(command -v python3||true)";[ -n "$PY" ]||die "python3 >=3.11 required";"$PY" - <<'PY'||die "python3 >=3.11 required"
import sys;raise SystemExit(0 if sys.version_info>=(3,11) else 1)
PY
resolve_ref(){ "$PY" - "$CHANNEL" "$TARGET_VERSION" <<'PY'
import json,re,sys,urllib.request
repo="DionisAI/sisyfus-skill";channel,version=sys.argv[1:]
def get(url):
 r=urllib.request.Request(url,headers={"Accept":"application/vnd.github+json","User-Agent":"sisyfus-installer"});return json.loads(urllib.request.urlopen(r,timeout=20).read())
if version:print("v"+version.lstrip("v"));raise SystemExit
if channel=="edge":print("main");raise SystemExit
try:
 release=get(f"https://api.github.com/repos/{repo}/releases/latest") if channel=="stable" else max([x for x in get(f"https://api.github.com/repos/{repo}/releases?per_page=100") if not x.get("draft")],key=lambda x:x.get("published_at") or "")
 print(release["tag_name"])
except Exception:
 try:
  tags=get(f"https://api.github.com/repos/{repo}/tags?per_page=100");versions=[]
  for item in tags:
   m=re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:-(.*))?$",item.get("name",""))
   if m and not m.group(4):versions.append((tuple(map(int,m.groups()[:3])),item["name"]))
  print(max(versions)[1] if versions else "main")
 except Exception:print("main")
PY
}
SRC="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" 2>/dev/null&&pwd)";CLEANUP="";USE_LOCAL=0
if [ -f "$SRC/SKILL.md" ]&&[ -d "$SRC/src/sisyfus" ]&&[ -z "$TARGET_VERSION" ];then USE_LOCAL=1;fi
if [ "$USE_LOCAL" -eq 0 ];then command -v git >/dev/null||die "git required";REF="$(resolve_ref)";SRC="$(mktemp -d ${TMPDIR:-/tmp}/sisyfus-skill.XXXXXX)";CLEANUP="$SRC";say "fetching $REPOSITORY@$REF";git clone --quiet --depth 1 --branch "$REF" "$REPO_URL" "$SRC"||die "fetch failed";if [ ! -f "$SRC/src/sisyfus/updater.py" ];then warn "$REF predates updater; bootstrapping main";rm -rf "$SRC";SRC="$(mktemp -d ${TMPDIR:-/tmp}/sisyfus-skill.XXXXXX)";CLEANUP="$SRC";git clone --quiet --depth 1 --branch main "$REPO_URL" "$SRC";REF=main;fi;else REF=local;fi
trap '[ -n "$CLEANUP" ]&&rm -rf "$CLEANUP"' EXIT
export SISYFUS_ENGINE_HOME="$ENGINE_HOME" SISYFUS_BIN_DIR="$BIN_DIR";if [ -z "${SISYFUS_SKILL_DIRS:-}" ];then dirs=();while IFS= read -r dir;do dirs+=("$dir");done < <(skill_dirs);export SISYFUS_SKILL_DIRS="$(IFS=:;echo "${dirs[*]}")";fi
ALLOW=False;[ "$ALLOW_ACTIVE" -eq 1 ]&&ALLOW=True
PYTHONPATH="$SRC/src" "$PY" - "$SRC" "$CHANNEL" "$REF" "$ALLOW" <<'PY'
import json,sys
from sisyfus.updater import bootstrap_from_source
source,channel,ref,allow=sys.argv[1:];print(json.dumps(bootstrap_from_source(source,channel=channel,tag=ref if ref.startswith("v") else None,allow_active=allow=="True"),sort_keys=True))
PY
VERSION="$("$BIN_DIR/sisyfus" --version)";say "engine ready: sisyfus $VERSION";say "restart coding-agent session"
if [ "$ENABLE_AUTO" -eq 1 ];then "$BIN_DIR/sisyfus" update --enable-auto --mode "$AUTO_MODE" --channel "$CHANNEL" --interval-hours "$AUTO_INTERVAL" --yes;fi
'''
RELEASE_BUILDER = '''#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,os,re,subprocess
from pathlib import Path
def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument("--output",default="dist");p.add_argument("--repository",default="DionisAI/sisyfus-skill");a=p.parse_args(argv);root=Path(__file__).resolve().parents[1];text=(root/"pyproject.toml").read_text();version=re.search(r'(?m)^version\s*=\s*"([^"]+)"',text).group(1);tag=f"v{version}";ref=os.environ.get("GITHUB_REF_NAME") or tag
 if ref!=tag:raise SystemExit(f"tag {ref} != {tag}")
 commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip();out=(root/a.output).resolve();out.mkdir(parents=True,exist_ok=True);archive=out/f"sisyfus-{version}.tar.gz";subprocess.run(["git","archive","--format=tar.gz",f"--prefix=sisyfus-{version}/","-o",str(archive),"HEAD"],cwd=root,check=True);digest=hashlib.sha256(archive.read_bytes()).hexdigest();manifest={"schema_version":"sisyfus.release.v1","repository":a.repository,"version":version,"tag":tag,"commit_sha":commit,"archive_name":archive.name,"archive_sha256":digest,"minimum_python":"3.11","autonomy_schema_version":2,"breaking":False};(out/"release-manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n");(out/f"{archive.name}.sha256").write_text(f"{digest}  {archive.name}\n");print(json.dumps(manifest,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
'''
RELEASE_WORKFLOW = '''name: Publish Sisyfus release
on:
  push:
    tags: ['v*']
permissions:
  contents: write
jobs:
  validate:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.11','3.12','3.13']
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 0}
      - uses: actions/setup-python@v5
        with: {python-version: '${{ matrix.python-version }}', cache: pip}
      - run: python -m pip install --upgrade pip pytest && python -m pip install -e .
      - env: {SISYFUS_AUTO_SERVE: '0', SISYFUS_AUTO_OPEN: '0'}
        run: test "v$(sisyfus --version)" = "$GITHUB_REF_NAME" && python -m compileall -q src tests && python -m pytest -q
  publish:
    needs: validate
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 0}
      - uses: actions/setup-python@v5
        with: {python-version: '3.12'}
      - run: python scripts/build_release_assets.py --output dist
      - uses: softprops/action-gh-release@v2
        with:
          body_path: RELEASE_NOTES_v0.8.1.md
          files: |
            dist/sisyfus-*.tar.gz
            dist/sisyfus-*.tar.gz.sha256
            dist/release-manifest.json
'''
TEST_UPDATER = '''from __future__ import annotations
import hashlib,io,json,os,tarfile
from pathlib import Path
import pytest
from sisyfus import __version__
from sisyfus.updater import *
ROOT=Path(__file__).resolve().parents[1]
def layout(t):return InstallLayout(t/"engine",t/"bin",t/"engine"/"releases",t/"engine"/"current",t/"engine"/"previous",t/"engine"/"update-state.json",t/"engine"/"projects.json",t/"engine"/"update.lock",(t/"skills",))
class FakeClient:
 def __init__(self,responses,archive=None):self.responses=responses;self.archive=archive
 def json(self,url):
  v=self.responses[url]
  if isinstance(v,Exception):raise v
  return v
 def download(self,url,destination,**kwargs):destination.write_bytes(self.archive);return hashlib.sha256(self.archive).hexdigest()
def release(v):return {"tag_name":f"v{v}","tarball_url":f"https://x/{v}.tgz","target_commitish":"a"*40,"prerelease":False,"draft":False,"assets":[{"name":f"sisyfus-{v}.tar.gz","browser_download_url":f"https://x/sisyfus-{v}.tar.gz"},{"name":"release-manifest.json","browser_download_url":"https://x/release-manifest.json"}]}
def archive():
 b=io.BytesIO()
 with tarfile.open(fileobj=b,mode="w:gz") as t:
  for r in ("pyproject.toml","SKILL.md","references","templates","src/sisyfus"):t.add(ROOT/r,arcname=f"sisyfus-{__version__}/{r}",recursive=True)
 return b.getvalue()
def test_semver():assert SemVer.parse("0.8.1-rc.1")<SemVer.parse("0.8.1")
def test_resolve_assets():
 c=resolve_candidate(client=FakeClient({f"{API_BASE}/repos/DionisAI/sisyfus-skill/releases/latest":release("0.8.1")}));assert c.verification=="manifest_sha256"
def test_safe_extract(tmp_path):
 a=tmp_path/"bad.tgz"
 with tarfile.open(a,"w:gz") as t:
  i=tarfile.TarInfo("../x");i.size=1;t.addfile(i,io.BytesIO(b"x"))
 with pytest.raises(IntegrityError):_safe_extract(a,tmp_path/"out")
def test_bootstrap(tmp_path,monkeypatch):
 monkeypatch.setenv("SISYFUS_UPDATE_FORCE_STDLIB","1");r=bootstrap_from_source(ROOT,layout=layout(tmp_path),allow_active=True);assert r["status"]=="UPDATED";assert (tmp_path/"skills"/"sisyfus-research"/"SKILL.md").exists()
def test_rollback(tmp_path,monkeypatch):
 monkeypatch.setenv("SISYFUS_UPDATE_FORCE_STDLIB","1");l=layout(tmp_path);l.ensure();a=_build_release(ROOT,Candidate(__version__,"a","edge",str(ROOT),"a"),l,archive_sha256=None,remote_manifest=None);b=_build_release(ROOT,Candidate(__version__,"b","edge",str(ROOT),"b"),l,archive_sha256=None,remote_manifest=None);_activate_release(a,l);_activate_release(b,l);assert UpdateManager(layout=l,client=FakeClient({}),installed_version=__version__).rollback(allow_active=True)["status"]=="ROLLED_BACK";assert l.current_link.resolve()==a
def test_active_blocks(tmp_path,monkeypatch):
 monkeypatch.setenv("SISYFUS_UPDATE_FORCE_STDLIB","1");l=layout(tmp_path);p=tmp_path/"p";d=p/".sisyfus"/"live";d.mkdir(parents=True);(d/"activity.json").write_text(json.dumps({"status":"RUNNING","heartbeat_at":"2999-01-01T00:00:00Z","pid":os.getpid()}));register_project(p,layout=l)
 with pytest.raises(ActiveWorkError):bootstrap_from_source(ROOT,layout=l)
def test_verified_apply(tmp_path,monkeypatch):
 monkeypatch.setenv("SISYFUS_UPDATE_FORCE_STDLIB","1");data=archive();digest=hashlib.sha256(data).hexdigest();rel=release(__version__);responses={f"{API_BASE}/repos/DionisAI/sisyfus-skill/releases/latest":rel,"https://x/release-manifest.json":{"schema_version":RELEASE_MANIFEST_SCHEMA,"repository":"DionisAI/sisyfus-skill","version":__version__,"tag":f"v{__version__}","archive_sha256":digest}};m=UpdateManager(layout=layout(tmp_path),client=FakeClient(responses,data),installed_version="0.8.0");assert m.apply(allow_active=True)["verification"]=="manifest_sha256"
def test_scheduler(tmp_path,monkeypatch):
 l=layout(tmp_path);monkeypatch.setattr("sisyfus.updater.platform.system",lambda:"Linux");monkeypatch.setenv("XDG_CONFIG_HOME",str(tmp_path/"cfg"));monkeypatch.setenv("SISYFUS_UPDATE_SKIP_SCHEDULER_ACTIVATION","1");r=UpdateManager(layout=l,client=FakeClient({}),installed_version=__version__).configure_auto(enabled=True,interval_hours=6);assert r["enabled"];assert "21600s" in (tmp_path/"cfg"/"systemd"/"user"/"sisyfus-update.timer").read_text()
'''
TEST_UPDATE_CLI = '''from pathlib import Path
import json
from sisyfus import __version__
from sisyfus.cli import build_parser,main
def env(t,m):m.setenv("SISYFUS_ENGINE_HOME",str(t/"e"));m.setenv("SISYFUS_BIN_DIR",str(t/"b"));m.setenv("SISYFUS_SKILL_DIRS",str(t/"s"))
def test_parser():
 a=build_parser().parse_args(["update","--check","--channel","beta","--version","0.8.1","--json"]);assert a.target_version=="0.8.1"
def test_status(tmp_path,monkeypatch,capsys):
 env(tmp_path,monkeypatch);assert main(["update","--status","--json"])==0;assert json.loads(capsys.readouterr().out)["installed_version"]==__version__
def test_noninteractive(tmp_path,monkeypatch,capsys):
 env(tmp_path,monkeypatch);monkeypatch.setattr("sys.stdin",type("X",(),{"isatty":lambda s:False})());assert main(["update"])==1;assert "requires --yes" in capsys.readouterr().err
def test_installer():
 s=(Path(__file__).resolve().parents[1]/"install.sh").read_text();assert "--version X.Y.Z" in s and "bootstrap_from_source" in s
'''
TEST_RELEASE_ASSETS = '''from pathlib import Path
def test_release_assets():
 r=Path(__file__).resolve().parents[1];w=(r/".github/workflows/release.yml").read_text();b=(r/"scripts/build_release_assets.py").read_text();assert "release-manifest.json" in w and "archive_sha256" in b
def test_version_docs():
 r=Path(__file__).resolve().parents[1];assert 'version = "0.8.1"' in (r/"pyproject.toml").read_text();assert "sisyfus update --rollback" in (r/"README.md").read_text()
'''
CMD_UPDATE = '''
def cmd_update(args: argparse.Namespace) -> int:
    from .updater import ActiveWorkError, UpdateManager, format_result
    manager = UpdateManager()
    try:
        if args.update_status: result = manager.status()
        elif args.check: result = manager.check(channel=args.channel, version=args.target_version)
        elif args.rollback:
            if not args.yes and not args.scheduled:
                import sys
                if not sys.stdin.isatty(): raise RuntimeError("rollback requires --yes in a non-interactive session")
                if input("Roll back Sisyfus? [y/N] ").strip().lower() not in {"y","yes"}: return 4
            result = manager.rollback(allow_active=args.allow_active)
        elif args.enable_auto:
            if not args.yes:
                import sys
                if not sys.stdin.isatty(): raise RuntimeError("enabling automatic updates requires --yes non-interactively")
                if input("Enable automatic Sisyfus updates? [y/N] ").strip().lower() not in {"y","yes"}: return 4
            result = manager.configure_auto(enabled=True, mode=args.mode, channel=args.channel, interval_hours=args.interval_hours)
        elif args.disable_auto: result = manager.configure_auto(enabled=False, mode=args.mode, channel=args.channel, interval_hours=args.interval_hours)
        else:
            if not args.yes and not args.scheduled:
                import sys
                if not sys.stdin.isatty(): raise RuntimeError("installing an update requires --yes in a non-interactive session")
                preview=manager.check(channel=args.channel,version=args.target_version)
                if not preview.get("update_available") and not args.force: result=preview
                elif input(f"Update to {(preview.get('candidate') or {}).get('version')}? [y/N] ").strip().lower() not in {"y","yes"}: return 4
                else: result=manager.apply(channel=args.channel,version=args.target_version,force=args.force,allow_active=args.allow_active)
            else: result=manager.apply(channel=args.channel,version=args.target_version,force=args.force,allow_active=args.allow_active)
    except ActiveWorkError as exc:
        result={"status":"DEFERRED_ACTIVE_WORK","message":str(exc),"active_work":exc.active}
        if args.json:_print_json(result)
        else:
            print("Sisyfus update deferred because active work is running.")
            for item in exc.active:print(f"  - {item.get('summary') or item}")
        return 0 if args.scheduled else 3
    if args.json:_print_json(result)
    else:print(format_result(result))
    return 0

'''
PARSER_UPDATE = '''
    p_update = sub.add_parser("update", help="check, install, schedule, or roll back Sisyfus releases")
    action = p_update.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true")
    action.add_argument("--status", dest="update_status", action="store_true")
    action.add_argument("--rollback", action="store_true")
    action.add_argument("--enable-auto", action="store_true")
    action.add_argument("--disable-auto", action="store_true")
    p_update.add_argument("--channel", choices=["stable","beta","edge"], default="stable")
    p_update.add_argument("--version", dest="target_version")
    p_update.add_argument("--mode", choices=["notify","auto"], default="notify")
    p_update.add_argument("--interval-hours", type=float, default=24.0)
    p_update.add_argument("--yes", action="store_true")
    p_update.add_argument("--force", action="store_true")
    p_update.add_argument("--allow-active", action="store_true")
    p_update.add_argument("--json", action="store_true")
    p_update.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)
    p_update.set_defaults(func=cmd_update)

'''
README_UPDATE = '''## Updating Sisyfus

Sisyfus updates the **engine and installed Skill together**. Releases live under
`~/.local/share/sisyfus/releases/`; activation is an atomic `current` symlink
switch and the previous release remains available for rollback.

```bash
sisyfus update --check
sisyfus update --yes
sisyfus update --version 0.8.1 --yes
sisyfus update --channel beta --yes
sisyfus update --channel edge --yes
sisyfus update --status
sisyfus update --rollback
```

Recommended automatic mode only checks and records availability:

```bash
sisyfus update --enable-auto --mode notify --interval-hours 24 --yes
```

`--mode auto` installs Stable only while all registered projects are idle.
Running activities, experiments, verifier work, Continuations, Decisions, and
unknown commits defer activation. Linux uses a systemd user timer; macOS uses a
LaunchAgent. Restart the coding-agent session after a switch so it reloads the
new Skill. Project `.sisyfus/` state is never removed.

'''
README_UPDATE_ZH = '''## 更新 Sisyfus

Sisyfus 会把 **Engine 与已安装 Skill 一起更新**。版本分别安装到
`~/.local/share/sisyfus/releases/`，校验后原子切换 `current`，上一版本可回滚。

```bash
sisyfus update --check
sisyfus update --yes
sisyfus update --version 0.8.1 --yes
sisyfus update --status
sisyfus update --rollback
sisyfus update --enable-auto --mode notify --interval-hours 24 --yes
```

自动安装只会在所有登记项目空闲时执行；运行中的 Activity、Experiment、Verifier、
Continuation、Decision 或 Unknown Commit 会让升级延后。升级后重启 Coding Agent
Session 以重新加载 Skill。项目 `.sisyfus/` 状态不会被删除。

'''
SKILL_UPDATE = '''## Updating the Skill and engine

The Skill and engine are one compatibility unit. Check with `sisyfus update
--check`; never install silently. After explicit approval use `sisyfus update
--yes`, an exact `--version`, or `--rollback`. Stable is the default channel;
beta includes prereleases and edge resolves main to one commit SHA. Activation
is blocked by running research, verifier work, leased Continuations, pending
Decisions, or unknown commits. After any switch tell the user to restart the
coding-agent session.

'''
CHANGELOG_BLOCK = '''## 0.8.1 — 2026-08-20

- Added `sisyfus update` with stable/beta/edge channels, exact versions, status,
  automatic checks, active-work protection, atomic activation, and rollback.
- Engine and Skill files now activate together from versioned release directories.
- Tagged releases publish a SHA-256 verified archive and `sisyfus.release.v1` manifest.
- `install.sh` is an idempotent bootstrap/update command with version and channel selection.

'''
RELEASE_NOTES = '''# Sisyfus v0.8.1

v0.8.1 adds versioned, atomic self-update and rollback for the Engine and Skill.

```bash
sisyfus update --check
sisyfus update --yes
sisyfus update --version 0.8.1 --yes
sisyfus update --status
sisyfus update --rollback
```

Stable releases prefer GitHub Release archives verified by SHA-256 manifests.
Automatic Notify or Auto mode uses systemd user timers on Linux and LaunchAgents
on macOS. Auto installs defer while research, verifier, Continuation, Decision,
or unknown-commit work is active. Restart the coding-agent session after a switch.
'''
write("src/sisyfus/updater.py", UPDATER)
write("install.sh", INSTALLER, 0o755)
write("scripts/build_release_assets.py", RELEASE_BUILDER, 0o755)
write(".github/workflows/release.yml", RELEASE_WORKFLOW)
write("tests/test_updater.py", TEST_UPDATER)
write("tests/test_update_cli.py", TEST_UPDATE_CLI)
write("tests/test_release_assets.py", TEST_RELEASE_ASSETS)
write("RELEASE_NOTES_v0.8.1.md", RELEASE_NOTES)
replace_once("pyproject.toml", 'version = "0.8.0"', 'version = "0.8.1"')
replace_once("src/sisyfus/__init__.py", '__version__ = "0.8.0"', '__version__ = "0.8.1"')
cli=read("src/sisyfus/cli.py")
if "def cmd_update(" not in cli:cli=cli.replace("def build_parser() -> argparse.ArgumentParser:\n",CMD_UPDATE+"def build_parser() -> argparse.ArgumentParser:\n",1)
if 'sub.add_parser("update"' not in cli:cli=cli.replace('    p_research = sub.add_parser("research", help="event-sourced branching research skill")\n',PARSER_UPDATE+'    p_research = sub.add_parser("research", help="event-sourced branching research skill")\n',1)
write("src/sisyfus/cli.py",cli)
paths=read("src/sisyfus/paths.py")
old='''def ensure_layout(root: str | Path | None = None) -> Path:\n    root_path = find_project_root(root)\n    sf = root_path / ".sisyfus"\n    for rel in LAYOUT_DIRS:\n        (sf / rel).mkdir(parents=True, exist_ok=True)\n    return sf\n'''
new='''def ensure_layout(root: str | Path | None = None) -> Path:\n    root_path = find_project_root(root)\n    sf = root_path / ".sisyfus"\n    for rel in LAYOUT_DIRS:\n        (sf / rel).mkdir(parents=True, exist_ok=True)\n    try:\n        from .updater import register_project\n        register_project(root_path)\n    except Exception:\n        pass\n    return sf\n'''
if new not in paths:paths=paths.replace(old,new,1)
write("src/sisyfus/paths.py",paths)
for path in ("README.md","README.zh-CN.md","SKILL.md"):write(path,read(path).replace("@v0.8.0","@v0.8.1"))
r=read("README.md");write("README.md",r if README_UPDATE.strip() in r else r.replace("## Install\n",README_UPDATE+"## Install\n",1))
r=read("README.zh-CN.md");write("README.zh-CN.md",r if README_UPDATE_ZH.strip() in r else r.replace("## 安装\n",README_UPDATE_ZH+"## 安装\n",1))
r=read("SKILL.md");write("SKILL.md",r if SKILL_UPDATE.strip() in r else r.replace("## Monitor-first lifecycle\n",SKILL_UPDATE+"## Monitor-first lifecycle\n",1))
r=read("CHANGELOG.md");write("CHANGELOG.md",r if "## 0.8.1" in r else r.replace("# Changelog\n\n","# Changelog\n\n"+CHANGELOG_BLOCK,1))
