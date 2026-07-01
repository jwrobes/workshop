#!/usr/bin/env bash
# run_verify.sh — regenerate the dashboard, then run the headless UI checks.
# Playwright is used from the GLOBAL node install (fleet-dashboard has no
# package.json — it's a Python tool), so we point NODE_PATH at the global dir.
set -euo pipefail
cd "$(dirname "$0")"

# 1. Regenerate from current data (so template/collector changes take effect).
./run.sh "$@" >/dev/null 2>&1 || python3 collector.py --out "${FLEET_OUT:-$HOME/.fleet}" "$@"

# 2. Run the UI verifier + the true e2e tests (real user navigation) against
#    the freshly generated dashboard. Every user-facing claim has an e2e gate.
export NODE_PATH="$(npm root -g)"
node verify_ui.mjs
node e2e_repo_board.mjs
node e2e_unified_card.mjs
node e2e_track_detail.mjs
