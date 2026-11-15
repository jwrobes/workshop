# Retrospect Phase

Analyze the orchestrator's own session to identify two types of
improvements: codebase refactors and skill gaps. Then create the
artifacts — not just suggestions, but actual skills and implementable
refactor plans.

This phase runs AFTER ship. It does not block the PR.

## Pre-conditions

- Ship phase complete (PR created, execution log available)
- Full execution log from all phases (decisions, blocks, friction)
- Optional: access to `~/workspace/skills/improve-codebase-architecture/SKILL.md`

## Step 1: Analyze Session Friction

Review the execution log from all phases. For each phase, identify
friction points — places where the orchestrator:

- **Spent time searching** for something that should have been obvious
- **Got blocked** and needed human input
- **Made a medium-confidence decision** where a clear convention would have made it high-confidence
- **Had to discover a pattern** by reading multiple files instead of having it documented
- **Built something from scratch** that could have been templated
- **Needed project-specific knowledge** that wasn't in any skill

Categorize each friction point:

| Category | Signal | Example |
|----------|--------|---------|
| **Skill gap** | "I had to figure out how X works by reading 5 files" | How this project wires up auth |
| **Missing template** | "I built boilerplate following an existing pattern" | Adding a feature flag, scaffolding a worker |
| **Codebase friction** | "The structure made it hard to understand/modify" | God module, tangled deps, shallow abstractions |
| **Convention gap** | "I had to guess the convention" | Logging format, metric naming, error style |
| **Tooling gap** | "I needed a CLI tool that doesn't exist" | Running E2E tests, toggling feature flags |

## Step 2: Identify Skill Gaps

For each friction point categorized as **skill gap**, **missing template**,
or **convention gap**, evaluate whether a project-level skill would
eliminate the friction for future runs.

### Evaluation criteria

A skill is worth creating if:

1. **Reusable** — this pattern will come up again (not a one-off).
2. **Non-obvious** — an agent wouldn't figure it out quickly from the codebase alone.
3. **Specific** — it captures project-specific knowledge, not generic programming advice.

### For each identified skill gap

Write a complete `SKILL.md` following the conventions in your other skills:

- Clear `name` and `description` in frontmatter
- "When to Use" triggers
- Exact steps with code examples from the codebase
- References to specific files and patterns
- Independently usable (not dependent on the orchestrator)

```markdown
### Skill: {name}

**Friction point:** {what happened during the session}
**Reusability:** {why this will come up again}
**Location:** `.claude/skills/{name}/SKILL.md` (project-level)

{Full SKILL.md content}
```

### Where to place new skills

- **Project-specific** ("how to add a feature flag in this app") → `{repo_root}/.claude/skills/{name}/SKILL.md` (commit it).
- **Cross-project** ("how to structure a webhook handler") → `~/workspace/skills/{name}/SKILL.md` and consider publishing to your public skills repo.

## Step 3: Identify Codebase Refactors

For each friction point categorized as **codebase friction**, analyze:

1. **What's the friction?** — Which modules were hard to understand or modify?
2. **Why is it coupled?** — Shared types, call patterns, co-ownership?
3. **What would help?** — Deeper modules, cleaner boundaries, extracted interfaces?
4. **Test impact** — What tests would improve if this were refactored?

### For each refactor opportunity

Write an implementable plan that can be turned into a GitHub issue:

```markdown
### Refactor: {short description}

**Friction encountered:** {what happened during the session}
**Files involved:** {list}
**Impact:** {what would be easier after this refactor}

#### Problem

{2–3 paragraphs describing the friction, citing specific files and coupling patterns}

#### Proposed Change

{Concrete description:
- What moves where
- What interfaces change
- What gets extracted or consolidated}

#### Implementation Plan

1. {step — with specific file paths}
2. {step}
3. {step}

#### Test Plan

- {what tests to add/modify}
- {how to verify the refactor doesn't break anything}

#### Estimated Scope

- Files modified: {count}
- New files: {count}
- Risk: {low/medium/high}
```

## Step 4: Write Retrospect Artifacts

### 4a: Create new skills

For each identified skill, write the `SKILL.md` to the appropriate location:

```bash
mkdir -p {repo_root}/.claude/skills/{name}
# Write SKILL.md
```

Commit project-scoped skills along with the work, in a follow-up commit
or a separate small PR.

### 4b: Write refactor plans

Write all refactor plans to a single document at the repo root or in a
notes folder you keep:

```
{repo_root}/RETROSPECT_REFACTORS.md
```

Each section is a complete issue description, ready to copy-paste into
`gh issue create --body-file`.

### 4c: Optionally create the GitHub issues now

```bash
gh issue create \
  --repo {owner/repo} \
  --title "Refactor: {short description}" \
  --body-file {section_file}
```

### 4d: Update the execution log

```markdown
## Retrospect

**Session friction points:** {count}
- Skill gaps: {count}
- Missing templates: {count}
- Codebase friction: {count}
- Convention gaps: {count}
- Tooling gaps: {count}

**Skills created:** {count}
| Skill | Location | Friction Resolved |
|-------|----------|-------------------|
| {name} | {path} | {one-line description} |

**Refactors identified:** {count}
| Refactor | Files | Scope | Risk |
|----------|-------|-------|------|
| {name} | {count} | {weight} | {risk} |

**Refactor plans at:** {repo_root}/RETROSPECT_REFACTORS.md
```

## Step 5: Comment on Issue

```bash
gh issue comment {NNN} --repo {owner/repo} --body "$(cat <<EOF
**Retrospect: improvements for future runs**

**Skills created:** ${SKILL_COUNT}
${SKILL_LIST}

**Refactors identified:** ${REFACTOR_COUNT}
${REFACTOR_LIST}

Refactor plans ready for ticketing at \`${REPO_ROOT}/RETROSPECT_REFACTORS.md\`
EOF
)"
```

## Step 6: Report to User

```text
Retrospect complete.

  Skills created:    {count}
  {list with paths}

  Refactors identified: {count}
  {list with scope estimates}

  Refactor plans at: {repo_root}/RETROSPECT_REFACTORS.md
  (Ready to create GitHub issues from these)

  The next orchestrator run on this project will benefit from
  {count} new skills that eliminate friction encountered this run.
```

## Output

- New project-level skills installed (and committed if appropriate)
- Refactor plans written (ready for ticketing)
- Optionally: GitHub issues created for each refactor
- Execution log updated
- Issue commented with retrospect summary
- User informed of improvements
