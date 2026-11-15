---
name: cleanup-tmux
description: Classify tmux sessions by workspace-lifecycle linkage, present a keep/kill report, write a manifest, and kill approved sessions with hard guards. Use when the user says "clean up my tmux sessions", "too many tmux sessions", "tmux is slowing my machine", "kill orphaned tmux sessions", or after a workspace-doctor run leaves sessions pointing at archived/removed worktrees.
---

# cleanup-tmux

Classify tmux sessions by workspace-lifecycle linkage, present a keep/kill report, write a manifest, and kill approved sessions — with hard guards.

## When to use

- "clean up my tmux sessions", "too many tmux sessions", "tmux is slowing my machine"
- After a `workspace-doctor` run (archived worktrees leave orphaned tmux sessions behind)

Sibling of `cleanup-workspace`. Consumes `workspace-doctor`'s `scan.json` for the authoritative live-worktree set, so run workspace-scan.py first when possible.

## How to invoke

```
/cleanup-tmux
```

## Procedure

### Step 1 — Scan

The scripts live two levels above this skill (`<workshop clone>/tmux_doctor/`). Resolve that from the
installed symlink so it works wherever the clone lives:

```bash
TMUX_DOCTOR="$(cd "$(dirname "$(readlink -f ~/.claude/skills/cleanup-tmux/SKILL.md)")/../.." && pwd)"
python3 "$TMUX_DOCTOR/tmux-scan.py"
```

This writes `~/.config/tmux-doctor/scan.json` and prints the grouped report. If a fresh `scan.json` already exists you can read it directly.

### Step 2 — Understand the classification

Each session is classified deterministically (no LLM needed). Priority order:

| Session signal | Class | Action |
|---|---|---|
| Currently attached | `attached` | **keep** |
| Name in protected allowlist (`sct-team-reviews`, …) | `protected-name` | **keep** |
| Base path in a durable non-workspace root | `protected-path` | **keep** |
| Any pane in a live worktree / open workbench initiative | `active-work` | **keep** |
| All project paths archived (`workbench/completed`, `workbench/archived`) or removed, none live | `archived-linked` | **kill** |
| Only home / repo / workspace-root paths, no project link | `generic` | **kill** |
| Anything else | `unclear` | review |

Conservative rule: **any** live worktree/open-workbench pane keeps the session, even if it also has archived paths.

### Step 3 — Present the report

Show the keep / kill / review groups from the scan, each session with the one-line reason and the path that drove it. Lead with the summary counts (`keep=N kill=N review=N`).

### Step 4 — Ask for scope

> Which sessions should I kill?
> - **archived-linked only** — sessions tied purely to completed/removed workspaces (safest)
> - **archived-linked + generic** — also clear home-only / no-project sessions
> - **select** — I'll tell you which
> - **none** — just show the report

Wait for the answer. Never proceed without it.

### Step 5 — Write the manifest

Write `~/.config/tmux-doctor/tmux-manifest.json`:

```json
{
  "generated_at": "<ISO>",
  "approved_by": "user",
  "actions": [
    {"type": "kill_session", "name": "myproject-feature-x", "reason": "archived-linked: workbench/completed/feature_x"}
  ]
}
```

Never put an `attached` or `protected-name` session in the manifest. (The executor will refuse them anyway — belt and suspenders.)

### Step 6 — Dry-run

```bash
python3 "$TMUX_DOCTOR/tmux-cleanup.py"
```

Show the output. Confirm: "Reply yes to execute, no to cancel."

### Step 7 — Execute

```bash
python3 "$TMUX_DOCTOR/tmux-cleanup.py" --execute
```

Report the result and the log path (`~/.config/tmux-doctor/cleanup-log.md` + `.html`). Surface any skipped sessions (attached/protected/already-gone) with their reasons.

## Guards (enforced by the executor, not just the skill)

- Never kills an **attached** session (re-checked live at execution).
- Never kills a **protected-name** session.
- Skips sessions already gone. Skips (never fails) rather than aborting the run.

## Edge cases

| Situation | Handling |
|---|---|
| Session touches a live worktree AND completed folders | `active-work` → keep (conservative) |
| Session attached mid-run | executor refuses the kill, logs skip |
| A keeper you want gone anyway | use **select** scope to add it explicitly |
| `workspace-doctor` scan.json missing | scan falls back to git worktree list / path existence; note reduced accuracy |
| Long-running utility you want to keep | add its name to `~/.config/tmux-doctor/config.json` `protected_names` |
