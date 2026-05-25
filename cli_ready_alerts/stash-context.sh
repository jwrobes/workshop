#!/usr/bin/env bash
###############################################################################
# stash-context.sh — beforeSubmitPrompt hook
#
# The `stop` event's stdin only contains {conversation_id, status} — no
# workspace_roots. But `beforeSubmitPrompt` DOES include workspace_roots.
# This script persists the workspace info keyed by conversation_id so the
# later `stop` dispatch can look it up for context resolution.
#
# Called from ~/.cursor/hooks.json:
#   { "command": "./hooks/cli-ready-alerts/stash-context.sh" }
#
# Design rules (same as everything in this framework):
#  - Fail open: never block, never produce stdout, always exit 0.
#  - Minimal dependencies: jq + coreutils.
###############################################################################

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

INPUT="$(cra_read_stdin)"

# Fast path: if the system is disabled, skip — no point persisting state.
if cra_is_disabled; then
  exit 0
fi

conversation_id="$(echo "$INPUT" | jq -r '.conversation_id // empty' 2>/dev/null || true)"
if [[ -z "$conversation_id" ]]; then
  cra_debug "stash-context: no conversation_id, skipping"
  exit 0
fi

workspace_roots="$(echo "$INPUT" | jq -c '.workspace_roots // []' 2>/dev/null || printf '[]')"
workspace_path="$(echo "$INPUT" | jq -r '.workspace_roots[0] // empty' 2>/dev/null || true)"

mkdir -p "$CRA_STATE_DIR" 2>/dev/null || true

state_file="$CRA_STATE_DIR/$conversation_id.json"
now="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

# Resolve context now (while we have the workspace path). Even if env var flips
# later, we use the snapshot at prompt-submit time.
context_name="$(cra_resolve_context "$workspace_path")"

jq -n \
  --arg cid "$conversation_id" \
  --arg ts "$now" \
  --arg wp "$workspace_path" \
  --arg ctx "$context_name" \
  --argjson ws "$workspace_roots" \
  '{
    conversation_id: $cid,
    updated_at: $ts,
    workspace_path: $wp,
    workspace_roots: $ws,
    context: $ctx
  }' > "$state_file" 2>/dev/null || true

cra_debug "stash-context: cid=$conversation_id workspace=$workspace_path context=$context_name"
exit 0
