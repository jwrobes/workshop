---
name: scaffold-workspace
description: Create a new project workspace folder with workbench, worktree, workspace CLAUDE.md, and .code-workspace file. Use when the user wants to set up a new project workspace, create a workspace for a new project, or start working on a new project initiative. Also handles adding new initiatives to an existing workspace.
---

# Scaffold Project Workspace

Set up a standardized project workspace at `<root>/<project>_workspace/` with a workbench, git worktree, workspace CLAUDE.md, and multi-root `.code-workspace` file.

## Prerequisites

The main project repository must already be cloned at `<root>/<project>/`. This skill does NOT clone from GitLab.

## When to Use

- User wants to create a new `<project>_workspace/` folder
- User mentions "set up a workspace for \<project\>"
- User wants to add a new initiative/feature to an existing workspace

## `<root>`: flat vs. nested layouts

Everything below is written in terms of **`<root>`** — the directory that holds *both* the
main clone and its `_workspace` sibling. The workspace is always created as a **sibling of
the clone**, whatever `<root>` happens to be. There are two layouts:

**Flat (the default).** `<root>` is `~/workspace/`. Most projects use this:

```
~/workspace/                    <- <root>
  yogada/                       <- main clone
  yogada_workspace/             <- workspace
```

**Nested (an org folder).** When several related repos belong to one org/product, they get
grouped in an org folder and `<root>` is that folder. Each repo still gets its own
`_workspace` sibling *inside* it:

```
~/workspace/
  AImposter-Syndrome/           <- org folder = <root>
    team-brain/                 <- main clone
    team-brain_workspace/       <- workspace (sibling of the clone)
    some-other-repo/
    some-other-repo_workspace/
```

**How to pick.** Resolve `<root>` by finding where the main clone actually lives — do not
assume `~/workspace/<project>/`:

```bash
find ~/workspace -maxdepth 3 -type d -name "<project>" -not -path "*/.git/*"
```

`<root>` is that clone's parent directory. If the clone is at `~/workspace/<project>/`,
`<root>` is `~/workspace/` (flat). If it's at `~/workspace/<org>/<project>/`, `<root>` is
`~/workspace/<org>/` (nested). When the user says they want the repos for one thing
"organized in the same folder," that's the nested layout.

**What changes in a nested layout.** Only two things, because the workspace is a sibling of
the clone either way:

- **Reference-project paths in `.code-workspace`** are relative to the workbench folder, so
  they depend on depth. Flat: `../../../<ref_project>` reaches `~/workspace/`. Nested:
  `../../../<ref_project>` reaches the *org folder* (siblings within the org), and
  `../../../../<ref_project>` reaches `~/workspace/` (repos outside the org). Count the hops
  from `workbench/<initiative>/` and verify the path resolves before writing it.
- **Nothing else.** The worktree, workbench, `.gitignore`, `CLAUDE.md`, and commit rules are
  all expressed relative to the workspace root, so they are layout-independent.

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

- The canonical file lives at `<root>/<project>_workspace/<file>` (the workspace root)
- Each worktree has a symlink to it: `<root>/<project>_workspace/<project>-<initiative>/<file> -> ../<file>`
- The workspace `.gitignore` excludes `<file>` so it's never committed to the workspace repo
- The project repo's `.gitignore` should also exclude it (verify when scaffolding)

This means: update the file in one place, every worktree picks up the change. Commands like `source .env.local` work from inside any worktree.

## Step 1: Gather Information

Ask the user for the following. Use sensible defaults where noted.

1. **Project name** — The name of the project repo (e.g., `my-app`, `api-service`). Verify it exists at `<root>/<project>/`.
2. **Initiative name** — What's the first unit of work? (e.g., `auth_refactor`, `dark_mode`). This becomes both the workbench subfolder and part of the worktree directory name. Use `lowercase_with_underscores`.
3. **Branch name** — Git branch for the worktree. Default: **`build-<slug>`** (the canonical hyphenated initiative slug — see Fleet integration above; do NOT prefix the username, it breaks dashboard slug-pairing).
4. **Reference projects** — Other repos the agent should have access to while working on this initiative. List of project names. The user can skip this.
5. **Shared bootstrap files** — Does this project need any files at the workspace root that should be symlinked into every worktree? Common examples: `.env.local` (API keys, store passwords for Shopify/Vercel/etc.), `.tool-versions` (asdf), `credentials.json`. List them. The skill will create the file(s) at the workspace root, add them to `.gitignore`, and symlink them into each worktree so commands run from inside a worktree can read them.

## Step 2: Validate

0. **Resolve `<root>` first** — locate the main clone and take its parent (see the `<root>`
   section above). Don't assume the flat layout:
   ```bash
   find ~/workspace -maxdepth 3 -type d -name "<project>" -not -path "*/.git/*"
   ```
   If the clone sits inside an org folder, `<root>` is that org folder and the workspace goes
   beside the clone, inside it. State the resolved `<root>` to the user before creating
   anything, so a wrong guess is caught before it makes directories.
1. Confirm `<root>/<project>/` exists and is a git repo
2. Check whether `<root>/<project>_workspace/` already exists
   - If it does → skip to **Add Initiative to Existing Workspace** (at the bottom of this doc)
   - If it doesn't → proceed with full workspace creation
3. Confirm the branch name doesn't already exist in the project repo: `cd <root>/<project> && git branch --list <branch_name>`

## Step 3: Create the Workspace Structure

```bash
mkdir -p <root>/<project>_workspace
cd <root>/<project>_workspace
git init
mkdir -p workbench/<initiative_name>
mkdir -p .claude/skills
```

### Write `.gitignore`

```
# Worktree directories (created from <root>/<project>)
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
cd <root>/<project>
git worktree add <root>/<project>_workspace/<project>-<initiative_slugified> -b <branch_name>
```

Where `<initiative_slugified>` converts underscores to hyphens (e.g., `coverage_transfer_bug` → `coverage-transfer-bug`).

## Step 4.5: Symlink Shared Bootstrap Files Into the Worktree

If the user named bootstrap files in Step 1, do the following for each one. If they didn't name any, skip this step entirely.

1. **Create the canonical file at the workspace root** with a placeholder template. For example, for `.env.local`:

   ```bash
   cat > <root>/<project>_workspace/.env.local <<'EOF'
   # Workspace-shared environment vars. Each worktree symlinks this. Do not commit.
   SHOPIFY_STORE_PASSWORD=
   EOF
   ```

   Include any keys the user mentioned, with `=` and a placeholder value they can fill in.

2. **Symlink the file into the worktree:**

   ```bash
   cd <root>/<project>_workspace/<project>-<initiative_slugified>
   ln -s ../<filename> <filename>
   ```

   The workspace root holds the canonical file (one place to update credentials). Each worktree has a symlink, so the file is reachable as `./<filename>` from inside any worktree, and `source .env.local` works from the worktree directory.

3. **Verify the project repo's `.gitignore` excludes the file** so the symlink is never committed by accident. The workspace `.gitignore` already excludes it (Step 3). Check `<root>/<project>/.gitignore` and add the pattern if missing — note this in your summary so the user can commit that change in the main repo when they're ready.

## Step 5: Create the `.code-workspace` File

Write to `<root>/<project>_workspace/workbench/<initiative_name>/<initiative_name>.code-workspace`:

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

**These paths are relative to `workbench/<initiative>/`, so the hop count depends on the
layout — this is the one place a nested workspace genuinely differs.** Three hops
(`../../../`) climbs `workbench/<initiative>/` → `workbench/` → the workspace root → and
lands in **`<root>`**. So:

- **Flat layout** (`<root>` is `~/workspace/`): `../../../<ref_project>` reaches any repo in
  `~/workspace/`. Three hops is correct.
- **Nested layout** (`<root>` is an org folder): `../../../<ref_project>` reaches repos
  *inside the org folder*. To reference a repo outside it, add a hop —
  `../../../../<ref_project>` reaches `~/workspace/`.

Verify before writing; a bad relative path fails silently as an empty folder in the editor:

```bash
cd <root>/<project>_workspace/workbench/<initiative_name>
ls -d ../../../<ref_project>   # add or remove hops until this resolves
```

## Step 5.5: Create `.claude/settings.json` — the Claude Code equivalent of `.code-workspace`

**Do not skip this. It is the counterpart to Step 5, not an optional extra.** Step 5 gives
*Cursor* multi-root access to the worktree. Without this step, a **Claude Code** session
can't reach the worktree at all — the workspace is a different git repo than the worktree,
so the worktree is outside the session's cwd scope. The symptom is that Claude can see
`workbench/` but not the code it's supposed to be working on, and the scaffold looks complete
while being half-wired.

The mechanism is **`permissions.additionalDirectories`** — the persistent, checked-in
equivalent of the `--add-dir` CLI flag.

### Write it in BOTH places — settings do not cascade

**Claude Code reads `.claude/settings.json` from the directory you launch it in. It does NOT
walk up the tree to find one.** This is the trap: a settings file at the workspace root is
invisible to a session started in `workbench/<initiative>/`, which is exactly where people
naturally `cd` to work — it's the folder that holds the initiative's docs and its
`.code-workspace`. Verified behavior: launching from the workbench folder with only a
root-level settings file produces *no* config discovery at all.

So write **two** files, differing only in path depth:

**1. Workspace root** — `<root>/<project>_workspace/.claude/settings.json`:

```json
{
  "permissions": {
    "additionalDirectories": [
      "./<project>-<initiative_slugified>",
      "../<project>"
    ]
  }
}
```

**2. Each initiative's workbench folder** —
`<root>/<project>_workspace/workbench/<initiative_name>/.claude/settings.json`. Same
directories, but two hops deeper, so every `../` count shifts by two:

```json
{
  "permissions": {
    "additionalDirectories": [
      "../../<project>-<initiative_slugified>",
      "../../../<project>"
    ]
  }
}
```

In both files:

- The **first** entry is the worktree — the whole point. One entry per worktree; when you add
  an initiative later, add its worktree to the root file too (see the Add Initiative flow).
- The **second** is the main clone, so a session can read the repo's existing code/docs for
  context. Read-context only — the `CLAUDE.md` commit rules still forbid working there.
- Paths are relative **to the file's own directory** and work in flat and nested layouts
  alike (absolute paths and `~` also work, but relative keeps the workspace portable). This
  relativity is precisely why the two files can't be identical.

**Trust is granted at the git-repo boundary, not per folder** — so accepting the trust dialog
once covers both launch points. The user does not get a second prompt for the workbench
folder.

**What this does and does not do.** `permissions.additionalDirectories` grants **file access
only** — it does *not* load `.claude/` config, skills, or a `CLAUDE.md` from the added
directory. The `--add-dir` flag and `/add-dir` command *do* load that config. So if a
worktree ever carries its own `CLAUDE.md` the session must honor, start with
`claude --add-dir ./<project>-<initiative_slugified>` instead. For the common case — reach
the worktree's files from a workspace-root session — the settings key is the right tool,
because it's persistent and checked in rather than something to retype each session.

Then **verify both files**, because a wrong path here fails quietly:

```bash
# 1. workspace root
cd <root>/<project>_workspace
python3 -c "import json;json.load(open('.claude/settings.json'))" && echo "valid JSON"
for d in ./<project>-<initiative_slugified> ../<project>; do
  [ -d "$d" ] && echo "OK  $d" || echo "BROKEN  $d"
done

# 2. the workbench initiative folder (deeper — different hop counts)
cd <root>/<project>_workspace/workbench/<initiative_name>
python3 -c "import json;json.load(open('.claude/settings.json'))" && echo "valid JSON"
for d in ../../<project>-<initiative_slugified> ../../../<project>; do
  [ -d "$d" ] && echo "OK  $d" || echo "BROKEN  $d"
done
```

To confirm Claude Code actually *finds* a settings file from a given directory, run
`claude --debug -p "reply OK"` there and look for a line mentioning
`permissions.additionalDirectories`. **Silence means the file was never found** — that is the
failure mode this step exists to prevent, and it looks identical to success unless you check.

### The trust gotcha — tell the user about this

`additionalDirectories` is **silently ignored in a freshly-scaffolded workspace until the
workspace is trusted.** Claude Code will parse the key, then drop the entries with:

```
Ignoring N permissions.additionalDirectories entries from .claude/settings.json:
this workspace has not been trusted.
```

Trust is granted per-directory, and a workspace you just created has never been trusted. The
fix is for **the user** to run `claude` in the workspace once and accept the trust dialog:

```bash
cd <root>/<project>_workspace && claude
```

**Do not flip the trust flag for them** by editing `hasTrustDialogAccepted` in
`~/.claude.json`. Trust is a security boundary — marking a directory trusted on the user's
behalf is precisely what that dialog exists to prevent. Surface it in the summary as a
one-time step they must do themselves, and note that until they do, Claude Code sessions in
the workspace won't see the worktree.

## Step 6: Create the Workspace CLAUDE.md

Write to `<root>/<project>_workspace/CLAUDE.md`. Claude Code auto-loads this file for any session opened inside the workspace, so it carries the workspace rules:

```markdown
# <project> Workspace

This is a multi-root workspace, not a single repo. Layout:

- `workbench/` — Planning docs, analysis scripts, experiments. Tracked by THIS workspace's own git repo (`<root>/<project>_workspace/.git`). One subfolder per initiative.
- `<project>-*/` — Git worktrees for active work, created from the main clone at `<root>/<project>/`. Each is a separate checkout of the project repo on its own branch.
- `<root>/<project>/` — The main project clone. Worktrees are created from it; do NOT work directly in it.

## Commit Rules

1. ONLY commit code changes (features, bug fixes, refactors) in git worktree directories (folders matching `<project>-*/`). Never commit directly to the main project clone at `<root>/<project>/`.
2. The workbench directory is tracked by this workspace's own git repo — workbench changes (docs, plans, output) are committed to the workspace repo at `<root>/<project>_workspace/`.
3. Never run `git push` from within a worktree without explicit user approval.
4. When creating new files, place them in the correct git context:
   - Code files → worktree directory
   - Documentation, plans, analysis output → workbench initiative folder
5. Before committing, verify you are in the correct directory by checking `git remote -v` — the worktree remote should point to the project's GitLab origin, not the workspace repo.
```

### Optional: Workspace-Scoped Permissions

`.claude/settings.json` already exists from Step 5.5 (it holds `additionalDirectories`). You
can *optionally* also allowlist common read-only commands there, so routine calls don't
prompt. **Ask the user first — do not add allow rules unprompted.** Widening what runs
without a prompt is the user's call, not the scaffold's:

```json
{
  "permissions": {
    "additionalDirectories": ["./<project>-<initiative_slugified>", "../<project>"],
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

## Step 7: Check for Project-Specific Setup Skill

Check if `<root>/<project>_workspace/.claude/skills/<project>-worktree-setup/SKILL.md` exists. Claude Code discovers skills in a project-level `.claude/skills/` directory.

- **If it exists:** Tell the user: "Found a project-specific worktree setup skill for `<project>`. Running it now..." and follow its instructions to configure the new worktree.
- **If it doesn't exist:** Ask the user: "No project-specific setup skill found for `<project>`. Some projects need special worktree setup (Docker config, `.env` files, credential scripts, etc.). Want to create a setup skill now?" If yes, scaffold a `SKILL.md` at `.claude/skills/<project>-worktree-setup/SKILL.md` by asking what setup steps are needed for this project's worktrees. Suggest including a **symlink-bootstrap-files step** as one of the standard things the setup skill should do — for any `.env*` or other shared credential files at the workspace root, the setup skill should `ln -s ../<filename> <filename>` into each new worktree. This is a recurring pattern (Shopify/Vercel/AWS credentials, asdf `.tool-versions`, etc.) and worth codifying once per project.

## Step 8: Create the Workspace README

Write to `<root>/<project>_workspace/README.md`:

```markdown
# <project>-workspace

Workspace for <project>-focused investigations and feature work. Worktrees are created from `<root>/<project>/` (the main clone).

## Structure

- `workbench/` — Planning docs, analysis scripts, experiments (tracked in this repo)
- `<project>-<branch>/` — Git worktrees for active work (created from main clone)
- `.claude/skills/` — Project-specific Claude Code skills
- `CLAUDE.md` — Workspace rules auto-loaded by Claude Code

## Setup

```bash
# Open an initiative in Cursor with scoped context
cursor <root>/<project>_workspace/workbench/<initiative_name>/<initiative_name>.code-workspace

# Or start Claude Code from the workspace (CLAUDE.md is auto-loaded)
cd <root>/<project>_workspace && claude

# Create a new worktree for a feature/bug
cd <root>/<project>
git worktree add <root>/<project>_workspace/<project>-<feature> -b build-<username>-<feature>
```

## Active Worktrees

| Worktree | Branch | Initiative |
|----------|--------|------------|
| `<project>-<initiative_slugified>/` | `<branch_name>` | [<initiative_name>](workbench/<initiative_name>/) |

## Git Repositories

| Location | Tracks |
|----------|--------|
| `<project>_workspace/.git` | workbench/ contents |
| `<root>/<project>/.git` | Project code (worktree parent) |

## Cleanup

When done with a worktree:

```bash
cd <root>/<project>
git worktree remove <root>/<project>_workspace/<project>-<feature>

# Update the Active Worktrees table above
# Remove its entry from the relevant .code-workspace file
```
```

## Step 9: Initial Commit

```bash
cd <root>/<project>_workspace
git add .
git commit -m "Initialize <project> workspace with <initiative_name> workbench"
```

## Step 10: Summary

Tell the user:
1. Workspace created at `<root>/<project>_workspace/`
2. Worktree created at `<root>/<project>_workspace/<project>-<initiative_slugified>/` on branch `<branch_name>`
3. Open in Cursor: `cursor <root>/<project>_workspace/workbench/<initiative_name>/<initiative_name>.code-workspace`
4. Workbench initiative folder: `<root>/<project>_workspace/workbench/<initiative_name>/`
5. **One-time step they must do themselves:** trust the workspace so
   `additionalDirectories` takes effect, otherwise Claude Code sessions started at the
   workspace root cannot see the worktree:

   ```bash
   cd <root>/<project>_workspace && claude   # accept the trust dialog once
   ```

   Say plainly that until they do this, the Claude side of the multi-root setup is inert
   (Cursor will work regardless). Do not set the trust flag for them.

---

## Add Initiative to Existing Workspace

If `<root>/<project>_workspace/` already exists, add a new initiative without re-creating the workspace:

1. **Ask** for initiative name, branch name, and reference projects (same as Step 1)
2. **Create** `workbench/<initiative_name>/` directory
3. **Create the worktree:**
   ```bash
   cd <root>/<project>
   git worktree add <root>/<project>_workspace/<project>-<initiative_slugified> -b <branch_name>
   ```
4. **Create** the `.code-workspace` file in `workbench/<initiative_name>/`
4.5. **Wire up Claude Code — BOTH files (see Step 5.5).** Skipping this is the most common way
   this skill half-works: the new initiative opens fine in Cursor but is invisible to Claude
   Code.
   - **Root** `.claude/settings.json`: append `"./<project>-<initiative_slugified>"` to
     `permissions.additionalDirectories` (keep the existing worktrees listed).
   - **New** `workbench/<initiative_name>/.claude/settings.json`: create it, with the
     two-hops-deeper paths (`../../<worktree>`, `../../../<project>`). Settings do not
     cascade from the workspace root, so an initiative folder without its own file cannot see
     its own worktree.

   If the workspace predates Step 5.5 and has no `.claude/settings.json` at all, create the
   root one now listing **every** existing worktree, and backfill a settings file into each
   existing workbench initiative folder.
5. **Symlink shared bootstrap files** — for each `.env*` file (or other shared credential file) at the workspace root, create a symlink in the new worktree so commands run from the worktree directory can source them:
   ```bash
   cd <root>/<project>_workspace/<project>-<initiative_slugified>
   for f in ../.env*; do
     [ -e "$f" ] && ln -s "$f" "$(basename "$f")"
   done
   ```
   If the project uses other shared files (e.g., `credentials.json`, `.tool-versions`), symlink those too: `ln -s ../<filename> <filename>`.
6. **Update** `.gitignore` — add the new worktree directory pattern if not already covered by the glob
7. **Update** `README.md` — add a row to the Active Worktrees table
8. **Run** the project-specific setup skill if it exists at `.claude/skills/<project>-worktree-setup/SKILL.md`
9. **Migrate older workspaces** — if the workspace predates this version and still has `.cursor/rules/commit-only-in-worktree.mdc` but no `CLAUDE.md` at the workspace root, offer to migrate: write the workspace `CLAUDE.md` (Step 6). Leave the Cursor rule in place for Cursor users, or delete it if the user confirms they no longer use Cursor in this workspace.
10. **Commit:**
   ```bash
   cd <root>/<project>_workspace
   git add .
   git commit -m "Add <initiative_name> initiative with worktree <project>-<initiative_slugified>"
   ```
