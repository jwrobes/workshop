# epic_conductor

A supervisor Claude session runs several worker sessions in parallel, one detached
tmux session per GitHub issue. Each worker runs the [`full-path-github`](../skills/full-path-github/)
skill on its issue; the supervisor (skill `conducting-epics`) spawns them, watches a
shared append-only log, and restarts workers that die or stall. It never merges anything.

(Ported from a GitLab version.)

**Status: Alpha — not exercised against live GitHub.** The helper scripts are covered by
tests that fake `gh`, `tmux` and `wsnew`. Nothing has been run end to end against a real
repo, a real `claude` worker, or the real GitHub dependency API.

## Requirements

- `gh` (GitHub CLI), authenticated (`gh auth login`)
- `tmux`, `claude` (Claude Code CLI)
- the `full-path-github` skill, installed in `~/.claude/skills/` (`../skills/install.sh full-path-github`)
- [`workspace_init`](../workspace_init/) (`wsnew`), which scaffolds each issue's workbench; its
  own requirements (target repo cloned at `~/workspace/<repo>/`) apply
- bash 3.2+, `awk`, `sed`

## Install

    ./setup.sh --dry-run     # preview
    ./setup.sh               # symlinks epic-* into ~/.local/bin, the skill into ~/.claude/skills

Idempotent. Existing different files are skipped unless `--force`. If `wsnew` is not on
`PATH`, it is linked from `../workspace_init/`. `BIN_DIR` and `SKILLS_DIR` override targets.

## Usage

In a supervisor session: "conduct epic `<name>` with these issues: ..." (skill
`conducting-epics`). Issues are `https://github.com/<owner>/<repo>/issues/<n>` or
`<owner>/<repo>#<n>`. Helpers:

    epic-spawn  <epic> <issue> [--dry-run] [--brief FILE] [--live] [--force]
    epic-adopt  <epic> <issue> <tmux-target> [--brief FILE]   # join a window you opened
    epic-status <epic>          # last event, age, tmux liveness, attempt count
    epic-check  <issue>         # read-only gh snapshot: blockers, orchestrator-blocked, PR, checks
    epic-kill   <epic> <issue> <reason...>
    epic-log    <epic> <repo>/<n> <EVENT> <message...>
    tail -f ~/.epic-conductor/<epic>/UPDATES.log

State lives under `~/.epic-conductor/` (override with `EPIC_CONDUCTOR_HOME`).

### How worker state maps to GitHub

`full-path-github` has no per-state labels. Its state is the issue (assignee, body,
comments), one optional `orchestrator-blocked` label, and the branch plus draft/ready PR.

- `BLOCKED` in the log = the skill added `orchestrator-blocked` and commented. Final for
  that attempt; the supervisor never respawns it. A human answers in the issue, then a
  new worker resumes (skill: "Resume After Block").
- `DONE` = the PR exists (`ready` or `draft`). `epic-check` confirms it and reports
  `gh pr checks` status (GitHub Actions).
- A respawned worker (attempt 2+) resumes from issue comments and the existing PR instead
  of restarting. Dependencies come from native `blocked_by` links, as in the skill's intake gate.
- 2-respawn limit: `epic-spawn` refuses a 4th attempt unless `--force`.

### Estimate gate

`full-path-github` pauses for the owner between intake, enrich and plan when an issue's
estimate is above 3. Unattended workers start with an explicit waiver so they do not
stall; live workers do not waive it. A worker that is alive but silent after an
intake/enrich/plan `PHASE` line is checked by pane, not treated as a crash.

### Live workers

`epic-spawn --live` or `epic-adopt` register a human-driven worker (`plan-first` mode, normal
permissions). It shows as `live` in `epic-status`, is never auto-restarted, and `epic-kill`
refuses it. It logs `HANDOFF` when the human ends the live phase.

## Log format

`UPDATES.log`, tab-separated, one line per event:

    <UTC timestamp>  <repo>/<n>  <EVENT>  <message>

Events: `STARTED`, `PHASE`, `HEARTBEAT`, `BLOCKED`, `HANDOFF`, `DONE`, `KILLED`.
The issue key uses the repo name without owner.

## Tests

    tests/run.sh

No network; stubs for `gh`, `tmux` and `wsnew` live in `tests/stubs/`.

## Known limits

- Dependent issues branch from the default branch, so they wait for a human to merge their blockers.
- Workers run with `--permission-mode bypassPermissions`. Only point this at issues you trust.
- `HEARTBEAT` depends on the worker following its prompt; the supervisor also checks tmux and the pane.
- The issue key drops the owner: two repos with the same name under different owners collide.
- `epic-check` finds the PR by searching for `closes #<n>`, which is how `full-path-github` titles its PRs.
- `full-path-github` does not write to the log itself; workers are told to, so a worker that
  ignores its prompt is only caught by the tmux and `epic-check` fallbacks.
- `wsnew` creates a `workbench/issue_<n>` folder; `full-path-github` expects its own worktree
  layout. How the two meet in practice is untested.
