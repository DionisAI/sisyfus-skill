#!/usr/bin/env bash
# One-shot installer for the sisyfus-research skill + engine.
#
#   From a clone:            ./install.sh
#   Straight from GitHub:    curl -fsSL https://raw.githubusercontent.com/DionisAI/sisyfus-skill/main/install.sh | bash
#   Remove everything:       ./install.sh --uninstall
#
# What it does (all idempotent, nothing touches system Python):
#   1. copies SKILL.md + references/ + templates/ into every detected skill
#      directory (~/.claude/skills/, ~/.agents/skills/) as `sisyfus-research`;
#   2. installs the engine into its own venv at ~/.sisyfus/venv and links the
#      CLI to ~/.local/bin/sisyfus.
set -euo pipefail

REPO_URL="https://github.com/DionisAI/sisyfus-skill"
SKILL_NAME="sisyfus-research"
VENV_DIR="${HOME}/.sisyfus/venv"
BIN_LINK="${HOME}/.local/bin/sisyfus"

say()  { printf '\033[1;32m[sisyfus]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[sisyfus]\033[0m %s\n' "$*"; }

skill_dirs() {
  local dirs=()
  [ -d "${HOME}/.claude/skills" ] && dirs+=("${HOME}/.claude/skills")
  [ -d "${HOME}/.agents/skills" ] && dirs+=("${HOME}/.agents/skills")
  [ ${#dirs[@]} -eq 0 ] && dirs+=("${HOME}/.claude/skills")
  printf '%s\n' "${dirs[@]}"
}

if [ "${1:-}" = "--uninstall" ]; then
  while IFS= read -r dir; do
    rm -rf "${dir}/${SKILL_NAME}" && say "removed ${dir}/${SKILL_NAME}"
  done < <(skill_dirs)
  rm -rf "${HOME}/.sisyfus/venv" && say "removed ${VENV_DIR}"
  rm -f "${BIN_LINK}" && say "removed ${BIN_LINK}"
  say "uninstalled. Per-project .sisyfus/ state trees are untouched."
  exit 0
fi

# --- locate the skill source (local clone, or fetch when piped) --------------
SRC="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd)"
CLEANUP=""
if [ ! -f "${SRC}/SKILL.md" ] || [ ! -d "${SRC}/references" ]; then
  command -v git >/dev/null || { warn "git is required"; exit 1; }
  SRC="$(mktemp -d /tmp/sisyfus-skill.XXXXXX)"
  CLEANUP="${SRC}"
  say "fetching ${REPO_URL} ..."
  git clone --quiet --depth 1 "${REPO_URL}" "${SRC}"
fi
trap '[ -n "${CLEANUP}" ] && rm -rf "${CLEANUP}"' EXIT

# --- 1. install the skill files ---------------------------------------------
while IFS= read -r dir; do
  target="${dir}/${SKILL_NAME}"
  mkdir -p "${target}"
  cp "${SRC}/SKILL.md" "${target}/SKILL.md"
  rm -rf "${target}/references" "${target}/templates"
  cp -R "${SRC}/references" "${SRC}/templates" "${target}/"
  say "skill installed -> ${target}"
done < <(skill_dirs)

# --- 2. install the engine in its own venv ----------------------------------
PY="$(command -v python3 || true)"
[ -z "${PY}" ] && { warn "python3 (>= 3.11) is required"; exit 1; }
"${PY}" - <<'EOF' || { printf '\033[1;33m[sisyfus]\033[0m python3 >= 3.11 required\n'; exit 1; }
import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)
EOF

mkdir -p "$(dirname "${VENV_DIR}")" "$(dirname "${BIN_LINK}")"
[ -x "${VENV_DIR}/bin/python" ] || "${PY}" -m venv "${VENV_DIR}"
say "installing engine into ${VENV_DIR} ..."
"${VENV_DIR}/bin/python" -m pip install --quiet --upgrade pip
"${VENV_DIR}/bin/python" -m pip install --quiet --force-reinstall "${SRC}"
ln -sf "${VENV_DIR}/bin/sisyfus" "${BIN_LINK}"

# --- verify ------------------------------------------------------------------
VERSION="$("${BIN_LINK}" --version)"
say "engine ready: sisyfus ${VERSION} (${BIN_LINK})"
case ":${PATH}:" in
  *":${HOME}/.local/bin:"*) ;;
  *) warn "~/.local/bin is not on your PATH — add:  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac
say "try it:  mkdir /tmp/sisyfus-demo && cd /tmp/sisyfus-demo && sisyfus init && sisyfus research demo --root . && sisyfus research serve latest --open --root ."
