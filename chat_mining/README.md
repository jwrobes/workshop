# chat_mining

Unified CLI for exploring, searching, and analyzing local chat history from both **Claude Code** (JSONL) and **Cursor** (SQLite). Three tools, one shared data model, a configurable taxonomy for LLM-assisted classification.

---

## Quick Start

All three tools are available as CLI wrappers from any directory:

```bash
chat-catalog --since 7 --source claude
chat-search "project a" "feature flag" --since 30
chat-analyze --since 21 --llm gaps
```

---

## Tools

### `chat-catalog` — Browse and rank recent chats

Lists conversations sorted by recent activity. Useful for finding unclosed work or picking up where you left off.

```bash
# Most recent 30 chats across both Claude and Cursor
chat-catalog

# Only Claude Code chats from the last 7 days
chat-catalog --source claude --since 7

# Chats matching a workspace path
chat-catalog --workspace project-a --since 14

# Flag sessions that never got a CONTINUATION_PROMPT (Cursor only)
chat-catalog --unclosed --since 7

# Sort by true creation time (avoids Cursor mtime pollution)
chat-catalog --sort created --limit 20

# Machine-readable output
chat-catalog --json --since 3 > /tmp/recent.json
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--source` | `all` | `cursor`, `claude`, or `all` |
| `--since N` | none | Only chats active in the last N days |
| `--workspace STR` | none | Filter by workspace path substring |
| `--limit N` | 30 | Max rows to show |
| `--min-blobs N` | 4 | Skip trivially short chats |
| `--unclosed` | off | Annotate/filter by CONTINUATION_PROMPT presence (Cursor only) |
| `--sort` | `activity` | `activity` or `created` |
| `--json` | off | Emit JSON |
| `--claude-root PATH` | `~/.claude/projects` | Override Claude projects root |

---

### `chat-search` — Full-text search across all chats

Answers "which chat did I discuss X in?" Scans message content, ranks by match count, returns snippets.

```bash
# Find chats about feature flags in Project A (both terms required)
chat-search "project a" "feature flag"

# Word-boundary match — useful for short acronyms to avoid UUID noise
chat-search -w "API" "validate"

# OR match across topics
chat-search --any "Project A" "Docs" "Tooling"

# Only search your own messages
chat-search --role user "how do I" --since 14

# Recent Claude chats only
chat-search --source claude --since 30 "analytics"

# Sort by recency instead of score
chat-search --sort activity "project-a"

# Pipe to jq
chat-search --json "schema" | jq '.[0].db_path'
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--source` | `all` | `cursor`, `claude`, or `all` |
| `--since N` | none | Only search chats active in the last N days |
| `--workspace STR` | none | Filter by workspace path substring |
| `--any` | off | OR match instead of AND |
| `-s / --case-sensitive` | off | Case-sensitive matching |
| `-w / --word` | off | Whole-word matching (wraps in `\b`) |
| `--role` | all | Restrict to `user`, `assistant`, `system`, or `tool` |
| `--limit N` | 15 | Max matching chats |
| `--snippets N` | 3 | Max context snippets per chat |
| `--sort` | `score` | `score`, `activity`, or `created` |
| `--json` | off | Emit JSON |

---

### `chat-analyze` — Where is your time actually going?

The main analysis tool. Classifies conversations by focus area using keyword rules and/or an LLM, then reports a breakdown of where time is being spent — by topic, week, and work pattern. Designed to surface the gap between where you *think* time is going and where it *actually* is.

```bash
# Default: last 90 days, keyword-only, both sources
chat-analyze

# Last 3 weeks with LLM filling classification gaps
chat-analyze --since 21 --llm gaps

# LLM classifies everything for max accuracy
chat-analyze --since 90 --llm full

# Claude Code only, verbose output
chat-analyze --source claude -v

# JSON output for downstream tooling
chat-analyze --json --since 30

# Use a different config or model
chat-analyze --config ~/other_config.json --model claude-sonnet-4-6
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--since N` | 90 | Days of history to analyze (0 = all) |
| `--source` | `all` | `cursor`, `claude`, or `all` |
| `--llm` | `off` | `off`, `gaps`, `confirm`, or `full` (see below) |
| `--model STR` | from config | Model for LLM classification |
| `--no-cache` | off | Ignore the classification cache |
| `--config PATH` | `~/.config/chat-mining/config.json` | Path to focus-area config |
| `--json` | off | Emit full JSON report |
| `-v / --verbose` | off | Show per-conversation classification |

**LLM modes:**

| Mode | Behavior |
|------|----------|
| `off` | Keywords only — fast, offline, no LLM cost |
| `gaps` | Keywords first; LLM classifies only `Uncategorized` conversations |
| `confirm` | Both run; LLM result wins; disagreements are flagged |
| `full` | LLM classifies everything — slowest, most accurate |

Classification results are cached at `~/.cache/chat_mining_classify.json` (keyed by conversation ID) so re-runs with the same history are fast. Use `--no-cache` to force re-classification.

**Report sections:**

1. **Focus area breakdown** — bar chart of conversation count and percentage per category
2. **Weekly activity** — last 16 weeks, conversations per week by source
3. **Known-items check** — cross-reference against the `known_items` list in your config; surfaces items that never appear in chats
4. **Work pattern** — weekday vs. weekend split, hour-of-day buckets (morning / afternoon / evening / late)
5. **Uncategorized list** — conversations that didn't match any keyword and weren't classified by LLM

---

## Configuration

Your real config lives at `~/.config/chat-mining/config.json` (honors `XDG_CONFIG_HOME`). On first run `chat-analyze` copies `config.example.json` there; edit it to match your own projects. Override with `--config PATH`.

```json
{
  "focus_areas": [
    {
      "name": "Project A",
      "description": "Main product work: features, bug fixes, and architecture",
      "workspace_keywords": ["project-a", "project_a"]
    },
    {
      "name": "Docs",
      "description": "Documentation, READMEs, process notes",
      "workspace_keywords": ["docs"]
    }
  ],
  "known_items": [
    { "name": "Project A Launch", "focus_area": "Project A" },
    { "name": "Weekly Reading Group", "focus_area": "__text:reading group" }
  ],
  "llm": {
    "default_model": "claude-haiku-4-5",
    "batch_size": 25,
    "cache_path": "~/.cache/chat_mining_classify.json"
  }
}
```

**`focus_areas`** — each entry has:
- `name` — label used in reports
- `description` — natural-language description sent to the LLM for classification
- `workspace_keywords` — path substrings checked first (fast, offline)

**`known_items`** — items from your work inventory. Each entry has:
- `name` — display label
- `focus_area` — the focus area it maps to, OR `"__text:keyword"` to match by text keyword instead

**`llm`** — LLM defaults:
- `default_model` — model used when `--model` isn't specified
- `batch_size` — conversations sent to LLM per request
- `cache_path` — where to persist classification results

---

## Data Sources

### Claude Code (`~/.claude/projects/`)

One `.jsonl` file per conversation, stored per-workspace. Records are typed: `user`, `assistant`, `ai-title`, `summary`. Only external user messages are indexed (system messages skipped). Workspace path comes from the explicit `cwd` field — no regex extraction needed.

### Cursor (`~/.cursor/chats/`)

One `store.db` (SQLite) per conversation. Two tables: `blobs` (content-addressable message store) and `meta` (conversation metadata as hex-encoded JSON). Workspace path is extracted from the `<user_info>` block injected into every user message.

### Shared model

Both backends produce the same `ChatRecord` dataclass, so all three tools work identically across sources.

---

## LLM Integration

Classification shells out to a CLI, chosen by the `CHAT_MINING_LLM_CMD` env var:

| Value | Command run |
|-------|-------------|
| unset / `claude` | `claude -p` (system prompt prepended to stdin; `--model` is ignored) |
| `llm` | `llm -m MODEL -s SYSTEM` ([llm](https://llm.datasette.io/)) |
| anything else | run as given; prompt on stdin, system prompt in `$CHAT_MINING_SYSTEM_PROMPT`; reply on stdout |

```bash
CHAT_MINING_LLM_CMD=llm chat-analyze --since 21 --llm gaps
```

All LLM access goes through one function, `run_llm()` in `chat_analyze.py`.

Tests: `python3 -m unittest test_llm_cmd.py`.

## File Guide

| File | Description |
|------|-------------|
| `README.md` | This file |
| `config.example.json` | Template for `~/.config/chat-mining/config.json` (focus areas, known items, LLM defaults) |
| `test_llm_cmd.py` | Tests for the LLM-command wrapper |
| `claude_reader.py` | Shared backend for reading Claude Code's JSONL format. Imported by the other tools; not a standalone CLI. |
| `chat_catalog.py` | Browse and rank chats by recency. Supports `--source`, `--since`, `--workspace`, `--unclosed`, `--sort`, `--json`. |
| `chat_search.py` | Full-text search with snippets. Supports `--source`, `-w`, `--role`, `--any`, `--sort`, `--json`. |
| `chat_analyze.py` | Focus-area analysis with keyword + LLM classification. Supports `--since`, `--llm`, `--model`, `--no-cache`, `--json`. |

---

## CLI Wrappers

Thin wrappers in `~/.local/bin` make the tools available from any directory:

```
~/.local/bin/chat-catalog  →  chat_mining/chat_catalog.py
~/.local/bin/chat-search   →  chat_mining/chat_search.py
~/.local/bin/chat-analyze  →  chat_mining/chat_analyze.py
```

If the scripts move, update the wrapper paths.
