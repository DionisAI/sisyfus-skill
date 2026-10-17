# Research graph redesign — frozen acceptance (2026-10-05)

## Request and scope

The operator explicitly requested Claude Opus 5.5 to rewrite the research
Observatory's graph presentation. This is a scoped exception to the default
Sol implementer role, not an RSI promotion or a change to worker dispatch.
Implementation and independent review must have distinct native receipts with
`requested_model=claude-opus-5-5` and top-level runtime model attestation.

Only `src/sisyfus/ui_theme.py`, presentation strings/functions in
`src/sisyfus/research_v2/observatory.py`, and presentation strings in
`src/sisyfus/activity.py` are editable. Stage the native changes separately;
controller integration is a later gate. Existing dirty chat/RSI files, installed
release, research events, task specifications, and artifacts are preserved.

## Frozen visual contract

- Theme ID: `sisyfus-research-workspace-v2`; shared `color-scheme: light`.
- Chinese-first, warm paper, restrained terracotta/olive accents. A clear topic
  header and understated status; no esports scoreboard, glowing HP bars,
  confetti, hero animation, or automatic completion overlay obscuring the map.
- Graph is the main view: legible rectangular claim nodes, dependency arrows,
  text status labels, useful truncation/wrapping of long Chinese labels. Fit,
  zoom in/out, and reset controls are accessible. Node selection opens a quiet
  inspector showing the claim, verdict, contracts/experiments and evidence links.
- The graph is legible and usable at 460px and 1440px widths. Large (12+ node)
  multi-level graphs expose all nodes through the viewport controls; no clipped
  page or overlapping nodes. Sidebar/details may stack or use disclosure.
- Completion keeps the graph visible. `SOLVED` is research completion, not a
  positive profit finding; `INCONCLUSIVE` and optional claims stay explicit.
- Bootstrap and full graph share the same light visual language. The activity
  HUD is collapsed by default with an accessible toggle, never covering the
  core graph on first load. Expand retains real activity/heartbeat/error facts.
- Keyboard node selection (Enter/Space), visible focus, reduced motion,
  translated labels, empty/wait/error states, and print output are retained.
- No new network dependencies, package installation, external fonts, framework
  migration, or backend/state changes. Self-contained persisted HTML remains.

## Frozen correctness gates

1. Existing theme, flicker, Observatory, live-server and wait regressions pass.
   Only obsolete *dark palette* assertions are replaced before implementation
   by the above explicit light contract. Shared shell/state checks stay intact.
2. Python functions outside presentation are unchanged by AST comparison. Keep
   `_json_for_script` script escaping and all persisted snapshot/event payloads.
   Frame selection/reduction, live polling, hash chain and verifier semantics
   remain unchanged. No experimental outcomes or tests are changed by Opus.
3. New static acceptance checks: versioned shared light theme, viewport controls,
   reduced motion/focus rules, escaped hostile content, collapsed activity HUD.
4. Actual browser checks: 460px + 1440px, real 26-event completed run, node
   selection, dependency layout, replay seek/play/live, report/audit tabs,
   language switch, bootstrap and retained 12+ node fixture, no JS errors.
5. Fresh read-only native Opus review of the scoped patch against this contract;
   reported issues must be resolved or remain visibly pending, never waved away.
6. Deliver an updated live graph page and retained before/after screenshots,
   test receipts, runtime model receipts, and source/research integrity manifest.

## Evidence location

`artifacts/techlead/graph-redesign-20261005/` holds reservations, native event
streams, receipts, staged proposals, baseline hashes, test logs and screenshots.
Native completion is not acceptance. No claim of measured RSI improvement.
