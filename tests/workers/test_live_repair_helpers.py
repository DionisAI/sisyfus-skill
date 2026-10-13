"""Offline helper tests; no native model claims or processes."""
import importlib.util
from pathlib import Path
import sys

import pytest

from sisyfus.workers.protocol import Receipt, Request


def helper():
    path = Path(__file__).resolve().parents[2] / "scripts/live_repair_validation.py"
    spec = importlib.util.spec_from_file_location("live_repair_validation_helper", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Delegate:
    def __init__(self):
        self.calls = []

    def probe(self):
        return {"available": True, "test_only": True}

    def run(self, request, emit, controls):
        self.calls.append(request.task_id)
        return Receipt("COMPLETED", requested_model=request.model,
                       output="Offline delegate fixture, not a native execution")


def test_only_first_controlled_request_installs_fault(tmp_path):
    module = helper()
    delegate = Delegate()
    worker = module.FaultOnce(delegate)
    events = []
    request = Request("task-one", "controlled test", str(tmp_path), "gpt-6.1-sol", mode="workspace-write")
    first = worker.run(request, lambda k, d: events.append((k, d)), lambda: [])
    assert first.as_dict()["native_worker_execution"] is False
    assert first.actual_model is None and first.session_id is None
    assert "print(" in (tmp_path / "job.py").read_text()
    assert events[0][0] == "synthetic_worker_fixture"
    assert delegate.calls == []
    second = worker.run(request, lambda *args: None, lambda: [])
    assert delegate.calls == ["task-one"]
    assert "native_worker_execution" not in second.as_dict()
    assert worker.probe()["test_only"] is True


@pytest.mark.parametrize("mode,controls", [("read-only", []), ("workspace-write", [{"action": "interrupt"}])])
def test_no_fault_installation_under_wrong_authority_or_pending_control(tmp_path, mode, controls):
    module = helper()
    delegate = Delegate()
    worker = module.FaultOnce(delegate)
    request = Request("task-one", "controlled test", str(tmp_path), "gpt-6.1-sol", mode=mode)
    with pytest.raises(ValueError, match="uninterrupted implementation"):
        worker.run(request, lambda *args: None, lambda: controls)
    assert not worker.injected and not delegate.calls
    assert not (tmp_path / "job.py").exists()
