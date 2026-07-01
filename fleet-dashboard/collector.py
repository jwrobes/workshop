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

import consolidate

STALE_DAYS = 14
# A merged PR anchors a track only if it merged within this window — recent
# shipped work (possibly broken, worth revisiting). Older merges are archive,
# not tracks. This is the deterministic scope that keeps the board usable (see
# TRACK-MODEL.md); without it, ALL merge history floods consolidation (77 tracks).
MERGED_RECENT_DAYS = 30
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


def dirty_count(path):
    code, out = git(path, "status", "--porcelain")
    return len(out.splitlines()) if code == 0 and out else 0


def dirty_files(path, cap=10):
    """Return (names, total): the uncommitted file paths in a worktree (porcelain),
    capped to `cap` names. `total` is the full count (so the UI can say "+N more")."""
    code, out = git(path, "status", "--porcelain")
    if code != 0 or not out:
        return [], 0
    lines = out.splitlines()
    # porcelain lines are "XY <path>" (rename shows "old -> new"); take the path tail.
    names = [ln[3:].split(" -> ")[-1].strip() for ln in lines if len(ln) > 3]
    return names[:cap], len(names)


def unmerged_subjects(path, branch, base, cap=10):
    """Return (subjects, total): commit subjects on `branch` not yet on
    origin/<base> — the actual in-flight work. Capped to `cap`; `total` is the
    full count. ([], 0) when not computable (detached, missing base, etc.)."""
    if not base or branch in ("(detached)", "(unknown)") or branch == base:
        return [], 0
    code, out = git(path, "log", "--format=%s", f"origin/{base}..{branch}")
    if code != 0 or not out:
        return [], 0
    subjects = [ln for ln in out.splitlines() if ln.strip()]
    return subjects[:cap], len(subjects)


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

    # --- Forge-only items: ALL open PRs / issues for a repo (no branch filter).
    # Concrete no-op defaults so existing Forge subclasses (and offline mode)
    # keep working; GitHubForge overrides these, GitLabForge raises.
    def list_open_prs(self, repo_slug):
        """Return a list of open-PR dicts for repo_slug:
        {number, title, headRefName, labels:[str], createdAt, isDraft, url}.
        [] when none/forge unavailable. Used to surface GitHub-only work that
        has no local footprint (the forge-only data path)."""
        return []

    def list_issues(self, repo_slug):
        """Return a list of open-issue dicts for repo_slug:
        {number, title, labels:[str], createdAt, url}. [] when none/unavailable."""
        return []

    def list_merged_prs(self, repo_slug, limit=60):
        """Return recently-MERGED PR dicts for repo_slug:
        {number, title, headRefName, labels:[str], mergedAt, url}. [] when
        none/unavailable. A merged *impl* PR is the 'shipped' signal (Phase 4a);
        a closed-not-merged PR is NOT here (a closed spec-PR is normal, not
        shipped). Default no-op so offline mode + GitLab stub keep working."""
        return []


class GitHubForge(Forge):
    """GitHub forge wrapping the `gh` CLI. This is the ONLY place `gh` is
    invoked — the collector body routes all forge calls through here."""

    def list_repos(self, product):
        # A product may define members only via `member_repos` (no forge_org);
        # then there's no org to enumerate — return [] and let the whitelist
        # supply members.
        org = product.get("forge_org")
        if not org:
            return []
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

    @staticmethod
    def _label_names(item):
        """Normalize gh's labels (list of {name}) to a list of label strings."""
        return [l.get("name") for l in (item.get("labels") or []) if l.get("name")]

    def list_open_prs(self, repo_slug):
        if not repo_slug:
            return []
        code, out = run(["gh", "pr", "list", "--repo", repo_slug,
                         "--state", "open", "--limit", "100", "--json",
                         "number,title,headRefName,labels,createdAt,isDraft,url"],
                        timeout=30)
        if code != 0 or not out:
            return []
        try:
            prs = json.loads(out)
        except json.JSONDecodeError:
            return []
        return [{"number": p.get("number"), "title": p.get("title") or "",
                 "headRefName": p.get("headRefName") or "",
                 "labels": self._label_names(p), "createdAt": p.get("createdAt"),
                 "isDraft": bool(p.get("isDraft")), "url": p.get("url")}
                for p in prs]

    def list_issues(self, repo_slug):
        if not repo_slug:
            return []
        # `gh issue list` excludes PRs by default (good — PRs come from list_open_prs).
        code, out = run(["gh", "issue", "list", "--repo", repo_slug,
                         "--state", "open", "--limit", "100", "--json",
                         "number,title,labels,createdAt,url"], timeout=30)
        if code != 0 or not out:
            return []
        try:
            issues = json.loads(out)
        except json.JSONDecodeError:
            return []
        return [{"number": i.get("number"), "title": i.get("title") or "",
                 "labels": self._label_names(i), "createdAt": i.get("createdAt"),
                 "url": i.get("url")}
                for i in issues]

    def list_merged_prs(self, repo_slug, limit=60):
        if not repo_slug:
            return []
        code, out = run(["gh", "pr", "list", "--repo", repo_slug,
                         "--state", "merged", "--limit", str(limit), "--json",
                         "number,title,headRefName,labels,mergedAt,url"],
                        timeout=30)
        if code != 0 or not out:
            return []
        try:
            prs = json.loads(out)
        except json.JSONDecodeError:
            return []
        return [{"number": p.get("number"), "title": p.get("title") or "",
                 "headRefName": p.get("headRefName") or "",
                 "labels": self._label_names(p), "mergedAt": p.get("mergedAt"),
                 "url": p.get("url")}
                for p in prs]


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

    def list_open_prs(self, repo_slug):
        raise NotImplementedError(
            "GitLabForge.list_open_prs: PR->MR; use `glab mr list -R <repo> --state opened -F json`")

    def list_issues(self, repo_slug):
        raise NotImplementedError(
            "GitLabForge.list_issues: use `glab issue list -R <repo> --state opened -F json`")


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

def parse_frontmatter(text, key):
    """Return a `<key>: value` from a leading YAML frontmatter block (between
    `---` fences), or None. Strips a single matched quote pair."""
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            for fm in lines[1:i]:
                m = re.match(r"\s*" + re.escape(key) + r"\s*:\s*(.+?)\s*$", fm)
                if m:
                    v = m.group(1).strip()
                    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                        v = v[1:-1]  # strip a matched quote pair only
                    return v or None
            return None
    return None


def parse_frontmatter_title(text):
    """Return the `title:` value from frontmatter, or None."""
    return parse_frontmatter(text, "title")


def _plan_goal(text):
    """Extract a one-line goal/highlight from a plan's markdown: the first
    non-empty prose line under a Goal/Summary/Overview/Purpose heading, else
    the first prose paragraph after the title/frontmatter. Best-effort."""
    if not text:
        return None
    body = text
    if body.lstrip().startswith("---"):
        parts = body.split("---", 2)
        if len(parts) == 3:
            body = parts[2]
    lines = body.splitlines()
    keys = ("goal", "summary", "overview", "purpose", "objective", "what", "why")
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("#"):
            head = s.lstrip("#").strip().lower().rstrip(":")
            if any(head == k or head.startswith(k) for k in keys):
                for nxt in lines[i + 1:]:
                    t = nxt.strip()
                    if t and not t.startswith("#"):
                        return t.lstrip("-*> ").strip()[:300]
    for ln in lines:
        t = ln.strip()
        if t and t[0] not in "#-*>":
            return t[:300]
    return None


def _slug_from_path(path):
    """Derive an initiative slug from a plan/card path. Handles both the flat
    `<slug>.md` form (stem = slug) and the folder `<slug>/README.md` form
    (the parent dir name is the slug, not 'README')."""
    p = Path(path)
    if p.name.lower() == "readme.md":
        return p.parent.name
    return p.stem


def _card(level, product_id, repo_name, status, title, path, text="", slug=None):
    # A product-level plan (in the coordinator/planning repo) can declare the
    # repo its work IMPLEMENTS in, via frontmatter `repo:`. That repo is where
    # spec-to-issue must file the issue — because the plan doc itself is in the
    # planning repo and unreachable from a session scoped to the impl repo.
    return {"level": level, "product": product_id, "repo": repo_name,
            "status": status, "title": title, "path": str(path),
            "slug": slug or _slug_from_path(path),
            "goal": _plan_goal(text), "body": text or "",
            "impl_repo": parse_frontmatter(text, "repo"),
            "workbench": None}


SPEC_BODY_MIN = 200  # chars of plan body that count as "a real spec exists"


def card_readiness(card):
    """Where a card sits on the spec->issue->build readiness ladder, so the
    dashboard can show what it NEEDS next:
      - 'done'      -> completed/shipped work (no action needed)
      - 'has-issue' -> a GitHub issue/PR exists -> ready to implement (full-path-github)
      - 'specd'     -> real plan body, no issue  -> needs the issue filed (spec-to-issue)
      - 'idea'      -> thin/empty body, no issue -> needs a spec authored first
    """
    if (card.get("status") or "") in ("completed", "done"):
        return "done"
    if (card.get("github") or {}).get("number"):
        return "has-issue"
    if len((card.get("body") or "").strip()) >= SPEC_BODY_MIN:
        return "specd"
    return "idea"


def _read_plan_entry(entry):
    """Given a plan entry that is EITHER a flat `<slug>.md` file OR a folder
    `<slug>/README.md`, return (slug, path_to_render, text). The two forms are
    equivalent (a richer plan gets a folder); the slug is the file stem or the
    dir name. Returns None if the entry isn't a recognizable plan."""
    if entry.is_file() and entry.suffix == ".md":
        return entry.stem, entry, entry.read_text(errors="replace")
    if entry.is_dir():
        readme = entry / "README.md"
        text = readme.read_text(errors="replace") if readme.is_file() else ""
        # A folder is a plan if it has a README (content) — else treat as a
        # plain folder card keyed by its dir name with no body.
        return entry.name, (readme if readme.is_file() else entry), text
    return None


def _kanban_local(base_dir, columns, level, product_id, repo_name):
    """Read cards from <base_dir>/<column>/ on the local filesystem. Each entry
    may be a flat `<slug>.md` file OR a folder `<slug>/README.md` — both forms
    produce one card (the folder form mirrors the workbench shape)."""
    cards = []
    base = Path(base_dir)
    for column in columns:
        col_dir = base / column
        if not col_dir.is_dir():
            continue
        for entry in sorted(col_dir.iterdir()):
            parsed = _read_plan_entry(entry)
            if parsed is None:
                continue
            slug, path, text = parsed
            title = parse_frontmatter_title(text) or slug
            cards.append(_card(level, product_id, repo_name, column, title, path, text))
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
            cards.append(_card(level, product_id, repo_name, column, title, path, text))
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
            coord_name = coord_repo.split("/")[-1]
            base = workspace_root / coord_name / coord_path
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
# Workbench reader (the LOCAL working surface, mirror of repo plans)
#
# An initiative's local working folder lives at
# <repo>_workspace/workbench/<slug>/ (README + resources + .code-workspace).
# Root-level dirs = active; a `completed/` subdir holds done initiatives. This
# is the enrichment half of the mirror: repo/plans is the durable record,
# workbench is the local working copy. Keyed by the same normalized slug.
# --------------------------------------------------------------------------

def collect_workbench(workspace_root):
    """Walk every `<repo>_workspace/workbench/<slug>/` initiative folder and
    return entries {repo, slug, status, path, title, goal, body, has_readme}.

    `repo` is the parent repo name (the `<repo>` of `<repo>_workspace`). Root
    dirs are `active`; dirs under a `completed/` subdir are `completed`. README
    content (if present) supplies title/goal/body."""
    entries = []
    workspace_root = Path(workspace_root)
    if not workspace_root.is_dir():
        return entries
    for ws in sorted(workspace_root.iterdir()):
        if not ws.is_dir() or not ws.name.endswith("_workspace"):
            continue
        repo = ws.name[: -len("_workspace")]
        bench = ws / "workbench"
        if not bench.is_dir():
            continue
        # (status, base_dir) pairs: active = bench root, completed = bench/completed
        scopes = [("active", bench), ("completed", bench / "completed")]
        for status, base in scopes:
            if not base.is_dir():
                continue
            for d in sorted(base.iterdir()):
                if not d.is_dir() or d.name == "completed":
                    continue
                readme = d / "README.md"
                has_readme = readme.is_file()
                text = readme.read_text(errors="replace") if has_readme else ""
                title = parse_frontmatter_title(text) or d.name
                entries.append({
                    "repo": repo, "slug": d.name, "status": status,
                    "path": str(d), "title": title,
                    "goal": _plan_goal(text), "body": text,
                    "has_readme": has_readme,
                })
    return entries


def merge_workbench_into_cards(cards, workbench_entries):
    """Merge workbench folders into the kanban cards by (repo, normalized slug).

    - A workbench entry whose slug matches a repo plan card ENRICHES that card
      (attaches `workbench` = {path, has_readme, status}). The repo plan stays
      authoritative for status/goal/body.
    - A workbench entry with NO matching repo plan becomes its own card (a
      local-only initiative not yet committed to the repo); its body/goal come
      from the workbench README.
    Returns the (possibly extended) card list."""
    index = {}
    for c in cards:
        index[(norm(c.get("repo") or ""), norm(c.get("slug") or ""))] = c
    for wb in workbench_entries:
        key = (norm(wb["repo"]), norm(wb["slug"]))
        card = index.get(key)
        wb_attach = {"path": wb["path"], "has_readme": wb["has_readme"],
                     "status": wb["status"]}
        if card is not None:
            card["workbench"] = wb_attach
        else:
            # Local-only initiative: workbench stands in as the card.
            new = _card("repo", None, wb["repo"], wb["status"], wb["title"],
                        wb["path"], wb["body"], slug=wb["slug"])
            new["workbench"] = wb_attach
            new["source"] = "workbench-only"
            cards.append(new)
            index[key] = new
    return cards


# --------------------------------------------------------------------------
# Forge-only data path (the 4th source: GitHub PRs/issues with no local footprint)
#
# Surfaces work that exists ONLY on the forge — a cloud-build spec with no local
# worktree, an orphan PR, an issue-as-spec — so the dashboard isn't local-first
# blind. Reconciles each GitHub item against the already-merged local cards
# (repo plan + workbench + worktree) by normalized slug or title; a match
# ATTACHES (no duplicate card), no match becomes a `remote-only` card. When
# uncertain we prefer remote-only over a wrong merge. build-spec items with no
# downstream implementation PR (and/or stale) are flagged `dangling-spec`.
# --------------------------------------------------------------------------

# A build-spec PR/issue open longer than this (and lacking an impl PR) is "stuck".
DANGLING_SPEC_DAYS = 7


def branch_slug_candidates(branch):
    """Candidate normalized slugs for a head branch like `bosque/build-spec-007`:
    the last path segment, with common build-/spec- prefixes also stripped.
    Returns a set of normalized slugs to match against card slugs."""
    if not branch:
        return set()
    tail = branch.split("/")[-1]
    cands = {norm(tail)}
    for pref in ("build-spec-", "build-", "spec-"):
        if tail.lower().startswith(pref):
            cands.add(norm(tail[len(pref):]))
    return {c for c in cands if c}


def _is_build_spec(labels, title):
    """Heuristic: a build-spec item carries a build-spec label or its title/
    branch reads like a build spec."""
    lab = {(l or "").lower() for l in (labels or [])}
    if "build-spec" in lab or "build_spec" in lab:
        return True
    return bool(re.search(r"\bbuild[\s_-]?spec\b", (title or ""), re.I))


def _age_days(created_iso, now):
    if not created_iso:
        return None
    try:
        return (now - datetime.datetime.fromisoformat(
            created_iso.replace("Z", "+00:00"))).days
    except ValueError:
        return None


def merge_forge_items_into_cards(cards, forge_items, now, repo_to_product=None):
    """Reconcile GitHub items (PRs + issues) against the local cards.

    `forge_items` is a list of dicts: {repo, kind:'pr'|'issue', number, title,
    branch, labels, createdAt, isDraft, url, has_impl_pr}. Each is matched to a
    local card in the SAME repo by branch-slug or normalized title:
      - match  -> attach `github` to that card (no duplicate).
      - no match -> a new `remote-only` card (source='remote-only').
      - ambiguous (matches >1 card) -> remote-only (never false-merge).
    A build-spec item that is open, has no impl PR, and (if datable) is older
    than DANGLING_SPEC_DAYS is flagged `dangling-spec` and parked at 'spec'd'.

    `repo_to_product` maps a repo name (lowercased) -> product id, so a
    remote-only card is attributed to the SAME product its repo belongs to (a
    claw-playbook PR lands under Magic Me, not product=None). Repos in no
    configured product get product=None (the unaffiliated bucket).
    Returns the (possibly extended) card list."""
    repo_to_product = repo_to_product or {}
    # Index local cards by (repo, slug) and (repo, title) for repo-level matches.
    # ALSO index product-level cards (repo=None) by (product, slug)/(product,
    # title): a Magic Me plan card lives at product level, but the PRs/branches
    # that implement it live in a member repo (claw-playbook). Without this, the
    # impl/spec PR can't find its plan card and scatters as a `remote-only` card
    # ("the real work is buried, not under Magic Me"). The product index lets a
    # member-repo item attach to its product-level plan via the shared slug.
    by_slug, by_title = {}, {}
    by_prod_slug, by_prod_title = {}, {}
    for c in cards:
        rk = norm(c.get("repo") or "")
        by_slug.setdefault((rk, norm(c.get("slug") or "")), []).append(c)
        by_title.setdefault((rk, norm(c.get("title") or "")), []).append(c)
        # Product-level cards (no repo) are the canonical plan; index by product.
        if c.get("level") == "product" and c.get("product"):
            pk = c["product"]
            by_prod_slug.setdefault((pk, norm(c.get("slug") or "")), []).append(c)
            by_prod_title.setdefault((pk, norm(c.get("title") or "")), []).append(c)

    for it in forge_items:
        rk = norm(it.get("repo") or "")
        pk = repo_to_product.get(rk)  # product this item's repo belongs to
        # Collect candidate matches, most-specific first:
        #   1. repo-level card by branch-slug, 2. repo-level card by title,
        #   3. product-level plan card by branch-slug, 4. by title.
        matches = []
        for cand in branch_slug_candidates(it.get("branch")):
            matches += by_slug.get((rk, cand), [])
        if not matches:
            matches += by_title.get((rk, norm(it.get("title") or "")), [])
        if not matches and pk:
            for cand in branch_slug_candidates(it.get("branch")):
                matches += by_prod_slug.get((pk, cand), [])
            if not matches:
                matches += by_prod_title.get((pk, norm(it.get("title") or "")), [])
        # De-dupe candidate cards (a card could match by both slug and title).
        uniq = []
        for m in matches:
            if m not in uniq:
                uniq.append(m)

        is_merged_item = bool(it.get("merged"))
        # `branch` (the PR head ref) is carried onto the card so strand-fact
        # source detection (bosque/web/dev) has a real signal — the title alone
        # can't distinguish a Bosque PR from a web one. Issues have branch=None.
        gh = {"kind": it.get("kind"), "number": it.get("number"),
              "title": it.get("title"), "url": it.get("url"),
              "state": "MERGED" if is_merged_item else "OPEN",
              "labels": it.get("labels") or [], "branch": it.get("branch"),
              "isDraft": bool(it.get("isDraft")), "createdAt": it.get("createdAt"),
              "mergedAt": it.get("mergedAt")}

        if len(uniq) == 1:
            # Unambiguous match -> attach (no duplicate card).
            card = uniq[0]
            # Phase 4a: a merged impl PR is the 'shipped' signal — it wins over a
            # prior open-PR attachment (a track can have both; shipped is later).
            # Don't downgrade a card already marked shipped to an open PR.
            already_shipped = card.get("shipped")
            if is_merged_item:
                card["github"] = gh
                card["shipped"] = True
                card["shipped_pr"] = it.get("number")
                card["shipped_at"] = it.get("mergedAt")
            elif not already_shipped:
                card["github"] = gh
        elif is_merged_item:
            # An UNMATCHED merged PR is shipped work whose (often auto-generated)
            # branch name matched no plan slug — e.g. `claude/trusting-bohr-...`.
            # RECENT ones (<= MERGED_RECENT_DAYS) anchor a track — they must NOT
            # vanish (that hid the real communications-hub feature #115/#117/#119).
            # OLD merges are archive: dropped, so they don't flood consolidation
            # (the 77-track wall). See TRACK-MODEL.md.
            mage = _age_days(it.get("mergedAt"), now)
            if mage is None or mage > MERGED_RECENT_DAYS:
                continue
            slug = (next(iter(branch_slug_candidates(it.get("branch"))), None)
                    or norm(it.get("title") or "")) or str(it.get("number"))
            cards.append({
                "level": "repo",
                "product": repo_to_product.get(norm(it.get("repo") or "")),
                "repo": it.get("repo"),
                "status": "shipped",
                "title": it.get("title") or f"{it.get('repo')}#{it.get('number')}",
                "path": it.get("url") or "", "slug": slug, "goal": None,
                "body": "", "workbench": None, "source": "merged-unmatched",
                "github": gh, "flags": [], "shipped": True,
                "shipped_pr": it.get("number"), "shipped_at": it.get("mergedAt"),
            })
            continue
        else:
            # No match, OR ambiguous (>1) -> remote-only card (never false-merge).
            # (Open PRs/issues with no local footprint ARE surfaced — that's
            # genuine GitHub-only work; only merged history is suppressed above.)
            age = _age_days(it.get("createdAt"), now)
            is_spec = _is_build_spec(it.get("labels"), it.get("title"))
            dangling = bool(is_spec and not it.get("has_impl_pr")
                            and (age is None or age >= DANGLING_SPEC_DAYS))
            slug = (next(iter(branch_slug_candidates(it.get("branch"))), None)
                    or norm(it.get("title") or "")) or str(it.get("number"))
            ref = f"{it.get('repo')}#{it.get('number')}"
            card = {
                "level": "repo",
                "product": repo_to_product.get(norm(it.get("repo") or "")),
                "repo": it.get("repo"),
                "status": "spec" if is_spec else "open",
                "title": it.get("title") or ref, "path": it.get("url") or "",
                "slug": slug, "goal": None, "body": "", "workbench": None,
                "source": "remote-only", "github": gh,
                "flags": (["dangling-spec"] if dangling else []),
                "age_days": age, "ambiguous_match": len(uniq) > 1,
            }
            cards.append(card)
            by_slug.setdefault((rk, slug), []).append(card)
    return cards


def collect_forge_items(cfg, forge, products_out):
    """Gather open PRs + issues for every product member repo, via the Forge.
    Returns a flat list of normalized item dicts (see merge_forge_items_into_cards).
    `has_impl_pr` marks a build-spec that has a SEPARATE non-spec PR referencing
    it (so the spec isn't 'dangling'); heuristically, any non-spec open PR in the
    repo whose branch slug matches the spec's slug counts as its impl."""
    items = []
    seen_repos = set()
    for prod in products_out:
        for repo in prod.get("repos", []):
            slug = repo.get("slug")
            if not slug or slug in seen_repos:
                continue
            seen_repos.add(slug)
            try:
                prs = forge.list_open_prs(slug)
                issues = forge.list_issues(slug)
            except NotImplementedError:
                continue
            # impl-PR detection: slugs of non-build-spec open PRs in this repo.
            impl_slugs = set()
            for p in prs:
                if not _is_build_spec(p.get("labels"), p.get("title")):
                    impl_slugs |= branch_slug_candidates(p.get("headRefName"))
            for p in prs:
                spec_slugs = branch_slug_candidates(p.get("headRefName"))
                has_impl = bool(_is_build_spec(p.get("labels"), p.get("title"))
                                and (spec_slugs & impl_slugs))
                items.append({
                    "repo": repo.get("name") or slug.split("/")[-1],
                    "kind": "pr", "number": p.get("number"),
                    "title": p.get("title"), "branch": p.get("headRefName"),
                    "labels": p.get("labels"), "createdAt": p.get("createdAt"),
                    "isDraft": p.get("isDraft"), "url": p.get("url"),
                    "has_impl_pr": has_impl,
                })
            for i in issues:
                items.append({
                    "repo": repo.get("name") or slug.split("/")[-1],
                    "kind": "issue", "number": i.get("number"),
                    "title": i.get("title"), "branch": None,
                    "labels": i.get("labels"), "createdAt": i.get("createdAt"),
                    "isDraft": False, "url": i.get("url"),
                    "has_impl_pr": False,
                })
            # Phase 4a: recently-MERGED impl PRs are the 'shipped' signal. A
            # merged *impl* PR (NOT a build-spec PR) attaches to its track/card
            # and marks it shipped. A merged build-spec PR is excluded — merging
            # a spec isn't shipping the feature. (Closed-not-merged PRs never get
            # here, so a closed spec-PR is correctly NOT treated as shipped.)
            try:
                merged = forge.list_merged_prs(slug)
            except NotImplementedError:
                merged = []
            for p in merged:
                if _is_build_spec(p.get("labels"), p.get("title")):
                    continue
                items.append({
                    "repo": repo.get("name") or slug.split("/")[-1],
                    "kind": "pr", "number": p.get("number"),
                    "title": p.get("title"), "branch": p.get("headRefName"),
                    "labels": p.get("labels"), "createdAt": p.get("mergedAt"),
                    "isDraft": False, "url": p.get("url"),
                    "has_impl_pr": False, "merged": True,
                    "mergedAt": p.get("mergedAt"),
                })
    return items


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

        # Membership: if `member_repos` is set, it's the AUTHORITATIVE whitelist
        # — the product claims ONLY those slugs. The forge org-member list is
        # IGNORED entirely (no union), so org members like a coordinator clone or
        # an unrelated org repo don't leak in. Otherwise fall back to org-match
        # (org = product boundary). This lets multiple products share one org.
        explicit = {s.lower() for s in (p.get("member_repos") or [])}
        use_whitelist = bool(explicit)

        if use_whitelist:
            for slug in explicit:
                if slug == coord:
                    continue  # coordinator is product-level, not a repo card
                repo_map.setdefault(slug, {"slug": slug,
                                           "name": slug.split("/")[-1],
                                           "worktrees": []})
        elif allow_forge and forge is not None:
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

        # Names already in the whitelist (so a local clone matches a whitelisted
        # member even when its remote slug differs by owner — e.g. whitelist
        # `owner-a/foo` vs the clone's remote `owner-b/foo`).
        explicit_names = {s.split("/")[-1].lower() for s in explicit}

        for c in clones:
            c_slug = (c.get("slug") or "").lower()
            c_org = (c.get("org") or "")
            key = (c.get("slug") or c["name"]).lower()
            # The coordinator is always claimed by its product (it's the Kanban
            # home, never a sub-repo card and never unaffiliated) — regardless of
            # whitelist/org membership rules below.
            if key == coord:
                claimed.add(c["name"])
                continue
            if use_whitelist:
                # match by exact slug OR by repo name (cross-owner same repo)
                if c_slug not in explicit and (c.get("name") or "").lower() not in explicit_names:
                    continue
            elif not (org and c_org == org):
                continue
            node = repo_map.setdefault(key, {"slug": c.get("slug"),
                                             "name": c["name"], "worktrees": []})
            node["worktrees"] = c["worktrees"]
            node["slug"] = c.get("slug") or node.get("slug")
            claimed.add(c["name"])

        pid = p.get("id") or p.get("forge_org") or "unknown"
        # De-dupe repos by normalized NAME so the same repo reached via two
        # different slugs (e.g. a whitelisted `owner-a/foo` plus the same repo
        # `owner-b/foo` discovered from a local clone's remote) collapses to one
        # card. Prefer the node that carries local worktrees when merging.
        by_name = {}
        for k in sorted(repo_map):
            node = repo_map[k]
            nk = norm(node.get("name") or "")
            cur = by_name.get(nk)
            if cur is None:
                by_name[nk] = node
                continue
            # Merge duplicate (same name, different slug): keep worktrees from
            # whichever node has them, and prefer a non-empty slug.
            if node.get("worktrees") and not cur.get("worktrees"):
                cur["worktrees"] = node["worktrees"]
            if not cur.get("slug") and node.get("slug"):
                cur["slug"] = node["slug"]
        products_out.append({
            "id": pid, "name": p.get("name") or pid,
            "coordinator_repo": p.get("coordinator_repo"),
            "repos": [by_name[k] for k in sorted(by_name)],
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
        # Key by the card's slug (robust to folder-form plans whose path ends in
        # README.md), falling back to the path stem for older cards.
        slug = c.get("slug") or _slug_from_path(c["path"])
        index.setdefault((norm(c.get("repo") or ""), norm(slug)), c)
    for row in rows:
        row["card"] = None
        if row.get("kind") != "worktree":
            continue
        card = index.get((norm(row.get("repo") or ""), worktree_card_key(row)))
        if card:
            card["has_worktree"] = True
            # Snapshot the card's goal too, so a worktree card can show real
            # context (what the work *is*) instead of just the branch name.
            row["card"] = {"title": card["title"], "status": card["status"],
                           "level": card["level"], "path": card["path"],
                           "goal": card.get("goal")}


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
    ap.add_argument("--consolidate", action="store_true",
                    help="run the LLM work-track consolidation pass (Phase 5), "
                         "caching tracks.json. Normal runs reuse the cache so "
                         "they stay fast + offline; corrections always apply.")
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
        # Skip worktree-bin folders: a `<repo>_workspace` dir with NO remote is a
        # holder for a project's worktrees, not a standalone repo. Its worktrees
        # already surface under the parent clone, so it must not appear as its own
        # repo/unaffiliated entry. (A `*_workspace` WITH a remote — e.g. a
        # coordinator like improve_ai_dev_workspace — is a real repo; keep it.)
        if repo.name.endswith("_workspace") and not slug:
            continue
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
            # Local work substance: the dirty file names and the unmerged commit
            # subjects (work on this branch not yet on main). Only meaningful for
            # worktrees; clones don't carry in-flight branch work here.
            dirty_names, dirty_total = ([], 0)
            unmerged, unmerged_total = ([], 0)
            if kind == "worktree":
                dirty_names, dirty_total = dirty_files(path)
                unmerged, unmerged_total = unmerged_subjects(path, branch, base)
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
            # `unprotected` means FEATURE-BRANCH work at risk (uncommitted or
            # unmerged-ahead with no PR safety net). It must NOT fire on a
            # default-branch (main/master) checkout: a dirty main clone is just
            # local edits on main, not feature work about to be lost — flagging
            # it buried the real actionable items under ~7 false positives.
            # A dirty default branch gets the quieter `dirty-default-branch`.
            is_default_branch = base is not None and branch == base
            # NOTE (v1-faithful): under --no-gh, `pr` is always None, so an
            # ahead-unmerged feature branch reads `unprotected` even if an open
            # PR would protect it online. Offline can't know PR state.
            if is_default_branch:
                if dirty:
                    flags.append("dirty-default-branch")
            elif dirty or (ahead and not pr and merged is False):
                flags.append("unprotected")
            if kind == "clone" and behind:
                flags.append("behind-origin")

            row = {
                "repo": repo.name, "kind": kind, "path": str(path),
                "branch": branch, "dirty_files": dirty, "last_commit": last,
                "ahead": ahead, "behind": behind, "merged": merged,
                "pr": pr,
                # local work substance (worktrees): dirty file names + unmerged
                # commit subjects, each capped with a *_total for "+N more".
                "dirty_files_names": dirty_names, "dirty_files_total": dirty_total,
                "unmerged_commits": unmerged, "unmerged_total": unmerged_total,
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

    # Merge the LOCAL workbench folders into the kanban (enrich matching repo
    # plans; surface workbench-only initiatives as their own cards). Local mode
    # only — workbench is a filesystem store, absent in forge-only runs.
    if local:
        workbench_entries = collect_workbench(workspace_root)
        merge_workbench_into_cards(kanban, workbench_entries)

    # Forge-only data path (4th source): open PRs/issues with no local footprint.
    # Reconcile against the local cards — matches attach, the rest become
    # `remote-only` cards (e.g. a dangling build-spec). Needs `gh`; skipped
    # under --no-gh. Runs in both local and forge-only modes.
    if not args.no_gh:
        forge_items = collect_forge_items(cfg, forge, products_out)
        # repo name -> product id, so remote-only cards inherit their repo's
        # product (a claw-playbook PR shows under Magic Me, not product=None).
        repo_to_product = {}
        for p in products_out:
            for r in p.get("repos", []):
                rn = (r.get("name") or (r.get("slug") or "").split("/")[-1])
                if rn:
                    repo_to_product[norm(rn)] = p.get("id")
        merge_forge_items_into_cards(kanban, forge_items, now, repo_to_product)

    # Link inference: pair worktrees to plan cards by naming; unmatched stays
    # visible (worktree with card=None, card with has_worktree=False).
    link_worktrees_to_cards(rows, kanban)

    # Readiness: classify every card AFTER github/workbench/worktree merges, so
    # it reflects the final state (idea / specd / has-issue / done). Drives the
    # card badge + the launch prompt's branch.
    for c in kanban:
        c["readiness"] = card_readiness(c)

    # Phase 5: work-track consolidation. The LLM pass is on-demand (--consolidate)
    # and cached to tracks.json so normal runs stay fast + offline. User
    # corrections (track-overrides.json, downloaded from the UI) ALWAYS win and
    # are applied every run — so a wrong grouping you fixed stays fixed, fully
    # reversible by editing/deleting the file.
    repo_dir = Path(__file__).parent
    if args.consolidate:
        llm_tracks = consolidate.run_llm_consolidation(kanban)
        consolidate.save_tracks(out_dir, llm_tracks)
        print(f"consolidate: {len(llm_tracks)} LLM track(s) -> {out_dir}/tracks.json")
    tracks = consolidate.load_tracks(out_dir)
    overrides = consolidate.load_overrides(out_dir, repo_dir)
    tracks = consolidate.apply_overrides(tracks, overrides)
    consolidate.attach_tracks_to_cards(kanban, tracks)
    # Phase 1: deterministic strand facts. Stamp each track with per-member
    # role/state/source/stage + a fact summary so the unified card renders
    # layer 1 (facts) with no LLM. See UNIFIED-CARD-MODEL.md.
    consolidate.stamp_track_facts(tracks, kanban)

    status = {
        "generated_at": now.isoformat(timespec="seconds"),
        "mode": "forge-only" if not local else "local",
        "worktrees": rows,
        "products": products_out,
        "unaffiliated": unaffiliated,
        "kanban": kanban,
        "initiatives": initiatives,
        "tracks": tracks,
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
