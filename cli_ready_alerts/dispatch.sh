#!/usr/bin/env bash
###############################################################################
# dispatch.sh — central router for cli-ready-alerts
#
# Invoked from ~/.cursor/hooks.json entries like:
#   { "command": "./hooks/cli-ready-alerts/dispatch.sh stop" }
#
# Reads the hook's stdin JSON, applies guardrails, resolves a "context" from
# workspace path (or env var override), looks up channels in config, and fires
# each enabled channel script in the background.
#
# Always exits 0. Never blocks the agent. Produces no stdout.
###############################################################################

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

event="${1:-unknown}"

INPUT="$(cra_read_stdin)"

cra_debug "dispatch: event=$event input_bytes=${#INPUT}"

# ── Short-circuits ──────────────────────────────────────────────────────────
if cra_is_disabled; then
  cra_debug "dispatch: disabled, exiting"
  exit 0
fi

if cra_is_quiet_hours; then
  cra_debug "dispatch: quiet hours, exiting"
  exit 0
fi

if cra_is_cursor_frontmost; then
  cra_debug "dispatch: cursor frontmost, exiting"
  exit 0
fi

# ── Event dedup ─────────────────────────────────────────────────────────────
# Two rules:
#   1) `done` right after `failed` → suppress `done`. Cursor fires postToolUseFailure
#      and then stop in quick succession on a failed tool call. Without this the
#      failed chime would be immediately overwritten by the done chime and the
#      user would mistake the end-state for "clean finish."
#   2) `approval` within 5s of the last `approval` → suppress. The approval
#      matcher can match several commands in a burst; one chime per burst is
#      enough.
#
# Implemented via timestamp stamp files in /tmp so it works across hook processes
# (each hook invocation is a fresh shell, so in-memory state doesn't help).
case "$event" in
  done)
    if cra_event_fired_within failed 2; then
      cra_log INFO "dispatch: event=done suppressed (failed fired within 2s)"
      exit 0
    fi
    ;;
  approval)
    if cra_event_fired_within approval 5; then
      cra_log INFO "dispatch: event=approval suppressed (approval fired within 5s)"
      exit 0
    fi
    ;;
esac

# ── Resolve context + channels ──────────────────────────────────────────────
# `stop` stdin only has {conversation_id, status} — no workspace_roots. Fall back
# to the state file written by stash-context.sh on beforeSubmitPrompt, keyed by
# conversation_id.
workspace_path="$(cra_extract_workspace_path "$INPUT")"
conversation_id="$(cra_extract_conversation_id "$INPUT")"

stashed_context=""
if [[ -z "$workspace_path" && -n "$conversation_id" ]]; then
  workspace_path="$(cra_stash_json_field "$conversation_id" 'workspace_path')"
  stashed_context="$(cra_stash_json_field "$conversation_id" 'context')"
fi

# Env var always wins. Otherwise, prefer the context snapshotted at prompt-
# submit time (already accounts for env var + regex match). Otherwise resolve
# from the workspace path we have now.
if [[ -n "${CURSOR_ALERT_CONTEXT:-}" ]]; then
  context_name="$CURSOR_ALERT_CONTEXT"
elif [[ -n "$stashed_context" ]]; then
  context_name="$stashed_context"
else
  context_name="$(cra_resolve_context "$workspace_path")"
fi

if cra_context_is_muted "$context_name"; then
  cra_log INFO "dispatch: event=$event context=$context_name workspace=$workspace_path channels=none (muted)"
  exit 0
fi

channels=()
while IFS= read -r _line; do
  [[ -z "$_line" ]] && continue
  channels+=("$_line")
done < <(cra_channels_for_event "$event")

channels_str=""
[[ ${#channels[@]} -gt 0 ]] && channels_str="${channels[*]}"
cra_log INFO "dispatch: event=$event context=$context_name workspace=$workspace_path channels=${channels_str:-none}"

if [[ ${#channels[@]} -eq 0 ]]; then
  cra_debug "dispatch: no enabled channels for event=$event"
  exit 0
fi

# ── Build payload passed to each channel ────────────────────────────────────
payload="$(jq -c -n \
  --arg event "$event" \
  --arg context "$context_name" \
  --arg workspace_path "$workspace_path" \
  --argjson raw "$INPUT" \
  '{event: $event, context: $context, workspace_path: $workspace_path, raw: $raw}')"

# ── Fire each channel in background ─────────────────────────────────────────
for ch in "${channels[@]}"; do
  script="$SCRIPT_DIR/channels/$ch.sh"
  if [[ ! -x "$script" ]]; then
    cra_log WARN "dispatch: channel script missing or not executable: $script"
    continue
  fi
  (
    printf '%s' "$payload" | "$script" "$event" "$context_name" "$CRA_CONFIG" \
      >> "$CRA_LOG" 2>&1
  ) &
done

cra_mark_event_fired "$event"

# Fire-and-forget: occasionally tidy old state files. Cheap; no-op if empty.
( cra_prune_stashed_state ) &

exit 0
