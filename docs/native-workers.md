# Native workers: an opt-in Sisyfus control-plane increment

This opt-in module, included in v0.9.0, extends the existing `AutonomousRuntime`, `AutonomyStore`,
`AutonomousSupervisor` and `research_v2.verifier.classify_observation`. It is not
another task-truth database or a demonstrated research gain.
The original evaluators and holdouts remain unchanged.

## What runs

An operator locks a mission specification: source snapshot, native executors and
models, required acceptance checks, evaluator hashes, call and retry limits.
A configured Codex or Claude planner can propose a bounded task DAG. Alternatively,
the operator supplies that DAG. A proposal cannot introduce executable tools,
change acceptance contracts, exceed retry limits or omit mandatory checks.

Existing continuations then drive:

```
planner proposal -> validate DAG -> existing continuation admission
  -> current dependency evidence -> reserve native invocation
  -> native session in an isolated candidate directory -> durable receipt
  -> unchanged research verifier classifier -> existing canonical verdict
  -> bounded repair with independent feedback OR dependent task unlock
```

The scheduler after initial decomposition is deterministic. Repair feedback is
passed to the next native attempt. Automatic replanning of graph structure,
learned executor routing and deployment of new policies are not implemented in
this increment. This is task-level iterative repair, not measured cross-task RSI.

## Entry points

Install this branch in a virtual environment with Python 3.11+, then:

```bash
python -m pip install -e .
sisyfus workers doctor
sisyfus workers demo --directory /tmp/sisyfus-native-demo
sisyfus workers serve --directory /tmp/sisyfus-native-demo/control --open
```

`python -m sisyfus.workers` and `python -m sisyfus workers` are equivalent worker
entry points. The installed CLI uses a thin router; the original CLI implementation
and its commands remain unchanged. Legacy top-level help does not list `workers`;
use `sisyfus workers --help`.

The demo launches real local subprocesses implementing **protocol fixtures**,
not real Codex, Claude or LLMs. Its deterministic plan has a failed first build,
a repaired build, and a dependent review. It should use four native-invocation
reservations, retain both FAIL and PASS evidence, and finish without unknown work.
Fixture token and cost values are fabricated test inputs, not API usage or savings.

For an approved live mission:

```bash
sisyfus workers up /absolute/path/mission.json \
  --directory /absolute/path/separate-control-directory \
  --allow-local-workers --open
```

The source and control directories must be disjoint. Source edits after approval
are rejected, not silently accepted on restart. To continue an unchanged mission,
run the same command with the same specification and control directory.
`serve` only attaches a browser to existing persisted data; it does not start workers.
`run` executes without an HTTP server. Closing the browser does not stop `up`.
Stopping its controller does require a restart; no systemd/launchd installer is
provided. When a bounded mission finishes, the `up` console stays available for
inspection. HTTP connectivity does not itself prove that a worker is running.

```bash
sisyfus workers status --directory /absolute/path/control
sisyfus workers export --directory /absolute/path/control --output trace.json
```

Export contains canonical event sequence references and verification artifacts.
Its chain check is performed against the database. It is not a replacement for
the complete database, nor yet an input adapter for `research_os` policy replay.

## Mission specification

Use actual installed executable paths, explicitly selected model names and real
hashes. Do not copy placeholder model names or a placeholder hash into a live run.
The following is a schema example, not a ready-to-run configuration:

```json
{
  "objective": "Implement and independently verify the requested change",
  "source": "/absolute/path/project",
  "planner": "claude",
  "drivers": {
    "codex": {"model": "YOUR_CODEX_MODEL", "command": ["codex"]},
    "claude": {"model": "YOUR_CLAUDE_MODEL", "command": ["claude"]}
  },
  "checks": {
    "acceptance": {
      "argv": ["/absolute/path/python", "-I", "-S", "/trusted/check.py", "{candidate}"],
      "code_hashes": {"/trusted/check.py": "ACTUAL_SHA256"},
      "contract": {
        "kind": "rules",
        "pass_if": {"all": [{"path": "accepted", "op": "eq", "value": true}]},
        "fail_if": {"all": [{"path": "accepted", "op": "eq", "value": false}]}
      }
    }
  },
  "required_checks": ["acceptance"],
  "max_calls": 8,
  "parallelism": 2,
  "max_attempts": 3,
  "timeout": 300,
  "max_turns": 8
}
```

`required_checks` defaults to all registered checks. With an operator-supplied
`tasks` array, omit `planner`. A task has `id`, `objective`, `driver`, `check`,
optional `depends_on` and `max_attempts`. All mandatory checks must be covered.
An accepted decomposition does not prove semantic completeness of the original
objective: only a sufficiently strong operator-owned acceptance check can do that.

A check receives the candidate path as one argv element and emits exactly one
JSON object. Actual process exit status overwrites any self-reported status.
Nonzero process exits, missing output and changed measurements cannot produce
PASS. Measurement files must be outside the mutable project and hash-pinned.
All executable measurement inputs and dependencies are the operator's responsibility;
this pilot does not infer transitive imports or freeze the OS/toolchain.

Checks should test the candidate with trusted tests outside the writable snapshot,
not let candidate-written tests certify themselves. No candidate is automatically
merged into the original project. Upstream artifacts are copied under
`inputs/<task_id>`; a downstream integrator must explicitly compose them. This is
not an automatic Git merge algorithm.

## Native interfaces and permissions

Codex uses `codex app-server` JSONL over stdio: initialize, create/resume a thread,
start a turn, stream native events, optional steer/interrupt. Approval escalation
is declined. The requested sandbox is read-only for planning and workspace-write
for implementation, with network disabled in the turn sandbox policy.

Claude uses native `claude -p --output-format stream-json --verbose
--include-partial-messages`. It receives a restricted Read/Glob/Grep tool set,
plus Write/Edit for implementation. Bash, Agent and Task are not supplied by this
adapter. MCP configuration is explicitly empty, external setting sources are
excluded, and unattended permission mode is `dontAsk`. This restricted worker
can edit files; the independent checker executes acceptance tests.

Claude live steering is unsupported and rejected, not emulated as a working
button. CLI interruption without a native final result remains UNKNOWN.
Native protocol request objects support explicit session IDs, but missions do
not automatically resume or replay an unknown turn. No session-recovery button
claims that uncertain work did not execute.

`max_turns` is forwarded to Claude. Codex uses one app-server turn per attempt;
this setting does not cap its internal model/tool iterations. Native Codex child
agents, if enabled in the operator's installation, are logged only to the extent
exposed by native events. They are not independently scheduled or cancelled by
this pilot. Use an operator-owned restricted native configuration.

`doctor` probes executable presence/version without making model calls. It reports
`authenticated: null`; executable availability is not proof of authentication.
Use the providers' installed authentication flows on the worker host. Never put
keys in the specification or paste keys into conversation. Explicit `env_names`
may forward `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `CODEX_HOME` or
`CLAUDE_CONFIG_DIR`. Other secret environment variables are not forwarded to
worker launches. Existing HOME-based authentication/configuration can still be read.

Official protocol references used for the implementation:
- https://developers.openai.com/codex/app-server
- https://code.claude.com/docs/en/headless
- https://code.claude.com/docs/en/cli-reference

A live authenticated provider run has not been established by the offline tests.
Operators must pin and validate their native CLI versions. Protocol fixtures are
not proof that every future native version accepts the same schema and flags.

## Persistence, failure and concurrency

Only native transport receipts and operator commands are new SQLite extension
tables; they live in the same existing autonomy database. Existing continuations,
leases, decisions, evidence, verdicts and append-only event hashes stay canonical.

An intent is committed before native dispatch. A matching terminal receipt can
be reused after a controller crash without another model invocation. Missing or
conflicting receipts cannot be guessed. Expired worker ownership is recorded as
UNKNOWN and blocks shared spending. Lease-lost workers cannot append new events
or settle results. Receipts with completed native output still require independent
verification; agent text claiming PASS is never sufficient.

There is deliberately no blind “clear unknown and retry” endpoint. This pilot
cannot query provider-side uncertain-turn history to reconcile an unknown receipt.
Preserve that mission for investigation; do not hide uncertainty by resetting its
budget. Operator/provider reconciliation is a remaining work item.

Bounded threads each use the existing supervisor/runtime and shared store.
Independent task concurrency is tested; dependencies require current PASS evidence.
Artifact or evaluator drift marks current downstream projections stale without
rewriting historical verdicts. The default is two workers. Limits are reservations
for native **invocations**, not token counts or dollars: planning, execution and
retry invocations all count. Unknown work does not release its reservation.
No hard dollar-spend guarantee is made, and reported session totals are not
incremental provider invoices. Verification CPU/storage are not included in that
counter.

## Console

The local console reuses the Arena theme, renders the task DAG, retains attempt
and retry lineage, and exposes evidence and native events in an inspector.
It polls persisted state/events once per second and resumes event cursors after
successful requests. It does not synthesize “progress” from LLM prose.

Pause/resume governs **new dispatch only**. Interrupt/steer are persisted commands;
202 accepted, native acknowledgment and terminal execution are separate states.
Existing active tools may continue after an interrupt request until acknowledged.
A task graph and attempt lineage are implemented; a fully interactive native
sub-agent tree and a merged global research-claim view are not.

The HTTP server binds only to 127.0.0.1. Its random bearer token is passed in a
URL fragment and removed from the address bar; dynamic endpoints require auth.
Host and Origin checks, CSP, text-only DOM insertion, bounded request bodies and
no-store headers are included. Keep the printed token URL private. No unauthenticated
remote/public-server mode is provided. There are no endpoints for arbitrary shell
commands, modifying evaluators, promoting policies, merging or deploying code.

## Boundary of this increment

This is trusted-local orchestration, not a hostile-code sandbox. Directory copies,
SQLite leases, environment filtering, provider permissions and code hashes do not
isolate same-user filesystem access, credentials or malicious subprocesses.
Use external OS/container/user boundaries before running untrusted agents against
valuable data or execution credentials. The HTTP token is not a substitute for
process isolation. Symlinks and oversized candidate trees are rejected; the pilot
snapshot limit is 4,000 files / 20 MB excluding selected cache directories.

The implementation is currently POSIX-only. No live trading, release, production
canary, merge, self-update activation or policy promotion is performed. Existing
Research OS policy/SOP learning stays unchanged and opt-in. Dynamic graph evolution,
fresh matched native-agent benchmarks and demonstrable cross-task RSI remain open
implementation stages, not successful results asserted by this delivery.

## v0.9.0 installation integration

The versioned source installer exposes the same `workers` entry point as pip
installation. Mission execution registers its control directory and holds a
shared installation lock until its bounded run returns. Update and rollback
cannot take their exclusive activation lock in that interval. Registration uses
a separate lock so independent mission controllers can coexist. Unknown native
receipts and unreadable registered autonomy state block later upgrades as well.
The inspection-only `serve` command does not hold an execution lock.

The 390px Chromium regression checks horizontal containment of every console
section. Large graphs scroll within their section instead of widening the page.
