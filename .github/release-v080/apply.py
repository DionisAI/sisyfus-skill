from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.8.0"
TAG = f"v{VERSION}"
RELEASE_DATE = "2026-08-20"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, before: str, after: str) -> None:
    text = read(path)
    if after in text and before not in text:
        return
    count = text.count(before)
    if count != 1:
        raise SystemExit(
            f"unexpected replacement count in {path}: {count} for {before!r}"
        )
    write(path, text.replace(before, after, 1))


def insert_before(path: str, marker: str, block: str) -> None:
    text = read(path)
    if block.strip() in text:
        return
    if text.count(marker) != 1:
        raise SystemExit(f"unexpected marker count in {path}: {marker!r}")
    write(path, text.replace(marker, block + marker, 1))


replace_once("pyproject.toml", 'version = "0.7.4"', f'version = "{VERSION}"')
replace_once(
    "src/sisyfus/__init__.py",
    '__version__ = "0.7.4"',
    f'__version__ = "{VERSION}"',
)

for path in ("README.md", "README.zh-CN.md", "SKILL.md"):
    text = read(path)
    text = text.replace("@v0.7.4", f"@{TAG}")
    write(path, text)

README_RELEASE = f'''## What's new in v{VERSION}

v{VERSION} turns Sisyfus from a verifier-gated research engine into a
**monitor-first autonomous research runtime**:

- **Mission Control opens first.** Every new Skill invocation hosts and opens a
  stable, game-style live monitor before research, coding, or experimentation.
  Progress, heartbeat, current operation, waits, errors, and verifier activity
  update continuously without being confused with research evidence.
- **Ambiguous work pauses for clarification.** Scope, terminal objective, and
  verification method are blocking intake gates. Missing high-impact details
  produce `CLARIFYING / NEEDS_USER`; the coding agent asks one compact batch of
  questions, then locks a concise intake contract before compiling the TaskSpec.
- **One continuous Arena.** The pre-TaskSpec map and the evidence-backed Claim
  map now share the same broadcast shell, visual tokens, node grammar, replay
  controls, right-side feed, quest panel, and live HUD.
- **Durable 24×7 autonomy.** A canonical SQLite-WAL control plane provides
  versioned state, renewable worker leases, heartbeat fencing, crash recovery,
  persisted decisions, idempotency receipts, bounded retries, and mechanically
  terminal outcomes.
- **Verifier-owned truth.** Planners may propose actions but cannot self-certify
  completion. `PASS / FAIL / INCONCLUSIVE / INVALID / ERROR` remain independent
  verifier outcomes; `FINISH` requires persisted PASS evidence.
- **Safer unattended execution.** Typed capabilities, an R0/R1 default risk
  ceiling, exact project roots, bounded planner output, process-group
  termination, sensor quarantine, and unknown-commit blocking reduce silent
  side effects and duplicate actions.
- **Evidence-safe memory.** Experience promotion counts unique evidence
  observations, so replaying one result cannot manufacture a validated lesson.

See [`RELEASE_NOTES_v{VERSION}.md`](RELEASE_NOTES_v{VERSION}.md) and
[`CHANGELOG.md`](CHANGELOG.md) for the complete release notes.

'''
insert_before("README.md", "## Install\n", README_RELEASE)

README_RELEASE_ZH = f'''## v{VERSION} 新版内容

v{VERSION} 把 Sisyfus 从验证者门控的研究引擎升级成了一个
**Monitor-first 的持续自主研究运行时**：

- **先打开 Mission Control，再开始工作。** 每次调用 Skill，系统都会先 host 并
  打开稳定的游戏化监控网页，再进行搜索、编码或实验；当前操作、进度、心跳、等待、
  错误和 Verifier 状态持续更新，但不会被误当成研究证据。
- **信息不明确时主动暂停并追问。** Scope、最终目标、验证方法是三道阻断式 intake
  gate。重大信息缺失时进入 `CLARIFYING / NEEDS_USER`，Coding Agent 一次性询问尚未
  解决的问题，并在编译 TaskSpec 前锁定 Intake Contract。
- **启动页和正式地图是一套 Arena。** Preflight Map 与正式 Claim Map 共用相同顶栏、
  配色、字体、节点、连线、Hero、战报、任务面板、Replay 和 Live HUD，不再有明显拼接感。
- **可恢复的 24×7 自主运行。** Canonical SQLite-WAL 控制平面提供版本化状态、可续租
  Worker Lease、Heartbeat Fencing、崩溃恢复、持久化 Decision、幂等 Receipt、有限重试和
  机械终局。
- **Verifier 拥有真相。** Planner 只能提案，不能自己宣布成功；`FINISH` 必须引用已持久化
  的 PASS Evidence，五种 Verdict 语义保持严格分离。
- **更安全的无人值守执行。** Typed Capability、默认 R0/R1 风险上限、严格项目根目录、
  有界 Planner 输出、进程组终止、Sensor 隔离和 Unknown Commit 阻断共同降低重复副作用。
- **不会被重复证据污染的经验。** Lesson 晋升只统计唯一 Evidence Observation，同一条结果
  重放多次不能伪造“已验证经验”。

完整内容见 [`RELEASE_NOTES_v{VERSION}.md`](RELEASE_NOTES_v{VERSION}.md) 和
[`CHANGELOG.md`](CHANGELOG.md)。

'''
insert_before("README.zh-CN.md", "## 安装\n", README_RELEASE_ZH)

CHANGELOG_SUMMARY = f'''v{VERSION} is the first release of the monitor-first, verifier-gated autonomous
research runtime.

### Highlights

- Mission Control is hosted and opened at the first Skill action, before research
  begins, with live phase, operation, progress, heartbeat, wait, error, and
  verifier telemetry.
- A proactive clarification gate blocks ambiguous scope, objective, or
  verification contracts and records `CLARIFYING / NEEDS_USER` in Mission
  Control until the user locks the intake contract.
- Bootstrap Mission Control and the full Claim-map Observatory now use one
  `sisyfus-arena-broadcast-v1` visual system and one continuous Arena shell.
- A canonical SQLite-WAL autonomy runtime adds opportunities, continuations,
  persisted decisions, evidence, experiences, renewable leases, heartbeat
  fencing, idempotency, recovery, risk tiers, bounded retries, and terminal
  state invariants.
- Independent verifiers own `PASS / FAIL / INCONCLUSIVE / INVALID / ERROR`;
  planners cannot self-certify completion and `FINISH` requires persisted PASS
  evidence.
- Experience accounting is evidence-unique, preventing replayed observations
  from fabricating validated lessons.
- Planner subprocesses and sensors gained bounded output, process-group
  termination, environment allowlisting, per-file quarantine, and bounded
  iteration.
- Full regression coverage passes on Python 3.11, 3.12, and 3.13.

### Upgrade

```bash
python3 -m pip install --upgrade \
  "sisyfus @ git+https://github.com/DionisAI/sisyfus-skill@{TAG}"
sisyfus --version
```

'''
changelog = read("CHANGELOG.md")
release_heading = f"## {VERSION} — {RELEASE_DATE}\n\n"
if release_heading not in changelog:
    marker = "## Unreleased\n\n"
    if changelog.count(marker) != 1:
        raise SystemExit("CHANGELOG.md does not contain one Unreleased heading")
    changelog = changelog.replace(
        marker,
        release_heading + CHANGELOG_SUMMARY,
        1,
    )
    write("CHANGELOG.md", changelog)

RELEASE_NOTES = f'''# Sisyfus {TAG}

**Release date:** {RELEASE_DATE}  
**Theme:** Monitor-first, verifier-gated autonomous research

## Overview

Sisyfus {TAG} is a substantial release. It combines the existing event-sourced
research engine with a durable autonomy control plane and a continuously hosted,
game-style Mission Control. The system now guides the user through research
intake, keeps long-running work observable, survives worker restarts, and still
refuses to let a planner or UI telemetry alter research truth.

## Major changes

### 1. Mission Control starts immediately

The first Skill action now hosts and opens Mission Control. It uses a stable
per-project URL and remains the same browser surface from initial intake through
the final report.

The live projection includes:

- current phase and operation;
- progress and elapsed time;
- worker heartbeat, stale detection, and reconnect state;
- current attempt and verifier activity;
- waits, user questions, failures, and recovery events;
- child-process progress through `$SISYFUS_PROGRESS_FILE`.

Operational telemetry is deliberately separate from Evidence. A process saying
"100% complete" cannot create a PASS or modify a Claim.

### 2. Proactive clarification before research

Sisyfus now treats three intake dimensions as blocking contracts:

1. **Scope** — included and excluded systems, markets, repositories, datasets,
   time periods, actions, constraints, and deliverables.
2. **Objective** — the artifact or decision to produce and a mechanically
   recognizable completion condition.
3. **Verification** — the test, backtest, benchmark, authority, rubric, or human
   gate that is allowed to reject the result.

When a material dimension is absent or contradictory, the Skill records:

```text
phase      CLARIFYING
status     NEEDS_USER
operation  research.intake.clarify
```

It asks one compact batch of unresolved questions, reuses information already
provided, and resumes only after locking Scope / Objective / Deliverables /
Verifier / Completion / Constraints.

### 3. Unified preflight and research Arena

The old standalone bootstrap splash has been removed. Before Claims exist, the
same Arena shell displays a preflight dependency map:

```text
Scope → Objective → Qualified Inputs → Claim Graph → Verifier → Autonomous Run
```

After TaskSpec compilation, the preflight nodes are replaced by the real Claim
Graph without switching visual products. Both phases share:

- `sisyfus-arena-broadcast-v1` theme tokens;
- broadcast top bar and score area;
- SVG map, node, edge, hero, and unit-card grammar;
- right-side feed, quest panel, waiting area, replay deck, caster bar, and tabs;
- responsive and reduced-motion behavior;
- a restyled live HUD using the same theme source.

### 4. Canonical 24×7 autonomy runtime

A single public autonomy API and a single versioned SQLite schema now implement:

- SQLite WAL with transactional mutations;
- opportunity deduplication and admission;
- durable Continuations and optimistic versions;
- opaque renewable leases and expiry-enforced writes;
- heartbeat fencing across planner, capability, and verifier calls;
- persisted Decisions and crash-safe `RESERVED` / `EXECUTED` recovery;
- stable idempotency keys and receipts;
- `UNKNOWN_COMMIT` blocking for unresolved non-replay-safe side effects;
- bounded retries, wake times, exhaustion, and terminal-state invariants;
- a continuous Supervisor suitable for systemd, containers, or Kubernetes.

### 5. Verifier-owned truth

The control flow is explicit:

```text
Sensor → Planner proposal → Policy admission → Capability execution
       → independent Verifier → Evidence → Reducer → terminal evaluator
```

The Planner cannot declare itself successful. Completion requires persisted PASS
evidence, and the five verdict outcomes retain distinct meanings:

```text
PASS / FAIL / INCONCLUSIVE / INVALID / ERROR
```

Final-attempt PASS can complete without consuming another execution attempt;
final INCONCLUSIVE becomes terminal rather than stranded.

### 6. Evidence-safe experience

Positive, negative, and operational experience remains linked to verifier
Evidence. Counts now derive from unique experience observations, so retrying or
replaying one Evidence ID cannot manufacture independent support or promote a
lesson falsely.

### 7. Safety and operational hardening

- typed Capability registry with unattended risk tiers;
- default unattended ceiling of R0/R1;
- exact `--root` handling;
- shell-command confirmation for research experiments;
- environment allowlisting for command planners;
- streamed, bounded subprocess output;
- process-group timeout termination;
- malformed or oversized sensor files quarantined independently;
- bounded sensor iteration and admission-before-persistence;
- versioned schema and incompatible-layout detection.

## New and important commands

```bash
# Start the one stable Mission Control surface
sisyfus research monitor-start --task "..." --objective "..." --root .

# Record that material user input is required
sisyfus research monitor-clarify \
  --missing scope --missing verification \
  --question "..." --root .

# Resume after locking the intake contract
sisyfus research monitor-resume --summary "..." --root .

# Operate the durable autonomy runtime
sisyfus-autonomy init
sisyfus-autonomy submit ...
sisyfus-autonomy status
sisyfus-autonomy recover
sisyfus-autonomy verify-chain
sisyfus-autonomy run --once ...
```

## Compatibility and operational notes

- Python 3.11 or newer is required.
- Mission Control hosting is enabled by default. Use `SISYFUS_AUTO_SERVE=0`
  only for deliberately headless operation.
- Use `SISYFUS_AUTO_OPEN=0` to keep hosting and activity recording while
  suppressing automatic browser opening.
- Existing research truth remains event-sourced. The autonomy database is a
  control plane; it does not make UI telemetry authoritative.
- High-risk external capabilities still require OS-level isolation, scoped
  secrets/network access, and provider-native reconciliation.

## Validation

The release candidate passes:

- full repository regression suite: **148 tests**;
- Python **3.11**, **3.12**, and **3.13** CI matrix;
- dedicated visual-continuity tests for bootstrap and full Arena;
- Mission Control lifecycle and clarification-gate tests;
- lease, recovery, idempotency, duplicate-evidence, sensor, and CLI coverage.

## Upgrade

```bash
python3 -m pip install --upgrade \
  "sisyfus @ git+https://github.com/DionisAI/sisyfus-skill@{TAG}"
sisyfus --version
```
'''
write(f"RELEASE_NOTES_v{VERSION}.md", RELEASE_NOTES)

TEST = f'''from __future__ import annotations

import tomllib
from pathlib import Path

import sisyfus


ROOT = Path(__file__).resolve().parents[1]
VERSION = "{VERSION}"
TAG = "{TAG}"


def test_release_version_is_consistent() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == VERSION
    assert sisyfus.__version__ == VERSION


def test_release_install_pins_and_notes_are_current() -> None:
    for relative in ("README.md", "README.zh-CN.md", "SKILL.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert f"@{{TAG}}" in text
        assert "@v0.7.4" not in text

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {{VERSION}} — {RELEASE_DATE}" in changelog
    assert "## Unreleased" not in changelog.split("## 0.7.4", 1)[0]

    notes = ROOT / f"RELEASE_NOTES_v{{VERSION}}.md"
    assert notes.exists()
    assert f"# Sisyfus {{TAG}}" in notes.read_text(encoding="utf-8")


def test_packaged_skill_matches_release_skill() -> None:
    canonical = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    packaged = (
        ROOT / "src" / "sisyfus" / "skill_assets" / "sisyfus-research" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert packaged == canonical
'''
write("tests/test_release_version.py", TEST)
