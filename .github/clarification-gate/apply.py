from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def insert_after(path: str, marker: str, addition: str) -> None:
    text = read(path)
    if addition.strip() in text:
        return
    if text.count(marker) != 1:
        raise SystemExit(f"unexpected marker count in {path}: {marker!r}")
    write(path, text.replace(marker, marker + addition, 1))


def insert_before(path: str, marker: str, addition: str) -> None:
    text = read(path)
    if addition.strip() in text:
        return
    if text.count(marker) != 1:
        raise SystemExit(f"unexpected marker count in {path}: {marker!r}")
    write(path, text.replace(marker, addition + marker, 1))


def replace_once(path: str, before: str, after: str) -> None:
    text = read(path)
    if after in text:
        return
    if text.count(before) != 1:
        raise SystemExit(f"unexpected replacement count in {path}: {before[:100]!r}")
    write(path, text.replace(before, after, 1))


CLARIFICATION_SKILL = r'''## Clarification gate — ask before acting

Immediately after Mission Control starts, inspect the user's request for three mandatory intake dimensions. Treat them as blocking gates, not optional prompt polish:

1. **Scope** — what is in scope and out of scope; target system, market, dataset, repository, time period, constraints, permitted actions, and required deliverables.
2. **Objective** — the decision or artifact the work must produce, plus a mechanically recognizable completion condition. “Research this”, “improve it”, or “find a good strategy” is not a sufficient terminal objective.
3. **Verification** — who or what can reject the result: deterministic tests, backtest/simulation, benchmark, external authority, human review, or an isolated model-jury rubric; include datasets, thresholds, invalidity rules, and guardrails where material.

If any of these dimensions is materially missing, contradictory, or admits several high-impact interpretations:

- **Do not begin web research, source collection, coding, experiments, or autonomous execution.** Do not silently choose a market, time horizon, deliverable, success threshold, or verifier.
- Record the wait in Mission Control before asking:

```bash
sisyfus research monitor-clarify \
  --missing scope \
  --missing objective \
  --missing verification \
  --question "<question shown to the user>" \
  --root <project>
```

- Ask the user one compact batch containing only the unresolved questions. Reuse facts already supplied in the conversation, files, repository, or prior answers; never ask the same question twice.
- Make every question decision-oriented. Where useful, offer two or three concrete options and state the recommended default rather than asking an unbounded “what do you want?” question.
- If the user cannot specify a verifier, propose the strongest feasible hierarchy: deterministic/programmatic first, hybrid second, isolated model jury third, human gate last. Ask the user to select or approve the proposed contract.
- Do not block on low-impact implementation details that are reversible and do not change scope, objective, safety, cost, or truth criteria. Choose a reasonable default, record it as an assumption, and continue.

After the user answers, restate and lock a compact intake contract containing **Scope / Objective / Deliverables / Verifier / Completion / Constraints**. Update Mission Control before compiling the TaskSpec:

```bash
sisyfus research monitor-resume \
  --summary "<locked intake contract>" \
  --root <project>
```

Proceed only when the three mandatory dimensions are sufficiently precise to compile falsifiable Claims and a verifier-backed Goal Graph. If the answer exposes another material contradiction, ask one follow-up batch limited to that contradiction; otherwise stop questioning and execute.

'''

insert_after(
    "SKILL.md",
    "- report the printed monitor URL to the user immediately.\n\n",
    CLARIFICATION_SKILL,
)

CLARIFICATION_REFERENCE = r'''## Clarification and user-wait state

After the bootstrap monitor starts, the coding agent evaluates three blocking
intake dimensions: task scope, terminal objective, and verification method. If
one is materially ambiguous, the agent must not silently select a high-impact
interpretation or begin research/coding. It records the state with:

```bash
sisyfus research monitor-clarify \
  --missing scope \
  --missing objective \
  --missing verification \
  --question "Which market, deliverables, and acceptance test should be locked?" \
  --root <project>
```

Mission Control then reports:

```text
phase      CLARIFYING
status     NEEDS_USER
operation  research.intake.clarify
```

The questions and missing dimensions are stored as operational metadata, not
research evidence. After the user answers, the agent locks a concise intake
contract and resumes with:

```bash
sisyfus research monitor-resume \
  --summary "Scope=...; Objective=...; Verifier=...; Completion=..." \
  --root <project>
```

The agent asks only for unresolved high-impact choices, reuses information
already supplied, offers concrete options when useful, and does not repeatedly
question the user about reversible implementation details.

'''

insert_before(
    "references/live-mission-control.md",
    "## Live activity state\n",
    CLARIFICATION_REFERENCE,
)

CLI_FUNCTIONS = r'''

def cmd_research_monitor_clarify(args: argparse.Namespace) -> int:
    root = Path(args.root or Path.cwd()).expanduser().resolve()
    ensure_layout(root)
    current = read_activity(root)
    if not current.get("task_id"):
        current = start_activity(
            root,
            title=args.task or "Clarify Sisyfus research task",
            objective="",
            actor=args.actor,
        )
    missing = sorted({str(item) for item in (args.missing or [])})
    questions = [str(item).strip() for item in (args.question or []) if str(item).strip()]
    if not missing and not questions:
        raise ValueError("monitor-clarify requires at least one --missing or --question")
    detail_parts = []
    if missing:
        detail_parts.append("missing=" + ", ".join(missing))
    if questions:
        detail_parts.append("questions=" + " | ".join(questions))
    activity = update_activity(
        root,
        phase="CLARIFYING",
        status="NEEDS_USER",
        operation="research.intake.clarify",
        message="Waiting for user clarification before research begins.",
        detail="; ".join(detail_parts),
        progress={"percent": 0.0, "label": "Clarification required"},
        actor=args.actor,
        metadata={
            "missing_intake_fields": missing,
            "clarification_questions": questions,
        },
        heartbeat=True,
    )
    entry = render_activity_monitor(root)
    url = ensure_activity_observatory(
        root,
        str(activity["task_id"]),
        open_browser=not args.no_open,
    )
    _print_json(
        {
            "status": "NEEDS_USER",
            "task_id": activity["task_id"],
            "missing": missing,
            "questions": questions,
            "monitor_url": url,
            "monitor_entry": str(entry),
        }
    )
    return 0


def cmd_research_monitor_resume(args: argparse.Namespace) -> int:
    root = Path(args.root or Path.cwd()).expanduser().resolve()
    ensure_layout(root)
    current = read_activity(root)
    if not current.get("task_id"):
        raise RuntimeError("monitor-resume requires an existing task; run monitor-start first")
    summary = str(args.summary or "").strip()
    if not summary:
        raise ValueError("monitor-resume requires a non-empty --summary")
    activity = update_activity(
        root,
        phase="INTAKE",
        status="RUNNING",
        operation="research.intake.lock",
        message="Clarification received. Locking the research program.",
        detail=summary,
        progress={"percent": 5.0, "label": "Intake contract"},
        actor=args.actor,
        metadata={
            "missing_intake_fields": [],
            "clarification_questions": [],
            "clarification_summary": summary,
        },
        heartbeat=True,
    )
    entry = render_activity_monitor(root)
    url = ensure_activity_observatory(
        root,
        str(activity["task_id"]),
        open_browser=not args.no_open,
    )
    _print_json(
        {
            "status": "INTAKE_LOCKED",
            "task_id": activity["task_id"],
            "summary": summary,
            "monitor_url": url,
            "monitor_entry": str(entry),
        }
    )
    return 0
'''

insert_before(
    "src/sisyfus/cli.py",
    "\n\ndef cmd_research_monitor_serve(args: argparse.Namespace) -> int:\n",
    CLI_FUNCTIONS,
)

CLI_PARSERS = r'''
    p_rclarify = research_sub.add_parser(
        "monitor-clarify",
        help="mark Mission Control as waiting for material user clarification",
    )
    p_rclarify.add_argument(
        "--missing",
        action="append",
        choices=["scope", "objective", "verification"],
        help="material intake dimension that is unresolved; may be repeated",
    )
    p_rclarify.add_argument(
        "--question",
        action="append",
        help="question being asked of the user; may be repeated",
    )
    p_rclarify.add_argument("--task", help="fallback title when monitor-start was not called")
    p_rclarify.add_argument("--root")
    p_rclarify.add_argument("--actor", default="skill")
    p_rclarify.add_argument("--no-open", action="store_true")
    p_rclarify.set_defaults(func=cmd_research_monitor_clarify)

    p_rresume = research_sub.add_parser(
        "monitor-resume",
        help="resume intake after the user clarifies scope, objective, and verifier",
    )
    p_rresume.add_argument("--summary", required=True, help="locked intake contract")
    p_rresume.add_argument("--root")
    p_rresume.add_argument("--actor", default="skill")
    p_rresume.add_argument("--no-open", action="store_true")
    p_rresume.set_defaults(func=cmd_research_monitor_resume)

'''

insert_before(
    "src/sisyfus/cli.py",
    "    p_rmonitor_serve = research_sub.add_parser(\n",
    CLI_PARSERS,
)

replace_once(
    "src/sisyfus/activity.py",
    '#sf-live-hud[data-status="COMPLETED"] .sf-dot,#sf-live-hud[data-status="READY"] .sf-dot { background:#e0b14b;box-shadow:0 0 12px #e0b14b;animation:none; }',
    '#sf-live-hud[data-status="COMPLETED"] .sf-dot,#sf-live-hud[data-status="READY"] .sf-dot,#sf-live-hud[data-status="NEEDS_USER"] .sf-dot { background:#e0b14b;box-shadow:0 0 12px #e0b14b;animation:none; }',
)
replace_once(
    "src/sisyfus/activity.py",
    '.event.COMPLETED,.event.READY{border-left-color:var(--gold)}',
    '.event.COMPLETED,.event.READY,.event.NEEDS_USER{border-left-color:var(--gold)}',
)

ACTIVITY_TEST = r'''


def test_monitor_clarification_gate_records_user_wait_and_resume(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("SISYFUS_AUTO_SERVE", "0")
    monkeypatch.setenv("SISYFUS_AUTO_OPEN", "0")

    assert main([
        "research", "monitor-start",
        "--task", "Ambiguous HFT study",
        "--root", str(tmp_path),
    ]) == 0
    capsys.readouterr()

    assert main([
        "research", "monitor-clarify",
        "--missing", "scope",
        "--missing", "verification",
        "--question", "Which venue and time horizon are in scope?",
        "--question", "Should the locked verifier be an OOS backtest?",
        "--root", str(tmp_path),
    ]) == 0
    clarification = json.loads(capsys.readouterr().out)
    waiting = read_activity(tmp_path)

    assert clarification["status"] == "NEEDS_USER"
    assert clarification["missing"] == ["scope", "verification"]
    assert waiting["phase"] == "CLARIFYING"
    assert waiting["status"] == "NEEDS_USER"
    assert waiting["operation"] == "research.intake.clarify"
    assert waiting["metadata"]["missing_intake_fields"] == ["scope", "verification"]
    assert len(waiting["metadata"]["clarification_questions"]) == 2

    summary = (
        "Scope=BTCUSDT on Binance, 2026 Q2; Objective=paper-trading candidate; "
        "Verifier=event-driven OOS backtest; Completion=all locked gates PASS"
    )
    assert main([
        "research", "monitor-resume",
        "--summary", summary,
        "--root", str(tmp_path),
    ]) == 0
    resumed_payload = json.loads(capsys.readouterr().out)
    resumed = read_activity(tmp_path)

    assert resumed_payload["status"] == "INTAKE_LOCKED"
    assert resumed["phase"] == "INTAKE"
    assert resumed["status"] == "RUNNING"
    assert resumed["operation"] == "research.intake.lock"
    assert resumed["metadata"]["missing_intake_fields"] == []
    assert resumed["metadata"]["clarification_questions"] == []
    assert resumed["metadata"]["clarification_summary"] == summary
'''

activity_tests = read("tests/test_activity_monitor.py")
if "test_monitor_clarification_gate_records_user_wait_and_resume" not in activity_tests:
    write("tests/test_activity_monitor.py", activity_tests.rstrip() + ACTIVITY_TEST + "\n")

SKILL_TEST = r'''from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SKILL = ROOT / "src" / "sisyfus" / "skill_assets" / "sisyfus-research" / "SKILL.md"


def test_skill_requires_proactive_clarification_before_research() -> None:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert text.index("## Monitor-first lifecycle") < text.index("## Clarification gate — ask before acting")
    assert text.index("## Clarification gate — ask before acting") < text.index("## Security model")
    assert "**Scope**" in text
    assert "**Objective**" in text
    assert "**Verification**" in text
    assert "Do not begin web research, source collection, coding, experiments, or autonomous execution" in text
    assert "Ask the user one compact batch containing only the unresolved questions" in text
    assert "never ask the same question twice" in text
    assert "sisyfus research monitor-clarify" in text
    assert "sisyfus research monitor-resume" in text
    assert PACKAGE_SKILL.read_text(encoding="utf-8") == text
'''
write("tests/test_skill_clarification_gate.py", SKILL_TEST)
