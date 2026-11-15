#!/usr/bin/env bash
# Symlink skills from this repo into your agent's skills folder.
#
# Usage:
#   skills/install.sh                    # all skills -> ~/.claude/skills
#   skills/install.sh grill-me           # one skill
#   skills/install.sh --cursor           # target ~/.cursor/skills instead
#   skills/install.sh --force            # overwrite existing entries
#
# Includes tool-bound skills (<tool>/skills/<name>) as well as skills/<name>.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$HOME/.claude/skills"; force=false; only=""
for a in "$@"; do
  case "$a" in
    --cursor) TARGET="$HOME/.cursor/skills" ;;
    --force|-f) force=true ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) only="$a" ;;
  esac
done
mkdir -p "$TARGET"

linked=0; skipped=0
for dir in "$ROOT"/skills/*/ "$ROOT"/*/skills/*/; do
  [ -f "$dir/SKILL.md" ] || continue
  name="$(basename "$dir")"
  [ -n "$only" ] && [ "$only" != "$name" ] && continue
  dest="$TARGET/$name"
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    if $force; then rm -rf "$dest"; else echo "skip   $name (exists; use --force)"; skipped=$((skipped+1)); continue; fi
  fi
  ln -s "${dir%/}" "$dest"; echo "link   $name"; linked=$((linked+1))
done
echo "linked=$linked skipped=$skipped target=$TARGET"
