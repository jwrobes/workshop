#!/usr/bin/env python3
"""fleet-doctor — terminal health check for the fleet (report only, no execution).

Reads the latest status.json (or runs the collector first with --refresh) and
prints what needs attention: worktrees safe to reap, stale/orphan/behind, and
plan cards with no matching worktree. Copy-paste commands are suggested but
NEVER run — this is the terminal twin of the dashboard's "needs attention".

Usage:
    python3 fleet-doctor.py [--status FILE] [--refresh] [--workspace DIR]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_status(status_path, refresh, workspace):
    if refresh:
        cmd = [sys.executable, str(HERE / "collector.py"), "--no-gh",
               "--out", str(status_path.parent)]
        if workspace:
            cmd += ["--workspace", workspace]
        subprocess.run(cmd, check=True)
    if not status_path.is_file():
        sys.exit(f"no status.json at {status_path} — run with --refresh, "
                 f"or run collector.py first.")
    return json.loads(status_path.read_text())


def worktree_dirty(path):
    r = subprocess.run(["git", "-C", path, "status", "--porcelain"],
                       capture_output=True, text=True)
    return r.returncode == 0 and bool(r.stdout.strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--status", default=str(Path.home() / ".fleet" / "status.json"))
    ap.add_argument("--refresh", action="store_true",
                    help="run the collector (--no-gh) before checking")
    ap.add_argument("--workspace", default=None)
    args = ap.parse_args()

    d = load_status(Path(args.status).expanduser(), args.refresh, args.workspace)
    wts = [w for w in d.get("worktrees", []) if w.get("kind") == "worktree"]

    # categorize
    reapable, reap_dirty, stale, orphan, behind = [], [], [], [], []
    for w in wts:
        flags = w.get("flags", [])
        if "merged-but-not-removed" in flags:
            (reap_dirty if worktree_dirty(w["path"]) else reapable).append(w)
        if "stale" in flags:
            stale.append(w)
        if "orphan" in flags:
            orphan.append(w)
        if "behind-origin" in flags:
            behind.append(w)

    # plan cards with no worktree (in-flight cards that aren't being worked)
    no_wt = [c for c in d.get("kanban", [])
             if c.get("status") in ("active",) and not c.get("has_worktree")]

    # ---- print report ----
    print(f"\n  FLEET DOCTOR  ·  {len(wts)} worktrees  ·  generated {d.get('generated_at','?')[:16]}")
    print("  " + "-" * 60)
    print(f"  {len(reapable)} reapable   {len(stale)} stale   "
          f"{len(orphan)} orphan   {len(behind)} behind-origin   "
          f"{len(no_wt)} active-plan-without-worktree")
    print()

    if reapable:
        print("  ✓ SAFE TO REAP (merged + clean) — copy-paste:")
        for w in reapable:
            # derive the main clone dir from the worktree's repo name
            print(f"      git -C ~/workspace/{w['repo']} worktree remove {w['path']}")
        print()
    if reap_dirty:
        print("  ⚠ MERGED BUT DIRTY (do NOT reap — has uncommitted changes):")
        for w in reap_dirty:
            print(f"      {w['branch']}  →  {w['path']}")
        print()
    if stale:
        print("  · STALE (>14d, unmerged) — review:")
        for w in stale:
            print(f"      {w['branch']}  ({w['repo']})")
        print()
    if orphan:
        print("  · ORPHAN (no upstream/PR) — review:")
        for w in orphan:
            print(f"      {w['branch']}  ({w['repo']})")
        print()
    if no_wt:
        print("  · ACTIVE PLANS WITHOUT A LOCAL WORKTREE (cloud work, or not started):")
        for c in no_wt[:12]:
            print(f"      {c['title']}  ({c.get('repo') or c.get('product')})")
        if len(no_wt) > 12:
            print(f"      … +{len(no_wt)-12} more")
        print()

    healthy = not (reapable or stale or orphan)
    print("  " + ("✓ nothing to reap; fleet is in a healthy state."
                  if healthy else "→ review the items above. Nothing was changed (report only)."))
    print()


if __name__ == "__main__":
    main()
