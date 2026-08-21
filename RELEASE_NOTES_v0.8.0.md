# Sisyfus v0.8.0

**Release date:** 2026-08-20
**Theme:** Monitor-first, verifier-gated autonomous research

## Overview

Sisyfus v0.8.0 is a substantial release. It combines the existing event-sourced
research engine with a durable autonomy control plane and a continuously hosted,
game-style Mission Control. The system now guides the user through research
intake, keeps long-running work observable, survives worker restarts, and still
refuses to let a planner or UI telemetry alter research truth.

## Major changes

### 1. Mission Control starts immediately

The first Skill action now hosts and opens Mission Control. It uses a stable
per-project URL and remains the same browser surface from initial intake through
the final report.

The live projection includes:

- current phase and operation;
- progress and elapsed time;
- worker heartbeat, stale detection, and reconnect state;
- current attempt and verifier activity;
- waits, user questions, failures, and recovery events;
- child-process progress through `$SISYFUS_PROGRESS_FILE`.

Operational telemetry is deliberately separate from Evidence. A process saying
"100% complete" cannot create a PASS or modify a Claim.

### 2. Proactive clarification before research

Sisyfus now treats three intake dimensions as blocking contracts:

1. **Scope** — included and excluded systems, markets, repositories, datasets,
   time periods, actions, constraints, and deliverables.
2. **Objective** — the artifact or decision to produce and a mechanically
   recognizable completion condition.
3. **Verification** — the test, backtest, benchmark, authority, rubric, or human
   gate that is allowed to reject the result.

When a material dimension is absent or contradictory, the Skill records:

```text
phase      CLARIFYING
status     NEEDS_USER
operation  research.intake.clarify
```

It asks one compact batch of unresolved questions, reuses information already
provided, and resumes only after locking Scope / Objective / Deliverables /
Verifier / Completion / Constraints.

### 3. Unified preflight and research Arena

The old standalone bootstrap splash has been removed. Before Claims exist, the
same Arena shell displays a preflight dependency map:

```text
Scope → Objective → Qualified Inputs → Claim Graph → Verifier → Autonomous Run
```

After TaskSpec compilation, the preflight nodes are replaced by the real Claim
Graph without switching visual products. Both phases share:

- `sisyfus-arena-broadcast-v1` theme tokens;
- broadcast top bar and score area;
- SVG map, node, edge, hero, and unit-card grammar;
- right-side feed, quest panel, waiting area, replay deck, caster bar, and tabs;
- responsive and reduced-motion behavior;
- a restyled live HUD using the same theme source.

### 4. Canonical 24×7 autonomy runtime

A single public autonomy API and a single versioned SQLite schema now implement:

- SQLite WAL with transactional mutations;
- opportunity deduplication and admission;
- durable Continuations and optimistic versions;
- opaque renewable leases and expiry-enforced writes;
- heartbeat fencing across planner, capability, and verifier calls;
- persisted Decisions and crash-safe `RESERVED` / `EXECUTED` recovery;
- stable idempotency keys and receipts;
- `UNKNOWN_COMMIT` blocking for unresolved non-replay-safe side effects;
- bounded retries, wake times, exhaustion, and terminal-state invariants;
- a continuous Supervisor suitable for systemd, containers, or Kubernetes.

### 5. Verifier-owned truth

The control flow is explicit:

```text
Sensor → Planner proposal → Policy admission → Capability execution
       → independent Verifier → Evidence → Reducer → terminal evaluator
```

The Planner cannot declare itself successful. Completion requires persisted PASS
evidence, and the five verdict outcomes retain distinct meanings:

```text
PASS / FAIL / INCONCLUSIVE / INVALID / ERROR
```

Final-attempt PASS can complete without consuming another execution attempt;
final INCONCLUSIVE becomes terminal rather than stranded.

### 6. Evidence-safe experience

Positive, negative, and operational experience remains linked to verifier
Evidence. Counts now derive from unique experience observations, so retrying or
replaying one Evidence ID cannot manufacture independent support or promote a
lesson falsely.

### 7. Safety and operational hardening

- typed Capability registry with unattended risk tiers;
- default unattended ceiling of R0/R1;
- exact `--root` handling;
- shell-command confirmation for research experiments;
- environment allowlisting for command planners;
- streamed, bounded subprocess output;
- process-group timeout termination;
- malformed or oversized sensor files quarantined independently;
- bounded sensor iteration and admission-before-persistence;
- versioned schema and incompatible-layout detection.

## New and important commands

```bash
# Start the one stable Mission Control surface
sisyfus research monitor-start \
  --task "..." \
  --objective "..." \
  --root .

# Record that material user input is required
sisyfus research monitor-clarify \
  --missing scope \
  --missing verification \
  --question "..." \
  --root .

# Resume after locking the intake contract
sisyfus research monitor-resume \
  --summary "..." \
  --root .

# Operate the durable autonomy runtime
sisyfus-autonomy init
sisyfus-autonomy submit ...
sisyfus-autonomy status
sisyfus-autonomy recover
sisyfus-autonomy verify-chain
sisyfus-autonomy run --once ...
```

## Compatibility and operational notes

- Python 3.11 or newer is required.
- Mission Control hosting is enabled by default. Use `SISYFUS_AUTO_SERVE=0`
  only for deliberately headless operation.
- Use `SISYFUS_AUTO_OPEN=0` to keep hosting and activity recording while
  suppressing automatic browser opening.
- Existing research truth remains event-sourced. The autonomy database is a
  control plane; it does not make UI telemetry authoritative.
- High-risk external capabilities still require OS-level isolation, scoped
  secrets/network access, and provider-native reconciliation.

## Validation

The release candidate passes:

- full repository regression suite: **151 tests**;
- Python **3.11**, **3.12**, and **3.13** CI matrix;
- dedicated visual-continuity tests for bootstrap and full Arena;
- Mission Control lifecycle and clarification-gate tests;
- lease, recovery, idempotency, duplicate-evidence, sensor, and CLI coverage.

## Upgrade

```bash
python3 -m pip install --upgrade \
  "sisyfus @ git+https://github.com/DionisAI/sisyfus-skill@v0.8.0"
sisyfus --version
```
