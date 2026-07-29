from __future__ import annotations

from pathlib import Path
import shutil

from .model_policy import write_default_model_policy
from .rubric import write_builtin_rubrics
from .paths import ensure_layout
from .utils import utc_now


def _write_if_missing(path: Path, content: str, *, force: bool = False) -> None:
    if force or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def init_project(root: Path, *, force: bool = False) -> Path:
    sf = ensure_layout(root)
    now = utc_now()
    write_default_model_policy(root, force=force)
    write_builtin_rubrics(root, force=force)

    _write_if_missing(
        sf / "memory" / "index.md",
        f"""# Sisyfus Memory Index\n\nCreated: {now}\n\nThis file is intentionally small. It routes agents to durable project state.\n\n## Stable facts\nRead `.sisyfus/memory/facts.jsonl` only when relevant.\n\n## Known failures\nRead `.sisyfus/memory/failures.jsonl` before repeating prior work.\n\n## Hypotheses\nRead `.sisyfus/memory/hypotheses.jsonl` only as uncertain context.\n\n## Decisions\nRead `.sisyfus/memory/decisions.md` for architecture decisions.\n\n## Invariants\nRead `.sisyfus/memory/invariants.md` before editing code.\n\n## Recent sessions\nRead compact summaries through `.sisyfus/sessions/index.jsonl`; do not load raw transcripts by default.\n\n## Beams\nUse `.sisyfus/beams/{{beam_id}}/beam.context.md` for branching research state. Beam branches are one-task sessions; do not expand branch count without checking beam budgets.\n\n## Open tasks\nRead `.sisyfus/tasks/open.jsonl` for current loop state.\n\n## Monitors\nUse `.sisyfus/monitors/registry.json` and built-in monitors for repeated ops checks. Prefer deterministic monitors over agent reasoning for recurring agentops work.\n\n## Model routing\nRead `.sisyfus/model_policy.json` to choose model tier by task type. Expensive frontier models are for planning/exploration; routine ops and summarization should use balanced/cheap profiles or no model.\n""",
        force=force,
    )
    for rel in ["facts.jsonl", "failures.jsonl", "hypotheses.jsonl"]:
        _write_if_missing(sf / "memory" / rel, "", force=force)
    _write_if_missing(
        sf / "memory" / "decisions.md",
        "# Decisions\n\nRecord architecture/process decisions here. Prefer ADR-style entries with date, context, decision, consequences.\n",
        force=force,
    )
    _write_if_missing(
        sf / "memory" / "invariants.md",
        """# Invariants\n\nRules that agent loops must not violate.\n\n- One Sisyfus session should complete exactly one concrete task. Split expanding work into follow-up GoalSpecs.\n- Do not mark a goal as passed unless deterministic verification passes or a human explicitly accepts uncertainty.\n- Do not edit canonical memory directly from agent role sessions; write run artifacts instead.\n- Do not spend model tokens on repeated monitor/agentops tasks when a deterministic monitor can do the job.\n- Do not load raw historical transcripts by default. Read compact session summaries and stable memory instead.\n- Route model calls by task type: frontier for high-ambiguity planning/exploration, balanced/cheap for collection/summarization, no model for known monitors.\n- Beam search must obey `max_depth`, `width`, `max_children_per_node`, and `max_sessions_total`; never spawn unbounded subagents.\n""",
        force=force,
    )
    for rel in ["open.jsonl", "done.jsonl", "dropped.jsonl"]:
        _write_if_missing(sf / "tasks" / rel, "", force=force)
    _write_if_missing(sf / "sessions" / "index.jsonl", "", force=force)
    _write_if_missing(
        sf / "sessions" / "README.md",
        """# Sisyfus Sessions\n\nA session is one run of one GoalSpec.\n\nPrinciple:\n\n1. finish one concrete task;\n2. write raw artifacts under `.sisyfus/runs/{run_id}/`;\n3. distill the run into `distill.json` and `session.compact.md`;\n4. append compact metadata to `.sisyfus/sessions/index.jsonl`;\n5. start the next session by reading compact memory, not raw transcript sludge.\n\nThis keeps context length bounded and prevents stale chat history from degrading model performance.\n""",
        force=force,
    )

    _write_if_missing(sf / "reviews" / "annotations.jsonl", "", force=force)
    _write_if_missing(sf / "reviews" / "guidance.jsonl", "", force=force)
    _write_if_missing(
        sf / "reviews" / "README.md",
        """# Sisyfus Human Review

This directory stores human annotations and steering guidance.

Files:

- `annotations.jsonl`: human verdicts over claims, sessions, goals, tasks, or runs.
- `guidance.jsonl`: active human guidance / next directions for future sessions.

Use:

```bash
sisyfus review claims
sisyfus review annotate <claim_id> --verdict correct --note "verified by human"
sisyfus guidance add "Next, stress-test SMA 72/336 across fees and regimes" --create-task
```

Future sessions read compact human review context before recent machine-generated session summaries.
""",
        force=force,
    )
    _write_if_missing(
        sf / "dashboard" / "README.md",
        """# Sisyfus Dashboard

Run:

```bash
sisyfus dashboard --open
```

The dashboard is a local panel for sessions, claims, human verdicts, guidance, open tasks, and run artifacts.
It is intentionally backed by `.sisyfus/` JSONL artifacts rather than a remote database.
""",
        force=force,
    )

    _write_if_missing(sf / "beams" / "index.jsonl", "", force=force)
    _write_if_missing(
        sf / "beams" / "README.md",
        """# Sisyfus Beams

Beams are bounded branching research loops for problems with multiple plausible directions.

Examples:

- scan known crypto cross-sectional factors;
- handcraft factor hypotheses;
- generate symbolic AlphaGPT-style factor expressions;
- turn promising branches into deterministic backtests or monitors.

Rules:

1. Every beam node is a normal one-task Sisyfus sub-session.
2. Every sub-session writes `distill.json` and `session.compact.md`.
3. The beam coordinator reads `beam.compact.md` and child compact summaries, not raw transcripts.
4. `max_rounds`, `max_children_per_node`, `width`, and `max_total_sessions` prevent exponential explosion.
5. A branch can propose future branches by writing `beam_result.json` with `next_directions`.
6. Human review can mark branch conclusions correct, wrong, uncertain, stale, or accepted from the dashboard.

Commands:

```bash
sisyfus beam template crypto-factor-research --objective "Explore a crypto cross-sectional strategy"
sisyfus beam run .sisyfus/goals/crypto-factor-research.beam.json
sisyfus beam status <beam_id>
sisyfus dashboard --open
```
""",
        force=force,
    )

    _write_if_missing(sf / "experiments" / "ledger.jsonl", "", force=force)
    _write_if_missing(
        sf / "experiments" / "README.md",
        """# Sisyfus Experiments

Research sessions write experiment cards here. This is the Parameter-Golf-style ledger for automatic research.

Each experiment should record: hypothesis, structural/scalar type, kept/discarded/crashed status, artifacts, metrics, grader outcome, and cost.
""",
        force=force,
    )
    _write_if_missing(sf / "memory_fsm" / "items.jsonl", "", force=force)
    _write_if_missing(sf / "memory_fsm" / "events.jsonl", "", force=force)
    _write_if_missing(
        sf / "memory_fsm" / "README.md",
        """# Sisyfus Memory FSM

Memory lifecycle:

`failure_note -> investigation -> verified_fact -> general_rule -> consulted_rule`

The point is not to collect notes. The point is to turn failures into checked rules that future sessions actually consult.
""",
        force=force,
    )
    _write_if_missing(
        sf / "outcomes" / "README.md",
        """# Sisyfus Outcomes

Outcomes are rubric-graded loops: iterate -> grade -> revise until the rubric passes or budget is exhausted.

The grader is independent and artifact-based. It should not trust the worker's self-assessment.
""",
        force=force,
    )
    _write_if_missing(
        sf / "provider" / "usage.jsonl",
        "",
        force=force,
    )

    _write_if_missing(
        sf / "monitors" / "registry.json",
        '{\n  "schema_version": "sisyfus.monitor_registry.v0.2",\n  "monitors": []\n}\n',
        force=force,
    )
    _write_if_missing(
        sf / "monitors" / "README.md",
        """# Sisyfus Monitors\n\nMonitors are deterministic, reusable programs for agentops work that should not consume model tokens every time.\n\nUse cases:\n\n- live-vs-backtest data comparison;\n- exact file/data equality checks;\n- log pattern checks;\n- regression artifact checks;\n- research-vs-production output comparison.\n\nPrinciple: use an agent once to write or upgrade a monitor, then route repeated ops tasks through the registered program.\n\nBuilt-ins are available without registration:\n\n- `file.exact_equal`\n- `file.contains`\n- `csv.exact_equal`\n- `csv.numeric_close`\n- `jsonl.exact_equal`\n""",
        force=force,
    )

    agents = {
        "explorer.toml": """name = "explorer"\ndescription = "Read-only context discovery and plan proposal."\ninstructions = "Do not edit files. Identify relevant files, risks, and a minimal implementation plan. Use frontier model profiles only for high-ambiguity exploration."\n""",
        "implementer.toml": """name = "implementer"\ndescription = "Make focused code changes for a GoalSpec."\ninstructions = "Edit only what is needed. Do not declare completion; verifier decides. Stay inside one task per session."\n""",
        "verifier.toml": """name = "verifier"\ndescription = "Independent reviewer. Challenge the diff and run checks."\ninstructions = "Ignore implementer confidence claims. Inspect diff, commands, monitors, and constraints. Return PASS, FAIL, or UNCERTAIN."\n""",
        "distiller.toml": """name = "distiller"\ndescription = "Convert run artifacts into structured memory candidates."\ninstructions = "Extract facts, failures, hypotheses, tasks, and skill candidates with evidence. Compact the session; do not preserve useless transcript sludge."\n""",
    }
    for name, content in agents.items():
        _write_if_missing(sf / "agents" / name, content, force=force)

    skills = {
        "session-distill": """---\nname: session-distill\ndescription: Distill a completed one-task agent run into compact structured memory candidates with evidence.\n---\n\n# Session Distill Skill\n\nRead run artifacts under `.sisyfus/runs/{run_id}/`. Extract only durable, useful information.\n\nClassify outputs as:\n\n- facts\n- decisions\n- failures\n- hypotheses\n- tasks\n- invariants\n\nRules:\n\n1. One session equals one concrete task.\n2. Compact aggressively. Future sessions should read the distill, not the raw transcript.\n3. Never promote uncertain claims into stable facts without evidence.\n4. If the session discovered a recurring ops check, propose a deterministic monitor.\n""",
        "verify-diff": """---\nname: verify-diff\ndescription: Independently verify a code diff against GoalSpec constraints and deterministic checks.\n---\n\n# Verify Diff Skill\n\nUse the GoalSpec as source of truth. Ignore implementer self-assessment.\n\nCheck:\n\n1. deterministic commands;\n2. deterministic monitor results;\n3. changed files;\n4. forbidden paths;\n5. unrelated changes;\n6. missing tests when behavior changed;\n7. stale or contradicted memory.\n\nReturn PASS, FAIL, or UNCERTAIN.\n""",
        "triage-ci": """---\nname: triage-ci\ndescription: Triage failing CI logs into likely root cause, owner area, and next action.\n---\n\n# Triage CI Skill\n\nSummarize failure signals, recent changes, likely root cause, and recommended next GoalSpec.\nDo not modify code during triage.\n""",
        "write-monitor": """---\nname: write-monitor\ndescription: Implement a deterministic reusable monitor program for repeated agentops tasks.\n---\n\n# Write Monitor Skill\n\nUse this when an ops/monitoring task is new and no registered monitor can handle it.\n\nRules:\n\n1. Write a small deterministic program or shell command.\n2. It should accept parameters from `SISYFUS_MONITOR_PARAMS_JSON` or explicit CLI args.\n3. It should emit JSON with `status`, `summary`, `metrics`, `evidence`, and optional `mismatches`.\n4. Register it with `sisyfus monitor add`.\n5. Future runs should call the monitor, not the agent.\n\nPrefer programmatic checks over natural-language review.\n""",
        "model-route": """---\nname: model-route\ndescription: Choose the cheapest sufficient model profile for a Sisyfus task type.\n---\n\n# Model Route Skill\n\nUse `.sisyfus/model_policy.json`.\n\nDefault mapping:\n\n- planning / architecture: `strategic_planning`\n- exploratory / divergent / research_design: `frontier_exploration`\n- information_collection / literature: `balanced_ops`\n- summarization / distillation: `cheap_summary`\n- monitoring / agentops / backtest_monitor: `deterministic_program`\n\nDo not use frontier models for routine monitoring or repeated agentops checks.\n""",
    }
    for slug, content in skills.items():
        _write_if_missing(sf / "skills" / slug / "SKILL.md", content, force=force)

    _write_if_missing(
        root / "AGENTS.md",
        """# Agent Entry Point\n\nRead this before working in this repo.\n\n## Sisyfus\n\nThis project uses `.sisyfus/` for loop state, durable memory, goal specs, run artifacts, reusable monitors, model routing, and verification reports.\n\nRules:\n\n- One session should complete one concrete task. Split expanding work into new GoalSpecs.\n- Do not edit canonical memory files directly. Write run artifacts under `.sisyfus/runs/{run_id}/`.\n- Do not mark work complete unless deterministic verification passes.\n- Prefer focused diffs and explicit evidence.\n- Future sessions should read compact distills and stable memory, not raw historical transcripts.\n- For recurring monitor/agentops tasks, use or create a deterministic monitor instead of spending tokens on repeated agent reasoning.\n- Respect `.sisyfus/model_policy.json`: frontier models are for high-ambiguity planning/exploration; balanced/cheap profiles are for collection/summarization; known monitoring should use programs, not models.\n\nCommon files:\n\n- `.sisyfus/memory/index.md`\n- `.sisyfus/model_policy.json`\n- `.sisyfus/sessions/index.jsonl`\n- `.sisyfus/tasks/open.jsonl`\n- `.sisyfus/goals/`\n- `.sisyfus/runs/`\n- `.sisyfus/monitors/registry.json`\n""",
        force=False,
    )


    # Install the integrated Sisyfus Research skill and its references/templates.
    source_skill = Path(__file__).resolve().parent / "skill_assets" / "sisyfus-research"
    target_skill = sf / "skills" / "sisyfus-research"
    if source_skill.exists():
        if force and target_skill.exists():
            shutil.rmtree(target_skill)
        if not target_skill.exists():
            shutil.copytree(source_skill, target_skill)

    _write_if_missing(
        sf / "research" / "README.md",
        """# Sisyfus Research v2

Research runs are event-sourced under `.sisyfus/research/runs/<research_id>/`.

Truth lives in `events.jsonl`. `snapshot.json`, Goal/Execution/Evidence graphs, frontier, lessons, and `report/index.html` are rebuildable projections.

Use `sisyfus research --help` and read `.sisyfus/skills/sisyfus-research/SKILL.md`.
""",
        force=force,
    )
    _write_if_missing(sf / "research" / "index.jsonl", "", force=force)

    return sf
