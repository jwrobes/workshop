# workshop

Jon's personal shelf of alpha tools: quick scripts, HTML utilities, and experimental helpers I use day-to-day but haven't hardened into proper packages.

## Philosophy

Tools here are **alpha** — I've built them, I use them (sometimes), but they don't carry a stability contract. The repo itself is the alpha marker; individual tools don't need their own version labels.

This follows [Simon Willison's "alpha" convention](https://simonwillison.net/): AI-assisted code can look polished — tests, docs, a proper README — without being *proven*. The only real signal of quality is that someone has used the tool for real work. When a tool has been used enough that I'd defend it, it graduates out to its own repo. See [Graduation](#graduation) below.

The implicit contract for anyone else: "Jon uses this but has not hardened it for others." Clone, read the tool's README, and adjust paths as needed.

## Two flavors of tool

### HTML tools (flat, at the repo root)

Single-file browser tools — zero install, zero dependencies. Open the `.html` locally or serve it, and it works. Mirrors [`simonw/tools`](https://github.com/simonw/tools).

- Naming: `kebab-case.html` at the repo root
- Optional companion: `kebab-case.docs.md` with a one-paragraph description
- Use for: text transformers, diff tools, token counters, format converters, regex playgrounds

### Script tools (subfolders)

Anything that runs on my machine with a real shell or Python/Node runtime. Each gets its own folder with a local README and its own requirements.

- Naming: `snake_case/` folder
- Must contain: `README.md` with install + usage, the script(s), and any `requirements.txt` / `package.json` / `Gemfile`
- Dependencies live **with the tool**, not in a shared requirements file
- Use for: CLI utilities, data mining scripts, API wrappers, shell automations

### Companion skills (optional, paired with a tool)

Some tools ship with a **companion Claude Code skill** — a `SKILL.md` that teaches the agent how to invoke the tool, parse its output, or reason about when to use it. These skills live **inside the tool's folder** and travel with it if the tool graduates out.

- Location: `{tool}/skills/{kebab-skill-name}/SKILL.md`
- Symlink into: `~/.claude/skills/{kebab-skill-name}` so Claude Code auto-loads it

## Install locations

The repo is the **source of truth** for tool code. Where a tool actually runs from depends on whether it has a heavy setup.

| Tool shape | Source | Runtime location |
|---|---|---|
| HTML tool | `workshop/{tool}.html` | Open in browser |
| Portable script (stdlib only) | `workshop/{tool}/` | Run directly from the clone, or symlink a wrapper into `~/.local/bin/` |
| Script with venv / node_modules / native bins | `workshop/{tool}/` (source) | `~/.local/share/{tool}/` (installed), set up via `setup.sh` |

## HTML tools

| Tool | Description |
|---|---|
| *(none yet)* | |

## Script tools

| Tool | Description | Runtime |
|---|---|---|
| [`cli_ready_alerts/`](./cli_ready_alerts/) | Context-aware notification framework for Cursor and Claude Code agents. Fires per-workspace sounds on `done` / `approval` / `failed`. Supports talking mode (macOS `say`) and custom recorded sounds. Ships a `cra` control CLI + companion skill. macOS-only. | Heavy (installs to `~/.local/share/cli_ready_alerts/`, symlinks `cra` into `~/.local/bin/`) |
| [`speak_to_code/`](./speak_to_code/) | Voice-to-code dictation pipeline. Records speech, transcribes on-device via Apple Silicon (mlx-whisper), cleans up with the `llm` CLI, and copies to clipboard. macOS + Apple Silicon only. | Heavy (symlinks `dictate` into `~/.local/bin/`) |
| [`comprehension_signoff/`](./comprehension_signoff/) | Standalone Claude Code skill — post-ship comprehension gate for vibe-coded changes. Generates explainer artifacts then verifies understanding via SOLO-graded teach-back. Local-only (not in synced skills repo). | Light (symlink `comprehension_signoff/` into `~/.claude/skills/comprehension-signoff`) |

## Graduation

When a tool has earned regular use — someone else relies on it, it needs versioning, or it's ready to publish — it graduates out of this repo:

1. **Extract into its own repo** with a proper `pyproject.toml`, tests, and CI.
2. **Package to PyPI / npm** if it's broadly useful and I'm committed to supporting it.
3. **Archive** — retired tools move to `_archive/` with a note explaining why.

## Folder tree

```
workshop/
├── README.md                      # This file — index of everything
├── cli_ready_alerts/              # Agent notification framework — heavy setup
│   ├── README.md                  # Install + usage + debugging
│   ├── setup.sh                   # Installs to ~/.local/share/cli_ready_alerts/, wires symlinks
│   ├── config.example.json        # Template config (sound_mode, talking, contexts)
│   ├── dispatch.sh                # Central router — called from hook entries
│   ├── dispatch-claudecode.sh     # Claude Code adapter (injects workspace_path)
│   ├── stash-context.sh           # beforeSubmitPrompt — snapshots workspace by conversation_id
│   ├── cra                        # Control CLI (symlinked to ~/.local/bin/cra)
│   ├── channels/sound.sh          # Three-tier sound channel (custom file → talking → system)
│   ├── sounds/                    # Drop <context>_<event>.mp3 here to override defaults
│   ├── lib/common.sh              # Shared helpers (config, context, dedup, logging)
│   └── skills/cra/SKILL.md        # Companion skill for Claude Code / Cursor
├── speak_to_code/                 # Voice dictation pipeline — record → transcribe → llm → clipboard
│   ├── README.md                  # Install + usage
│   ├── setup.sh                   # Installs deps, symlinks dictate to ~/.local/bin/
│   ├── dictate                    # Main script
│   └── dictate-context.md.example # Vocabulary template for context.md
├── comprehension_signoff/         # Standalone Claude Code skill — post-ship comprehension gate
│   ├── README.md                  # Install + usage
│   ├── SKILL.md                   # The skill (symlinked into ~/.claude/skills/)
│   └── reference/                 # Research dossier + SOLO grading rubric
└── _archive/                      # Retired tools, kept for reference
```
