# Live Mission Control and Activity Protocol

Sisyfus follows a monitor-first lifecycle.

## First-use behavior

The first command issued by the Skill for a new task is:

```bash
sisyfus research monitor-start \
  --task "<short task title>" \
  --objective "<completion objective>" \
  --root <project>
```

This command:

1. creates `.sisyfus/live/activity.json`;
2. renders the game-style bootstrap Mission Control page;
3. starts or reuses the stable per-project local HTTP server;
4. opens the page in the default browser;
5. returns the stable monitor URL.

`SISYFUS_AUTO_SERVE=0` disables daemon spawning.
`SISYFUS_AUTO_OPEN=0` disables browser opening. These switches are intended for
CI, headless services, or environments where another process owns the browser.

When `research new` creates the real research run, the bootstrap daemon is
replaced on the same stable port. The already-open bootstrap page detects
`snapshot.json` and reloads into the full Arena automatically.

## Clarification and user-wait state

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

## Unified broadcast shell

The bootstrap Mission Control is not a separate splash application. It uses the
same `sisyfus-arena-broadcast-v1` visual system and the same structural shell as
the post-TaskSpec Observatory:

```text
broadcast top bar
arena map
right-side match feed and quest panel
replay deck
caster bar
detail tabs
```

Before Claims exist, the map renders the intake gates — Scope, Objective,
Inputs, Claims, Verifier, and Autonomous Run — using the same nodes, dependency
edges, hero, status colors, and unit card used by the real Claim map. Handoff
changes the projection and enables the full tabs; it does not replace the page
with a visually unrelated application.

Palette and typography tokens live in `sisyfus.ui_theme` and are injected into
both documents. Structural tests require both rendered pages to declare the
same theme ID and broadcast-shell markers, preventing the two surfaces from
drifting apart again.

## Live activity state

The authoritative live status projection is:

```text
<root>/.sisyfus/live/activity.json
```

It reports:

- logical task ID and research ID;
- current phase and operation;
- running/completed/error status;
- current message and detail;
- progress;
- operation start time, elapsed time, and heartbeat time;
- actor, PID, and bounded metadata.

Phase changes are also projected to:

```text
<root>/.sisyfus/live/activity-events.json
```

The Arena and bootstrap monitor poll the activity projection independently from
the research snapshot. A long backtest therefore remains visibly alive even
when no verifier event has yet been committed.

## Child-process progress protocol

Command experiments receive:

```text
SISYFUS_PROGRESS_FILE=<root>/.sisyfus/live/progress.json
```

A backtest or other long-running program may atomically replace that file with:

```json
{
  "current": 420000,
  "total": 1000000,
  "label": "market events",
  "message": "Replaying 2026-07-14",
  "detail": "BTCUSDT / volatility regime 3"
}
```

It may alternatively provide an explicit `percent`.

The activity heartbeat consumes the file and projects it into the page. This
file is telemetry only: it cannot change Claim truth or issue a verifier
verdict.

## Research phases

Typical research phases are:

```text
INTAKE
INITIALIZING
INSPECTING
PLANNING
EXECUTING
COLLECTING
VERIFYING
RECOVERING
LEARNING
FINALIZING
READY
```

The autonomy supervisor additionally reports:

```text
DISCOVERING
AUTONOMY_PLANNING
AUTONOMY_EXECUTING
AUTONOMY_VERIFYING
WAITING
```

## Trust boundary

Live activity is an operational projection, not research evidence.

The monitor may display:

- what is currently running;
- how long it has been running;
- its emitted progress telemetry;
- the most recently committed state and evidence.

It may not infer missing results, claim that a step succeeded before verifier
settlement, or convert progress telemetry into a PASS verdict.
