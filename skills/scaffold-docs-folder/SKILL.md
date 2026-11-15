---
name: scaffold-docs-folder
description: Create a new project folder or subfolder inside a documentation repo with README scaffolding and index updates. Use when the user wants to add a new documentation project folder, create a subfolder in an existing project, or organize new documentation.
---

# Scaffold Documentation Folder

Create a new project folder or subfolder inside a documentation repo with a properly structured README and updated indexes.

## Paths

Determine the docs repo root dynamically:

1. If the current working directory is inside a docs repo (has a master index markdown file at its root), use that.
2. Otherwise, ask the user: "Which docs repo should I create this folder in?"

| Resource | How to Find |
|----------|-------------|
| Docs repo root | Current directory or user-specified path |
| Master index | Look for `*-INDEX.md` or `INDEX.md` at the repo root |
| Documentation rules | Check for `.cursor/rules/documentation-maintenance.mdc` |

## When to Use

- User wants to create a new project/topic folder in a docs repo
- User wants to add a subfolder within an existing project
- User mentions "new docs folder", "new project in docs", "add a folder for \<topic\>"

## Step 1: Determine Scope

Ask the user:

1. **Top-level or subfolder?**
   - Top-level: new project folder directly under the docs repo root
   - Subfolder: new folder inside an existing project (e.g., `<existing_project>/new_analysis/`)

2. **Folder name** — Use `lowercase_with_underscores` per repo conventions.

3. **Brief description** — 1-2 sentences about what this folder covers.

4. **Related workspace?** — "Is this docs folder related to a project workspace (e.g., `<project>_workspace`)? If so, which one?"

## Step 2: Create the Folder and README

### For Top-Level Project Folders

Create `<docs_repo_root>/<folder_name>/README.md`:

```markdown
# <Title (Title Case of folder name)>

**Status:** Active

---

## Overview

<Brief description from Step 1>

**Related Workspace:** `~/workspace/<project>_workspace/`
<!-- Remove the Related Workspace line if no workspace relationship -->

---

## Folder Structure

```
<folder_name>/
├── README.md          # This file
```

---

## Document Index

| Document | Description |
|----------|-------------|

---

## Related Resources

<!-- Links to other docs folders, external references, or workspace initiatives -->
```

### For Subfolders

Create `<docs_repo_root>/<project>/<subfolder_name>/README.md`:

```markdown
# <Title>

## Purpose

<Brief description from Step 1>

## Context

<Enough background for an LLM to understand the domain without reading every file. Ask the user for this or infer from the parent project's README.>

**Related Workspace:** `~/workspace/<project>_workspace/`
<!-- Remove if no workspace relationship -->

## File Guide

| File | Description |
|------|-------------|
| `README.md` | This file |

## Key Terminology

<!-- Add domain-specific terms if the subfolder has specialized vocabulary -->

## Recommended Reading Order

1. This README
```

## Step 3: Update Indexes

If the repo has documentation-maintenance rules in `.cursor/rules/`, follow them. The update cascade is:

### For Top-Level Folders

1. **Read** the master index file (e.g., `*-INDEX.md` or `INDEX.md`) to understand the current structure
2. **Add** an entry under "Active Projects" in alphabetical position:

```markdown
#### [<folder_name>/](./<folder_name>/)
<Description>

**Key Documents:**
- `<folder_name>/README.md` - Project index
```

### For Subfolders

1. **Read** the parent project's `README.md`
2. **Update the folder tree** — add the new subfolder with an inline comment
3. **Update the document index table** — add a row linking to the subfolder's README with a description

## Step 4: Commit

```bash
cd <docs_repo_root>
git add <new_folder_path>/
git add <master_index_file>             # if top-level folder was created
git add <project>/README.md             # if subfolder was created
git commit -m "Add <folder_name> documentation folder"
```

## Step 5: Offer Next Steps

Tell the user:
1. Folder created at `<full_path>`
2. README scaffolded with template structure
3. Indexes updated
4. Suggest: "Want to add any initial documents to this folder?"

## Guidelines

1. Always use `lowercase_with_underscores` for folder names.
2. Every folder MUST have a `README.md` — this is non-negotiable per the repo conventions.
3. Read the parent README and index before updating them — don't blindly append; maintain alphabetical order and consistent formatting.
4. If the user provides initial documents to place in the folder, add them to the README's file guide and folder tree.
5. Don't create placeholder files beyond the README unless the user asks.
6. If the subfolder will contain 3+ files, the README should include all the standard subfolder sections (Purpose, Context, File Guide, Key Terminology, Recommended Reading Order).
