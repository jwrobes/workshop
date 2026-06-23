---
title: Fleet dashboard — forge-only data path (surface GitHub-only specs/PRs/issues)
---

# Fleet dashboard — forge-only data path

**Goal:** Make the fleet dashboard surface specs/PRs/issues that exist only on GitHub (no local file or worktree) — closing the "local-first" blind spot so cloud-build work, orphan PRs, and issue-as-spec records all appear.

## Context
The dashboard is local-first today: it reads local `plans/*.md` + worktrees (with each worktree's PR via `gh pr list --head`). It does NOT independently query GitHub for all PRs/issues in a repo. So it's blind to:
- cloud-build specs an agent is working on the web (no local worktree),
- open PRs on branches not checked out locally,
- issue-as-spec records with no local plan file.

This is the #1 documented limitation (see fleet-dashboard/README "Known limitations") and the gate to the dashboard being a *complete* view. Tool lives at `~/workspace/workshop/fleet-dashboard/`.

## Approach
- Extend the `Forge` interface with `list_open_prs(repo)` and `list_issues(repo)` (GitHub via `gh`; GitLab stub).
- In the collector, for each product member repo, pull open PRs + issues and reconcile against local plans/worktrees by branch/title/issue-ref.
- Emit GitHub-only items (no local match) into status.json so the template can show them — as plan cards flagged "cloud / no local footprint" and/or in a "remote-only" lane on the pipeline map.
- Gate behind `gh` availability (degrade gracefully under `--no-gh`); works in `--no-local` forge-only mode too.

## Acceptance
- [ ] Collector lists open PRs + issues per member repo via the Forge interface.
- [ ] GitHub-only items (no local plan/worktree) appear in status.json + render in the dashboard, visibly distinct from local-backed plans.
- [ ] Reconciliation: an item with BOTH a local plan and a PR is not double-counted.
- [ ] Degrades cleanly under `--no-gh`; collector tests stay green + new tests for the forge-only reconciliation.
- [ ] README "Known limitations" updated to mark this closed.

## Out of scope (separate follow-ups)
- Per-plan issue links on existing local cards, real cloud/local path-tag detection, artifact discovery from docs/ — related stubbed bits, but not this card.
