# Tech Lead quick start

This is an opt-in development extension of Sisyfus 0.9.0. The normal research
observatory and legacy worker console are unchanged. The **Tech Lead console is
an operational surface**, not only a read-only status page.

## Roles and execution

- Lead: `claude-opus-5-5`, architecture, interfaces, task DAG and diagnosis.
- Workers: `gpt-6.1-sol`, scoped implementation in separate candidate copies.
- Reviewer: a fresh read-only `claude-opus-5-5` session.
- Controller: immutable executable acceptance, leases/receipts, integration,
  pause/stop and evidence-gated procedure changes.

The native Claude and Codex CLIs must already be signed in. Requested models and
runtime-attested models are distinct fields; a missing actual model stays null.
Default aggregate budgets are Unlimited. Individual calls still have time and
output limits, and parallelism defaults to two.

## Start the browser hub

From this development checkout with its `src` on PYTHONPATH:

```sh
PYTHONPATH="$PWD/src" python3 -m sisyfus techlead hub \
  --directory "$HOME/Documents/Sisyfus-TechLead/missions" --port 8781 --open
```

The printed loopback URL includes a private token in its fragment. Keep this URL
private. The hub starts **no mission automatically**. Create a mission with a
source project, objective, role models, and approved executable checks. Creating
and selecting a mission do not execute models. **Start** explicitly starts the
local native workers. Pause suppresses new dispatch; an in-flight call can finish.
Resume continues the same mission. Stop is durable and requests cooperative
interruption; its acknowledgement is not a terminal receipt.

A model's stop/wait recommendation is advisory (`NEEDS_OPERATOR` /
`WAITING_LEAD`), not the operator's durable Stop. After addressing the condition,
explicit Start advances the diagnosis epoch and restarts an idle controller;
Resume advances the epoch and clears dispatch pause but does not itself start
an idle thread. Neither operation clears UNKNOWN or an operator-owned Stop.

## Run a prepared specification

```sh
PYTHONPATH="$PWD/src" python3 -m sisyfus techlead new mission.json \
  --directory /absolute/disjoint/control-directory
PYTHONPATH="$PWD/src" python3 -m sisyfus techlead run mission.json \
  --directory /absolute/disjoint/control-directory --allow-local-workers
PYTHONPATH="$PWD/src" python3 -m sisyfus techlead serve \
  --directory /absolute/disjoint/control-directory --port 8781 --open
```

Source and control directories must be disjoint. Checks are operator-approved
commands, with code hashes and explicit pass/fail contracts, located outside the
mutable project. A free-text objective by itself is not an executable acceptance
contract. Changed requirements/checks require a newly approved mission, not an
agent silently weakening an existing gate.

## Inspect results

The console shows task history, scoped dependencies, immutable attempts,
requested/actual models, deterministic measurements, independent reviews,
diagnoses, integration and procedure history. A task is accepted only when its
test and independent review agree. Whole-project integration is a separate gate.
Failed historical attempts remain visible after a versioned repair.

UNKNOWN means execution outcome has not been established. Restarting preserves
the reservation and does not resend it. Missing cost/token telemetry is displayed
as unknown, not zero; configured monetary/token caps fence further dispatch when
the relevant telemetry is missing. Reported provider cost is not an invoice.

Procedure proposals are not demonstrated improvements. Promotion needs frozen,
matched baseline/candidate runs plus an independent untouched holdout. Evidence
gaps and non-improvement remain explicit, and active policy is kept unchanged.
Current delivery and verification status is in `TECHLEAD-ACCEPTANCE.md`.

## Enable the paired procedure lab

The operator supplies a frozen catalog; the Lead never invents its own holdout.
In a new mission specification, set:

```json
"rsi": {
  "enabled": true,
  "auto_promote": true,
  "evaluation_root": "/absolute/path/to/operator-catalog"
}
```

The catalog's `manifest.json` has nonempty `search` and `holdout` arrays of
`{"id": "unique-case", "spec": "relative-spec.json"}` entries. Each spec owns
source content, approved external hash-pinned checks and explicit role models.
`scripts/prepare_procedure_trials.py <new-directory>` prepares the retained
engineering pilot used for this delivery. It does not run a model.

At an accepted boundary the controller asks the real Lead for a grounded policy
candidate, runs actual baseline/candidate child missions, and evaluates canonical
receipts. Children disable recursive labs. Later Lead decisions read the active
procedure version. Policy proposals, rejected evaluations and rollbacks stay in
the same canonical store; promotion never changes model weights.

An already accepted mission can be exercised explicitly with:

```sh
PYTHONPATH="$PWD/src" python3 scripts/run_native_procedure_trials.py \
  --origin /absolute/path/to/accepted-mission \
  --catalog /absolute/path/to/operator-catalog \
  --output /absolute/path/to/new-retained-report \
  --allow-local-workers
```

The output directory is exclusive, not an overwrite/retry slot. Pending or
UNKNOWN requests are fenced. Holdout content is consumed on first inspection,
including failed evaluations; use genuinely independent fresh cases for a later
candidate. No savings means NONPROMOTION, not success by fiat. Null runtime model
telemetry limits claims to a requested-model matched pilot.

Finite aggregate caps work for the main mission. **Current limitation:** any
finite parent aggregate cap conservatively fences native RSI child dispatch;
cross-database shared spending is not implemented. Unlimited parents may run the
lab, with individual call limits and stop/pause still active. Snapshots distinguish
parent, registered-child and total native-call reservations and unknown metering.

Same-user copies are not an OS-level secrecy boundary for hostile workers.
Keep evaluation fixtures free of private data; external code hashes and lineage
checks establish the trusted local pilot contract, not adversarial isolation.

## Retained engineering validation

`scripts/prepare_lead_fixture.py <new-directory>` creates a small job-polling
engineering project and external six-test contract. This validates orchestration;
it is not a completed Tripo3D integration or a network-service test.

`scripts/test_retained.py` runs pytest with retained temporary files and a
permanent-deletion tripwire. Existing legacy migration tests that permanently
unlink a database must be excluded under the user's active deletion policy;
their policy failure must be recorded rather than hidden.
