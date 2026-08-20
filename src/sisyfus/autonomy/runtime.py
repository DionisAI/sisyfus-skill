from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from .models import (
    AssuranceLevel,
    CapabilityResult,
    ContinuationState,
    Decision,
    DecisionKind,
    ExperienceLesson,
    ExperiencePolarity,
    TickResult,
    VerificationMode,
    VerificationResult,
    Verdict,
    stable_id,
)
from .policy import (
    AttemptBudgetExceeded,
    AutonomyError,
    AutonomyPolicy,
    CapabilityRegistry,
    ConcurrentUpdate,
    IdempotencyConflictError,
    LeaseLost,
    Planner,
    PolicyDeniedError,
    UnknownCommitError,
    VerificationRequiredError,
)
from .store import AutonomyStore


@dataclass
class LeaseHeartbeat:
    store: AutonomyStore
    continuation_id: str
    worker_id: str
    lease_token: str
    lease_seconds: float
    interval_seconds: float | None = None
    initial_now: str | None = None

    def __post_init__(self) -> None:
        interval = self.interval_seconds
        if interval is None:
            interval = max(0.02, min(5.0, float(self.lease_seconds) / 6.0))
        self.interval_seconds = float(interval)
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._error: BaseException | None = None
        self._thread: threading.Thread | None = None
        self._renew_lock = threading.Lock()
        self._started_monotonic = time.monotonic()

    def __enter__(self) -> "LeaseHeartbeat":
        self.refresh()
        self._thread = threading.Thread(
            target=self._run,
            name=f"sisyfus-heartbeat-{self.continuation_id[:12]}",
            daemon=True,
        )
        self._thread.start()
        return self

    def _now(self) -> str | None:
        if self.initial_now is None:
            return None
        base = datetime.fromisoformat(self.initial_now.replace("Z", "+00:00"))
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        elapsed = max(0.0, time.monotonic() - self._started_monotonic)
        return (
            base.astimezone(timezone.utc) + timedelta(seconds=elapsed)
        ).isoformat(timespec="microseconds").replace("+00:00", "Z")

    def refresh(self) -> None:
        self.check()
        try:
            with self._renew_lock:
                self.store.renew_lease(
                    self.continuation_id,
                    worker_id=self.worker_id,
                    lease_token=self.lease_token,
                    lease_seconds=self.lease_seconds,
                    now=self._now(),
                    record_event=False,
                )
        except BaseException as exc:
            self._error = exc
            self._lost.set()
            raise LeaseLost(
                f"lease renewal failed for {self.continuation_id}: {exc}"
            ) from exc

    def _run(self) -> None:
        assert self.interval_seconds is not None
        while not self._stop.wait(self.interval_seconds):
            try:
                self.refresh()
            except LeaseLost:
                return

    def check(self) -> None:
        if self._lost.is_set():
            raise LeaseLost(
                f"lease heartbeat failed for {self.continuation_id}: {self._error}"
            ) from self._error

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, (self.interval_seconds or 0.1) * 2.0))
        if _type is None:
            self.check()


class AutonomousRuntime:
    """Single canonical verifier-gated continuation runtime."""

    def __init__(
        self,
        store: AutonomyStore,
        registry: CapabilityRegistry,
        *,
        workspace: str | Path,
        policy: AutonomyPolicy | None = None,
        retry_base_seconds: float = 5.0,
        retry_max_seconds: float = 300.0,
    ) -> None:
        self.store = store
        self.registry = registry
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.policy = policy or AutonomyPolicy()
        self.retry_base_seconds = max(0.0, float(retry_base_seconds))
        self.retry_max_seconds = max(self.retry_base_seconds, float(retry_max_seconds))

    def planner_context(self, continuation: Mapping[str, Any]) -> dict[str, Any]:
        continuation_id = str(continuation["id"])
        return {
            "continuation": dict(continuation),
            "latest_evidence": self.store.latest_evidence(continuation_id),
            "pending_decision": self.store.pending_decision(continuation_id),
            "validated_experiences": self.store.list_experiences(status="validated")[:50],
            "capabilities": [
                {
                    "name": binding.capability.name,
                    "risk_tier": int(binding.capability.risk_tier),
                    "description": str(binding.capability.description),
                    "replay_safe": bool(binding.capability.replay_safe),
                    "verifier_id": str(binding.verifier.verifier_id),
                }
                for binding in self.registry.list()
                if int(binding.capability.risk_tier) <= int(self.policy.max_unattended_risk)
            ],
            "rules": [
                "FINISH requires persisted PASS evidence from this continuation.",
                "Planner confidence is not evidence.",
                "A persisted pending decision is resumed before asking the planner again.",
                "Prefer WAIT over inventing observations.",
            ],
        }

    def run_once(
        self,
        *,
        worker_id: str,
        planner: Planner,
        lease_seconds: float = 60.0,
        now: str | None = None,
    ) -> TickResult | None:
        self.store.recover_expired_leases(
            now=now,
            retry_delay_seconds=self.retry_base_seconds,
        )
        continuation = self.store.claim_due_continuation(
            worker_id,
            lease_seconds=lease_seconds,
            now=now,
        )
        if continuation is None:
            return None
        continuation_id = str(continuation["id"])
        heartbeat = LeaseHeartbeat(
            self.store,
            continuation_id,
            worker_id,
            str(continuation["lease_token"]),
            lease_seconds,
            initial_now=now,
        )
        try:
            with heartbeat:
                pending = self.store.pending_decision(continuation_id)
                if pending is not None:
                    return self._resume_pending(
                        continuation,
                        pending,
                        worker_id=worker_id,
                        heartbeat=heartbeat,
                        now=now,
                    )

                if int(continuation["attempt_count"]) >= int(continuation["max_attempts"]):
                    latest = self.store.latest_evidence(continuation_id)
                    if latest is None or latest.get("verdict") != Verdict.PASS.value:
                        current = self._current_owned(continuation_id, worker_id)
                        exhausted = self.store.mark_exhausted(
                            continuation_id,
                            worker_id=worker_id,
                            lease_token=str(current["lease_token"]),
                            expected_version=int(current["version"]),
                            reason="execution budget exhausted without PASS evidence",
                            now=now,
                        )
                        return TickResult(
                            continuation_id,
                            exhausted["state"],
                            {"reason": exhausted["last_error"]},
                        )

                decision = planner(continuation, self.planner_context(continuation))
                if not isinstance(decision, Decision):
                    raise TypeError(
                        f"planner returned {type(decision).__name__}, expected Decision"
                    )
                heartbeat.check()
                return self.apply_decision(
                    continuation,
                    decision,
                    worker_id=worker_id,
                    heartbeat=heartbeat,
                    now=now,
                )
        except (
            PolicyDeniedError,
            IdempotencyConflictError,
            UnknownCommitError,
            VerificationRequiredError,
        ) as exc:
            return self._block_after_error(continuation_id, worker_id, exc, now=now)
        except AttemptBudgetExceeded as exc:
            return self._exhaust_after_error(continuation_id, worker_id, exc, now=now)
        except (LeaseLost, ConcurrentUpdate) as exc:
            current = self.store.get_continuation(continuation_id)
            return TickResult(
                continuation_id,
                str(current["state"]),
                {"status": "LOST_RACE", "error": f"{type(exc).__name__}: {exc}"},
            )
        except BaseException as exc:
            return self._wait_after_internal_error(continuation_id, worker_id, exc, now=now)

    def _current_owned(self, continuation_id: str, worker_id: str) -> dict[str, Any]:
        current = self.store.get_continuation(continuation_id)
        if current.get("lease_owner") != worker_id or not current.get("lease_token"):
            raise LeaseLost(f"worker {worker_id!r} no longer owns {continuation_id}")
        return current

    def _resume_pending(
        self,
        continuation: Mapping[str, Any],
        pending: Mapping[str, Any],
        *,
        worker_id: str,
        heartbeat: LeaseHeartbeat,
        now: str | None,
    ) -> TickResult:
        decision = Decision.from_dict(dict(pending.get("payload") or {}))
        binding = self.registry.get(decision.capability)
        status = str(pending["status"])
        if status in {"RESERVED", "EXECUTING"}:
            if bool(pending.get("recovery_required")) and not bool(
                binding.capability.replay_safe
            ):
                raise UnknownCommitError(
                    f"decision {pending['id']} may have committed externally; "
                    f"capability {binding.capability.name} is not replay-safe"
                )
            return self._execute_pending(
                continuation,
                pending,
                decision,
                binding=binding,
                worker_id=worker_id,
                heartbeat=heartbeat,
                now=now,
                mark_started=status == "RESERVED",
            )
        if status == "EXECUTED":
            result = CapabilityResult.from_dict(dict(pending.get("result") or {}))
            return self._verify_pending(
                continuation,
                pending,
                decision,
                result,
                binding=binding,
                worker_id=worker_id,
                heartbeat=heartbeat,
                now=now,
            )
        raise AutonomyError(f"unsupported pending decision status: {status}")

    def apply_decision(
        self,
        continuation: Mapping[str, Any],
        decision: Decision,
        *,
        worker_id: str,
        heartbeat: LeaseHeartbeat,
        now: str | None = None,
    ) -> TickResult:
        item = decision.normalized()
        continuation_id = str(continuation["id"])
        if item.kind != DecisionKind.EXECUTE:
            heartbeat.check()
            current = self._current_owned(continuation_id, worker_id)
            updated = self.store.apply_non_execution_decision(
                continuation_id,
                worker_id=worker_id,
                lease_token=str(current["lease_token"]),
                expected_version=int(current["version"]),
                decision=item,
                now=now,
            )
            return TickResult(
                continuation_id,
                str(updated["state"]),
                {"decision": item.as_dict()},
            )

        binding = self.registry.get(item.capability)
        authorization = self.policy.authorize(item, binding.capability)
        if not authorization.allowed:
            raise PolicyDeniedError(authorization.reason)
        current = self._current_owned(continuation_id, worker_id)
        record, running, created = self.store.reserve_decision(
            continuation_id,
            worker_id=worker_id,
            lease_token=str(current["lease_token"]),
            expected_version=int(current["version"]),
            decision=item,
            now=now,
        )
        if not created and record["status"] == "VERIFIED":
            evidence = self.store.latest_evidence(continuation_id)
            return TickResult(
                continuation_id,
                str(running["state"]),
                {
                    "cached": True,
                    "decision_id": record["id"],
                    "evidence_id": evidence["id"] if evidence else None,
                },
            )
        return self._execute_pending(
            running,
            record,
            item,
            binding=binding,
            worker_id=worker_id,
            heartbeat=heartbeat,
            now=now,
            mark_started=record["status"] == "RESERVED",
        )

    def _execute_pending(
        self,
        continuation: Mapping[str, Any],
        record: Mapping[str, Any],
        decision: Decision,
        *,
        binding: Any,
        worker_id: str,
        heartbeat: LeaseHeartbeat,
        now: str | None,
        mark_started: bool,
    ) -> TickResult:
        current = dict(continuation)
        if mark_started:
            _, current = self.store.mark_execution_started(
                str(record["id"]),
                worker_id=worker_id,
                lease_token=str(current["lease_token"]),
                expected_version=int(current["version"]),
                now=now,
            )
        heartbeat.refresh()
        try:
            result = binding.capability.execute(
                dict(decision.arguments),
                idempotency_key=str(decision.idempotency_key or record["idempotency_key"]),
            )
            if not isinstance(result, CapabilityResult):
                raise TypeError(
                    f"capability {binding.capability.name!r} returned "
                    f"{type(result).__name__}, expected CapabilityResult"
                )
            result = result.normalized()
        except BaseException as exc:
            result = CapabilityResult(
                status="ERROR",
                observation={"exception_type": type(exc).__name__},
                error=str(exc),
            )
        heartbeat.refresh()
        current = self._current_owned(str(current["id"]), worker_id)
        _, verifying = self.store.record_execution(
            str(record["id"]),
            worker_id=worker_id,
            lease_token=str(current["lease_token"]),
            expected_version=int(current["version"]),
            result=result.as_dict(),
            now=now,
        )
        return self._verify_pending(
            verifying,
            record,
            decision,
            result,
            binding=binding,
            worker_id=worker_id,
            heartbeat=heartbeat,
            now=now,
        )

    def _verify_pending(
        self,
        continuation: Mapping[str, Any],
        record: Mapping[str, Any],
        decision: Decision,
        result: CapabilityResult,
        *,
        binding: Any,
        worker_id: str,
        heartbeat: LeaseHeartbeat,
        now: str | None,
    ) -> TickResult:
        heartbeat.refresh()
        try:
            verification = binding.verifier.verify(
                self.planner_context(continuation),
                decision,
                result,
            )
            if not isinstance(verification, VerificationResult):
                raise TypeError(
                    f"verifier returned {type(verification).__name__}, expected VerificationResult"
                )
            verification = verification.normalized()
        except BaseException as exc:
            verification = VerificationResult(
                verdict=Verdict.ERROR,
                verifier_id=f"engine.verifier-boundary:{binding.verifier.verifier_id}",
                summary=f"verifier raised {type(exc).__name__}: {exc}",
                metrics={"exception_type": type(exc).__name__},
                assurance=AssuranceLevel.U,
                verification_mode=VerificationMode.ENGINE,
            )
        heartbeat.refresh()
        current = self._current_owned(str(continuation["id"]), worker_id)
        return self._settle(
            current,
            str(record["id"]),
            decision,
            verification,
            worker_id=worker_id,
            now=now,
        )

    def _settle(
        self,
        continuation: Mapping[str, Any],
        decision_id: str,
        decision: Decision,
        verification: VerificationResult,
        *,
        worker_id: str,
        now: str | None,
    ) -> TickResult:
        attempts = int(continuation["attempt_count"])
        maximum = int(continuation["max_attempts"])
        exhausted = attempts >= maximum
        next_wake: str | None = None
        last_error: str | None = None
        if verification.verdict == Verdict.PASS:
            state = (
                ContinuationState.SUCCEEDED
                if decision.terminal_on_pass
                else ContinuationState.READY
            )
        elif verification.verdict == Verdict.FAIL:
            state = ContinuationState.FAILED if exhausted else ContinuationState.READY
            last_error = verification.summary
        elif verification.verdict in {Verdict.INCONCLUSIVE, Verdict.INVALID}:
            state = ContinuationState.EXHAUSTED if exhausted else ContinuationState.WAITING
            next_wake = None if exhausted else self._retry_at(attempts, now=now)
            last_error = verification.summary
        else:
            state = ContinuationState.FAILED if exhausted else ContinuationState.WAITING
            next_wake = None if exhausted else self._retry_at(attempts, now=now)
            last_error = verification.summary

        lessons: list[ExperienceLesson] = []
        if decision.experience_key:
            if verification.verdict == Verdict.PASS:
                polarity = ExperiencePolarity.POSITIVE
            elif verification.verdict == Verdict.FAIL:
                polarity = ExperiencePolarity.NEGATIVE
            else:
                polarity = ExperiencePolarity.OPERATIONAL
            lessons.append(
                ExperienceLesson(
                    pattern_key=decision.experience_key,
                    polarity=polarity,
                    claim=verification.summary,
                    scope=dict(decision.experience_scope),
                    confidence=(
                        0.75
                        if verification.verdict in {Verdict.PASS, Verdict.FAIL}
                        else 0.4
                    ),
                    outcome="support",
                )
            )
        evidence, updated = self.store.record_verdict(
            decision_id,
            worker_id=worker_id,
            lease_token=str(continuation["lease_token"]),
            expected_version=int(continuation["version"]),
            verification=verification,
            to_state=state,
            next_wake_at=next_wake,
            last_error=last_error,
            experiences=lessons,
            now=now,
        )
        return TickResult(
            str(continuation["id"]),
            str(updated["state"]),
            {
                "decision_id": decision_id,
                "evidence_id": evidence["id"],
                "verdict": verification.verdict.value,
                "summary": verification.summary,
                "next_wake_at": next_wake,
            },
        )

    def _retry_at(self, attempt_count: int, *, now: str | None = None) -> str:
        seconds = min(
            self.retry_max_seconds,
            self.retry_base_seconds * (2 ** max(0, int(attempt_count) - 1)),
        )
        base = (
            datetime.fromisoformat(str(now).replace("Z", "+00:00"))
            if now
            else datetime.now(timezone.utc)
        )
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        return (base.astimezone(timezone.utc) + timedelta(seconds=seconds)).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")

    def _block_after_error(
        self,
        continuation_id: str,
        worker_id: str,
        exc: BaseException,
        *,
        now: str | None,
    ) -> TickResult:
        try:
            current = self._current_owned(continuation_id, worker_id)
            updated = self.store.block_owned_continuation(
                continuation_id,
                worker_id=worker_id,
                lease_token=str(current["lease_token"]),
                expected_version=int(current["version"]),
                reason=f"{type(exc).__name__}: {exc}",
                now=now,
            )
            state = str(updated["state"])
        except AutonomyError:
            state = str(self.store.get_continuation(continuation_id)["state"])
        return TickResult(
            continuation_id,
            state,
            {"error": str(exc), "exception_type": type(exc).__name__},
        )

    def _exhaust_after_error(
        self,
        continuation_id: str,
        worker_id: str,
        exc: BaseException,
        *,
        now: str | None,
    ) -> TickResult:
        try:
            current = self._current_owned(continuation_id, worker_id)
            updated = self.store.mark_exhausted(
                continuation_id,
                worker_id=worker_id,
                lease_token=str(current["lease_token"]),
                expected_version=int(current["version"]),
                reason=str(exc),
                now=now,
            )
            state = str(updated["state"])
        except AutonomyError:
            state = str(self.store.get_continuation(continuation_id)["state"])
        return TickResult(
            continuation_id,
            state,
            {"error": str(exc), "exception_type": type(exc).__name__},
        )

    def _wait_after_internal_error(
        self,
        continuation_id: str,
        worker_id: str,
        exc: BaseException,
        *,
        now: str | None,
    ) -> TickResult:
        try:
            current = self._current_owned(continuation_id, worker_id)
            updated = self.store.apply_non_execution_decision(
                continuation_id,
                worker_id=worker_id,
                lease_token=str(current["lease_token"]),
                expected_version=int(current["version"]),
                decision=Decision(
                    kind=DecisionKind.WAIT,
                    reason=f"internal_error:{type(exc).__name__}:{exc}",
                    wait_seconds=self.retry_base_seconds,
                ),
                now=now,
            )
            state = str(updated["state"])
        except AutonomyError as recovery_exc:
            current = self.store.get_continuation(continuation_id)
            return TickResult(
                continuation_id,
                str(current["state"]),
                {
                    "error": str(exc),
                    "exception_type": type(exc).__name__,
                    "recovery_error": str(recovery_exc),
                },
            )
        return TickResult(
            continuation_id,
            state,
            {"error": str(exc), "exception_type": type(exc).__name__},
        )


@dataclass
class EchoCapability:
    name: str = "core.echo"
    risk_tier: int = 0
    replay_safe: bool = True
    description: str = "Pure deterministic echo used for runtime checks."

    def execute(
        self, arguments: Mapping[str, Any], *, idempotency_key: str
    ) -> CapabilityResult:
        return CapabilityResult(
            status="OK",
            observation={"idempotency_key": idempotency_key},
            metrics={"value": arguments.get("value")},
        )


@dataclass
class EchoVerifier:
    verifier_id: str = "builtin.echo.readback"

    def verify(
        self,
        _context: Mapping[str, Any],
        decision: Decision,
        result: CapabilityResult,
    ) -> VerificationResult:
        matched = result.metrics.get("value") == decision.arguments.get("value")
        return VerificationResult(
            verdict=Verdict.PASS if matched else Verdict.FAIL,
            verifier_id=self.verifier_id,
            summary="echo matched input" if matched else "echo differed from input",
            metrics={"matched": matched},
            assurance=AssuranceLevel.A,
            verification_mode=VerificationMode.PROGRAMMATIC,
        )


@dataclass
class WorkspaceWriteCapability:
    workspace: Path
    name: str = "workspace.write_text"
    risk_tier: int = 1
    replay_safe: bool = True
    description: str = "Atomically write one UTF-8 artifact inside the workspace."

    def _target(self, relative_path: str) -> Path:
        target = (self.workspace / relative_path).resolve()
        try:
            target.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("artifact path escapes workspace") from exc
        return target

    def execute(
        self, arguments: Mapping[str, Any], *, idempotency_key: str
    ) -> CapabilityResult:
        relative_path = str(arguments.get("path") or "").strip()
        if not relative_path:
            raise ValueError("path is required")
        content = str(arguments.get("content") or "")
        target = self._target(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=target.name + ".", suffix=".tmp", dir=str(target.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return CapabilityResult(
            status="OK",
            observation={
                "relative_path": str(target.relative_to(self.workspace)),
                "idempotency_key": idempotency_key,
            },
            metrics={"sha256": digest, "bytes": len(content.encode("utf-8"))},
            artifacts=({"path": str(target.relative_to(self.workspace)), "sha256": digest},),
        )


@dataclass
class WorkspaceWriteVerifier:
    workspace: Path
    verifier_id: str = "builtin.workspace.exact-readback"

    def verify(
        self,
        _context: Mapping[str, Any],
        decision: Decision,
        result: CapabilityResult,
    ) -> VerificationResult:
        relative_path = str(result.observation.get("relative_path") or "")
        target = (self.workspace / relative_path).resolve()
        try:
            target.relative_to(self.workspace)
        except ValueError:
            return VerificationResult(
                verdict=Verdict.FAIL,
                verifier_id=self.verifier_id,
                summary="reported artifact escaped workspace",
                assurance=AssuranceLevel.A,
                verification_mode=VerificationMode.PROGRAMMATIC,
            )
        expected = str(decision.arguments.get("content") or "")
        exists = target.is_file()
        actual = target.read_text(encoding="utf-8") if exists else None
        passed = exists and actual == expected
        return VerificationResult(
            verdict=Verdict.PASS if passed else Verdict.FAIL,
            verifier_id=self.verifier_id,
            summary=(
                "artifact exists with exact requested content"
                if passed
                else "artifact read-back verification failed"
            ),
            metrics={
                "exists": exists,
                "bytes": len(actual.encode("utf-8")) if actual is not None else 0,
            },
            evidence={"relative_path": relative_path},
            assurance=AssuranceLevel.A,
            verification_mode=VerificationMode.PROGRAMMATIC,
        )


def register_safe_builtins(registry: CapabilityRegistry, *, workspace: str | Path) -> None:
    root = Path(workspace).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    registry.register(EchoCapability(), EchoVerifier())
    registry.register(WorkspaceWriteCapability(root), WorkspaceWriteVerifier(root))
