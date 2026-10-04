"""External reference validation only; no native calls or claimed RSI improvement."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sisyfus.workers.lead_contracts import DEFAULT_PROCEDURE, load_lead_spec, validate_plan
from sisyfus.workers.lead_learning import _operator_spec
from sisyfus.workers.mission import copy_candidate, files
from sisyfus.workers.protocol import digest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/prepare_procedure_trials.py"
SPEC = importlib.util.spec_from_file_location("procedure_trial_fixture_generator", SCRIPT)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)

# These solutions are NOT emitted into the catalog/public sources. They are
# installed only into separate retained test-side candidates to verify the gates.
REFERENCES = {
    "durable-job-retries": {
        "job_state.py": '''import json, os
from pathlib import Path

def validate(event, history):
    if not isinstance(event, dict) or set(event) != {"job_id", "status", "result"}:
        raise ValueError("invalid journal event schema")
    ident, status = event["job_id"], event["status"]
    if not isinstance(ident, str) or not ident.strip() or not isinstance(status, str) or status not in {"queued", "running", "succeeded", "failed"}:
        raise ValueError("invalid journal event fields")
    try:
        encoded = json.dumps(event, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("invalid finite JSON result") from None
    old = history.get(ident)
    if old and (old["status"] in {"succeeded", "failed"} or old["status"] == "running" and status == "queued"):
        raise ValueError("invalid journal transition")
    return encoded

def reject_constant(value):
    raise ValueError("nonfinite journal number")

def read_state(path):
    try:
        stream = Path(path).open(encoding="utf-8")
    except FileNotFoundError:
        return {}
    history = {}
    with stream:
        for line in stream:
            if not line.endswith("\\n"):
                raise ValueError("incomplete journal event")
            try:
                event = json.loads(line, parse_constant=reject_constant)
            except ValueError:
                raise ValueError("invalid journal JSON") from None
            validate(event, history)
            history[event["job_id"]] = event
    return history

def append_state(path, job_id, status, result=None):
    history = read_state(path)
    event = {"job_id":job_id, "status":status, "result":result}
    encoded = validate(event, history)
    with Path(path).open("a",encoding="utf-8") as stream:
        stream.write(encoded + "\\n")
        stream.flush()
        os.fsync(stream.fileno())
''',
        "request_retry.py": '''import job_state

def retry_request(fetch, job_id, journal_path, max_attempts=3):
    if type(max_attempts) is not int or max_attempts <= 0 or not isinstance(job_id,str) or not job_id.strip():
        raise ValueError("invalid request limit or identity")
    for attempt in range(max_attempts):
        try:
            result = fetch(job_id)
        except OSError:
            if attempt + 1 == max_attempts:
                raise
            continue
        job_state.append_state(journal_path,job_id,"succeeded",result)
        return result
''',
    },
    "archive-export-argv": {
        "export_manifest.py": '''import re

def build_manifest(entries):
    if not isinstance(entries,list):
        raise ValueError("invalid entry container")
    names, copies = set(), []
    for item in entries:
        if not isinstance(item,dict) or set(item) != {"name","size","sha256"}:
            raise ValueError("invalid archive entry schema")
        name,size,sha = item["name"],item["size"],item["sha256"]
        if not isinstance(name,str) or not name or name.startswith("/") or any(c in name for c in ("\\\\",":","\\x00")) or any(part in {"",".",".."} for part in name.split("/")):
            raise ValueError("invalid archive member path")
        if name in names:
            raise ValueError("duplicate archive member")
        if type(size) is not int or size < 0 or not isinstance(sha,str) or not re.fullmatch("[0-9a-f]{64}",sha):
            raise ValueError("invalid archive entry metadata")
        names.add(name)
        copies.append(dict(item))
    return {"schema":"archive-export.v1","files":sorted(copies,key=lambda x:x["name"]),"total_bytes":sum(x["size"] for x in copies)}
''',
        "export_command.py": '''import json
import export_manifest

def build_export_command(executable, output_path, entries):
    for value in (executable,output_path):
        if not isinstance(value,str) or not value.strip() or value.startswith("-") or "\\x00" in value:
            raise ValueError("invalid export argument")
    value = export_manifest.build_manifest(entries)
    return [executable,"--output",output_path,"--manifest-json",json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)]
''',
    },
}


@pytest.fixture
def catalog(tmp_path):
    return helper.build_catalog(tmp_path / "catalog", python=sys.executable)


def public_spec(catalog, ident):
    manifest = json.loads(Path(catalog["manifest"]).read_text())
    row = next(row for rows in manifest.values() for row in rows if row["id"] == ident)
    return json.loads(Path(row["spec"]).read_text())


def candidate(tmp_path, raw, ident, *, reference=True):
    destination = tmp_path / (ident + "-" + ("reference" if reference else "stub"))
    copy_candidate(Path(raw["source"]), destination)
    if reference:
        for name, text in REFERENCES[ident].items():
            (destination / name).write_text(text)
    return destination


def measure(raw, destination, stage):
    check = raw["checks"][stage]
    argv = [str(destination) if value == "{candidate}" else value for value in check["argv"]]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30,
                            env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1"})
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.splitlines()) == 1, result.stdout
    assert not result.stderr
    return json.loads(result.stdout)


def test_manifest_shape_distinct_domains_and_operator_sources(catalog):
    manifest = json.loads(Path(catalog["manifest"]).read_text())
    assert set(manifest) == {"search","holdout"}
    assert [row["id"] for row in manifest["search"]] == ["durable-job-retries"]
    assert [row["id"] for row in manifest["holdout"]] == ["archive-export-argv"]
    assert helper.sha256(Path(catalog["manifest"])) == catalog["manifest_sha256"]
    hashes, modules = [], []
    for ident in REFERENCES:
        raw = public_spec(catalog, ident)
        assert Path(raw["source"]).is_absolute()
        assert raw["procedure"] == DEFAULT_PROCEDURE and "tasks" not in raw
        assert raw["required_checks"] == raw["integration_checks"] == ["whole"]
        assert raw["roles"]["reviewer"]["model"] == "claude-opus-5-5"
        normalized = load_lead_spec(raw)
        assert "initial_plan" not in normalized
        modules.append(set(REFERENCES[ident]))
        hashes.append(digest(files(Path(raw["source"]))))
        for name,check in raw["checks"].items():
            code = Path(next(iter(check["code_hashes"])))
            assert code.is_absolute() and not code.is_relative_to(Path(raw["source"]))
            assert helper.sha256(code) == check["code_hashes"][str(code)]
        assert set(files(Path(raw["source"]))) == {"README.md",*REFERENCES[ident]}
        assert all("NotImplementedError" in (Path(raw["source"]) / name).read_text() for name in REFERENCES[ident])
    assert len(set(hashes)) == 2 and not modules[0] & modules[1]


@pytest.mark.parametrize("ident", list(REFERENCES))
@pytest.mark.parametrize("stage,expected", [("component",8),("whole",16)])
def test_external_correct_reference_passes_frozen_check(catalog, tmp_path, ident, stage, expected):
    raw = public_spec(catalog,ident)
    before = files(Path(raw["source"]))
    destination = candidate(tmp_path,raw,ident)
    measured = measure(raw,destination,stage)
    assert measured["accepted"] is True and measured["tests"] == expected and not measured["failures"]
    assert files(Path(raw["source"])) == before


@pytest.mark.parametrize("ident", list(REFERENCES))
def test_bad_reference_is_rejected_by_whole_check(catalog, tmp_path, ident):
    raw = public_spec(catalog,ident)
    destination = candidate(tmp_path,raw,ident)
    if ident == "durable-job-retries":
        (destination / "request_retry.py").write_text("def retry_request(fetch, job_id, journal_path, max_attempts=3):\n    return 999\n")
    else:
        (destination / "export_command.py").write_text("def build_export_command(executable, output_path, entries):\n    return 'shell ' + str(entries)\n")
    measured = measure(raw,destination,"whole")
    assert measured["accepted"] is False and measured["tests"] == 16 and measured["failures"]


@pytest.mark.parametrize("ident", list(REFERENCES))
def test_component_can_pass_with_dependent_module_still_stub(catalog, tmp_path, ident):
    raw = public_spec(catalog,ident)
    destination = candidate(tmp_path,raw,ident,reference=False)
    first = next(iter(REFERENCES[ident]))
    (destination / first).write_text(REFERENCES[ident][first])
    assert measure(raw,destination,"component")["accepted"] is True
    measured = measure(raw,destination,"whole")
    assert measured["accepted"] is False and measured["tests"] == 16


@pytest.mark.parametrize("ident", list(REFERENCES))
def test_two_task_or_bundled_plan_preserves_identical_operator_hash(catalog,ident):
    raw = public_spec(catalog,ident)
    baseline, alternative = load_lead_spec(raw), load_lead_spec({**raw,"procedure":"Coalesce only cohesive bounded interfaces without weakening acceptance."})
    assert digest(_operator_spec(baseline)) == digest(_operator_spec(alternative))
    modules = list(REFERENCES[ident])
    first = {"id":"component","objective":"Implement interface A","check":"component","write_paths":[modules[0]],"depends_on":[],"acceptance":raw["objective"]}
    second = {"id":"integration","objective":"Implement dependent interface B","check":"whole","write_paths":[modules[1]],"depends_on":["component"],"acceptance":raw["objective"]}
    split = validate_plan({"architecture":"two explicit interfaces","interfaces":modules,"tasks":[first,second]},baseline)
    bundled = validate_plan({"architecture":"one cohesive bounded implementation","interfaces":modules,"tasks":[{**first,"check":"whole","write_paths":modules}]},alternative)
    assert len(split["tasks"]) == 2 and len(bundled["tasks"]) == 1
    assert baseline["acceptance_hash"] == alternative["acceptance_hash"]


def test_no_catalog_overwrite_and_no_native_claims(catalog):
    root = Path(catalog["evaluation_root"])
    before = files(root)
    with pytest.raises(FileExistsError):
        helper.build_catalog(root)
    assert files(root) == before
    metadata = json.loads((root/"catalog.json").read_text())
    assert metadata["native_calls"] == 0
    assert metadata["holdout_status"] == "PREPARED_UNTOUCHED_BY_MODELS"
    assert "UNMEASURED" in metadata["improvement"] and "NOT_TRIPO_PRODUCT" in metadata["kind"]


def test_actual_paired_runner_catalog_reader_accepts_frozen_manifest(catalog):
    from sisyfus.workers.lead_trials import _catalog
    parsed = _catalog(Path(catalog["evaluation_root"]))
    assert parsed["manifest_hash"] == catalog["manifest_sha256"]
    cases = parsed["execution_cases"]
    assert {case["split"] for case in cases} == {"search","holdout"}
    assert len({case["family_hash"] for case in cases}) == 2
    assert not set(cases[0]["families"]) & set(cases[1]["families"])
    assert all(not case["missions"] and not case["provenance"] for case in cases)
    assert all(case["spec"]["required_checks"] == ["whole"] for case in cases)
