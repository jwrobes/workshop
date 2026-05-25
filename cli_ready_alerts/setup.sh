#!/usr/bin/env bash
###############################################################################
# setup.sh — idempotent installer for cli-ready-alerts
#
# What it does:
#   1. Preflight: checks jq, afplay, osascript.
#   2. Copies source to ~/.local/share/cli_ready_alerts/ (clobbers code, preserves config).
#   3. Seeds config.json from config.example.json if missing.
#   4. Symlinks ~/.cursor/hooks/cli-ready-alerts -> install dir (for Cursor).
#   5. Symlinks ~/.local/bin/cra -> install dir's cra.
#   6. Prints the hooks.json snippet to paste into ~/.cursor/hooks.json
#      (no automatic JSON edit — hooks.json is too personal to clobber).
#
# Flags:
#   --dry-run      Print what would happen; no filesystem changes.
#   --uninstall    Remove the two symlinks; leave install dir + user config alone.
#   --install-dir  Override ~/.local/share/cli_ready_alerts/ (advanced).
#
# Idempotent: safe to re-run; code updates, config is never clobbered.
###############################################################################

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/share/cli_ready_alerts}"
HOOKS_SYMLINK="$HOME/.cursor/hooks/cli-ready-alerts"
BIN_SYMLINK="$HOME/.local/bin/cra"

DRY_RUN=0
UNINSTALL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --install-dir) shift; INSTALL_DIR="$1" ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
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

# ── Uninstall ───────────────────────────────────────────────────────────────
if [[ "$UNINSTALL" == "1" ]]; then
  say "Uninstalling symlinks (install dir $INSTALL_DIR is preserved)..."
  [[ -L "$HOOKS_SYMLINK" ]] && run "rm -f '$HOOKS_SYMLINK'" && say "removed $HOOKS_SYMLINK"
  [[ -L "$BIN_SYMLINK" ]] && run "rm -f '$BIN_SYMLINK'" && say "removed $BIN_SYMLINK"
  say "Also remove the hook entries from ~/.cursor/hooks.json manually (see README)."
  say "To fully wipe: rm -rf '$INSTALL_DIR'"
  exit 0
fi

# ── Preflight ───────────────────────────────────────────────────────────────
missing=()
for bin in jq afplay osascript; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    missing+=("$bin")
  fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "Missing required tools: ${missing[*]}" >&2
  echo "  - jq:          brew install jq" >&2
  echo "  - afplay:      ships with macOS (you're not on macOS?)" >&2
  echo "  - osascript:   ships with macOS" >&2
  exit 1
fi
say "preflight: jq, afplay, osascript all present"

# ── Install dir ─────────────────────────────────────────────────────────────
say "install target: $INSTALL_DIR"
run "mkdir -p '$INSTALL_DIR'"

# Copy code (not config.json — we never clobber user config).
run "rsync -a --delete --exclude='config.json' --exclude='.DS_Store' '$SRC_DIR/' '$INSTALL_DIR/'"
say "code synced from $SRC_DIR/"

# Seed config on first install only.
if [[ ! -f "$INSTALL_DIR/config.json" ]]; then
  run "cp '$SRC_DIR/config.example.json' '$INSTALL_DIR/config.json'"
  say "seeded $INSTALL_DIR/config.json from config.example.json"
else
  say "preserved existing $INSTALL_DIR/config.json"
fi

# Make scripts executable (rsync preserves perms, but be defensive).
for script in dispatch.sh dispatch-claudecode.sh stash-context.sh cra channels/*.sh; do
  [[ -f "$INSTALL_DIR/$script" ]] && run "chmod +x '$INSTALL_DIR/$script'"
done

# ── Symlinks ────────────────────────────────────────────────────────────────
run "mkdir -p '$(dirname "$HOOKS_SYMLINK")'"
run "mkdir -p '$(dirname "$BIN_SYMLINK")'"
run "ln -sfn '$INSTALL_DIR' '$HOOKS_SYMLINK'"
say "symlinked $HOOKS_SYMLINK -> $INSTALL_DIR"
run "ln -sfn '$INSTALL_DIR/cra' '$BIN_SYMLINK'"
say "symlinked $BIN_SYMLINK -> $INSTALL_DIR/cra"

# Verify symlinks resolve (catches typos before they silently fail at hook-fire time).
if [[ "$DRY_RUN" != "1" ]]; then
  if [[ ! -e "$HOOKS_SYMLINK/dispatch.sh" ]]; then
    echo "WARN: $HOOKS_SYMLINK/dispatch.sh does not resolve — symlink may be broken" >&2
  fi
  if [[ ! -x "$BIN_SYMLINK" ]]; then
    echo "WARN: $BIN_SYMLINK is not executable — symlink may be broken" >&2
  fi
fi

# ── Hooks.json snippet ──────────────────────────────────────────────────────
cat <<'HOOKS'

[setup] Next step — merge these entries into ~/.cursor/hooks.json.
[setup] Existing hooks are additive — keep them alongside.
[setup] Paste or jq-merge:

{
  "hooks": {
    "beforeSubmitPrompt": [
      { "command": "./hooks/cli-ready-alerts/stash-context.sh" }
    ],
    "stop": [
      { "command": "./hooks/cli-ready-alerts/dispatch.sh done" }
    ],
    "postToolUseFailure": [
      { "command": "./hooks/cli-ready-alerts/dispatch.sh failed" }
    ],
    "beforeShellExecution": [
      {
        "command": "./hooks/cli-ready-alerts/dispatch.sh approval",
        "matcher": "(sudo|rm\\s+-[rf]+|\\bcurl\\b|\\bwget\\b|npm\\s+install|npm\\s+ci|pip\\s+install|pipx\\s+install|gem\\s+install|bundle\\s+install|brew\\s+install|brew\\s+uninstall|git\\s+push\\s+-f|git\\s+push[^\\n]*--force|git\\s+reset\\s+--hard|git\\s+clean\\s+-fd|chmod\\s+-R|\\bchown\\b)"
      }
    ]
  }
}

HOOKS

# ── Claude Code hooks snippet ───────────────────────────────────────────────
cat <<CLAUDE

[setup] Claude Code: merge this into ~/.claude/settings.json under "hooks".
[setup] Stop/Notification don't include workspace_path — dispatch-claudecode.sh
[setup] injects \$PWD. PermissionRequest includes "cwd" directly and is used as-is.

{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$INSTALL_DIR/dispatch-claudecode.sh done"
          }
        ]
      }
    ],
    "Notification": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$INSTALL_DIR/dispatch-claudecode.sh approval"
          }
        ]
      }
    ],
    "PermissionRequest": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$INSTALL_DIR/dispatch-claudecode.sh approval"
          }
        ]
      }
    ],
    "StopFailure": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$INSTALL_DIR/dispatch-claudecode.sh failed"
          }
        ]
      }
    ],
    "Elicitation": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$INSTALL_DIR/dispatch-claudecode.sh approval"
          }
        ]
      }
    ],
    "SubagentStop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$INSTALL_DIR/dispatch-claudecode.sh done"
          }
        ]
      }
    ]
  }
}

CLAUDE

say "Done. Verify with:  cra status"
say "Tail log during a session with:  cra tail -f   (or:  tail -f /tmp/cli-ready-alerts.log)"
