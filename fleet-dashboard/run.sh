#!/usr/bin/env bash
# run.sh — regenerate the fleet dashboard and open it.
# Usage: ./run.sh [extra collector flags]
#   ./run.sh              # local mode (worktrees + plans + PRs via gh)
#   ./run.sh --no-gh      # offline (no forge calls)
#   ./run.sh --no-local   # forge-only (cloud-portable, no checkouts)
set -euo pipefail
cd "$(dirname "$0")"

# Preflight: tools the collector needs.
command -v python3 >/dev/null || { echo "error: python3 not found on PATH"; exit 1; }
command -v git >/dev/null || { echo "error: git not found on PATH"; exit 1; }
if ! command -v gh >/dev/null; then
  echo "note: gh (GitHub CLI) not found — falling back to --no-gh (no PR/repo lookups)."
  set -- --no-gh "$@"
elif ! gh auth status >/dev/null 2>&1; then
  echo "note: gh is not authenticated (run 'gh auth login') — falling back to --no-gh."
  set -- --no-gh "$@"
fi

OUT="${FLEET_OUT:-$HOME/.fleet}"
python3 collector.py --out "$OUT" "$@"

DASH="$OUT/dashboard.html"
echo "→ $DASH"
# Open in the default browser (mac: open, linux: xdg-open).
if command -v open >/dev/null; then open "$DASH"
elif command -v xdg-open >/dev/null; then xdg-open "$DASH"
else echo "Open it manually: $DASH"
fi
