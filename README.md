# sisyfus-research — an agent skill for verifier-gated autonomous research

> A planner may propose experiments, but only a preregistered verifier and a
> deterministic reducer may change research truth.

**This repository is the skill.** [`SKILL.md`](SKILL.md) at the root is the agent
entry point; [`references/`](references/) hold the contracts the skill operates
under; [`templates/`](templates/) are the TaskSpec and experiment scaffolds. The
Python engine in `src/` is the skill's deterministic backend — agents drive it
through the `sisyfus` CLI and never mutate research state directly.

## What the skill does

Given an open research question, an agent using this skill:

1. compiles it into a **TaskSpec** — falsifiable claims, an AND/OR Goal Graph,
   preregistered verification contracts, optional hard budgets;
2. loops: propose experiments (citing prior evidence/lessons) → admission
   control → execute → a **pure-code verifier** classifies each observation as
   `PASS / FAIL / INCONCLUSIVE / INVALID / ERROR` → an event-sourced reducer
   commits state;
3. banks **lessons** that are evidence-gated, promoted into a project-wide store,
   and relevance-ranked into every future run's planner context;
4. stops mechanically: goal proven (`SOLVED`), goal refuted (`REFUTED`), or a
   declared budget exhausted — never on vibes;
5. renders a self-contained bilingual **HTML Observatory ("Arena")**: an
   esports-broadcast view of the exploration with kill feed, caster commentary,
   deterministic visual replay, and a print-ready final report.

Every projection is rebuildable from an append-only, hash-chained event log.
`sisyfus research replay` re-derives the whole run; `sisyfus research reproduce`
re-runs any command evidence's hashed measurement code and re-classifies it under
the same locked contract — no model in the loop.

## Install

**One command** — installs the skill *and* the engine, idempotent, nothing
touches system Python:

```bash
curl -fsSL https://raw.githubusercontent.com/DionisAI/sisyfus-skill/main/install.sh | bash
```

The installer:

1. copies `SKILL.md` + `references/` + `templates/` into every detected skill
   directory (`~/.claude/skills/`, `~/.agents/skills/`) as `sisyfus-research`;
2. installs the engine into its own venv at `~/.sisyfus/venv` and links the CLI
   to `~/.local/bin/sisyfus` (avoids PEP 668 / system-Python issues entirely);
3. verifies `sisyfus --version` and warns if `~/.local/bin` is missing from
   `PATH`.

Uninstall everything with `install.sh --uninstall` (per-project `.sisyfus/`
state trees are never touched).

<details>
<summary>Manual install</summary>

Skill: copy `SKILL.md`, `references/`, and `templates/` into
`~/.claude/skills/sisyfus-research/` (or any skills directory your agent scans),
or use a skills CLI: `npx skills add github:DionisAI/sisyfus-skill`.

Engine (pure standard library, Python >= 3.11):

```bash
python3 -m pip install "sisyfus @ git+https://github.com/DionisAI/sisyfus-skill"
```

`SKILL.md` performs this check itself, so an agent landing on a clean machine
bootstraps the engine on first use.

</details>

## Use it from your agent

This is the primary interface. After install, any skills-aware harness
(Claude Code, Codex, and friends) discovers `sisyfus-research` on its own:

- **Explicit** — name it:

  ```text
  /sisyfus-research 验证「0-5c 做市在 Polymarket 是否可行」
  ```

- **Automatic** — just describe the job in your own words: *"帮我验证这个假设
  是否成立,要可复现"*, *"backtest this strategy properly"*, *"做一个
  证据驱动的研究"*. The harness matches the skill's frontmatter description and
  loads it without being asked.

Either way the skill takes over end to end: it bootstraps the engine if the CLI
is missing, compiles your question into a TaskSpec with preregistered
verification contracts, runs the propose → verify → commit loop, and hands you
the Arena report. You never need to touch the Python directly.

For harnesses without a skills registry, point your `AGENTS.md` at the installed
`~/.claude/skills/sisyfus-research/SKILL.md` (or copy the skill into the
project's own `.agents/skills/`).

## Quickstart (CLI, for humans and scripts)

The same engine, driven by hand:

```bash
mkdir /tmp/sisyfus-demo && cd /tmp/sisyfus-demo
sisyfus init                       # installs .sisyfus/ layout + a local skill copy
sisyfus research demo --root .     # scripted run: fail, branch, recover, solve
sisyfus research serve latest --open --root .   # live Arena in the browser
sisyfus research replay latest --root .         # hash-verify the whole run
```

Then read [`SKILL.md`](SKILL.md) — it is the operating manual an agent follows:
start/resume, the research loop, verdict semantics, waits and wakes, lessons,
stopping rules, and the audit commands.

## Repository layout

```text
SKILL.md          # the skill: agent-facing operating manual (canonical)
references/       # task-spec / verifier-contract / event-model contracts
templates/        # TaskSpec and experiment JSON scaffolds
src/sisyfus/      # deterministic engine: CLI, reducer, verifier, Arena renderer
  skill_assets/   # wheel payload — synced copy of the root skill (do not edit)
scripts/          # sync_skill_assets.py keeps root skill == wheel payload
tests/            # engine + skill regression suite (pytest -q)
examples/         # legacy v0.6 goal-spec demos
SPEC.md           # engine design document
CHANGELOG.md      # per-version history
```

Root skill files are canonical; `scripts/sync_skill_assets.py` copies them into
the wheel payload and a test fails if the two ever drift.

## Design commitments

- **Verdicts are code, not opinion**: the verifier evaluates preregistered rule
  contracts; contracts are hash-locked before execution; measurement code is
  content-hashed into every evidence record. The trust model is documented in
  [`references/verifier-contract.md`](references/verifier-contract.md).
- **Failure is information**: refuted claims, invalid measurements, and budget
  exhaustion are first-class outcomes with their own visuals — the Arena never
  renders a MISS as damage.
- **Memory must be earned**: lessons require evidence from independent
  experiments before promotion, and carry cross-run usage/efficacy statistics.
- **Local-first, dependency-free**: one file-based state tree per project, no
  runtime dependencies, everything auditable offline.

## Test

```bash
python3 -m pytest -q
```

## License

MIT — see [LICENSE](LICENSE).
