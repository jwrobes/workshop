#!/usr/bin/env python3
"""Fleet collector: walk a workspace of git clones + worktrees, gather
worktree/PR/health status, and emit status.json plus a self-contained
dashboard.html (data inlined — no CORS issues opening from file://).

This is Leaf 1 (foundation) of Fleet Dashboard v2. It ports the v1 collector
engine and adds two seams the rest of v2 builds on:

  * a config file (`fleet.config.json`) — no org/path/forge is hardcoded in
    logic; everything product- or forge-specific is read from config; and
  * a forge abstraction (`Forge` ABC) — every forge call (PR/repo listing)
    routes through the interface, so the collector body contains no direct
    `gh` calls. `GitHubForge` is complete; `GitLabForge` is a documented stub.

The Kanban reader (`collect_kanban()`, Leaf 2 / #3) reads plans at two levels
— product coordinator + per-repo. The product spine (`build_product_tree()`,
Leaf 3 / #4) groups repos under products and worktrees under repos, with an
unaffiliated bucket for loose clones. The render (`template.html`), worktree<->
card link inference (`link_worktrees_to_cards()`), and `--no-local` forge-only
mode are Leaf 4 (#5). The v1 `collect_initiatives()` workbench reader was
replaced by `collect_kanban()`.

Modes:
    (default)   local — walk worktrees on disk + read plans from disk + forge PRs.
    --no-gh     skip forge calls (PR/repo lookups); local data only.
    --no-local  forge-only — product->repo->PR + Kanban from the API, no checkouts
                (cloud-portable; runs as a scheduled job with no local clones).

Usage:
    python3 collector.py [--config FILE] [--out DIR] [--workspace DIR]
                         [--no-gh] [--no-local]
"""

import argparse
import base64
import datetime
import json
import re
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path

STALE_DAYS = 14
DEFAULT_CONFIG = Path(__file__).parent / "fleet.config.json"


# --------------------------------------------------------------------------
# Shell + git helpers (ported verbatim from the v1 collector engine)
# --------------------------------------------------------------------------

def run(args, cwd=None, timeout=15):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        return 1, str(e)


def git(repo, *args):
    return run(["git", "-C", str(repo), *args])


def default_branch(repo):
    code, out = git(repo, "symbolic-ref", "refs/remotes/origin/HEAD")
    if code == 0:
        return out.rsplit("/", 1)[-1]
    for cand in ("main", "master"):
        if git(repo, "rev-parse", "--verify", f"refs/heads/{cand}")[0] == 0:
            return cand
    return None


def remote_slug(repo):
    code, out = git(repo, "remote", "get-url", "origin")
    if code != 0:
        return None
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", out)
    return m.group(1) if m else None


def _find_clone_by_slug(workspace_root, slug):
    """Return the local clone dir whose git remote matches `slug`
    (case-insensitive), or None. Maps a repo to its on-disk folder by its
    durable git identity, not by folder name (which may differ from the repo
    name). Mirrors how the repo-level Kanban reader attributes by remote org.
    """
    if not slug:
        return None
    target = slug.lower()
    workspace_root = Path(workspace_root)
    if not workspace_root.is_dir():
        return None
    for d in sorted(workspace_root.iterdir()):
        if (d / ".git").is_dir() and (remote_slug(d) or "").lower() == target:
            return d
    return None


def dirty_count(path):
    code, out = git(path, "status", "--porcelain")
    return len(out.splitlines()) if code == 0 and out else 0


def last_commit_iso(path):
    code, out = git(path, "log", "-1", "--format=%cI")
    return out if code == 0 and out else None


def ahead_behind(path, branch, base):
    """Returns (ahead, behind) vs origin/<base>; (None, None) if not computable."""
    code, out = git(path, "rev-list", "--left-right", "--count",
                    f"origin/{base}...{branch}")
    parts = out.split()
    if code != 0 or len(parts) != 2:
        return None, None
    behind, ahead = (int(x) for x in parts)
    return ahead, behind


def is_merged(path, branch, base):
    """Merged check that survives squash merges: git cherry lines starting
    with '-' are patch-equivalent upstream; any '+' line is unmerged."""
    # Fast path: no commits unique to the branch (incl. a branch sitting at
    # base) => nothing left to merge, treat as merged.
    code, out = git(path, "rev-list", "--count", f"origin/{base}..{branch}")
    if code == 0 and out == "0":
        return True
    code, out = git(path, "cherry", f"origin/{base}", branch)
    if code != 0:
        return None
    return not any(line.startswith("+") for line in out.splitlines())


def norm(s):
    return re.sub(r"[-_]", "-", s.lower())


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

class ConfigError(Exception):
    """Raised when fleet.config.json is missing or malformed."""


def load_config(path=DEFAULT_CONFIG):
    """Load fleet.config.json. All product/forge/path specifics live here;
    the collector logic reads them rather than hardcoding any value."""
    p = Path(path).expanduser()
    try:
        return json.loads(p.read_text())
    except FileNotFoundError:
        raise ConfigError(f"config not found: {p}")
    except json.JSONDecodeError as e:
        raise ConfigError(f"config is not valid JSON ({p}): {e}")


# --------------------------------------------------------------------------
# Forge abstraction seam
#
# Every forge interaction (listing repos for a product, listing PRs for a
# branch) goes through this interface. Adding a new forge is one class with
# zero collector changes. The collector body below makes NO direct `gh` calls.
# --------------------------------------------------------------------------

class Forge(ABC):
    """A version-control forge (GitHub, GitLab, ...). Maps the fleet's
    product/repo/PR concepts onto a concrete forge CLI or API."""

    @abstractmethod
    def list_repos(self, product):
        """Return member repo slugs ("org/repo") for a product (from its org/group)."""

    @abstractmethod
    def list_prs(self, repo_slug, branch=None):
        """Return a list of PR dicts ({number, state, mergedAt}) for repo_slug,
        optionally filtered to a head branch. [] when none/forge unavailable."""

    @abstractmethod
    def read_dir(self, repo_slug, path):
        """List a directory in a repo's default branch. Returns a list of
        {name, path, type} dicts ([] when missing/unavailable). Used by the
        forge-only Kanban reader so it needs no local checkout."""

    @abstractmethod
    def get_file(self, repo_slug, path):
        """Return the decoded text of a file in a repo's default branch,
        or None when missing/unavailable."""


class GitHubForge(Forge):
    """GitHub forge wrapping the `gh` CLI. This is the ONLY place `gh` is
    invoked — the collector body routes all forge calls through here."""

    def list_repos(self, product):
        org = product["forge_org"]
        code, out = run(["gh", "repo", "list", org,
                         "--json", "nameWithOwner", "--limit", "200"], timeout=30)
        if code != 0 or not out:
            return []
        try:
            repos = json.loads(out)
        except json.JSONDecodeError:
            return []
        return [r["nameWithOwner"] for r in repos if r.get("nameWithOwner")]

    def list_prs(self, repo_slug, branch=None):
        if not repo_slug:
            return []
        args = ["gh", "pr", "list", "--repo", repo_slug,
                "--state", "all", "--limit", "3",
                "--json", "number,state,mergedAt"]
        if branch:
            args += ["--head", branch]
        code, out = run(args, timeout=20)
        if code != 0 or not out:
            return []
        try:
            prs = json.loads(out)
        except json.JSONDecodeError:
            return []
        return prs

    def read_dir(self, repo_slug, path):
        if not repo_slug:
            return []
        code, out = run(["gh", "api", f"repos/{repo_slug}/contents/{path}"], timeout=20)
        if code != 0 or not out:
            return []
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):  # a file, not a directory
            return []
        return [{"name": e.get("name"), "path": e.get("path"), "type": e.get("type")}
                for e in data]

    def get_file(self, repo_slug, path):
        if not repo_slug:
            return None
        code, out = run(["gh", "api", f"repos/{repo_slug}/contents/{path}",
                         "--jq", ".content"], timeout=20)
        if code != 0 or not out:
            return None
        try:
            return base64.b64decode(out).decode("utf-8", "replace")
        except (ValueError, TypeError):
            return None


class GitLabForge(Forge):
    """STUB — not yet implemented. GitLab mapping for a future port:

      * GitHub *org* -> GitLab *group* (`product["forge_org"]` is the group path).
      * GitHub *PR*  -> GitLab *MR* (merge request).
      * `gh` CLI     -> `glab` CLI.

    Intended implementation:
      list_repos: `glab repo list -g <group> --output json`
      list_prs:   `glab mr list -R <group/repo> --source-branch <branch> -F json`

    Same method signatures as GitHubForge, so the collector needs zero changes
    when this is filled in.
    """

    def list_repos(self, product):
        raise NotImplementedError(
            "GitLabForge.list_repos: map org->group; use `glab repo list -g <group>`")

    def list_prs(self, repo_slug, branch=None):
        raise NotImplementedError(
            "GitLabForge.list_prs: PR->MR; use `glab mr list -R <repo> --source-branch <branch>`")

    def read_dir(self, repo_slug, path):
        raise NotImplementedError(
            "GitLabForge.read_dir: use `glab api projects/:id/repository/tree?path=<path>`")

    def get_file(self, repo_slug, path):
        raise NotImplementedError(
            "GitLabForge.get_file: use `glab api projects/:id/repository/files/<path>/raw`")


FORGES = {"github": GitHubForge, "gitlab": GitLabForge}


def make_forge(name):
    """Instantiate the forge named in config (e.g. cfg["forge"])."""
    try:
        return FORGES[name]()
    except KeyError:
        raise ValueError(f"unknown forge {name!r}; known: {sorted(FORGES)}")


# --------------------------------------------------------------------------
# Kanban reader (two-level: product coordinator + per-repo plans)
#
# Replaces v1's collect_initiatives() workbench reader. Plans live as markdown
# under <plans_path>/<column>/*.md; the column directory IS the card's status.
# Paths and columns come from config, so `completed` and `done` are both just
# configured columns. Reads from the local filesystem, or — in forge-only mode
# — through the Forge file API (no checkout needed).
# --------------------------------------------------------------------------

def parse_frontmatter_title(text):
    """Return the `title:` value from a leading YAML frontmatter block
    (between `---` fences), or None if absent."""
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            for fm in lines[1:i]:
                m = re.match(r"\s*title\s*:\s*(.+?)\s*$", fm)
                if m:
                    v = m.group(1).strip()
                    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                        v = v[1:-1]  # strip a matched quote pair only
                    return v or None
            return None
    return None


def _card(level, product_id, repo_name, status, title, path):
    return {"level": level, "product": product_id, "repo": repo_name,
            "status": status, "title": title, "path": str(path)}


def _kanban_local(base_dir, columns, level, product_id, repo_name):
    """Read cards from <base_dir>/<column>/*.md on the local filesystem."""
    cards = []
    base = Path(base_dir)
    for column in columns:
        col_dir = base / column
        if not col_dir.is_dir():
            continue
        for md in sorted(col_dir.glob("*.md")):
            text = md.read_text(errors="replace")
            title = parse_frontmatter_title(text) or md.stem
            cards.append(_card(level, product_id, repo_name, column, title, md))
    return cards


def _kanban_via_forge(forge, repo_slug, plans_path, columns, level, product_id, repo_name):
    """Read cards from <plans_path>/<column>/*.md via the Forge file API."""
    cards = []
    for column in columns:
        dir_path = "/".join(p for p in (plans_path, column) if p)
        try:
            entries = forge.read_dir(repo_slug, dir_path)
        except NotImplementedError:
            return cards
        for entry in entries:
            name = entry.get("name") or ""
            path = entry.get("path")
            if not path or not name.endswith(".md"):
                continue
            try:
                text = forge.get_file(repo_slug, path) or ""
            except NotImplementedError:
                text = ""
            title = parse_frontmatter_title(text) or name[:-3]
            cards.append(_card(level, product_id, repo_name, column, title, path))
    return cards


def collect_kanban(cfg, workspace_root, forge=None, use_forge=False):
    """Collect Kanban cards at two levels, paths/columns driven by config:

      * product level — each product's coordinator repo `coordinator_plans_path`;
      * repo level     — each member clone's `repo_plans_path`.

    In local mode reads the filesystem; in forge-only mode reads via the Forge
    file API. Each card carries its level, owning product/repo, status (the
    column), title (frontmatter or filename), and path.
    """
    columns = cfg.get("plan_columns", [])
    repo_plans_path = cfg.get("repo_plans_path", "plans")
    products = cfg.get("products", [])
    org_to_product = {p["forge_org"].lower(): p["id"]
                      for p in products if p.get("forge_org")}
    workspace_root = Path(workspace_root)
    cards = []

    # Product level — coordinator repo plans.
    for p in products:
        coord_repo = p.get("coordinator_repo", "")
        coord_path = p.get("coordinator_plans_path", "")
        if use_forge and forge is not None:
            cards += _kanban_via_forge(forge, coord_repo, coord_path, columns,
                                       "product", p["id"], None)
        else:
            # Resolve the coordinator's LOCAL dir by matching its git remote
            # slug to coordinator_repo — NOT by assuming the folder name equals
            # the repo name. A local checkout is often named differently from
            # its repo (the on-disk folder vs the remote slug), so a
            # name-equality assumption silently reads zero product-level cards.
            # The repo-level reader below already maps by remote; do the same here.
            coord_dir = _find_clone_by_slug(workspace_root, coord_repo)
            if coord_dir is None:
                coord_dir = workspace_root / coord_repo.split("/")[-1]  # fallback
            base = coord_dir / coord_path
            cards += _kanban_local(base, columns, "product", p["id"], None)

    # Repo level — each member repo's plans.
    if use_forge and forge is not None:
        # Forge-only: enumerate member repos from the forge and read via the API.
        for p in products:
            coord = (p.get("coordinator_repo") or "").lower()
            try:
                member_slugs = forge.list_repos(p)
            except NotImplementedError:
                member_slugs = []
            for slug in member_slugs:
                if slug.lower() == coord:
                    continue  # coordinator already read at product level
                cards += _kanban_via_forge(forge, slug, repo_plans_path, columns,
                                           "repo", p["id"], slug.split("/")[-1])
    elif workspace_root.is_dir():
        # Local: each clone's plans, attributed to a product by org.
        for repo in sorted(workspace_root.iterdir()):
            if not (repo / ".git").is_dir():
                continue
            org = (remote_slug(repo) or "/").split("/")[0].lower()
            product_id = org_to_product.get(org)
            cards += _kanban_local(repo / repo_plans_path, columns,
                                   "repo", product_id, repo.name)

    # De-dupe by path so a card never double-counts (e.g. a coordinator whose
    # repo_plans_path and coordinator_plans_path overlap at both levels).
    seen, unique = set(), []
    for c in cards:
        if c["path"] in seen:
            continue
        seen.add(c["path"])
        unique.append(c)
    return unique


# --------------------------------------------------------------------------
# PR selection (collector-side, forge-agnostic)
#
# v1's gh_pr() both fetched and ranked PRs. Fetching now lives in the Forge;
# ranking (prefer merged > open > closed) stays here as collector logic.
# --------------------------------------------------------------------------

def pick_pr(prs):
    """From a list of PR dicts, return the most relevant one
    (prefer MERGED > OPEN > CLOSED), or None if the list is empty."""
    if not prs:
        return None
    order = {"MERGED": 0, "OPEN": 1, "CLOSED": 2}
    return sorted(prs, key=lambda p: order.get(p.get("state"), 3))[0]


# --------------------------------------------------------------------------
# Worktree discovery
# --------------------------------------------------------------------------

def parse_worktree_porcelain(out):
    """Parse `git worktree list --porcelain` into a list of
    {path, branch} dicts. Detached worktrees get branch '(detached)'."""
    entries = []
    cur = {}
    for line in out.splitlines() + [""]:
        if not line:
            if cur:
                entries.append(cur)
            cur = {}
        elif line.startswith("worktree "):
            cur["path"] = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            cur["branch"] = line.split("/")[-1]
        elif line == "detached":
            cur["branch"] = "(detached)"
    return entries


# --------------------------------------------------------------------------
# Product spine: group repos under products, worktrees under repos
# --------------------------------------------------------------------------

def build_product_tree(cfg, clones, forge=None, allow_forge=False):
    """Group repos under their product and worktrees under their repo.

    `clones` is a list of {name, slug, org, worktrees:[rows]} for the local
    workspace. A product's member repos come from config + `Forge.list_repos`
    (when `allow_forge`), unioned with any matching local clones. The
    coordinator repo is the product's Kanban home and is NOT listed as a
    sub-repo card. Local clones whose org matches no configured product land in
    the unaffiliated bucket. Returns `(products_out, unaffiliated_repos)`.
    """
    products = cfg.get("products", [])
    claimed = set()  # names of local clones placed under some product
    products_out = []

    for p in products:
        org = (p.get("forge_org") or "").lower()
        coord = (p.get("coordinator_repo") or "").lower()
        repo_map = {}  # keyed by slug-or-name (lower) -> repo node

        member_slugs = []
        if allow_forge and forge is not None:
            try:
                member_slugs = forge.list_repos(p)
            except NotImplementedError:
                member_slugs = []
        for slug in member_slugs:
            if slug.lower() == coord:
                continue  # coordinator is product-level, not a repo card
            repo_map.setdefault(slug.lower(),
                                {"slug": slug, "name": slug.split("/")[-1],
                                 "worktrees": []})

        if org:
            for c in clones:
                if (c.get("org") or "") != org:
                    continue
                key = (c.get("slug") or c["name"]).lower()
                if key == coord:
                    claimed.add(c["name"])  # coordinator clone: not a sub-repo card
                    continue
                node = repo_map.setdefault(key, {"slug": c.get("slug"),
                                                 "name": c["name"], "worktrees": []})
                node["worktrees"] = c["worktrees"]
                node["slug"] = c.get("slug") or node.get("slug")
                claimed.add(c["name"])

        pid = p.get("id") or p.get("forge_org") or "unknown"
        products_out.append({
            "id": pid, "name": p.get("name") or pid,
            "coordinator_repo": p.get("coordinator_repo"),
            "repos": [repo_map[k] for k in sorted(repo_map)],
        })

    unaffiliated = [{"slug": c.get("slug"), "name": c["name"],
                     "worktrees": c["worktrees"]}
                    for c in clones if c["name"] not in claimed]
    return products_out, unaffiliated


# --------------------------------------------------------------------------
# Link inference: pair worktrees to plan cards by naming (reuse norm())
# --------------------------------------------------------------------------

def worktree_card_key(row):
    """Derive a normalized slug for a worktree row from its branch
    (`build-<slug>`) or directory name (`<repo>-<slug>`)."""
    branch = row.get("branch") or ""
    if branch.startswith("build-"):
        return norm(branch[len("build-"):])
    name = Path(row.get("path", "")).name
    repo = row.get("repo") or ""
    prefix = repo + "-"
    if name.lower().startswith(prefix.lower()):
        return norm(name[len(prefix):])
    return norm(branch or name)


def link_worktrees_to_cards(rows, cards):
    """Attach a matching plan card to each worktree row by naming, and mark
    which cards have a worktree. Mutates rows (adds `card`) and cards (adds
    `has_worktree`). Unmatched both ways are left visible: a worktree keeps
    `card=None`; a card keeps `has_worktree=False`."""
    # Scope matches to the same repo so two repos' cards that normalize to the
    # same stem don't cross-link across the fleet.
    index = {}
    for c in cards:
        c.setdefault("has_worktree", False)
        index.setdefault((norm(c.get("repo") or ""), norm(Path(c["path"]).stem)), c)
    for row in rows:
        row["card"] = None
        if row.get("kind") != "worktree":
            continue
        card = index.get((norm(row.get("repo") or ""), worktree_card_key(row)))
        if card:
            card["has_worktree"] = True
            row["card"] = {"title": card["title"], "status": card["status"],
                           "level": card["level"], "path": card["path"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG),
                    help="path to fleet.config.json")
    ap.add_argument("--out", default=None,
                    help="output dir (default: <workspace_root>/.fleet)")
    ap.add_argument("--workspace", default=None,
                    help="override workspace_root from config")
    ap.add_argument("--no-gh", action="store_true", help="skip forge PR lookups (offline)")
    ap.add_argument("--no-local", action="store_true",
                    help="forge-only mode: product->repo->PR+Kanban from the API, "
                         "no local worktrees (cloud-portable)")
    args = ap.parse_args()

    try:
        cfg = load_config(args.config)
        forge = make_forge(cfg.get("forge", "github"))
    except (ConfigError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    # Resolve to an absolute path so each clone's path matches what
    # `git worktree list --porcelain` reports (which is always absolute) —
    # otherwise a relative --workspace misclassifies main clones as worktrees.
    workspace_root = Path(args.workspace or cfg.get("workspace_root", "~/workspace")).expanduser().resolve()
    out_dir = Path(args.out).expanduser() if args.out else (workspace_root / ".fleet")
    out_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.now(datetime.timezone.utc)

    # local mode walks worktrees + reads plans from disk; --no-local is
    # forge-only (product->repo->PR + Kanban from the API, no checkouts).
    local = not args.no_local
    if not local and args.no_gh:
        print("warning: --no-local with --no-gh has no data source "
              "(no local worktrees, no forge calls)", file=sys.stderr)

    # Two-level Kanban cards (product coordinator + per-repo plans).
    kanban = collect_kanban(cfg, workspace_root, forge, use_forge=not local)
    initiatives = []
    init_index = {}
    for ini in initiatives:
        init_index.setdefault(norm(ini["name"]), ini)

    rows = []
    clones = []
    seen_paths = set()
    if local and not workspace_root.is_dir():
        workspace_root.mkdir(parents=True, exist_ok=True)
    repo_iter = sorted(workspace_root.iterdir()) if local and workspace_root.is_dir() else []
    for repo in repo_iter:
        if not (repo / ".git").is_dir():  # main clones only (worktrees have a .git *file*)
            continue
        base = default_branch(repo)
        slug = remote_slug(repo)
        clone = {"name": repo.name, "slug": slug,
                 "org": (slug.split("/")[0].lower() if slug else None),
                 "worktrees": []}
        clones.append(clone)
        code, out = git(repo, "worktree", "list", "--porcelain")
        for e in parse_worktree_porcelain(out):
            path = Path(e["path"])
            if str(path) in seen_paths:
                continue
            seen_paths.add(str(path))
            kind = "clone" if path == repo else "worktree"
            branch = e.get("branch", "(unknown)")
            dirty = dirty_count(path)
            last = last_commit_iso(path)
            merged = None
            ahead = behind = None
            if base and branch not in ("(detached)", "(unknown)"):
                ahead, behind = ahead_behind(repo, branch, base)
                if kind == "worktree" and branch != base:
                    merged = is_merged(repo, branch, base)
            pr = None
            if (not args.no_gh and kind == "worktree"
                    and branch not in ("(detached)", "(unknown)") and branch != base):
                pr = pick_pr(forge.list_prs(slug, branch))

            # initiative pairing: worktree dir name is <project>-<slug-hyphens>
            ini = None
            if kind == "worktree":
                tail = path.name
                pref = repo.name + "-"
                if tail.lower().startswith(pref.lower()):
                    tail = tail[len(pref):]
                ini = init_index.get(norm(tail))

            flags = []
            in_workspace_dir = "_workspace" in str(path.parent.name)
            if kind == "worktree":
                if merged:
                    flags.append("merged-but-not-removed")
                if ini and ini["state"] == "completed":
                    flags.append("zombie")
                if last:
                    age = (now - datetime.datetime.fromisoformat(last)).days
                    if age >= STALE_DAYS and not merged:
                        flags.append("stale")
                # Only assert a missing pair when we actually have pairing data.
                # In Leaf 1 `initiatives` is empty (collect_initiatives() stripped;
                # collect_kanban() repopulates it in Leaf 2 / #3), so suppress this
                # flag rather than tag every worktree spuriously.
                if initiatives and not ini:
                    flags.append("no-workbench-pair")
                if not in_workspace_dir:
                    flags.append("orphan")
            # NOTE (v1-faithful behavior): under --no-gh, `pr` is always None, so a
            # dirty/ahead-unmerged worktree is flagged `unprotected` even if an open
            # PR would protect it online. Offline mode cannot know PR state; this
            # matches the v1 engine. Treat offline `unprotected` as "PR state unknown".
            if dirty or (ahead and not pr and merged is False):
                flags.append("unprotected")
            if kind == "clone" and behind:
                flags.append("behind-origin")

            row = {
                "repo": repo.name, "kind": kind, "path": str(path),
                "branch": branch, "dirty_files": dirty, "last_commit": last,
                "ahead": ahead, "behind": behind, "merged": merged,
                "pr": pr,
                "initiative": ini["name"] if ini else None,
                "initiative_state": ini["state"] if ini else None,
                "flags": flags,
            }
            rows.append(row)
            clone["worktrees"].append(row)

    paired = {r["initiative"] for r in rows if r["initiative"]}
    for ini in initiatives:
        ini["has_worktree"] = ini["name"] in paired
        ini["flags"] = []
        if ini["state"] == "active" and not ini["has_worktree"]:
            ini["flags"].append("no-worktree-pair")  # may be docs-only; informational

    products_out, unaffiliated = build_product_tree(
        cfg, clones, forge, allow_forge=not args.no_gh)

    # Forge-only mode: repos carry no local worktrees — surface their open PRs.
    if not local and not args.no_gh:
        for prod in products_out:
            for repo in prod["repos"]:
                if repo.get("slug"):
                    try:
                        repo["prs"] = forge.list_prs(repo["slug"])
                    except NotImplementedError:
                        repo["prs"] = []

    # Link inference: pair worktrees to plan cards by naming; unmatched stays
    # visible (worktree with card=None, card with has_worktree=False).
    link_worktrees_to_cards(rows, kanban)

    status = {
        "generated_at": now.isoformat(timespec="seconds"),
        "mode": "forge-only" if not local else "local",
        "worktrees": rows,
        "products": products_out,
        "unaffiliated": unaffiliated,
        "kanban": kanban,
        "initiatives": initiatives,
    }

    (out_dir / "status.json").write_text(json.dumps(status, indent=2))
    # keep dated history for diffing (phase 3)
    (out_dir / f"status-{now.date()}.json").write_text(json.dumps(status, indent=2))

    template = (Path(__file__).parent / "template.html").read_text()
    # Escape <, >, & as JSON \uXXXX so an inlined string containing "</script>"
    # (a card title, branch, path, ...) can't break out of the <script> element.
    payload = (json.dumps(status)
               .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))
    html = template.replace("/*__DATA__*/null", payload)
    (out_dir / "dashboard.html").write_text(html)

    n_flagged = sum(1 for r in rows if r["flags"])
    print(f"{len(rows)} rows ({sum(1 for r in rows if r['kind']=='worktree')} worktrees), "
          f"{n_flagged} flagged · wrote {out_dir}/dashboard.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
