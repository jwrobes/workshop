# fleet-dashboard

A cross-product **fleet dashboard** — one view of every product, repo, and
worktree, grouped **product → repo → worktree**, with two-level Kanban
(coordinator + per-repo `plans/`), worktree/PR health flags, and plan↔work
links inferred from naming. Walks a workspace of git clones and emits
`status.json` plus a self-contained `dashboard.html` (data inlined, so it opens
straight from `file://` — no server, no CORS).

> **Alpha.** Built and used, not hardened — see the repo root README's "alpha"
> convention. v1 scope is the **Magic Me** product, then fan out.

## What ships here

| File | Role |
|------|------|
| `collector.py` | walks the workspace → `status.json` + `dashboard.html` |
| `template.html` | the rendered dashboard (4-level + pipeline map) |
| `fleet.config.json` | machine-/account-specific config (products, member_repos, paths) |
| `run.sh` | regenerate + open the dashboard (one command) |
| `fleet-doctor.py` | **terminal** health check — flags reapable/stale/orphan worktrees, plans without worktrees, AND **likely-duplicate cards** (same initiative living unmerged across sources — repo plan / workbench / GitHub — with the proposed slug alignment to merge them). Report-only, copy-paste commands, never executes. |
| `skills/new-plan/` | start new work in fleet format — plan card (+ a `build-<slug>` worktree for LOCAL work; card-only + launch prompt for CLOUD work). The front door that keeps the fleet from drifting. |

**Keeping the fleet healthy is two moves, not a repeated cleanup chore:**
1. **Start new work via `new-plan`** so it lands in-format (card the dashboard reads; worktree named so it auto-links).
2. **Check state via the dashboard (`./run.sh`) or `fleet-doctor.py`** — both surface what's mergeable/stale/drifted. Reaps are proposed, you approve.

## Quick start (including on a fresh machine)

```bash
# 1. you need: python3, git, and gh (GitHub CLI, authenticated: `gh auth login`)
# 2. point fleet.config.json at THIS machine's setup:
#    - workspace_root: the dir holding your git clones (default ~/workspace)
#    - products[].member_repos: the repo slugs that belong to each product
#    (config is machine-/account-specific — edit it, don't assume the defaults)
# 3. run it:
./run.sh                 # regenerate + open the dashboard (auto-falls back to --no-gh if gh is missing)
# or directly:
python3 collector.py --out ~/.fleet && open ~/.fleet/dashboard.html
```

No install step, no third-party Python deps. Everything the dashboard needs is
inlined into `dashboard.html`, so it opens from `file://` with no server.

## Why

It's the single gate before overnight scheduling: visibility before autonomy.
One morning-triage page showing what's in flight, what's merged-but-not-cleaned,
what's stale, and which plan cards have (or lack) a worktree.

## How it's built

Forge-agnostic and config-driven by design, so it can run on your laptop against
local checkouts **or** as a scheduled cloud job with no checkouts at all:

- **Config-driven** — no org/path/forge is hardcoded. `fleet.config.json`
  declares products, the coordinator repo, and plan paths/columns.
- **Forge seam** — every forge call goes through a `Forge` interface.
  `GitHubForge` wraps `gh`; `GitLabForge` is a documented stub (org→group,
  PR→MR, `gh`→`glab`). Adding GitLab later is one class, zero collector changes.
- **Two collectors + a spine + a render:**
  - `collect_kanban()` — reads plan cards as markdown at two levels: product
    (coordinator repo's `coordinator_plans_path`) and repo (each member clone's
    `repo_plans_path`). The column dir is the card's status; the title comes
    from YAML frontmatter `title:` or the filename.
  - the worktree walk — git/PR/flag fidelity from v1, incl. the
    **squash-merge-aware** merged check.
  - `build_product_tree()` — groups repos under products and worktrees under
    repos (from config + `Forge.list_repos`); loose clones go to an
    **unaffiliated** bucket; the coordinator repo is the product's Kanban home,
    not a sub-repo card.
  - `link_worktrees_to_cards()` — pairs a worktree (`build-<slug>` branch or
    `<repo>-<slug>` dir) to a plan card by naming; unmatched is shown gracefully
    both ways (worktree with no card, card with no worktree).
  - `template.html` — renders the drill hierarchy with both Kanban levels and
    health flags up top for fast triage.

## Requirements

- Python 3.8+ (stdlib only — no third-party deps).
- `git` on `PATH` (for local mode).
- `gh` (GitHub CLI), authenticated — for PR/repo lookups and forge-only mode.
  Not needed with `--no-gh`.

## Usage

```bash
python3 collector.py [--config FILE] [--out DIR] [--workspace DIR] [--no-gh] [--no-local]
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--config` | `./fleet.config.json` | fleet config to read |
| `--workspace` | `workspace_root` from config | dir of git clones to walk |
| `--out` | `<workspace_root>/.fleet` | where to write artifacts |
| `--no-gh` | off | skip forge calls (PR + repo lookups); local data only |
| `--no-local` | off | forge-only: product→repo→PR+Kanban from the API, no checkouts |

Writes `status.json`, a dated `status-YYYY-MM-DD.json`, and the self-contained
`dashboard.html` into the output dir. Open `dashboard.html` in a browser.

### Modes

| Mode | Command | What it reads |
|------|---------|---------------|
| **Local** (default) | `python3 collector.py` | worktrees + plans from disk, PRs from the forge |
| **Offline** | `python3 collector.py --no-gh` | local worktrees + plans only (no forge calls) |
| **Forge-only** | `python3 collector.py --no-local` | product→repo→PR + Kanban from the forge API; no worktree layer (cloud-portable — runs as a scheduled job with no clones) |

## Configuration

`fleet.config.json`:

```json
{
  "forge": "github",
  "workspace_root": "~/workspace",
  "repo_plans_path": "plans",
  "plan_columns": ["active", "backlog", "completed", "done"],
  "products": [
    {
      "id": "magic-me",
      "name": "Magic Me",
      "forge_org": "Jwrobes-Magic",
      "coordinator_repo": "Jwrobes-Magic/magic-me-workbench",
      "coordinator_plans_path": "workbench/plans"
    }
  ]
}
```

| Key | Meaning |
|-----|---------|
| `forge` | which `Forge` to use (`github`; `gitlab` is a stub) |
| `workspace_root` | dir of local git clones to walk |
| `repo_plans_path` | per-repo plans dir (relative to each clone) |
| `plan_columns` | Kanban columns = status values (`completed` and `done` both fine) |
| `products[]` | `id`, `name`, `forge_org`, `coordinator_repo`, `coordinator_plans_path`, `member_repos` |
| `products[].member_repos` | **Authoritative whitelist** of repo slugs in this product. When set, the product claims ONLY these (org is ignored for membership) — so multiple products can share one org, and cross-org members work (e.g. `jwrobes/wizard` in a `Jwrobes-Magic` product). When omitted, membership falls back to `forge_org` match. Repos in no product → the unaffiliated bucket. |

## Output shape (`status.json`)

```
generated_at, mode,
worktrees[]    — flat rows (repo, kind, branch, flags, pr, merged, card, …)
products[]     — { id, name, coordinator_repo, repos[] { slug, name, worktrees[], prs[] } }
unaffiliated[] — loose repos (no configured product)
kanban[]       — cards { level, product, repo, status, title, path, has_worktree }
```

## Health flags

`merged-but-not-removed`, `stale` (>14d, unmerged), `zombie`, `unprotected`,
`orphan`, `behind-origin`, `no-workbench-pair`. The dashboard surfaces flagged
worktrees in a "Needs attention" block at the top.

## Known limitations

- **Forge-only items (GitHub PRs/issues with no local footprint) — now surfaced.**
  The collector lists every member repo's open PRs + issues via the `Forge`
  (`gh`), reconciles each against the local cards by branch-slug or title, and
  either **attaches** it to the matching card (no duplicate) or surfaces it as a
  **`remote-only`** card. So cloud-build specs with no local worktree, orphan
  PRs, and issue-as-spec records are visible. A `build-spec` item that is open
  with no implementation PR (and older than a threshold) is flagged
  **`dangling-spec`** and parked at the `spec'd` stage on the pipeline map.
  Requires `gh`; under `--no-gh` the collector stays local-only (no remote-only
  cards). Reconciliation is conservative — an ambiguous match becomes
  remote-only rather than risk a wrong merge.
- **Per-plan issue links + cloud/local path tags are inferred/stubbed.** Issue
  links show "not wired yet"; the path tag (cloud/local) is best-effort from
  branch/PR signals, not authoritative. Same forge-wiring task addresses these.
- **Comprehension artifacts (the "what I built" slot) aren't auto-discovered.**
  The L4 slot always renders (so it's clear where workflow HTML belongs), but the
  collector doesn't yet scan `docs/` for actual artifacts.
- **Offline `unprotected` is approximate.** Under `--no-gh` the collector can't
  know PR state, so a dirty/ahead-unmerged worktree may be flagged `unprotected`
  even when an open PR protects it. Faithful to the v1 engine.
- **Forge-only `--no-local` with `--no-gh`** has no data source (no worktrees,
  no forge) and warns.

## Tests

```bash
python3 test_collector.py      # stdlib unittest, no deps
```

Covers config loading, the forge seam (GitHub + GitLab stub), PR selection, the
two-level Kanban reader (frontmatter + filename fallback, config columns), the
product spine (grouping + unaffiliated + coordinator handling), link inference,
the squash-merge-aware merged check (real git fixture), `--no-gh` and
`--no-local` modes, and end-to-end smoke runs.
