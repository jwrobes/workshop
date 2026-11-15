#!/usr/bin/env python3
"""
tmux-cleanup.py  Execute an approved tmux-manifest.json (kill sessions).
Dry-run by default; pass --execute to apply.

Guards (re-checked live at execution, independent of the scan):
  - never kill an attached session
  - never kill a session whose name is in the protected allowlist

Usage:
    python tmux-cleanup.py            # dry-run
    python tmux-cleanup.py --execute  # kill for real
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
RUNTIME_DIR = HOME / ".config/tmux-doctor"
CONFIG_PATH = RUNTIME_DIR / "config.json"
MANIFEST = RUNTIME_DIR / "tmux-manifest.json"
LOG_MD = RUNTIME_DIR / "cleanup-log.md"
LOG_HTML = RUNTIME_DIR / "cleanup-log.html"

DEFAULT_PROTECTED = ["sct-team-reviews"]

# ─── tmux helpers ─────────────────────────────────────────────────────────────


def tmux(args):
    r = subprocess.run(["tmux", *args], capture_output=True, text=True)
    return r.stdout.strip(), r.stderr.strip(), r.returncode


def live_session_state():
    """Return {name: attached_bool} for currently running sessions."""
    out, _, rc = tmux(["list-sessions", "-F", "#{session_name}\t#{session_attached}"])
    if rc != 0:
        return {}
    state = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            state[parts[0]] = parts[1] == "1"
    return state


def load_protected():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text()).get("protected_names", DEFAULT_PROTECTED)
        except Exception:
            pass
    return DEFAULT_PROTECTED


# ─── Action ───────────────────────────────────────────────────────────────────


def kill_session(name, dry_run, live, protected):
    # Live guards — independent of what the manifest claims
    if name not in live:
        print(f"  [skip] {name}: not running (already gone)")
        return False
    if live.get(name):
        print(f"  [skip] {name}: currently ATTACHED — refusing to kill", file=sys.stderr)
        return False
    if name in protected:
        print(f"  [skip] {name}: in protected allowlist — refusing to kill", file=sys.stderr)
        return False

    if dry_run:
        print(f"  tmux kill-session -t {name}")
        return True

    _, stderr, rc = tmux(["kill-session", "-t", name])
    if rc == 0:
        print(f"  Killed {name}")
        return True
    print(f"  [error] kill-session {name} failed: {stderr}", file=sys.stderr)
    return False


# ─── Logging (mirrors workspace-cleanup.py) ───────────────────────────────────


def write_log(action_results):
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ok = sum(1 for _, done in action_results if done)
    total = len(action_results)

    lines = [f"\n## {ts} — {ok}/{total} sessions killed\n\n",
             "| # | session | reason | result |\n", "|---|---------|--------|--------|\n"]
    for i, (a, done) in enumerate(action_results, 1):
        lines.append(f"| {i} | {a.get('name','')} | {a.get('reason','')} | "
                     f"{'✓ killed' if done else '⚠ skip'} |\n")
    with open(LOG_MD, "a") as f:
        f.writelines(lines)

    _render_html()
    print(f"\nLogged to {LOG_MD}")
    print(f"HTML:      {LOG_HTML}")


def _render_html():
    entries = []
    cur = None
    if LOG_MD.exists():
        for line in LOG_MD.read_text().splitlines():
            if line.startswith("## "):
                if cur:
                    entries.append(cur)
                head = line[3:]
                cur = {"head": head, "rows": []}
            elif line.startswith("|") and cur is not None and "---" not in line and "session |" not in line:
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) >= 4:
                    cur["rows"].append(cells[:4])
        if cur:
            entries.append(cur)

    blocks = ""
    for e in reversed(entries):
        rows = "".join(
            f"<tr><td>{c[0]}</td><td>{c[1]}</td><td>{c[2]}</td>"
            f"<td class='{'ok' if '✓' in c[3] else 'skip'}'>{c[3]}</td></tr>"
            for c in e["rows"]
        )
        blocks += (f"<details><summary><strong>{e['head']}</strong></summary>"
                   f"<table><tr><th>#</th><th>session</th><th>reason</th><th>result</th></tr>"
                   f"{rows}</table></details>")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>tmux-doctor cleanup log</title><style>
 body{{font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;
   background:#0b0d13;color:#e7e9f0}}
 h1{{font-size:1.4rem}}
 details{{border:1px solid #252c3d;border-radius:6px;margin:.5rem 0;padding:.5rem 1rem;background:#141824}}
 summary{{cursor:pointer}}
 table{{border-collapse:collapse;width:100%;margin-top:.5rem;font-size:.85rem}}
 th,td{{text-align:left;padding:.3rem .6rem;border-bottom:1px solid #252c3d}}
 th{{color:#69707f;font-size:.72rem;text-transform:uppercase;letter-spacing:.1em}}
 .ok{{color:#5fd7a7}} .skip{{color:#f5c451}}
</style></head><body><h1>tmux-doctor cleanup log</h1>{blocks}</body></html>"""
    LOG_HTML.write_text(html)


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="Execute tmux-manifest.json (dry-run by default)")
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--execute", action="store_true", help="apply (default is dry-run)")
    args = ap.parse_args()

    mpath = Path(args.manifest)
    if not mpath.exists():
        print(f"Error: {mpath} not found. Run the cleanup-tmux skill to generate it.", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(mpath.read_text())
    actions = [a for a in manifest.get("actions", []) if a.get("type") == "kill_session"]
    if not actions:
        print("No kill_session actions in manifest.")
        return

    live = live_session_state()
    protected = load_protected()
    dry = not args.execute
    print(f"{'DRY-RUN' if dry else 'EXECUTING'} — {len(actions)} session(s)\n")

    results = []
    for i, a in enumerate(actions, 1):
        print(f"[{i}/{len(actions)}] {a.get('name','?')}  ({a.get('reason','')})")
        done = kill_session(a.get("name", ""), dry, live, protected)
        results.append((a, done))

    ok = sum(1 for _, d in results if d)
    print(f"\n{ok}/{len(actions)} sessions {'would be killed' if dry else 'killed'}")
    if dry:
        print("\nRun with --execute to apply.")
    else:
        write_log(results)


if __name__ == "__main__":
    main()
