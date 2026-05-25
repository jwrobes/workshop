#!/usr/bin/env bash
# setup.sh — idempotent installer for speak_to_code
#
# What it does:
#   1. Preflight: checks sox (rec), mlx_whisper, llm.
#   2. Symlinks ~/.local/bin/dictate -> this folder's dictate script.
#   3. Seeds ~/.config/dictate/context.md from dictate-context.md.example if missing.
#
# Flags:
#   --dry-run    Print what would happen; no filesystem changes.
#   --uninstall  Remove the dictate symlink (context.md is preserved).

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_SYMLINK="$HOME/.local/bin/dictate"
CONTEXT_DIR="$HOME/.config/dictate"
CONTEXT_FILE="$CONTEXT_DIR/context.md"
CONTEXT_EXAMPLE="$SRC_DIR/dictate-context.md.example"

DRY_RUN=0
UNINSTALL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)   DRY_RUN=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help)
      sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown flag: $1" >&2; exit 1 ;;
  esac
  shift
done

say() { printf '[setup] %s\n' "$*"; }
run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run] %s\n' "$*"
  else
    eval "$@"
  fi
}

# ── Uninstall ────────────────────────────────────────────────────────────────
if [[ "$UNINSTALL" == "1" ]]; then
  [[ -L "$BIN_SYMLINK" ]] && run "rm -f '$BIN_SYMLINK'" && say "removed $BIN_SYMLINK"
  say "context.md preserved at $CONTEXT_FILE"
  exit 0
fi

# ── Preflight ────────────────────────────────────────────────────────────────
ok=1

if ! command -v rec >/dev/null 2>&1; then
  echo "MISSING: rec (SoX) — brew install sox" >&2; ok=0
else
  say "preflight: rec (sox) ✓"
fi

if ! command -v mlx_whisper >/dev/null 2>&1; then
  echo "MISSING: mlx_whisper — pip install mlx-whisper" >&2; ok=0
else
  say "preflight: mlx_whisper ✓"
fi

if ! command -v llm >/dev/null 2>&1; then
  echo "MISSING: llm — pip install llm  (then: llm keys set openai)" >&2; ok=0
else
  say "preflight: llm ✓"
fi

if [[ "$ok" == "0" ]]; then
  echo "" >&2
  echo "Fix the above, then re-run setup.sh." >&2
  exit 1
fi

# ── Symlink dictate ──────────────────────────────────────────────────────────
run "mkdir -p '$(dirname "$BIN_SYMLINK")'"
run "ln -sfn '$SRC_DIR/dictate' '$BIN_SYMLINK'"
say "symlinked $BIN_SYMLINK -> $SRC_DIR/dictate"

# ── Seed context.md ──────────────────────────────────────────────────────────
run "mkdir -p '$CONTEXT_DIR'"
if [[ ! -f "$CONTEXT_FILE" ]]; then
  run "cp '$CONTEXT_EXAMPLE' '$CONTEXT_FILE'"
  say "seeded $CONTEXT_FILE from dictate-context.md.example"
  say "Edit it to match your vocabulary: \$EDITOR $CONTEXT_FILE"
else
  say "preserved existing $CONTEXT_FILE"
fi

say ""
say "Done. Test with:"
say "  dictate --raw       # record + transcribe only"
say "  dictate             # full pipeline"
