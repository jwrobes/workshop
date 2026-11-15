#!/usr/bin/env python3
"""
workspace-scan.py  Layer 1: scan workspaces, parse git state and workbench metadata.
No LLM, no API calls. Emits scan.json (default: ~/.config/workspace-doctor/scan.json).

Usage:
    python workspace-scan.py
    python workspace-scan.py --output-dir /path/to/output
    python workspace-scan.py --list-workspaces   # show discovered workspaces and exit
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ─── Config ───────────────────────────────────────────────────────────────────

HOME = Path.home()
WORKSPACE_ROOT = HOME / "workspace"
DEFAULT_OUTPUT_DIR = Path(
    os.environ.get("WORKSPACE_DOCTOR_DIR", HOME / ".config/workspace-doctor")
)

# Matches | **Key** | value | rows in markdown tables
METADATA_ROW_RE = re.compile(r"\|\s*\*\*([^*|]+)\*\*\s*\|\s*([^|]+?)\s*\|")

# Matches any GitHub pull request or issue URL in text
GITHUB_URL_RE = re.compile(
    r"https://github\.com/([\w.\-]+/[\w.\-]+)/(pull|issues)/(\d+)"
)

# Matches short-form references in prose: #988 or owner/repo#988.
# The lookbehind avoids matching inside URLs/paths; requires digits right after '#'.
SHORT_ISSUE_REF_RE = re.compile(r"(?<![\w./#!-])((?:[\w.\-]+/)+[\w.\-]+|[\w.\-]+)?#(\d{1,7})(?!\w)")

# Branch-name pattern for your own work branches vs. review branches checked out for
# someone else's pull request. Override with WORKSPACE_DOCTOR_OWN_BRANCH_RE.
OWN_BRANCH_RE = re.compile(
    os.environ.get("WORKSPACE_DOCTOR_OWN_BRANCH_RE", r"^build-"), re.IGNORECASE
)


def is_own_branch(branch):
    """True if branch matches the own-branch pattern, False if not, None if unknown."""
    if not branch:
        return None
    return bool(OWN_BRANCH_RE.match(branch))

# ─── Workspace discovery ──────────────────────────────────────────────────────


def discover_workspaces(workspace_root):
    """
    Auto-discover *_workspace/ dirs under workspace_root.
    Derives parent repo name by stripping the _workspace suffix.
    Skips entries where the parent repo directory doesn't contain a .git.
    Returns list of (workspace_path, parent_repo_path) pairs.
    """
    pairs = []
    for d in sorted(workspace_root.glob("*_workspace")):
        if not d.is_dir():
            continue
        repo_name = d.name[: -len("_workspace")]
        parent_repo = workspace_root / repo_name
        if parent_repo.is_dir() and (parent_repo / ".git").exists():
            pairs.append((d, parent_repo))
        else:
            print(f"  [skip] {d.name} — no git repo at {parent_repo}", file=sys.stderr)
    return pairs


# ─── Git helpers ──────────────────────────────────────────────────────────────


def run_git(args, cwd):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    return result.stdout.strip(), result.returncode


def parse_worktree_porcelain(output):
    """Parse `git worktree list --porcelain` into a list of dicts."""
    entries = []
    current = {}
    for line in output.splitlines():
        if line.startswith("worktree "):
            if current:
                entries.append(current)
            current = {
                "path": line[len("worktree "):],
                "branch": None,
                "head": None,
                "prunable": False,
                "locked": False,
                "detached": False,
            }
        elif line.startswith("HEAD "):
            current["head"] = line[5:]
        elif line.startswith("branch "):
            ref = line[7:]
            current["branch"] = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref
        elif line == "detached":
            current["detached"] = True
        elif line.startswith("prunable"):
            current["prunable"] = True
        elif line.startswith("locked"):
            current["locked"] = True
    if current:
        entries.append(current)
    return entries


def get_dirty_files(worktree_path):
    out, rc = run_git(["git", "status", "--porcelain"], cwd=worktree_path)
    if rc != 0 or not out:
        return []
    return [f.strip() for f in out.splitlines() if f.strip()]


def get_ahead_count(worktree_path):
    """Return (ahead_count, has_upstream). ahead_count is None if no upstream."""
    out, rc = run_git(["git", "rev-list", "--count", "@{u}..HEAD"], cwd=worktree_path)
    if rc != 0:
        return None, False
    try:
        return int(out), True
    except ValueError:
        return None, False


# ─── README parser ────────────────────────────────────────────────────────────


def expand_tilde(value):
    """Strip backticks and expand ~ in a path string."""
    value = value.strip().strip("`")
    if value.startswith("~/") or value == "~":
        return str(HOME / value[2:])
    return value


def parse_workbench_readme(readme_path):
    """
    Parse a workbench README.md.
    Returns (metadata_dict, pr_urls, issue_urls, issue_refs).
    metadata_dict: keys from | **Key** | value | rows.
    issue_refs: short-form references found in prose (#988, owner/repo#123);
                fully-qualified ones are also folded into issue_urls for Layer 2 to fetch.
    """
    try:
        text = Path(readme_path).read_text()
    except OSError:
        return {}, [], [], []

    metadata = {}
    for key, value in METADATA_ROW_RE.findall(text):
        key = key.strip()
        value = value.strip()
        # Strip markdown link syntax from value: [text](url) → url or text
        link_match = re.match(r"\[([^\]]*)\]\(([^)]+)\)", value)
        if link_match:
            metadata[key] = link_match.group(2)  # prefer URL
        else:
            metadata[key] = value

    # Extract all GitHub PR and issue URLs from full text
    pr_urls = []
    issue_urls = []
    seen = set()
    for project, kind, iid in GITHUB_URL_RE.findall(text):
        url = f"https://github.com/{project}/{kind}/{iid}"
        if url not in seen:
            seen.add(url)
            if kind == "pull":
                pr_urls.append(url)
            else:
                issue_urls.append(url)

    # Short-form references in prose that never appeared as full URLs.
    issue_refs = []
    seen_refs = set()
    seen_iids = {u.rsplit("/", 1)[-1] for u in issue_urls}
    for project_ref, iid in SHORT_ISSUE_REF_RE.findall(text):
        project_ref = project_ref or None
        key = (project_ref, iid)
        if key in seen_refs:
            continue
        seen_refs.add(key)
        # A bare #N whose iid we already have as a full issue URL is redundant.
        if project_ref is None and iid in seen_iids:
            continue
        qualified = bool(project_ref and "/" in project_ref)
        full_url = (
            f"https://github.com/{project_ref}/issues/{iid}" if qualified else None
        )
        issue_refs.append({
            "raw": f"{project_ref}#{iid}" if project_ref else f"#{iid}",
            "project_ref": project_ref,
            "iid": int(iid),
            "qualified": qualified,
            "url": full_url,
        })

    # Fold fully-qualified short refs into issue_urls so Layer 2 fetches them.
    for ref in issue_refs:
        if ref["url"] and ref["url"] not in issue_urls:
            issue_urls.append(ref["url"])

    return metadata, pr_urls, issue_urls, issue_refs


# ─── Worktree ↔ workbench matching ───────────────────────────────────────────


def normalize_name(name):
    return name.lower().replace("-", "_")


def find_workbench_for_worktree(wt, workbench_map, parent_repo_name):
    """
    Find the best-matching workbench for a worktree.
    workbench_map: {workbench_path_str: (metadata, pr_urls, issue_urls, issue_refs)}
    Returns (wb_path_str, metadata, pr_urls, issue_urls, issue_refs)
    or (None, None, None, None, None).
    """
    wt_path_str = wt["path"]

    # Primary: explicit **Worktree** field in metadata table
    for wb_path, (metadata, pr_urls, issue_urls, issue_refs) in workbench_map.items():
        wt_field = metadata.get("Worktree", "")
        if wt_field:
            expanded = expand_tilde(wt_field)
            if expanded == wt_path_str:
                return wb_path, metadata, pr_urls, issue_urls, issue_refs

    # Secondary: name-based matching
    wt_basename = Path(wt_path_str).name
    wt_norm = normalize_name(wt_basename)

    for wb_path, (metadata, pr_urls, issue_urls, issue_refs) in workbench_map.items():
        wb_basename = Path(wb_path).name
        wb_norm = normalize_name(wb_basename)

        # Direct normalized match (e.g., myrepo-feature-x → feature_x)
        if wt_norm == wb_norm:
            return wb_path, metadata, pr_urls, issue_urls, issue_refs

        # Strip parent repo name prefix from worktree basename and compare
        # e.g., "myrepo-fix-login-bug" → "fix_login_bug"
        prefix = normalize_name(parent_repo_name) + "_"
        if wt_norm.startswith(prefix):
            stripped = wt_norm[len(prefix):]
            if stripped == wb_norm:
                return wb_path, metadata, pr_urls, issue_urls, issue_refs

    return None, None, None, None, None


# ─── Per-workspace scan ───────────────────────────────────────────────────────


def scan_workspace(workspace_path, parent_repo):
    entries = []

    if not workspace_path.exists():
        print(f"  [skip] {workspace_path} does not exist", file=sys.stderr)
        return entries

    if not parent_repo.exists():
        print(f"  [skip] parent repo {parent_repo} does not exist", file=sys.stderr)
        return entries

    # 1. List all registered worktrees
    raw, rc = run_git(["git", "worktree", "list", "--porcelain"], cwd=parent_repo)
    if rc != 0:
        print(f"  [error] git worktree list failed for {parent_repo}", file=sys.stderr)
        return entries

    all_wts = parse_worktree_porcelain(raw)

    # Filter to worktrees inside this workspace (skip main repo entry)
    workspace_wts = [wt for wt in all_wts if Path(wt["path"]).parent == workspace_path]

    # 2. Collect workbench folders (skip 'completed' subfolder)
    workbench_dir = workspace_path / "workbench"
    workbench_map = {}

    if workbench_dir.exists():
        for item in sorted(workbench_dir.iterdir()):
            if not item.is_dir() or item.name.startswith(".") or item.name in ("completed", "archived"):
                continue
            readme = item / "README.md"
            if readme.exists():
                metadata, pr_urls, issue_urls, issue_refs = parse_workbench_readme(readme)
            else:
                metadata, pr_urls, issue_urls, issue_refs = {}, [], [], []
            workbench_map[str(item)] = (metadata, pr_urls, issue_urls, issue_refs)

    # 3. Match worktrees ↔ workbenches
    matched_wb_paths = set()

    for wt in workspace_wts:
        wb_path, metadata, pr_urls, issue_urls, issue_refs = find_workbench_for_worktree(
            wt, workbench_map, parent_repo.name
        )

        # Check git state for live (non-prunable) worktrees
        dirty_files = []
        ahead_count = None
        has_upstream = False

        wt_path_obj = Path(wt["path"])
        if not wt["prunable"] and wt_path_obj.exists():
            dirty_files = get_dirty_files(wt["path"])
            if not wt["detached"]:
                ahead_count, has_upstream = get_ahead_count(wt["path"])

        entry = {
            "workspace": str(workspace_path),
            "parent_repo": str(parent_repo),
            "worktree": {
                "path": wt["path"],
                "branch": wt["branch"],
                "head": wt["head"],
                "prunable": wt["prunable"],
                "detached": wt["detached"],
                "locked": wt["locked"],
                "dirty": len(dirty_files) > 0,
                "dirty_files": dirty_files,
                "ahead_count": ahead_count,
                "has_upstream": has_upstream,
                "is_own_branch": is_own_branch(wt["branch"]),
            },
            "workbench": None,
        }

        if wb_path:
            matched_wb_paths.add(wb_path)
            entry["workbench"] = {
                "path": wb_path,
                "readme_path": str(Path(wb_path) / "README.md"),
                "metadata": metadata,
                "pr_urls": pr_urls,
                "issue_urls": issue_urls,
                "issue_refs": issue_refs,
            }

        entries.append(entry)

    # 4. Orphan workbenches — workbench folder with no matching worktree
    for wb_path, (metadata, pr_urls, issue_urls, issue_refs) in workbench_map.items():
        if wb_path in matched_wb_paths:
            continue
        entries.append({
            "workspace": str(workspace_path),
            "parent_repo": str(parent_repo),
            "worktree": None,
            "workbench": {
                "path": wb_path,
                "readme_path": str(Path(wb_path) / "README.md"),
                "metadata": metadata,
                "pr_urls": pr_urls,
                "issue_urls": issue_urls,
                "issue_refs": issue_refs,
            },
        })

    return entries


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Scan workspaces and emit scan.json (no LLM, no API)"
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory to write scan.json (default: ~/.config/workspace-doctor/)",
    )
    parser.add_argument(
        "--workspace-root",
        default=str(WORKSPACE_ROOT),
        help="Root directory to search for *_workspace/ dirs (default: ~/workspace)",
    )
    parser.add_argument(
        "--list-workspaces",
        action="store_true",
        help="Print discovered workspace → parent-repo pairs and exit",
    )
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root)
    print(f"Discovering workspaces under {workspace_root} ...", file=sys.stderr)
    workspace_pairs = discover_workspaces(workspace_root)

    if args.list_workspaces:
        print(f"\n{'Workspace':<45}  Parent repo")
        print("-" * 75)
        for ws, repo in workspace_pairs:
            print(f"{ws.name:<45}  {repo.name}")
        print(f"\n{len(workspace_pairs)} workspace(s) found")
        return

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_entries = []

    for workspace_path, parent_repo in workspace_pairs:
        print(f"Scanning {workspace_path.name} ...", file=sys.stderr)
        entries = scan_workspace(workspace_path, parent_repo)
        all_entries.extend(entries)
        print(f"  → {len(entries)} entries", file=sys.stderr)

    result = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "workspace_root": str(workspace_root),
            "workspaces": [str(ws) for ws, _ in workspace_pairs],
            "output_dir": str(output_dir),
        },
        "entries": all_entries,
    }

    out_path = output_dir / "scan.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"Wrote {out_path} ({len(all_entries)} entries total)", file=sys.stderr)
    print(str(out_path))


if __name__ == "__main__":
    main()
