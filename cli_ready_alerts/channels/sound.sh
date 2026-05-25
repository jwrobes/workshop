#!/usr/bin/env bash
###############################################################################
# channels/sound.sh — play a sound for an event in a given context
#
# Three-tier priority:
#   1. Custom file in sounds/ dir: <context>_<event>.{mp3,aiff,wav}
#      Drop your recorded files there — no config change needed.
#      These are gitignored and never committed.
#   2. Talking mode (sound_mode=talking in config): macOS `say` with
#      configured voice and message text. Nothing to install or check in.
#   3. System sounds (sound_mode=sounds, the default): afplay with the
#      sound filenames configured in default_context.sounds / context.sounds.
#
# Called from dispatch.sh with:
#   stdin: JSON { event, context, workspace_path, raw }
#   args:  $1=event $2=context $3=config_path
###############################################################################

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

event="${1:-unknown}"
context="${2:-default}"

# ── Tier 1: custom file in sounds/ (<context>_<event>.{mp3,aiff,wav}) ────────
custom_file=""
for ext in mp3 aiff wav; do
  candidate="$CRA_SOUNDS_DIR/${context}_${event}.$ext"
  if [[ -f "$candidate" ]]; then
    custom_file="$candidate"
    break
  fi
done

if [[ -n "$custom_file" ]]; then
  cra_debug "sound: playing custom $custom_file (context=$context event=$event)"
  afplay "$custom_file" >/dev/null 2>&1 &
  disown || true
  exit 0
fi

# ── Tier 2: talking mode ──────────────────────────────────────────────────────
sound_mode="$(jq -r '.sound_mode // "sounds"' "$CRA_CONFIG" 2>/dev/null || echo "sounds")"

if [[ "$sound_mode" == "talking" ]]; then
  voice="$(jq -r '.talking.voice // "Samantha"' "$CRA_CONFIG" 2>/dev/null || echo "Samantha")"
  message="$(jq -r --arg e "$event" '.talking.messages[$e] // ""' "$CRA_CONFIG" 2>/dev/null || echo "")"
  if [[ -n "$message" ]]; then
    cra_debug "sound: saying '$message' voice=$voice (context=$context event=$event)"
    say -v "$voice" "$message" &
    disown || true
  else
    cra_log WARN "sound: talking mode but no message configured for event=$event"
  fi
  exit 0
fi

# ── Tier 3: system/config sounds (default) ───────────────────────────────────
sound_file="$(cra_sound_for_context_event "$context" "$event")"

if [[ -z "$sound_file" ]]; then
  cra_log WARN "sound: no sound mapped for context=$context event=$event"
  exit 0
fi

if [[ ! -f "$sound_file" ]]; then
  cra_log WARN "sound: file not found: $sound_file"
  exit 0
fi

cra_debug "sound: playing $sound_file (context=$context event=$event)"
afplay "$sound_file" >/dev/null 2>&1 &
disown || true
exit 0
