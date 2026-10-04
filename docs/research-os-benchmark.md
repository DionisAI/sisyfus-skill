# Research OS effectiveness pilot

This adds a **real-provider-capable, resource-matched comparison harness**, not a
claim that Sisyfus beats GPT-6-Astra. A network-free smoke worker is deliberately
weak and is always identified as a fixture. No live provider was used to validate
this implementation.

## What is compared

| Arm | Proposal context | Candidate selection |
| --- | --- | --- |
| `direct_refine` | Task + accumulated development feedback | Model's proposed order |
| `independent_search` | Same task, independent calls without previous feedback | Model's proposed order |
| `research_os` | Same feedback as direct refinement | Actual `ResearchOS.run` and frozen scheduling policy |

All arms receive the same model, reasoning effort, JSON schema, maximum calls,
generated-output tokens (including reasoning), development evaluations, deadline,
and operator-priced dollar reservation limit. All select the highest development
score, with an earlier-candidate tie break. Independent search is a real baseline,
not a single unassisted model call. Arm order is seeded and shuffled within each
task/repeat. A seed controls ordering/bootstrap only; it does not make the provider
or research outcomes deterministic.

This is a **bounded artifact-proposal / trusted-evaluator** benchmark. The model
returns JSON data. It cannot run arbitrary Python, browse, open files or call
unregistered tools. It is NOT a comparison against the full Codex/Claude coding
agent or the user's earlier unrestricted GPT-6-Astra workflow. A result here must
not be generalized to that workflow. Global research-portfolio scheduling and
learned SOP-graph construction are also outside this pilot.

The baseline uses the same evidence engine as a measurement service, but bypasses
the new Research OS selection controller. This holds measurement machinery
constant and isolates scheduling/context differences. Each research workspace
retains the existing engine's independent verdicts and hash-chained evidence.

## Offline smoke test

```bash
python -m pip install -e .
SISYFUS_AUTO_SERVE=0 sisyfus os benchmark-demo --output /tmp/os-benchmark-new
sisyfus os benchmark-status --output /tmp/os-benchmark-new/run
```

Use a new empty directory. The example has three tiny expression tasks and a
scripted provider that always proposes `x`. On the development inputs 0 and 1,
that wrong candidate appears to solve all tasks. The final negative input exposes
all nine false development positives (three tasks times three arms). All arms tie
at zero final passes. This tests frozen selection and negative-result handling,
not useful research performance. Its token counts and dollar estimates are
**synthetic test values**, not actual usage or savings.

The expression evaluator has a bounded AST, no `eval`/`exec`, and no candidate
imports. It rejects attribute access, arbitrary calls and unbounded expressions.

## Real provider execution

The optional OpenAI adapter uses the official Responses API and input-token
counter. No network calls occur on import. The adapter sets `max_retries=0`,
`store=False`, explicit model/effort and a per-request output-token maximum.
No tools, implicit model fallback, or credentials in prompts are supported.

```bash
python -m pip install -e '.[benchmark]'
# Set OPENAI_API_KEY outside source control.
# Review your suite, evaluator, allowed model IDs and CURRENT rate card first.
sisyfus os benchmark \
  --suite /path/to/reviewed/suite.json \
  --output /tmp/os-provider-pilot-new \
  --model "$BENCHMARK_MODEL" \
  --rates /path/to/reviewed/rates.json \
  --allow-paid-provider --allow-local-evaluator \
  --max-calls 3 --max-evaluations 6 \
  --max-output-tokens 12000 --max-output-per-call 4000 \
  --max-seconds 300 --max-usd 1 --max-total-usd 5
```

The model ID is explicit. Returned model IDs must match the requested ID unless
operator-reviewed `--actual-model` values are provided. Multiple actual models
in a completed suite invalidate a matched-model comparison; the runner never
silently substitutes a cheaper or stronger model. Unsupported model/effort/SDK
combinations fail rather than falling back.

`rates.json` contains exactly `input_per_million` and `output_per_million`, both
positive numeric USD rates. There is no baked-in current price. Input is charged
at the supplied uncached rate even when cached tokens are reported, making the
estimate conservative. Output usage already includes reasoning and is not
counted twice. These amounts are **rate-card estimates, not provider invoices**.
Tool execution dollars and controller-training dollars are unknown/null, not
silently zero. Include them in a subsequent business-cost comparison.

`--max-usd` is PER ARM, TASK and REPEAT. The runner rejects a nominal suite
allowance above `--max-total-usd` before any generation. For example, a suite of
three tasks, three arms and one repeat at $1 each requires a nominal $9 allowance;
the default $5 ceiling refuses it. Explicitly lower the per-arm allowance or raise
the reviewed total. Spending caps depend on the supplied rates, token-counter
accuracy and provider semantics; they are not a billing-provider hard limit.

Before generation, count input tokens and reserve counted input plus maximum
output cost. Settlement uses actual usage. Incomplete and malformed outputs still
consume budget. More usage than reserved invalidates the comparison and stops the
suite. An uncertain transport failure retains its reservation and stops the whole
suite without retries. Input-count failures stop before generation.

The deadline is checked at scheduling boundaries and passed as a bounded request
or tool timeout. It is not an OS-wide hard termination guarantee. Observed deadline
overruns invalidate the matched-envelope flag. Provider retries are disabled.

## Bring real tasks

The suite schema is:

```json
{
  "schema": "sisyfus.benchmark_suite.v1",
  "tasks": [
    {
      "id": "unique-task-id",
      "family": "task-family-for-clustered-analysis",
      "prompt": "Public requirements and artifact JSON format. No hidden answers.",
      "evaluator": "evaluate.py",
      "cases": "cases.json",
      "threshold": 1.0
    }
  ]
}
```

`evaluate.py` is an operator-reviewed, self-contained Python evaluator. It accepts:

```text
--candidate <artifact.json>
--cases <cases.json>
--split development|holdout
--output <measurement.json>
```

It writes the measurement JSON and prints the same object to stdout:

```json
{"metrics": {"score": 0.8}, "summary": "Measured against frozen reference"}
```

Scores must be finite in [0,1]. The existing engine derives PASS/FAIL using the
preregistered threshold and actual process exit status. The model cannot choose
a command, evaluator, cases path, approval, or verifier verdict. New candidate
DATA is executable only by the already reviewed evaluator. An evaluator that
executes arbitrary candidate code defeats this design: put such work behind a
separate sandbox before enabling it.

Evaluator and case bytes are hashed at registration, copied into independent arm
workspaces, checked before approval, and checked around actual execution. Explicit
source paths in the suite are trusted operator inputs. Python/dependency/environment
isolation is not guaranteed by these hashes. Additional imported evaluator modules
are not automatically snapshotted; use a hermetic external evaluator for those.

Only `prompt`, the common protocol and permitted development feedback reach the
provider. Private paths, hidden test inputs, thresholds, raw contracts and final
verdicts do not. The process adapter grants no model filesystem or shell tools.
Same-user access to files remains outside this boundary: do not use the benchmark
filesystem as a security sandbox.

## Evidence and interruption

The output contains:

- `manifest.json`: frozen suite/asset/code hashes, policy, provider configuration,
  limits, rate card, ordering, platform and interpreter.
- `audit.jsonl`: fsynced hash-chained intents, receipts, errors and selection events.
- Per-arm research workspaces: artifacts, independent development verdicts, frozen
  selection and existing engine evidence; the OS arm also exports replay history.
- Independent final-evaluation workspaces and `summary.json`.

ALL candidate selections are frozen before ANY final test is run. Final results
are never fed into subsequent generation, scheduling, replay export or selection.
Repeated external adaptation to the same final set can still contaminate it;
operators must provide fresh, separately held test families for future studies.

Use `benchmark-status` to verify the audit/summary and list unresolved provider
intentions. It is read-only. Interrupted output directories are never auto-resumed
or reused: first reconcile actual provider outcomes/billing. A process crash after
intent but before receipt cannot be interpreted as a free failed attempt.

Registration hashes and a file hash chain detect accidental changes; they are not
authentication or protection against a malicious same-user process rewriting the
entire ledger. Keep provider credentials and evaluator administration out of the
worker's permissions.

## Reading results

Success counts use the entire planned task denominator, including malformed
responses and budget exhaustion. Partial or model-mismatched suites are flagged
as non-comparable, not silently reduced to their successful rows.

`development_false_positives` counts development PASS followed by final FAIL. It
does not mean the OS released those artifacts; final evaluation rejected them.
Errors in the final evaluator are not evidence that the candidate is scientifically
wrong and invalidate a matched comparison.

Paired pass differences average within task families, then weight families equally.
The descriptive bootstrap resamples families, not attempts or correlated repeats.
There is no interval for fewer than two families. A tiny or degenerate interval,
especially from the scripted fixture, is not a generalization guarantee. Report
both raw task counts and family-weighted comparisons.

`beats_gpt6_astra` remains null: this harness does not automatically issue broad
superiority claims or activate a policy. A full effectiveness study still requires
real relevant tasks, a strong full-agent baseline, adequate independent families,
frozen evaluators, wall/dollar accounting and controller training costs. The
existing staged-policy promotion remains a separate explicit operator action.

## Provider references

- [Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create/)
- [Reasoning and output-token accounting](https://developers.openai.com/api/docs/guides/reasoning)
- [Official Python SDK](https://github.com/openai/openai-python)
