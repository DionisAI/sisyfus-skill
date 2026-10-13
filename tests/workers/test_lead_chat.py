"""Retained chat boundaries with fake Receipts and a missing-executable launch.

Reuse the console's DB-backed mission fixture. Event gates make reservation and
busy-state assertions deterministic; the retained runner owns all temp paths.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sisyfus.workers import lead_chat
from sisyfus.workers.lead_chat import MODEL, ChatSessions
from sisyfus.workers.lead_console import LeadConsole, MissionHub, PAGE, approved_spec
from sisyfus.workers.lead_contracts import load_lead_spec
from sisyfus.workers.protocol import Receipt, digest
from test_lead_console import StubMission, make_spec, request


def plan_reply():
    return {
        "reply": "规划已整理；等待你在开工按钮上明确确认。",
        "proposal": {
            "objective": "Add the agreed chat interface and retain fixed acceptance.",
            "architecture": "Chat draft -> explicit confirmation -> core mission controller.",
            "deliverables": ["Operator-owned console", "Conversation interface"],
            "constraints": ["Keep immutable acceptance", "Read-only planning before confirmation"],
            "tasks": [
                {"title": "Build conversation", "acceptance": "Fixed checker passes", "depends_on": []},
                {"title": "Review interface", "acceptance": "Independent review passes", "depends_on": ["Build conversation"]},
            ],
        },
    }


def completed(output=None, *, actual_model=MODEL):
    return Receipt(
        "COMPLETED", session_id="fixture-native-session", exit_code=0,
        output=json.dumps(plan_reply(), ensure_ascii=False) if output is None else output,
        requested_model=MODEL, actual_model=actual_model,
    )


class FakeDriver:
    """A receipt fixture, not model attestation or an executable native driver."""

    def __init__(self, receipt=None, *, failure=None):
        self.receipt = receipt if receipt is not None else completed()
        self.failure = failure
        self.calls = []
        self.chat_root = None
        self.reservations = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def run(self, native_request, emit):
        self.calls.append(native_request)
        # Inspect the durable reservation at the actual dispatch boundary.
        request_id = native_request.task_id.removeprefix("chat-")
        reservations = [json.loads(path.read_text()) for path in self.chat_root.glob("c_*/draft.json")]
        matches = [s for s in reservations if s["status"] == "RUNNING" and request_id in s["requests"]]
        if len(matches) != 1:
            raise AssertionError("fake dispatch did not have exactly one durable reservation")
        self.reservations.append(matches[0])
        emit("fixture_started", {"model": native_request.model})
        self.entered.set()
        if not self.release.wait(5):
            raise RuntimeError("fake driver release timed out")
        if self.failure is not None:
            raise self.failure
        return self.receipt


def draft_path(chats, ident):
    return chats.root / ident / "draft.json"


def stored(chats, ident):
    return json.loads(draft_path(chats, ident).read_text())


def finish(chats, ident):
    thread = chats.threads[ident]
    thread.join(5)
    assert not thread.is_alive(), "fake reply thread did not finish"
    return chats.get(ident)


def start_chat(chats, ident, permission, request_id):
    """Normal confirmation uses the exact public plan the caller just read."""
    return chats.start(ident, permission, request_id, chats.get(ident)["approval_hash"])


def attach(chats, spec_file):
    ident = chats.create()["id"]
    chats.context(ident, spec_path=str(spec_file))
    return ident


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def unexpected_native(*args, **kwargs):
        pytest.fail("chat test reached a real native driver")

    original_native_run = lead_chat.ClaudeCodeDriver.run
    monkeypatch.setattr(lead_chat.ClaudeCodeDriver, "run", unexpected_native)
    monkeypatch.setattr(StubMission, "created", [])
    monkeypatch.setattr(StubMission, "block", True)
    monkeypatch.setattr(StubMission, "failure", None)
    return original_native_run


@pytest.fixture
def hub(tmp_path):
    value = MissionHub(tmp_path / "hub", mission_factory=StubMission)
    yield value
    value.close()


@pytest.fixture
def driver():
    return FakeDriver()


@pytest.fixture
def chat_factory(hub, driver):
    services = []

    def create(*, fake=None):
        fake = driver if fake is None else fake
        service = ChatSessions(hub, driver=fake)
        fake.chat_root = service.root
        services.append((service, fake))
        return service

    yield create
    for service, fake in reversed(services):
        if isinstance(fake, FakeDriver):
            fake.release.set()
        if not service.owner.closed:
            service.close()


@pytest.fixture
def chats(chat_factory):
    return chat_factory()


@pytest.fixture
def spec(tmp_path):
    value = make_spec(tmp_path)
    value.update(
        constraints=["Keep immutable acceptance", "Keep the operator's source intact"],
        deliverables=["Operator-owned console", "Fixed acceptance evidence"],
        roles={"lead": {"driver": "claude", "model": MODEL},
               "worker": {"driver": "codex", "model": "gpt-6.1-sol"},
               "reviewer": {"driver": "claude", "model": MODEL}},
        drivers={"claude": {"model": MODEL, "command": ["fixture-claude"]},
                 "codex": {"model": "gpt-6.1-sol", "command": ["fixture-codex"]}},
        max_calls=19, max_iterations=7, max_tokens=100000, max_cost_usd=3.0,
    )
    return value


@pytest.fixture
def spec_file(spec, tmp_path):
    path = tmp_path / "approved-spec.json"
    path.write_text(json.dumps(spec))
    return path


@pytest.fixture
def ready_chat(chats, spec_file):
    ident = attach(chats, spec_file)
    chats.message(ident, "规划工程，保留全部验收条件。", "plan-request-01")
    assert finish(chats, ident)["readiness"]["ready"] is True
    return ident


@pytest.fixture
def server(hub, chats):
    value = LeadConsole(hub, port=0)
    value._chats = chats  # Inject the same fake-only service at the HTTP boundary.
    thread = threading.Thread(target=value.serve_forever, daemon=True)
    thread.start()
    yield value
    value.shutdown()
    value.server_close()
    thread.join(5)
    assert not thread.is_alive()


def assert_no_mission(hub):
    assert hub.inventory()["missions"] == []
    assert StubMission.created == []
    assert not list(hub.directory.rglob("autonomy.sqlite3"))


def test_create_get_inventory_are_durable_without_dispatch(chats, driver, hub):
    state = chats.create()
    ident = state["id"]
    assert ident.startswith("c_") and len(ident) == 34
    assert state["status"] == "IDLE" and state["messages"] == []
    assert state["proposal"] is None and state["mission_id"] is None
    assert state["checks"] == [] and state["readiness"]["ready"] is False
    assert state["model"] == {"requested": MODEL, "actual": None}
    assert not {"bound_spec", "requests", "native_session"} & state.keys()
    assert chats.get(ident) == state
    inventory = chats.inventory()
    assert inventory["auto_start"] is False
    assert [row["id"] for row in inventory["chats"]] == [ident]
    assert stored(chats, ident)["requests"] == {}
    assert draft_path(chats, ident).stat().st_mode & 0o777 == 0o600
    assert driver.calls == []
    assert_no_mission(hub)
    state["messages"].append({"role": "user", "text": "not persisted"})
    assert chats.get(ident)["messages"] == []


def test_attached_context_preserves_operator_checks_and_source_override(chats, spec, spec_file, tmp_path, driver, hub):
    alternate = tmp_path / "alternate-project"
    alternate.mkdir()
    ident = chats.create()["id"]
    state = chats.context(ident, source=str(alternate), spec_path=str(spec_file))
    assert state["source"] == str(alternate.resolve())
    assert state["spec_path"] == str(spec_file.resolve())
    assert state["readiness"]["ready"] is False
    check = spec["checks"]["fixed"]["contract"]
    assert state["checks"] == [{"id": "fixed", "pass_if": check["pass_if"], "fail_if": check["fail_if"]}]
    bound = stored(chats, ident)["bound_spec"]
    assert bound["checks"] == spec["checks"]
    assert bound["roles"] == spec["roles"] and bound["constraints"] == spec["constraints"]
    assert bound["source"] == str(alternate)
    assert json.loads(spec_file.read_text()) == spec
    assert driver.calls == []
    assert_no_mission(hub)


@pytest.mark.parametrize("change", ["source", "spec_path", "spec_contents"])
def test_context_changes_invalidate_proposal_and_native_session(chats, ready_chat, spec, spec_file, tmp_path, driver, hub, change):
    ident = ready_chat
    before = chats.get(ident)
    unchanged = chats.context(ident, spec_path=str(spec_file))
    assert unchanged["proposal"] == before["proposal"]
    assert unchanged["messages"] == before["messages"]
    assert stored(chats, ident)["native_session"] == "fixture-native-session"
    source, path = "", str(spec_file)
    if change == "source":
        alternate = tmp_path / "new-project"
        alternate.mkdir()
        source = str(alternate)
    elif change == "spec_path":
        alternate = tmp_path / "another-approved-spec.json"
        alternate.write_text(spec_file.read_text())
        path = str(alternate)
    else:
        changed = copy.deepcopy(spec)
        changed["constraints"].append("New operator-owned constraint")
        spec_file.write_text(json.dumps(changed))
    result = chats.context(ident, source, path)
    assert result["proposal"] is None and result["readiness"]["ready"] is False
    assert result["messages"][:-1] == before["messages"]
    assert stored(chats, ident)["native_session"] is None
    assert stored(chats, ident)["bound_spec"]["checks"] == spec["checks"]
    assert len(driver.calls) == 1
    assert_no_mission(hub)
    chats.message(ident, "按更新后的工程重新规划。", "new-plan-request")
    assert finish(chats, ident)["readiness"]["ready"] is True
    assert driver.calls[-1].session_id is None


def test_async_reservation_and_concurrent_duplicate_dispatch_exactly_once(chats, driver, hub):
    ident = chats.create()["id"]
    driver.release.clear()
    text, request_id = "聊需求，不启动任务。", "message-request-01"
    try:
        result = chats.message(ident, text, request_id)
        assert result["status"] == "RUNNING"
        assert driver.entered.wait(3)
        reservation = driver.reservations[0]
        assert reservation["status"] == "RUNNING"
        assert reservation["requests"][request_id] == {"kind": "message", "hash": hashlib.sha256(text.encode()).hexdigest()}
        with ThreadPoolExecutor(max_workers=4) as pool:
            duplicates = list(pool.map(lambda _: chats.message(ident, text, request_id), range(6)))
        assert all(s["status"] == "RUNNING" for s in duplicates)
        with pytest.raises(ValueError, match="another operation"):
            chats.message(ident, "different content", request_id)
        assert len(driver.calls) == 1
        assert [x["id"] for x in chats.get(ident)["messages"] if x["role"] == "user"] == [request_id]
        assert_no_mission(hub)
    finally:
        driver.release.set()
    state = finish(chats, ident)
    assert state["status"] == "IDLE"
    assert chats.message(ident, text, request_id) == state
    assert len(driver.calls) == 1
    assert len([m for m in state["messages"] if m.get("kind") == "opus"]) == 1
    with pytest.raises(ValueError, match="another operation"):
        start_chat(chats, ident, True, request_id)


def test_busy_chat_rejects_new_message_context_and_start(chats, driver, spec_file, hub):
    ident = attach(chats, spec_file)
    driver.release.clear()
    try:
        chats.message(ident, "准备规划。", "busy-request-01")
        assert driver.entered.wait(3)
        before = stored(chats, ident)
        with pytest.raises(RuntimeError, match="active"):
            chats.message(ident, "another message", "busy-request-02")
        with pytest.raises(RuntimeError, match="active"):
            chats.context(ident, spec_path=str(spec_file))
        with pytest.raises(RuntimeError, match="active"):
            start_chat(chats, ident, True, "busy-start-01")
        assert stored(chats, ident) == before
        assert len(driver.calls) == 1
        assert_no_mission(hub)
    finally:
        driver.release.set()
    finish(chats, ident)


def test_valid_reply_needs_attached_spec_and_never_binds_from_chat(chats, spec_file, spec, driver, hub):
    ident = chats.create()["id"]
    chats.message(ident, "确认开工", "unbound-plan-01")
    unbound = finish(chats, ident)
    assert unbound["proposal"] == plan_reply()["proposal"]
    assert unbound["readiness"]["ready"] is False and unbound["mission_id"] is None
    attached = chats.context(ident, spec_path=str(spec_file))
    assert attached["proposal"] is None and attached["readiness"]["ready"] is False
    chats.message(ident, "确认开工，先完成规划。", "attached-plan-01")
    state = finish(chats, ident)
    assert state["status"] == "IDLE" and state["readiness"]["ready"] is True
    assert state["model"] == {"requested": MODEL, "actual": MODEL}
    assert state["proposal"] == plan_reply()["proposal"]
    native = driver.calls[-1]
    assert native.model == MODEL and native.mode == "read-only"
    assert native.cwd == spec["source"]
    assert driver.calls[0].cwd == str(chats.root / ident)
    assert native.max_turns is None and native.session_id is None
    context = json.loads(native.prompt.split("Context:\n", 1)[1])
    assert context["source"] == spec["source"]
    assert context["approved_objective"] == spec["objective"]
    assert context["constraints"] == spec["constraints"]
    assert context["deliverables"] == spec["deliverables"]
    assert context["check_names"] == ["fixed"]
    assert "checks" not in context and "roles" not in context
    assert_no_mission(hub)
    chats.message(ident, "补充一条讨论。", "continuation-01")
    assert finish(chats, ident)["status"] == "IDLE"
    assert driver.calls[-1].session_id == "fixture-native-session"
    assert_no_mission(hub)


@pytest.mark.parametrize("output", [
    "{", "plain model prose", "[]",
    '{"reply":"first","reply":"second","proposal":null}',
    '{"reply":"ok","proposal":NaN}',
    '{"reply":"","proposal":null}',
    '{"reply":"ok","proposal":{"objective":"incomplete"}}',
])
def test_invalid_json_is_error_without_automatic_retry(chats, chat_factory, driver, spec_file, hub, output):
    driver.receipt = completed(output)
    ident = attach(chats, spec_file)
    text, request_id = "plan this", "invalid-json-01"
    chats.message(ident, text, request_id)
    state = finish(chats, ident)
    assert state["status"] == "ERROR" and state["proposal"] is None
    assert state["error"]["type"] and state["error"]["message"]
    assert state["readiness"]["ready"] is False
    assert not [m for m in state["messages"] if m.get("kind") == "opus"]
    assert chats.message(ident, text, request_id) == state
    chats.close()
    restarted = chat_factory()
    assert restarted.get(ident) == state
    assert restarted.message(ident, text, request_id) == state
    assert len(driver.calls) == 1
    assert_no_mission(hub)


@pytest.mark.parametrize("location,field", [
    ("proposal", "commands"), ("proposal", "checks"), ("proposal", "roles"),
    ("proposal", "budgets"), ("proposal", "tools"), ("proposal", "drivers"),
    ("task", "argv"), ("task", "check"), ("reply", "allow_local_workers"),
])
def test_model_invented_executable_or_authority_fields_are_errors(chats, driver, spec_file, hub, location, field):
    raw = plan_reply()
    target = raw if location == "reply" else (raw["proposal"] if location == "proposal" else raw["proposal"]["tasks"][0])
    target[field] = "model-invented-field"
    driver.receipt = completed(json.dumps(raw))
    ident = attach(chats, spec_file)
    chats.message(ident, "plan only", "invented-field-01")
    state = finish(chats, ident)
    assert state["status"] == "ERROR" and state["error"]["type"] == "ValueError"
    assert state["proposal"] is None and state["readiness"]["ready"] is False
    with pytest.raises(ValueError):
        start_chat(chats, ident, True, "invented-start-01")
    assert len(driver.calls) == 1
    assert_no_mission(hub)


def test_runtime_model_mismatch_surfaces_error(chats, driver, spec_file, hub):
    driver.receipt = completed(actual_model="gpt-6.1-sol")
    ident = attach(chats, spec_file)
    chats.message(ident, "plan only", "model-mismatch-01")
    state = finish(chats, ident)
    assert state["status"] == "ERROR" and state["proposal"] is None
    assert state["error"]["type"] == "ValueError"
    assert "runtime-attested" in state["error"]["message"]
    receipt = json.loads((chats.root / ident / "receipt_model-mismatch-01.json").read_text())
    assert receipt["actual_model"] == "gpt-6.1-sol"
    assert state["model"] == {"requested": MODEL, "actual": "gpt-6.1-sol"}
    assert state["readiness"]["ready"] is False and len(driver.calls) == 1
    assert_no_mission(hub)


@pytest.mark.parametrize("transport_exception", [False, True])
def test_unknown_receipt_is_fenced_across_restart(chats, chat_factory, driver, hub, transport_exception):
    if transport_exception:
        driver.failure = RuntimeError("fixture transport lost its result")
    else:
        driver.receipt = Receipt("UNKNOWN", requested_model=MODEL, error="fixture result uncertain")
    ident = chats.create()["id"]
    text, request_id = "plan only", "unknown-request-01"
    chats.message(ident, text, request_id)
    state = finish(chats, ident)
    assert state["status"] == "UNKNOWN" and state["proposal"] is None
    assert state["error"]["type"] == "NativeOutcomeUnknown"
    assert state["error"]["message"] and state["readiness"]["ready"] is False
    receipt_file = chats.root / ident / ("receipt_" + request_id + ".json")
    events_file = chats.root / ident / ("events_" + request_id + ".jsonl")
    assert json.loads(receipt_file.read_text())["status"] == "UNKNOWN"
    assert receipt_file.stat().st_mode & 0o777 == 0o600
    assert events_file.stat().st_mode & 0o777 == 0o600
    assert json.loads(events_file.read_text().splitlines()[0])["kind"] == "fixture_started"
    chats.close()
    fresh_driver = FakeDriver()
    restarted = chat_factory(fake=fresh_driver)
    assert restarted.get(ident) == state
    assert restarted.inventory()["chats"][0]["status"] == "UNKNOWN"
    assert restarted.message(ident, text, request_id) == state
    for action in (
        lambda: restarted.message(ident, "new message", "unknown-request-02"),
        lambda: restarted.context(ident),
        lambda: start_chat(restarted, ident, True, "unknown-start-01"),
    ):
        with pytest.raises(RuntimeError, match="reconciliation"):
            action()
    assert len(driver.calls) == 1 and fresh_driver.calls == []
    assert_no_mission(hub)


@pytest.mark.parametrize("interrupted_status", ["RUNNING", "STARTING"])
def test_restart_fences_unreceipted_reservation_without_dispatch(chats, chat_factory, driver, hub, ready_chat, interrupted_status):
    ident = ready_chat if interrupted_status == "STARTING" else chats.create()["id"]
    calls_before = len(driver.calls)
    approval_hash = chats.get(ident)["approval_hash"]
    chats.close()
    # Simulate a process dying after its durable reservation, not a native call.
    state = stored(chats, ident)
    state["status"] = interrupted_status
    request_id = "interrupted-request"
    text = "reserved request"
    state["requests"][request_id] = ({"kind": "start", "approval_hash": approval_hash} if interrupted_status == "STARTING" else
                                      {"kind": "message", "hash": hashlib.sha256(text.encode()).hexdigest()})
    draft_path(chats, ident).write_text(json.dumps(state))
    restarted = chat_factory()
    fenced = restarted.get(ident)
    assert fenced["status"] == "UNKNOWN"
    assert fenced["error"]["type"] == "InterruptedRequest"
    replay = (start_chat(restarted, ident, True, request_id) if interrupted_status == "STARTING" else
              restarted.message(ident, text, request_id))
    assert replay == fenced
    with pytest.raises(RuntimeError, match="reconciliation"):
        restarted.message(ident, "new message", "new-interrupted-request")
    with pytest.raises(RuntimeError, match="reconciliation"):
        restarted.context(ident)
    assert len(driver.calls) == calls_before
    assert_no_mission(hub)


@pytest.mark.parametrize("permission", [False, None, 1, 1.0, "true", "True", [], {}])
def test_start_requires_literal_true(chats, ready_chat, driver, hub, permission):
    before = stored(chats, ready_chat)
    with pytest.raises(PermissionError):
        start_chat(chats, ready_chat, permission, "permission-start")
    assert stored(chats, ready_chat) == before
    assert len(driver.calls) == 1
    assert_no_mission(hub)


@pytest.mark.parametrize("missing", ["both", "spec", "proposal", "null_proposal"])
def test_start_requires_approved_spec_and_complete_proposal(chats, driver, spec_file, hub, missing):
    ident = chats.create()["id"]
    if missing in {"proposal", "null_proposal"}:
        chats.context(ident, spec_path=str(spec_file))
    if missing in {"spec", "null_proposal"}:
        if missing == "null_proposal":
            driver.receipt = completed('{"reply":"请补充需求。","proposal":null}')
        chats.message(ident, "plan only", "missing-plan-01")
        finish(chats, ident)
    assert chats.get(ident)["readiness"]["ready"] is False
    with pytest.raises(ValueError):
        start_chat(chats, ident, True, "missing-start-01")
    assert "missing-start-01" not in stored(chats, ident)["requests"]
    assert_no_mission(hub)


def test_explicit_start_binds_exactly_one_mission_and_preserves_approved_truth(chats, ready_chat, spec, driver, hub):
    approved = load_lead_spec(spec)
    state = start_chat(chats, ready_chat, True, "confirmed-start-01")
    ident = state["mission_id"]
    assert ident and state["status"] == "IDLE"
    assert state["readiness"]["ready"] is False
    assert len(StubMission.created) == 1
    mission = StubMission.created[0]
    assert mission.started.wait(3) and mission.calls == 1
    assert mission.last_cycles is None
    bound = approved_spec(hub.path(ident))
    assert bound["objective"].startswith(spec["objective"] + "\n\nOperator-confirmed conversation plan:\n")
    assert plan_reply()["proposal"]["objective"] in bound["objective"]
    assert plan_reply()["proposal"]["architecture"] in bound["objective"]
    assert json.dumps(plan_reply()["proposal"]["tasks"], ensure_ascii=False) in bound["objective"]
    for key in ("checks", "required_checks", "integration_checks", "roles", "drivers", "acceptance_hash",
                "max_calls", "max_iterations", "max_tokens", "max_cost_usd", "max_wall_minutes", "source"):
        assert bound[key] == approved[key], key
    for key in ("constraints", "deliverables"):
        assert bound[key] == list(dict.fromkeys([*spec[key], *plan_reply()["proposal"][key]]))
    assert not bound.get("tasks") and "initial_plan" not in bound
    assert not {"commands", "tools", "budgets", "argv"} & bound.keys()
    assert start_chat(chats, ready_chat, True, "confirmed-start-01") == state
    assert len(StubMission.created) == 1 and mission.calls == 1 and len(driver.calls) == 1
    assert [c["action"] for c in hub.controls(ident)] == ["start"]
    assert mission.store.verify_event_chain()["valid"]
    assert hub.snapshot(ident)["snapshot"]["all_verified"] is False


def test_start_revalidates_checker_hash_after_chat(chats, ready_chat, spec, driver, hub):
    checker = Path(next(iter(spec["checks"]["fixed"]["code_hashes"])))
    checker.write_text("print('mutated after planning')\n")
    before = stored(chats, ready_chat)
    with pytest.raises(ValueError, match="hash mismatch"):
        start_chat(chats, ready_chat, True, "mutated-start-01")
    assert stored(chats, ready_chat) == before
    assert "mutated-start-01" not in before["requests"]
    assert len(driver.calls) == 1
    assert_no_mission(hub)


def test_bound_chat_blocks_messages_and_context_and_mapping_survives_restart(chats, ready_chat, spec_file, chat_factory, driver, hub):
    state = start_chat(chats, ready_chat, True, "bound-start-01")
    assert StubMission.created[0].started.wait(3)
    for action in (
        lambda: chats.message(ready_chat, "change the task", "bound-message-01"),
        lambda: chats.context(ready_chat, spec_path=str(spec_file)),
        lambda: start_chat(chats, ready_chat, True, "bound-start-02"),
    ):
        with pytest.raises(RuntimeError, match="immutable mission"):
            action()
    assert chats.get(ready_chat) == state
    chats.close()
    restarted = chat_factory()
    assert restarted.get(ready_chat) == state
    assert restarted.inventory()["chats"][0]["mission_id"] == state["mission_id"]
    assert start_chat(restarted, ready_chat, True, "bound-start-01") == state
    with pytest.raises(RuntimeError, match="immutable mission"):
        restarted.message(ready_chat, "new message", "reopened-message-01")
    with pytest.raises(RuntimeError, match="immutable mission"):
        restarted.context(ready_chat)
    assert len(driver.calls) == 1 and len(StubMission.created) == 1
    assert StubMission.created[0].calls == 1


@pytest.mark.parametrize("case,exception,diagnostic", [
    ("missing_source", FileNotFoundError, "No such file"),
    ("file_source", ValueError, "工程"),
    ("control_source", ValueError, "工程"),
    ("source_parent", ValueError, "工程"),
    ("missing_spec", FileNotFoundError, "No such file"),
    ("invalid_json", ValueError, "Expecting"),
    ("missing_pass", ValueError, "PASS"),
    ("missing_fail", ValueError, "通过与失败"),
    ("mutated_checker", ValueError, "hash mismatch"),
    ("wrong_type", ValueError, "must be text"),
])
def test_context_errors_surface_and_leave_previous_context_intact(chats, ready_chat, spec, spec_file, tmp_path, hub, driver, case, exception, diagnostic):
    source, path = "", str(spec_file)
    if case == "missing_source":
        source, path = str(tmp_path / "missing-project"), ""
    elif case == "file_source":
        source, path = str(spec_file), ""
    elif case == "control_source":
        source, path = str(hub.directory), ""
    elif case == "source_parent":
        source, path = str(tmp_path), ""
    elif case == "missing_spec":
        path = str(tmp_path / "missing-spec.json")
    elif case == "invalid_json":
        spec_file.write_text("{")
    elif case in {"missing_pass", "missing_fail"}:
        invalid = copy.deepcopy(spec)
        invalid["checks"]["fixed"]["contract"].pop("pass_if" if case == "missing_pass" else "fail_if")
        spec_file.write_text(json.dumps(invalid))
    elif case == "mutated_checker":
        Path(next(iter(spec["checks"]["fixed"]["code_hashes"]))).write_text("print('changed')\n")
    else:
        source = None
    before = stored(chats, ready_chat)
    with pytest.raises(exception, match=diagnostic):
        chats.context(ready_chat, source, path)
    assert stored(chats, ready_chat) == before
    assert len(driver.calls) == 1
    assert_no_mission(hub)


def test_owner_lock_close_and_idle_persistence(chats, ready_chat, chat_factory, driver, hub):
    before = chats.get(ready_chat)
    with pytest.raises(RuntimeError, match="active owner"):
        chat_factory()
    chats.close()
    assert chats.owner.closed
    with pytest.raises(RuntimeError, match="closing"):
        chats.create()
    with pytest.raises(RuntimeError, match="closing"):
        chats.message(ready_chat, "new message", "closed-message-01")
    reopened = chat_factory()
    assert reopened.get(ready_chat) == before
    assert stored(reopened, ready_chat)["native_session"] == "fixture-native-session"
    assert reopened.inventory()["auto_start"] is False
    assert len(driver.calls) == 1
    assert_no_mission(hub)


@pytest.mark.parametrize("path,body", [
    ("/api/chats", None), ("/api/chat?chat_id=invalid", None),
    ("/api/chats", {}),
    ("/api/chat/attach_mission", {"chat_id": "invalid", "mission_id": "missing"}),
    ("/api/chat/context", {"chat_id": "invalid", "source": "", "spec_path": ""}),
    ("/api/chat/message", {"chat_id": "invalid", "message": "plan", "request_id": "http-request-01"}),
    ("/api/chat/start", {"chat_id": "invalid", "allow_local_workers": True, "request_id": "http-start-01", "approval_hash": "a" * 64}),
])
def test_http_chat_routes_enforce_auth_host_and_origin(server, driver, hub, path, body):
    assert request(server, path, body=body, auth=False)[0] == 401
    assert request(server, path, body=body, headers={"Authorization": "Bearer invalid-token"})[0] == 401
    assert request(server, path, body=body, headers={"Host": "attacker.test"})[0] == 403
    assert request(server, path, body=body, headers={"Origin": "https://attacker.test"})[0] == 403
    assert request(server, path, body=body, headers={"Origin": "null"})[0] == 403
    assert server.chats.inventory()["chats"] == [] and driver.calls == []
    assert_no_mission(hub)


@pytest.mark.parametrize("path,body", [
    ("/api/chats", {"source": "not-allowed"}),
    ("/api/chat/attach_mission", {"chat_id": "invalid"}),
    ("/api/chat/attach_mission", {"chat_id": "invalid", "mission_id": "missing", "spec": {}}),
    ("/api/chat/context", {"chat_id": "invalid", "source": ""}),
    ("/api/chat/context", {"chat_id": "invalid", "source": "", "spec_path": "", "checks": {}}),
    ("/api/chat/message", {"chat_id": "invalid", "message": "plan"}),
    ("/api/chat/message", {"chat_id": "invalid", "message": "plan", "request_id": "http-request-01", "commands": []}),
    ("/api/chat/start", {"chat_id": "invalid", "request_id": "http-start-01"}),
    ("/api/chat/start", {"chat_id": "invalid", "request_id": "http-start-01", "allow_local_workers": True, "approval_hash": "a" * 64, "spec": {}}),
    ("/api/chat/start", {"chat_id": "invalid", "request_id": "http-start-01", "allow_local_workers": True}),
])
def test_http_chat_rejects_missing_and_extra_fields(server, driver, hub, path, body):
    status, raw, headers = request(server, path, body=body)
    assert status == 400
    error = json.loads(raw)["error"]
    assert error["type"] == "ValueError" and error["message"]
    assert headers["Cache-Control"] == "no-store"
    assert driver.calls == [] and server.chats.inventory()["chats"] == []
    assert_no_mission(hub)


@pytest.mark.parametrize("query", ["", "chat_id=", "chat_id=../outside", "chat_id=x", "chat_id=x&chat_id=y", "chat_id=x&extra=1"])
def test_http_get_chat_requires_one_fixed_id(server, query, driver):
    status, raw, _ = request(server, "/api/chat?" + query)
    assert status == 400
    assert json.loads(raw)["error"]["message"]
    assert driver.calls == []


@pytest.mark.parametrize("fields", [
    {"message": ""}, {"message": " "}, {"message": "x" * 12001}, {"message": 4},
    {"request_id": "short"}, {"request_id": "../outside"}, {"request_id": None},
])
def test_http_message_rejects_invalid_values_without_dispatch(server, fields, driver):
    ident = server.chats.create()["id"]
    body = {"chat_id": ident, "message": "plan", "request_id": "valid-request-01", **fields}
    status, raw, _ = request(server, "/api/chat/message", body=body)
    assert status == 400 and json.loads(raw)["error"]["message"]
    assert server.chats.get(ident)["messages"] == [] and driver.calls == []


def test_http_context_errors_are_visible_and_redacted(server, tmp_path, driver):
    ident = server.chats.create()["id"]
    body = {"chat_id": ident, "source": "", "spec_path": str(tmp_path / "missing.json")}
    status, raw, _ = request(server, "/api/chat/context", body=body)
    assert status == 404 and json.loads(raw)["error"]["type"] == "FileNotFoundError"
    # A reflected credential-shaped path must not leak its bearer value.
    body["source"], body["spec_path"] = "Bearer fixture-secret-token", ""
    status, raw, _ = request(server, "/api/chat/context", body=body)
    assert status == 404 and b"fixture-secret-token" not in raw
    body["source"] = None
    status, raw, _ = request(server, "/api/chat/context", body=body)
    assert status == 400 and json.loads(raw)["error"]["type"] == "ValueError"
    assert server.chats.get(ident)["source"] == "" and driver.calls == []


def test_http_chat_lifecycle_has_separate_explicit_idempotent_start(server, driver, spec_file, hub):
    status, raw, _ = request(server, "/api/chats", body={})
    assert status == 201
    ident = json.loads(raw)["id"]
    assert json.loads(request(server, "/api/chats")[1])["auto_start"] is False
    context = {"chat_id": ident, "source": "", "spec_path": str(spec_file)}
    assert request(server, "/api/chat/context", body=context)[0] == 200
    driver.release.clear()
    message = {"chat_id": ident, "message": "确认开工，先完成规划。", "request_id": "http-message-01"}
    try:
        status, raw, _ = request(server, "/api/chat/message", body=message)
        assert status == 202 and json.loads(raw)["status"] == "RUNNING"
        assert driver.entered.wait(3)
        assert request(server, "/api/chat/message", body=message)[0] == 202
        assert request(server, "/api/chat/message", body={**message, "message": "different"})[0] == 400
        assert request(server, "/api/chat/message", body={**message, "request_id": "http-message-02"})[0] == 409
        assert request(server, "/api/chat/context", body=context)[0] == 409
        assert len(driver.calls) == 1
        assert_no_mission(hub)
    finally:
        driver.release.set()
    finish(server.chats, ident)
    status, raw, _ = request(server, "/api/chat?chat_id=" + ident)
    assert status == 200 and json.loads(raw)["readiness"]["ready"] is True
    start = {"chat_id": ident, "allow_local_workers": "true", "request_id": "http-start-01",
             "approval_hash": json.loads(raw)["approval_hash"]}
    assert request(server, "/api/chat/start", body=start)[0] == 403
    assert_no_mission(hub)
    start["allow_local_workers"] = True
    status, raw, _ = request(server, "/api/chat/start", body=start)
    assert status == 202
    state = json.loads(raw)
    assert state["mission_id"] and StubMission.created[0].started.wait(3)
    assert json.loads(request(server, "/api/chat/start", body=start)[1]) == state
    assert request(server, "/api/chat/message", body={**message, "request_id": "http-message-03"})[0] == 409
    assert request(server, "/api/chat/context", body=context)[0] == 409
    assert len(StubMission.created) == 1 and StubMission.created[0].calls == 1
    assert len(driver.calls) == 1


def test_http_console_keeps_existing_page_and_security_headers(server, driver):
    status, raw, headers = request(server, "/console", auth=False)
    assert status == 200 and headers["Cache-Control"] == "no-store"
    nonce = headers["Content-Security-Policy"].split("script-src 'nonce-", 1)[1].split("'", 1)[0]
    assert raw.decode() == PAGE.replace("NONCE", nonce)
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert server.token.encode() not in raw
    assert request(server, "/console", auth=False, headers={"Host": "attacker.test"})[0] == 403
    assert request(server, "/console", auth=False, headers={"Origin": "https://attacker.test"})[0] == 403
    assert driver.calls == []


def test_http_root_delivers_new_chat_page_not_old_console(server, driver):
    status, raw, headers = request(server, "/", auth=False)
    assert status == 200, raw.decode()
    from sisyfus.workers.lead_chat_page import PAGE as CHAT_PAGE
    nonce = headers["Content-Security-Policy"].split("script-src 'nonce-", 1)[1].split("'", 1)[0]
    assert raw.decode() == CHAT_PAGE.replace("NONCE", nonce)
    assert raw.decode() != PAGE.replace("NONCE", nonce)
    assert headers["Cache-Control"] == "no-store" and server.token.encode() not in raw
    assert driver.calls == []


@pytest.mark.parametrize("operator_dag", [False, True])
def test_attach_mission_reuses_only_approved_contract_without_results_or_dispatch(chats, ready_chat, spec, driver, hub, operator_dag):
    raw = copy.deepcopy(spec)
    if operator_dag:
        raw["tasks"] = [{"id": "operator-build", "objective": "Build the operator's interface",
                         "depends_on": [], "check": "fixed", "write_paths": ["console.py"],
                         "acceptance": "Retain fixed PASS and FAIL branches"}]
    original_id = hub.create(raw)["id"]
    original = approved_spec(hub.path(original_id))
    old_snapshot = hub.snapshot(original_id)
    prior_messages = chats.get(ready_chat)["messages"]
    attached = chats.attach_mission(ready_chat, original_id)
    copied_path = Path(attached["spec_path"])
    assert copied_path.parent == chats.root / ready_chat
    assert copied_path.stat().st_mode & 0o777 == 0o600
    copied = json.loads(copied_path.read_text())
    assert load_lead_spec(copied) == original
    assert copied["checks"] == original["checks"] and copied["roles"] == original["roles"]
    assert copied["objective"] == original["objective"]
    assert attached["source"] == original["source"]
    assert attached["proposal"] is None and attached["mission_id"] is None
    assert attached["readiness"]["ready"] is False
    assert attached["messages"][:-1] == prior_messages
    assert stored(chats, ready_chat)["native_session"] is None
    assert not {"attempts", "tests", "reviews", "integration", "results", "source_hash", "acceptance_hash"} & copied.keys()
    assert not {"attempts", "tests", "reviews", "integration", "results"} & attached.keys()
    assert hub.snapshot(original_id) == old_snapshot
    assert [m["id"] for m in hub.inventory()["missions"]] == [original_id]
    assert len(StubMission.created) == 1 and StubMission.created[0].calls == 0
    assert len(driver.calls) == 1


def test_http_attach_mission_reuses_contract_and_reports_invalid_target(server, spec, driver, hub):
    original_id = hub.create(spec)["id"]
    chat_id = server.chats.create()["id"]
    body = {"chat_id": chat_id, "mission_id": original_id}
    status, raw, _ = request(server, "/api/chat/attach_mission", body=body)
    assert status == 200
    state = json.loads(raw)
    assert state["source"] == spec["source"] and state["mission_id"] is None
    assert state["readiness"]["ready"] is False
    assert load_lead_spec(Path(state["spec_path"])) == approved_spec(hub.path(original_id))
    before = server.chats.get(chat_id)
    for mission_id, expected in (("../outside", 400), ("missing", 404)):
        status, raw, _ = request(server, "/api/chat/attach_mission", body={**body, "mission_id": mission_id})
        assert status == expected and json.loads(raw)["error"]["message"]
    assert server.chats.get(chat_id) == before
    assert driver.calls == []
    assert len(StubMission.created) == 1 and StubMission.created[0].calls == 0


@pytest.mark.parametrize("change", ["proposal", "source", "approved_spec"])
def test_stale_approval_hash_rejects_confirmation_after_plan_or_context_change(chats, ready_chat, driver, spec, spec_file, tmp_path, hub, change):
    ident = ready_chat
    old_hash = chats.get(ident)["approval_hash"]
    assert isinstance(old_hash, str) and len(old_hash) == 64
    if change == "proposal":
        revised = plan_reply()
        revised["proposal"]["architecture"] += " Add an explicit request reservation interface."
        driver.receipt = completed(json.dumps(revised))
    elif change == "source":
        alternate = tmp_path / "approval-project"
        alternate.mkdir()
        chats.context(ident, str(alternate), str(spec_file))
    else:
        revised = copy.deepcopy(spec)
        revised["constraints"].append("New operator constraint changes the approved context")
        spec_file.write_text(json.dumps(revised))
        chats.context(ident, spec_path=str(spec_file))
    chats.message(ident, "按最新需求重新规划。", "revised-approval-plan")
    state = finish(chats, ident)
    assert state["readiness"]["ready"] is True and state["approval_hash"] != old_hash
    raw = stored(chats, ident)
    assert state["approval_hash"] == digest({"source": raw["source"], "spec": raw["bound_spec"], "proposal": raw["proposal"]})
    with pytest.raises(RuntimeError, match="重新确认"):
        chats.start(ident, True, "approval-start-01", old_hash)
    assert stored(chats, ident) == raw
    assert_no_mission(hub)
    # The rejected stale request did not consume the operator's idempotency key.
    started = chats.start(ident, True, "approval-start-01", state["approval_hash"])
    assert started["mission_id"] and StubMission.created[0].started.wait(3)
    assert len(StubMission.created) == 1 and StubMission.created[0].calls == 1
    assert len(driver.calls) == 2
    with pytest.raises(ValueError, match="another operation"):
        chats.start(ident, True, "approval-start-01", old_hash)
    assert chats.start(ident, True, "approval-start-01", state["approval_hash"]) == started


def test_pre_dispatch_local_failure_is_error_not_unknown(chats, spec, spec_file, tmp_path, driver, hub):
    ident = attach(chats, spec_file)
    # Keep the project recoverable while making the approved cwd disappear.
    Path(spec["source"]).rename(tmp_path / "retained-moved-project")
    chats.message(ident, "plan this project", "local-failure-01")
    state = finish(chats, ident)
    assert state["status"] == "ERROR" and state["proposal"] is None
    assert state["error"]["type"] == "ValueError" and "cwd" in state["error"]["message"]
    assert not (chats.root / ident / "receipt_local-failure-01.json").exists()
    assert chats.message(ident, "plan this project", "local-failure-01") == state
    assert driver.calls == []
    assert_no_mission(hub)


def test_history_bound_counts_utf8_bytes_before_reserving_or_dispatching(chats, driver, hub):
    ident = chats.create()["id"]
    for number in range(3):
        chats.message(ident, "界" * 12000, f"utf8-request-{number:02d}")
        assert finish(chats, ident)["status"] == "IDLE"
    before = stored(chats, ident)
    assert sum(len(m["text"]) for m in before["messages"]) < 100000
    assert sum(len(m["text"].encode("utf-8")) for m in before["messages"]) > 100000
    with pytest.raises(ValueError, match="对话已较长"):
        chats.message(ident, "界" * 12000, "utf8-request-overflow")
    assert stored(chats, ident) == before and len(driver.calls) == 3
    assert_no_mission(hub)


def test_inventory_skips_incomplete_chat_and_reports_issue(chats, driver, hub):
    ident = chats.create()["id"]
    incomplete_id = "c_" + "a" * 32
    incomplete = chats.root / incomplete_id
    incomplete.mkdir()
    inventory = chats.inventory()
    assert [row["id"] for row in inventory["chats"]] == [ident]
    assert inventory["auto_start"] is False
    issues = {row["id"]: row["error"] for row in inventory["issues"]}
    assert issues[incomplete_id]["type"] == "FileNotFoundError"
    assert issues[incomplete_id]["message"]
    assert not (incomplete / "draft.json").exists() and driver.calls == []
    assert_no_mission(hub)


def test_http_stale_approval_hash_is_conflict_without_binding(server, ready_chat, driver, hub):
    old_hash = server.chats.get(ready_chat)["approval_hash"]
    revised = plan_reply()
    revised["proposal"]["objective"] += " Preserve the revised interface."
    driver.receipt = completed(json.dumps(revised))
    server.chats.message(ready_chat, "更新规划。", "http-revised-plan")
    state = finish(server.chats, ready_chat)
    body = {"chat_id": ready_chat, "allow_local_workers": True, "request_id": "http-revised-start", "approval_hash": old_hash}
    status, raw, _ = request(server, "/api/chat/start", body=body)
    assert status == 409 and "重新确认" in json.loads(raw)["error"]["message"]
    assert server.chats.get(ready_chat) == state
    assert_no_mission(hub)
    body["approval_hash"] = state["approval_hash"]
    status, raw, _ = request(server, "/api/chat/start", body=body)
    assert status == 202 and json.loads(raw)["mission_id"]
    assert len(StubMission.created) == 1 and StubMission.created[0].started.wait(3)
    assert StubMission.created[0].calls == 1 and len(driver.calls) == 2


@pytest.mark.parametrize("corruption", ["malformed_json", "non_object", "missing_status", "wrong_identity"])
def test_restart_isolates_corrupt_draft_and_keeps_other_chats_readable(chats, chat_factory, driver, hub, corruption):
    valid_id = chats.create()["id"]
    corrupt_id = "c_" + "b" * 32
    corrupt_directory = chats.root / corrupt_id
    corrupt_directory.mkdir()
    if corruption == "malformed_json":
        content = "{"
    elif corruption == "non_object":
        content = "[]"
    elif corruption == "missing_status":
        content = json.dumps({"id": corrupt_id})
    else:
        content = json.dumps({"id": valid_id, "status": "IDLE"})
    corrupt_path = corrupt_directory / "draft.json"
    corrupt_path.write_text(content)
    chats.close()
    restarted = chat_factory()
    assert restarted.get(valid_id)["status"] == "IDLE"
    inventory = restarted.inventory()
    assert [row["id"] for row in inventory["chats"]] == [valid_id]
    issues = {row["id"]: row["error"] for row in inventory["issues"]}
    assert issues[corrupt_id]["type"] and issues[corrupt_id]["message"]
    assert corrupt_path.read_text() == content
    assert driver.calls == []
    assert_no_mission(hub)


@pytest.mark.parametrize("operation", ["context", "attach_mission", "start"])
def test_closed_owner_rejects_mutations_after_new_owner_acquires_lock(chats, ready_chat, chat_factory, spec, spec_file, driver, hub, operation):
    mission_id = hub.create(spec)["id"] if operation == "attach_mission" else None
    expected_missions = len(StubMission.created)
    chats.close()
    reopened = chat_factory()
    before = stored(reopened, ready_chat)
    if operation == "context":
        action = lambda: chats.context(ready_chat, spec_path=str(spec_file))
    elif operation == "attach_mission":
        action = lambda: chats.attach_mission(ready_chat, mission_id)
    else:
        approval_hash = reopened.get(ready_chat)["approval_hash"]
        action = lambda: chats.start(ready_chat, True, "closed-owner-start", approval_hash)
    with pytest.raises(RuntimeError, match="closing"):
        action()
    assert stored(reopened, ready_chat) == before
    assert len(StubMission.created) == expected_missions
    assert all(m.calls == 0 for m in StubMission.created)
    assert len(driver.calls) == 1



def test_native_missing_executable_is_launch_error_not_unknown(chat_factory, offline_only, monkeypatch, spec_file, tmp_path, hub):
    missing = tmp_path / "nonexistent-claude-fixture"
    assert not missing.exists()
    native = lead_chat.ClaudeCodeDriver(command=(str(missing),))
    calls = []

    def missing_executable_run(native_request, emit):
        # Exercise the real adapter and Popen failure, never a working CLI.
        # Restore only this instance; the global paid-call guard stays active.
        assert native.command == (str(missing),) and not missing.exists()
        calls.append(native_request)
        return offline_only(native, native_request, emit)

    monkeypatch.setattr(native, "run", missing_executable_run)
    chats = chat_factory(fake=native)
    ident = attach(chats, spec_file)
    text, request_id = "plan only", "native-missing-launch"
    chats.message(ident, text, request_id)
    state = finish(chats, ident)
    identity = {"requested_model": MODEL, "actual_model": None,
                "reported_models": [], "telemetry": "missing"}
    assert state["status"] == "ERROR" and state["error"]["type"] == "NativeLaunchError"
    assert "FileNotFoundError" in state["error"]["message"]
    assert state["model"] == {"requested": MODEL, "actual": None}
    assert state["model_identity"] == identity
    assert state["proposal"] is None and state["readiness"]["ready"] is False
    assert not [m for m in state["messages"] if m.get("kind") == "opus"]
    events_path = chats.root / ident / ("events_" + request_id + ".jsonl")
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    assert events == [{"kind": "model_identity", "data": identity}]
    assert not any(e["kind"] == "process_started" for e in events)
    receipt_path = chats.root / ident / ("receipt_" + request_id + ".json")
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "UNKNOWN"  # Native adapter receipt is retained unchanged.
    assert receipt["actual_model"] is None and receipt["exit_code"] is None
    assert "FileNotFoundError" in receipt["error"]
    assert chats.message(ident, text, request_id) == state and len(calls) == 1
    assert not missing.exists()
    assert_no_mission(hub)


def test_native_ambiguous_identity_is_error_and_public_diagnostics_survive_restart(chat_factory, spec_file, hub):
    identity = {"requested_model": MODEL, "actual_model": None,
                "reported_models": [MODEL, "wrong-model"], "telemetry": "ambiguous"}

    class NativeIdentityFixture(lead_chat.ClaudeCodeDriver):
        """Simulated native identity telemetry; no subprocess or provider call."""

        def __init__(self):
            super().__init__(command=("unused-native-identity-fixture",))
            self.calls = []

        def run(self, native_request, emit):
            self.calls.append(native_request)
            emit("model_identity", copy.deepcopy(identity))
            # Null actual identity is ambiguity, not a requested-model echo.
            return completed(actual_model=None)

    native = NativeIdentityFixture()
    chats = chat_factory(fake=native)
    ident = attach(chats, spec_file)
    text, request_id = "plan only", "native-ambiguous-identity"
    chats.message(ident, text, request_id)
    state = finish(chats, ident)
    assert state["status"] == "ERROR" and state["error"]["type"] == "ValueError"
    assert "ambiguous" in state["error"]["message"]
    assert state["model"] == {"requested": MODEL, "actual": None}
    assert state["model_identity"] == identity
    assert state["proposal"] is None and state["readiness"]["ready"] is False
    assert not [m for m in state["messages"] if m.get("kind") == "opus"]
    receipt_path = chats.root / ident / ("receipt_" + request_id + ".json")
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "COMPLETED" and receipt["actual_model"] is None
    assert json.loads(receipt["output"]) == plan_reply()
    events_path = chats.root / ident / ("events_" + request_id + ".jsonl")
    assert json.loads(events_path.read_text().splitlines()[0]) == {"kind": "model_identity", "data": identity}
    assert chats.message(ident, text, request_id) == state and len(native.calls) == 1
    chats.close()
    fresh = FakeDriver()
    reopened = chat_factory(fake=fresh)
    assert reopened.get(ident) == state
    assert reopened.message(ident, text, request_id) == state
    assert stored(reopened, ident)["model_identity"] == identity
    assert fresh.calls == [] and len(native.calls) == 1
    assert_no_mission(hub)


def test_preflight_unbound_plan_explains_gaps_without_mutation_or_dispatch(chats, driver, hub):
    ident = chats.create()["id"]
    chats.message(ident, "新建工程，按讨论的验收推进", "preflight-plan-01")
    finish(chats, ident)
    before = draft_path(chats, ident).read_bytes()
    public = chats.get(ident)
    readiness = public["readiness"]
    assert readiness["can_prepare"] is True and readiness["ready"] is False
    requirements = {r["id"]: r for r in readiness["requirements"]}
    assert requirements["proposal"]["ready"] is True
    assert requirements["source"]["ready"] is False
    assert requirements["acceptance"]["ready"] is False
    assert requirements["native"]["ready"] is True
    assert "明确要求" in requirements["source"]["detail"]
    assert "文字验收" in requirements["acceptance"]["detail"]
    assert "工程目录" in readiness["reason"] and "固定验收" in readiness["reason"]
    with pytest.raises(ValueError):
        start_chat(chats, ident, True, "preflight-start-01")
    assert draft_path(chats, ident).read_bytes() == before
    assert len(driver.calls) == 1
    assert_no_mission(hub)


@pytest.mark.parametrize("context", ["source", "spec"])
def test_preflight_distinguishes_source_and_approved_checks(chats, spec, spec_file, context):
    ident = chats.create()["id"]
    if context == "source":
        chats.context(ident, source=spec["source"])
    else:
        chats.context(ident, spec_path=str(spec_file))
    readiness = chats.get(ident)["readiness"]
    requirements = {r["id"]: r for r in readiness["requirements"]}
    assert requirements["source"]["ready"] is True
    assert requirements["acceptance"]["ready"] is (context == "spec")
    assert requirements["proposal"]["ready"] is False
    assert readiness["can_prepare"] is False and readiness["ready"] is False


@pytest.mark.parametrize("status", ["RUNNING", "STARTING", "UNKNOWN", "ERROR"])
def test_preflight_can_inspect_but_fences_non_idle_native_outcomes(chats, ready_chat, driver, hub, status):
    state = stored(chats, ready_chat)
    state["status"] = status
    chats._save(state)
    before = draft_path(chats, ready_chat).read_bytes()
    readiness = chats.get(ready_chat)["readiness"]
    assert readiness["can_prepare"] is True and readiness["ready"] is False
    requirements = {r["id"]: r for r in readiness["requirements"]}
    assert requirements["native"]["ready"] is False
    assert requirements["native"]["detail"] and "调用状态" in readiness["reason"]
    assert draft_path(chats, ready_chat).read_bytes() == before
    assert len(driver.calls) == 1
    assert_no_mission(hub)


def test_preflight_ready_draft_and_bound_mission_have_distinct_actions(chats, ready_chat):
    readiness = chats.get(ready_chat)["readiness"]
    assert readiness["ready"] is True and readiness["can_prepare"] is True
    assert all(r["ready"] for r in readiness["requirements"])
    result = start_chat(chats, ready_chat, True, "preflight-bound-01")
    assert result["readiness"]["ready"] is False
    assert result["readiness"]["can_prepare"] is False
    assert "进度" in result["readiness"]["reason"]


@pytest.fixture
def directory_home(monkeypatch, tmp_path):
    home = tmp_path / "operator-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def requested_directory_chat(chats, home, *, target=None):
    """Retained pre-upgrade draft: user authorized HOME, Opus proposed a name."""
    target = target or home / "cex-dex-research"
    ident = chats.create()["id"]
    state = stored(chats, ident)
    state["messages"] = [
        {"id":"directory-grant-01", "role":"user", "text":"我们在$HOME 里新建一个文件夹搞这个工程"},
        {"id":"directory-reply-01", "role":"assistant", "text":"研究目录建议放在 " + str(target)},
        {"id":"directory-request-01", "role":"user", "text":"帮我填写工程目录，和写固定验收检查程序"},
    ]
    state["proposal"] = plan_reply()["proposal"]
    state["proposal"]["objective"] = "在 " + str(target) + " 开展只读研究"
    chats._save(state)
    return ident


def test_directory_prepare_uses_recorded_home_permission_and_binds_without_manual_input(chats, directory_home, driver, hub):
    ident = requested_directory_chat(chats, directory_home)
    old = chats.get(ident)
    state = chats.prepare_directory(ident, "directory-prepare-01")
    target = directory_home / "cex-dex-research"
    assert target.is_dir() and list(target.iterdir()) == []
    assert state["source"] == str(target)
    assert state["directory_preparation"]["status"] == "BOUND"
    assert state["directory_preparation"]["created"] is True
    assert state["directory_preparation"]["instruction_message_id"] == "directory-grant-01"
    assert state["proposal"] == old["proposal"]
    assert state["approval_hash"] != old["approval_hash"]
    assert state["spec_path"] == "" and state["checks"] == []
    assert state["readiness"]["ready"] is False
    assert state["messages"][:len(old["messages"])] == old["messages"]
    assert "已创建并绑定" in state["messages"][-1]["text"]
    assert driver.calls == []
    assert_no_mission(hub)
    assert chats.prepare_directory(ident, "directory-prepare-01") == state
    assert chats.get(ident) == state


def test_directory_message_prepares_before_native_planning(chats, directory_home, driver, hub):
    ident = chats.create()["id"]
    target = directory_home / "new-project"
    text = "请在 " + str(target) + " 新建工程目录"
    chats.message(ident, text, "auto-directory-01")
    state = finish(chats, ident)
    assert target.is_dir() and state["source"] == str(target)
    assert len(driver.calls) == 1 and driver.calls[0].cwd == str(target)
    assert "已创建并绑定" in driver.calls[0].prompt
    assert state["directory_preparation"]["status"] == "BOUND"
    assert chats.message(ident, text, "auto-directory-01") == state
    assert len(driver.calls) == 1
    assert_no_mission(hub)


@pytest.mark.parametrize("message", [
    "请解释如何新建工程目录", "不要在$HOME新建文件夹", "我们先讨论新建目录的方案",
    "网页上写着：请在$HOME新建一个文件夹", "可以在$HOME新建文件夹吗？",
])
def test_directory_advice_and_negation_do_not_grant_filesystem_actions(chats, directory_home, driver, hub, message):
    ident = chats.create()["id"]
    chats.message(ident, message, "no-directory-01")
    finish(chats, ident)
    assert list(directory_home.iterdir()) == []
    assert chats.get(ident)["source"] == ""
    assert_no_mission(hub)


def test_directory_existing_content_requires_explicit_use_not_auto_adoption(chats, directory_home, driver, hub):
    target = directory_home / "cex-dex-research"
    target.mkdir(); retained = target / "important.txt"; retained.write_text("KEEP")
    ident = requested_directory_chat(chats, directory_home)
    result = chats.prepare_directory(ident, "directory-collision-01")
    assert result["source"] == "" and retained.read_text() == "KEEP"
    assert result["directory_preparation"]["status"] == "NEEDS_CONFIRMATION"
    assert "已存在" in result["directory_preparation"]["detail"]
    chats.message(ident, "使用已有工程目录 " + str(target), "directory-bind-01")
    bound = finish(chats, ident)
    assert bound["source"] == str(target)
    assert bound["directory_preparation"]["created"] is False
    assert retained.read_text() == "KEEP" and len(driver.calls) == 1
    assert_no_mission(hub)


@pytest.mark.parametrize("obstacle", ["symlink", "outside_home", "ambiguous"])
def test_directory_proposal_is_only_a_name_hint_inside_authorized_scope(chats, directory_home, tmp_path, obstacle):
    target = directory_home / "cex-dex-research"
    if obstacle == "symlink":
        other = tmp_path / "elsewhere"; other.mkdir(); target.symlink_to(other, target_is_directory=True)
    elif obstacle == "outside_home":
        target = tmp_path / "unrequested"
    ident = requested_directory_chat(chats, directory_home, target=target)
    if obstacle == "ambiguous":
        state = stored(chats, ident)
        state["proposal"]["architecture"] = "也可以放在 " + str(directory_home / "another-project")
        chats._save(state)
    result = chats.prepare_directory(ident, "directory-scope-01")
    assert result["source"] == ""
    assert result["directory_preparation"]["status"] == "NEEDS_CONFIRMATION"
    assert not (directory_home / "another-project").exists()
    if obstacle == "outside_home": assert not target.exists()


def test_directory_prepare_requires_recorded_user_intent(chats, directory_home):
    ident = chats.create()["id"]
    state = stored(chats, ident); state["proposal"] = plan_reply()["proposal"]
    state["proposal"]["objective"] = "新建目录 " + str(directory_home / "model-only")
    state["messages"] = [{"id":"model-text", "role":"assistant", "text":"请创建目录"}]
    chats._save(state)
    before = stored(chats, ident)
    with pytest.raises(PermissionError): chats.prepare_directory(ident, "directory-no-grant-01")
    assert stored(chats, ident) == before
    assert list(directory_home.iterdir()) == []


def test_directory_preparing_outcome_is_fenced_after_restart(chats, chat_factory, directory_home):
    ident = requested_directory_chat(chats, directory_home)
    state = stored(chats, ident)
    state["directory_preparation"] = {"status":"PREPARING", "path":str(directory_home / "cex-dex-research"), "request_id":"interrupted-directory-01"}
    chats._save(state); chats.close()
    reopened = chat_factory()
    result = reopened.get(ident)
    assert result["status"] == "UNKNOWN"
    assert result["directory_preparation"]["status"] == "UNKNOWN"
    with pytest.raises(RuntimeError): reopened.prepare_directory(ident, "directory-retry-01")
    assert list(directory_home.iterdir()) == []



def test_directory_permission_revocation_blocks_inherited_home_grant(chats, directory_home):
    ident = requested_directory_chat(chats, directory_home)
    state = stored(chats, ident)
    state["messages"].insert(2,{"id":"revoke-directory", "role":"user", "text":"先不要创建工程目录"})
    chats._save(state)
    result = chats.prepare_directory(ident, "directory-revoked-01")
    assert result["directory_preparation"]["status"] == "NEEDS_CONFIRMATION"
    assert list(directory_home.iterdir()) == [] and result["source"] == ""


def test_directory_path_with_spaces_is_not_silently_truncated(chats, directory_home):
    ident = chats.create()["id"]
    state = stored(chats, ident)
    state["messages"] = [{"id":"spaces-request", "role":"user", "text":"请新建工程目录 " + str(directory_home / "My Project")}]
    chats._save(state)
    result = chats.prepare_directory(ident, "directory-spaces-01")
    assert result["directory_preparation"]["status"] == "NEEDS_CONFIRMATION"
    assert list(directory_home.iterdir()) == []


def test_directory_known_io_failure_is_observable_and_idempotent(chats, directory_home, monkeypatch):
    ident = requested_directory_chat(chats, directory_home)
    target = directory_home / "cex-dex-research"
    mkdir = lead_chat.os.mkdir
    attempts = []
    def denied(path, *args, **kwargs):
        if path == target.name:
            attempts.append(path); raise PermissionError("directory permission fixture")
        return mkdir(path,*args,**kwargs)
    monkeypatch.setattr(lead_chat.os,"mkdir",denied)
    with pytest.raises(PermissionError): chats.prepare_directory(ident,"directory-io-error-01")
    result = chats.get(ident)
    assert result["status"] == "ERROR" and result["directory_preparation"]["status"] == "ERROR"
    assert "permission fixture" in result["error"]["message"]
    assert chats.prepare_directory(ident,"directory-io-error-01") == result
    assert attempts == [target.name] and not target.exists()


def test_directory_post_mkdir_failure_preserves_directory_and_fences(chats, directory_home, monkeypatch):
    ident = requested_directory_chat(chats, directory_home)
    target = directory_home / "cex-dex-research"
    flush = lead_chat.durable_flush
    def fail_new_directory(fd):
        if target.exists() and lead_chat.os.fstat(fd).st_ino == target.stat().st_ino:
            raise OSError("directory durability fixture")
        return flush(fd)
    monkeypatch.setattr(lead_chat,"durable_flush",fail_new_directory)
    with pytest.raises(OSError): chats.prepare_directory(ident,"directory-partial-01")
    result = chats.get(ident)
    assert target.is_dir() and result["status"] == "UNKNOWN"
    assert result["directory_preparation"]["status"] == "UNKNOWN"
    assert result["source"] == ""
    assert chats.prepare_directory(ident,"directory-partial-01") == result
    with pytest.raises(RuntimeError): chats.prepare_directory(ident,"directory-partial-02")


def test_directory_parallel_duplicate_request_creates_once(chats, directory_home):
    ident = requested_directory_chat(chats, directory_home)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: chats.prepare_directory(ident,"directory-concurrent-01"),range(2)))
    assert results[0] == results[1]
    assert len([m for m in results[0]["messages"] if m.get("kind") == "directory"]) == 1
    assert len(list(directory_home.iterdir())) == 1


def test_http_directory_action_is_authenticated_exact_and_read_only_until_post(server, directory_home, driver, hub):
    ident = requested_directory_chat(server.chats, directory_home)
    body = {"chat_id":ident,"request_id":"http-directory-01"}
    assert request(server,"/api/chat?chat_id=" + ident)[0] == 200
    assert not (directory_home / "cex-dex-research").exists()
    assert request(server,"/api/chat/prepare_directory",body=body,auth=False)[0] == 401
    assert request(server,"/api/chat/prepare_directory",body={**body,"path":"/unrequested"})[0] == 400
    status,raw,_ = request(server,"/api/chat/prepare_directory",body=body)
    assert status == 200 and json.loads(raw)["source"] == str(directory_home / "cex-dex-research")
    assert json.loads(request(server,"/api/chat/prepare_directory",body=body)[1]) == json.loads(raw)
    assert driver.calls == []
    assert_no_mission(hub)


@pytest.mark.parametrize("status", ["RUNNING","STARTING","UNKNOWN"])
def test_directory_prepare_respects_existing_native_fences(chats, directory_home, status):
    ident = requested_directory_chat(chats,directory_home)
    state = stored(chats,ident); state["status"] = status; chats._save(state)
    with pytest.raises(RuntimeError): chats.prepare_directory(ident,"directory-fenced-01")
    assert list(directory_home.iterdir()) == []
