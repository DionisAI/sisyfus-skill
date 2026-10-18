# Sisyfus Tech Lead development contract

- Work on dedicated `codex/techlead-*` development branches; use `git switch`
  before substantial new work. Preserve the installed
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

- The default local operator UI is a Chinese light conversational interface.
  See `.impeccable.md` for design context. `/console` retains the developer view.
  Conversation drafts and native chat receipts are not task truth: execution
  still requires an operator-confirmed objective and existing immutable checks.
  Opening pages, attaching context and sending chat messages never dispatch Sol.

- Bound planning drafts stay frozen. Runtime communication uses the separate
  controller-owned mission inbox: `/btw` projects persisted controller facts;
  supplementary messages are data, not changed acceptance or execution permission.
  Bind context atomically with a new eligible native reservation. Show receipt,
  binding and native prompt acceptance separately; cached or unknown calls are
  never rebound or resent. Independent reviews and RSI evaluation children remain
  outside this supplementary-context channel.

- Explicit user chat directives may grant a controller-owned directory preparation
  capability: exclusive creation or explicit binding, no shell commands, overwrite,
  acceptance approval or worker dispatch. Prose supplies only a name inside the
  granted parent. Persist the request before mkdir and fence interrupted outcomes.
  Native chat remains read-only; report controller preparation back into its context.

- Explicit user chat directives may configure RSI before mission binding. The
  controller inspects only catalog metadata, pins its manifest, and excludes
  evaluation paths/content from native planning. Chat configuration never
  dispatches workers or establishes improvement. Separate confirmed Start and
  canonical paired/holdout evidence still govern execution and promotion.

- The opt-in phone portal requires an operator-set password and a fixed task
  specification. Planning and Start remain separate confirmations; UNKNOWN
  mutations are fenced rather than retried. Graph, progress and engineering
  projection share one capture. Fixed HTML reports have a separate pinned
  version; source review and viewport checks do not establish public or physical
  device acceptance. Keep controller/NodeGateway endpoints private.
