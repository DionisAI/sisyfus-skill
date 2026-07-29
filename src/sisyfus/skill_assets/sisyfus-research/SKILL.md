---
name: sisyfus-research
description: Run or supervise a resumable, branching, evidence-backed research loop. Use when a task requires repeated hypothesis generation, preregistered verification, structured trial and error, graph-based branch management, rollback, durable lessons, or an HTML research observatory.
---

# Sisyfus Research Skill

Sisyfus is a control surface for an event-sourced research engine. The skill may plan, explain, call tools, and propose experiments. It must never treat its own prose as research truth. Only committed verifier verdicts may change the research state.

## Engine setup

This skill drives the `sisyfus` CLI (pure-stdlib Python >= 3.11). Check availability first:

```bash
sisyfus --version || python3 -m pip install "sisyfus @ git+https://github.com/DionisAI/sisyfus-skill"
```

Working from a clone of this repository, `python3 -m pip install -e .` is equivalent. All commands below take `--root <project>` — the project directory that owns the `.sisyfus/` state tree.

## Core model

Keep these objects separate:

1. **Claim** — a falsifiable proposition.
2. **Goal Graph** — AND/OR composition of claims; mechanically determines completion.
3. **State Node** — an immutable snapshot of accepted claim statuses and evidence.
4. **Experiment** — a proposed edge from one State Node toward one target claim.
5. **Attempt** — one concrete execution of an Experiment.
6. **Observation** — raw metrics, artifacts, execution facts, and telemetry.
7. **Verification Contract** — preregistered rules that classify an Observation.
8. **Evidence** — the traceable output of a settled Attempt.
9. **Lesson** — scoped procedural memory grounded in multiple evidence items.

The event stream is the source of truth. `snapshot.json`, the three graph files, and HTML are rebuildable projections.

## Non-negotiable rules

- Compile a TaskSpec before exploration. A topic alone is not executable.
- Encode every machine-enforced hard constraint as a required Claim or verifier `guardrail`; bare `hard_constraints` text is descriptive only (`research new` prints a warning listing unenforced constraints).
- Declare an `action_family` for every Experiment; it must be present in the TaskSpec `action_space`. `mode` must be one of `explore`, `validate`, `falsify`, `hidden_eval`, `skillopt`.
- Measurement code is part of the measurement. Files referenced by a command action are content-hashed into the attempt manifest (`code_hashes`) and into the evidence record; a change between attempts of the same experiment is flagged as `code_changed_since_last_attempt`. Never silently rewrite a measurement script to make a locked contract pass — redesign openly via a new Experiment with a rationale.
- Re-supporting a Claim that carries FAIL evidence on any branch marks it `contested`. The superseding PASS experiment must carry a `discriminating_note` explaining why its measurement supersedes the refutation. With `stop_policy.require_uncontested_solve: true` (recommended for new runs) the run cannot become SOLVED while a required claim is contested and unresolved.
- Every admitted Experiment must target exactly one Claim and bind one versioned Verification Contract.
- Lock the Verification Contract before an Attempt begins. Do not change success criteria after seeing results.
- Use exactly five verifier outcomes: `PASS`, `FAIL`, `INCONCLUSIVE`, `INVALID`, `ERROR`.
- `FAIL` means a valid experiment refuted the claim or failed a hard guardrail.
- `INVALID` means the experiment did not correctly measure the claim.
- `ERROR` means infrastructure or execution failure. Neither `INVALID` nor `ERROR` may alter claim truth.
- A Planner proposes; an admission controller admits; an Executor acts; a deterministic Verifier classifies; the Reducer commits state; only the terminal evaluator can declare completion.
- The Verifier is pure code over preregistered rules — the engine never calls a model. The trust boundary is metrics production (Planner-authored measurement code), controlled by contract hash-locking, `code_hashes`, required artifacts, and repetition gates; see `references/verifier-contract.md` § Trust model.
- A failed branch does not erase its parent checkpoint. Roll back only when previously accepted upstream evidence is later refuted.
- Unsupported but valuable proposals go to backlog. Do not rewrite them to fit an unrelated verifier.
- Do not automatically promote free-form reflection into active memory. Create a Lesson candidate, ground it in evidence, then explicitly promote it after independent support.
- The HTML reporter renders persisted facts only. Missing data must remain missing.

## Start or resume

First inspect the local project:

```bash
sisyfus research list --root <project>
sisyfus research status latest --brief --root <project>
sisyfus research context latest --root <project>
```

`--brief` (also on `propose`, `execute`, `settle`) emits a compact agent-friendly summary. `context` includes `global_lessons`: promoted lessons from every other research run under this project root — review them before compiling a new TaskSpec so prior experience compounds across tasks. CLI failures are structured JSON errors on stderr (set `SISYFUS_DEBUG=1` for tracebacks).

For a new run, create a TaskSpec using `templates/research-task.json` and the contract in `references/task-spec.md`:

```bash
sisyfus research new task.json --root <project>
```

Do not begin experiments while required unresolved claims appear in `verifier_gaps`.

## Research loop

Repeat this bounded cycle:

### 1. Inspect state

Read planner context, not the entire historical transcript. Identify:

- unresolved required claims;
- critical assumptions and invalidated dependents;
- current frontier;
- waiting experiments and `next_wake_at`;
- verifier gaps;
- remaining attempt and cost budget;
- active, scoped lessons;
- recent failures without leaking host-only hidden-evaluation details.

### 2. Propose at most three experiments

Favor a small diverse set:

- one exploitation experiment that advances the best current path;
- one experiment resolving the highest-value uncertainty;
- one falsification or adversarial test of the leading explanation.

Each proposal must state:

- one target claim;
- parent `from_state_id`;
- verifier contract;
- action and context;
- expected `pass`, `fail`, `inconclusive`, and `invalid` interpretations;
- information value, goal value, cost, and invalidity risk.

Use `templates/experiment.json`:

```bash
sisyfus research propose <research_id> experiment.json --root <project>
```

The engine backlogs missing-verifier, target-mismatched, duplicate, or over-budget proposals.

Cite what the experiment builds on with `based_on`:

```json
"based_on": {"evidence_ids": ["evidence-attempt-e1-01"], "lesson_ids": ["funding-snapshot-timing"]}
```

Cited ids must exist in the run's evidence/lessons or in the global lesson store — an
out-of-context citation is rejected (`citation_out_of_context`). With
`stop_policy.require_citations: true`, every proposal after the first citable fact must
carry at least one citation (`missing_citations` otherwise). Citations feed
`lesson_usage` in the snapshot and cross-run efficacy statistics
(`sisyfus research lesson-stats`), so cite honestly rather than defensively.

### 3. Execute or externally settle

For a deterministic command Experiment:

```bash
sisyfus research execute <research_id> <experiment_id> --root <project>
```

For web research, human work, remote jobs, or other external execution:

```bash
sisyfus research begin <research_id> <experiment_id> --root <project>
# Produce an observation JSON with execution, metrics, artifacts, and summary.
sisyfus research settle <research_id> <attempt_id> observation.json --root <project>
```

Never manufacture missing telemetry. An incomplete run should become `INVALID`, `ERROR`, or `INCONCLUSIVE` according to the locked contract.

An experiment that must not run yet — for example a second repetition context that needs
time to pass, or a dependent measurement that needs new evidence first — declares a `wait`
(see **Waiting and wakes** below for the full lifecycle):

```json
"wait": {"kind": "time", "after": {"evidence_id": "evidence-attempt-e1-01", "minutes": 360}}
"wait": {"kind": "evidence", "until_evidence": {"claim_id": "data-valid", "verdict": "PASS"}}
```

### 4. Interpret the verdict correctly

- `PASS`: add supporting evidence; promote the claim only if repetition/context gates are met.
- `FAIL`: refute the claim and propagate dependency invalidation.
- `INCONCLUSIVE`: retain uncertainty and design a discriminating next experiment.
- `INVALID`: fix experiment design or telemetry; retry only within invalid-attempt budget.
- `ERROR`: repair infrastructure; retry without treating it as research evidence.

A State Node is committed after every settled Attempt so all branches are replayable. To explore an alternative branch, set `from_state_id` to a prior valid checkpoint.

### 5. Stop mechanically

The run is solved only when the Goal Graph root is `PASS`, all hard gates are satisfied, and the terminal evaluator accepts it. Other valid terminal states are `REFUTED`, `BLOCKED`, `EXHAUSTED`, `BUDGET_EXHAUSTED`, and `FAILED`. `WAITING` is not terminal: finalize refuses while experiments are waiting, and the wall-clock budget must cover the full calendar span the waits require.

Goal-driven stopping is symmetric and works without any budget: root `PASS` auto-stops the
run as `SOLVED` (`stop_on_goal_pass`, default on); when the root is `FAIL` and nothing is
in flight, `terminal_assessment` becomes `REFUTED` — finalize resolves it as the terminal
answer "no". Set `stop_policy.stop_on_goal_refuted: true` to make that a hard stop that
refuses further experiments (recommended, together with explicit budgets, for unattended
runs); leave it off when branch recovery from a refuted claim should stay possible.

```bash
sisyfus research finalize <research_id> --status auto --root <project>
```

Do not call an active run complete merely because the latest result looks promising.

## Waiting and wakes

A `wait` gates execution only; it never changes claim truth. Full declaration:

```json
"wait": {
  "kind": "time",
  "not_before": "2026-08-01T00:00:00Z",
  "after": {"evidence_id": "evidence-attempt-e1-01", "minutes": 360},
  "deadline_minutes": 1440,
  "on_expire": "backlog"
}
```

- `kind: time` takes exactly one of `not_before` (absolute) or `after` (relative to an
  existing evidence's recorded timestamp; resolved to an absolute time at proposal).
- `kind: evidence` takes `until_evidence: {claim_id, contract_id?, verdict?, context_id?}`
  and releases when a later matching verdict settles. `ERROR`/`INVALID` never release a wait.
- `deadline_minutes` (optional) bounds the wait from proposal time; on expiry the experiment
  goes to backlog (`on_expire: backlog`, default) or runs anyway (`release`).

Lifecycle: the experiment is admitted but held as `status: WAITING`, out of the frontier;
`begin`/`execute` refuse it and report the due time. When the wait releases, the experiment
re-enters the frontier. `status`/`context` expose `waits`, `waiting`, and `next_wake_at`.

Time enters truth only through recorded events. **Every engine preflight settles due time
waits** — `status`, `context`, `report`, `serve` page refreshes, `propose`, `begin`, and
`finalize` all fire `WAIT_FIRED`/`WAIT_EXPIRED` for anything past due. The explicit command:

```bash
sisyfus research wake <research_id> --root <project>            # settle due waits, print fired/expired/next_wake_at
sisyfus research wake <research_id> --root <project> --execute  # also run command experiments released BY THIS wake
```

Operational semantics validated on a live run:

- `--execute` only runs experiments released by that wake call. If another surface fired the
  wait first (a running `serve` page polls every 2 seconds and settles due waits on its own),
  `wake` reports `fired: []` and the experiment sits in `frontier` — run `research execute`
  on it directly.
- When the frontier is empty but experiments are waiting (`terminal_assessment: WAITING`),
  do not finalize; `finalize --status auto` refuses. Schedule a return at `next_wake_at` —
  a cron/launchd line running `wake --execute` gives unattended multi-day runs, or ask the
  host agent runtime to wake you then.
- The wall-clock budget keeps accruing while waiting: set `max_wall_minutes` to the full
  calendar span of the research program, or the wall-budget preflight will finalize
  `BUDGET_EXHAUSTED` before the wait ever fires.
- If an attempt after release settles `INVALID` repeatedly (e.g. a network outage) and the
  experiment exhausts `max_invalid_attempts_per_experiment`, it completes without a valid
  measurement. Re-measure with a **new experiment id and a changed action** (the dedupe key
  includes the action — an identical copy is rejected as duplicate). No new wait is needed
  if the required calendar separation has already passed.

## Verification contract design

Read `references/verifier-contract.md`. Prefer deterministic rules over model opinion. A contract should define:

- preconditions;
- invalidity conditions;
- hard guardrails;
- pass rules;
- fail rules;
- required artifacts;
- repetition and independent-context requirements.

Add a missing contract without mutating the locked TaskSpec:

```bash
sisyfus research contract-add <research_id> contract.json --root <project>
```

Manual contracts are exceptional and require the TaskSpec to allow manual verdicts.

## Lessons and skill improvement

Raw observations are not lessons. Create a scoped candidate only after identifying a reusable pattern:

```bash
sisyfus research lesson-add <research_id> lesson.json --root <project>
```

The natural lifecycle is one observation → candidate, second independent confirmation → promotion. Append later-earned evidence to an existing candidate instead of recreating it:

```bash
sisyfus research lesson-evidence-add <research_id> <lesson_id> <evidence_id> [...] --root <project>
```

Promotion requires evidence from at least two independent Experiments and no unresolved counterexample:

```bash
sisyfus research lesson-promote <research_id> <lesson_id> --root <project>
```

Promotion also upserts the lesson into `.sisyfus/research/global_lessons.jsonl`, the project-wide store that feeds `global_lessons` in every run's planner context; revocation updates the store as well. `global_lessons` entries are ranked by scope/topic relevance to the current TaskSpec (recency breaks ties) and carry an `efficacy` block — how often experiments cited the lesson across runs and what verdicts followed. Inspect the aggregate view with:

```bash
sisyfus research lesson-stats <research_id> --root <project>
```

Revoke a lesson when later evidence contradicts its scope:

```bash
sisyfus research lesson-revoke <research_id> <lesson_id> --reason "..." --root <project>
```

For optimization of this skill itself, use batches of scored trajectories, bounded add/delete/replace edits, a held-out selection gate, and a rejected-edit buffer. Do not rewrite the whole skill after one anecdotal failure.

## Observatory

Two delivery modes share the same projection:

```bash
sisyfus research report <research_id> --open --root <project>              # static, self-contained HTML file
sisyfus research serve <research_id> --open --port 8787 --root <project>   # hosted live monitor
```

- **`report`** writes `report/index.html` — a single offline file for archiving and sharing.
- **`serve`** hosts the same page live: every request to `/index.html` or `/snapshot.json`
  replays the event stream, settles due waits, and re-renders, so the page tracks a run
  being mutated by another process (CLI, cron, another agent). The page itself polls
  `snapshot.json` every 2 seconds and reloads whenever the snapshot hash changes — no manual
  refresh. Note the side effect: a running serve page is itself a wake surface; due time
  waits fire as soon as the next poll lands.

Prefer `serve` while a run is active (especially one with waits — the Waiting card shows
each held experiment, its release condition, and `next_wake_at`); use `report` for a
finalized run.

The Observatory is an esports-broadcast Arena. The default view maps research onto
spectator-game idioms so an observer understands the exploration at a glance:

- **Arena map** — the Goal Graph is the battlefield: claims are boss nodes connected by
  dependency edges. 👑 = SUPPORTED, ☠️ = REFUTED, 🌀 = INVALIDATED by a rollback cascade,
  amber `?!` = INCONCLUSIVE, dim `?` = untouched. The hero (the agent) stands at the claim
  the current experiment targets.
- **Combat truth rules** — PASS lands as a hit (SUPPORTED slams the announcer banner),
  FAIL is a counter-kill (screen shake + REFUTED banner + cascade markers), and
  INVALID/ERROR render as MISS: measurement failures never look like damage.
- **Top bar** — verified-vs-refuted score, attempts as HP and cost units as mana,
  objective/epistemic %, lesson loot count.
- **Kill feed & caster bar** — every event translated into one punchy line plus a
  narrated commentary sentence; the quest panel lists claims with live statuses; the
  respawn panel shows WAITING experiments and `next_wake_at`.
- **Replay deck** — a timeline with verdict/lesson/final markers (click to jump),
  play/pause at 1×/2×/4×, and a LIVE button. Each frame is a deterministic re-reduction
  of the event prefix (cached in `report/frames.json`); scrubbing time-travels through
  provable history, never an animator's guess. A `serve` page polls every 2 seconds and
  broadcasts newly landed events with full effects, no page reload.

Detail tabs (**Report / Goal Graph / Execution / Audit / Events**) keep the full audit layer:
contracts, attempts, evidence, lessons with citation counts, and the hash-chain head. The
Report tab is the answer-first final page: the optional `report` block
(`{headline, do, dont}` per language, in the TaskSpec `i18n` block or the display-only
`<run>/i18n.json` sidecar — author it at finalize time, grounded in recorded evidence)
leads, followed by per-claim one-liners, with the full evidence and loot details folded
behind disclosures; printing the page strips the broadcast chrome down to that report.

The score reflects verdict-backed claim statuses only — never token use, elapsed time,
report length, or Planner confidence. Epistemic progress is displayed separately.

## Recovery and audit

After interruption:

```bash
sisyfus research recover <research_id> --root <project>
sisyfus research replay <research_id> --root <project>
sisyfus research reproduce <research_id> <evidence_id> --root <project>
```

Recovery records stranded Attempts as `ERROR` and requeues their Experiments. Replay must reproduce the same snapshot hash from the event stream. Reproduce independently re-derives one command evidence — hash-checks the measurement code, re-runs it, diffs the metrics, and re-classifies under the locked contract — recording the outcome in the event chain (see `references/verifier-contract.md` § Trust model).

## Output discipline

When reporting to the user, include:

- current Goal Graph root status;
- objective and epistemic progress separately;
- strongest supported and refuted claims;
- frontier and next discriminating experiment;
- waiting experiments and `next_wake_at` whenever a wait is pending;
- verifier gaps and invalid/error rates;
- budget remaining;
- exact HTML report path (and the serve URL if a live monitor is running).

Never collapse `FAIL`, `INVALID`, `ERROR`, and `INCONCLUSIVE` into a generic failure count.
