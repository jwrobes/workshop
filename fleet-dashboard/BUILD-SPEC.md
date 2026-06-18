# Build Spec — Fleet Dashboard v2 (product → repo → worktree, two-level Kanban)

**Target repo:** `jwrobes/workshop` → new subfolder `fleet-dashboard/`
(shared alpha-tool shelf — the dashboard observes products, so it's a library,
not owned by any one product. Per STATE-OF-PLAY decision #8.)

**Scope of v1 of this build:** **Magic Me product only** (prove the model on the
product you actively run), then fan out to Yogada + an unaffiliated bucket later.

**Why this build:** it's the single gate before overnight scheduling
(visibility-before-autonomy). Once it exists, scheduling is turn-on, not build.

---

## What already exists (PORT, do not rewrite)

A working v1 collector lives at
`~/workspace/improve_ai_dev_workspace/improve_ai_dev-fleet-dashboard/fleet-dashboard/collector.py`
(branch `build-jwrobes-fleet-dashboard` of the local-only `improve_ai_dev` clone).
**Copy it as the starting point.** It already does the hard parts well:

- `git()/run()` helpers, `default_branch()`, `remote_slug()` (→ `org/repo`),
  `dirty_count()`, `last_commit_iso()`, `ahead_behind()`.
- **`is_merged()`** — squash-merge-aware (uses `git cherry` patch-equivalence).
- **`gh_pr(slug, branch)`** — PR state per branch (prefers merged>open>closed).
- Walks `~/workspace`, parses `git worktree list --porcelain`, builds rows with
  flags (`merged-but-not-removed`, `zombie`).
- **Naming-based initiative pairing** (`<repo>-<slug>` dir → initiative) — this is
  exactly the link-inference approach chosen for v2; keep and extend it.
- Emits a **self-contained HTML with data inlined** (no CORS, opens from
  `file://`). Output dir defaults to `~/workspace/.fleet/`.

Keep the two-layer architecture (DESIGN-v2 §137): `collector.py → status.json →
dashboard.html`. The JSON is the diffable seam the nightly loop needs.

## The two gaps v1 has (this build closes them)

### Gap 1 — Kanban source is wrong/shallow
v1's `collect_initiatives()` reads `*_workspace/workbench/` **folders**. The real
Kanban is **markdown files in `plans/` dirs**, at TWO levels:

- **Product level:** `~/workspace/magic-me-workspace/workbench/plans/`
  (coordinator repo = `Jwrobes-Magic/magic-me-workbench`) — the overall,
  cross-repo initiatives.
- **Repo level:** each member repo's own `plans/{active,backlog,completed}/`
  (e.g. `~/workspace/claw-playbook/plans/active/*.md`).

Replace `collect_initiatives()` with a **`collect_kanban()`** that reads both
levels: each `*.md` under `plans/<column>/` is a card; the column dir name
(`active`/`backlog`/`completed`, also accept `done`) is its status; parse YAML
frontmatter if present (title), else use the filename. Record `level`
(`product` | `repo`), the owning repo/product, and the card's path.

### Gap 2 — no product grouping
v1 emits flat lists. Add the **product → repo → worktree spine** from GitHub org
membership (DESIGN-v2 §1, §4; decision #4 — the org is the manifest, can't drift):

- `gh repo list Jwrobes-Magic --json name,nameWithOwner` → the member repos of the
  Magic Me product. Map each local clone in `~/workspace` to its product via its
  `remote_slug()` org (`Jwrobes-Magic` → Magic Me).
- Loose `jwrobes/*` repos (skills, tools, workshop, Jwrobes-AI-App, …) → an
  **"unaffiliated"** bucket (don't force them into a product). For v1 you may
  collect-but-collapse these; the focus is Magic Me.
- The coordinator repo (`magic-me-workbench` = `~/workspace/magic-me-workspace`)
  is the product's planning home, not a code member — tag it as the product's
  Kanban source, listed at the product level, not as a sub-repo card.

## Portability & forge abstraction (REQUIRED — design constraint)

This must not be a laptop-only, GitHub-only, Jwrobes-Magic-only tool. Three
levels of portability, in priority order:

### 1. Forge-agnostic seam (GitHub now, GitLab later)
All forge calls go behind a small **`Forge` interface** — never call `gh`
directly in the collector body. Define an ABC:

```python
class Forge:
    def list_repos(self, product_id) -> list[RepoRef]: ...   # org/group members
    def list_prs(self, repo_slug, branch=None) -> list[PR]:  ...
    # (issues later; v1 needs repos + PRs)

class GitHubForge(Forge):   # wraps `gh` CLI / REST  (org = product boundary)
class GitLabForge(Forge):   # STUB for v1 — wraps `glab` / GitLab API (group = product)
```

v1 implements `GitHubForge` fully and ships `GitLabForge` as a **documented stub**
(method signatures + a NotImplementedError noting the mapping: GitHub org→GitLab
group, PR→merge request, `gh`→`glab`). The collector picks the forge from config.
Goal: adding GitLab later = implement one class, change zero collector logic.

### 2. Config-driven, not hardcoded
No literal `Jwrobes-Magic` / `magic-me-workspace` / `~/workspace` in the logic.
A **`fleet.config.json`** (or YAML) declares the structure:

```json
{
  "forge": "github",
  "workspace_root": "~/workspace",
  "products": [
    { "id": "magic-me",
      "name": "Magic Me",
      "forge_org": "Jwrobes-Magic",
      "coordinator_repo": "Jwrobes-Magic/magic-me-workbench",
      "coordinator_plans_path": "workbench/plans" }
  ],
  "repo_plans_path": "plans",
  "plan_columns": ["active", "backlog", "completed", "done"]
}
```

The collector reads config → derives everything. Someone with a different forge,
org names, or `plans/` layout edits config, not code. Ship a real config for the
Magic Me setup as the working example.

### 3. Off-GitHub / cloud-portable state
Per DESIGN-v2 §4, local-git is one source, the **forge API is the shared,
cloud-portable layer**. The collector must run in two modes:
- **local mode** — has `~/workspace` checkouts: read worktrees/dirty/ahead-behind
  from local git AND repos/PRs from the forge.
- **forge-only mode** (`--no-local`) — no local checkouts (e.g. a cloud/CI run):
  skip the worktree layer, build the product→repo→PR + Kanban view purely from
  the forge API + reading `plans/` via the forge's file API. This is what makes
  it runnable as a scheduled cloud job, not just on the laptop.

Worktrees are inherently local (they live on disk), so forge-only mode shows
repos/PRs/Kanban but not local worktree dirtiness — that's expected and correct.

## Output shape (`status.json`)

```json
{
  "generated": "<iso>",
  "products": [
    {
      "name": "Magic Me",
      "coordinator": "Jwrobes-Magic/magic-me-workbench",
      "product_kanban": [ {"title","status","path"} ],
      "repos": [
        {
          "slug": "Jwrobes-Magic/claw-playbook",
          "repo_kanban": [ {"title","status","path"} ],
          "worktrees": [
            {"path","branch","dirty","ahead","behind","merged",
             "pr": {"number","state","mergedAt"},
             "linked_card": "<title or null>",   // naming inference
             "flags": ["merged-but-not-removed","zombie", ...]}
          ]
        }
      ]
    }
  ],
  "unaffiliated": { "repos": [ ... ] }
}
```

## Link inference (worktree/PR ↔ plan card)
Derive, no new frontmatter discipline (the chosen approach):
- Worktree dir `claw-playbook-spec-009` / branch `build-spec-009-*` → match a card
  whose filename/title contains `009` or the slug. Reuse v1's `norm()` + the
  `<repo>-<slug>` strip already in the worktree loop.
- A PR body "Implements spec #NNN" can corroborate but isn't required for v1.
- Unmatched is fine — show the worktree without a card and the card without a
  worktree (v1 already flags `no-worktree-pair`).

## Render (`dashboard.html`)
- Group **product → repo → worktree**, with the repo's Kanban columns and the
  product Kanban visible at their levels (the drill shape, DESIGN-v2 §27–30).
- Keep v1's self-contained-inlined approach; phone-readable is a plus, not
  required (the dashboard itself stays local/no-Pages — DESIGN-v2 §141; only
  comprehension artifacts get Pages).
- Surface the health flags prominently — fast morning triage is the goal
  (DESIGN-v2 §110). Don't re-noise: v1's first run flagged 20/26; only flag
  genuinely actionable states.

## Acceptance criteria
- [ ] Code lives in `jwrobes/workshop/fleet-dashboard/` (collector.py + template).
- [ ] `python3 collector.py` emits `status.json` + a self-contained `dashboard.html`.
- [ ] Reads BOTH Kanban levels (`magic-me-workspace/workbench/plans/` AND each
      member repo's `plans/{active,backlog,completed}/`) as markdown cards.
- [ ] Groups output by product from `gh repo list Jwrobes-Magic`; loose repos →
      unaffiliated bucket.
- [ ] Worktree rows retain v1's dirty/ahead/behind/merged/PR/flags fidelity
      (squash-merge-aware `is_merged` preserved).
- [ ] Worktree↔card links inferred from naming; unmatched handled gracefully.
- [ ] `--no-gh` offline mode still works (port v1's flag).
- [ ] **No hardcoded org/path/forge in logic** — all from `fleet.config.json`; a
      real Magic Me config ships as the working example.
- [ ] **All forge calls go through the `Forge` interface**; `GitHubForge` complete,
      `GitLabForge` a documented stub (org→group, PR→MR, gh→glab mapping noted).
- [ ] **`--no-local` (forge-only) mode works** — builds product→repo→PR + Kanban
      from the forge API with no local checkouts (cloud-portable); worktree layer
      gracefully absent.
- [ ] README in the subfolder (workshop convention) with run instructions.

## Decompose into leaves (parent tracker + native sub-issues)
1. **Port v1 engine + config + Forge seam into workshop** — copy collector.py;
   strip the initiative-folder reader; keep git/PR/flag logic; introduce
   `fleet.config.json` and the `Forge` ABC with `GitHubForge` (wrapping the v1
   `gh` calls) + a `GitLabForge` stub. The collector reads config and routes all
   forge calls through the interface. (foundation — blocks the rest)
2. **`collect_kanban()`** — two-level `plans/*.md` reader (product coordinator +
   each repo), columns from config, frontmatter-aware. Reads via local FS in
   local mode; via the Forge file API in forge-only mode.
3. **Product-grouping spine** — `Forge.list_repos(product)` → product→repo
   nesting from config; loose repos → unaffiliated bucket. Local clones mapped to
   products by remote org.
4. **Render the hierarchy + modes** — template.html drill view + flags; wire
   JSON→HTML; honor `--no-local` (forge-only) and `--no-gh`/offline. README.
   (Leaf 4 depends on 1–3; leaves 2 and 3 are parallel after leaf 1.)

## Out of scope for this v1
- Yogada / other products (fan out after Magic Me validates the model).
- The nightly `/schedule` diff-and-notify wiring (that's the NEXT step, post-build).
- Cleanup execution (v1 is report-only; DESIGN-v2 §139 — never auto-delete).
