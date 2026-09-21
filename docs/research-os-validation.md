# Research OS v1: validation and limits

## Scope

This is an integrated, opt-in experimental controller over the existing Sisyfus `ResearchEngine`, not a replacement runtime and not a demonstrated improvement over GPT-6-Astra. The kernel keeps its existing authority for admissions, artifacts, budgets and verdicts. Main, production execution and the unrelated self-update PR are not modified by activating this development branch.

## Executed evidence

- Baseline: 151 existing tests passed in GitHub Actions (run 35299298882).
- Implementation: 205 tests passed locally, including 54 new Research OS tests, with no skips or failures.
- GitHub independently applied the exact source patch, verified its SHA-256 and ran all 205 tests successfully on Python 3.11 (run 35301519635, job 105464967033; 30.24 seconds).
- Implementation commit: `4d8f8514e45cea8b41f9532923bdb6bf45efe2fc`. All 19 transferred source/documentation files were compared byte-for-byte with the locally tested tree; no differences.
- Subsequent cleanup changes only validation workflow/documentation and removes the temporary source-transfer machinery. The final PR checks are authoritative for the final head, including the existing Python 3.11/3.12/3.13 matrix. Do not infer their completion from the earlier run.

The temporary checksum-verified transfer workflow is not part of the final tree. Retained validation workflows have `contents: read` and do not push, merge or deploy.

## What the new tests cover

Real command execution and verifier-owned verdicts; code drift before and after execution; nonzero exit status overriding spoofed JSON success; unresolved execution blocking retries; reserved cost accounting; coordinator locking; mandatory SOP gates; current dependency checks; hidden evaluation exclusion; malformed/non-finite judgment rejection and redacted fallback; mocked Jev SDK shape/privacy; evidence-linked trace export; exclusion of post-completion diagnostic rewrites from training; support-limited replay; unknown/cyclic/overbudget replay actions; train/search/holdout family separation; learned weight updates; no replay-only activation; actual paired fresh-run validation; evaluator/configuration mismatch rejection; and a bounded real subprocess proposal worker that cannot execute its proposals or self-certify completion.

These tests are not an adversarial operating-system sandbox audit, proof of scientific correctness, or a real-provider LLM benchmark.

## Real subprocess demo and null result

Run in a new workspace:

```bash
python -m pip install -e .
SISYFUS_AUTO_SERVE=0 sisyfus os demo --workspace /tmp/sisyfus-os-demo-new
```

The demo evaluates arithmetic candidate implementations with actual subprocesses and the existing independent contract evaluator. Four task families produce 12 actual check executions: 4 PASS and 8 FAIL. Every verdict references persisted evidence and deterministic replay is checked.

The resulting records are split into 6 training, 3 search and 3 holdout rows, with different task families. A small logistic policy is trained and compared with fixed/FIFO alternatives. Selection uses the search split only. In this fixture the selected candidate is the fixed policy, not the learned policy. Under a budget of two abstract units, the selected candidate, fixed baseline and FIFO each obtain one PASS for two units on holdout. **There is no measured holdout improvement.** This is deliberately reported instead of tuning the fixture or selecting on holdout.

Costs are preregistered abstract evaluation units, not dollars, tokens or seconds. The fixture is too small for a general performance conclusion. It checks the actual loop and honest negative-result handling. No policy is automatically promoted.

The positive fresh-promotion regression uses an intentionally hand-built better policy to exercise validation mechanics; it is not evidence of learned generalization.

Machine-readable reports preserve:

```json
{
  "real_llm_executed": false,
  "live_jev_executed": false,
  "beats_gpt6_astra": null,
  "automatic_policy_activation": false
}
```

## Boundaries before real deployment

- The learned component ranks admitted experiments. This release does not autonomously discover arbitrary SOP graphs or edit acceptance standards.
- Proposal generation reuses the existing bounded command-worker interface, but no real Codex/Claude/other LLM was invoked in these tests. New commands require explicit operator approval before execution.
- Jev is an optional adapter with contract tests, not a reproduced RLCD model. Actual provider latency, calibration and billing are unmeasured. Provider cost is unknown rather than silently recorded as zero.
- Replay reveals only recorded supported actions. Reordering requires an explicit independence assumption; it cannot evaluate new code, worker behavior, prompts or unavailable outcomes.
- Fresh-run promotion checks at least two matched pairs and requires a named operator. This is a small pilot gate, not a statistical performance guarantee or an authentication system.
- Same-user shell execution is not isolation. Use an external container/process/credential boundary before untrusted workers. The new controller's lock does not fence unrelated legacy writers.
- Cross-workspace portfolio scheduling is implemented as a serial, registered-workspace coordinator. Dynamic task/project creation, automatic execution of newly generated commands, production canaries, and live-provider effectiveness remain future work.

The learnable-SOP pilot currently optimizes only bounded retry depth; mandatory authorization, dependency, budget, and verifier gates are not learnable.\n\nThe next effectiveness test is a resource-matched real-provider comparison against a strong direct-worker plus simple-search baseline, using independent task families and frozen evaluators. Each component must show incremental benefit before promotion.
