# Execute Phase

Drive each task through a strict red-green-refactor TDD loop. The TDD
behavior is delegated to the [`tdd-pocock`](../../tdd-pocock/) skill.
This phase wraps that loop with task management and parallel-group
dispatch.

## Pre-conditions

- Plan phase complete (`PROMPT.md` + task files exist in the worktree)
- Parallel execution groups identified
- Worktree exists and is on the correct branch
- Access to `~/workspace/skills/tdd-pocock/SKILL.md`

## Step 1: Choose Execution Strategy

Based on task count and complexity:

| Condition | Strategy |
|-----------|----------|
| ≤ 3 tasks, all sequential, simple scope | Inline execution (you run the loop) |
| > 3 tasks OR parallel groups exist | Subagent(s) in isolated worktree(s) |
| Mode is `build-first` with parallel plans | Two subagents, one per plan |

## Step 2: Read the TDD Loop

Read `~/workspace/skills/tdd-pocock/SKILL.md` once and keep its rules in
mind for every task:

- Vertical slices via tracer bullets (one test → one impl → repeat).
- **Never** write all tests first then all implementation.
- Tests verify behavior through public interfaces, not implementation
  details.
- After GREEN, look for refactor candidates; never refactor while RED.
- Companion docs at `tests.md`, `mocking.md`, `deep-modules.md`,
  `interface-design.md`, `refactoring.md` cover the per-cycle decisions.

## Step 3: Per-Task Workflow

For each task file in dependency order:

```
1. Read the task file (frontmatter + body).
2. Read the referenced "Existing Code You Must Work With" files.
3. Confirm the public interface and the first behavior to test.
4. Apply the tdd-pocock loop:
   RED:   Write ONE failing test for the first behavior.
   GREEN: Minimal code to pass.
   RED:   Next behavior.
   GREEN: Minimal code.
   ...
   REFACTOR (after all GREEN): deepen modules, extract duplication.
5. Run the full test suite for this slice — must be green.
6. Commit (one logical commit per slice; multi-commit ok per task).
7. Mark `status: done` in the task file frontmatter.
```

Stop and re-orient any time:
- A test you wrote fails for the wrong reason (you mis-modeled the API).
- The implementation reveals an abstraction the plan didn't capture.
- You're tempted to write a second test before the current one is GREEN.

## Step 4: Dispatch

### Inline Execution

Run the loop yourself, one task at a time. Stay strict on red-green-refactor.

### Subagent Execution

For each execution group, compose the subagent prompt:

```
You are executing tasks from a structured backlog.

System prompt: read {worktree_path}/backlog/PROMPT.md
TDD method:    read ~/workspace/skills/tdd-pocock/SKILL.md and follow it
               STRICTLY (vertical slices, no horizontal slicing).

Tasks (in order):
{list task file paths for this group}

For each task:
1. Read the task file.
2. Run the red-green-refactor loop per the tdd-pocock rules.
3. After all behaviors are tested and passing, run the full test suite.
4. Commit work in revert-friendly slices.
5. Mark `status: done` in the task frontmatter.

If any task is unclear or blocked, write a BLOCKED section in the task
file explaining what's needed and stop.

After all tasks complete, run the full test suite once more and report.
```

Sequential groups: wait for the previous group's subagent to finish.
Parallel groups: launch all parallel subagents simultaneously.

### Parallel Plans (build-first mode)

When two plans exist from a low-confidence ENRICH split:

1. Set up a second worktree for Plan B (`scaffold-workspace` or manual).
2. Launch two subagents, one per worktree.
3. Both run to completion. VALIDATE picks the winner.

## Step 5: Monitor Completion

For each subagent:

1. Wait for completion.
2. Read the subagent's output.
3. Check for `BLOCKED` markers in any task file.

### If a task reports BLOCKED

Read the blocked task file. Determine if the block is:

- **Resolvable from context** (info exists elsewhere in the codebase) → provide the info and retry.
- **Needs human input** → comment on the issue with details, add `orchestrator-blocked`, stop.

### If tests fail

The subagent should have attempted to fix failures. If persistent:

1. Read the failure output.
2. Attempt a fix (one retry).
3. If still failing after retry → stop and report (per guardrails).

## Step 6: Collect Results

After all groups complete:

1. Verify all task files have `status: done` in frontmatter.
2. Run the full test suite in the worktree.
3. Count new tests added vs. existing.
4. Verify no existing tests were broken.

```bash
cd {worktree_path}
{test_command}
```

Record:

```markdown
**Test results:**
- Total: {count}
- New: {count}
- Passing: {count}
- Failing: {count}
- Pending: {count}
```

## Step 7: Record Execute Summary

```markdown
## Execute

**Strategy:** {inline / subagent / parallel plans}
**Tasks completed:** {count}/{total}
**Execution groups:** {count} ({parallel_count} parallel)

**Subagents launched:** {count}
- Group 1: {task range} — {status}
- Group 2: {task range} — {status}

**Test results:**
- Total: {count} ({new_count} new)
- Passing: {count}
- Failing: {count}

**Blocks encountered:** {count}
- {description} — {resolution}

**Commits:** {count}
```

## Output

- All task files executed with passing tests
- Code committed in the worktree (revert-friendly slices)
- Execution log updated
- Proceed to `validate.md`
