#!/usr/bin/env bash
# setup.sh — idempotent installer for sharpen_prompt
#
# What it does:
#   1. Symlinks ~/.local/bin/sharpen -> this folder's sharpen script.
#   2. Registers Claude Code hooks in ~/.claude/settings.json:
#        Stop             -> sharpen hook stop    (last-message snapshot; copy-out in sharpen panes)
#        UserPromptSubmit -> sharpen hook prompt  (attach the working session's last message)
#   3. Registers Cursor CLI hooks in ~/.cursor/hooks.json:
#        afterAgentResponse -> sharpen hook after_response (snapshot + copy-out)
#        sessionStart       -> sharpen hook session_start  (persona + initial context)
#      All hooks exit immediately in panes that aren't part of a pair.
#   4. Prints the tmux line to load sharpen.tmux (key bindings + pane-border labels).
#
# Flags:
#   --dry-run          Print what would happen; no changes.
#   --uninstall        Remove the symlink and every hook entry.
#   --skip-cursor      Don't touch ~/.cursor/hooks.json (Claude only).
#   --skip-claude      Don't touch ~/.claude/settings.json (Cursor only).

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_SYMLINK="$HOME/.local/bin/sharpen"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"
CURSOR_HOOKS="$HOME/.cursor/hooks.json"

DRY_RUN=0
UNINSTALL=0
SKIP_CURSOR=0
SKIP_CLAUDE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)     DRY_RUN=1 ;;
    --uninstall)   UNINSTALL=1 ;;
    --skip-cursor) SKIP_CURSOR=1 ;;
    --skip-claude) SKIP_CLAUDE=1 ;;
    -h|--help)     sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 1 ;;
  esac
  shift
done

say() { printf '[setup] %s\n' "$*"; }

# Claude settings.json: hooks are grouped under hooks.<Event> as a list of {hooks:[{type,command,timeout}]}.
edit_claude_hooks() {
  local mode="$1"
  python3 - "$CLAUDE_SETTINGS" "$BIN_SYMLINK" "$mode" "$DRY_RUN" <<'PYEOF'
import json, os, sys
path, bin_path, mode, dry = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] == "1"
wanted = {"Stop": f"{bin_path} hook stop", "UserPromptSubmit": f"{bin_path} hook prompt"}
settings = json.load(open(path)) if os.path.exists(path) else {}
hooks = settings.setdefault("hooks", {})
for event, cmd in wanted.items():
    groups = hooks.setdefault(event, [])
    present = any(h.get("command") == cmd for g in groups for h in g.get("hooks", []))
    if mode == "install" and not present:
        groups.append({"hooks": [{"type": "command", "command": cmd, "timeout": 10}]})
        print(f"[setup] claude add {event}: {cmd}")
    elif mode == "uninstall" and present:
        for g in groups:
            g["hooks"] = [h for h in g.get("hooks", []) if h.get("command") != cmd]
        hooks[event] = [g for g in groups if g.get("hooks")]
        if not hooks[event]:
            del hooks[event]
        print(f"[setup] claude remove {event}: {cmd}")
    else:
        print(f"[setup] claude {event} already {'present' if present else 'absent'}")
if not dry:
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
PYEOF
}

# Cursor hooks.json: {version:1, hooks:{<event>:[{command:"..."}]}}. Preserves existing entries.
edit_cursor_hooks() {
  local mode="$1"
  python3 - "$CURSOR_HOOKS" "$BIN_SYMLINK" "$mode" "$DRY_RUN" <<'PYEOF'
import json, os, sys
path, bin_path, mode, dry = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] == "1"
wanted = {
    "afterAgentResponse": f"{bin_path} hook after_response",
    "sessionStart":       f"{bin_path} hook session_start",
}
cfg = json.load(open(path)) if os.path.exists(path) else {"version": 1, "hooks": {}}
cfg.setdefault("version", 1)
hooks = cfg.setdefault("hooks", {})
for event, cmd in wanted.items():
    entries = hooks.setdefault(event, [])
    present = any(h.get("command") == cmd for h in entries)
    if mode == "install" and not present:
        entries.append({"command": cmd})
        print(f"[setup] cursor add {event}: {cmd}")
    elif mode == "uninstall" and present:
        hooks[event] = [h for h in entries if h.get("command") != cmd]
        if not hooks[event]:
            del hooks[event]
        print(f"[setup] cursor remove {event}: {cmd}")
    else:
        print(f"[setup] cursor {event} already {'present' if present else 'absent'}")
if not dry:
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
PYEOF
}

if [[ "$UNINSTALL" == "1" ]]; then
  if [[ -L "$BIN_SYMLINK" ]]; then
    [[ "$DRY_RUN" == "1" ]] && say "would remove $BIN_SYMLINK" || { rm "$BIN_SYMLINK"; say "removed $BIN_SYMLINK"; }
  fi
  [[ "$SKIP_CLAUDE" == "0" ]] && edit_claude_hooks uninstall
  [[ "$SKIP_CURSOR" == "0" ]] && edit_cursor_hooks uninstall
  say "tmux: remove the 'source-file .../sharpen.tmux' line from ~/.tmux.conf if you added it, then press prefix+r to reload."
  exit 0
fi

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
command -v tmux >/dev/null || say "warning: tmux not found — pairing by pane and voice delivery need it"
command -v claude >/dev/null || say "note: claude not found on PATH (fine if you only use cursor-agent)"
command -v cursor-agent >/dev/null || say "note: cursor-agent not found on PATH (fine if you only use claude)"

mkdir -p "$(dirname "$BIN_SYMLINK")"
if [[ "$DRY_RUN" == "1" ]]; then
  say "would symlink $BIN_SYMLINK -> $SRC_DIR/sharpen"
else
  ln -sfn "$SRC_DIR/sharpen" "$BIN_SYMLINK"
  say "symlinked $BIN_SYMLINK -> $SRC_DIR/sharpen"
fi

if [[ "$SKIP_CLAUDE" == "0" ]]; then
  [[ -f "$CLAUDE_SETTINGS" && "$DRY_RUN" == "0" ]] && cp "$CLAUDE_SETTINGS" "$CLAUDE_SETTINGS.bak-sharpen"
  edit_claude_hooks install
fi
if [[ "$SKIP_CURSOR" == "0" ]]; then
  [[ -f "$CURSOR_HOOKS" && "$DRY_RUN" == "0" ]] && cp "$CURSOR_HOOKS" "$CURSOR_HOOKS.bak-sharpen"
  edit_cursor_hooks install
fi

cat <<EOF

[setup] tmux bindings (prefix+v / prefix+V dictate, prefix+y recopy) and pane-border labels:
          tmux source-file $SRC_DIR/sharpen.tmux        # this tmux server, now

        To keep them across restarts, add this line to ~/.tmux.conf ABOVE the
        run '~/.tmux/plugins/tpm/tpm' line (tpm must stay the last line of the file):

          source-file $SRC_DIR/sharpen.tmux

Try it (Claude):
  1. In the pane that will be the sharpen session:   sharpen session my-pair
  2. In the working Claude pane (any shell first):   sharpen join my-pair
  3. Type a draft in the sharpen session, or press prefix+v anywhere in the pair to dictate one.

Try it (Cursor CLI):
  1. In the pane that will be the sharpen session:   sharpen session my-pair --agent cursor
  2. In the working cursor-agent pane (any shell):   sharpen join my-pair
  3. Same as above. Cursor sessions pull the working-session reply with \`sharpen last\` per pass
     rather than injecting it per-turn (beforeSubmitPrompt is block-only in Cursor).
EOF
