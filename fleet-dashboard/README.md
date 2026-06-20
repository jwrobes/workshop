# fleet-dashboard

A cross-product **fleet dashboard** — one view of every product, repo, and
worktree, grouped **product → repo → worktree**, with two-level Kanban
(coordinator + per-repo `plans/`), worktree/PR health flags, and plan↔work
links inferred from naming. Walks a workspace of git clones and emits
`status.json` plus a self-contained `dashboard.html` (data inlined, so it opens
straight from `file://` — no server, no CORS).

> **Alpha.** Built and used, not hardened — see the repo root README's "alpha"
> convention. v1 scope is the **Magic Me** product, then fan out.

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
| `products[]` | `id`, `name`, `forge_org`, `coordinator_repo`, `coordinator_plans_path` |

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
