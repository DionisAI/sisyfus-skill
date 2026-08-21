from __future__ import annotations
import hashlib,io,json,os,tarfile
from pathlib import Path
import pytest
from sisyfus import __version__
from sisyfus.updater import *
from sisyfus.updater import _activate_release, _build_release, _safe_extract
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
