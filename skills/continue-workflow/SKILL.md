---
name: continue-workflow
description: Resume a previous working session by finding and loading the most recent continuation prompt. Use when the user says "continue", "pick up where I left off", "resume", "what was I working on", or starts a new session in a project workspace or docs folder and wants to restore context.
disable_model_invocation: true
---

# Continue Workflow

Find and load the most recent continuation prompt to resume work from a previous session.

## When to Use

- User starts a new session and says "continue", "resume", "pick up where I left off"
- User opens a workspace and wants to know the current state of an initiative
- User says "what was I working on?"

## Step 1: Find the Continuation Prompt

Search for continuation prompts and checkpoints in the current directory tree and common locations. Continuation prompts use descriptive filenames: `CONTINUATION_PROMPT--<slug>.md` (the slug describes the session state). Legacy files named exactly `CONTINUATION_PROMPT.md` are also matched.

### Determine search scope from the current working directory:

**If in a project workspace** (`*_workspace/`):
```bash
# Use glob to find all continuation prompts in the workbench
find ~/workspace/<project>_workspace/workbench/ \
  \( -name "CONTINUATION_PROMPT*.md" -o -name "CHECKPOINT.md" \) \
  2>/dev/null
```

**If in a documentation repo** (has a master index file like `*-INDEX.md`):
```bash
find <docs_repo_root>/ -maxdepth 3 \
  \( -name "CONTINUATION_PROMPT*.md" -o -name "CHECKPOINT.md" \) \
  2>/dev/null
```

**If the location is unclear**, search the workspace root:
```bash
find ~/workspace/ -maxdepth 5 \
  \( -name "CONTINUATION_PROMPT*.md" -o -name "CHECKPOINT.md" \) \
  2>/dev/null
```

### Suggest the best match, then ask

When prompts are found, rank them and present to the user:

1. **Folder match first:** If the current directory is inside a specific initiative folder (e.g., `workbench/local_judge_parallelization/`), the prompt from that folder is the top suggestion.
2. **Recency second:** Sort remaining prompts by last-modified date (newest first).
3. **Extract the slug** from the filename to display a human-readable description. The slug is everything between `CONTINUATION_PROMPT--` and `.md`, with hyphens replaced by spaces.

```
Found continuation prompts:

→ 1. local_judge_parallelization/CONTINUATION_PROMPT--judge-concurrency-plumbed-run-5k-baseline-next.md
     "judge concurrency plumbed, run 5k baseline next" (2026-04-10 08:05) ← current folder
  2. sns_sqs_architecture/CONTINUATION_PROMPT--event-schema-v2-migration-next.md
     "event schema v2, migration next" (2026-04-09 16:30)
  3. coverage_transfer_bug/CONTINUATION_PROMPT--root-cause-found-fix-pending.md
     "root cause found, fix pending" (2026-04-07 11:15)

Which would you like to continue? [1]
```

Get last-modified dates with: `stat -f "%Sm" -t "%Y-%m-%d %H:%M" <file>` (macOS)

**Always ask the user** even if there's only one match — confirm before loading context.

### Priority order when multiple prompts exist in the same directory:

1. `CHECKPOINT.md` (if newer than any `CONTINUATION_PROMPT*.md`) — represents auto-saved state from a more recent session
2. The most recent `CONTINUATION_PROMPT*.md` — represents an intentional close-out

## Step 2: Load and Execute the Prompt

1. **Read** the continuation prompt file
2. **Read all files** listed in the "Context Files to Read" section, in the order specified — this is critical for rebuilding context
3. **Review** the "Current State" and "Open TODOs / Next Steps" sections
4. **Note** the "Key Decisions Made" and "Key Constraints" sections — these are guardrails for the session

## Step 3: Present Summary to User

After reading all context files, present a brief summary:

```
Resuming: <Initiative/Project Name>
Last session: <date from the prompt>

What was done:
- <bullet from Session Summary>
- <bullet from Session Summary>

Current state: <1-2 sentences from Current State section>

Next steps:
1. <top TODO>
2. <second TODO>

Ready to continue with "<top TODO>", or would you like to do something else?
```

## Step 4: Verify State

Before starting work, do a quick consistency check:

```bash
# Check for uncommitted changes (might have changed since the prompt was written)
cd <workspace_or_docs_root>
git status --short
```

If in a project workspace:
```bash
# Verify the worktree still exists
ls -d <worktree_path> 2>/dev/null

# Check worktree status
cd <worktree_path>
git status --short
```

**If there are unexpected changes** (files modified since the continuation prompt was written), flag them:
```
Note: These files have changed since the last session close-out:
- <file> (modified after the continuation prompt was written)
You may want to review these before continuing.
```

**If the worktree no longer exists** (was cleaned up), tell the user:
```
The worktree at <path> no longer exists. The branch <branch_name> may still exist in the project repo.
Want to re-create the worktree, or has this initiative been completed?
```

## Step 5: Begin Work

Once the user confirms what to work on, proceed with the task. Keep the continuation prompt's constraints and decisions in mind throughout the session.

## When No Continuation Prompt Is Found

If no `CONTINUATION_PROMPT*.md` or `CHECKPOINT.md` exists:

1. Tell the user: "No continuation prompt found in the current directory tree."
2. Offer to help reconstruct context:
   - Read the README for the current workspace/project
   - Check recent git history: `git log --oneline -10`
   - List recently modified files: `find . -name "*.md" -newer <some_reference> -type f`
3. Ask: "Would you like me to read the README and recent history to figure out where things stand?"

## Guidelines

1. **Always read all context files.** The continuation prompt was written specifically to restore context — skipping files means working with incomplete information.
2. **Respect the "Key Decisions Made" section.** Don't re-litigate settled decisions unless the user explicitly wants to revisit them.
3. **CHECKPOINT.md takes precedence** over `CONTINUATION_PROMPT*.md` if both exist in the same directory and CHECKPOINT.md has a newer timestamp — it represents a more recent auto-saved state.
4. **Don't modify the continuation prompt during this skill.** It's a read-only input. A new one will be written by `/close-out-session` at the end of the session.
5. **If the continuation prompt references files that no longer exist**, flag this to the user rather than silently skipping them — it might indicate work was completed or reorganized.
