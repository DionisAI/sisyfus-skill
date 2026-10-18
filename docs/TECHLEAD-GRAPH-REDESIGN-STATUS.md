# Research graph redesign — delivery status (2026-10-05)

## Delivered

- Branch: `codex/techlead-graph-redesign`. Existing dirty chat/RSI changes preserved.
- Live page: http://127.0.0.1:8756/index.html. Only the existing graph service was restarted.
- Actual native `claude-opus-5-5` implemented the scoped presentation; fresh read-only review session `809ea75c-9e52-4ae6-a51d-81021a8c228a` returned PASS. Requested and runtime-attested model both match.
- Chinese-first light paper workbench, layered claim cards/arrows, keyboard selection, evidence inspector, Fit/zoom/reset, replay and report/audit tabs. Completion stays on the graph; SOLVED does not imply profit.

## Verified

- 73 frozen regressions pass (7.79s); 35 nonpresentation AST fingerprints and exact `frameAt`/`deriveTimeline` remain unchanged. Five inline fixture scripts parse.
- Retained 14-node synthetic DAG at 460/1440px: no overlaps/page overflow; narrow Fit exposes every node, Reset restores readable zoom; Enter and Space selection, language and replay exercised.
- Actual controller provisional PASS remains INCONCLUSIVE until its frozen repeat threshold. Live polling updated node/list from provisional 1 to 2 without reload.
- Real 26-event study: 2 SUPPORTED / 1 optional INCONCLUSIVE; no completion overlay. All 3 nodes contained at both 460 and 1440px, no HUD overlap, no browser console errors. HUD expansion and collapse verified.
- Real first-event seek, playback through event 26, Latest, Chinese/English/Chinese, inspector, report and audit tabs verified.
- Real report/replay artifact HTTP responses are 200 and byte-identical to retained canonical run_dir files. Event chain/replay remain valid with matching hash `sha256:02b54b9b87a4df1dc7259498df9f4e5d0a25ff3e2bc217021e97410d47bd6bc8`.
- Print media hides interactive graph/HUD and shows the research report. Print emulation was cleared; no PDF export was performed.
- Reviewed source hashes unchanged at delivery. Sixteen protected files, including task/events and unrelated user work, unchanged. No worker dispatch, native trading, or RSI promotion. Temporary fixture tabs/server and viewport overrides cleaned up; real localhost graph remains live.

## Retained diagnosis and limits

- Initial native implementation timed out with a durable proposal and UNKNOWN receipt. It was fenced, not blindly retried or treated as accepted. Distinct scoped native sessions completed remaining presentation and observed repairs.
- First independent review was CHANGES_REQUIRED for narrow fixed-HUD overlap and provisional-cache staleness. These were repaired by Opus; final fresh review passed. Incorrect-width/mid-relayout and distorted CDP screenshots remain retained but were excluded from acceptance.
- Initial HTTP checker assumed artifacts under mission root. The unchanged server uses ResearchWorkspace.run_dir; readback at that canonical path matches file bytes. No server change was needed.
- Existing `evExtras` is byte-identical to baseline and still produces blank links for legacy artifact entries without `.path`. Valid path-backed report/evidence links were checked successfully. This pre-existing presentation rough edge is not counted as a new regression.

## Receipts

All native reservations/events/receipts, frozen baseline/AST manifests, failed diagnoses, tests and before/after images are retained under `artifacts/techlead/graph-redesign-20261005/`. See `final-acceptance-receipt.json`, `review-final-receipt.json`, `deterministic-tests-03.log`, `live-http-checks.json`, and `live-graph-final-wide.png`. Frozen requirements remain in `docs/TECHLEAD-GRAPH-REDESIGN-ACCEPTANCE.md`.
