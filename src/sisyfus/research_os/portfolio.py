"""One guarded experiment at a time across multiple existing research workspaces.

This ledger owns shared reservations, NOT scientific truth. All verdicts are
resolved against immutable member events. Only cooperating ResearchOS entrypoints
are fenced; local files and named operator approvals are not security boundaries.
"""
from __future__ import annotations

import re
import hashlib
import time
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from typing import Iterator

from ..research_v2.engine import ResearchEngine
from ..research_v2.workspace import atomic_write_json
from .controller import PREFIX, ResearchOS, configuration, coordinator_lock
from .frontier import ready_frontier
from .judgments import Judge, NullJudge, assess_safely
from .models import Candidate, SOP, digest, number
from .policy import SchedulingPolicy
from .portfolio_store import PortfolioStore

SCHEMA = "sisyfus.portfolio.v1"


def identity(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", value):
        raise ValueError("invalid portfolio/project identity")
    return value


def positive_int(value: object, maximum: int = 10000) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("expected a positive bounded integer")
    return value


def _cfg(engine: ResearchEngine) -> dict:
    cfg = configuration(engine)
    if digest({k: v for k, v in cfg.items() if k != "config_hash"}) != cfg.get("config_hash"):
        raise ValueError("member configuration hash mismatch")
    return cfg


class Portfolio:
    def __init__(self, root: Path):
        self.store = PortfolioStore(root)
        self.manifest = self.store.manifest()
        self.projects = {p["id"]: p for p in self.manifest["projects"]}
        self.engines = {pid: ResearchEngine.load(p["root"], p["research_id"]) for pid, p in self.projects.items()}
        self.policy = SchedulingPolicy.load(self.manifest["policy"])

    @classmethod
    def create(cls, root: Path, spec: dict, *, actor: str) -> "Portfolio":
        identity(actor)
        if spec.get("schema") != SCHEMA or set(spec) - {"schema", "id", "family", "projects", "budget", "policy", "max_consecutive"}:
            raise ValueError("invalid portfolio specification")
        identity(spec.get("id"))
        identity(spec.get("family", spec["id"]))
        budget = dict(spec["budget"])
        if set(budget) != {"max_attempts", "max_cost_units"}:
            raise ValueError("shared attempt and abstract-cost budgets required")
        positive_int(budget["max_attempts"])
        number(budget["max_cost_units"], minimum=0.000001)
        fairness = positive_int(spec.get("max_consecutive", 2), maximum=1000)
        policy = SchedulingPolicy.load(spec["policy"]) if "policy" in spec else SchedulingPolicy()
        raw_projects = spec["projects"]
        if not isinstance(raw_projects, list) or not 1 <= len(raw_projects) <= 100:
            raise ValueError("portfolio requires 1..100 projects")
        projects, engines, paths = {}, {}, set()
        for raw in raw_projects:
            if not isinstance(raw, dict) or set(raw) - {"id", "root", "research_id", "weight", "requires", "max_attempts"}:
                raise ValueError("invalid project fields")
            pid = identity(raw.get("id"))
            if pid in projects:
                raise ValueError("duplicate project ID")
            requested = raw.get("research_id", "latest")
            identity(requested)
            path = Path(raw["root"])
            if not path.is_absolute():
                raise ValueError("project roots must be explicit absolute paths")
            e = ResearchEngine.load(path.resolve(), requested)
            physical = e.workspace.path.resolve()
            if physical in paths:
                raise ValueError("two aliases refer to the same research workspace")
            paths.add(physical)
            requires = raw.get("requires", [])
            if not isinstance(requires, list) or len(requires) > 100:
                raise ValueError("invalid dependency list")
            for req in requires:
                if not isinstance(req, dict) or set(req) != {"project", "claim"}:
                    raise ValueError("dependency requires exactly project and claim")
                identity(req["project"])
                identity(req["claim"])
            if len({(r["project"], r["claim"]) for r in requires}) != len(requires):
                raise ValueError("duplicate dependency")
            projects[pid] = {"id": pid, "root": str(e.workspace.root.resolve()),
                             "research_id": e.workspace.research_id, "workspace_path": str(physical),
                             "weight": number(raw.get("weight", 1), minimum=0.000001, maximum=100),
                             "max_attempts": positive_int(raw.get("max_attempts", budget["max_attempts"])),
                             "requires": requires}
            engines[pid] = e
        ordered = sorted(engines, key=lambda pid: str(engines[pid].workspace.path.resolve()))
        with ExitStack() as stack:
            for pid in ordered:
                stack.enter_context(coordinator_lock(engines[pid]))
            for pid, p in projects.items():
                e = engines[pid]
                snap = e.snapshot()
                if any(a["status"] in {"RESERVED", "RUNNING"} for a in snap["attempts"].values()):
                    raise ValueError("cannot register a project with unresolved work")
                cfg = _cfg(e)
                p.update(task_hash=digest(e.task), config_hash=cfg["config_hash"],
                         anchor_hash=e.events[-1]["event_hash"], anchor_seq=len(e.events))
                for req in p["requires"]:
                    if req["project"] not in projects or req["claim"] not in engines[req["project"]].snapshot()["claims"]:
                        raise ValueError("unknown dependency project or claim")
            pending, done = set(projects), set()
            while pending:
                ready = {pid for pid in pending if {r["project"] for r in projects[pid]["requires"]} <= done}
                if not ready:
                    raise ValueError("cross-project dependency cycle")
                pending -= ready
                done |= ready
            manifest = {"schema": SCHEMA, "id": spec["id"], "family": spec.get("family", spec["id"]),
                        "projects": list(projects.values()), "budget": budget,
                        "policy": asdict(policy), "max_consecutive": fairness, "actor": actor}
            root = root.resolve()
            root.mkdir(parents=True, exist_ok=False)
            store = PortfolioStore(root)
            with store.lock():
                atomic_write_json(root / "manifest.json", manifest)
                store.append("REGISTERED", manifest)
        return cls(root)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        # Stable order + nonblocking member locks avoids cross-portfolio deadlock.
        with self.store.lock(), ExitStack() as stack:
            if self.store.manifest() != self.manifest:
                raise ValueError("portfolio registration changed")
            for e in sorted(self.engines.values(), key=lambda x: str(x.workspace.path.resolve())):
                stack.enter_context(coordinator_lock(e))
            yield

    def _current_configs(self) -> dict[str, str]:
        result = {pid: p["config_hash"] for pid, p in self.projects.items()}
        for event in self.store.events():
            if event["kind"] == "BINDING_REFRESHED":
                result[event["data"]["project"]] = event["data"]["config_hash"]
        return result

    def _source(self, op: dict) -> dict | None:
        """Only an actual verifier event can settle a reserved portfolio attempt."""
        d = op["intent"]
        e = self.engines[d["project"]]
        events = e.events
        anchors = [i for i, event in enumerate(events) if event["event_hash"] == d["source_anchor"]]
        if len(anchors) != 1:
            raise ValueError("member history lost the portfolio source anchor")
        tail = events[anchors[0] + 1:]
        reserves = [(i, v) for i, v in enumerate(tail) if v["event_type"] == "ATTEMPT_RESERVED" and v["data"]["attempt"]["id"] == d["attempt_id"]]
        verdicts = [v for v in tail if v["event_type"] == "VERDICT_ISSUED" and v["data"]["attempt_id"] == d["attempt_id"]]
        if not reserves:
            if verdicts:
                raise ValueError("verdict without portfolio-bound reservation")
            return None
        if len(reserves) != 1:
            raise ValueError("duplicate member reservation")
        index, reserved = reserves[0]
        bound = [v for v in tail[:index] if v["event_type"] == PREFIX + "DECISION" and v["data"].get("attempt_id") == d["attempt_id"]]
        expected_context = {"portfolio": self.manifest["id"], "intent_hash": op["intent_hash"]}
        if len(bound) != 1 or bound[0]["data"].get("dispatch_context") != expected_context:
            raise ValueError("member attempt lacks matching portfolio decision")
        a = reserved["data"]["attempt"]
        if (a["experiment_id"] != d["experiment"] or digest(a["action"]) != d["candidate"]["action_hash"]
                or number(a["cost_units_reserved"]) != d["candidate"]["cost"]
                or bound[0]["data"]["config_hash"] != d["config_hash"]):
            raise ValueError("portfolio attempt differs from approved intent")
        if len(verdicts) > 1:
            raise ValueError("duplicate member verdict")
        if not verdicts:
            return None
        v = verdicts[0]
        observed = [ev for ev in tail if ev["event_type"] == "OBSERVATION_RECORDED"
                    and ev["data"]["attempt_id"] == d["attempt_id"]]
        if any(ev["data"]["observation"].get("execution", {}).get("error") == "stranded_attempt_recovered" for ev in observed):
            return None  # A synthetic recovery ERROR is not a reconciled external result.
        if (v["seq"] <= reserved["seq"] or v["visibility"] == "host_only"
                or number(v["data"]["cost_units"]) != d["candidate"]["cost"]):
            raise ValueError("member verdict violates portfolio provenance or cost")
        return v

    def _reconcile(self) -> None:
        for op in self.store.operations():
            if op["settlement"] is None and op["release"] is None:
                source = self._source(op)
                if source is not None:
                    self.store.append("SETTLED", {"operation_id": op["intent"]["operation_id"],
                                                 "verdict_event_hash": source["event_hash"]})
                # No attempt/receipt is not proof of nonexecution. Keep reservation.

    def _view(self) -> dict:
        configs = self._current_configs()
        snapshots, events, problems = {}, {}, []
        ops = self.store.operations()
        by_source = {}
        spent = reserved = 0.0
        counts = {pid: 0 for pid in self.projects}
        outcomes, pending = [], []
        for op in ops:
            d = op["intent"]
            if op["release"] is not None:
                tail = self.engines[d["project"]].events
                seq = op["release"]["member_sequence"]
                if len(tail) < seq or tail[seq - 1]["event_hash"] != op["release"]["member_head"]:
                    raise ValueError("released intent lost its member anchor")
                if any(ev["event_type"] == "ATTEMPT_RESERVED" and ev["data"]["attempt"]["id"] == d["attempt_id"]
                       and ev["seq"] <= op["release"]["member_sequence"] for ev in tail):
                    raise ValueError("released intent had a member reservation")
                continue
            counts[d["project"]] += 1
            source = self._source(op)
            if op["settlement"] is not None:
                if source is None or op["settlement"]["verdict_event_hash"] != source["event_hash"]:
                    raise ValueError("portfolio settlement differs from source verifier")
                spent += number(source["data"]["cost_units"])
                by_source[source["event_hash"]] = op
                outcomes.append({"operation_id": d["operation_id"], "project": d["project"],
                                 "attempt_id": d["attempt_id"], "verdict": source["data"]["verdict"]["status"],
                                 "evidence_id": source["data"]["evidence"]["id"],
                                 "source_event_hash": source["event_hash"], "cost_units": source["data"]["cost_units"],
                                 "dependency_proofs": d["dependency_proofs"]})
            else:
                reserved += d["candidate"]["cost"]
                pending.append({"operation_id": d["operation_id"], "project": d["project"],
                                "attempt_id": d["attempt_id"], "receipt_available": source is not None})
        for pid, p in self.projects.items():
            e = self.engines[pid]
            snapshots[pid], events[pid] = e.snapshot(), e.events
            if e.workspace.path.resolve() != Path(p["workspace_path"]) or digest(e.task) != p["task_hash"]:
                raise ValueError("project identity or locked task changed")
            if len(events[pid]) < p["anchor_seq"] or events[pid][p["anchor_seq"] - 1]["event_hash"] != p["anchor_hash"]:
                raise ValueError("project registration anchor lost")
            if _cfg(e)["config_hash"] != configs[pid]:
                problems.append(pid + ":configuration_changed")
            owned = {o["intent"]["attempt_id"] for o in ops if o["intent"]["project"] == pid and o["release"] is None}
            for ev in events[pid][p["anchor_seq"]:]:
                if ev["event_type"] == "ATTEMPT_RESERVED" and ev["data"]["attempt"]["id"] not in owned:
                    problems.append(pid + ":unmanaged_attempt:" + ev["data"]["attempt"]["id"])
        remaining = max(0.0, self.manifest["budget"]["max_cost_units"] - spent - reserved)
        if spent + reserved > self.manifest["budget"]["max_cost_units"] + 1e-9 or sum(counts.values()) > self.manifest["budget"]["max_attempts"]:
            problems.append("shared_budget_violation")

        cache = {}

        def dependencies(pid: str) -> tuple[list[dict], list[str]]:
            if pid in cache:
                return list(cache[pid][0]), list(cache[pid][1])
            proofs, errors = [], []
            for req in self.projects[pid]["requires"]:
                upstream, claim_id = req["project"], req["claim"]
                ancestors, blocked = dependencies(upstream)
                claim = snapshots[upstream]["claims"][claim_id]
                if blocked or claim["status"] != "SUPPORTED" or claim.get("contested"):
                    errors.append(f"{upstream}:{claim_id}:unsupported_or_contested")
                    continue
                supports = [ev for ev in events[upstream] if ev["event_type"] == "VERDICT_ISSUED"
                            and ev["visibility"] != "host_only"
                            and ev["data"]["verdict"]["status"] == "PASS"
                            and ev["data"]["evidence"]["id"] in claim["evidence_ids"]
                            and any(c["claim_id"] == claim_id and c["status"] == "SUPPORTED"
                                    for c in ev["data"]["claim_effects"])]
                if not supports:
                    errors.append(f"{upstream}:{claim_id}:missing_public_support")
                    continue
                support = supports[-1]
                evidence = support["data"]["evidence"]
                contract = snapshots[upstream]["contracts"][evidence["contract_id"]]
                if evidence["contract_hash"] != self.engines[upstream]._contract_hash(contract):
                    errors.append(f"{upstream}:{claim_id}:stale_contract")
                    continue
                artifacts_valid = True
                for ref in evidence.get("artifact_refs", []):
                    location = (self.engines[upstream].workspace.path / ref.get("path", "")).resolve()
                    if (not location.is_relative_to(self.engines[upstream].workspace.path.resolve())
                            or not location.is_file()
                            or hashlib.sha256(location.read_bytes()).hexdigest() != ref.get("sha256")):
                        artifacts_valid = False
                        break
                if not artifacts_valid:
                    errors.append(f"{upstream}:{claim_id}:missing_or_modified_artifact")
                    continue
                # A result with upstream dependencies must have been measured with
                # those same dependencies. A later gate opening cannot retroactively
                # validate an earlier unbound result.
                bound = by_source.get(support["event_hash"])
                if ancestors and (bound is None or bound["intent"]["dependency_proofs"] != ancestors):
                    errors.append(f"{upstream}:{claim_id}:stale_dependency_provenance")
                    continue
                proofs.append({"project": upstream, "claim": claim_id, "claim_hash": digest(claim),
                               "evidence_id": evidence["id"], "verdict_event_hash": support["event_hash"]})
                proofs.extend(ancestors)
            cache[pid] = (sorted({digest(p): p for p in proofs}.values(), key=digest), sorted(set(errors)))
            return list(cache[pid][0]), list(cache[pid][1])

        project_views, choices = {}, []
        for pid, p in self.projects.items():
            proofs, blocked = dependencies(pid)
            cfg = _cfg(self.engines[pid])
            if counts[pid] >= p["max_attempts"]:
                blocked.append("project_attempt_budget_exhausted")
            if any(a["status"] in {"RESERVED", "RUNNING"} for a in snapshots[pid]["attempts"].values()):
                problems.append(pid + ":unresolved_local_attempt")
            local = ready_frontier(snapshots[pid], max_attempts=SOP(**{**cfg["sop"], "preflight_order": tuple(cfg["sop"]["preflight_order"])}).max_attempts_per_experiment)
            approved = [c for c in local if c.id in cfg["approvals"]]
            if local and not approved:
                blocked.append("needs_operator_approval")
            project_views[pid] = {"research_id": p["research_id"], "status": snapshots[pid]["run_status"],
                                  "blocked": blocked, "dependency_proofs": proofs,
                                  "attempts_in_portfolio": counts[pid], "ready_count": len(approved)}
            if not blocked and not pending and not problems and sum(counts.values()) < self.manifest["budget"]["max_attempts"]:
                for c in approved:
                    if c.cost <= remaining:
                        choices.append({"project": pid, "experiment": c.id,
                                        "candidate": replace(c, id=pid + "::" + c.id).public(),
                                        "dependency_proofs": proofs})
        # Problems found in a later project must also suppress earlier choices.
        if problems or pending:
            choices = []
        for out in outcomes:
            proofs, blocked = dependencies(out["project"])
            out["stale_dependencies"] = bool(blocked or out["dependency_proofs"] != proofs)
        return {"schema": SCHEMA, "portfolio_id": self.manifest["id"], "projects": project_views,
                "choices": choices, "problems": sorted(set(problems)), "unresolved": pending,
                "budget": {"attempts_used_or_reserved": sum(counts.values()), "cost_used": spent, "cost_reserved": reserved,
                           "cost_remaining": remaining, "max_attempts": self.manifest["budget"]["max_attempts"],
                           "max_cost_units": self.manifest["budget"]["max_cost_units"], "units": "abstract_not_usd"},
                "outcomes": outcomes, "policy_hash": self.policy.hash,
                "source_heads": {pid: es[-1]["event_hash"] for pid, es in events.items()}}

    def status(self) -> dict:
        with self._locked():
            return self._view()

    def reconcile(self) -> dict:
        """Join already committed verifier receipts; never execute or infer failure."""
        with self._locked():
            self._reconcile()
            return self._view()

    def cancel_unstarted(self, operation_id: str, *, actor: str) -> dict:
        """Explicit release only if the member never recorded a dispatch decision.

        A decision or tool reservation is deliberately too late for this command.
        Those cases need independent reconciliation; neither absence of a reply
        nor a legacy synthetic recovery ERROR establishes nonexecution.
        """
        identity(actor)
        with self._locked():
            ops = self.store.operations()
            op = next((o for o in ops if o["intent"]["operation_id"] == operation_id), None)
            if op is None or op["settlement"] is not None or op["release"] is not None:
                raise ValueError("no unresolved portfolio intent with that ID")
            d = op["intent"]
            events = self.engines[d["project"]].events
            index = next((i for i, e in enumerate(events) if e["event_hash"] == d["source_anchor"]), None)
            if index is None:
                raise ValueError("member history lost the portfolio source anchor")
            if any(e["event_type"] in {"ATTEMPT_RESERVED", PREFIX + "DECISION"} for e in events[index + 1:]):
                raise ValueError("member dispatch may have started; cannot release reservation")
            self.store.append("RELEASED", {"operation_id": operation_id, "actor": actor,
                                          "member_sequence": len(events), "member_head": events[-1]["event_hash"]})
            return self._view()

    def refresh_binding(self, project: str, *, actor: str) -> dict:
        """Explicitly accept a newly operator-approved member config, not a new task."""
        identity(actor)
        if project not in self.projects:
            raise ValueError("unknown project")
        with self._locked():
            self._reconcile()
            view = self._view()
            if view["unresolved"] or any(":unresolved_local_attempt" in p or ":unmanaged_attempt:" in p for p in view["problems"]):
                raise ValueError("reconcile unresolved/unmanaged work before refreshing")
            cfg = _cfg(self.engines[project])
            self.store.append("BINDING_REFRESHED", {"project": project, "config_hash": cfg["config_hash"], "actor": actor})
            return self._view()

    def run(self, *, max_steps: int = 10, max_seconds: float = 300,
            allow_local_commands: bool = False, judge: Judge | None = None,
            allow_judgments: bool = False) -> dict:
        positive_int(max_steps, maximum=1000)
        number(max_seconds, minimum=1, maximum=86400)
        if not allow_local_commands:
            raise PermissionError("portfolio execution requires explicit local-command permission")
        if self.policy.judgment_weight and (not allow_judgments or judge is None):
            raise PermissionError("nonzero judgment weight requires explicit judgment opt-in and a configured adapter")
        started, executed, stop = time.monotonic(), 0, "step_limit"
        with self._locked():
            self._reconcile()
            for _ in range(max_steps):
                if time.monotonic() - started >= max_seconds:
                    stop = "wall_budget_boundary"
                    break
                for e in self.engines.values():
                    e.refresh_waits()
                view = self._view()
                if view["unresolved"] or view["problems"]:
                    stop = "reconciliation_or_operator_action_required"
                    break
                choices = view["choices"]
                if not choices:
                    stop = "no_affordable_ready_action"
                    break
                public = [Candidate.load(c["candidate"]) for c in choices]
                judgments = assess_safely(judge if self.policy.judgment_weight else NullJudge(), public)
                # A semantic judge is not trusted to preserve state while assessing.
                current = self._view()
                if current["source_heads"] != view["source_heads"] or current["problems"]:
                    stop = "state_changed_during_judgment"
                    break
                if time.monotonic() - started >= max_seconds:
                    stop = "wall_budget_boundary"
                    break
                ops = self.store.operations()
                # Persisted max-consecutive fairness, effective only if alternatives
                # are eligible. No guaranteed time fairness or value-of-information claim.
                scheduled = [op for op in ops if op["release"] is None]
                last = scheduled[-1]["intent"]["project"] if scheduled else None
                streak = 0
                for op in reversed(scheduled):
                    if op["intent"]["project"] != last:
                        break
                    streak += 1
                alternatives = [c for c in choices if c["project"] != last]
                eligible = alternatives if alternatives and streak >= self.manifest["max_consecutive"] else choices
                def score(c: dict) -> float:
                    candidate = Candidate.load(c["candidate"])
                    j = judgments[candidate.id]
                    return self.projects[c["project"]]["weight"] * (self.policy.predict(candidate.features) + self.policy.judgment_weight * (j.actionable - j.duplicate)) - self.policy.cost_weight * candidate.cost
                selected = min(eligible, key=lambda c: (0 if self.policy.selection == "fifo" else -score(c), c["candidate"]["id"]))
                e = self.engines[selected["project"]]
                exp = e.snapshot()["experiments"][selected["experiment"]]
                approval = _cfg(e)["approvals"][exp["id"]]
                if (digest(exp["action"]) != approval["action_hash"]
                        or digest(e.snapshot()["contracts"][exp["contract_id"]]) != approval["contract_hash"]
                        or {p: e._action_code_hashes(exp["action"]).get(p, "missing") for p in approval["code_hashes"]} != approval["code_hashes"]):
                    self.store.append("PREFLIGHT_REJECTED", {"project": selected["project"], "experiment": exp["id"], "reason": "approved_inputs_changed"})
                    stop = "approved_inputs_changed"
                    break
                attempt = f"attempt-{exp['id']}-{len(exp.get('attempt_ids', [])) + 1:02d}"
                data = {**selected, "operation_id": f"op-{len(ops):06d}", "attempt_id": attempt,
                        "source_anchor": e.events[-1]["event_hash"], "config_hash": _cfg(e)["config_hash"],
                        "policy_hash": self.policy.hash, "frontier": choices,
                        "scores": {c["candidate"]["id"]: score(c) for c in choices},
                        "judgments": {k: asdict(v) for k, v in judgments.items()},
                        "judge_cost_usd": None, "fairness_applied": eligible is alternatives}
                intent = self.store.append("INTENT", data)  # Durable before dispatch.
                try:
                    # All member coordinator locks are held; do not acquire them again.
                    report = ResearchOS(e)._run(1, only_experiment=exp["id"],
                        dispatch_context={"portfolio": self.manifest["id"], "intent_hash": intent["hash"]})
                except Exception as exc:
                    self.store.append("DISPATCH_ERROR", {"operation_id": data["operation_id"], "error_type": type(exc).__name__})
                    stop = "dispatch_uncertain:reconcile"
                    break
                self._reconcile()
                if not report.results:
                    stop = "dispatch_unresolved:reconcile"
                    break
                executed += 1
            view = self._view()
            view.update(steps_this_call=executed, stop_reason=stop, elapsed_seconds=time.monotonic() - started,
                        automatically_activated_policy=False)
            atomic_write_json(self.store.root / "status.json", view)
            return view

    def export(self) -> dict:
        """Conservative chronological replay only, never imagined global outcomes."""
        with self._locked():
            view = self._view()
            nodes, prior = [], []
            for op, outcome in zip((op for op in self.store.operations() if op["settlement"] is not None), view["outcomes"]):
                d = op["intent"]
                nodes.append({"id": d["operation_id"], "candidate": d["candidate"], "available_after": list(prior),
                    "outcome": {"verdict": outcome["verdict"], "label": int(outcome["verdict"] == "PASS"),
                                "cost_units": outcome["cost_units"], "evidence_id": outcome["evidence_id"],
                                "evidence_hash": outcome["source_event_hash"]},
                    "provenance": {"portfolio_intent_hash": op["intent_hash"], "project": d["project"],
                                   "source_research_id": self.projects[d["project"]]["research_id"],
                                   "historical_label_only": True, "stale_dependencies_now": outcome["stale_dependencies"]}})
                prior.append(d["operation_id"])
            return {"schema": "sisyfus.replay.v1", "research_id": self.manifest["id"] + ":" + digest(self.manifest),
                    "family": self.manifest["family"],
                    "source_research_ids": [p["research_id"] for p in self.projects.values()],
                    "source_families": sorted({str(e.task.get("metadata", {}).get("task_family") or e.task["id"]) for e in self.engines.values()}),
                    "support": "chronological_recorded_actions_only",
                    "nodes": nodes, "source_event_head": self.store.events()[-1]["hash"],
                    "task_hash": digest(self.manifest), "unresolved_excluded": view["unresolved"],
                    "limitation": "Historical contract labels; not current validity or a counterfactual portfolio evaluation"}
