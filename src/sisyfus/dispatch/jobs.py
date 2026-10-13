"""Dispatch jobs: persisted records and the runner that drives headless agent turns.

One job is one conversation with a headless research agent in one allowlisted
project. Each turn is a detached process whose stream-json output goes to a file;
a monitor thread tails that file, so turns survive a dispatch-server restart and
are re-attached by PID. Uncertain outcomes are recorded as INTERRUPTED and are
never re-sent automatically.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import research
from .agent import build_command, first_prompt, project_line, redact
from .config import ConfigError, DispatchConfig

JOB_SCHEMA = "sisyfus.dispatch.job.v1"
RUNNING = "RUNNING"
TERMINAL_TURN = {"NEEDS_REPLY", "IDLE", "DONE", "FAILED", "STOPPED", "INTERRUPTED"}
MAX_TEXT = 8000
_STRIP_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")


class JobError(ValueError):
    """A request the operator can correct (busy project, bad input, wrong state)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _process_start(pid: int) -> str | None:
    """Process start time from ps; together with the PID it identifies one process instance."""
    try:  # fixed C locale: the string must compare equal across server restarts under any LANG
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True,
                             timeout=5, env={**os.environ, "LC_ALL": "C", "LANG": "C"}).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return out.strip() or None


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class JobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def _dir(self, job_id: str) -> Path:
        if not (job_id.startswith("j_") and len(job_id) == 18 and job_id[2:].isalnum()):
            raise JobError("NOT_FOUND", "unknown job")
        return self.root / job_id

    def path(self, job_id: str, name: str) -> Path:
        return self._dir(job_id) / name

    def create(self, project: str, brief: str) -> dict[str, Any]:
        job_id = "j_" + secrets.token_hex(8)
        now = utc_now()
        title = next((line.strip() for line in brief.splitlines() if line.strip()), "研究任务")[:80]
        job = {"schema_version": JOB_SCHEMA, "id": job_id, "project": project, "title": title,
               "brief": brief, "status": "CREATED", "created_at": now, "updated_at": now, "turns": 0,
               "session_id": None, "model": None, "pid": None, "turn_started_at": None,
               "turn_output": None, "turn_offset": 0, "last_text": "", "last_result": None,
               "cost_usd_total": 0.0, "research_ids": [], "error": None, "stop_requested": False}
        self._dir(job_id).mkdir(parents=True)
        self.save(job)
        return job

    def save(self, job: dict[str, Any]) -> None:
        with self.lock:
            job["updated_at"] = utc_now()
            target = self.path(job["id"], "job.json")
            temporary = target.with_name(".job.json.tmp")
            temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            os.replace(temporary, target)

    def load(self, job_id: str) -> dict[str, Any]:
        try:
            return json.loads(self.path(job_id, "job.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JobError("NOT_FOUND", "unknown job") from exc

    def update(self, job_id: str, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        with self.lock:
            job = self.load(job_id)
            change(job)
            self.save(job)
            return job

    def all(self) -> list[dict[str, Any]]:
        jobs = []
        for entry in self.root.iterdir() if self.root.exists() else []:
            if entry.is_dir() and entry.name.startswith("j_"):
                try:
                    jobs.append(self.load(entry.name))
                except JobError:
                    continue
        return sorted(jobs, key=lambda j: j.get("updated_at") or "", reverse=True)

    def append_event(self, job_id: str, event: dict[str, Any]) -> None:
        self.append_events(job_id, [event])

    def append_events(self, job_id: str, events: list[dict[str, Any]]) -> None:
        """Append in one write, so a failure cannot leave half a chunk to be re-appended later."""
        if not events:
            return
        with self.lock:
            path = self.path(job_id, "events.jsonl")
            seq = sum(1 for _ in path.open(encoding="utf-8")) if path.exists() else 0
            now = utc_now()
            lines = [json.dumps({"seq": seq + i + 1, "ts": now, **event}, ensure_ascii=False) for i, event in enumerate(events)]
            with path.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")

    def events(self, job_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        try:
            lines = [line for line in self.path(job_id, "events.jsonl").read_text(encoding="utf-8").split("\n") if line]
        except OSError:
            return []
        out = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


class JobRunner:
    def __init__(self, config: DispatchConfig, store: JobStore, *, poll_interval: float = 0.5) -> None:
        self.config = config
        self.store = store
        self.poll_interval = poll_interval
        self._procs: dict[str, subprocess.Popen[bytes]] = {}
        self._launch_lock = threading.Lock()

    # ---------- operator actions ----------
    def start(self, project: str, brief: str) -> dict[str, Any]:
        brief = (brief or "").strip()
        if not brief:
            raise JobError("EMPTY", "请写下研究问题")
        if len(brief) > MAX_TEXT:
            raise JobError("TOO_LONG", "研究问题太长")
        self._project_dir(project)
        with self._launch_lock:
            self._check_capacity(project, None)
            job = self.store.create(project, brief)
            self.store.append_event(job["id"], {"kind": "user", "text": brief})
            try:
                return self._launch(job["id"], first_prompt(brief), resume=False)
            except JobError as exc:
                self._close(job["id"], "FAILED", str(exc))
                raise

    def reply(self, job_id: str, text: str) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise JobError("EMPTY", "回复不能为空")
        if len(text) > MAX_TEXT:
            raise JobError("TOO_LONG", "回复太长")
        with self._launch_lock:
            job = self.store.load(job_id)
            if job["status"] == RUNNING:
                raise JobError("RUNNING", "这一轮还在运行，请等它结束或先停止")
            if not job.get("session_id"):
                raise JobError("NO_SESSION", "这个任务没有可以继续的会话")
            self._check_capacity(job["project"], job_id)
            launched = self._launch(job_id, text, resume=True)
            self.store.append_event(job_id, {"kind": "user", "text": text})
            return launched

    def stop(self, job_id: str) -> dict[str, Any]:
        job = self.store.update(job_id, lambda j: j.__setitem__("stop_requested", j["status"] == RUNNING))
        if job["status"] != RUNNING:
            raise JobError("NOT_RUNNING", "这个任务当前没有在运行")
        proc = self._procs.get(job_id)
        if proc is not None or self._is_our_agent(job):
            self._signal(job.get("pid"), signal.SIGTERM)
            threading.Thread(target=self._kill_later, args=(job, proc), daemon=True).start()
        return job

    def recover(self) -> None:
        """Re-attach turns that kept running across a server restart; close out the rest."""
        for job in self.store.all():
            if job["status"] != RUNNING:
                continue
            try:
                if self._is_our_agent(job):
                    self._watch(job["id"], None)
                else:
                    self._monitor(job["id"], None, watch_pid=False)
            except Exception as exc:  # one damaged job must not keep the server from starting
                self._close(job["id"], "FAILED", f"恢复失败：{exc}")

    # ---------- internals ----------
    def _project_dir(self, project: str) -> Path:
        path = self.config.project_path(project)
        if not path.is_dir():
            raise JobError("PROJECT_MISSING", "这个工程目录已不存在")
        return path

    def _check_capacity(self, project: str, job_id: str | None) -> None:
        running = [j for j in self.store.all() if j["status"] == RUNNING and j["id"] != job_id]
        if any(j["project"] == project for j in running):
            raise JobError("PROJECT_BUSY", "这个工程已有研究在运行，同一工程一次只运行一个")
        if len(running) >= self.config.max_concurrent:
            raise JobError("BUSY", f"同时最多运行 {self.config.max_concurrent} 个研究")

    def _launch(self, job_id: str, prompt: str, *, resume: bool) -> dict[str, Any]:
        job = self.store.load(job_id)
        project = self._project_dir(job["project"])
        turn = int(job["turns"]) + 1
        output = self.store.path(job_id, f"turn-{turn}.jsonl")
        stderr = self.store.path(job_id, f"turn-{turn}.stderr")
        env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
        env.update({"SISYFUS_AUTO_OPEN": "0", "SISYFUS_DISPATCH_JOB": job_id})
        command = build_command(self.config, resume_session=job.get("session_id") if resume else None)
        with output.open("wb") as out, stderr.open("wb") as err:
            try:
                proc = subprocess.Popen(command, cwd=project, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                        env=env, start_new_session=True, close_fds=True)
            except OSError as exc:
                raise JobError("AGENT_UNAVAILABLE", f"无法启动研究代理：{exc.strerror or exc}") from exc
        try:
            assert proc.stdin is not None
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass
        self._procs[job_id] = proc
        self._keep_awake(proc.pid)
        started = _process_start(proc.pid)

        def mark(j: dict[str, Any]) -> None:
            j.update({"status": RUNNING, "turns": turn, "pid": proc.pid, "pid_started": started,
                      "turn_started_at": utc_now(), "turn_output": output.name, "turn_offset": 0,
                      "error": None, "stop_requested": False, "last_result": None})
        job = self.store.update(job_id, mark)
        self._watch(job_id, proc)
        return job

    def _watch(self, job_id: str, proc: subprocess.Popen[bytes] | None) -> None:
        threading.Thread(target=self._monitor, args=(job_id, proc), daemon=True,
                         name=f"dispatch-{job_id}").start()

    def _monitor(self, job_id: str, proc: subprocess.Popen[bytes] | None, *, watch_pid: bool = True) -> None:
        job = self.store.load(job_id)
        output = self.store.path(job_id, job["turn_output"] or "missing.jsonl")
        offset = int(job.get("turn_offset") or 0)
        result: dict[str, Any] | None = None
        linked_at, failures = 0.0, 0
        while True:
            try:
                if proc is not None:
                    alive = proc.poll() is None
                else:
                    alive = watch_pid and self._is_our_agent(job)
                offset, found = self._drain(job_id, output, offset)
                result = found or result
                if not alive or time.monotonic() - linked_at > 5:
                    self._link_runs(job_id)
                    linked_at = time.monotonic()
                failures = 0
            except Exception:  # transient I/O (e.g. fd exhaustion): back off and retry
                failures += 1
                # A process we still hold is never declared gone; only an unreachable re-attached turn gives up.
                alive = (proc is not None and proc.poll() is None) or failures < 20
            if not alive:
                break
            time.sleep(min(5.0, self.poll_interval * (1 + failures)))
        self._procs.pop(job_id, None)
        returncode = proc.returncode if proc is not None else None
        try:
            self._finish(job_id, result, returncode)
        except Exception as exc:
            self._close(job_id, "FAILED", f"无法读取这一轮的结果：{exc}")

    def _drain(self, job_id: str, output: Path, offset: int) -> tuple[int, dict[str, Any] | None]:
        try:
            with output.open("rb") as handle:
                handle.seek(offset)
                chunk = handle.read()
        except FileNotFoundError:
            return offset, None
        complete = chunk[: chunk.rfind(b"\n") + 1]
        if not complete:
            return offset, None
        result = None
        updates: dict[str, Any] = {}
        pending: list[dict[str, Any]] = []
        # Split on the newline byte only: JSON strings may carry raw U+2028/U+2029.
        for raw in complete.split(b"\n"):
            if not raw.strip():
                continue
            for event in project_line(raw.decode("utf-8", errors="replace")):
                kind = event["kind"]
                if kind == "session":
                    updates["session_id"] = event.get("session_id") or updates.get("session_id")
                    updates["model"] = event.get("model")
                    continue
                pending.append(event)
                if kind == "text":
                    updates["last_text"] = event["text"]
                elif kind == "result":
                    result = event
                    if event.get("session_id"):
                        updates["session_id"] = event["session_id"]
        new_offset = offset + len(complete)
        self.store.append_events(job_id, pending)

        def apply(job: dict[str, Any]) -> None:
            for key, value in updates.items():
                if value is not None:
                    job[key] = value
            job["turn_offset"] = new_offset
        self.store.update(job_id, apply)
        return new_offset, result

    def _link_runs(self, job_id: str) -> None:
        job = self.store.load(job_id)
        since = job.get("turn_started_at") or job["created_at"]
        try:
            runs = research.list_runs(self.config.project_path(job["project"]), limit=50)
        except Exception:  # a project read problem must never stop the monitor
            return
        found = [r["research_id"] for r in runs if str(r.get("created_at") or "") >= since[:19]]
        if any(rid not in job["research_ids"] for rid in found):
            self.store.update(job_id, lambda j: j.__setitem__(
                "research_ids", list(dict.fromkeys([*j["research_ids"], *found]))))

    def _finish(self, job_id: str, result: dict[str, Any] | None, returncode: int | None) -> None:
        job = self.store.load(job_id)
        try:
            project: Path | None = self.config.project_path(job["project"])
        except ConfigError:
            project = None
        if job.get("stop_requested"):
            status, error = "STOPPED", None
        elif result is not None and result.get("ok"):
            status, error = (self._settled_status(job, project) if project else "IDLE"), None
        elif result is not None:
            reason = {"error_max_budget_usd": f"本轮达到花费上限 ${self.config.max_budget_usd:g}",
                      "error_max_turns": "本轮达到步数上限",
                      "error_during_execution": "代理执行出错"}.get(str(result.get("subtype")))
            status, error = "FAILED", (reason or f"代理本轮未正常结束（{result.get('subtype') or 'error'}）") + "；可以回复让它继续"
        elif returncode not in (None, 0):
            status, error = "FAILED", self._stderr_tail(job) or f"代理退出码 {returncode}"
        else:
            status, error = "INTERRUPTED", "这一轮的结果未知（进程已不在），没有自动重发"
        self._close(job_id, status, error, result)

    def _close(self, job_id: str, status: str, error: str | None, result: dict[str, Any] | None = None) -> None:
        def close(j: dict[str, Any]) -> None:
            # total_cost_usd is cumulative over a resumed session: add only this turn's increase.
            cost = (result or {}).get("cost_usd")
            if isinstance(cost, (int, float)):
                same = j.get("cost_session") and j.get("cost_session") == j.get("session_id")
                previous = float(j.get("session_cost_usd") or 0.0) if same else 0.0
                increase = float(cost) - previous if float(cost) >= previous else float(cost)  # a lower value is a fresh counter
                j["cost_usd_total"] = round(float(j.get("cost_usd_total") or 0.0) + increase, 4)
                j["session_cost_usd"], j["cost_session"] = float(cost), j.get("session_id")
            j.update({"status": status, "error": error, "pid": None, "pid_started": None,
                      "stop_requested": False, "last_result": result})
            if result and result.get("text"):
                j["last_text"] = result["text"]
        self.store.update(job_id, close)
        self.store.append_event(job_id, {"kind": "status", "status": status, "error": error})

    def _settled_status(self, job: dict[str, Any], project: Path) -> str:
        live = research.activity(project) or {}
        if str(live.get("status") or "").upper() == "NEEDS_USER":
            return "NEEDS_REPLY"
        runs = []
        for rid in job.get("research_ids") or []:
            try:
                runs.append(research.run_summary(project, rid))
            except LookupError:
                continue
        if runs and all(run["final"] for run in runs):
            return "DONE"
        return "IDLE"

    def _stderr_tail(self, job: dict[str, Any]) -> str:
        try:
            text = self.store.path(job["id"], f"turn-{job['turns']}.stderr").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return redact(text.strip()[-500:])

    def _is_our_agent(self, job: dict[str, Any]) -> bool:
        """The recorded PID still belongs to the agent turn we launched (guards against PID reuse)."""
        pid = job.get("pid")
        if not _pid_alive(pid):
            return False
        if job.get("pid_started"):
            return _process_start(pid) == job["pid_started"]
        try:
            argv = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True,
                                  text=True, timeout=5).stdout.split()
        except (OSError, subprocess.SubprocessError):
            return False
        return bool(argv) and Path(argv[0]).name == Path(self.config.agent_command[0]).name and "stream-json" in argv

    @staticmethod
    def _signal(pid: int | None, sig: int) -> None:
        if pid:
            try:
                os.killpg(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass

    def _kill_later(self, job: dict[str, Any], proc: subprocess.Popen[bytes] | None) -> None:
        time.sleep(8)
        if (proc.poll() is None) if proc is not None else self._is_our_agent(job):
            self._signal(job.get("pid"), signal.SIGKILL)

    @staticmethod
    def _keep_awake(pid: int) -> None:
        """Keep the Mac from idle-sleeping while a turn runs (macOS caffeinate, best effort)."""
        caffeinate = shutil.which("caffeinate")
        if caffeinate:
            try:
                subprocess.Popen([caffeinate, "-i", "-w", str(pid)], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError:
                pass
