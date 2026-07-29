# Verification Contract v2

A contract is locked before execution and classifies one target claim.

```json
{
  "id": "verify-example",
  "version": "1",
  "target_claim_id": "claim-example",
  "kind": "metric",
  "description": "What this contract actually measures",
  "preconditions": {
    "all": [{"path": "metrics.sample_valid", "op": "==", "value": true}]
  },
  "invalid_if": {
    "any": [{"path": "metrics.leakage", "op": "==", "value": true}]
  },
  "guardrails": {
    "all": [{"path": "metrics.cost", "op": "<=", "value": 0.2}]
  },
  "pass_if": {
    "all": [{"path": "metrics.score", "op": ">=", "value": 0.7}]
  },
  "fail_if": {
    "all": [{"path": "metrics.score", "op": "<", "value": 0.3}]
  },
  "required_artifacts": ["summary.json"],
  "repetition": {
    "min_passes": 2,
    "min_independent_contexts": 2
  }
}
```

## Evaluation order

1. Execution timeout/error/non-zero exit → `ERROR`.
2. Missing required artifact, failed precondition, or `invalid_if` match → `INVALID`.
3. Guardrail failure → `FAIL`.
4. Both pass and fail match → `INVALID` because the contract is contradictory.
5. Pass match → `PASS`.
6. Fail match → `FAIL`.
7. Otherwise → `INCONCLUSIVE`.

Supported operators: `==`, `!=`, `>`, `>=`, `<`, `<=`, `in`, `not_in`, `contains`, `not_contains`, `regex`, `exists`, `not_exists`, `truthy`, `falsy`, and `approx`.

A PASS verdict may remain provisional until repetition and independent-context gates are met. The raw verdict remains PASS; the claim effect is INCONCLUSIVE until promotion.

Set `visibility` to `host_only` for selection or hidden evaluation. Admission prevents a host-only contract or `hidden_eval` Experiment from being downgraded to normal visibility; planner context receives only a redacted event summary.

## Trust model — what the verifier does and does not do

The verifier is deterministic code, never a model: `classify_observation` is a pure
function over (locked contract, observation). No LLM is called anywhere in the engine —
the only model in the loop is the external Planner agent driving the CLI, and its prose
can never change research state.

The trust boundary is **observation production**, not verdict logic. Metrics are produced
by measurement code the (context-laden) Planner wrote, or supplied directly on external
settles; the verifier only evaluates preregistered rules against those numbers. There is
NO independent fresh-context re-measurement step. The controls around that boundary are:
thresholds preregistered and hash-locked before results exist (a changed contract settles
INVALID), `code_hashes` content-hashing the measurement code into every evidence record
(`code_changed_since_last_attempt` flags mid-experiment edits), `required_artifacts`,
repetition across independent contexts, and host-only hidden evaluation. `kind: manual`
contracts (gated by `allow_manual_verdict`, default off) trust the settling human entirely.

`sisyfus research reproduce <research_id> <evidence_id>` closes the loop on demand for
command evidence: it re-verifies the hashed measurement code, re-runs the recorded
command, diffs fresh metrics against the recorded ones, and re-classifies them under the
same locked contract — still zero models. The outcome (`code_intact`,
`deterministic_match`, `verdict_stable`, drift detail) is appended to the event chain as
`EVIDENCE_REPRODUCED` and surfaces on the evidence record; the original evidence is
immutable. Expect drift on live-world measurements (order books, prices): for those,
independence comes from repetition contexts, not reproduction. Exit code 0 means code
intact and verdict stable; 2 means drift or a flipped verdict.

## Cost semantics

`cost.units` is a **preregistered declaration**, not a measurement: admission checks it
against the remaining budget, `begin` reserves it, and settlement charges exactly the
declared amount — for every verdict, including `INVALID` and `ERROR`. Note the asymmetry:
an `ERROR` attempt does not consume `max_attempts` (it counts as `infra_error_attempts`
so retries stay possible) but it does consume `cost_units` — infrastructure failures
spend real resources. Planner-side token/API costs are not tracked by the engine.
