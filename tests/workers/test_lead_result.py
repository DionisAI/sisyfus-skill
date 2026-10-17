"""S0 public projection contract; static draft, outcomes gated separately.

The real-producer fixture is isolated protocol evidence, not native acceptance.
Import the NEW feature only at a test call so absence is an explicit assertion.
"""
from __future__ import annotations

import ast
import builtins
import copy
import datetime
import importlib
import inspect
import json
import math
import os
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest


PUBLIC_MODULE = "sisyfus.workers.lead_result"
SCHEMA = "sisyfus.lead_result.engineering.s0.v1"
CLASSIFICATION = "CAPTURED_ENGINEERING_PROJECTION_NOT_ACCEPTANCE"
TOP_KEYS = (
    "schema", "classification", "question", "conclusion", "tasks",
    "integration", "attempts", "control", "provenance", "limitations",
    "diagnostics",
)
INPUT_ERROR_CODES = (
    "INPUT_TYPE", "ENVELOPE_KEYS", "MISSION_ID_INVALID",
    "SNAPSHOT_REQUIRED_FIELD", "TEXT_ENCODING", "LIMIT_EXCEEDED",
    "DEPTH_EXCEEDED", "VISIT_LIMIT", "INPUT_CYCLE", "OUTPUT_LIMIT",
)
DIAGNOSTIC_CODES = (
    "MALFORMED", "TEXT_LIMIT", "HASH_INVALID", "UNRECOGNIZED_ENUM",
    "NUMERIC_NONFINITE", "UNSAFE_PATH", "WITHHELD_SENSITIVE_PATH",
    "MALFORMED_DELTA", "DUPLICATE_ID", "VERDICT_MISMATCH",
    "CANDIDATE_HASH_MISMATCH", "CHECK_HASH_MISMATCH", "CHECK_NAME_MISMATCH",
    "REVIEW_RUN_KEY_MISMATCH", "REVIEW_REFERENCE_MISMATCH",
    "DEPENDENCY_EVIDENCE_MISMATCH", "DEPENDENCY_GRAPH_INVALID",
    "INTEGRATION_CONTINUATION_MISMATCH", "INTEGRATION_REVISION_MISMATCH",
    "CURRENT_FLAG_SHAPE", "ACCEPTANCE_HASH_DIVERGENT", "WITHHELD_SENSITIVE_ID",
)
DIAGNOSTIC_SECTIONS = (
    "mission", "task", "check", "measurement", "review", "integration",
    "build", "attempt",
)
FACT_STATES = (
    "RECORDED", "FILTERED", "NOT_RECORDED", "REDACTED_AT_CAPTURE",
    "WITHHELD", "MALFORMED",
)
LIMITATION_CODES = (
    "NO_FILE_CONTENT", "NON_ATOMIC_CAPTURE", "NO_REVERIFICATION",
    "SPEC_NOT_IN_SNAPSHOT", "NOT_DLP", "NO_LIVE_RUNTIME",
    "NO_RESEARCH_RESULT", "NO_DEVICE_OR_SECOND_HOST_ACCEPTANCE",
    "MEASUREMENT_SELECTION_PARTIAL_BY_POLICY",
)
LIMITATION_TEXT = {
    "NO_FILE_CONTENT": "仅展示记录的文件hash增量，不包含文件正文。",
    "NON_ATOMIC_CAPTURE": "输入由调用方非原子捕获，不是同一事务的全局事实。",
    "NO_REVERIFICATION": "本投影未重新运行检查、审查或重新验证文件字节。",
    "SPEC_NOT_IN_SNAPSHOT": "输入不含完整冻结spec，所列指纹仅按记录展示。",
    "NOT_DLP": "确定性模式过滤是纵深防御，不是敏感内容清除证明。",
    "NO_LIVE_RUNTIME": "不展示实时进程、节点在线性或原生终止事实。",
    "NO_RESEARCH_RESULT": "本投影没有研究结果或研究发布状态。",
    "NO_DEVICE_OR_SECOND_HOST_ACCEPTANCE": "本投影没有手机、设备或第二主机验收。",
    "MEASUREMENT_SELECTION_PARTIAL_BY_POLICY": "仅展示有界有限数值或bool测量；不输出项与省略项分别计数。",
}
# Exact draft vocabulary; Main reads it before the separate freeze gate.
TEMPLATES = {
    "Q01": "目标问题：{objective}。",
    "C01": "尚无已记录的工程结果。",
    "C02": "已记录候选或历史证据；不表示已通过验收。",
    "C03": "已记录任务证据；项目集成证据仍待记录。",
    "C04": "已记录集成证据；控制器未记录项目通过。",
    "C05": "捕获时控制器记录项目通过；本投影不是验收。",
    "C06": "捕获记录存在冲突；保留分项事实，不给出通过结论。",
    "D01": "{subject}文件增量：{path}，{change_kind}；before={before}，after={after}；hash 为前12位。",
    "M01": "{subject}检查 {check}：记录分类 {status}；评估器说明：{summary}。",
    "M02": "{subject}检查 {check} 的记录测量：{name}={value}。",
    "R01": "{subject}独立审查：记录裁决 {verdict}；归属理由：{reason}。",
    "R02": "{subject}审查记录引用：{reference}。",
    "I01": "尚无已记录的项目集成证据。",
    "I02": "已记录集成候选；不表示通过项目验收。",
    "I03": "集成记录未被接受；continuation={continuation_id}，行裁决={recorded_verdict}，payload裁决={payload_verdict}。",
    "I04": "捕获时记录集成通过且 current=true；continuation={continuation_id}，evidence={evidence_id}，revision={revision}。",
    "I05": "保留历史集成证据；current={current}，行裁决={recorded_verdict}。",
    "I06": "集成捕获记录存在冲突；continuation={continuation_id}，evidence={evidence_id}。",
    "K01": "控制器记录：phase={phase}，paused={paused}，stopped={stopped}，project_verified={project_verified}，all_verified={all_verified}，待核对调用={unresolved_count}；这不是实时进程终止证明。",
    "L01": "限制：非原子捕获，不重新验证字节，不是脱敏完备性证明；没有文件正文、研究结果或设备及第二主机验收。",
}
CONCLUSION_TEMPLATE = {
    "NO_ENGINEERING_RESULT_RECORDED": "C01",
    "CANDIDATES_RECORDED": "C02",
    "TASK_EVIDENCE_RECORDED_INTEGRATION_PENDING": "C03",
    "INTEGRATION_EVIDENCE_RECORDED_PROJECT_NOT_VERIFIED": "C04",
    "PROJECT_VERIFIED_AS_CAPTURED": "C05",
    "CAPTURE_CONFLICT": "C06",
}
INTEGRATION_TEMPLATE = {
    "PENDING": "I01", "INTEGRATION_CANDIDATE_RECORDED": "I02",
    "NOT_ACCEPTED": "I03", "INTEGRATION_VERIFIED_AS_CAPTURED": "I04",
    "HISTORICAL_RESULT": "I05", "EVIDENCE_CONFLICT": "I06",
}
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64
VERIFICATION_KEYS = {
    "verdict", "verifier_id", "summary", "metrics", "evidence", "assurance",
    "verification_mode", "lessons",
}


def _public():
    try:
        module = importlib.import_module(PUBLIC_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != PUBLIC_MODULE:
            raise
        pytest.fail("missing S0 public module: sisyfus.workers.lead_result",
                    pytrace=False)
    assert callable(getattr(module, "project_engineering_result", None)), (
        "missing S0 public function: project_engineering_result"
    )
    error = getattr(module, "EngineeringResultInputError", None)
    assert isinstance(error, type) and issubclass(error, ValueError), (
        "missing S0 public error: EngineeringResultInputError(ValueError)"
    )
    return module


class _Unselected:
    def __repr__(self):
        raise AssertionError("unselected repr accessed")

    def __iter__(self):
        raise AssertionError("unselected iterator accessed")

    def __deepcopy__(self, memo):
        raise AssertionError("unselected copy accessed")


class _EnvironmentTrap:
    def _blocked(self, *args, **kwargs):
        raise AssertionError("environment accessed during pure projection")

    __getitem__ = get = __iter__ = items = keys = values = __contains__ = _blocked


@contextmanager
def _pure_traps():
    def blocked(*args, **kwargs):
        raise AssertionError("side effect accessed during pure projection")

    class NoNow(datetime.datetime):
        now = classmethod(blocked)
        utcnow = classmethod(blocked)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "environ", _EnvironmentTrap())
        mp.setattr(builtins, "open", blocked)
        mp.setattr(Path, "open", blocked)
        mp.setattr(sqlite3, "connect", blocked)
        mp.setattr(socket, "socket", blocked)
        mp.setattr(subprocess, "Popen", blocked)
        mp.setattr(threading.Thread, "start", blocked)
        mp.setattr(time, "time", blocked)
        mp.setattr(time, "monotonic", blocked)
        mp.setattr(datetime, "datetime", NoNow)
        protocol = sys.modules.get("sisyfus.workers.protocol")
        if protocol is not None:
            mp.setattr(protocol, "redact", blocked)
        yield


def _project(payload):
    module = _public()
    with _pure_traps():
        return module.project_engineering_result(payload)


def _reject(payload, code):
    module = _public()
    with pytest.raises(module.EngineeringResultInputError) as found:
        _project(payload)
    exc = found.value
    assert type(exc) is module.EngineeringResultInputError
    assert exc.code == code and exc.code in INPUT_ERROR_CODES
    assert str(exc) == "engineering result input rejected: " + code
    assert exc.__cause__ is None and exc.__suppress_context__ is True
    assert set(vars(exc)) == {"code"}


def _verification(data, verdict="PASS", summary="Controller recorded fixture verification"):
    return {
        "verdict": verdict, "verifier_id": "lead.fixture.v1", "summary": summary,
        "metrics": {}, "evidence": data, "assurance": "TRUSTED",
        "verification_mode": "DETERMINISTIC", "lessons": [],
    }


def _artifact(check="unit", run_key="worker:build:1", dependencies=None):
    receipt_id = "check:" + check
    return {
        "status": "COMPLETED", "run_key": run_key,
        "candidate": "/private/fixture/candidate-withheld", "candidate_hash": SHA_A,
        "patch": {
            "added.txt": {"before": None, "after": SHA_B},
            "modified.txt": {"before": SHA_C, "after": SHA_D},
            "removed.txt": {"before": SHA_E, "after": None},
        },
        "checks": [{
            "id": receipt_id, "check": check, "candidate_hash": SHA_A,
            "check_hash": SHA_F,
            "classification": {"status": "PASS", "summary": "Evaluator recorded fixture pass"},
            "measurement": {"execution": {"exit_code": 0, "timed_out": False}, "score": 0.5},
        }],
        "review": {
            "verdict": "PASS", "reasons": ["Reviewer inspected fixture receipts"],
            "evidence": [receipt_id], "run_key": "review:" + run_key,
            "candidate_hash": SHA_A,
        },
        "acceptance_hash": SHA_B, "check_hashes": {check: SHA_F},
        "task_hash": SHA_C, "dependencies": {} if dependencies is None else dependencies,
    }


def _node(ident="build", *, verified=False, depends=(), evidence_id=101):
    return {
        "id": ident, "objective": "Implement the fixture delta", "acceptance": "Frozen fixture check",
        "check": "unit", "depends_on": list(depends), "write_paths": ["added.txt"],
        "state": "SUCCEEDED" if verified else "READY", "attempts": 1 if verified else 0,
        "active": True, "superseded_by": None, "stale": False,
        "verdict": "PASS" if verified else "UNVERIFIED",
        "evidence_id": evidence_id if verified else None,
        "verification": _verification(_artifact(run_key="worker:" + ident + ":1")) if verified else None,
    }


def _envelope(*, verified=False, integrated=False):
    nodes = [_node(verified=True)] if verified or integrated else []
    integration = {"continuation": None, "evidence": None, "current": False, "builds": []}
    if integrated:
        data = _artifact("whole", "integration:1", {"build": 101})
        data.pop("task_hash")
        integration.update(
            continuation={"id": "integration-cont:1", "state": "SUCCEEDED", "context": {"lead_integration": 1}},
            evidence={"id": 201, "continuation_id": "integration-cont:1", "verdict": "PASS", "payload": _verification(data)},
            current=True,
        )
    return {
        "id": "mission",
        "snapshot": {
            "objective": "Implement an isolated fixture", "phase": "COMPLETED" if integrated else "IMPLEMENTING",
            "revision": 1, "resume_epoch": 0, "nodes": nodes, "runs": [],
            "integration": integration, "unresolved": [], "paused": False,
            "stopped": False, "project_verified": integrated, "all_verified": integrated,
            "reason": "",
        },
        "controller": {"running": False, "auto_start": False}, "controls": [],
    }


def _data(payload, index=0):
    return payload["snapshot"]["nodes"][index]["verification"]["evidence"]


def _run(key="worker:build:1", *, task="build", status="RECEIPTED", native="COMPLETED"):
    return {
        "key": key, "task_id": task, "status": status, "evidence_id": None,
        "receipt": {"status": native, "candidate_hash": SHA_A,
                    "patch": {"added.txt": {"before": None, "after": SHA_B}}},
    }


def _walk(value):
    yield value
    if type(value) is dict:
        for child in value.values():
            yield from _walk(child)
    elif type(value) is list:
        for child in value:
            yield from _walk(child)


def _codes(value):
    return {x["code"] for x in _walk(value)
            if type(x) is dict and {"code", "section", "source"} <= x.keys()}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=False, allow_nan=False)


def _resolve(payload, pointer):
    assert pointer.startswith("/")
    value = payload
    for segment in pointer[1:].split("/"):
        key = segment.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if type(value) is list else value[key]
    return value


def _assert_closed_schema(result):
    assert tuple(result) == TOP_KEYS
    assert result["schema"] == SCHEMA and result["classification"] == CLASSIFICATION
    assert set(result["question"]) == {"mission_id", "objective"}
    assert set(result["conclusion"]) == {"stage", "statements"}
    assert set(result["control"]) == {
        "phase", "reason", "paused", "stopped", "project_verified", "all_verified",
        "unresolved", "live_runtime",
    }
    assert result["control"]["live_runtime"] == "NOT_PROJECTED"
    assert tuple(x["code"] for x in result["limitations"]) == LIMITATION_CODES
    assert all(set(x) == {"code", "text"} for x in result["limitations"])
    assert all(x["text"] == LIMITATION_TEXT[x["code"]] for x in result["limitations"])
    assert set(result["integration"]) == {
        "stage", "continuation_id", "continuation_state", "lead_integration_revision",
        "evidence_id", "evidence_continuation_id", "recorded_verdict", "payload_verdict",
        "current", "result", "builds", "diagnostics",
    }
    task_keys = {
        "task_id", "objective", "acceptance", "check", "depends_on", "write_paths",
        "workflow", "currentness", "stage", "deliverable", "checks", "review",
        "acceptance_fingerprints", "failure_indicators", "uncertain_run_keys", "diagnostics",
    }
    for task in result["tasks"]:
        assert set(task) == task_keys
        assert set(task["workflow"]) == {
            "state", "attempts", "recorded_verdict", "payload_verdict",
            "evidence_id", "verification_summary",
        }
        assert set(task["currentness"]) == {"active", "stale", "superseded_by", "label"}
        assert set(task["acceptance_fingerprints"]) == {
            "acceptance_hash", "check_hashes", "task_hash", "dependencies",
        }
    artifacts = [t["deliverable"] for t in result["tasks"] if t["deliverable"] is not None]
    checks = [c for t in result["tasks"] for c in t["checks"]]
    reviews = [t["review"] for t in result["tasks"]]
    integrated = result["integration"]["result"]
    if integrated is not None:
        assert set(integrated) == {
            "deliverable", "checks", "review", "acceptance_hash", "check_hashes",
            "dependencies", "failure_indicators",
        }
        artifacts.append(integrated["deliverable"])
        checks.extend(integrated["checks"])
        reviews.append(integrated["review"])
    for artifact in artifacts:
        assert set(artifact) == {"candidate_hash", "candidate_location", "run_key", "patch"}
        assert set(artifact["patch"]) == {"row_count", "withheld_count", "rows"}
        for row in artifact["patch"]["rows"]:
            assert {"path", "change_kind", "before", "after", "source"} <= row.keys()
            assert set(row) <= {"path", "change_kind", "before", "after", "source", "row_ordinal"}
    for check in checks:
        assert set(check) == {"id", "check", "candidate_hash", "check_hash", "status", "summary", "measurement"}
        assert set(check["measurement"]) == {
            "scalars", "execution_error_recorded", "withheld_count", "omitted_scalar_count", "complete",
        }
        assert all(set(s) == {"name", "value", "source"} for s in check["measurement"]["scalars"])
    for review in reviews:
        assert set(review) == {
            "recorded", "verdict", "reasons", "evidence_refs", "run_key",
            "candidate_hash", "references_cover_recorded_checks",
        }
    for attempt in result["attempts"]:
        assert set(attempt) == {
            "run_key", "task_id", "status", "receipt_status", "evidence_id", "association",
            "associated_task_id", "unresolved", "unverified_candidate", "source",
        }
    for item in _walk(result):
        assert type(item) in (dict, list, str, int, float, bool, type(None))
        if type(item) is float:
            assert math.isfinite(item)
        if type(item) is not dict:
            continue
        if {"state", "value", "source"} <= item.keys():
            assert set(item) <= {"state", "value", "source", "row_ordinal", "utf8_bytes"}
            assert item["state"] in FACT_STATES
            assert type(item["source"]) is str
            if item["state"] not in {"RECORDED", "FILTERED"}:
                assert item["value"] is None
        if {"code", "section", "source"} <= item.keys():
            assert set(item) == {"code", "section", "source"}
            assert item["code"] in DIAGNOSTIC_CODES
            assert item["section"] in DIAGNOSTIC_SECTIONS
        if "template_id" in item:
            assert set(item) == {"template_id", "text", "sources"}
            assert item["template_id"] in TEMPLATES
            assert item["sources"] == sorted(set(item["sources"]))
            assert len(item["sources"]) <= 64
    _json(result)


def test_ms10_public_feature_availability_is_an_explicit_assertion():
    module = _public()
    parameters = list(inspect.signature(module.project_engineering_result).parameters.values())
    assert len(parameters) == 1
    assert parameters[0].name == "hub_payload"
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_ONLY
    assert parameters[0].default is inspect.Parameter.empty
    _assert_closed_schema(_project(_envelope()))


def _capture_real_producer(root):
    # MS15 permits this isolated fixture at a later outcome gate, not this draft.
    from test_lead_mission import Stub, make_spec, mission
    from sisyfus.workers.lead_console import MissionHub
    from sisyfus.workers.lead_mission import LeadMission
    from sisyfus.workers.mission import files

    raw = make_spec(root, initial=False)
    constructed = []

    def factory(directory, spec=None):
        assert directory == root / "control"
        current = mission(root, spec)
        assert type(current) is LeadMission
        assert all(type(driver) is Stub for driver in current.drivers.values())
        constructed.append(current)
        return current

    hub = MissionHub(root / "control", single=True, mission_factory=factory)
    try:
        bound = hub.create(raw)
        assert bound["id"] == "mission" and bound["started"] is False
        assert len(constructed) == 1 and not any(d.requests for d in constructed[0].drivers.values())
        original_source = Path(constructed[0].spec["source"])
        before_source = files(original_source)
        ack = hub.control("mission", "start", allow_local_workers=True)
        assert ack["status"] == "ACK" and ack["terminal"] is False
        deadline = time.monotonic() + 20
        while True:
            captured = hub.snapshot("mission")
            if not captured["controller"]["running"]:
                break
            assert time.monotonic() < deadline, "isolated producer fixture did not complete"
            time.sleep(0.01)
        snap = captured["snapshot"]
        assert captured["controller"]["error"] is None
        assert snap["phase"] == "COMPLETED" and snap["all_verified"] is True
        assert snap["project_verified"] is True
        assert type(snap["integration"]["current"]) is bool
        assert snap["integration"]["current"] is True
        assert set(snap["integration"]["evidence"]["payload"]) == VERIFICATION_KEYS
        assert all(value is None for value in snap["budgets"].values())
        assert set(snap["budget_display"].values()) == {"unlimited"}
        assert all(run["receipt"]["actual_model"] is None for run in snap["runs"])
        # Exact Stub type was checked before Start; probe here is stub metadata.
        stub_metadata = {name: d.probe() for name, d in constructed[0].drivers.items()}
        assert all(meta["version"] == "PROTOCOL-STUB-NOT-A-MODEL" for meta in stub_metadata.values())
        after_source = files(original_source)
        retained = root / "s0-producer-evidence"
        retained.mkdir()
        roundtripped = json.loads(json.dumps(captured, allow_nan=False))
        (retained / "captured-envelope.json").write_text(json.dumps(roundtripped, ensure_ascii=False, indent=2))
        (retained / "original-source-full-tree.json").write_text(json.dumps({
            "before": before_source, "after": after_source,
        }, ensure_ascii=False, indent=2))
        (retained / "dependency-checks-and-receipts.json").write_text(json.dumps({
            "task_verification": [n["verification"] for n in snap["nodes"]],
            "integration_evidence": snap["integration"]["evidence"],
            "run_receipts": [r["receipt"] for r in snap["runs"]],
            "stub_probe_metadata_not_native": stub_metadata,
        }, ensure_ascii=False, indent=2))
        assert before_source == after_source, "isolated original fixture source changed"
        return roundtripped
    finally:
        hub.close()


def test_fc01_ms02_ms03_ms10_actual_captured_envelope(tmp_path):
    payload = _capture_real_producer(tmp_path)
    result = _project(payload)
    _assert_closed_schema(result)
    assert result["conclusion"]["stage"] == "PROJECT_VERIFIED_AS_CAPTURED"
    captured = payload["snapshot"]["integration"]["evidence"]["payload"]["evidence"]
    integrated = result["integration"]["result"]
    assert result["integration"]["current"]["value"] is True
    assert result["integration"]["stage"] == "INTEGRATION_VERIFIED_AS_CAPTURED"
    assert integrated["acceptance_hash"]["value"] == captured["acceptance_hash"]
    assert integrated["deliverable"]["candidate_hash"]["value"] == captured["candidate_hash"]
    for row in integrated["deliverable"]["patch"]["rows"]:
        assert {"before": row["before"], "after": row["after"]} == captured["patch"][row["path"]]
    for check, raw_check in zip(integrated["checks"], captured["checks"], strict=True):
        assert check["check"]["value"] == raw_check["check"]
        assert check["status"]["value"] == raw_check["classification"]["status"]
        assert check["summary"]["value"] == raw_check["classification"]["summary"]
        assert check["check_hash"]["value"] == raw_check["check_hash"]
    assert [r["value"] for r in integrated["review"]["reasons"]] == captured["review"]["reasons"]
    assert [r["value"] for r in integrated["review"]["evidence_refs"]] == captured["review"]["evidence"]
    assert integrated["review"]["run_key"]["value"] == captured["review"]["run_key"]
    assert "I claim success; not evidence" not in _json(result)
    _assert_fact_sources(payload, result)


def test_ms02_hub_id_generator_and_eight_key_serializer_are_source_pinned():
    root = Path(__file__).resolve().parents[2]
    console = ast.parse((root / "src/sisyfus/workers/lead_console.py").read_text())
    hub = next(x for x in console.body if isinstance(x, ast.ClassDef) and x.name == "MissionHub")
    create = next(x for x in hub.body if isinstance(x, ast.FunctionDef) and x.name == "create")
    assert any(isinstance(x, ast.Constant) and x.value == "mission" for x in ast.walk(create))
    assert any(isinstance(x, ast.BinOp) and isinstance(x.op, ast.Add)
               and isinstance(x.left, ast.Constant) and x.left.value == "m_"
               and isinstance(x.right, ast.Call) and isinstance(x.right.func, ast.Attribute)
               and x.right.func.attr == "token_hex" and len(x.right.args) == 1
               and isinstance(x.right.args[0], ast.Constant) and x.right.args[0].value == 16
               for x in ast.walk(create))
    for ident in ("mission", "m_" + "0123456789abcdef" * 2):
        payload = _envelope()
        payload["id"] = ident
        assert _project(payload)["question"]["mission_id"]["value"] == ident
    models = ast.parse((root / "src/sisyfus/autonomy/models.py").read_text())
    verification = next(x for x in models.body if isinstance(x, ast.ClassDef) and x.name == "VerificationResult")
    serializer = next(x for x in verification.body if isinstance(x, ast.FunctionDef) and x.name == "as_dict")
    dictionaries = [x.value for x in ast.walk(serializer)
                    if isinstance(x, ast.Return) and isinstance(x.value, ast.Dict)]
    assert len(dictionaries) == 1
    assert {x.value for x in dictionaries[0].keys} == VERIFICATION_KEYS


def test_fc02_excluded_native_and_private_fields_never_become_result():
    payload = _envelope(integrated=True)
    markers = ["native-prose-marker", "usage-marker", "session-marker", "requested-model-marker",
               "prompt-marker", "private-driver-report-marker", "role-private-marker"]
    data = _data(payload)
    data.update(output=markers[0], usage=markers[1], session_id=markers[2], requested_model=markers[3],
                prompt=markers[4], materialization={"driver_report": markers[5]})
    run = _run()
    run.update(role_metadata={"private": markers[6]}, request={"prompt": markers[4]})
    run["receipt"].update(output=markers[0], usage=markers[1], session_id=markers[2], requested_model=markers[3])
    payload["snapshot"]["runs"] = [run]
    payload["snapshot"]["nodes"][0]["title"] = "invented-title-marker"
    result = _project(payload)
    _assert_closed_schema(result)
    assert not any(marker in _json(result) for marker in markers + ["invented-title-marker", data["candidate"]])


def test_fc03_empty_result_has_question_then_nonacceptance_conclusion():
    payload = _envelope()
    payload["snapshot"]["integration"]["current"] = None
    result = _project(payload)
    _assert_closed_schema(result)
    assert result["tasks"] == [] and result["attempts"] == []
    assert result["conclusion"]["stage"] == "NO_ENGINEERING_RESULT_RECORDED"
    statements = result["conclusion"]["statements"]
    assert statements[0]["template_id"] == "Q01"
    assert statements[0]["text"] == TEMPLATES["Q01"].format(objective=payload["snapshot"]["objective"])
    assert statements[1]["text"] == TEMPLATES["C01"]
    assert "PASS" not in _json(result)
    assert result["diagnostics"] == []


@pytest.mark.parametrize("state,run_status,expected", [
    ("READY", None, "PENDING"), ("RUNNING", None, "IN_PROGRESS"),
    ("VERIFYING", None, "IN_PROGRESS"), ("READY", "IN_FLIGHT", "IN_PROGRESS"),
])
def test_fc04_pending_and_inflight_do_not_invent_candidate_or_measurement(state, run_status, expected):
    payload = _envelope()
    node = _node()
    node["state"] = state
    payload["snapshot"]["nodes"] = [node]
    if run_status:
        payload["snapshot"]["runs"] = [{"key": "worker:build:1", "task_id": "build", "status": run_status, "receipt": None}]
    task = _project(payload)["tasks"][0]
    assert task["stage"] == expected
    assert task["deliverable"] is None and task["checks"] == []
    assert task["review"]["recorded"] is False and task["diagnostics"] == []


@pytest.mark.parametrize("native,transport,expected", [
    ("COMPLETED", "RECEIPTED", "CANDIDATE_RECORDED"), ("UNKNOWN", "UNKNOWN", "PENDING"),
])
def test_fc05_receipt_candidate_remains_unverified_and_unknown_not_upgraded(native, transport, expected):
    payload = _envelope()
    payload["snapshot"]["nodes"] = [_node()]
    payload["snapshot"]["runs"] = [_run(native=native, status=transport)]
    if native == "UNKNOWN":
        payload["snapshot"]["unresolved"] = ["worker:build:1"]
    result = _project(payload)
    assert result["tasks"][0]["stage"] == expected
    assert result["attempts"][0]["unverified_candidate"]["candidate_hash"]["value"] == SHA_A
    assert result["tasks"][0]["deliverable"] is None
    assert result["tasks"][0]["uncertain_run_keys"] == (["worker:build:1"] if native == "UNKNOWN" else [])


@pytest.mark.parametrize("status", ["FAIL", "ERROR", "INVALID", "INCONCLUSIVE"])
def test_fc06_recorded_check_failure_is_not_reclassified(status):
    payload = _envelope(verified=True)
    node = payload["snapshot"]["nodes"][0]
    node.update(verdict=status, state="FAILED")
    node["verification"]["verdict"] = status
    data = _data(payload)
    data.pop("review")
    data["checks"][0]["classification"] = {"status": status, "summary": "Evaluator classification unchanged"}
    task = _project(payload)["tasks"][0]
    assert task["stage"] == "NOT_ACCEPTED"
    assert task["checks"][0]["status"]["value"] == status
    assert task["checks"][0]["summary"]["value"] == "Evaluator classification unchanged"
    assert task["review"]["recorded"] is False and task["diagnostics"] == []


@pytest.mark.parametrize("verdict,refs", [("FAIL", ["check:unit"]), ("INVALID", [])])
def test_fc07_pass_check_with_failed_or_invalid_review_not_accepted(verdict, refs):
    payload = _envelope(verified=True)
    node = payload["snapshot"]["nodes"][0]
    node.update(verdict=verdict, state="FAILED")
    node["verification"]["verdict"] = verdict
    _data(payload)["review"].update(verdict=verdict, evidence=refs, reasons=["Canonical reviewer objection"])
    task = _project(payload)["tasks"][0]
    assert task["stage"] == "NOT_ACCEPTED"
    assert task["review"]["verdict"]["value"] == verdict
    assert task["review"]["reasons"][0]["value"] == "Canonical reviewer objection"
    assert task["diagnostics"] == []


def test_fc08_ms01_complete_task_and_substantive_statements():
    payload = _envelope(verified=True)
    result = _project(payload)
    _assert_closed_schema(result)
    task = result["tasks"][0]
    assert task["stage"] == "TASK_VERIFIED_AS_CAPTURED"
    assert task["currentness"]["label"] == "CURRENT_AS_CAPTURED"
    assert result["conclusion"]["stage"] == "TASK_EVIDENCE_RECORDED_INTEGRATION_PENDING"
    statements = result["conclusion"]["statements"]
    text = "\n".join(s["text"] for s in statements)
    for path in ("added.txt", "modified.txt", "removed.txt"):
        assert path in text
    for sha in (SHA_B, SHA_C, SHA_D, SHA_E):
        assert sha[:12] in text
    assert "前12位" in text and "unit" in text
    assert "Evaluator recorded fixture pass" in text and "score=0.5" in text
    assert "Reviewer inspected fixture receipts" in text and "check:unit" in text
    assert {"D01", "M01", "M02", "R01", "R02"} <= {s["template_id"] for s in statements}


@pytest.mark.parametrize("field", ["candidate_hash", "acceptance_hash", "task_hash", "checks", "review", "check_hashes", "dependencies"])
def test_ms01_missing_required_positive_evidence_never_auto_passes(field):
    payload = _envelope(verified=True)
    _data(payload).pop(field)
    task = _project(payload)["tasks"][0]
    assert task["stage"] != "TASK_VERIFIED_AS_CAPTURED"


def test_ms01_empty_checks_are_not_vacuous_pass():
    payload = _envelope(verified=True)
    data = _data(payload)
    data.update(checks=[], check_hashes={})
    data["review"]["evidence"] = []
    assert _project(payload)["tasks"][0]["stage"] != "TASK_VERIFIED_AS_CAPTURED"


@pytest.mark.parametrize("changes,label", [
    ({"stale": True}, "STALE"), ({"active": False, "superseded_by": "x2"}, "SUPERSEDED"),
    ({"active": False}, "INACTIVE"), ({"state": "READY"}, "STATE_NOT_SUCCEEDED"),
])
def test_fc09_fc10_historical_pass_is_not_current(changes, label):
    payload = _envelope(verified=True)
    payload["snapshot"]["nodes"][0].update(changes)
    task = _project(payload)["tasks"][0]
    assert task["stage"] == "HISTORICAL_RESULT" and task["currentness"]["label"] == label
    assert task["currentness"]["active"]["value"] is changes.get("active", True)
    assert task["currentness"]["stale"]["value"] is changes.get("stale", False)


@pytest.mark.parametrize("mutation,code", [
    ("candidate", "CANDIDATE_HASH_MISMATCH"), ("check_hash", "CHECK_HASH_MISMATCH"),
    ("check_set", "CHECK_HASH_MISMATCH"), ("check_name", "CHECK_NAME_MISMATCH"),
    ("review_key", "REVIEW_RUN_KEY_MISMATCH"), ("review_refs", "REVIEW_REFERENCE_MISMATCH"),
    ("review_candidate", "CANDIDATE_HASH_MISMATCH"), ("payload_verdict", "VERDICT_MISMATCH"),
    ("unverified", "VERDICT_MISMATCH"),
])
def test_fc11_evidence_conflicts_have_fixed_diagnostics(mutation, code):
    payload = _envelope(verified=True)
    node, data = payload["snapshot"]["nodes"][0], _data(payload)
    if mutation == "candidate": data["checks"][0]["candidate_hash"] = SHA_E
    elif mutation == "check_hash": data["check_hashes"]["unit"] = SHA_E
    elif mutation == "check_set": data["check_hashes"]["extra"] = SHA_F
    elif mutation == "check_name": node["check"] = "other-check"
    elif mutation == "review_key": data["review"]["run_key"] = "review:wrong-key"
    elif mutation == "review_refs": data["review"]["evidence"] = []
    elif mutation == "review_candidate": data["review"]["candidate_hash"] = SHA_E
    elif mutation == "payload_verdict": node["verification"]["verdict"] = "FAIL"
    elif mutation == "unverified": node["verdict"] = "UNVERIFIED"
    task = _project(payload)["tasks"][0]
    assert task["stage"] == "EVIDENCE_CONFLICT" and code in _codes(task)


def test_fc12_three_delta_kinds_preserve_distinct_full_hashes():
    result = _project(_envelope(verified=True))
    artifact = result["tasks"][0]["deliverable"]
    assert artifact["candidate_location"] == "WITHHELD_ABSOLUTE_LOCATOR"
    assert artifact["candidate_hash"]["value"] == SHA_A
    patch = artifact["patch"]
    assert patch["row_count"] == 3 and patch["withheld_count"] == 0
    assert [(r["path"], r["change_kind"], r["before"], r["after"]) for r in patch["rows"]] == [
        ("added.txt", "ADDED", None, SHA_B), ("modified.txt", "MODIFIED", SHA_C, SHA_D),
        ("removed.txt", "REMOVED", SHA_E, None),
    ]


@pytest.mark.parametrize("before,after,code", [
    (None, None, "MALFORMED_DELTA"), (SHA_B, SHA_B, "MALFORMED_DELTA"),
    (None, "B" * 64, "HASH_INVALID"), (None, "b" * 63, "HASH_INVALID"),
])
def test_fc12_malformed_delta_and_hash_do_not_count_as_delivery(before, after, code):
    payload = _envelope(verified=True)
    _data(payload)["patch"] = {"malformed.txt": {"before": before, "after": after}}
    task = _project(payload)["tasks"][0]
    assert code in _codes(task) and task["stage"] != "TASK_VERIFIED_AS_CAPTURED"
    assert task["deliverable"]["patch"]["rows"][0]["change_kind"] == "MALFORMED"


@pytest.mark.parametrize("path", ["/abs", "a/../b", "C:x", "a\\b", "a/\u202eb", "a//b", "a/%2e%2e/b", "https:x"])
def test_fc12_unsafe_path_and_pointer_withhold_original_label(path):
    payload = _envelope(verified=True)
    _data(payload)["patch"] = {path: {"before": None, "after": SHA_B}}
    task = _project(payload)["tasks"][0]
    row = task["deliverable"]["patch"]["rows"][0]
    assert row["path"] is None and row["change_kind"] == "WITHHELD"
    assert row["row_ordinal"] == 0
    assert row["source"] == "/snapshot/nodes/0/verification/evidence/patch"
    assert "UNSAFE_PATH" in _codes(task)
    assert path not in _json(task)


@pytest.mark.parametrize("path", [".env", "x/holdout/y", ".ssh/id_rsa", "keys/key.pem", ".aws/config"])
def test_fc12_sensitive_path_withholds_label_not_recorded_delta_hash(path):
    payload = _envelope(verified=True)
    _data(payload)["patch"] = {path: {"before": None, "after": SHA_B}}
    task = _project(payload)["tasks"][0]
    row = task["deliverable"]["patch"]["rows"][0]
    assert row["path"] is None and row["change_kind"] == "ADDED"
    assert row["after"] == SHA_B and row["before"] is None
    assert "WITHHELD_SENSITIVE_PATH" in _codes(task)
    assert path not in _json(task)


def test_fc12_dotgithub_is_a_deliverable_and_empty_patch_is_honest():
    payload = _envelope(verified=True)
    _data(payload)["patch"] = {".github/workflows/ci.yml": {"before": None, "after": SHA_B}}
    assert _project(payload)["tasks"][0]["deliverable"]["patch"]["rows"][0]["path"] == ".github/workflows/ci.yml"
    _data(payload)["patch"] = {}
    result = _project(payload)
    assert result["tasks"][0]["deliverable"]["patch"]["row_count"] == 0
    assert any(s["template_id"] == "D01" and s["text"] == "未记录文件增量"
               for s in result["conclusion"]["statements"])


@pytest.mark.parametrize("field,key", [("patch", "cfg/secret.py"), ("dependencies", "rotate-token"), ("check_hashes", "api_key")])
def test_fc13_capture_redaction_is_not_a_conflict_and_never_positive(field, key):
    payload = _envelope(verified=True)
    _data(payload)[field] = {key: "[REDACTED]"}
    task = _project(payload)["tasks"][0]
    assert task["stage"] not in {"TASK_VERIFIED_AS_CAPTURED", "EVIDENCE_CONFLICT"}
    assert any(type(x) is dict and (x.get("state") == "REDACTED_AT_CAPTURE"
               or x.get("change_kind") == "REDACTED_AT_CAPTURE") for x in _walk(task))
    assert "CHECK_HASH_MISMATCH" not in _codes(task)
    assert "DEPENDENCY_EVIDENCE_MISMATCH" not in _codes(task)


@pytest.mark.parametrize("raw,expected,state", [
    ("sk-abcdefghijklmnop", "[REDACTED]", "FILTERED"),
    ("Bearer synthetic.fixture.secret", "Bearer [REDACTED]", "FILTERED"),
    ("AKIAABCDEFGHIJKLMNOP", "[REDACTED]", "FILTERED"),
    ("ghp_" + "a" * 36, "[REDACTED]", "FILTERED"),
    ("xoxb-abcdefghijk", "[REDACTED]", "FILTERED"),
    ("password=synthetic", "password=[REDACTED]", "FILTERED"),
    ("x\x00\x7f\u202ey", "x\ufffd\ufffd\ufffdy", "FILTERED"),
    ("-----BEGIN PRIVATE KEY-----\nsynthetic", None, "REDACTED_AT_CAPTURE"),
    ("<script>alert(1)</script>", "<script>alert(1)</script>", "RECORDED"),
    ("lines\nand\ttabs", "lines\nand\ttabs", "RECORDED"),
])
def test_fc14_text_filter_and_original_source_provenance(raw, expected, state):
    payload = _envelope(verified=True)
    payload["snapshot"]["objective"] = raw
    _data(payload)["review"]["reasons"] = [raw]
    result = _project(payload)
    for fact in (result["question"]["objective"], result["tasks"][0]["review"]["reasons"][0]):
        assert fact["state"] == state and fact["value"] == expected
        assert _resolve(payload, fact["source"]) == raw
    if state != "RECORDED":
        assert raw not in _json(result)


def test_fc15_measurement_selects_only_bounded_finite_scalars_with_exact_counts():
    payload = _envelope(verified=True)
    _data(payload)["checks"][0]["measurement"] = {
        "execution": {"exit_code": 1, "timed_out": False, "error": "withheld error text"},
        "score": 0.5, "notes": "withheld note", "token_count": 3, "nan": float("nan"),
    }
    task = _project(payload)["tasks"][0]
    measured = task["checks"][0]["measurement"]
    assert [(x["name"], x["value"]) for x in measured["scalars"]] == [
        ("execution.exit_code", 1), ("execution.timed_out", False), ("score", 0.5),
    ]
    assert measured["withheld_count"] == 4 and measured["omitted_scalar_count"] == 0
    assert measured["complete"] is False and measured["execution_error_recorded"] is True
    assert "NUMERIC_NONFINITE" in _codes(task)
    assert "withheld error text" not in _json(task) and "token_count" not in _json(task)


def test_fc15_measurement_64_selection_has_precise_omission_count():
    payload = _envelope(verified=True)
    _data(payload)["checks"][0]["measurement"] = {f"score_{i:03d}": i for i in range(70)}
    measured = _project(payload)["tasks"][0]["checks"][0]["measurement"]
    assert [x["name"] for x in measured["scalars"]] == [f"score_{i:03d}" for i in range(64)]
    assert measured["withheld_count"] == 0 and measured["omitted_scalar_count"] == 6
    assert measured["complete"] is False


def test_fc15_measurement_visit_overflow_is_rejection_not_partial_answer():
    payload = _envelope(verified=True)
    _data(payload)["checks"][0]["measurement"] = {f"score_{i:04d}": i for i in range(4097)}
    _reject(payload, "LIMIT_EXCEEDED")


@pytest.mark.parametrize("value", [float("inf"), -float("inf"), float("nan"), 2**63, -(2**63) - 1])
def test_r04_measurement_bad_numeric_values_do_not_escape(value):
    payload = _envelope(verified=True)
    _data(payload)["checks"][0]["measurement"] = {"value": value}
    task = _project(payload)["tasks"][0]
    assert task["checks"][0]["measurement"]["scalars"] == []
    assert ("NUMERIC_NONFINITE" if type(value) is float else "MALFORMED") in _codes(task)


def test_fc16_build_only_is_candidate_and_sparse_error_is_not_a_conflict():
    payload = _envelope()
    payload["snapshot"]["integration"]["builds"] = [
        {"key": "build:1", "created_at": "2026-01-01T00:00:00Z", "data": _artifact("whole", "integration:1")},
        {"key": "build:2", "created_at": "2026-01-01T00:00:01Z", "data": {"status": "ERROR", "run_key": "build:2"}},
    ]
    integration = _project(payload)["integration"]
    assert integration["stage"] == "INTEGRATION_CANDIDATE_RECORDED"
    assert integration["result"] is None
    assert all(x["label"] == "CANDIDATE_ONLY_NOT_ACCEPTANCE" for x in integration["builds"])
    assert integration["builds"][1]["candidate_hash"]["state"] == "NOT_RECORDED"
    assert integration["diagnostics"] == []


@pytest.mark.parametrize("mutation,code", [
    ("continuation", "INTEGRATION_CONTINUATION_MISMATCH"),
    ("revision", "INTEGRATION_REVISION_MISMATCH"),
    ("dependency", "DEPENDENCY_EVIDENCE_MISMATCH"),
])
def test_fc16_current_true_integration_conflicts_cannot_be_promoted(mutation, code):
    payload = _envelope(integrated=True)
    integrated = payload["snapshot"]["integration"]
    if mutation == "continuation": integrated["evidence"]["continuation_id"] = "wrong-continuation"
    elif mutation == "revision": integrated["continuation"]["context"]["lead_integration"] = 2
    else: integrated["evidence"]["payload"]["evidence"]["dependencies"]["build"] = 102
    result = _project(payload)
    assert result["integration"]["stage"] == "EVIDENCE_CONFLICT"
    assert code in _codes(result["integration"])
    assert result["conclusion"]["stage"] == "CAPTURE_CONFLICT"


def test_ms05_missing_integration_revision_is_not_recorded_and_never_verified():
    payload = _envelope(integrated=True)
    payload["snapshot"]["integration"]["continuation"]["context"].pop("lead_integration")
    result = _project(payload)
    assert result["integration"]["lead_integration_revision"]["state"] == "NOT_RECORDED"
    assert result["integration"]["stage"] != "INTEGRATION_VERIFIED_AS_CAPTURED"
    assert result["conclusion"]["stage"] != "PROJECT_VERIFIED_AS_CAPTURED"


@pytest.mark.parametrize("current", [False, None, "yes", {}])
def test_fc16_false_missing_or_malformed_current_never_upgrade(current):
    payload = _envelope(integrated=True)
    payload["snapshot"].update(phase="IMPLEMENTING", project_verified=False, all_verified=False)
    payload["snapshot"]["integration"]["current"] = current
    result = _project(payload)
    assert result["integration"]["stage"] != "INTEGRATION_VERIFIED_AS_CAPTURED"
    if type(current) not in (bool, type(None)):
        assert "CURRENT_FLAG_SHAPE" in _codes(result["integration"])
    else:
        assert result["integration"]["stage"] == "HISTORICAL_RESULT"


@pytest.mark.parametrize("flags", [
    {"project_verified": True, "all_verified": False},
    {"project_verified": False, "all_verified": True},
    {"project_verified": 1, "all_verified": False},
    {"project_verified": False, "all_verified": "true"},
])
def test_fc17_inconsistent_controller_flags_cannot_become_success(flags):
    payload = _envelope()
    payload["snapshot"].update(flags)
    assert _project(payload)["conclusion"]["stage"] == "CAPTURE_CONFLICT"


def test_fc17_missing_controller_flags_are_not_recorded_not_inferred_from_tasks():
    payload = _envelope(integrated=True)
    payload["snapshot"].update(phase="IMPLEMENTING")
    payload["snapshot"].pop("project_verified")
    payload["snapshot"].pop("all_verified")
    result = _project(payload)
    assert result["conclusion"]["stage"] == "INTEGRATION_EVIDENCE_RECORDED_PROJECT_NOT_VERIFIED"
    assert result["control"]["project_verified"]["state"] == "NOT_RECORDED"
    assert result["control"]["all_verified"]["state"] == "NOT_RECORDED"


def test_fc17_divergent_acceptance_hash_is_capture_conflict():
    payload = _envelope(verified=True)
    second = _node("other", verified=True, evidence_id=102)
    second["verification"]["evidence"]["acceptance_hash"] = SHA_E
    payload["snapshot"]["nodes"].append(second)
    result = _project(payload)
    assert result["conclusion"]["stage"] == "CAPTURE_CONFLICT"
    assert "ACCEPTANCE_HASH_DIVERGENT" in _codes(result)


@pytest.mark.parametrize("phase", ["STOPPED", "PAUSED", "UNKNOWN", "TRIAL_FENCED", "STALE"])
def test_fc18_control_context_preserves_history_not_live_termination(phase):
    payload = _envelope(verified=True)
    payload["snapshot"].update(phase=phase, stopped=phase == "STOPPED", paused=phase == "PAUSED")
    payload["snapshot"]["unresolved"] = ["unassociated:unknown"]
    result = _project(payload)
    assert result["tasks"][0]["stage"] == "TASK_VERIFIED_AS_CAPTURED"
    assert result["control"]["unresolved"][0]["associated_task_id"] is None
    text = next(s["text"] for s in result["conclusion"]["statements"] if s["template_id"] == "K01")
    assert phase in text and "已终止" not in text and "已完成" not in text


@pytest.mark.parametrize("value", [None, [], (), "fixture input marker", 1])
def test_fc19_required_envelope_exact_type_errors_are_content_free(value):
    _reject(value, "INPUT_TYPE")


def test_fc19_dict_subclass_is_rejected_without_inspection():
    class Derived(dict):
        def __iter__(self):
            raise AssertionError("dict subclass iterated")
    _reject(Derived(_envelope()), "INPUT_TYPE")


@pytest.mark.parametrize("mutation", ["extra", "missing"])
def test_fc19_exact_envelope_keys(mutation):
    payload = _envelope()
    if mutation == "extra": payload["unexpected-private-key"] = _Unselected()
    else: payload.pop("controls")
    _reject(payload, "ENVELOPE_KEYS")


@pytest.mark.parametrize("ident", ["", "/private/fixture", "has space", "a" * 129, "任务", "x\ud800"])
def test_fc19_mission_identity_is_not_reconstructed_or_echoed(ident):
    payload = _envelope()
    payload["id"] = ident
    _reject(payload, "MISSION_ID_INVALID")


@pytest.mark.parametrize("field,value", [
    ("objective", None), ("revision", True), ("revision", -1), ("revision", 1.0),
    ("resume_epoch", 2**63), ("nodes", ()), ("runs", {}), ("integration", []), ("unresolved", ()),
])
def test_fc19_required_snapshot_field_shapes(field, value):
    payload = _envelope()
    payload["snapshot"][field] = value
    _reject(payload, "SNAPSHOT_REQUIRED_FIELD")


def test_fc19_missing_objective_and_invalid_required_text_encoding():
    payload = _envelope()
    payload["snapshot"].pop("objective")
    _reject(payload, "SNAPSHOT_REQUIRED_FIELD")
    payload = _envelope()
    payload["snapshot"]["objective"] = "x\ud800"
    _reject(payload, "TEXT_ENCODING")


@pytest.mark.parametrize("field,count", [("nodes", 257), ("runs", 2049), ("unresolved", 2049)])
def test_fc19_required_list_cardinality_caps(field, count):
    payload = _envelope()
    item = _node() if field == "nodes" else (_run() if field == "runs" else "uncertain:1")
    payload["snapshot"][field] = [copy.deepcopy(item) for _ in range(count)]
    _reject(payload, "LIMIT_EXCEEDED")


@pytest.mark.parametrize("field,count", [
    ("patch", 513), ("checks", 65), ("check_hashes", 65), ("dependencies", 65),
    ("review_reasons", 65), ("review_evidence", 65),
])
def test_r02_artifact_and_review_structural_caps_reject(field, count):
    payload = _envelope(verified=True)
    data = _data(payload)
    if field == "patch": data[field] = {f"file{i}.txt": {"before": None, "after": SHA_B} for i in range(count)}
    elif field == "checks": data[field] = [copy.deepcopy(data[field][0]) for _ in range(count)]
    elif field in {"dependencies", "check_hashes"}: data[field] = {f"key{i}": SHA_F for i in range(count)}
    elif field == "review_reasons": data["review"]["reasons"] = ["reason"] * count
    else: data["review"]["evidence"] = ["check:unit"] * count
    _reject(payload, "LIMIT_EXCEEDED")


@pytest.mark.parametrize("field", ["depends_on", "write_paths"])
def test_r02_task_structural_caps_reject(field):
    payload = _envelope(verified=True)
    payload["snapshot"]["nodes"][0][field] = [f"item{i}" for i in range(65)]
    _reject(payload, "LIMIT_EXCEEDED")


def test_r02_build_cardinality_cap_rejects():
    payload = _envelope()
    payload["snapshot"]["integration"]["builds"] = [{"key": f"build:{i}", "data": {"status": "ERROR"}} for i in range(257)]
    _reject(payload, "LIMIT_EXCEEDED")


def test_fc19_objective_length_reject_and_optional_text_withholding_are_distinct():
    payload = _envelope()
    payload["snapshot"]["objective"] = "q" * 20001
    _reject(payload, "LIMIT_EXCEEDED")
    payload = _envelope(verified=True)
    text = "r" * 16385
    _data(payload)["review"]["reasons"] = [text]
    task = _project(payload)["tasks"][0]
    fact = task["review"]["reasons"][0]
    assert fact["state"] == "WITHHELD" and fact["value"] is None
    assert fact["utf8_bytes"] == 16385 and "TEXT_LIMIT" in _codes(task)
    assert task["stage"] != "TASK_VERIFIED_AS_CAPTURED" and text not in _json(task)


@pytest.mark.parametrize("branch", ["measurement", "verification", "integration_payload"])
def test_ms06_fc19_every_selected_cycle_is_rejected(branch):
    payload = _envelope(verified=True)
    if branch == "measurement":
        cycle = {}
        cycle["nested"] = cycle
        _data(payload)["checks"][0]["measurement"] = cycle
    elif branch == "verification":
        verification = payload["snapshot"]["nodes"][0]["verification"]
        verification["evidence"] = verification
    else:
        payload = _envelope(integrated=True)
        evidence = payload["snapshot"]["integration"]["evidence"]
        evidence["payload"] = evidence
    _reject(payload, "INPUT_CYCLE")


def test_fc19_ms14_total_visits_and_output_budget_are_independent():
    payload = _envelope()
    payload["snapshot"]["nodes"] = [_node(f"task{i}", verified=True, evidence_id=i + 1) for i in range(256)]
    for node in payload["snapshot"]["nodes"]:
        node["verification"]["evidence"]["checks"][0]["measurement"] = {f"v{i:04d}": i for i in range(1600)}
    _reject(payload, "VISIT_LIMIT")

    payload = _envelope()
    payload["snapshot"]["nodes"] = [_node(f"task{i}") for i in range(256)]
    for node in payload["snapshot"]["nodes"]:
        node.update(objective="o" * 20000, acceptance="a" * 20000)
    _reject(payload, "OUTPUT_LIMIT")


def test_fc20_import_surface_and_no_mutable_global_writes():
    module = _public()
    tree = ast.parse(Path(module.__file__).read_text())
    allowed = {"__future__", "json", "math", "re", "typing"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name in allowed for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module in allowed
        assert not isinstance(node, (ast.Global, ast.Nonlocal))
    payload = _envelope(integrated=True)
    assert _project(payload)["conclusion"]["stage"] == "PROJECT_VERIFIED_AS_CAPTURED"


def test_ms06_fc20_unselected_poison_and_cycles_are_not_visited_or_copied():
    payload = _envelope(integrated=True)
    cycle = {}
    cycle["cycle"] = cycle
    payload["controller"] = _Unselected()
    payload["controls"] = cycle
    snap = payload["snapshot"]
    for key in ("plans", "diagnoses", "format_errors", "controller_errors", "procedure", "rsi",
                "usage", "session", "request", "prompt", "cwd", "counters", "budgets",
                "roles", "versions", "placement_preparation", "future_extra"):
        snap[key] = cycle if key == "plans" else _Unselected()
    _data(payload)["output"] = _Unselected()
    _data(payload)["materialization"] = cycle
    assert _project(payload)["conclusion"]["stage"] == "PROJECT_VERIFIED_AS_CAPTURED"


def test_fc21_input_is_unchanged_and_every_output_container_is_detached():
    payload = _envelope(integrated=True)
    before = copy.deepcopy(payload)
    result = _project(payload)
    assert payload == before
    input_ids = {id(x) for x in _walk(payload) if type(x) in (dict, list)}
    output_ids = {id(x) for x in _walk(result) if type(x) in (dict, list)}
    assert input_ids.isdisjoint(output_ids)
    result["tasks"][0]["acceptance_fingerprints"]["dependencies"].append({"mutated": True})
    result["tasks"][0]["deliverable"]["patch"]["rows"][0]["after"] = "mutated"
    assert payload == before
    assert "mutated" not in _json(_project(payload))


def test_r05_nonancestor_shared_selected_objects_are_allowed_not_cycles():
    payload = _envelope(verified=True)
    second = _node("other", verified=True, evidence_id=102)
    second["verification"]["evidence"] = _data(payload)
    payload["snapshot"]["nodes"].append(second)
    result = _project(payload)
    assert all(t["stage"] == "TASK_VERIFIED_AS_CAPTURED" for t in result["tasks"])


def _reverse_dicts(value):
    if type(value) is dict:
        return {key: _reverse_dicts(child) for key, child in reversed(list(value.items()))}
    if type(value) is list:
        return [_reverse_dicts(child) for child in value]
    return value


def test_fc22_equal_inputs_and_key_permutations_have_identical_ordered_json_bytes():
    payload = _envelope(integrated=True)
    first = _project(payload)
    assert first == _project(payload)
    assert _json(first).encode() == _json(_project(payload)).encode()
    assert _json(first).encode() == _json(_project(_reverse_dicts(payload))).encode()


def _assert_fact_sources(payload, result):
    for fact in _walk(result):
        if type(fact) is dict and {"state", "value", "source"} <= fact.keys():
            if fact["state"] == "RECORDED":
                raw = _resolve(payload, fact["source"])
                assert type(raw) is type(fact["value"])
                assert raw == fact["value"]
            elif fact["state"] == "FILTERED":
                assert _resolve(payload, fact["source"]) != fact["value"]


def test_fc23_ms04_provenance_is_original_recorded_source_not_fake_pin():
    payload = _envelope(integrated=True)
    patch = _data(payload)["patch"]
    patch["src/a~b/c.txt"] = {"before": None, "after": SHA_D}
    result = _project(payload)
    _assert_fact_sources(payload, result)
    row = next(x for x in result["tasks"][0]["deliverable"]["patch"]["rows"] if x["path"] == "src/a~b/c.txt")
    assert row["source"].endswith("/src~1a~0b~1c.txt")
    assert _resolve(payload, row["source"]) == patch["src/a~b/c.txt"]
    provenance = result["provenance"]
    assert provenance["mission_id_source"] == "/id" and provenance["pinned"] is False
    assert provenance["capture_basis"] == "CALLER_CAPTURED_NON_ATOMIC"
    assert provenance["bytes_reverified"] is False and provenance["projection_is_acceptance"] is False
    assert provenance["event_cursor"] is None and provenance["event_head_hash"] is None
    assert provenance["captured_at"] is None
    assert provenance["redaction"] == "UPSTREAM_CONTROLLER_REDACT_ASSUMED_PLUS_S0_PATTERN_FILTER_NOT_DLP"
    assert type(provenance["selected_source_fields"]) is list and provenance["selected_source_fields"]
    assert not any(type(x) is str and re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", x) for x in _walk(result))
    assert "title" not in result["tasks"][0]


def test_fc24_exact_review_and_attempt_associations_without_role_guessing():
    payload = _envelope(integrated=True)
    review_key = _data(payload)["review"]["run_key"]
    integration_key = payload["snapshot"]["integration"]["evidence"]["payload"]["evidence"]["review"]["run_key"]
    payload["snapshot"]["runs"] = [
        _run(), _run(review_key, task="planner"), _run(integration_key, task="planner"),
        _run("unrelated:1", task="planner"),
    ]
    result = _project(payload)
    assert [a["association"] for a in result["attempts"]] == [
        "TASK_ATTEMPT", "TASK_REVIEW", "INTEGRATION_REVIEW", "MISSION_LEVEL",
    ]
    assert [a["associated_task_id"] for a in result["attempts"]] == ["build", "build", None, None]


def test_fc24_duplicate_run_keys_do_not_participate_in_association():
    payload = _envelope()
    payload["snapshot"]["nodes"] = [_node()]
    payload["snapshot"]["runs"] = [_run(), _run()]
    result = _project(payload)
    assert "DUPLICATE_ID" in _codes(result)
    assert result["tasks"][0]["stage"] == "PENDING"
    assert all(a["association"] == "MISSION_LEVEL" for a in result["attempts"])


def test_r06_duplicate_node_ids_suppress_all_duplicates_and_mission_success():
    payload = _envelope(verified=True)
    payload["snapshot"]["nodes"].append(copy.deepcopy(payload["snapshot"]["nodes"][0]))
    result = _project(payload)
    assert all(t["stage"] == "EVIDENCE_CONFLICT" for t in result["tasks"])
    assert result["conclusion"]["stage"] == "CAPTURE_CONFLICT"
    assert all("DUPLICATE_ID" in _codes(t) for t in result["tasks"])


@pytest.mark.parametrize("kind", ["checks", "review_refs"])
def test_r06_duplicate_check_identity_and_review_refs_are_conflicts(kind):
    payload = _envelope(verified=True)
    data = _data(payload)
    if kind == "checks": data["checks"].append(copy.deepcopy(data["checks"][0]))
    else: data["review"]["evidence"].append("check:unit")
    task = _project(payload)["tasks"][0]
    assert task["stage"] == "EVIDENCE_CONFLICT"
    assert ("DUPLICATE_ID" if kind == "checks" else "REVIEW_REFERENCE_MISMATCH") in _codes(task)


@pytest.mark.parametrize("kind", ["unknown", "cycle"])
def test_fc25_dependency_graph_invalid_suppresses_positive_labels(kind):
    payload = _envelope()
    if kind == "unknown":
        nodes = [_node("a", verified=True, depends=("missing",))]
    else:
        nodes = [_node("a", verified=True, depends=("b",), evidence_id=101),
                 _node("b", verified=True, depends=("a",), evidence_id=102)]
    payload["snapshot"]["nodes"] = nodes
    for node in nodes:
        node["verification"]["evidence"]["dependencies"] = {dep: 102 if dep == "b" else 101 for dep in node["depends_on"]}
    result = _project(payload)
    assert all(t["stage"] != "TASK_VERIFIED_AS_CAPTURED" for t in result["tasks"])
    assert all("DEPENDENCY_GRAPH_INVALID" in _codes(t) for t in result["tasks"])


@pytest.mark.parametrize("dependency", [101, "101", None, "missing"])
def test_ms01_r13_dependency_complete_keys_and_exact_evidence_identity(dependency):
    payload = _envelope(verified=True)
    downstream = _node("downstream", verified=True, depends=("build",), evidence_id=102)
    downstream["verification"]["evidence"]["dependencies"] = {} if dependency == "missing" else {"build": dependency}
    payload["snapshot"]["nodes"].append(downstream)
    task = _project(payload)["tasks"][1]
    if type(dependency) is int:
        assert task["stage"] == "TASK_VERIFIED_AS_CAPTURED"
        assert task["acceptance_fingerprints"]["dependencies"][0]["matches_captured_upstream"] is True
    else:
        assert task["stage"] != "TASK_VERIFIED_AS_CAPTURED"


def test_r03_old_missing_task_fields_and_sparse_failed_evidence_are_honest():
    payload = _envelope()
    node = _node()
    node.pop("acceptance")
    node.pop("write_paths")
    node.update(state="FAILED", verdict="ERROR", evidence_id=101,
                verification=_verification({"status": "ERROR", "run_key": "worker:build:1"}, "ERROR"))
    payload["snapshot"]["nodes"] = [node]
    task = _project(payload)["tasks"][0]
    assert task["stage"] == "NOT_ACCEPTED" and task["checks"] == []
    assert task["acceptance"]["state"] == "NOT_RECORDED"
    assert task["write_paths"]["state"] == "NOT_RECORDED"
    assert task["deliverable"]["candidate_hash"]["state"] == "NOT_RECORDED"
    assert task["diagnostics"] == []


def test_r18_failure_indicators_record_presence_without_error_text():
    payload = _envelope(verified=True)
    node = payload["snapshot"]["nodes"][0]
    node.update(state="FAILED", verdict="INVALID")
    node["verification"]["verdict"] = "INVALID"
    data = _data(payload)
    data.update(status="ERROR", integrity_error="integrity-private-message-marker",
                scope_error="scope-private-message-marker")
    data.pop("review")
    task = _project(payload)["tasks"][0]
    assert task["failure_indicators"]["native_status"]["value"] == "ERROR"
    assert task["failure_indicators"]["integrity_error_recorded"] is True
    assert task["failure_indicators"]["scope_error_recorded"] is True
    assert "integrity-private-message-marker" not in _json(task)
    assert "scope-private-message-marker" not in _json(task)


def test_r01_internal_custom_objects_are_diagnosed_without_repr_and_other_rows_survive():
    payload = _envelope(verified=True)
    payload["snapshot"]["nodes"].append(_Unselected())
    result = _project(payload)
    assert result["tasks"][0]["stage"] == "TASK_VERIFIED_AS_CAPTURED"
    assert "MALFORMED" in _codes(result)
    assert result["conclusion"]["stage"] != "PROJECT_VERIFIED_AS_CAPTURED"
    _assert_closed_schema(result)


def test_r04_unrecognized_enum_is_preserved_but_not_positive():
    payload = _envelope(verified=True)
    node = payload["snapshot"]["nodes"][0]
    node["verdict"] = node["verification"]["verdict"] = "FUTURE_VERDICT"
    task = _project(payload)["tasks"][0]
    assert task["workflow"]["recorded_verdict"]["value"] == "FUTURE_VERDICT"
    assert "UNRECOGNIZED_ENUM" in _codes(task)
    assert task["stage"] != "TASK_VERIFIED_AS_CAPTURED"


def test_ms08_statement_ids_order_and_actual_integration_facts():
    payload = _envelope(integrated=True)
    result = _project(payload)
    _assert_closed_schema(result)
    statements = result["conclusion"]["statements"]
    assert statements[0]["template_id"] == "Q01"
    assert statements[1]["template_id"] == CONCLUSION_TEMPLATE[result["conclusion"]["stage"]]
    assert any(s["template_id"] == INTEGRATION_TEMPLATE[result["integration"]["stage"]] for s in statements)
    assert statements[-2]["template_id"] == "K01" and statements[-1]["template_id"] == "L01"
    text = "\n".join(s["text"] for s in statements)
    assert "whole" in text and "integration-cont:1" in text and "201" in text
    assert "current=true" in text
    assert statements[-1]["text"] == TEMPLATES["L01"]


def test_fc26_s0_classification_has_no_permissions_generation_or_research_results():
    result = _project(_envelope(integrated=True))
    forbidden_keys = {"title", "generate", "compose", "resolve_unknown", "allow_local_workers",
                      "acceptance_approved", "execution_permission", "report_job", "research_result"}
    assert not any(forbidden_keys & x.keys() for x in _walk(result) if type(x) is dict)
    assert result["provenance"]["projection_is_acceptance"] is False


KEY_CAPS = {
    "snapshot": 128, "task": 64, "verification": 32, "evidence": 128,
    "integration": 8, "continuation": 64, "continuation_context": 64,
    "run": 64, "run_receipt": 128, "build_record": 16, "build_data": 128,
    "check": 16, "classification": 16, "review": 16, "patch_item": 2,
}


def _dictionary_boundary(kind):
    payload = _envelope(integrated=True)
    payload["snapshot"]["runs"] = [_run()]
    payload["snapshot"]["integration"]["builds"] = [
        {"key": "build:1", "created_at": "2026-01-01T00:00:00Z", "data": _artifact("whole", "integration:1")},
    ]
    snap = payload["snapshot"]
    data = _data(payload)
    selected = {
        "envelope": (payload, "snapshot", "INPUT_TYPE"),
        "snapshot": (snap, "objective", "SNAPSHOT_REQUIRED_FIELD"),
        "task": (snap["nodes"][0], "id", None),
        "verification": (snap["nodes"][0]["verification"], "verdict", None),
        "evidence": (data, "candidate_hash", None),
        "integration": (snap["integration"], "evidence", "SNAPSHOT_REQUIRED_FIELD"),
        "continuation": (snap["integration"]["continuation"], "id", None),
        "continuation_context": (snap["integration"]["continuation"]["context"], "lead_integration", None),
        "run": (snap["runs"][0], "key", None),
        "run_receipt": (snap["runs"][0]["receipt"], "status", None),
        "build_record": (snap["integration"]["builds"][0], "key", None),
        "build_data": (snap["integration"]["builds"][0]["data"], "status", None),
        "check": (data["checks"][0], "check", None),
        "classification": (data["checks"][0]["classification"], "status", None),
        "review": (data["review"], "verdict", None),
        "patch_item": (data["patch"]["added.txt"], "after", None),
        "patch_map": (data["patch"], "added.txt", None),
        "dependency_map": (snap["integration"]["evidence"]["payload"]["evidence"]["dependencies"], "build", None),
        "check_hash_map": (data["check_hashes"], "unit", None),
        "measurement": (data["checks"][0]["measurement"], "score", None),
    }
    return payload, *selected[kind]


class _HostileKey:
    def __init__(self, text):
        self.text = text
        self.armed = False
        self.calls = []

    def __hash__(self):
        if self.armed:
            self.calls.append("hash")
            raise AssertionError("custom key hash called before rejection")
        return hash(self.text)

    def __eq__(self, other):
        if self.armed:
            self.calls.append("eq")
            raise AssertionError("custom key equality called before rejection")
        return False

    def __repr__(self):
        raise AssertionError("custom key repr called")


class _HostileStringKey(str):
    def __new__(cls, text):
        result = super().__new__(cls, text)
        result.armed = False
        result.calls = []
        return result

    def __hash__(self):
        if self.armed:
            self.calls.append("hash")
            raise AssertionError("str subclass hash called before rejection")
        return str.__hash__(self)

    def __eq__(self, other):
        if self.armed:
            self.calls.append("eq")
            raise AssertionError("str subclass equality called before rejection")
        return str.__eq__(self, other)

    def __repr__(self):
        raise AssertionError("str subclass repr called")


@pytest.mark.parametrize("kind", [
    "envelope", "snapshot", "task", "verification", "evidence", "integration",
    "continuation", "continuation_context", "run", "run_receipt", "build_record",
    "build_data", "check", "classification", "review", "patch_item", "patch_map",
    "dependency_map", "check_hash_map", "measurement",
])
@pytest.mark.parametrize("key_type", [_HostileKey, _HostileStringKey])
def test_ms11_exact_keys_are_checked_before_hash_lookup_equality_or_sort(kind, key_type):
    payload, container, selected_key, rejection = _dictionary_boundary(kind)
    raw = container.pop(selected_key)
    hostile = key_type(selected_key)
    container[hostile] = raw
    hostile.armed = True
    if rejection:
        _reject(payload, rejection)
    else:
        result = _project(payload)
        assert "MALFORMED" in _codes(result)
        _assert_closed_schema(result)
    assert hostile.calls == []


@pytest.mark.parametrize("kind", list(KEY_CAPS))
def test_ms11_selected_dictionary_key_cardinality_is_bounded_before_values(kind):
    payload, container, _, _ = _dictionary_boundary(kind)
    cap = KEY_CAPS[kind]
    for i in range(cap + 1 - len(container)):
        container[f"unknown_{i}"] = _Unselected()
    assert len(container) == cap + 1
    _reject(payload, "LIMIT_EXCEEDED")


def test_ms11_unknown_snapshot_keys_are_checked_without_reading_unknown_values():
    payload = _envelope(verified=True)
    snapshot = payload["snapshot"]
    for i in range(128 - len(snapshot)):
        snapshot[f"unused_{i}"] = _Unselected()
    assert len(snapshot) == 128
    result = _project(payload)
    assert result["tasks"][0]["stage"] == "TASK_VERIFIED_AS_CAPTURED"


@pytest.mark.parametrize("path", [
    "src/sk-abcdefghijklmnop.py", "src/Bearer synthetic.fixture.secret",
    "keys/-----BEGIN PRIVATE KEY-----", "cfg/password=synthetic",
])
def test_ms12_credential_shaped_paths_never_escape_in_pointer_or_statement(path):
    payload = _envelope(verified=True)
    _data(payload)["patch"] = {path: {"before": None, "after": SHA_B}}
    result = _project(payload)
    row = result["tasks"][0]["deliverable"]["patch"]["rows"][0]
    assert row["path"] is None and row["row_ordinal"] == 0
    assert row["source"] == "/snapshot/nodes/0/verification/evidence/patch"
    assert row["change_kind"] == "ADDED" and row["after"] == SHA_B
    assert path not in _json(result)
    assert "WITHHELD_SENSITIVE_PATH" in _codes(result)


@pytest.mark.parametrize("position", ["mission_id", "task_id", "run_key", "check_id", "dependency_key", "check_hash_key"])
def test_ms12_opaque_identities_are_withheld_not_renamed(position):
    payload = _envelope(integrated=True)
    secret = "sk-abcdefghijklmnop"
    snap, data = payload["snapshot"], _data(payload)
    if position == "mission_id": payload["id"] = secret
    elif position == "task_id": snap["nodes"][0]["id"] = secret
    elif position == "run_key":
        data["run_key"] = secret
        data["review"]["run_key"] = "review:" + secret
        snap["runs"] = [_run(secret, status="UNKNOWN", native="UNKNOWN")]
        snap["unresolved"] = [secret]
    elif position == "check_id":
        data["checks"][0]["id"] = secret
        data["review"]["evidence"] = [secret]
    elif position == "dependency_key":
        snap["integration"]["evidence"]["payload"]["evidence"]["dependencies"] = {secret: 101}
    else:
        data["check_hashes"] = {secret: SHA_F}
    result = _project(payload)
    encoded = _json(result)
    assert secret not in encoded
    withheld = [x for x in _walk(result) if type(x) is dict and x.get("state") == "WITHHELD"]
    assert withheld and all(x["value"] is None for x in withheld)
    assert result["conclusion"]["stage"] != "PROJECT_VERIFIED_AS_CAPTURED"
    assert "WITHHELD_SENSITIVE_ID" in _codes(result)


def test_ms12_unused_credential_shaped_keys_do_not_create_source_paths():
    payload = _envelope(integrated=True)
    private_key = "sk-abcdefghijklmnop"
    payload["snapshot"][private_key] = _Unselected()
    _data(payload)[private_key] = _Unselected()
    result = _project(payload)
    assert private_key not in _json(result)
    assert result["conclusion"]["stage"] == "PROJECT_VERIFIED_AS_CAPTURED"


@pytest.mark.parametrize("target", ["task", "integration"])
@pytest.mark.parametrize("contradiction", ["ERROR", "UNKNOWN", "INTERRUPTED", "integrity_error", "scope_error"])
def test_ms13_pass_rows_with_known_native_failure_cannot_be_positive(target, contradiction):
    payload = _envelope(integrated=target == "integration", verified=True)
    if target == "task":
        data = _data(payload)
    else:
        data = payload["snapshot"]["integration"]["evidence"]["payload"]["evidence"]
    marker = "private-native-failure-marker"
    if contradiction in {"integrity_error", "scope_error"}:
        data[contradiction] = marker
    else:
        data["status"] = contradiction
    result = _project(payload)
    section = result["tasks"][0] if target == "task" else result["integration"]
    verdicts = section["workflow"] if target == "task" else section
    assert verdicts["recorded_verdict"]["value"] == "PASS"
    assert verdicts["payload_verdict"]["value"] == "PASS"
    assert section["stage"] == "EVIDENCE_CONFLICT"
    assert "VERDICT_MISMATCH" in _codes(section)
    canonical = section if target == "task" else section["result"]
    assert all(check["status"]["value"] == "PASS" for check in canonical["checks"])
    assert canonical["review"]["verdict"]["value"] == "PASS"
    assert canonical["review"]["reasons"][0]["value"] == "Reviewer inspected fixture receipts"
    assert marker not in _json(result)
    if target == "integration":
        assert result["control"]["project_verified"]["value"] is True
        assert result["control"]["all_verified"]["value"] is True
        assert result["conclusion"]["stage"] == "CAPTURE_CONFLICT"


@pytest.mark.parametrize("target", ["task", "integration"])
@pytest.mark.parametrize("optional_errors", ["absent", "empty", "null"])
def test_ms13_missing_or_empty_optional_errors_are_not_known_failure(target, optional_errors):
    payload = _envelope(integrated=target == "integration", verified=True)
    data = (_data(payload) if target == "task"
            else payload["snapshot"]["integration"]["evidence"]["payload"]["evidence"])
    if optional_errors != "absent":
        data.update(integrity_error="" if optional_errors == "empty" else None,
                    scope_error="" if optional_errors == "empty" else None)
    result = _project(payload)
    section = result["tasks"][0] if target == "task" else result["integration"]
    expected = "TASK_VERIFIED_AS_CAPTURED" if target == "task" else "INTEGRATION_VERIFIED_AS_CAPTURED"
    assert section["stage"] == expected
    assert "VERDICT_MISMATCH" not in _codes(section)
    assert "MALFORMED" not in _codes(section)


@pytest.mark.parametrize("depth", [4, 5])
def test_ms14_measurement_container_root_zero_depth4_allowed_depth5_rejected(depth):
    payload = _envelope(verified=True)
    measurement = {}
    cursor = measurement
    for i in range(depth):
        cursor[f"level_{i}"] = {}
        cursor = cursor[f"level_{i}"]
    cursor["value"] = 1
    _data(payload)["checks"][0]["measurement"] = measurement
    if depth == 5:
        _reject(payload, "DEPTH_EXCEEDED")
    else:
        measured = _project(payload)["tasks"][0]["checks"][0]["measurement"]
        assert [(s["name"], s["value"]) for s in measured["scalars"]] == [
            ("level_0.level_1.level_2.level_3.value", 1),
        ]
        assert measured["complete"] is True
        assert measured["withheld_count"] == measured["omitted_scalar_count"] == 0


def test_ms14_selected_ancestor_cycle_has_priority_over_measurement_depth5():
    payload = _envelope(verified=True)
    measurement = {}
    cursor = measurement
    for i in range(4):
        cursor[f"level_{i}"] = {}
        cursor = cursor[f"level_{i}"]
    cursor["cycle"] = cursor
    _data(payload)["checks"][0]["measurement"] = measurement
    _reject(payload, "INPUT_CYCLE")


@pytest.mark.parametrize("scalar_count", [4095, 4096])
def test_ms14_per_check_visits_include_root_but_not_dictionary_keys(scalar_count):
    payload = _envelope(verified=True)
    _data(payload)["checks"][0]["measurement"] = {f"score_{i:04d}": i for i in range(scalar_count)}
    if scalar_count == 4096:
        _reject(payload, "LIMIT_EXCEEDED")
    else:
        first = _project(payload)
        measured = first["tasks"][0]["checks"][0]["measurement"]
        assert len(measured["scalars"]) == 64
        assert [s["name"] for s in measured["scalars"]] == [f"score_{i:04d}" for i in range(64)]
        assert measured["omitted_scalar_count"] == 4031
        assert measured["withheld_count"] == 0 and measured["complete"] is False
        # Comparisons and statements reuse these source positions, not new visits.
        assert _json(first) == _json(_project(payload))


@pytest.mark.parametrize("denied_roots", [1, 2])
def test_ms14_denied_measurement_subtree_counts_root_once_without_descending(denied_roots):
    payload = _envelope(verified=True)
    measurement = {f"value_{i:04d}": i for i in range(4094)}
    for i in range(denied_roots):
        measurement[f"secret_block_{i}"] = {"nested": ["ignored measurement subtree"] * 5000}
    _data(payload)["checks"][0]["measurement"] = measurement
    if denied_roots == 2:
        # root + 4094 scalars + 2 denied roots = 4097, not counting keys/children.
        _reject(payload, "LIMIT_EXCEEDED")
    else:
        measured = _project(payload)["tasks"][0]["checks"][0]["measurement"]
        assert len(measured["scalars"]) == 64
        assert measured["withheld_count"] == 1 and measured["omitted_scalar_count"] == 4030
        assert measured["complete"] is False
        assert "ignored measurement subtree" not in _json(measured)


@pytest.mark.parametrize("positions", [32, 64])
def test_ms14_shared_objects_count_per_distinct_source_position_and_repeat_is_deterministic(positions):
    payload = _envelope()
    measurement = {f"value_{i:04d}": "withheld scalar text" for i in range(4095)}
    payload["snapshot"]["nodes"] = [
        _node(f"task{i}", verified=True, evidence_id=i + 1) for i in range(positions)
    ]
    for node in payload["snapshot"]["nodes"]:
        node["verification"]["evidence"]["checks"][0]["measurement"] = measurement
    if positions == 64:
        # 64 distinct measurement roots * 4096 values = 262144; other selected
        # source positions prove overflow, without guessing an overhead constant.
        _reject(payload, "VISIT_LIMIT")
        _reject(payload, "VISIT_LIMIT")
        _reject(_reverse_dicts(payload), "VISIT_LIMIT")
    else:
        first = _project(payload)
        assert len(first["tasks"]) == 32
        for task in first["tasks"]:
            measured = task["checks"][0]["measurement"]
            assert measured["scalars"] == [] and measured["withheld_count"] == 4095
            assert measured["omitted_scalar_count"] == 0 and measured["complete"] is False
        assert _json(first) == _json(_project(payload))
