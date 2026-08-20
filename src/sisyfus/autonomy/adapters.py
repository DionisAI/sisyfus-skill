from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .discovery import OpportunitySignal
from .runtime import Decision


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def decision_from_mapping(raw: Mapping[str, Any]) -> Decision:
    """Convert an untrusted planner response into the narrow Decision schema."""
    return Decision(
        kind=str(raw.get("kind") or "").upper(),  # type: ignore[arg-type]
        capability=str(raw["capability"]) if raw.get("capability") is not None else None,
        arguments=dict(raw.get("arguments") or {}),
        idempotency_key=(
            str(raw["idempotency_key"]) if raw.get("idempotency_key") is not None else None
        ),
        evidence_id=str(raw["evidence_id"]) if raw.get("evidence_id") is not None else None,
        wait_seconds=float(raw["wait_seconds"]) if raw.get("wait_seconds") is not None else None,
        reason=str(raw.get("reason") or ""),
    ).normalized()


@dataclass(frozen=True)
class CommandPlanner:
    """Call any model/agent CLI as a proposal-only planner.

    The command is executed without a shell. It receives immutable context via
    ``SISYFUS_AUTONOMY_CONTEXT_PATH`` and should write one Decision JSON object
    either to ``SISYFUS_AUTONOMY_RESPONSE_PATH`` or stdout. The adapter never
    grants the command authority to settle evidence or mutate runtime truth.
    """

    command: Sequence[str] | str
    workspace: str | Path
    timeout_seconds: float = 300.0
    max_response_bytes: int = 1_000_000

    def _argv(self, *, context_path: Path, response_path: Path, workspace: Path) -> list[str]:
        raw = shlex.split(self.command) if isinstance(self.command, str) else [str(x) for x in self.command]
        if not raw:
            raise ValueError("planner command must not be empty")
        replacements = {
            "{context_path}": str(context_path),
            "{response_path}": str(response_path),
            "{workspace}": str(workspace),
        }
        return [
            token.replace("{context_path}", replacements["{context_path}"])
            .replace("{response_path}", replacements["{response_path}"])
            .replace("{workspace}", replacements["{workspace}"])
            for token in raw
        ]

    def __call__(self, continuation: dict[str, Any], context: Mapping[str, Any]) -> Decision:
        workspace = Path(self.workspace).expanduser().resolve()
        runs_dir = workspace / ".sisyfus" / "autonomy" / "planner-runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_id = f"planner-{uuid.uuid4().hex}"
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=False, exist_ok=False)
        context_path = run_dir / "context.json"
        response_path = run_dir / "response.json"
        stdout_path = run_dir / "stdout.txt"
        stderr_path = run_dir / "stderr.txt"
        context_path.write_text(
            _json(
                {
                    "schema_version": "sisyfus.autonomy_planner_context.v0.8",
                    "continuation": continuation,
                    "context": dict(context),
                }
            ),
            encoding="utf-8",
        )
        argv = self._argv(context_path=context_path, response_path=response_path, workspace=workspace)
        env = os.environ.copy()
        env.update(
            {
                "SISYFUS_AUTONOMY_CONTEXT_PATH": str(context_path),
                "SISYFUS_AUTONOMY_RESPONSE_PATH": str(response_path),
                "SISYFUS_AUTONOMY_WORKSPACE": str(workspace),
                "SISYFUS_AUTONOMY_CONTINUATION_ID": str(continuation.get("id") or ""),
                "SISYFUS_AUTONOMY_EXPECTED_VERSION": str(continuation.get("version") or ""),
            }
        )
        try:
            completed = subprocess.run(
                argv,
                cwd=str(workspace),
                env=env,
                shell=False,
                text=False,
                capture_output=True,
                timeout=float(self.timeout_seconds),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = bytes(exc.stdout or b"")
            stderr = bytes(exc.stderr or b"") + f"\nTIMEOUT after {self.timeout_seconds}s".encode()
            stdout_path.write_bytes(stdout[: self.max_response_bytes])
            stderr_path.write_bytes(stderr[: self.max_response_bytes])
            raise RuntimeError(f"planner command timed out after {self.timeout_seconds}s") from exc
        stdout_path.write_bytes(completed.stdout[: self.max_response_bytes])
        stderr_path.write_bytes(completed.stderr[: self.max_response_bytes])
        if len(completed.stdout) > self.max_response_bytes or len(completed.stderr) > self.max_response_bytes:
            raise RuntimeError("planner output exceeded configured byte limit")
        if completed.returncode != 0:
            tail = completed.stderr.decode("utf-8", errors="replace")[-2000:]
            raise RuntimeError(f"planner command exited {completed.returncode}: {tail}")
        if response_path.exists():
            if response_path.stat().st_size > self.max_response_bytes:
                raise RuntimeError("planner response file exceeded configured byte limit")
            raw_text = response_path.read_text(encoding="utf-8")
        else:
            raw_text = completed.stdout.decode("utf-8", errors="strict")
        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"planner response is not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError("planner response must be one JSON object")
        normalized = decision_from_mapping(raw)
        response_path.write_text(_json(raw), encoding="utf-8")
        return normalized


@dataclass(frozen=True)
class RunbookPlanner:
    """Deterministic planner for audited runbooks and integration tests."""

    decisions: Sequence[Mapping[str, Any]]
    repeat_last: bool = False

    def __call__(self, continuation: dict[str, Any], _context: Mapping[str, Any]) -> Decision:
        index = int(continuation.get("attempt_count") or 0)
        if index >= len(self.decisions):
            if not self.repeat_last or not self.decisions:
                return Decision(kind="WAIT", wait_seconds=60, reason="runbook exhausted")
            index = len(self.decisions) - 1
        return decision_from_mapping(self.decisions[index])


@dataclass(frozen=True)
class JsonInboxSensor:
    """Discover OpportunitySignal objects from a local JSON inbox.

    Each file can contain one signal object, a list of signal objects, or
    ``{"signals": [...]}``. Files are not deleted; durable content-based dedupe
    makes repeated scans safe. Operators can archive files after observing the
    admitted continuation.
    """

    inbox: str | Path
    name: str = "json-inbox"
    source: str = "json-inbox"
    max_files: int = 1000
    max_file_bytes: int = 2_000_000

    def scan(self, _context: Mapping[str, Any]) -> list[OpportunitySignal]:
        inbox = Path(self.inbox).expanduser().resolve()
        inbox.mkdir(parents=True, exist_ok=True)
        paths = sorted(path for path in inbox.glob("*.json") if path.is_file())[: int(self.max_files)]
        signals: list[OpportunitySignal] = []
        for path in paths:
            raw_bytes = path.read_bytes()
            if len(raw_bytes) > int(self.max_file_bytes):
                raise ValueError(f"inbox file exceeds byte limit: {path.name}")
            try:
                decoded = json.loads(raw_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid inbox JSON {path.name}: {exc}") from exc
            if isinstance(decoded, dict) and isinstance(decoded.get("signals"), list):
                items = decoded["signals"]
            elif isinstance(decoded, list):
                items = decoded
            else:
                items = [decoded]
            content_hash = hashlib.sha256(raw_bytes).hexdigest()
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    raise ValueError(f"inbox item {path.name}#{index} must be an object")
                payload = dict(item.get("payload") or {})
                payload.setdefault("_inbox_file", path.name)
                payload.setdefault("_inbox_sha256", content_hash)
                signal = OpportunitySignal(
                    source=str(item.get("source") or self.source),
                    title=str(item.get("title") or path.stem),
                    objective=str(item.get("objective") or ""),
                    payload=payload,
                    priority=float(item.get("priority") or 0.0),
                    dedupe_key=str(
                        item.get("dedupe_key")
                        or f"json-inbox:{path.name}:{index}:{content_hash}"
                    ),
                    max_attempts=(
                        int(item["max_attempts"]) if item.get("max_attempts") is not None else None
                    ),
                    context=dict(item.get("context") or {}),
                ).normalized()
                signals.append(signal)
        return signals
