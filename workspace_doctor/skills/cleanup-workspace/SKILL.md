---
name: cleanup-workspace
description: Classify a workspace scan (git worktree + GitHub PR/issue state), present a grouped cleanup report, write a manifest, and optionally archive completed workbench folders and remove merged worktrees. Use when the user says "clean up my workspaces", "workspace doctor", "what worktrees can I remove", "classify the scan", "show me what can be cleaned up", or after running workspace-scan.py / github-check.py.
---

# cleanup-workspace

Classify a workspace scan, present a cleanup report, write a manifest, and optionally execute it.

Scripts live in the public clone at `~/personal/workshop/workspace_doctor/`. State lives in `~/.config/workspace-doctor/` (or `$WORKSPACE_DOCTOR_DIR`).

## When to use

Run this skill after both scan layers have produced output:
- `scan.json` exists (from `workspace-scan.py`)
- `scan-with-github.json` exists (from `github-check.py`)

If `scan-with-github.json` is missing, run `github-check.py` first (needs the `gh` CLI, authenticated).

## How to invoke

```
/cleanup-workspace
```

Or: "Run cleanup-workspace" / "classify the scan" / "show me what can be cleaned up"

---

## Skill procedure

### Step 1: Load scan data

```bash
cat ~/.config/workspace-doctor/scan-with-github.json
```

If that file does not exist, fall back to `scan.json` and note that GitHub state is unavailable.

### Step 2: Classify each entry

Each entry has `worktree` (or null), `workbench` (or null), and `github` with `prs` and `issues`. PR and issue `state` values are `open | merged | closed | error`; PRs also carry `draft`.

| Conditions | Classification | Recommended action |
|---|---|---|
| All PRs merged, worktree clean | `completed` | Archive workbench to `workbench/completed/`, `git worktree remove`, optionally delete branch |
| All PRs merged, worktree dirty | `completed-with-leftovers` | Same, plus flag dirty files for review first |
| Any PR open (including draft) | `in-flight` | Keep, show PR link + state |
| No PR, any issue open, worktree dirty | `in-progress` | Keep, active local work |
| No PR, any issue open, worktree clean | `stalled` | Flag, needs restart or abandon decision |
| No PR, worktree prunable or no issue | `orphan` | Archive workbench to `workbench/archived/`, `git worktree remove` |
| workbench exists, worktree is null | `orphan-workbench` | Flag for review; archive to `completed/` if all PRs merged, `archived/` otherwise |
| worktree exists, workbench is null | `no-context` | Flag, cannot fully classify without a workbench README |

**Archive destination rules:**
- `workbench/completed/`: PRs confirmed merged (code shipped)
- `workbench/archived/`: work abandoned, superseded, or never merged

The `archive_workbench` manifest action accepts a `"destination"` field (`"completed"` or `"archived"`). Default is `"completed"` if omitted.

Notes on GitHub state:
- `merged` counts as done
- `open` counts as in-flight
- `closed` (not merged) means abandoned; classify toward `orphan` unless dirty
- `error` on a lookup means unknown; classify conservatively as `no-context`
- PRs with `"source": "issue_related"` were found through a closed issue, not the README; mention that in the report
- `worktree.merged_into_main: true` is supporting evidence that the branch shipped even when no PR is tracked

### Step 3: Present grouped report

Show a summary count first:

```
Scan: N entries across K workspaces
  completed: N  |  completed-with-leftovers: N
  in-flight: N  |  in-progress: N  |  stalled: N
  orphan: N  |  orphan-workbench: N  |  no-context: N
```

Then group entries by classification. For each entry list the worktree, its state, the PR/issue link, and the proposed action:

```
## completed (N)
  fix_login_bug
    worktree: myrepo_workspace/myrepo-fix-login-bug  [clean]
    PR myorg/myrepo#42 merged 2026-07-14
    -> archive workbench, remove worktree, delete branch

## in-progress (N)
  dark_mode
    worktree: myrepo_workspace/myrepo-dark-mode  [4 dirty files]  [branch: build-dark-mode]
    issue myorg/myrepo#17 open
    -> keep
```

### Step 4: Ask for approval

> Which entries should I include in the cleanup manifest?
> - **all completed**: only `completed` entries (safest)
> - **all completed + orphans**: also removes orphan worktrees
> - **select**: you tell me which ones
> - **none**: just show the report, do not write a manifest

Wait for the user's response before proceeding.

### Step 5: Write cleanup-manifest.json

For each approved `completed` (or `completed-with-leftovers`) entry, generate three actions in order:

1. `archive_workbench`: move workbench folder to `workbench/completed/`
2. `remove_worktree`: `git worktree remove`
3. `remove_branch`: delete local branch (only if the worktree is confirmed clean and `has_upstream: true`)

For approved `orphan` entries with no workbench: `remove_worktree`, then `remove_branch` if applicable.

Write to `~/.config/workspace-doctor/cleanup-manifest.json`:

```json
{
  "generated_at": "<ISO timestamp>",
  "approved_by": "user",
  "actions": [
    {
      "type": "archive_workbench",
      "label": "fix_login_bug",
      "workbench_path": "/Users/me/workspace/myrepo_workspace/workbench/fix_login_bug",
      "workspace_path": "/Users/me/workspace/myrepo_workspace",
      "destination": "completed"
    },
    {
      "type": "remove_worktree",
      "label": "myrepo-fix-login-bug",
      "worktree_path": "/Users/me/workspace/myrepo_workspace/myrepo-fix-login-bug",
      "parent_repo": "/Users/me/workspace/myrepo"
    },
    {
      "type": "remove_branch",
      "label": "build-fix-login-bug",
      "branch": "build-fix-login-bug",
      "parent_repo": "/Users/me/workspace/myrepo"
    }
  ]
}
```

### Step 6: Dry-run preview

```bash
python3 ~/personal/workshop/workspace_doctor/workspace-cleanup.py
```

Show the output and ask: "Does this look right? Reply 'yes' to execute, or 'no' to cancel."

### Step 7: Execute (on user confirmation only)

```bash
python3 ~/personal/workshop/workspace_doctor/workspace-cleanup.py --execute
```

Report the result. If any action failed, surface the error and suggest remediation. The run is logged to `~/.config/workspace-doctor/cleanup-log.md` and `.html`.

---

## Edge cases

| Situation | How to handle |
|---|---|
| `completed-with-leftovers` | Include in the report with the dirty file list; ask the user to confirm before adding to the manifest |
| PR closed (not merged) + clean worktree | Classify as `orphan`: closed without merging is abandoned |
| Multiple PRs in one workbench | All must be merged (or closed) for `completed`; any open PR means `in-flight` |
| Worktree locked | Never include in cleanup; mention it and skip |
| `ahead_count > 0` | Treat as dirty even if `dirty_files` is empty: unpushed commits exist |
| `has_upstream: false` | Cannot determine ahead count; classify conservatively |
| `is_own_branch: false` | A review branch for someone else's PR; do not delete the branch without asking |
| GitHub error on a URL fetch | Mark that entry `no-context`; do not guess |
