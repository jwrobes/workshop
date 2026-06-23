---
title: Fleet dashboard — pair worktrees with their workbench + surface local work substance
---

# Fleet dashboard — local worktree + workbench pairing

**Goal:** Make each local worktree a rich, first-class card by (1) pairing it with its associated workbench folder so the card's goal/context/plan come from those docs, and (2) surfacing the actual in-flight substance — dirty changes AND commits not yet on `main`. Most real work lives in local worktrees + their workbenches; the dashboard should reflect that, not just bare git-state rows.

## Context
Today the collector reads plan cards from the **main clone's `plans/`** and treats each worktree as a thin git-state row (dirty count, ahead/behind, PR). It does NOT:
- connect a worktree to **its** workbench's planning docs (the `*_workspace/<initiative>/` or paired workbench that actually describes the work), so the card lacks real goal/context;
- surface **commits not on main** as work substance (a worktree can have real unmerged progress that's invisible beyond an "ahead N" number).

Result: a worktree where most of your work happens shows up nearly empty. The richest source of a card's content is local — this closes that. Tool: `~/workspace/workshop/fleet-dashboard/`.

## Approach
- **Pair by naming convention** (matches existing inference): worktree dir `<repo>-<slug>` / branch `build-<slug>` ↔ workbench initiative `<slug>` (a `workbench/<slug>/` folder or a `plans/.../<slug>.md`). Find the paired workbench for each worktree.
- **Pull card content from the paired workbench**: goal/title/body from the workbench's plan doc(s), so a worktree card shows what the work *is*, not just its branch name.
- **Surface unmerged substance**: list/summarize commits on the branch not on `main` (subjects), alongside dirty changes — the actual in-flight work.
- Keep it config-driven (workspace_root, naming) and degrade gracefully when no paired workbench exists (fall back to today's behavior).

## Acceptance
- [ ] Each worktree is paired (by slug) to its workbench folder/plan doc when one exists; pairing surfaced in status.json.
- [ ] A worktree card shows goal/context pulled from the paired workbench (not just the branch name).
- [ ] Commits-not-on-main (subjects) + dirty changes are in status.json and render on the worktree/plan card.
- [ ] Graceful fallback when no paired workbench; collector tests stay green + new tests for pairing + unmerged-commit reading.
- [ ] Dashboard renders the richer worktree cards.

## Out of scope (separate cards)
- **Forge-only GitHub items** (PRs/issues with no local footprint) → `plans/backlog/fleet-forge-only-data-path.md` (next PR).
- Per-plan issue links, real path-tag detection, `docs/` artifact discovery.
