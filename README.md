# Sisyfus

Sisyfus is a local-first control plane for auditable agent work and autonomous research. Its central rule is stricter than “an agent keeps thinking”:

> A planner may propose experiments, but only a preregistered verifier and deterministic reducer may change research truth.

v0.7 adds a complete **Sisyfus Research Skill** over the existing v0.6 harness. The skill is the user-facing control surface; the Python engine owns state, event replay, verification, budgets, and reports.

## What changed in v0.7

The old bounded Beam model remains available for legacy workflows, but new research runs use a more precise model:

- **TaskSpec compiler**: topic → falsifiable claims, AND/OR Goal Graph, constraints, action space, verification contracts, budgets, and stop policy.
- **Three separate graphs**:
  - Goal Graph: what must be established;
  - Execution Graph: immutable State Nodes, Experiment edges, and Attempts;
  - Evidence Graph: why a claim is supported, refuted, or still qualified.
- **Five verifier outcomes**: `PASS`, `FAIL`, `INCONCLUSIVE`, `INVALID`, and `ERROR`.
- **Preregistered verification contracts**: preconditions, invalidity rules, hard guardrails, pass/fail rules, artifacts, and repetition gates.
- **Append-only hash-chained events**: every projection can be rebuilt and replay-checked.
- **True branching and rollback**: an alternative experiment may start from any prior checkpoint; refuting an accepted upstream claim invalidates dependents.
- **WAL-style attempts and recovery**: reserved/running attempts survive interruption and recover as infrastructure errors, not false research failures.
- **Scoped lesson lifecycle**: raw observations → candidate lesson → evidence-gated explicit promotion → revocation.
- **Self-contained HTML Observatory ("Arena")**: an esports-broadcast spectator view — the Goal Graph is a battlefield of claim "bosses", verdicts land as hits or counter-kills, budgets drain as HP/mana, every event becomes a kill-feed line with caster commentary, and a replay deck scrubs deterministically re-reduced frames of the whole run. INVALID/ERROR render as MISS: measurement failures never look like progress. Fully bilingual (zh/en toggle, data-layer i18n included) plus a print-ready final Report tab.

The implementation is dependency-free at runtime and remains file-based.

## Highlights since 0.7.0

See `CHANGELOG.md` for detail. In brief:

- **Waits and wakes (0.7.2)**: experiments can wait on wall-clock time or future evidence; one cron line (`sisyfus research wake --execute`) gives unattended multi-day runs.
- **Learning loop (0.7.3)**: experiments cite the evidence/lessons they build on (`based_on`, admission-checked); promoted lessons flow into a project-wide store, relevance-ranked into every planner context, with cross-run efficacy statistics (`lesson-stats`).
- **Visual replay (0.7.3+)**: every event prefix is re-reduced into a keyframe by the same deterministic reducer — scrubbing the timeline time-travels through provable history, never an animation.
- **Symmetric goal stopping (0.7.4)**: root PASS auto-stops as `SOLVED`; a refuted root with nothing in flight resolves as `REFUTED` (opt-in hard stop). Budgets are opt-in guardrails — omitted limits are unlimited, declared limits are hard.
- **Deterministic evidence reproduction**: `sisyfus research reproduce <run> <evidence_id>` hash-checks the recorded measurement code, re-runs it, diffs the metrics, and re-classifies under the same locked contract — zero models involved. The verifier trust model is documented in the skill's `references/verifier-contract.md`.

## Install

```bash
python -m pip install -e .
```

## Initialize

```bash
mkdir /tmp/sisyfus-demo
cd /tmp/sisyfus-demo
sisyfus init
```

The relevant new layout is:

```text
.sisyfus/
  research/
    index.jsonl
    runs/<research_id>/
      task.json
      events.jsonl              # source of truth
      snapshot.json             # rebuildable projection
      goal_graph.json
      execution_graph.json
      evidence_graph.json
      frontier.json
      lessons.json
      attempts/
      artifacts/
      report/
        index.html
        snapshot.json
  skills/
    sisyfus-research/
      SKILL.md
      references/
      templates/
```

Earlier `.sisyfus/goals`, sessions, beams, monitors, Outcomes rubrics, experiment ledger, review, and memory files remain supported.

## Run the built-in research demonstration

```bash
sisyfus research demo --root /tmp/sisyfus-demo
sisyfus research status latest --root /tmp/sisyfus-demo
sisyfus research replay latest --root /tmp/sisyfus-demo
sisyfus research report latest --open --root /tmp/sisyfus-demo
sisyfus research serve latest --open --root /tmp/sisyfus-demo
```

The demonstration includes:

- a verified data checkpoint;
- one valid but failed candidate branch;
- a second branch from the earlier checkpoint that succeeds;
- a two-context repetition gate;
- a solved Goal Graph and HTML Observatory.

## Start a real research run

Copy the installed template or create a TaskSpec JSON:

```bash
cp .sisyfus/skills/sisyfus-research/templates/research-task.json task.json
sisyfus research new task.json
```

A minimal TaskSpec:

```json
{
  "id": "candidate-method",
  "topic": "Determine whether the candidate method is valid and robust",
  "claims": [
    {
      "id": "method-works",
      "statement": "The method reaches the preregistered out-of-sample threshold",
      "required": true,
      "weight": 1.0
    }
  ],
  "verification_contracts": [
    {
      "id": "verify-method",
      "version": "1",
      "target_claim_id": "method-works",
      "pass_if": {
        "all": [{"path": "metrics.oos_score", "op": ">=", "value": 0.7}]
      },
      "fail_if": {
        "all": [{"path": "metrics.oos_score", "op": "<", "value": 0.3}]
      },
      "invalid_if": {
        "any": [{"path": "metrics.leakage", "op": "==", "value": true}]
      },
      "repetition": {
        "min_passes": 2,
        "min_independent_contexts": 2
      }
    }
  ],
  "budget": {
    "max_attempts": 20,
    "max_cost_units": 20,
    "max_wall_minutes": 120
  }
}
```

Budgets are opt-in guardrails: omit any limit for unlimited. Set explicit budgets for
unattended runs — an unbudgeted cron run has no mechanical stop.

Inspect the bounded planner context:

```bash
sisyfus research context <research_id>
```

## Propose and run an experiment

```bash
cp .sisyfus/skills/sisyfus-research/templates/experiment.json experiment.json
sisyfus research propose <research_id> experiment.json
```

Command-backed experiment:

```bash
sisyfus research execute <research_id> <experiment_id>
```

External/web/human/remote experiment:

```bash
sisyfus research begin <research_id> <experiment_id>
sisyfus research settle <research_id> <attempt_id> observation.json
```

The observation schema is intentionally simple:

```json
{
  "summary": "What was observed",
  "execution": {"exit_code": 0, "timed_out": false},
  "metrics": {"oos_score": 0.76, "leakage": false},
  "artifacts": [
    {"path": "summary.json", "sha256": "..."}
  ],
  "metadata": {}
}
```

## Correct verdict semantics

| Verdict | Meaning | Claim update |
|---|---|---|
| `PASS` | Valid experiment supports the claim | Support only after repetition gate |
| `FAIL` | Valid experiment refutes the claim or violates a hard guardrail | Refute and propagate invalidation |
| `INCONCLUSIVE` | Valid experiment is not decisive | Preserve uncertainty |
| `INVALID` | Experiment did not measure the claim correctly | No truth inference; bounded redesign/retry |
| `ERROR` | Infrastructure or execution failed | No truth inference; bounded retry |

The planner cannot mark a task solved. The run becomes `SOLVED` only when the Goal Graph root evaluates to `PASS`.

## Branching, checkpoints, and rollback

Every settled Attempt creates an immutable State Node. An Experiment normally starts from the current state, but it may explicitly use a prior `from_state_id` to explore a sibling branch.

A failed Experiment does not erase its parent checkpoint. Verified progress rolls back only when an upstream claim that was previously supported becomes refuted; dependent claims become `INVALIDATED` automatically.

## Add a missing verifier

Unsupported claims are visible in `verifier_gaps` and block progress by default:

```bash
sisyfus research contract-add <research_id> contract.json
```

Contracts are versioned and copied into every Attempt manifest by hash before execution.

## Recovery, replay, and reproduction

```bash
sisyfus research recover <research_id>
sisyfus research replay <research_id>
sisyfus research reproduce <research_id> <evidence_id>
```

Recovery converts stranded Attempts into `ERROR`, then requeues the Experiment within its retry policy. Replay verifies both the event hash chain and deterministic snapshot hash. Reproduce independently re-derives one command evidence — hash-checks the measurement code, re-runs it, diffs the metrics, re-classifies under the locked contract — and records the outcome in the event chain.

## Lessons

```bash
sisyfus research lesson-add <research_id> lesson.json
sisyfus research lesson-promote <research_id> <lesson_id>
sisyfus research lesson-revoke <research_id> <lesson_id> --reason "contradicted by later evidence"
```

Promotion requires evidence from at least two independent Experiments by default. There is no automatic promotion of free-form reflection.

## Enforcement notes

- `task.json` is hash-locked by the event stream; edit it only by creating a new run.
- Every Experiment has an admission-checked `action_family`, and dependent claims may run only from a State where their prerequisites are supported.
- Declared attempt, cost, and wall-clock budgets are enforced as hard ceilings; omitted limits are unlimited by design.
- `hard_constraints` text is documentation; encode enforceable constraints as required Claims or verifier guardrails.

## Legacy v0.6 capabilities

These commands remain available:

```bash
sisyfus goal new ...
sisyfus run ...
sisyfus verify ...
sisyfus beam ...
sisyfus rubric ...
sisyfus outcome ...
sisyfus experiment ...
sisyfus memory ...
sisyfus monitor ...
sisyfus dashboard ...
```

They provide one-task sessions, deterministic monitors, bounded legacy beam search, artifact rubrics, experiment golf, memory FSM, human review, model routing, and the original dashboard.

## Test

```bash
python -m pytest -q
```

v0.7 ships regression tests for the old harness plus TaskSpec validation, all five verdicts, repetition gates, branch recovery, dependency rollback, event replay, command execution, skill installation, CLI, and HTML report generation.
