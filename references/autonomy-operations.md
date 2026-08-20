# Operating the Sisyfus autonomous runtime

The v0.8 autonomy slice is a verifier-gated control loop, not an unrestricted
LLM shell. Sensors discover opportunities, a planner proposes one narrow
Decision, policy admits a typed capability, and an independent verifier decides
whether evidence is PASS, FAIL, INCONCLUSIVE, or ERROR.

## Install this branch

```bash
git clone https://github.com/DionisAI/sisyfus-skill.git
cd sisyfus-skill
git checkout feat/autonomous-agent-v08
python -m pip install -e .
```

Initialize the SQLite-WAL control plane:

```bash
sisyfus-autonomy --root "$PWD" init
```

The default database is `.sisyfus/autonomy.sqlite3`. The service heartbeat is
`.sisyfus/autonomy-heartbeat.json`.

## Planner protocol

The planner is deliberately provider-neutral. Configure any executable that:

1. reads `SISYFUS_AUTONOMY_CONTEXT_PATH`;
2. emits one JSON Decision to `SISYFUS_AUTONOMY_RESPONSE_PATH` or stdout;
3. never assumes its proposal is accepted or verified.

Decision examples:

```json
{
  "kind": "EXECUTE",
  "capability": "workspace.write_text",
  "arguments": {"path": "result.txt", "content": "verified candidate\n"},
  "idempotency_key": "result-write-v1",
  "reason": "produce a read-back-verifiable artifact"
}
```

```json
{
  "kind": "WAIT",
  "wait_seconds": 300,
  "reason": "the environment has not produced new evidence"
}
```

```json
{
  "kind": "FINISH",
  "evidence_id": "ev_...",
  "reason": "the independent verifier returned PASS"
}
```

A FINISH without persisted PASS evidence is rejected. Planner prose and model
confidence never change continuation truth.

## Discover opportunities from an inbox

Copy or write JSON files into an inbox directory. The format is demonstrated by
`examples/autonomy/inbox/example.json`. Each file may contain one object, an
array, or `{"signals": [...]}`. Content-based dedupe makes repeated scans safe;
provide an explicit `dedupe_key` when the same logical need may be rewritten.

Run one end-to-end cycle with the deterministic example planner:

```bash
sisyfus-autonomy --root "$PWD" run \
  --planner-command "python examples/autonomy/planner.py" \
  --inbox examples/autonomy/inbox \
  --once
```

Run continuously:

```bash
sisyfus-autonomy --root "$PWD" run \
  --planner-command "python examples/autonomy/planner.py" \
  --inbox /srv/sisyfus/inbox \
  --worker-id "$(hostname)-1" \
  --lease-seconds 60 \
  --idle-sleep 1 \
  --error-sleep 5
```

SIGINT and SIGTERM stop the supervisor cleanly. A dead worker's lease expires;
a later worker recovers the continuation. Multiple workers may share one
SQLite database on one host, but this first slice is not a distributed network
filesystem database.

## systemd example

```ini
[Unit]
Description=Sisyfus verifier-gated autonomous supervisor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=sisyfus
Group=sisyfus
WorkingDirectory=/srv/sisyfus
ExecStart=/srv/sisyfus/.venv/bin/sisyfus-autonomy --root /srv/sisyfus run --planner-command "python /srv/sisyfus/examples/autonomy/planner.py" --inbox /srv/sisyfus/inbox --worker-id %H-1 --lease-seconds 60 --idle-sleep 1 --error-sleep 5
Restart=always
RestartSec=5
TimeoutStopSec=30
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/srv/sisyfus

[Install]
WantedBy=multi-user.target
```

Inspect state and integrity:

```bash
sisyfus-autonomy --root /srv/sisyfus status
sisyfus-autonomy --root /srv/sisyfus verify-chain
sisyfus-autonomy --root /srv/sisyfus recover
```

## Default safety boundary

Only these built-ins are registered by default:

- `core.echo` — R0, pure deterministic check;
- `workspace.write_text` — R1, workspace-confined write followed by exact
  read-back verification.

The default unattended ceiling is R1. Arbitrary shell, deployment, outbound
messages, trading, deletion, and irreversible operations are not registered.
Adding those requires a typed capability, narrow policy, idempotency strategy,
and an external-side-effect reconciliation design.

## Current limitations

This branch provides the durable supervisor kernel and provider-neutral planner
protocol. It does not yet provide production model-provider adapters, container
sandboxing, distributed queues, secret-scoped capability manifests, unknown
external-commit reconciliation, or held-out causal efficacy for lessons.
Experience promotion is evidence-linked and contradiction-aware, but it is not
yet a causal proof that consulting a lesson improved an outcome.
