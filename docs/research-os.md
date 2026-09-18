# Closed-loop Research OS (experimental)

This is an **integrated, opt-in research controller**, not a replacement Sisyfus
runtime, a released version bump, or evidence that orchestration beats a strong
base model. `research_v2.ResearchEngine` remains the sole owner of experiments,
claims, artifacts, verdicts, budgets, and the hash-chained research history.

## The implemented loop

```text
Existing claims / dependencies / experiments / evidence
                         |
              ready frontier projection
                         |
       fixed or learned ranker + optional Jev judgments
                         |
      versioned SOP: authorization / dependencies / budget
                         |
       approved local measurement -> existing verifier
                         |
        recorded decision + reservation + actual verdict
                         |
     train -> search replay -> holdout replay -> candidate
                         |
     fresh matched execution -> named operator promotion
```

A separate proposal bridge calls Sisyfus's existing bounded `CommandPlanner`.
It may propose follow-up experiments from the existing planner context. It
cannot execute its returned capability, create a verification contract, claim
completion, or approve a new command. New commands require operator review.
The existing lessons, claim graph and Arena remain in use; there is no second
truth database or replacement dashboard.

## Quick start: executable offline example

```bash
python -m pip install -e .
SISYFUS_AUTO_SERVE=0 sisyfus os demo --workspace /tmp/sisyfus-os-demo
python -m pytest -q
```

Use an empty demo path. The demo executes twelve real Python subprocess
measurements across absolute-value, square, nonnegative-part, and cube tasks.
Candidates are data in a bounded expression language, **not arbitrary Python
from an LLM**. The fixed evaluator compares against reference functions; both
positive and negative results enter the normal research evidence ledger.

The demo writes `summary.json`, four `*-history.json` archives, and
`policy-candidate.json`. Training uses two task families, search one, and final
holdout one. Search/holdout compare FIFO, fixed-value scheduling and a learned
logistic ranker under equal abstract evaluation budgets. The current example
shows **no holdout gain**: all three reach one PASS at cost two. Nothing is
automatically promoted. This is a runnable plumbing/learning example, not a
credible sample size for a general superiority claim.

## Use an existing research workspace

First compile a TaskSpec and propose experiments through the existing commands:

```bash
sisyfus research new task.json --root /path/to/project
sisyfus research propose latest experiment.json --root /path/to/project
sisyfus os frontier --root /path/to/project
```

Review each action, its evaluator and explicit `action.code_paths`. Then:

```bash
sisyfus os approve --root /path/to/project --allow-local-commands
sisyfus os run --root /path/to/project --allow-local-commands --max-steps 10
sisyfus os export --root /path/to/project --output episode.json
```

Approval pins exact commands, contracts and **explicit** input/measurement file
hashes. Generated output files are not mistaken for approved source files.
The guarded execution path checks measurement code before and after execution
and overwrites any stdout-supplied execution status with the actual process
status. Nonzero exits cannot be hidden behind a JSON `exit_code: 0`.

The controller checks current dependencies, not merely the state at original
admission. Hidden evaluations, missing contracts, manual verifiers, unsupported
or contested dependencies, missing cited evidence, exhausted budgets, and
unresolved attempts are excluded. This does not infer the semantic validity of
all cited evidence: the underlying evidence/claim model and operator contract
remain authoritative.

An unknown execution result leaves its reservation intact and blocks further
execution. Inspect the normal attempt manifest and reconcile the actual tool
result before continuing. **Do not blindly invoke the legacy recover command
as a substitute for reconciliation.** The controller does not assume an
unacknowledged action did not execute and does not label it as a failed idea.
Reports separate committed abstract cost from reserved in-flight cost.

### Generate follow-up proposals with an existing worker

```bash
sisyfus os propose --root /path/to/project \
  --planner-command 'python /path/to/my_proposal_worker.py' \
  --allow-local-planner --timeout-seconds 120 --limit 4
```

The adapter reuses `sisyfus.autonomy.adapters.CommandPlanner`: no shell for
launching the worker, environment allowlisting, bounded response files, process
group termination and an explicit timeout. The worker reads
`SISYFUS_AUTONOMY_CONTEXT_PATH` and writes `SISYFUS_AUTONOMY_RESPONSE_PATH`:

```json
{
  "kind": "EXECUTE",
  "reason": "Propose a falsifying check for the observed discrepancy",
  "capability": "research.propose",
  "arguments": {"experiments": ["replace with a valid Experiment object"]}
}
```

`experiments` must contain actual existing-schema Experiment objects, not
strings. The bridge pre-validates the entire batch and then uses normal engine
admission. The returned capability is a proposal envelope, never executed.
A process worker was tested; **no real LLM provider was invoked**. Use an
already configured worker for provider access; secrets are not automatically
forwarded. The new execution loop does not automatically launch a proposer
when the frontier empties: `propose -> review/approve -> run` is explicit in
this first release candidate.

### Optional Jev / TypeSafe judgment adapter

```bash
python -m pip install -e '.[jev]'
# Configure TYPESAFE_API_KEY outside source control.
sisyfus os approve --root /path/to/project --allow-local-commands \
  --judgment-weight 0.2
sisyfus os run --root /path/to/project --allow-local-commands \
  --max-steps 5 --judge jev
```

The adapter follows the [official Python SDK](https://docs.typesafe.ai/sdk/python)
and [judgment primitives](https://docs.typesafe.ai/primitives). It asks whether
a proposal is specific/falsifiable and whether it duplicates another candidate.
Only candidate titles and rationales are sent. Do not place sensitive content
in those fields without permission to send it to the provider.

Jev returns advisory features, never a truth verdict or execution permission.
IDs and probabilities are validated; unavailable/invalid judges yield a neutral
fallback and a redacted error type in the decision record. Default judgment
weight is zero (disabled); the CLI refuses paid calls with zero weight.
`CallableJudge` exposes the same typed seam for an existing LLM.

The SDK is lazy and optional; offline installation and tests need no API key.
The SDK-shaped client was mocked in tests, **not live-validated**. In a deployment,
construct `JevJudge` with a configured SDK client and set that client's timeout,
retry and spend controls. Provider dollar costs are currently **unknown/null**,
not zero; max steps and abstract tool costs are not a dollar-spend guarantee.

## Learning and replay

```bash
sisyfus os optimize \
  --train train-a.json train-b.json \
  --search search.json --holdout holdout.json \
  --budget 20 --output candidate.json
sisyfus os stage --root /path/to/project --report candidate.json
```

The small standard-library logistic model learns six pre-execution priority
features from **executed verifier-labeled attempts**. Labels are PASS under the
locked contract, not scientific usefulness, commercial value or causal treatment
effects. Negative research remains a valid result; it simply is not a positive
label for this narrow model. Unchosen and unresolved actions have no labels.

Dataset IDs and task families must be disjoint across train/search/holdout.
A fixed policy, FIFO and a finite grid of learned cost weights are compared.
Only search selects the candidate. Holdout is not used in training or selection
within an optimization call; operators must also prevent repeated external
adaptation to the same holdout. The code does not certify split labels supplied
by the operator or prevent filesystem access by a hostile Python policy.

This implements the **support-limited replay principle** from
[Dream-RSI](https://github.com/zhengkid/Dream-RSI), not its undisclosed/full
implementation, arbitrary policy-code evolution, new model weights for Jev,
or a simulation of new research outcomes.

Replay returns candidate features, not unreached outcomes. Unknown, repeated,
unaffordable, or dependency-blocked actions raise `UnsupportedAction`. Only
recorded actions have outcomes. Histories with no outcomes are not silently
expanded. `prefix` mode conservatively preserves earlier execution order;
`independent` mode requires an explicit operator declaration and rejects known
evidence/lesson/dependency-linked experiments. Independence beyond those checks
is a domain assumption, not something the scheduler proves.

Replay selection is conditional on the recorded support. It cannot estimate
an unexecuted branch, new worker output, a changed SOP or new Jev judgments.
Live-judge policies are therefore not scored counterfactually by this replay.
Fresh evaluation is mandatory before promotion.

### Fresh validation and promotion

Create separate fresh workspaces with the same candidate pool, measurement
code, claims, contracts, priorities, budgets and SOP. Assign equal nonempty
`metadata.evaluation_pair_id` values within each pair and a held-out
`metadata.task_family`. Approve the frozen fixed/candidate policy JSON in the
respective workspaces and execute with equal max-step budgets. A policy JSON
is the `candidate` object within the replay report, not the whole report.

```bash
sisyfus os validate-policy --root /path/to/project --report candidate.json \
  --baseline-roots /trials/b1 /trials/b2 \
  --challenger-roots /trials/c1 /trials/c2
sisyfus os promote --root /path/to/project --report candidate.json \
  --baseline-roots /trials/b1 /trials/b2 \
  --challenger-roots /trials/c1 /trials/c2 --approver operator-name
```

Promotion reads actual hash-checked engine histories, not a supplied
`online_passed` flag. It requires at least two fresh matched pairs, no unresolved
attempts, no mixed policy/configuration, no per-pair regression in PASS count or
abstract cost, and at least one strict improvement. The candidate must be staged
first. Promotion preserves command approvals and mandatory SOP gates. It is
still only a conservative **small pilot gate**, not statistical evidence of
superiority; a production deployment should add its own larger preregistered
acceptance test. Named approval is an audit entry, **not authentication**.

## Security and measurement boundaries

The controller uses a POSIX nonblocking coordinator lock. Do not concurrently
write through legacy direct engine APIs; they do not participate in that lock.
Do not let untrusted workers share a writable evaluator, ledger or credentials.
Hash checks and Python APIs **are not OS isolation**. The original command engine
uses local shell execution. Operate only trusted approved commands here, or put
untrusted work behind a separate process/user/container capability boundary.

Only explicitly listed code files are approval-pinned. This is not a complete
hermetic environment/dependency snapshot, nor a protection against a same-user
attacker modifying files between checks. Evaluator correctness, hidden-data
access control and provider access require independent deployment controls.
Existing production and autonomy entrypoints are not silently redirected.
There are no exchange calls, deployments, automatic merges or background daemons.

The new `RESEARCH_OS_*` records are diagnostic/control metadata in the existing
hash chain. They cannot issue verdicts. Export joins an intent **before its
reservation** to the actual verifier event; late duplicate intents and forged
controller result fields cannot create new training labels.

## Implemented vs. not yet established

Implemented: ready frontier over the existing graph; learned experiment ranking;
optional narrow judge; executable versioned preflight; explicit follow-up
proposal bridge; real execution/evidence feedback; support-limited replay;
family-separated fitting/evaluation; staged and evidence-gated policy promotion;
CLI and adversarial/integration tests.

Not implemented here: arbitrary learned SOP graph edits, unrestricted recursive
self-modification, multi-workspace global portfolio allocation, automatic
approval of LLM-written commands, new graphics, a complete remote sandbox, or a
continuously running autonomous service. The SOP's mandatory checks remain fixed;
the learnable part is the selection policy inside the permitted frontier.

Not established: improved real GPT-6-Astra/Codex/Claude performance, live Jev
calibration, real dollar savings, or real commercial research gains. Evaluate
those with the same task pool, strong direct-agent and fixed-search baselines,
held-out tasks, equal budgets, independent evaluators, false-acceptance counts,
and both cold-start and steady-state costs before expanding this prototype.


## Resource-matched provider pilot

The optional `sisyfus os benchmark` command compares direct refinement,
independent search, and actual Research OS scheduling with the same provider and
resource envelope. It freezes all selections before final tests and preserves
unknown spending reservations. `benchmark-demo` is network-free; `benchmark-status`
checks evidence without resuming. See [benchmark protocol and boundaries](research-os-benchmark.md).
This is a bounded JSON-artifact pilot, not yet a full coding-agent effectiveness study.

## Cross-workspace portfolio continuation

`sisyfus os portfolio` now provides an opt-in shared-budget coordinator over
multiple pinned research workspaces. It reuses the existing kernel, adds explicit
cross-project claim dependencies, detects stale downstream results, and reconciles
source verifier receipts after crashes. See [portfolio operator guide](research-os-portfolio.md).
This supersedes the earlier "not implemented" statement about basic cross-workspace
allocation; arbitrary workflow discovery and demonstrated LLM gains remain unimplemented/unproven.
