"""Fence updater activation while a native mission controller is running."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from ..updater import InstallLayout


@contextmanager
def running_installation(layout: InstallLayout) -> Iterator[None]:
    # Native workers are POSIX-only. Independent mission controllers may share
    # this lock; updater activation/rollback requires its exclusive counterpart.
    import fcntl

    layout.ensure()
    with layout.lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
