# speak_to_code

Voice-to-code dictation pipeline for Claude Code and Cursor. Records speech on-device, transcribes locally via Apple Silicon (mlx-whisper), cleans up with an LLM backend of your choice (`llm`, `claude`, or local `ollama`), and lands the result on the macOS clipboard for immediate paste.

**Status:** Alpha — used daily by the author. macOS + Apple Silicon only.

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
LLM backend ── fixes grammar, removes filler words, preserves technical terms
    │           (llm, claude -p, or local ollama)
    ▼
pbcopy ──────── macOS clipboard
    │
    ▼
Claude Code / Cursor ── Cmd-V to paste
```

**Data flow:** Audio never leaves your machine — recording and transcription are fully on-device via SoX and mlx-whisper. The cleaned-up *text* transcript is sent to the cleanup backend you pick (`llm` and `claude` call a hosted model). Use `--backend ollama` for fully local cleanup, or `--raw` to skip the cleanup step entirely and copy the raw transcript.

## Install (new machine)

### 1. Install system dependencies

```bash
brew install sox          # provides the `rec` command
pip install mlx-whisper   # Apple Silicon transcription
```

### 2. Install a cleanup backend

Install at least one. `llm` is the default.

```bash
pip install llm && llm keys set openai    # default backend
# or use your logged-in Claude Code:      dictate --backend claude
# or fully local:                         brew install ollama && ollama pull llama3.2
```

### 3. Run setup.sh

```bash
cd ~/personal/workshop/speak_to_code
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
| a cleanup backend installed | `which llm` (or `claude`, `ollama`) |
| dictate on PATH | `which dictate` |

## Usage

```bash
dictate                              # record, transcribe, clean via llm, copy
dictate --raw                        # skip LLM cleanup — copy raw transcript
dictate --backend ollama             # fully local cleanup (offline / airplane)
dictate --model mlx-community/whisper-medium.en-mlx   # larger model for longer dictations
dictate write a cursor prompt about the auth flow     # context hint for cleanup LLM
dictate --meeting                                     # meeting mode: attribute speakers (see below)
```

### Flags

| Flag | Default | Notes |
|------|---------|-------|
| `--backend` | `llm` | `llm` (Simon Willison's CLI), `claude` (`claude -p`), `ollama` (local) |
| `--model` | `mlx-community/whisper-small.en-mlx` | Any mlx-community `-mlx` whisper variant |
| `--ollama-model` | `llama3.2` | Ollama model for `--backend ollama` |
| `--raw` | off | Skip LLM cleanup entirely |
| `--meeting` | off | Diarize + attribute speakers (meeting mode) — see below |
| `--clean` | off | Meeting mode: LLM-polish the attributed transcript (labels/turns preserved) |
| `--audio FILE` | — | Use an existing recording instead of recording live |
| `--num-speakers N` | auto | Hint the exact number of speakers to diarization |
| `--min-speakers N` / `--max-speakers N` | auto | Bound the speaker count (use for 5–7 person meetings; can't combine with `--num-speakers`) |
| `--out FILE` | — | Also write the final transcript to `FILE` |

### Context hints

Pass words after the flags to give the cleanup LLM a hint about what you're dictating:

```bash
dictate write a GitHub issue for the auth refactor
dictate slack message to a teammate about the sprint priorities
```

## Meeting mode (speaker attribution)

`dictate --meeting` turns the same on-device pipeline into a meeting-notes tool. It diarizes the recording (who spoke when) with `pyannote.audio` running **locally** on Apple Silicon, then emits a speaker-attributed transcript. **Audio never leaves the machine** — diarization is on-device, same as recording and transcription. Only the optional `--clean` step sends the *text* transcript to the LLM (never the audio).

Pipeline: **record → transcribe (mlx-whisper) → diarize (pyannote) → merge by timestamp → relabel → [optional `--clean`] → clipboard.**

### One-time setup

```bash
bash setup.sh --meeting-deps
```

This installs `pyannote.audio` into an isolated venv (`~/.local/share/dictate-diarize/.venv`), separate from the core dictate install. pyannote's models are **gated** — accept the contact-info form on all **three** repos, then log in once:

- https://huggingface.co/pyannote/speaker-diarization-3.1
- https://huggingface.co/pyannote/segmentation-3.0
- https://huggingface.co/pyannote/speaker-diarization-community-1

```bash
hf auth login   # paste a READ token from https://huggingface.co/settings/tokens
```

The token authorizes a **one-time** model download (~31 MB). Diarization runs fully offline afterward (verified with `HF_HUB_OFFLINE=1`).

### Usage

```bash
dictate --meeting                       # record a meeting, attribute speakers, relabel at the end
dictate --meeting --audio call.wav      # attribute an existing recording (skips recording)
dictate --meeting --clean               # attribute, then LLM-polish (labels + turns preserved)
dictate --meeting --num-speakers 3      # hint the exact speaker count to diarization
dictate --meeting --min-speakers 5 --max-speakers 7   # larger meeting, count uncertain
dictate --meeting --out notes.md        # also write the transcript to a file
```

By default meeting mode emits a **verbatim** attributed transcript (no LLM cleanup). In an interactive terminal you're prompted at the end to map each `SPEAKER_00` → a real name (blank keeps the label). With `--clean`, the transcript is polished by the LLM — filler removed, grammar fixed — while **every speaker label and turn boundary is preserved**, and `~/.config/dictate/context.md` is applied for proper nouns.

### Notes & limitations

- **Your recording is kept.** Unlike single-voice dictation (throwaway), meeting recordings are saved to `~/.config/dictate/recordings/meeting-<timestamp>.wav` (override with `DICTATE_RECORDINGS_DIR`) and printed before processing — so a meeting can't be lost to a mid-pipeline error, and you can re-run attribution later with `--audio`.
- **Speed:** on an M1 Max, diarization runs ~30× faster than realtime on the GPU (MPS) — a 34-min recording processes in ~70s. Set `DICTATE_DIARIZE_DEVICE=cpu` to force CPU (slower, ~0.7× realtime).
- **Overlapping speech** and very short interjections can be mislabeled; the end-of-run relabel fixes names, and `--clean` improves readability.
- Very long meetings may exceed the cleanup model's output limit under `--clean`; the raw attributed transcript is always the reliable fallback.

## Context file

`~/.config/dictate/context.md` is a small markdown file prepended to every LLM cleanup call. It teaches the model your proper nouns, team names, and current focus — so "Cloud" becomes "Claude" and "surcharge care team" becomes "SuperCharged Care Team".

Edit it directly:

```bash
$EDITOR ~/.config/dictate/context.md
```

See `dictate-context.md.example` in this folder for a starter template.

**Keep it under ~400 tokens** (~1600 chars). Larger files add measurable latency.

## Backends

| Backend | Command | When to use |
|---------|---------|-------------|
| `llm` (default) | Simon Willison's `llm` | Any hosted model via your own API key |
| `claude` | `claude -p` | You already use Claude Code; no extra key |
| `ollama` | `ollama run` | Offline, airplane, no text leaves the machine |

**Privacy note:** `llm` and `claude` send the transcript text to a hosted model. For sensitive content, use `ollama`.

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

## Session context

`dictate --session` prepends a distilled summary of your active Claude Code session to the cleanup prompt. This resolves references like *"that function"* or *"the service we discussed"* without forcing you to re-state context you already typed.

### Writer / reader split

- **Writer (hook):** `bin/dictate-session-hook` is registered as a Claude Code `Stop` event hook. After each assistant turn, it reads the transcript, distills it to ~300 tokens via `claude -p` (fallback: `llm`), and writes `~/.config/dictate/sessions/<cwd-hash>.md`. The hook is non-blocking (forks a background process) and throttled to at most once per 120 seconds.
- **Reader (dictate):** when `--session` is passed, `dictate` reads the distilled file for `$PWD`, strips frontmatter, and appends it to the cleanup prompt.

### Why opt-in by default

You often dictate Slack messages, GitHub issues, or unrelated content from the same terminal as a coding session. Auto-attaching would leak coding context into unrelated dictations. Explicit `--session` is the only safe default.

### Install the hook

```bash
bash setup.sh     # answers "y" to "Install dictate session hook?"
```

Or add manually to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [{"command": "/path/to/speak_to_code/bin/dictate-session-hook", "timeout": 5}]
  }
}
```

For Cursor, add the same entry to `~/.cursor/hooks.json`.

To uninstall: `bash setup.sh --uninstall-hook`

### Session flags

| Flag | Behavior |
|------|----------|
| `--session` | Include distilled session context for `$PWD` |
| `--no-session` | Explicit override (for when you flip the default later) |
| `--session-cwd <path>` | Use a different directory's session file |
| `--gc-sessions` | Remove session files older than 24h, exit |

```bash
dictate --session                              # include session for $PWD
dictate --session --session-cwd ~/other-repo   # use a different repo's session
dictate --gc-sessions                          # sweep stale session files
```

---

## Context library

Load topic-specific vocabulary bundles on demand via `--context`. Each bundle is a small markdown file (≤400 tokens) that primes the cleanup LLM with proper nouns, team names, and current focus for one domain.

### Storage layout

```
~/.config/dictate/
├── context.md             # global, always loaded
└── contexts/
    ├── myproject.md       # project vocabulary and service names
    └── gitlab-issues.md   # issue-writing voice and templates
```

Bundle names are slugs `[a-z0-9-]+`. `~/.config/dictate/contexts/` is empty by default — use `--generate-context` or hand-write bundles.

### CLI surface

```bash
# Per-call bundle selection
dictate --context myproject                    # load one bundle
dictate --context myproject,gitlab-issues      # load multiple in order

# List installed bundles
dictate --list-contexts

# Generate a bundle from a docs folder or file
dictate --generate-context myproject --from ~/workspace/myproject/docs
dictate --generate-context myproject-api --from ~/workspace/myproject/services/api

# Regenerate an existing bundle (will warn if hand-edited)
dictate --generate-context myproject --from ~/workspace/myproject/docs --force

# Debug: print assembled prompt without recording
dictate --show-context --session --context myproject,gitlab-issues
```

### Generation flow

`--generate-context` walks `--from` (file or directory), collects up to 50 files / 200KB, and distills them into a bundle via `claude -p` (fallback: `llm`). Prefers READMEs, design docs, `vocabulary.md`, and `glossary.md` when walking directories. Writes the result with frontmatter to `~/.config/dictate/contexts/<name>.md`.

### Hand-edit detection

Bundles carry `hand_edited: false` in frontmatter. The first time you modify a generated bundle outside of `--generate-context`, `dictate` detects that the file's mtime is newer than `generated_at` and flips the flag to `hand_edited: true`. A subsequent `--force` regeneration shows a loud warning before overwriting.

### Starter templates

`dictate-context-bundles.example/` in this folder contains starter templates for a project vocabulary and GitLab issue writing. Copy and edit them:

```bash
cp speak_to_code/dictate-context-bundles.example/myproject.md.example ~/.config/dictate/contexts/myproject.md
$EDITOR ~/.config/dictate/contexts/myproject.md
```

### Context budget

All context sources combined are capped at 6500 chars (sources 1–3 below):

| # | Source | Typical size | When loaded |
|---|---|---|---|
| 1 | `context.md` | ≤1600 chars | Always |
| 2 | `--context` bundles | ≤1600 chars each | When `--context` is passed |
| 3 | Session distillation | ≤1200 chars | When `--session` is passed |
| 4 | Raw transcript | ~100–500 chars | Always (not counted in cap) |

When over the cap, `dictate` drops sources in order: session first, then oldest bundles, never `context.md`. It always prints a visibility line:

```
Context: 5840 chars (context.md + myproject + session). Within budget.
```

## Related

- [`sharpen_prompt/`](../sharpen_prompt/) — `dictate --to-sharpen` sends a spoken draft into a paired sharpen session
- [`cli_ready_alerts/`](../cli_ready_alerts/) — session stash that feeds the session-aware context
