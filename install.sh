#!/usr/bin/env bash
# One-shot installer for the sisyfus-research skill + engine.
#
#   From a clone:            ./install.sh
#   Straight from GitHub:    curl -fsSL https://raw.githubusercontent.com/DionisAI/sisyfus-skill/main/install.sh | bash
#   Remove everything:       ./install.sh --uninstall
#
# What it does (all idempotent, no sudo, nothing touches system Python):
#   1. copies SKILL.md + references/ + templates/ into every detected skill
#      directory (~/.claude/skills/, ~/.agents/skills/) as `sisyfus-research`;
#   2. installs the engine under ~/.local/share/sisyfus and links the CLI to
#      ~/.local/bin/sisyfus. Preferred route is a venv + pip; on machines
#      missing python3-venv/ensurepip/pip it falls back to a pure-stdlib
#      source install (sisyfus has zero runtime dependencies).
set -euo pipefail

REPO_URL="https://github.com/DionisAI/sisyfus-skill"
SKILL_NAME="sisyfus-research"
ENGINE_HOME="${SISYFUS_ENGINE_HOME:-${HOME}/.local/share/sisyfus}"
VENV_DIR="${ENGINE_HOME}/venv"
LIB_DIR="${ENGINE_HOME}/lib"
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
  rm -rf "${ENGINE_HOME}" "${HOME}/.sisyfus/venv" && say "removed ${ENGINE_HOME}"
  rm -f "${BIN_LINK}" && say "removed ${BIN_LINK}"
  say "uninstalled. Per-project .sisyfus/ state trees are untouched."
  exit 0
fi

# --- locate the skill source (local clone, or fetch when piped) --------------
SRC="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd)"
CLEANUP=""
if [ ! -f "${SRC}/SKILL.md" ] || [ ! -d "${SRC}/references" ]; then
  command -v git >/dev/null || { warn "git is required"; exit 1; }
  SRC="$(mktemp -d "${TMPDIR:-/tmp}/sisyfus-skill.XXXXXX")"
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

# --- 2. install the engine ---------------------------------------------------
PY="$(command -v python3 || true)"
[ -z "${PY}" ] && { warn "python3 (>= 3.11) is required"; exit 1; }
"${PY}" - <<'EOF' || { printf '\033[1;33m[sisyfus]\033[0m python3 >= 3.11 required (found %s)\n' "$("${PY}" -V 2>&1)"; exit 1; }
import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)
EOF
mkdir -p "${ENGINE_HOME}" "$(dirname "${BIN_LINK}")"

install_engine_venv() {
  [ -n "${SISYFUS_FORCE_STDLIB:-}" ] && return 1
  if [ ! -x "${VENV_DIR}/bin/python" ]; then
    "${PY}" -m venv "${VENV_DIR}" 2>/dev/null \
      || "${PY}" -m venv --without-pip "${VENV_DIR}" 2>/dev/null \
      || return 1
  fi
  local vpy="${VENV_DIR}/bin/python"
  if ! "${vpy}" -m pip --version >/dev/null 2>&1; then
    "${vpy}" -m ensurepip --upgrade >/dev/null 2>&1 || return 1
  fi
  "${vpy}" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
  "${vpy}" -m pip install --quiet --force-reinstall "${SRC}" || return 1
  rm -f "${BIN_LINK}"
  ln -s "${VENV_DIR}/bin/sisyfus" "${BIN_LINK}"
  say "engine installed via venv+pip (${VENV_DIR})"
}

install_engine_stdlib() {
  # sisyfus is pure standard library: a source copy plus a launcher is a
  # complete install. No venv, no pip, no ensurepip, no sudo, no network
  # beyond the clone itself.
  rm -rf "${LIB_DIR}"
  mkdir -p "${LIB_DIR}"
  cp -R "${SRC}/src/sisyfus" "${LIB_DIR}/"
  rm -f "${BIN_LINK}"
  cat > "${BIN_LINK}" <<EOF
#!/usr/bin/env python3
import sys
sys.path.insert(0, "${LIB_DIR}")
from sisyfus.cli import main
sys.exit(main())
EOF
  chmod +x "${BIN_LINK}"
  say "engine installed from source, no pip needed (${LIB_DIR})"
}

if ! install_engine_venv; then
  warn "venv/pip route unavailable (python3-venv or ensurepip missing?) — using the pure-stdlib install"
  install_engine_stdlib
fi

# --- verify ------------------------------------------------------------------
VERSION="$("${BIN_LINK}" --version)" || { warn "install verification failed"; exit 1; }
say "engine ready: sisyfus ${VERSION} (${BIN_LINK})"
case ":${PATH}:" in
  *":${HOME}/.local/bin:"*) ;;
  *) warn "~/.local/bin is not on your PATH — add:  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac
say "try it:  mkdir /tmp/sisyfus-demo && cd /tmp/sisyfus-demo && sisyfus init && sisyfus research demo --root . && sisyfus research serve latest --open --root ."
