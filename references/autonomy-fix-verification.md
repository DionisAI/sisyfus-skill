# Autonomy runtime repair verification

This note records the correctness repair applied to the v0.8 autonomy branch after the first full-branch review.

## Canonical runtime

The package now has one public autonomy API and one SQLite schema owner. The competing split and monolithic implementations were replaced by the modules below:

- `models.py`
- `policy.py`
- `store.py`
- `runtime.py`
- `supervisor.py`
- `adapters.py`
- `discovery.py`
- `cli.py`

The default database remains `.sisyfus/autonomy.sqlite3`. The store uses an explicit schema version and rejects an incompatible legacy layout unless migration is requested.

## Repaired invariants

- Every mutation is fenced by continuation version, opaque lease token, and unexpired lease time.
- Long planner, capability, and verifier calls renew the lease; lease loss prevents stale settlement.
- Heartbeats renew at one-sixth of the lease interval, renew synchronously at execution and verification boundaries, and use monotonic elapsed time when tests inject a deterministic starting timestamp.
- High-frequency heartbeat renewals update authoritative lease columns without flooding the immutable event stream; explicit renewals remain auditable.
- A PASS on the final execution attempt can still complete through a non-attempt-consuming FINISH decision.
- A final INCONCLUSIVE result becomes mechanically terminal rather than remaining unclaimable in WAITING.
- Experience counts change only for a newly inserted `(experience, evidence, outcome)` observation; replaying one evidence item cannot promote a lesson.
- RESERVED and EXECUTED decisions resume after worker failure without asking the planner to invent a replacement decision.
- An unresolved non-replay-safe external action becomes `UNKNOWN_COMMIT`/BLOCKED rather than being repeated blindly.
- Planner subprocess output is captured with streaming byte limits and process-group termination.
- Planner environment variables are allowlisted rather than inherited wholesale.
- Inbox failures are isolated per file; malformed and oversized files are quarantined while valid files continue.
- Discovery applies admission policy before persistence and consumes sensor iterables with a hard bound.
- Continuous operation requires explicit acknowledgement when the planner is not OS-sandboxed.

## Validation

The canonical-runtime repair was tested in clean GitHub Actions checkouts. The final heartbeat repair commit is:

```text
4a6075180aa22a67396fc5072efe9b9f66a742ee
```

Its validation job completed all of the following successfully on Python 3.12:

```text
editable installation             PASS
compileall                         PASS
heartbeat race repetition 1/5      PASS
heartbeat race repetition 2/5      PASS
heartbeat race repetition 3/5      PASS
heartbeat race repetition 4/5      PASS
heartbeat race repetition 5/5      PASS
complete repository suite          132 passed in 13.07s
```

Dedicated autonomy tests cover public imports and CLI startup, schema detection and migration, concurrent claims, final-attempt behavior, duplicate-evidence resistance, lease expiry and heartbeat fencing, crash recovery boundaries, idempotency and unknown-commit handling, planner output limits, and inbox quarantine.

This documentation commit triggers the normal CI workflow against the actual repaired tree on Python 3.11, 3.12, and 3.13. The pull request must remain draft until that matrix is green.

## Remaining boundary

The runtime now fences and limits a command planner, but a real unattended deployment should still execute model providers and side-effecting capabilities inside a container, restricted service account, or microVM with network and secret scopes. This is an operational isolation requirement, not a substitute for the runtime's verifier and transaction boundaries.
