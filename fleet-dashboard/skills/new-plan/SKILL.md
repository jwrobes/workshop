---
name: new-plan
description: >-
  Start a new unit of work in the fleet format so it shows up correctly in the
  dashboard. Creates a plan card in the right product/repo plans/<column>/ dir,
  and — for LOCAL execution only — scaffolds a matching build-<slug> worktree.
  Routing-aware: cloud-build work gets a card (+ issue/launch prompt), no local
  worktree; local work gets card + worktree. Use when the user says "new plan",
  "start a plan/initiative", "add this to the fleet", or wants to kick off work.
---

# New Plan (fleet-format work setup)

The front door for new work. Its job: make sure every new initiative lands in
the **fleet format** — a plan card the dashboard can read, and (when worked
locally) a worktree named so the dashboard auto-links it — so the fleet never
drifts back into untracked mess.

## The routing decision (ask first — mirrors cloud-build vs local-only)

**Who executes this work?** This determines whether a LOCAL worktree is created:

| Path | Executor | Worktree? |
|------|----------|-----------|
| **local** | you, or local Claude Code on this machine | **Yes** — `build-<slug>` worktree so you work in it and it shows in the dashboard |
| **cloud** | Claude-on-web (claude.ai/code) | **No local worktree** — the cloud session makes its own branch remotely. Create the card + (optionally) the issue/launch prompt instead. |

A local worktree for cloud work would be dead weight you never touch — don't make
it. (Same logic as the build-spec `cloud-build` vs `local-only` routing.)

## Inputs
- **title** — the plan title (becomes the slug, kebab-cased).
- **path** — `local` or `cloud` (ask if not given).
- **product / repo** — which product + member repo this belongs to (read from
  the fleet config / dashboard; ask if ambiguous). Product-level plans live in
  the coordinator's `coordinator_plans_path`; repo plans in that repo's
  `repo_plans_path`.
- **column** — defaults to `active` (or `backlog` if not started).

## Step 1: Resolve where the card goes
Read `fleet.config.json` (next to this tool). A plan belongs to either:
- a **repo**: `<workspace_root>/<repo>/<repo_plans_path>/<column>/<slug>.md`
- the **product** (cross-cutting): `<coordinator clone>/<coordinator_plans_path>/<column>/<slug>.md`

Confirm the target dir exists (create the `<column>/` dir if missing).

## Step 2: Write the plan card
Create `<slug>.md` with frontmatter the dashboard reads (title) and a **goal**
line up top (the dashboard surfaces the first prose line / a Goal heading):

```markdown
---
title: <Human Title>
---

# <Human Title>

**Goal:** <one sentence — what this delivers / the highlight the dashboard shows>

## Context
<why now, where it lives, links>

## Approach
- <step>
- <step>

## Acceptance
- [ ] <testable criterion>
```

Keep the goal line crisp — it's what shows on the plan card and L4 hub.

## Step 3a: LOCAL path → scaffold the worktree
Create a worktree named to match the slug so the dashboard's naming-inference
links it to the card automatically:

```bash
cd <workspace_root>/<repo>
git worktree add <workspace_root>/<repo>_workspace/<repo>-<slug> -b build-<slug> origin/main
```

(If the repo uses the `scaffold-workspace` conventions / a project setup skill,
follow those for bootstrap-file symlinks etc.) The `build-<slug>` branch + the
`<repo>-<slug>` dir are what the collector pairs to the card.

## Step 3b: CLOUD path → no worktree; prep for the web
Do NOT create a local worktree. Instead:
- (optional) file the GitHub issue with the spec inline (the issue body IS the
  spec — see the `spec-to-issue` skill) and label it for cloud-build.
- emit the standard cloud launch prompt (clone `jwrobes/skills`, run
  `full-path-github` on the issue) for the human to paste into claude.ai/code.
- the plan card stays as the local record; the dashboard shows it as an active
  plan **without** a local worktree (correct — it's cloud work).

## Step 4: Confirm it shows up
Re-run the dashboard (`./run.sh` / `fleet-doctor.py --refresh`) and confirm the
new card appears under the right product/repo, linked to its worktree (local) or
flagged as worktree-less (cloud). That round-trip is the proof it's in-format.

## Output
- A plan card in the correct `plans/<column>/` dir, dashboard-readable.
- LOCAL: a `build-<slug>` worktree linked to the card.
- CLOUD: no worktree; optional issue + launch prompt.
- A confirmation that the dashboard now reflects the new work.

## Composition
The fleet-format front door. Pairs with `scaffold-workspace` (worktree
mechanics), `spec-to-issue` (cloud issue/spec), and the fleet dashboard +
`fleet-doctor` (which then track the work you just created).
