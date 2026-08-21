from pathlib import Path
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
