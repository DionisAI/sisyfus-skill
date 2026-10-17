# Node host close admission — supplemental frozen TEST-ONLY contract

Release: `artifacts/techlead/orchestra-20261006/node-host-admission-test-only-release-v2.json`.
Requested author is `gpt-6.1-sol`; runtime attestation is separate. This standalone
four-case measurement is additional to original15 and NEW26, not their replacement,
source admission, native review, N6 two-process acceptance, A7/A8 or integration.
The source finding is static inference until an actual retained outcome.

## Actual public interfaces and source observations

- `MissionHub(directory, *, single=False, mission_factory=None)` with real core
  binding via `create(spec, *, directory=None)`, returning `id` and existing
  `{id,snapshot,controller,controls}` snapshot wrapper. `LeadMission.snapshot()`
  is direct; no new backend field or top-level phase alias is stipulated.
- `start(ident, *, allow_local_workers=False, max_cycles=None)` forwards to real
  `control(ident, 'start', ...)`. Explicit permission True and max_cycles1 are
  supplied for the isolated fixture, not a user mission or a worker release.
- `prepare_placement(ident, request_id, *, allow_planning=False)` receives True
  and one fixed valid fixture identity. Original control ACK is acceptance only.
- `close()` requests Stop and joins only already-active sessions. Current source
  `lead_console.py:373,390–423,442–476,507–514` retrieves a session, then admits
  under session.lock, separately from close's Hub-lock active-session capture.
  `lead_mission.py:1034–1081` synchronously saves REQUESTED before thread launch.
  These are current-source facts, not a fabricated API, DB or outcome.

## Exact four measurement cases

1. After idle Hub.close has returned, explicit Start rejects as closed before
   control method entry/write or process/native dispatch attempt.
2. After idle close, explicit preparation rejects before entry into the real
   `_request_placement_preparation` durable admission, controls or dispatch.
3. Start completes its original real session lookup; a barrier pauses its return.
   Close observes the idle session and returns; only then release caller. Closed
   rejection and zero late control/admission/dispatch are required.
4. The same deterministic interleaving for preparation requires no late REQUESTED,
   control or dispatch. No sleeps or randomized scheduling stand in for ordering.

Idle close preserves core snapshot, acceptance/spec, source bytes, native run
reservations, events/hash-chain projection, complete logical DB content and raw
DB bytes. It never durably Stops all idle missions as a mask for revoked admission.
Rejection is an explicit RuntimeError/PermissionError with close/closing diagnostic,
not an ACK, successful result or a Stop-based substitute. Existing permission,
role, acceptance and uncertain-native fences are unchanged.

## Fixture and DI boundaries

Real MissionHub and real LeadMission use an isolated, bound retained fixture store.
The unchanged original `make_spec` helper constructs fixed source/check inputs;
no old test function or check command is run. Inputs and pre-call core projection,
original source hashes, controls, events, SQL logical hash and raw store bytes
are saved before each call. Read-only SQLite access is confined to that exact
retained fixture root; repository/user databases stay outside this measurement.

Only the Hub module's standard Thread reference uses process-boundary DI. Its
constructor matches retained Python's group/target/name/args/kwargs plus kwonly
daemon/context. It records construction/start attempts without executing the
target. `is_alive=False` reflects that no target has executed; this is not a
native spawn, receipt or process-completion claim. Actual Python threads and
Events supply bounded scheduling barriers. They are not worker threads.

Race DI forwards the original `_session(ident)` result unchanged, then delays
only the measured caller after retrieval. It adds no session, public result,
closed flag, response alias or production capability. Scoped Python call profiling
observes real `_record`, `_ack`, preparation admission/save, run and planning
entry; it neither replaces those methods nor changes their arguments/results.
The actual admission/controls code continues into the real bound store if faulty;
only the native/process boundary is intercepted.

Events establish lookup < completed idle close < barrier release < lookup return.
Barrier waits are at most3s; join waits at most2s. All post-call observations are
retained before the single aggregate assertion. Failures show exact stopping
points; zero native counts under DI never imply real provider validation.

## Preserved surrounding obligations and evidence

Remote listeners must remain serving while active controllers drain, and readiness
inside native write transactions remains lock-free and DB/file/network-free.
These existing NEW26 obligations stay frozen: this four-case supplement neither
replaces nor credits their unreached assertions, and opens no listener itself.
Listener capability, node-online/model login, native terminal status, deterministic
check, independent review and integration remain separate facts.

Freeze test/doc and exact source/helper/input-code pins before the only bounded
guard-on retained outcome. Preserve original26/15, their failures, prior static
errors and evidence. No post-outcome test/doc/source edits, aliases, skip or xfail.
Keep deletion/external-network/process/DB-scope guard active before setup. No
native/provider/profile/login/SSH/deploy/real private mission/eval/WAL6/cleanup
or additional test selections. Final file-only readback and independent handoff
end this slice; production remains HOLD pending a separate source release.
