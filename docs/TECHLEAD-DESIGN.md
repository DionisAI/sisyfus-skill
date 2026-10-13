# Continuous Tech Lead design

## Scope and baseline

Extend released v0.9.0, opt-in under `sisyfus techlead`. Preserve legacy workers,
the old development checkout and the installed release. The real Opus 5.5
architecture-planning receipt is retained under `artifacts/techlead/`; its
decomposition is guidance, not evidence that any feature is complete.

## Architecture

```
operator objective + frozen acceptance + role configuration
                 |
       LeadMission (persistent controller)
       /         |             \
Opus Lead     Sol tasks      independent Opus review
       \         |             /
       existing AutonomyStore + canonical evidence + hash-chain
                 |
        candidate integration + whole-project acceptance
                 |
          procedure candidate + paired/holdout evaluation
                 |
         validated procedure version for later Lead decisions
```

## Boundaries

- `lead_contracts.py` validates operator specs, role bindings, immutable checks,
  DAGs, relative write ownership and unlimited aggregate defaults.
- `lead_mission.py` and `lead_journal.py` own iterative orchestration state and
  revisions, using the existing native driver/continuation/evidence machinery.
- `lead_learning.py` owns only procedure lineage and evidence-gated promotion;
  it references authoritative mission databases rather than inventing outcomes.
- `lead_chat.py` stores conversation drafts and read-only native Opus receipts;
  it never supplies task truth or executable checks. Explicit confirmation binds
  the approved contract to the existing controller, retaining the approved
  objective/constraints and adding the accepted conversation plan. Idempotent
  request IDs and restart UNKNOWN fencing prevent blind resend.
- `lead_chat_page.py` is the default Chinese chat interface; `/console` retains
  the developer interface.
- `lead_console.py` and `lead_cli.py` expose user operations. A web connection or
  successful request is not proof that a model executed or a task passed.
- Native drivers retain requested and returned execution model identity
  separately. Missing telemetry stays missing.

## Why this design

Lifecycle ownership, acceptance provenance and restart correctness are the
three primary design lenses. Reusing the canonical store avoids conflicting
sources of task truth; separating role contracts from lifecycle lets the web
surface stay small. Merely adding prompts to the initial planner would not
create diagnosis/replanning/integration. A wholesale rewrite or one wrapper
module for each competency would add migration cost without hiding complexity.

## Adversarial checks

- A model attempts to add a command, weaken a check or select its own executor:
  the contract rejects unknown fields; original checks remain hash-pinned.
- Parallel tasks write the same file: DAG admission detects overlapping scope;
  integration must also verify bases and reject conflicts before mutation.
- A reviewer approves an agent's prose: the review packet must instead contain
  frozen requirements, candidate changes and deterministic evidence.
- An interrupted request has no final receipt: preserve UNKNOWN and its
  reservation; restarting does not establish non-execution or permit replay.
- A procedure claims improvement: only recomputed matched execution/holdout
  evidence can activate a version; no changed evaluators or invented metrics.

## Residual limits

Independent sessions of the same model may share blind spots. Tests and negative
controls remain mandatory. Native model telemetry may be missing, and provider
reported session cost is not an invoice. Same-user candidate copies and hash
checks are not OS-level protection for untrusted code or private holdout data.
Aggregate limits default to null; single-call limits and stop remain active.

## Status

Implementation, independent code-review repairs, real autonomous repair and a
four-arm native procedure pilot have been verified. The pilot measured zero
invocation savings, so its candidate was not promoted. The authoritative
delivery and completion checklist is `TECHLEAD-ACCEPTANCE.md`.
