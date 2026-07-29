# Event and graph model

`events.jsonl` is append-only and hash chained. Its projections are disposable.

Important events:

- `RUN_CREATED`, `SPEC_LOCKED`
- `CONTRACT_ADDED`
- `EXPERIMENT_PROPOSED`, `EXPERIMENT_ADMITTED`, `EXPERIMENT_BACKLOGGED`, `EXPERIMENT_PRUNED`
- `ATTEMPT_RESERVED`, `ATTEMPT_STARTED`, `OBSERVATION_RECORDED`, `VERDICT_ISSUED`
- `WAIT_FIRED`, `WAIT_EXPIRED`
- `LESSON_CANDIDATE_CREATED`, `LESSON_EVIDENCE_ADDED`, `LESSON_PROMOTED`, `LESSON_REVOKED`
- `RUN_PAUSED`, `RUN_RESUMED`, `RUN_FAILED`, `RUN_FINALIZED`

## Three projections

- Goal Graph: AND/OR/CLAIM nodes and mechanical completion.
- Execution Graph: immutable State Nodes, Experiment edges, and Attempt executions. It is a DAG, not necessarily a tree.
- Evidence Graph: Evidence → Claim relations, including provisional support, support, refutation, and qualification.

Each VERDICT creates a new State Node from the Experiment's `from_state_id`, not necessarily from the latest global state. This makes sibling branches and rollback explicit.
