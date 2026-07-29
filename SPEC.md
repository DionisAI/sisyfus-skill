# Sisyfus Engineering Spec v0.7

## Thesis

Sisyfus is an event-sourced research control plane, not an autonomous monologue. The system converts an open-ended topic into a bounded environment of claims, actions, verification contracts, state transitions, and terminal conditions.

The user-facing artifact is one **Sisyfus Research Skill**. The runtime remains a separate deterministic harness. A skill can monitor and steer a run, but it cannot become the source of truth for that run.

## Architecture

```text
Sisyfus Research Skill
  ├─ inspect status/context
  ├─ compile TaskSpec and verifier contracts
  ├─ propose bounded experiments
  ├─ call command/external tools
  └─ open the HTML Observatory

Research Engine
  ├─ TaskSpec compiler
  ├─ admission controller
  ├─ attempt WAL and recovery
  ├─ deterministic verifier
  ├─ deterministic state reducer
  ├─ terminal evaluator
  ├─ budget manager
  └─ append-only event store

Projections
  ├─ Goal Graph
  ├─ Execution Graph
  ├─ Evidence Graph
  ├─ frontier / lessons / snapshot
  └─ self-contained HTML Observatory
```

## Core invariants

1. `events.jsonl` is the authoritative state; every event includes sequence, previous hash, and event hash.
2. TaskSpec and an Attempt's verification contract are immutable after lock/reservation.
3. A State Node is an immutable accepted-knowledge snapshot.
4. An Experiment is an edge from a State Node, not a State Node itself.
5. An Attempt is a concrete execution of one Experiment.
6. Each admitted Experiment targets exactly one Claim through exactly one versioned contract.
7. `ERROR` and `INVALID` never alter claim truth.
8. Planner output cannot directly modify claims, state, terminal status, or active lessons.
9. Goal completion is the deterministic evaluation of an AND/OR Goal Graph.
10. HTML and JSON graph files are projections and may be deleted/rebuilt.
11. A branch failure preserves its parent state. Dependency rollback occurs only after upstream refutation.
12. Lessons require evidence and explicit promotion; no automatic reflection promotion.

## TaskSpec v2

A TaskSpec contains:

```text
id
topic
claims[]
  id, statement, required, critical, weight, depends_on
goal_graph
  root_id, AND/OR/CLAIM nodes
hard_constraints[]  # descriptive; enforce through claims/guardrails
action_space[]       # admission-checked against Experiment.action_family
verification_contracts[]
budget
  max_attempts, max_cost_units, max_wall_minutes
stop_policy
  stop_on_goal_pass
  block_without_verifier
  allow_manual_verdict
  max_invalid_attempts_per_experiment
  max_error_attempts_per_experiment
```

Compilation rejects duplicate IDs, unknown dependencies, dependency cycles, Goal Graph cycles, missing required claims, unknown claim references, and metric contracts without both pass and fail rules.

## Verification contract v2

A metric contract defines:

```text
id / version / target_claim_id
description
preconditions
invalid_if
guardrails
pass_if
fail_if
required_artifacts
repetition.min_passes
repetition.min_independent_contexts
visibility
```

Rule groups have optional `all` and `any` checks. Supported operators are equality, inequality, numeric comparisons, membership, contains, regex, existence, truthiness, and approximate equality.

Evaluation order is fixed:

```text
execution fault                 -> ERROR
missing artifact/precondition/
invalidity condition            -> INVALID
guardrail violation             -> FAIL
pass and fail both match        -> INVALID
pass rule matches               -> PASS
fail rule matches               -> FAIL
otherwise                       -> INCONCLUSIVE
```

A raw PASS may produce a provisional claim effect until repetition and independent-context gates are met.

## Three graphs

### Goal Graph

AND/OR/CLAIM nodes mechanically determine the final root status. Claim dependency is separate from Goal composition: dependency controls invalidation, while AND/OR controls sufficiency.

### Execution Graph

```text
State S0
  ├─ Experiment E1 → Attempt A1 → Verdict → State S1
  ├─ Experiment E2 → Attempt A2 → Verdict → State S2
  └─ Experiment E3 → Attempt A3 → ERROR → State S3 (truth unchanged)
```

Experiments may start from any existing state. Multiple parents are supported through explicit merge metadata, making the graph a DAG rather than a strict tree.

### Evidence Graph

Evidence nodes link to Claims as:

```text
supports
provisional_support
refutes
qualifies
```

Every link is traceable to Experiment, Attempt, contract version/hash, observation metrics, artifacts, and verdict reason.

## Event model

Core events:

```text
RUN_CREATED
SPEC_LOCKED
CONTRACT_ADDED
EXPERIMENT_PROPOSED
EXPERIMENT_ADMITTED
EXPERIMENT_BACKLOGGED
EXPERIMENT_PRUNED
ATTEMPT_RESERVED
ATTEMPT_STARTED
OBSERVATION_RECORDED
VERDICT_ISSUED
WAIT_FIRED
WAIT_EXPIRED
LESSON_CANDIDATE_CREATED
LESSON_EVIDENCE_ADDED
LESSON_PROMOTED
LESSON_REVOKED
RUN_PAUSED
RUN_RESUMED
RUN_FAILED
RUN_FINALIZED
REPORT_RENDERED
```

`ATTEMPT_RESERVED` stores a hash of the locked contract and a copy of the action. A verifier refuses promotion if the current contract hash differs at settlement.

## Admission

A proposal is backlogged rather than executed when it:

- lacks a verifier;
- binds an unknown verifier;
- targets a different claim from the contract;
- duplicates an existing experiment in the same context;
- requires a disallowed manual verdict;
- starts from an unknown state;
- exceeds attempt, cost, or wall-clock budget;
- uses an `action_family` outside the TaskSpec `action_space`;
- starts from a State where target-claim dependencies are not supported.

The default planner policy proposes at most three diverse, decision-relevant experiments.

## Wait conditions

An Experiment may declare an optional `wait`. Waiting experiments are admitted but held out
of the frontier (`status: WAITING`); `begin` refuses them. Waits gate execution only — they
never alter claim truth.

```text
wait.kind = time
  not_before            # absolute ISO timestamp, or
  after                 # {evidence_id, minutes} resolved to an absolute
                        # not_before_ts at proposal from the evidence's recorded time
wait.kind = evidence
  until_evidence        # {claim_id, contract_id?, verdict?, context_id?}
common
  deadline_minutes      # optional; deadline_ts = proposal time + deadline_minutes
  on_expire             # backlog (default) | release
```

Time enters research truth only through events, mirroring the wall-clock budget preflight:

- evidence waits are satisfied deterministically by a later matching `VERDICT_ISSUED`
  (only settled verdicts with claim effects match; `ERROR`/`INVALID` never release a wait);
- time waits are satisfied only when a wake preflight records `WAIT_FIRED`;
- passed deadlines record `WAIT_EXPIRED`, sending the experiment to backlog
  (`backlog_reason: wait_expired`) or releasing it per `on_expire`.

The snapshot exposes `waits` and `next_wake_at` (the earliest pending `not_before_ts` or
`deadline_ts`). `research wake` runs the preflight explicitly; `--execute` runs command
experiments released by that wake. Scheduling stays external (cron, launchd, host agent).
`terminal_assessment` gains `WAITING`: an empty frontier with waiting experiments is not
`EXHAUSTED`, and finalize refuses it. The wall-clock budget keeps accruing while waiting —
`max_wall_minutes` is the calendar deadline of the whole research program.

## Budgets and retry

- PASS/FAIL/INCONCLUSIVE/INVALID consume committed attempt budget.
- ERROR consumes infrastructure-error count but not committed verification-attempt count; real cost units may still be charged.
- INVALID retries are capped per Experiment.
- ERROR retries are capped per Experiment.
- Cost and total committed-attempt ceilings are hard terminal gates.

## Terminal states

```text
SOLVED
BLOCKED
EXHAUSTED
BUDGET_EXHAUSTED
FAILED
```

`SOLVED` requires Goal Graph root `PASS`. A terminal evaluator cannot override this condition.

## Observatory

The report is a single local HTML file backed only by persisted facts. It contains:

1. Arena — an esports-broadcast spectator view: the Goal Graph as a battlefield of claim nodes, a hero unit at the active target, kill feed, caster commentary, HP/mana budget bars, announcer banners, and a replay deck over deterministically re-reduced event-prefix frames (zh/en toggle, live polling without reloads).
2. Goal Graph — completion structure and verifier coverage.
3. Execution Graph — states, parents, experiments, attempts, verdicts.
4. Audit — contracts, attempts, evidence (with reproduction records), lessons.
5. Events — full append-only event stream and chain head.
6. Report — answer-first final summary (headline/do/don't per language), claim one-liners, evidence disclosures; print-ready.

Visual semantics:

- score / claim node skins = verdict-backed claim statuses only;
- epistemic progress is displayed separately from objective progress;
- FAIL = counter-kill (refutation), with dependency cascades shown;
- INVALID/ERROR = MISS — measurement failures never render as damage;
- budget bars drain only on declared budgets; omitted limits show ∞.

## Skill boundary

The shipped `SKILL.md` instructs an agent how to operate the engine, not how to bypass it. The skill is installed to `.sisyfus/skills/sisyfus-research/` by `sisyfus init` and also exists repo-locally under `.agents/skills/`.

The engine does not include a provider-specific LLM planner. Any capable agent or external planner can use `research context`, write Experiment JSON, and call the CLI. This separation keeps planning replaceable and truth transitions deterministic.

## v0.7 non-goals

- hosted distributed execution;
- vector database or graph database;
- live trading or account-changing connectors;
- automatic human-free promotion of open-ended model judgments;
- universal verifier generation for every research domain;
- automatic SkillOpt training loop. The skill documents the required bounded/held-out protocol, but v0.7 does not ship a benchmark optimizer.

## Acceptance

v0.7 is accepted when:

- old v0.6 tests remain green;
- TaskSpec compiler rejects ambiguous/cyclic specifications;
- all five verifier outcomes are distinct;
- ERROR/INVALID do not refute claims;
- repetition gates work across independent contexts;
- sibling branch exploration from an earlier checkpoint works;
- upstream refutation invalidates dependents and lowers progress;
- stranded attempts recover as ERROR;
- event hash chain and replay snapshot hash are stable;
- command experiments capture metrics/artifacts and settle deterministically;
- the skill installs with references/templates;
- the HTML Observatory renders from persisted state only.
