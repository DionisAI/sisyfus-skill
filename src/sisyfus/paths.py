from __future__ import annotations

from pathlib import Path


LAYOUT_DIRS = [
    "agents",
    "beams",
    "beams/specs",
    "beams/runs",
    "dashboard",
    "evals",
    "evals/runs",
    "experiments",
    "experiments/artifacts",
    "outcomes",
    "provider",
    "rubrics",
    "memory_fsm",
    "goals",
    "inbox",
    "memory",
    "monitors",
    "monitors/scripts",
    "monitors/runs",
    "promotions",
    "reviews",
    "research",
    "research/runs",
    "runs",
    "sessions",
    "skills",
    "tasks",
    "worktrees",
]


def find_project_root(start: str | Path | None = None) -> Path:
    cur = Path(start or Path.cwd()).resolve()
    if cur.is_file():
        cur = cur.parent
    for candidate in [cur, *cur.parents]:
        if (candidate / ".sisyfus").exists():
            return candidate
    for candidate in [cur, *cur.parents]:
        if (candidate / ".git").exists():
            return candidate
    return cur


def sisyfus_dir(root: str | Path | None = None) -> Path:
    return find_project_root(root) / ".sisyfus"


def ensure_layout(root: str | Path | None = None) -> Path:
    root_path = find_project_root(root)
    sf = root_path / ".sisyfus"
    for rel in LAYOUT_DIRS:
        (sf / rel).mkdir(parents=True, exist_ok=True)
    return sf
