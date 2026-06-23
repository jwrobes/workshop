---
title: fleet-doctor — detect duplicate/same-initiative cards across sources, propose merging
---

# fleet-doctor — unmerged/duplicate card detection

**Goal:** Extend fleet-doctor (the terminal health check) to find cards that are likely the SAME initiative but live unmerged across sources, and propose the exact alignment to merge them — report+propose, never auto. Directly attacks the "disjoint piles" problem (58 repo-plan cards vs 14 workbench cards, currently 0 overlap — some are surely the same work recorded twice).

## Depends on
The forge-only data path (4-way merge) landing first, so status.json carries all sources (repo plan + workbench + worktree + GitHub PR/issue) for the check to compare.

## What it does
- Compare cards across sources by fuzzy slug/title similarity (normalized; near-match, not just exact).
- Flag likely-same pairs that DIDN'T auto-merge (because slugs differ): e.g. `plans/venmo-enrichment.md` + `workbench/venmo_enrichment/` + PR `bosque/...venmo...`.
- For each, **propose the concrete alignment** to make them merge: the rename/move command (e.g. "rename workbench/venmo_enrichment → venmo-enrichment to match the plan slug") + show what would unify.
- Report-only; human approves each (same posture as the reap proposals).
- Optionally: a guarded "apply" mode that does the rename after confirmation.

## Acceptance
- [ ] fleet-doctor lists likely-duplicate cards across sources with a similarity reason.
- [ ] For each, proposes the exact rename/move to unify them.
- [ ] Never auto-applies; human approves (apply mode optional + guarded).
- [ ] Tests for the similarity/dup detection.
