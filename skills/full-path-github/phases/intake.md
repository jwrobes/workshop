# Intake Phase

Read the GitHub issue, evaluate whether the orchestrator has enough
to proceed, and gather code context.

## Pre-conditions

- GitHub issue URL or `owner/repo#NNN` provided
- Project identifier provided
- `guardrails.md` read

## Step 1: Fetch the Issue

```bash
gh issue view {NNN} --repo {owner/repo} --json number,title,body,labels,assignees,author,url,comments
```

Check:

- [ ] Issue is accessible (not private/denied)
- [ ] Issue has a title
- [ ] Issue has some body (even one sentence)

If literally empty (blank issue with no title), stop and report.

Record the current labels and assignees for the execution log.

## Step 1.5: Dependency Gate (blocked-by check)

GitHub issues carry native **dependencies** (`blocked_by` / `blocking`) and
**sub-issues**. Never start an issue whose blockers are still open — the work
will hit a missing precondition and stall mid-run.

Query the blockers (the summary lives in the issue JSON; the list is a
separate endpoint):

```bash
# Quick count — is anything blocking this issue?
gh api repos/{owner/repo}/issues/{NNN} \
  --jq '.issue_dependencies_summary.blocked_by'

# The actual blockers, with their state:
gh api repos/{owner/repo}/issues/{NNN}/dependencies/blocked_by \
  --jq '.[] | "#\(.number) [\(.state)] \(.title)"'
```

> Note: these endpoints are eventually-consistent. A `summary` of `0` right
> after a write can be stale — trust the `dependencies/blocked_by` **list**
> over the `summary` count when they disagree.

### Decision

- **Any blocker still `open`** → do **not** proceed. Add `orchestrator-blocked`,
  comment which issues block this one, and stop:

  ```bash
  gh issue edit {NNN} --repo {owner/repo} --add-label orchestrator-blocked
  gh issue comment {NNN} --repo {owner/repo} --body \
    "**Blocked by open dependencies:** {#A, #B}. Will pick this up once they close."
  ```

  If this issue also has the `ready` label, remove it — a blocked issue is
  not ready, and leaving the label invites the loop to re-grab it:
  `gh issue edit {NNN} --repo {owner/repo} --remove-label ready`.

- **All blockers `closed` (or none)** → proceed to Step 2.

### For unattended / loop runs — pick a runnable issue, don't just gate one

When the orchestrator is selecting work from a queue (not handed a specific
`#NNN`), filter the `ready` set down to issues with **zero open blockers**
before choosing — gating after selection wastes a run. A dependency-aware
picker:

```bash
for n in $(gh issue list --repo {owner/repo} --label ready --state open \
             --json number --jq '.[].number'); do
  open_blockers=$(gh api repos/{owner/repo}/issues/$n/dependencies/blocked_by \
    --jq '[.[] | select(.state=="open")] | length')
  [ "$open_blockers" -eq 0 ] && echo "$n is runnable"
done
```

**Convention that keeps the queue honest:** mark only currently-unblocked
leaves `ready`; when a PR merges and closes a blocker, promote the issues it
unblocks to `ready` (this can be a follow-up automation). The `ready` label is
the *human-promoted* signal; the dependency gate is the *machine-enforced*
backstop. Both must agree before work starts.

## Step 2: Discover Project Skills

Scan for project-level skills the orchestrator can lean on. These provide
project-specific patterns the generic skills don't know about.

### Scan locations (in priority order)

1. **Worktree skills:** `{worktree_path}/.claude/skills/`
2. **Repo-root skills:** `{repo_root}/.claude/skills/`
3. **User skills:** `~/workspace/skills/` (already loaded in your session)

### Read each skill's frontmatter

For every `SKILL.md` found, read the `name` and `description` fields and
categorize:

| Category | Used In Phase |
|----------|---------------|
| **Setup** (env, secrets, dev login) | Before EXECUTE |
| **Patterns** (logging, error handling) | ENRICH |
| **E2E Testing** (Playwright, API harnesses) | VALIDATE |

Record discovered skills in the execution log. If none are found, note
it — the orchestrator can still proceed via codebase search.

## Step 3: Assign Yourself

Signal that the orchestrator is actively working on this issue:

```bash
gh issue edit {NNN} --repo {owner/repo} --add-assignee @me
```

## Step 4: Evaluate Code Context

Check the issue body for code pointers:

**Strong signals** (proceed immediately):
- File paths (`src/auth/middleware.ts`)
- Module names (`auth.middleware`)
- Class/function references (`requireSession`)
- "Follow the pattern in X" or "similar to X"

**Weak signals** (need codebase search):
- Domain terms without code references
- Feature names without module pointers
- Behavioral descriptions ("when a user logs in")

### If strong signals found

Read the referenced files to confirm they exist and are relevant. Record
them as code context for the ENRICH phase.

### If only weak signals found

Search the codebase:

1. Grep for domain keywords from the issue title and body.
2. Look for directory names that match the domain.
3. Check for existing modules in the domain.
4. Read any matching files to understand existing structure.

If the search finds relevant code, record it as context and proceed.

### If no signals found

The issue is too vague to locate in the codebase. Block:

```bash
gh issue edit {NNN} --repo {owner/repo} --add-label orchestrator-blocked

gh issue comment {NNN} --repo {owner/repo} --body "$(cat <<'EOF'
**Orchestrator needs code context to proceed.**

I couldn't find where this work belongs in the codebase. Please add a
comment with:
- Which module/directory this work lives in
- An example file that follows the pattern this should use
- Any config files or dependencies involved
EOF
)"
```

Stop. Wait for manual restart.

## Step 5: Vagueness Gate

Apply the three-question test from `guardrails.md`:

### 1. What — behavior change

Can you write one paragraph describing what changes for the user or
system? Source from the issue body, enriched by any codebase context.

### 2. Where — location in codebase

Do you have at least one directory or module? This should be resolved
by Step 4.

### 3. How to verify — acceptance criteria

Can you state at least one testable AC? This can come from:
- Explicit ACs in the issue body
- Derivable from the behavior change description
- Inferred from existing test patterns in the module

If the issue has no ACs and you can't derive any, this is a
medium-confidence gap — the ENRICH phase will generate ACs, so only
block if you can't even describe the behavior change.

If any of the three is "no", add `orchestrator-blocked` and comment
listing which questions can't be answered.

## Step 6: Record Intake Summary

Append to the execution log:

```markdown
## Intake

**Issue:** {repo}#{number} — {title}
**Initial labels:** {labels}
**Code context source:** {from issue / from codebase search / blocked}

**Vagueness gate:**
- What: {pass/fail — one sentence}
- Where: {pass/fail — module path}
- How to verify: {pass/fail — AC or derivable}

**Project skills discovered:**
- Setup: {list or "none"}
- Patterns: {list or "none"}
- E2E Testing: {list or "none"}

**Code pointers found:**
- {file_path} — {what it does}

**Patterns identified for evaluation:**
- {file_path} — candidate pattern (to be scored in ENRICH)
```

## Output

- Issue assigned to you
- Code context gathered (file paths, module structure, candidate patterns)
- Vagueness gate passed (or blocked with comment)
- Execution log updated
- Proceed to `enrich.md`
