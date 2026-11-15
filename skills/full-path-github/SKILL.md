---
name: full-path-github
description: >-
  Confidence-gated orchestrator that takes a raw GitHub issue and delivers a
  reviewed, tested pull request on a personal GitHub project. Chains intake,
  enrichment, planning, execution, validation, and shipping with a three-tier
  confidence model. Use when the user says "full path", "orchestrate", "run
  the full pipeline", "take this issue end to end", or provides a GitHub
  issue URL for autonomous implementation.
---

# Full Path Orchestrator (GitHub)

Confidence-gated pipeline. Takes a GitHub issue (raw or groomed) and
delivers a reviewed, tested pull request. Stops only when it genuinely
can't proceed — otherwise makes decisions, documents them, and moves on.

This is a personal-projects orchestrator: assumes one repo owner (you),
no SLA, the `gh` CLI for all GitHub interaction, and the `~/workspace/`
worktree convention — worktrees live in a sibling `~/workspace/{project}_workspace/`
directory, named `{project}-{slug}`, on a `build-{slug}` branch (see Input
and EXECUTE).

## Intent Detection

| Keywords | Action |
|----------|--------|
| "full path", "orchestrate", "end to end", "take this issue" | Use this skill |
| "run the pipeline on #NNN", "implement this issue" | Use this skill |
| "resume the orchestrator on #NNN" | Resume from last phase |

## Input

| Required | Description |
|----------|-------------|
| Issue reference | GitHub issue URL, number, or `owner/repo#NNN` format |
| Project | The repo to implement in (e.g., `jwrobes/some-project`) |

| Optional | Default |
|----------|---------|
| Mode | `auto` (other options: `plan-first`, `build-first`) |
| Branch name | `build-{issue-slug}` |
| Worktree path | `~/workspace/{project}_workspace/{project}-{slug}/` |

## Prerequisites

### Skills (at `~/workspace/skills/` or installed via `install.sh`)

| Skill | Phase | Required |
|-------|-------|----------|
| `grill-me` | Enrich | Yes |
| `structured-backlog` | Plan | Yes |
| `tdd-pocock` | Execute | Yes — the inner TDD loop |
| `code-review` | Enrich + Validate | Yes |
| `scaffold-workspace` | Pre-execute | Optional but recommended |
| `gh-pr-create` | Ship | Yes |
| `comprehension-artifact` | Ship | Optional, strongly encouraged (non-trivial work) |

### Tools

| Tool | Purpose |
|------|---------|
| `gh` (GitHub CLI) | Issue + PR + label operations |
| `git` (with worktree support) | Isolated execution environment |

Verify before starting:

```bash
gh auth status
ls ~/workspace/skills/{grill-me,structured-backlog,tdd-pocock,code-review,gh-pr-create}/SKILL.md
```

## Sub-Skills

This orchestrator is a thin conductor. All phase logic lives in
composable sub-skills under `phases/`. Read them in order as each phase
begins:

```
full-path-github/
├── SKILL.md          # This file
└── phases/
    ├── guardrails.md  # READ FIRST — hard rules, confidence thresholds
    ├── intake.md      # Phase 1 — read issue, find code context
    ├── enrich.md      # Phase 2 — grill-me self-interrogation, pattern eval
    ├── plan.md        # Phase 3 — structured-backlog decomposition
    ├── execute.md     # Phase 4 — TDD loop via tdd-pocock
    ├── validate.md    # Phase 5 — tests + ACs + review rubric
    ├── ship.md        # Phase 6 — PR creation, execution log
    └── retrospect.md  # Phase 7 — friction analysis, skill creation
```

## GitHub State Model (no `state::` labels)

Personal projects don't need a six-state Kanban. The orchestrator uses
**three signals** that are native to GitHub:

| Signal | Meaning | How to set |
|--------|---------|------------|
| Issue is **open** with assignee = me | Work in progress | `gh issue edit --add-assignee @me` |
| **Draft PR** linked to the issue | Implementation done, validating | `gh pr create --draft` |
| **PR marked ready for review** | All gates passed; awaiting human merge | `gh pr ready` |

Add a single optional label `orchestrator-blocked` only when the orchestrator
needs human input mid-flight. The presence of that label is the only
"blocked-on-human" signal — its absence means work continues.

### Native dependencies & sub-issues (work-ordering signals)

GitHub provides two native relationships the orchestrator respects (GA 2025):

| Relationship | Meaning | API |
|--------------|---------|-----|
| **Sub-issue** | Parent tracker → child leaves | `POST issues/{n}/sub_issues` (`-F sub_issue_id=<int>`) |
| **Dependency** | This issue is `blocked_by` / `blocking` another | `POST issues/{n}/dependencies/blocked_by` (`-F issue_id=<int>`) |

These differ from `orchestrator-blocked` (which is "blocked on a human").
`blocked_by` is "blocked on **other work**" — INTAKE's dependency gate refuses
to start an issue with open blockers (see `intake.md` Step 1.5), and SHIP
reports which downstream issues a merge will unblock (`ship.md` Step 6.5).

> Gotcha: both POST bodies take an **integer** id (`-F`, not `-f`). The string
> form silently no-ops. Reads are eventually-consistent — trust the
> `dependencies/blocked_by` list over the `summary` count when they disagree.

Create the label once in the repo:

```bash
gh label create orchestrator-blocked --description "Full-path orchestrator blocked on human input" --color B60205 --force
```

## Workflow

```text
Issue URL + Project
  │
  ├─ 0. Read guardrails.md                    ── Always first
  │
  ├─ 1. INTAKE (intake.md)                    ── assign issue to me
  │     Fetch issue, find code context,
  │     dependency gate (skip if blocked_by open),
  │     vagueness gate (what/where/verify)
  │     → blocked if too vague OR has open blockers
  │
  ├─ 2. ENRICH (enrich.md)                    ── update issue body
  │     Pattern quality evaluation
  │     Grill-me self-interrogation
  │     Confidence-gated decisions
  │     → blocked if low-confidence (plan-first/auto mode)
  │
  ├─ 3. PLAN (plan.md)
  │     E2E hook check (build if missing)
  │     Structured-backlog decomposition
  │     Parallel group identification
  │
  ├─ 4. EXECUTE (execute.md)                  ── follow tdd-pocock per task
  │     Worktree set up via scaffold-workspace (if not already)
  │     Vertical-slice TDD: test→impl→test→impl
  │     Parallel groups via subagents (optional)
  │
  ├─ 5. VALIDATE (validate.md)
  │     Layer 1:   Tests pass
  │     Layer 1.5: Schema-refutation (refute-first; external-contract code)
  │     Layer 2:   ACs verified
  │     Layer 3:   code-review ≥ Solid
  │     Layer 4:   E2E hooks pass (if applicable)
  │     → blocked if validation fails after retry
  │
  ├─ 6. SHIP (ship.md)                        ── draft PR → ready for review
  │     Push branch, create draft PR (gh-pr-create)
  │     Execution log in PR description
  │     Mark PR ready when validation green
  │
  └─ 7. RETROSPECT (retrospect.md)
        Analyze session friction
        Create skills for gaps found
        Write implementable refactor plans
```

## Execution

### Fresh Start

1. Read `phases/guardrails.md`
2. Read `phases/intake.md` — execute it
3. Read `phases/enrich.md` — execute it
4. Read `phases/plan.md` — execute it
5. Read `phases/execute.md` — execute it
6. Read `phases/validate.md` — execute it
7. Read `phases/ship.md` — execute it
8. Read `phases/retrospect.md` — execute it

At each phase transition, append to the execution log (a markdown buffer
the orchestrator carries through the run, embedded in the PR description
at SHIP time).

### Resume After Block

When the user says "resume the orchestrator on issue #NNN":

1. Fetch the issue: `gh issue view NNN --json title,body,labels,comments`
2. Read the latest comment to find the human's response to the blocking question
3. Look at whether a draft PR exists to know how far along the run got
4. Read `phases/guardrails.md`
5. Read the sub-skill for the blocked phase
6. Continue from where the phase stopped, incorporating the human's input
7. Remove the `orchestrator-blocked` label

### Resume mapping

| Signal | Resume from |
|--------|-------------|
| Issue assigned, no code context comment | `intake.md` |
| Issue body enriched, no draft PR | `enrich.md` or `plan.md` (check log) |
| Draft PR exists, tests failing | `execute.md` or `validate.md` |
| Draft PR exists, review fails | `validate.md` |

## Mode Reference

| Mode | When to use | Low-confidence behavior |
|------|-------------|------------------------|
| `plan-first` | Default. Architectural decisions, new features. | Write parallel plan sketches, ask human to pick. |
| `build-first` | Implementation-level uncertainty. | Build both options in parallel worktrees, compare in VALIDATE. |
| `auto` | Let the orchestrator decide. | Architectural → plan-first. Implementation → build-first. |

## Error Handling

| Error | Action |
|-------|--------|
| Issue is private and you don't have access | Stop. |
| Issue has open `blocked_by` dependencies (intake) | Add `orchestrator-blocked`, comment which issues block it, stop. Don't start blocked work. |
| Code context not found (intake) | Add `orchestrator-blocked` label, comment asking for pointers |
| Vagueness gate fails | Add `orchestrator-blocked` label, comment listing unanswerable questions |
| Low-confidence decision (enrich) | Mode-dependent: block or split |
| Tests fail after 2 attempts | Stop and report |
| `code-review` phase scores 0 after retry | Stop and report |
| E2E validation can't be built | Stop and report |
| `gh` CLI not authenticated | Stop and report |
| Sub-skill file missing | Stop and list what needs to be installed |

## Output

When complete, report:

```text
Full-path orchestrator complete.

  Issue:     {repo}#{number} — {title}
  PR:        {pr_url}
  Branch:    {branch_name}
  Worktree:  {worktree_path}

  Tasks:     {completed}/{total}
  Tests:     {pass_count} passing ({new_count} new)
  ACs:       {covered}/{total} verified
  Review:    {band} ({pct}%)
  E2E:       {pass/fail/n/a}

  Decisions: {high_count} high, {medium_count} medium (flagged)
  Blocks:    {block_count} encountered, {resolved_count} resolved

  Retrospect:
    Skills created:     {count}
    Refactors proposed: {count}

Review the PR when ready.
```

## Composition

This skill composes other skills — each remains usable independently:

```text
grill-me ─────────────┐
code-review ──────────┤
structured-backlog ───┤── full-path-github ──▶ PR
tdd-pocock ───────────┤
gh-pr-create ─────────┘
scaffold-workspace ──── (optional, for worktree setup)
```

## Predecessor

A GitHub issue exists (raw or groomed). For personal projects this is
typically your own brain dump — a sentence or two is fine; INTAKE will
flag if it's too vague to proceed.

## Successor

You review the PR. The orchestrator's execution log in the PR description
provides full context for self-review.

## Origin

Adapted from a private GitLab-flavored orchestrator. The TDD inner loop
in EXECUTE delegates to the [`tdd-pocock`](../tdd-pocock/) skill (Matt
Pocock's TDD skill, MIT-licensed, redistributed in this repo with
attribution).
