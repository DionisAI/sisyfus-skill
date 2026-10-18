# Node host admission — independent stable-accounting TEST-ONLY contract

Main release-v4 selects a separate NEW4 measurement, not a revision of observed
admission4. Requested author `gpt-6.1-sol`; actual runtime attestation separate.
Original admission4 c80aad/doc736601 and its helper-oracle failures, NEW26, entry9,
old15 and every outcome remain byte-stable. Source remains HOLD, no source/model
design approval or native review, N6 two-process/A7/A8/device acceptance.

## Real source and immutable measurement scope

`MissionHub.start(ident, *, allow_local_workers=False, max_cycles=None)` delegates
to real control; `prepare_placement(ident, request_id, *, allow_planning=False)`
admits the real synchronous core request then Hub thread. Explicit fixture
permission True and max_cycles1/request identity are supplied. Current source
lookup is at lead_console.py442/373, with admission in the subsequent session
lock; close507–514 captures active sessions under the Hub lock, then Stop/join.
`LeadMission._request_placement_preparation` uses the canonical core locks/store.
No invented backend fields, receipt aliases, replacement admission method or
control return shape. Operator ACK remains acceptance, never completion truth.

Hub snapshot is exactly `{id,snapshot,controller,controls}`, core snapshot direct.
LeadJournal.counters136–145 recomputes wall_minutes from datetime.now(timezone.utc)
and persisted creation time. This live accounting is not durable mission change.
Neither production clocks nor raw snapshots are changed, frozen or overwritten.

## Exact one-leaf accounting separation

Preserve both actual raw Hub and core snapshots and every later raw readback.
Stable comparison deep-copies only its local measured data and excludes exactly
`core_snapshot.counters.wall_minutes` (within wrapper calibration, the same core
snapshot leaf). No other key, value, counter, nested field, default, ordering or
type is filtered/normalized. This is not a public alias or a changed core return.

Each wall sample must be int/float but not bool, finite and nonnegative. Sequential
observations preserve raw value, label and monotonic observation time. Wall and
observation times must be nondecreasing. Hub-to-core calibration includes actual
10ms elapsed sleep and positive elapsed monotonic measurement; no clock DI/freeze.
All remaining snapshot fields compare exactly.

Full real SQLite iterdump text plus logical SHA, raw journal state, complete
events projection (bounded1000 with explicit completeness assertion), controls,
native runs, full immutable spec/hash, original source file hashes and raw main
DB bytes/hash remain exact. SQL access is readonly and scoped to the actual
retained fixture store. Save raw before/after DB byte copies, not a synthetic DB
snapshot. Idle close must preserve all these facts and stop_event/stoppedFalse;
durably Stopping idle missions is never accepted as revoked host admission.

## Four unchanged lifecycle obligations

1. After completed idle close, explicit Start rejects as closed before controls,
   process construction/start, native admission or target entry.
2. After completed idle close, preparation rejects before the real synchronous
   durable request/save, control record/ACK, process or native target entry.
3. In the actual Start/control caller, after original `_session` returned and
   assigned the real session local, pause before final admission. Close observes
   idle and returns. Release caller only afterwards: explicit rejection and zero
   late writes/dispatch are required.
4. The identical real post-lookup interleaving for preparation. Preserve existing
   cached settlement/readback semantics; no forced Stop/native receipt invention.

Closed rejection is RuntimeError/PermissionError with close/closing explanation,
not a successful ACK or durable-Stop substitute. Method-entry observation plus
real SQL/events/controls and dispatch-attempt records expose actual violations.
All result evidence is saved before the aggregate assertion and retained on fail.
No assertion beyond the actual stopping point is credited.

## Clearly bounded fixture boundaries

Real Hub/LeadMission with existing immutable make_spec input helper; no old test
function called or edited. Original check code is input only, never executed.
Process-boundary DI replaces only the Hub module's existing Thread reference.
Its stdlib-compatible group/target/name/args/kwargs/kwonly daemon/context records
construction/start/join attempts, never invokes target; is_aliveFalse is truthful
for this interception, not an actual process/native completion claim. Scheduling
uses separate actual Python threads/Events, not model/provider worker processes.

Scoped source-line tracing in the measured caller uses only exact public Hub
control/preparation code and the already-assigned real session local. It pauses
after lookup actually returned, before the subsequent admission statement; no
session or result replacement, global frame scan, saved frame/locals or production
flag. Call profiling observes real control/request/save/native methods unchanged.
Restore prior profile/trace settings after that one public call.

Lookups/close waits at most1s, release3s, scheduling joins2s; parent outcome120s.
Original native target/provider/profile/login/check/eval/SSH/remote/deploy/private
mission/credential/WAL6/deletion all remain outside scope. No listener is needed.
Actual cached transport/drain and lock-free readiness obligations stay frozen in
the independent existing contracts, not weakened or newly credited here.

Statically verify public signatures, exact counter/source paths and metadata
projection before new test/doc SHAfreeze; then sole retained guard-on outcome.
Deletion/external-network/process/DB-root guard starts before setup. No aliases,
skip/xfail, post-outcome test/doc/source edit or rerun. Original4 never becomes
GREEN by this separate result. Finish physical readback/handoff and STOPWRITE.
