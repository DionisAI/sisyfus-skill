from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model_policy import estimate_tokens_from_chars
from .review import load_review_context
from .session import load_recent_session_context
from .utils import run_process, truncate_middle, write_json


@dataclass
class AgentResult:
    role: str
    round_index: int
    adapter: str
    prompt_path: str
    stdout_path: str | None
    stderr_path: str | None
    exit_code: int
    elapsed_seconds: float
    prompt_chars: int
    output_chars: int
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "round_index": self.round_index,
            "adapter": self.adapter,
            "prompt_path": self.prompt_path,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "exit_code": self.exit_code,
            "elapsed_seconds": self.elapsed_seconds,
            "prompt_chars": self.prompt_chars,
            "output_chars": self.output_chars,
            "metadata": self.metadata,
        }


def read_context(root: Path, goal: dict[str, Any], *, max_chars: int = 50000) -> str:
    chunks: list[str] = []
    context_cfg = goal.get("context", {}) or {}
    session_policy = goal.get("session_policy", {}) or {}

    for rel in context_cfg.get("read_memory", []) + context_cfg.get("extra_files", []):
        path = (root / rel).resolve() if not Path(rel).is_absolute() else Path(rel)
        try:
            if path.exists() and path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
                chunks.append(f"\n--- FILE: {rel} ---\n" + truncate_middle(text, max(1000, max_chars // 5)))
        except OSError as exc:
            chunks.append(f"\n--- FILE: {rel} unavailable: {exc} ---\n")

    read_human_review = bool(context_cfg.get("read_human_review", session_policy.get("read_human_review", True)))
    if read_human_review:
        review_chars = int(context_cfg.get("human_review_max_chars") or session_policy.get("human_review_max_chars") or 10000)
        review_context = load_review_context(root, max_chars=review_chars)
        if review_context.strip():
            chunks.append("\n--- HUMAN REVIEW / GUIDANCE CONTEXT ---\n" + review_context)

    read_recent = bool(context_cfg.get("read_recent_sessions", session_policy.get("read_recent_sessions", True)))
    if read_recent:
        limit = int(context_cfg.get("recent_session_limit") or session_policy.get("recent_session_limit") or 3)
        session_chars = int(session_policy.get("session_context_max_chars") or 12000)
        recent = load_recent_session_context(root, limit=limit, max_chars=session_chars)
        if recent:
            chunks.append("\n--- RECENT COMPACT SESSION SUMMARIES ---\n" + recent)

    return truncate_middle("\n".join(chunks), max_chars)

def build_prompt(
    *,
    role: str,
    goal: dict[str, Any],
    root: Path,
    workdir: Path,
    run_dir: Path,
    round_index: int,
    memory_context: str,
    previous_verifier: dict[str, Any] | None,
    model_route: dict[str, Any] | None = None,
) -> str:
    role_header = {
        "explorer": "You are the Explorer. Read context and propose a minimal plan. Do not edit files.",
        "implementer": "You are the Implementer. Make focused edits to satisfy the GoalSpec. Do not mark the task done; verifier decides.",
        "verifier": "You are the Verifier. Ignore implementer confidence claims. Inspect diff, commands, monitors, and constraints. Return PASS, FAIL, or UNCERTAIN with evidence.",
        "distiller": "You are the Distiller. Extract durable memory candidates with evidence from run artifacts.",
    }.get(role, f"You are role {role}.")

    verifier_text = ""
    if previous_verifier:
        verifier_text = "\n## Previous verifier result\n```json\n" + truncate_middle(json.dumps(previous_verifier, indent=2, sort_keys=True, default=str), 8000) + "\n```\n"

    route_text = ""
    if model_route:
        route_text = f"""
## Model route
- task_type: `{model_route.get('task_type')}`
- role: `{model_route.get('role')}`
- model profile: `{model_route.get('profile_id')}`
- model alias: `{model_route.get('model')}`
- reasoning: `{model_route.get('reasoning')}`
- cost class: `{model_route.get('cost_class')}`
- context max chars: `{model_route.get('context_max_chars')}` ≈ `{model_route.get('estimated_context_tokens')}` prompt tokens
"""

    outcome_text = ""
    outcome = goal.get("outcome") or {}
    if outcome.get("enabled"):
        outcome_text = f"""
## Outcome / rubric loop
- outcome mode: `{outcome.get('mode', 'rubric')}`
- rubric: `{outcome.get('rubric_id') or '(auto-selected by task type)'}`
- max iterations: `{outcome.get('max_iterations') or goal.get('loop', {}).get('max_rounds')}`
- pass threshold: `{outcome.get('pass_threshold') or '(rubric default)'}`
- judge: independent artifact grader; do not self-certify your own work.
- If the rubric is not met, use grader feedback in the next turn and revise artifacts.
"""

    experiment_text = ""
    exp_policy = goal.get("experiment_policy") or {}
    if exp_policy.get("enabled") or str(goal.get("task_type", "")) in {"factor_research", "formula_alpha_mining", "alpha_mining", "beam_research", "research_design", "exploratory"}:
        experiment_text = """
## Experiment ledger protocol
For automatic research / strategy / factor work, write `experiment.json` under the run directory when possible.
Recommended schema: {"experiment_id":"...", "type":"structural|scalar", "status":"kept|discarded|crashed|uncertain", "hypothesis":"...", "change_summary":"...", "artifact":{}, "metrics":{}}.
Classify big idea changes as structural. Classify threshold/lookback/constant tweaks as scalar.
"""

    beam_text = ""
    beam_node = goal.get("beam_node") or {}
    if isinstance(beam_node, dict) and beam_node:
        beam_text = f"""
## Beam research node
- beam: `{beam_node.get('beam_id')}` / run `{beam_node.get('beam_run_id')}`
- node: `{beam_node.get('node_id')}` depth `{beam_node.get('depth')}` parent `{beam_node.get('parent_id')}`
- direction: `{beam_node.get('direction_id')}` — {beam_node.get('title') or ''}
- beam objective: {beam_node.get('beam_objective') or ''}

Beam protocol:
- This sub-session is exactly one branch in a bounded beam search.
- Do not spawn child sessions manually.
- If you propose child branches, write at most a few `next_directions` in `beam_result.json` under the run directory.
- Treat branch findings as claims with evidence. Correct, wrong, and uncertain conclusions are all useful when distilled.
- Recommended `beam_result.json` schema: {{"score": 0.0-1.0, "verdict": "promising|dead_end|uncertain", "summary": "...", "claims": [...], "next_directions": [{{"id":"...","title":"...","objective":"...","task_type":"..."}}]}}.
"""

    return f"""{role_header}\n\n# GoalSpec\n\nGoal ID: {goal['id']}\nObjective: {goal['objective']}\nTask type: {goal.get('task_type', 'implementation')}\nRound: {round_index}\nProject root: {root}\nActive workdir: {workdir}\nRun dir: {run_dir}\n{route_text}\n{beam_text}\n## Done when\nCommands:\n{chr(10).join('- ' + c for c in goal.get('done_when', {}).get('commands', [])) or '- No deterministic commands declared'}\n\nMonitors:\n{chr(10).join('- ' + str(m) for m in (goal.get('monitors', []) + goal.get('done_when', {}).get('monitors', []))) or '- No monitors declared'}\n\nDiff requirements:\n{chr(10).join('- ' + c for c in goal.get('done_when', {}).get('diff_requirements', [])) or '- None declared'}\n\n## Constraints\n{goal.get('constraints', {})}\n\n## Session boundary rules\n- This session is responsible for exactly one concrete GoalSpec. Do not start unrelated work.\n- Write durable notes under the run directory. Session compaction will compact useful results for future sessions.\n- Do not rely on raw old transcripts; use compact memory and recent compact session summaries only.\n- If the task expands into multiple tasks, create follow-up task candidates rather than doing them here.\n- In a beam branch, propose child branches through `beam_result.json`; do not run them yourself.\n\n## Operating rules\n- Write any notes or proposals under the run directory, not into canonical memory.\n- Keep diffs focused.\n- If you are unsure, say UNCERTAIN rather than inventing confidence.\n- Never directly edit `.sisyfus/memory/*.jsonl`; Sisyfus applies distill candidates through the memory broker.\n- For recurring monitor/agentops tasks, prefer writing or invoking a deterministic monitor over repeated model reasoning.\n\n## Loaded project memory/context\n{memory_context or '(none loaded)'}\n{verifier_text}\n"""


class MockAgentAdapter:
    name = "mock"

    def run(
        self,
        *,
        role: str,
        goal: dict[str, Any],
        root: Path,
        workdir: Path,
        run_dir: Path,
        round_index: int,
        memory_context: str,
        previous_verifier: dict[str, Any] | None = None,
        model_route: dict[str, Any] | None = None,
    ) -> AgentResult:
        round_dir = run_dir / f"round-{round_index:02d}" / role
        round_dir.mkdir(parents=True, exist_ok=True)
        prompt = build_prompt(
            role=role,
            goal=goal,
            root=root,
            workdir=workdir,
            run_dir=run_dir,
            round_index=round_index,
            memory_context=memory_context,
            previous_verifier=previous_verifier,
            model_route=model_route,
        )
        prompt_path = round_dir / "prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        stdout = f"[mock:{role}] No external agent executed. This adapter only exercises loop mechanics.\n"
        if role == "explorer":
            stdout += "Plan: run implementer, then deterministic verifier.\n"
        elif role == "implementer":
            stdout += "No code changes made.\n"
        elif role == "verifier":
            stdout += "Verifier role delegated to deterministic verifier in MVP.\n"
        stdout_path = round_dir / "stdout.txt"
        stderr_path = round_dir / "stderr.txt"
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        result = AgentResult(
            role,
            round_index,
            self.name,
            str(prompt_path),
            str(stdout_path),
            str(stderr_path),
            0,
            0.0,
            len(prompt),
            len(stdout),
            {"mock": True, "model_route": model_route or {}},
        )
        write_json(round_dir / "result.json", result.to_dict())
        return result


class CommandAgentAdapter:
    name = "command"

    def __init__(self, command: str | None = None, *, timeout: int = 1800) -> None:
        self.command = command
        self.timeout = timeout

    def _command_for_role(self, goal: dict[str, Any], role: str) -> str:
        role_cfg = goal.get("agents", {}).get(role, {}) or {}
        command = role_cfg.get("command") or self.command
        if not command:
            raise ValueError(f"No command configured for role {role}. Pass --agent-command or set agents.{role}.command")
        return str(command)

    def run(
        self,
        *,
        role: str,
        goal: dict[str, Any],
        root: Path,
        workdir: Path,
        run_dir: Path,
        round_index: int,
        memory_context: str,
        previous_verifier: dict[str, Any] | None = None,
        model_route: dict[str, Any] | None = None,
    ) -> AgentResult:
        round_dir = run_dir / f"round-{round_index:02d}" / role
        round_dir.mkdir(parents=True, exist_ok=True)
        prompt = build_prompt(
            role=role,
            goal=goal,
            root=root,
            workdir=workdir,
            run_dir=run_dir,
            round_index=round_index,
            memory_context=memory_context,
            previous_verifier=previous_verifier,
            model_route=model_route,
        )
        prompt_path = round_dir / "prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        command = self._command_for_role(goal, role)
        route = model_route or {}
        env = os.environ.copy()
        env.update(
            {
                "SISYFUS_PROMPT_PATH": str(prompt_path),
                "SISYFUS_WORKDIR": str(workdir),
                "SISYFUS_RUN_DIR": str(run_dir),
                "SISYFUS_ROLE": role,
                "SISYFUS_GOAL_ID": str(goal["id"]),
                "SISYFUS_TASK_TYPE": str(goal.get("task_type", "implementation")),
                "SISYFUS_ROUND": str(round_index),
                "SISYFUS_MODEL": str(route.get("model", "")),
                "SISYFUS_MODEL_PROFILE": str(route.get("profile_id", "")),
                "SISYFUS_MODEL_REASONING": str(route.get("reasoning", "")),
                "SISYFUS_MODEL_COST_CLASS": str(route.get("cost_class", "")),
                "SISYFUS_CONTEXT_MAX_CHARS": str(route.get("context_max_chars", "")),
                "SISYFUS_BEAM_ID": str((goal.get("beam_node") or {}).get("beam_id", "")),
                "SISYFUS_BEAM_RUN_ID": str((goal.get("beam_node") or {}).get("beam_run_id", "")),
                "SISYFUS_BEAM_NODE_ID": str((goal.get("beam_node") or {}).get("node_id", "")),
                "SISYFUS_BEAM_PARENT_ID": str((goal.get("beam_node") or {}).get("parent_id", "")),
                "SISYFUS_BEAM_DEPTH": str((goal.get("beam_node") or {}).get("depth", "")),
                "SISYFUS_BEAM_DIRECTION_ID": str((goal.get("beam_node") or {}).get("direction_id", "")),
            }
        )
        replacements = {
            "{prompt_path}": str(prompt_path),
            "{workdir}": str(workdir),
            "{run_dir}": str(run_dir),
            "{role}": role,
            "{goal_id}": str(goal["id"]),
            "{task_type}": str(goal.get("task_type", "implementation")),
            "{round}": str(round_index),
            "{model}": str(route.get("model", "")),
            "{model_profile}": str(route.get("profile_id", "")),
            "{reasoning}": str(route.get("reasoning", "")),
            "{beam_id}": str((goal.get("beam_node") or {}).get("beam_id", "")),
            "{beam_run_id}": str((goal.get("beam_node") or {}).get("beam_run_id", "")),
            "{beam_node_id}": str((goal.get("beam_node") or {}).get("node_id", "")),
            "{beam_parent_id}": str((goal.get("beam_node") or {}).get("parent_id", "")),
            "{beam_depth}": str((goal.get("beam_node") or {}).get("depth", "")),
            "{beam_direction_id}": str((goal.get("beam_node") or {}).get("direction_id", "")),
        }
        formatted = command
        for token, value in replacements.items():
            formatted = formatted.replace(token, value)
        start = time.monotonic()
        proc = run_process(formatted, cwd=workdir, timeout=self.timeout, env=env, shell=True)
        elapsed = time.monotonic() - start
        stdout_path = round_dir / "stdout.txt"
        stderr_path = round_dir / "stderr.txt"
        stdout_path.write_text(proc["stdout"], encoding="utf-8")
        stderr_path.write_text(proc["stderr"], encoding="utf-8")
        result = AgentResult(
            role=role,
            round_index=round_index,
            adapter=self.name,
            prompt_path=str(prompt_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            exit_code=int(proc["exit_code"]),
            elapsed_seconds=round(elapsed, 3),
            prompt_chars=len(prompt),
            output_chars=len(proc["stdout"]) + len(proc["stderr"]),
            metadata={
                "command": formatted,
                "timed_out": proc.get("timed_out", False),
                "model_route": route,
                "approx_prompt_tokens": estimate_tokens_from_chars(len(prompt)),
                "approx_output_tokens": estimate_tokens_from_chars(len(proc["stdout"]) + len(proc["stderr"])),
            },
        )
        write_json(round_dir / "result.json", result.to_dict())
        return result


def adapter_from_name(name: str, *, command: str | None = None) -> MockAgentAdapter | CommandAgentAdapter:
    if name == "mock":
        return MockAgentAdapter()
    if name == "command":
        return CommandAgentAdapter(command)
    raise ValueError(f"Unknown adapter: {name}")
