# Reader-first report delivery — 2026-10-06

## Delivered

The operator's Entropy × XYZ question now leads the live Report: whether the
strategy works and how much it can earn. The answer is plain language: this
10-minute public sample did not complete a cycle in either model, so profit is
unestablished. Study-phase completion is not an answer to the profitability
question. No trading, account integration or RSI promotion occurred.

The report explains the mechanism, conditional profit arithmetic, full-cycle
fees, measured results, limitations and a concrete next measurement. Four
process steps describe what was done, what was found and why it matters.
Controller counts/contracts/verdict details are behind a closed technical
disclosure; graph, quest and inspector show matching latest-frame takeaways.
The original reports, market data, ledgers and event chain remain unchanged.

Live entry: http://127.0.0.1:8756/index.html?view=report

Research: `research-entropy-xyz-turnover-20261005-20261005T142741Z-d9bcdfb8`.
Snapshot/replay pin:
`sha256:02b54b9b87a4df1dc7259498df9f4e5d0a25ff3e2bc217021e97410d47bd6bc8`,
26 events; profitability remains `INCONCLUSIVE`.

## Evidence and scope

- Development branch: `codex/techlead-reader-report`; existing dirty work retained.
- Implementation is limited to the Observatory `_TEMPLATE`. Python projection,
  verifier, HTTP, state and invocation functions are unchanged. Theme unchanged.
- New `i18n.json` is presentation only, pinned to the exact snapshot/event count.
  Stale, missing and invalid reports show diagnostics instead of financial prose.
  The standalone human report is a new `artifacts/reader-report.md`; prior report
  artifacts were not overwritten.
- Frozen acceptance preceded native implementation. Both candidate runs passed
  all 81 checks (73 existing + 8 new), without changing expectations. Final run:
  `artifacts/techlead/reader-report-20261006/candidate-final-tests.log`.
- Browser checks: 460px and 1440px without page overflow; contained tables;
  four process steps, seven sources; closed/default and expanded audit; labelled
  Chinese-original fallback in English; latest/history separation; same-snapshot
  sidecar refresh; missing/stale/invalid diagnostics; no observed console errors.
- Opus Lead returned corrections, all eight essential financial corrections were
  incorporated. Its incorrect "below the step" minor note was corrected to
  "not aligned to the step": 0.0132 is greater than 0.001.
- Native implementation requested `gpt-6.1-sol`, completed in an isolated stage.
  Runtime model identity is **unattested** (`actual_model=null`); this driver's
  telemetry does not provide per-generation identity. No model echo is treated
  as attestation. Two subsequent bilingual footer strings were controller copy
  edits and separately reviewed.
- Fresh read-only independent review: requested and runtime-attested
  `claude-opus-5-5`, session `593182a2-c63d-483e-a482-1cda17bc57c6`, **PASS**.
  This is a presentation/financial-narrative review, not new trading evidence.
- Controller separately gated deployment, verified the old 8756 service's PID
  and command, preserved its state via SIGTERM, and restarted only that service.
  Protected 27-file hashes and deterministic snapshot/events were unchanged.

Retained receipts, prompts, failures, fixtures and screenshots are in
`artifacts/techlead/reader-report-20261006/`.

## Limits and retained diagnoses

- The first preview helper read a non-persisted snapshot file. The failure and
  fixture were retained; `engine.snapshot()` plus a fresh fixture directory fixed
  the harness without changing product code. Native scratch-harness failure was
  also retained and diagnosed separately from product checks.
- Financial inputs are historical public data, not private fills. Official
  Entropy fee/referral rules were refreshed; XYZ live fetch failed, so its fee
  assumptions remain explicitly sampling-date inputs. Conditional 1/2/5bp
  profits are not measured daily returns or achieved capacity.
- This adds a reusable reader schema/renderer, not an automatic report-authoring
  worker. Future missions must supply an evidence-linked reader narrative as
  described in the frozen contract; missing prose is exposed as missing prose.
- Independent review noted non-blocking legacy fallback/link-scope and wording
  items in its retained receipt. They are not financial proof, acceptance changes
  or a request to expand this delivery into unrelated refactoring.
