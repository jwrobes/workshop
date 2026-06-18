#!/usr/bin/env python3
"""Fleet collector: walk ~/workspace, gather worktree/initiative status, emit
status.json and a self-contained dashboard.html (data inlined — no CORS issues
opening from file://).

Usage:
    python3 collector.py [--out DIR] [--no-gh]

Output dir defaults to ~/workspace/.fleet/
"""

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path.home() / "workspace"
STALE_DAYS = 14


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


def last_commit_iso(path):
    code, out = git(path, "log", "-1", "--format=%cI")
    return out if code == 0 and out else None


def ahead_behind(path, branch, base):
    """Returns (ahead, behind) vs origin/<base>; (None, None) if not computable."""
    code, out = git(path, "rev-list", "--left-right", "--count",
                    f"origin/{base}...{branch}")
    if code != 0:
        return None, None
    behind, ahead = (int(x) for x in out.split())
    return ahead, behind


def is_merged(path, branch, base):
    """Merged check that survives squash merges: git cherry lines starting
    with '-' are patch-equivalent upstream; any '+' line is unmerged."""
    code, out = git(path, "rev-list", "--count", f"origin/{base}..{branch}")
    if code == 0 and out == "0":
        return True
    code, out = git(path, "cherry", f"origin/{base}", branch)
    if code != 0:
        return None
    return not any(line.startswith("+") for line in out.splitlines())


def gh_pr(slug, branch):
    if not slug:
        return None
    code, out = run(["gh", "pr", "list", "--repo", slug, "--head", branch,
                     "--state", "all", "--limit", "3",
                     "--json", "number,state,mergedAt"], timeout=20)
    if code != 0 or not out:
        return None
    try:
        prs = json.loads(out)
    except json.JSONDecodeError:
        return None
    if not prs:
        return None
    # prefer merged > open > closed
    order = {"MERGED": 0, "OPEN": 1, "CLOSED": 2}
    prs.sort(key=lambda p: order.get(p.get("state"), 3))
    return prs[0]


def norm(s):
    return re.sub(r"[-_]", "-", s.lower())


def collect_initiatives():
    """Scan *_workspace/workbench for initiative folders."""
    initiatives = []
    for ws in sorted(WORKSPACE.glob("*_workspace")):
        bench = ws / "workbench"
        if not bench.is_dir():
            continue
        for d in sorted(bench.iterdir()):
            if not d.is_dir() or d.name in ("completed", "plans", "scripts"):
                continue
            initiatives.append({"workspace": ws.name, "name": d.name,
                                "state": "active", "path": str(d)})
        comp = bench / "completed"
        if comp.is_dir():
            for d in sorted(comp.iterdir()):
                if d.is_dir():
                    initiatives.append({"workspace": ws.name, "name": d.name,
                                        "state": "completed", "path": str(d)})
    return initiatives


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(WORKSPACE / ".fleet"))
    ap.add_argument("--no-gh", action="store_true", help="skip gh PR lookups")
    args = ap.parse_args()
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.now(datetime.timezone.utc)
    initiatives = collect_initiatives()
    init_index = {}
    for ini in initiatives:
        init_index.setdefault(norm(ini["name"]), ini)

    rows = []
    seen_paths = set()
    for repo in sorted(WORKSPACE.iterdir()):
        if not (repo / ".git").is_dir():  # main clones only (worktrees have a .git *file*)
            continue
        base = default_branch(repo)
        slug = remote_slug(repo)
        code, out = git(repo, "worktree", "list", "--porcelain")
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
        for e in entries:
            path = Path(e["path"])
            if str(path) in seen_paths:
                continue
            seen_paths.add(str(path))
            kind = "clone" if path == repo else "worktree"
            branch = e.get("branch", "(unknown)")
            dirty = dirty_count(path)
            last = last_commit_iso(path) if kind == "worktree" else last_commit_iso(path)
            merged = None
            ahead = behind = None
            if base and branch not in ("(detached)", "(unknown)"):
                ahead, behind = ahead_behind(repo, branch, base)
                if kind == "worktree" and branch != base:
                    merged = is_merged(repo, branch, base)
            pr = None
            if not args.no_gh and kind == "worktree" and branch not in ("(detached)", "(unknown)") and branch != base:
                pr = gh_pr(slug, branch)

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
                if not ini:
                    flags.append("no-workbench-pair")
                if not in_workspace_dir:
                    flags.append("orphan")
            if dirty or (ahead and not pr and merged is False):
                flags.append("unprotected")
            if kind == "clone" and behind:
                flags.append("behind-origin")

            rows.append({
                "repo": repo.name, "kind": kind, "path": str(path),
                "branch": branch, "dirty_files": dirty, "last_commit": last,
                "ahead": ahead, "behind": behind, "merged": merged,
                "pr": pr,
                "initiative": ini["name"] if ini else None,
                "initiative_state": ini["state"] if ini else None,
                "flags": flags,
            })

    paired = {r["initiative"] for r in rows if r["initiative"]}
    for ini in initiatives:
        ini["has_worktree"] = ini["name"] in paired
        ini["flags"] = []
        if ini["state"] == "active" and not ini["has_worktree"]:
            ini["flags"].append("no-worktree-pair")  # may be docs-only; informational

    status = {
        "generated_at": now.isoformat(timespec="seconds"),
        "worktrees": rows,
        "initiatives": initiatives,
    }

    (out_dir / "status.json").write_text(json.dumps(status, indent=2))
    # keep dated history for diffing (phase 3)
    (out_dir / f"status-{now.date()}.json").write_text(json.dumps(status, indent=2))

    template = (Path(__file__).parent / "template.html").read_text()
    html = template.replace("/*__DATA__*/null", json.dumps(status))
    (out_dir / "dashboard.html").write_text(html)

    n_flagged = sum(1 for r in rows if r["flags"])
    print(f"{len(rows)} rows ({sum(1 for r in rows if r['kind']=='worktree')} worktrees), "
          f"{n_flagged} flagged · wrote {out_dir}/dashboard.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
