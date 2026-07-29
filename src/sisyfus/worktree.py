from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

from .utils import run_process, slugify


def is_git_repo(path: Path) -> bool:
    result = run_process(["git", "rev-parse", "--is-inside-work-tree"], cwd=path, timeout=10, shell=False)
    return result["exit_code"] == 0 and result["stdout"].strip() == "true"


def git_root(path: Path) -> Path | None:
    result = run_process(["git", "rev-parse", "--show-toplevel"], cwd=path, timeout=10, shell=False)
    if result["exit_code"] != 0:
        return None
    return Path(result["stdout"].strip()).resolve()


class WorktreeManager:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def create_or_use(self, *, goal_id: str, run_id: str, isolate: bool, base_ref: str = "HEAD") -> dict[str, Any]:
        if not isolate:
            return {"isolated": False, "workdir": str(self.root), "branch": None, "created": False, "reason": "isolation disabled"}
        if not is_git_repo(self.root):
            return {"isolated": False, "workdir": str(self.root), "branch": None, "created": False, "reason": "not a git repo"}
        workdir = self.root / ".sisyfus" / "worktrees" / run_id
        branch = f"sisyfus/{slugify(goal_id)}/{run_id}"
        workdir.parent.mkdir(parents=True, exist_ok=True)
        if workdir.exists():
            return {"isolated": True, "workdir": str(workdir), "branch": branch, "created": False, "reason": "already exists"}
        result = run_process(["git", "worktree", "add", "-b", branch, str(workdir), base_ref], cwd=self.root, timeout=60, shell=False)
        if result["exit_code"] != 0:
            # Branch might already exist from a prior interrupted run; try without -b.
            result2 = run_process(["git", "worktree", "add", str(workdir), branch], cwd=self.root, timeout=60, shell=False)
            if result2["exit_code"] != 0:
                return {"isolated": False, "workdir": str(self.root), "branch": branch, "created": False, "reason": result["stderr"] + result2["stderr"]}
        return {"isolated": True, "workdir": str(workdir), "branch": branch, "created": True, "reason": "created"}

    @staticmethod
    def changed_files(workdir: Path) -> list[str]:
        if not is_git_repo(workdir):
            return []
        result = run_process(["git", "diff", "--name-only", "HEAD"], cwd=workdir, timeout=20, shell=False)
        if result["exit_code"] != 0:
            return []
        return [line.strip() for line in result["stdout"].splitlines() if line.strip()]

    @staticmethod
    def diff_text(workdir: Path, *, max_chars: int = 20000) -> str:
        if not is_git_repo(workdir):
            return ""
        result = run_process(["git", "diff", "--", "."], cwd=workdir, timeout=60, shell=False)
        text = result["stdout"] if result["exit_code"] == 0 else result["stderr"]
        if len(text) > max_chars:
            return text[: max_chars // 2] + "\n...[diff truncated]...\n" + text[-max_chars // 2 :]
        return text

    @staticmethod
    def diff_numstat(workdir: Path) -> dict[str, Any]:
        if not is_git_repo(workdir):
            return {"available": False, "files": [], "added": 0, "deleted": 0, "changed_lines": 0}
        result = run_process(["git", "diff", "--numstat", "HEAD"], cwd=workdir, timeout=20, shell=False)
        files = []
        added = deleted = 0
        if result["exit_code"] == 0:
            for line in result["stdout"].splitlines():
                parts = line.split("\t")
                if len(parts) < 3:
                    continue
                add_s, del_s, path = parts[0], parts[1], parts[2]
                add_n = int(add_s) if add_s.isdigit() else 0
                del_n = int(del_s) if del_s.isdigit() else 0
                added += add_n
                deleted += del_n
                files.append({"path": path, "added": add_n, "deleted": del_n})
        return {"available": True, "files": files, "added": added, "deleted": deleted, "changed_lines": added + deleted}


def matches_forbidden(path: str, patterns: list[str]) -> str | None:
    normalized = path.replace("\\", "/")
    for pattern in patterns:
        p = pattern.replace("\\", "/").rstrip("/")
        if not p:
            continue
        if fnmatch.fnmatch(normalized, p) or normalized == p or normalized.startswith(p + "/"):
            return pattern
    return None
