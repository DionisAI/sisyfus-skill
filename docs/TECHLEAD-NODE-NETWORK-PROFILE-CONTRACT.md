# Node operator network profile — schema 2

Status: implementation candidate; independent native Opus read-only audit and
fresh second-host acceptance are separate pending gates. Protocol fake evidence
is neither model attestation nor mission acceptance.

## Frozen contract

The constructor remains `NodeAgent(credential_file, state_directory, *, driver=None)`.
CLI flags, signatures, exits and help stay unchanged. Schema 1 retains exactly
`schema`, `controller_mission_id`, `node_id`, `secret`, `gateway_url`,
`gateway_host`; its persisted identity bytes and heartbeat default 0.4s remain
unchanged.

Schema 2 requires exactly those six fields plus `heartbeat_timeout_seconds`.
`schema` must be integer 2, and the budget must be an int or float, excluding
bool, finite and in the inclusive range **0.4..1.0 seconds**. Missing/extra
fields and invalid numbers fail through existing redacted credential errors.
Ownership, 0600 credential mode, protected state and path/host rules remain.

Identity is compact sorted JSON of every field except secret, including schema
and the exact parsed numeric representation: `1` and `1.0` differ. Secret-only
changes keep the existing identity behavior. A changed schema/budget/number
representation on an existing state fails closed; no migration is performed.

Only heartbeat's duration selection changes. The selected value still drives
the same HTTPConnection timeout, monotonic aggregate deadline and watchdog.
Claim, inputs, sync, status, uploads and receipt retain 2s. Slow-drip responses
are still aggregate-bounded. Retry/lost window 2s, join(2), cadence 0.1s,
watchdog join(0.1), DB bounds, driver, response validation, node/core authority,
leases, IN_FLIGHT and UNKNOWN fencing remain unchanged.

## Operator procedure and evidence limits

Create a new operator-owned credential exclusively (O_CREAT|O_EXCL, 0600),
outside state/workspaces, and choose a fresh empty protected state directory
for a fresh operator-controlled mission/session. Keep the original real
UNKNOWN mission quarantined; preserve its original credential, attempts and
evidence. Do not replay that mission to test this profile.

Original fixed-input readback plus committed initial heartbeat before absent
IN_FLIGHT strongly supports an initial heartbeat ACK/deadline inference.
The later UNKNOWN status/LeaseLost read timings are not active heartbeat
latency measurements. The 0.6s local response-delay fixture proves opt-in
behavior, not a WAN timing root cause or adequacy of 1.0s on a real route.

The native Opus REVISE decision caps the budget at 1.0s rather than 1.5s for
unchanged join/retry/DB margin. Worst-case simultaneous DB contention remains
a separate edge verification gate even with a passing uncontended stop/join.

## Frozen checks and release boundaries

New tests use real NodeAgent, MissionHub/LeadMission, NodeClaims and public
NodeGateway HTTP with fresh synthetic credentials and explicit protocol fake
(actual native/provider calls zero). They check v1 identity/CLI, v2 validation
and representation drift, delayed initial heartbeat pre-spawn boundaries,
slow-drip aggregate deadlines, all six non-heartbeat budgets, public authority
loss and response rejection, crash reservation quarantine and stop/join/retry.
Existing tests/oracles are hashed before implementation and remain read-only.
Keep every failed run and distinguish pre-existing fixture-contract differences
from this profile candidate. Tests are frozen before observing outcomes.

Production write set: only NodeAgent.__init__ credential parsing and the
single `_call` duration line. No acceptance/review promotion, old oracle
adjustment, native invocation, SSH or external transport verification here.
After bounded validation, pin source SHA and stop writes for a fresh explicit
claude-opus-5-5 independent read-only audit. Real second-host heartbeat latency,
one fresh native task, receipt and canonical reconciliation remain pending.
