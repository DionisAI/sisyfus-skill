from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .discovery import SensorError, SensorScanResult
from .models import Decision, DecisionKind, OpportunitySignal


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
        default=str,
    ) + "\n"


def _utc_after(seconds: float) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=max(0.0, float(seconds)))
    ).isoformat(timespec="microseconds").replace("+00:00", "Z")


def decision_from_mapping(raw: Mapping[str, Any]) -> Decision:
    kind = str(raw.get("kind") or raw.get("action") or "").upper()
    wait_seconds = raw.get("wait_seconds")
    if kind == DecisionKind.WAIT.value and wait_seconds is None and raw.get("wait_until"):
        target = datetime.fromisoformat(str(raw["wait_until"]).replace("Z", "+00:00"))
        wait_seconds = max(0.0, (target - datetime.now(timezone.utc)).total_seconds())
    return Decision(
        kind=kind,
        reason=str(raw.get("reason") or raw.get("rationale") or "planner proposal"),
        capability=str(raw["capability"]) if raw.get("capability") is not None else None,
        arguments=dict(raw.get("arguments") or {}),
        risk_tier=int(raw.get("risk_tier") or 0),
        verifier_id=str(raw.get("verifier_id") or "default"),
        idempotency_key=(
            str(raw["idempotency_key"]) if raw.get("idempotency_key") is not None else None
        ),
        evidence_id=str(raw["evidence_id"]) if raw.get("evidence_id") is not None else None,
        wait_seconds=float(wait_seconds) if wait_seconds is not None else None,
        terminal_on_pass=bool(raw.get("terminal_on_pass", False)),
        experience_key=(
            str(raw["experience_key"]) if raw.get("experience_key") is not None else None
        ),
        experience_scope=dict(raw.get("experience_scope") or {}),
    ).normalized()


@dataclass(frozen=True)
class CommandPlanner:
    """Proposal-only process adapter with bounded streamed output.

    This reduces ambient authority by using an environment allowlist. It is not
    an OS sandbox; the continuous CLI therefore requires an explicit opt-in.
    """

    command: Sequence[str] | str
    workspace: str | Path
    timeout_seconds: float = 300.0
    max_response_bytes: int = 1_000_000
    poll_interval_seconds: float = 0.02
    environment_allowlist: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "PATH",
                "HOME",
                "USER",
                "LOGNAME",
                "LANG",
                "LC_ALL",
                "LC_CTYPE",
                "TMPDIR",
                "TEMP",
                "TMP",
                "PYTHONPATH",
                "VIRTUAL_ENV",
                "SYSTEMROOT",
                "WINDIR",
                "PATHEXT",
            }
        )
    )

    def _argv(self) -> list[str]:
        raw = shlex.split(self.command) if isinstance(self.command, str) else [str(x) for x in self.command]
        if not raw:
            raise ValueError("planner command must not be empty")
        return raw

    @staticmethod
    def _kill(process: subprocess.Popen[Any]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:  # pragma: no cover - Windows
                process.kill()
        except ProcessLookupError:
            pass
        process.wait(timeout=5)

    def __call__(self, continuation: Mapping[str, Any], context: Mapping[str, Any]) -> Decision:
        workspace = Path(self.workspace).expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        run_dir = workspace / ".sisyfus" / "autonomy" / "planner-runs" / f"planner-{uuid.uuid4().hex}"
        run_dir.mkdir(parents=True, exist_ok=False)
        context_path = run_dir / "context.json"
        response_path = run_dir / "response.json"
        stdout_path = run_dir / "stdout.bin"
        stderr_path = run_dir / "stderr.bin"
        context_path.write_text(
            _json(
                {
                    "schema_version": "sisyfus.autonomy_planner_context.v0.8",
                    "continuation": dict(continuation),
                    "context": dict(context),
                }
            ),
            encoding="utf-8",
        )
        env = {
            key: value
            for key, value in os.environ.items()
            if key in self.environment_allowlist
        }
        env.update(
            {
                "SISYFUS_AUTONOMY_CONTEXT_PATH": str(context_path),
                "SISYFUS_AUTONOMY_RESPONSE_PATH": str(response_path),
                "SISYFUS_AUTONOMY_WORKSPACE": str(workspace),
                "SISYFUS_AUTONOMY_CONTINUATION_ID": str(continuation.get("id") or ""),
                "SISYFUS_AUTONOMY_EXPECTED_VERSION": str(continuation.get("version") or ""),
            }
        )
        started = time.monotonic()
        with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
            process = subprocess.Popen(
                self._argv(),
                cwd=str(workspace),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                shell=False,
                start_new_session=(os.name == "posix"),
            )
            limit_error: str | None = None
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed > float(self.timeout_seconds):
                    limit_error = f"planner command timed out after {self.timeout_seconds}s"
                    break
                stdout_size = stdout_path.stat().st_size
                stderr_size = stderr_path.stat().st_size
                response_size = response_path.stat().st_size if response_path.exists() else 0
                if max(stdout_size, stderr_size, response_size) > int(self.max_response_bytes):
                    limit_error = "planner output exceeded configured byte limit"
                    break
                time.sleep(max(0.001, float(self.poll_interval_seconds)))
            if limit_error is not None:
                self._kill(process)
                raise RuntimeError(limit_error)
            returncode = process.wait()
        for path in (stdout_path, stderr_path, response_path):
            if path.exists() and path.stat().st_size > int(self.max_response_bytes):
                raise RuntimeError("planner output exceeded configured byte limit")
        if returncode != 0:
            tail = stderr_path.read_bytes()[-2000:].decode("utf-8", errors="replace")
            raise RuntimeError(f"planner command exited {returncode}: {tail}")
        raw_text = (
            response_path.read_text(encoding="utf-8")
            if response_path.exists()
            else stdout_path.read_text(encoding="utf-8")
        )
        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"planner response is not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError("planner response must be one JSON object")
        response_path.write_text(_json(raw), encoding="utf-8")
        return decision_from_mapping(raw)

    def decide(self, context: Any) -> Decision:
        continuation = (
            dict(context.continuation)
            if hasattr(context, "continuation")
            else dict(context.get("continuation") or {})
        )
        raw_context = context.as_dict() if hasattr(context, "as_dict") else dict(context)
        return self(continuation, raw_context)


@dataclass
class RunbookPlanner:
    decisions: Sequence[Mapping[str, Any]]
    repeat_last: bool = False

    def __call__(self, continuation: Mapping[str, Any], _context: Mapping[str, Any]) -> Decision:
        index = int(continuation.get("step_index") or continuation.get("attempt_count") or 0)
        if index >= len(self.decisions):
            if self.repeat_last and self.decisions:
                index = len(self.decisions) - 1
            else:
                return Decision(
                    kind=DecisionKind.WAIT,
                    reason="runbook exhausted",
                    wait_seconds=60,
                )
        return decision_from_mapping(self.decisions[index])

    def decide(self, context: Any) -> Decision:
        continuation = (
            dict(context.continuation)
            if hasattr(context, "continuation")
            else dict(context.get("continuation") or {})
        )
        return self(continuation, {})


@dataclass(frozen=True)
class JsonInboxSensor:
    inbox: str | Path
    name: str = "json-inbox"
    source: str = "json-inbox"
    quarantine_dir: str | Path | None = None
    max_files: int = 1000
    max_file_bytes: int = 2_000_000

    def _quarantine(self, path: Path) -> Path | None:
        if self.quarantine_dir is None:
            return None
        root = Path(self.quarantine_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        target = root / path.name
        counter = 1
        while target.exists():
            target = root / f"{path.stem}-{counter}{path.suffix}"
            counter += 1
        shutil.move(str(path), str(target))
        return target

    def scan(self, _context: Mapping[str, Any]) -> SensorScanResult:
        inbox = Path(self.inbox).expanduser().resolve()
        inbox.mkdir(parents=True, exist_ok=True)
        signals: list[OpportunitySignal] = []
        errors: list[SensorError] = []
        paths = sorted(path for path in inbox.glob("*.json") if path.is_file())[: int(self.max_files)]
        for path in paths:
            try:
                size = path.stat().st_size
                if size > int(self.max_file_bytes):
                    raise ValueError(f"inbox file exceeds byte limit: {path.name}")
                raw_bytes = path.read_bytes()
                if len(raw_bytes) > int(self.max_file_bytes):
                    raise ValueError(f"inbox file exceeds byte limit: {path.name}")
                decoded = json.loads(raw_bytes.decode("utf-8"))
                if isinstance(decoded, dict) and isinstance(decoded.get("signals"), list):
                    items = decoded["signals"]
                elif isinstance(decoded, list):
                    items = decoded
                else:
                    items = [decoded]
                content_hash = hashlib.sha256(raw_bytes).hexdigest()
                for index, raw in enumerate(items):
                    if not isinstance(raw, dict):
                        raise ValueError(f"inbox item {path.name}#{index} must be an object")
                    payload = dict(raw.get("payload") or {})
                    payload.setdefault("_inbox_file", path.name)
                    payload.setdefault("_inbox_sha256", content_hash)
                    signals.append(
                        OpportunitySignal(
                            source=str(raw.get("source") or self.source),
                            kind=str(raw.get("kind") or "research_need"),
                            title=str(raw.get("title") or path.stem),
                            objective=str(raw.get("objective") or ""),
                            payload=payload,
                            priority=float(raw.get("priority") or 0.0),
                            confidence=float(raw.get("confidence") or 0.5),
                            dedupe_key=str(
                                raw.get("dedupe_key")
                                or f"json-inbox:{path.name}:{index}:{content_hash}"
                            ),
                            max_attempts=(
                                int(raw["max_attempts"])
                                if raw.get("max_attempts") is not None
                                else None
                            ),
                            context=dict(raw.get("context") or {}),
                            not_before=(
                                str(raw["not_before"])
                                if raw.get("not_before") is not None
                                else None
                            ),
                            expires_at=(
                                str(raw["expires_at"])
                                if raw.get("expires_at") is not None
                                else None
                            ),
                        ).normalized()
                    )
            except BaseException as exc:
                quarantined = self._quarantine(path)
                errors.append(
                    SensorError(
                        source=self.name,
                        item=str(quarantined or path),
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                )
        return SensorScanResult(tuple(signals), tuple(errors))
