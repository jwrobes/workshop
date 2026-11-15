---
name: setup-nvim-tmux
description: >-
  Set up a macOS development environment with Neovim and tmux, matching
  Jonathan's config. Use when the user says "set up neovim", "set up tmux",
  "configure my terminal", "copy dev environment", or wants to replicate
  this Neovim + tmux workflow on a new machine.
---

# Neovim + Tmux Environment Setup

Automated setup for a macOS dev environment with Neovim, tmux, vim-plug, TPM, and seamless vim/tmux navigation.

## Prerequisites

- macOS with Homebrew installed
- A terminal emulator (iTerm2 recommended)

## Setup Workflow

Copy this checklist and track progress:

```
- [ ] Step 1: Install core tools via Homebrew
- [ ] Step 2: Install config files
- [ ] Step 3: Install tmux scripts and plugins (TPM)
- [ ] Step 4: Install Neovim plugins (vim-plug)
- [ ] Step 5: Verify the setup
```

### Step 1: Install Core Tools

```bash
brew install neovim tmux the_silver_searcher reattach-to-user-namespace node fzf
```

| Tool | Purpose |
|------|---------|
| `neovim` | Editor (init.vim sources ~/.vimrc) |
| `tmux` | Terminal multiplexer |
| `the_silver_searcher` | `ag` — fast code search, used by fzf and vim grep |
| `reattach-to-user-namespace` | macOS clipboard integration for tmux copy/paste |
| `node` | Required by coc.nvim and markdown-preview.nvim |
| `fzf` | Fuzzy finder (also installed as a vim plugin) |

### Step 2: Install Config Files

Read and write each config file from this skill's `configs/` directory:

1. Read [configs/vimrc](configs/vimrc) → write to `~/.vimrc`
2. Read [configs/init.vim](configs/init.vim) → write to `~/.config/nvim/init.vim` (create dir with `mkdir -p ~/.config/nvim`)
3. Read [configs/tmux.conf](configs/tmux.conf) → write to `~/.tmux.conf`
4. Read [configs/save-scrollback.sh](configs/save-scrollback.sh) → write to `~/.tmux/scripts/save-scrollback.sh`
5. Read [configs/restore-scrollback.sh](configs/restore-scrollback.sh) → write to `~/.tmux/scripts/restore-scrollback.sh`
6. Make scripts executable:

```bash
mkdir -p ~/.tmux/scripts
chmod +x ~/.tmux/scripts/save-scrollback.sh ~/.tmux/scripts/restore-scrollback.sh
```

### Step 3: Install Tmux Plugin Manager (TPM)

```bash
git clone https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm
```

Then install the tmux plugins:

1. Start tmux: `tmux`
2. Press `Ctrl-a` then `I` (capital I) to install plugins (tmux-resurrect, tmux-continuum)
3. Wait for "TMUX environment reloaded" message

### Step 4: Install Neovim Plugins (vim-plug)

vim-plug auto-installs on first launch (see the curl in .vimrc). Just run:

```bash
nvim +PlugInstall +qall
```

This installs all plugins defined in the `plug#begin` / `plug#end` block. Key plugins:

| Plugin | What it does |
|--------|-------------|
| `fzf` + `fzf.vim` | Fuzzy file finder (`Ctrl-p`) and history (`Ctrl-b`) |
| `vim-tmux-navigator` | Seamless `Ctrl-h/j/k/l` between vim splits and tmux panes |
| `vim-tmux-runner` | Send commands from vim to a tmux pane |
| `coc.nvim` | Autocomplete engine (needs Node.js) |
| `vim-fugitive` | Git wrapper (`:Git blame`, `:Git diff`, etc.) |
| `vim-surround` | Change surrounding chars (`cs"'` to swap `"` → `'`) |
| `vim-commentary` | Toggle comments with `gcc` |
| `vim-test` + `tslime` | Run tests from vim, output in a tmux pane |
| `markdown-preview.nvim` | Live markdown preview in browser |
| `vim-easy-align` | Align text across lines |
| `jellybeans.vim` | Color scheme |

### Step 5: Verify

```bash
# Neovim launches without errors
nvim --version

# Tmux launches with correct prefix (Ctrl-a)
tmux new -s test
# Press Ctrl-a then : — should open tmux command prompt

# ag works
ag --version

# Clipboard integration works
echo "test" | pbcopy && pbpaste
```

## Key Bindings Quick Reference

### Tmux (prefix = `Ctrl-a`)

| Binding | Action |
|---------|--------|
| `Ctrl-a \|` | Split pane horizontally |
| `Ctrl-a -` | Split pane vertically |
| `Ctrl-a h/j/k/l` | Navigate panes (vim-style) |
| `Ctrl-a H/J/K/L` | Resize panes |
| `Ctrl-a r` | Reload tmux.conf |
| `Ctrl-a I` | Install TPM plugins |
| `Ctrl-h/j/k/l` | Navigate between vim splits AND tmux panes seamlessly |

### Neovim (leader = `Space`)

| Binding | Action |
|---------|--------|
| `Ctrl-p` | Fuzzy find files |
| `Ctrl-b` | Fuzzy find from file history |
| `Space s` | Run nearest test |
| `Space t` | Run current test file |
| `Space v` | Re-run last test |
| `Space lp` | Start markdown preview |
| `Space lc` | Stop markdown preview |
| `gcc` | Toggle comment on line |
| `jk` | Exit insert mode (alternative to Esc) |
| `Space Space` | Switch between last two files |
| `Space ff` | Toggle fold |
| `K` | Grep word under cursor |
| `\` | Start an Ag search |

## Customization Notes

- **Color scheme**: Set by `jellybeans.vim`. Change in `.vimrc` if preferred.
- **Tab width**: 2 spaces (set in `.vimrc` via `tabstop`/`shiftwidth`).
- **Tmux status bar**: Red with session name, positioned at top. Customize in `.tmux.conf`.
- **Test runner**: Configured for RSpec and Mocha via `vim-test`. Adjust `test#ruby#rspec#executable` for your project.
- **Copilot**: Commented out in .vimrc — uncomment the Copilot section if desired.
- **Tree-sitter**: Commented out in both init.vim and .vimrc — uncomment to enable better syntax highlighting.
