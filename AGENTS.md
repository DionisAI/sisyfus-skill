# Sisyfus Tech Lead development contract

- Work only on the `codex/techlead-rsi` development branch. Preserve the installed
  release, the older development checkout, and unrelated user work.
- Never permanently delete files or directories. All removals use
  `/usr/bin/trash <absolute-path>` without `--`. No destructive Git commands.
- The controller owns state, invocation reservations, immutable acceptance,
  evidence, stop/pause, graph revisions, and integration. Models propose; they
  do not replace deterministic truth, approve arbitrary commands, or edit tests
  after observing outcomes.
- Lead and independent reviewer use explicit `claude-opus-5-5`; implementers
  use explicit `gpt-6.1-sol`. Requested and runtime-attested models are separate.
- Default whole-mission invocation, iteration, token, and cash limits are null
  (unlimited). Per-invocation timeout/output limits, finite parallelism, unknown
  receipt fencing, and operator stop controls remain active.
- A task review is a separate read-only native session. Acceptance requires both
  a deterministic check and independent review; integration is a separate gate.
- Trial-and-error must preserve failed attempts and diagnoses. A revised plan
  keeps completed evidence, freezes existing acceptance, detects cycles and
  write conflicts, and does not blindly resend an unknown native invocation.
- RSI means recursive, evidence-backed improvement of orchestration strategy,
  task specification, and versioned Lead procedures. Promotion requires frozen
  baseline/candidate evaluation, independent holdout evidence and no gate
  weakening; report measured changes, not unproven model capability gains.
- Reuse the existing autonomy database, hash-chained events, drivers and verifier
  where their contracts fit. Add only state needed for the changed lifecycle.
- Errors must be explicit and traceable without leaking credentials. Keep real
  native runs separate from protocol fixtures and report pending checks honestly.
- Use retained test artifacts. New tests must not depend on permanent deletion.
