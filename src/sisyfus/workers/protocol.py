from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

EventSink = Callable[[str, dict[str, Any]], None]
ControlSource = Callable[[], list[dict[str, Any]]]


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def bounded(value: Any, low: float, high: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be in [{low}, {high}]")
    return float(value)


@dataclass(frozen=True)
class Request:
    task_id: str
    prompt: str
    cwd: str
    model: str
    mode: str = "read-only"
    timeout: float = 300
    max_output_bytes: int = 8_000_000
    # None omits a provider turn cap, not the per-call timeout/output bounds.
    max_turns: int | None = 8
    session_id: str | None = None

    def __post_init__(self) -> None:
        if not self.task_id or not self.model.strip() or not self.prompt.strip():
            raise ValueError("task_id, explicit model, and prompt are required")
        if len(self.prompt.encode()) > 200_000:
            raise ValueError("prompt exceeds 200KB")
        if self.mode not in {"read-only", "workspace-write"}:
            raise ValueError("unsupported permission mode")
        if not Path(self.cwd).is_absolute() or not Path(self.cwd).is_dir():
            raise ValueError("cwd must be an existing absolute directory")
        bounded(self.timeout, .05, 7200, "timeout")
        if type(self.max_output_bytes) is not int:
            raise ValueError("output limit must be an integer")
        bounded(self.max_output_bytes, 1024, 32_000_000, "max_output_bytes")
        if self.max_turns is not None:
            if type(self.max_turns) is not int:
                raise ValueError("turn limit must be an integer or None")
            bounded(self.max_turns, 1, 100, "max_turns")


@dataclass(frozen=True)
class Receipt:
    # Native completion is NOT a verifier PASS. UNKNOWN retains its reservation.
    status: str
    session_id: str | None = None
    turn_id: str | None = None
    exit_code: int | None = None
    output: str = ""
    usage: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    # Appended to preserve the existing positional receipt constructor.
    requested_model: str | None = None
    # Native execution telemetry only; configuration echoes are not attestation.
    # None also covers multiple reported execution models, not just missing data.
    actual_model: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


SAFE_ENV = frozenset({"PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL",
                      "LC_CTYPE", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "WINDIR", "PATHEXT"})
PROVIDER_ENV = frozenset({"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_HOME", "CLAUDE_CONFIG_DIR"})


def environment(extra_names: tuple[str, ...] = ()) -> dict[str, str]:
    if set(extra_names) - PROVIDER_ENV:
        raise ValueError("unsupported environment forwarding; use an operator-owned launcher")
    return {key: value for key, value in os.environ.items() if key in SAFE_ENV | set(extra_names)}


def redact(value: Any) -> Any:
    """Defense in depth, not a complete DLP system. Raw stderr is never persisted."""
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if re.search(r"api.?key|authorization|password|secret|token$", str(k), re.I)
                else redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        for key in PROVIDER_ENV:
            secret = os.environ.get(key, "")
            if "KEY" in key and len(secret) >= 8:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}", "[REDACTED]", value)
        value = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~-]+", "Bearer [REDACTED]", value)
        return value
    return value
