---
name: scaffold-workspace
description: Create a new project workspace folder with workbench, worktree, workspace CLAUDE.md, and .code-workspace file. Use when the user wants to set up a new project workspace, create a workspace for a new project, or start working on a new project initiative. Also handles adding new initiatives to an existing workspace.
---

# Scaffold Project Workspace

Set up a standardized project workspace at `~/workspace/<project>_workspace/` with a workbench, git worktree, workspace CLAUDE.md, and multi-root `.code-workspace` file.

## Prerequisites

The main project repository must already be cloned at `~/workspace/<project>/`. This skill does NOT clone from GitLab.

## When to Use

- User wants to create a new `<project>_workspace/` folder
- User mentions "set up a workspace for \<project\>"
- User wants to add a new initiative/feature to an existing workspace

## Fleet integration (make new work show up in the dashboard)

This skill is the **front door of the single work process**: scaffolding a
workspace should produce *fleet-format* work so it appears, correctly linked, in
the fleet dashboard (`workshop/fleet-dashboard/`). The dashboard pairs an
initiative's worktree, workbench, and plan card **by a shared, normalized slug**,
so consistency is everything:

1. **One canonical `<slug>`** per initiative, used EVERYWHERE: the worktree dir
   (`<repo>-<slug>`), the branch (**`build-<slug>`** — NOT `build-<username>-…`;
   the username breaks the dashboard's slug-pairing), the workbench folder
   (`workbench/<slug>/`), and the plan card. Normalize to hyphens (`_`/spaces →
   `-`, lowercase).

2. **Always create the paired workbench folder** `workbench/<slug>/` (with a
   README) alongside the worktree — the local working surface the dashboard reads
   and pairs to the worktree.

3. **Write a plan card** to the work-repo's `plans/active/<slug>.md` (or
   `<slug>/README.md`) with frontmatter `title:` and a one-line **Goal:** — the
   durable, dashboard-readable record (shows even for cloud work). A plan card is
   a tracking artifact, not code: commit it to the repo's main so it shows
   immediately (don't strand it on the feature branch).

4. **A product-level plan MUST declare its implementation repo** via frontmatter
   `repo: <org>/<repo>` (e.g. `repo: Jwrobes-Magic/claw-playbook`). A plan that
   lives in the planning/coordinator repo (`<product>-workbench`) but implements
   elsewhere is **unreachable** from a session scoped to the impl repo — so the
   `repo:` field is what tells `spec-to-issue` *where to file the issue* and the
   dashboard's launch prompt to **copy the spec INLINE into an issue in that repo**
   (never link the local plan doc). Without it, the launch prompt can't route the
   work to a reachable place. (A plan that lives in the same repo it implements in
   may omit `repo:` — it's already reachable.) This is the structural guard
   against the planning→impl reachability dead-end.

Result: the moment you scaffold, the dashboard shows the new initiative as one
slug-paired card (plan + workbench + worktree), launchable via its handoff
prompt. (Cloud-only work skips the local worktree/workbench — just the plan card +
a GitHub issue; see `spec-to-issue`. scaffold-workspace lives in `jwrobes/skills`,
not workshop, because every project uses it — it's *paired with* the fleet by
this convention, not co-located.)

## The bootstrap-files pattern

Many projects need credentials or config files (Shopify store passwords, API keys, asdf `.tool-versions`) that aren't safe to commit but need to be available to commands run from inside a worktree. The pattern this skill uses:

- The canonical file lives at `~/workspace/<project>_workspace/<file>` (the workspace root)
- Each worktree has a symlink to it: `~/workspace/<project>_workspace/<project>-<initiative>/<file> -> ../<file>`
- The workspace `.gitignore` excludes `<file>` so it's never committed to the workspace repo
- The project repo's `.gitignore` should also exclude it (verify when scaffolding)

This means: update the file in one place, every worktree picks up the change. Commands like `source .env.local` work from inside any worktree.

## Step 1: Gather Information

Ask the user for the following. Use sensible defaults where noted.

1. **Project name** — The name of the project repo (e.g., `my-app`, `api-service`). Verify it exists at `~/workspace/<project>/`.
2. **Initiative name** — What's the first unit of work? (e.g., `auth_refactor`, `dark_mode`). This becomes both the workbench subfolder and part of the worktree directory name. Use `lowercase_with_underscores`.
3. **Branch name** — Git branch for the worktree. Default: **`build-<slug>`** (the canonical hyphenated initiative slug — see Fleet integration above; do NOT prefix the username, it breaks dashboard slug-pairing).
4. **Reference projects** — Other repos the agent should have access to while working on this initiative. List of project names. The user can skip this.
5. **Shared bootstrap files** — Does this project need any files at the workspace root that should be symlinked into every worktree? Common examples: `.env.local` (API keys, store passwords for Shopify/Vercel/etc.), `.tool-versions` (asdf), `credentials.json`. List them. The skill will create the file(s) at the workspace root, add them to `.gitignore`, and symlink them into each worktree so commands run from inside a worktree can read them.

## Step 2: Validate

1. Confirm `~/workspace/<project>/` exists and is a git repo
2. Check whether `~/workspace/<project>_workspace/` already exists
   - If it does → skip to **Add Initiative to Existing Workspace** (at the bottom of this doc)
   - If it doesn't → proceed with full workspace creation
3. Confirm the branch name doesn't already exist in the project repo: `cd ~/workspace/<project> && git branch --list <branch_name>`

## Step 3: Create the Workspace Structure

```bash
mkdir -p ~/workspace/<project>_workspace
cd ~/workspace/<project>_workspace
git init
mkdir -p workbench/<initiative_name>
mkdir -p .claude/skills
```

### Write `.gitignore`

```
# Worktree directories (created from ~/workspace/<project>)
<project>-*/

# Workspace-shared bootstrap files (credentials, env vars, etc.)
# Lives at the workspace root and is symlinked into each worktree.
.env*

# OS files
.DS_Store
*.swp
*.swo

# Large data files
*.csv
*.parquet
```

## Step 4: Create the Git Worktree

```bash
cd ~/workspace/<project>
git worktree add ~/workspace/<project>_workspace/<project>-<initiative_slugified> -b <branch_name>
```

Where `<initiative_slugified>` converts underscores to hyphens (e.g., `coverage_transfer_bug` → `coverage-transfer-bug`).

## Step 4.5: Symlink Shared Bootstrap Files Into the Worktree

If the user named bootstrap files in Step 1, do the following for each one. If they didn't name any, skip this step entirely.

1. **Create the canonical file at the workspace root** with a placeholder template. For example, for `.env.local`:

   ```bash
   cat > ~/workspace/<project>_workspace/.env.local <<'EOF'
   # Workspace-shared environment vars. Each worktree symlinks this. Do not commit.
   SHOPIFY_STORE_PASSWORD=
   EOF
   ```

   Include any keys the user mentioned, with `=` and a placeholder value they can fill in.

2. **Symlink the file into the worktree:**

   ```bash
   cd ~/workspace/<project>_workspace/<project>-<initiative_slugified>
   ln -s ../<filename> <filename>
   ```

   The workspace root holds the canonical file (one place to update credentials). Each worktree has a symlink, so the file is reachable as `./<filename>` from inside any worktree, and `source .env.local` works from the worktree directory.

3. **Verify the project repo's `.gitignore` excludes the file** so the symlink is never committed by accident. The workspace `.gitignore` already excludes it (Step 3). Check `~/workspace/<project>/.gitignore` and add the pattern if missing — note this in your summary so the user can commit that change in the main repo when they're ready.

## Step 5: Create the `.code-workspace` File

Write to `~/workspace/<project>_workspace/workbench/<initiative_name>/<initiative_name>.code-workspace`:

```json
{
  "folders": [
    {
      "name": "worktree: <project>-<initiative_slugified>",
      "path": "../../<project>-<initiative_slugified>"
    },
    {
      "name": "workbench: <initiative_name>",
      "path": "."
    }
  ],
  "settings": {}
}
```

If the user specified reference projects, add entries for each:

```json
{
  "name": "ref: <ref_project> (read-only)",
  "path": "../../../<ref_project>"
}
```

The path `../../../<ref_project>` navigates from `workbench/<initiative>/` up to `~/workspace/` and into the reference project.

## Step 6: Create the Workbench Initiative README

Write to `~/workspace/<project>_workspace/workbench/<initiative_name>/README.md`.

This is the launch document — when Claude Code opens from this folder, the README is the first thing it reads. It must contain enough context to start work without prompting the user for orientation. Populate it from what the user described in Step 1, plus any GitLab issue/MR links they provided.

```markdown
# <initiative title>

<One paragraph: what this work is and why it's being done.>

| | |
|---|---|
| **Issue** | <GitLab issue URL if provided, else "TBD"> |
| **Worktree** | `~/workspace/<project>_workspace/<project>-<initiative_slugified>` |
| **Branch** | `<branch_name>` |
| **MR** | TBD |
| **Status** | In progress |

## Why

<Motivation: what problem this solves or what goal it advances.>

## Work to Do

1. <First concrete step>
2. <Next step>
3. Commit and open MR against `main`

## Key Files

| File | Role |
|------|------|
| <path> | <purpose> |

## Key Directories

This initiative works with:
- Worktree: `~/workspace/<project>_workspace/<project>-<initiative_slugified>/`
- Workbench: `~/workspace/<project>_workspace/workbench/<initiative_name>/` (this folder)

## Start Here

\`\`\`bash
cd ~/workspace/<project>_workspace/workbench/<initiative_name>
claude
# settings.json grants access to the worktree via additionalDirectories
\`\`\`
```

**Important:** If the user provided an issue description or design notes, incorporate them into the README body now. Do not leave placeholder sections empty — a stub README gives Claude nothing to work from when the session reopens.

## Step 7: Create the Workspace CLAUDE.md

Write to `~/workspace/<project>_workspace/CLAUDE.md`. Claude Code auto-loads this file for any session opened inside the workspace, so it carries the workspace rules:

```markdown
# <project> Workspace

This is a multi-root workspace, not a single repo. Layout:

- `workbench/` — Planning docs, analysis scripts, experiments. Tracked by THIS workspace's own git repo (`~/workspace/<project>_workspace/.git`). One subfolder per initiative.
- `<project>-*/` — Git worktrees for active work, created from the main clone at `~/workspace/<project>/`. Each is a separate checkout of the project repo on its own branch.
- `~/workspace/<project>/` — The main project clone. Worktrees are created from it; do NOT work directly in it.

## Commit Rules

1. ONLY commit code changes (features, bug fixes, refactors) in git worktree directories (folders matching `<project>-*/`). Never commit directly to the main project clone at `~/workspace/<project>/`.
2. The workbench directory is tracked by this workspace's own git repo — workbench changes (docs, plans, output) are committed to the workspace repo at `~/workspace/<project>_workspace/`.
3. Never run `git push` from within a worktree without explicit user approval.
4. When creating new files, place them in the correct git context:
   - Code files → worktree directory
   - Documentation, plans, analysis output → workbench initiative folder
5. Before committing, verify you are in the correct directory by checking `git remote -v` — the worktree remote should point to the project's GitLab origin, not the workspace repo.
```

### Optional: Workspace-Scoped Permissions

Optionally create `.claude/settings.json` at the workspace root to allowlist common read-only commands for any Claude Code session in the workspace. Ask the user — they can skip this. Minimal example:

```json
{
  "permissions": {
    "allow": [
      "Bash(git status:*)",
      "Bash(git log:*)",
      "Bash(git diff:*)",
      "Bash(git worktree list:*)",
      "Bash(ls:*)"
    ]
  }
}
```

## Step 8: Check for Project-Specific Setup Skill

Check if `~/workspace/<project>_workspace/.claude/skills/<project>-worktree-setup/SKILL.md` exists. Claude Code discovers skills in a project-level `.claude/skills/` directory.

- **If it exists:** Tell the user: "Found a project-specific worktree setup skill for `<project>`. Running it now..." and follow its instructions to configure the new worktree.
- **If it doesn't exist:** Ask the user: "No project-specific setup skill found for `<project>`. Some projects need special worktree setup (Docker config, `.env` files, credential scripts, etc.). Want to create a setup skill now?" If yes, scaffold a `SKILL.md` at `.claude/skills/<project>-worktree-setup/SKILL.md` by asking what setup steps are needed for this project's worktrees. Suggest including a **symlink-bootstrap-files step** as one of the standard things the setup skill should do — for any `.env*` or other shared credential files at the workspace root, the setup skill should `ln -s ../<filename> <filename>` into each new worktree. This is a recurring pattern (Shopify/Vercel/AWS credentials, asdf `.tool-versions`, etc.) and worth codifying once per project.

## Step 9: Create the Workspace README

Write to `~/workspace/<project>_workspace/README.md`:

```markdown
# <project>-workspace

Workspace for <project>-focused investigations and feature work. Worktrees are created from `~/workspace/<project>/` (the main clone).

## Structure

- `workbench/` — Planning docs, analysis scripts, experiments (tracked in this repo)
- `<project>-<branch>/` — Git worktrees for active work (created from main clone)
- `.claude/skills/` — Project-specific Claude Code skills
- `CLAUDE.md` — Workspace rules auto-loaded by Claude Code

## Setup

```bash
# Open an initiative in Cursor with scoped context
cursor ~/workspace/<project>_workspace/workbench/<initiative_name>/<initiative_name>.code-workspace

# Or start Claude Code from the workspace (CLAUDE.md is auto-loaded)
cd ~/workspace/<project>_workspace && claude

# Create a new worktree for a feature/bug
cd ~/workspace/<project>
git worktree add ~/workspace/<project>_workspace/<project>-<feature> -b build-<username>-<feature>
```

## Active Worktrees

| Worktree | Branch | Initiative |
|----------|--------|------------|
| `<project>-<initiative_slugified>/` | `<branch_name>` | [<initiative_name>](workbench/<initiative_name>/) |

## Git Repositories

| Location | Tracks |
|----------|--------|
| `<project>_workspace/.git` | workbench/ contents |
| `~/workspace/<project>/.git` | Project code (worktree parent) |

## Cleanup

When done with a worktree:

```bash
cd ~/workspace/<project>
git worktree remove ~/workspace/<project>_workspace/<project>-<feature>

# Update the Active Worktrees table above
# Remove its entry from the relevant .code-workspace file
```
```

## Step 10: Initial Commit

```bash
cd ~/workspace/<project>_workspace
git add .
git commit -m "Initialize <project> workspace with <initiative_name> workbench"
```

## Step 11: Summary

Tell the user:
1. Workspace created at `~/workspace/<project>_workspace/`
2. Worktree created at `~/workspace/<project>_workspace/<project>-<initiative_slugified>/` on branch `<branch_name>`
3. Open in Cursor: `cursor ~/workspace/<project>_workspace/workbench/<initiative_name>/<initiative_name>.code-workspace`
4. Workbench initiative folder: `~/workspace/<project>_workspace/workbench/<initiative_name>/`

---

## Add Initiative to Existing Workspace

If `~/workspace/<project>_workspace/` already exists, add a new initiative without re-creating the workspace:

1. **Ask** for initiative name, branch name, and reference projects (same as Step 1)
2. **Create** `workbench/<initiative_name>/` directory
3. **Create the worktree:**
   ```bash
   cd ~/workspace/<project>
   git worktree add ~/workspace/<project>_workspace/<project>-<initiative_slugified> -b <branch_name>
   ```
4. **Create** the `.code-workspace` file in `workbench/<initiative_name>/`
5. **Create** `workbench/<initiative_name>/README.md` (same as Step 6 above) — populate with the initiative description and any issue/MR links the user provided. Do not leave it empty.
6. **Symlink shared bootstrap files** — for each `.env*` file (or other shared credential file) at the workspace root, create a symlink in the new worktree so commands run from the worktree directory can source them:
   ```bash
   cd ~/workspace/<project>_workspace/<project>-<initiative_slugified>
   for f in ../.env*; do
     [ -e "$f" ] && ln -s "$f" "$(basename "$f")"
   done
   ```
   If the project uses other shared files (e.g., `credentials.json`, `.tool-versions`), symlink those too: `ln -s ../<filename> <filename>`.
7. **Update** `.gitignore` — add the new worktree directory pattern if not already covered by the glob
8. **Update** `README.md` — add a row to the Active Worktrees table
9. **Run** the project-specific setup skill if it exists at `.claude/skills/<project>-worktree-setup/SKILL.md`
10. **Migrate older workspaces** — if the workspace predates this version and still has `.cursor/rules/commit-only-in-worktree.mdc` but no `CLAUDE.md` at the workspace root, offer to migrate: write the workspace `CLAUDE.md` (Step 6). Leave the Cursor rule in place for Cursor users, or delete it if the user confirms they no longer use Cursor in this workspace.
11. **Commit:**
   ```bash
   cd ~/workspace/<project>_workspace
   git add .
   git commit -m "Add <initiative_name> initiative with worktree <project>-<initiative_slugified>"
   ```
