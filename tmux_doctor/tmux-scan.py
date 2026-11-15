#!/usr/bin/env python3
"""
tmux-scan.py  Layer 1: enumerate tmux sessions, resolve their working dirs to
workspace-lifecycle roles, and classify each session. No kills, no side effects
beyond writing scan.json.

Sibling of workspace-doctor: consumes its scan.json (if present) for the
authoritative set of live worktrees — a tmux session tied only to archived or
removed workspaces is a cleanup candidate; one still sitting in a live worktree
is kept.

Usage:
    python tmux-scan.py            # write ~/.config/tmux-doctor/scan.json
    python tmux-scan.py --list     # print the grouped keep/kill table, no writes
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
RUNTIME_DIR = HOME / ".config/tmux-doctor"
CONFIG_PATH = RUNTIME_DIR / "config.json"
WORKSPACE_DOCTOR_SCAN = HOME / ".config/workspace-doctor/scan.json"

DEFAULT_CONFIG = {
    "workspace_root": str(HOME / "workspace"),
    "protected_names": [],
    "protected_path_roots": [
        str(HOME / "personal"),
    ],
    "activity_grace_days": None,
}

# keep = kept; kill = cleanup candidate; review = surface, don't auto-touch
ACTION = {
    "attached": "keep",
    "protected-name": "keep",
    "protected-path": "keep",
    "active-work": "keep",
    "archived-linked": "kill",
    "generic": "kill",
    "unclear": "review",
}
CLASS_ORDER = ["attached", "protected-name", "protected-path", "active-work",
               "archived-linked", "generic", "unclear"]

# ─── Config ─────────────────────────────────────────────────────────────────


def expand(p):
    return str(Path(os.path.expanduser(p)).resolve()) if p else p


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text()))
        except Exception as e:
            print(f"Warning: bad config {CONFIG_PATH} ({e}); using defaults", file=sys.stderr)
    cfg["workspace_root"] = expand(cfg["workspace_root"])
    cfg["protected_path_roots"] = [expand(r) for r in cfg.get("protected_path_roots", [])]
    return cfg


# ─── tmux enumeration ─────────────────────────────────────────────────────────


def tmux(args):
    r = subprocess.run(["tmux", *args], capture_output=True, text=True)
    return r.stdout, r.returncode


def list_sessions():
    fmt = "#{session_name}\t#{session_created}\t#{session_attached}\t#{session_windows}\t#{session_activity}"
    out, rc = tmux(["list-sessions", "-F", fmt])
    if rc != 0:
        return None  # no server / no sessions
    sessions = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        name, created, attached, windows, activity = parts[:5]
        sessions[name] = {
            "name": name,
            "created": int(created) if created.isdigit() else None,
            "attached": attached == "1",
            "windows": int(windows) if windows.isdigit() else None,
            "activity": int(activity) if activity.isdigit() else None,
            "panes": [],
        }
    return sessions


def attach_panes(sessions):
    fmt = "#{session_name}\t#{window_index}\t#{pane_index}\t#{pane_current_path}"
    out, rc = tmux(["list-panes", "-a", "-F", fmt])
    if rc != 0:
        return
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        name, wi, pi, path = parts[0], parts[1], parts[2], parts[3]
        if name in sessions:
            sessions[name]["panes"].append({
                "w": int(wi) if wi.isdigit() else 0,
                "p": int(pi) if pi.isdigit() else 0,
                "path": path,
            })


# ─── Path role resolution ─────────────────────────────────────────────────────


def load_live_worktrees(cfg):
    """Authoritative set of live worktree paths from workspace-doctor's scan.json."""
    live = set()
    if WORKSPACE_DOCTOR_SCAN.exists():
        try:
            scan = json.loads(WORKSPACE_DOCTOR_SCAN.read_text())
            for e in scan.get("entries", []):
                wt = e.get("worktree")
                if wt and wt.get("path") and not wt.get("prunable"):
                    live.add(os.path.realpath(wt["path"]))
        except Exception as e:
            print(f"Warning: could not read workspace-doctor scan.json ({e})", file=sys.stderr)
    return live


def role_of(path, cfg, live_worktrees):
    """Classify a single pane path into a lifecycle role."""
    if not path:
        return "home"
    rp = os.path.realpath(path)
    ws_root = cfg["workspace_root"]
    home = str(HOME)

    # protected durable roots (base-path check happens later; role is informational)
    for root in cfg["protected_path_roots"]:
        if rp == root or rp.startswith(root + os.sep):
            return "non-workspace"

    # home / workspace root with no project
    if rp == home or rp == ws_root:
        return "home"

    exists = os.path.isdir(rp)

    # archived: inside a workbench/completed or workbench/archived tree
    if "/workbench/completed/" in rp + "/" or "/workbench/archived/" in rp + "/":
        return "archived"

    if not exists:
        return "gone"

    # inside a *_workspace?
    seg = None
    parts = Path(rp).parts
    for part in parts:
        if part.endswith("_workspace"):
            seg = part
            break

    if seg:
        wsdir = os.path.join(ws_root, seg)
        # bare workspace root (~/workspace/<x>_workspace) — ambiguous, NOT a live signal
        if rp == wsdir:
            return "workspace-root"
        # authoritative live worktree
        if rp in live_worktrees:
            return "live-worktree"
        # bare workbench dir (…/workbench) with no initiative subfolder — not live
        if Path(rp).name == "workbench":
            return "workspace-root"
        # an open workbench initiative subfolder (not completed/archived — checked above)
        if "/workbench/" in rp + "/":
            return "live-workbench"
        # a worktree-looking sibling dir <repo>-<slug> that exists on disk
        if os.path.dirname(rp) == wsdir:
            return "live-worktree"
        return "live-workbench"

    # a bare parent repo (e.g. ~/workspace/my-repo) — has a .git, under workspace root
    if os.path.dirname(rp) == ws_root and os.path.isdir(os.path.join(rp, ".git")):
        return "repo"

    # anything else under workspace root
    if rp.startswith(ws_root + os.sep):
        return "repo"

    return "home"


PROJECT_ROLES = {"live-worktree", "live-workbench", "archived", "gone"}
LIVE_ROLES = {"live-worktree", "live-workbench"}


def classify(session, cfg, live_worktrees):
    name = session["name"]
    panes = session["panes"]
    # base path = min (window, pane)
    base = None
    if panes:
        base = sorted(panes, key=lambda x: (x["w"], x["p"]))[0]["path"]
    base_role = role_of(base, cfg, live_worktrees) if base else "home"

    paths = []
    seen = set()
    for pane in panes:
        if pane["path"] in seen:
            continue
        seen.add(pane["path"])
        paths.append({"path": pane["path"], "role": role_of(pane["path"], cfg, live_worktrees)})

    roles = {p["role"] for p in paths}
    project_paths = [p for p in paths if p["role"] in PROJECT_ROLES]
    has_live = any(p["role"] in LIVE_ROLES for p in paths)
    has_archived = any(p["role"] in {"archived", "gone"} for p in paths)

    reasons = []

    # 1 attached
    if session["attached"]:
        cls = "attached"; reasons.append("currently attached")
    # 2 protected name
    elif name in cfg["protected_names"]:
        cls = "protected-name"; reasons.append(f"name in protected allowlist")
    # 3 protected base path
    elif base_role == "non-workspace":
        cls = "protected-path"; reasons.append(f"base path is a durable non-workspace root: {base}")
    # 4 active work (conservative: any live path keeps it)
    elif has_live:
        cls = "active-work"
        live_ex = next(p["path"] for p in paths if p["role"] in LIVE_ROLES)
        reasons.append(f"touches a live worktree/workbench: {live_ex}")
    # 5 archived-linked
    elif has_archived and not has_live:
        cls = "archived-linked"
        ax = next(p["path"] for p in paths if p["role"] in {"archived", "gone"})
        reasons.append(f"only archived/removed project paths (e.g. {ax})")
    # 6 generic
    elif not project_paths:
        cls = "generic"; reasons.append("only home/repo paths, no project link")
    else:
        cls = "unclear"; reasons.append("could not resolve confidently")

    session["base_path"] = base
    session["base_role"] = base_role
    session["paths"] = paths
    session["classification"] = cls
    session["recommended_action"] = ACTION[cls]
    session["reasons"] = reasons
    return session


# ─── Report ─────────────────────────────────────────────────────────────────


def print_report(sessions):
    groups = {}
    for s in sessions.values():
        groups.setdefault(s["classification"], []).append(s)

    total = len(sessions)
    kill = sum(len(groups.get(c, [])) for c in groups if ACTION[c] == "kill")
    keep = sum(len(groups.get(c, [])) for c in groups if ACTION[c] == "keep")
    review = sum(len(groups.get(c, [])) for c in groups if ACTION[c] == "review")
    print(f"\n{total} sessions   keep={keep}  kill={kill}  review={review}\n")
    for c in CLASS_ORDER:
        if c not in groups:
            continue
        act = ACTION[c].upper()
        print(f"── {c}  [{act}]  ({len(groups[c])})")
        for s in sorted(groups[c], key=lambda x: x["name"]):
            att = " *attached*" if s["attached"] else ""
            print(f"   {s['name']}{att}")
            if s["reasons"]:
                print(f"       {s['reasons'][0]}")
        print()


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="Scan + classify tmux sessions (no kills)")
    ap.add_argument("--list", action="store_true", help="print grouped table and exit (no writes)")
    ap.add_argument("--out", default=str(RUNTIME_DIR / "scan.json"), help="output path for scan.json")
    args = ap.parse_args()

    cfg = load_config()
    sessions = list_sessions()
    if sessions is None:
        print("No tmux server running / no sessions.", file=sys.stderr)
        sys.exit(0)
    attach_panes(sessions)
    live = load_live_worktrees(cfg)
    print(f"Scanned {len(sessions)} sessions; {len(live)} live worktrees from workspace-doctor.",
          file=sys.stderr)

    for s in sessions.values():
        classify(s, cfg, live)

    if args.list:
        print_report(sessions)
        return

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    result = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "config": cfg,
        "live_worktree_count": len(live),
        "sessions": list(sessions.values()),
    }
    Path(args.out).write_text(json.dumps(result, indent=2))
    print_report(sessions)
    print(f"Wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
