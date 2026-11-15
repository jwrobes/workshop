#!/usr/bin/env bash
# epic_conductor/setup.sh: symlink the epic-* helpers into ~/.local/bin and the
# conducting-epics skill into ~/.claude/skills. Idempotent.
# usage: setup.sh [--dry-run] [--force]
#   BIN_DIR / SKILLS_DIR override the install targets.
set -euo pipefail
SRC="${BASH_SOURCE[0]}"; while [ -h "$SRC" ]; do D="$(cd -P "$(dirname "$SRC")" && pwd)"; SRC="$(readlink "$SRC")"; [[ $SRC != /* ]] && SRC="$D/$SRC"; done
ROOT="$(cd -P "$(dirname "$SRC")" && pwd)"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
SKILLS_DIR="${SKILLS_DIR:-$HOME/.claude/skills}"
dry=false; force=false
for a in "$@"; do
  case "$a" in
    --dry-run) dry=true ;;
    --force) force=true ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $a" >&2; exit 2 ;;
  esac
done

link() { # link <target> <dest>
  local target="$1" dest="$2"
  if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$target" ]; then echo "ok       $dest"; return; fi
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    if ! $force; then echo "SKIP     $dest exists and points elsewhere (use --force)" >&2; return; fi
    $dry || rm -rf "$dest"
  fi
  if $dry; then echo "DRY link $dest -> $target"; else ln -s "$target" "$dest"; echo "linked   $dest -> $target"; fi
}

$dry || mkdir -p "$BIN_DIR" "$SKILLS_DIR"
for f in epic-spawn epic-adopt epic-kill epic-log epic-status epic-check; do
  link "$ROOT/bin/$f" "$BIN_DIR/$f"
done
link "$ROOT/skills/conducting-epics" "$SKILLS_DIR/conducting-epics"

WSNEW="$ROOT/../workspace_init/wsnew.sh"
if ! command -v wsnew >/dev/null 2>&1 && [ -f "$WSNEW" ]; then
  link "$(cd "$(dirname "$WSNEW")" && pwd)/wsnew.sh" "$BIN_DIR/wsnew"
fi

echo
for c in gh tmux claude wsnew; do
  command -v "$c" >/dev/null 2>&1 || [ "$c" = wsnew -a -f "$WSNEW" ] || echo "warning: '$c' not found on PATH" >&2
done
[ -d "$SKILLS_DIR/full-path-github" ] || [ -L "$SKILLS_DIR/full-path-github" ] || \
  echo "warning: full-path-github skill not installed (run skills/install.sh full-path-github)" >&2
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "note: $BIN_DIR is not on PATH" >&2 ;; esac
$dry && echo "dry run: nothing written" || echo "done. Start a new Claude session to load the skill."
