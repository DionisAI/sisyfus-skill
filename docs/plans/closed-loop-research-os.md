# Closed-loop Research OS implementation plan

Base: main at 2aa4b851e39a44eae02c54d8f1311e73c2c213af. Work is isolated from the unrelated self-update PR.

## Objective
Extend Sisyfus with a budgeted, evidence-backed research frontier, typed judgment adapters, executable SOPs, a learned scheduler, and Dream-RSI-inspired replay policy selection. Preserve the existing research engine as the authority for claims, artifacts, and verdicts. Do not build a replacement truth store.

## Non-negotiable boundaries
- Proposals and judgments are not evidence. Only the existing verifier establishes research verdicts.
- No production deployments, exchange orders, credentials, or automatic merging.
- Version-pin contracts, policies, workflows and execution contexts.
- Replay exposes only reached recorded outcomes; unknown actions are unsupported, not simulated successes.
- Replay wins never authorize automatic promotion. Fresh execution and explicit approval are required.
- Retain dependency, invalidation, budget and evidence checks even with adversarial or unavailable judges.
- Optional network providers remain opt-in; offline tests need no API key.
- Do not claim improvement over GPT-6-Astra without a real paired provider evaluation.

## Implementation sequence
1. Inspect existing research/autonomy APIs and establish baseline regression results.
2. Add a read-only frontier view and bounded scheduler over existing research state.
3. Add judgment protocol and optional Jev adapter with strict numeric validation and conservative fallback.
4. Add versioned research SOP contracts and a bounded execution loop using existing artifacts/verifiers.
5. Add trace export, support-limited replay, small learned ranking policy and held-out evaluation.
6. Add runnable offline example, CLI, ablations, failure-injection tests and operator documentation.
7. Run local and GitHub CI checks; publish exact evidence and remaining limitations in this PR.

## Acceptance
Tests must establish that no worker or judge can self-certify completion; dependency and contract gates cannot be bypassed; missing or stale evidence blocks closure; replay does not expose future outcomes; unrecorded actions fail explicitly; costs and unsuccessful attempts remain in accounting; candidate policies cannot change acceptance standards. An executable demonstration must go from research frontier through real tool evaluation to recorded evidence and policy evaluation.
