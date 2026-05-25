#!/usr/bin/env bash
###############################################################################
# common.sh — shared helpers for cli-ready-alerts
#
# Source with:  source "$(dirname "$0")/lib/common.sh"
#
# Design rules:
#  - Fail open: never block, never exit non-zero from here.
#  - No stdout: Cursor would interpret it as a hook response. Log to stderr or
#    to the log file. Callers suppress stderr via > /dev/null 2>&1 when needed.
#  - Minimal dependencies: jq + coreutils only.
###############################################################################

CRA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRA_CONFIG="${CRA_CONFIG:-$CRA_ROOT/config.json}"
CRA_SOUNDS_DIR="$CRA_ROOT/sounds"
CRA_SYSTEM_SOUNDS_DIR="/System/Library/Sounds"
CRA_LOG="${CRA_LOG:-/tmp/cli-ready-alerts.log}"
CRA_STATE_DIR="${CRA_STATE_DIR:-/tmp/cli-ready-alerts-state}"
CRA_STATE_TTL_SECONDS="${CRA_STATE_TTL_SECONDS:-86400}"
CRA_DEBUG="${CRA_DEBUG:-0}"

# ── Logging ──────────────────────────────────────────────────────────────────
cra_log() {
  local level="$1"; shift
  printf '[%s] [%s] %s\n' "$(date +'%Y-%m-%dT%H:%M:%S')" "$level" "$*" >> "$CRA_LOG" 2>/dev/null || true
}

cra_debug() {
  [[ "$CRA_DEBUG" == "1" ]] || return 0
  cra_log DEBUG "$*"
}

# ── Config accessors ────────────────────────────────────────────────────────
cra_config_get() {
  # $1 = jq filter, e.g. '.enabled'
  jq -r "$1 // empty" "$CRA_CONFIG" 2>/dev/null || printf ''
}

cra_config_get_json() {
  jq -c "$1 // empty" "$CRA_CONFIG" 2>/dev/null || printf ''
}

# ── Guardrails ──────────────────────────────────────────────────────────────
cra_is_disabled() {
  # True if the whole system is disabled.
  if [[ "${CURSOR_ALERT_DISABLE:-0}" == "1" ]]; then return 0; fi
  local enabled
  enabled="$(cra_config_get '.enabled')"
  [[ "$enabled" == "false" ]]
}

cra_is_quiet_hours() {
  local start end hour
  start="$(cra_config_get '.guardrails.quiet_hours.start')"
  end="$(cra_config_get '.guardrails.quiet_hours.end')"
  [[ -z "$start" || -z "$end" ]] && return 1
  hour=$(date +%H)
  hour=$((10#$hour))
  start=$((10#$start))
  end=$((10#$end))
  if (( start <= end )); then
    (( hour >= start && hour < end )) && return 0
  else
    (( hour >= start || hour < end )) && return 0
  fi
  return 1
}

cra_is_cursor_frontmost() {
  local skip
  skip="$(cra_config_get '.guardrails.skip_if_cursor_frontmost')"
  [[ "$skip" == "true" ]] || return 1
  local frontmost
  frontmost="$(osascript -e 'tell application "System Events" to get name of first application process whose frontmost is true' 2>/dev/null || true)"
  [[ "$frontmost" == "Cursor" ]]
}

# ── Channel routing ─────────────────────────────────────────────────────────
cra_channels_for_event() {
  # $1 = event name (done | approval | failed)
  # Prints one enabled channel name per line (nothing if none).
  local event="$1"
  local routed ch enabled
  routed="$(jq -r --arg e "$event" '.routing[$e] // [] | .[]' "$CRA_CONFIG" 2>/dev/null || true)"
  [[ -z "$routed" ]] && return 0
  while IFS= read -r ch; do
    [[ -z "$ch" ]] && continue
    enabled="$(jq -r --arg c "$ch" '.channels[$c].enabled // false' "$CRA_CONFIG" 2>/dev/null)"
    [[ "$enabled" == "true" ]] && printf '%s\n' "$ch"
  done <<< "$routed"
}

# ── Context resolution ──────────────────────────────────────────────────────
cra_resolve_context() {
  # $1 = workspace_path (may be empty)
  # Prints the resolved context name (falls back to "default").
  local workspace_path="${1:-}"
  if [[ -n "${CURSOR_ALERT_CONTEXT:-}" ]]; then
    printf '%s' "$CURSOR_ALERT_CONTEXT"
    return 0
  fi
  if [[ -z "$workspace_path" ]]; then
    printf 'default'
    return 0
  fi
  local name
  # Bind the regex to a variable *before* piping $p into test(), otherwise jq
  # evaluates .match.workspace_path in $p's (string) scope and throws
  # "Cannot index string with string \"match\"".
  name="$(jq -r --arg p "$workspace_path" '
    (.contexts // [])
    | map(select(.match.workspace_path as $r | $r != null and ($p | test($r))))
    | .[0].name // empty
  ' "$CRA_CONFIG" 2>/dev/null || true)"
  [[ -n "$name" ]] && { printf '%s' "$name"; return 0; }
  printf 'default'
}

_cra_resolve_sound_file() {
  # $1 = sound filename (or absolute path). Prints absolute path if found, else empty.
  local file="$1"
  [[ -z "$file" || "$file" == "null" ]] && { printf ''; return 0; }
  if [[ -f "$CRA_SOUNDS_DIR/$file" ]]; then
    printf '%s' "$CRA_SOUNDS_DIR/$file"
  elif [[ -f "$CRA_SYSTEM_SOUNDS_DIR/$file" ]]; then
    printf '%s' "$CRA_SYSTEM_SOUNDS_DIR/$file"
  elif [[ -f "$file" ]]; then
    printf '%s' "$file"
  else
    printf ''
  fi
}

cra_context_is_muted() {
  # $1 = context name. Returns 0 (true) if the context has muted=true in config.
  local ctx="$1"
  [[ -z "$ctx" ]] && return 1
  local muted
  muted="$(jq -r --arg c "$ctx" '(.contexts // []) | map(select(.name == $c)) | .[0].muted // false' "$CRA_CONFIG" 2>/dev/null)"
  [[ "$muted" == "true" ]]
}

cra_sound_for_context_event() {
  # $1 = context name, $2 = event name
  # Prints absolute path to the sound file. Strategy:
  #   1) Context-specific sound → use if the file exists.
  #   2) If the context sound is unset OR its file is missing, fall back to
  #      default_context sound for the event.
  # This makes "context defines done but not approval" and "context references
  # a sound file that hasn't been dropped in yet" both safe — they fall through
  # to the default sound instead of going silent.
  local context="$1" event="$2"
  local file resolved

  file="$(jq -r --arg c "$context" --arg e "$event" '
    (.contexts // []) | map(select(.name == $c)) | .[0].sounds[$e] // empty
  ' "$CRA_CONFIG" 2>/dev/null || true)"

  resolved="$(_cra_resolve_sound_file "$file")"
  if [[ -n "$resolved" ]]; then
    printf '%s' "$resolved"
    return 0
  fi

  # Fall back to default_context sound for this event.
  file="$(jq -r --arg e "$event" '.default_context.sounds[$e] // empty' "$CRA_CONFIG" 2>/dev/null || true)"
  resolved="$(_cra_resolve_sound_file "$file")"
  printf '%s' "$resolved"
}

# ── Stdin helpers ───────────────────────────────────────────────────────────
cra_read_stdin() {
  # Reads all of stdin and echoes it. Empty string if no stdin or invalid.
  local input
  input="$(cat 2>/dev/null || true)"
  [[ -z "$input" ]] && { printf '{}'; return 0; }
  # Validate it parses as JSON; if not, return empty object.
  if echo "$input" | jq -e . >/dev/null 2>&1; then
    printf '%s' "$input"
  else
    printf '{}'
  fi
}

cra_extract_workspace_path() {
  # $1 = stdin JSON. Tries common fields for workspace path. Empty if none.
  local input="$1"
  local wp
  wp="$(echo "$input" | jq -r '.workspace_roots[0] // .workspace_path // .cwd // empty' 2>/dev/null || true)"
  printf '%s' "$wp"
}

cra_extract_conversation_id() {
  # $1 = stdin JSON. Returns conversation_id or empty.
  local input="$1"
  echo "$input" | jq -r '.conversation_id // empty' 2>/dev/null || true
}

# ── Stashed state (written by stash-context.sh at beforeSubmitPrompt) ───────
cra_read_stashed_context() {
  # $1 = conversation_id.
  # Prints JSON with {workspace_path, context} or empty if no state file.
  local cid="$1"
  [[ -z "$cid" ]] && return 0
  local f="$CRA_STATE_DIR/$cid.json"
  [[ -f "$f" ]] || return 0
  jq -c '{workspace_path: (.workspace_path // ""), context: (.context // "")}' "$f" 2>/dev/null || true
}

cra_stash_json_field() {
  # $1 = conversation_id, $2 = field (workspace_path | context).
  # Prints the single field value from the stashed state, or empty.
  local cid="$1" field="$2"
  [[ -z "$cid" ]] && return 0
  local f="$CRA_STATE_DIR/$cid.json"
  [[ -f "$f" ]] || return 0
  jq -r --arg k "$field" '.[$k] // empty' "$f" 2>/dev/null || true
}

cra_prune_stashed_state() {
  # Best-effort cleanup: remove state files older than CRA_STATE_TTL_SECONDS.
  # Safe to call from any hook; fire-and-forget (fast, no find flags unique to GNU).
  [[ -d "$CRA_STATE_DIR" ]] || return 0
  local ttl_min
  ttl_min=$(( CRA_STATE_TTL_SECONDS / 60 ))
  (( ttl_min < 1 )) && ttl_min=1
  find "$CRA_STATE_DIR" -type f -name '*.json' -mmin "+${ttl_min}" -delete 2>/dev/null || true
}

# ── Event dedup (across processes via timestamp files) ──────────────────────
#
# Why dedup:
#   - On a failed tool call, Cursor fires `postToolUseFailure` AND then `stop`.
#     Without dedup we'd hear both the failed sound AND the done sound,
#     and the done would mask/confuse the signal that something actually broke.
#   - The approval matcher can hit multiple commands in a burst (e.g., an
#     agent running `pip install X && pip install Y`). One approval chime per
#     burst is enough.
#
# Strategy:
#   - `cra_mark_event_fired <event>` stamps /tmp/cli-ready-alerts-last-<event>.ts
#     with the current epoch seconds.
#   - `cra_event_fired_within <event> <window_seconds>` returns 0 if the stamp
#     is newer than window_seconds ago.
# Fail-open: if stat fails or files are missing, we treat "not recently fired"
# as the answer (no suppression).

CRA_DEDUP_DIR="${CRA_DEDUP_DIR:-/tmp}"

cra_mark_event_fired() {
  local event="$1"
  [[ -z "$event" ]] && return 0
  printf '%s' "$(date +%s)" > "$CRA_DEDUP_DIR/cli-ready-alerts-last-$event.ts" 2>/dev/null || true
}

cra_event_fired_within() {
  # $1 = event name, $2 = window in seconds. Returns 0 if fired within window.
  local event="$1" window="$2"
  [[ -z "$event" || -z "$window" ]] && return 1
  local f="$CRA_DEDUP_DIR/cli-ready-alerts-last-$event.ts"
  [[ -f "$f" ]] || return 1
  local then now
  then="$(cat "$f" 2>/dev/null || printf '0')"
  now="$(date +%s)"
  # Guard against bad input (empty/non-numeric) — treat as "not recent".
  [[ "$then" =~ ^[0-9]+$ ]] || return 1
  (( now - then < window ))
}
