#!/usr/bin/env python3
"""
github-check.py  Layer 2: annotate scan.json with GitHub PR/issue state.
Requires the GitHub CLI (`gh`) on PATH and authenticated (`gh auth login`).

Usage:
    python github-check.py
    python github-check.py --dir /path/to/output

What it adds:
  - merged_into_main: True/False/None on every worktree entry (local git check, no API)
  - For closed issues with no PR links in the workbench README, the PRs that GitHub
    says closed the issue are fetched too (catches PRs that were never linked)

PR states are normalized to: open | merged | closed | error  (draft PRs are "open"
with draft: true). Issue states are normalized to: open | closed | error.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ─── Config ───────────────────────────────────────────────────────────────────

HOME = Path.home()
DEFAULT_DIR = Path(os.environ.get("WORKSPACE_DOCTOR_DIR", HOME / ".config/workspace-doctor"))

URL_RE = re.compile(
    r"^https://github\.com/([\w.\-]+/[\w.\-]+)/(pull|issues)/(\d+)/?$"
)
# owner/repo#123 shorthand
SLUG_REF_RE = re.compile(r"^([\w.\-]+/[\w.\-]+)#(\d+)$")

# ─── Git helpers ──────────────────────────────────────────────────────────────


def check_merged_into_main(parent_repo, head_sha):
    """Return True if head_sha is an ancestor of origin/main, False if not, None on error."""
    if not head_sha or not parent_repo:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", parent_repo, "merge-base", "--is-ancestor", head_sha, "origin/main"],
            capture_output=True,
        )
        # rc 0 = ancestor, rc 1 = not ancestor, anything else = error (e.g. no origin/main)
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        return None
    except Exception:
        return None


# ─── Parsing / state mapping ──────────────────────────────────────────────────


def parse_github_url(url):
    """
    Return (repo_slug, kind, number) or (None, None, None).
    kind is "pr" or "issue". Accepts a full https://github.com/<owner>/<repo>/{pull,issues}/<n>
    URL or an `owner/repo#n` shorthand (shorthand is treated as an issue reference).
    """
    m = URL_RE.match(url.strip())
    if m:
        return m.group(1), ("pr" if m.group(2) == "pull" else "issue"), int(m.group(3))
    m = SLUG_REF_RE.match(url.strip())
    if m:
        return m.group(1), "issue", int(m.group(2))
    return None, None, None


def map_pr_state(state, is_draft=False):
    """
    Map a gh PR state (OPEN/MERGED/CLOSED) to open|merged|closed.
    Unknown values map to "error" so the classifier treats them conservatively.
    """
    s = (state or "").upper()
    if s == "OPEN":
        return "open"
    if s == "MERGED":
        return "merged"
    if s == "CLOSED":
        return "closed"
    return "error"


def map_issue_state(state):
    s = (state or "").upper()
    if s == "OPEN":
        return "open"
    if s == "CLOSED":
        return "closed"
    return "error"


# ─── gh helpers ───────────────────────────────────────────────────────────────


def run_gh(args):
    """Run `gh <args>` and return parsed JSON. Raises RuntimeError on failure."""
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"gh exited {result.returncode}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"could not parse gh output: {e}")


def fetch_pr(repo, number):
    try:
        d = run_gh(
            ["pr", "view", str(number), "-R", repo, "--json", "state,title,url,isDraft"]
        )
        return {
            "state": map_pr_state(d.get("state")),
            "draft": bool(d.get("isDraft")),
            "title": d.get("title"),
            "web_url": d.get("url"),
        }
    except Exception as e:
        return {"state": "error", "error": str(e)}


def fetch_issue(repo, number):
    """Fetch an issue; fall back to a PR lookup when the number is actually a PR."""
    try:
        d = run_gh(["issue", "view", str(number), "-R", repo, "--json", "state,title,url"])
        return {
            "state": map_issue_state(d.get("state")),
            "title": d.get("title"),
            "web_url": d.get("url"),
        }
    except Exception as e:
        pr = fetch_pr(repo, number)
        if pr.get("state") != "error":
            return pr
        return {"state": "error", "error": str(e)}


def fetch_related_prs_for_issue(repo, number, cache):
    """
    Fetch PRs GitHub says closed this issue. Catches the case where the workbench
    README never linked the PR. Cached to avoid duplicate calls.
    """
    cache_key = f"related:{repo}#{number}"
    if cache_key in cache:
        return cache[cache_key]
    result = []
    try:
        d = run_gh(
            ["issue", "view", str(number), "-R", repo, "--json", "closedByPullRequestsReferences"]
        )
        for ref in d.get("closedByPullRequestsReferences") or []:
            url = ref.get("url")
            if not url:
                continue
            slug, kind, n = parse_github_url(url)
            if slug and kind == "pr":
                pr = fetch_pr(slug, n)
                result.append({"url": url, **pr, "source": "issue_related"})
    except Exception:
        result = []
    cache[cache_key] = result
    return result


# ─── Entry annotation ─────────────────────────────────────────────────────────


def annotate_entry(entry, pr_cache, issue_cache, related_cache):
    """Add a 'github' key to the entry with fetched PR/issue state."""
    wb = entry.get("workbench")
    if not wb:
        entry["github"] = {"prs": [], "issues": []}
        return

    prs = []
    for url in wb.get("pr_urls", []):
        if url not in pr_cache:
            repo, kind, n = parse_github_url(url)
            if repo and kind == "pr":
                print(f"  PR  {url}", file=sys.stderr)
                pr_cache[url] = fetch_pr(repo, n)
            else:
                pr_cache[url] = {"state": "error", "error": "could not parse URL"}
        prs.append({"url": url, **pr_cache[url]})

    issues = []
    for url in wb.get("issue_urls", []):
        if url not in issue_cache:
            repo, kind, n = parse_github_url(url)
            if repo and kind in ("issue", "pr"):
                print(f"  ISS {url}", file=sys.stderr)
                issue_cache[url] = fetch_issue(repo, n)
            else:
                issue_cache[url] = {"state": "error", "error": "could not parse URL"}
        issues.append({"url": url, **issue_cache[url]})

    # No PRs tracked in the workbench README: look for PRs linked to closed issues.
    if not prs:
        for iss in issues:
            if iss.get("state") == "closed":
                repo, kind, n = parse_github_url(iss["url"])
                if repo and kind == "issue":
                    print(f"  REL {iss['url']}", file=sys.stderr)
                    for rel in fetch_related_prs_for_issue(repo, n, related_cache):
                        if not any(p["url"] == rel["url"] for p in prs):
                            prs.append(rel)

    entry["github"] = {"prs": prs, "issues": issues}


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Annotate scan.json with GitHub PR/issue state -> scan-with-github.json"
    )
    parser.add_argument(
        "--dir",
        default=str(DEFAULT_DIR),
        help="Directory containing scan.json (also writes scan-with-github.json here)",
    )
    args = parser.parse_args()

    if not shutil.which("gh"):
        print(
            "Error: the GitHub CLI (`gh`) is not on PATH. Install it and run `gh auth login`.",
            file=sys.stderr,
        )
        sys.exit(1)

    work_dir = Path(args.dir)
    scan_path = work_dir / "scan.json"

    if not scan_path.exists():
        print(f"Error: {scan_path} not found. Run workspace-scan.py first.", file=sys.stderr)
        sys.exit(1)

    scan = json.loads(scan_path.read_text())
    entries = scan.get("entries", [])

    url_entries = [
        e for e in entries
        if e.get("workbench") and (
            e["workbench"].get("pr_urls") or e["workbench"].get("issue_urls")
        )
    ]
    print(
        f"Checking {len(url_entries)} entries with GitHub links "
        f"(out of {len(entries)} total)...",
        file=sys.stderr,
    )

    pr_cache = {}
    issue_cache = {}
    related_cache = {}

    for entry in entries:
        annotate_entry(entry, pr_cache, issue_cache, related_cache)

        # merged_into_main uses local git only. It reads cached remote refs; run
        # `git fetch origin main` in each repo first if they may be stale.
        wt = entry.get("worktree")
        if wt and wt.get("head") and entry.get("parent_repo"):
            wt["merged_into_main"] = check_merged_into_main(
                entry["parent_repo"], wt["head"]
            )

    out = {
        **scan,
        "github_checked_at": datetime.now(timezone.utc).isoformat(),
    }
    out_path = work_dir / "scan-with-github.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"Wrote {out_path}", file=sys.stderr)
    print(str(out_path))


if __name__ == "__main__":
    main()
