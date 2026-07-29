from __future__ import annotations

import json
import os
import re
import webbrowser
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from ..utils import run_process
from .models import (
    normalize_contract,
    normalize_experiment,
    normalize_lesson,
    safe_id,
)
from .reducer import (
    FRAMES_SCHEMA_VERSION,
    planner_context,
    projection_bundle,
    reduce_research,
    replay_frames,
)
from .verifier import classify_observation
from .workspace import ResearchWorkspace, add_minutes, atomic_write_json, canonical_ts, utc_now


_TOKEN_RE = re.compile(r"[a-z0-9一-鿿]{2,}")


def _relevance_tokens(value: Any) -> set[str]:
    """Flatten arbitrary strings/lists/dicts into a lowercase token set."""
    tokens: set[str] = set()
    stack = [value]
    while stack:
        item = stack.pop()
        if item is None:
            continue
        if isinstance(item, str):
            tokens.update(_TOKEN_RE.findall(item.lower()))
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, (list, tuple, set)):
            stack.extend(item)
        else:
            stack.append(str(item))
    return tokens


def _lesson_relevance(lesson: dict[str, Any], task_tokens: set[str]) -> int:
    lesson_tokens = _relevance_tokens(
        [
            lesson.get("scope"),
            lesson.get("preconditions"),
            lesson.get("topic"),
            lesson.get("observation"),
            lesson.get("recommendation"),
        ]
    )
    return len(lesson_tokens & task_tokens)


class ResearchEngine:
    """Event-sourced research control plane.

    The engine owns durable state transitions. Planners and workers may propose
    experiments and produce observations, but only this engine can admit an
    experiment, issue a verifier verdict, or commit a new research state.
    """

    def __init__(self, workspace: ResearchWorkspace):
        self.workspace = workspace

    @classmethod
    def create(
        cls,
        root: str | Path | None,
        spec: dict[str, Any],
        *,
        actor: str = "user",
        render: bool = True,
    ) -> "ResearchEngine":
        engine = cls(ResearchWorkspace.create(root, spec, actor=actor))
        engine.sync(render=render)
        return engine

    @classmethod
    def load(cls, root: str | Path | None, research_id: str = "latest") -> "ResearchEngine":
        return cls(ResearchWorkspace.load(root, research_id))

    @property
    def task(self) -> dict[str, Any]:
        return self.workspace.read_task()

    @property
    def events(self) -> list[dict[str, Any]]:
        return self.workspace.read_events(verify_chain=True)

    def snapshot(self, *, persist: bool = False, render: bool = False) -> dict[str, Any]:
        snapshot = reduce_research(self.task, self.events)
        if persist or render:
            self._persist(snapshot, render=render)
        return snapshot

    def sync(self, *, render: bool = True) -> dict[str, Any]:
        snapshot = reduce_research(self.task, self.events)
        self._persist(snapshot, render=render)
        return snapshot

    def refresh_wall_budget(
        self,
        *,
        now: str | None = None,
        actor: str = "budget-manager",
        render: bool = False,
    ) -> dict[str, Any]:
        """Commit wall-clock exhaustion at a deterministic event boundary.

        Pure replay measures time between recorded events. This preflight compares
        the run creation time with the supplied/current time and records a terminal
        event before any new Experiment or Attempt can start after the deadline.
        """
        snapshot = self.snapshot()
        if snapshot["run_status"] != "ACTIVE":
            if render:
                self._persist(snapshot, render=True)
            return snapshot
        created_at = snapshot.get("created_at")
        if not created_at:
            if render:
                self._persist(snapshot, render=True)
            return snapshot
        try:
            created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            current = datetime.fromisoformat(str(now or utc_now()).replace("Z", "+00:00"))
        except ValueError:
            if render:
                self._persist(snapshot, render=True)
            return snapshot
        raw_limit = snapshot["budget"]["max_wall_minutes"]
        if raw_limit is None:
            if render:
                self._persist(snapshot, render=True)
            return snapshot
        elapsed_minutes = max(0.0, (current - created).total_seconds() / 60.0)
        limit = float(raw_limit)
        if elapsed_minutes < limit:
            if render:
                self._persist(snapshot, render=True)
            return snapshot
        self.workspace.append_event(
            "RUN_FINALIZED",
            actor=actor,
            data={
                "status": "BUDGET_EXHAUSTED",
                "reason": "wall_clock_budget_exhausted",
                "elapsed_minutes": round(elapsed_minutes, 6),
                "max_wall_minutes": limit,
                "goal_root_status": snapshot["goal_evaluation"]["root_status"],
            },
        )
        return self.sync(render=render)

    def _persist(self, snapshot: dict[str, Any], *, render: bool) -> None:
        bundle = projection_bundle(snapshot)
        for name, data in bundle.items():
            self.workspace.write_projection(name, data)
        self.workspace.update_index(snapshot)
        if render:
            from .observatory import render_observatory

            events = self.events
            render_observatory(self.workspace, snapshot, events=events, frames=self._replay_frames(events))

    def _replay_frames(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Visual-replay keyframes, extended incrementally.

        Frame k depends only on events[:k]; the log is append-only and hash-chained,
        so a cached prefix is valid iff its last event hash still matches.
        """
        cache_path = self.workspace.report_frames_path
        cached: dict[str, Any] = {}
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                cached = {}
        frames = list(cached.get("frames") or [])
        if (
            cached.get("schema_version") != FRAMES_SCHEMA_VERSION
            or len(frames) > len(events)
            or (frames and events[len(frames) - 1].get("event_hash") != cached.get("last_event_hash"))
        ):
            frames = []
        if len(frames) < len(events):
            frames.extend(replay_frames(self.task, events, start=len(frames)))
            atomic_write_json(
                cache_path,
                {
                    "schema_version": FRAMES_SCHEMA_VERSION,
                    "research_id": self.workspace.research_id,
                    "last_event_hash": events[-1].get("event_hash") if events else None,
                    "frames": frames,
                },
            )
        return frames

    def refresh_waits(
        self,
        *,
        now: str | None = None,
        actor: str = "wake",
        render: bool = False,
    ) -> dict[str, Any]:
        """Settle due time waits and expired deadlines at a deterministic event boundary.

        Like refresh_wall_budget, wall-clock time enters research truth only through
        recorded events: pending time waits whose not_before has passed produce
        WAIT_FIRED, and pending waits whose deadline has passed produce WAIT_EXPIRED.
        Evidence waits never need this preflight; the reducer satisfies them directly
        from later VERDICT_ISSUED events.
        """
        snapshot = self.refresh_wall_budget(now=now)
        if snapshot["run_status"] != "ACTIVE":
            if render:
                self._persist(snapshot, render=True)
            return snapshot
        current = canonical_ts(now or utc_now())
        appended = False
        for wait in snapshot.get("waits") or []:
            if wait.get("status") != "PENDING":
                continue
            experiment = snapshot["experiments"].get(wait["experiment_id"]) or {}
            visibility = experiment.get("visibility", "normal")
            if wait.get("deadline_ts") and current >= wait["deadline_ts"]:
                self.workspace.append_event(
                    "WAIT_EXPIRED",
                    actor=actor,
                    visibility=visibility,
                    data={
                        "experiment_id": wait["experiment_id"],
                        "now": current,
                        "on_expire": wait.get("on_expire") or "backlog",
                    },
                )
                appended = True
            elif wait.get("kind") == "time" and wait.get("not_before_ts") and current >= wait["not_before_ts"]:
                self.workspace.append_event(
                    "WAIT_FIRED",
                    actor=actor,
                    visibility=visibility,
                    data={"experiment_id": wait["experiment_id"], "now": current},
                )
                appended = True
        if appended:
            return self.sync(render=render)
        if render:
            self._persist(snapshot, render=True)
        return snapshot

    def planner_context(self) -> dict[str, Any]:
        snapshot = self.refresh_waits()
        context = planner_context(snapshot, recent_events=self.events)
        context["global_lessons"] = self.global_lessons(with_efficacy=True)
        return context

    def add_contract(self, raw_contract: dict[str, Any], *, actor: str = "user") -> dict[str, Any]:
        snapshot = self.refresh_wall_budget()
        if snapshot["run_status"] != "ACTIVE":
            raise RuntimeError(f"research run does not accept new contracts in status {snapshot['run_status']}")
        contract = normalize_contract(raw_contract, known_claim_ids=set(snapshot["claims"]))
        if contract["id"] in snapshot["contracts"]:
            raise ValueError(f"verification contract already exists: {contract['id']}")
        self.workspace.append_event("CONTRACT_ADDED", actor=actor, data={"contract": contract})
        self.sync()
        return contract

    def propose_experiment(
        self,
        raw_experiment: dict[str, Any],
        *,
        actor: str = "planner",
        auto_admit: bool = True,
    ) -> dict[str, Any]:
        snapshot = self.refresh_waits()
        if snapshot["run_status"] in {"PAUSED", "FAILED", "SOLVED", "REFUTED", "BUDGET_EXHAUSTED", "EXHAUSTED"}:
            raise RuntimeError(f"research run does not accept new experiments in status {snapshot['run_status']}")
        experiment = normalize_experiment(
            raw_experiment,
            known_claim_ids=set(snapshot["claims"]),
            known_contract_ids=set(snapshot["contracts"]),
            current_state_id=snapshot["current_state_id"],
        )
        if experiment["id"] in snapshot["experiments"]:
            raise ValueError(f"experiment id already exists: {experiment['id']}")
        if experiment["from_state_id"] not in snapshot["states"]:
            raise ValueError(f"experiment starts from unknown state: {experiment['from_state_id']}")
        self._resolve_wait(experiment, snapshot)

        self.workspace.append_event(
            "EXPERIMENT_PROPOSED",
            actor=actor,
            visibility=experiment["visibility"],
            data={"experiment": experiment},
        )

        admission = self._admission_decision(experiment, snapshot)
        if auto_admit and admission["accepted"]:
            self.workspace.append_event(
                "EXPERIMENT_ADMITTED",
                actor="admission-controller",
                visibility=experiment["visibility"],
                data={"experiment_id": experiment["id"], "admission": admission},
            )
        elif auto_admit:
            self.workspace.append_event(
                "EXPERIMENT_BACKLOGGED",
                actor="admission-controller",
                visibility=experiment["visibility"],
                data={"experiment_id": experiment["id"], "reason": admission["reason"], "admission": admission},
            )
        self.sync()
        return {"experiment": experiment, "admission": admission}

    def _admission_decision(self, experiment: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        contract_id = experiment.get("contract_id")
        if not contract_id:
            return {
                "accepted": False,
                "reason": "missing_verification_contract",
                "checks": {"contract_bound": False},
            }
        contract = snapshot["contracts"].get(contract_id)
        if not contract:
            return {
                "accepted": False,
                "reason": "unknown_verification_contract",
                "checks": {"contract_bound": False},
            }
        if contract.get("kind") == "manual" and not self.task["stop_policy"].get("allow_manual_verdict", False):
            return {
                "accepted": False,
                "reason": "manual_verdict_not_allowed",
                "checks": {"contract_bound": True, "allow_manual_verdict": False},
            }
        if (
            contract.get("visibility") == "host_only"
            or experiment.get("mode") == "hidden_eval"
        ) and experiment.get("visibility") != "host_only":
            return {
                "accepted": False,
                "reason": "hidden_visibility_downgrade",
                "checks": {
                    "contract_visibility": contract.get("visibility"),
                    "experiment_mode": experiment.get("mode"),
                    "experiment_visibility": experiment.get("visibility"),
                },
            }
        action_family = str(experiment.get("action_family") or "")
        allowed_action_space = set(self.task.get("action_space") or [])
        if action_family not in allowed_action_space:
            return {
                "accepted": False,
                "reason": "action_family_not_allowed",
                "checks": {
                    "action_family": action_family,
                    "allowed_action_space": sorted(allowed_action_space),
                },
            }
        target_claims = list(experiment.get("target_claim_ids") or [])
        if target_claims != [contract["target_claim_id"]]:
            return {
                "accepted": False,
                "reason": "contract_target_mismatch",
                "checks": {
                    "contract_bound": True,
                    "experiment_targets": target_claims,
                    "contract_target": contract["target_claim_id"],
                },
            }
        from_state = snapshot["states"].get(experiment.get("from_state_id")) or {}
        target_claim = snapshot["claims"].get(contract["target_claim_id"]) or {}
        allow_provisional = bool(self.task["stop_policy"].get("allow_provisional_prereq", False))
        unsatisfied_dependencies = []
        for dependency in target_claim.get("depends_on") or []:
            dep_status = (from_state.get("claim_statuses") or {}).get(dependency)
            if dep_status == "SUPPORTED":
                continue
            if (
                allow_provisional
                and dep_status == "INCONCLUSIVE"
                and int((snapshot["claims"].get(dependency) or {}).get("provisional_passes") or 0) >= 1
            ):
                continue
            unsatisfied_dependencies.append(dependency)
        if unsatisfied_dependencies:
            return {
                "accepted": False,
                "reason": "claim_dependencies_not_supported",
                "checks": {
                    "from_state_id": experiment.get("from_state_id"),
                    "unsatisfied_dependencies": unsatisfied_dependencies,
                },
            }
        duplicates = [
            item["id"]
            for item in snapshot["experiments"].values()
            if item.get("dedupe_key") == experiment.get("dedupe_key")
            and item.get("status") not in {"PRUNED"}
        ]
        if duplicates:
            return {
                "accepted": False,
                "reason": "duplicate_experiment",
                "checks": {"duplicate_ids": duplicates},
            }
        based_on = experiment.get("based_on") or {"evidence_ids": [], "lesson_ids": []}
        unknown_evidence = [x for x in based_on.get("evidence_ids") or [] if x not in snapshot["evidence"]]
        known_lesson_ids = set(snapshot["lessons"]) | self._global_lesson_ids()
        unknown_lessons = [x for x in based_on.get("lesson_ids") or [] if x not in known_lesson_ids]
        if unknown_evidence or unknown_lessons:
            # A citation of something outside recorded context is an error, not a policy choice.
            return {
                "accepted": False,
                "reason": "citation_out_of_context",
                "checks": {
                    "unknown_evidence_ids": unknown_evidence,
                    "unknown_lesson_ids": unknown_lessons,
                },
            }
        if self.task["stop_policy"].get("require_citations", False) and not (
            based_on.get("evidence_ids") or based_on.get("lesson_ids")
        ):
            citable = bool(snapshot["evidence"]) or bool(known_lesson_ids)
            if citable:
                return {
                    "accepted": False,
                    "reason": "missing_citations",
                    "checks": {
                        "require_citations": True,
                        "citable_evidence": len(snapshot["evidence"]),
                        "citable_lessons": len(known_lesson_ids),
                    },
                }
        estimated_attempts = int((experiment.get("cost") or {}).get("attempts") or 1)
        estimated_units = float((experiment.get("cost") or {}).get("units") or 0.0)
        attempts_remaining = snapshot["budget"]["attempts_remaining"]
        cost_units_remaining = snapshot["budget"]["cost_units_remaining"]
        if (
            (attempts_remaining is not None and estimated_attempts > attempts_remaining)
            or (cost_units_remaining is not None and estimated_units > cost_units_remaining)
        ):
            return {
                "accepted": False,
                "reason": "budget_exceeded_by_experiment",
                "checks": {
                    "estimated_attempts": estimated_attempts,
                    "estimated_cost_units": estimated_units,
                    "budget": snapshot["budget"],
                },
            }
        return {
            "accepted": True,
            "reason": "admitted",
            "checks": {
                "contract_bound": True,
                "target_matches": True,
                "action_family_allowed": True,
                "dependencies_supported": True,
                "not_duplicate": True,
                "citations_in_context": True,
                "within_budget": True,
                "expected_outcomes_preregistered": True,
            },
            "contract_hash": self._contract_hash(contract),
        }

    @staticmethod
    def _contract_hash(contract: dict[str, Any]) -> str:
        from .models import canonical_hash

        return canonical_hash(contract)

    @staticmethod
    def _resolve_wait(experiment: dict[str, Any], snapshot: dict[str, Any]) -> None:
        """Resolve a wait's relative anchors into absolute canonical timestamps.

        Resolution happens once, at proposal, and the result is recorded inside the
        EXPERIMENT_PROPOSED event so replay never needs a wall clock.
        """
        wait = experiment.get("wait")
        if not wait:
            return
        now = utc_now()
        not_before_ts = None
        if wait["kind"] == "time":
            after = wait.get("after")
            if after:
                evidence = snapshot["evidence"].get(after["evidence_id"])
                if not evidence:
                    raise ValueError(
                        f"experiment {experiment['id']} wait references unknown evidence: {after['evidence_id']}"
                    )
                anchor = str(evidence.get("created_at") or now)
                not_before_ts = add_minutes(anchor, after["minutes"])
            else:
                not_before_ts = canonical_ts(wait["not_before"])
        wait["not_before_ts"] = not_before_ts
        wait["deadline_ts"] = add_minutes(now, wait["deadline_minutes"]) if wait.get("deadline_minutes") else None
        wait["created_ts"] = now

    def _action_code_hashes(self, action: dict[str, Any]) -> dict[str, str]:
        """Hash the measurement code an action references.

        The verification contract preregisters thresholds, but the code that
        produces the metrics is part of the measurement. Every file mentioned
        in the command line (plus explicit action.code_paths) is content-hashed
        into the attempt manifest so an audit can prove which measurement
        procedure produced each verdict.
        """
        import hashlib
        import re

        base_dir = Path(action.get("cwd") or self.workspace.root)
        if not base_dir.is_absolute():
            base_dir = (self.workspace.root / base_dir).resolve()
        candidates: list[str] = [str(p) for p in (action.get("code_paths") or [])]
        for token in re.split(r"[\s;&|<>()]+", str(action.get("command") or "")):
            token = token.strip("'\"")
            if not token or token.startswith("-"):
                continue
            candidates.append(token)
        hashes: dict[str, str] = {}
        for token in dict.fromkeys(candidates):
            path = Path(token)
            if not path.is_absolute():
                path = base_dir / token
            if path.is_file():
                hashes[token] = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
            elif token in (action.get("code_paths") or []):
                hashes[token] = "missing"
        return hashes

    def prune_experiment(self, experiment_id: str, *, reason: str, actor: str = "user") -> dict[str, Any]:
        snapshot = self.snapshot()
        experiment = snapshot["experiments"].get(experiment_id)
        if not experiment:
            raise KeyError(experiment_id)
        if experiment["status"] in {"RUNNING", "RESERVED"}:
            raise RuntimeError("cannot prune a reserved or running experiment")
        self.workspace.append_event(
            "EXPERIMENT_PRUNED",
            actor=actor,
            visibility=experiment.get("visibility", "normal"),
            data={"experiment_id": experiment_id, "reason": reason},
        )
        return self.sync()

    def begin_attempt(self, experiment_id: str, *, actor: str = "executor") -> dict[str, Any]:
        snapshot = self.refresh_waits()
        if snapshot["run_status"] != "ACTIVE":
            raise RuntimeError(f"cannot start attempt while run status is {snapshot['run_status']}")
        experiment = snapshot["experiments"].get(experiment_id)
        if not experiment:
            raise KeyError(f"unknown experiment: {experiment_id}")
        if experiment["status"] == "WAITING":
            wait = experiment.get("wait") or {}
            raise RuntimeError(
                f"experiment {experiment_id} is waiting "
                f"(not_before={wait.get('not_before_ts')}, deadline={wait.get('deadline_ts')}); "
                "run `sisyfus research wake` once the wait is due"
            )
        if experiment["status"] != "ADMITTED":
            raise RuntimeError(f"experiment {experiment_id} is not admitted (status={experiment['status']})")
        attempts_remaining = snapshot["budget"]["attempts_remaining"]
        if attempts_remaining is not None and attempts_remaining <= 0:
            raise RuntimeError("attempt budget exhausted or fully reserved")
        reserved_units = float((experiment.get("cost") or {}).get("units") or 0.0)
        cost_units_remaining = snapshot["budget"]["cost_units_remaining"]
        if cost_units_remaining is not None and reserved_units > cost_units_remaining:
            raise RuntimeError("cost budget exhausted or fully reserved")
        contract_id = experiment.get("contract_id")
        contract = snapshot["contracts"].get(contract_id)
        if not contract:
            raise RuntimeError(f"experiment {experiment_id} has no available verification contract")

        attempt_number = len(experiment.get("attempt_ids") or []) + 1
        attempt_id = safe_id(f"attempt-{experiment_id}-{attempt_number:02d}")
        attempt = {
            "id": attempt_id,
            "experiment_id": experiment_id,
            "attempt_number": attempt_number,
            "from_state_id": experiment["from_state_id"],
            "context_id": experiment.get("context_id") or "default",
            "mode": experiment.get("mode") or "validate",
            "contract_id": contract_id,
            "contract_version": contract.get("version"),
            "contract_hash": self._contract_hash(contract),
            "action": deepcopy(experiment.get("action") or {}),
            "cost_units_reserved": float((experiment.get("cost") or {}).get("units") or 0.0),
        }
        code_hashes = self._action_code_hashes(experiment.get("action") or {})
        if code_hashes:
            attempt["code_hashes"] = code_hashes
            prior_ids = list(experiment.get("attempt_ids") or [])
            if prior_ids:
                prior = snapshot["attempts"].get(prior_ids[-1]) or {}
                prior_hashes = prior.get("code_hashes")
                if prior_hashes is not None:
                    attempt["code_changed_since_last_attempt"] = prior_hashes != code_hashes
        self.workspace.write_attempt_json(attempt_id, "manifest.json", attempt)
        self.workspace.append_event(
            "ATTEMPT_RESERVED",
            actor=actor,
            visibility=experiment.get("visibility", "normal"),
            data={"attempt": attempt},
        )
        self.workspace.append_event(
            "ATTEMPT_STARTED",
            actor=actor,
            visibility=experiment.get("visibility", "normal"),
            data={"attempt_id": attempt_id},
        )
        self.sync()
        return attempt

    def record_observation(
        self,
        attempt_id: str,
        observation: dict[str, Any],
        *,
        actor: str = "executor",
    ) -> dict[str, Any]:
        snapshot = self.snapshot()
        attempt = snapshot["attempts"].get(attempt_id)
        if not attempt:
            raise KeyError(f"unknown attempt: {attempt_id}")
        if attempt.get("verdict"):
            raise RuntimeError(f"attempt already settled: {attempt_id}")
        if attempt.get("observation") is not None:
            raise RuntimeError(f"attempt already has an observation: {attempt_id}")
        normalized = self._normalize_observation(observation)
        self.workspace.write_attempt_json(attempt_id, "observation.json", normalized)
        experiment = snapshot["experiments"][attempt["experiment_id"]]
        self.workspace.append_event(
            "OBSERVATION_RECORDED",
            actor=actor,
            visibility=experiment.get("visibility", "normal"),
            data={"attempt_id": attempt_id, "observation": normalized},
        )
        self.sync()
        return normalized

    @staticmethod
    def _normalize_observation(observation: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(observation, dict):
            raise ValueError("observation must be an object")
        normalized = deepcopy(observation)
        normalized.setdefault("summary", "")
        normalized["execution"] = dict(normalized.get("execution") or {})
        normalized["metrics"] = dict(normalized.get("metrics") or {})
        normalized["artifacts"] = list(normalized.get("artifacts") or [])
        normalized["metadata"] = dict(normalized.get("metadata") or {})
        return normalized

    def settle_attempt(
        self,
        attempt_id: str,
        observation: dict[str, Any] | None = None,
        *,
        actor: str = "verifier",
    ) -> dict[str, Any]:
        if observation is not None:
            snapshot = self.snapshot()
            attempt = snapshot["attempts"].get(attempt_id)
            if not attempt:
                raise KeyError(f"unknown attempt: {attempt_id}")
            if attempt.get("observation") is None:
                self.record_observation(attempt_id, observation, actor="executor")

        snapshot = self.snapshot()
        attempt = snapshot["attempts"].get(attempt_id)
        if not attempt:
            raise KeyError(f"unknown attempt: {attempt_id}")
        if attempt.get("verdict"):
            raise RuntimeError(f"attempt already settled: {attempt_id}")
        observed = attempt.get("observation")
        if observed is None:
            raise RuntimeError(f"attempt has no observation: {attempt_id}")
        experiment = snapshot["experiments"][attempt["experiment_id"]]
        contract = snapshot["contracts"].get(attempt["contract_id"])
        if not contract:
            raise RuntimeError(f"contract disappeared before settlement: {attempt['contract_id']}")
        if self._contract_hash(contract) != attempt.get("contract_hash"):
            verdict = {
                "status": "INVALID",
                "reason_code": "contract_changed_after_preregistration",
                "summary": "Verification contract changed after the attempt was reserved.",
                "checks": {},
            }
        else:
            verdict = classify_observation(contract, observed)

        claim_effects = self._claim_effects(snapshot, experiment, contract, verdict)
        evidence_id = safe_id(f"evidence-{attempt_id}")
        evidence = {
            "id": evidence_id,
            "summary": verdict.get("summary") or observed.get("summary") or "",
            "reason_code": verdict.get("reason_code"),
            "metrics": deepcopy(observed.get("metrics") or {}),
            "artifact_refs": deepcopy(observed.get("artifacts") or []),
            "contract_id": contract["id"],
            "contract_version": contract.get("version"),
            "contract_hash": attempt.get("contract_hash"),
            "context_id": experiment.get("context_id") or "default",
            "claim_effects": deepcopy(claim_effects),
            "checks": deepcopy(verdict.get("checks") or {}),
            "code_hashes": deepcopy(attempt.get("code_hashes") or {}),
        }
        data = {
            "attempt_id": attempt_id,
            "experiment_id": experiment["id"],
            "verdict": verdict,
            "claim_effects": claim_effects,
            "evidence": evidence,
            "cost_units": float((experiment.get("cost") or {}).get("units") or 0.0),
        }
        self.workspace.write_attempt_json(attempt_id, "verdict.json", data)
        self.workspace.append_event(
            "VERDICT_ISSUED",
            actor=actor,
            visibility=experiment.get("visibility", "normal"),
            data=data,
        )
        new_snapshot = self.sync()
        return {
            "verdict": verdict,
            "claim_effects": claim_effects,
            "evidence": evidence,
            "snapshot": new_snapshot,
        }

    def _claim_effects(
        self,
        snapshot: dict[str, Any],
        experiment: dict[str, Any],
        contract: dict[str, Any],
        verdict: dict[str, Any],
    ) -> list[dict[str, Any]]:
        status = verdict["status"]
        claim_id = contract["target_claim_id"]
        if status in {"INVALID", "ERROR"}:
            return []
        if status == "FAIL":
            return [
                {
                    "claim_id": claim_id,
                    "status": "REFUTED",
                    "reason": verdict.get("reason_code"),
                    "provisional": False,
                }
            ]
        if status == "INCONCLUSIVE":
            return [
                {
                    "claim_id": claim_id,
                    "status": "INCONCLUSIVE",
                    "reason": verdict.get("reason_code"),
                    "provisional": False,
                }
            ]

        # PASS is promoted only after the preregistered repetition contract is met.
        prior_passes: list[dict[str, Any]] = []
        contexts: set[str] = set()
        for prior_attempt in snapshot["attempts"].values():
            prior_verdict = prior_attempt.get("verdict") or {}
            prior_experiment = snapshot["experiments"].get(prior_attempt.get("experiment_id")) or {}
            if (
                prior_verdict.get("status") == "PASS"
                and prior_experiment.get("contract_id") == contract["id"]
                and prior_attempt.get("contract_hash") == self._contract_hash(contract)
                and claim_id in (prior_experiment.get("target_claim_ids") or [])
            ):
                prior_passes.append(prior_attempt)
                contexts.add(str(prior_attempt.get("context_id") or "default"))
        contexts.add(str(experiment.get("context_id") or "default"))
        pass_count = len(prior_passes) + 1
        repetition = contract.get("repetition") or {}
        min_passes = int(repetition.get("min_passes") or 1)
        min_contexts = int(repetition.get("min_independent_contexts") or 1)
        promoted = pass_count >= min_passes and len(contexts) >= min_contexts
        return [
            {
                "claim_id": claim_id,
                "status": "SUPPORTED" if promoted else "INCONCLUSIVE",
                "reason": "repetition_gate_passed" if promoted else "provisional_pass_repetition_pending",
                "provisional": not promoted,
                "pass_count": pass_count,
                "independent_context_count": len(contexts),
                "required_passes": min_passes,
                "required_contexts": min_contexts,
            }
        ]

    def execute_experiment(
        self,
        experiment_id: str,
        *,
        workdir: str | Path | None = None,
        actor: str = "command-executor",
    ) -> dict[str, Any]:
        snapshot = self.snapshot()
        experiment = snapshot["experiments"].get(experiment_id)
        if not experiment:
            raise KeyError(experiment_id)
        action = dict(experiment.get("action") or {})
        if action.get("kind") != "command":
            raise RuntimeError("execute_experiment only supports action.kind=command; use begin/settle for external or manual work")
        attempt = self.begin_attempt(experiment_id, actor=actor)
        attempt_id = attempt["id"]
        cwd = Path(workdir or action.get("cwd") or self.workspace.root)
        if not cwd.is_absolute():
            cwd = (self.workspace.root / cwd).resolve()
        timeout = int(action.get("timeout_seconds") or 600)
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in dict(action.get("env") or {}).items()})
        env.update(
            {
                "SISYFUS_RESEARCH_ID": self.workspace.research_id,
                "SISYFUS_EXPERIMENT_ID": experiment_id,
                "SISYFUS_ATTEMPT_ID": attempt_id,
                "SISYFUS_ATTEMPT_DIR": str(self.workspace.attempts_dir / attempt_id),
            }
        )
        result = run_process(str(action["command"]), cwd=cwd, timeout=timeout, env=env, shell=True)
        self.workspace.write_attempt_text(attempt_id, "stdout.txt", str(result.get("stdout") or ""))
        self.workspace.write_attempt_text(attempt_id, "stderr.txt", str(result.get("stderr") or ""))

        observation: dict[str, Any] = {
            "summary": str(action.get("summary") or f"Executed command experiment {experiment_id}"),
            "execution": {
                "command": result.get("command"),
                "exit_code": result.get("exit_code"),
                "elapsed_seconds": result.get("elapsed_seconds"),
                "timed_out": result.get("timed_out", False),
                "error": result.get("error"),
                "stdout_tail": str(result.get("stdout") or "")[-4000:],
                "stderr_tail": str(result.get("stderr") or "")[-4000:],
            },
            "metrics": {},
            "artifacts": [],
            "metadata": {"cwd": str(cwd)},
        }

        observation_path = action.get("observation_path")
        if observation_path:
            path = self._resolve_action_path(cwd, observation_path)
            if path.exists():
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise ValueError(f"observation_path must contain a JSON object: {path}")
                observation = self._deep_merge(observation, loaded)
            else:
                observation["metadata"]["observation_path_missing"] = str(path)

        metrics_path = action.get("metrics_path")
        if metrics_path:
            path = self._resolve_action_path(cwd, metrics_path)
            if path.exists():
                loaded_metrics = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded_metrics, dict):
                    observation["metrics"].update(loaded_metrics)
                else:
                    observation["metadata"]["metrics_path_error"] = "metrics file was not a JSON object"
            else:
                observation["metadata"]["metrics_path_missing"] = str(path)

        if action.get("parse_stdout_json"):
            parsed = self._parse_stdout_json(str(result.get("stdout") or ""))
            if parsed is not None:
                observation = self._deep_merge(observation, parsed)
            else:
                observation["metadata"]["stdout_json_parse_failed"] = True

        for artifact_path in action.get("artifact_paths") or []:
            path = self._resolve_action_path(cwd, artifact_path)
            if path.exists() and path.is_file():
                observation["artifacts"].append(self.workspace.add_artifact(path))
            else:
                observation["artifacts"].append({"path": str(artifact_path), "missing": True})

        self.record_observation(attempt_id, observation, actor=actor)
        return self.settle_attempt(attempt_id)

    @staticmethod
    def _resolve_action_path(cwd: Path, value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else (cwd / path).resolve()

    @staticmethod
    def _parse_stdout_json(stdout: str) -> dict[str, Any] | None:
        candidates = [stdout.strip(), *reversed([line.strip() for line in stdout.splitlines() if line.strip()])]
        for candidate in candidates:
            try:
                value = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        return None

    @staticmethod
    def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base)
        for key, value in overlay.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = ResearchEngine._deep_merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged

    def recover_stranded(self, *, actor: str = "recovery") -> list[dict[str, Any]]:
        """Convert stranded RESERVED/RUNNING attempts into ERROR and requeue experiments.

        Recovery never creates claim evidence. It records an infrastructure error so
        replay remains complete and the experiment can be attempted again.
        """
        recovered: list[dict[str, Any]] = []
        while True:
            snapshot = self.snapshot()
            stranded = next(
                (
                    item
                    for item in snapshot["attempts"].values()
                    if item.get("status") in {"RESERVED", "RUNNING"} and not item.get("verdict")
                ),
                None,
            )
            if not stranded:
                break
            attempt_id = stranded["id"]
            if stranded.get("observation") is None:
                self.record_observation(
                    attempt_id,
                    {
                        "summary": "Recovered a stranded attempt after interruption.",
                        "execution": {"error": "stranded_attempt_recovered"},
                        "metrics": {},
                        "artifacts": [],
                        "metadata": {"recovered_at": utc_now()},
                    },
                    actor=actor,
                )
            recovered.append(self.settle_attempt(attempt_id, actor=actor))
        return recovered

    @property
    def _global_lessons_path(self) -> Path:
        return self.workspace.root / ".sisyfus" / "research" / "global_lessons.jsonl"

    def _read_global_lessons(self) -> list[dict[str, Any]]:
        path = self._global_lessons_path
        if not path.exists():
            return []
        items: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                items.append(value)
        return items

    def _upsert_global_lesson(self, record: dict[str, Any]) -> None:
        items = [
            item
            for item in self._read_global_lessons()
            if not (
                item.get("research_id") == record.get("research_id")
                and item.get("lesson_id") == record.get("lesson_id")
            )
        ]
        items.append(record)
        path = self._global_lessons_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n" for item in items),
            encoding="utf-8",
        )

    def _global_lesson_ids(self) -> set[str]:
        """Active global lesson ids only — cheap enough for the admission hot path."""
        return {
            str(item.get("lesson_id"))
            for item in self._read_global_lessons()
            if item.get("status") == "ACTIVE" and item.get("lesson_id")
        }

    def global_lessons(
        self,
        *,
        exclude_current: bool = True,
        limit: int = 20,
        with_efficacy: bool = False,
    ) -> list[dict[str, Any]]:
        """Promoted lessons from every research run under this project root.

        Ranked by scope/topic relevance to the current TaskSpec first, recency
        second, so a growing lesson library surfaces what applies here instead
        of merely what is newest.
        """
        items = [
            dict(item)
            for item in self._read_global_lessons()
            if item.get("status") == "ACTIVE"
            and not (exclude_current and item.get("research_id") == self.workspace.research_id)
        ]
        task = self.task
        task_tokens = _relevance_tokens(
            [
                task.get("topic"),
                task.get("action_space"),
                [claim.get("statement") for claim in task.get("claims") or []],
                [claim.get("tags") for claim in task.get("claims") or []],
            ]
        )
        for item in items:
            item["relevance"] = _lesson_relevance(item, task_tokens)
        items.sort(key=lambda x: (int(x.get("relevance") or 0), str(x.get("promoted_at") or "")), reverse=True)
        items = items[:limit]
        if with_efficacy:
            stats = self.lesson_efficacy()
            for item in items:
                item["efficacy"] = stats.get(str(item.get("lesson_id"))) or {"uses": 0, "verdicts": {}, "runs": []}
        return items

    def lesson_efficacy(self) -> dict[str, dict[str, Any]]:
        """Aggregate lesson citations and their verdict outcomes across all runs.

        Derived lazily from each run's persisted snapshot projection — no counters
        are mutated anywhere, so the numbers can always be re-derived from source.
        """
        stats: dict[str, dict[str, Any]] = {}
        for item in ResearchWorkspace.list(self.workspace.root):
            run_path = self.workspace.root / str(item.get("path") or "")
            snapshot_path = run_path / "snapshot.json"
            if not snapshot_path.exists():
                continue
            try:
                snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            for lesson_id, usage in (snapshot.get("lesson_usage") or {}).items():
                entry = stats.setdefault(lesson_id, {"uses": 0, "verdicts": {}, "runs": []})
                entry["uses"] += len(usage.get("experiment_ids") or [])
                entry["runs"].append(str(item.get("research_id")))
                for status, count in (usage.get("verdicts") or {}).items():
                    entry["verdicts"][status] = entry["verdicts"].get(status, 0) + int(count)
        for entry in stats.values():
            entry["runs"] = sorted(set(entry["runs"]))
        return stats

    def add_lesson(self, raw_lesson: dict[str, Any], *, actor: str = "reviewer") -> dict[str, Any]:
        snapshot = self.snapshot()
        lesson = normalize_lesson(raw_lesson)
        if lesson["id"] in snapshot["lessons"]:
            raise ValueError(f"lesson already exists: {lesson['id']}")
        unknown_evidence = [item for item in lesson["evidence_ids"] if item not in snapshot["evidence"]]
        if unknown_evidence:
            raise ValueError(f"lesson references unknown evidence: {unknown_evidence}")
        self.workspace.append_event("LESSON_CANDIDATE_CREATED", actor=actor, data={"lesson": lesson})
        self.sync()
        return lesson

    def add_lesson_evidence(
        self,
        lesson_id: str,
        evidence_ids: list[str],
        *,
        actor: str = "reviewer",
    ) -> dict[str, Any]:
        """Append later-earned evidence to an existing lesson without recreating it."""
        snapshot = self.snapshot()
        lesson = snapshot["lessons"].get(lesson_id)
        if not lesson:
            raise KeyError(lesson_id)
        if lesson.get("status") == "REVOKED":
            raise RuntimeError(f"cannot add evidence to a revoked lesson: {lesson_id}")
        cleaned = [str(x).strip() for x in evidence_ids if str(x).strip()]
        if not cleaned:
            raise ValueError("no evidence ids supplied")
        unknown = [item for item in cleaned if item not in snapshot["evidence"]]
        if unknown:
            raise ValueError(f"lesson evidence references unknown evidence: {unknown}")
        new_items = [item for item in cleaned if item not in (lesson.get("evidence_ids") or [])]
        if not new_items:
            raise ValueError(f"all supplied evidence is already attached to lesson {lesson_id}")
        self.workspace.append_event(
            "LESSON_EVIDENCE_ADDED",
            actor=actor,
            data={"lesson_id": lesson_id, "evidence_ids": new_items},
        )
        self.sync()
        return self.snapshot()["lessons"][lesson_id]

    def promote_lesson(self, lesson_id: str, *, actor: str = "human", min_independent_experiments: int = 2) -> dict[str, Any]:
        snapshot = self.snapshot()
        lesson = snapshot["lessons"].get(lesson_id)
        if not lesson:
            raise KeyError(lesson_id)
        evidence_ids = lesson.get("evidence_ids") or []
        experiment_ids = {
            (snapshot["evidence"].get(evidence_id) or {}).get("experiment_id")
            for evidence_id in evidence_ids
            if evidence_id in snapshot["evidence"]
        }
        experiment_ids.discard(None)
        if len(experiment_ids) < min_independent_experiments:
            raise RuntimeError(
                f"lesson promotion requires evidence from at least {min_independent_experiments} independent experiments"
            )
        active_counterexamples = [item for item in lesson.get("counterexample_ids") or [] if item in snapshot["evidence"]]
        if active_counterexamples:
            raise RuntimeError(f"lesson has unresolved counterexamples: {active_counterexamples}")
        self.workspace.append_event(
            "LESSON_PROMOTED",
            actor=actor,
            data={"lesson_id": lesson_id, "experiment_ids": sorted(experiment_ids)},
        )
        self.sync()
        promoted = self.snapshot()["lessons"][lesson_id]
        snapshot = self.snapshot()
        self._upsert_global_lesson(
            {
                "research_id": self.workspace.research_id,
                "lesson_id": lesson_id,
                "status": "ACTIVE",
                "topic": snapshot.get("topic"),
                "scope": promoted.get("scope") or {},
                "preconditions": promoted.get("preconditions") or [],
                "observation": promoted.get("observation"),
                "recommendation": promoted.get("recommendation"),
                "confidence": promoted.get("confidence"),
                "promoted_at": promoted.get("promoted_at"),
                "supporting_experiments": sorted(experiment_ids),
            }
        )
        return promoted

    def revoke_lesson(self, lesson_id: str, *, reason: str, actor: str = "human") -> dict[str, Any]:
        snapshot = self.snapshot()
        if lesson_id not in snapshot["lessons"]:
            raise KeyError(lesson_id)
        self.workspace.append_event(
            "LESSON_REVOKED",
            actor=actor,
            data={"lesson_id": lesson_id, "reason": reason},
        )
        self.sync()
        revoked = self.snapshot()["lessons"][lesson_id]
        for item in self._read_global_lessons():
            if item.get("research_id") == self.workspace.research_id and item.get("lesson_id") == lesson_id:
                self._upsert_global_lesson({**item, "status": "REVOKED", "revoke_reason": reason})
                break
        return revoked

    def pause(self, *, actor: str = "user", reason: str = "") -> dict[str, Any]:
        self.workspace.append_event("RUN_PAUSED", actor=actor, data={"reason": reason})
        return self.sync()

    def resume(self, *, actor: str = "user") -> dict[str, Any]:
        snapshot = self.snapshot()
        if snapshot["run_status"] != "PAUSED":
            raise RuntimeError("only a paused research run can be resumed")
        self.workspace.append_event("RUN_RESUMED", actor=actor, data={})
        return self.sync()

    def fail(self, *, actor: str = "system", reason: str) -> dict[str, Any]:
        self.workspace.append_event("RUN_FAILED", actor=actor, data={"reason": reason})
        return self.sync()

    def finalize(self, *, status: str = "auto", actor: str = "terminal-evaluator", reason: str = "") -> dict[str, Any]:
        snapshot = self.refresh_waits()
        requested = status.upper()
        if requested == "AUTO":
            if snapshot["run_status"] in {"SOLVED", "REFUTED", "BUDGET_EXHAUSTED", "FAILED"}:
                requested = snapshot["run_status"]
            elif snapshot["terminal_assessment"] in {"BLOCKED", "EXHAUSTED", "REFUTED"}:
                requested = snapshot["terminal_assessment"]
            elif snapshot["terminal_assessment"] == "WAITING":
                raise RuntimeError(
                    "run is not terminal; experiments are waiting "
                    f"(next_wake_at={snapshot.get('next_wake_at')})"
                )
            else:
                raise RuntimeError("run is not terminal; frontier or unresolved work remains")
        allowed = {"SOLVED", "REFUTED", "BLOCKED", "EXHAUSTED", "BUDGET_EXHAUSTED", "FAILED"}
        if requested not in allowed:
            raise ValueError(f"invalid final status: {requested}")
        if requested == "SOLVED" and snapshot["goal_evaluation"]["root_status"] != "PASS":
            raise RuntimeError("terminal evaluator cannot mark SOLVED while the Goal Graph root is not PASS")
        if requested == "REFUTED" and snapshot["goal_evaluation"]["root_status"] != "FAIL":
            raise RuntimeError("terminal evaluator cannot mark REFUTED while the Goal Graph root is not FAIL")
        if (
            requested == "SOLVED"
            and snapshot.get("contested_claims")
            and self.task["stop_policy"].get("require_uncontested_solve", False)
        ):
            raise RuntimeError(
                "terminal evaluator cannot mark SOLVED while required claims are contested "
                f"({', '.join(snapshot['contested_claims'])}); add a later PASS experiment with a "
                "discriminating_note explaining why it supersedes the refuting evidence"
            )
        if requested == "SOLVED" and snapshot["run_status"] == "BUDGET_EXHAUSTED":
            raise RuntimeError("terminal evaluator cannot override a hard budget exhaustion")
        self.workspace.append_event(
            "RUN_FINALIZED",
            actor=actor,
            data={"status": requested, "reason": reason, "goal_root_status": snapshot["goal_evaluation"]["root_status"]},
        )
        return self.sync()

    def render_report(self, *, open_browser: bool = False, log_event: bool = False) -> Path:
        if log_event:
            self.workspace.append_event("REPORT_RENDERED", actor="reporter", data={"path": "report/index.html"})
        self.refresh_waits(render=True)
        if open_browser:
            webbrowser.open(self.workspace.report_path.resolve().as_uri())
        return self.workspace.report_path

    def serve_report(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8787,
        open_browser: bool = False,
        verbose: bool = False,
    ) -> tuple[Any, str]:
        from .observatory import serve_observatory

        self.refresh_waits(render=True)
        return serve_observatory(
            self.workspace,
            refresh_callback=lambda: self.refresh_waits(render=True),
            host=host,
            port=port,
            open_browser=open_browser,
            verbose=verbose,
        )

    def reproduce_evidence(
        self,
        evidence_id: str,
        *,
        workdir: str | Path | None = None,
        actor: str = "reproducer",
    ) -> dict[str, Any]:
        """Deterministically re-derive one piece of evidence, no model involved.

        Re-verifies the hashed measurement code, re-runs the recorded command,
        compares the fresh metrics against the recorded ones, and re-classifies
        them under the same locked contract. The outcome is appended to the
        event chain as EVIDENCE_REPRODUCED; the original evidence is immutable.
        Live-world measurements are expected to drift — for those, independence
        comes from repetition contexts, not reproduction.
        """
        snapshot = self.snapshot()
        evidence = snapshot["evidence"].get(evidence_id)
        if not evidence:
            raise KeyError(f"unknown evidence: {evidence_id}")
        experiment = snapshot["experiments"].get(evidence.get("experiment_id")) or {}
        action = dict(experiment.get("action") or {})
        if action.get("kind") != "command":
            raise RuntimeError(
                "reproduce supports only command evidence; external/manual measurements "
                "need an independent repetition context instead"
            )
        contract = snapshot["contracts"].get(evidence.get("contract_id"))
        if not contract:
            raise RuntimeError(f"contract not found for evidence: {evidence.get('contract_id')}")
        contract_intact = self._contract_hash(contract) == evidence.get("contract_hash")

        recorded_hashes = dict(evidence.get("code_hashes") or {})
        current_hashes = self._action_code_hashes(action)
        code_mismatches = {
            key: {"recorded": value, "current": current_hashes.get(key)}
            for key, value in recorded_hashes.items()
            if current_hashes.get(key) != value
        }
        code_intact = not code_mismatches

        cwd = Path(workdir or action.get("cwd") or self.workspace.root)
        if not cwd.is_absolute():
            cwd = (self.workspace.root / cwd).resolve()
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in dict(action.get("env") or {}).items()})
        env.update(
            {
                "SISYFUS_RESEARCH_ID": self.workspace.research_id,
                "SISYFUS_REPRODUCTION": "1",
            }
        )
        timeout = int(action.get("timeout_seconds") or 600)
        result = run_process(str(action["command"]), cwd=cwd, timeout=timeout, env=env, shell=True)

        reproduced_metrics: dict[str, Any] = {}
        metrics_path = action.get("metrics_path")
        if metrics_path:
            path = self._resolve_action_path(cwd, metrics_path)
            if path.exists():
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    reproduced_metrics = loaded
        observation = {
            "summary": f"Reproduction of {evidence_id}",
            "execution": {
                "command": result.get("command"),
                "exit_code": result.get("exit_code"),
                "timed_out": result.get("timed_out", False),
                "error": result.get("error"),
            },
            "metrics": reproduced_metrics,
            "artifacts": evidence.get("artifact_refs") or [],
        }
        reproduced_verdict = classify_observation(contract, observation)

        recorded_metrics = dict(evidence.get("metrics") or {})
        drift = {
            key: {"recorded": recorded_metrics.get(key), "reproduced": reproduced_metrics.get(key)}
            for key in sorted(set(recorded_metrics) | set(reproduced_metrics))
            if recorded_metrics.get(key) != reproduced_metrics.get(key)
        }
        deterministic_match = not drift
        verdict_stable = reproduced_verdict["status"] == evidence.get("verdict_status")

        capped_drift = dict(list(drift.items())[:20])
        event_data = {
            "evidence_id": evidence_id,
            "experiment_id": experiment.get("id"),
            "contract_intact": contract_intact,
            "code_intact": code_intact,
            "code_mismatches": code_mismatches,
            "deterministic_match": deterministic_match,
            "metric_drift": capped_drift,
            "metric_drift_truncated": max(0, len(drift) - len(capped_drift)),
            "reproduced_status": reproduced_verdict["status"],
            "recorded_status": evidence.get("verdict_status"),
            "verdict_stable": verdict_stable,
            "execution": {
                "exit_code": result.get("exit_code"),
                "elapsed_seconds": result.get("elapsed_seconds"),
                "timed_out": result.get("timed_out", False),
            },
        }
        self.workspace.append_event(
            "EVIDENCE_REPRODUCED",
            actor=actor,
            visibility=experiment.get("visibility", "normal"),
            data=event_data,
        )
        self.sync()
        return {
            **event_data,
            "metric_drift": drift,
            "reproduced_verdict": reproduced_verdict,
        }

    def verify_replay(self) -> dict[str, Any]:
        first = self.snapshot()
        second = reduce_research(self.task, self.workspace.read_events(verify_chain=True))
        stable = first.get("snapshot_hash") == second.get("snapshot_hash")
        return {
            "research_id": self.workspace.research_id,
            "event_count": len(self.events),
            "event_chain_valid": True,
            "snapshot_hash": first.get("snapshot_hash"),
            "replay_hash": second.get("snapshot_hash"),
            "deterministic": stable,
        }


def load_json_object(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def make_demo_spec() -> dict[str, Any]:
    """Return a deterministic demo with a failed branch, checkpoint recovery, and repetition gates."""
    return {
        "id": "stone-demo",
        "topic": "验证一个候选研究方法是否可靠、可复现且满足最终质量门槛",
        "i18n": {
            "en": {
                "topic": "Verify that a candidate research method is reliable, reproducible, and meets the final quality bar",
                "claims": {
                    "data-valid": {"label": "data quality", "statement": "Input data is complete and leakage-free"},
                    "method-works": {"label": "method works", "statement": "The candidate method clears the preregistered out-of-sample threshold"},
                    "robust": {"label": "robustness", "statement": "The candidate method stays robust across independent contexts"},
                },
            }
        },
        "claims": [
            {
                "id": "data-valid",
                "statement": "输入数据完整且无泄漏",
                "label": "数据质量",
                "required": True,
                "critical": True,
                "weight": 1.0,
            },
            {
                "id": "method-works",
                "label": "方法有效",
                "statement": "候选方法在样本外达到预注册阈值",
                "required": True,
                "weight": 2.0,
                "depends_on": ["data-valid"],
            },
            {
                "id": "robust",
                "label": "稳健性",
                "statement": "候选方法在独立情境中保持稳健",
                "required": True,
                "weight": 1.5,
                "depends_on": ["data-valid", "method-works"],
            },
        ],
        "verification_contracts": [
            {
                "id": "verify-data",
                "target_claim_id": "data-valid",
                "description": "检查数据完整性与泄漏标志",
                "pass_if": {"all": [{"path": "metrics.data_complete", "op": "==", "value": True}, {"path": "metrics.leakage", "op": "==", "value": False}]},
                "fail_if": {"any": [{"path": "metrics.leakage", "op": "==", "value": True}]},
                "invalid_if": {"any": [{"path": "metrics.telemetry_missing", "op": "==", "value": True}]},
            },
            {
                "id": "verify-performance",
                "target_claim_id": "method-works",
                "description": "样本外指标和护栏",
                "preconditions": {"all": [{"path": "metrics.data_validated", "op": "==", "value": True}]},
                "pass_if": {"all": [{"path": "metrics.oos_score", "op": ">=", "value": 0.7}]},
                "fail_if": {"all": [{"path": "metrics.oos_score", "op": "<", "value": 0.4}]},
                "guardrails": {"all": [{"path": "metrics.cost", "op": "<=", "value": 0.2}]},
            },
            {
                "id": "verify-robustness",
                "target_claim_id": "robust",
                "description": "两个独立情境均需通过",
                "pass_if": {"all": [{"path": "metrics.robust_score", "op": ">=", "value": 0.6}]},
                "fail_if": {"all": [{"path": "metrics.robust_score", "op": "<", "value": 0.3}]},
                "repetition": {"min_passes": 2, "min_independent_contexts": 2},
            },
        ],
        "budget": {"max_attempts": 12, "max_cost_units": 12, "max_wall_minutes": 60},
        "stop_policy": {"block_without_verifier": True, "max_invalid_attempts_per_experiment": 2},
    }


def build_demo(root: str | Path | None) -> ResearchEngine:
    engine = ResearchEngine.create(root, make_demo_spec(), actor="demo")

    def propose(exp_id: str, claim: str, contract: str, context: str, title: str) -> None:
        engine.propose_experiment(
            {
                "id": exp_id,
                "title": title,
                "target_claim_ids": [claim],
                "contract_id": contract,
                "context_id": context,
                "action": {"kind": "external"},
                "expected_outcomes": {
                    "pass": "支持目标命题并推进石头",
                    "fail": "有效反驳目标命题并关闭该路径",
                    "inconclusive": "保留未知状态并规划新实验",
                    "invalid": "实验设计或遥测无效，不更新命题",
                },
                "priority": {"goal_progress": 0.8, "information_gain": 0.8, "cost": 1.0},
                "cost": {"units": 1.0},
            },
            actor="demo-planner",
        )

    # Data checkpoint passes.
    propose("data-check", "data-valid", "verify-data", "dataset-a", "检查数据完整性")
    attempt = engine.begin_attempt("data-check", actor="demo")
    engine.settle_attempt(
        attempt["id"],
        {"summary": "数据检查通过", "metrics": {"data_complete": True, "leakage": False}},
        actor="demo-verifier",
    )

    # One valid but failed branch; it refutes only the branch's target claim.
    propose("weak-method", "method-works", "verify-performance", "model-a", "测试弱候选路径")
    attempt = engine.begin_attempt("weak-method", actor="demo")
    engine.settle_attempt(
        attempt["id"],
        {"summary": "弱候选在样本外失败", "metrics": {"data_validated": True, "oos_score": 0.2, "cost": 0.1}},
        actor="demo-verifier",
    )

    # Branch from the data checkpoint, not from the refuted branch state.
    data_state = engine.snapshot()["experiments"]["data-check"]["to_state_ids"][-1]
    engine.propose_experiment(
        {
            "id": "strong-method",
            "title": "从已验证数据检查点探索另一候选",
            "target_claim_ids": ["method-works"],
            "contract_id": "verify-performance",
            "from_state_id": data_state,
            "context_id": "model-b",
            "action": {"kind": "external"},
            "expected_outcomes": {
                "pass": "支持样本外有效性",
                "fail": "反驳该候选",
                "inconclusive": "需要更多数据",
                "invalid": "实验设置无效",
            },
            "priority": {"goal_progress": 1.0, "information_gain": 0.9, "cost": 1.0},
            "cost": {"units": 1.0},
        },
        actor="demo-planner",
    )
    attempt = engine.begin_attempt("strong-method", actor="demo")
    engine.settle_attempt(
        attempt["id"],
        {"summary": "替代路径通过", "metrics": {"data_validated": True, "oos_score": 0.82, "cost": 0.12}},
        actor="demo-verifier",
    )

    for exp_id, context, score in (("robust-a", "regime-a", 0.72), ("robust-b", "regime-b", 0.67)):
        propose(exp_id, "robust", "verify-robustness", context, f"稳健性验证 {context}")
        attempt = engine.begin_attempt(exp_id, actor="demo")
        engine.settle_attempt(
            attempt["id"],
            {"summary": f"{context} 稳健性通过", "metrics": {"robust_score": score}},
            actor="demo-verifier",
        )
    engine.render_report()
    return engine
