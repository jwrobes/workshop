#!/bin/bash
# Restore scrollback history for all panes
# Displays saved content in each pane after restore

RESURRECT_DIR="$HOME/.tmux/resurrect"
SCROLLBACK_DIR="$RESURRECT_DIR/scrollback"

[ -d "$SCROLLBACK_DIR" ] || exit 0

# Small delay to let panes initialize
sleep 1

for file in "$SCROLLBACK_DIR"/*.txt; do
    [ -f "$file" ] || continue
    [ -s "$file" ] || continue  # Skip empty files
    
    # Extract pane identifier from filename (undo the underscore replacement)
    filename=$(basename "$file" .txt)
    
    # Convert filename back to pane format: session_window_pane -> session:window.pane
    # Format: sessionname_windowindex_paneindex
    session="${filename%%_*}"
    rest="${filename#*_}"
    window="${rest%%_*}"
    pane_idx="${rest#*_}"
    pane_target="${session}:${window}.${pane_idx}"
    
    # Check if pane exists
    if tmux list-panes -a -F "#{session_name}:#{window_index}.#{pane_index}" 2>/dev/null | grep -q "^${pane_target}$"; then
        # Echo a separator and the old content
        tmux send-keys -t "$pane_target" "echo '=== Restored scrollback ===' && cat '$file' && echo '=== End restored ===' && clear" Enter
    fi
done
