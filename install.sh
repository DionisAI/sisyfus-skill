#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${SISYFUS_REPO_URL:-https://github.com/DionisAI/sisyfus-skill}"
REPOSITORY="${SISYFUS_UPDATE_REPOSITORY:-DionisAI/sisyfus-skill}"
ENGINE_HOME="${SISYFUS_ENGINE_HOME:-${HOME}/.local/share/sisyfus}"
BIN_DIR="${SISYFUS_BIN_DIR:-${HOME}/.local/bin}"
CHANNEL="stable"
TARGET_VERSION=""
ACTION="install"
ALLOW_ACTIVE=0
ENABLE_AUTO=0
AUTO_MODE="notify"
AUTO_INTERVAL=24

say()  { printf '\033[1;32m[sisyfus]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[sisyfus]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[sisyfus]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: install.sh [options]
  --version X.Y.Z             Install one exact release
  --channel stable|beta|edge  Select update channel (default: stable)
  --check                     Check only; never install
  --allow-active              Override active-work protection
  --enable-auto               Configure scheduled checks after install
  --auto-mode notify|auto     Notify only or install stable automatically
  --interval-hours N          Scheduled interval (minimum 15 minutes)
  --uninstall                 Remove engine and installed Skill files
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version) TARGET_VERSION="${2:?missing version}"; shift 2 ;;
    --channel) CHANNEL="${2:?missing channel}"; shift 2 ;;
    --check) ACTION="check"; shift ;;
    --allow-active) ALLOW_ACTIVE=1; shift ;;
    --enable-auto) ENABLE_AUTO=1; shift ;;
    --auto-mode) AUTO_MODE="${2:?missing mode}"; shift 2 ;;
    --interval-hours) AUTO_INTERVAL="${2:?missing interval}"; shift 2 ;;
    --uninstall) ACTION="uninstall"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

case "$CHANNEL" in stable|beta|edge) ;; *) die "invalid channel: $CHANNEL" ;; esac
case "$AUTO_MODE" in notify|auto) ;; *) die "invalid auto mode: $AUTO_MODE" ;; esac
if [ "$AUTO_MODE" = auto ] && [ "$CHANNEL" != stable ]; then
  die "automatic installation is restricted to the stable channel"
fi

skill_dirs() {
  if [ -n "${SISYFUS_SKILL_DIRS:-}" ]; then
    printf '%s' "$SISYFUS_SKILL_DIRS" | tr ':' '\n'
    return
  fi
  local found=0
  for directory in "$HOME/.claude/skills" "$HOME/.agents/skills"; do
    if [ -d "$directory" ]; then
      printf '%s\n' "$directory"
      found=1
    fi
  done
  [ "$found" -eq 0 ] && printf '%s\n' "$HOME/.claude/skills"
}

if [ "$ACTION" = uninstall ]; then
  if [ -x "$BIN_DIR/sisyfus" ]; then
    "$BIN_DIR/sisyfus" update --disable-auto --yes >/dev/null 2>&1 || true
  fi
  while IFS= read -r directory; do
    rm -rf "$directory/sisyfus-research"
  done < <(skill_dirs)
  rm -rf "$ENGINE_HOME"
  rm -f "$BIN_DIR/sisyfus" "$BIN_DIR/sisyfus-autonomy"
  say "uninstalled; project .sisyfus state is untouched"
  exit 0
fi

PYTHON="$(command -v python3 || true)"
[ -n "$PYTHON" ] || die "python3 >= 3.11 is required"
"$PYTHON" - <<'PY' || die "python3 >= 3.11 is required"
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY

resolve_ref() {
  "$PYTHON" - "$CHANNEL" "$TARGET_VERSION" "$REPOSITORY" <<'PY'
import json
import re
import sys
import urllib.error
import urllib.request

channel, requested, repository = sys.argv[1:]
api = "https://api.github.com"

def get(url):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "sisyfus-installer",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))

def semver(value):
    match = re.fullmatch(
        r"v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?", value
    )
    if not match:
        return None
    prerelease = match.group(4)
    pre_key = (1,) if prerelease is None else (0, prerelease)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)), pre_key)

if requested:
    print("v" + requested.lstrip("v"))
    raise SystemExit(0)
if channel == "edge":
    print("main")
    raise SystemExit(0)

if channel == "stable":
    try:
        release = get(f"{api}/repos/{repository}/releases/latest")
        print(release["tag_name"])
        raise SystemExit(0)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    tags = get(f"{api}/repos/{repository}/tags?per_page=100")
    candidates = []
    for item in tags:
        parsed = semver(str(item.get("name") or ""))
        if parsed and parsed[3] == (1,):
            candidates.append((parsed, item["name"]))
    if not candidates:
        raise SystemExit("no stable semantic release found")
    print(max(candidates)[1])
    raise SystemExit(0)

releases = get(f"{api}/repos/{repository}/releases?per_page=100")
candidates = []
for release in releases:
    if release.get("draft"):
        continue
    parsed = semver(str(release.get("tag_name") or ""))
    if parsed:
        candidates.append((parsed, release["tag_name"]))
if not candidates:
    raise SystemExit("no semantic beta/stable release found")
print(max(candidates)[1])
PY
}

if [ "$ACTION" = check ] && [ -x "$BIN_DIR/sisyfus" ]; then
  args=(update --check --channel "$CHANNEL")
  [ -n "$TARGET_VERSION" ] && args+=(--version "$TARGET_VERSION")
  exec "$BIN_DIR/sisyfus" "${args[@]}"
fi
if [ "$ACTION" = check ]; then
  REF="$(resolve_ref)" || die "unable to resolve requested release"
  say "Sisyfus is not installed; selected release is $REF"
  exit 0
fi

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
SOURCE=""
CLEANUP=""
USE_LOCAL=0
if [ -n "$SCRIPT_SOURCE" ] && [ -f "$SCRIPT_SOURCE" ] && [ -z "$TARGET_VERSION" ]; then
  SOURCE="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
  if [ -f "$SOURCE/SKILL.md" ] && [ -d "$SOURCE/src/sisyfus" ]; then
    USE_LOCAL=1
  fi
fi

if [ "$USE_LOCAL" -eq 0 ]; then
  command -v git >/dev/null || die "git is required"
  REF="$(resolve_ref)" || die "unable to resolve requested release"
  SOURCE="$(mktemp -d "${TMPDIR:-/tmp}/sisyfus-skill.XXXXXX")"
  CLEANUP="$SOURCE"
  say "fetching $REPOSITORY@$REF"
  git clone --quiet --depth 1 --branch "$REF" "$REPO_URL" "$SOURCE" \
    || die "failed to fetch $REF"
  if [ ! -f "$SOURCE/src/sisyfus/updater.py" ]; then
    die "$REF predates the versioned updater; install v0.8.1 or newer"
  fi
else
  REF="local"
fi
trap '[ -n "$CLEANUP" ] && rm -rf "$CLEANUP"' EXIT

export SISYFUS_ENGINE_HOME="$ENGINE_HOME"
export SISYFUS_BIN_DIR="$BIN_DIR"
if [ -z "${SISYFUS_SKILL_DIRS:-}" ]; then
  directories=()
  while IFS= read -r directory; do directories+=("$directory"); done < <(skill_dirs)
  export SISYFUS_SKILL_DIRS="$(IFS=:; printf '%s' "${directories[*]}")"
fi

ALLOW="False"
[ "$ALLOW_ACTIVE" -eq 1 ] && ALLOW="True"
PYTHONPATH="$SOURCE/src" "$PYTHON" - "$SOURCE" "$CHANNEL" "$REF" "$ALLOW" <<'PY'
import json
import sys
from sisyfus.updater import bootstrap_from_source

source, channel, ref, allow = sys.argv[1:]
result = bootstrap_from_source(
    source,
    channel=channel,
    tag=ref if ref.startswith("v") else None,
    allow_active=allow == "True",
)
print(json.dumps(result, sort_keys=True))
PY

VERSION="$($BIN_DIR/sisyfus --version)"
say "engine and Skill ready: Sisyfus $VERSION"
say "restart the coding-agent session so it reloads the Skill"
if [ "$ENABLE_AUTO" -eq 1 ]; then
  "$BIN_DIR/sisyfus" update \
    --enable-auto \
    --mode "$AUTO_MODE" \
    --channel "$CHANNEL" \
    --interval-hours "$AUTO_INTERVAL" \
    --yes
fi
