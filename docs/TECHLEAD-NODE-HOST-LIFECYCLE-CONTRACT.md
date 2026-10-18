# Node host listener / public CLI lifecycle — frozen TEST-ONLY contract

Release basis: `artifacts/techlead/orchestra-20261006/node-host-lifecycle-test-only-release-v1.json`.
Requested author: `gpt-6.1-sol`; runtime model attestation is separate. This
contract and the standalone new tests are measurements for a later separately
released implementation, not SOURCE approval, login readiness, N6 two-process
acceptance, A7/A8, a task PASS or integration approval. Old frozen15 and all prior
failed attempts remain unchanged and have independent outcomes.

## Public source calibration

- `lead_cli.py`: `parser()`, `_main(argv=None)`, `main(argv=None)`; existing
  `--max-cycles` defaults to None, worker permission remains explicit.
- Real `MissionHub(directory, *, single=False, mission_factory=None)` caches
  `_Session` objects in `_sessions`, constructs current/future real LeadMission
  instances in `create` / `_session`, and cooperatively requests stop then joins
  active controller threads in `close`. Core snapshot is direct; Hub snapshot is
  the existing `{id,snapshot,controller,controls}` wrapper.
- `LeadMission.__init__` assigns the instance callback
  `remote_execution_ready: Callable[[], bool] = lambda: False` (line136), not a
  class method. Remote reservation admission invokes that instance callable
  inside its existing transaction (lines1401–1405).
- Real `LeadConsole(hub, *, port=DEFAULT_PORT)` and
  `NodeGateway(hub, *, port=0)` bind IPv4 `127.0.0.1`; their standard public
  socket, `server_address`, `server_port`, `serve_forever`, `shutdown`, and
  `server_close` are used. Gateway URL has no credential. Operator token URL is
  private and is absent from retained listener evidence.
- Real `threading.Thread(group=None,target=None,name=None,args=(),kwargs=None,
  *,daemon=None,context=None)` in the retained Python supplies start/is_alive/join.
  No invented gateway thread field; the DI constructor preserves this exact
  optional keyword shape and is not an OS/native thread receipt.
- Parent host attachment methods and optional CLI flag are absent: new tests
  identify missing public interfaces in test bodies, after fixture calibration,
  rather than making them setup/import failures or installing production aliases.

## Host capability, not persisted mission truth

Required exact methods: `attach_node_gateway(gateway, *, serve_thread)`,
`detach_node_gateway()`, `node_gateway_state()` returning exactly
`{gateway,effective_ready,basis}`. `gateway` is None or exactly `{url,host}`;
readiness is a bool and basis is an explicit nonempty explanation.

Explicit trusted same-hub attachment requires a live loopback listener and live
serving thread. The default is false. Cached and future real missions use this
host-owned callback without altering specs, placement pins, request fingerprints,
acceptance, native reservations or task outcomes. Registration/selected placement
does not imply liveness, model readiness or acceptance. A second attach conflicts.
Detach is idempotent, revokes capability only and leaves an externally owned
server alive. Socket or thread loss revokes effective readiness.

The callback is valid inside the existing native reservation write transaction:
it acquires neither Hub nor session lock and opens no database/file, queries no
network, and creates no backend. Tests hold both actual locks on another thread
and invoke readiness inside a real temporary store transaction. Callback-scoped
audit checks cover file opens, SQLite connects, directory enumeration, socket
connect/bind and process calls; local socket/thread observations remain allowed.
This is not a new database or an online cache.

Closing/shutting-down Hub revokes new readiness and late attachment. During its
cooperative wait the node gateway stays serving, including anonymous401 evidence
that its actual listener remains alive; no native stop ACK or terminal receipt is
invented. The process-wait fixture is an explicit Event-wait thread, not a worker
or a model call. Externally owned listener destruction remains outside detach.

## Public CLI startup and ownership

`--node-gateway-port` is an integer 0..65535 for hub/serve/up only, default None.
The plain default constructs/imports no gateway and starts no gateway thread.
new/run/status reject the flag before Hub binding. Valid0 calibration precedes
invalid-port assertions so an unrecognized flag does not pass range validation.
Unlimited cycles and old worker permission boundaries remain intact.

Bind distinct operator and node listeners before any explicit up Start. Start
and attach the serving gateway thread before Start. hub/serve never create or
dispatch a mission implicitly. Listener capability remains separate from model
login, node-online evidence and the explicit local-worker acknowledgement.
No new CLI output field names are stipulated. Public host state publishes only
gateway URL/Host plus listener basis/readiness, never node credentials; the
existing operator token URL privacy rule remains in force.

Cooperative Hub.close precedes owned gateway shutdown/join/close. Clear host
readiness and close the operator listener as well, including partial startup,
thread-start failure, browser/serve exceptions and cleanup errors. Unstarted
servers get close, not shutdown; unstarted threads are not joined. Failures are
nonzero, redacted and preserve their exception type without sensitive raw path
or token. Keep original KeyboardInterrupt130 on a successful cooperative cleanup;
cleanup failure is not exit0 or130. No forced kill, guessed completion or deletion.

## Fixture / measurement boundaries

The new file uses real Hub/LeadMission plus two real anonymous authenticated-
boundary listeners in isolated retained temporary directories. It performs no
enrollment, creates/copies no node credential file and calls no Start/run/probe,
driver, model, checker, evaluation, profile, SSH, remote host or private mission.
Source hashes and fixed specs remain pinned. Real listener capability is not
actual two-process staging or a phone/second-host test.

CLI process/server DI replaces only existing constructor references to MissionHub,
LeadConsole, NodeGateway, standard Thread and webbrowser.open. No production
field/alias is inserted. Hub DI represents public process lifecycle only; its
spec argument is clearly marked process DI, not real core admission or truth.
Serving Thread DI is not an OS spawn. Deep lifecycle scenarios that stop at an
absent option/API remain unreached, not falsely credited as cleanup/dispatch PASS.
Synthetic sensitive exception strings are data, not credentials or file access.

NEW test + this contract are statically compiled and SHA-frozen before the sole
bounded retained outcome. Early deletion/external-network/process/DB-scope guard
stays active; only actual fixture ephemeral loopback listeners are permitted.
All temporary directories, inputs, exceptions, results and proof are retained.
No post-outcome test/doc/source/helper edit, alias, xfail, skip or retry. Known
concurrent Main STATUS/dashboard artifacts are classified separately, not restored.

The fixed cases cover parser/default/positive-before-negative/permission,
nonservice rejection, no-import default hosting, explicit bind-before-Start and
cooperative ordering, three partial startup failures, browser/serve errors, four
cleanup failures, real anonymous listener calibration, exact public Hub shape,
cached/future immutability, write-TX callback exclusions, detach ownership,
socket/thread loss and closing/closed late-attach fences. This is a bounded new
selection; original15 and other frozen suites are not run or edited by this slice.
