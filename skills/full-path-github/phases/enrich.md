# Enrich Phase

Self-interrogate the issue using the `grill-me` framework. Evaluate
confidence on each decision. Enrich the issue body with structured
content. Evaluate candidate patterns for quality.

## Pre-conditions

- Intake phase complete (code context gathered, vagueness gate passed)
- `guardrails.md` read (confidence tiers, pattern evaluation rules)
- Access to `~/workspace/skills/grill-me/SKILL.md` for the interrogation framework
- Access to `~/workspace/skills/code-review/SKILL.md` for the review rubric

## Step 1: Evaluate Candidate Patterns

For each candidate pattern file from intake:

1. Read the file.
2. Score against `code-review` phases:
   - Phase 1: Architecture / organization (0–3)
   - Phase 3: Naming / domain alignment (0–3)
   - Phase 4: Error handling / defensive coding (0–3)
   - Phase 5: Testing completeness (0–3) — read the matching test file
3. Apply guardrails scoring rules:
   - All ≥ 2 → follow the pattern
   - Any = 1 → follow with improvements
   - Any = 0 → reject, find a better pattern

Record the evaluation:

```markdown
### Pattern Evaluation

**{file_path}** — {what it does}
- Architecture: {score}/3 — {one-line rationale}
- Naming: {score}/3 — {one-line rationale}
- Error handling: {score}/3 — {one-line rationale}
- Testing: {score}/3 — {one-line rationale}
- **Verdict:** {follow / follow with improvements / reject}
- **Improvements needed:** {list if any}
```

If all candidates are rejected, note "greenfield — no strong precedent"
and use the `code-review` checklists to define the pattern.

## Step 2: Build the Decision Tree

Using the `grill-me` framework, identify the top-level decisions this
issue requires. Common branches:

- **Architecture**: How should this be structured? (entry point, layering)
- **Data model**: New tables/columns/config files?
- **Integration points**: External services, APIs, queues?
- **Feature gating**: Feature flags, rollout strategy?
- **Observability**: Logging, metrics, tracing approach?
- **Error handling**: Failure modes and degradation strategy?
- **Testing strategy**: Unit, integration, E2E?

Write the decision tree:

```markdown
## Decision Tree

1. [ ] Architecture choice
   1.1 [ ] Entry point
   1.2 [ ] Internal structure
2. [ ] Data model
   2.1 [ ] New models / tables / config?
3. [ ] Integration points
   ...
```

## Step 3: Self-Interrogate (Depth-First)

For each open node in the tree, follow the `grill-me` loop but answer
your own questions:

1. **State context** — What do you know from the issue + codebase?
2. **Identify the question** — What exactly needs deciding?
3. **Search for evidence** — Look in the codebase for precedent.
4. **Evaluate the evidence** — Does it pass the pattern quality check?
5. **Assess confidence** — Which tier? (high / medium / low)
6. **Act on confidence:**

### High confidence

Make the decision. Document it:

```markdown
1. [x] Architecture → middleware chain (HIGH confidence)
   **Evidence:** `src/auth/middleware.ts` uses this exact pattern for
   composable request guards. Scores 3/3/2/3 on review.
   **Rationale:** Same shape (sequential checks, single entry function).
```

### Medium confidence

Make the decision but flag it:

```markdown
1. [x] Cache strategy → in-memory with TTL (MEDIUM confidence)
   **Evidence:** No existing cache in this module. Project does have
   Redis but it's used elsewhere for sessions, not config-like values.
   **Rationale:** In-memory + TTL is simpler for low-mutation data.
   **Flag:** Override in a comment if Redis-backed caching is preferred.
```

### Low confidence

Check the orchestrator's mode:

**plan-first mode (default):**
- Write both options as parallel plan sketches (2–3 paragraphs each).
- Comment on the issue with both options and your lean.
- Add `orchestrator-blocked` label and stop.

**build-first mode:**
- Write both options as full plans.
- Proceed to PLAN with both — execution will run in parallel worktrees.
- Winner picked in VALIDATE by comparing test coverage and review scores.

**auto mode:**
- Architectural decision (file structure, module boundaries, data model) → use plan-first.
- Implementation-level decision (algorithm, caching, error path) → use build-first.

## Step 4: Generate Acceptance Criteria

From the resolved decision tree + issue body, generate concrete ACs:

```markdown
## Acceptance Criteria

- [ ] #1 {specific, testable criterion}
- [ ] #2 {specific, testable criterion}
- [ ] #3 {specific, testable criterion}
```

Each AC must be:
- Independently verifiable (not "it works correctly")
- Mapped to at least one test
- Written as a checkbox

## Step 5: Overwrite Issue Body

Compose the enriched body and write it via the `gh` CLI. Build the
content as a temp file first, then update:

```bash
cat > /tmp/issue-body.md <<'EOF'
## Summary

{One paragraph: what this does and why}

## Acceptance Criteria

- [ ] #1 {criterion}
- [ ] #2 {criterion}

## Engineering Considerations

### Architecture
{Resolved decisions with rationale}

### Code Context
- **Module:** {path}
- **Pattern:** {file_path} ({follow / follow with improvements})
- **Config:** {paths}
- **Test pattern:** {paths}

### Feature Flags
{If applicable}

### Observability
{Logging, metrics, tracing approach}

### Open Questions
{Any medium-confidence flags or deferred decisions}

## Orchestrator Decisions

| Decision | Choice | Confidence | Evidence |
|----------|--------|------------|----------|
| {decision} | {choice} | {high/medium} | {file path or rationale} |
EOF

gh issue edit {NNN} --repo {owner/repo} --body-file /tmp/issue-body.md
```

## Step 6: Record Enrich Summary

Append to the execution log:

```markdown
## Enrich

**Patterns evaluated:** {count}
- {path}: {verdict} ({scores})

**Decision tree:** {count} decisions resolved
- High confidence: {count}
- Medium confidence: {count} (flagged for override)
- Low confidence: {count} (blocked / split)

**Acceptance criteria generated:** {count}

**Issue body overwritten:** yes
```

## Output

- Issue body enriched with structured content
- Candidate patterns evaluated and scored
- Decision tree resolved (or blocked on low-confidence items)
- Acceptance criteria generated
- Execution log updated
- Proceed to `plan.md`
