# Research TaskSpec v2

A TaskSpec turns an open-ended topic into a bounded research environment.

## Required fields

```json
{
  "id": "stable-task-id",
  "topic": "The final research objective",
  "claims": [
    {
      "id": "claim-id",
      "statement": "A falsifiable proposition",
      "label": "短别名",
      "required": true,
      "critical": false,
      "weight": 1.0,
      "depends_on": []
    }
  ],
  "verification_contracts": [],
  "budget": {
    "max_attempts": 20,
    "max_cost_units": 20,
    "max_wall_minutes": 120
  }
}
```

Budgets are opt-in guardrails: any limit you omit is unlimited — no default ceiling ends a
run the author never chose. Set explicit budgets whenever a run executes unattended
(cron wakes, `wake --execute`, paid APIs); an unbudgeted unattended run has no mechanical
stop. `BUDGET_EXHAUSTED` remains a hard terminal state once a declared limit is hit.

If `goal_graph` is omitted, Sisyfus creates an AND root over all required claims. Supply an explicit AND/OR graph when the goal has alternative sufficient paths.

## Design rules

- Claims must be propositions, not activities. “Search the literature” is an action; “three independent primary sources support X” is a claim.
- Always give each claim a `label`: a 2-6 character display alias (e.g. "点差经济", "fee census"). The Arena map shows only labels; the full statement lives in the unit card and quest panel. Without a label the UI falls back to the first tag, then the truncated id.
- Provide a top-level `i18n` block with both zh and en translations of the topic and every claim's label/statement — the Arena has a language toggle and shows the active language's text, falling back to the authored original. Claims also accept an optional one-line `conclusion` per language: a plain-language takeaway shown in the quest panel, unit card, and Report tab in place of the (usually longer) statement. For a run whose spec is already locked, write a presentation sidecar `<run>/i18n.json` with the same shape (plus optional `experiments: {id: {title}}` and `lessons: {id: {recommendation, observation}}`); it is display-only, never part of the event chain:

```json
"i18n": {"en": {"topic": "…", "claims": {"claim-id": {"label": "…", "statement": "…", "conclusion": "…"}}}}
```

- At finalize time (or when writing the post-hoc sidecar), author a per-language `report` block alongside `topic`: `{"headline": "…", "do": ["…"], "dont": ["…"]}` — the answer-first summary the Report tab leads with (what the run proved, how to act on it, and what to avoid). Ground every line in recorded evidence; without a block the tab falls back to banked lessons and FAIL records.
- Split a broad objective into the smallest claims that can be independently verified.
- Put causal prerequisites in `depends_on`. Refuting a prerequisite invalidates dependent claims.
- Use AND when every child is necessary. Use OR only for genuinely alternative sufficient paths.
- `hard_constraints` are human-readable annotations. A constraint is machine-enforced only when represented as a required Claim or a Verification Contract guardrail. `research new` warns about every unenforced constraint.
- `action_space` names allowed action families. Every Experiment declares `action_family`; admission rejects families outside this set.
- Required unresolved claims without contracts appear in `verifier_gaps` and block terminal progress by default.
- Budgets are hard ceilings, not planning targets.

## stop_policy flags

- `stop_on_goal_pass` (default true) — the run becomes SOLVED as soon as the Goal Graph root passes.
- `block_without_verifier` (default true) — verifier gaps block terminal progress.
- `allow_manual_verdict` (default false) — permit manual-kind contracts.
- `max_invalid_attempts_per_experiment` (default 2) / `max_error_attempts_per_experiment` (default 3).
- `require_uncontested_solve` (default false; recommended true) — a required claim that is SUPPORTED on the current branch while FAIL evidence exists on any branch is `contested`; while unresolved, the run cannot become SOLVED. Resolve by settling a later PASS experiment that carries a `discriminating_note`.
- `allow_provisional_prereq` (default false) — admit experiments whose prerequisite claims have at least one provisional PASS (repetition gate still pending). Dependent results are still invalidated automatically if the prerequisite is later refuted. Use this instead of weakening declared `depends_on` edges to keep throughput.
