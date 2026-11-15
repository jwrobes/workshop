# Task File Template

Copy and adapt this template for each task.

```markdown
---
id: <PREFIX>-<NNN>
title: "<PREFIX>-<NNN>: <Imperative verb> <what>"
status: Todo
dependencies:
  - <PREFIX>-<NNN>  # or empty list if none
priority: high|medium|low
ordinal: <NNN>000
branch: <branch-name>
worktree: <worktree-dir-name>
---

## Description

<2-4 sentences. What this task does, why it exists, and what the end state looks like.
Write in present tense imperative: "Create X that does Y" not "We need to create X".>

## Context

<Background the executor needs to understand the task. Why does this component exist in
the larger system? What came before it? What comes after it?>

### Existing Code You Must Work With

<List every file this task reads from, modifies, or depends on. Include a 1-line description
of what each file does and which methods/classes matter.>

- `path/to/file.rb` — `ClassName#method_name` does X. You will call/modify this.
- `path/to/config.yml` — Contains `section.key` configuration used by this component.

### Patterns to Follow

<Copy exact patterns from the codebase. Not "use structured logging" but the actual format:>

<Examples — replace with patterns from your own codebase:>

- Use `include Interactor` (not `Interactor::Organizer`)
- Log: `Logger.info("#{self.class.name}: Static message", key: value)`
- Metrics: `Statsd.increment("prefix.metric", tags: ["key:value"])`
- On non-critical failure: log warning, do NOT `context.fail!`

## Acceptance Criteria

<Numbered checkboxes. Each one is independently verifiable and maps to at least one test.>

- [ ] #1 <File exists at correct path>
- [ ] #2 <Behavior on success: sets X, calls Y, returns Z>
- [ ] #3 <Behavior on failure: falls back, logs, does not halt pipeline>
- [ ] #4 <Observability: logs with correct format, increments correct metric>
- [ ] #5 <Integration: wired into organizer/caller at correct position>
- [ ] #6 <Tests: spec covers success, failure, edge cases>

## TDD Workflow

<Numbered steps. Each step is explicitly Red, Green, or Refactor.
The executor follows these sequentially — no skipping.>

1. **Red:** Write spec for `<Component>` — stub `<Dependency>`, assert `<behavior>`
2. **Green:** Implement `<Component>` to make spec pass
3. **Refactor:** <Specific refactoring target, or "Clean up if needed">
4. **Red:** Update `<ExistingSpec>` to expect `<new behavior>`
5. **Green:** Update `<ExistingCode>` to support new behavior
6. **Red:** Update `<IntegrationSpec>` to include new component
7. **Green:** Update `<Orchestrator>` to wire in new component
8. Run full suite: `<exact test command>`

## Run Tests

<Exact command with env vars, working directory, and scope.>

```bash
cd <worktree-path>
<ENV_VAR>=<value> <test-command> <scope> --format documentation
```
```

## Guidelines for Writing Each Section

### Description
- 2-4 sentences max
- First sentence: what the component does
- Second sentence: why it exists / what problem it solves
- Third sentence (optional): key constraint or design decision

### Context
- Explain the "why" not the "what"
- Reference the larger pipeline/system
- Mention what runs before and after this task
- Include any design decisions that constrain implementation

### Existing Code You Must Work With
- Read the actual files before writing this section
- Include the module/class path, not just the file path
- Note which methods the task will call vs. modify
- If a config file is involved, specify the exact keys

### Acceptance Criteria
- Start with file existence (cheapest verification)
- Then behavior on happy path
- Then behavior on error/edge cases
- Then observability (logging, metrics)
- Then integration (wired into the system correctly)
- End with test coverage requirements

### TDD Workflow
- One Red-Green pair per acceptance criterion (roughly)
- Integration wiring is always the last Red-Green pair
- Full suite run is always the final step
- If the task modifies existing code, include Red-Green pairs for updating existing specs

## Anti-Patterns

| Anti-Pattern | Why It Fails | Fix |
|---|---|---|
| "Implement FetchPrompt correctly" | No verifiable criteria | List specific behaviors as ACs |
| Skipping "Existing Code" section | Executor invents wrong abstractions | Read the codebase, list every dependency |
| "Write tests" as a single AC | Executor writes 1 test and moves on | List specific scenarios to test |
| TDD steps without Red/Green labels | Executor writes all code then all tests | Label each step explicitly |
| Two components in one task | Executor cuts corners on the second | Split into separate tasks |
| Generic patterns ("use good logging") | Executor uses its own conventions | Copy exact format from codebase |
