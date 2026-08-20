from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .models import ContinuationState


class AutonomyStoreError(RuntimeError):
    """Base class for durable autonomy-store failures."""


class ConcurrentUpdate(AutonomyStoreError):
    """A caller attempted to mutate state derived from a stale snapshot."""


class LeaseLost(AutonomyStoreError):
    """The caller no longer owns the continuation lease."""


class InvalidTransition(AutonomyStoreError):
    """The requested continuation transition violates the state machine."""


_ALLOWED_TRANSITIONS: dict[ContinuationState, set[ContinuationState]] = {
    ContinuationState.READY: {ContinuationState.RUNNING, ContinuationState.BLOCKED, ContinuationState.CANCELLED},
    ContinuationState.RUNNING: {
        ContinuationState.READY, ContinuationState.WAITING, ContinuationState.VERIFYING,
        ContinuationState.SUCCEEDED, ContinuationState.FAILED, ContinuationState.BLOCKED,
        ContinuationState.CANCELLED,
    },
    ContinuationState.VERIFYING: {
        ContinuationState.READY, ContinuationState.WAITING, ContinuationState.SUCCEEDED,
        ContinuationState.FAILED, ContinuationState.BLOCKED, ContinuationState.CANCELLED,
    },
    ContinuationState.WAITING: {ContinuationState.RUNNING, ContinuationState.BLOCKED, ContinuationState.CANCELLED},
    ContinuationState.SUCCEEDED: set(),
    ContinuationState.FAILED: {ContinuationState.READY},
    ContinuationState.BLOCKED: {ContinuationState.READY, ContinuationState.CANCELLED},
    ContinuationState.CANCELLED: set(),
}


def _parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_ts(value: str) -> str:
    return _parse_ts(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _add_seconds(value: str, seconds: int) -> str:
    return (_parse_ts(value) + timedelta(seconds=max(1, int(seconds)))).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")


def _decode_json(value: str | None, default: Any) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value)
