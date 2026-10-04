#!/usr/bin/env python3
"""Prepare frozen operator engineering cases, not native runs or a Tripo product.

The paired runner consumes evaluation_root/manifest.json with search/holdout
arrays of {id, spec: absolute-public-spec-path}. Both procedures use the SAME
spec/source/checks. No initial DAG, preferred task count, baseline handicap or
claimed improvement is supplied. The public module interfaces make a normal
two-task dependency plan plausible; one cohesive scoped task is also valid.

This command creates a NEW catalog and never overwrites/removes an existing one.
Reference implementations exist only in helper tests outside worker projects.
All checks are external, hash-frozen, stdlib-only and retain temporary artifacts.
Holdout is prepared but never sent to a model here. Real native counts, reviews,
integration evidence and untouched-holdout evaluation belong to the core runner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sisyfus.workers.lead_contracts import DEFAULT_PROCEDURE, load_lead_spec
from sisyfus.workers.mission import files
from sisyfus.workers.protocol import digest

DEFAULT_ROOT = ROOT / "artifacts/techlead/procedure-trials-catalog"

SEARCH_README = '''# Durable job checkpoint and request retries

Engineering-validation fixture, not a production service or a Tripo integration.
Implement only job_state.py and request_retry.py. No external network, sleep,
subprocesses, payload logging or permanent deletion. Keep this README unchanged.

Interface A (job_state.py):
* read_state(path) returns a mapping of job ID to its latest event. A missing
  file returns {}. Read UTF-8 JSONL; every line must be complete and newline-ended.
  Each event has EXACTLY job_id, status, result. job_id is a nonblank string;
  status is queued/running/succeeded/failed. result is any finite JSON value.
  Reject malformed JSON, schema, nonfinite numbers and illegal transitions with
  ValueError without returning partial state or leaking payloads in diagnostics.
* append_state(path, job_id, status, result=None) first validates the existing
  journal and new event, then appends ONE UTF-8 JSON line, flushes and calls
  os.fsync on the descriptor before returning None. Never truncate/replace/delete
  history or create missing parent directories. Missing job IDs may start in any
  valid status; queued may remain queued or become running/succeeded/failed;
  running may remain running or become succeeded/failed. Terminal records are
  immutable: every subsequent event for that ID, even identical, is invalid.
  Invalid input/corrupt history leaves existing bytes unchanged. File errors and
  fsync errors propagate; never claim a failed persistence operation succeeded.

Interface B (request_retry.py):
* retry_request(fetch, job_id, journal_path, max_attempts=3) validates a nonblank
  job ID and a positive STRICT int (bool rejected) before calling fetch. Calls
  fetch(job_id) at most max_attempts times, retrying ONLY OSError. On exhaustion
  re-raise the final original OSError instance. All other fetch exceptions propagate
  unchanged immediately. On success persist one succeeded event via job_state's
  append_state, then return the ORIGINAL result object, not its JSON copy. Any
  serialization, transition or persistence error propagates; no successful return
  precedes durability. No failed-attempt payload is recorded; no printing/logging.

Frozen external checks: component validates A (8 tests); whole validates both
modules and their integration (16 tests). required_checks=[whole] and integration
checks=[whole]. A separate first task may use component, followed by B/whole;
bundling both tightly related modules is equally acceptable. Do not weaken tests,
choose a known failing baseline, or assume coalescing improves actual call counts.
'''

HOLDOUT_README = '''# Archive export manifest and command argument boundary

Independent engineering-validation holdout, not a Tripo export/product workflow.
Implement only export_manifest.py and export_command.py. Keep this README unchanged.
No file IO, network, sleep, process execution, payload printing/logging or deletion
in these pure functions. No actual archive is created; no command is executed.

Interface A (export_manifest.py):
* build_manifest(entries) accepts a list of dicts, each with EXACTLY name, size,
  sha256. name is a nonempty portable relative member path: reject absolute paths,
  backslashes, colon, NUL, empty slash components, '.' or '..' components. Unicode,
  spaces and shell metacharacters are data, not shell syntax. Names must be unique.
  size is a STRICT int >=0 (bool rejected). sha256 is exactly 64 lowercase hex
  characters. Invalid containers/fields raise ValueError with generic diagnostics
  that do not include the entry or its values. Do not mutate inputs or reuse input
  dicts in the result. Empty input is valid. Return EXACTLY
  {schema:'archive-export.v1', files:[validated copies sorted by name],
  total_bytes:<sum>}. Do not normalize unsafe paths into accepted paths.

Interface B (export_command.py):
* build_export_command(executable, output_path, entries) validates executable and
  output_path as nonempty strings, neither beginning '-' nor containing NUL;
  whitespace-only is invalid, but valid strings are preserved verbatim. Paths
  with spaces/quotes/metacharacters remain SINGLE argument values. Delegate entry
  validation to export_manifest.build_manifest; propagate validation errors.
  Return EXACTLY a list [executable, '--output', output_path, '--manifest-json',
  <canonical JSON manifest>]. Canonical JSON is ensure_ascii=False, sort_keys=True,
  separators=(',', ':'), allow_nan=False. No shell quoting, joining into a command
  string, execution or filesystem reads/writes. Return fresh lists on every call.

Frozen external checks: component validates A (8 tests); whole validates both
modules and their integration (16 tests). required_checks=[whole] and integration
checks=[whole]. A component task then dependent whole task or a cohesive bundled
task may satisfy the SAME acceptance. This holdout is a distinct domain, not a
renamed request/retry task. Procedures must earn measured improvements on real
reservations while preserving semantic acceptance and independent review.
'''

# Each checker imports only the first module in component mode: a legitimate
# component-first DAG can pass before the dependent module is implemented.
CHECK_COMMON = '''import contextlib, importlib, io, json, logging, os, pathlib, sys, tempfile, unittest
from unittest import mock
candidate = pathlib.Path(sys.argv[1]).resolve()
stage = sys.argv[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(candidate))

def scratch():
    return pathlib.Path(tempfile.mkdtemp(prefix="sisyfus-procedure-check-", dir=os.environ.get("TMPDIR", "/private/tmp")))

def project_scope(test):
    test.assertEqual((candidate / "README.md").read_text(), README)
    names = {p.name for p in candidate.iterdir() if p.name != "__pycache__"}
    test.assertEqual(names, {"README.md", *MODULE_FILES})

def no_output(test, callback):
    out, err, logs = io.StringIO(), io.StringIO(), io.StringIO()
    handler = logging.StreamHandler(logs)
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            callback()
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)
    test.assertEqual((out.getvalue(), err.getvalue(), logs.getvalue()), ("", "", ""))
'''

SEARCH_TESTS = '''class Component(unittest.TestCase):
    def test_01_missing_journal(self):
        self.assertEqual(state.read_state(scratch() / "events.jsonl"), {})
    def test_02_utf8_durable_round_trip(self):
        path = scratch() / "events.jsonl"
        result = {"asset": "fixture://图像", "items": [1, None, True]}
        original = os.fsync
        with mock.patch("os.fsync", wraps=original) as sync:
            self.assertIsNone(state.append_state(path, "作业", "succeeded", result))
            self.assertGreaterEqual(sync.call_count, 1)
        raw = path.read_text()
        self.assertTrue(raw.endswith("\\n"))
        event = json.loads(raw)
        self.assertEqual(event, {"job_id": "作业", "status": "succeeded", "result": result})
        self.assertEqual(state.read_state(path), {"作业": event})
    def test_03_append_history_and_multiple_jobs(self):
        path = scratch() / "events.jsonl"
        state.append_state(path, "a", "queued")
        before = path.read_bytes()
        state.append_state(path, "b", "failed", None)
        state.append_state(path, "a", "running")
        state.append_state(path, "a", "running")
        state.append_state(path, "a", "succeeded", 42)
        self.assertTrue(path.read_bytes().startswith(before))
        self.assertEqual(len(path.read_text().splitlines()), 5)
        self.assertEqual(state.read_state(path)["a"]["result"], 42)
        self.assertEqual(state.read_state(path)["b"]["status"], "failed")
    def test_04_invalid_new_event_preserves_bytes(self):
        path = scratch() / "events.jsonl"
        state.append_state(path, "ok", "queued")
        before = path.read_bytes()
        for ident, status in [("", "queued"), (" ", "queued"), (None, "queued"), (7, "queued"),
                              ("a", "unknown"), ("a", None)]:
            with self.subTest(ident=ident, status=status), self.assertRaises(ValueError):
                state.append_state(path, ident, status)
            self.assertEqual(path.read_bytes(), before)
    def test_05_terminal_and_reverse_transitions_rejected(self):
        for status in ("succeeded", "failed", "running"):
            path = scratch() / "events.jsonl"
            state.append_state(path, "job", status)
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                state.append_state(path, "job", "queued")
            self.assertEqual(path.read_bytes(), before)
            if status != "running":
                with self.assertRaises(ValueError):
                    state.append_state(path, "job", status)
                self.assertEqual(path.read_bytes(), before)
    def test_06_corruption_and_schema_are_not_partial_success(self):
        valid = json.dumps({"job_id":"j", "status":"queued", "result":None}) + "\\n"
        bad_lines = ["not-json\\n", '{}\\n', '[]\\n',
            '{"job_id":"j","status":"queued","result":NaN}\\n',
            '{"job_id":"j","status":"queued","result":null,"extra":1}\\n',
            '{"job_id":"j","status":"queued","result":null}',
            '{"job_id":null,"status":"queued","result":null}\\n',
            '{"job_id":"j","status":"invalid","result":null}\\n']
        for bad in bad_lines:
            path = scratch() / "events.jsonl"
            path.write_text(valid + bad)
            before = path.read_bytes()
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                state.read_state(path)
            with self.assertRaises(ValueError):
                state.append_state(path, "new", "queued")
            self.assertEqual(path.read_bytes(), before)
        path = scratch() / "events.jsonl"
        path.write_text(json.dumps({"job_id":"j","status":"failed","result":None}) + "\\n" + valid)
        with self.assertRaises(ValueError):
            state.read_state(path)
    def test_07_nonfinite_result_rejected_before_write(self):
        path = scratch() / "events.jsonl"
        state.append_state(path, "ok", "queued")
        before = path.read_bytes()
        for value in (float("nan"), {"x":float("inf")}, object()):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                state.append_state(path, "bad", "queued", value)
            self.assertEqual(path.read_bytes(), before)
    def test_08_persistence_and_fsync_errors_propagate(self):
        with self.assertRaises(OSError):
            state.append_state(scratch() / "missing-parent" / "events.jsonl", "j", "queued")
        error = OSError("fixture durability error")
        with mock.patch("os.fsync", side_effect=error), self.assertRaises(OSError) as raised:
            state.append_state(scratch() / "events.jsonl", "j", "queued")
        self.assertIs(raised.exception, error)

class Integration(unittest.TestCase):
    def test_09_immediate_success_persists_before_return(self):
        path = scratch() / "events.jsonl"
        payload, calls = {"asset":[1,2]}, []
        def fetch(ident):
            calls.append(ident)
            return payload
        self.assertIs(retry.retry_request(fetch, "job", path), payload)
        self.assertEqual(calls, ["job"])
        self.assertEqual(state.read_state(path)["job"], {"job_id":"job","status":"succeeded","result":payload})
    def test_10_transient_errors_retry_to_success(self):
        path = scratch() / "events.jsonl"
        calls = []
        def fetch(ident):
            calls.append(ident)
            if len(calls) < 3:
                raise OSError("fixture transient")
            return 42
        self.assertEqual(retry.retry_request(fetch, "j", path, max_attempts=3), 42)
        self.assertEqual(calls, ["j"] * 3)
        self.assertEqual(len(path.read_text().splitlines()), 1)
    def test_11_exhaustion_reraises_last_original_error(self):
        errors = [OSError("first"), OSError("last")]
        calls = []
        path = scratch() / "events.jsonl"
        def fetch(ident):
            calls.append(ident)
            raise errors[len(calls)-1]
        with self.assertRaises(OSError) as raised:
            retry.retry_request(fetch, "j", path, max_attempts=2)
        self.assertIs(raised.exception, errors[-1])
        self.assertEqual(len(calls), 2)
        self.assertFalse(path.exists())
    def test_12_other_fetch_error_propagates_without_retry(self):
        error, calls = TypeError("fixture protocol error"), []
        path = scratch() / "events.jsonl"
        def fetch(ident):
            calls.append(ident)
            raise error
        with self.assertRaises(TypeError) as raised:
            retry.retry_request(fetch, "j", path)
        self.assertIs(raised.exception, error)
        self.assertEqual(calls, ["j"])
        self.assertFalse(path.exists())
    def test_13_invalid_limits_and_ids_precede_fetch(self):
        for ident, limit in [("j",0),("j",-1),("j",True),("j",1.5),("j","3"),("",3),(None,3),(" ",3)]:
            calls = []
            with self.subTest(ident=ident, limit=limit), self.assertRaises(ValueError):
                retry.retry_request(lambda x:calls.append(x), ident, scratch() / "events.jsonl", max_attempts=limit)
            self.assertEqual(calls, [])
    def test_14_success_never_masks_persistence_error(self):
        with self.assertRaises(OSError):
            retry.retry_request(lambda _:42, "j", scratch() / "missing" / "events.jsonl")
        error = OSError("fixture fsync failure")
        with mock.patch("os.fsync", side_effect=error), self.assertRaises(OSError) as raised:
            retry.retry_request(lambda _:42, "j", scratch() / "events.jsonl")
        self.assertIs(raised.exception, error)
    def test_15_result_validation_and_terminal_checkpoint(self):
        path = scratch() / "events.jsonl"
        with self.assertRaises(ValueError):
            retry.retry_request(lambda _:object(), "j", path)
        self.assertFalse(path.exists())
        state.append_state(path, "j", "succeeded", 1)
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            retry.retry_request(lambda _:2, "j", path)
        self.assertEqual(path.read_bytes(), before)
    def test_16_no_payload_output_and_frozen_write_scope(self):
        path = scratch() / "events.jsonl"
        no_output(self, lambda:retry.retry_request(lambda _:{"private":"FIXTURE_PRIVATE_DATA"}, "j", path))
        no_output(self, lambda:state.read_state(path))
        no_output(self, lambda:state.append_state(scratch() / "other.jsonl", "q", "queued", "FIXTURE_PRIVATE_DATA"))
        project_scope(self)
'''

HOLDOUT_TESTS = '''def entry(name="data.bin", size=7, sha="a"*64):
    return {"name":name,"size":size,"sha256":sha}

class Component(unittest.TestCase):
    def test_01_empty_archive(self):
        self.assertEqual(manifest.build_manifest([]), {"schema":"archive-export.v1","files":[],"total_bytes":0})
    def test_02_sorted_copied_unicode_and_total(self):
        rows = [entry("图像/asset.bin",4),entry("a b.bin",3)]
        result = manifest.build_manifest(rows)
        self.assertEqual(result, {"schema":"archive-export.v1","files":[rows[1],rows[0]],"total_bytes":7})
        self.assertIsNot(result["files"][0], rows[1])
    def test_03_unsafe_member_paths(self):
        for name in ("", "/root", "../x", "a/../x", "./x", "a/./x", "a//x", "a/", "a\\\\b", "C:x", "x\\x00y"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                manifest.build_manifest([entry(name)])
    def test_04_duplicate_members(self):
        with self.assertRaises(ValueError):
            manifest.build_manifest([entry("x",1),entry("x",2)])
    def test_05_strict_nonnegative_sizes(self):
        for size in (-1,True,False,1.5,"7",None):
            with self.subTest(size=size), self.assertRaises(ValueError):
                manifest.build_manifest([entry(size=size)])
        self.assertEqual(manifest.build_manifest([entry(size=0)])["total_bytes"],0)
    def test_06_lowercase_sha256(self):
        for sha in ("a"*63,"a"*65,"A"*64,"g"*64,None,7):
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                manifest.build_manifest([entry(sha=sha)])
    def test_07_exact_schema_and_container_types(self):
        for rows in (None,{},(),"text",[None],[{}],[{**entry(),"private":"FIXTURE_PRIVATE_DATA"}],
                     [{"name":"x","size":1}],[entry(name=None)]):
            with self.subTest(rows=type(rows).__name__), self.assertRaises(ValueError):
                manifest.build_manifest(rows)
    def test_08_inputs_unchanged_and_defensive_copies(self):
        rows = [entry("b"),entry("a")]
        before = json.dumps(rows)
        result = manifest.build_manifest(rows)
        result["files"][0]["name"] = "changed"
        self.assertEqual(json.dumps(rows), before)

class Integration(unittest.TestCase):
    def test_09_exact_argv_and_canonical_json(self):
        rows = [entry("图像/x",2),entry("a",1)]
        expected = json.dumps(manifest.build_manifest(rows),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
        self.assertEqual(command.build_export_command("/fixture/export", "archive bundle.json", rows),
            ["/fixture/export","--output","archive bundle.json","--manifest-json",expected])
    def test_10_metacharacters_remain_atomic_data(self):
        executable, output = '/fixture/tool name', 'a;$(echo nope) "quoted".json'
        rows = [entry("assets/a;$(echo nope) b.bin")]
        argv = command.build_export_command(executable, output, rows)
        self.assertIsInstance(argv,list)
        self.assertEqual(len(argv),5)
        self.assertEqual(argv[:4],[executable,"--output",output,"--manifest-json"])
        self.assertEqual(json.loads(argv[4])["files"][0]["name"],rows[0]["name"])
    def test_11_invalid_executable(self):
        for value in (""," ",None,7,"-program","a\\x00b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                command.build_export_command(value,"out",[])
    def test_12_invalid_output_argument(self):
        for value in (""," ",None,7,"--output=other","a\\x00b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                command.build_export_command("tool",value,[])
    def test_13_upstream_validation_is_not_bypassed(self):
        for rows in ([entry("../payload")],[entry(size=-1)],[entry(sha="bad")],[entry("x"),entry("x")]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                command.build_export_command("tool","out",rows)
    def test_14_no_mutation_or_shared_argv(self):
        rows = [entry("b"),entry("a")]
        before = json.dumps(rows)
        first = command.build_export_command("tool","out",rows)
        second = command.build_export_command("tool","out",rows)
        first[0] = "changed"
        self.assertEqual(second[0],"tool")
        self.assertEqual(json.dumps(rows),before)
    def test_15_no_io_or_execution(self):
        import subprocess
        def prohibited(*a,**k):
            raise AssertionError("pure export function attempted IO/execution")
        with mock.patch("builtins.open",side_effect=prohibited), mock.patch("os.open",side_effect=prohibited), \\
             mock.patch("os.system",side_effect=prohibited), mock.patch("subprocess.run",side_effect=prohibited), \\
             mock.patch("subprocess.Popen",side_effect=prohibited), mock.patch("pathlib.Path.open",side_effect=prohibited):
            command.build_export_command("tool","out",[entry()])
    def test_16_no_payload_output_scope_and_private_diagnostics(self):
        rows = [entry("FIXTURE_PRIVATE_DATA.bin")]
        no_output(self, lambda:manifest.build_manifest(rows))
        no_output(self, lambda:command.build_export_command("tool","out",rows))
        try:
            manifest.build_manifest([{**entry(),"private":"FIXTURE_PRIVATE_DATA"}])
        except ValueError as exc:
            self.assertNotIn("FIXTURE_PRIVATE_DATA",str(exc))
        else:
            self.fail("private extra field was accepted")
        project_scope(self)
'''

CHECK_END = '''
result = unittest.TestResult()
expected = 8 if stage == "component" else 16
out, err = io.StringIO(), io.StringIO()
try:
    if stage not in {"component", "whole"}:
        raise ValueError("unknown checker stage")
    FIRST_IMPORT
    if stage == "whole":
        SECOND_IMPORT
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Component)
    if stage == "whole":
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(Integration))
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        suite.run(result)
    accepted = result.wasSuccessful() and result.testsRun == expected and not out.getvalue() and not err.getvalue()
    failures = [test.id() for test, trace in result.failures + result.errors]
    if out.getvalue() or err.getvalue():
        failures.append("unexpected candidate stdout/stderr")
except Exception as exc:
    accepted, failures = False, ["checker boundary: " + type(exc).__name__]
print(json.dumps({"accepted":accepted,"tests":result.testsRun,"expected_tests":expected,
                  "failures":failures,"stdout_bytes":len(out.getvalue().encode()),"stderr_bytes":len(err.getvalue().encode())}))
'''

CASES = {
    "durable-job-retries": {"split": "search", "readme": SEARCH_README,
        "modules": {"job_state.py": '''"""Append-only durable job history; implement the README contract."""
def read_state(path):
    raise NotImplementedError("read_state contract pending")

def append_state(path, job_id, status, result=None):
    raise NotImplementedError("durable append contract pending")
''', "request_retry.py": '''"""Bounded fetch retry coordinated with durable job checkpoints."""
def retry_request(fetch, job_id, journal_path, max_attempts=3):
    raise NotImplementedError("retry and persistence integration pending")
'''}, "tests": SEARCH_TESTS,
        "first": 'state = importlib.import_module("job_state")',
        "second": 'retry = importlib.import_module("request_retry")'},
    "archive-export-argv": {"split": "holdout", "readme": HOLDOUT_README,
        "modules": {"export_manifest.py": '''"""Portable archive member validation and deterministic manifest construction."""
def build_manifest(entries):
    raise NotImplementedError("archive manifest contract pending")
''', "export_command.py": '''"""Pure shell-free argument construction for an archive export boundary."""
def build_export_command(executable, output_path, entries):
    raise NotImplementedError("export argument integration pending")
'''}, "tests": HOLDOUT_TESTS,
        "first": 'manifest = importlib.import_module("export_manifest")',
        "second": 'command = importlib.import_module("export_command")'},
}


def write(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


def write_json(path: Path, value) -> None:
    write(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checker_text(case) -> str:
    ending = CHECK_END.replace("FIRST_IMPORT", case["first"]).replace("SECOND_IMPORT", case["second"])
    return CHECK_COMMON + "\nREADME = " + repr(case["readme"]) + "\nMODULE_FILES = " + repr(list(case["modules"])) + "\n" + case["tests"] + ending


def build_catalog(directory: Path, *, python: str = sys.executable) -> dict:
    directory = directory.resolve()
    if not Path(python).is_absolute() or not Path(python).is_file():
        raise ValueError("checker Python must be an existing absolute executable file")
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {"search": [], "holdout": []}
    metadata = {}
    for ident, case in CASES.items():
        base = directory / case["split"] / ident
        project, trusted = base / "project", base / "trusted"
        project.mkdir(parents=True)
        trusted.mkdir()
        write(project / "README.md", case["readme"])
        for name, stub in case["modules"].items():
            write(project / name, stub)
        checker = trusted / "acceptance.py"
        write(checker, checker_text(case))
        checker_hash = sha256(checker)
        def check(stage, tests):
            return {"argv": [python, "-I", "-S", "-B", str(checker), "{candidate}", stage],
                "timeout": 30, "code_hashes": {str(checker):checker_hash},
                "contract": {"kind":"rules", "pass_if":{"all":[{"path":"accepted","op":"eq","value":True},
                    {"path":"tests","op":"eq","value":tests}]},
                    "fail_if":{"all":[{"path":"accepted","op":"eq","value":False}]}}}
        spec = {"schema_version":"sisyfus.techlead.v1", "source":str(project),
            "objective":case["readme"], "constraints":["Only " + ", ".join(case["modules"]) + " are writable",
                "Frozen README, trusted acceptance and controller state must remain unchanged",
                "No payload printing/logging, external network, sleeps, subprocess execution or permanent deletion"],
            "deliverables":list(case["modules"]) + ["component and whole deterministic receipts", "independent reviews", "integrated candidate"],
            "roles":{"lead":{"driver":"claude","model":"claude-opus-5-5"},
                "worker":{"driver":"codex","model":"gpt-6.1-sol"}, "reviewer":{"driver":"claude","model":"claude-opus-5-5"}},
            "checks":{"component":check("component",8),"whole":check("whole",16)},
            "required_checks":["whole"], "integration_checks":["whole"], "procedure":DEFAULT_PROCEDURE,
            "parallelism":2,"timeout":900,"max_turns":None,"max_calls":None,"max_iterations":None,
            "max_tokens":None,"max_cost_usd":None,"max_wall_minutes":None,
            "rsi":{"enabled":False,"auto_promote":False},
            "validation_kind":"OPERATOR_ENGINEERING_PROCEDURE_TRIAL_NOT_TRIPO_PRODUCT"}
        normalized = load_lead_spec(spec)
        spec_path = base / "mission.json"
        write_json(spec_path, spec)
        manifest[case["split"]].append({"id":ident,"spec":str(spec_path)})
        metadata[ident] = {"split":case["split"],"spec_sha256":sha256(spec_path),
            "source_hash":digest(files(project)),"acceptance_hash":normalized["acceptance_hash"],
            "checker_sha256":checker_hash,"component_tests":8,"whole_tests":16,"modules":list(case["modules"])}
    if len({c["source_hash"] for c in metadata.values()}) != len(metadata):
        raise ValueError("distinct domains require distinct source content fingerprints")
    write_json(directory / "catalog.json", {"kind":"ENGINEERING_VALIDATION_NOT_TRIPO_PRODUCT",
        "native_calls":0,"holdout_status":"PREPARED_UNTOUCHED_BY_MODELS","cases":metadata,
        "improvement":"UNMEASURED; actual paired native reservations and full acceptance determine outcome"})
    write(directory / "README.md", __doc__ + "\n\nSource/check hashes are in catalog.json. Reference helper tests live outside all public worker projects.\n")
    # Publish the runner entrypoint last, only after all specs/checks are complete.
    manifest_path = directory / "manifest.json"
    write_json(manifest_path, manifest)
    return {"status":"PREPARED_NO_NATIVE_CALLS","evaluation_root":str(directory),
        "manifest":str(manifest_path),"manifest_sha256":sha256(manifest_path),"cases":metadata}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=DEFAULT_ROOT)
    parser.add_argument("--python",default=sys.executable,help="absolute checker interpreter for both arms")
    args = parser.parse_args(argv)
    print(json.dumps(build_catalog(args.output,python=args.python),ensure_ascii=False,allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
