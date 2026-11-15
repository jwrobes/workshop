---
name: spec-to-issue
description: >-
  Set up loop-runnable work from a spec: put the spec where the executor can
  ALWAYS reach it (the GitHub issue body), optionally open a draft review-PR that
  is closed-not-merged when work begins, and instruct the executor to
  re-materialize the spec onto its branch if durable. Feeds full-path-github.
  Use when the user says "turn this into an issue", "set up this spec for the
  loop", "groom this for the orchestrator", or hands you a spec/plan to delegate.
---

# Spec → Issue (work setup that feeds full-path-github)

This is the **pre-intake** step. `full-path-github` starts from a *groomed
issue*; this skill produces that issue from a spec, in a way that avoids the
recurring discoverability dead-end (the executor told to fetch something it can't
reach) and the dirty-local-git trap.

## The core rule — the issue body IS the spec

A cloud / headless session is **guaranteed** to have one thing: the issue it's
pointed at. Anything else (a spec file in another repo, a vendored doc, a
local-only clone) may be unreachable. So:

> **The full spec goes in the issue body.** Not a link to a spec file. Not "see
> the spec PR." The text itself. Reachability becomes a non-problem because there
> is nothing to fetch.

Corollaries:
- **Small reference *code* to port goes inline too** — as a fenced code block in
  the issue (GitHub blocks `.py` attachments and has no attachments API, so
  attachments don't help). A few hundred lines in a ```` ```python ```` block is
  fine and fully reachable. Large source belongs in the repo, not the issue.
- **Never** reference a path in a local-only clone (no remote) or in a *different*
  repo than the one the executor is scoped to. Verify reachability (see Step 3).

## Reaching SHARED skills (workshop) from a non-laptop instance

Reusable skills live in **one source of truth** — `jwrobes/workshop` (and
`jwrobes/skills` for the dev/orchestrator skills). How an instance reaches them
depends on the instance, and there are **three** types (not two):

| Instance | Skill access | Mechanism |
|----------|--------------|-----------|
| **Laptop** (interactive) | `~/.claude/skills/` symlinks → the workshop/skills checkouts | already set up; add a symlink per new shared skill |
| **Cloud / web** (claude.ai/code) | repo-scoped, no shared FS | **clone at runtime** |
| **Server cron** (headless) | bare `~/.claude`, NO skills dir, NO local checkout | **clone at runtime** (same as cloud) |

So **clone-at-runtime is the portable mechanism for any non-laptop instance.**
When a launch prompt (or a spec's instructions) needs a shared skill, include
this preamble so the session can always reach it:

```bash
# Shared skills live in their own repos, NOT in this work-repo. Clone what you need:
git clone --depth 1 https://github.com/jwrobes/skills.git   /tmp/skills    # dev/orchestrator skills
git clone --depth 1 https://github.com/jwrobes/workshop.git /tmp/workshop  # shared workshop tools/skills
# then read e.g. /tmp/skills/full-path-github/SKILL.md  or  /tmp/workshop/<skill>/SKILL.md
```

Only clone what the work actually needs. One source of truth, zero drift, zero
per-repo vendoring — the cost is that the prompt must include the clone line, so
make it boilerplate. (Vendoring a skill into the work-repo is the alternative —
zero-setup reach but drift risk; reserve it for skills a session can't function
without and that change rarely, like the orchestrator.)

## The spec-PR is a review surface, not an artifact

A spec doesn't *need* a PR — but a PR is a far better **review** surface (inline
comments, rendered diff, a thread). So the spec-PR is **optional and
review-only**:

- Open it as a **DRAFT**, titled `SPEC (review only — do not merge)`.
- Review/comment there; sync accepted edits **back into the issue body** (the
  source of truth).
- **Close it — do NOT merge it — when implementation begins.** Its job was
  review; merging it would commit a planning doc into the repo (clutter +
  reachability risk) and never-merging it would leave a zombie PR (the exact
  "unhealthy state" the fleet dashboard exists to kill).
- The spec's *durable* home is the impl branch (next rule), not this PR.

## Re-materialize the spec onto the impl branch (if durable)

Tell the executor: **if the spec is worth keeping with the code**, write it into
the implementation branch as a `docs/` or `plans/` file as part of the work — so
the spec ships, reviewed, on the real (merged) PR, co-located with what it
describes. This dovetails with the comprehension-artifact gate. Trivial specs
need not be materialized; say so.

## Steps

### Step 1: Assess the spec
- Is it groomed enough to run? (what / where / how-to-verify — the vagueness
  gate `full-path-github` will apply anyway). Tighten if not.
- Does it cite reference *code* to port? Decide: small → inline in the issue;
  large → it must live in the target repo (commit it there first), never in a
  local-only/other repo.

### Step 2: Decompose if needed
Multi-part work → parent tracker + native sub-issues (`POST issues/{n}/sub_issues
-F sub_issue_id=<int>`), `blocked_by` deps (`-F issue_id=<int>`), `ready` on the
unblocked leaf. (Same conventions as `full-path-github` guardrails — integer
`-F` form; the string form silently no-ops.)

### Step 3: Reachability pre-flight (the dead-end guard)
Before filing, for EVERY path/repo the spec references, confirm the executor can
reach it from the repo it will be scoped to:

```bash
# Is a referenced repo a local-only clone (no remote)? → unreachable, inline or vendor it.
git -C <referenced-clone> remote -v        # empty = local-only = NOT reachable
# Is the referenced file in a DIFFERENT repo than the executor's target? → unreachable.
```

Anything unreachable → **inline it into the issue** (spec text, or small code in a
code block) or **commit it into the target repo first**. This is the step that
prevents the #105 / vendored-skill / v1-collector dead-ends.

### Step 4: File the issue(s) with the spec inline
Issue body = the full spec + any inline reference code block + (for leaves) the
acceptance criteria. Add the standing instruction:

> Your spec is THIS issue body. Implement against the repo as it really is
> (ground every cited path). If this spec is worth keeping, write it into your
> branch under `docs/` or `plans/` as part of the work.

### Step 5: (Optional) Open the draft review-PR
Only if the user wants a review pass before work starts. Draft, titled `SPEC
(review only — do not merge)`, body = the spec (or a pointer to the issue).
Record that it must be **closed, not merged**, when implementation begins.

### Step 6: Handle dirty local git (don't disturb in-flight work)
If you must touch a local repo (e.g. to commit reference code into the target),
NEVER work in a dirty checkout or on someone's feature branch:
- Check `git -C <repo> status --short` and `git branch --show-current`.
- If dirty / on a feature branch → create an **isolated worktree off
  `origin/main`** (`git worktree add <tmp> -b <branch> origin/main`) and work
  there. Leave the existing checkout untouched. Push the new branch; open a PR.

### Step 7: Hand off
Report the issue number(s) + the launch instruction for `full-path-github`
(point it at the ready leaf; it clones the orchestrator skill or reads the
vendored copy). Note any spec-PR that must be closed-not-merged at impl start.

## Output
- Issue(s) whose body IS the spec, fully reachable (nothing to fetch).
- Native sub-issue tree + deps if decomposed; `ready` on the unblocked leaf.
- Optional draft review-PR, flagged close-not-merge.
- Reference code inlined or committed into the target repo (never local-only).
- A clean hand-off to `full-path-github`.

## Composition
Feeds `full-path-github` (this produces the groomed issue it consumes). Pairs
with `structured-backlog` (decomposition) and the `comprehension-artifact` gate
(the spec re-materialized on-branch is the same low-comprehension-debt instinct).
