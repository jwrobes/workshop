#!/usr/bin/env bash
###############################################################################
# dispatch-claudecode.sh — Claude Code hook adapter for cli-ready-alerts
#
# Claude Code hook stdin formats:
#   Stop:              {"session_id": "...", "stop_hook_active": false}
#   StopFailure:       {"session_id": "...", "error": "..."}
#   Notification:      {"session_id": "...", "message": "..."}
#   PermissionRequest: {"session_id": "...", "cwd": "...", "tool_name": "...", "tool_input": {...}}
#   Elicitation:       {"session_id": "...", "cwd": "...", "server_name": "...", "elicitation_data": {...}}
#   SubagentStop:      {"session_id": "...", "cwd": "...", "agent_type": "...", "agent_id": "..."}
#
# All events include "cwd" except Stop/Notification — we fall back to $PWD for those.
#
# Event → sound mapping:
#   done:     Stop, SubagentStop
#   approval: Notification, PermissionRequest, Elicitation
#   failed:   StopFailure
#
# Usage (in ~/.claude/settings.json hooks):
#   "command": "/path/to/dispatch-claudecode.sh done|approval|failed"
###############################################################################

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

event="${1:-done}"

input="$(cat 2>/dev/null || printf '{}')"
if ! printf '%s' "$input" | jq -e . >/dev/null 2>&1; then
  input='{}'
fi

session_id="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null || true)"

# PermissionRequest provides cwd directly; Stop/Notification don't.
payload_cwd="$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null || true)"
workspace_path="${payload_cwd:-$PWD}"

augmented="$(printf '%s' "$input" | jq -c \
  --arg wp "$workspace_path" \
  --arg cid "${session_id:-}" \
  '. + {workspace_path: $wp, conversation_id: $cid}' 2>/dev/null \
  || printf '{"workspace_path":"%s","conversation_id":"%s"}' "$workspace_path" "${session_id:-}")"

printf '%s' "$augmented" | "$SCRIPT_DIR/dispatch.sh" "$event"
