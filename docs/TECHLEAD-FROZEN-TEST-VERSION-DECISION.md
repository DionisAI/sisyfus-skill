# Frozen-test version decision (signed 2026-10-13)

- **Status:** SIGNED by the user on 2026-10-13: "approve all, WAL-aux, p16 no — apply it". Every item is approved with its recommended option: V1 keeps the 35 old-contract tests red and fixes the 24 agent-side tests; V10 keeps red; V11 is WAL-aux; for p16, the web `diagnostics50` cap does not cover task-level diagnostics. Application is recorded in the ledger under "用户决定：冻结测试版本（2026-10-13）".
- **Date:** 2026-10-12
- **Tree:** branch `codex/techlead-delivery-20261008` at `d03d58c`, plus the uncommitted working tree.
- **Answers:** the pending "原冻结测试版本决定" / "旧冻结oracle版本决定" in [TECHLEAD-ORCHESTRA-STATUS.md](TECHLEAD-ORCHESTRA-STATUS.md) lines 34 and 104. It also settles the open sub-questions at lines 150, 159, 175 and 208.

## Scope

Under the retained runner, 247 tests in 43 files fail today:

| Run | Failed | Errors |
|---|---|---|
| Main run (`scripts/test_retained.py`, Python 3.12, `SISYFUS_TEST_LOOPBACK=1`) | 197 | 28 |
| Web guard | 2 | 19 |
| Share guard | 1 | 0 |

Every failing test is classified below and listed in Appendix A. A classifier reproduced each failure first. An independent verifier then reproduced it again and checked the reading. Where the two disagreed, this draft uses the verifier's reading.

| Verified category | Tests |
|---|---|
| Superseded contract: the test encodes an older contract version | 133 |
| Test defect: the oracle or fixture is wrong under every contract version | 56 |
| Missing baseline: a frozen input file was lost | 20 |
| Policy conflict: the outcome depends on a choice the user has not made | 18 |
| Harness or environment | 11 |
| Open source bug | 9 |

CI (`python -m pytest -q`, Python 3.11–3.13) is not affected by any of this. CI sees only committed files, and nearly all of these tests are untracked.

## How to sign

Mark each item **Approve**, **Alternative**, or **Hold**. Approved items are carried out in the order given in "Order of work". Each item gets its own rerun, and its own ledger entry under a new "用户决定：冻结测试版本（2026-10-12）" heading. Items marked Hold stay red and documented, exactly as they are today.

## Summary

| Item | Question | Tests | Recommendation | Result if approved |
|---|---|---|---|---|
| R0 | Standing rule for minimal, recorded corrections to frozen tests | enables T, V3–V9, V11 | Approve | — |
| B1 | Restore the lost 0073 claims baseline | 20 | Approve | 20 green |
| V1 | Gateway response-admission v2: what happens to the old tests | 59 | Keep the 35 old-contract tests red. Fix the 24 agent-side test wrappers. | 24 green, 35 red |
| V2 | Public-tree verification pinned to node_agent `fe5efc13` | 13 | Archive | 13 archived |
| V3 | Mission inbox v2: terminal status NOT_APPLIED replaces BOUND | 5 | Ratify v2 | 5 green |
| V4 | Revoked offer: does the spending fence come before PermissionError? | 1 | Ratify fence-first | 1 green |
| V5 | Sync schema: reject a bad batch, never rewrite it | 1 | Ratify reject | 1 green |
| V6 | `GET placements` is now 200 | 1 | Ratify | 1 green |
| V7 | Host CLI: owned shutdown helper thread | 10 | Ratify | 10 green |
| V8 | Remote pipeline: gateway attach | 1 | Ratify | 1 green |
| V9 | Portal v5/v6 calibration | 38 | Ratify v6 | 37 green, 1 archived |
| V10 | Share gateway: exact public-signature lock | 1 | Keep red | 1 red |
| V11 | W3: strict physical zero-write, or WAL auxiliary sync | 10 | WAL-aux | 8 green, 2 archived |
| T | Test defects and harness bugs (wrong under every version) | 67 | Fix 63, archive 4 (under R0) | 63 green, 4 archived |
| S1–S3 | Source fixes (source is on HOLD) | 9 | Approve | 9 green |
| P | Deletion guard vs. core tests | 8 | Keep red | 8 red |
| A | Already decided by the user | 3 | No action | 3 red |
| **Total** | | **247** | | **180 green, 20 archived, 47 red** |

These counts are a projection. Each group has been proven in scratch copies, but a group is counted green only after it is rerun in place.

## R0 — Standing rule for frozen-test corrections

Today a frozen test may change only with the user's approval of that specific edit. The one precedent is the placement-recovery read fix (ledger lines 245–249). This draft proposes a standing rule, so that the user does not have to approve dozens of individual edits.

A frozen test may be corrected only when one of these holds:

- **(a)** the oracle or fixture is wrong under every contract version. Examples: a wrong index, a wrong field name, a bad call signature, or an assertion that compares a dict to a Path.
- **(b)** the user has ratified a newer contract version in this document, and the test still encodes the older one.

Every correction must also meet all of these conditions:

1. **Smallest possible diff.** The edit touches only the lines named in this document. Everything else stays byte-identical.
2. **No masking.** Do not add `skip`, `xfail`, or deselection. Do not add a source alias, shim, or compatibility name just to make an old test pass.
3. **Ledger entry for each file.** Record the old sha, the new sha, the lines changed, and the R0 clause used. Records that cite the old sha keep referring to the pre-edit version, exactly as in the placement-recovery precedent.
4. **Retiring a test is a move, never a deletion.**
   - **Whole file:** move it byte-identical to `artifacts/techlead/retired-tests-20261012/`. That location is outside `testpaths = ["tests"]`, so pytest no longer collects it.
   - **One function:** copy the function verbatim into an archive file there, then remove it from the host file. The removal is itself an R0 edit.
   - Most of these files are untracked, so this move keeps the only copy. Nothing goes to Trash.
5. **Reproduce first.** Each corrected test is reproduced red before the edit and green after it, on the retained runner.

*Alternative:* do not adopt R0, and approve each T and V item one edit at a time instead.

## B1 — Restore the 0073 claims baseline (20 tests)

`test_node_gateway_claim_request_admission.py` needs `SISYFUS_GATEWAY_CLAIMS_BASELINE`. That variable must point to a read-only copy of `node_claims.py` at sha `0073e15c…`.

The original copy lived under `/private/tmp/sisyfus-gateway-v6-claim-ingress-9f60f188f8fc/`. It is pinned in `source-gate-progress-v30.json:60` and has since been lost.

**Rebuild.**
- The file was rebuilt byte-exact from the Read results in the `node-gateway-review-v6` `events.jsonl` transcript.
- The rebuild produces one extra trailing newline. With that byte removed, the sha matches.
- With the rebuilt copy, the file reproduces its recorded result: 20 passed and 8 failed. The 8 failures are the V1 tests in gw1.

**Proposal.**
1. Place both baselines read-only (mode 444) under `artifacts/techlead/frozen-baselines/`:
   - `node_claims.0073.py`, the rebuilt file.
   - `node_claims.8302.py`, a byte copy of the existing `artifacts/techlead/orchestra-20261006/node-response-admission-source-v1-halley-8cea280add/node_claims.before.8302.txt`.
   - The 8302 copy is needed because that file is mode 644, and the fixtures require a read-only file. Today the retained recipe points `SISYFUS_GATEWAY_RESPONSE_CLAIMS_BASELINE` at a scratch copy, which gets wiped.
2. Export both variables in the retained-runner recipe.

No test or source file changes.

*Alternative:* leave the 20 tests red as "baseline lost", with the rebuild recorded only as evidence.

## Version rulings

### V1 — Gateway response-admission v2 (59 tests)

The gateway now requires each NodeClaims method to accept a named, keyword-only `admit_response`. Without it, the gateway refuses with an explicit 500 before dispatch (`node_gateway.py:452-461`; ledger line 217). The v2 and compat test files encode this contract, and they pass (92 + 7).

**Recommendation, part 1: keep 35 old-contract tests red.** These tests assert the pre-v2 behaviour itself. The record says to keep them unchanged: `preliminary66-preservation-v1.json` has `preserve_old66_unchanged`, and the ledger rule is "original kept, v2 in a separate file". The current contract is covered by the v2 and compat files.

| Group | File | Tests | Note |
|---|---|---|---|
| gw1 | `test_node_gateway_claim_request_admission` (ordinary identity) | 8 | After B1, these fail with the designed 500 instead of a KeyError |
| gw2, gw3, gw4 | `test_node_gateway_response_admission` (v1 file, sha `82e13d76`) | 20 | The other 46 tests in the file pass |
| gw5 | `test_node_gateway_response_deadline` | 6 | Compat re-expresses them and imports helpers from this file |
| gw6 | `test_node_gateway` internal-errors diagnostics | 1 | Covered by compat scenario 1 |

**Recommendation, part 2: fix 24 agent-side tests under R0(b).** The agent behaviour these tests check is still current; only their monkeypatched wrappers predate v2.

| Group | File | Tests |
|---|---|---|
| ah1 | `test_node_agent` | 9 |
| ah2 | `test_node_agent_gateway_error_type` | 6 |
| ah3 | `test_node_agent_review_v1_micro` | 4 |
| ah4 | `test_node_agent_review_v2_micro` | 5 |

- **The fix:** give each fault-injection wrapper the exact backend signature plus `*, admit_response=None`, and forward it. This is the pattern compat7's `_postcommit_wrapper` already uses.
- **Proof:** scratch copies with this fix, plus the T/ah0 read fix, pass 31/31.
- **Same pass, 20 more tests:** these currently pass vacuously. The gateway refuses them with a 500 before the tamper under test is ever applied. Fix their wrappers in the same pass so that they test what they claim. They are:
  - `test_tampered_claim_offer_or_input_never_grants_native` (13)
  - `test_corrupt_sync_ack_identity_or_highwater_never_acknowledges_local_events` (7)

*Alternative A:* archive the 35 old-contract tests. They duplicate v2/compat, but this contradicts the preservation record.
*Alternative B:* keep all 59 red, and leave the 20 vacuous passes as they are.

### V2 — Public-tree verification pinned to `fe5efc13` (13 tests)

`test_node_agent_public_tree_verification.py` is one parametrized function, 13 cases. It hard-pins two hashes:
- `node_agent.py` at `fe5efc13` (lines 32, 113)
- `test_node_agent.py` at `e5957efd` (lines 33, 114, 258-259)

`node_agent.py` has since moved through this revision chain, each step a reviewed or user-approved revision:
- `8c6fa0b1` (v1 micro)
- `68194a4b` (v2)
- `5bab92bc` (v3 error type)
- `6293bb32` (network profile, FINAL-PIN)
- `2f0abd23` (timeout race fix, current)

The file cannot pass on current source without changing both pins and its wrappers, which would make it a new test. It passed 13/13 at `fe5efc13`, and that record is kept.

**Recommendation:** archive the whole file, together with its "13 passed at fe5efc13" record.

*Alternative:* keep red, as historical pin evidence.

### V3 — Mission inbox v2 terminal status (5 tests)

`test_mission_inbox_review_dispatch::test_ordinary_and_legacy_default_purpose_calls_still_receive_context` (×5) fails NOT_APPLIED ≠ BOUND at line 71.
- The v2 semantics came from an independent review fix. A known-terminal operator note with no acceptance evidence now shows NOT_APPLIED.
- Ledger line 150 records that user confirmation was requested and is still open.
- The point of the test is that the context is delivered, and that part passes.

**Recommendation:** ratify v2, and change line 71 to expect NOT_APPLIED. Alternatively, assert BOUND before the terminal receipt.

*Alternative:* reject v2. The source then returns BOUND in `mission_inbox._application_status`, and the test stays unchanged.

### V4 — Revoked offer error order (1 test)

`test_node_claims::test_revoked_offer_is_never_claimed` expects a PermissionError. Instead, `DispatchBlocked` is raised first, from the UNKNOWN spending fence at `journal.py:107-114`. That fence came from a fix for an independent review finding (ledger line 159). The offer is still never claimed.

**Recommendation:** ratify fence-first. Change lines 216-222 to expect `DispatchBlocked(match='shared spending')`.

*Alternative:* keep red until a separate error-order contract is written.

### V5 — Sync schema policy (1 test)

`test_node_gateway::test_sync_schema_batches_and_secret_redaction_not_fake_native_identity` expects 200. The gateway returns 400: a batch that carries the node's credential material is rejected as a whole, never redacted and accepted (`node_gateway.py:736-737`).

**Recommendation:** ratify reject. Change line 560 to expect 400, and keep the secret-not-in-state and IN_FLIGHT assertions.

*Alternative:* keep red.

### V6 — `GET placements` is 200 (1 test)

`test_node_operator_http::test_unknown_unbound_symlink_paths_and_strict_route_queries` still lists `placements(ident)` among the routes that must 404. TECHLEAD-NODE-WEB-CONTRACT.md lines 30-35 made it a 200 route.

**Recommendation:** remove that entry at lines 178-179.

*Alternative:* keep red.

### V7 — Host CLI owned shutdown thread (10 tests)

The `test_node_host_cli_lifecycle` ThreadDI fixture was written against the old `lead_cli`, which used `target=gateway.serve_forever`. The source has since changed in two reviewed ways, and the fixture fails on both:
- The thread target is now an owned closure, `serve_owned`, which calls `serve_forever()` and records loop errors. Line 396 asserts `target.__self__ is r.gateway`, which no longer holds. The lifecycle contract (TECHLEAD-NODE-HOST-LIFECYCLE-CONTRACT.md:25) only requires that the public `serve_forever` is used, and that still holds.
- `_shutdown_owned` now starts a second thread for shutdown. ThreadDI replaces `threading.Thread` globally, so this helper thread overwrites the recorded `r.thread`.

**Recommendation:** change ThreadDI in two places. Both changes together are proven 26/26.
- At line 396, accept any callable target.
- Record only the thread named `techlead-node-gateway`.

*Alternative:* keep red.

### V8 — Remote pipeline gateway attach (1 test)

`test_orchestra_remote_pipeline::test_real_coupled_public_pipeline_materializes_bytes_and_keeps_context_not_acceptance` needs a hub with an attached node gateway.

**Recommendation:** call `self.hub.attach_node_gateway(self.gateway, serve_thread=self.server)` in this test's own setup. Do not put the call in the shared `Pipeline.__init__`. That would break `test_orchestra_delivery_context` with "host gateway already attached".

*Alternative:* keep red.

### V9 — Portal v5/v6 calibration (38 tests)

Portal v6 deliberately changed four things:
- P3: `approval_hash` must be a real digest.
- P1/P4: a pre-send GET failure is a known no-POST 409.
- P1: replay does one readonly GET.
- P3: GET no longer persists the mission mapping.

The current portal source is pinned by PHONE-PORTAL-SOURCE-GATE-v8. HANDOFF-v6 leaves calibration to "a fresh Main audit", and REVIEW.json line 16 says it is "not waived". So the decision belongs here.

**Recommendation:** ratify v6.

| Group | Tests | Change |
|---|---|---|
| p0, p5 | 30 | Shared fixture: `approval_hash = protocol.digest({source, spec, proposal})`, as `test_portal_review_v6` already does |
| p1 | 3 | Digest fixture. Also inject the failure on the mutating POST only. |
| p2 | 1 | Digest fixture. Also add `kind: 'remote'` to the DI placement receipt. |
| p3 | 2 | Digest fixture. Also allow one readonly GET on replay, and set up the mission mapping by an explicit mutation before asserting the 409. |
| p6 | 1 | Archive (one function). `test_portal_review_v6.py:166` is its exact current-contract replacement and passes. |
| p7 | 1 | Line 34: expect CREATED, with spec PENDING. |

*Alternative:* keep all 38 red until the fresh Main audit runs.

### V10 — Share gateway exact-signature lock (1 test)

`test_share_gateway::test_frozen_share_gateway_public_api_availability` locks the exact public signatures. The password feature added the keyword-only `password_verifier=None`.

**Recommendation:** keep red. PASSWORD-CONTRACT-v1.md line 16 says the lock is "not edited to green", and that matches the scope-lock precedent at ledger lines 238-243.

*Alternative:* rewrite the lock to the v1 password contract, with `password_verifier` keyword-only and default None.

### V11 — W3: strict zero-write or WAL auxiliary sync (10 tests)

This is the W3 choice that has been pending since ledger lines 34, 104 and 208.

**Measured facts:**
- A SQLite reader opened with URI `mode=ro` on a live WAL database still writes `-shm`. If `-shm` is missing, the reader creates it.
- In the six-candidate artifact-only measurement, no reader achieved zero writes (ledger line 213).
- The accepted delivery claims logical read-only and makes no physical zero-write claim: DELIVERY-ACCEPTANCE-20261008.md lines 21 and 45.

| Group | Tests | Under WAL-aux (recommended) | Under strict zero-write |
|---|---|---|---|
| prc10: `test_real_wal_substitution_get_has_zero_tree_effects`, warm and cold `approval_open` | 8 | Rewrite the oracle to allow a change to `-shm` only, plus its directory entry when it was created → green | Source fix: fence `approved_spec`'s connection before its SELECT (proven to give zero tree change in the `cold-snapshot_open` case) → green |
| prc11: `test_actual_uri_ro_live_wal_zero_full_tree_candidate` | 2 | Archive (one function). It measures SQLite itself. | Keep red, as an unmet requirement that no SQLite reader can meet |

**Recommendation:** WAL-aux. It matches the accepted delivery, and it is achievable.

## T — Test defects and harness bugs (67 tests, under R0(a))

Each of these is wrong under every contract version. The exact change for each group is in Appendix A.

| Group | File | Tests | Defect |
|---|---|---|---|
| ah0 | test_node_agent | 7 | Reads `claims.get()['tree']`. Under the no-backfill rule, which predates the test, old projections never gain `tree`. Read `status()['tree']` instead. This also breaks the `e5957efd` pin in V2. |
| gw7 | test_node_gateway | 1 | BOUND is read at the wrong level (line 340). |
| gw8 | test_node_gateway | 1 | Compares the receipt (transport view, with `tree`) to `claims.get()` (legacy view, without `tree`), so it can never be equal (line 473). The no-backfill rule predates the test. |
| gw11 | test_node_gateway_lifecycle | 1 | `make_spec(tmp_path)` is called twice, giving FileExistsError (line 67). |
| ah8 | test_node_host_admission | 4 | Asserts a non-deterministic `wall_minutes`. Archive the whole file; `test_node_host_admission_stable.py` passes 4/4. |
| ah9 | test_node_host_review_boundaries | 3 | `Thread(context=)` exists only on Python 3.14. |
| ah10 | test_node_host_review_boundaries | 1 | Same, plus a literal message that stdlib selectors never produce (lines 1089-1090). Relax to a type-only check. |
| ah11 | test_node_cli | 3 | In the f-string at line 413, `{{…'run':guard.name}}` is escaped, so `guard.name` is written literally into the child's code, where `guard` is undefined. Interpolate `{guard.name!r}`. |
| prc7 | test_node_placement_readback | 2 | Revision fixture omits required check `b` (lines 157, 225). |
| prc8 | test_node_placement_preparation_http | 1 | Expects the canonical run status to equal the receipt status (`'RECEIPTED' == 'ERROR'`). The canonical status is UNKNOWN/RECEIPTED, and the native status lives in the receipt (line 250). |
| prc13 | test_node_placement_readback_sideeffects | 3 | `real_swap` leaves stale `-wal`/`-shm` beside the new database. |
| prc14 | test_node_placement_readback_sideeffects | 1 | Same oracle fix. Green only together with S2. |
| prc16 | test_remote_artifact_io_v2 | 1 | `env[3]` should be `env[5]` (line 54; ledger line 175). |
| prc18 | test_orchestra_remote_pipeline | 2 | Asserts `is None` where the contract gives UNKNOWN with no candidate (lines 464, 523). |
| prc19 | test_orchestra_delivery_context | 1 | pytest rewrites an imported helper's assertion text (line 98). |
| p4 | test_portal_review_v6 | 9 | Compares the error object to a string. The `*_wire_v2` copies already pass. |
| p9 | test_mission_inbox_terminal_review | 1 | `event_type` should be `type` (line 313; ledger line 150). |
| p10 | test_lead_journal_record_in | 1 | The SQL starts with a newline, so the match needs `lstrip()` (line 48; ledger line 179). |
| p11 | test_share_cli | 2 | `fail()` must accept the sleep argument (line 106). |
| p13 | test_share_runtime | 1 | The upstream fixture is not a real Console capture. |
| p14 | test_lead_engineering_result_web | 8 | The web guard blocks the stdlib `gethostbyaddr('127.0.0.1')` that every HTTP bind performs. `web_guard.py` is sha-pinned in FINAL-FROZEN-HANDOFF.json, so this is a new freeze. |
| p15 | test_lead_engineering_result_web | 12 | Same guard fix, plus `snapshot_calls` needs a reset after `hub.create()`. |
| p16 | test_lead_engineering_result_web | 1 | Needs one answer first: does the web `diagnostics50` cap cover task-level diagnostics? Recommended answer: no. In that case the fixture must produce more than 50 non-task diagnostics. |

## S — Source fixes (9 tests; source is on HOLD)

Each of these lifts the source HOLD for one narrow change. Each change gets its own fresh independent review before it is accepted.

### S1 — Warm-path placement readback writes (7 tests, prc9)

**Problem:** the warm branch of `lead_console.placements()` opens a read-write `store._transaction(...)`, which runs `PRAGMA journal_mode=WAL` before the identity fence. A GET can therefore:
- create the database,
- flip header bytes 18-19 from [1,1] to [2,2],
- and write the main database, `-wal`, and `-shm`.

This is the P2 still on HOLD at ledger line 197.

**Proposed fix:** route the warm and cold branches through one URI `mode=ro` transaction, fenced before any read.

**Caveat:** `test_node_placement_readback.py:194-216`, which passes today, asserts `admissions == [False]` for the warm path, and the fix may change that. If it does, the test needs its own R0(b) entry. Otherwise, choose a fix that keeps the warm admission.

### S2 — Cold-path open error is 500, not 403 (1 test, prc12)

**Problem:** the cold branch calls `sqlite3.connect(...?mode=ro)` before its `try`, so an open error on a vanished database surfaces as a 500.

**Fix:** map these errors to the identity PermissionError (403), as `_check_placement_identity` already does for OSError.

### S3 — Share gateway listen backlog (1 test, p17)

**Problem:** `ShareGateway` admits up to `MAX_HANDLERS = 16` requests at once, but keeps the stdlib listen backlog of 5. On macOS loopback, a burst of 16 clients overflows that backlog and gets TCP resets. The contract only allows 200, 429 or 503 in that case.

**Fix:** set `request_queue_size = 64`. Proven 3/3; the whole file is 62 passed with it. The test is unchanged.

*Alternative for each:* keep red until the next source window.

## P — Deletion guard vs. core tests (8 tests): keep red

These core tests delete files inside their own temp directories:
- `test_benchmark`
- `test_portfolio`
- `test_autonomy_store`
- `test_cli`
- `test_release_integration`
- `test_updater` (×2)
- `test_updater_hardening`

The retained runner's audit hook blocks permanent deletion, so they fail there. They pass in CI. Ledger line 153 already records this, so no action is needed.

## A — Already decided (3 tests)

- `test_node_agent_network_profile::test_static_constructor_cli_and_only_duration_change` stays red. The user decided this on 2026-10-11 (ledger lines 238-243, commit `804658f`).
- `test_remote_artifacts::test_real_deletion_uses_exact_trash_argv_and_is_recoverable` and `test_failed_trash_explicitly_retains_candidate_before_and_originals` stay red. The user confirmed the IO v2 staging-Trash contract and asked to keep the old tests (ARTIFACT-IO-V2 contract lines 3-15; ledger line 175).

## Order of work

These steps apply only after signature.

**Dependencies.** Some groups cannot go green on their own:

| Group | Needs first |
|---|---|
| ah1 | ah0 |
| prc14 | S2 |
| p15 | p14 |
| p0–p3, p5 | the shared digest fixture (one edit fixes 30 tests) |

**Steps.**
1. **B1.** Create the read-only baselines and update the recipe.
2. **T and the R0(b) rewrites.** Work one file at a time. For each file: reproduce red, edit, rerun the file, then rerun its neighbours, then write the ledger entry. Start with ah0 → ah1–ah4, then the portal fixture.
3. **Guard re-freeze for p14.** Treat it as a new freeze of `web_guard.py`, with its sha recorded. Then fix p15.
4. **S1, S2, S3.** Do each in its own source window, each with a fresh review.
5. **Archive moves**, for the 20 retired tests.
6. **Full rerun.** Run the full retained suite plus both gated guards. Confirm 47 red, and that each of them is one of the A, V1, V10 or P tests listed in Appendix A. Compare against the 4776 tests that pass today, with zero new failures.

**Constraints that apply throughout.**
- Editing a frozen file changes its sha. Every existing record that cites the old sha keeps referring to the pre-edit version. Nothing is rewritten retroactively.
- Most affected files are untracked, so CI will not see these fixes unless the user later decides to commit the files together with their sources. Before committing any test, run CI's own command in a clean worktree. That lesson comes from `804658f`/`d03d58c`.
- No skip, no xfail, no deletion, and no source alias.

## Projected outcome

| State | Tests | Made up of |
|---|---|---|
| Green | 180 | B1 20 + V1 24 + V3–V8 19 + V9 37 + V11 8 + T 63 + S 9 |
| Archived | 20 | V2 13 + T 4 + V9 1 + V11 2 |
| Still red, documented | 47 | A 3 + V1 35 + V10 1 + P 8 |

If V11 goes strict instead, the outcome is still 8 green (by the source fix), but 2 more stay red: 180 green, 18 archived, 49 red.

## Signature

| Item | Approve | Alternative | Hold | Note |
|---|---|---|---|---|
| R0 | ☑ | ☐ | ☐ | |
| B1 | ☑ | ☐ | ☐ | |
| V1 | ☑ | ☐ A / ☐ B | ☐ | |
| V2 | ☑ | ☐ | ☐ | |
| V3 | ☑ | ☐ | ☐ | |
| V4 | ☑ | ☐ | ☐ | |
| V5 | ☑ | ☐ | ☐ | |
| V6 | ☑ | ☐ | ☐ | |
| V7 | ☑ | ☐ | ☐ | |
| V8 | ☑ | ☐ | ☐ | |
| V9 | ☑ | ☐ | ☐ | |
| V10 | ☑ keep red | ☐ rewrite | ☐ | |
| V11 | ☑ WAL-aux | ☐ strict | ☐ | |
| T | ☑ | ☐ | ☐ | p16 answer: no — the cap does not cover task-level diagnostics |
| S1 / S2 / S3 | ☑ / ☑ / ☑ | | ☐ | |

## Appendix A — Every failing test, by file

Group IDs: `gw` gateway/claims, `ah` agent/host/CLI, `prc` placement/remote/orchestra/core, `p` portal/share/inbox/lead/web. "Category" is the verified category; "After" is the projected state if every recommendation is approved.


### `tests/workers/test_node_gateway_claim_request_admission.py`

- **gw0** · 20 tests · MISSING_BASELINE · ruling **B1** · after: green  
  Restore the 0073 baseline; no test or source edit.  
  Tests: `test_claim_schema_rejects_redaction_changing_identity_content_free ×3`, `test_authenticated_invalid_claim_is_400_before_hub_session ×3`, `test_ingress_preserves_real_rows_events_offers_and_expiry_before_exact_retry ×12`, `test_independent_readonly_0073_source_control_exhibits_original_raw_identity_commit ×2`
- **gw1** · 8 tests · SUPERSEDED_CONTRACT · ruling **V1** · after: red  
  Keep red. After B1 these fail with the designed 500 (0073 has no admit_response) instead of the setup KeyError.  
  Tests: `test_ordinary_identity_and_positive_public_wire_exact_replay_are_unchanged ×8`

### `tests/workers/test_node_gateway_response_admission.py`

- **gw2** · 11 tests · SUPERSEDED_CONTRACT · ruling **V1** · after: red  
  Keep red (preliminary66 preservation record).  
  Tests: `test_static_response_depth_rejects_before_lazy_dispatch_then_deliverable_depth_replays ×4`, `test_depth_under_redacted_value_is_admitted_without_overrejecting_raw_subtree`, `test_redact_changing_receipt_key_rejected_before_session_without_echo ×2`, `test_exact_items_callback_rolls_back_receipt_but_independent_expire_stays_attributed ×2`, `test_byte_bound_is_reachable_under_original_input_caps_and_rolls_back`, `test_ordinary_real_roundtrip_controls_conflict_and_restart_preserve_full_wire`
- **gw3** · 8 tests · SUPERSEDED_CONTRACT · ruling **V1** · after: red  
  Keep red (looks up the unadopted name `_finalize_envelope`).  
  Tests: `test_pure_finalizer_exact_byte_limit_without_branch_based_http_oracle ×3`, `test_pure_finalizer_fixed_structural_boundary ×4`, `test_pure_finalizer_counter_excludes_dictionary_keys`
- **gw4** · 1 test · SUPERSEDED_CONTRACT · ruling **V1** · after: red  
  Keep red (v2 test asserts the opposite and passes).  
  Tests: `test_missing_named_public_admission_is_dependency500_before_dispatch_real_8302`

### `tests/workers/test_node_gateway_response_deadline.py`

- **gw5** · 6 tests · SUPERSEDED_CONTRACT · ruling **V1** · after: red  
  Keep red; intent is green in test_node_gateway_response_admission_compat.py.  
  Tests: `test_committed_transport_fact_survives_expiry_without_late_400 ×5`, `test_postcommit_revocation_never_sends_late_permission_rejection`

### `tests/workers/test_node_gateway.py`

- **gw6** · 1 test · SUPERSEDED_CONTRACT · ruling **V1** · after: red  
  Keep red; intent is green as compat scenario 1.  
  Tests: `test_internal_errors_have_correlated_sanitized_diagnostics_no_access_logging`
- **gw7** · 1 test · TEST_DEFECT · ruling **R0** · after: green  
  Line 340: read `['applications'][0]['status']`; BOUND exists only at application level.  
  Tests: `test_sync_native_acceptance_atomic_application_cursor_replay_and_concurrency`
- **gw8** · 1 test · TEST_DEFECT · ruling **R0** · after: green  
  Line 473: compare like with like: the receipt minus `tree` against `get()`, or the receipt against `status()`.  
  Tests: `test_full_transport_inputs_upload_tree_receipt_retry_and_restart`
- **gw9** · 1 test · SUPERSEDED_CONTRACT · ruling **V5** · after: green  
  Line 560: expect 400; keep the secret-not-in-state and IN_FLIGHT assertions.  
  Tests: `test_sync_schema_batches_and_secret_redaction_not_fake_native_identity`

### `tests/workers/test_node_claims.py`

- **gw10** · 1 test · SUPERSEDED_CONTRACT · ruling **V4** · after: green  
  Lines 216-222: expect `DispatchBlocked(match='shared spending')` at reserve.  
  Tests: `test_revoked_offer_is_never_claimed`

### `tests/workers/test_node_gateway_lifecycle.py`

- **gw11** · 1 test · TEST_DEFECT · ruling **R0** · after: green  
  Line 67: build the second spec under its own subdirectory (`make_spec` mkdirs unconditionally).  
  Tests: `test_attach_real_listener_applies_to_existing_and_future_sessions_without_spec_mutation`

### `tests/workers/test_node_operator_http.py`

- **gw12** · 1 test · SUPERSEDED_CONTRACT · ruling **V6** · after: green  
  Lines 178-179: drop `placements(ident)` from the 404 list.  
  Tests: `test_unknown_unbound_symlink_paths_and_strict_route_queries`

### `tests/workers/test_node_agent.py`

- **ah0** · 7 tests · TEST_DEFECT · ruling **R0** · after: green  
  Lines 197-203, 441-447: read the tree from public `status(...)['tree']`, as compat7 does.  
  Tests: `test_authenticated_gateway_full_positive_original_request_source_and_namespace`, `test_complete_tree_retains_diagnostics_and_uploads_only_exact_allowlist ×6`
- **ah1** · 9 tests · SUPERSEDED_CONTRACT · ruling **V1** · after: green  
  Give each wrapper `*, admit_response=None` and forward it; 6 of the 9 also need the ah0 read fix. Same pass: the 20 vacuous siblings.  
  Tests: `test_no_work_is_committed_then_next_explicit_call_uses_new_claim_id`, `test_dropped_response_reuses_original_request_events_upload_and_receipt ×4`, `test_quiet_native_has_independent_heartbeat_and_finite_original_timeout`, `test_outbox_events_commit_before_sync_and_sequences_remain_contiguous`, `test_terminal_fact_commits_before_upload_and_fixed_bytes_survive_response_loss`, `test_lease_loss_preserves_confirmed_stored_subset_and_late_original_result`

### `tests/workers/test_node_agent_gateway_error_type.py`

- **ah2** · 6 tests · SUPERSEDED_CONTRACT · ruling **V1** · after: green  
  Same wrapper fix (trace, conflict ×2, fault, expired).  
  Tests: `test_live_upload_io_409_retains_pending_bytes_then_retries_full_manifest`, `test_live_sync_conflict_409_is_explicit_without_freezing_empty_receipt`, `test_unknown_restart_conflict_keeps_outbox_and_never_reserves_again`, `test_heartbeat_conflict_or_schema_is_explicit_not_lease_expiry ×2`, `test_genuine_controller_lease_lost_409_retains_terminal_subset`

### `tests/workers/test_node_agent_review_v1_micro.py`

- **ah3** · 4 tests · SUPERSEDED_CONTRACT · ruling **V1** · after: green  
  Same wrapper fix on the receipt spy (lines 53-59).  
  Tests: `test_canonical_redacted_tree_ack_preserves_raw_native_fact_and_replay ×4`

### `tests/workers/test_node_agent_review_v2_micro.py`

- **ah4** · 5 tests · SUPERSEDED_CONTRACT · ruling **V1** · after: green  
  Same wrapper fix (missing, transient, unavailable, upload_and_expire, sync_after_expiry).  
  Tests: `test_local_404_cooperative_stop_does_not_skip_live_controller_uploads`, `test_transient_heartbeat_retry_after_wall_skew_stays_live`, `test_local_monotonic_failure_budget_stops_but_does_not_make_upstream_late`, `test_only_actual_controller_409_selects_stored_subset ×2`

### `tests/workers/test_node_agent_public_tree_verification.py`

- **ah5** · 13 tests · SUPERSEDED_CONTRACT · ruling **V2** · after: archived  
  Archive byte-identical with its `13 passed at fe5efc13` record.  
  Tests: `test_additional_verification_public_complete_tree_and_terminal_facts ×13`

### `tests/workers/test_node_agent_network_profile.py`

- **ah6** · 1 test · SUPERSEDED_CONTRACT · ruling **A** · after: red  
  Keep red. User decision 2026-10-11 (ledger 238-243).  
  Tests: `test_static_constructor_cli_and_only_duration_change`

### `tests/workers/test_node_host_cli_lifecycle.py`

- **ah7** · 10 tests · SUPERSEDED_CONTRACT · ruling **V7** · after: green  
  ThreadDI: accept any callable target (line 396), and record only the thread named `techlead-node-gateway` (the `_shutdown_owned` helper thread otherwise overwrites `r.thread`). Proven 26/26.  
  Tests: `test_explicit_cli_binds_both_before_start_and_keeps_gateway_until_cooperative_close ×3`, `test_partial_startup_closes_every_acquired_resource_without_shutdown_of_unstarted_thread`, `test_serve_or_browser_failure_is_redacted_nonzero_and_all_owned_resources_close ×2`, `test_cleanup_failure_is_never_exit_zero_or_130_and_other_resources_still_close ×4`

### `tests/workers/test_node_host_admission.py`

- **ah8** · 4 tests · TEST_DEFECT · ruling **R0** · after: archived  
  Archive; test_node_host_admission_stable.py covers the same four scenarios and passes 4/4.  
  Tests: `test_start_after_close_rejects_before_controls_or_process_launch`, `test_prepare_after_close_rejects_before_durable_request_or_process_launch`, `test_retrieved_start_session_released_after_close_has_zero_admission`, `test_retrieved_prepare_session_released_after_close_has_zero_admission`

### `tests/workers/test_node_host_review_boundaries.py`

- **ah9** · 3 tests · HARNESS_OR_ENV · ruling **R0** · after: green  
  Forward `context=` to `Thread.__init__` only when not None (4 sites); it exists only on Python 3.14.  
  Tests: `test_source01_extra_interrupts_keep_real_gateway_during_captured_controller_drain`, `test_source02_blocked_replacement_hook_has_bounded_shutdown_and_explicit_remaining_resources`, `test_source05_interrupt_status_emit_failure_keeps_all_real_cleanup_diagnostics`
- **ah10** · 1 test · TEST_DEFECT · ruling **R0** · after: green  
  Same portability fix plus a type-only check at lines 1089-1090 (the literal message is never produced by stdlib selectors). Whole file then 10/10 on 3.12.  
  Tests: `test_source04_real_pre_started_window_is_bounded_and_late_loop_error_is_owned_diagnostic`

### `tests/workers/test_node_cli.py`

- **ah11** · 3 tests · TEST_DEFECT · ruling **R0** · after: green  
  Line 413: interpolate `{guard.name!r}`; the escaped `{{…}}` writes `guard.name` literally into the child, where `guard` is undefined.  
  Tests: `test_actual_module_help_is_local_and_has_no_agent_side_effect`, `test_actual_module_default_no_work_gateway_private_paths_and_retained_state`, `test_persisted_unknown_replay_zero_native_one_readback_no_idle_respawn`

### `tests/research_os/test_benchmark.py`

- **prc0** · 1 test · POLICY_CONFLICT · ruling **P** · after: red  
  Keep red under the retained runner; green in CI.  
  Tests: `test_audit_and_report_tampering_detected`

### `tests/research_os/test_portfolio.py`

- **prc1** · 1 test · POLICY_CONFLICT · ruling **P** · after: red  
  Same.  
  Tests: `test_removed_evidence_artifact_blocks_consumers`

### `tests/test_autonomy_store.py`

- **prc2** · 1 test · POLICY_CONFLICT · ruling **P** · after: red  
  Same (deletion is in source `migrate_legacy`).  
  Tests: `test_one_schema_rejects_legacy_database`

### `tests/test_cli.py`

- **prc3** · 1 test · POLICY_CONFLICT · ruling **P** · after: red  
  Same (deletion is in source `evals.py`).  
  Tests: `test_cli_init_goal_eval`

### `tests/test_release_integration.py`

- **prc4** · 1 test · POLICY_CONFLICT · ruling **P** · after: red  
  Same (updater `_remove_path`).  
  Tests: `test_updater_cannot_destroy_activated_release_on_identity_conflict`

### `tests/test_updater.py`

- **prc5** · 2 tests · POLICY_CONFLICT · ruling **P** · after: red  
  Same (updater).  
  Tests: `test_rollback`, `test_verified_apply`

### `tests/test_updater_hardening.py`

- **prc6** · 1 test · POLICY_CONFLICT · ruling **P** · after: red  
  Same (updater).  
  Tests: `test_engine_and_skill_share_one_atomic_current_switch`

### `tests/workers/test_node_placement_readback.py`

- **prc7** · 2 tests · TEST_DEFECT · ruling **R0** · after: green  
  Lines 157, 225: give the `later` revision tasks for both required checks a and b.  
  Tests: `test_all_immutable_plan_records_not_only_latest_or_continuations_or_orphan_pins`, `test_tasks_and_pins_share_snapshot_while_writer_commits_new_pin_and_plan`

### `tests/workers/test_node_placement_preparation_http.py`

- **prc8** · 1 test · TEST_DEFECT · ruling **R0** · after: green  
  Line 250: compare the receipt's own status (or expect RECEIPTED for a known receipt); the canonical run status is UNKNOWN/RECEIPTED, with the native status in the receipt.  
  Tests: `test_native_unknown_or_error_replays_including_restart_without_resend`

### `tests/workers/test_node_placement_readback_sideeffects.py`

- **prc9** · 7 tests · OPEN_SOURCE_BUG · ruling **S1** · after: green  
  Source fix: warm path must not open read-write or run `PRAGMA journal_mode=WAL` before the identity fence.  
  Tests: `test_get_preopen_race_has_no_database_or_header_write_authority ×3`, `test_real_wal_substitution_get_has_zero_tree_effects ×4`
- **prc10** · 8 tests · POLICY_CONFLICT · ruling **V11** · after: green  
  WAL-aux: allow a change to `-shm` only (plus its directory entry). Strict: source fix, fence `approved_spec` before its SELECT.  
  Tests: `test_real_wal_substitution_get_has_zero_tree_effects ×8`
- **prc11** · 2 tests · POLICY_CONFLICT · ruling **V11** · after: archived  
  WAL-aux: archive (they measure SQLite itself). Strict: keep red as an unmet requirement no SQLite reader meets.  
  Tests: `test_actual_uri_ro_live_wal_zero_full_tree_candidate ×2`
- **prc12** · 1 test · OPEN_SOURCE_BUG · ruling **S2** · after: green  
  Source fix: cold-path open errors map to the identity PermissionError (403), not 500.  
  Tests: `test_get_preopen_race_has_no_database_or_header_write_authority`
- **prc13** · 3 tests · TEST_DEFECT · ruling **R0** · after: green  
  `real_swap` must move `-wal`/`-shm` with the main DB (as `wal_swap` does), or compare against the at-swap snapshot.  
  Tests: `test_get_preopen_race_has_no_database_or_header_write_authority`, `test_actual_same_database_uri_ro_primitive_has_no_create_or_header_mutation ×2`
- **prc14** · 1 test · TEST_DEFECT · ruling **R0** · after: green  
  Same oracle fix; then needs S2 to go green.  
  Tests: `test_get_preopen_race_has_no_database_or_header_write_authority`

### `tests/workers/test_remote_artifacts.py`

- **prc15** · 2 tests · SUPERSEDED_CONTRACT · ruling **A** · after: red  
  Keep red. User confirmed IO v2 and keeping the old tests (ARTIFACT-IO-V2 contract lines 3-4).  
  Tests: `test_real_deletion_uses_exact_trash_argv_and_is_recoverable`, `test_failed_trash_explicitly_retains_candidate_before_and_originals`

### `tests/workers/test_remote_artifact_io_v2.py`

- **prc16** · 1 test · TEST_DEFECT · ruling **R0** · after: green  
  Line 54: `env[3]` → `env[5]`.  
  Tests: `test_v2_real_deletion_uses_exact_staging_trash_argv_and_is_recoverable`

### `tests/workers/test_orchestra_remote_pipeline.py`

- **prc17** · 1 test · SUPERSEDED_CONTRACT · ruling **V8** · after: green  
  Call `hub.attach_node_gateway(...)` in this test's setup, not in `Pipeline.__init__` (would double-attach in test_orchestra_delivery_context).  
  Tests: `test_real_coupled_public_pipeline_materializes_bytes_and_keeps_context_not_acceptance`
- **prc18** · 2 tests · TEST_DEFECT · ruling **R0** · after: green  
  Lines 464, 523: assert an UNKNOWN diagnostic with no `candidate`, not `is None`.  
  Tests: `test_interrupted_protocol_driver_unknown_restart_syncs_original_outbox_no_candidate`, `test_real_expired_controller_lease_keeps_original_stored_subset_and_known_native_terminal`

### `tests/workers/test_orchestra_delivery_context.py`

- **prc19** · 1 test · TEST_DEFECT · ruling **R0** · after: green  
  Line 98: compare only the first line of the message (pytest rewrites the imported helper's assertion text).  
  Tests: `test_original_supplement_reports_readiness_rebind_before_any_reservation`

### `tests/workers/test_portal_gateway.py`

- **p0** · 16 tests · SUPERSEDED_CONTRACT · ruling **V9** · after: green  
  Fixture `approval_hash` = `protocol.digest({source, spec, proposal})`, as test_portal_review_v6 does.  
  Tests: `test_chat_directives_rejected_before_side_effect ×2`, `test_actual_binding_drift_blocks_mutations ×3`, `test_spec_sha_drift_blocks_mutation`, `test_planning_literal_permission_required ×4`, `test_start_requires_ack_separate_permission_and_matching_hash`, `test_nodes_allowlist_public_rows_not_namespace_or_secret`, `test_busy_rejects_without_upstream`, `test_single_capture_hash_and_inbox_receipt`, `test_creation_audited_no_cross_route_request_id_reuse`, `test_redaction_removes_nested_prompt_output_raw_and_credentials`
- **p1** · 3 tests · SUPERSEDED_CONTRACT · ruling **V9** · after: green  
  Digest fixture, and inject the failure on the mutating POST only (a pre-send GET failure is a known 409 by design).  
  Tests: `test_mutation_unknown_persisted_no_resend`, `test_unknown_blocks_new_request_not_just_same_id`, `test_unknown_readback_receipt_visible_after_new_login`
- **p2** · 1 test · SUPERSEDED_CONTRACT · ruling **V9** · after: green  
  Digest fixture, and add `kind: 'remote'` to the DI placement receipt (the real Console always sends it).  
  Tests: `test_actual_console_placements_wire_shape_and_allowlist`
- **p3** · 2 tests · SUPERSEDED_CONTRACT · ruling **V9** · after: green  
  Digest fixture; allow one readonly GET on replay; establish the mission mapping by an explicit mutation before asserting 409.  
  Tests: `test_create_before_context_once_and_projection`, `test_mission_mapping_drift_readback_never_controls_other_mission`

### `tests/workers/test_portal_review_v6.py`

- **p4** · 9 tests · TEST_DEFECT · ruling **R0** · after: green  
  Lines 83, 94, 125, 153: assert `['error']['code']`; the `*_wire_v2` copies already do and pass.  
  Tests: `test_presend_spec_reader_error_409_not_store_failure_retryable ×4`, `test_invalid_pinned_source_presend_known_no_post`, `test_actual_old_bound_new_display_pin_pending_and_mutation_rejected ×2`, `test_no_proposal_cannot_prepare_or_start_even_with_fake_readiness ×2`

### `tests/workers/test_portal_review_v5.py`

- **p5** · 14 tests · SUPERSEDED_CONTRACT · ruling **V9** · after: green  
  Digest fixture (imports `HASH = 'c'*64` from test_portal_gateway).  
  Tests: `test_post_success_then_local_409_is_unknown_on_wire_and_fenced ×6`, `test_presend_chat_read_failure_known_no_post_and_same_id_retryable ×3`, `test_actual_upstream_4xx_is_known_rejection_not_unknown`, `test_post_timeout_is_unknown_exact_replay_get_only`, `test_post_success_then_audit_write_failure_is_unknown`, `test_placement_post_projects_receipt_not_inventory_or_node_namespace`, `test_actual_private_store_unknown_persisted_and_message_not_stored`
- **p6** · 1 test · SUPERSEDED_CONTRACT · ruling **V9** · after: archived  
  Archive; test_portal_review_v6.py:166 is its exact current-contract replacement and passes.  
  Tests: `test_adoption_exact_actual_public_approval_envelope_binds_readonly`

### `tests/workers/test_portal_console_integration.py`

- **p7** · 1 test · SUPERSEDED_CONTRACT · ruling **V9** · after: green  
  Line 34: expect CREATED / spec PENDING (the real Driver returns no proposal).  
  Tests: `test_real_console_create_context_message_and_adoption`

### `tests/workers/test_mission_inbox_review_dispatch.py`

- **p8** · 5 tests · SUPERSEDED_CONTRACT · ruling **V3** · after: green  
  Line 71: expect NOT_APPLIED after the terminal receipt (or assert BOUND before it).  
  Tests: `test_ordinary_and_legacy_default_purpose_calls_still_receive_context ×5`

### `tests/workers/test_mission_inbox_terminal_review.py`

- **p9** · 1 test · TEST_DEFECT · ruling **R0** · after: green  
  Line 313: `e['type']`, the public field since c853aef.  
  Tests: `test_reader_report_store_only_transaction_facade_records_events`

### `tests/workers/test_lead_journal_record_in.py`

- **p10** · 1 test · TEST_DEFECT · ruling **R0** · after: green  
  Line 48: `sql.lstrip().startswith(...)`; the events INSERT starts with a newline.  
  Tests: `test_sql_failure_preserves_exception_and_rolls_back_hash_chain`

### `tests/workers/test_share_cli.py`

- **p11** · 2 tests · TEST_DEFECT · ruling **R0** · after: green  
  Line 106: `def fail(*_)`; the source calls `pause(0.2)`.  
  Tests: `test_all_failure_boundaries_explicit_and_only_owned_close ×2`

### `tests/workers/test_share_gateway.py`

- **p12** · 1 test · SUPERSEDED_CONTRACT · ruling **V10** · after: red  
  Keep red (exact-signature lock; the password contract says "not edited to green").  
  Tests: `test_frozen_share_gateway_public_api_availability`

### `tests/workers/test_share_runtime.py`

- **p13** · 1 test · TEST_DEFECT · ruling **R0** · after: green  
  Fixture upstream: JSON Content-Type, `controls` as a list, sidecar-v1 `engineering_result`.  
  Tests: `test_real_gateway_local_only_one_upstream_capture_and_original_survives`

### `tests/workers/test_lead_engineering_result_web.py`

- **p14** · 8 tests · HARNESS_OR_ENV · ruling **R0** · after: green  
  Fix the web guard: allow `gethostbyaddr('127.0.0.1')` during an armed bind, as the share guard does. The guard is sha-pinned, so this is a new freeze.  
  Tests: `test_w05_capture_errors_internal_failure_and_base_exception ×4`, `test_w06_real_sidecar_secrecy_predicate_not_full_wrapper ×3`, `test_w12_bounded_text_only_security_and_wire_csp`
- **p15** · 12 tests · TEST_DEFECT · ruling **R0** · after: green  
  Guard fix, plus reset `snapshot_calls` after `hub.create()` in `http_fixture`.  
  Tests: `test_w01_default_exact_four_no_projection_or_import`, `test_w02_opted_once_exact_capture_pointer_root`, `test_w03_header_security_query_admission_and_other_route ×8`, `test_w04_genuine_public_typed_rejection ×2`
- **p16** · 1 test · TEST_DEFECT · ruling **R0** · after: green  
  Needs a contract answer first: does the web `diagnostics50` cap cover task-level diagnostics? Recommended: make the fixture produce >50 non-task diagnostics.  
  Tests: `test_w12_bounded_text_only_security_and_wire_csp`

### `tests/workers/test_share_gateway_http.py`

- **p17** · 1 test · OPEN_SOURCE_BUG · ruling **S3** · after: green  
  Source fix: set `ShareGateway.request_queue_size` ≥ 64 (the stdlib backlog of 5 resets a 16-client burst).  
  Tests: `test_at_most_16_admitted_requests_with_real_blocked_console`
