# Node host loop-entry — independent frozen TEST-ONLY contract

Main release-v3 selects Pauli plan-v3 candidate B as a test contract only.
Requested author: `gpt-6.1-sol`; actual runtime attestation is separate. This
NEW9 is independent of unchanged old15, NEW26 and admission4 with their original
failures. No production, native design, N6 two-process, A7/A8 or device approval.

## Static public / stdlib basis

Current `NodeGateway(hub, *, port=0)` inherits `BaseServer.serve_forever(self,
poll_interval=0.5)` and `service_actions(self)` unchanged. The standard loop
registers its selector, polls/handles requests, then directly calls the public
hook; its finally sets shutdown completion. Bound sockets/live/start-returned
threads alone do not establish loop entry or make shutdown safe.

The existing selected public interface is `attach_node_gateway(gateway,
*, serve_thread)`, `detach_node_gateway()`, and `node_gateway_state()` with
the unchanged `{gateway,effective_ready,basis}` shape. No proposed internal proof
or receipt field is exposed or installed as a test alias. Missing host API is a
test-body failure after actual loop fixture calibration, never a fake success.

Host installs a generation-scoped instance hook, delegates the original hook and
publishes only after its normal return. Proof binds the exact supplied Gateway
and Thread objects. Only direct `sys._getframe(1)` caller code equals actual
stdlib `BaseServer.serve_forever.__code__`, and that caller's self is the exact
Gateway. No global frame scan, other task frame/locals inspection, frame/locals
retention, thread-name guessing or private target alias is admissible proof.

Attach has finite wait outside Hub/session locks. Before publication, recheck
closing/closed, socket, Thread, hook ownership and attachment generation. Late
old proof never creates readiness after close/detach. Socket/thread exit or later
hook replacement revokes capability. Restore only a hook still owned by that
generation; preserve a later owner's replacement.

The canonical writeTX readiness callback reads published memory plus allowed
local socket/Thread observations only. No frame API, Event.wait, Hub/session
locks, SQL/file/network/ENV/backend acquisition or global thread scan. Explicit
permissions, immutable acceptance, UNKNOWN and role fences stay unchanged.

## Fixed nine cases and evidence

1. Actual direct stdlib loop on exact Gateway/Thread grants readiness for the
   cached real mission, not native reservation/task/model/verification truth.
2. Unrelated live Thread rejects, with no foreign join or listener shutdown;
   the actual serving Thread subsequently remains eligible.
3. Same-Hub other Gateway's actual serving Thread rejects object affinity.
4. Matching live Thread manually calling service_actions rejects wrong caller
   code; bound-but-never-entered server gets no shutdown or blind join.
5. Hook replacement revokes readiness and detach preserves later owner.
6. Original hook exception after successful attachment remains observable,
   ends the actual loop and revokes proof; host never swallows it as success.
7. In a real core writeTX, callback completes while another thread owns actual
   Hub/session locks. Scoped frame/global-scan/wait/ENV guards and IO audit expose
   forbidden callback access, without affecting ordinary server-loop witnesses.
8. Block the original hook before normal return; attach waits outside Hub locks,
   idle close completes, then release. No late publication; external loop stays
   alive. Generation/final-close fence is observed through public readiness.
9. Explicit Event-wait process DI marks one active controller, not Mission.run.
   Cooperative close waits with readiness false while the actual Gateway still
   serves anonymous401; release then allows close to finish. Real active Stop is
   separate from idle Stop masking and not a native control ACK or receipt.

Each positive-loop fixture first retains actual direct caller-code/self/exact
Thread calibration and anonymous HTTP401 using the exact server Host header.
The manual-caller fixture retains its bound/live-but-not-entered classification.
Frame calibration discards its local frame immediately and saves booleans only.
Readiness state, direct core and wrapped Hub snapshot shapes are statically
verified. Save one input snapshot; dynamic `counters.wall_minutes` is neither
asserted equal across reads nor renamed, suppressed or added as an alias.

All serving Threads are actual same-process standard Python threads on isolated
loopback listeners, not provider/native-model sessions, remote nodes or actual
OS/two-process controller/worker proof. Original hook fault and manual/barrier/
process-wait DI are explicit. No CLI-owned startup/cleanup is modeled in NEW9;
the frozen NEW26 CLI contracts/outcomes remain independent, including bounded
entry failure and no never-entered shutdown/blind join obligations. Wrong/manual
ownership guards here observe real host attachment behavior, not a fake CLI.

Fixture teardown only shuts down loops with a witnessed actual entry; manual
never-entered listeners are closed without shutdown. It releases fixture-owned
Events and joins its own threads boundedly, never a foreign owner on Hub's behalf.
Original exceptions are captured by type only; frames/tracebacks/credentials are
not retained. No real enrollment, credential file, mission Start, checker,
model/provider/probe/profile/login/SSH/remote/deploy/private mission/eval/WAL6 or
deletion. Temporary inputs, stores and all failures are retained under guard.

Compile actual sources and NEW tests, freeze complete SHA pins before the sole
bounded retained outcome. Keep current Gateway5406 and every production/old test/
contract/helper unchanged. Distinguish actual calibration, target assertions and
unreached scenarios; no post-outcome correction, alias, skip, xfail or restart.
End with file-only readback and separate handoff; source remains HOLD.
