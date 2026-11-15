# workspace_doctor

Workspace cleanup tool: scans `~/workspace/*_workspace/` directories, checks git worktree state, queries GitHub pull request / issue status with the `gh` CLI, classifies each worktree, and drives a close-out flow that archives completed workbench folders and removes merged worktrees.

(Ported from a GitLab version; merge requests became pull requests.)

## Why

Workspaces accumulate stale worktrees and workbench folders over time. Identifying what is safe to remove requires checking PR state, a manual step that rarely gets done. This tool makes it a one-command operation with LLM-assisted classification and a script-driven cleanup.

## Architecture

Three layers, each independently runnable:

**Layer 1: `workspace-scan.py` (no LLM, no API)**
- Walks every `~/workspace/*_workspace/` directory (the parent repo is `~/workspace/<name>/`)
- Runs `git worktree list --porcelain` on each parent repo
- Parses workbench `README.md` metadata tables (`**Worktree**`, `**Branch**`, `**PR**`, `**Status**`) and any GitHub PR / issue URLs in the text
- Detects: prunable, dirty, detached HEAD, ahead-of-origin
- Emits `scan.json`

**Layer 2: `github-check.py` (cheap API calls, no LLM)**
- Takes PR / issue links from `scan.json`
- Uses `gh pr view --json` and `gh issue view --json` to fetch state
- Normalizes PR state to `open | merged | closed | error` (a draft PR is `open` with `draft: true`)
- Adds a local `merged_into_main` flag to each worktree (no API call)
- Emits `scan-with-github.json`

**Layer 3: `cleanup-workspace` skill (single LLM pass)**
- Reads `scan-with-github.json`
- Classifies each worktree/workbench pair
- Presents a grouped report for approval
- On approval: writes `cleanup-manifest.json` and runs `workspace-cleanup.py` (dry-run first, then `--execute`)

## Classification

| Git + PR state | Classification | Recommended action |
|----------------|---------------|-------------------|
| PR merged, worktree clean | `completed` | Archive workbench to `workbench/completed/`, `git worktree remove`, delete branch |
| PR merged, worktree dirty | `completed-with-leftovers` | Same, but flag dirty files for review first |
| PR open | `in-flight` | Keep, show PR link + status |
| No PR, issue open, dirty | `in-progress` | Keep, active local work |
| No PR, issue open, clean | `stalled` | Flag, needs restart or abandon decision |
| No PR, prunable / no issue | `orphan` | Recommend `git worktree remove` |
| Workbench folder with no worktree | `orphan-workbench` | Flag for review |
| Worktree with no workbench README | `no-context` | Flag, cannot fully classify |

## Install

Requirements: Python 3 (stdlib only) and the [GitHub CLI](https://cli.github.com/), authenticated:

```bash
gh auth login
bash setup.sh        # checks the environment and lists discovered workspaces
```

## Usage

```bash
# Layer 1: scan workspaces
python3 workspace-scan.py

# Layer 2: annotate with GitHub PR/issue state
python3 github-check.py

# Layer 3: classify + drive cleanup (run from Claude Code)
# claude -> /cleanup-workspace
```

Install the skill by symlinking `skills/cleanup-workspace` into `~/.claude/skills/`.

All state lives in `~/.config/workspace-doctor/` (override with `WORKSPACE_DOCTOR_DIR` or `--dir`):

| File | Written by |
|------|-----------|
| `scan.json` | `workspace-scan.py` (the sibling `tmux_doctor` tool reads this too) |
| `scan-with-github.json` | `github-check.py` |
| `cleanup-manifest.json` | the `cleanup-workspace` skill, after you approve |
| `cleanup-log.md`, `cleanup-log.html` | `workspace-cleanup.py --execute` |

Environment knobs:

- `WORKSPACE_DOCTOR_DIR`: state directory
- `WORKSPACE_DOCTOR_OWN_BRANCH_RE`: regex for branches that are your own work (default `^build-`); other branches are flagged as someone else's review branches

## Safety

- Layer 3 only acts on a manifest you approved; `workspace-cleanup.py` is dry-run unless `--execute` is passed
- Branches are removed with `git branch -d` (merged only), never `-D`
- Archiving refuses to overwrite an existing destination
- Locked worktrees are never included; commits ahead of upstream count as dirty

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests put a stub `gh` script on `PATH` that prints canned JSON, so they run offline.

## Files

| File | Layer | Purpose |
|------|-------|---------|
| `workspace-scan.py` | 1 | Walk workspaces, git state, README parse -> `scan.json` |
| `github-check.py` | 2 | Annotate `scan.json` with PR/issue state -> `scan-with-github.json` |
| `workspace-cleanup.py` | - | Execute an approved `cleanup-manifest.json` (worktree remove, folder archive) |
| `skills/cleanup-workspace/SKILL.md` | 3 | Companion skill: classify, report, drive approval + cleanup |
| `tests/test_github_check.py` | - | URL parsing, state mapping, stubbed-`gh` tests |
