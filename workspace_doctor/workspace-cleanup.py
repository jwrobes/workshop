#!/usr/bin/env python3
"""
workspace-cleanup.py  Execute approved cleanup-manifest.json.
Dry-run by default; pass --execute to apply changes.

Usage:
    python workspace-cleanup.py              # dry-run (shows what would happen)
    python workspace-cleanup.py --execute    # execute for real
    python workspace-cleanup.py --dir /path/to/manifest/dir --execute
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
DEFAULT_DIR = Path(os.environ.get("WORKSPACE_DOCTOR_DIR", HOME / ".config/workspace-doctor"))
LOG_DIR = DEFAULT_DIR
LOG_MD = LOG_DIR / "cleanup-log.md"
LOG_HTML = LOG_DIR / "cleanup-log.html"

# ─── Action handlers ──────────────────────────────────────────────────────────


def run_git(args):
    result = subprocess.run(args, capture_output=True, text=True)
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def action_archive_workbench(action, dry_run):
    """Move a workbench folder to workbench/completed/ or workbench/archived/."""
    src = Path(action["workbench_path"])
    workspace = Path(action["workspace_path"])
    # "completed" = PRs confirmed merged; "archived" = abandoned/never merged
    subfolder = action.get("destination", "completed")
    target_dir = workspace / "workbench" / subfolder
    dst = target_dir / src.name

    if dry_run:
        print(f"  mv  {src}")
        print(f"    → {dst}")
        return True

    if not src.exists():
        print(f"  [skip] source does not exist: {src}", file=sys.stderr)
        return False

    if dst.exists():
        print(f"  [skip] destination already exists: {dst}", file=sys.stderr)
        return False

    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    print(f"  Archived {src.name} → workbench/{subfolder}/")
    return True


def action_remove_worktree(action, dry_run):
    """Run `git worktree remove` for a worktree."""
    wt_path = action["worktree_path"]
    parent_repo = action["parent_repo"]

    if dry_run:
        print(f"  git worktree remove --force {wt_path}")
        print(f"    (repo: {Path(parent_repo).name})")
        return True

    _, stderr, rc = run_git(
        ["git", "-C", parent_repo, "worktree", "remove", "--force", wt_path]
    )
    if rc == 0:
        print(f"  Removed worktree {Path(wt_path).name}")
        return True

    print(f"  [error] git worktree remove failed: {stderr}", file=sys.stderr)
    return False


def action_remove_branch(action, dry_run):
    """Delete a local branch (merged branches only; -d not -D)."""
    branch = action["branch"]
    parent_repo = action["parent_repo"]

    if dry_run:
        print(f"  git branch -d {branch}")
        print(f"    (repo: {Path(parent_repo).name})")
        return True

    _, stderr, rc = run_git(["git", "-C", parent_repo, "branch", "-d", branch])
    if rc == 0:
        print(f"  Deleted branch {branch}")
        return True

    print(f"  [warn] git branch -d failed (may not be merged): {stderr}", file=sys.stderr)
    return False


HANDLERS = {
    "archive_workbench": action_archive_workbench,
    "remove_worktree": action_remove_worktree,
    "remove_branch": action_remove_branch,
}

# ─── Logging ──────────────────────────────────────────────────────────────────


def _html_from_entries(all_entries):
    """Render all log entries as a self-contained HTML page."""
    rows = ""
    for e in reversed(all_entries):
        rows += f"""
    <details>
      <summary><strong>{e['timestamp']}</strong> — {e['ok']}/{e['total']} actions &nbsp;
        <span class="tag">{e['manifest']}</span></summary>
      <table>
        <tr><th>#</th><th>Type</th><th>Label</th><th>Destination / Repo</th><th>Result</th></tr>
        {''.join(
            f"<tr><td>{a['n']}</td><td>{a['type']}</td><td>{a['label']}</td>"
            f"<td>{a.get('detail','')}</td>"
            f"<td class='{'ok' if a['ok'] else 'skip'}'>"
            f"{'✓' if a['ok'] else '⚠ skip'}</td></tr>"
            for a in e['actions']
        )}
      </table>
    </details>"""
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>workspace-doctor cleanup log</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.4rem; }}
  details {{ border: 1px solid #ddd; border-radius: 6px; margin: .5rem 0; padding: .5rem 1rem; }}
  summary {{ cursor: pointer; padding: .25rem 0; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: .5rem; font-size: .85rem; }}
  th, td {{ text-align: left; padding: .25rem .5rem; border-bottom: 1px solid #eee; }}
  th {{ background: #f5f5f5; }}
  .tag {{ background: #e8f0fe; color: #1a56db; border-radius: 4px; padding: 1px 6px; font-size: .8rem; }}
  .ok {{ color: #16a34a; }} .skip {{ color: #b45309; }}
</style>
</head>
<body>
<h1>workspace-doctor cleanup log</h1>
{rows}
</body>
</html>"""


def write_log(manifest_path, action_results):
    """Append this run to ~/.config/workspace-doctor/cleanup-log.md and regenerate HTML."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ok_count = sum(1 for _, ok in action_results if ok)
    total = len(action_results)
    manifest_name = Path(manifest_path).name

    # ── Markdown entry ──────────────────────────────────────────────────────
    md_lines = [f"\n## {ts} — {ok_count}/{total} actions ({manifest_name})\n\n"]
    md_lines.append("| # | type | label | detail | result |\n")
    md_lines.append("|---|------|-------|--------|--------|\n")
    for i, (action, ok) in enumerate(action_results, 1):
        kind = action.get("type", "")
        label = action.get("label", "")
        if kind == "archive_workbench":
            dest = action.get("destination", "completed")
            detail = f"→ workbench/{dest}/"
        elif kind == "remove_worktree":
            detail = Path(action.get("parent_repo", "")).name
        elif kind == "remove_branch":
            detail = action.get("branch", "")
        else:
            detail = ""
        result = "✓" if ok else "⚠ skip"
        md_lines.append(f"| {i} | {kind} | {label} | {detail} | {result} |\n")

    with open(LOG_MD, "a") as f:
        f.writelines(md_lines)

    # ── HTML (rebuild from full markdown log) ───────────────────────────────
    # Parse existing entries from markdown log for full rebuild
    all_entries = _parse_md_log(LOG_MD)
    LOG_HTML.write_text(_html_from_entries(all_entries))

    print(f"\nLogged to {LOG_MD}")
    print(f"HTML:      {LOG_HTML}")


def _parse_md_log(path):
    """Parse cleanup-log.md into a list of entry dicts for HTML rendering."""
    entries = []
    current = None
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            if current:
                entries.append(current)
            parts = line[3:].split(" — ", 1)
            current = {
                "timestamp": parts[0].strip(),
                "manifest": parts[1].split("(")[-1].rstrip(")") if "(" in parts[1] else "",
                "ok": int(parts[1].split("/")[0].split()[-1]) if "/" in parts[1] else 0,
                "total": int(parts[1].split("/")[1].split()[0]) if "/" in parts[1] else 0,
                "actions": [],
            }
        elif current and line.startswith("| ") and not line.startswith("| #") and not line.startswith("|---"):
            cols = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cols) >= 5:
                current["actions"].append({
                    "n": cols[0], "type": cols[1], "label": cols[2],
                    "detail": cols[3], "ok": cols[4] == "✓",
                })
    if current:
        entries.append(current)
    return entries

# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Execute cleanup-manifest.json (dry-run by default)"
    )
    parser.add_argument(
        "--dir",
        default=str(DEFAULT_DIR),
        help="Directory containing cleanup-manifest.json",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply changes (default is dry-run — prints what would happen)",
    )
    args = parser.parse_args()

    manifest_path = Path(args.dir) / "cleanup-manifest.json"
    if not manifest_path.exists():
        print(f"Error: {manifest_path} not found.", file=sys.stderr)
        print("Run the cleanup-workspace skill to generate it.", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text())
    actions = manifest.get("actions", [])
    dry_run = not args.execute

    if not actions:
        print("No actions in manifest.")
        return

    mode = "DRY-RUN" if dry_run else "EXECUTING"
    print(f"{mode} — {len(actions)} action(s)\n")

    ok_count = 0
    action_results = []
    for i, action in enumerate(actions, 1):
        kind = action.get("type", "unknown")
        label = action.get("label", "")
        print(f"[{i}/{len(actions)}] {kind}{' — ' + label if label else ''}")

        handler = HANDLERS.get(kind)
        if handler is None:
            print(f"  [skip] unknown action type: {kind}", file=sys.stderr)
            action_results.append((action, False))
            continue

        ok = handler(action, dry_run)
        action_results.append((action, bool(ok)))
        if ok:
            ok_count += 1

    status = "would succeed" if dry_run else "succeeded"
    print(f"\n{ok_count}/{len(actions)} actions {status}")

    if dry_run:
        print("\nRun with --execute to apply.")
    else:
        write_log(manifest_path, action_results)


if __name__ == "__main__":
    main()
