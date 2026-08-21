# Sisyfus v0.8 autonomous runtime

This document defines the first executable slice toward a continuously running,
self-directed Sisyfus agent. It is deliberately narrower than “put an LLM in an
infinite loop.” The runtime separates proposal, execution, verification and
truth so that a bad planner cannot silently certify its own work.

## Control loop

```text
signal / sensor
    -> deduplicated opportunity
    -> policy admission
    -> durable continuation
    -> leased supervisor worker
    -> planner decision
    -> typed capability admission
    -> idempotent execution
    -> independent verifier
    -> PASS / FAIL / INCONCLUSIVE / ERROR
    -> continue / wait / finish / block
    -> evidence-linked experience candidate
```

## Guarantees in the first slice

- **Durable continuation state:** SQLite WAL stores opportunities,
  continuations, decisions, evidence, events and experience candidates.
- **Single active worker:** renewable leases prevent two supervisors from
  driving one continuation simultaneously.
- **Optimistic concurrency:** every continuation mutation checks a monotonically
  increasing version; stale planners lose the race rather than overwriting
  newer state.
- **Crash recovery:** expired RUNNING/VERIFYING leases return to WAITING or fail
  once the attempt budget is exhausted.
- **Typed capabilities:** unattended execution defaults to risk tiers R0/R1.
  Arbitrary shell, production deployment, outbound messaging, trading and
  destructive actions are denied unless a narrow policy explicitly authorizes
  them.
- **Verifier ownership of truth:** planner FINISH requests do not complete a
  continuation unless an independent verifier returns PASS.
- **Idempotency:** executable decisions carry a unique idempotency key persisted
  before the capability is called.
- **Experience provenance:** positive, negative and operational experience
  candidates cite the evidence record that produced them. Repetition may
  promote a candidate to validated; counterexamples can contradict it.

## Deliberate omissions

This slice does not yet provide sensor plugins, model-provider adapters,
container sandboxing, distributed queues, external side-effect reconciliation,
or causal/held-out lesson efficacy. Those are subsequent layers. In particular,
no global switch should turn arbitrary shell commands into unattended actions.

## Next implementation steps

1. Bridge verified `research_v2` experiments into autonomy evidence without
   creating a second truth store.
2. Add a capability manifest with input/output JSON schemas and secret scopes.
3. Add worker heartbeats, cancellation and unknown-commit reconciliation for
   external side effects.
4. Add opportunity sensors and a policy-scored inbox.
5. Replace simple repetition-based experience promotion with matched-context or
   held-out efficacy checks.
