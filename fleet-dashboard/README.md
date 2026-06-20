# fleet-dashboard

A cross-product fleet view — **product → repo → worktree** — with worktree/PR
health and (coming in later leaves) two-level Kanban. Walks a workspace of git
clones and emits `status.json` plus a self-contained `dashboard.html` (data
inlined, so it opens straight from `file://` with no CORS).

> **Alpha / work in progress.** This is **Leaf 1** (foundation) of Fleet
> Dashboard v2 — see issues #1 (tracker) and #2 (this leaf). It ports the v1
> collector engine and lays two seams the rest of v2 builds on. Leaves #3–#5
> add the Kanban reader, the product spine, and the real hierarchy render.

## What's here (Leaf 1)

- **`collector.py`** — the ported v1 engine: git/PR/flag fidelity, including the
  **squash-merge-aware** `is_merged` check, the `git worktree list --porcelain`
  parse, naming-based pairing, and the self-contained HTML emit.
- **`collect_kanban()`** (Leaf 2) — reads plans as markdown at two levels:
  product (coordinator repo's `coordinator_plans_path`) and repo (each member
  clone's `repo_plans_path`). The column directory is the card's status; the
  title comes from YAML frontmatter (`title:`) or the filename. Reads the local
  filesystem, or — in forge-only mode — via `Forge.read_dir`/`get_file`.
  Replaces v1's `collect_initiatives()`.
- **`fleet.config.json`** — declares the forge, workspace root, products, and
  plan paths/columns. **No org or path is hardcoded in code** — it all comes
  from here. Ships a real Magic Me config.
- **A forge seam** — a `Forge` ABC with `list_repos(product)` and
  `list_prs(repo_slug, branch=None)`. `GitHubForge` (wraps `gh`) is complete;
  `GitLabForge` is a documented stub (org→group, PR→MR, `gh`→`glab`). The
  collector body makes **no direct `gh` calls** — everything routes through the
  interface. Swapping forges is one class, zero collector changes.
- **`template.html`** — a minimal placeholder render (Leaf 4 ships the real
  product→repo→worktree drill hierarchy).

## Requirements

- Python 3.8+ (stdlib only — no third-party deps).
- `git` on `PATH`.
- `gh` (GitHub CLI), authenticated — only needed for PR lookups. Use `--no-gh`
  to skip them and run fully offline.

## Usage

```bash
python3 collector.py [--config FILE] [--out DIR] [--workspace DIR] [--no-gh]
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--config` | `./fleet.config.json` | fleet config to read |
| `--workspace` | `workspace_root` from config | dir of git clones to walk |
| `--out` | `<workspace_root>/.fleet` | where to write artifacts |
| `--no-gh` | off | skip forge PR lookups (offline) |

Outputs `status.json`, a dated `status-YYYY-MM-DD.json`, and `dashboard.html`
into the output dir.

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

## Known limitations (Leaf 1)

- **Offline `unprotected` is approximate.** Under `--no-gh` the collector can't
  know PR state, so a dirty/ahead-unmerged worktree may be flagged `unprotected`
  even when an open PR actually protects it. This is faithful to the v1 engine;
  read offline `unprotected` as "PR state unknown."
- **Pairing flags are dormant until Leaf 2.** `collect_initiatives()` was removed
  here; `collect_kanban()` (#3) repopulates the pairing set. Until then,
  pair-dependent flags (`no-workbench-pair`, `zombie`) don't fire.

## Tests

```bash
python3 test_collector.py      # stdlib unittest, no deps
```

Covers config loading, the forge seam (GitHub + GitLab stub), PR selection,
worktree parsing, the squash-merge-aware merged check (against a real local
git fixture), and an end-to-end `--no-gh` smoke run.
