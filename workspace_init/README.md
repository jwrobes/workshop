# workspace_init

Headless trigger for the `scaffold-workspace` skill, seeded from either a GitHub issue URL or just a repo (URL or `owner/repo` slug). It skips manually invoking the skill and re-describing the context every time.

(Ported from a GitLab version.)

## What it does

Two modes, auto-detected from the `<target>` argument:

**Issue mode**: target is `https://github.com/<owner>/<repo>/issues/<n>` or `<owner>/<repo>#<n>`:

1. Parses the repo and issue number.
2. Fetches the issue title and body with `gh issue view <n> -R <owner>/<repo> --json title,body`.
3. Derives an initiative name from the issue title (or use `--initiative` to override).

**Project mode**: target is any other github.com repo URL (repo root, `/tree/...`, `/pull/<n>`, etc.) or a bare slug (`myorg/myrepo` or just `myrepo`):

1. Parses the repo only; no issue lookup.
2. `--initiative NAME` is required (there is no issue title to derive one from).
3. `--description TEXT` is optional and seeds the workbench README's "Why" section.

Then, in both modes:

4. Prints a plan and asks for confirmation.
5. Runs `claude -p "/scaffold-workspace ..."` headlessly with `--dangerously-skip-permissions`, so it can `mkdir`, `git worktree add`, and write files without prompting.
6. Creates (or reuses) a tmux session at the new workbench root, split into two panes: top is a plain shell, bottom starts `claude --permission-mode bypassPermissions`. Then attaches (or, if already inside tmux, switches the client).

The skill does the real work (workspace structure, worktree, `.claude/settings.json`, workbench README, commits). This script is a dispatcher that supplies the initiative name and issue context up front, plus the tmux hop that follows.

The `scaffold-workspace` skill is in `../skills/scaffold-workspace/`.

## Usage

```bash
./wsnew.sh https://github.com/myorg/myrepo/issues/123
./wsnew.sh myorg/myrepo#123

# project mode: no issue, just a repo + initiative
./wsnew.sh https://github.com/myorg/myrepo/tree/main --initiative explore_feature
./wsnew.sh myorg/myrepo --initiative explore_feature --description "Exploring feasibility of feature X"
```

Options:

- `--project NAME`: local folder under `~/workspace/` if it differs from the repo name
- `--initiative NAME`: override the derived `lowercase_with_underscores` initiative name (required in project mode)
- `--description TEXT`: freeform blurb for the README's "Why" section (project mode only)
- `--ref repo1,repo2`: reference projects to grant worktree access to
- `--yes`: skip the confirmation prompt
- `--no-tmux`: skip the tmux question, just scaffold the workspace
- `--session NAME`: override the tmux session name (default: `<project>-<initiative-hyphenated>`)

## Requirements

- `gh` (GitHub CLI), authenticated with `gh auth login` (issue mode only)
- `claude` CLI on `PATH`
- `tmux` (unless run with `--no-tmux`)
- The target repo already cloned at `~/workspace/<project>/`

## Caveats

- Runs with `--dangerously-skip-permissions`. Only use it on issues you trust, and review the printed plan (project, initiative, tmux) before confirming.
- If the workspace already exists, the skill takes its "Add Initiative to Existing Workspace" path instead of re-scaffolding.
- The initiative name is auto-slugified from the issue title and truncated to 40 chars; pass `--initiative` to control it.
- Tmux pane targeting uses `#{pane_id}` rather than `session:window.pane` indices, so a `base-index 1` tmux.conf does not break it.
- If a session with that name already exists it is reused as-is, not re-split.
- Only github.com URLs are accepted.

## Install

Plain bash + python3. Run from the clone, or symlink onto `PATH`:

```bash
ln -s ~/personal/workshop/workspace_init/wsnew.sh ~/.local/bin/wsnew
```
