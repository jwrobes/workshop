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

### Standalone skills (`skills/`)

Skills that don't belong to one tool live in `skills/<kebab-name>/SKILL.md`. This folder also absorbed the former `jwrobes/skills` repo. Install with `skills/install.sh` (Claude Code by default, `--cursor` for Cursor). It also links tool-bound skills.

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
| [`sharpen_prompt/`](./sharpen_prompt/) | Pairs a `sharpen-prompt` Claude session with a working session in tmux. Hooks hand the working session's last reply to the sharpen session and copy the sharpened message to the clipboard when it is READY. Ships the `sharpen-prompt` companion skill. macOS + tmux only. | Portable, stdlib python3; `setup.sh` symlinks `sharpen` and registers two Claude Code hooks |
| [`tmux_doctor/`](./tmux_doctor/) | Classifies tmux sessions, writes a keep/kill report and manifest, and kills approved sessions with hard guards. Ships the `cleanup-tmux` companion skill. | Portable, stdlib python3; runtime in `~/.config/tmux-doctor/` |
| [`smart_screenshots/`](./smart_screenshots/) | Names new macOS screenshots with a vision model, hard-links them into the workbench folder of your active tmux pane, and pastes the path into that pane's Claude input. Vision command is configurable (`claude -p` or `llm`). macOS only. | Portable, stdlib python3; launchd agent via `setup.sh` |
| [`workspace_init/`](./workspace_init/) | `wsnew <github-issue-url>`: derives an initiative name, runs `claude -p "/scaffold-workspace ..."` headlessly, then opens a 2-pane tmux session. Needs the `gh` CLI. | Portable bash + python3 |
| [`workspace_doctor/`](./workspace_doctor/) | Scans git worktrees across `*_workspace/` dirs, checks PR and issue state with `gh`, classifies what is safe to clean up, and archives or removes it after approval. Dry-run by default. Ships the `cleanup-workspace` skill. | Portable python3; state in `~/.config/workspace-doctor/` |
| [`chat_mining/`](./chat_mining/) | Catalogs, searches and classifies local Claude Code and Cursor chat history. LLM command is configurable (`claude -p` or `llm`). | Portable, stdlib python3 |
| [`epic_conductor/`](./epic_conductor/) | Supervisor that runs several `full-path-github` workers in parallel, one detached tmux session per GitHub issue, coordinated through a shared log. Restarts dead workers, supports live human-driven workers, never merges. Needs `gh`, `tmux`, `claude`, and `workspace_init`. Ships the `conducting-epics` skill. | Portable bash; `setup.sh` symlinks the helpers into `~/.local/bin` |

## Standalone skills

| Skill | Purpose |
|---|---|
| [`close-out-session/`](./skills/close-out-session/) | Close out the current working session by summarizing progress, capturing uncommitted changes, writing a continuation prompt, updating READMEs, and committing. |
| [`code-review/`](./skills/code-review/) | Seven-phase code review checklist (architecture, collaboration, naming, errors, tests, frontend, commits) with a 0–3 per-phase scoring rubric. |
| [`comprehension-artifact/`](./skills/comprehension-artifact/) | Render a "what I built" comprehension artifact for a non-trivial change so a reviewer can understand it from a phone without pulling code. |
| [`continue-workflow/`](./skills/continue-workflow/) | Resume a previous working session by finding and loading the most recent continuation prompt. |
| [`enforce-integration-test/`](./skills/enforce-integration-test/) | Plan and validate end-to-end integration tests before running them. |
| [`extract-engineering-style/`](./skills/extract-engineering-style/) | Extracts coding conventions and review voice from git history and optional GitLab/GitHub MR data for named engineers. |
| [`full-path-github/`](./skills/full-path-github/) | Confidence-gated orchestrator that takes a raw GitHub issue and delivers a reviewed, tested pull request on a personal GitHub project. |
| [`generate-skill-doc/`](./skills/generate-skill-doc/) | Extract learnings from a debugging or investigation session and produce a structured skill doc. |
| [`gh-pr-create/`](./skills/gh-pr-create/) | Create GitHub pull requests with structured descriptions via the gh CLI. Use when the user says "create pr", "open pr", "submit pr", "push and create pr", or "draft pr". |
| [`grill-me/`](./skills/grill-me/) | Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. |
| [`improve-codebase-architecture/`](./skills/improve-codebase-architecture/) | Explore a codebase for architectural friction, discover opportunities for improving testability, and propose module-deepening refactors. |
| [`playwright-capture-flow/`](./skills/playwright-capture-flow/) | Playwright: Capture Flow. |
| [`pr-review-walkthrough/`](./skills/pr-review-walkthrough/) | Build a single-file HTML review walkthrough for one GitHub pull request, so a reviewer understands the change before reading the diff. |
| [`prd-to-issues/`](./skills/prd-to-issues/) | Break a PRD into independently-grabbable GitHub issues using tracer-bullet vertical slices. |
| [`readable-output/`](./skills/readable-output/) | Rewrite a complex answer, conversation, change, or agent run into clear, easy-to-review output - simplified technical English (STE), then a diagram, interactive HTML page. |
| [`refresh-context-pack/`](./skills/refresh-context-pack/) | Build or refresh a fast-load, project-scoped context pack — a compact snapshot of live tracker state (GitLab epics/issues, or an equivalent) plus standing traps and links. |
| [`scaffold-docs-folder/`](./skills/scaffold-docs-folder/) | Create a new project folder or subfolder inside a documentation repo with README scaffolding and index updates. |
| [`scaffold-workspace/`](./skills/scaffold-workspace/) | Create a new project workspace folder with workbench, worktree, workspace CLAUDE.md, and .code-workspace file. |
| [`setup-nvim-tmux/`](./skills/setup-nvim-tmux/) | Set up a macOS development environment with Neovim and tmux, matching Jonathan's config. |
| [`spec-to-issue/`](./skills/spec-to-issue/) | Set up loop-runnable work from a spec: put the spec where the executor can ALWAYS reach it (the GitHub issue body), optionally open a draft review-PR that is closed-not-m. |
| [`structured-backlog/`](./skills/structured-backlog/) | Decompose an implementation plan into structured backlog task files with acceptance criteria and TDD workflows for high-quality AI handoff. |
| [`tdd-pocock/`](./skills/tdd-pocock/) | Test-driven development with red-green-refactor loop. |

Install: `skills/install.sh` (or `--cursor`).

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
