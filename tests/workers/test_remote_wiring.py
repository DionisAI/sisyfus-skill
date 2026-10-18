"""Frozen W1/W2 controller wiring: real public transport, scripted fixture nodes.

Default readiness and all original gates remain. The successful driver contract
was read back before freeze: {candidate:str, before:str, delta:dict}, no status.
No Gateway/NodeAgent, native model, second host, phone or deployment is exercised.
"""
from contextlib import contextmanager
import copy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from sisyfus.autonomy.models import Verdict
from sisyfus.autonomy.policy import IdempotencyConflictError, LeaseLost
from sisyfus.workers import lead_mission as module
from sisyfus.workers import remote_artifacts as artifacts
from sisyfus.workers import remote_driver as remote_module
from sisyfus.workers.node_claims import NodeClaims
from sisyfus.workers.protocol import Receipt, Request, digest
from sisyfus.workers.mission import files
from test_lead_mission import make_spec, mission
from test_node_placement import assign, enroll, execution, remote_tables


REAL_REMOTE_DRIVER = remote_module.RemoteCodexDriver
KEY = "wire-worker-0001"


def put(root, path, data):
    dest = Path(root) / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("xb") as stream:
        stream.write(data)
    return dest


def raw_run(m, key=KEY):
    with m.store._transaction(immediate=False) as db:
        row = db.execute("SELECT * FROM native_worker_runs WHERE key=?", (key,)).fetchone()
        return dict(row) if row else None


def task_placement(m, data, task_id="build"):
    """Synthetic canonical corruption/race fixture; never mutates production files."""
    with m.store._transaction() as db:
        db.execute("UPDATE metadata SET value=? WHERE key=?",
                   (json.dumps(data), "techlead:placement:" + task_id))


def verify(m, args, result):
    continuation = m.store.get_continuation(args["continuation_id"])
    decision = SimpleNamespace(capability="workers.execute", arguments=args)
    return m.registry.get("workers.execute").verifier.verify(
        m.runtime.planner_context(continuation), decision, result)


def no_admission(m, key=KEY):
    assert raw_run(m, key) is None
    assert m.inbox.for_run(key) is None
    assert m.journal.get("run_placements", key) is None
    assert m.node_claims.get(key) is None
    assert not (m.directory / "attempts" / key).exists()
    assert not m.drivers["codex"].requests
    assert m.store.verify_event_chain()["valid"]


class ScriptedRemote:
    """Wrap the stable REAL driver; script only public local node transport IO."""

    def __init__(self, m, root, monkeypatch, *, native_status="COMPLETED", actual=None,
                 changes=None, no_work=False, interrupt=False, after=None):
        self.m, self.root, self.patch = m, Path(root), monkeypatch
        self.native_status, self.actual = native_status, actual
        self.changes = {"a.txt": b"42"} if changes is None else changes
        self.no_work, self.interrupt, self.after = no_work, interrupt, after
        self.instances, self.requests, self.receipts, self.events = [], [], [], []

    def install(self):
        # Covers either a module-level import or a lazy import of the same API.
        self.patch.setattr(module, "RemoteCodexDriver", self.factory, raising=False)
        self.patch.setattr(remote_module, "RemoteCodexDriver", self.factory)
        return self

    def factory(self, claims, run_key, node_id, **kwargs):
        assert claims.journal is self.m.journal
        assert isinstance(claims, NodeClaims)
        assert raw_run(self.m, run_key)["status"] == "IN_FLIGHT"
        instance = SimpleNamespace(key=run_key, node_id=node_id, kwargs=copy.deepcopy(kwargs),
                                   claims=claims, tick=0.0, phase=0, calls=0, claim=None)
        self.instances.append(instance)
        actual_kwargs = dict(kwargs, clock=lambda: instance.tick, poll_seconds=0.2)
        instance.driver = REAL_REMOTE_DRIVER(claims, run_key, node_id, **actual_kwargs)
        parent = self

        class Wrapped:
            name, controls = "codex", ("interrupt",)

            @property
            def materialization(self):
                return instance.driver.materialization

            def run(self, request, emit, controls=lambda: []):
                instance.calls += 1
                assert instance.calls == 1 and isinstance(request, Request)
                instance.request = request
                parent.requests.append(request)

                def observed(kind, data):
                    parent.events.append((kind, data))
                    emit(kind, data)

                def sleep(seconds):
                    assert 0 < seconds <= 0.2
                    instance.tick += seconds
                    if not parent.no_work:
                        parent.node_step(instance)

                with parent.patch.context() as patch:
                    patch.setattr(remote_module.time, "sleep", sleep)
                    receipt = instance.driver.run(request, observed, controls)
                instance.returned = receipt
                if parent.after:
                    parent.after(instance, receipt)
                return receipt

        return Wrapped()

    def node_step(self, instance):
        claims, node = instance.claims, instance.node_id
        if instance.phase == 0:
            claimed = claims.claim(node, "claim_wire_" + uuid.uuid4().hex)
            assert claimed["status"] == "CLAIMED"
            instance.claim = claimed["claim"]
            owned = instance.claim
            assert owned["request"] == asdict(instance.request)
            instance.original = artifacts.full_tree_manifest(instance.request.cwd)
            instance.input_bytes = {}
            for item in owned["input_manifest"]["files"]:
                data = claims.read_input(node, owned["claim_id"], owned["epoch"], item["path"])
                assert len(data) == item["size"] and hashlib.sha256(data).hexdigest() == item["sha256"]
                instance.input_bytes[item["path"]] = data
            claims.sync(node, owned["claim_id"], owned["epoch"], [
                {"seq": 1, "kind": "session_bound", "data": {"session_id": "fixture-session-" + instance.key}},
                {"seq": 2, "kind": "turn_bound", "data": {"session_id": "fixture-session-" + instance.key,
                                                           "turn_id": "fixture-turn-" + instance.key}}])
            instance.phase = 1
            if self.interrupt:
                self.m.stop.set()
                return
        elif instance.phase != 1:
            return
        owned = instance.claim
        if self.interrupt:
            pending = claims.pending_controls(node, owned["claim_id"], owned["epoch"])
            expected = {"id": instance.key + ":controller-stop", "action": "interrupt", "text": ""}
            assert pending == [expected]
            with self.m.store._transaction(immediate=False) as db:
                assert db.execute("SELECT status FROM remote_transport_controls WHERE id=?", (expected["id"],)).fetchone()[0] == "PENDING"
            claims.sync(node, owned["claim_id"], owned["epoch"], [
                {"seq": 3, "kind": "control_ack", "data": {"command_id": expected["id"], "accepted": True}}])
            assert claims.pending_controls(node, owned["claim_id"], owned["epoch"]) == []
        final = self.root / ("node-final-" + uuid.uuid4().hex)
        final.mkdir(parents=True)
        contents = dict(instance.input_bytes)
        changes = ({instance.request.task_id == "other" and "b.txt" or "a.txt": b"42"}
                   if self.changes == {"a.txt": b"42"} else self.changes)
        contents.update(changes)
        for path, data in sorted(contents.items()):
            put(final, path, data)
        manifest = []
        for path, data in sorted(changes.items()):
            sha = hashlib.sha256(data).hexdigest()
            claims.upload(node, owned["claim_id"], owned["epoch"], path, sha, data)
            manifest.append({"path": path, "size": len(data), "sha256": sha})
        (claims.artifact_root / owned["claim_id"]).mkdir(exist_ok=True)
        native = Receipt(self.native_status, "fixture-session-" + instance.key,
                         "fixture-turn-" + instance.key, 0, "scripted fixture receipt", {}, None,
                         "gpt-6.1-sol", self.actual)
        tree = artifacts.full_tree_manifest(final)
        result = claims.receipt(node, owned["claim_id"], owned["epoch"], native, manifest, tree=tree)
        assert result["status"] == ("UNKNOWN" if self.native_status == "UNKNOWN" else "RECEIPTED")
        assert "tree" not in claims.get(instance.key)
        assert claims.status(node, owned["claim_id"], owned["epoch"])["tree"] == tree
        self.receipts.append(native)
        instance.phase = 2


@pytest.fixture
def m(tmp_path):
    controller = mission(tmp_path, make_spec(tmp_path))
    controller._initial_plan()
    return controller


def remote(m, monkeypatch, tmp_path, **script_kwargs):
    node = enroll(m)
    pin = assign(m, node)
    m.remote_execution_ready = lambda: True
    script = ScriptedRemote(m, tmp_path / "node-script", monkeypatch, **script_kwargs).install()
    capability, args = execution(m)
    return pin, script, capability, args


def test_direct_default_readiness_is_false_readonly_not_persisted(m):
    before = m.store.verify_event_chain()
    frozen = digest(m.spec)
    assert callable(m.remote_execution_ready) and m.remote_execution_ready() is False
    assert digest(m.spec) == frozen and "remote_execution_ready" not in m.spec
    assert m.store.verify_event_chain() == before and not remote_tables(m)


@pytest.mark.parametrize("marker", ["techlead:inbox_policy:trial-child", "techlead:learning_config:trial"])
def test_reopened_trial_child_has_default_false_not_parent_host_readiness(m, tmp_path, marker):
    m.remote_execution_ready = lambda: True
    with m.store._transaction() as db:
        db.execute("INSERT INTO metadata VALUES(?,?)", (marker, "{}"))
    child = mission(tmp_path, None)
    assert child.remote_execution_ready() is False and not remote_tables(child)
    assert not child.journal.runs()


@pytest.mark.parametrize("ready", [False, None, 0, 1, "ready", {"ready": True}])
def test_only_literal_true_allows_new_remote_admission(m, tmp_path, ready):
    pin = assign(m, enroll(m))
    m.remote_execution_ready = lambda: ready
    capability, args = execution(m)
    frozen = digest(m.spec)
    result = capability.execute(args, idempotency_key=KEY)
    assert result.status == "ERROR"
    no_admission(m)
    assert m.placement("build") == pin and pin["execution_ready"] is False
    assert digest(m.spec) == frozen


def test_prepared_start_waits_without_consuming_attempts_when_host_false(tmp_path):
    m = mission(tmp_path, make_spec(tmp_path))
    m.prepare_for_placement("prepare_wire_0001")
    pin = assign(m, enroll(m))
    before = m.continuations()
    result = m.run(max_cycles=2)
    assert result["phase"] == "WAITING_PLACEMENT"
    assert m.continuations() == before and not m.journal.runs()
    assert not m.drivers["codex"].requests and m.placement("build") == pin


def test_prepared_start_ready_real_transport_reaches_original_checks_review_integration(tmp_path, monkeypatch):
    m = mission(tmp_path, make_spec(tmp_path, two=True, parallelism=1))
    m.prepare_for_placement("prepare_wire_0001")
    pins = {task_id: assign(m, enroll(m, serial), "placement_wire_%04d" % serial, task_id)
            for serial, task_id in enumerate(("build", "other"), start=1)}
    m.remote_execution_ready = lambda: True
    script = ScriptedRemote(m, tmp_path / "node-script", monkeypatch).install()
    frozen = digest(m.spec)
    source = artifacts.full_tree_manifest(m.spec["source"])
    result = m.run(max_cycles=20)
    assert result["all_verified"] is True and result["phase"] == "COMPLETED"
    assert len(script.instances) == len(script.requests) == 2
    assert {r.task_id for r in script.requests} == {"build", "other"}
    assert not m.drivers["codex"].requests
    assert result["integration"]["evidence"]["verdict"] == "PASS"
    assert all(r["role"] == "reviewer" for r in result["runs"] if r["task_id"] == "planner")
    assert len(m.drivers["claude"].requests) == 3
    assert all(r.model == "claude-opus-5-5" and r.mode == "read-only" for r in m.drivers["claude"].requests)
    assert all(m.placement(task_id) == pin and pin["execution_ready"] is False for task_id, pin in pins.items())
    assert digest(m.spec) == frozen and artifacts.full_tree_manifest(m.spec["source"]) == source
    assert m.store.verify_event_chain()["valid"]


@pytest.mark.parametrize("ready", [False, True])
def test_local_path_keeps_original_fingerprint_roles_receipt_and_no_remote_metadata(m, ready):
    m.remote_execution_ready = lambda: ready
    capability, args = execution(m)
    frozen = digest(m.spec)
    expected = digest({"arguments": args, "task": m.task("build"), "spec": frozen})
    result = capability.execute(args, idempotency_key=KEY)
    assert result.status == "COMPLETED" and raw_run(m)["fingerprint"] == expected
    role = m.journal.get("roles", KEY)
    assert role == {"role": "worker", "driver": "codex", "model": "gpt-6.1-sol", "mode": "workspace-write",
                    "cwd": str(m.directory / "attempts" / KEY / "candidate"),
                    "procedure_hash": m.procedure()["hash"], "node": "build", "task_hash": digest(m.task("build"))}
    m.remote_execution_ready = lambda: not ready
    assert capability.execute(args, idempotency_key=KEY).observation == result.observation
    assert len(m.drivers["codex"].requests) == 1
    assert not remote_tables(m) and m.journal.get("run_placements", KEY) is None
    assert digest(m.spec) == frozen


def test_remote_pins_canonical_full_placement_and_original_role_request_paths(m, tmp_path, monkeypatch):
    pin, script, capability, args = remote(m, monkeypatch, tmp_path)
    before_source = artifacts.full_tree_manifest(m.spec["source"])
    result = capability.execute(args, idempotency_key=KEY)
    assert result.status == "COMPLETED"
    expected = digest({"arguments": args, "task": m.task("build"), "spec": digest(m.spec), "placement": pin})
    assert raw_run(m)["fingerprint"] == expected
    saved = m.journal.get("run_placements", KEY)
    base = m.directory / "attempts" / KEY
    assert saved["placement"] == pin and saved["placement"]["execution_ready"] is False
    assert {k: saved[k] for k in ("role", "driver", "model", "mode", "cwd")} == {
        "role": "worker", "driver": "codex", "model": "gpt-6.1-sol", "mode": "workspace-write", "cwd": str(base / "candidate")}
    assert Path(saved["input_snapshot"]) == base / "remote-input"
    assert Path(saved["candidate_root"]) == base / "remote-candidate"
    instance = script.instances[0]
    assert instance.node_id == pin["node_id"] and instance.request.cwd == saved["cwd"]
    assert instance.kwargs["output_paths"] == ["README.md", "a.txt"]
    assert Path(instance.kwargs["input_snapshot"]) == Path(saved["input_snapshot"])
    assert Path(instance.kwargs["candidate_root"]) == Path(saved["candidate_root"])
    assert m.journal.get("roles", KEY)["cwd"] == instance.request.cwd
    assert artifacts.full_tree_manifest(instance.request.cwd) == before_source
    assert artifacts.full_tree_manifest(m.spec["source"]) == before_source
    assert result.observation["patch"] == {"a.txt": {"before": None, "after": hashlib.sha256(b"42").hexdigest()}}
    assert Path(result.observation["candidate"]) == base / "artifact"
    assert (base / "artifact/a.txt").read_bytes() == b"42" and not (base / "candidate/a.txt").exists()
    assert result.observation["candidate_hash"] == digest(files(base / "artifact"))
    assert result.observation["actual_model"] is None and result.observation["requested_model"] == "gpt-6.1-sol"
    assert not m.drivers["codex"].requests and not m.snapshot()["all_verified"]


def test_context_and_run_placement_share_canonical_reservation_transaction(m, tmp_path, monkeypatch):
    pin, script, capability, args = remote(m, monkeypatch, tmp_path)
    entry = m.inbox.submit("固定补充资料，不改变验收。", "context_wire_0001", task_id="build",
                           snapshot=m.snapshot(), controller={"running": True})
    original_bind, original_record = m.inbox.bind, m.journal.record_in
    dbs = []

    def bind(db, key, **kwargs):
        if key == KEY:
            assert db.execute("SELECT status FROM native_worker_runs WHERE key=?", (key,)).fetchone()[0] == "IN_FLIGHT"
            dbs.append(db)
        return original_bind(db, key, **kwargs)

    def record(db, category, key, data):
        if category == "run_placements":
            assert key == KEY and dbs == [db]
            assert m.journal._context_admissions[id(db)] == KEY
            assert db.execute("SELECT 1 FROM lead_mission_contexts WHERE run_key=?", (key,)).fetchone()
            assert data["placement"] == pin
        return original_record(db, category, key, data)

    monkeypatch.setattr(m.inbox, "bind", bind)
    monkeypatch.setattr(m.journal, "record_in", record)
    result = capability.execute(args, idempotency_key=KEY)
    assert result.status == "COMPLETED" and len(dbs) == 1
    binding = m.inbox.for_run(KEY)
    assert script.requests[0].prompt == binding["prompt"] and "固定补充资料" in script.requests[0].prompt
    assert result.observation["context_binding_hash"] == digest(binding)
    current = next(x for x in m.inbox.messages()["messages"] if x["id"] == entry["id"])
    assert current["applications"][0]["status"] == "APPLIED"
    events = [e for e in m.journal.events(0, 1000) if e["run_key"] == KEY]
    assert sum(e["type"] == "WORKER_SESSION_BOUND" for e in events) == 1
    assert sum(e["type"] == "WORKER_TURN_BOUND" for e in events) == 1
    assert sum(e["type"] == "WORKER_MISSION_CONTEXT_APPLIED" for e in events) == 1
    assert script.events == [] and m.store.verify_event_chain()["valid"]


def test_run_placement_event_failure_rolls_back_run_context_and_transport(m, tmp_path, monkeypatch):
    _, script, capability, args = remote(m, monkeypatch, tmp_path)
    original = m.journal._event

    def fail(db, kind, *args, **kwargs):
        original(db, kind, *args, **kwargs)
        if kind == "lead_run_placements":
            raise RuntimeError("fixed remote record event failure")

    monkeypatch.setattr(m.journal, "_event", fail)
    with pytest.raises(RuntimeError, match="fixed remote record event failure"):
        capability.execute(args, idempotency_key=KEY)
    no_admission(m)
    assert not script.instances


def test_node_backend_lazy_construction_is_outside_any_admission_transaction(m, tmp_path, monkeypatch):
    _, script, capability, args = remote(m, monkeypatch, tmp_path)
    m._node_claims = None
    original_tx, original_init = m.store._transaction, NodeClaims.__init__
    depth, observed = [0], []

    @contextmanager
    def transaction(*a, **kw):
        with original_tx(*a, **kw) as db:
            depth[0] += 1
            try:
                yield db
            finally:
                depth[0] -= 1

    def initialize(self, *a, **kw):
        assert depth[0] == 0
        observed.append(True)
        return original_init(self, *a, **kw)

    monkeypatch.setattr(m.store, "_transaction", transaction)
    monkeypatch.setattr(NodeClaims, "__init__", initialize)
    result = capability.execute(args, idempotency_key=KEY)
    assert result.status == "COMPLETED" and observed == [True]
    assert len(script.requests) == 1 and depth[0] == 0


@pytest.mark.parametrize("race", ["placement-local", "placement-node", "placement-revision", "placement-hash",
                                  "ready-false", "revoked", "trial", "continuation-kind"])
def test_remote_admission_rechecks_current_identity_readiness_and_scope_atomically(m, tmp_path, monkeypatch, race):
    pin, script, capability, args = remote(m, monkeypatch, tmp_path)
    other = enroll(m, 2)
    original = m.journal.reserve

    def reserved(*a, **kw):
        changed = dict(pin)
        if race.startswith("placement-"):
            field, value = {"placement-local": ("kind", "local"), "placement-node": ("node_id", other["node_id"]),
                            "placement-revision": ("revision", pin["revision"] + 1), "placement-hash": ("task_hash", "f" * 64)}[race]
            changed[field] = value
            task_placement(m, changed)
        elif race == "ready-false":
            m.remote_execution_ready = lambda: False
        elif race == "revoked":
            m.node_claims.registry.revoke(pin["node_id"])
        elif race == "trial":
            monkeypatch.setattr(m.inbox, "context_allowed", lambda db: False)
        else:
            with m.store._transaction() as db:
                row = db.execute("SELECT context_json FROM continuations WHERE id=?", (args["continuation_id"],)).fetchone()
                context = json.loads(row[0]); context["lead_kind"] = "reviewer"
                db.execute("UPDATE continuations SET context_json=? WHERE id=?", (json.dumps(context), args["continuation_id"]))
        return original(*a, **kw)

    monkeypatch.setattr(m.journal, "reserve", reserved)
    result = capability.execute(args, idempotency_key=KEY)
    assert result.status == "ERROR"
    # Trial policy intentionally denies the convenience backend property; read
    # the already-created same-store transport without granting a new backend.
    assert raw_run(m) is None and m.inbox.for_run(KEY) is None
    assert m.journal.get("run_placements", KEY) is None and m._node_claims.get(KEY) is None
    assert not script.instances and not m.drivers["codex"].requests
    assert not (m.directory / "attempts" / KEY).exists()
    assert m.store.verify_event_chain()["valid"]


def test_local_to_remote_race_never_falls_back_or_creates_remote_attempt(m, monkeypatch):
    node = enroll(m)
    m.remote_execution_ready = lambda: True
    capability, args = execution(m)
    original = m.journal.reserve

    def reserved(*a, **kw):
        assign(m, node)
        return original(*a, **kw)

    monkeypatch.setattr(m.journal, "reserve", reserved)
    result = capability.execute(args, idempotency_key=KEY)
    assert result.status == "ERROR"
    no_admission(m)


@pytest.mark.parametrize("status", ["COMPLETED", "UNKNOWN"])
@pytest.mark.parametrize("current", ["ready-false", "placement-local", "other-node", "revoked", "trial"])
def test_canonical_cached_remote_receipt_uses_original_pin_zero_driver_on_replay(m, tmp_path, monkeypatch, status, current):
    pin, script, capability, args = remote(m, monkeypatch, tmp_path, native_status=status)
    other = enroll(m, 2)
    first = capability.execute(args, idempotency_key=KEY)
    assert first.status == status and len(script.instances) == 1
    original_saved = m.journal.get("run_placements", KEY)
    original_row = raw_run(m)
    if current == "ready-false":
        m.remote_execution_ready = lambda: False
    elif current in {"placement-local", "other-node"}:
        task_placement(m, dict(pin, **({"kind": "local"} if current == "placement-local" else {"node_id": other["node_id"]})))
    elif current == "revoked":
        m.node_claims.registry.revoke(pin["node_id"])
    else:
        with m.store._transaction() as db:
            db.execute("INSERT INTO metadata VALUES('techlead:inbox_policy:trial-child','{}')")

    def forbidden(*a, **kw):
        raise AssertionError("cached run must be read before backend/current readiness")

    monkeypatch.setattr(module, "RemoteCodexDriver", forbidden, raising=False)
    monkeypatch.setattr(remote_module, "RemoteCodexDriver", forbidden)
    monkeypatch.setattr(m, "remote_execution_ready", forbidden)
    assert capability.execute(args, idempotency_key=KEY).observation == first.observation
    assert raw_run(m) == original_row and m.journal.get("run_placements", KEY) == original_saved
    assert len(script.instances) == len(script.requests) == 1 and not m.drivers["codex"].requests
    with pytest.raises(IdempotencyConflictError):
        capability.execute(dict(args, prompt=args["prompt"] + " changed"), idempotency_key=KEY)


def test_remote_output_paths_are_exact_sorted_files_not_directory_expansion(tmp_path):
    candidate = tmp_path / "prepared"
    put(candidate, "src/keep.txt", b"keep")
    put(candidate, "README.md", b"readme")
    before = files(candidate)
    assert module.remote_output_paths(before, ["src", "new.txt", "src/keep.txt"], candidate) == ["README.md", "new.txt", "src/keep.txt"]
    assert not (candidate / "new.txt").exists()
    assert artifacts.full_tree_manifest(candidate)["errors"] == []


@pytest.mark.parametrize("paths", [[".hidden"], ["auth.json"], ["sub/.git/config"], ["../bad"],
                                   ["/absolute"], ["x", "X"], ["x", "x/y"], ["pipe\x00name"]])
def test_remote_output_paths_reject_node_unsafe_path_and_collision_contract(tmp_path, paths):
    candidate = tmp_path / "prepared"
    candidate.mkdir()
    with pytest.raises(ValueError):
        module.remote_output_paths({}, paths, candidate)
    assert list(candidate.iterdir()) == []


def test_remote_output_path_union_128_bound_before_driver_offer(m, tmp_path, monkeypatch):
    # Reconstruct the fixture from this intentionally large initial source so
    # its frozen source hash is legitimate, not a post-admission input change.
    root = tmp_path / "large"
    root.mkdir()
    large_spec = make_spec(root)
    for number in range(128):
        put(Path(large_spec["source"]), "input-%03d.txt" % number, b"fixed")
    large = mission(root, large_spec)
    large._initial_plan()
    _, script, capability, args = remote(large, monkeypatch, root)
    result = capability.execute(args, idempotency_key=KEY)
    assert result.status == "ERROR" and result.observation.get("error")
    assert not script.instances and large.node_claims.get(KEY) is None
    assert not large.drivers["codex"].requests
    assert (large.directory / "attempts" / KEY / "candidate/README.md").read_bytes() == b"frozen fixture project"


@pytest.mark.parametrize("fault", ["extra-status", "invalid", "not-materialized", "missing-candidate", "missing-before",
                                  "delta-false", "delta-integer", "before-bytes", "before-extra-file", "before-hidden",
                                  "before-control", "before-empty-dir", "before-symlink", "before-fifo", "before-missing",
                                  "original-bytes", "original-hidden", "candidate-hidden", "candidate-symlink", "candidate-fifo",
                                  "before-original", "candidate-original", "before-snapshot", "candidate-snapshot"])
def test_known_native_terminal_rejects_invalid_materialization_and_full_tree_without_check_or_review(m, tmp_path, monkeypatch, fault):
    def inject(instance, receipt):
        mat = instance.driver.materialization
        assert receipt.status == "COMPLETED" and set(mat) == {"candidate", "before", "delta"}
        before, candidate = Path(mat["before"]), Path(mat["candidate"])
        if fault == "extra-status":
            mat["status"] = "MATERIALIZED"
        elif fault in {"invalid", "not-materialized"}:
            instance.driver.materialization = {"status": "INVALID" if fault == "invalid" else "NOT_MATERIALIZED", "report": {"errors": [{"code": "fixture"}]}}
        elif fault in {"missing-candidate", "missing-before"}:
            mat.pop("candidate" if fault == "missing-candidate" else "before")
        elif fault in {"delta-false", "delta-integer"}:
            mat["delta"]["valid"] = False if fault == "delta-false" else 1
        elif fault == "before-bytes":
            (before / "README.md").write_bytes(b"mismatched independent before")
        elif fault == "before-extra-file":
            put(before, "unexpected.txt", b"extra")
        elif fault == "before-hidden":
            put(before, ".hidden", b"unreported by mission.files")
        elif fault == "before-control":
            put(before, ".git/config", b"synthetic control")
        elif fault == "before-empty-dir":
            (before / "unexpected-empty").mkdir()
        elif fault in {"before-symlink", "candidate-symlink"}:
            root = before if fault == "before-symlink" else candidate
            (root / "link").symlink_to(root / "README.md")
        elif fault in {"before-fifo", "candidate-fifo"}:
            os.mkfifo((before if fault == "before-fifo" else candidate) / "pipe")
        elif fault == "before-missing":
            os.rename(before, before.with_name("retained-before"))
        elif fault in {"before-original", "candidate-original", "before-snapshot", "candidate-snapshot"}:
            field = "before" if fault.startswith("before-") else "candidate"
            mat[field] = instance.request.cwd if fault.endswith("original") else str(instance.kwargs["input_snapshot"])
        elif fault == "original-bytes":
            (Path(instance.request.cwd) / "README.md").write_bytes(b"original candidate changed")
        elif fault == "original-hidden":
            put(instance.request.cwd, ".sisyfus/fixture", b"unreported original change")
        else:
            put(candidate, ".hidden", b"unreported output change")

    _, script, capability, args = remote(m, monkeypatch, tmp_path, after=inject)
    source = artifacts.full_tree_manifest(m.spec["source"])
    result = capability.execute(args, idempotency_key=KEY)
    assert result.status == "COMPLETED" and result.observation["integrity_error"]
    assert result.observation["session_id"] == script.receipts[0].session_id
    assert "candidate" not in result.observation and "candidate_hash" not in result.observation
    monkeypatch.setattr(m.registry.get("workers.execute").verifier, "check", lambda *a: pytest.fail("invalid materialization reached check"))
    assert verify(m, args, result).verdict == Verdict.INVALID
    assert not m.drivers["codex"].requests and not m.drivers["claude"].requests
    assert not m.journal.records("reviews") and not m.journal.records("integrations")
    assert artifacts.full_tree_manifest(m.spec["source"]) == source
    assert Path(script.instances[0].kwargs["input_snapshot"]).exists()
    assert not m.snapshot()["all_verified"]


@pytest.mark.parametrize("native", ["ERROR", "INTERRUPTED"])
def test_native_noncompleted_with_invalid_materialization_keeps_original_error_gate(m, tmp_path, monkeypatch, native):
    def inject(instance, receipt):
        instance.driver.materialization = {"status": "INVALID", "report": {"errors": [{"code": "fixture"}]}}

    _, script, capability, args = remote(m, monkeypatch, tmp_path, native_status=native, after=inject)
    result = capability.execute(args, idempotency_key=KEY)
    assert result.status == native and result.observation["integrity_error"]
    assert result.observation["session_id"] == script.receipts[0].session_id
    assert verify(m, args, result).verdict == Verdict.ERROR
    assert not m.drivers["claude"].requests and not m.journal.records("integrations")


def test_transport_allowlisted_input_modification_still_fails_original_task_write_scope(m, tmp_path, monkeypatch):
    _, script, capability, args = remote(m, monkeypatch, tmp_path,
                                        changes={"README.md": b"out of original task ownership", "a.txt": b"42"})
    result = capability.execute(args, idempotency_key=KEY)
    assert result.status == "COMPLETED" and "README.md" in result.observation["scope_error"]
    assert script.instances[0].driver.materialization["delta"]["valid"] is True
    assert verify(m, args, result).verdict == Verdict.INVALID
    assert not m.drivers["claude"].requests and not m.drivers["codex"].requests
    assert (Path(m.spec["source"]) / "README.md").read_bytes() == b"frozen fixture project"


def test_unknown_receipt_fences_core_and_never_reoffers_or_uses_local_fallback(m, tmp_path, monkeypatch):
    _, script, capability, args = remote(m, monkeypatch, tmp_path, native_status="UNKNOWN")
    result = capability.execute(args, idempotency_key=KEY)
    assert result.status == "UNKNOWN" and raw_run(m)["status"] == "UNKNOWN"
    assert "candidate" not in result.observation and m.node_claims.get(KEY)["status"] == "UNKNOWN"
    assert capability.execute(args, idempotency_key=KEY).observation == result.observation
    assert len(script.instances) == len(script.requests) == 1 and not m.drivers["codex"].requests
    assert not m.snapshot()["all_verified"]


@pytest.mark.parametrize("when,expected", [("constructor", "ERROR"), ("run", "UNKNOWN")])
def test_driver_exception_boundary_keeps_known_prestart_vs_unknown_poststart(m, tmp_path, monkeypatch, when, expected):
    _, script, capability, args = remote(m, monkeypatch, tmp_path)

    def factory(*a, **kw):
        if when == "constructor":
            raise RuntimeError("fixture before driver.run")
        class Failure:
            materialization = None
            def run(self, *a, **kw):
                raise RuntimeError("fixture after driver.run entry")
        return Failure()

    monkeypatch.setattr(module, "RemoteCodexDriver", factory, raising=False)
    monkeypatch.setattr(remote_module, "RemoteCodexDriver", factory)
    result = capability.execute(args, idempotency_key=KEY)
    assert result.status == expected and result.observation["error"]
    assert not m.drivers["codex"].requests and not script.requests and m.node_claims.get(KEY) is None
    assert "candidate" not in result.observation


def test_unclaimed_deadline_is_known_nonexecution_not_local_fallback(m, tmp_path, monkeypatch):
    _, script, capability, args = remote(m, monkeypatch, tmp_path, no_work=True)
    result = capability.execute(args, idempotency_key=KEY)
    assert result.status == "ERROR"
    view = m.node_claims.get(KEY)
    assert view["status"] == "WITHDRAWN" and view["epoch"] == 0 and view["claim_id"] is None
    assert not m.drivers["codex"].requests and len(script.requests) == 1
    assert capability.execute(args, idempotency_key=KEY).observation == result.observation
    assert len(script.requests) == 1


def test_stop_posts_interrupt_with_one_real_sync_ack_not_driver_synthetic_ack(m, tmp_path, monkeypatch):
    _, script, capability, args = remote(m, monkeypatch, tmp_path, native_status="INTERRUPTED",
                                        changes={}, interrupt=True)
    result = capability.execute(args, idempotency_key=KEY)
    assert result.status == "INTERRUPTED"
    with m.store._transaction(immediate=False) as db:
        assert db.execute("SELECT status FROM remote_transport_controls WHERE id=?", (KEY + ":controller-stop",)).fetchone()[0] == "ACK"
        assert db.execute("SELECT count(*) FROM remote_event_sync WHERE kind='control_ack'").fetchone()[0] == 1
    assert script.events == []
    events = [e for e in m.journal.events(0, 1000) if e["run_key"] == KEY]
    assert sum(e["type"] == "WORKER_CONTROL_ACK" for e in events) == 1
    assert not m.drivers["codex"].requests and not m.drivers["claude"].requests


def test_core_lease_loss_after_driver_io_exposes_fence_and_retains_unknown_without_reoffer(m, tmp_path, monkeypatch):
    def inject(instance, receipt):
        with m.store._transaction() as db:
            db.execute("UPDATE continuations SET lease_token='fixture-changed-owner' WHERE id=?", (args["continuation_id"],))

    _, script, capability, args = remote(m, monkeypatch, tmp_path, after=inject)
    with pytest.raises(LeaseLost):
        capability.execute(args, idempotency_key=KEY)
    assert raw_run(m)["status"] == "IN_FLIGHT"
    assert m.journal.reconcile_expired() == 1 and raw_run(m)["status"] == "UNKNOWN"
    assert len(script.requests) == 1 and not m.drivers["codex"].requests
    assert Path(script.instances[0].kwargs["input_snapshot"]).exists()
    assert Path(script.instances[0].driver.materialization["candidate"]).exists()
    assert not m.snapshot()["all_verified"]


def test_native_model_attestation_mismatch_keeps_original_precheck_gate(m, tmp_path, monkeypatch):
    _, _, capability, args = remote(m, monkeypatch, tmp_path, actual="fixture-native-other-model")
    result = capability.execute(args, idempotency_key=KEY)
    assert result.status == "COMPLETED" and result.observation["actual_model"] == "fixture-native-other-model"
    assert verify(m, args, result).verdict == Verdict.INVALID
    assert not m.drivers["claude"].requests
