# Automatic human research reports — frozen first-slice contract

## Product / scope

After an opted-in research run reaches a terminal state through a confirmed
write command, produce a question-first Chinese report automatically. Tell the
operator what was investigated, what was learned, how the mechanism works,
measured results versus conditional arithmetic, remaining gaps and next useful
measurement. Controller counts do not substitute for a substantive answer.

This slice covers ResearchEngine / Observatory; the separate native TechLead
Mission graph is not bridged. No account access, trading, acceptance changes,
new market evidence, model-capability claims or RSI promotion. Preserve installed
release, unrelated dirty work and all original evidence. Never permanently delete.

Engine, reducer, verifier, renderer and HTTP stay deterministic/model-free.
Only the outer CLI calls `research_v2.reporting.maybe_compose` after execute,
settle, finalize, or wake --execute. Read commands, GET, refresh, replay and
pure engine calls do not dispatch a model. Malformed opted-in policy is exposed
before a CLI mutation. Legacy missing policy is disabled, not silently enabled.
Research stdout/legacy exit codes remain unchanged; report outcome on stderr.
Report error returns 5 only when the research command itself succeeded.

## Policy and API

Immutable TaskSpec `metadata.reader_reporting`:

```json
{"schema_version":"sisyfus.reader-policy.v1","enabled":true,
 "revision":"initial","question":"这个策略是否盈利，收益来自哪里？",
 "primary_claim_ids":["profit"],"artifact_paths":["artifacts/metrics.json"],
 "facts":{"cycles":{"path":"artifacts/metrics.json","pointer":"/cycles"}}}
```

Optional approved source labels/HTTPS links are presentation references, not new
retrieval. Freeze them with policy. Facts use strict JSON/RFC6901 pointer finite
numeric scalars (including exact numeric decimal strings); no booleans, duplicate
JSON keys, NaN/Infinity, unsafe paths or hidden evaluation inputs. Unknown primary
IDs fail. Optional per-call timeout is bounded; aggregate caps remain null by
default, shared Journal caps are always respected. Models are fixed explicit
`claude-opus-5-5`, not policy-selectable. Revision permits an explicit new candidate
after known failure; it never clears UNKNOWN or reuses unknown reservations.

`ReportCoordinator(engine, policy=None, driver=None, clock=time.time)` provides
`compose(approved=True)`, `status()`, and `control(action, key=None, note='',
approved=False)`. `ReportError` has an explicit code. `answer_state(snapshot,ids)`
is pure. CLI: `research report-compose [RID] --yes --policy JSON --root ROOT`;
`research report-control RID {status,pause,resume,stop,resolve-unknown} --root ROOT`.
Unknown resolution additionally needs `--key`, `--yes`, and a nonempty `--note`.

## Evidence / model boundary

Freeze task/event hashes, chain-verified snapshot basis, claim statuses/contested
flags, typed event sequence, policy, artifact size/sha/content and numeric facts.
Allowlist files confined under run/artifacts, reject symlinks/traversal/evaluation/
holdout paths. Fail on size limits rather than truncate. Report history is outside
artifacts and is not automatically evidence for future reports.

Inline the entire bounded frozen bundle in each prompt. No-tools native roles:
Request.mode=`no-tools`, tools empty, strict MCP empty, `--bare`, settings sources
empty, slash commands disabled. This is a minimal extension to existing drivers;
normal read-only/workspace-write modes remain unchanged. Codex explicitly rejects
no-tools. Test actual native init tool inventory, not just configured flags.

Model proposes title, answer, sections, process, takeaway/event text. Controller
owns exact question/language/basis/scope/claim statuses/event types/source links.
For v1-shaped proposals any asserted structural field must match frozen truth;
incorrect fields fail rather than being accepted as authority. Server validation
matches v1 browser shapes with stronger status/event/link binding.

Prose/table numerals require `{{fact:ID}}`; controller substitutes exact retained
values, detecting Unicode numeric-category literals as well as ordinary digits.
Unused declared facts are allowed and listed. This is numeric provenance, not
proof of semantic truth. Independent reviewer checks spelled-out quantities,
financial mechanism/denominator, assumption labels and unsupported extrapolation.

Author and reviewer are separate fresh sessions with requested AND attested
Opus identity, completed native receipts, non-null distinct session IDs. Reviewer
strict JSON pins bundle hash, finalized reader hash and basis; PASS has no blocking
findings. Rejected/missing/unattested/malformed review never publishes.

## Question state / publication / controls

Primary claims are conjunctive. ESTABLISHED requires all SUPPORTED/uncontested;
REFUTED requires an uncontested primary REFUTED; otherwise UNRESOLVED. Contested
refutation is unresolved. Terminal excludes CREATED/ACTIVE/PAUSED. Always show
execution state separately; SOLVED never implies profitability. Unresolved scope
contains `问题结论尚待证据`.

Use canonical ROOT/.sisyfus/autonomy.sqlite3 with existing Journal reservations,
receipts, shared spending/concurrency, and hash-chain. Never rebind an existing
worker spec or relax its caps/pause. Add only report-job, owner lease and report
control state; one active job per run. Unique bundle+policy+schema key; cached
terminal jobs never auto-repeat. Expired native lease becomes durable UNKNOWN
through Journal; no silent slot release or resend. Explicit report-key-only
unknown resolution preserves receipt bytes and uncertainty, with operator note
and hash-chained event; it does not turn unknown execution into success.

Pause gates report calls/publication, not research truth or other worker missions.
Resume preserves a REVIEWED candidate and publishes it without extra calls. Stop
latches the run's reports off, marks active jobs STOPPED and requests interrupt
through Journal; resume never revives STOPPED jobs. A publication claim taken
before stop may finish; claim/check/state transition serialized by DB transaction.

Write-once version/history directory retains bundle, prompts, native proof,
candidate, review, markdown, previous sidecar bytes and manifest. Under the run
event lock claim PUBLISHING, recheck sources/candidate and sidecar compare-and-swap,
atomically replace only zh.report.reader, fsync, then commit PUBLISHED. Render
directly with pure render_observatory, no research event/refresh append. On crash
after replacement, exact candidate-sidecar digest reconciles publication; mismatch
is fenced. Malformed sidecar fails explicitly. Preserve other locales/keys;
retained stale English reader is reported in status, not silently erased.

## Frozen acceptance

New `tests/test_reader_pipeline.py` and `tests/workers/test_report_no_tools.py`
freeze automatic terminal CLI report production, plain unresolved answer despite
SOLVED, truth/translation/history integrity, opt-in/approval/active/read-only
boundaries, exact facts/Unicode/structural assertions, source/sidecar drift,
review/model/session failures, cached known failures and global UNKNOWN fencing,
shared Journal caps, pause/stop/resume, crashed lease, explicit unknown resolution,
publication crash reconciliation, language warning and post-publication staleness.
Existing UI/truth/native worker expectations stay unchanged.

Retain RED/GREEN evidence. Native Opus Lead design review precedes native Sol
implementation. Independent native Opus implementation review is a separate gate.
Verify actual tool-free native author/reviewer on a new terminal fixture and
compose the retained historical Entropy/XYZ study after integration review.
Actual browser checks human question/answer/process, narrow/wide layout, audit,
graph/history and zero native calls from refresh. No manual narrative patch.
