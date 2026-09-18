# Shared-budget research portfolio (experimental)

The portfolio is the next layer above `ResearchOS`: it chooses one approved
experiment across multiple existing research workspaces, executes it through the
same SOP/kernel, and then updates the frontier from the real verifier receipts.
It does not add another claim database or allow models to approve themselves.

## What is now executable

```
Multiple pinned research workspaces
              |
Live cross-project claim dependencies + local frontier gates
              |
Shared cost/attempt budget + fixed/learned ranking + bounded fairness
              |
Durable portfolio intent / reservation
              |
Existing ResearchOS SOP -> actual command -> existing verifier
              |
Evidence-linked portfolio settlement -> updated global frontier
              |
Chronological replay export -> existing policy training/search lab
```

A high-ranking experiment cannot run while its upstream claims are unsupported,
contested, hidden, missing their evidence artifacts, or based on stale upstream
results. A producer's PASS can unlock a consumer in the next step of the same run.
A later contradictory result marks dependent results stale in the portfolio
view, transitively, without deleting or rewriting the historical research ledger.

The selection model is still the existing six-feature `SchedulingPolicy`, not a
new foundation model or an empirical estimate of commercial value. A fixed or
previously fitted policy can be registered. Global policy changes and budgets are
not self-authorized. Arbitrary SOP graph discovery is still not implemented.

## Register existing workspaces

First use ordinary Sisyfus commands to create research runs, propose experiments,
and explicitly approve their commands with `sisyfus os approve`. Then create a
portfolio specification, for example:

```json
{
  "schema": "sisyfus.portfolio.v1",
  "id": "research-portfolio",
  "family": "execution-research",
  "budget": {"max_attempts": 12, "max_cost_units": 20},
  "max_consecutive": 2,
  "projects": [
    {
      "id": "data-audit",
      "root": "/absolute/path/to/data-audit",
      "research_id": "latest",
      "weight": 1,
      "max_attempts": 4
    },
    {
      "id": "candidate-model",
      "root": "/absolute/path/to/candidate-model",
      "research_id": "latest",
      "weight": 2,
      "requires": [{"project": "data-audit", "claim": "data-valid"}]
    }
  ]
}
```

`data-valid` must be an actual claim in the source research run. Roots must be
absolute. `latest` is resolved ONCE at registration and replaced by the concrete
research ID. Creating a new run later does not silently redirect the portfolio.
Duplicate IDs, filesystem aliases to the same workspace, unknown claims, and
cross-project cycles are rejected before portfolio registration.

```bash
sisyfus os portfolio init --spec portfolio.json \
  --directory /path/to/new-portfolio --actor operator-name

sisyfus os portfolio status --directory /path/to/new-portfolio

sisyfus os portfolio run --directory /path/to/new-portfolio \
  --allow-local-commands --max-steps 10 --max-seconds 300
```

The registry directory must not already exist. Status does not execute work or
settle reservations. Runs are bounded synchronous commands, not a daemon.
Restarting the command retains global spending, operation IDs, fairness history
and unresolved work. `max_seconds` is a per-invocation scheduling deadline, not a
lifetime budget or an OS hard-kill guarantee for an already executing command.

Shared cost units are declared experiment evaluation units, NOT dollars. Local
budgets remain enforced as well. A separate per-project attempt cap can prevent
one project from consuming the entire portfolio. The max-consecutive rule forces
a different eligible project after the configured streak when an affordable
alternative exists; it does not guarantee wall-clock fairness or optimal value.

In value mode, the score is:

```
project_weight * (policy_prediction + judgment_weight * (actionable - duplicate))
    - policy_cost_weight * declared_experiment_cost
```

In FIFO mode, eligible composite `project::experiment` IDs order the queue. This
is deterministic identifier order, not a claim about arrival-time scheduling.
Scores are ranking heuristics, not calibrated research success probabilities.

## Dependencies and stale results

Each dispatch binds the consumer to concrete upstream claim fingerprints,
verifier-event hashes and evidence IDs. Dependencies are re-read from the real
member histories on each step. Positive support must be public, match the current
verification contract, and retain its copied evidence artifacts intact.

Dependencies of dependencies are included. A middle project's old PASS cannot
retroactively satisfy a newly declared upstream requirement: when upstream
requirements exist, its support must have been obtained by a portfolio dispatch
bound to those same proofs. Already verified root claims without external
prerequisites can be reused at registration.

A later change to a relevant claim's proof fingerprint conservatively marks the
consumer's old outcome `stale_dependencies=true`. This can include additional
support, not just a contradiction. Reevaluate the affected result explicitly;
do not silently reclassify history or equate an old PASS with current validity.
Unrelated changes to another claim do not change the dependency fingerprint.

Portfolio dependency gates control execution eligibility and provenance. They do
not copy an upstream dataset into a consumer, prove the scientific relevance of
an edge, or manufacture a logically correct conclusion from successful tests.
The operator must define meaningful contracts and data handoffs.

## Crash recovery without duplicate execution

A portfolio reservation is fsynced before local dispatch. A local decision binds
the resulting attempt to that exact intent. Only an actual `VERDICT_ISSUED` event
with matching attempt/action/configuration/cost can settle it.

```bash
sisyfus os portfolio reconcile --directory /path/to/portfolio
```

Reconciliation only joins already committed verifier events. It never submits a
command, invents a failure, or labels unfinished work. If the member completed but
the coordinator crashed before recording settlement, this recovers the receipt
without repeating execution. Repeated reconciliation is idempotent.

If a crash occurred before ANY member dispatch decision, an explicit operator
can release the unstarted reservation:

```bash
sisyfus os portfolio cancel-unstarted --directory /path/to/portfolio \
  --operation op-000000 --actor operator-name
```

This refuses once a member decision or reservation exists after the source
anchor. At that point, independent tool reconciliation is needed. A legacy
`recover_stranded()` synthetic error is intentionally NOT treated as a reconciled
external outcome and does not free the portfolio budget or permit a blind retry.
Unknown work blocks the entire shared-budget run, including other projects.

## New approvals without resetting the shared budget

When experiments or measurement inputs change, review them and use the existing
member approval command first. The portfolio detects configuration drift and
stops rather than accepting the new command automatically. Then explicitly bind
the revised approved configuration:

```bash
sisyfus os approve --root /path/to/member --allow-local-commands
sisyfus os portfolio refresh --directory /path/to/portfolio \
  --project member-id --actor operator-name
```

This retains spending, reservations, membership, task identity and dependencies.
It cannot reset the budget or authorize a new task. Membership, dependency graph,
global policy and shared budget remain fixed for this portfolio version.

## Optional judgment and learning interfaces

The Python `Portfolio.run()` interface accepts the existing `CallableJudge` or
`JevJudge`. Nonzero global judgment weight requires both a supplied adapter and
`allow_judgments=True`. Malformed judgments use the existing neutral fallback.
Judges receive only public candidate fields and composite IDs, never commands,
raw source evidence or hidden evaluation content. Zero weight makes no judgment
call; the selected member uses a neutral judge to avoid a second paid ranking.

The CLI deliberately does not enable paid judging. Provider costs, retry/timeouts
and calibration are not covered by the abstract experiment budget. A deployment
must configure them separately; costs remain unknown/null. No live Jev or LLM
call was used to test this change.

```bash
sisyfus os portfolio export --directory /path/to/portfolio \
  --output portfolio-history.json
```

Export joins outcomes to source verifier events. Unfinished/cancelled intents have
no training labels. Current staleness is recorded separately; historical PASS
still means PASS under the then-current contract, not present validity. The export
uses conservative chronological prerequisites and cannot infer outcomes for a
new branch, altered code, or another scheduling order. It is accepted by the
existing replay/policy-lab interfaces, with no automatic policy activation.

Exports include underlying research IDs and task families. PolicyLab rejects
cross-split reuse even when the same member episodes are wrapped in portfolios
with different IDs. Operator-supplied archives still require independent data
provenance and protection from repeated holdout adaptation.

## Concurrency and security limits

The portfolio acquires its own lock and every member's existing coordinator lock
in canonical path order, nonblockingly. This first implementation executes one
experiment at a time. Another cooperating controller cannot mutate dependencies
mid-dispatch. Legacy direct-engine writers do not honor these locks; do not run
them concurrently. Newly detected non-portfolio attempts stop the coordinator
as unmanaged work rather than hiding them in the accounting.

Shared budgeting applies to dispatches through this registry, not unrelated
processes, external providers or another registry's intentionally new budget.
Hash chains and named approvals are not authentication. A same-user shell can
modify code, files or credentials. Use separate users/containers, an immutable
verifier and restricted tools before untrusted or production deployment.

No trading, deployment, merge, automatic task creation, or unrestricted generated
command execution is added. Existing production entrypoints remain unchanged.

## Executable coordination demo

```bash
SISYFUS_AUTO_SERVE=0 sisyfus os portfolio demo \
  --directory /tmp/sisyfus-portfolio-demo-new
sisyfus os portfolio status \
  --directory /tmp/sisyfus-portfolio-demo-new/registry
```

The demo uses three existing bounded arithmetic workspaces with artificial
cross-project dependencies. It dispatches `reference`, then unlocks `dependent`,
then executes `independent`, including a controller restart. There are three real
subprocess/verifier evaluations and one shared three-unit budget. This is an
integration fixture, not a research benchmark or evidence of an LLM improvement.
The separate provider comparison harness remains the effectiveness test.
