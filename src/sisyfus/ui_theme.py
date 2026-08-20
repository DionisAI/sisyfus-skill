"""Shared visual language for bootstrap Mission Control and the full Arena."""

from __future__ import annotations

ARENA_THEME_ID = "sisyfus-arena-broadcast-v1"

# Keep this block deliberately small: it is injected into both documents and is
# the single source of truth for palette, typography, sizing, and motion.
ARENA_THEME_CSS = r"""
:root {
  color-scheme: dark;
  --arena:oklch(0.17 0.018 75);
  --arena-deep:oklch(0.13 0.015 75);
  --panel:oklch(0.21 0.02 80);
  --panel-strong:oklch(0.18 0.02 78);
  --surface:oklch(0.18 0.018 78);
  --surface-hover:oklch(0.25 0.022 80);
  --line:oklch(0.32 0.03 85);
  --ink:oklch(0.93 0.02 90);
  --muted:oklch(0.66 0.03 85);
  --radiant:oklch(0.78 0.17 150);
  --dire:oklch(0.62 0.21 25);
  --gold:oklch(0.82 0.13 88);
  --amber:oklch(0.78 0.14 75);
  --ghost:oklch(0.62 0.12 310);
  --hp:oklch(0.66 0.19 30);
  --mana:oklch(0.7 0.1 230);
  --stage-height:min(72vh, 700px);
  --right-column:336px;
  --shadow-deep:0 24px 70px oklch(0 0 0 / .58);
  --font-sans:-apple-system,"Helvetica Neue","PingFang SC","Microsoft YaHei",sans-serif;
  --font-mono:ui-monospace,Menlo,Consolas,monospace;
  --ease-out:cubic-bezier(.16,1,.3,1);
}
* { box-sizing:border-box; }
html { min-height:100%; background:var(--arena-deep); }
body {
  min-height:100vh;
  margin:0;
  background:var(--arena-deep);
  color:var(--ink);
  font-family:var(--font-sans);
}
button,input,select { font:inherit; }
.caps { text-transform:uppercase; letter-spacing:.14em; font-weight:800; }
.mono { font-family:var(--font-mono); }
"""
