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
        self.assertIn("initiatives", status)
        # dashboard.html is self-contained with the data inlined (token replaced)
        html = (self.out / "dashboard.html").read_text()
        self.assertNotIn("/*__DATA__*/null", html)
        self.assertIn("generated_at", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
