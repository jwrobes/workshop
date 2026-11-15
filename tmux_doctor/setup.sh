#!/usr/bin/env bash
# tmux_doctor/setup.sh — verify environment, seed config, preview the keep/kill split
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$HOME/.config/tmux-doctor"

echo "=== tmux-doctor setup ==="
echo ""

# 1. tmux present
if command -v tmux >/dev/null 2>&1; then
  echo "tmux: $(tmux -V)"
else
  echo "tmux: NOT FOUND — install tmux first (brew install tmux)"
  exit 1
fi

# 2. tmux server running?
if tmux list-sessions >/dev/null 2>&1; then
  echo "tmux server: running ($(tmux list-sessions 2>/dev/null | wc -l | tr -d ' ') sessions)"
else
  echo "tmux server: not running (nothing to clean up yet)"
fi

# 3. runtime dir + config
mkdir -p "$RUNTIME_DIR"
if [[ -f "$RUNTIME_DIR/config.json" ]]; then
  echo "config: $RUNTIME_DIR/config.json (exists)"
else
  cp "$SCRIPT_DIR/config.example.json" "$RUNTIME_DIR/config.json"
  echo "config: seeded $RUNTIME_DIR/config.json from example"
fi

# 4. workspace-doctor linkage
WS_SCAN="$HOME/.config/workspace-doctor/scan.json"
if [[ -f "$WS_SCAN" ]]; then
  echo "workspace-doctor scan.json: found (authoritative live-worktree set)"
else
  echo "workspace-doctor scan.json: NOT found — run workspace-scan.py first for best accuracy"
fi

echo ""
echo "=== keep/kill preview ==="
python3 "$SCRIPT_DIR/tmux-scan.py" --list

echo ""
echo "Next:"
echo "  python $SCRIPT_DIR/tmux-scan.py        # write scan.json"
echo "  # then in Claude: /cleanup-tmux"
