# Plan Phase

Decompose the enriched issue into a structured backlog of task files
using the `structured-backlog` skill. Ensure E2E validation hooks are
built first if they don't exist and they're feasible.

## Pre-conditions

- Enrich phase complete (decision tree resolved, ACs generated)
- Issue body contains enriched engineering considerations
- Access to `~/workspace/skills/structured-backlog/SKILL.md`

## Step 1: Set Up the Worktree

If you don't already have an isolated worktree for this issue, create
one now using `scaffold-workspace` (or your preferred worktree convention).

Default convention (`~/workspace/`): the main clone lives at
`~/workspace/$PROJECT`, and worktrees go in the sibling
`~/workspace/${PROJECT}_workspace/` directory, named `$PROJECT-$SLUG`:

```bash
PROJECT={short-project-name}          # e.g. claw-playbook
SLUG={kebab-case-issue-slug}

git -C ~/workspace/$PROJECT fetch origin main
git -C ~/workspace/$PROJECT worktree add \
  ~/workspace/${PROJECT}_workspace/$PROJECT-$SLUG \
  -b build-$SLUG origin/main          # ← branch off main EXPLICITLY
```

(`~/workspace/${PROJECT}_workspace/` already exists for active projects;
`worktree add` creates the leaf dir. The `_workspace` parent is a sibling
of the main clone, not nested inside it.)

> **Branch off `origin/main`, NOT the current branch — always be explicit.**
> Without the explicit base, `worktree add -b` branches from wherever HEAD
> happens to be. When the orchestrator runs several leaves of one parent in a
> row (e.g. a decomposed plan: foundation → reads → writes), the naive default
> stacks each leaf on the previous unmerged one. Stacked branches then
> **conflict on merge** — the second PR carries duplicate copies of the first
> PR's commits, and once PR #1 lands as a merge commit, PR #2 goes
> `CONFLICTING`. Each leaf must be an **independent branch off `main`** so the
> PRs merge in any order. (For genuine code dependencies between leaves, the
> dependency gate in `intake.md` sequences the *work*; the *branches* still
> start from `main`, and SHIP's pre-push rebase keeps them current — see
> `ship.md` Step 2.)

Record the worktree path for use in EXECUTE / VALIDATE / SHIP.

## Step 2: Check E2E Validation Hooks

Determine if E2E validation hooks exist for this project/feature.

Search for:
- Existing test scripts validating end-to-end behavior
- Playwright scripts, API harnesses, fixture replays
- Project-level QA skills in `~/workspace/skills/` or the project's
  `.claude/skills/` directory

### If hooks exist

Record them:

```markdown
**E2E validation:** {path to skill or script}
**How to run:** {command or skill invocation}
```

### If hooks don't exist and they're feasible

Add building them as **task-001** in the backlog. Validation hooks
should:

1. Exercise the feature's primary happy path.
2. Verify observable output (logs, API responses, DB state).
3. Be runnable from the command line without manual setup.
4. Follow existing project patterns if any test tooling exists.

### If hooks aren't feasible

Document the gap (e.g., "no automated E2E for this feature; manual
smoke test in PR description"). VALIDATE phase Layer 4 will be `n/a`.

## Step 3: Generate Implementation Plan

Produce a plan from:

- The enriched issue body (ACs, architecture decisions)
- The resolved decision tree from ENRICH
- The code context (module paths, patterns to follow / avoid)

The plan should:

- Start with a refactor phase if existing code needs restructuring.
- Include E2E validation hook creation as the first implementation task (if applicable).
- Follow the TDD red-green-refactor cycle (see `tdd-pocock`).
- Include observability in every phase, not as an afterthought.

Write the plan to:

```
{worktree_path}/backlog/PLAN.md
```

## Step 4: Decompose into Task Files

Read and follow `~/workspace/skills/structured-backlog/SKILL.md`.

Input: the implementation plan from Step 3.

The skill generates:

```
{worktree_path}/backlog/
├── PROMPT.md                    # System context for the executor
└── tasks/
    ├── 001-{name}.md            # E2E validation hooks (if needed)
    ├── 002-{name}.md            # First feature task
    ├── 003-{name}.md            # Second feature task
    └── ...
```

### Quality Checks

Before proceeding, verify the structured-backlog output:

1. **AC coverage** — Every acceptance criterion from the enriched issue
   maps to at least one task's ACs.
2. **Dependency order** — Tasks with dependencies are sequenced correctly.
3. **Parallel opportunities** — Independent tasks are identified
   (no dependency chain between them).
4. **Pattern references** — Every task's "Existing Code You Must Work
   With" section references the evaluated patterns from ENRICH.
5. **E2E hooks first** — If validation hooks need to be built, they're
   task-001 with no dependencies on feature tasks.

## Step 5: Identify Parallel Groups

Group tasks by dependency chains:

```markdown
### Execution Groups

**Group 1 (sequential):** 001 → 002 → 003
**Group 2 (parallel with Group 1):** 004, 005
**Group 3 (depends on Groups 1+2):** 006
```

Tasks within a group with no interdependencies can run in parallel
subagents. Tasks across groups with dependencies must run sequentially.

## Step 6: Comment Plan Summary on Issue

```bash
gh issue comment {NNN} --repo {owner/repo} --body "$(cat <<EOF
**Plan generated.** ${TASKS} tasks decomposed from ${ACS} acceptance criteria.

**Execution groups:**
- Group 1: ${G1_NAMES} (sequential)
- Group 2: ${G2_NAMES} (parallel)

**E2E validation:** ${E2E_STATUS}

Plan artifacts at \`${WORKTREE}/backlog/\`
EOF
)"
```

## Step 7: Record Plan Summary

Append to the execution log:

```markdown
## Plan

**Worktree:** {worktree_path}
**Tasks generated:** {count}
**AC coverage:** {issue_ac_count} ACs → {task_ac_count} task-level ACs
**Parallel groups:** {count}
**E2E hooks:** {existing / task-001 / n/a}

**Task list:**
| Task | Name | Dependencies | Parallel Group |
|------|------|-------------|----------------|
| 001 | {name} | none | 1 |
| 002 | {name} | 001 | 1 |
| 003 | {name} | none | 2 |
```

## Output

- Worktree exists with branch `build-{slug}` checked out
- Implementation plan at `{worktree_path}/backlog/PLAN.md`
- `PROMPT.md` and task files at `{worktree_path}/backlog/tasks/`
- Parallel execution groups identified
- Issue commented with plan summary
- Execution log updated
- Proceed to `execute.md`
