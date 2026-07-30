# Changelog

## Unreleased

- Removed the v0.6 human-review dashboard: the `sisyfus dashboard` and `sisyfus panel` commands, `sisyfus/dashboard.py`, and `dashboard_static/` are gone — the Arena observatory (`sisyfus research serve`) is the single web UI. The review store itself (claims, guidance, human-context injection, the `sisyfus review` / `sisyfus guidance` CLI) is unchanged.

- Skill-first repository layout: the repo root is now the canonical skill — `SKILL.md` (with an engine bootstrap section), `references/`, and `templates/` live at the top level and are installable directly by a skills CLI; the Python engine under `src/` is the deterministic backend. `scripts/sync_skill_assets.py` mirrors the root skill into the wheel payload (`src/sisyfus/skill_assets/`, still installed per-project by `sisyfus init`), a regression test fails on drift, and the redundant `.agents/skills/` mirror is removed. README rewritten in skill form: what the skill does, install (skill + engine), quickstart, layout, design commitments.

- Deterministic evidence reproduction: `sisyfus research reproduce <research_id> <evidence_id>` re-verifies the hashed measurement code, re-runs the recorded command, diffs fresh metrics against the recorded ones, and re-classifies under the same locked contract — no model involved. Results (`contract_intact`, `code_intact`, `deterministic_match`, `verdict_stable`, capped metric drift) are appended to the event chain as the new `EVIDENCE_REPRODUCED` event and surface as `reproductions` on the evidence record; originals stay immutable. Exit 0 = code intact and verdict stable, 2 = drift or flipped verdict. Command evidence only — external/manual measurements get independence from repetition contexts instead. The verifier trust model (code-only verdicts, metrics production as the trust boundary, declared-not-measured cost units, ERROR charging cost but not attempts) is now documented in `references/verifier-contract.md`.

Arena second-pass polish: the broadcast now has a post-match ceremony, real replay navigation, reachable evidence, and a usable small-screen layout.

- Post-match scoreboard: when the run reaches a terminal status, the Arena dims and a MATCH RESULT panel slams in — final score, attempts/cost spent, match duration, loot banked, per-claim end states, with REPLAY MATCH / VIEW MAP actions; a floating RESULT button reopens it after dismissal. The topbar chip switches LIVE → ENDED once the match is over instead of pulsing red forever.
- Replay navigation: kill-feed rows are clickable (jump straight to that event) and carry timestamps; the timeline gets a visible gold knob, start/end clock labels, a 0.5× speed, and full keyboard control (Space play/pause, ←/→ step a frame, Shift+←/→ ten frames, Home/End); the current frame is deep-linkable via `#seq=N`.
- Map readability: dependency edges of touched claims light up green and the edge to the current target runs an animated gold dash; untouched claims show 🔒 instead of a misleading `?`; the hero bobs idle and clamps inside the map edge; columns spread wider so the battlefield uses its full width.
- Evidence is reachable: audit evidence rows render inline metric chips (up to 8 key values) and link every artifact reference; `serve` exposes them at `/artifact/<path>` confined to the run directory (path traversal rejected with 403).
- Events tab rework: the raw JSON dump is now one collapsible row per event (colored type, actor, clock, narrated summary) with an event-type dropdown and a JSON text filter.
- Small-screen repair: the topbar wraps (score + chip + language stay reachable, title clamps to two lines), HP/mana bars move to their own full-width row instead of vanishing, the deck re-flows, tab bar scrolls horizontally, detail grids stack, and the Arena compacts to fit.
- Detail polish: tabs stick to the top while scrolling and clicking one smooth-scrolls its section into view; the truncated match title and meta abbreviations (obj/epi, run status) are localized with explanatory tooltips; quest rows expose full statements on hover; the respawn panel collapses when nothing waits; budget drains float −N numbers off the HP/mana bars during playback; unit cards dock bottom-center (no longer covering the boss column) with a blur backdrop and slide-in.
- Report tab: an answer-first final report next to the Arena tab — terminal banner, match stats and verdict tally, then the run-level answer block (`report.headline/do/dont` per language from the TaskSpec `i18n` block or the display-only `<run>/i18n.json` sidecar, falling back to banked lessons and FAIL records), per-claim one-liners, and claims/loot evidence folded behind disclosures; `@media print` strips the broadcast chrome so the single self-contained index.html doubles as the shareable/printable final report.
- Claim `conclusion` one-liners: claims accept an optional per-language `conclusion` (TaskSpec `i18n` block or display-only `<run>/i18n.json` sidecar) rendered as the primary takeaway in the quest panel, unit card, and Report tab, falling back to the statement; renderer-added conclusions never enter the event chain.
- Verifier summaries are localized at render time by `reason_code` (zh/en, faithful to the persisted templates); dynamic details (exit codes, missing artifacts, error text) stay as a secondary original-language line — the event chain itself is untouched.

## 0.7.4 — 2026-07-28

Observatory rebuilt as an esports-broadcast Arena: the mountain view is gone, replaced by a spectator UI that shows *how* the exploration happens with the immediacy of watching a Dota match.

- Arena map: the Goal Graph is the battlefield — claims are boss nodes on dependency edges (👑 SUPPORTED, ☠️ REFUTED, 🌀 INVALIDATED cascade, `?!` INCONCLUSIVE, dim untouched); the hero unit stands at the claim the active experiment targets, with a pulsing target ring.
- Combat honesty: PASS lands as a hit (promotions slam a full-screen SUPPORTED banner; the first PASS fires FIRST EVIDENCE), FAIL is a counter-kill (REFUTED slam + screen shake + visible dependency cascade), INVALID/ERROR render as MISS — measurement failures never look like damage. Consecutive passes show a combo counter.
- Broadcast HUD: verified-vs-refuted scoreboard, attempts as HP bar, cost units as mana bar, lesson loot counter; kill feed translating every event into one punchy line; caster bar narrating the current moment; quest panel with live claim statuses; respawn panel for WAITING experiments with next_wake_at.
- Replay deck: timeline with clickable verdict/lesson/final markers, play/pause at 1×/2×/4×, LIVE button and LIVE/REPLAY chip. Frames remain deterministic prefix re-reductions (schema v3 adds attempts/cost remaining and lesson count per frame); live pages broadcast newly landed events sequentially with full effects, no reload.
- Unit identity: claims accept a `label` (2-6 char display alias; falls back to first tag, then truncated id). The map shows only numbered badges + labels; hovering a boss shows a tooltip, clicking it (or its quest-panel row) opens a Dota-style unit card with the full statement, verifier contract and repetition gate, evidence counts, and per-experiment engagement records.
- i18n: every UI string (HUD, kill feed, caster commentary, announcer slams, unit card, tab and section titles, footer) lives in a zh/en locale layer with a topbar toggle; the choice persists in localStorage and defaults to the browser language. System enums (PASS/REFUTED/…) and ids render verbatim as technical terms.
- Goal-driven stopping is symmetric (and budget-independent): root PASS already auto-stops as SOLVED; now a FAIL root with nothing in flight yields `terminal_assessment: REFUTED`, `finalize --status auto` resolves to the new terminal status `REFUTED` (guarded: only while the root is actually FAIL), and opt-in `stop_policy.stop_on_goal_refuted` makes it a hard stop that refuses further experiments. Default stays advisory so checkpoint branch recovery from a refuted claim keeps working; old locked specs are untouched (missing key reads as off).
- Budgets are now opt-in guardrails: an omitted `budget` limit means unlimited (`max_attempts`/`max_cost_units`/`max_wall_minutes` default to none instead of 20/20/120), so no default ceiling ever terminates a run its author didn't bound. Declared limits remain hard (`BUDGET_EXHAUSTED` is still terminal); admission/begin gates and the wall-clock preflight skip only the unlimited dimensions; the Arena HP/mana bars show ∞. Set explicit budgets for unattended runs — an unbudgeted cron run has no mechanical stop.
- Data-layer i18n: TaskSpecs accept a top-level `i18n` block ({lang: {topic, claims: {id: {label, statement}}}}) carried into the snapshot, and locked runs can add a display-only `<run>/i18n.json` sidecar (claims/experiments/lessons translations) merged at render time — switching language re-translates the map, quest panel, unit card, kill feed titles, goal tree, and loot texts, with fallback to the authored original. The sidecar never enters the event chain.
- The audit layer is untouched: Goal Graph / Execution / Audit / Events tabs, hash-chain head, and the replay hash check.

## 0.7.3 — 2026-07-28

Visual replay, live map streaming, and a hardened learning loop: the Observatory now shows *how* the exploration happened, and lessons carry citation-backed efficacy.

- Visual replay: every event prefix is projected into a keyframe (`objective`, `epistemic`, per-claim statuses, current state, rollback flag) by the same deterministic reducer that builds the live snapshot — scrubbing time-travels through provable history, never an animation. Frames are cached incrementally in `report/frames.json` (the append-only hash chain makes prefixes immutable, so only new events are reduced).
- Observatory replay bar: timeline slider, play/pause, 1×/2×/4× speed, and a LIVE button on the game view; the HUD labels each frame with its seq/event/state; progress-rollback frames trigger the stone-rolls-back animation.
- Live streaming without reloads: a `serve` page polls `snapshot.json` every 2 seconds and re-renders in place — the stone and scout tween to new positions, side panels refresh, and the replay slider grows as events land (previously the whole page reloaded).
- Branch map: settled verdicts are drawn on the mountain at the objective progress they occurred at — green trunk dots for PASS, red offshoots for FAIL branches, dashed violet offshoots for INVALID/ERROR, dashed red rings for dependency rollbacks; hover shows experiment title, verdict, and seq. Replay filters branches to the scrubbed moment.
- Citation discipline: experiments accept `based_on: {evidence_ids, lesson_ids}`; the admission controller rejects citations of ids outside recorded context (`citation_out_of_context`); new `stop_policy.require_citations` (default false) additionally rejects uncited proposals once at least one citable fact exists (`missing_citations`).
- Scope-aware lesson retrieval: `global_lessons` in planner context is ranked by token overlap between each lesson's scope/topic/observation and the current TaskSpec (recency breaks ties) instead of recency alone; entries carry `relevance`.
- Lesson efficacy: snapshots gain `lesson_usage` (which experiments cited each lesson and the verdicts that followed); `engine.lesson_efficacy()` aggregates lazily across all runs from persisted snapshots — no mutable counters; planner-context `global_lessons` entries carry `efficacy`; new `sisyfus research lesson-stats` CLI.
- Tests: loopback HTTP tests now bypass system proxies (a macOS system proxy at `127.0.0.1:1081` made `urllib` route loopback requests through it, failing the dashboard and observatory serve tests on any machine with a local proxy).
- Backward compatible: experiments without `based_on` are unchanged; `require_citations` defaults off; prior event streams replay deterministically; `snapshot_hash` reflects the new projections as usual (it is recomputed per reduce, not chained).

## 0.7.2 — 2026-07-24

Wait conditions: long-horizon research runs (repetition contexts separated by hours or days) no longer depend on the driving agent remembering to come back.

- Experiments accept an optional `wait`: `kind: time` (`not_before` or `after: {evidence_id, minutes}`, resolved to an absolute timestamp at proposal) or `kind: evidence` (`until_evidence: {claim_id, contract_id?, verdict?, context_id?}`). Optional `deadline_minutes` with `on_expire: backlog|release`.
- Waiting experiments are admitted but held out of the frontier (`status: WAITING`); `begin`/`execute` refuse them with the due time in the error.
- Time enters truth only through events (same pattern as the wall-clock preflight): `WAIT_FIRED`/`WAIT_EXPIRED` are recorded by the wake preflight; evidence waits are satisfied deterministically by a later matching `VERDICT_ISSUED` (ERROR/INVALID never release a wait). Replay stays hash-stable.
- New `sisyfus research wake [--now ISO] [--execute]`: settles due waits, prints `fired`/`expired`/`next_wake_at`; `--execute` runs command experiments released by that wake — one cron/launchd line gives unattended multi-day runs.
- Snapshot/planner context gain `waits`, `waiting`, and `next_wake_at`; `status`/`--brief` surface them; `terminal_assessment` gains `WAITING` (not EXHAUSTED, finalize refuses); a planner rule tells agents to schedule a wake instead of finalizing.
- `status`, `context`, `report`, `serve`, `propose`, `begin`, and `finalize` preflights now settle due waits alongside the wall budget. Wall budget keeps accruing while waiting: `max_wall_minutes` is the calendar deadline of the whole research program — size it accordingly for waiting runs.
- Backward compatible: experiments without `wait` are unchanged; v0.7.0/v0.7.1 event streams replay deterministically.

## 0.7.1 — 2026-07-24

Trust-boundary, lesson-lifecycle, and DX improvements driven by the first real research run (cross-venue funding-arb study).

- Measurement-code preregistration: files referenced by a command action are content-hashed into the attempt manifest and evidence (`code_hashes`); changes between attempts of the same experiment are flagged (`code_changed_since_last_attempt`).
- Cross-branch contradiction accounting: a claim SUPPORTED on the current branch while FAIL evidence exists on any branch is marked `contested` (with `contradicting_evidence_ids`); a later PASS experiment carrying a `discriminating_note` resolves it. New `stop_policy.require_uncontested_solve` (default false, template default true) blocks SOLVED and finalize while a required claim is contested; `terminal_assessment` gains `CONTESTED`.
- Global lesson store: `lesson-promote` upserts into `.sisyfus/research/global_lessons.jsonl`; every run's planner context now includes `global_lessons` from other runs so experience compounds across tasks; `lesson-revoke` updates the store.
- `lesson-evidence-add` (CLI + `LESSON_EVIDENCE_ADDED` event): append later-earned evidence to an existing lesson instead of recreating it.
- `stop_policy.allow_provisional_prereq` (default false): admit dependent-claim experiments once the prerequisite has a provisional PASS, removing the incentive to weaken declared `depends_on` edges.
- `falsify` is now a valid experiment mode; experiments accept `discriminating_note`.
- CLI: structured JSON errors on stderr instead of tracebacks (`SISYFUS_DEBUG=1` restores tracebacks); `--brief` on `status`/`propose`/`execute`/`settle`; `research new` warns about unenforced `hard_constraints`; summaries surface `contested_claims`.
- Backward compatible: default-off enforcement flags; v0.7.0 event streams replay deterministically and keep their final statuses.

## 0.7.0 — 2026-07-21

- Added the integrated `sisyfus-research` skill.
- Added Research TaskSpec v2, Goal/Execution/Evidence graphs, and event-sourced reducer.
- Added five-state verification contracts and preregistration hashes.
- Added branch checkpoints, dependency rollback, repetition gates, attempt recovery, and scoped lessons.
- Added locked TaskSpec verification, dependency/action-space admission gates, host-only visibility gates, and in-flight attempt/cost reservations.
- Added hard attempt, cost, and wall-clock budget enforcement.
- Added `sisyfus research` CLI and self-contained Sisyphus HTML Observatory.
- Preserved v0.6 harness, beam, rubric, monitor, dashboard, and memory commands.
