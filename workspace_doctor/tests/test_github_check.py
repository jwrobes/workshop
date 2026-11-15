"""Offline tests for github-check.py. A stub `gh` on PATH prints canned JSON."""
import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("github_check", HERE.parent / "github-check.py")
gc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gc)

STUB = """#!/usr/bin/env bash
# args: <noun> view <n> -R <repo> --json <fields>
noun="$1"; num="$3"
case "$noun:$num" in
  pr:1) echo '{"state":"MERGED","title":"Ship it","url":"https://github.com/myorg/myrepo/pull/1","isDraft":false}' ;;
  pr:2) echo '{"state":"OPEN","title":"WIP","url":"https://github.com/myorg/myrepo/pull/2","isDraft":true}' ;;
  pr:3) echo '{"state":"CLOSED","title":"Nope","url":"https://github.com/myorg/myrepo/pull/3","isDraft":false}' ;;
  issue:10) echo '{"state":"OPEN","title":"Bug","url":"https://github.com/myorg/myrepo/issues/10"}' ;;
  issue:11) echo '{"state":"CLOSED","title":"Done","url":"https://github.com/myorg/myrepo/issues/11","closedByPullRequestsReferences":[{"url":"https://github.com/myorg/myrepo/pull/1"}]}' ;;
  *) echo "not found" >&2; exit 1 ;;
esac
"""


class ParseTests(unittest.TestCase):
    def test_pr_url(self):
        self.assertEqual(
            gc.parse_github_url("https://github.com/myorg/myrepo/pull/42"),
            ("myorg/myrepo", "pr", 42),
        )

    def test_issue_url(self):
        self.assertEqual(
            gc.parse_github_url("https://github.com/my-org/my.repo/issues/7"),
            ("my-org/my.repo", "issue", 7),
        )

    def test_slug_shorthand(self):
        self.assertEqual(gc.parse_github_url("myorg/myrepo#5"), ("myorg/myrepo", "issue", 5))

    def test_rejects_other(self):
        self.assertEqual(gc.parse_github_url("https://example.com/a/b/pull/1"), (None, None, None))
        self.assertEqual(gc.parse_github_url("#12"), (None, None, None))


class StateTests(unittest.TestCase):
    def test_pr_states(self):
        self.assertEqual(gc.map_pr_state("OPEN"), "open")
        self.assertEqual(gc.map_pr_state("MERGED"), "merged")
        self.assertEqual(gc.map_pr_state("CLOSED"), "closed")
        self.assertEqual(gc.map_pr_state("weird"), "error")
        self.assertEqual(gc.map_pr_state(None), "error")

    def test_issue_states(self):
        self.assertEqual(gc.map_issue_state("open"), "open")
        self.assertEqual(gc.map_issue_state("CLOSED"), "closed")


class StubGhTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        gh = Path(self.tmp.name) / "gh"
        gh.write_text(STUB)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.old_path = os.environ["PATH"]
        os.environ["PATH"] = f"{self.tmp.name}{os.pathsep}{self.old_path}"

    def tearDown(self):
        os.environ["PATH"] = self.old_path
        self.tmp.cleanup()

    def test_fetch_pr_states(self):
        self.assertEqual(gc.fetch_pr("myorg/myrepo", 1)["state"], "merged")
        pr2 = gc.fetch_pr("myorg/myrepo", 2)
        self.assertEqual((pr2["state"], pr2["draft"]), ("open", True))
        self.assertEqual(gc.fetch_pr("myorg/myrepo", 3)["state"], "closed")
        self.assertEqual(gc.fetch_pr("myorg/myrepo", 99)["state"], "error")

    def test_fetch_issue_falls_back_to_pr(self):
        self.assertEqual(gc.fetch_issue("myorg/myrepo", 10)["state"], "open")
        self.assertEqual(gc.fetch_issue("myorg/myrepo", 1)["state"], "merged")
        self.assertEqual(gc.fetch_issue("myorg/myrepo", 99)["state"], "error")

    def test_annotate_finds_related_pr_for_closed_issue(self):
        entry = {"workbench": {
            "pr_urls": [],
            "issue_urls": ["https://github.com/myorg/myrepo/issues/11"],
        }}
        gc.annotate_entry(entry, {}, {}, {})
        self.assertEqual(entry["github"]["issues"][0]["state"], "closed")
        prs = entry["github"]["prs"]
        self.assertEqual(len(prs), 1)
        self.assertEqual((prs[0]["state"], prs[0]["source"]), ("merged", "issue_related"))

    def test_annotate_unparseable_url(self):
        entry = {"workbench": {"pr_urls": ["https://example.com/x"], "issue_urls": []}}
        gc.annotate_entry(entry, {}, {}, {})
        self.assertEqual(entry["github"]["prs"][0]["state"], "error")


if __name__ == "__main__":
    unittest.main()
