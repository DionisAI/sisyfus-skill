# Sisyfus v0.9.1

Released 2026-10-09. A presentation and robustness release for the research
Observatory, plus the Tech Lead work committed since v0.9.0.

## Research pages match the chat

- The Observatory and the bootstrap Mission Control use the Tech Lead chat's
  palette (paper, ink, lines, terracotta accent, success green), its Chinese-first
  fonts, the ✳ wordmark and lighter serif headings. The developer view
  (`/console`) uses the same palette instead of a dark theme.
- Live progress is a status pill in the top bar ("运行中 · 执行实验 · 34/40 folds")
  with a plain-language popover. Raw phases, operations and run IDs stay in a
  closed technical section. On phones it sits at the top of the page.
- The pill describes only the page's own run. Another study running in the same
  project reads as such; finished runs show no live pill.
- Refuted and exhausted runs are treated as finished: the status chip reads
  "已结束" and the study summary is available.
- The setup page counts finished setup steps, shows elapsed time instead of a
  heartbeat meter, and hides controls that could only be disabled.

## Robustness

- A run that records a `NaN` metric no longer renders a blank Observatory.
  Browser-facing JSON carries non-finite numbers as `"NaN"`/`"Infinity"`, and
  older pages parse leniently. The hash-chained `events.jsonl` is unchanged.
- If page data cannot be read, the page says so and the status chip shows
  "加载失败"; repeated or hung refreshes show "连接中断".
- Non-finite progress values no longer stop the activity heartbeat thread.
- "No recent update" is shown only after an observed heartbeat rhythm stops,
  or after an hour for one-shot records.

## Also since v0.9.0

- Evidence-gated Opus Tech Lead and Sol orchestration, conversational planning
  with explicit mission confirmation, read-only preflight, and project directory
  preparation from explicit chat instructions.

## Install or update

```bash
sisyfus update --check
sisyfus update --version 0.9.1 --yes
```

An older install without the `update` command needs the current installer once:

```bash
curl -fsSL https://raw.githubusercontent.com/DionisAI/sisyfus-skill/main/install.sh | bash -s -- --version 0.9.1
```

Restart the coding-agent session after upgrading so the installed Skill reloads.

## Validation and scope

UI changes were checked on real research runs at desktop and phone widths, with
WCAG AA contrast measured for text and status colours. The frozen
graph-redesign fingerprints were updated only for the functions changed by the
NaN fix (`_json_for_script`, `render_observatory`, `_normalise_progress`,
`ActivityTracker` and two new helpers). That fingerprint check runs on Python
3.13 and later, where `ast.dump` output matches the stored snapshot.
