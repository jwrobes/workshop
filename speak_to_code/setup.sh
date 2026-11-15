#!/usr/bin/env bash
# setup.sh — idempotent installer for speak_to_code
#
# What it does:
#   1. Preflight: checks sox (rec), mlx_whisper, and at least one cleanup backend (llm, claude, or ollama).
#   2. Symlinks ~/.local/bin/dictate -> this folder's dictate script.
#   3. Seeds ~/.config/dictate/context.md from dictate-context.md.example if missing.
#   4. (Optional) Installs dictate-session-hook as a Claude Code Stop hook.
#
# Flags:
#   --dry-run         Print what would happen; no filesystem changes.
#   --uninstall       Remove the dictate symlink (context.md is preserved).
#   --uninstall-hook  Remove the dictate-session-hook Stop entry from ~/.claude/settings.json.
#   --meeting-deps    Install on-device diarization deps (pyannote.audio) into an
#                     isolated venv for `dictate --meeting`, then print HF setup steps.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_SYMLINK="$HOME/.local/bin/dictate"
CONTEXT_DIR="$HOME/.config/dictate"
CONTEXT_FILE="$CONTEXT_DIR/context.md"
CONTEXT_EXAMPLE="$SRC_DIR/dictate-context.md.example"

DRY_RUN=0
UNINSTALL=0
UNINSTALL_HOOK=0
MEETING_DEPS=0
DIARIZE_VENV="${DICTATE_DIARIZE_VENV:-$HOME/.local/share/dictate-diarize/.venv}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)        DRY_RUN=1 ;;
    --uninstall)      UNINSTALL=1 ;;
    --uninstall-hook) UNINSTALL_HOOK=1 ;;
    --meeting-deps)   MEETING_DEPS=1 ;;
    -h|--help)
      sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown flag: $1" >&2; exit 1 ;;
  esac
  shift
done

say() { printf '[setup] %s\n' "$*"; }
run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run] %s\n' "$*"
  else
    eval "$@"
  fi
}

HOOK_SCRIPT="$SRC_DIR/bin/dictate-session-hook"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"

# ── Uninstall hook ────────────────────────────────────────────────────────────
if [[ "$UNINSTALL_HOOK" == "1" ]]; then
  if [[ ! -f "$CLAUDE_SETTINGS" ]]; then
    say "No $CLAUDE_SETTINGS found; nothing to remove."
    exit 0
  fi
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run] Would remove dictate-session-hook Stop entry from %s\n' "$CLAUDE_SETTINGS"
  else
    python3 - "$CLAUDE_SETTINGS" "$HOOK_SCRIPT" <<'PYEOF'
import sys, json, os

settings_path = sys.argv[1]
hook_script = sys.argv[2]

with open(settings_path) as f:
    settings = json.load(f)

hooks = settings.get("hooks", {})
stop_hooks = hooks.get("Stop", [])

original_len = len(stop_hooks)
stop_hooks = [
    h for h in stop_hooks
    if not (
        isinstance(h, dict) and
        any(
            isinstance(inner, dict) and inner.get("command", "") == hook_script
            for inner in h.get("hooks", [])
        )
    )
]

if len(stop_hooks) == original_len:
    print("[setup] dictate-session-hook Stop entry not found; nothing to remove.")
else:
    hooks["Stop"] = stop_hooks
    settings["hooks"] = hooks
    tmp = settings_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2)
    os.replace(tmp, settings_path)
    print(f"[setup] Removed dictate-session-hook Stop entry from {settings_path}")
PYEOF
  fi
  exit 0
fi

# ── Uninstall ────────────────────────────────────────────────────────────────
if [[ "$UNINSTALL" == "1" ]]; then
  [[ -L "$BIN_SYMLINK" ]] && run "rm -f '$BIN_SYMLINK'" && say "removed $BIN_SYMLINK"
  say "context.md preserved at $CONTEXT_FILE"
  exit 0
fi

# ── Meeting deps (opt-in) ──────────────────────────────────────────────────────
# On-device speaker diarization for `dictate --meeting`. Installs pyannote.audio
# into an isolated venv so the core dictate install stays lightweight.
if [[ "$MEETING_DEPS" == "1" ]]; then
  say "installing meeting/diarization deps into $DIARIZE_VENV"
  run "mkdir -p '$(dirname "$DIARIZE_VENV")'"
  [[ -d "$DIARIZE_VENV" ]] || run "python3 -m venv '$DIARIZE_VENV'"
  run "'$DIARIZE_VENV/bin/pip' install --upgrade pip"
  run "'$DIARIZE_VENV/bin/pip' install 'pyannote.audio>=3.1'"
  say "meeting deps installed."
  say ""
  say "One-time HuggingFace setup (models download once, then diarization runs offline):"
  say "  1. Accept model terms (a contact-info form) on ALL THREE gated repos:"
  say "       https://huggingface.co/pyannote/speaker-diarization-3.1"
  say "       https://huggingface.co/pyannote/segmentation-3.0"
  say "       https://huggingface.co/pyannote/speaker-diarization-community-1"
  say "  2. Create a READ token:  https://huggingface.co/settings/tokens"
  say "  3. hf auth login         # paste the token"
  say ""
  say "Then test:  dictate --meeting --audio SOME_RECORDING.wav"
  exit 0
fi

# ── Preflight ────────────────────────────────────────────────────────────────
ok=1

if ! command -v rec >/dev/null 2>&1; then
  echo "MISSING: rec (SoX) — brew install sox" >&2; ok=0
else
  say "preflight: rec (sox) ✓"
fi

if ! command -v mlx_whisper >/dev/null 2>&1; then
  echo "MISSING: mlx_whisper — pip install mlx-whisper" >&2; ok=0
else
  say "preflight: mlx_whisper ✓"
fi

backend_found=0
for b in llm claude ollama; do
  if command -v "$b" >/dev/null 2>&1; then say "preflight: cleanup backend $b ✓"; backend_found=1; fi
done
if [[ "$backend_found" == "0" ]]; then
  echo "MISSING: a cleanup backend — install one of: llm (pip install llm), claude (Claude Code), ollama" >&2; ok=0
fi

if [[ "$ok" == "0" ]]; then
  echo "" >&2
  echo "Fix the above, then re-run setup.sh." >&2
  exit 1
fi

# ── Symlink dictate ──────────────────────────────────────────────────────────
run "mkdir -p '$(dirname "$BIN_SYMLINK")'"
run "ln -sfn '$SRC_DIR/dictate' '$BIN_SYMLINK'"
say "symlinked $BIN_SYMLINK -> $SRC_DIR/dictate"

# ── Seed context.md ──────────────────────────────────────────────────────────
run "mkdir -p '$CONTEXT_DIR'"
if [[ ! -f "$CONTEXT_FILE" ]]; then
  run "cp '$CONTEXT_EXAMPLE' '$CONTEXT_FILE'"
  say "seeded $CONTEXT_FILE from dictate-context.md.example"
  say "Edit it to match your vocabulary: \$EDITOR $CONTEXT_FILE"
else
  say "preserved existing $CONTEXT_FILE"
fi

# ── Optional: install session hook ───────────────────────────────────────────
printf '\nInstall dictate session hook for Claude Code? [y/N] '
read -r hook_answer
if [[ "$hook_answer" =~ ^[Yy]$ ]]; then
  if [[ ! -x "$HOOK_SCRIPT" ]]; then
    say "ERROR: hook script not found or not executable: $HOOK_SCRIPT" >&2
  else
    if [[ "$DRY_RUN" == "1" ]]; then
      printf '[dry-run] Would add Stop hook entry to %s\n' "$CLAUDE_SETTINGS"
    else
      python3 - "$CLAUDE_SETTINGS" "$HOOK_SCRIPT" <<'PYEOF'
import sys, json, os

settings_path = sys.argv[1]
hook_script = sys.argv[2]

settings = {}
if os.path.exists(settings_path):
    with open(settings_path) as f:
        try:
            settings = json.load(f)
        except json.JSONDecodeError:
            settings = {}

hooks = settings.setdefault("hooks", {})
stop_hooks = hooks.setdefault("Stop", [])

# Idempotency check
for h in stop_hooks:
    if isinstance(h, dict) and any(
        isinstance(inner, dict) and inner.get("command", "") == hook_script
        for inner in h.get("hooks", [])
    ):
        print(f"[setup] dictate-session-hook already installed in {settings_path}")
        sys.exit(0)

correct_entry = {"hooks": [{"type": "command", "command": hook_script}]}
stop_hooks.append(correct_entry)
settings["hooks"]["Stop"] = stop_hooks

os.makedirs(os.path.dirname(settings_path), exist_ok=True)
tmp = settings_path + ".tmp"
with open(tmp, "w") as f:
    json.dump(settings, f, indent=2)
os.replace(tmp, settings_path)
print(f"[setup] Added dictate-session-hook Stop entry to {settings_path}")
PYEOF
    fi
    say ""
    say "Cursor: add this to ~/.cursor/hooks.json manually:"
    say '  "Stop": [{"command": "'"$HOOK_SCRIPT"'", "timeout": 5}]'
    say "To uninstall: bash setup.sh --uninstall-hook"
  fi
else
  say "Skipped hook installation. Run 'bash setup.sh --uninstall-hook' to remove later if needed."
fi

say ""
say "Done. Test with:"
say "  dictate --raw                   # record + transcribe only"
say "  dictate                         # full pipeline"
say "  dictate --list-contexts         # list installed context bundles"
say "  dictate --session               # include session context for \$PWD"
say ""
say "For meeting mode (speaker attribution), also run:"
say "  bash setup.sh --meeting-deps    # installs on-device diarization + HF steps"
