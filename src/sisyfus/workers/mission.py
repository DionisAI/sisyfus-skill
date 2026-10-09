from __future__ import annotations

import json
import os
import re
import shutil
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..autonomy.models import (AssuranceLevel, CapabilityResult, Decision, OpportunitySignal,
                               VerificationResult, Verdict, stable_id)
from ..autonomy.policy import AutonomyPolicy, CapabilityRegistry
from ..autonomy.runtime import AutonomousRuntime
from ..autonomy.store import AutonomyStore
from ..autonomy.supervisor import AutonomousSupervisor, SupervisorConfig
from ..research_v2.verifier import classify_observation
from .claude_code import ClaudeCodeDriver
from .codex import CodexDriver
from .journal import DispatchBlocked, Journal
from .protocol import Receipt, Request, bounded, digest, environment, redact
from .transport import Process

IGNORED = {".git", ".sisyfus", "__pycache__", ".pytest_cache", ".venv", "node_modules"}


def files(root: Path) -> dict[str, str]:
    """Bounded content snapshot; links are rejected, never followed."""
    if not root.is_dir() or root.is_symlink():
        raise ValueError("candidate snapshot directory is missing or a symlink")
    result: dict[str, str] = {}
    total = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in list(dirs):
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError("candidate directory symlink rejected")
            if name in IGNORED:
                dirs.remove(name)
        for name in names:
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("candidate must contain regular files only")
            total += path.stat().st_size
            if total > 20_000_000 or len(result) >= 4000:
                raise ValueError("candidate snapshot exceeds configured pilot limit")
            import hashlib
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def copy_candidate(source: Path, destination: Path) -> str:
    manifest = files(source)
    destination.mkdir(parents=True, exist_ok=False)
    for name in manifest:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    if files(source) != manifest or files(destination) != manifest:
        raise ValueError("candidate changed during snapshot")
    return digest(manifest)


def validate_tasks(tasks: Any, spec: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 32:
        raise ValueError("plan requires 1..32 tasks")
    normalized = []
    ids = set()
    for raw in tasks:
        if not isinstance(raw, dict) or set(raw) - {"id", "objective", "driver", "check", "depends_on", "max_attempts"}:
            raise ValueError("unknown task fields; agents cannot change policies or evaluators")
        task = {**raw, "depends_on": raw.get("depends_on", []), "max_attempts": raw.get("max_attempts", 2)}
        ident = task.get("id")
        if not isinstance(ident, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", ident) or ident in ids or ident == "planner":
            raise ValueError("invalid or duplicate task id")
        if task.get("driver") not in spec["drivers"] or task.get("check") not in spec["checks"]:
            raise ValueError("plan selected an unapproved driver/check")
        if not isinstance(task.get("objective"), str) or not 1 <= len(task["objective"]) <= 20000:
            raise ValueError("task objective missing or too large")
        if type(task["max_attempts"]) is not int or not 1 <= task["max_attempts"] <= spec["max_attempts"]:
            raise ValueError("task retry budget exceeds mission authorization")
        deps = task["depends_on"]
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps) or len(deps) != len(set(deps)):
            raise ValueError("invalid task dependencies")
        normalized.append(task)
        ids.add(ident)
    if set(spec.get("required_checks", spec["checks"])) - {t["check"] for t in normalized}:
        raise ValueError("plan omits a mandatory operator-approved acceptance check")
    graph = {t["id"]: t["depends_on"] for t in normalized}
    visiting, visited = set(), set()

    def visit(node: str) -> None:
        if node not in graph or node in visiting:
            raise ValueError("unknown dependency or dependency cycle")
        if node in visited:
            return
        visiting.add(node)
        for dep in graph[node]:
            visit(dep)
        visiting.remove(node)
        visited.add(node)
    for ident in graph:
        visit(ident)
    return normalized


def load_spec(path: Path) -> dict[str, Any]:
    spec = json.loads(path.read_text())
    if not isinstance(spec, dict):
        raise ValueError("mission spec must be an object")
    allowed = {"objective", "source", "drivers", "checks", "tasks", "planner", "max_calls", "parallelism",
               "timeout", "max_attempts", "max_turns", "validation_kind", "required_checks"}
    if set(spec) - allowed:
        raise ValueError("unknown mission specification field")
    spec = {"max_calls": 8, "parallelism": 2, "timeout": 300, "max_attempts": 3,
            "max_turns": 8, "validation_kind": "native_cli_unvalidated", **spec}
    if not isinstance(spec.get("objective"), str) or not spec["objective"].strip():
        raise ValueError("mission objective required")
    for name, high in (("max_calls", 1000), ("parallelism", 8), ("max_attempts", 20), ("max_turns", 100)):
        if type(spec[name]) is not int:
            raise ValueError(f"{name} must be an integer")
        bounded(spec[name], 1, high, name)
    bounded(spec["timeout"], .1, 7200, "timeout")
    source = Path(spec["source"]).expanduser().resolve(strict=True)
    if not source.is_dir():
        raise ValueError("source must be a directory")
    spec["source"] = str(source)
    if not isinstance(spec.get("drivers"), dict) or not spec["drivers"] or set(spec["drivers"]) - {"codex", "claude"}:
        raise ValueError("only native Codex and Claude drivers are supported")
    for name, config in spec["drivers"].items():
        if set(config) - {"model", "command", "env_names"} or not isinstance(config.get("model"), str) or not config["model"].strip():
            raise ValueError("each driver requires an explicit model")
        argv = config.setdefault("command", ["codex" if name == "codex" else "claude"])
        if not isinstance(argv, list) or not argv or any(not isinstance(a, str) or not a or "\0" in a for a in argv):
            raise ValueError("driver command must be a nonempty argv array")
        environment(tuple(config.setdefault("env_names", [])))
    if not isinstance(spec.get("checks"), dict) or not spec["checks"]:
        raise ValueError("preapproved checks required")
    for check in spec["checks"].values():
        if set(check) - {"argv", "code_hashes", "contract", "timeout"}:
            raise ValueError("unknown check field")
        argv = check.get("argv")
        if not isinstance(argv, list) or not argv or any(not isinstance(a, str) or not a for a in argv) or "{candidate}" not in argv:
            raise ValueError("check argv must include a separate {candidate} argument")
        if not check.get("code_hashes") or not check.get("contract", {}).get("pass_if"):
            raise ValueError("check code hashes and explicit PASS contract are required")
        if check["contract"].get("kind") == "manual" or (check["contract"].get("metadata") or {}).get("nonzero_exit_is_valid"):
            raise ValueError("manual or nonzero-exit success contracts are not supported")
        for code, expected in check["code_hashes"].items():
            p = Path(code)
            if not p.is_absolute() or p.is_symlink() or not p.is_file() or p.resolve().is_relative_to(source):
                raise ValueError("trusted measurement code must be outside the mutable project")
            import hashlib
            if hashlib.sha256(p.read_bytes()).hexdigest() != expected:
                raise ValueError("measurement code hash mismatch")
        bounded(check.get("timeout", 30), .05, 300, "check timeout")
    required = spec.setdefault("required_checks", sorted(spec["checks"]))
    if not isinstance(required, list) or not required or any(not isinstance(c, str) for c in required) or len(required) != len(set(required)) or set(required) - set(spec["checks"]):
        raise ValueError("required_checks must be a nonempty subset of approved checks")
    if spec.get("planner") is not None and spec["planner"] not in spec["drivers"]:
        raise ValueError("unapproved planner driver")
    if spec.get("tasks"):
        spec["tasks"] = validate_tasks(spec["tasks"], spec)
    elif not spec.get("planner"):
        raise ValueError("supply tasks or an approved native planner")
    spec["source_hash"] = digest(files(source))
    return spec


class Mission:
    def __init__(self, directory: Path, spec: dict[str, Any] | None = None):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.store = AutonomyStore(self.directory / "autonomy.sqlite3")
        self.journal = Journal(self.store)
        if spec is not None:
            source = Path(spec["source"])
            if self.directory.is_relative_to(source) or source.is_relative_to(self.directory):
                raise ValueError("controller and source directories must be disjoint")
            self.journal.bind(spec)
        self.spec = self.journal.spec()
        self.drivers = {name: (CodexDriver if name == "codex" else ClaudeCodeDriver)(
            tuple(c["command"]), env_names=tuple(c.get("env_names", []))) for name, c in self.spec["drivers"].items()}
        self.registry = CapabilityRegistry()
        self.registry.register(NativeCapability(self), NativeVerifier(self))
        self.runtime = AutonomousRuntime(self.store, self.registry, workspace=self.directory,
            policy=AutonomyPolicy(allowed_capabilities=frozenset({"workers.execute"})), retry_base_seconds=.1)
        self.stop = threading.Event()
        self.versions: dict[str, Any] = {}
        self.errors: list[str] = []

    def doctor(self) -> dict[str, Any]:
        self.versions = {name: driver.probe() for name, driver in self.drivers.items()}
        return self.versions

    def tasks(self) -> list[dict[str, Any]]:
        if self.spec.get("tasks"):
            return self.spec["tasks"]
        with self.store._transaction(immediate=False) as db:
            row = db.execute("SELECT value FROM metadata WHERE key='native_worker_plan'").fetchone()
        return json.loads(row[0]) if row else []

    def prepare(self) -> None:
        tasks = self.tasks()
        if not tasks:
            name = self.spec["planner"]
            prompt = ("Return ONLY a JSON object with a tasks array. Each task has id (lowercase slug), objective, "
                      "driver, check, depends_on (task IDs), max_attempts. Do not execute work or change acceptance criteria. "
                      "Use at most 8 tasks, cover every required_check, and only use authorized driver/check IDs below.\n" + json.dumps({
                          "goal": self.spec["objective"], "drivers": list(self.drivers),
                          "checks": list(self.spec["checks"]), "required_checks": self.spec["required_checks"], "max_attempts": self.spec["max_attempts"]}))
            cwd = self.directory / "planner"
            cwd.mkdir(exist_ok=True)
            request = Request("planner", prompt, str(cwd), self.spec["drivers"][name]["model"],
                              timeout=self.spec["timeout"], max_turns=self.spec["max_turns"])
            receipt = self.journal.reserve("planner", "planner", digest(asdict(request)))
            if receipt is None:
                try:
                    r = self.drivers[name].run(request, lambda k, d: self.journal.event("planner", k, d),
                                               lambda: self.journal.controls("planner"))
                except Exception as exc:
                    r = Receipt("UNKNOWN", error=f"planner transport: {type(exc).__name__}")
                receipt = self.journal.complete("planner", r.as_dict())
            if receipt["status"] != "COMPLETED":
                raise DispatchBlocked("native planner has no successful terminal receipt")
            raw = json.loads(receipt["output"])
            if not isinstance(raw, dict) or set(raw) != {"tasks"}:
                raise ValueError("planner must return only a tasks object")
            tasks = validate_tasks(raw["tasks"], self.spec)
            with self.store._transaction() as db:
                db.execute("INSERT OR IGNORE INTO metadata VALUES('native_worker_plan',?)", (json.dumps(tasks),))
                self.journal._event(db, "plan_admitted", "mission", {"tasks": tasks, "source_run": "planner"})
        # Idempotent per-task admission; restart completes a partially admitted DAG.
        for task in tasks:
            opportunity, _ = self.store.submit_opportunity(OpportunitySignal(
                source="native-workers", title=task["id"], objective=task["objective"],
                dedupe_key="native-task:" + task["id"]))
            self.store.admit_opportunity(opportunity["id"], max_attempts=task["max_attempts"],
                                        context={"native_task": task["id"]})

    def task(self, ident: str) -> dict[str, Any]:
        return next(t for t in self.tasks() if t["id"] == ident)

    def continuations(self) -> dict[str, dict[str, Any]]:
        return {c["context"]["native_task"]: c for c in self.store.list_continuations() if "native_task" in c["context"]}

    def evidence_current(self, ident: str, seen: set[str] | None = None) -> bool:
        seen = set() if seen is None else seen
        if ident in seen:
            return False
        seen = seen | {ident}
        cont = self.continuations().get(ident)
        if not cont or cont["state"] != "SUCCEEDED":
            return False
        evidence = self.store.latest_evidence(cont["id"])
        if not evidence or evidence["verdict"] != "PASS":
            return False
        payload = evidence["payload"].get("evidence", {})
        try:
            if digest(files(Path(payload["candidate"]))) != payload["candidate_hash"]:
                return False
            check = self.spec["checks"][self.task(ident)["check"]]
            if not check_intact(check) or payload.get("check_hash") != digest(check):
                return False
            proofs = payload.get("dependencies", {})
            for dep in self.task(ident)["depends_on"]:
                upstream = self.continuations().get(dep)
                if not upstream or not self.evidence_current(dep, seen):
                    return False
                if proofs.get(dep) != self.store.latest_evidence(upstream["id"])["id"]:
                    return False
            return True
        except (KeyError, OSError, ValueError):
            return False

    def planner(self, continuation: dict[str, Any], context: dict[str, Any]) -> Decision:
        ident = continuation["context"]["native_task"]
        task = self.task(ident)
        if self.journal.paused():
            return Decision("WAIT", "operator paused new dispatch", wait_seconds=.5)
        runs = self.journal.runs()
        if any(r["status"] == "UNKNOWN" or (r["status"] == "IN_FLIGHT" and r["continuation_id"] == continuation["id"]) for r in runs):
            return Decision("BLOCK", "unknown worker execution requires reconciliation")
        proofs = {}
        for dep in task["depends_on"]:
            upstream = self.continuations().get(dep)
            if not upstream or upstream["state"] in {"READY", "WAITING", "RUNNING", "VERIFYING"}:
                return Decision("WAIT", f"waiting for dependency {dep}", wait_seconds=.2)
            if not self.evidence_current(dep):
                return Decision("BLOCK", f"dependency {dep} lacks current verified evidence")
            proofs[dep] = self.store.latest_evidence(upstream["id"])["id"]
        if self.spec.get("max_calls") is not None and len(runs) >= self.spec["max_calls"]:
            return Decision("BLOCK", "mission native-call budget exhausted")
        previous = context.get("latest_evidence")
        prompt = (f"Task: {task['objective']}\nWork only inside this candidate directory. "
                  "Do not change tests, evaluators, credentials or control state. Your report cannot certify success.\n")
        if previous:
            prompt += "Independent previous verification (use it to repair the candidate):\n" + json.dumps(redact(previous["payload"]))[:16000]
        if proofs:
            prompt += "Verified dependencies are available under inputs/<task_id>.\n"
        key = stable_id("native", continuation["id"], continuation["attempt_count"] + 1)
        return Decision("EXECUTE", "verified prerequisites satisfied; run bounded candidate attempt",
            capability="workers.execute", arguments={"task_id": ident, "continuation_id": continuation["id"],
            "prompt": prompt, "dependencies": proofs}, risk_tier=1, verifier_id="workers.locked-check",
            idempotency_key=key, terminal_on_pass=True)

    def run(self, *, max_cycles: int = 1000) -> dict[str, Any]:
        from ..updater import InstallLayout, register_project
        from .installation_guard import running_installation
        layout = InstallLayout.discover()
        register_project(self.directory, layout=layout)
        with running_installation(layout):
            return self._run(max_cycles=max_cycles)

    def _run(self, *, max_cycles: int = 1000) -> dict[str, Any]:
        if type(max_cycles) is not int or not 1 <= max_cycles <= 1_000_000:
            raise ValueError("invalid supervisor cycle budget")
        if not all(d["available"] for d in self.doctor().values()):
            raise DispatchBlocked("native CLI preflight failed; run doctor")
        self.journal.reconcile_expired()
        self.prepare()
        threads = []
        for index in range(self.spec["parallelism"]):
            supervisor = AutonomousSupervisor(self.runtime, planner=self.planner,
                config=SupervisorConfig(worker_id=f"native-{os.getpid()}-{index}", idle_sleep_seconds=.05))
            def loop(s: AutonomousSupervisor = supervisor) -> None:
                for _ in range(max_cycles):
                    if self.stop.is_set():
                        break
                    try:
                        s.cycle()
                    except Exception as exc:
                        error = f"{type(exc).__name__}: {exc}"
                        self.errors.append(error)
                        with self.store._transaction() as db:
                            self.journal._event(db, "controller_error", "mission", {"error": error})
                        self.stop.set()
                        break
                    states = [c["state"] for c in self.continuations().values()]
                    if states and all(x in {"SUCCEEDED", "FAILED", "BLOCKED", "CANCELLED", "EXHAUSTED"} for x in states):
                        break
                    self.stop.wait(.05)
            thread = threading.Thread(target=loop, daemon=False)
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        nodes = []
        for ident, cont in self.continuations().items():
            evidence = self.store.latest_evidence(cont["id"])
            nodes.append({"id": ident, "objective": cont["objective"], "state": cont["state"],
                          "attempts": cont["attempt_count"], "depends_on": self.task(ident)["depends_on"],
                          "driver": self.task(ident)["driver"], "verdict": evidence["verdict"] if evidence else "UNVERIFIED",
                          "evidence_id": evidence["id"] if evidence else None,
                          "verification": evidence["payload"] if evidence else None,
                          "stale": cont["state"] == "SUCCEEDED" and not self.evidence_current(ident)})
        runs = self.journal.runs()
        for run in runs:
            driver = self.spec.get("planner") if run["task_id"] == "planner" else self.task(run["task_id"])["driver"]
            run["driver"] = driver
            run["controls"] = list(self.drivers[driver].controls) if driver in self.drivers else []
        return {"objective": self.spec["objective"], "paused": self.journal.paused(), "nodes": nodes, "runs": runs,
                "native_call_reservations": len(runs), "max_calls": self.spec["max_calls"],
                "unresolved": [r["key"] for r in runs if r["status"] in {"UNKNOWN", "IN_FLIGHT"}],
                "all_verified": not self.errors and not any(r["status"] in {"UNKNOWN", "IN_FLIGHT"} for r in runs) and bool(nodes) and len(nodes) == len(self.tasks()) and all(n["state"] == "SUCCEEDED" and not n["stale"] for n in nodes),
                "controller_errors": self.errors,
                "validation_kind": self.spec["validation_kind"], "provider_cost_usd": None,
                "versions": self.versions}


def check_intact(check: dict[str, Any]) -> bool:
    import hashlib
    return all(not Path(p).is_symlink() and Path(p).is_file() and
               hashlib.sha256(Path(p).read_bytes()).hexdigest() == sha for p, sha in check["code_hashes"].items())


class NativeCapability:
    name = "workers.execute"
    risk_tier = 1
    # Only the journal wrapper is replay-safe: it reuses receipts, NEVER resends unknown work.
    replay_safe = True
    description = "Run a bounded native agent in a separate candidate snapshot"

    def __init__(self, mission: Mission):
        self.mission = mission

    def execute(self, arguments: dict[str, Any], *, idempotency_key: str) -> CapabilityResult:
        m = self.mission
        task = m.task(arguments["task_id"])
        cont = m.store.get_continuation(arguments["continuation_id"])
        if cont["context"].get("native_task") != task["id"]:
            raise ValueError("task/continuation mismatch")
        base = m.directory / "attempts" / idempotency_key
        candidate = base / "candidate"
        request = {"arguments": arguments, "spec": digest(m.spec), "candidate": str(candidate)}
        try:
            cached = m.journal.reserve(idempotency_key, task["id"], digest(request), continuation_id=cont["id"],
                                       lease_token=cont["lease_token"])
        except DispatchBlocked as exc:
            return CapabilityResult("UNKNOWN", {"run_key": idempotency_key}, error=str(exc))
        if cached is None:
            try:
                source = Path(m.spec["source"])
                older = [r for r in m.journal.runs() if r["task_id"] == task["id"] and r["key"] != idempotency_key
                         and r["receipt"] and r["receipt"].get("candidate")]
                expected_source = m.spec["source_hash"]
                if older:
                    source = Path(older[-1]["receipt"]["candidate"])
                    expected_source = older[-1]["receipt"]["candidate_hash"]
                if digest(files(source)) != expected_source:
                    raise ValueError("candidate input changed since its pinned snapshot")
                copy_candidate(source, candidate)
                for dep in task["depends_on"]:
                    upstream = m.store.latest_evidence(m.continuations()[dep]["id"])["payload"]["evidence"]
                    dest = candidate / "inputs" / dep
                    if dest.exists():
                        import subprocess
                        subprocess.run(["/usr/bin/trash", str(dest.resolve())], check=True,
                                       capture_output=True, text=True)
                    copy_candidate(Path(upstream["candidate"]), dest)
                driver = m.drivers[task["driver"]]
                envelope = Request(task["id"], arguments["prompt"], str(candidate),
                    m.spec["drivers"][task["driver"]]["model"], mode="workspace-write", timeout=m.spec["timeout"],
                    max_turns=m.spec["max_turns"])
                m.journal.event(idempotency_key, "driver", {"driver": task["driver"], "model": envelope.model,
                    "version": m.versions.get(task["driver"], {}).get("version"), "controls": list(driver.controls)})
                receipt = driver.run(envelope, lambda k, d: m.journal.event(idempotency_key, k, d),
                                     lambda: m.journal.controls(idempotency_key)).as_dict()
                artifact = base / "artifact"
                sha = copy_candidate(candidate, artifact)
                receipt.update(candidate=str(artifact), candidate_hash=sha, dependencies=arguments["dependencies"])
            except Exception as exc:
                receipt = Receipt("UNKNOWN", error=f"worker boundary: {type(exc).__name__}: {exc}").as_dict()
            cached = m.journal.complete(idempotency_key, receipt)
        return CapabilityResult(cached["status"], {**cached, "run_key": idempotency_key})


class NativeVerifier:
    verifier_id = "workers.locked-check"

    def __init__(self, mission: Mission):
        self.mission = mission

    def verify(self, context: dict[str, Any], decision: Decision, result: CapabilityResult) -> VerificationResult:
        m = self.mission
        task = m.task(decision.arguments["task_id"])
        check = m.spec["checks"][task["check"]]
        data = dict(result.observation)
        observation: dict[str, Any] = {}
        if result.status != "COMPLETED":
            return VerificationResult(Verdict.ERROR, self.verifier_id, "native execution did not complete; no success inference", evidence=data)
        if not check_intact(check) or digest(files(Path(data["candidate"]))) != data["candidate_hash"]:
            return VerificationResult(Verdict.INVALID, self.verifier_id, "measurement or candidate integrity changed", evidence=data)
        for dep, expected in data.get("dependencies", {}).items():
            if not m.evidence_current(dep) or m.store.latest_evidence(m.continuations()[dep]["id"])["id"] != expected:
                return VerificationResult(Verdict.INVALID, self.verifier_id, "upstream evidence became stale", evidence=data)
        argv = [str(data["candidate"]) if a == "{candidate}" else a for a in check["argv"]]
        proc = Process(argv, cwd=str(m.directory), env={**environment(), "PYTHONDONTWRITEBYTECODE": "1"},
                       timeout=check.get("timeout", 30), max_bytes=1_000_000)
        try:
            proc.send_bytes(b"", close=True)
            messages = []
            while True:
                try:
                    message = proc.receive()
                except EOFError:
                    break
                if message is not None:
                    messages.append(message)
            code = proc.wait()
            if len(messages) != 1:
                raise ValueError("measurement must emit exactly one JSON object")
            observation = messages[0]
            # Native or evaluator-provided JSON cannot spoof process outcome.
            observation["execution"] = {"exit_code": code, "timed_out": False}
        except Exception as exc:
            observation = {"execution": {"error": f"{type(exc).__name__}: {exc}"}}
        finally:
            proc.close()
        if not check_intact(check) or digest(files(Path(data["candidate"]))) != data["candidate_hash"]:
            return VerificationResult(Verdict.INVALID, self.verifier_id, "input or evaluator changed during verification", evidence=data)
        classified = classify_observation(check["contract"], observation)
        return VerificationResult(classified["status"], self.verifier_id, classified["summary"], assurance=AssuranceLevel.A,
            evidence={"candidate": data["candidate"], "candidate_hash": data["candidate_hash"],
                      "dependencies": data.get("dependencies", {}), "check_hash": digest(check),
                      "run_key": data["run_key"], "measurement": redact(observation), "classification": classified})
