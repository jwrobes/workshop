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
node e2e_pipeline_tracks.mjs
# LLM e2e (Passes 1-3) — each generates its OWN dashboard via a canned
# --triage-fixture / --analyze-fixture (offline, never the real claude CLI), so
# these stay deterministic and don't mutate the user's ~/.fleet overrides.
node e2e_triage.mjs      # Pass 1 — triage (attach/archive/suggest)
node e2e_llm_runlog.mjs  # Pass 1 — change-log panel
node e2e_verdict.mjs     # Pass 2 — per-track verdict in the render slots
node e2e_rollup.mjs      # Pass 3 — product/fleet rollup
