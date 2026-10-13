"""Run pytest without deleting temporary artifacts; retain existing file policy."""
from __future__ import annotations
import os
from pathlib import Path
import sys
import tempfile
import uuid
import pytest

class RetainedPaths:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="sisyfus-techlead-tests-")).resolve()
    def getbasetemp(self):
        return self.root
    def mktemp(self, basename, numbered=True):
        if Path(basename).name != basename or basename in {"", ".", ".."}:
            raise ValueError("temporary basename must be a single path component")
        path = self.root / (f"{basename}-{uuid.uuid4().hex}" if numbered else basename)
        path.mkdir()
        return path

class RetainedTemporaryFiles:
    def __init__(self, paths): self.paths = paths
    @pytest.fixture(scope="session")
    def tmp_path_factory(self): return self.paths
    @pytest.fixture
    def tmp_path(self): return self.paths.mktemp("test")

def guard_deletion(event, args):
    if event not in {"os.remove", "os.rmdir", "shutil.rmtree"}: return
    if len(args) > 1 and isinstance(args[1], int) and args[1] not in (-1,):
        raise RuntimeError(f"Permanent deletion blocked: {event} {args}")
    if os.path.lexists(args[0]):
        raise RuntimeError(f"Permanent deletion blocked: {event} {args}")

if __name__ == "__main__":
    paths = RetainedPaths()
    source = str(Path(__file__).resolve().parents[1] / "src")
    os.environ["PYTHONPATH"] = source + os.pathsep + os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["SISYFUS_ENGINE_HOME"] = str(paths.root / "installation/engine")
    os.environ["SISYFUS_BIN_DIR"] = str(paths.root / "installation/bin")
    os.environ["SISYFUS_SKILL_DIRS"] = str(paths.root / "installation/skills")
    sys.addaudithook(guard_deletion)
    print(f"Retained test artifacts: {paths.root}", flush=True)
    sys.path.insert(0, source)
    code = pytest.main(["-p", "no:cacheprovider", "--capture=sys", *sys.argv[1:]],
                      plugins=[RetainedTemporaryFiles(paths)])
    print(f"Retained test artifacts: {paths.root}", flush=True)
    raise SystemExit(code)
