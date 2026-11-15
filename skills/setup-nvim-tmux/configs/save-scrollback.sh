#!/bin/bash
# Save scrollback history for all panes
# Reads @scrollback-lines from tmux.conf (default: 500)

RESURRECT_DIR="$HOME/.tmux/resurrect"
SCROLLBACK_DIR="$RESURRECT_DIR/scrollback"
mkdir -p "$SCROLLBACK_DIR"

# Get configurable line count from tmux option (default 500)
LINES=$(tmux show-option -gqv @scrollback-lines 2>/dev/null)
LINES=${LINES:-500}

# Clear old scrollback files
rm -f "$SCROLLBACK_DIR"/*.txt 2>/dev/null

for pane in $(tmux list-panes -a -F "#{session_name}:#{window_index}.#{pane_index}"); do
    # Replace colons and dots with underscores for safe filename
    filename="${pane//[:.]/_}"
    tmux capture-pane -t "$pane" -p -S -"$LINES" > "$SCROLLBACK_DIR/${filename}.txt" 2>/dev/null
done
