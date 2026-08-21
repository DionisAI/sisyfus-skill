from __future__ import annotations

from pathlib import Path


LAYOUT_DIRS = [
    "agents",
    "beams",
    "beams/specs",
    "beams/runs",
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
    """Resolve the project root.

    An explicit `start` (e.g. the CLI's ``--root``) is honored exactly and
    never traded for an ancestor directory that happens to contain
    ``.sisyfus/`` or ``.git`` — silently walking above the requested root used
    to relocate state and command execution outside the intended project
    (an ancestor such as ``$HOME`` with a ``.sisyfus/`` would win). Upward
    discovery only happens when no root is given, starting from the cwd.
    """
    if start is not None:
        cur = Path(start).resolve()
        return cur.parent if cur.is_file() else cur
    cur = Path.cwd().resolve()
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
    try:
        from .updater import register_project
        register_project(root_path)
    except Exception:
        pass
    return sf
