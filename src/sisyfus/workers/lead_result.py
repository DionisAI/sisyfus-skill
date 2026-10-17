"""Bounded, pure projection of caller-captured engineering evidence.

This is neither a reader nor an acceptance gate. Source pointers refer to the
supplied capture, not to newly verified files or a transactionally pinned state.
"""
from __future__ import annotations

import json
import math
import re


class EngineeringResultInputError(ValueError):
    code: str

    def __init__(self, code: str):
        self.code = code
        super().__init__("engineering result input rejected: " + code)


def _reject(code):
    raise EngineeringResultInputError(code) from None


_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_MISSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_CAPTURE_KEY = re.compile(r"api.?key|authorization|password|secret|token$", re.I)
_MEASUREMENT_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
_MEASUREMENT_DENY = re.compile(
    r"api.?key|authorization|password|secret|token|credential|cookie|session|private|bearer|holdout", re.I
)
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY")
_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_PATH_CONTROLS = re.compile(r"[\x00-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_CREDENTIALS = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"), "[REDACTED]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.I), "Bearer [REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"), "[REDACTED]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "[REDACTED]"),
    (re.compile(r"\b(api[_-]?key|password|passwd|secret|token)(\s*[:=]\s*)\S+", re.I), r"\1\2[REDACTED]"),
)
_SENSITIVE_SEGMENT = re.compile(
    r"^\.env(\..*)?$|^\.ssh$|^\.aws$|^\.netrc$|^\.npmrc$|^\.pypirc$|^id_[a-z0-9]+$|\.(pem|key|p12)$", re.I
)
_ENCODED_PATH = re.compile(r"%2[ef]", re.I)
_VERDICTS = frozenset(("PASS", "FAIL", "ERROR", "INVALID", "INCONCLUSIVE", "UNVERIFIED"))
_WORKFLOW = frozenset(("ADMITTING", "READY", "RUNNING", "VERIFYING", "WAITING", "SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED", "EXHAUSTED"))
_NATIVE = frozenset(("COMPLETED", "FAILED", "ERROR", "INTERRUPTED", "CANCELLED", "UNKNOWN"))
_TRANSPORT = frozenset(("RESERVED", "IN_FLIGHT", "UNKNOWN", "RECEIPTED", "RESOLVED_UNKNOWN", "KNOWN_NONEXECUTED"))
_PHASES = frozenset(("IDLE", "NEW", "PLANNING", "IMPLEMENTING", "VERIFYING", "INTEGRATING", "COMPLETED", "STOPPED", "PAUSED", "UNKNOWN", "STALE", "TRIAL_FENCED", "TRIAL_RUNNING", "BUDGET_EXHAUSTED", "NEEDS_OPERATOR", "WAITING_PLACEMENT"))
_CONFLICTS = frozenset((
    "DUPLICATE_ID", "VERDICT_MISMATCH", "CANDIDATE_HASH_MISMATCH", "CHECK_HASH_MISMATCH",
    "CHECK_NAME_MISMATCH", "REVIEW_RUN_KEY_MISMATCH", "REVIEW_REFERENCE_MISMATCH",
    "DEPENDENCY_EVIDENCE_MISMATCH", "DEPENDENCY_GRAPH_INVALID", "MALFORMED_DELTA",
    "INTEGRATION_CONTINUATION_MISMATCH", "INTEGRATION_REVISION_MISMATCH",
))

# Only these source values are entered. Unknown dictionary keys are shape-checked
# under their caps; their values are never obtained, traversed, or copied.
_FIELDS = {
    "envelope": (("id", "scalar"), ("snapshot", "snapshot")),
    "snapshot": (("objective", "scalar"), ("phase", "scalar"), ("revision", "scalar"), ("resume_epoch", "scalar"),
                 ("nodes", "nodes"), ("integration", "integration"), ("runs", "runs"), ("unresolved", "unresolved"),
                 ("paused", "scalar"), ("stopped", "scalar"), ("project_verified", "scalar"), ("all_verified", "scalar"), ("reason", "scalar")),
    "task": (("id", "scalar"), ("objective", "scalar"), ("acceptance", "scalar"), ("check", "scalar"),
             ("write_paths", "paths"), ("depends_on", "ids"), ("state", "scalar"), ("verdict", "scalar"),
             ("attempts", "scalar"), ("evidence_id", "scalar"), ("active", "scalar"), ("stale", "scalar"),
             ("superseded_by", "scalar"), ("verification", "verification")),
    "verification": (("verdict", "scalar"), ("summary", "scalar"), ("evidence", "evidence")),
    "integration_verification": (("verdict", "scalar"), ("summary", "scalar"), ("evidence", "integration_evidence")),
    "evidence": (("candidate_hash", "scalar"), ("run_key", "scalar"), ("patch", "patch"), ("checks", "checks"),
                 ("review", "review"), ("acceptance_hash", "scalar"), ("task_hash", "scalar"),
                 ("check_hashes", "check_hashes"), ("dependencies", "dependencies"), ("status", "scalar"),
                 ("integrity_error", "scalar"), ("scope_error", "scalar")),
    "integration_evidence": (("candidate_hash", "scalar"), ("run_key", "scalar"), ("patch", "patch"), ("checks", "checks"),
                             ("review", "review"), ("acceptance_hash", "scalar"), ("check_hashes", "check_hashes"),
                             ("dependencies", "dependencies"), ("status", "scalar"), ("integrity_error", "scalar"), ("scope_error", "scalar")),
    "check": (("id", "scalar"), ("check", "scalar"), ("candidate_hash", "scalar"), ("check_hash", "scalar"),
              ("classification", "classification"), ("measurement", "measurement")),
    "classification": (("status", "scalar"), ("summary", "scalar")),
    "review": (("verdict", "scalar"), ("reasons", "reasons"), ("evidence", "refs"), ("candidate_hash", "scalar"), ("run_key", "scalar")),
    "patch_item": (("before", "scalar"), ("after", "scalar")),
    "integration": (("continuation", "continuation"), ("evidence", "evidence_row"), ("current", "scalar"), ("builds", "builds")),
    "continuation": (("id", "scalar"), ("state", "scalar"), ("context", "continuation_context")),
    "continuation_context": (("lead_integration", "scalar"),),
    "evidence_row": (("id", "scalar"), ("continuation_id", "scalar"), ("verdict", "scalar"), ("payload", "integration_verification")),
    "build_record": (("key", "scalar"), ("created_at", "scalar"), ("data", "build_data")),
    "build_data": (("status", "scalar"), ("run_key", "scalar"), ("candidate_hash", "scalar"), ("patch", "patch"), ("dependencies", "dependencies")),
    "run": (("key", "scalar"), ("task_id", "scalar"), ("status", "scalar"), ("evidence_id", "scalar"), ("verdict", "scalar"), ("receipt", "run_receipt")),
    "run_receipt": (("status", "scalar"), ("candidate_hash", "scalar"), ("patch", "patch")),
}
_KEY_CAPS = {
    "envelope": 4, "snapshot": 128, "task": 64, "verification": 32, "evidence": 128,
    "check": 16, "classification": 16, "review": 16, "patch_item": 2,
    "integration": 8, "continuation": 64, "continuation_context": 64, "evidence_row": 128,
    "build_record": 16, "build_data": 128, "run": 64, "run_receipt": 128,
    "integration_verification": 32, "integration_evidence": 128,
    "patch": 512, "dependencies": 64, "check_hashes": 64,
}
_LISTS = {
    "nodes": (256, "task"), "runs": (2048, "run"), "unresolved": (2048, "scalar"),
    "paths": (64, "scalar"), "ids": (64, "scalar"), "checks": (64, "check"),
    "reasons": (64, "scalar"), "refs": (64, "scalar"), "builds": (256, "build_record"),
}
_LIMITATIONS = (
    ("NO_FILE_CONTENT", "仅展示记录的文件hash增量，不包含文件正文。"),
    ("NON_ATOMIC_CAPTURE", "输入由调用方非原子捕获，不是同一事务的全局事实。"),
    ("NO_REVERIFICATION", "本投影未重新运行检查、审查或重新验证文件字节。"),
    ("SPEC_NOT_IN_SNAPSHOT", "输入不含完整冻结spec，所列指纹仅按记录展示。"),
    ("NOT_DLP", "确定性模式过滤是纵深防御，不是敏感内容清除证明。"),
    ("NO_LIVE_RUNTIME", "不展示实时进程、节点在线性或原生终止事实。"),
    ("NO_RESEARCH_RESULT", "本投影没有研究结果或研究发布状态。"),
    ("NO_DEVICE_OR_SECOND_HOST_ACCEPTANCE", "本投影没有手机、设备或第二主机验收。"),
    ("MEASUREMENT_SELECTION_PARTIAL_BY_POLICY", "仅展示有界有限数值或bool测量；不输出项与省略项分别计数。"),
)
_SOURCE_FIELDS = (
    "/id", "/snapshot/objective", "/snapshot/revision", "/snapshot/resume_epoch",
    "/snapshot/phase", "/snapshot/reason", "/snapshot/paused", "/snapshot/stopped",
    "/snapshot/project_verified", "/snapshot/all_verified", "/snapshot/unresolved/{k}",
    "/snapshot/nodes/{i}/id", "/snapshot/nodes/{i}/objective", "/snapshot/nodes/{i}/acceptance",
    "/snapshot/nodes/{i}/check", "/snapshot/nodes/{i}/depends_on", "/snapshot/nodes/{i}/write_paths",
    "/snapshot/nodes/{i}/state", "/snapshot/nodes/{i}/attempts", "/snapshot/nodes/{i}/active",
    "/snapshot/nodes/{i}/superseded_by", "/snapshot/nodes/{i}/stale", "/snapshot/nodes/{i}/verdict",
    "/snapshot/nodes/{i}/evidence_id", "/snapshot/nodes/{i}/verification/verdict",
    "/snapshot/nodes/{i}/verification/summary", "/snapshot/nodes/{i}/verification/evidence/{field}",
    "/snapshot/integration/continuation/{field}", "/snapshot/integration/continuation/context/lead_integration",
    "/snapshot/integration/evidence/{field}", "/snapshot/integration/evidence/payload/verdict",
    "/snapshot/integration/evidence/payload/evidence/{field}", "/snapshot/integration/current",
    "/snapshot/integration/builds/{b}/{field}", "/snapshot/integration/builds/{b}/data/{field}",
    "/snapshot/runs/{r}/{field}", "/snapshot/runs/{r}/receipt/{field}",
)


class _Invalid:
    """A selected dictionary whose keys failed the exact builtin boundary."""


class _Denied:
    """One selected measurement root, with no visit to its denied children."""


def _pointer(parent, key):
    return parent + "/" + key.replace("~", "~0").replace("/", "~1")


def _filter(text):
    if _PRIVATE_KEY.search(text):
        return None
    for pattern, replacement in _CREDENTIALS:
        text = pattern.sub(replacement, text)
    return _CONTROLS.sub("\ufffd", text)


def _sensitive(text):
    return _filter(text) != text


def _path_kind(text):
    if (not text or text.startswith("/") or "\\" in text or _PATH_CONTROLS.search(text)
            or _ENCODED_PATH.search(text)):
        return "UNSAFE_PATH"
    parts = text.split("/")
    if len(parts) > 64 or ":" in parts[0] or any(x in ("", ".", "..") for x in parts):
        return "UNSAFE_PATH"
    if _sensitive(text) or _sensitive(text + "0") or any(_SENSITIVE_SEGMENT.search(x) or "holdout" in x.lower() for x in parts):
        return "WITHHELD_SENSITIVE_PATH"
    return None


class _Selection:
    """Single visit per selected source position, before any projection work.

    Shared objects at distinct positions are deliberately revisited. Ancestor
    identity, not a global seen-object cache, distinguishes sharing from cycles.
    """

    def __init__(self):
        self.visits = 0

    def select(self, value, kind, depth=0, ancestors=(), measurement=None, denied=False):
        container = type(value) in (dict, list)
        if container and id(value) in ancestors:
            _reject("INPUT_CYCLE")
        if container and depth > 16:
            _reject("DEPTH_EXCEEDED")
        if measurement is not None and container and measurement[1] > 4:
            _reject("DEPTH_EXCEEDED")
        self.visits += 1
        if self.visits > 262144:
            _reject("VISIT_LIMIT")
        if measurement is not None:
            measurement[0][0] += 1
            if measurement[0][0] > 4096:
                _reject("LIMIT_EXCEEDED")
        if denied:
            return _Denied()
        if kind == "scalar" or value is None:
            return value
        if kind == "measurement":
            if measurement is None:
                # The root was already counted above, including its local visit.
                measurement = ([1], 0)
            if type(value) not in (dict, list):
                return value
            if len(value) > 4096:
                _reject("LIMIT_EXCEEDED")
            lineage = ancestors + (id(value),)
            child_measurement = (measurement[0], measurement[1] + 1)
            if type(value) is list:
                return [self.select(x, kind, depth + 1, lineage, child_measurement) for x in value]
            if any(type(k) is not str for k in value):
                return _Invalid()
            selected = {}
            for key in sorted(value):
                deny = len(key) > 64 or not _MEASUREMENT_KEY.fullmatch(key) or bool(_MEASUREMENT_DENY.search(key)) or _sensitive(key) or _sensitive(key + "=0")
                selected[key] = self.select(value[key], kind, depth + 1, lineage, child_measurement, deny)
            return selected
        if kind in _LISTS:
            if type(value) is not list:
                return value
            cap, child_kind = _LISTS[kind]
            if len(value) > cap:
                _reject("LIMIT_EXCEEDED")
            lineage = ancestors + (id(value),)
            return [self.select(x, child_kind, depth + 1, lineage) for x in value]
        if type(value) is not dict:
            return value
        if len(value) > _KEY_CAPS[kind]:
            _reject("LIMIT_EXCEEDED")
        if any(type(k) is not str for k in value):
            if kind in ("snapshot", "integration"):
                _reject("SNAPSHOT_REQUIRED_FIELD")
            return _Invalid()
        if kind == "snapshot":
            self.required_snapshot(value)
        lineage = ancestors + (id(value),)
        if kind in ("patch", "dependencies", "check_hashes"):
            child_kind = "patch_item" if kind == "patch" else "scalar"
            return {k: self.select(value[k], child_kind, depth + 1, lineage) for k in sorted(value)}
        return {k: self.select(value[k], child_kind, depth + 1, lineage)
                for k, child_kind in _FIELDS[kind] if k in value}

    @staticmethod
    def required_snapshot(value):
        for key, typ in (("objective", str), ("phase", str), ("revision", int), ("resume_epoch", int),
                         ("nodes", list), ("runs", list), ("integration", dict), ("unresolved", list)):
            if key not in value or type(value[key]) is not typ:
                _reject("SNAPSHOT_REQUIRED_FIELD")
        for key in ("revision", "resume_epoch"):
            if not 0 <= value[key] <= 2**63 - 1:
                _reject("SNAPSHOT_REQUIRED_FIELD")
        if not _TOKEN.fullmatch(value["phase"]):
            _reject("SNAPSHOT_REQUIRED_FIELD")
        objective = value["objective"]
        if len(objective) > 20000:
            _reject("LIMIT_EXCEEDED")
        try:
            size = len(objective.encode("utf-8"))
        except UnicodeEncodeError:
            _reject("TEXT_ENCODING")
        if size > 80000:
            _reject("LIMIT_EXCEEDED")


def _fact(state, value, source, ordinal=None):
    result = {"state": state, "value": value, "source": source}
    if ordinal is not None:
        result["row_ordinal"] = ordinal
    return result


def _recorded(fact):
    return fact["state"] == "RECORDED"


def _value(fact):
    return fact["value"] if _recorded(fact) else None


def _same(left, right):
    return type(left) is type(right) and left == right


class _Projection:
    def __init__(self):
        self.diagnostic_count = 0

    def diag(self, target, code, section, source):
        diagnostic = {"code": code, "section": section, "source": source}
        if diagnostic not in target:
            self.diagnostic_count += 1
            if self.diagnostic_count > 8192:
                _reject("LIMIT_EXCEEDED")
            target.append(diagnostic)

    def dictionary(self, value, ds, section, source):
        if value is None:
            return {}
        if type(value) is dict:
            return value
        self.diag(ds, "MALFORMED", section, source)
        return {}

    def sequence(self, value, ds, section, source):
        if value is None:
            return []
        if type(value) is list:
            return value
        self.diag(ds, "MALFORMED", section, source)
        return []

    def fact(self, raw, kind, source, ds, section, ordinal=None, known=None):
        if raw is None:
            return _fact("NOT_RECORDED", None, source, ordinal)
        if type(raw) is str and raw == "[REDACTED]":
            return _fact("REDACTED_AT_CAPTURE", None, source, ordinal)
        valid = False
        if kind == "bool":
            valid = type(raw) is bool
        elif kind == "int":
            valid = type(raw) is int and 0 <= raw <= 2**63 - 1
        elif kind == "identity" and type(raw) is int:
            valid = 0 <= raw <= 2**63 - 1
        elif kind in ("str", "identity", "hash", "token", "path") and type(raw) is str:
            cap = 1024 if kind == "path" else (64 if kind == "hash" else (32 if kind == "token" else 256))
            if len(raw) <= cap:
                try:
                    valid = 0 < len(raw.encode("utf-8")) <= cap
                except UnicodeEncodeError:
                    valid = False
            if valid and kind == "hash":
                valid = bool(_SHA.fullmatch(raw))
            if valid and kind == "token":
                valid = bool(_TOKEN.fullmatch(raw))
            if valid and _sensitive(raw):
                self.diag(ds, "WITHHELD_SENSITIVE_PATH" if kind == "path" else "WITHHELD_SENSITIVE_ID", section, source)
                return _fact("WITHHELD", None, source, ordinal)
            if valid and kind == "path":
                error = _path_kind(raw)
                if error:
                    self.diag(ds, error, section, source)
                    return _fact("WITHHELD", None, source, ordinal)
        if not valid:
            self.diag(ds, "HASH_INVALID" if kind == "hash" else "MALFORMED", section, source)
            return _fact("MALFORMED", None, source, ordinal)
        if known is not None and raw not in known:
            self.diag(ds, "UNRECOGNIZED_ENUM", section, source)
        return _fact("RECORDED", raw, source, ordinal)

    def text(self, raw, source, ds, section, objective=False):
        if raw is None:
            return _fact("NOT_RECORDED", None, source)
        if type(raw) is not str:
            self.diag(ds, "MALFORMED", section, source)
            return _fact("MALFORMED", None, source)
        try:
            size = len(raw.encode("utf-8"))
        except UnicodeEncodeError:
            self.diag(ds, "MALFORMED", section, source)
            return _fact("MALFORMED", None, source)
        if (objective and len(raw) > 20000) or size > (80000 if objective else 16384):
            self.diag(ds, "TEXT_LIMIT", section, source)
            result = _fact("WITHHELD", None, source)
            result["utf8_bytes"] = size
            return result
        filtered = _filter(raw)
        if filtered is None or raw == "[REDACTED]":
            return _fact("REDACTED_AT_CAPTURE", None, source)
        return _fact("RECORDED" if filtered == raw else "FILTERED", filtered, source)

    def strings(self, raw, source, ds, section, paths=False):
        if raw is None:
            return _fact("NOT_RECORDED", None, source)
        if type(raw) is not list:
            self.diag(ds, "MALFORMED", section, source)
            return _fact("MALFORMED", None, source)
        facts = [self.fact(x, "path" if paths else "str", source + "/" + str(i), ds, section) for i, x in enumerate(raw)]
        if all(_recorded(x) for x in facts):
            return _fact("RECORDED", [x["value"] for x in facts], source)
        state = "MALFORMED" if any(x["state"] == "MALFORMED" for x in facts) else "WITHHELD"
        return _fact(state, None, source)

    def presence(self, raw, source, ds, section):
        if raw is None:
            return None
        if type(raw) is str:
            return len(raw) > 0
        self.diag(ds, "MALFORMED", section, source)
        return None

    def failure(self, data, p, ds, section):
        return {
            "native_status": self.fact(data.get("status"), "token", p + "/status", ds, section, known=_NATIVE),
            "scope_error_recorded": self.presence(data.get("scope_error"), p + "/scope_error", ds, section),
            "integrity_error_recorded": self.presence(data.get("integrity_error"), p + "/integrity_error", ds, section),
        }

    def patch(self, raw, p, ds, section):
        data = self.dictionary(raw, ds, section, p)
        rows = []
        withheld = 0
        for ordinal, key in enumerate(sorted(data)):
            value = data[key]
            key_valid = len(key) <= 1024
            if key_valid:
                try:
                    key_valid = len(key.encode("utf-8")) <= 1024
                except UnicodeEncodeError:
                    key_valid = False
            error = _path_kind(key) if key_valid else "UNSAFE_PATH"
            pointer = _pointer(p, key) if error is None else p
            row = {"path": key if error is None else None, "change_kind": "MALFORMED", "before": None, "after": None, "source": pointer}
            if error:
                row["row_ordinal"] = ordinal
                withheld += 1
                self.diag(ds, error, section, p)
            if type(value) is str and value == "[REDACTED]" and _CAPTURE_KEY.search(key):
                row["change_kind"] = "REDACTED_AT_CAPTURE"
            elif type(value) is not dict or set(value) != {"before", "after"}:
                self.diag(ds, "MALFORMED", section, pointer)
            else:
                before = self.fact(value["before"], "hash", pointer + "/before", ds, section)
                after = self.fact(value["after"], "hash", pointer + "/after", ds, section)
                row["before"], row["after"] = _value(before), _value(after)
                valid = all(x["state"] in ("RECORDED", "NOT_RECORDED") for x in (before, after))
                if valid and row["before"] != row["after"]:
                    row["change_kind"] = "ADDED" if row["before"] is None else "REMOVED" if row["after"] is None else "MODIFIED"
                elif valid:
                    self.diag(ds, "MALFORMED_DELTA", section, pointer)
            if error == "UNSAFE_PATH":
                row["change_kind"] = "WITHHELD"
            rows.append(row)
        return {"row_count": len(data), "withheld_count": withheld, "rows": rows}

    def keyed_facts(self, raw, p, ds, section, hashes=False, checks=()):
        data = self.dictionary(raw, ds, section, p)
        rows = []
        for ordinal, key in enumerate(sorted(data)):
            # Key validation precedes pointer construction. Withheld map entries
            # use their parent and ordinal, never a renamed source identity.
            name = self.fact(key, "str", p, ds, section, ordinal)
            if _recorded(name):
                pointer = _pointer(p, key)
                # A pointer to a map entry addresses its VALUE, not its key.
                # Record the label only through a genuine associated identity
                # value at an already selected source position.
                name = _fact("NOT_RECORDED", None, pointer)
                value = self.fact(data[key], "hash" if hashes else "identity", pointer, ds, section)
                if hashes and _recorded(value):
                    associated = [c["check"] for c in checks
                                  if _recorded(c["check"]) and _value(c["check"]) == key
                                  and _recorded(c["check_hash"]) and _same(_value(c["check_hash"]), _value(value))]
                    if len(associated) == 1:
                        canonical = associated[0]
                        name = _fact("RECORDED", canonical["value"], canonical["source"])
            else:
                value = _fact(name["state"], None, p, ordinal)
            if type(data[key]) is str and data[key] == "[REDACTED]" and _CAPTURE_KEY.search(key):
                value = _fact("REDACTED_AT_CAPTURE", None, name["source"], name.get("row_ordinal"))
            if hashes:
                rows.append({"check": name, "check_hash": value})
            else:
                rows.append({"task_id": name, "evidence_id": value, "matches_captured_upstream": None})
        return rows

    def measurement(self, raw, p, ds):
        scalars = []
        withheld = 0
        execution_error = None
        if type(raw) is dict and type(raw.get("execution")) is dict:
            ex = raw["execution"]
            execution_error = self.presence(ex.get("error"), p + "/execution/error", ds, "measurement")

        def visit(value, name, pointer):
            nonlocal_count = 0
            if type(value) is _Denied:
                return 1
            if type(value) is dict:
                for key in sorted(value):
                    child = value[key]
                    # Denied keys, including credential-shaped ones, have no
                    # output name or pointer. Their root was counted upstream.
                    if type(child) is _Denied:
                        nonlocal_count += 1
                    else:
                        nonlocal_count += visit(child, name + "." + key if name else key, _pointer(pointer, key))
                return nonlocal_count
            if type(value) is list:
                for i, child in enumerate(value):
                    nonlocal_count += visit(child, name + "." + str(i) if name else str(i), pointer + "/" + str(i))
                return nonlocal_count
            if type(value) is bool:
                scalars.append({"name": name, "value": value, "source": pointer})
                return 0
            if type(value) is int:
                if -(2**63) <= value <= 2**63 - 1:
                    scalars.append({"name": name, "value": value, "source": pointer})
                    return 0
                self.diag(ds, "MALFORMED", "measurement", pointer)
            elif type(value) is float:
                if math.isfinite(value):
                    scalars.append({"name": name, "value": value, "source": pointer})
                    return 0
                self.diag(ds, "NUMERIC_NONFINITE", "measurement", pointer)
            elif type(value) not in (str, type(None)):
                self.diag(ds, "MALFORMED", "measurement", pointer)
            return 1

        if raw is not None:
            withheld = visit(raw, "", p)
        scalars.sort(key=lambda x: (x["name"], x["source"]))
        omitted = max(0, len(scalars) - 64)
        return {"scalars": scalars[:64], "execution_error_recorded": execution_error,
                "withheld_count": withheld, "omitted_scalar_count": omitted, "complete": not (withheld or omitted)}

    def check(self, raw, p, ds):
        data = self.dictionary(raw, ds, "check", p)
        classification = self.dictionary(data.get("classification"), ds, "check", p + "/classification")
        return {
            "id": self.fact(data.get("id"), "str", p + "/id", ds, "check"),
            "check": self.fact(data.get("check"), "str", p + "/check", ds, "check"),
            "candidate_hash": self.fact(data.get("candidate_hash"), "hash", p + "/candidate_hash", ds, "check"),
            "check_hash": self.fact(data.get("check_hash"), "hash", p + "/check_hash", ds, "check"),
            "status": self.fact(classification.get("status"), "token", p + "/classification/status", ds, "check", known=_VERDICTS),
            "summary": self.text(classification.get("summary"), p + "/classification/summary", ds, "check"),
            "measurement": self.measurement(data.get("measurement"), p + "/measurement", ds),
        }

    def review(self, raw, p, checks, ds):
        data = self.dictionary(raw, ds, "review", p)
        reasons = self.sequence(data.get("reasons"), ds, "review", p + "/reasons")
        references = self.sequence(data.get("evidence"), ds, "review", p + "/evidence")
        result = {
            "recorded": type(raw) is dict,
            "verdict": self.fact(data.get("verdict"), "token", p + "/verdict", ds, "review", known=_VERDICTS),
            "reasons": [self.text(x, p + "/reasons/" + str(i), ds, "review") for i, x in enumerate(reasons)],
            "candidate_hash": self.fact(data.get("candidate_hash"), "hash", p + "/candidate_hash", ds, "review"),
            "evidence_refs": [self.fact(x, "str", p + "/evidence/" + str(i), ds, "review") for i, x in enumerate(references)],
            "run_key": self.fact(data.get("run_key"), "str", p + "/run_key", ds, "review"),
            "references_cover_recorded_checks": None,
        }
        if type(data.get("evidence")) is list and all(_recorded(x) for x in result["evidence_refs"]) and all(_recorded(x["id"]) for x in checks):
            refs = [x["value"] for x in result["evidence_refs"]]
            ids = [x["id"]["value"] for x in checks]
            covered = len(refs) == len(set(refs)) and set(refs) == set(ids)
            result["references_cover_recorded_checks"] = covered
            if len(refs) != len(set(refs)) or not set(refs) <= set(ids) or (_value(result["verdict"]) == "PASS" and not covered):
                self.diag(ds, "REVIEW_REFERENCE_MISMATCH", "review", p + "/evidence")
        return result

    def artifact(self, raw, p, ds, section, task=False):
        data = self.dictionary(raw, ds, section, p)
        checks_raw = self.sequence(data.get("checks"), ds, section, p + "/checks")
        checks = [self.check(x, p + "/checks/" + str(i), ds) for i, x in enumerate(checks_raw)]
        result = {
            "deliverable": {
                "candidate_location": "WITHHELD_ABSOLUTE_LOCATOR",
                "candidate_hash": self.fact(data.get("candidate_hash"), "hash", p + "/candidate_hash", ds, section),
                "run_key": self.fact(data.get("run_key"), "str", p + "/run_key", ds, section),
                "patch": self.patch(data.get("patch"), p + "/patch", ds, section),
            },
            "checks": checks,
            "review": self.review(data.get("review"), p + "/review", checks, ds),
            "acceptance_hash": self.fact(data.get("acceptance_hash"), "hash", p + "/acceptance_hash", ds, section),
            "check_hashes": self.keyed_facts(data.get("check_hashes"), p + "/check_hashes", ds, section, hashes=True, checks=checks),
            "dependencies": self.keyed_facts(data.get("dependencies"), p + "/dependencies", ds, section),
            "failure_indicators": self.failure(data, p, ds, section),
        }
        if task:
            result["task_hash"] = self.fact(data.get("task_hash"), "hash", p + "/task_hash", ds, section)
        self.artifact_consistency(result, data, p, ds, section)
        return result, data

    def artifact_consistency(self, result, raw, p, ds, section):
        deliverable, checks, review = result["deliverable"], result["checks"], result["review"]
        candidate = _value(deliverable["candidate_hash"])
        for field in ("id", "check"):
            names = [_value(c[field]) for c in checks if _recorded(c[field])]
            if len(names) != len(set(names)):
                self.diag(ds, "DUPLICATE_ID", "check", p + "/checks")
        for check in checks:
            if candidate is not None and _recorded(check["candidate_hash"]) and _value(check["candidate_hash"]) != candidate:
                self.diag(ds, "CANDIDATE_HASH_MISMATCH", "check", check["candidate_hash"]["source"])
        if candidate is not None and _recorded(review["candidate_hash"]) and _value(review["candidate_hash"]) != candidate:
            self.diag(ds, "CANDIDATE_HASH_MISMATCH", "review", review["candidate_hash"]["source"])
        key = _value(deliverable["run_key"])
        if key is not None and _recorded(review["run_key"]) and _value(review["run_key"]) != "review:" + key:
            self.diag(ds, "REVIEW_RUN_KEY_MISMATCH", "review", review["run_key"]["source"])
        hashes = result["check_hashes"]
        if (type(raw.get("check_hashes")) is dict and all(x["check"]["state"] in ("RECORDED", "NOT_RECORDED") and _recorded(x["check_hash"]) for x in hashes)
                and all(_recorded(x["check"]) and _recorded(x["check_hash"]) for x in checks)):
            # Safe raw keys were validated in keyed_facts. A missing label
            # association must not hide an actual key/hash consistency conflict.
            recorded_hashes = {key: row["check_hash"]["value"]
                               for key, row in zip(sorted(raw["check_hashes"]), hashes)}
            expected_hashes = {x["check"]["value"]: x["check_hash"]["value"] for x in checks}
            if recorded_hashes != expected_hashes:
                self.diag(ds, "CHECK_HASH_MISMATCH", section, p + "/check_hashes")

    @staticmethod
    def artifact_ready(result, raw, task=False):
        checks, review, artifact = result["checks"], result["review"], result["deliverable"]
        native = result["failure_indicators"]["native_status"]
        prerequisites = [artifact["candidate_hash"], artifact["run_key"], result["acceptance_hash"]]
        if task:
            prerequisites.append(result["task_hash"])
        prerequisites.extend(x for c in checks for x in (c["id"], c["check"], c["candidate_hash"], c["check_hash"], c["status"], c["summary"]))
        prerequisites.extend((review["verdict"], review["run_key"], review["candidate_hash"]))
        prerequisites.extend(review["reasons"] + review["evidence_refs"])
        prerequisites.extend(x for row in result["check_hashes"] for x in (row["check"], row["check_hash"]))
        prerequisites.extend(x for row in result["dependencies"] for x in (row["task_id"], row["evidence_id"]))
        return (
            bool(checks) and all(_recorded(x) for x in prerequisites)
            and all(_value(c["status"]) == "PASS" for c in checks)
            and review["recorded"] and _value(review["verdict"]) == "PASS"
            and type(raw.get("review")) is dict and type(raw["review"].get("reasons")) is list
            and type(raw["review"].get("evidence")) is list and review["references_cover_recorded_checks"] is True
            and type(raw.get("patch")) is dict and type(raw.get("check_hashes")) is dict
            and type(raw.get("dependencies")) is dict
            and (native["state"] == "NOT_RECORDED" or (_recorded(native) and _value(native) == "COMPLETED"))
            and all(r["path"] is not None and r["change_kind"] in ("ADDED", "REMOVED", "MODIFIED") for r in artifact["patch"]["rows"])
            and all(r["matches_captured_upstream"] is True for r in result["dependencies"])
        )

    def task(self, raw, p):
        ds = []
        data = self.dictionary(raw, ds, "task", p)
        verification = self.dictionary(data.get("verification"), ds, "task", p + "/verification")
        workflow = {
            "state": self.fact(data.get("state"), "token", p + "/state", ds, "task", known=_WORKFLOW),
            "recorded_verdict": self.fact(data.get("verdict"), "token", p + "/verdict", ds, "task", known=_VERDICTS),
            "payload_verdict": self.fact(verification.get("verdict"), "token", p + "/verification/verdict", ds, "task", known=_VERDICTS),
            "attempts": self.fact(data.get("attempts"), "int", p + "/attempts", ds, "task"),
            "evidence_id": self.fact(data.get("evidence_id"), "identity", p + "/evidence_id", ds, "task"),
            "verification_summary": self.text(verification.get("summary"), p + "/verification/summary", ds, "task"),
        }
        result, evidence = self.artifact(verification.get("evidence"), p + "/verification/evidence", ds, "task", task=True)
        projected = {
            "task_id": self.fact(data.get("id"), "str", p + "/id", ds, "task"),
            "objective": self.text(data.get("objective"), p + "/objective", ds, "task", objective=True),
            "acceptance": self.text(data.get("acceptance"), p + "/acceptance", ds, "task", objective=True),
            "check": self.fact(data.get("check"), "str", p + "/check", ds, "task"),
            "write_paths": self.strings(data.get("write_paths"), p + "/write_paths", ds, "task", paths=True),
            "depends_on": self.strings(data.get("depends_on"), p + "/depends_on", ds, "task"),
            "workflow": workflow,
            "currentness": {
                "active": self.fact(data.get("active"), "bool", p + "/active", ds, "task"),
                "stale": self.fact(data.get("stale"), "bool", p + "/stale", ds, "task"),
                "superseded_by": self.fact(data.get("superseded_by"), "str", p + "/superseded_by", ds, "task"),
                "label": "NOT_APPLICABLE",
            },
            "deliverable": result["deliverable"] if data.get("verification") is not None else None,
            "checks": result["checks"], "review": result["review"],
            "acceptance_fingerprints": {k: result[k] for k in ("acceptance_hash", "task_hash", "check_hashes", "dependencies")},
            "failure_indicators": result["failure_indicators"], "uncertain_run_keys": [],
            "stage": "PENDING", "diagnostics": ds,
        }
        self.verdict_consistency(workflow["recorded_verdict"], workflow["payload_verdict"], result["failure_indicators"], ds, "task", p + "/verification")
        if data.get("verification") is not None and _value(workflow["recorded_verdict"]) == "UNVERIFIED":
            self.diag(ds, "VERDICT_MISMATCH", "task", p + "/verdict")
        if result["checks"] and _recorded(projected["check"]) and all(_recorded(c["check"]) for c in result["checks"]):
            if len(result["checks"]) != 1 or _value(result["checks"][0]["check"]) != _value(projected["check"]):
                self.diag(ds, "CHECK_NAME_MISMATCH", "task", p + "/check")
        return projected, {"source": p, "raw": data, "artifact": result, "evidence": evidence}

    def verdict_consistency(self, recorded, payload, failure, ds, section, p):
        if _recorded(recorded) and _recorded(payload) and _value(recorded) != _value(payload):
            self.diag(ds, "VERDICT_MISMATCH", section, p)
        if _value(recorded) == _value(payload) == "PASS":
            native = failure["native_status"]
            if ((_recorded(native) and _value(native) != "COMPLETED") or failure["scope_error_recorded"] is True or failure["integrity_error_recorded"] is True):
                self.diag(ds, "VERDICT_MISMATCH", section, p)

    @staticmethod
    def bind_dependency_names(rows, raw, tasks, lookup, declared=None):
        if type(raw) is not dict:
            return
        declared_sources = {}
        if declared is not None and _recorded(declared):
            for i, value in enumerate(declared["value"]):
                declared_sources.setdefault(value, declared["source"] + "/" + str(i))
        for key, row in zip(sorted(raw), rows):
            if row["task_id"]["state"] != "NOT_RECORDED":
                continue
            if key in declared_sources:
                row["task_id"] = _fact("RECORDED", key, declared_sources[key])
            elif key in lookup:
                canonical = tasks[lookup[key]]["task_id"]
                if _recorded(canonical) and _same(canonical["value"], key):
                    row["task_id"] = _fact("RECORDED", canonical["value"], canonical["source"])

    def dependencies(self, rows, raw, expected, tasks, lookup, ds, section, p, declared=None):
        self.bind_dependency_names(rows, raw, tasks, lookup, declared)
        names_complete = all(r["task_id"]["state"] in ("RECORDED", "NOT_RECORDED") and _recorded(r["evidence_id"]) for r in rows)
        if type(raw) is dict and expected is not None and names_complete:
            if set(raw) != set(expected):
                self.diag(ds, "DEPENDENCY_EVIDENCE_MISMATCH", section, p)
        for name, row in zip(sorted(raw) if type(raw) is dict else (), rows):
            evidence = _value(row["evidence_id"])
            if row["task_id"]["state"] not in ("RECORDED", "NOT_RECORDED") or evidence is None:
                continue
            index = lookup.get(name)
            matches = index is not None and _same(evidence, _value(tasks[index]["workflow"]["evidence_id"])) and tasks[index]["stage"] == "TASK_VERIFIED_AS_CAPTURED"
            row["matches_captured_upstream"] = matches
            if not matches:
                self.diag(ds, "DEPENDENCY_EVIDENCE_MISMATCH", section, row["evidence_id"]["source"])

    def task_stage(self, task, meta, attempts):
        ds, current, workflow = task["diagnostics"], task["currentness"], task["workflow"]
        if any(d["code"] in _CONFLICTS for d in ds):
            task["stage"] = "EVIDENCE_CONFLICT"
            current["label"] = "UNDETERMINED"
            return
        has_verification = meta["raw"].get("verification") is not None
        superseded = _value(current["superseded_by"])
        if superseded is not None or _value(current["active"]) is False:
            current["label"] = "SUPERSEDED" if superseded is not None else "INACTIVE"
            task["stage"] = "HISTORICAL_RESULT" if has_verification else "PENDING"
        elif _value(current["stale"]) is True:
            current["label"], task["stage"] = "STALE", "HISTORICAL_RESULT"
        elif not has_verification:
            associated = [a for a in attempts if a["association"] == "TASK_ATTEMPT" and a["associated_task_id"] == _value(task["task_id"])]
            if _value(workflow["state"]) in ("RUNNING", "VERIFYING") or any(_value(a["status"]) == "IN_FLIGHT" for a in associated):
                task["stage"] = "IN_PROGRESS"
            elif any(a["unverified_candidate"] is not None and _recorded(a["receipt_status"]) and _value(a["receipt_status"]) != "UNKNOWN" for a in associated):
                task["stage"] = "CANDIDATE_RECORDED"
        elif _value(workflow["recorded_verdict"]) == _value(workflow["payload_verdict"]) == "PASS":
            if _value(workflow["state"]) != "SUCCEEDED":
                task["stage"], current["label"] = "HISTORICAL_RESULT", "STATE_NOT_SUCCEEDED"
            else:
                required = [task[k] for k in ("task_id", "objective", "acceptance", "check", "depends_on", "write_paths")]
                required += [workflow[k] for k in ("state", "attempts", "evidence_id", "verification_summary")]
                ready = (all(_recorded(f) for f in required) and _value(current["active"]) is True and _value(current["stale"]) is False
                         and meta["raw"].get("superseded_by") is None and not ds
                         and self.artifact_ready(meta["artifact"], meta["evidence"], task=True))
                task["stage"] = "TASK_VERIFIED_AS_CAPTURED" if ready else "HISTORICAL_RESULT"
                current["label"] = "CURRENT_AS_CAPTURED" if ready else "UNDETERMINED"
        else:
            task["stage"] = "NOT_ACCEPTED"

    def attempts(self, raw, tasks, metas, integration, ds):
        projected = []
        for i, item in enumerate(raw):
            p = "/snapshot/runs/" + str(i)
            data = self.dictionary(item, ds, "attempt", p)
            receipt = self.dictionary(data.get("receipt"), ds, "attempt", p + "/receipt")
            candidate = self.fact(receipt.get("candidate_hash"), "hash", p + "/receipt/candidate_hash", ds, "attempt")
            patch = self.patch(receipt.get("patch"), p + "/receipt/patch", ds, "attempt")
            projected.append({
                "run_key": self.fact(data.get("key"), "str", p + "/key", ds, "attempt"),
                "task_id": self.fact(data.get("task_id"), "str", p + "/task_id", ds, "attempt"),
                "status": self.fact(data.get("status"), "token", p + "/status", ds, "attempt", known=_TRANSPORT),
                "receipt_status": self.fact(receipt.get("status"), "token", p + "/receipt/status", ds, "attempt", known=_NATIVE),
                "evidence_id": self.fact(data.get("evidence_id"), "identity", p + "/evidence_id", ds, "attempt"),
                "association": "MISSION_LEVEL", "associated_task_id": None, "unresolved": False,
                "unverified_candidate": {"candidate_hash": candidate, "patch": patch} if _recorded(candidate) else None,
                "source": p,
            })
        keys = [_value(a["run_key"]) for a in projected]
        for i, attempt in enumerate(projected):
            key, ident = keys[i], _value(attempt["task_id"])
            if key is None:
                continue
            if keys.count(key) != 1:
                self.diag(ds, "DUPLICATE_ID", "attempt", attempt["run_key"]["source"])
                continue
            matches = [j for j, task in enumerate(tasks) if _value(task["task_id"]) is not None and _value(task["task_id"]) == ident]
            if ident != "planner" and len(matches) == 1:
                attempt["association"], attempt["associated_task_id"] = "TASK_ATTEMPT", ident
            else:
                matches = [j for j, task in enumerate(tasks) if _value(task["review"]["run_key"]) == key and _recorded(task["task_id"])]
                if len(matches) == 1:
                    attempt["association"] = "TASK_REVIEW"
                    attempt["associated_task_id"] = _value(tasks[matches[0]]["task_id"])
                elif integration["result"] is not None and _value(integration["result"]["review"]["run_key"]) == key:
                    attempt["association"] = "INTEGRATION_REVIEW"
            data = raw[i] if type(raw[i]) is dict else {}
            if data.get("verdict") is not None:
                verdict = self.fact(data["verdict"], "token", attempt["source"] + "/verdict", ds, "attempt", known=_VERDICTS)
                for j, task in enumerate(tasks):
                    if (_recorded(attempt["evidence_id"]) and _recorded(task["workflow"]["evidence_id"])
                            and _same(_value(attempt["evidence_id"]), _value(task["workflow"]["evidence_id"]))
                            and _recorded(verdict) and _recorded(task["workflow"]["recorded_verdict"])
                            and _value(verdict) != _value(task["workflow"]["recorded_verdict"])):
                        self.diag(task["diagnostics"], "VERDICT_MISMATCH", "task", metas[j]["source"] + "/verdict")
        return projected

    def integration(self, raw):
        p, ds = "/snapshot/integration", []
        continuation = self.dictionary(raw.get("continuation"), ds, "integration", p + "/continuation")
        context = self.dictionary(continuation.get("context"), ds, "integration", p + "/continuation/context")
        evidence = self.dictionary(raw.get("evidence"), ds, "integration", p + "/evidence")
        payload = self.dictionary(evidence.get("payload"), ds, "integration", p + "/evidence/payload")
        artifact, data = self.artifact(payload.get("evidence"), p + "/evidence/payload/evidence", ds, "integration")
        current = self.fact(raw.get("current"), "bool", p + "/current", ds, "integration")
        if current["state"] == "MALFORMED":
            self.diag(ds, "CURRENT_FLAG_SHAPE", "integration", p + "/current")
        result = {
            "stage": "PENDING",
            "continuation_id": self.fact(continuation.get("id"), "identity", p + "/continuation/id", ds, "integration"),
            "continuation_state": self.fact(continuation.get("state"), "token", p + "/continuation/state", ds, "integration", known=_WORKFLOW),
            "lead_integration_revision": self.fact(context.get("lead_integration"), "int", p + "/continuation/context/lead_integration", ds, "integration"),
            "evidence_id": self.fact(evidence.get("id"), "identity", p + "/evidence/id", ds, "integration"),
            "evidence_continuation_id": self.fact(evidence.get("continuation_id"), "identity", p + "/evidence/continuation_id", ds, "integration"),
            "recorded_verdict": self.fact(evidence.get("verdict"), "token", p + "/evidence/verdict", ds, "integration", known=_VERDICTS),
            "payload_verdict": self.fact(payload.get("verdict"), "token", p + "/evidence/payload/verdict", ds, "integration", known=_VERDICTS),
            "current": current,
            "result": artifact if evidence.get("payload") is not None else None,
            "builds": [], "diagnostics": ds,
        }
        builds = self.sequence(raw.get("builds"), ds, "integration", p + "/builds")
        for i, row in enumerate(builds):
            bp = p + "/builds/" + str(i)
            record = self.dictionary(row, ds, "build", bp)
            build = self.dictionary(record.get("data"), ds, "build", bp + "/data")
            result["builds"].append({
                "key": self.fact(record.get("key"), "str", bp + "/key", ds, "build"),
                "created_at": self.fact(record.get("created_at"), "str", bp + "/created_at", ds, "build"),
                "status": self.fact(build.get("status"), "token", bp + "/data/status", ds, "build", known=_NATIVE),
                "run_key": self.fact(build.get("run_key"), "str", bp + "/data/run_key", ds, "build"),
                "candidate_hash": self.fact(build.get("candidate_hash"), "hash", bp + "/data/candidate_hash", ds, "build"),
                "patch": self.patch(build.get("patch"), bp + "/data/patch", ds, "build"),
                "dependencies": self.keyed_facts(build.get("dependencies"), bp + "/data/dependencies", ds, "build"),
                "label": "CANDIDATE_ONLY_NOT_ACCEPTANCE", "source": bp,
            })
        return result, data

    def integration_stage(self, result, data, raw, tasks, lookup, revision):
        ds, p = result["diagnostics"], "/snapshot/integration"
        self.verdict_consistency(result["recorded_verdict"], result["payload_verdict"],
                                 result["result"]["failure_indicators"] if result["result"] is not None else self.failure({}, p, ds, "integration"), ds, "integration", p + "/evidence")
        if _recorded(result["continuation_id"]) and _recorded(result["evidence_continuation_id"]):
            if not _same(_value(result["continuation_id"]), _value(result["evidence_continuation_id"])):
                self.diag(ds, "INTEGRATION_CONTINUATION_MISMATCH", "integration", p + "/evidence/continuation_id")
        if _recorded(result["lead_integration_revision"]) and _value(result["lead_integration_revision"]) != revision:
            self.diag(ds, "INTEGRATION_REVISION_MISMATCH", "integration", p + "/continuation/context/lead_integration")
        if result["result"] is not None:
            expected = [_value(t["task_id"]) for t in tasks if _value(t["currentness"]["active"]) is True and _value(t["currentness"]["superseded_by"]) is None]
            self.dependencies(result["result"]["dependencies"], data.get("dependencies"), expected, tasks, lookup, ds, "integration", p + "/evidence/payload/evidence/dependencies")
        has_evidence = raw.get("evidence") is not None
        if raw.get("continuation") is None and not has_evidence and not result["builds"]:
            return
        if not has_evidence:
            if any(_value(b["status"]) == "COMPLETED" and _recorded(b["candidate_hash"]) for b in result["builds"]):
                result["stage"] = "INTEGRATION_CANDIDATE_RECORDED"
            return
        if _value(result["current"]) is True:
            required = [result[k] for k in ("continuation_id", "continuation_state", "lead_integration_revision", "evidence_id", "evidence_continuation_id", "recorded_verdict", "payload_verdict", "current")]
            ready = (all(_recorded(x) for x in required) and _value(result["lead_integration_revision"]) == revision
                     and _value(result["continuation_state"]) == "SUCCEEDED" and _value(result["recorded_verdict"]) == _value(result["payload_verdict"]) == "PASS"
                     and not ds and result["result"] is not None and self.artifact_ready(result["result"], data))
            result["stage"] = "INTEGRATION_VERIFIED_AS_CAPTURED" if ready else "EVIDENCE_CONFLICT"
        elif _value(result["recorded_verdict"]) == "PASS":
            result["stage"] = "HISTORICAL_RESULT"
        else:
            result["stage"] = "NOT_ACCEPTED"

    def finish_tasks(self, tasks, metas, attempts):
        ids = [_value(t["task_id"]) for t in tasks]
        lookup = {ident: i for i, ident in enumerate(ids) if ident is not None and ids.count(ident) == 1}
        remaining = set(range(len(tasks)))
        for i, ident in enumerate(ids):
            if ident is not None and ids.count(ident) > 1:
                self.diag(tasks[i]["diagnostics"], "DUPLICATE_ID", "task", metas[i]["source"] + "/id")
        order = []
        # At most 256 nodes, with bounded adjacency. No recursive graph walk.
        for _ in range(len(tasks)):
            eligible = []
            for i in sorted(remaining):
                depends = _value(tasks[i]["depends_on"])
                if depends is None:
                    eligible.append(i)
                    continue
                unknown = [name for name in depends if name not in lookup]
                if unknown:
                    self.diag(tasks[i]["diagnostics"], "DEPENDENCY_GRAPH_INVALID", "task", metas[i]["source"] + "/depends_on")
                if all(lookup.get(name) not in remaining for name in depends):
                    eligible.append(i)
            if not eligible:
                break
            for i in eligible:
                remaining.remove(i)
                order.append(i)
        for i in sorted(remaining):
            self.diag(tasks[i]["diagnostics"], "DEPENDENCY_GRAPH_INVALID", "task", metas[i]["source"] + "/depends_on")
            order.append(i)
        for i in order:
            task, meta = tasks[i], metas[i]
            self.dependencies(task["acceptance_fingerprints"]["dependencies"], meta["evidence"].get("dependencies"), _value(task["depends_on"]),
                              tasks, lookup, task["diagnostics"], "task", meta["source"] + "/verification/evidence/dependencies", declared=task["depends_on"])
            self.task_stage(task, meta, attempts)
        return lookup

    def project(self, selected):
        snap, ds = selected["snapshot"], []
        question = {"mission_id": self.fact(selected["id"], "str", "/id", ds, "mission"),
                    "objective": self.text(snap["objective"], "/snapshot/objective", ds, "mission", objective=True)}
        tasks, metas = [], []
        for i, raw in enumerate(snap["nodes"]):
            task, meta = self.task(raw, "/snapshot/nodes/" + str(i))
            tasks.append(task)
            metas.append(meta)
        integration, integrated_data = self.integration(snap["integration"])
        attempts = self.attempts(snap["runs"], tasks, metas, integration, ds)
        lookup = self.finish_tasks(tasks, metas, attempts)
        self.integration_stage(integration, integrated_data, snap["integration"], tasks, lookup, snap["revision"])
        builds = snap["integration"].get("builds")
        if type(builds) is list:
            for raw, build in zip(builds, integration["builds"]):
                if type(raw) is dict and type(raw.get("data")) is dict:
                    self.bind_dependency_names(build["dependencies"], raw["data"].get("dependencies"), tasks, lookup)
        unresolved = []
        for i, key in enumerate(snap["unresolved"]):
            fact = self.fact(key, "str", "/snapshot/unresolved/" + str(i), ds, "mission")
            associations = [a for a in attempts if _recorded(fact) and _value(a["run_key"]) == fact["value"]]
            associated = associations[0]["associated_task_id"] if len(associations) == 1 else None
            unresolved.append({"key": fact, "associated_task_id": associated})
            for attempt in associations:
                attempt["unresolved"] = True
            if associated in lookup:
                tasks[lookup[associated]]["uncertain_run_keys"].append(fact["value"])
        control = {"phase": self.fact(snap["phase"], "token", "/snapshot/phase", ds, "mission", known=_PHASES)}
        for key in ("paused", "stopped", "project_verified", "all_verified"):
            control[key] = self.fact(snap.get(key), "bool", "/snapshot/" + key, ds, "mission")
        control["reason"] = self.text(snap.get("reason"), "/snapshot/reason", ds, "mission")
        control["unresolved"], control["live_runtime"] = unresolved, "NOT_PROJECTED"
        hashes = {_value(t["acceptance_fingerprints"]["acceptance_hash"]) for t in tasks
                  if _value(t["currentness"]["active"]) is True and _value(t["currentness"]["stale"]) is False
                  and _value(t["currentness"]["superseded_by"]) is None}
        if _value(integration["current"]) is True and integration["result"] is not None:
            hashes.add(_value(integration["result"]["acceptance_hash"]))
        hashes.discard(None)
        if len(hashes) > 1:
            self.diag(ds, "ACCEPTANCE_HASH_DIVERGENT", "mission", "/snapshot/nodes")
        project_verified, all_verified = _value(control["project_verified"]), _value(control["all_verified"])
        conflict = (
            (project_verified is True and integration["stage"] != "INTEGRATION_VERIFIED_AS_CAPTURED")
            or (all_verified is True and project_verified is not True)
            or (_value(control["phase"]) == "COMPLETED" and project_verified is not True)
            or any(d["code"] == "DUPLICATE_ID" for t in tasks for d in t["diagnostics"])
            or len(hashes) > 1 or any(control[k]["state"] == "MALFORMED" for k in ("project_verified", "all_verified"))
            or not _recorded(question["mission_id"])
        )
        if conflict:
            stage = "CAPTURE_CONFLICT"
        elif project_verified is True and integration["stage"] == "INTEGRATION_VERIFIED_AS_CAPTURED":
            stage = "PROJECT_VERIFIED_AS_CAPTURED"
        elif integration["stage"] == "INTEGRATION_VERIFIED_AS_CAPTURED":
            stage = "INTEGRATION_EVIDENCE_RECORDED_PROJECT_NOT_VERIFIED"
        elif any(t["stage"] == "TASK_VERIFIED_AS_CAPTURED" for t in tasks):
            stage = "TASK_EVIDENCE_RECORDED_INTEGRATION_PENDING"
        elif any(t["stage"] in ("CANDIDATE_RECORDED", "NOT_ACCEPTED", "HISTORICAL_RESULT") for t in tasks) or integration["stage"] == "INTEGRATION_CANDIDATE_RECORDED":
            stage = "CANDIDATES_RECORDED"
        else:
            stage = "NO_ENGINEERING_RESULT_RECORDED"
        result = {
            "schema": "sisyfus.lead_result.engineering.s0.v1",
            "classification": "CAPTURED_ENGINEERING_PROJECTION_NOT_ACCEPTANCE",
            "question": question, "conclusion": {"stage": stage, "statements": []}, "tasks": tasks,
            "integration": integration, "attempts": attempts, "control": control,
            "provenance": {
                "capture_basis": "CALLER_CAPTURED_NON_ATOMIC", "captured_at": None, "event_cursor": None, "event_head_hash": None,
                "pinned": False, "bytes_reverified": False, "projection_is_acceptance": False,
                "redaction": "UPSTREAM_CONTROLLER_REDACT_ASSUMED_PLUS_S0_PATTERN_FILTER_NOT_DLP", "mission_id_source": "/id",
                "revision": self.fact(snap["revision"], "int", "/snapshot/revision", ds, "mission"),
                "resume_epoch": self.fact(snap["resume_epoch"], "int", "/snapshot/resume_epoch", ds, "mission"),
                "selected_source_fields": list(_SOURCE_FIELDS),
            },
            "limitations": [{"code": code, "text": text} for code, text in _LIMITATIONS], "diagnostics": ds,
        }
        result["conclusion"]["statements"] = _statements(result)
        if len(json.dumps(result, sort_keys=False, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 8388608:
            _reject("OUTPUT_LIMIT")
        return result


def _display(fact):
    if fact["state"] in ("RECORDED", "FILTERED"):
        value = fact["value"]
        return value if type(value) is str else json.dumps(value, ensure_ascii=False, allow_nan=False)
    return "未记录" if fact["state"] == "NOT_RECORDED" else "已隐藏"


def _statements(result):
    statements = []

    def add(template, text, sources=()):
        if len(statements) >= 4096:
            _reject("LIMIT_EXCEEDED")
        sources = sorted(set(sources))
        if len(sources) > 64:
            _reject("LIMIT_EXCEEDED")
        text = _filter(text) or "已隐藏"
        statements.append({"template_id": template, "text": text, "sources": sources})

    objective = result["question"]["objective"]
    add("Q01", "目标问题：" + _display(objective) + "。", (objective["source"],))
    conclusions = {
        "NO_ENGINEERING_RESULT_RECORDED": ("C01", "尚无已记录的工程结果。"),
        "CANDIDATES_RECORDED": ("C02", "已记录候选或历史证据；不表示已通过验收。"),
        "TASK_EVIDENCE_RECORDED_INTEGRATION_PENDING": ("C03", "已记录任务证据；项目集成证据仍待记录。"),
        "INTEGRATION_EVIDENCE_RECORDED_PROJECT_NOT_VERIFIED": ("C04", "已记录集成证据；控制器未记录项目通过。"),
        "PROJECT_VERIFIED_AS_CAPTURED": ("C05", "捕获时控制器记录项目通过；本投影不是验收。"),
        "CAPTURE_CONFLICT": ("C06", "捕获记录存在冲突；保留分项事实，不给出通过结论。"),
    }
    template, text = conclusions[result["conclusion"]["stage"]]
    add(template, text, ("/snapshot/phase", "/snapshot/project_verified", "/snapshot/all_verified"))

    def evidence_statements(subject, artifact, checks, review):
        if artifact is not None:
            patch = artifact["patch"]
            if not patch["rows"]:
                add("D01", "未记录文件增量", (artifact["candidate_hash"]["source"].rsplit("/", 1)[0] + "/patch",))
            for row in patch["rows"]:
                path = row["path"] if row["path"] is not None else "已隐藏"
                kind = {"ADDED": "新增", "REMOVED": "删除", "MODIFIED": "修改", "REDACTED_AT_CAPTURE": "已隐藏", "WITHHELD": "已隐藏", "MALFORMED": "畸形记录"}[row["change_kind"]]
                before = row["before"][:12] if row["before"] is not None else "未记录"
                after = row["after"][:12] if row["after"] is not None else "未记录"
                add("D01", f"{subject}文件增量：{path}，{kind}；before={before}，after={after}；hash 为前12位。", (row["source"],))
        for check in checks:
            name = _display(check["check"])
            add("M01", f"{subject}检查 {name}：记录分类 {_display(check['status'])}；评估器说明：{_display(check['summary'])}。", (check["check"]["source"], check["status"]["source"], check["summary"]["source"]))
            for scalar in check["measurement"]["scalars"]:
                value = json.dumps(scalar["value"], ensure_ascii=False, allow_nan=False)
                add("M02", f"{subject}检查 {name} 的记录测量：{scalar['name']}={value}。", (check["check"]["source"], scalar["source"]))
        for reason in review["reasons"]:
            add("R01", f"{subject}独立审查：记录裁决 {_display(review['verdict'])}；归属理由：{_display(reason)}。", (review["verdict"]["source"], reason["source"]))
        for reference in review["evidence_refs"]:
            add("R02", f"{subject}审查记录引用：{_display(reference)}。", (reference["source"],))

    for task in result["tasks"]:
        evidence_statements("任务 " + _display(task["task_id"]), task["deliverable"], task["checks"], task["review"])
    integration = result["integration"]
    if integration["result"] is not None:
        artifact = integration["result"]
        evidence_statements("集成", artifact["deliverable"], artifact["checks"], artifact["review"])
    stage = integration["stage"]
    if stage == "PENDING":
        add("I01", "尚无已记录的项目集成证据。", ("/snapshot/integration",))
    elif stage == "INTEGRATION_CANDIDATE_RECORDED":
        add("I02", "已记录集成候选；不表示通过项目验收。", ("/snapshot/integration/builds",))
    elif stage == "NOT_ACCEPTED":
        add("I03", f"集成记录未被接受；continuation={_display(integration['continuation_id'])}，行裁决={_display(integration['recorded_verdict'])}，payload裁决={_display(integration['payload_verdict'])}。", (integration["continuation_id"]["source"], integration["recorded_verdict"]["source"], integration["payload_verdict"]["source"]))
    elif stage == "INTEGRATION_VERIFIED_AS_CAPTURED":
        add("I04", f"捕获时记录集成通过且 current=true；continuation={_display(integration['continuation_id'])}，evidence={_display(integration['evidence_id'])}，revision={_display(integration['lead_integration_revision'])}。", (integration["continuation_id"]["source"], integration["evidence_id"]["source"], integration["lead_integration_revision"]["source"], integration["current"]["source"]))
    elif stage == "HISTORICAL_RESULT":
        add("I05", f"保留历史集成证据；current={_display(integration['current'])}，行裁决={_display(integration['recorded_verdict'])}。", (integration["current"]["source"], integration["recorded_verdict"]["source"]))
    else:
        add("I06", f"集成捕获记录存在冲突；continuation={_display(integration['continuation_id'])}，evidence={_display(integration['evidence_id'])}。", (integration["continuation_id"]["source"], integration["evidence_id"]["source"]))
    control = result["control"]
    add("K01", f"控制器记录：phase={_display(control['phase'])}，paused={_display(control['paused'])}，stopped={_display(control['stopped'])}，project_verified={_display(control['project_verified'])}，all_verified={_display(control['all_verified'])}，待核对调用={len(control['unresolved'])}；这不是实时进程终止证明。", (control[k]["source"] for k in ("phase", "paused", "stopped", "project_verified", "all_verified")))
    add("L01", "限制：非原子捕获，不重新验证字节，不是脱敏完备性证明；没有文件正文、研究结果或设备及第二主机验收。")
    return statements


def project_engineering_result(hub_payload: object, /) -> dict[str, object]:
    """Project only selected recorded facts; perform no IO or acceptance work."""
    if type(hub_payload) is not dict:
        _reject("INPUT_TYPE")
    if len(hub_payload) != 4:
        _reject("ENVELOPE_KEYS")
    if any(type(k) is not str for k in hub_payload):
        _reject("INPUT_TYPE")
    if set(hub_payload) != {"id", "snapshot", "controller", "controls"}:
        _reject("ENVELOPE_KEYS")
    ident = hub_payload["id"]
    if type(ident) is not str or not 1 <= len(ident) <= 128 or not _MISSION_ID.fullmatch(ident):
        _reject("MISSION_ID_INVALID")
    # The lexical mission ID is ASCII. Credential-shaped ASCII identities are
    # admitted as input facts, then withheld rather than renamed by projection.
    if type(hub_payload["snapshot"]) is not dict:
        _reject("SNAPSHOT_REQUIRED_FIELD")
    selected = _Selection().select(hub_payload, "envelope")
    return _Projection().project(selected)
