#!/usr/bin/env bash
# setup.sh — idempotent installer for smart_screenshots (snapname)
#
# What it does:
#   1. Checks that the configured vision command (SNAPNAME_VISION_CMD; default `claude`) is on PATH.
#   2. Symlinks ~/.local/bin/snapname -> this folder's snapname script.
#   3. Points macOS screenshots at the watch folder (default ~/workspace/Screenshots) if they
#      aren't already, and turns off the floating thumbnail so files land immediately.
#   4. Writes and loads the launchd agent ~/Library/LaunchAgents/com.jwrobes.snapname.plist,
#      which runs `snapname process` whenever the watch folder changes.
#
# Run it from a stable clone, not a temporary worktree: the symlink and the agent point at
# wherever this script lives.
#
# Flags:
#   --dry-run       Print what would happen; no changes.
#   --keep-thumbnail Leave the floating thumbnail preview on (files then land ~5s later).
#   --uninstall     Unload the agent and remove the symlink. Leaves screenshot settings alone.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_SYMLINK="$HOME/.local/bin/snapname"
WATCH_DIR="$(python3 "$SRC_DIR/snapname" config watch_dir)"

DRY_RUN=0
UNINSTALL=0
KEEP_THUMBNAIL=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)        DRY_RUN=1 ;;
    --uninstall)      UNINSTALL=1 ;;
    --keep-thumbnail) KEEP_THUMBNAIL=1 ;;
    -h|--help)        sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 1 ;;
  esac
  shift
done

say() { printf '[setup] %s\n' "$*"; }
do_or_say() { if [[ $DRY_RUN -eq 1 ]]; then say "would run: $*"; else "$@"; fi; }

if [[ $UNINSTALL -eq 1 ]]; then
  do_or_say python3 "$SRC_DIR/snapname" uninstall-agent
  if [[ -L "$BIN_SYMLINK" ]]; then do_or_say rm "$BIN_SYMLINK"; fi
  say "uninstalled (screenshot location and thumbnail settings unchanged)"
  exit 0
fi

VISION_CMD="$(python3 "$SRC_DIR/snapname" config vision_cmd)"
VISION_BIN="$(printf '%s' "$VISION_CMD" | awk '{print $1}')"
if command -v "$VISION_BIN" >/dev/null; then
  say "vision command found: $VISION_BIN"
elif [[ $DRY_RUN -eq 1 ]]; then
  say "vision command '$VISION_BIN' not found; a real run stops here (install it or set SNAPNAME_VISION_CMD)"
else
  say "vision command '$VISION_BIN' not found. Install it (e.g. Claude Code's \`claude\`, or \`pip install llm\`)"
  say "or set SNAPNAME_VISION_CMD to a command that takes an image; see README.md"
  exit 1
fi

mkdir -p "$HOME/.local/bin"
if [[ "$(readlink "$BIN_SYMLINK" 2>/dev/null)" != "$SRC_DIR/snapname" ]]; then
  do_or_say ln -sfn "$SRC_DIR/snapname" "$BIN_SYMLINK"
  say "symlink $BIN_SYMLINK -> $SRC_DIR/snapname"
else
  say "symlink already in place"
fi

current_location="$(defaults read com.apple.screencapture location 2>/dev/null || true)"
if [[ "${current_location%/}" != "${WATCH_DIR%/}" ]]; then
  do_or_say mkdir -p "$WATCH_DIR"
  do_or_say defaults write com.apple.screencapture location "$WATCH_DIR"
  say "screenshot location: ${current_location:-default} -> $WATCH_DIR"
else
  say "screenshot location already $WATCH_DIR"
fi
if [[ $KEEP_THUMBNAIL -eq 0 ]]; then
  do_or_say defaults write com.apple.screencapture show-thumbnail -bool false
  say "floating thumbnail off (pass --keep-thumbnail to keep it)"
fi
do_or_say killall SystemUIServer 2>/dev/null || true

if [[ $DRY_RUN -eq 1 ]]; then
  say "would install launchd agent watching $WATCH_DIR"
else
  python3 "$SRC_DIR/snapname" install-agent
fi

say "done. Take a screenshot (cmd-shift-4), then: snapname log"
