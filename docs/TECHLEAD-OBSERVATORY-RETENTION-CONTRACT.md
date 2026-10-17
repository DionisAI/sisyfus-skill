# Observatory live-state retention contract v1

Status: frozen standalone acceptance before retained RED; source authoring is
released only after valid RED. Candidate GREEN does not establish real Trash,
independent review, integration, or formal delivery acceptance.

## Authority and scope

Design: `artifacts/techlead/orchestra-20261008/full-delivery-b9e7b9660c534c98bfaaba7f7fede382/observatory-retention-design-v1/DESIGN.json`.
Its native receipt is COMPLETED, requested and actual `claude-opus-5-5`.
The operator's release corrects the proposed fake's `os.renames` to `os.rename`
into an already-existing owned directory, corrects the new test filename, and
requires fixed diagnostics with no raw subprocess stderr/state body.

Owned source: `src/sisyfus/research_v2/live.py`:
only `clear_live_state`, necessary standard-library imports, `_TRASH_BIN`,
`LiveStateRetained`, and minimal private helpers. The public signature and None
return remain. Writers, readers, callers, old tests, node agents, portal code,
global policy/runner, and unrelated cleanup remain unchanged.

NEW frozen tests: `tests/test_observatory_live_retention.py`.
Artifacts are retained under `artifacts/techlead/orchestra-20261008/full-delivery-b9e7b9660c534c98bfaaba7f7fede382/observatory-retention-sol`.

## Clear lifecycle

1. Require directory-relative open/mkdir/rename/stat support. Resolve the root,
   open and pin it with no-follow directory flags, compare root pathname identity.
   Open `.sisyfus` relative to it; reject parent aliases/foreign ownership.
2. Open only `observatory.json` no-follow/nonblocking, require a regular owned
   file with one link and at most 64 KiB. Parse bounded bytes as a dict with a
   truthy port, exactly resolved root, and integer non-bool PID. Invalid present
   state raises; reader `None` is not clear permission. A valid foreign PID or
   missing root/parent/state is a normal no-op.
3. Require an absolute executable Trash binary before staging. Check file identity
   `(device, inode, size, mtime_ns)` against the admitted pin before rename.
4. Exclusively create unpredictable `.observatory-retire-<pid>-<hex>` at mode
   0700, owned and same-device. Pin it. Rename the state relative to pinned source
   and stage descriptors. Never touch the canonical name after this operation.
5. Verify staged metadata, single-link shape, and exact admitted bytes through a
   new no-follow descriptor. A mismatch is retained, reported, and never trashed
   or restored. Recheck parent/stage path identities just before external exec.
6. Invoke `[_TRASH_BIN, absolute_stage_directory]` with stdin DEVNULL,
   capture_output=True, check=False, timeout=30, no shell and no `--`.
   Success requires exit zero AND disappearance of that stage name relative to
   the pinned parent. Zero without a move is failure. Close every opened descriptor
   on all outcomes. No unlink/remove/rmdir/rmtree/implicit parent cleanup.

## Diagnostics and retention

`LiveStateRetained(RuntimeError)` exposes `reason`, `path: Path`, and
`detail = {"type": fixed_label, "returncode": int_or_none}`. Diagnostics contain
only fixed reasons, fixed error-type labels, return codes and the retained path;
no raw stderr, arbitrary state body, exception arguments, or command output.
Internal translated exceptions suppress their raw traceback context.

Pre-move reasons: `no_dir_fd`, `root_alias`, `parent_alias`, `state_symlink`,
`state_unadmitted`, `trash_missing`, `state_changed`, `stage_failed`.
`stage_failed` explicitly reports exclusive creation/open/rename failure; any
empty created stage remains and canonical state is retained when rename failed.
Post-move reasons: `staged_mismatch`, `trash_failed`; retain stage and never roll
back over a concurrent publication. `.path` identifies canonical state before
move and the stage directory after move. Parent-path retargeting may leave the
stage under the moved pinned parent rather than the originally named path;
diagnostics name the intended stage and retained artifacts support diagnosis.
Fixed type labels include `Validation`, `OSError`, `InvalidState`, `TrashResult`,
and `TimeoutExpired`. `TrashResult` exposes the observed returncode, including
zero/no-move. OS and timeout errors expose None as returncode.

## Races: detection and retention, not prevention

A publication between precheck and rename can be displaced into the stage.
Post-rename identity/byte mismatch detects it and leaves it recoverable; no
promise is made that a newer canonical state is never displaced. A publication
after rename survives because canonical state is never subsequently touched.
Do not automatically restore a stage or Trash a mismatching object.

Cooperating writers publish via same-directory temp-file plus `os.replace`,
never mutate in place, hardlink state, or touch retirement directories. Root
resolution normalizes initial aliases; intermediate components are not pinned
individually. Post-open identity checks detect only observable mismatches.
Path-based Trash has a residual same-UID hostile race after recheck; it is not
eliminated by pinned descriptors. This contract adds no writer lock/prevention.

## Read-only caller/writer evidence and test gates

The actual `src/sisyfus/cli.py`
shutdown finally blocks call clear with `pid=os.getpid()` and do not swallow
retention errors. `cmd_research_serve` propagates; outer `main` catches RuntimeError
and reports an error with exit 1 (or rethrows with SISYFUS_DEBUG). Tests assert
that observed behavior rather than the design's earlier unverified main-raises
assumption. No missing `research_v2/cli.py` is created.

Read-only `src/sisyfus/research_v2/workspace.py`
confirms same-directory temporary publication plus `os.replace`. Its existing
missing-temporary cleanup call stays out of scope; new fixtures seed manifests
directly and model atomic publication without invoking that cleanup.

Freeze tests and this contract hashes BEFORE RED against unchanged source.
Valid RED is a behavioral regression/missing implementation, not collection or
setup failure. Retain failures and fixtures. Only then author source; compile and
pin source BEFORE GREEN using identical frozen test/contract hashes. A scoped
executable fake moves the whole stage with `os.rename` into its existing fixture
sink. Deletion tripwires and retained runner remain active; fake subprocesses
are scoped and log exact argv and device/inode/hash evidence.

Acceptance includes scoped/unscoped clear, absence, foreign PID, invalid JSON and
bindings, oversized/nonregular/aliased resources, missing Trash/dir-fd support,
nonzero/no-move/timeout/exec failures, deterministic pre/post-rename races,
path retargeting, immutable unrelated resources, descriptor closure, CLI error
propagation, and exact byte/identity/argv/resource bounds.

The original retained baseline remains separate: 338 passed, 2 failed due to
permanent clear removal. Immutable old tests with real Trash and platform audit
are Main-owned gates after fresh narrow approval; this sidecar invokes no real
Trash, DB, native provider, SSH, CF, credentials, or evaluation work. Stop source
on stable HOLD for a fresh independent Opus review; integration is separate.
