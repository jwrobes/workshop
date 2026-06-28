#!/usr/bin/env python3
"""Tests for the Fleet v2 Leaf 1 collector.

Stdlib unittest only — no third-party deps. Run:

    python3 test_collector.py            # or: python3 -m unittest -v

Each test maps to a Leaf 1 acceptance criterion (see assertions / docstrings).
"""

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import collector


def _run(args, cwd):
    subprocess.run(args, cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _git(cwd, *args):
    _run(["git", *args], cwd)


class ConfigTests(unittest.TestCase):
    """AC2: config present with real Magic Me values; read from config."""

    def setUp(self):
        self.cfg = collector.load_config()

    def test_loads_default_config(self):
        self.assertEqual(self.cfg["forge"], "github")
        self.assertIn("workspace_root", self.cfg)

    def test_magic_me_product_values(self):
        prod = self.cfg["products"][0]
        self.assertEqual(prod["forge_org"], "Jwrobes-Magic")
        self.assertEqual(prod["coordinator_repo"], "Jwrobes-Magic/magic-me-workbench")
        self.assertEqual(prod["coordinator_plans_path"], "workbench/plans")

    def test_columns_include_completed_and_done(self):
        self.assertEqual(self.cfg["repo_plans_path"], "plans")
        for col in ("active", "backlog", "completed", "done"):
            self.assertIn(col, self.cfg["plan_columns"])


class NoHardcodingTests(unittest.TestCase):
    """AC2/AC3: no hardcoded org/path or direct `gh` in the collector body."""

    def setUp(self):
        self.src = Path(collector.__file__).read_text()

    def test_no_hardcoded_org_or_coordinator_path_in_code(self):
        # These live in fleet.config.json, never in collector logic.
        self.assertNotIn("Jwrobes-Magic", self.src)
        self.assertNotIn("magic-me-workbench", self.src)
        self.assertNotIn("workbench/plans", self.src)

    def test_gh_only_invoked_inside_github_forge(self):
        # Every `"gh"` literal must sit inside the GitHubForge class — the
        # collector body routes all forge calls through the Forge interface.
        gh_lines = [i for i, ln in enumerate(self.src.splitlines())
                    if '"gh"' in ln or "'gh'" in ln]
        self.assertTrue(gh_lines, "expected gh usage inside GitHubForge")
        start = self.src.index("class GitHubForge")
        end = self.src.index("class GitLabForge")
        gh_region = range(self.src[:start].count("\n"), self.src[:end].count("\n"))
        for ln in gh_lines:
            self.assertIn(ln, gh_region, f"`gh` used outside GitHubForge at line {ln + 1}")


class ForgeTests(unittest.TestCase):
    """AC3: Forge ABC + complete GitHubForge + documented GitLabForge stub."""

    def test_make_forge_github(self):
        self.assertIsInstance(collector.make_forge("github"), collector.GitHubForge)

    def test_make_forge_unknown_raises(self):
        with self.assertRaises(ValueError):
            collector.make_forge("bitbucket")

    def test_forge_is_abstract(self):
        with self.assertRaises(TypeError):
            collector.Forge()  # cannot instantiate an ABC with abstract methods

    def test_gitlab_stub_raises_not_implemented(self):
        gl = collector.GitLabForge()
        with self.assertRaises(NotImplementedError):
            gl.list_repos({"forge_org": "g"})
        with self.assertRaises(NotImplementedError):
            gl.list_prs("g/r", "branch")

    def test_gitlab_stub_documents_mapping(self):
        doc = collector.GitLabForge.__doc__ or ""
        self.assertIn("group", doc.lower())
        self.assertIn("glab", doc.lower())
        self.assertIn("mr", doc.lower())

    def test_github_forge_list_prs_no_slug(self):
        self.assertEqual(collector.GitHubForge().list_prs(None, "b"), [])


class PickPrTests(unittest.TestCase):
    """PR selection logic preserved from v1 (prefer merged > open > closed)."""

    def test_empty(self):
        self.assertIsNone(collector.pick_pr([]))

    def test_prefers_merged(self):
        prs = [{"number": 1, "state": "CLOSED"},
               {"number": 2, "state": "OPEN"},
               {"number": 3, "state": "MERGED"}]
        self.assertEqual(collector.pick_pr(prs)["number"], 3)

    def test_prefers_open_over_closed(self):
        prs = [{"number": 1, "state": "CLOSED"}, {"number": 2, "state": "OPEN"}]
        self.assertEqual(collector.pick_pr(prs)["number"], 2)


class WorktreeParseTests(unittest.TestCase):
    def test_parses_paths_branches_and_detached(self):
        porcelain = (
            "worktree /ws/proj\nHEAD abc\nbranch refs/heads/main\n\n"
            "worktree /ws/proj-feature\nHEAD def\nbranch refs/heads/build-feature\n\n"
            "worktree /ws/proj-detached\nHEAD 999\ndetached\n"
        )
        entries = collector.parse_worktree_porcelain(porcelain)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["branch"], "main")
        self.assertEqual(entries[1]["branch"], "build-feature")
        self.assertEqual(entries[2]["branch"], "(detached)")


class IsMergedSquashTests(unittest.TestCase):
    """AC1: squash-merge-aware merged check preserved.

    Builds a real local 'origin' where a feature branch was SQUASH-merged into
    main (so its commit SHA differs but its patch is upstream). git cherry must
    still report it merged.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.origin = root / "origin.git"
        self.work = root / "work"
        _git(root, "init", "--bare", str(self.origin))
        _git(root, "clone", str(self.origin), str(self.work))
        env = ["-c", "user.email=t@t", "-c", "user.name=t"]
        # main: initial commit
        (self.work / "a.txt").write_text("a\n")
        _git(self.work, "add", "a.txt")
        _git(self.work, *env, "commit", "-m", "init")
        _git(self.work, "branch", "-M", "main")
        _git(self.work, "push", "origin", "main")
        # feature branch with one change
        _git(self.work, "checkout", "-b", "build-feature")
        (self.work / "b.txt").write_text("b\n")
        _git(self.work, "add", "b.txt")
        _git(self.work, *env, "commit", "-m", "feature change")
        _git(self.work, "push", "origin", "build-feature")
        # squash-merge feature into main (new SHA, same patch)
        _git(self.work, "checkout", "main")
        _git(self.work, "merge", "--squash", "build-feature")
        _git(self.work, *env, "commit", "-m", "squashed feature")
        _git(self.work, "push", "origin", "main")
        _git(self.work, "fetch", "origin")

    def tearDown(self):
        self.tmp.cleanup()

    def test_squash_merged_branch_detected_as_merged(self):
        self.assertTrue(collector.is_merged(self.work, "build-feature", "main"))

    def test_unmerged_branch_not_merged(self):
        _git(self.work, "checkout", "-b", "build-unmerged")
        (self.work / "c.txt").write_text("c\n")
        _git(self.work, "add", "c.txt")
        _git(self.work, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-m", "unmerged change")
        self.assertFalse(collector.is_merged(self.work, "build-unmerged", "main"))


class ListReposParseTests(unittest.TestCase):
    """AC3: GitHubForge.list_repos parses the forge response (stubbed run)."""

    def test_parses_name_with_owner(self):
        orig = collector.run
        collector.run = lambda *a, **k: (0, json.dumps(
            [{"nameWithOwner": "Jwrobes-Magic/claw-playbook"},
             {"nameWithOwner": "Jwrobes-Magic/magic-me-workbench"}]))
        try:
            repos = collector.GitHubForge().list_repos({"forge_org": "Jwrobes-Magic"})
        finally:
            collector.run = orig
        self.assertEqual(repos, ["Jwrobes-Magic/claw-playbook",
                                 "Jwrobes-Magic/magic-me-workbench"])

    def test_returns_empty_on_error(self):
        orig = collector.run
        collector.run = lambda *a, **k: (1, "boom")
        try:
            self.assertEqual(collector.GitHubForge().list_repos({"forge_org": "x"}), [])
        finally:
            collector.run = orig


class FlagEngineTests(unittest.TestCase):
    """AC1: flag fidelity — a squash-merged worktree yields merged==True and
    the `merged-but-not-removed` flag. Exercises the engine end to end, not
    just is_merged() in isolation."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ws = root / "workspace"
        self.ws.mkdir(parents=True)
        repo = self.ws / "demo"
        origin = root / "demo.git"
        env = ["-c", "user.email=t@t", "-c", "user.name=t"]
        _git(root, "init", "--bare", str(origin))
        _git(root, "clone", str(origin), str(repo))
        (repo / "a.txt").write_text("a\n")
        _git(repo, "add", "a.txt")
        _git(repo, *env, "commit", "-m", "init")
        _git(repo, "branch", "-M", "main")
        _git(repo, "push", "origin", "main")
        # feature branch, then squash-merge into main
        _git(repo, "checkout", "-b", "build-feature")
        (repo / "b.txt").write_text("b\n")
        _git(repo, "add", "b.txt")
        _git(repo, *env, "commit", "-m", "feature")
        _git(repo, "checkout", "main")
        _git(repo, "merge", "--squash", "build-feature")
        _git(repo, *env, "commit", "-m", "squashed")
        _git(repo, "push", "origin", "main")
        _git(repo, "fetch", "origin")
        # a worktree still checked out on the merged branch
        _git(repo, "worktree", "add", str(self.ws / "demo-feature"), "build-feature")
        self.repo = repo
        self.out = root / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def test_merged_worktree_flagged(self):
        import sys
        old = sys.argv
        sys.argv = ["collector.py", "--no-gh", "--workspace", str(self.ws),
                    "--out", str(self.out)]
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(collector.main(), 0)
        finally:
            sys.argv = old
        status = json.loads((self.out / "status.json").read_text())
        feat = [r for r in status["worktrees"] if r["branch"] == "build-feature"]
        self.assertEqual(len(feat), 1, "expected the merged worktree row")
        self.assertIs(feat[0]["merged"], True)
        self.assertIn("merged-but-not-removed", feat[0]["flags"])
        # F5 guard: pairing flag suppressed while initiatives is empty
        self.assertNotIn("no-workbench-pair", feat[0]["flags"])


class ConfigErrorTests(unittest.TestCase):
    """F2: malformed/missing config yields a clean error, not a traceback."""

    def test_missing_config_raises_config_error(self):
        with self.assertRaises(collector.ConfigError):
            collector.load_config("/nonexistent/fleet.config.json")

    def test_malformed_config_raises_config_error(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{not json")
            name = f.name
        try:
            with self.assertRaises(collector.ConfigError):
                collector.load_config(name)
        finally:
            os.unlink(name)


class FrontmatterTests(unittest.TestCase):
    """Leaf 2: frontmatter title parsed when present; filename fallback."""

    def test_title_from_frontmatter(self):
        text = "---\ntitle: Ship the thing\nstatus: wip\n---\n\nbody\n"
        self.assertEqual(collector.parse_frontmatter_title(text), "Ship the thing")

    def test_quoted_title(self):
        self.assertEqual(
            collector.parse_frontmatter_title('---\ntitle: "Quoted: Title"\n---\n'),
            "Quoted: Title")

    def test_asymmetric_quote_not_stripped(self):
        # only a matched quote pair is stripped — a trailing inline quote stays
        self.assertEqual(
            collector.parse_frontmatter_title('---\ntitle: She said "hi"\n---\n'),
            'She said "hi"')

    def test_no_frontmatter_returns_none(self):
        self.assertIsNone(collector.parse_frontmatter_title("# Just a heading\n"))

    def test_frontmatter_without_title_returns_none(self):
        self.assertIsNone(collector.parse_frontmatter_title("---\nstatus: x\n---\n"))


class CollectKanbanTests(unittest.TestCase):
    """Leaf 2: collect_kanban() returns product- AND repo-level cards with
    status from the column dir; columns/paths from config; title fallback."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ws = root / "workspace"
        self.ws.mkdir(parents=True)
        self.cfg = {
            "forge": "github",
            "workspace_root": str(self.ws),
            "repo_plans_path": "plans",
            "plan_columns": ["active", "backlog", "completed", "done"],
            "products": [{
                "id": "magic-me", "name": "Magic Me", "forge_org": "Jwrobes-Magic",
                "coordinator_repo": "Jwrobes-Magic/magic-me-workbench",
                "coordinator_plans_path": "workbench/plans",
            }],
        }
        # product-level coordinator plans
        coord = self.ws / "magic-me-workbench" / "workbench" / "plans"
        (coord / "active").mkdir(parents=True)
        (coord / "active" / "launch.md").write_text("---\ntitle: Launch Magic Me\n---\nx\n")
        (coord / "done").mkdir(parents=True)
        (coord / "done" / "kickoff.md").write_text("kickoff body, no frontmatter\n")
        self._init_clone(self.ws / "magic-me-workbench", "Jwrobes-Magic/magic-me-workbench")
        # repo-level plans in a member clone
        member = self.ws / "claw-playbook"
        self._init_clone(member, "Jwrobes-Magic/claw-playbook")
        rp = member / "plans"
        (rp / "backlog").mkdir(parents=True)
        (rp / "backlog" / "retries.md").write_text("---\ntitle: Add retries\n---\n")
        (rp / "completed").mkdir(parents=True)
        (rp / "completed" / "auth.md").write_text("no frontmatter\n")

    def tearDown(self):
        self.tmp.cleanup()

    def _init_clone(self, path, slug):
        path.mkdir(parents=True, exist_ok=True)
        _git(path, "init")
        _git(path, "remote", "add", "origin", f"https://github.com/{slug}.git")

    def _cards(self):
        return collector.collect_kanban(self.cfg, self.ws)

    def test_product_level_cards(self):
        cards = self._cards()
        prod = [c for c in cards if c["level"] == "product"]
        titles = {c["title"]: c for c in prod}
        self.assertIn("Launch Magic Me", titles)
        self.assertEqual(titles["Launch Magic Me"]["status"], "active")
        self.assertEqual(titles["Launch Magic Me"]["product"], "magic-me")
        # filename fallback + 'done' column honored
        self.assertIn("kickoff", titles)
        self.assertEqual(titles["kickoff"]["status"], "done")

    def test_repo_level_cards(self):
        cards = self._cards()
        repo = [c for c in cards if c["level"] == "repo"]
        by_title = {c["title"]: c for c in repo}
        self.assertEqual(by_title["Add retries"]["status"], "backlog")
        self.assertEqual(by_title["Add retries"]["repo"], "claw-playbook")
        self.assertEqual(by_title["Add retries"]["product"], "magic-me")  # org match
        # 'completed' column accepted alongside 'done'
        self.assertEqual(by_title["auth"]["status"], "completed")

    def test_columns_come_from_config(self):
        # a column not in config is ignored
        stray = self.ws / "claw-playbook" / "plans" / "icebox"
        stray.mkdir(parents=True)
        (stray / "later.md").write_text("---\ntitle: Later\n---\n")
        titles = {c["title"] for c in self._cards()}
        self.assertNotIn("Later", titles)


class KanbanForgeReadTests(unittest.TestCase):
    """Leaf 2: forge-only Kanban read goes through Forge.read_dir/get_file."""

    def test_via_forge_stubbed(self):
        class FakeForge(collector.Forge):
            def list_repos(self, product): return []
            def list_prs(self, repo_slug, branch=None): return []
            def read_dir(self, repo_slug, path):
                if path == "workbench/plans/active":
                    return [{"name": "go.md", "path": "workbench/plans/active/go.md",
                             "type": "file"}]
                return []
            def get_file(self, repo_slug, path):
                return "---\ntitle: Go Live\n---\n"
        cards = collector._kanban_via_forge(
            FakeForge(), "Jwrobes-Magic/magic-me-workbench", "workbench/plans",
            ["active", "done"], "product", "magic-me", None)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["title"], "Go Live")
        self.assertEqual(cards[0]["status"], "active")

    def test_collect_kanban_use_forge_through_public_entry(self):
        # Drives the forge path end to end via collect_kanban(use_forge=True),
        # incl. an entry missing 'path' (must be skipped, not KeyError).
        class FakeForge(collector.Forge):
            def list_repos(self, product): return []
            def list_prs(self, repo_slug, branch=None): return []
            def read_dir(self, repo_slug, path):
                if path == "workbench/plans/active":
                    return [{"name": "go.md", "path": "workbench/plans/active/go.md"},
                            {"name": "broken.md"}]  # no 'path' → skipped
                return []
            def get_file(self, repo_slug, path):
                return "---\ntitle: Go Live\n---\n"
        cfg = {
            "plan_columns": ["active", "done"], "repo_plans_path": "plans",
            "products": [{"id": "magic-me", "forge_org": "Jwrobes-Magic",
                          "coordinator_repo": "Jwrobes-Magic/magic-me-workbench",
                          "coordinator_plans_path": "workbench/plans"}],
        }
        cards = collector.collect_kanban(cfg, "/unused", forge=FakeForge(), use_forge=True)
        self.assertEqual([c["title"] for c in cards], ["Go Live"])
        self.assertEqual(cards[0]["level"], "product")

    def test_gitlab_kanban_methods_stubbed(self):
        gl = collector.GitLabForge()
        with self.assertRaises(NotImplementedError):
            gl.read_dir("g/r", "p")
        with self.assertRaises(NotImplementedError):
            gl.get_file("g/r", "p")


class ProductTreeTests(unittest.TestCase):
    """Leaf 3: group product->repo->worktree; unaffiliated bucket; coordinator
    is product-level, not a sub-repo card; member repos from Forge.list_repos."""

    CFG = {
        "products": [{
            "id": "magic-me", "name": "Magic Me", "forge_org": "Jwrobes-Magic",
            "coordinator_repo": "Jwrobes-Magic/magic-me-workbench",
        }],
    }

    def _clone(self, name, org, worktrees=()):
        slug = f"{org}/{name}" if org else None
        return {"name": name, "slug": slug,
                "org": (org.lower() if org else None),
                "worktrees": list(worktrees)}

    def test_groups_clone_under_matching_product(self):
        clones = [self._clone("claw-playbook", "Jwrobes-Magic",
                              [{"branch": "build-x"}])]
        products, unaff = collector.build_product_tree(self.CFG, clones)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["id"], "magic-me")
        names = [r["name"] for r in products[0]["repos"]]
        self.assertEqual(names, ["claw-playbook"])
        self.assertEqual(products[0]["repos"][0]["worktrees"], [{"branch": "build-x"}])
        self.assertEqual(unaff, [])

    def test_loose_repo_goes_to_unaffiliated(self):
        clones = [self._clone("random-tool", "SomeoneElse")]
        products, unaff = collector.build_product_tree(self.CFG, clones)
        self.assertEqual(products[0]["repos"], [])
        self.assertEqual([r["name"] for r in unaff], ["random-tool"])

    def test_coordinator_not_listed_as_repo(self):
        clones = [self._clone("magic-me-workbench", "Jwrobes-Magic")]
        products, unaff = collector.build_product_tree(self.CFG, clones)
        self.assertEqual(products[0]["repos"], [])   # coordinator excluded
        self.assertEqual(unaff, [])                   # but still claimed, not loose

    def test_forge_member_repos_unioned(self):
        # An org repo with no local clone still appears (worktree layer empty).
        class FakeForge(collector.Forge):
            def list_repos(self, product):
                return ["Jwrobes-Magic/api-only-repo",
                        "Jwrobes-Magic/magic-me-workbench"]  # coordinator filtered
            def list_prs(self, s, branch=None): return []
            def read_dir(self, s, p): return []
            def get_file(self, s, p): return None
        products, _ = collector.build_product_tree(
            self.CFG, [], forge=FakeForge(), allow_forge=True)
        names = [r["name"] for r in products[0]["repos"]]
        self.assertEqual(names, ["api-only-repo"])

    def test_forge_member_and_local_clone_dedup(self):
        # same repo from forge AND a local clone => one node, worktrees attached
        class FakeForge(collector.Forge):
            def list_repos(self, product):
                return ["Jwrobes-Magic/claw-playbook"]
            def list_prs(self, s, branch=None): return []
            def read_dir(self, s, p): return []
            def get_file(self, s, p): return None
        clones = [self._clone("claw-playbook", "Jwrobes-Magic", [{"branch": "build-x"}])]
        products, unaff = collector.build_product_tree(
            self.CFG, clones, forge=FakeForge(), allow_forge=True)
        repos = products[0]["repos"]
        self.assertEqual([r["name"] for r in repos], ["claw-playbook"])  # not duplicated
        self.assertEqual(repos[0]["worktrees"], [{"branch": "build-x"}])
        self.assertEqual(unaff, [])

    def test_product_without_id_does_not_crash(self):
        cfg = {"products": [{"forge_org": "Jwrobes-Magic", "name": "Magic Me"}]}
        products, _ = collector.build_product_tree(cfg, [])
        self.assertEqual(products[0]["id"], "Jwrobes-Magic")  # falls back to org

    def test_forge_not_called_when_disallowed(self):
        class BoomForge(collector.Forge):
            def list_repos(self, product): raise AssertionError("should not be called")
            def list_prs(self, s, branch=None): return []
            def read_dir(self, s, p): return []
            def get_file(self, s, p): return None
        products, _ = collector.build_product_tree(
            self.CFG, [], forge=BoomForge(), allow_forge=False)
        self.assertEqual(products[0]["repos"], [])

    # --- member_repos is the AUTHORITATIVE whitelist (no forge-org union) ---
    WL_CFG = {
        "products": [{
            "id": "magic-me", "name": "Magic Me", "forge_org": "Jwrobes-Magic",
            "coordinator_repo": "Jwrobes-Magic/magic-me-workbench",
            "member_repos": ["Jwrobes-Magic/claw-playbook", "jwrobes/wizard"],
        }],
    }

    def test_whitelist_ignores_forge_org_members(self):
        # When member_repos is set, Forge.list_repos() org members must NOT leak
        # in (e.g. an unrelated org repo or the coordinator clone).
        class FakeForge(collector.Forge):
            def list_repos(self, product):
                return ["Jwrobes-Magic/improve_ai_dev_workspace",
                        "Jwrobes-Magic/some-other-repo"]
            def list_prs(self, s, branch=None): return []
            def read_dir(self, s, p): return []
            def get_file(self, s, p): return None
        products, _ = collector.build_product_tree(
            self.WL_CFG, [], forge=FakeForge(), allow_forge=True)
        names = sorted(r["name"] for r in products[0]["repos"])
        self.assertEqual(names, ["claw-playbook", "wizard"])  # exactly the whitelist

    def test_whitelist_dedups_repo_by_name_across_slugs(self):
        # `jwrobes/wizard` (whitelisted) and a local clone `Jwrobes-Magic/wizard`
        # are the same repo NAME -> one card, not two.
        clones = [self._clone("wizard", "Jwrobes-Magic", [{"branch": "build-w"}]),
                  self._clone("claw-playbook", "Jwrobes-Magic")]
        products, unaff = collector.build_product_tree(self.WL_CFG, clones)
        names = sorted(r["name"] for r in products[0]["repos"])
        self.assertEqual(names, ["claw-playbook", "wizard"])  # wizard once
        wiz = [r for r in products[0]["repos"] if r["name"] == "wizard"][0]
        self.assertEqual(wiz["worktrees"], [{"branch": "build-w"}])  # local worktrees kept
        self.assertEqual(unaff, [])


class ProductTreeE2ETests(unittest.TestCase):
    """Leaf 3 AC: works for Magic Me end to end (local, --no-gh)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "workspace"
        self.ws.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _clone(self, name, slug):
        origin = Path(self.tmp.name) / f"{name}.git"
        repo = self.ws / name
        _git(Path(self.tmp.name), "init", "--bare", str(origin))
        _git(Path(self.tmp.name), "clone", str(origin), str(repo))
        _git(repo, "remote", "set-url", "origin", f"https://github.com/{slug}.git")
        (repo / "f.txt").write_text("x\n")
        _git(repo, "add", "f.txt")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init")
        _git(repo, "branch", "-M", "main")
        return repo

    def test_magic_me_end_to_end(self):
        self._clone("claw-playbook", "Jwrobes-Magic/claw-playbook")
        self._clone("speak-to-code", "jwrobes/speak-to-code")  # loose
        cfg = {
            "forge": "github", "workspace_root": str(self.ws),
            "repo_plans_path": "plans", "plan_columns": ["active"],
            "products": [{"id": "magic-me", "name": "Magic Me",
                          "forge_org": "Jwrobes-Magic",
                          "coordinator_repo": "Jwrobes-Magic/magic-me-workbench"}],
        }
        cfg_path = Path(self.tmp.name) / "fleet.config.json"
        cfg_path.write_text(json.dumps(cfg))
        out = Path(self.tmp.name) / "out"
        import sys
        old = sys.argv
        sys.argv = ["collector.py", "--no-gh", "--config", str(cfg_path),
                    "--workspace", str(self.ws), "--out", str(out)]
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(collector.main(), 0)
        finally:
            sys.argv = old
        status = json.loads((out / "status.json").read_text())
        self.assertEqual([p["id"] for p in status["products"]], ["magic-me"])
        repos = [r["name"] for r in status["products"][0]["repos"]]
        self.assertIn("claw-playbook", repos)
        self.assertEqual([r["name"] for r in status["unaffiliated"]], ["speak-to-code"])


class RelativeWorkspaceTests(unittest.TestCase):
    """Regression: a relative --workspace must still classify a main clone as
    'clone' (git porcelain reports absolute paths; workspace_root is resolved)."""

    def test_relative_workspace_classifies_clone(self):
        import os
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        ws = root / "ws"
        ws.mkdir()
        repo, origin = ws / "demo", root / "demo.git"
        _git(root, "init", "--bare", str(origin))
        _git(root, "clone", str(origin), str(repo))
        (repo / "f.txt").write_text("x\n")
        _git(repo, "add", "f.txt")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init")
        _git(repo, "branch", "-M", "main")
        cfg = {"forge": "github", "plan_columns": [], "products": []}
        (root / "c.json").write_text(json.dumps(cfg))
        out = root / "out"
        import sys
        oldcwd, old = os.getcwd(), sys.argv
        os.chdir(root)
        sys.argv = ["collector.py", "--no-gh", "--config", "c.json",
                    "--workspace", "ws", "--out", str(out)]
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(collector.main(), 0)
        finally:
            sys.argv = old
            os.chdir(oldcwd)
        status = json.loads((out / "status.json").read_text())
        kinds = {w["branch"]: w["kind"] for w in status["worktrees"]}
        self.assertEqual(kinds.get("main"), "clone")


class LinkInferenceTests(unittest.TestCase):
    """Leaf 4: worktree<->card link inference by naming (reuse norm())."""

    def test_branch_build_slug_matches_card(self):
        rows = [{"kind": "worktree", "branch": "build-add-retries",
                 "path": "/ws/claw-add-retries", "repo": "claw"}]
        cards = [{"title": "Add retries", "status": "active", "level": "repo",
                  "repo": "claw", "path": "plans/active/add-retries.md"}]
        collector.link_worktrees_to_cards(rows, cards)
        self.assertEqual(rows[0]["card"]["title"], "Add retries")
        self.assertTrue(cards[0]["has_worktree"])

    def test_dir_repo_slug_matches_card(self):
        rows = [{"kind": "worktree", "branch": "feature",
                 "path": "/ws/claw-playbook-auth-flow", "repo": "claw-playbook"}]
        cards = [{"title": "Auth flow", "status": "backlog", "level": "repo",
                  "repo": "claw-playbook", "path": "plans/backlog/auth-flow.md"}]
        collector.link_worktrees_to_cards(rows, cards)
        self.assertEqual(rows[0]["card"]["status"], "backlog")
        self.assertTrue(cards[0]["has_worktree"])

    def test_unmatched_is_graceful_both_ways(self):
        rows = [{"kind": "worktree", "branch": "build-nothing",
                 "path": "/ws/x", "repo": "r"}]
        cards = [{"title": "Other", "status": "active", "level": "repo",
                  "repo": "r", "path": "plans/active/other.md"}]
        collector.link_worktrees_to_cards(rows, cards)
        self.assertIsNone(rows[0]["card"])          # worktree w/o card
        self.assertFalse(cards[0]["has_worktree"])  # card w/o worktree

    def test_same_stem_different_repos_scoped(self):
        # two repos each with a 'deploy' card — must not cross-link
        rows = [
            {"kind": "worktree", "branch": "build-deploy", "path": "/ws/a-deploy", "repo": "a"},
            {"kind": "worktree", "branch": "build-deploy", "path": "/ws/b-deploy", "repo": "b"},
        ]
        cards = [
            {"title": "Deploy A", "status": "active", "level": "repo", "repo": "a",
             "path": "a/plans/active/deploy.md"},
            {"title": "Deploy B", "status": "active", "level": "repo", "repo": "b",
             "path": "b/plans/active/deploy.md"},
        ]
        collector.link_worktrees_to_cards(rows, cards)
        self.assertEqual(rows[0]["card"]["title"], "Deploy A")
        self.assertEqual(rows[1]["card"]["title"], "Deploy B")
        self.assertTrue(all(c["has_worktree"] for c in cards))

    def test_clone_rows_not_linked(self):
        rows = [{"kind": "clone", "branch": "main", "path": "/ws/r", "repo": "r"}]
        cards = [{"title": "main", "status": "active", "level": "repo",
                  "path": "plans/active/main.md"}]
        collector.link_worktrees_to_cards(rows, cards)
        self.assertIsNone(rows[0]["card"])


class PairingGoalTests(unittest.TestCase):
    """Local-pairing: the worktree's card snapshot carries the card's goal so the
    worktree shows real context, not just the branch name."""

    def test_paired_card_includes_goal(self):
        rows = [{"kind": "worktree", "branch": "build-venmo",
                 "path": "/ws/claw-venmo", "repo": "claw"}]
        cards = [{"title": "Venmo", "status": "active", "level": "repo",
                  "repo": "claw", "path": "plans/active/venmo.md",
                  "goal": "Categorize Venmo exports automatically."}]
        collector.link_worktrees_to_cards(rows, cards)
        self.assertEqual(rows[0]["card"]["goal"],
                         "Categorize Venmo exports automatically.")

    def test_paired_card_goal_none_when_absent(self):
        rows = [{"kind": "worktree", "branch": "build-x",
                 "path": "/ws/r-x", "repo": "r"}]
        cards = [{"title": "X", "status": "active", "level": "repo",
                  "repo": "r", "path": "plans/active/x.md"}]  # no goal key
        collector.link_worktrees_to_cards(rows, cards)
        self.assertIsNone(rows[0]["card"]["goal"])


class WorkSubstanceTests(unittest.TestCase):
    """Local work substance: unmerged commit subjects + dirty file names.
    Builds a real git repo with a branch ahead of origin/main + dirty files."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.origin = root / "origin.git"
        self.work = root / "work"
        _git(root, "init", "--bare", str(self.origin))
        _git(root, "clone", str(self.origin), str(self.work))
        env = ["-c", "user.email=t@t", "-c", "user.name=t"]
        (self.work / "a.txt").write_text("a\n")
        _git(self.work, "add", "a.txt")
        _git(self.work, *env, "commit", "-m", "init")
        _git(self.work, "branch", "-M", "main")
        _git(self.work, "push", "origin", "main")
        # branch with two commits not on origin/main
        _git(self.work, "checkout", "-b", "build-feature")
        (self.work / "b.txt").write_text("b\n")
        _git(self.work, "add", "b.txt")
        _git(self.work, *env, "commit", "-m", "first feature commit")
        (self.work / "c.txt").write_text("c\n")
        _git(self.work, "add", "c.txt")
        _git(self.work, *env, "commit", "-m", "second feature commit")
        _git(self.work, "fetch", "origin")

    def tearDown(self):
        self.tmp.cleanup()

    def test_unmerged_subjects_lists_branch_commits(self):
        subs, total = collector.unmerged_subjects(self.work, "build-feature", "main")
        self.assertEqual(total, 2)
        self.assertEqual(set(subs),
                         {"first feature commit", "second feature commit"})

    def test_unmerged_subjects_empty_for_base_branch(self):
        subs, total = collector.unmerged_subjects(self.work, "main", "main")
        self.assertEqual((subs, total), ([], 0))

    def test_unmerged_subjects_cap(self):
        subs, total = collector.unmerged_subjects(self.work, "build-feature", "main", cap=1)
        self.assertEqual(len(subs), 1)
        self.assertEqual(total, 2)  # full count still reported for "+N more"

    def test_dirty_files_lists_names_and_total(self):
        (self.work / "dirty1.txt").write_text("x\n")
        (self.work / "dirty2.txt").write_text("y\n")
        names, total = collector.dirty_files(self.work)
        self.assertEqual(total, 2)
        self.assertEqual(set(names), {"dirty1.txt", "dirty2.txt"})

    def test_dirty_files_clean_is_empty(self):
        names, total = collector.dirty_files(self.work)
        self.assertEqual((names, total), ([], 0))


class NoLocalModeTests(unittest.TestCase):
    """Leaf 4 AC: --no-local forge-only mode (cloud-portable, no checkouts)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_make = collector.make_forge

        class FakeForge(collector.Forge):
            def list_repos(self, product):
                return ["Jwrobes-Magic/claw-playbook",
                        "Jwrobes-Magic/magic-me-workbench"]  # coordinator filtered
            def list_prs(self, slug, branch=None):
                return [{"number": 7, "state": "OPEN"}]
            def read_dir(self, slug, path):
                return [{"name": "go.md", "path": path + "/go.md"}] \
                    if path.endswith("active") else []
            def get_file(self, slug, path):
                return "---\ntitle: Go\n---\n"
        collector.make_forge = lambda name: FakeForge()

    def tearDown(self):
        collector.make_forge = self.orig_make
        self.tmp.cleanup()

    def test_forge_only_end_to_end(self):
        cfg = {
            "forge": "github", "workspace_root": str(Path(self.tmp.name) / "ws"),
            "repo_plans_path": "plans", "plan_columns": ["active"],
            "products": [{"id": "magic-me", "name": "Magic Me",
                          "forge_org": "Jwrobes-Magic",
                          "coordinator_repo": "Jwrobes-Magic/magic-me-workbench",
                          "coordinator_plans_path": "workbench/plans"}],
        }
        cfgp = Path(self.tmp.name) / "c.json"
        cfgp.write_text(json.dumps(cfg))
        out = Path(self.tmp.name) / "out"
        import sys
        old = sys.argv
        sys.argv = ["collector.py", "--no-local", "--config", str(cfgp), "--out", str(out)]
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(collector.main(), 0)
        finally:
            sys.argv = old
        status = json.loads((out / "status.json").read_text())
        self.assertEqual(status["mode"], "forge-only")
        self.assertEqual(status["worktrees"], [])  # worktree layer absent
        prod = status["products"][0]
        claw = [r for r in prod["repos"] if r["name"] == "claw-playbook"][0]
        self.assertEqual(claw["prs"], [{"number": 7, "state": "OPEN"}])  # PRs from API
        self.assertTrue(any(c["level"] == "product" for c in status["kanban"]))
        self.assertTrue(any(c["level"] == "repo" for c in status["kanban"]))


class DashboardInjectionTests(unittest.TestCase):
    """Leaf 4 security: an inlined string containing </script> must not break
    out of the dashboard's <script> element."""

    def test_script_breakout_is_escaped(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        ws = root / "ws"
        repo = ws / "claw-playbook"
        repo.mkdir(parents=True)
        _git(repo, "init")
        _git(repo, "remote", "add", "origin",
             "https://github.com/Jwrobes-Magic/claw-playbook.git")
        col = repo / "plans" / "active"
        col.mkdir(parents=True)
        (col / "x.md").write_text('---\ntitle: INJ</script><img src=x>INJ\n---\n')
        cfg = {"forge": "github", "repo_plans_path": "plans",
               "plan_columns": ["active"],
               "products": [{"id": "magic-me", "forge_org": "Jwrobes-Magic",
                             "coordinator_repo": "Jwrobes-Magic/magic-me-workbench",
                             "coordinator_plans_path": "workbench/plans"}]}
        (root / "c.json").write_text(json.dumps(cfg))
        out = root / "out"
        import sys
        old = sys.argv
        sys.argv = ["collector.py", "--no-gh", "--config", str(root / "c.json"),
                    "--workspace", str(ws), "--out", str(out)]
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(collector.main(), 0)
        finally:
            sys.argv = old
        html = (out / "dashboard.html").read_text()
        self.assertNotIn("INJ</script>", html)              # not a raw breakout
        self.assertIn("INJ\\u003c/script\\u003e", html)     # escaped instead
        self.assertEqual(html.count("</script>"), 1)        # only the real tag


class NoLocalForgeErrorTests(unittest.TestCase):
    """Leaf 4: --no-local must not crash when a forge method raises
    (e.g. GitLabForge stub) — cloud-portability must degrade gracefully."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = collector.make_forge

        class RaisingForge(collector.Forge):
            def list_repos(self, product): return ["Jwrobes-Magic/claw-playbook"]
            def list_prs(self, slug, branch=None):
                raise NotImplementedError("no PRs here")
            def read_dir(self, slug, path):
                raise NotImplementedError("no files here")
            def get_file(self, slug, path):
                raise NotImplementedError("no files here")
        collector.make_forge = lambda name: RaisingForge()

    def tearDown(self):
        collector.make_forge = self.orig
        self.tmp.cleanup()

    def test_no_local_survives_raising_forge(self):
        root = Path(self.tmp.name)
        cfg = {"forge": "github", "repo_plans_path": "plans", "plan_columns": ["active"],
               "products": [{"id": "magic-me", "forge_org": "Jwrobes-Magic",
                             "coordinator_repo": "Jwrobes-Magic/magic-me-workbench",
                             "coordinator_plans_path": "workbench/plans"}]}
        (root / "c.json").write_text(json.dumps(cfg))
        out = root / "out"
        import sys
        old = sys.argv
        sys.argv = ["collector.py", "--no-local", "--config", str(root / "c.json"),
                    "--workspace", str(root / "ws"), "--out", str(out)]
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(collector.main(), 0)  # no crash
        finally:
            sys.argv = old
        status = json.loads((out / "status.json").read_text())
        self.assertEqual(status["kanban"], [])  # reads degraded to empty
        claw = status["products"][0]["repos"][0]
        self.assertEqual(claw["prs"], [])       # PRs degraded to empty


class SmokeRunTests(unittest.TestCase):
    """AC1 + AC4: collector.py runs end to end, --no-gh works, emits artifacts."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "workspace"
        self.ws.mkdir(parents=True)
        # one real clone in the workspace so the walk has something to chew on
        repo = self.ws / "demo"
        origin = Path(self.tmp.name) / "demo.git"
        _git(Path(self.tmp.name), "init", "--bare", str(origin))
        _git(Path(self.tmp.name), "clone", str(origin), str(repo))
        (repo / "f.txt").write_text("x\n")
        _git(repo, "add", "f.txt")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init")
        _git(repo, "branch", "-M", "main")
        _git(repo, "push", "origin", "main")
        self.out = Path(self.tmp.name) / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def _main(self, argv):
        import sys
        old = sys.argv
        sys.argv = ["collector.py", *argv]
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = collector.main()
            return rc, buf.getvalue()
        finally:
            sys.argv = old

    def test_runs_no_gh_and_emits_artifacts(self):
        rc, out = self._main(["--no-gh", "--workspace", str(self.ws), "--out", str(self.out)])
        self.assertEqual(rc, 0)
        status = json.loads((self.out / "status.json").read_text())
        self.assertIn("worktrees", status)
        self.assertIn("kanban", status)
        # dashboard.html is self-contained with the grouped data inlined
        html = (self.out / "dashboard.html").read_text()
        self.assertNotIn("/*__DATA__*/null", html)
        self.assertIn("generated_at", html)
        self.assertIn("products", html)     # product->repo->worktree tree inlined
        self.assertIn("Fleet Dashboard", html)


class FolderFormPlanTests(unittest.TestCase):
    """Repo plan reader accepts a flat <slug>.md OR a folder <slug>/README.md."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name) / "plans"
        (self.base / "active").mkdir(parents=True)
        # flat file form
        (self.base / "active" / "flat-plan.md").write_text(
            "---\ntitle: Flat Plan\n---\nthe flat goal line\n")
        # folder form (slug = dir name; content from README.md)
        folder = self.base / "active" / "folder-plan"
        folder.mkdir()
        (folder / "README.md").write_text(
            "---\ntitle: Folder Plan\n---\nthe folder goal line\n")
        (folder / "diagram.txt").write_text("resource")

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_both_forms(self):
        cards = collector._kanban_local(self.base, ["active"], "repo", "p", "r")
        by = {c["title"]: c for c in cards}
        self.assertIn("Flat Plan", by)
        self.assertIn("Folder Plan", by)
        # folder-form slug is the DIR name, not 'README'
        self.assertEqual(by["Folder Plan"]["slug"], "folder-plan")
        self.assertEqual(by["Flat Plan"]["slug"], "flat-plan")
        self.assertEqual(by["Folder Plan"]["goal"], "the folder goal line")


class WorkbenchReaderTests(unittest.TestCase):
    """collect_workbench() walks <repo>_workspace/workbench/<slug>/ (active at
    root, completed/ subdir) and reads README content."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        bench = self.ws / "claw-playbook_workspace" / "workbench"
        (bench / "cot_trip_matcher").mkdir(parents=True)
        (bench / "cot_trip_matcher" / "README.md").write_text(
            "---\ntitle: COT Trip Matcher\n---\nmatch trips to receipts\n")
        (bench / "completed" / "reminder_revive").mkdir(parents=True)
        (bench / "completed" / "reminder_revive" / "README.md").write_text("done work\n")
        # a no-README folder still counts (title = dir name)
        (bench / "venmo_enrichment").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_active_and_completed(self):
        entries = collector.collect_workbench(self.ws)
        by = {e["slug"]: e for e in entries}
        self.assertEqual(by["cot_trip_matcher"]["status"], "active")
        self.assertEqual(by["cot_trip_matcher"]["repo"], "claw-playbook")
        self.assertEqual(by["cot_trip_matcher"]["title"], "COT Trip Matcher")
        self.assertTrue(by["cot_trip_matcher"]["has_readme"])
        self.assertEqual(by["reminder_revive"]["status"], "completed")
        # no-README folder: present, title falls back to dir name
        self.assertIn("venmo_enrichment", by)
        self.assertFalse(by["venmo_enrichment"]["has_readme"])


class MergeWorkbenchTests(unittest.TestCase):
    """merge_workbench_into_cards: enrich matching repo plan; surface
    workbench-only initiatives; match across _/- normalization."""

    def _plan_card(self, repo, slug, status="active"):
        c = collector._card("repo", "p", repo, status, slug, f"/plans/{slug}.md", "body")
        return c

    def test_enriches_matching_plan_normalized(self):
        # repo plan slug uses hyphens; workbench folder uses underscores
        cards = [self._plan_card("claw-playbook", "cot-trip-matcher")]
        wb = [{"repo": "claw-playbook", "slug": "cot_trip_matcher",
               "status": "active", "path": "/ws/cot_trip_matcher",
               "title": "X", "goal": None, "body": "", "has_readme": True}]
        merged = collector.merge_workbench_into_cards(cards, wb)
        self.assertEqual(len(merged), 1)  # enriched, not duplicated
        self.assertIsNotNone(merged[0]["workbench"])
        self.assertEqual(merged[0]["workbench"]["path"], "/ws/cot_trip_matcher")

    def test_workbench_only_becomes_card(self):
        cards = []
        wb = [{"repo": "ableton-mcp", "slug": "mcp_exploration",
               "status": "active", "path": "/ws/mcp_exploration",
               "title": "MCP Exploration", "goal": "g", "body": "b",
               "has_readme": True}]
        merged = collector.merge_workbench_into_cards(cards, wb)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source"], "workbench-only")
        self.assertEqual(merged[0]["title"], "MCP Exploration")
        self.assertEqual(merged[0]["repo"], "ableton-mcp")
        self.assertIsNotNone(merged[0]["workbench"])

    def test_different_repo_same_slug_not_merged(self):
        # same slug in two repos must NOT cross-merge
        cards = [self._plan_card("yogada", "homepage")]
        wb = [{"repo": "yogada-shop", "slug": "homepage", "status": "active",
               "path": "/ws/homepage", "title": "H", "goal": None,
               "body": "", "has_readme": False}]
        merged = collector.merge_workbench_into_cards(cards, wb)
        self.assertEqual(len(merged), 2)  # yogada plan + yogada-shop workbench-only


class ForgeListItemsTests(unittest.TestCase):
    """list_open_prs / list_issues parse the forge response; GitLab stub raises."""

    def test_github_list_open_prs_parses(self):
        sample = json.dumps([
            {"number": 88, "title": "Build Spec 007", "headRefName": "bosque/build-spec-007",
             "labels": [{"name": "build-spec"}], "createdAt": "2026-06-08T00:00:00Z",
             "isDraft": False, "url": "https://x/pull/88"}])
        import unittest.mock as mock
        with mock.patch.object(collector, "run", return_value=(0, sample)):
            prs = collector.GitHubForge().list_open_prs("org/repo")
        self.assertEqual(len(prs), 1)
        self.assertEqual(prs[0]["number"], 88)
        self.assertEqual(prs[0]["labels"], ["build-spec"])  # flattened from {name}
        self.assertEqual(prs[0]["headRefName"], "bosque/build-spec-007")

    def test_github_list_issues_parses(self):
        sample = json.dumps([{"number": 5, "title": "An issue", "labels": [],
                              "createdAt": "2026-06-01T00:00:00Z", "url": "u"}])
        import unittest.mock as mock
        with mock.patch.object(collector, "run", return_value=(0, sample)):
            iss = collector.GitHubForge().list_issues("org/repo")
        self.assertEqual(iss[0]["number"], 5)

    def test_github_list_open_prs_no_slug(self):
        self.assertEqual(collector.GitHubForge().list_open_prs(None), [])

    def test_gitlab_stub_raises(self):
        with self.assertRaises(NotImplementedError):
            collector.GitLabForge().list_open_prs("g/r")
        with self.assertRaises(NotImplementedError):
            collector.GitLabForge().list_issues("g/r")

    def test_base_forge_defaults_empty(self):
        # A Forge subclass that doesn't override gets safe [] defaults.
        class Bare(collector.Forge):
            def list_repos(self, p): return []
            def list_prs(self, s, branch=None): return []
            def read_dir(self, s, p): return []
            def get_file(self, s, p): return None
        self.assertEqual(Bare().list_open_prs("r"), [])
        self.assertEqual(Bare().list_issues("r"), [])


class BranchSlugCandidateTests(unittest.TestCase):
    def test_strips_owner_and_spec_prefixes(self):
        cands = collector.branch_slug_candidates("bosque/build-spec-007")
        self.assertIn("build-spec-007", cands)
        self.assertIn("007", cands)  # build-spec- prefix stripped, then norm

    def test_underscore_normalized(self):
        cands = collector.branch_slug_candidates("feature/cot_trip_matcher")
        self.assertIn("cot-trip-matcher", cands)


class ForgeReconcileTests(unittest.TestCase):
    """4th source: GitHub items attach to a matching card, else become
    remote-only; ambiguous never false-merges; dangling-spec flagged."""

    NOW = collector.datetime.datetime(2026, 6, 23, tzinfo=collector.datetime.timezone.utc)

    def _card(self, repo, slug, title, status="active"):
        return {"level": "repo", "product": "p", "repo": repo, "status": status,
                "title": title, "path": f"/x/{slug}.md", "slug": slug,
                "goal": None, "body": "", "workbench": None}

    def _item(self, **kw):
        base = {"repo": "claw-playbook", "kind": "pr", "number": 1, "title": "T",
                "branch": "feature/x", "labels": [], "createdAt": "2026-06-01T00:00:00Z",
                "isDraft": False, "url": "u", "has_impl_pr": False}
        base.update(kw); return base

    def test_branch_slug_match_attaches(self):
        cards = [self._card("claw-playbook", "venmo-enrichment", "Venmo")]
        items = [self._item(branch="build-venmo-enrichment", number=42)]
        out = collector.merge_forge_items_into_cards(cards, items, self.NOW)
        self.assertEqual(len(out), 1)               # no new card
        self.assertEqual(out[0]["github"]["number"], 42)

    def test_title_match_attaches(self):
        cards = [self._card("claw-playbook", "x", "Cot Trip Matcher")]
        items = [self._item(title="cot trip matcher", branch=None, number=7)]
        out = collector.merge_forge_items_into_cards(cards, items, self.NOW)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["github"]["number"], 7)

    def test_no_match_becomes_remote_only_and_dangling(self):
        cards = []
        items = [self._item(branch="bosque/build-spec-007", number=88,
                            title="Build Spec 007", labels=["build-spec"],
                            createdAt="2026-06-08T00:00:00Z")]
        out = collector.merge_forge_items_into_cards(cards, items, self.NOW)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source"], "remote-only")
        self.assertIn("dangling-spec", out[0]["flags"])  # build-spec, no impl, old

    def test_ambiguous_match_does_not_false_merge(self):
        # two cards with the same title -> ambiguous -> remote-only, not attached
        cards = [self._card("claw-playbook", "a", "Same"),
                 self._card("claw-playbook", "b", "Same")]
        items = [self._item(title="same", branch=None, number=9)]
        out = collector.merge_forge_items_into_cards(cards, items, self.NOW)
        self.assertEqual(len(out), 3)               # 2 originals + 1 remote-only
        self.assertEqual(out[-1]["source"], "remote-only")

    def _product_card(self, product, slug, title):
        # A product-level plan card has NO repo (the plan lives at product level;
        # impl PRs live in a member repo). This is the canonical plan card.
        return {"level": "product", "product": product, "repo": None,
                "status": "active", "title": title, "path": f"/p/{slug}.md",
                "slug": slug, "goal": None, "body": "", "workbench": None}

    def test_member_repo_pr_attaches_to_product_level_plan(self):
        # The real bug: a product-level plan card (repo=None) and a member-repo
        # PR whose build-branch slug matches it. Must ATTACH to the plan, not
        # spawn a remote-only card ("real work buried, not under the product").
        cards = [self._product_card("magic-me", "communications-hub-morning-briefing",
                                    "Communications Hub & Morning Briefing")]
        items = [self._item(repo="claw-playbook", number=113,
                            branch="build-communications-hub-morning-briefing")]
        out = collector.merge_forge_items_into_cards(
            cards, items, self.NOW, repo_to_product={"claw-playbook": "magic-me"})
        self.assertEqual(len(out), 1)                  # no new card — attached
        self.assertEqual(out[0]["level"], "product")
        self.assertEqual(out[0]["github"]["number"], 113)

    def test_member_repo_pr_attaches_to_product_plan_by_title(self):
        cards = [self._product_card("magic-me", "comm-hub", "Communications Hub")]
        items = [self._item(repo="claw-playbook", number=200, branch=None,
                            title="communications hub")]
        out = collector.merge_forge_items_into_cards(
            cards, items, self.NOW, repo_to_product={"claw-playbook": "magic-me"})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["github"]["number"], 200)

    def test_repo_level_match_wins_over_product_level(self):
        # If a repo-level card matches, prefer it (most specific) — the product
        # card is only the fallback, so we don't double-match the same item.
        cards = [self._card("claw-playbook", "feat-x", "Feat X"),
                 self._product_card("magic-me", "feat-x", "Feat X")]
        items = [self._item(repo="claw-playbook", number=5, branch="build-feat-x")]
        out = collector.merge_forge_items_into_cards(
            cards, items, self.NOW, repo_to_product={"claw-playbook": "magic-me"})
        self.assertEqual(len(out), 2)                  # no new card
        repo_card = next(c for c in out if c["level"] == "repo")
        self.assertEqual(repo_card["github"]["number"], 5)  # attached to repo card
        prod_card = next(c for c in out if c["level"] == "product")
        self.assertNotIn("github", prod_card)               # product NOT touched

    def test_product_plan_no_false_match_across_products(self):
        # A claw-playbook PR must NOT attach to a same-slug plan under a DIFFERENT
        # product. Product scoping prevents cross-product bleed.
        cards = [self._product_card("other-product", "shared-slug", "Shared")]
        items = [self._item(repo="claw-playbook", number=9, branch="build-shared-slug")]
        out = collector.merge_forge_items_into_cards(
            cards, items, self.NOW, repo_to_product={"claw-playbook": "magic-me"})
        self.assertEqual(len(out), 2)                  # original + remote-only
        self.assertEqual(out[-1]["source"], "remote-only")
        self.assertNotIn("github", cards[0])        # the cross-product plan untouched

    def test_recent_build_spec_not_dangling(self):
        cards = []
        items = [self._item(branch="bosque/build-spec-009", number=99,
                            title="Build Spec 009", labels=["build-spec"],
                            createdAt="2026-06-22T00:00:00Z")]  # 1 day old
        out = collector.merge_forge_items_into_cards(cards, items, self.NOW)
        self.assertNotIn("dangling-spec", out[0]["flags"])

    def test_build_spec_with_impl_not_dangling(self):
        cards = []
        items = [self._item(branch="bosque/build-spec-007", number=88,
                            title="Build Spec 007", labels=["build-spec"],
                            createdAt="2026-06-01T00:00:00Z", has_impl_pr=True)]
        out = collector.merge_forge_items_into_cards(cards, items, self.NOW)
        self.assertNotIn("dangling-spec", out[0]["flags"])


class ReadinessTests(unittest.TestCase):
    def test_has_issue_when_github_number(self):
        self.assertEqual(collector.card_readiness(
            {"status": "active", "github": {"number": 88}, "body": ""}), "has-issue")

    def test_specd_when_real_body_no_issue(self):
        self.assertEqual(collector.card_readiness(
            {"status": "active", "body": "x" * 250}), "specd")

    def test_idea_when_thin_body_no_issue(self):
        self.assertEqual(collector.card_readiness(
            {"status": "active", "body": "short"}), "idea")
        self.assertEqual(collector.card_readiness(
            {"status": "active", "body": ""}), "idea")

    def test_done_for_completed(self):
        self.assertEqual(collector.card_readiness(
            {"status": "completed", "body": "x" * 250}), "done")


if __name__ == "__main__":
    unittest.main(verbosity=2)
