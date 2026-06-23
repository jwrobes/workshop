---
title: Fleet dashboard — forge-only data path (surface GitHub-only items + dangling build-specs)
---

# Fleet dashboard — forge-only data path

**Goal:** Make the dashboard see work that exists only on GitHub — PRs/issues with no local footprint — and flag build-specs that are **dangling** in the pipeline. Reconcile against local sources so overlap doesn't create duplicate cards.

## Why (the gap, proven)
Local-first today: reads local plans + workbenches + worktrees (+ a worktree's PR). Does NOT query GitHub for all PRs/issues. So GitHub-only work is invisible.

**Worked example — PR #88** (Jwrobes-Magic/claw-playbook): "Build Spec 007: Email-Based Travel Transaction Filter", label `build-spec`, OPEN since 2026-06-08, branch `bosque/build-spec-007`. No local worktree/plan/workbench → invisible today. A **dangling build-spec**: spec PR open 2+ weeks, no implementation PR — fell out of the build-spec flow (SYSTEM-FLOWS.html). Exactly the debt to surface.

## Model: 4-way merge by normalized slug
Extend the 3-way merge (repo plan + workbench + worktree) with GitHub PRs/issues, keyed by norm() slug:
- Per member repo via Forge: list_open_prs + list_issues (GitHub real; GitLab stub).
- Reconcile against local (overlap IS expected): attach if branch-slug (bosque/build-spec-007 -> spec-007) OR title-norm matches a local card; no match -> remote-only card (#88); unsure -> remote-only (never false-merge).
- Dangling build-spec: a build-spec PR/issue OPEN with no downstream impl PR (and/or stale) -> flag dangling-spec, place early on the pipeline map.

## Acceptance
- [ ] Forge.list_open_prs + list_issues (GitHub real, GitLab stub).
- [ ] GitHub items with no local match -> remote-only cards (#88 shows).
- [ ] Items WITH a local match attach (no dup); unsure -> remote-only (no false-merge).
- [ ] build-spec open w/ no impl PR -> dangling-spec flag, early on pipeline map.
- [ ] Degrades under --no-gh; works under --no-local.
- [ ] Tests + new: list via Forge, reconciliation, dangling detection, no-false-merge.
- [ ] README local-first limitation marked closed.
