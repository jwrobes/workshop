# sharpen_prompt

Turns the `sharpen-prompt` skill into a loop between two tmux panes. You give a sharpen Claude session a
draft, typed or dictated. It already has the working session's last reply, it shows the usual sharpened
output (READ FIRST / MESSAGE TO COPY / what changed / open questions), you adjust it if you want, and the
final message lands on your clipboard ready to paste into the working session.

**Status:** Alpha. macOS + tmux.

```
┌ [demo · working] ───────────────┬ [demo · sharpen] ───────────────┐
│ claude (doing the task)         │ claude (sharpen session)        │
│   ↑ paste (Cmd-V)               │   draft in (typed, or prefix+v) │
│                                 │   message out → clipboard       │
└─────────────────────────────────┴─────────────────────────────────┘
```

## Pieces

| Piece | What it does |
|---|---|
| `sharpen` | CLI: pairing, status, re-copy, delivery, and the hook entry points |
| `sharpen hook stop` (Stop hook) | Every paired pane: saves the last assistant message to `~/.config/sharpen/sessions/`. Sharpen panes: also extracts the MESSAGE TO COPY block and copies it if READY |
| `sharpen hook prompt` (UserPromptSubmit hook) | Sharpen panes only: attaches the working session's last message and a `Pair …` header line |
| `prompts/sharpen-session.md` | Appended to the sharpen session's system prompt: draft/refine semantics, header, four-backtick fence |
| `sharpen.tmux` | `prefix+v` / `prefix+V` dictation popups, and pane-border labels `[pair · role]` |
| `../speak_to_code/dictate --to-sharpen` | Light cleanup, then pastes into the sharpen pane **and submits it**; never writes the clipboard |

Panes outside a pair are untouched: both hooks exit immediately and nothing is written.

## Install

```bash
bash setup.sh                                   # symlink ~/.local/bin/sharpen + register hooks
tmux source-file "$PWD/sharpen.tmux"            # key bindings + border labels for this tmux server
```

To keep the bindings across tmux restarts, add this line to `~/.tmux.conf` **above** the
`run '~/.tmux/plugins/tpm/tpm'` line (tpm has to stay the last line of the file), then reload with
`prefix + r`:

```
source-file ~/personal/workshop/sharpen_prompt/sharpen.tmux
```

Use the path of wherever your clone of this repo lives; the one above is the worktree this was built in.
The bindings are `prefix + v` / `V` (dictate a draft / a refinement) and `prefix + y` (recopy the last
sharpened message), plus pane-border labels that turn on `pane-border-status` for every pane.
`bash setup.sh --uninstall` removes the symlink and hooks; delete the `source-file` line yourself.

Hooks are read when a Claude session starts, so restart the working session (or `/hooks` → reload)
after installing.

## Use

```bash
# Sharpen pane: claims the pair and launches claude with the session prompt
sharpen session demo

# Working pane: join before (or after) starting claude there
sharpen join demo
# …or from the sharpen pane: sharpen pair right   (also %ID, left/up/down, or a cwd substring)
```

`sharpen session` starts Claude in `bypassPermissions` mode, the same as your working sessions. The
sharpen session appends a row to `~/.claude/skills/sharpen-prompt/log/prompt_log.md` on every pass, and
Claude Code treats that path as a sensitive file: it asks for confirmation in every other mode, even
with an allow rule for it. Set `SHARPEN_PERMISSION_MODE=default` to get the normal prompts back, or
any other mode name (for example `acceptEdits`) to use it instead. Sessions already running keep the
mode they started with.

Then in the sharpen session, type a draft (`new: …` forces a fresh draft; anything else after a pass is
a refinement). Or from either pane:

| Key | Does |
|---|---|
| `prefix + v` | popup: dictate a new draft; it is pasted into this pair's sharpen pane **and submitted** |
| `prefix + V` | popup: dictate a refinement; same, sent as `refine [voice]: …` |
| `prefix + y` | put this pair's last sharpened message back on the clipboard (from the working or the sharpen pane) |

Ctrl-C ends the recording (same as `dictate`).

### The dictation hand-off is automatic

By design, you do not paste or press Enter for a dictation. When transcription finishes, `sharpen`
pastes the text into the sharpen session's input box, checks that it landed there, presses Enter, and
checks the box emptied. Sharpen starts on the draft straight away and the popup closes. If the sharpen
session is in the middle of a pass, Claude queues the draft and handles it next. If the sharpen pane is
scrolled back, scrollback is cancelled first.

That is a decision, not a gap: a mistranscribed draft is cheap to fix with a `refine:` follow-up, and
the cost of reviewing every dictation first is the step this tool exists to remove. One thing to keep in
mind is that sharpen sessions run in bypass-permissions mode (above), so a draft is sent into a session
that can run tools unprompted. Dictate things you'd be happy for that session to read.

The text is saved before anything is sent, so a failed delivery never loses it:

| What happened | What you see | What to do |
|---|---|---|
| Sent | the popup closes | nothing |
| Sharpen pane has a dialog open or half-typed text | popup stays open with the reason; nothing was typed into the pane | clear the pane, then `sharpen resend` |
| This pane isn't paired and several sharpen sessions exist | popup lists them: a number sends to that session, `c` copies the transcript, Enter skips | pick one |
| This pane isn't paired and no sharpen session exists | popup asks whether to copy the transcript to the clipboard | `y` copies it so you can paste it yourself |

A key pressed in an unpaired pane delivers to the one sharpen session in the same tmux window, if there
is exactly one. The system clipboard is never written without asking, because it may still hold a
sharpened message you haven't pasted. Transcripts for unpaired panes are saved under
`~/.config/sharpen/dictations/` (one file each, owner-only, removed by `sharpen gc` after 24 hours).

When the pass comes back READY, a notification says `[demo] copied — READY, N chars`. Paste into the
working pane. NOT READY isn't copied: answer the blocking question, or `sharpen copy` to take the best
guess anyway.

### Several pairs at once

The system clipboard is shared, so another pair's reply can replace a message you haven't pasted yet.
Nothing is lost, but you should know it happened:

- The notification names it: `[beta] copied — READY, 412 chars; replaced [alpha]'s message`.
- `prefix + y` in any pane of that pair puts its last sharpened message back (`sharpen copy` does the
  same from a shell). Each pair keeps its message in `~/.config/sharpen/pairs/<pair>.last-message.md`.
- tmux buffers are per pair (`sharpen-<pair>`), and voice delivery uses a buffer named for the pair and
  process, so two pairs can't deliver into each other's session.

A clipboard manager such as Alfred's history is a second safety net: anything that reaches the system
clipboard is still in it after being replaced.

### Switching and rollover

| Situation | Command |
|---|---|
| Working session filled up, new `claude` in the same pane | nothing — same pane, same pair |
| New working session in another pane | `sharpen join demo` there, or `sharpen pair %17` from the sharpen pane |
| Two working panes alive, want the older one | `sharpen pin %12` (`sharpen unpin` to go back to most recent) |
| Point this sharpen session at another initiative | `sharpen pair other-pair` (from the sharpen pane) |
| Leave a pair | `sharpen leave` |

You can run these from inside the sharpen Claude session too, with `!sharpen pair right`.

### Inspect

```bash
sharpen pairs       # every pair: panes, current target, last pass
sharpen status      # this pane
sharpen last        # the working-session message the sharpen pane will see
sharpen copy        # re-copy the last extracted message (prefix+y does this from tmux)
sharpen resend      # send the last saved dictation again after a failed delivery
sharpen gc          # drop snapshots and saved transcripts older than 24h
```

Hook errors go to `~/.config/sharpen/.hook.log` and never block a session.

## Notes

- **Pair names** default to the workbench initiative folder (`…/workbench/sharpen_prompt_tool` →
  `sharpen-prompt-tool`), else the current folder name.
- **Outside tmux**, set `SHARPEN_PAIR` and `SHARPEN_ROLE` (working|sharpen) before launching claude.
  Snapshots and copy-out work. Voice delivery needs tmux; without it `dictate --to-sharpen` exits 3,
  saves the transcript, and the popup wrapper offers to copy it.
- **Keys:** `prefix+v`/`V` are used because `prefix+s` is tmux's session chooser.
- **Delivery** uses tmux bracketed paste, so a multi-line dictation arrives as one prompt. Every
  attempt (pair, pane, result, reason, length, never the text) is logged to
  `~/.config/sharpen/.hook.log`, and `sharpen status` shows the last one.

## Test

```bash
python3 -m unittest sharpen_prompt/test_sharpen.py
```
