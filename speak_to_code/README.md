# speak_to_code

Voice-to-code dictation pipeline for Claude Code and Cursor. Records speech on-device, transcribes locally via Apple Silicon (mlx-whisper), cleans up with the `llm` CLI, and lands the result on the macOS clipboard for immediate paste.

**Status:** Alpha — Jon uses this daily. macOS + Apple Silicon only.

## What it does

```
Microphone
    │
    ▼
rec (SoX) ──── records until Ctrl-C
    │
    ▼
mlx-whisper ── on-device transcription (no cloud, no privacy concerns)
    │
    ▼
llm ─────────── fixes grammar, removes filler words, preserves technical terms
    │
    ▼
pbcopy ──────── macOS clipboard
    │
    ▼
Claude Code / Cursor ── Cmd-V to paste
```

## Install (new machine)

### 1. Install system dependencies

```bash
brew install sox          # provides the `rec` command
pip install mlx-whisper   # Apple Silicon transcription
```

### 2. Install llm

The default backend uses Simon Willison's [`llm`](https://llm.datasette.io/) CLI:

```bash
pip install llm
llm keys set openai       # or any supported provider
```

`llm` supports OpenAI, Anthropic, Gemini, and local models via plugins. Any model that accepts a system prompt will work.

### 3. Run setup.sh

```bash
cd speak_to_code
bash setup.sh
```

This symlinks `~/.local/bin/dictate` → the `dictate` script in this folder and seeds `~/.config/dictate/context.md` from the example template if it doesn't exist yet.

### 4. First run

The first run downloads the whisper model (~300MB). Expect a 30–60s pause on first transcription — subsequent runs are cached and fast (~2–5s).

```bash
dictate --raw    # test recording + transcription only (skips LLM cleanup)
dictate          # full pipeline
```

### Preflight checklist

| Check | Command |
|-------|---------|
| sox installed | `which rec` |
| mlx_whisper installed | `which mlx_whisper` |
| llm installed | `which llm` |
| llm key set | `llm keys` |
| dictate on PATH | `which dictate` |

## Usage

```bash
dictate                              # record, transcribe, clean via llm, copy
dictate --raw                        # skip LLM cleanup — copy raw transcript
dictate --backend ollama             # fully local cleanup (off-VPN / airplane)
dictate --model mlx-community/whisper-medium.en-mlx   # larger model for longer dictations
dictate write a cursor prompt about the auth flow     # context hint for cleanup LLM
```

### Flags

| Flag | Default | Notes |
|------|---------|-------|
| `--backend` | `llm` | `llm` (Simon Willison's CLI), `ollama` (local) |
| `--model` | `mlx-community/whisper-small.en-mlx` | Any mlx-community `-mlx` whisper variant |
| `--ollama-model` | `llama3.2` | Ollama model for `--backend ollama` |
| `--raw` | off | Skip LLM cleanup entirely |

### Context hints

Pass words after the flags to give the cleanup LLM a hint about what you're dictating:

```bash
dictate write a GitLab issue for the auth refactor
dictate slack message to the team about sprint priorities
```

## Context file

`~/.config/dictate/context.md` is a small markdown file prepended to every LLM cleanup call. It teaches the model your proper nouns, team names, and current focus — so "Cloud" becomes "Claude" and transcription errors on project names get corrected.

Edit it directly:

```bash
$EDITOR ~/.config/dictate/context.md
```

See `dictate-context.md.example` in this folder for a starter template.

**Keep it under ~400 tokens** (~1600 chars). Larger files add measurable latency.

## Backends

| Backend | Command | When to use |
|---------|---------|-------------|
| `llm` (default) | Simon Willison's `llm` CLI | Any API key — OpenAI, Anthropic, Gemini, etc. |
| `ollama` | `ollama run` | Fully offline / no API key needed |

### Ollama setup (optional)

```bash
brew install ollama
ollama pull llama3.2
dictate --backend ollama    # test it
```

## Whisper model variants

Always use the `-mlx` suffix variants — the non-suffix variants (`whisper-small.en`, `whisper-base.en`) are gated on HuggingFace and return 401 without an account.

| Model | Size | Speed | Quality | Use for |
|-------|------|-------|---------|---------|
| `mlx-community/whisper-base.en-mlx` | ~150MB | fastest | good | Quick one-liners |
| `mlx-community/whisper-small.en-mlx` | ~300MB | fast | better | Default — daily use |
| `mlx-community/whisper-medium.en-mlx` | ~700MB | moderate | best | Long dictations (>30s) |

## Planned next phase

**Session-aware context:** `dictate` will optionally pull the last N lines from the active Claude Code session (via `cli_ready_alerts` context stash) or Cursor session (via `cursor_chat_mining` SQLite) and prepend them to the cleanup prompt alongside `context.md`. This gives the cleanup LLM live session awareness — resolving "that function" or "the service we discussed" — with no extra LLM calls.

## Related

- [`cli_ready_alerts/`](../cli_ready_alerts/) — session stash that will feed the session-aware context phase
- [`cursor_chat_mining/`](../cursor_chat_mining/) — Cursor SQLite reader for the same future phase
