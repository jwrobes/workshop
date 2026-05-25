# cli_ready_alerts

Context-aware notification framework for Cursor CLI / IDE agents. Fires a sound (and, later, banners or Telegram pings) when an agent transitions to a state that needs your attention — **done**, **needs approval**, or **failed** — with per-workspace sounds so you can tell by ear which project just pinged you.

Alpha: shipped 2026-04-22. macOS-only today; written for Cursor, with a Claude Code adapter planned.

## What it does

When a Cursor agent (CLI or IDE) hits a lifecycle event, a small `dispatch.sh` script reads the hook's stdin, resolves a **context** (e.g. `api` vs `frontend` vs `docs`) from the workspace path, and fires each enabled **channel** (sound today, banner/Telegram later) with a context-specific sound.

Three events, all deduplicated to keep the sound-scape quiet:

| Event | Hook source | Meaning | Dedup rule |
|---|---|---|---|
| `done` | `stop` | Agent is idle, ready for your next prompt. | Suppressed if `failed` fired <2s earlier (so the happy chime can't mask a real failure). |
| `approval` | `beforeShellExecution` (matcher-gated) | Agent is about to run a command Cursor typically prompts for (sudo/rm -rf/curl/package installs/force push/reset --hard/chown/chmod -R). **Observe-only** — never overrides Cursor's permission decision. | Suppressed if another `approval` fired <5s earlier (one chime per burst). |
| `failed` | `postToolUseFailure` | Any tool call errored. | None — always fires. |

Everything is additive and fail-open. If a sound file is missing, dispatch falls back to the default context's sound. If dispatch itself crashes, the agent is untouched.

## Install

```bash
cd /path/to/cli_ready_alerts
bash setup.sh
```

Installs into `~/.local/share/cli_ready_alerts/`, symlinks:

- `~/.cursor/hooks/cli-ready-alerts` → install dir (so Cursor hooks can find it)
- `~/.local/bin/cra` → the control CLI

Idempotent — safe to re-run. Code is synced; your `config.json` is preserved after first install.

**One manual step:** merge the hook entries printed by `setup.sh` into `~/.cursor/hooks.json`. Keep any existing entries alongside — Cursor allows multiple entries per event.

### Preflight requirements

- macOS (uses `afplay`, `osascript`)
- `jq` (`brew install jq`)
- Bash 3.2+ (ships with macOS)

### Uninstall

```bash
bash setup.sh --uninstall
```

Removes the two symlinks. Also remove the hook entries from `~/.cursor/hooks.json` manually. Install dir + user config are preserved (delete them explicitly if you want a full wipe).

## Usage

The `cra` CLI is the one-stop control surface:

```
cra status             # show config, contexts, routing, overrides
cra off                # disable alerts globally (persists across sessions)
cra on                 # re-enable
cra mute <context>     # silence one context, keep others firing
cra unmute <context>   # re-enable
cra test done default  # fire the sound that WOULD play for event+context
cra tail 20            # tail the last 20 log lines
cra edit               # open config.json in $EDITOR
cra help               # usage
```

Per-shell overrides (no persistence):

- `export CURSOR_ALERT_DISABLE=1` — kill-switch, one terminal.
- `export CURSOR_ALERT_CONTEXT=mywork` — force a context in one terminal (useful when no workspace-path match applies).

## Adding your own contexts

Edit `~/.local/share/cli_ready_alerts/config.json` (or `cra edit`). A context is:

```json
{
  "name": "mywork",
  "match": { "workspace_path": "/mywork(/|$)" },
  "sounds": {
    "done": "mywork_done.aiff",
    "approval": "mywork_approval.aiff",
    "failed": "mywork_failed.aiff"
  }
}
```

`workspace_path` is a PCRE regex. Resolution order at dispatch time:

1. `$CURSOR_ALERT_CONTEXT` env var (wins everything).
2. Context snapshotted at `beforeSubmitPrompt` time (`stash-context.sh` writes the context into `/tmp/cli-ready-alerts-state/<conversation_id>.json`).
3. Match the workspace path against each context's `match.workspace_path` regex — first hit wins.
4. Fall through to `default_context`.

Drop your custom sound files into `~/.local/share/cli_ready_alerts/sounds/` by the filenames you referenced, or leave them out to fall through to `default_context.sounds`. `.aiff`, `.wav`, and `.mp3` all play via `afplay`. Copy from `/System/Library/Sounds/` for freebies. A sample `myproject_done.aiff` is included in `sounds/` as a naming reference.

## How it works (for future you)

```
~/.cursor/hooks/cli-ready-alerts/       (symlink → ~/.local/share/cli_ready_alerts/)
├── dispatch.sh           # central router — invoked by each hook entry
├── stash-context.sh      # beforeSubmitPrompt — snapshots workspace by conversation_id
├── config.json           # your config (not tracked in workshop)
├── config.example.json   # template; seeds config.json on first install
├── cra                   # control CLI (symlinked to ~/.local/bin/cra)
├── channels/
│   └── sound.sh          # afplay channel
├── sounds/               # custom sounds per context
├── lib/common.sh         # helpers (config, context resolution, dedup, logging)
├── setup.sh              # this installer
└── skills/cra/SKILL.md   # companion Cursor skill (agent-facing)
```

**Why a `stash-context.sh`?** Cursor's `stop` event stdin only contains `{conversation_id, status}` — no workspace info. But `beforeSubmitPrompt` DOES include `workspace_roots`. `stash-context.sh` writes a per-conversation state file (`/tmp/cli-ready-alerts-state/<conversation_id>.json`) at prompt-submit time, and `dispatch.sh` reads it back at stop time to resolve the right context. Files are auto-pruned after 24h.

**Why dedup with `/tmp` stamp files?** Each hook invocation is a fresh shell process — no in-memory state survives. Stamp files are the smallest cross-process mechanism. `/tmp/cli-ready-alerts-last-<event>.ts` holds a Unix timestamp; dedup checks `now - then < window` and suppresses if so.

**Why observe-only on `beforeShellExecution`?** Returning a permission response from a hook would override Cursor's own allow/deny logic for *every* matched command. Observe-only means we play a chime and exit without a permission JSON — Cursor's decision-making is untouched. If you later want to actively gate a narrow pattern (e.g., anything touching `~/.aws/credentials`), add a *second* `beforeShellExecution` entry with a tighter matcher that returns `permission: "ask"`.

## Debugging

| Problem | Action |
|---|---|
| No sounds firing at all | `cra status` — check `enabled: true` and no `CURSOR_ALERT_DISABLE` env var. |
| Sound fires but wrong context | `cra tail 40` — the log shows `context=<resolved>`. Check your regex against the actual `workspace_path` in the log line. |
| Hook seems not to fire | `tail -f /tmp/cli-ready-alerts.log` while triggering. If nothing appears, confirm `~/.cursor/hooks.json` has the entries and that `~/.cursor/hooks/cli-ready-alerts/dispatch.sh` resolves (`ls -l` the symlink). |
| Tests pass but real Cursor doesn't | Reload Cursor once after editing `hooks.json` — it reads that file at startup. `config.json` is hot-reloaded every dispatch. |
| Sounds stomping over each other | `cra tail` should show dedup lines like `event=done suppressed`. If not, bump the dedup windows in `dispatch.sh` (2s / 5s by default). |
| Verbose mode | `export CRA_DEBUG=1` in the shell Cursor launched from. |

## Dependencies

- `jq` (required)
- `afplay` (macOS built-in)
- `osascript` (macOS built-in, used for frontmost-app guardrail)
- `terminal-notifier` (optional, only for future banner channel — `brew install terminal-notifier`)

No Python, no Node, no network dependencies. Pure bash + jq.

## Notes / caveats

- Alpha: the `cra` CLI and the approval matcher haven't hit a wide variety of real-world commands yet — tune the regex in `~/.cursor/hooks.json` if it misfires or misses.
- macOS only. Linux/WSL is a possible future port but not planned.
- The approval matcher is a *best-effort proxy* for Cursor's own allowlist. We can't know Cursor's exact rules, so we match commonly-gated patterns. False positives are low-stakes (extra chime); false negatives mean silence on a command Cursor prompted about.
- Not yet tested with Claude Code. A platform adapter (`runtime/platforms/claude-code.sh`) is sketched in the upstream plan and is a one-file addition when Claude Code lands.

## Roadmap

Planned: banner channel (`terminal-notifier`), Telegram channel, tmux status indicator, Linux port.
