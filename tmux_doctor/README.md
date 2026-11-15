# tmux_doctor

Cleanup tool for accumulated tmux sessions. Scans every session, resolves its
panes' working directories to workspace-lifecycle roles, classifies each session,
and kills the ones tied only to **archived or removed** workspaces — while
guarding attached, protected, and actively-worked sessions.

Sibling of [`workspace_doctor`](../workspace_doctor/): tmux sessions are usually
created per worktree/initiative, so when `workspace-doctor` archives a workbench
and removes its worktree, the tmux session is left orphaned. `tmux-doctor`
**consumes `workspace-doctor`'s `scan.json`** for the authoritative live-worktree
set and reaps what's no longer backed by live work.

## Why

One-off per-project tmux sessions plus a few long-running ones (`sct-team-reviews`)
accumulate — a tmux-resurrect restore can bring back dozens at once. They cost
memory and clutter the switcher. The safe-to-kill signal is **linkage**: a session
whose directories all point at `workbench/completed/`, `workbench/archived/`, or
removed worktrees is done; one still sitting in a live worktree is not.

## Architecture

**Layer 1 — `tmux-scan.py`** (deterministic, no kills)
- Enumerates sessions (`tmux list-sessions`) and panes (`tmux list-panes -a`).
- Resolves each pane path to a role: `live-worktree`, `live-workbench`,
  `archived`, `gone`, `repo`, `workspace-root`, `non-workspace`, `home`.
- Reads `workspace_doctor/scan.json` for the authoritative live-worktree set.
- Classifies each session and writes `~/.config/tmux-doctor/scan.json`.
- `--list` prints the grouped keep/kill table without writing.

**Executor — `tmux-cleanup.py`** (dry-run by default; `--execute`)
- Reads `~/.config/tmux-doctor/tmux-manifest.json`.
- Re-checks guards live: never kills an attached or protected-name session.
- Logs each run to `~/.config/tmux-doctor/cleanup-log.md` + `.html`.

**Layer 3 — `skills/cleanup-tmux/SKILL.md`**
- Loads the scan, presents the report, gets scope approval, writes the manifest,
  dry-runs, then executes.

## Classification

| Session signal | Class | Action |
|---|---|---|
| Currently attached | `attached` | keep |
| Name in protected allowlist | `protected-name` | keep |
| Base path in a durable non-workspace root | `protected-path` | keep |
| Any pane in a live worktree / open workbench initiative | `active-work` | keep |
| All project paths archived or removed, none live | `archived-linked` | **kill** |
| Only home / repo / workspace-root paths | `generic` | **kill** |
| Anything else | `unclear` | review |

Conservative: any live worktree/open-workbench pane keeps the session.

## Install

```bash
bash setup.sh
```

Verifies tmux, seeds `~/.config/tmux-doctor/config.json` from `config.example.json`,
and prints the keep/kill preview. No heavy deps (Python stdlib only).

### Config (`~/.config/tmux-doctor/config.json`)

| Key | Meaning |
|---|---|
| `workspace_root` | Root that holds `*_workspace/` dirs (default `~/workspace`) |
| `protected_names` | Session names never killed (default: none) |
| `protected_path_roots` | Durable dirs whose sessions are kept (default: `~/personal`) |
| `activity_grace_days` | Optional: keep sessions active within N days. Off by default (tmux-resurrect resets activity timestamps, making it unreliable) |

## Usage

```bash
python tmux-scan.py --list          # preview classification, no writes
python tmux-scan.py                 # write ~/.config/tmux-doctor/scan.json
# then, in Claude:  /cleanup-tmux   # report → approve → dry-run → execute
python tmux-cleanup.py              # dry-run the current manifest
python tmux-cleanup.py --execute    # kill approved sessions
```

## Guards

- **Never kills attached sessions** — re-checked live at execution, not just at scan.
- **Never kills protected-name sessions.**
- Skips already-gone sessions; skips rather than aborting on any single failure.
- Dry-run is the default; `--execute` is required to kill.

## Relationship to workspace_doctor

Run `workspace-doctor` first (it produces `scan.json` and archives/removes
worktrees), then `tmux-doctor` to reap the sessions those removals orphaned. The
two share the same lifecycle model — scan → classify → report → approve → act →
log — and the same `~/.config/<tool>/` runtime + log convention.

## Status

Alpha. First built and validated against 38 live sessions. Only whole-session
kills (not individual windows/panes). No auto-scheduling. Session persistence /
revival is tmux-resurrect's job, not this tool's.
