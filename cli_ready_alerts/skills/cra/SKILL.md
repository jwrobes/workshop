---
name: cra
description: Operate the cli_ready_alerts framework via its `cra` CLI — toggle alerts on/off, mute contexts, play test sounds, tail the log, and diagnose a silent hook. Use when the user says "mute alerts", "turn off the sounds", "my CLI is suddenly silent", "play a test sound", "is the hook wired up", or is renaming a workspace and needs to update context regexes.
---

# cra

Companion skill for the `cli_ready_alerts` tool. Teaches the agent how to invoke `cra` (installed at `~/.local/bin/cra` by the tool's `setup.sh`), what its output means, and how to diagnose common failure modes without opening `config.json` by hand.

## Related tool

[cli_ready_alerts](../../) — this skill is a companion. Installation, architecture, and event model are documented there. This skill is *only* about driving the framework through `cra` after install.

## When to use

| Trigger | Action |
|---|---|
| "mute the alerts" / "turn off the sounds" / "silence cursor" (globally) | `cra off` |
| "turn the alerts back on" / "enable the sounds" | `cra on` |
| "mute <context>" / "silence <project>" | `cra mute <context>` (check spelling against `cra status` output) |
| "unmute <context>" | `cra unmute <context>` |
| "why is my CLI suddenly silent" / "alerts aren't firing" | Run the **silent-hook diagnostic** (below) |
| "play a test sound" / "is the sound wired up" / "does my new context work" | `cra test <event> <context>` |
| "show me what the alerts are set to" / "what context is docs using" | `cra status` |
| "show me recent alerts" / "what fired in the last hour" | `cra tail 200` |
| User renames a workspace folder | Remind them to update the `match.workspace_path` regex in `config.json` (via `cra edit`) — otherwise events from the renamed folder fall through to `default_context` |

## Commands

```
cra on | off                  # global enable/disable (persists across sessions, writes config.json)
cra status                    # config, contexts, routing, overrides, paths
cra mute <ctx>                # silence one context (writes muted: true)
cra unmute <ctx>              # reverse mute
cra test [event] [ctx]        # play the sound that WOULD fire (defaults: event=done, ctx=default)
cra tail [N]                  # tail last N lines of /tmp/cli-ready-alerts.log (default 40)
cra edit                      # open config.json in $EDITOR
cra help                      # usage
```

Per-shell env overrides the user might mention:

- `CURSOR_ALERT_DISABLE=1` — kill-switch, one terminal only (doesn't touch config).
- `CURSOR_ALERT_CONTEXT=<name>` — force a context in one terminal.

## Steps

### Silent-hook diagnostic (alerts used to work, now don't)

1. `cra status` — confirm `enabled: true`. If false → `cra on`. Also check for `shell override: CURSOR_ALERT_DISABLE=1 (this terminal is muted)` at the top of the output.
2. `cra test done default` — confirms `afplay` + a default sound file still work. If silent here, the issue is audio-layer (system volume, headphones, DND) not the framework.
3. Have the user trigger a real agent `stop`, then `cra tail 20`.
   - If you see `dispatch: event=done ... channels=sound` → the framework fired; the sound channel was invoked. Silent means `afplay` failed (missing file, wrong path). Read the next line of the log for the channel's own output.
   - If you see `dispatch: event=done ... channels=none (muted)` → the resolved context is muted. `cra unmute <ctx>`.
   - If you see nothing in the log after the `stop` → the hook didn't fire. Check `~/.cursor/hooks.json` still contains the `./hooks/cli-ready-alerts/dispatch.sh done` entry, and `ls -l ~/.cursor/hooks/cli-ready-alerts` resolves (not a dangling symlink). Re-run `bash setup.sh` from the tool directory to re-create the symlinks idempotently.
4. If the context resolves wrong (e.g., `context=default` when the user expected `myproject`), check the regex: `cra status` prints `match=<regex>` per context. `cra edit` to fix.

### "My new context isn't firing"

User just added a context to `config.json`. Walk them through:

1. `cra status` — confirm the new context appears in the list.
2. `cra test done <name>` — fires the sound directly, bypassing regex match. Proves the sound file exists and is playable.
3. Have them trigger a real agent in the new workspace, then `cra tail 10`. The log line `dispatch: ... workspace=<path>` shows what `dispatch.sh` actually saw. Compare to the regex.
4. Most common mistake: regex is anchored incorrectly. `myproject` matches anywhere in the path; `^myproject` would require it at the start. Prefer something like `/myproject(/|$|_)` to avoid collisions with other paths containing the substring.

### "Install seems broken after rename / move"

If the user moved the tool folder, symlinks silently dangle. Check:

```bash
ls -l ~/.cursor/hooks/cli-ready-alerts
ls -l ~/.local/bin/cra
```

If either shows `->` pointing at a path that doesn't exist, re-run `bash setup.sh` from the new location — it `ln -sfn`'s both symlinks idempotently.

## Notes

- Alpha: this skill is tied to the parent tool. If `cli_ready_alerts` graduates to its own repo, this skill travels with it.
- Graduation: if the diagnostic patterns here prove useful beyond this specific tool (e.g., they generalize to any hook-driven notification framework), consider splitting it into a standalone skill.
- Never edit `config.json` directly via `cat > config.json` — `cra` uses atomic jq writes to avoid half-written config. Either use `cra edit` (opens `$EDITOR`) or use `jq` yourself with `mktemp + mv`.
- The config lives at whatever path `setup.sh` installed to — `cra status` prints it under `paths: config:`. Usually `~/.local/share/cli_ready_alerts/config.json`.
