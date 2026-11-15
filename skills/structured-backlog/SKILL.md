---
name: structured-backlog
description: >-
  Decompose an implementation plan into structured backlog task files with
  acceptance criteria and TDD workflows for high-quality AI handoff. Use when
  the user says "create backlog", "break into tasks", "structured handoff",
  "task files", or wants to hand off implementation to a subagent or
  implementing-plans with maximum quality.
---

# Structured Backlog

Decompose an implementation plan into task files that maximize AI implementation quality.

## Why This Exists

Tested head-to-head: handing a subagent a plan dump vs. structured task files with acceptance
criteria. The structured approach produced 69% more tests, hit every acceptance criterion,
used thread-safe patterns, and followed the correct two-step API lifecycle. The plan dump
approach missed observability fields, skipped thread safety, and had no way to measure
coverage against intent.

The extra work is ~10 minutes of decomposition. The payoff is significant.

## When to Use

| Signal | Action |
|--------|--------|
| User has an implementation plan and wants to hand off to a subagent | Use this skill |
| User says "create backlog", "break into tasks", "task files" | Use this skill |
| User wants to run parallel `best-of-n-runner` attempts | Use this skill to create the task input |
| User wants to use `implementing-plans` skill with maximum quality | Use this skill first |

## Inputs

1. **Implementation plan** — a markdown file with phases/slices/commits describing what to build
2. **Codebase context** — existing code the tasks will modify (read from repo)
3. **Conventions** — project patterns for logging, testing, metrics, error handling

## Outputs

```
<project>/backlog/
├── PROMPT.md                    # System context for the executor
└── tasks/
    ├── <prefix>-001-<name>.md   # First task
    ├── <prefix>-002-<name>.md   # Second task (may depend on 001)
    └── ...
```

## Step 1: Read the Plan

Read the implementation plan file. Identify:

- Which items are DONE vs TODO
- Dependencies between TODO items
- The existing code each item touches
- The project's conventions (logging, testing, metrics, error handling)

## Step 2: Read Existing Code

For each TODO item, read the files it will modify or depend on. You need this to write
accurate "Context" and "Existing Code You Must Work With" sections in the task files.

Also read 2-3 existing specs to extract the project's testing style.

## Step 3: Generate PROMPT.md

The system prompt gives the executor (subagent or implementing-plans) everything it needs
to follow project conventions without asking questions.

Use this template:

```markdown
PROMPT.md — <Project Name>

SYSTEM

You are a senior <language> engineer working inside an existing <framework> application
named <app>.

You are implementing <brief scope>. <1-2 sentences of context about what exists and
what you're adding.>

This work uses red-green-refactor TDD. Every new behavior starts with a failing test.

The result must be:
- correct
- tested
- following existing codebase patterns exactly
- not breaking any existing tests

CODEBASE CONVENTIONS

<Extract from the repo. Include ONLY conventions the executor needs. Examples:>

Testing:
- <framework-specific patterns, e.g. "Use describe (not RSpec.describe)">
- <doubles pattern, e.g. "Use instance_double (not double)">
- <assertion style>

Logging:
- <exact format with example>

Metrics:
- <exact format with example>

<Pattern>:
- <exact format with example>

ARCHITECTURE

<Brief description of how the components fit together. Use ASCII diagram if helpful.>

TASK EXECUTION

1. Read the task file in `backlog/tasks/`
2. Follow the TDD workflow exactly as specified
3. Write the failing test FIRST, then implement to make it pass, then refactor
4. After each task, run the full spec suite to confirm no regressions
5. Do not modify files outside the task's scope unless the task explicitly says to

RUN TESTS

<exact command>

All tests must pass after each task.

STOP CONDITIONS

If anything is unclear, stop and output:

BLOCKED:
- issue:
- repository evidence:
- why it matters:
- minimal resolution:

DEFINITION OF DONE

Done means:
<checklist derived from the plan's overall goals>
```

### PROMPT.md Quality Rules

- Extract conventions from the actual codebase, not generic best practices
- Include the exact test command with any env vars needed
- The ARCHITECTURE section should show the component graph, not explain what each does
- Keep under 100 lines — this is a system prompt, not documentation

## Step 4: Generate Task Files

Each task file follows this structure. See [references/TASK_TEMPLATE.md](references/TASK_TEMPLATE.md)
for the full template.

### Task File Quality Rules

These are the rules that made the structured approach win:

1. **Acceptance criteria are checkboxes, not prose.** Each AC is independently verifiable.
   The executor checks them off. Missing ACs = missing implementation.

2. **"Existing Code You Must Work With" is mandatory.** List every file the task reads or
   modifies, with a 1-line description of what it does. This prevents the executor from
   inventing its own abstractions.

3. **"Patterns to Follow" is mandatory.** Include the exact logging format, the exact metric
   naming convention, the exact error handling pattern. Copy from the codebase, don't
   describe abstractly.

4. **TDD Workflow is numbered steps.** Each step is Red, Green, or Refactor. The executor
   follows them sequentially. This prevents "write all tests then implement" shortcuts.

5. **One concern per task.** If a task has two interactors, split it into two tasks. The
   executor should never be juggling multiple new files simultaneously.

6. **Dependencies are explicit.** If task 002 requires task 001's output on the context
   object, say so in the Description.

### Naming Convention

```
<prefix>-<NNN>-<kebab-name>.md
```

- Prefix: 2-4 letter project abbreviation (e.g., `ls` for LangSmith, `mr` for message routing)
- NNN: zero-padded sequence number
- Name: kebab-case description of the task

### Acceptance Criteria Guidelines

Write ACs that are **specific and testable**, not vague:

```markdown
# Bad — vague
- [ ] #1 FetchPrompt works correctly

# Good — specific and testable
- [ ] #1 FetchPrompt interactor exists at `app/service_objects/.../fetch_prompt.rb`
- [ ] #2 On success, sets `context.prompt_template` and `context.system_message`
- [ ] #3 On failure, falls back to YAML config and logs a warning
- [ ] #4 Sets `context.prompt_source` to "langsmith" or "fallback"
```

Each AC should map to at least one test.

## Step 5: Verify

Before presenting to the user:

1. Count ACs across all tasks — does every requirement from the plan have a corresponding AC?
2. Check dependencies — is the task order correct? Can any tasks run in parallel?
3. Check "Existing Code" sections — did you reference every file the task touches?
4. Check TDD steps — does every AC have a corresponding Red step?

## Handoff Options

After generating the backlog, present the user with options:

| Option | When |
|--------|------|
| Hand to `implementing-plans` | User wants to supervise, review at stop points |
| Hand to `best-of-n-runner` subagent | User wants autonomous execution in isolated worktree |
| Hand to parallel subagents | User wants to compare approaches (A/B test) |
| Execute yourself | Tasks are small enough to do inline |

For subagent handoff, the prompt should be:

```
Read PROMPT.md at <path>, then execute tasks in order from <path>/tasks/.
Follow the TDD workflow in each task. Run tests after each red/green/refactor cycle.
```

## Predecessor Skills

| Skill | Relationship |
|-------|-------------|
| `writing-plans` | Creates the implementation plan this skill decomposes |
| `grill-me` | Resolves design ambiguity before decomposition |
| `structuring-outlines` | Provides the phase structure the plan is built from |

## Successor Skills

| Skill | Relationship |
|-------|-------------|
| `implementing-plans` | Executes the generated tasks with stop points |
| `creating-merge-requests` | Creates MR after tasks are complete |
