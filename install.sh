#!/usr/bin/env bash
set -euo pipefail
REPO_URL="https://github.com/DionisAI/sisyfus-skill"
REPOSITORY="DionisAI/sisyfus-skill"
SKILL_NAME="sisyfus-research"
ENGINE_HOME="${SISYFUS_ENGINE_HOME:-${HOME}/.local/share/sisyfus}"
BIN_DIR="${SISYFUS_BIN_DIR:-${HOME}/.local/bin}"
CHANNEL="stable"; TARGET_VERSION=""; ACTION="install"; ALLOW_ACTIVE=0; ENABLE_AUTO=0; AUTO_MODE="notify"; AUTO_INTERVAL=24
say(){ printf '[1;32m[sisyfus][0m %s
' "$*"; }
warn(){ printf '[1;33m[sisyfus][0m %s
' "$*" >&2; }
die(){ printf '[1;31m[sisyfus][0m %s
' "$*" >&2; exit 1; }
usage(){ cat <<'EOF'
Usage: install.sh [options]
  --version X.Y.Z
  --channel stable|beta|edge
  --check
  --allow-active
  --enable-auto
  --auto-mode notify|auto
  --interval-hours N
  --uninstall
EOF
}
while [ "$#" -gt 0 ]; do case "$1" in --version) TARGET_VERSION="${2:?}";shift 2;;--channel) CHANNEL="${2:?}";shift 2;;--check)ACTION="check";shift;;--allow-active)ALLOW_ACTIVE=1;shift;;--enable-auto)ENABLE_AUTO=1;shift;;--auto-mode)AUTO_MODE="${2:?}";shift 2;;--interval-hours)AUTO_INTERVAL="${2:?}";shift 2;;--uninstall)ACTION="uninstall";shift;;-h|--help)usage;exit 0;;*)die "unknown option: $1";;esac;done
case "$CHANNEL" in stable|beta|edge);;*)die "invalid channel";;esac
skill_dirs(){ if [ -n "${SISYFUS_SKILL_DIRS:-}" ];then printf '%s' "$SISYFUS_SKILL_DIRS"|tr ':' '
';return;fi;local found=0;for dir in "$HOME/.claude/skills" "$HOME/.agents/skills";do if [ -d "$dir" ];then printf '%s
' "$dir";found=1;fi;done;[ "$found" -eq 0 ]&&printf '%s
' "$HOME/.claude/skills"; }
if [ "$ACTION" = uninstall ];then if [ -x "$BIN_DIR/sisyfus" ];then "$BIN_DIR/sisyfus" update --disable-auto --yes >/dev/null 2>&1||true;fi;while IFS= read -r dir;do rm -rf "$dir/$SKILL_NAME";done < <(skill_dirs);rm -rf "$ENGINE_HOME";rm -f "$BIN_DIR/sisyfus" "$BIN_DIR/sisyfus-autonomy";say "uninstalled; project state untouched";exit 0;fi
if [ "$ACTION" = check ]&&[ -x "$BIN_DIR/sisyfus" ];then args=(update --check --channel "$CHANNEL");[ -n "$TARGET_VERSION" ]&&args+=(--version "$TARGET_VERSION");exec "$BIN_DIR/sisyfus" "${args[@]}";fi
PY="$(command -v python3||true)";[ -n "$PY" ]||die "python3 >=3.11 required";"$PY" - <<'PY'||die "python3 >=3.11 required"
import sys;raise SystemExit(0 if sys.version_info>=(3,11) else 1)
PY
resolve_ref(){ "$PY" - "$CHANNEL" "$TARGET_VERSION" <<'PY'
import json,re,sys,urllib.request
repo="DionisAI/sisyfus-skill";channel,version=sys.argv[1:]
def get(url):
 r=urllib.request.Request(url,headers={"Accept":"application/vnd.github+json","User-Agent":"sisyfus-installer"});return json.loads(urllib.request.urlopen(r,timeout=20).read())
if version:print("v"+version.lstrip("v"));raise SystemExit
if channel=="edge":print("main");raise SystemExit
try:
 release=get(f"https://api.github.com/repos/{repo}/releases/latest") if channel=="stable" else max([x for x in get(f"https://api.github.com/repos/{repo}/releases?per_page=100") if not x.get("draft")],key=lambda x:x.get("published_at") or "")
 print(release["tag_name"])
except Exception:
 try:
  tags=get(f"https://api.github.com/repos/{repo}/tags?per_page=100");versions=[]
  for item in tags:
   m=re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:-(.*))?$",item.get("name",""))
   if m and not m.group(4):versions.append((tuple(map(int,m.groups()[:3])),item["name"]))
  print(max(versions)[1] if versions else "main")
 except Exception:print("main")
PY
}
SRC="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" 2>/dev/null&&pwd)";CLEANUP="";USE_LOCAL=0
if [ -f "$SRC/SKILL.md" ]&&[ -d "$SRC/src/sisyfus" ]&&[ -z "$TARGET_VERSION" ];then USE_LOCAL=1;fi
if [ "$USE_LOCAL" -eq 0 ];then command -v git >/dev/null||die "git required";REF="$(resolve_ref)";SRC="$(mktemp -d ${TMPDIR:-/tmp}/sisyfus-skill.XXXXXX)";CLEANUP="$SRC";say "fetching $REPOSITORY@$REF";git clone --quiet --depth 1 --branch "$REF" "$REPO_URL" "$SRC"||die "fetch failed";if [ ! -f "$SRC/src/sisyfus/updater.py" ];then warn "$REF predates updater; bootstrapping main";rm -rf "$SRC";SRC="$(mktemp -d ${TMPDIR:-/tmp}/sisyfus-skill.XXXXXX)";CLEANUP="$SRC";git clone --quiet --depth 1 --branch main "$REPO_URL" "$SRC";REF=main;fi;else REF=local;fi
trap '[ -n "$CLEANUP" ]&&rm -rf "$CLEANUP"' EXIT
export SISYFUS_ENGINE_HOME="$ENGINE_HOME" SISYFUS_BIN_DIR="$BIN_DIR";if [ -z "${SISYFUS_SKILL_DIRS:-}" ];then dirs=();while IFS= read -r dir;do dirs+=("$dir");done < <(skill_dirs);export SISYFUS_SKILL_DIRS="$(IFS=:;echo "${dirs[*]}")";fi
ALLOW=False;[ "$ALLOW_ACTIVE" -eq 1 ]&&ALLOW=True
PYTHONPATH="$SRC/src" "$PY" - "$SRC" "$CHANNEL" "$REF" "$ALLOW" <<'PY'
import json,sys
from sisyfus.updater import bootstrap_from_source
source,channel,ref,allow=sys.argv[1:];print(json.dumps(bootstrap_from_source(source,channel=channel,tag=ref if ref.startswith("v") else None,allow_active=allow=="True"),sort_keys=True))
PY
VERSION="$("$BIN_DIR/sisyfus" --version)";say "engine ready: sisyfus $VERSION";say "restart coding-agent session"
if [ "$ENABLE_AUTO" -eq 1 ];then "$BIN_DIR/sisyfus" update --enable-auto --mode "$AUTO_MODE" --channel "$CHANNEL" --interval-hours "$AUTO_INTERVAL" --yes;fi
