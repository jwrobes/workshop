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
import re
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


# --------------------------------------------------------------------------
# Duplicate-card detection: same initiative living unmerged across sources.
#
# The collector merges cards by EXACT normalized slug. Cards that are really
# the same initiative but whose slugs differ (e.g. plan `venmo-enrichment.md`,
# workbench `venmo_enrichment/`, PR branch `bosque/...venmo...`) stay separate.
# This finds those likely-same pairs (fuzzy, within a repo, across sources) and
# proposes the slug alignment to merge them. Report-only.
# --------------------------------------------------------------------------

def _slug_norm(s):
    return re.sub(r"[-_\s]+", "-", (s or "").lower()).strip("-")


def _tokens(s):
    # word tokens from slug/title, dropping noise words that don't disambiguate.
    stop = {"the", "a", "an", "and", "or", "for", "to", "of", "plan", "spec",
            "build", "system", "v1", "v2", "v3", "2026", "bosque"}
    words = re.split(r"[-_\s:]+", (s or "").lower())
    return {w for w in words if w and w not in stop and not w.isdigit()}


def _similarity(a, b):
    """Jaccard token overlap between two card identities (slug+title)."""
    ta = _tokens(a.get("slug") or "") | _tokens(a.get("title") or "")
    tb = _tokens(b.get("slug") or "") | _tokens(b.get("title") or "")
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _source_of(c):
    return c.get("source") or "repo-plan"


def find_duplicate_cards(cards, threshold=0.5):
    """Return likely-same-initiative pairs from DIFFERENT sources in the SAME
    product/repo that did NOT auto-merge (their normalized slugs differ).
    Each pair: (a, b, score, shared_tokens). Sorted strongest-first."""
    pairs = []
    n = len(cards)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = cards[i], cards[j]
            if _source_of(a) == _source_of(b):
                continue  # same source can't be a cross-source duplicate
            # same product (and repo when both have one)
            if (a.get("product") or None) != (b.get("product") or None):
                continue
            if a.get("repo") and b.get("repo") and a.get("repo") != b.get("repo"):
                continue
            if _slug_norm(a.get("slug")) == _slug_norm(b.get("slug")):
                continue  # would have already auto-merged
            score = _similarity(a, b)
            if score >= threshold:
                shared = (_tokens(a.get("slug") or "") | _tokens(a.get("title") or "")) & \
                         (_tokens(b.get("slug") or "") | _tokens(b.get("title") or ""))
                pairs.append((a, b, round(score, 2), sorted(shared)))
    pairs.sort(key=lambda p: p[2], reverse=True)
    return pairs


def _align_suggestion(a, b):
    """Propose the concrete move to unify a pair: align the more-malleable
    source's slug to the durable repo-plan's slug. Returns a human string."""
    order = {"repo-plan": 0, "workbench-only": 1, "remote-only": 2}
    keep, change = sorted([a, b], key=lambda c: order.get(_source_of(c), 9))
    target = keep.get("slug") or _slug_norm(keep.get("title"))
    src = _source_of(change)
    if src == "workbench-only":
        return (f"rename workbench dir → '{target}' (match the repo plan slug) "
                f"so they merge   [{change.get('path')}]")
    if src == "remote-only":
        gh = change.get("github") or {}
        return (f"align PR/issue {('#'+str(gh.get('number'))) if gh.get('number') else ''} "
                f"branch/title to slug '{target}', or add a repo plan with that slug")
    return f"align slug to '{target}'"


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

    # likely-duplicate cards: same initiative unmerged across sources
    dups = find_duplicate_cards(d.get("kanban", []))

    # ---- print report ----
    print(f"\n  FLEET DOCTOR  ·  {len(wts)} worktrees  ·  generated {d.get('generated_at','?')[:16]}")
    print("  " + "-" * 60)
    print(f"  {len(reapable)} reapable   {len(stale)} stale   "
          f"{len(orphan)} orphan   {len(behind)} behind-origin   "
          f"{len(no_wt)} active-plan-without-worktree   {len(dups)} likely-duplicate")
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
    if dups:
        print("  · LIKELY THE SAME INITIATIVE (unmerged across sources) — align to merge:")
        for a, b, score, shared in dups[:15]:
            sa, sb = _source_of(a), _source_of(b)
            print(f"      [{score}] {a.get('title')[:38]!r} ({sa})")
            print(f"            ↔  {b.get('title')[:38]!r} ({sb})   shared: {', '.join(shared)}")
            print(f"            → {_align_suggestion(a, b)}")
        if len(dups) > 15:
            print(f"      … +{len(dups)-15} more pairs")
        print()

    healthy = not (reapable or stale or orphan or dups)
    print("  " + ("✓ nothing to reap; fleet is in a healthy state."
                  if healthy else "→ review the items above. Nothing was changed (report only)."))
    print()


if __name__ == "__main__":
    main()
