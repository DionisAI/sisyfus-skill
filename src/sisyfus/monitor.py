from __future__ import annotations

import csv
import json
import os
import re
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .paths import ensure_layout, find_project_root
from .utils import read_json, run_id as make_run_id, run_process, sha256_text, truncate_middle, utc_now, write_json


Status = str
MonitorFn = Callable[[dict[str, Any], Path], dict[str, Any]]


@dataclass(frozen=True)
class BuiltinMonitor:
    id: str
    description: str
    tags: list[str]
    params: dict[str, str]
    fn: MonitorFn

    def spec(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": "builtin",
            "description": self.description,
            "tags": self.tags,
            "params": self.params,
        }


def _as_path(workdir: Path, value: Any) -> Path:
    if value is None or str(value).strip() == "":
        raise ValueError("missing path parameter")
    p = Path(str(value))
    return p if p.is_absolute() else (workdir / p).resolve()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [x.strip() for x in text.split(",") if x.strip()]


def _as_float(params: dict[str, Any], key: str, default: float) -> float:
    raw = params.get(key, default)
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be numeric; got {raw!r}") from exc


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _result(status: Status, *, summary: str, evidence: dict[str, Any] | None = None, metrics: dict[str, Any] | None = None, mismatches: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "summary": summary,
        "evidence": evidence or {},
        "metrics": metrics or {},
        "mismatches": mismatches or [],
    }


def monitor_file_exact_equal(params: dict[str, Any], workdir: Path) -> dict[str, Any]:
    left = _as_path(workdir, params.get("left"))
    right = _as_path(workdir, params.get("right"))
    if not left.exists() or not right.exists():
        return _result("FAILED", summary="one or both files do not exist", evidence={"left_exists": left.exists(), "right_exists": right.exists(), "left": str(left), "right": str(right)})
    left_hash = _sha256_file(left)
    right_hash = _sha256_file(right)
    passed = left_hash == right_hash and left.stat().st_size == right.stat().st_size
    return _result(
        "PASSED" if passed else "FAILED",
        summary="files are byte-identical" if passed else "files differ",
        evidence={"left": str(left), "right": str(right), "left_sha256": left_hash, "right_sha256": right_hash},
        metrics={"left_bytes": left.stat().st_size, "right_bytes": right.stat().st_size},
    )


def monitor_file_contains(params: dict[str, Any], workdir: Path) -> dict[str, Any]:
    path = _as_path(workdir, params.get("file"))
    pattern = params.get("pattern") or params.get("text")
    if pattern is None:
        raise ValueError("file.contains requires pattern=... or text=...")
    if not path.exists():
        return _result("FAILED", summary="file does not exist", evidence={"file": str(path)})
    text = path.read_text(encoding=str(params.get("encoding") or "utf-8"), errors="replace")
    regex = str(params.get("regex", "false")).lower() in {"1", "true", "yes"}
    if regex:
        matched = re.search(str(pattern), text, flags=re.MULTILINE) is not None
    else:
        matched = str(pattern) in text
    return _result(
        "PASSED" if matched else "FAILED",
        summary="pattern found" if matched else "pattern not found",
        evidence={"file": str(path), "regex": regex, "pattern": str(pattern)},
        metrics={"chars": len(text)},
    )


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {path}")
        rows = [dict(row) for row in reader]
        return list(reader.fieldnames), rows


def monitor_csv_exact_equal(params: dict[str, Any], workdir: Path) -> dict[str, Any]:
    left = _as_path(workdir, params.get("left"))
    right = _as_path(workdir, params.get("right"))
    try:
        left_header, left_rows = _read_csv(left)
        right_header, right_rows = _read_csv(right)
    except Exception as exc:  # noqa: BLE001 - converted to monitor failure
        return _result("FAILED", summary=f"could not read CSV: {exc}", evidence={"left": str(left), "right": str(right)})
    mismatches: list[dict[str, Any]] = []
    if left_header != right_header:
        mismatches.append({"type": "header_mismatch", "left_header": left_header, "right_header": right_header})
    if len(left_rows) != len(right_rows):
        mismatches.append({"type": "row_count_mismatch", "left_rows": len(left_rows), "right_rows": len(right_rows)})
    max_mismatches = int(params.get("max_mismatches", 20) or 20)
    for i, (lrow, rrow) in enumerate(zip(left_rows, right_rows), start=1):
        if lrow != rrow:
            mismatches.append({"type": "row_mismatch", "row": i, "left": lrow, "right": rrow})
            if len(mismatches) >= max_mismatches:
                break
    passed = not mismatches
    return _result(
        "PASSED" if passed else "FAILED",
        summary="CSV files are exactly equal" if passed else "CSV files differ",
        evidence={"left": str(left), "right": str(right)},
        metrics={"left_rows": len(left_rows), "right_rows": len(right_rows), "mismatch_count_sampled": len(mismatches)},
        mismatches=mismatches,
    )


def _make_key(row: dict[str, str], key_cols: list[str], index: int) -> tuple[str, ...]:
    if key_cols:
        return tuple(row.get(k, "") for k in key_cols)
    return (str(index),)


def _row_map(rows: list[dict[str, str]], key_cols: list[str]) -> dict[tuple[str, ...], dict[str, str]]:
    result: dict[tuple[str, ...], dict[str, str]] = {}
    duplicates: list[tuple[str, ...]] = []
    for i, row in enumerate(rows):
        key = _make_key(row, key_cols, i)
        if key in result:
            duplicates.append(key)
        result[key] = row
    if duplicates:
        sample = ["|".join(k) for k in duplicates[:5]]
        raise ValueError(f"duplicate CSV keys: {sample}")
    return result


def _close_enough(left: float, right: float, *, abs_tol: float, rel_tol: float) -> bool:
    diff = abs(left - right)
    return diff <= max(abs_tol, rel_tol * max(abs(left), abs(right)))


def monitor_csv_numeric_close(params: dict[str, Any], workdir: Path) -> dict[str, Any]:
    """Compare numeric columns in two CSV files, optionally keyed by one or more columns."""

    left = _as_path(workdir, params.get("left"))
    right = _as_path(workdir, params.get("right"))
    key_cols = _as_list(params.get("key") or params.get("keys"))
    requested_cols = _as_list(params.get("columns") or params.get("cols"))
    ignore_cols = set(_as_list(params.get("ignore_columns")))
    abs_tol = _as_float(params, "abs_tol", 0.0)
    rel_tol = _as_float(params, "rel_tol", 0.0)
    max_mismatches = int(params.get("max_mismatches", 50) or 50)
    try:
        left_header, left_rows = _read_csv(left)
        right_header, right_rows = _read_csv(right)
        left_by_key = _row_map(left_rows, key_cols)
        right_by_key = _row_map(right_rows, key_cols)
    except Exception as exc:  # noqa: BLE001
        return _result("FAILED", summary=f"could not prepare CSV comparison: {exc}", evidence={"left": str(left), "right": str(right)})

    left_keys = set(left_by_key)
    right_keys = set(right_by_key)
    common_keys = sorted(left_keys & right_keys)
    missing_right = sorted(left_keys - right_keys)
    missing_left = sorted(right_keys - left_keys)

    if requested_cols:
        columns = requested_cols
    else:
        columns = [c for c in left_header if c in right_header and c not in set(key_cols) and c not in ignore_cols]

    mismatches: list[dict[str, Any]] = []
    for key in missing_right[:max_mismatches]:
        mismatches.append({"type": "missing_in_right", "key": list(key)})
    for key in missing_left[: max(0, max_mismatches - len(mismatches))]:
        mismatches.append({"type": "missing_in_left", "key": list(key)})

    compared_values = 0
    max_abs_diff = 0.0
    max_rel_diff = 0.0
    for key in common_keys:
        if len(mismatches) >= max_mismatches:
            break
        lrow = left_by_key[key]
        rrow = right_by_key[key]
        for col in columns:
            if col in ignore_cols:
                continue
            lraw = lrow.get(col, "")
            rraw = rrow.get(col, "")
            try:
                lval = float(lraw)
                rval = float(rraw)
            except ValueError:
                if str(lraw) != str(rraw):
                    mismatches.append({"type": "non_numeric_mismatch", "key": list(key), "column": col, "left": lraw, "right": rraw})
                continue
            compared_values += 1
            abs_diff = abs(lval - rval)
            rel_diff = abs_diff / max(abs(lval), abs(rval), 1e-300)
            max_abs_diff = max(max_abs_diff, abs_diff)
            max_rel_diff = max(max_rel_diff, rel_diff)
            if not _close_enough(lval, rval, abs_tol=abs_tol, rel_tol=rel_tol):
                mismatches.append(
                    {
                        "type": "numeric_mismatch",
                        "key": list(key),
                        "column": col,
                        "left": lval,
                        "right": rval,
                        "abs_diff": abs_diff,
                        "rel_diff": rel_diff,
                        "abs_tol": abs_tol,
                        "rel_tol": rel_tol,
                    }
                )
                if len(mismatches) >= max_mismatches:
                    break

    passed = not mismatches
    return _result(
        "PASSED" if passed else "FAILED",
        summary="CSV numeric columns match within tolerance" if passed else "CSV numeric comparison found mismatches",
        evidence={"left": str(left), "right": str(right), "key_columns": key_cols, "columns": columns},
        metrics={
            "left_rows": len(left_rows),
            "right_rows": len(right_rows),
            "common_rows": len(common_keys),
            "compared_values": compared_values,
            "max_abs_diff": max_abs_diff,
            "max_rel_diff": max_rel_diff,
            "mismatch_count_sampled": len(mismatches),
            "missing_in_right_count": len(missing_right),
            "missing_in_left_count": len(missing_left),
        },
        mismatches=mismatches,
    )


def _read_jsonl(path: Path) -> list[Any]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def monitor_jsonl_exact_equal(params: dict[str, Any], workdir: Path) -> dict[str, Any]:
    left = _as_path(workdir, params.get("left"))
    right = _as_path(workdir, params.get("right"))
    key_cols = _as_list(params.get("key") or params.get("keys"))
    max_mismatches = int(params.get("max_mismatches", 20) or 20)
    try:
        left_rows = _read_jsonl(left)
        right_rows = _read_jsonl(right)
    except Exception as exc:  # noqa: BLE001
        return _result("FAILED", summary=f"could not read JSONL: {exc}", evidence={"left": str(left), "right": str(right)})

    def key(row: Any, index: int) -> str:
        if not key_cols:
            return str(index)
        if not isinstance(row, dict):
            return str(index)
        return "|".join(str(row.get(k, "")) for k in key_cols)

    left_map = {key(row, i): row for i, row in enumerate(left_rows)}
    right_map = {key(row, i): row for i, row in enumerate(right_rows)}
    mismatches: list[dict[str, Any]] = []
    for k in sorted(set(left_map) | set(right_map)):
        if k not in left_map:
            mismatches.append({"type": "missing_in_left", "key": k})
        elif k not in right_map:
            mismatches.append({"type": "missing_in_right", "key": k})
        elif left_map[k] != right_map[k]:
            mismatches.append({"type": "object_mismatch", "key": k, "left": left_map[k], "right": right_map[k]})
        if len(mismatches) >= max_mismatches:
            break
    passed = not mismatches
    return _result(
        "PASSED" if passed else "FAILED",
        summary="JSONL records are exactly equal" if passed else "JSONL records differ",
        evidence={"left": str(left), "right": str(right), "keys": key_cols},
        metrics={"left_rows": len(left_rows), "right_rows": len(right_rows), "mismatch_count_sampled": len(mismatches)},
        mismatches=mismatches,
    )


BUILTINS: dict[str, BuiltinMonitor] = {
    "file.exact_equal": BuiltinMonitor(
        id="file.exact_equal",
        description="Check whether two files are byte-identical using size and SHA-256. Useful for exact data equality and artifact regression checks.",
        tags=["file", "hash", "sha256", "exact", "same", "identical", "数据是否相同", "文件相同", "完全一致"],
        params={"left": "left file path", "right": "right file path"},
        fn=monitor_file_exact_equal,
    ),
    "file.contains": BuiltinMonitor(
        id="file.contains",
        description="Check whether a file contains text or a regular expression pattern.",
        tags=["file", "grep", "contains", "regex", "日志", "包含", "模式"],
        params={"file": "file path", "pattern": "text or regex", "regex": "true/false"},
        fn=monitor_file_contains,
    ),
    "csv.exact_equal": BuiltinMonitor(
        id="csv.exact_equal",
        description="Check whether two CSV files have exactly the same header and rows.",
        tags=["csv", "exact", "table", "数据对比", "完全相同", "行相同"],
        params={"left": "left CSV path", "right": "right CSV path"},
        fn=monitor_csv_exact_equal,
    ),
    "csv.numeric_close": BuiltinMonitor(
        id="csv.numeric_close",
        description="Compare numeric columns in two CSV files by row index or key columns with absolute/relative tolerance. Designed for live-vs-backtest, research-vs-production, and regression data comparisons.",
        tags=["csv", "numeric", "tolerance", "live", "backtest", "prod", "research", "实盘", "回测", "数据对比", "数值容差", "行情", "成交", "因子"],
        params={"left": "left CSV path", "right": "right CSV path", "key": "comma-separated key columns", "columns": "comma-separated columns", "abs_tol": "absolute tolerance", "rel_tol": "relative tolerance"},
        fn=monitor_csv_numeric_close,
    ),
    "jsonl.exact_equal": BuiltinMonitor(
        id="jsonl.exact_equal",
        description="Compare two JSONL files exactly, by line index or key fields.",
        tags=["jsonl", "events", "records", "exact", "日志", "事件", "记录", "相同"],
        params={"left": "left JSONL path", "right": "right JSONL path", "key": "comma-separated object keys"},
        fn=monitor_jsonl_exact_equal,
    ),
}


class MonitorRegistry:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = find_project_root(root)
        self.sf = ensure_layout(self.root)
        self.registry_path = self.sf / "monitors" / "registry.json"
        self.runs_dir = self.sf / "monitors" / "runs"
        if not self.registry_path.exists():
            write_json(self.registry_path, {"schema_version": "sisyfus.monitor_registry.v0.2", "monitors": []})

    def _read_registry(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {"schema_version": "sisyfus.monitor_registry.v0.2", "monitors": []}
        data = read_json(self.registry_path)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid monitor registry: {self.registry_path}")
        data.setdefault("monitors", [])
        return data

    def _write_registry(self, data: dict[str, Any]) -> None:
        data["schema_version"] = "sisyfus.monitor_registry.v0.2"
        write_json(self.registry_path, data)

    def list(self, *, include_builtin: bool = True) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if include_builtin:
            items.extend(m.spec() for m in BUILTINS.values())
        for spec in self._read_registry().get("monitors", []):
            if isinstance(spec, dict):
                item = {"source": "custom", **spec}
                items.append(item)
        return sorted(items, key=lambda x: str(x.get("id")))

    def get(self, monitor_id: str) -> dict[str, Any]:
        if monitor_id in BUILTINS:
            return BUILTINS[monitor_id].spec()
        for item in self._read_registry().get("monitors", []):
            if item.get("id") == monitor_id:
                return {"source": "custom", **item}
        raise KeyError(f"Unknown monitor: {monitor_id}")

    def add_custom(self, monitor_id: str, *, description: str, command: str, tags: list[str] | None = None) -> dict[str, Any]:
        if monitor_id in BUILTINS:
            raise ValueError(f"Cannot override builtin monitor id: {monitor_id}")
        data = self._read_registry()
        monitors = [m for m in data.get("monitors", []) if m.get("id") != monitor_id]
        spec = {
            "id": monitor_id,
            "type": "command",
            "description": description,
            "tags": tags or [],
            "command": command,
            "created_at": utc_now(),
            "usage_count": 0,
        }
        monitors.append(spec)
        data["monitors"] = sorted(monitors, key=lambda x: str(x.get("id")))
        self._write_registry(data)
        return {"source": "custom", **spec}

    def _bump_usage(self, monitor_id: str, status: str) -> None:
        data = self._read_registry()
        changed = False
        for item in data.get("monitors", []):
            if item.get("id") == monitor_id:
                item["usage_count"] = int(item.get("usage_count", 0) or 0) + 1
                item["last_used_at"] = utc_now()
                item["last_status"] = status
                changed = True
        if changed:
            self._write_registry(data)

    def suggest(self, task_text: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        task_l = task_text.lower()
        task_tokens = set(re.findall(r"[a-zA-Z0-9_.-]+", task_l))
        cjk_chars = set(ch for ch in task_text if "\u4e00" <= ch <= "\u9fff")
        for spec in self.list(include_builtin=True):
            haystack = " ".join([str(spec.get("id", "")), str(spec.get("description", "")), " ".join(map(str, spec.get("tags", [])))])
            hay_l = haystack.lower()
            spec_tokens = set(re.findall(r"[a-zA-Z0-9_.-]+", hay_l))
            score = 0.0
            if str(spec.get("id", "")).lower() in task_l:
                score += 6.0
            score += len(task_tokens & spec_tokens) * 1.0
            for tag in spec.get("tags", []):
                tag_s = str(tag).lower()
                if tag_s and tag_s in task_l:
                    score += 3.0
            for ch in cjk_chars:
                if ch in haystack:
                    score += 0.15
            # Specific phrase boosts for the user's dominant quant ops use case.
            if any(x in task_l for x in ["backtest", "回测"]) and any(x in task_l for x in ["live", "prod", "实盘"]):
                if spec.get("id") == "csv.numeric_close":
                    score += 4.0
            if score > 0:
                item = dict(spec)
                item["score"] = round(score, 3)
                scored.append(item)
        scored.sort(key=lambda x: (-float(x["score"]), str(x.get("id"))))
        return scored[:top_k]

    def run(self, monitor_id: str, *, params: dict[str, Any] | None = None, workdir: str | Path | None = None, run_dir: str | Path | None = None) -> dict[str, Any]:
        params = params or {}
        workdir_path = Path(workdir or self.root).resolve()
        rid = make_run_id("monitor-")
        out_dir = Path(run_dir) if run_dir else self.runs_dir / rid
        out_dir.mkdir(parents=True, exist_ok=True)
        spec = self.get(monitor_id)
        started = time.monotonic()
        try:
            if spec.get("source") == "builtin":
                raw = BUILTINS[monitor_id].fn(params, workdir_path)
            else:
                raw = self._run_custom(spec, params=params, workdir=workdir_path, run_dir=out_dir)
        except Exception as exc:  # noqa: BLE001 - monitor failure should be structured, not crash outer loop
            raw = _result("FAILED", summary=f"monitor raised exception: {exc}", evidence={"exception_type": type(exc).__name__})
        elapsed = round(time.monotonic() - started, 3)
        status = str(raw.get("status") or "UNCERTAIN").upper()
        if status not in {"PASSED", "FAILED", "UNCERTAIN", "NEEDS_AGENT", "NEEDS_HUMAN"}:
            status = "UNCERTAIN"
        result = {
            "schema_version": "sisyfus.monitor_result.v0.2",
            "run_id": rid,
            "monitor_id": monitor_id,
            "status": status,
            "summary": raw.get("summary", ""),
            "params": params,
            "workdir": str(workdir_path),
            "run_dir": str(out_dir),
            "elapsed_seconds": elapsed,
            "created_at": utc_now(),
            "source": spec.get("source"),
            "description": spec.get("description"),
            "evidence": raw.get("evidence", {}),
            "metrics": raw.get("metrics", {}),
            "mismatches": raw.get("mismatches", []),
            "signature": sha256_text(json.dumps(raw, sort_keys=True, default=str)),
        }
        write_json(out_dir / "result.json", result)
        self._write_markdown(out_dir / "report.md", result)
        self._bump_usage(monitor_id, status)
        return result

    def _run_custom(self, spec: dict[str, Any], *, params: dict[str, Any], workdir: Path, run_dir: Path) -> dict[str, Any]:
        command = str(spec.get("command") or "")
        if not command:
            return _result("UNCERTAIN", summary="custom monitor has no command", evidence={"monitor_id": spec.get("id")})
        env = os.environ.copy()
        env.update(
            {
                "SISYFUS_MONITOR_ID": str(spec.get("id")),
                "SISYFUS_MONITOR_PARAMS_JSON": json.dumps(params, sort_keys=True),
                "SISYFUS_WORKDIR": str(workdir),
                "SISYFUS_MONITOR_RUN_DIR": str(run_dir),
            }
        )
        # Quote every interpolated value: monitor params are external input and
        # must not gain shell metacharacter meaning (shlex quoting stays a
        # single word even inside template-supplied quotes).
        formatted = command.replace("{workdir}", shlex.quote(str(workdir))).replace("{run_dir}", shlex.quote(str(run_dir)))
        for key, value in params.items():
            formatted = formatted.replace("{param." + str(key) + "}", shlex.quote(str(value)))
        proc = run_process(formatted, cwd=workdir, timeout=int(spec.get("timeout_seconds", 600) or 600), shell=True, env=env)
        stdout = proc.get("stdout", "")
        stderr = proc.get("stderr", "")
        (run_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
        (run_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
        try:
            parsed = json.loads(stdout.strip()) if stdout.strip() else {}
            if isinstance(parsed, dict) and parsed.get("status"):
                return parsed
        except json.JSONDecodeError:
            pass
        status = "PASSED" if int(proc.get("exit_code", 1)) == 0 else "FAILED"
        return _result(
            status,
            summary="custom monitor command exited successfully" if status == "PASSED" else "custom monitor command failed",
            evidence={"command": formatted, "exit_code": proc.get("exit_code"), "stdout_tail": truncate_middle(stdout, 2000), "stderr_tail": truncate_middle(stderr, 2000)},
            metrics={"elapsed_seconds": proc.get("elapsed_seconds"), "timed_out": proc.get("timed_out")},
        )

    def _write_markdown(self, path: Path, result: dict[str, Any]) -> None:
        lines = ["# Sisyfus Monitor Report", "", f"Monitor: `{result['monitor_id']}`", f"Status: **{result['status']}**", f"Summary: {result.get('summary', '')}", ""]
        if result.get("metrics"):
            lines.append("## Metrics")
            for k, v in result["metrics"].items():
                lines.append(f"- `{k}`: `{v}`")
            lines.append("")
        if result.get("mismatches"):
            lines.append("## Sample mismatches")
            for mismatch in result["mismatches"][:20]:
                lines.append("```json")
                lines.append(json.dumps(mismatch, indent=2, sort_keys=True, default=str))
                lines.append("```")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_param_assignments(assignments: list[str] | None) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in assignments or []:
        if "=" not in item:
            raise ValueError(f"parameter must be KEY=VALUE, got: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"empty parameter key in: {item}")
        params[key] = value
    return params


def route_ops_task(root: str | Path | None, *, task: str, params: dict[str, Any] | None = None, threshold: float = 2.0, workdir: str | Path | None = None) -> dict[str, Any]:
    """Route an ops task to a reusable monitor when confidence is sufficient.

    If no monitor is good enough, no model is called. A structured NEEDS_AGENT
    record is returned so the caller can ask an agent to write a new monitor once,
    then register it for future reuse.
    """

    registry = MonitorRegistry(root)
    suggestions = registry.suggest(task, top_k=3)
    if suggestions and float(suggestions[0].get("score", 0.0)) >= threshold:
        monitor_id = str(suggestions[0]["id"])
        result = registry.run(monitor_id, params=params or {}, workdir=workdir)
        result["routing"] = {"task": task, "selected_monitor": monitor_id, "score": suggestions[0].get("score"), "alternatives": suggestions[1:]}
        return result
    sf = ensure_layout(root)
    task_id = "write-monitor-" + sha256_text(task)[:19].replace(":", "-")
    open_task = {
        "task_id": task_id,
        "source": "sisyfus-ops-router",
        "title": f"Write reusable monitor for ops task: {task[:120]}",
        "reason": "No registered monitor matched above routing threshold; use an agent once to implement and register a deterministic monitor.",
        "task": task,
        "params": params or {},
        "suggestions": suggestions,
        "status": "open",
        "priority": "P2",
        "created_at": utc_now(),
    }
    from .utils import append_jsonl

    append_jsonl(sf / "tasks" / "open.jsonl", open_task)
    return {
        "schema_version": "sisyfus.ops_route.v0.2",
        "status": "NEEDS_AGENT",
        "summary": "No suitable reusable monitor found; wrote open task for one-time agent implementation.",
        "task": open_task,
        "suggestions": suggestions,
    }
