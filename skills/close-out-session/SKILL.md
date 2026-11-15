---
name: close-out-session
description: Close out the current working session by summarizing progress, capturing uncommitted changes, writing a continuation prompt, updating READMEs, and committing. Use when the user says "close out", "wrap up", "save my context", "create a handoff", or wants to end a session with a clean handoff for the next one.
disable_model_invocation: true
---

# Close Out Session

Generate a continuation prompt and update documentation so the next session (or a different agent) can pick up exactly where this one left off.

## When to Use

- User says "close out", "wrap up", "let's stop here", "save context", "create a handoff"
- User is about to switch to a different task or end for the day
- Session is getting long and context might be lost

## Step 1: Determine Context

Figure out what kind of workspace you're in by examining the current working directory and project structure:

| Context | Signal | Continuation Prompt Directory |
|---------|--------|-------------------------------|
| Project workspace initiative | Inside `<project>_workspace/` with a `workbench/` folder | `<project>_workspace/workbench/<initiative>/` |
| Documentation repo project | Inside a git repo with a master index file (`*-INDEX.md`) | `<docs_repo>/<project>/` |
| Documentation repo subfolder | Inside a docs repo subfolder | `<docs_repo>/<project>/<subfolder>/` |

If the location is ambiguous (e.g., work spanned multiple initiatives), ask the user where the continuation prompt should be saved.

For project workspaces, identify the specific initiative by checking which workbench subfolder has been actively worked on (most recently modified files, or ask the user).

### Filename Convention

Continuation prompts use descriptive filenames so you can tell what a session was about without opening the file:

```
CONTINUATION_PROMPT--<slug-describing-state-and-next-step>.md
```

The slug should capture **what was done** and **what's next** in a few hyphenated words. Examples:
- `CONTINUATION_PROMPT--schema-migrated-api-endpoints-next.md`
- `CONTINUATION_PROMPT--speed-tests-done-plumb-concurrency-flag.md`
- `CONTINUATION_PROMPT--draft-rfc-ready-for-review.md`

Rules:
- Always start with `CONTINUATION_PROMPT--` (the `continue-workflow` skill globs for this prefix)
- Use lowercase, hyphen-separated words
- Keep under ~80 chars total
- Delete any existing `CONTINUATION_PROMPT*.md` files in the same directory before writing (the old version is preserved in git history)

## Step 2: Gather Session State

### From git

Run these commands to capture the current state:

```bash
# Workspace repo status (tracks workbench)
cd <workspace_or_docs_root>
git status --short
git log --oneline -5
```

If in a project workspace, also check the worktree:
```bash
cd <worktree_directory>
git status --short
git diff --stat
git log --oneline -5
```

### From the conversation

Review the current conversation to extract:
- Files created or modified during this session
- Tasks completed
- Decisions made (architectural, design, workflow)
- Work still in progress or blocked
- Open questions or TODOs discussed

### From the file system

Read the existing README for the initiative/project to understand:
- What status fields exist and need updating
- The current folder structure (to update if new files were added)
- The document index (to add new entries)

## Step 3: Write the Continuation Prompt

Remove any existing `CONTINUATION_PROMPT*.md` files in the target directory, then write the new file using the descriptive filename convention from Step 1.

Use this template, filling in every section from the state gathered in Step 2:

```markdown
# Continuation Prompt — <Initiative/Project Name>

**Last updated:** <YYYY-MM-DD HH:MM>
**Workspace type:** <project_workspace | docs_project | docs_subfolder>

Copy everything below the line into a new Cursor CLI or Claude session to resume this work.

---

I'm continuing work on <initiative/project description — 1-2 sentences of what this is about>. This is a handoff from a previous session. Please read the following files to rebuild context, then we'll pick up where we left off.

## Context Files to Read

<Ordered list of the most important files for the next session to read. Always include:
- The README for the initiative/project
- Any active plan or spec documents
- Recently modified files that contain important state
- Relevant skill files (e.g., project-specific setup skills)
Use absolute paths so they work regardless of where the next session starts.>

1. `<absolute_path>` — <why to read this file>
2. `<absolute_path>` — <why to read this file>

## Session Summary

<2-5 bullet points of what was accomplished this session. Be specific — mention file names, decisions, and concrete outcomes.>

- <accomplishment>
- <accomplishment>

## Current State

<What's in progress, what's blocked, what's the immediate next step. Be concrete.>

## Files Modified (uncommitted)

<From git status. If everything is committed, say "All changes committed.">

| File | Status | What Changed |
|------|--------|-------------|
| `<relative_path>` | modified/new/deleted | <brief description> |

## Open TODOs / Next Steps

<Prioritized list — most important first. Each item should be actionable.>

1. **<Next immediate action>** — <details and any relevant file paths>
2. **<Following action>** — <details>

## Key Decisions Made

<Decisions from this session that the next session should NOT re-litigate.>

- **<Decision>:** <Rationale>

## Key Constraints

<Rules the next session needs to follow — PHI restrictions, commit-only-in-worktree rules, API limitations, etc.>
```

### Template Guidelines

- **Context Files to Read:** This is the most important section. Be generous — list 5-10 files if needed. The next session starts completely cold.
- **Session Summary:** Focus on outcomes, not process. "Created the transform SQL and validated against preprod" not "We talked about how to structure the transform."
- **Open TODOs:** Make them copy-paste actionable. Include commands to run, files to edit, questions to ask.
- **Key Decisions:** Only include decisions that someone might reasonably want to revisit. Don't document obvious things.

## Step 4: Update the README

Read the initiative/project README and update:

1. **Status fields** — Update any "Current Status", "Phase", or similar indicators
2. **Folder tree** — Add any new files created during this session
3. **Document index** — Add entries for any new documents
4. **Open questions / next steps** — Sync with the continuation prompt's TODO list

## Step 5: Commit

```bash
cd <workspace_or_docs_root>
# If you deleted an old CONTINUATION_PROMPT, stage the deletion too
git add <initiative_dir>/CONTINUATION_PROMPT*.md
git add <path_to_README.md>
# Add any other documentation files that were updated during this session
git commit -m "Close out session: <brief description of work done>"
```

If in a project workspace, only commit to the workspace repo (workbench changes). Do NOT commit to the worktree repo as part of close-out — that's the user's responsibility.

## Step 6: Tell the User

Summarize:
1. Continuation prompt written to `<path>`
2. README updated at `<path>`
3. Changes committed to `<repo>`
4. Uncommitted worktree changes (if any) listed for awareness
5. To resume: start a new session and use `/continue-workflow`, or paste the continuation prompt contents directly

## Guidelines

1. **Be thorough in the context files list.** The next session starts cold — it needs enough files to rebuild the full picture without guessing.
2. **Don't include conversation-specific ephemera.** Focus on durable state in files, not things only discussed in chat that didn't get written down anywhere.
3. **Err on the side of more context, not less.** A verbose continuation prompt is better than one that leaves the next session confused.
4. **Use absolute paths** in the continuation prompt so it works regardless of where the next session starts.
5. **Always commit the continuation prompt.** This is insurance — if the session dies after close-out, the handoff is preserved in git.
6. **Don't commit worktree code changes during close-out.** Close-out is for documentation and context preservation only. The user decides when to commit code.
7. **Delete any existing `CONTINUATION_PROMPT*.md`** in the target directory before writing the new one — each directory should have at most one. The old version is preserved in git history.
