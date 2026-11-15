# Improve Codebase Architecture — Reference

This reference supports `SKILL.md` for architecture-deepening reviews.

## Dependency Categories

Use one primary category per candidate (you can note a secondary category if needed).

1. **Shared runtime state dependency**
   - Multiple modules rely on mutable shared state (globals/singletons/caches), so behavior depends on call order and hidden side effects.
   - Typical signal: hard-to-reproduce bugs, tests that require global setup/teardown.

2. **Cross-process orchestration dependency**
   - Domain logic is split across process boundaries (CLI calls, subprocesses, remote jobs), with fragile handoffs in args/files/env.
   - Typical signal: difficult integration testing; command-building logic duplicated or embedded in many callers.

3. **Parallel domain-logic duplication dependency**
   - The same concept is reimplemented in multiple modules (parsers, transforms, filtering rules), causing drift.
   - Typical signal: one path fixes a bug while another still fails.

4. **Temporal/workflow coupling dependency**
   - Correctness depends on a strict sequence of steps, with state encoded implicitly in files/metadata rather than explicit contracts.
   - Typical signal: retries, partial runs, and resumability are brittle or unclear.

## Refactor RFC Template

Use this structure when writing a local refactor RFC:

```markdown
## Problem
<What architectural friction are we seeing? Why now?>

## Context
- Cluster: <modules/files/concepts>
- Dependency category: <one of the four categories above>
- Current coupling: <how modules are coupled today>
- User impact: <how this slows delivery, causes bugs, or blocks testing>

## Goals
- <goal 1>
- <goal 2>
- <goal 3>

## Non-goals
- <what this refactor will explicitly not do>

## Proposed Deep Module Boundary
- Interface shape (high-level): <small public surface>
- Hidden complexity: <what moves behind the boundary>
- Dependency strategy: <injection/adapters/session/etc.>

## Migration Plan
1. <step>
2. <step>
3. <step>

## Testing Strategy
- Boundary tests to add: <integration/contract tests at new module seam>
- Existing tests to retire/replace: <unit tests for internal wiring>
- Risk checks: <regression areas>

## Risks & Mitigations
- Risk: <...>
  - Mitigation: <...>

## Acceptance Criteria
- [ ] New boundary is used by all intended callers
- [ ] Duplicate logic removed from old paths
- [ ] Workflow still supports existing runbook/CLI usage
- [ ] Tests validate behavior at module boundary
```

## Output Path Resolution

Check for existing directories in order: `docs/rfcs/`, `docs/thoughts/rfcs/`, `.cursor/thoughts/rfcs/`. Use the first that exists. If none exist, ask the user where to save the RFC.
