# smart_screenshots

Take a screenshot with ⌘⇧4 as usual. A few seconds later it has a descriptive name, a copy sits in
the workbench you're working in, and its path is waiting in the input box of the Claude session you
were looking at.

```
Screenshot 2026-10-20 at 4.40.33 PM.png
  → ~/Screenshots/2026-10-20_xcodebuild-admin-authentication-dialog.png
  → ~/workspace/myproject_workspace/workbench/fix_login_bug/screenshots/2026-10-20_xcodebuild-admin-authentication-dialog.png
  → pasted into the active Claude pane:  …/screenshots/2026-10-20_xcodebuild-admin-authentication-dialog.png ▌
```

CLI: `snapname`. macOS only. Stdlib python3; calls `sips`, `tmux`, `osascript`, and a vision
command of your choice (default: `claude -p`).

**Status: Alpha.** Works on my machine; the launchd agent and tmux/Claude paste paths are lightly
tested. Expect rough edges.

## How it works

1. **Trigger.** A per-user launchd agent (`com.jwrobes.snapname`) watches the screenshot folder with
   `WatchPaths` and runs `snapname process` whenever it changes. No Folder Actions, no AppleScript,
   no admin rights.
2. **Name.** Only files with the macOS default name (`Screenshot <date> at <time>.png`) created in
   the last two minutes (`max_age_seconds`) are touched, so an existing backlog of unnamed
   screenshots is left alone. Use `snapname backfill` to rename those on purpose.
   A 1024px JPEG copy goes to `claude-haiku-4-5` through the configurable vision command
   (see [Vision backend](#vision-backend)), which returns a slug; the file is renamed to
   `{date}_{slug}.png`. The prompt tells the model to keep names, emails, personal details, and IDs
   out of the slug. If anything fails, the
   original name is kept and you get a notification.
3. **Route.** The destination is the working folder of the **active pane of the most recently used
   tmux client**:

   | Active pane cwd | Destination |
   |---|---|
   | `~/workspace/X_workspace/workbench/<initiative>/…` | `<initiative>/screenshots/` |
   | a worktree that a workbench's `.claude/settings.json` lists in `additionalDirectories` | that workbench's `screenshots/` |
   | anything else under `~/workspace/X_workspace/` | `X_workspace/screenshots/` |
   | outside any `*_workspace`, or no tmux | stays in `~/Screenshots/` only |

   Worktrees are never a destination, so screenshots can't sneak into commits. Each new
   `screenshots/` folder gets a `.gitignore` of `*` for the same reason. The file is **hard-linked**
   (same bytes, no extra disk), so the central folder stays a complete archive and the workbench
   copy survives the workbench being archived.
4. **Hand to Claude.** If that pane is running `claude` and is at its input box (not a permission
   dialog or menu), the image path plus a trailing space is bracket-pasted into the box. Nothing is
   submitted; keep typing your question and press Enter. Claude reads the image from the path.

`snapname pin DIR` overrides step 3 (useful outside tmux, or to collect a batch somewhere specific);
`snapname unpin` goes back to following the active pane.

## Install

Prerequisites: macOS, python3, tmux (for routing/pasting), and a vision command (below).

```bash
git clone https://github.com/jwrobes/workshop ~/workshop     # keep it somewhere stable
cd ~/workshop
bash smart_screenshots/setup.sh --dry-run
bash smart_screenshots/setup.sh
```

`setup.sh`:

1. Checks that the vision command (first word of `vision_cmd`; `claude` by default) is on `PATH`.
2. Symlinks `~/.local/bin/snapname` to this folder's script.
3. Sets `com.apple.screencapture location` to the watch folder if it isn't already, and turns off
   the floating thumbnail (`show-thumbnail false`), which otherwise delays the file landing by ~5s.
   Pass `--keep-thumbnail` to keep it.
4. Writes `~/Library/LaunchAgents/com.jwrobes.snapname.plist` and loads it with `launchctl bootstrap`.
   The agent runs through `zsh -ic` so it picks up API keys exported in `~/.zshrc`.

Uninstall: `bash smart_screenshots/setup.sh --uninstall` (leaves screenshot settings alone).

### First-run permissions

None need admin. You may see:

- A one-time **notification permission** prompt for the notifications `snapname` posts via
  `osascript` (allow it in System Settings → Notifications → Script Editor, or set `"notify": false`).
- macOS's **"background item added"** notice for the launchd agent; leave it enabled in System
  Settings → General → Login Items & Extensions.

## Usage

```bash
snapname where             # where would a screenshot taken right now go, and will it paste?
snapname log               # what happened to recent screenshots
snapname name some.png     # dry-run the naming step on any image
snapname pin ~/workspace/myproject_workspace/workbench/fix_login_bug
snapname unpin
snapname process --dry-run # show what would happen to anything waiting in the watch folder
snapname config            # effective config
snapname backfill --dry-run           # older default-named screenshots waiting to be renamed
snapname backfill --limit 20          # rename the 20 most recent of them in place
```

`backfill` only renames inside the watch folder. It never routes into a workbench or pastes into
Claude, since those decisions only make sense for a screenshot you just took. Each file is one model
call (~1.5s), so a few hundred take several minutes.

## Config

`~/.config/snapname/config.json` (all keys optional):

| Key | Default | Notes |
|---|---|---|
| `watch_dir` | `~/Screenshots` | Re-run `setup.sh` after changing it. |
| `workspace_root` | `~/workspace` | Where `*_workspace` folders live. |
| `model` | `claude-haiku-4-5` | Passed to the vision command as `{model}`. Env: `SNAPNAME_MODEL`. |
| `vision_cmd` | `claude -p ...` (see below) | Command template for the vision call. Env: `SNAPNAME_VISION_CMD`. |
| `name_format` | `{date}_{slug}` | `{date}` is the capture date from the macOS name. |
| `max_slug_words` | `6` | |
| `max_age_seconds` | `120` | Older default-named files are ignored by the agent; see `backfill`. |
| `route` | `link` | `link` (hard-link into the working folder), `move` (working folder only), `off`. |
| `inject` | `paste` | `off` to never touch the Claude pane. |
| `notify` | `true` | macOS notification with the new name and destination. |

State and logs: `~/.local/state/snapname/` (`snapname.log`, `agent.log`, `pin`).

## Vision backend

The model call lives in one function, `call_vision_model()` in `snapname`. It runs the
`vision_cmd` template: the string is split like a shell command line, then each word has these
placeholders filled in: `{image}` (1024px JPEG copy), `{image_dir}`, `{model}`, `{system}` (the
naming instructions), `{prompt}`, `{max_tokens}`. The command must print the slug on stdout.

| Backend | `SNAPNAME_VISION_CMD` |
|---|---|
| Claude Code (default) | `claude -p --model {model} --allowedTools Read --add-dir {image_dir} --append-system-prompt {system} "Read the image file {image}. {prompt}"` |
| [`llm`](https://llm.datasette.io) CLI | `llm -m {model} -a {image} -s {system} {prompt}` (set `SNAPNAME_MODEL` to a vision model you have configured, e.g. `gpt-4o-mini`) |
| Anything else | any command that takes an image and prints text; or edit `call_vision_model()` |

Set the env var in your shell profile (the launchd agent reads `~/.zshrc` via `zsh -ic`), or put
`"vision_cmd"` in `config.json`. Try it with `snapname name some.png` before relying on the agent.

## Data handling

**Screenshots are sent to the model you configure.** Whatever backend `vision_cmd` points at (a
hosted API via `claude` or `llm`, or a local model) receives a 1024px copy of every new
screenshot, including anything sensitive on screen. Use a backend and provider you trust with that
content, or a local model. The full-resolution file stays on your machine; the downscaled copy is
written to a temp dir that is deleted after the call. The prompt asks the model to keep names,
emails, and IDs out of the slug, but slugs can still name a topic.

## Limits

- Routing follows tmux. Outside tmux (a plain Terminal tab, Cursor's terminal) screenshots stay in
  the watch folder unless you `pin`.
- "Most recently used client" means the terminal window you last typed in. With two tmux windows on
  two monitors, it's whichever you touched last.
- Screen recordings (`Screen Recording … .mov`) and already-named files are ignored.

## Tests

```bash
cd smart_screenshots && python3 -m unittest
```
