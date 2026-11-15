# sharpen_prompt tmux integration. Load with:
#   tmux source-file /path/to/sharpen_prompt/sharpen.tmux
# or add that line to ~/.tmux.conf.

# prefix + v : dictate a new draft into this pane's pair's sharpen session (popup, closes when done)
bind-key v display-popup -E -w 70% -h 30% -T " dictate → sharpen (Ctrl-C to stop) " \
  "~/.local/bin/sharpen dictate --from-pane '#{pane_id}'"

# prefix + V : dictate a refinement of the current draft
bind-key V display-popup -E -w 70% -h 30% -T " dictate → refine (Ctrl-C to stop) " \
  "~/.local/bin/sharpen dictate --refine --from-pane '#{pane_id}'"

# prefix + y : put this pane's pair's last sharpened message back on the clipboard (works from the
# working pane or the sharpen pane), e.g. after another pair's reply replaced it
bind-key y run-shell -b "~/.local/bin/sharpen copy --quiet --from-pane '#{pane_id}'"

# Pane borders show [pair · role] so every pane says what it's paired to, wherever it is.
set -g pane-border-status top
set -g pane-border-format " #{?@sharpen_pair,#[bold][#{@sharpen_pair} · #{@sharpen_role}]#[default] ,}#{b:pane_current_path} "
