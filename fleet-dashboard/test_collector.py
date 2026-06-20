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

    def test_forge_not_called_when_disallowed(self):
        class BoomForge(collector.Forge):
            def list_repos(self, product): raise AssertionError("should not be called")
            def list_prs(self, s, branch=None): return []
            def read_dir(self, s, p): return []
            def get_file(self, s, p): return None
        products, _ = collector.build_product_tree(
            self.CFG, [], forge=BoomForge(), allow_forge=False)
        self.assertEqual(products[0]["repos"], [])


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
        # dashboard.html is self-contained with the data inlined (token replaced)
        html = (self.out / "dashboard.html").read_text()
        self.assertNotIn("/*__DATA__*/null", html)
        self.assertIn("generated_at", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
