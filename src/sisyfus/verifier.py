from __future__ import annotations

from pathlib import Path
from typing import Any

from .monitor import MonitorRegistry
from .utils import run_process, sha256_text, truncate_middle, write_json
from .worktree import WorktreeManager, matches_forbidden


def command_signature(command_results: list[dict[str, Any]], monitor_results: list[dict[str, Any]] | None = None) -> str:
    failed = []
    for result in command_results:
        if result.get("exit_code") != 0:
            failed.append(
                result.get("command", "")
                + "\n"
                + truncate_middle(result.get("stderr", "") + result.get("stdout", ""), 2000)
            )
    for result in monitor_results or []:
        if result.get("status") not in {"PASSED"}:
            failed.append(str(result.get("monitor_id", "")) + "\n" + truncate_middle(str(result), 2000))
    return sha256_text("\n---\n".join(failed)) if failed else sha256_text("PASS")


def _normalize_monitor_entries(goal: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[Any] = []
    entries.extend(goal.get("monitors", []) or [])
    entries.extend(goal.get("done_when", {}).get("monitors", []) or [])
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, str):
            normalized.append({"id": entry, "params": {}})
        elif isinstance(entry, dict):
            monitor_id = entry.get("id") or entry.get("monitor_id")
            if not monitor_id:
                normalized.append({"id": "", "params": {}, "invalid": entry})
            else:
                normalized.append({"id": str(monitor_id), "params": dict(entry.get("params", {}) or {})})
        else:
            normalized.append({"id": "", "params": {}, "invalid": entry})
    return normalized


def verify_goal(
    goal: dict[str, Any],
    *,
    workdir: Path,
    run_dir: Path | None = None,
    round_index: int | None = None,
    command_timeout: int = 900,
    root: Path | None = None,
) -> dict[str, Any]:
    commands = list(goal.get("done_when", {}).get("commands", []) or [])
    monitor_entries = _normalize_monitor_entries(goal)
    constraints = goal.get("constraints", {}) or {}
    command_results: list[dict[str, Any]] = []
    monitor_results: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    warnings: list[str] = []

    if not commands and not monitor_entries:
        warnings.append("No deterministic done_when.commands or monitors declared. Verifier cannot safely PASS.")
    for command in commands:
        command_results.append(run_process(str(command), cwd=workdir, timeout=command_timeout, shell=True))

    if monitor_entries:
        registry = MonitorRegistry(root or workdir)
        monitor_parent = None
        if run_dir:
            monitor_parent = run_dir / "monitors" / (f"round-{round_index:02d}" if round_index is not None else "manual")
            monitor_parent.mkdir(parents=True, exist_ok=True)
        for idx, entry in enumerate(monitor_entries, start=1):
            if entry.get("invalid") or not entry.get("id"):
                monitor_results.append(
                    {
                        "schema_version": "sisyfus.monitor_result.v0.2",
                        "monitor_id": "<invalid>",
                        "status": "UNCERTAIN",
                        "summary": "Invalid monitor entry in GoalSpec",
                        "params": entry.get("params", {}),
                        "evidence": {"entry": entry.get("invalid", entry)},
                        "metrics": {},
                        "mismatches": [],
                    }
                )
                continue
            run_subdir = monitor_parent / f"{idx:02d}-{entry['id'].replace('/', '_')}" if monitor_parent else None
            monitor_results.append(registry.run(str(entry["id"]), params=entry.get("params", {}), workdir=workdir, run_dir=run_subdir))

    changed_files = WorktreeManager.changed_files(workdir)
    forbidden = list(constraints.get("forbidden_paths", []) or [])
    for path in changed_files:
        matched = matches_forbidden(path, forbidden)
        if matched:
            violations.append({"type": "forbidden_path_changed", "path": path, "pattern": matched})

    numstat = WorktreeManager.diff_numstat(workdir)
    max_changed_lines = int(constraints.get("max_changed_lines", 0) or 0)
    if constraints.get("require_small_diff") and max_changed_lines and numstat.get("available"):
        if int(numstat.get("changed_lines", 0)) > max_changed_lines:
            violations.append(
                {
                    "type": "diff_too_large",
                    "changed_lines": numstat.get("changed_lines"),
                    "max_changed_lines": max_changed_lines,
                }
            )

    failed_commands = [r for r in command_results if int(r.get("exit_code", 1)) != 0]
    failed_monitors = [r for r in monitor_results if r.get("status") == "FAILED"]
    uncertain_monitors = [r for r in monitor_results if r.get("status") not in {"PASSED", "FAILED"}]
    if not commands and not monitor_entries:
        status = "UNCERTAIN"
    elif failed_commands or failed_monitors or violations:
        status = "FAILED"
    elif uncertain_monitors:
        status = "UNCERTAIN"
    else:
        status = "PASSED"

    result = {
        "status": status,
        "round": round_index,
        "commands": command_results,
        "monitors": monitor_results,
        "failed_command_count": len(failed_commands),
        "failed_monitor_count": len(failed_monitors),
        "uncertain_monitor_count": len(uncertain_monitors),
        "violations": violations,
        "warnings": warnings,
        "changed_files": changed_files,
        "numstat": numstat,
        "signature": command_signature(command_results, monitor_results) if (failed_commands or failed_monitors or uncertain_monitors) else None,
        "workdir": str(workdir),
    }
    if run_dir:
        name = f"verifier-round-{round_index:02d}.json" if round_index is not None else "verifier.json"
        write_json(run_dir / name, result)
        write_verifier_markdown(run_dir / name.replace(".json", ".md"), result)
    return result


def write_verifier_markdown(path: Path, result: dict[str, Any]) -> None:
    lines = [f"# Verifier Report", "", f"Status: **{result['status']}**", ""]
    if result.get("warnings"):
        lines.append("## Warnings")
        for w in result["warnings"]:
            lines.append(f"- {w}")
        lines.append("")
    if result.get("violations"):
        lines.append("## Violations")
        for v in result["violations"]:
            lines.append(f"- `{v.get('type')}`: {v}")
        lines.append("")
    lines.append("## Commands")
    if not result.get("commands"):
        lines.append("No deterministic commands declared.")
    for cmd in result.get("commands", []):
        lines.append(f"### `{cmd.get('command')}`")
        lines.append(f"Exit code: `{cmd.get('exit_code')}`; elapsed: `{cmd.get('elapsed_seconds')}` seconds")
        stdout = truncate_middle(cmd.get("stdout", ""), 2000).strip()
        stderr = truncate_middle(cmd.get("stderr", ""), 2000).strip()
        if stdout:
            lines.append("\nStdout:\n```text\n" + stdout + "\n```")
        if stderr:
            lines.append("\nStderr:\n```text\n" + stderr + "\n```")
    if result.get("monitors"):
        lines.append("\n## Monitors")
        for mon in result["monitors"]:
            lines.append(f"### `{mon.get('monitor_id')}`")
            lines.append(f"Status: **{mon.get('status')}**")
            lines.append(f"Summary: {mon.get('summary', '')}")
            metrics = mon.get("metrics") or {}
            if metrics:
                lines.append("Metrics:")
                for k, v in metrics.items():
                    lines.append(f"- `{k}`: `{v}`")
            mismatches = mon.get("mismatches") or []
            if mismatches:
                lines.append("Sample mismatches:")
                for mismatch in mismatches[:5]:
                    lines.append("```json")
                    import json

                    lines.append(json.dumps(mismatch, indent=2, sort_keys=True, default=str))
                    lines.append("```")
    if result.get("changed_files"):
        lines.append("\n## Changed files")
        for f in result["changed_files"]:
            lines.append(f"- `{f}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
