---
title: Fleet dashboard — unify repo plans + workbench + worktree into one card per initiative
---

# Fleet dashboard — local work, fully in concert

**Goal:** Make each initiative show as ONE rich card in the dashboard by merging its three physical pieces — the durable repo plan, the local workbench folder, and the worktree — keyed by a normalized slug. So the dashboard reflects how work actually lives, whether it's local or cloud-originated.

## The model (settled with Jon, 2026-06-23)
An initiative has up to three pieces, tied by one slug (normalize `_` / `-` / case — `cot_trip_matcher` == `cot-trip-matcher`):

1. **Durable plan — `<repo>/plans/<column>/<slug>`** (in the repo, on main). Authoritative card source, so **cloud-originated work always shows** (cloud has no local workbench). May be a **flat file `<slug>.md` OR a folder `<slug>/README.md`** (+ resources) — the two forms are equivalent; richer plans get a folder.
2. **Local working surface — `<repo>_workspace/workbench/<slug>/`** (README + resources + `.code-workspace`). Enrichment when present; this is where active local thinking lives. `scaffold-workspace` should always create it alongside a worktree.
3. **Worktree — `build-<slug>` / `<repo>-<slug>`** — the code + its substance (unmerged commits, dirty files — already implemented).

**The two stores mirror each other** (same folder shape, two homes): workbench = local working copy; repo/plans = durable committed copy. A completed workbench folder commits into `repo/plans/completed/<slug>/` as-is. They cover each other's blind spots: local work has a workbench but needs its plan committed to the repo for durability/cloud-reach; cloud work has only the repo plan.

## Approach
- **Plan reader accepts folder OR file:** `plans/<column>/<slug>.md` or `plans/<column>/<slug>/README.md`; read title/goal/body from whichever exists.
- **Read workbench folders too:** walk `<repo>_workspace/workbench/` (root = active, `completed/` = done) as initiative folders — re-introducing (and generalizing) the initiative reader that v1 had and Leaf 1 stripped.
- **3-way merge by normalized slug:** unify repo-plan (authoritative card) + workbench folder (enrichment: local context, paired `.code-workspace`) + worktree (substance). Each piece optional; degrade gracefully (cloud = plan only; old local = workbench+worktree, maybe no repo plan yet).
- Surface in the card: plan goal/body, "local working context" from the workbench, and the worktree substance (done).

## Acceptance
- [ ] Repo plan reader handles both `<slug>.md` and `<slug>/README.md` (folder) forms.
- [ ] Collector reads `<repo>_workspace/workbench/<slug>/` initiative folders (active/completed).
- [ ] One card per initiative merges repo-plan + workbench + worktree by normalized slug (`_`/`-`/case insensitive); pieces optional.
- [ ] Cloud-only initiative (repo plan, no workbench/worktree) shows correctly; local-only (workbench+worktree, no repo plan yet) shows correctly.
- [ ] Existing underscore workbench folders (cot_trip_matcher) pair to hyphen plans/branches without renames.
- [ ] Collector tests green + new tests for folder-form plans, workbench reading, 3-way merge, slug normalization.
- [ ] Dashboard renders the unified card.

## Companion skill updates (this PR or noted)
- **scaffold-workspace:** always create a paired `workbench/<slug>/` folder with the worktree.
- **new-plan:** write the durable plan to `<repo>/plans/<column>/` (folder-or-file), and for LOCAL work also scaffold the workbench folder. Commit the plan to main (it's a tracking artifact, not code).

## Out of scope (next PR)
- Forge-only GitHub items (PRs/issues with no local footprint) → `plans/backlog/fleet-forge-only-data-path.md`.
