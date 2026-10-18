"""Contract v2 on a host without Trash: races are still detected before the warning.

The frozen harness always installs a fake Trash, so its race tests never reach
the v2 no-Trash branch. These variants remove the Trash binary and replay the
same races: a mismatch must still raise ``staged_mismatch`` with no warning and
no exec, and a publication after the rename must survive the warning path.
Runs under scripts/test_retained.py with the frozen file (its tripwires apply).
"""
from __future__ import annotations

import json
import os
import warnings

import pytest

from sisyfus.research_v2 import live
from test_observatory_live_retention import (  # noqa: F401  (fixtures by name)
    deletion_tripwire, descriptor_tripwire, harness, identity, publish,
)


def _without_trash(h):
    h.monkeypatch.setattr(live, "_TRASH_BIN", str(h.base / "missing-binary"))


def _clear_raises_without_warning(h, *, pid):
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        with pytest.raises(RuntimeError) as caught:
            live.clear_live_state(h.root, pid=pid)
    assert not [w for w in seen if issubclass(w.category, RuntimeWarning)]
    assert type(caught.value).__name__ == "LiveStateRetained"
    return caught.value


def test_swap_at_rename_without_trash_is_staged_mismatch_not_warning(harness):
    h = harness
    _without_trash(h)
    h.seed()
    new_bytes = json.dumps(dict(h.state, pid=os.getpid() + 1)).encode()
    later_bytes = json.dumps(dict(h.state, pid=os.getpid() + 2)).encode()
    real_stage = live._stage_state
    def racing(dfd, stfd):
        publish(h.path, new_bytes)
        real_stage(dfd, stfd)
        publish(h.path, later_bytes)
    h.monkeypatch.setattr(live, "_stage_state", racing)
    error = _clear_raises_without_warning(h, pid=os.getpid())
    assert error.reason == "staged_mismatch"
    assert (error.path / "observatory.json").read_bytes() == new_bytes
    assert h.path.read_bytes() == later_bytes and not h.calls


def test_same_inode_change_without_trash_is_staged_mismatch_not_warning(harness):
    h = harness
    _without_trash(h)
    h.seed()
    new = json.dumps(dict(h.state, pid=os.getpid() + 1)).encode()
    real_stage = live._stage_state
    def mutate(dfd, stfd):
        real_stage(dfd, stfd)
        (h.stages()[0] / "observatory.json").write_bytes(new)
    h.monkeypatch.setattr(live, "_stage_state", mutate)
    error = _clear_raises_without_warning(h, pid=None)
    assert error.reason == "staged_mismatch"
    assert (error.path / "observatory.json").read_bytes() == new and not h.calls


def test_parent_retarget_without_trash_is_staged_mismatch_not_warning(harness):
    h = harness
    _without_trash(h)
    old = h.seed()
    other = h.root / "original-parent"
    real_stage = live._stage_state
    def retarget(dfd, stfd):
        real_stage(dfd, stfd)
        os.rename(h.path.parent, other)
        h.path.parent.mkdir()
        h.path.write_bytes(b"replacement-owner")
    h.monkeypatch.setattr(live, "_stage_state", retarget)
    error = _clear_raises_without_warning(h, pid=None)
    assert error.reason == "staged_mismatch" and not h.calls
    assert h.path.read_bytes() == b"replacement-owner"
    stages = list(other.glob(".observatory-retire-*"))
    assert len(stages) == 1 and (stages[0] / "observatory.json").read_bytes() == old


def test_publication_after_rename_survives_the_warning_path(harness):
    h = harness
    _without_trash(h)
    old = h.seed()
    new = json.dumps(dict(h.state, pid=os.getpid() + 1)).encode()
    real_stage = live._stage_state
    def publish_after(dfd, stfd):
        real_stage(dfd, stfd)
        publish(h.path, new)
    h.monkeypatch.setattr(live, "_stage_state", publish_after)
    with pytest.warns(RuntimeWarning) as caught:
        assert live.clear_live_state(h.root, pid=os.getpid()) is None
    (stage,) = h.stages()
    assert [str(w.message) for w in caught] == [f"Live state retained: reason=trash_missing; path={stage}"]
    assert h.path.read_bytes() == new and (stage / "observatory.json").read_bytes() == old
    assert not h.calls
