---
name: extract-engineering-style
description: >-
  Extracts coding conventions and review voice from git history and optional
  GitLab/GitHub MR data for named engineers. Use when the user wants to
  understand team style from commits, onboard to a repo, build style guides or
  review personas from engineer history, or says extract style, study commits,
  create style guide from history, or learn from engineers.
---

# Extract Engineering Style

End-to-end workflow for turning **local git history** (and optionally **merge-request discussion**) into **per-engineer profiles**, **team synthesis**, and **Cursor skills** (review personas + project style). Adapt paths, ticket patterns, and file classification to the target stack.

## When to Use

- When you want to understand a codebase's conventions by studying its best engineers
- When onboarding to a new project and want to extract style guides
- When creating code review personas from real engineer history
- User says **"extract style"**, **"study commits"**, **"create style guide from history"**, **"learn from engineers"**

## Prerequisites

- A **local git clone** of the target repository (full history helps)
- **(Optional)** GitLab or GitHub API access for MR/PR comment history
- **Names** of target engineers to study (recommended 1–5)
- **Write access** to an output directory (e.g. `output/` beside your scripts)

## Step 1: Gather Information

Ask the user for:

1. **Repository path** — local git clone location
2. **Target engineers** — display names to study (1–5 engineers)
3. **Focus areas** — backend, frontend, fullstack, infrastructure (filters reading priorities later)
4. **API access** — GitLab project ID or `owner/repo` for GitHub PR comments (or "skip")
5. **Language / stack** — primary language(s) (Ruby, Python, TypeScript, Go, etc.) and framework (Rails, React, …)

Record a working **`ENGINEERS` map** (conceptually; implement in JSON or in-script):

- Stable key: `snake_case` id (e.g. `jane_doe`)
- `display_name`: canonical name
- `git_authors`: list of exact `git log` author names to query (include known aliases)
- `pair_pattern`: optional regex to tag pair-programming commits in author strings (see Step 3)
- For MR extraction: `platform_username` (if known), `email_patterns` or name substrings to match API users

## Step 2: Discover Engineer Identities

From the repo root (or any path; use `git -C <repo>` consistently):

```bash
git -C "<REPO>" log --all --format='%an <%ae>' | sort | uniq -c | sort -rn
```

Cross-reference lines with the user's named engineers. For each engineer, collect:

| Field | How |
|--------|-----|
| **Author name variants** | All `an` strings that plausibly map to the same person (solo and pair) |
| **Email patterns** | Domains and local-parts seen in `%ae` |
| **Active range** | `git log --all --author='<name>' --format=%ai --reverse \| head -1` and same with `tail -1` |
| **Commit count** | `git log --all --author='<name>' --oneline \| wc -l` (repeat per variant; dedupe SHAs later) |

**Pair-heavy repos:** pair commits often appear as `Alice & Bob`, `Alice+Bob`, `pair+alice`, etc. Keep them in the dataset but **flag** `is_pair` so message and diff stats can be segmented (solo vs pair).

## Step 3: Extract Commit Data

This step mirrors a small extraction script pattern (generalized from `extract_commits.py`). Implement as a script **or** execute the same operations manually for a one-off.

### 3.1 Per-author git log (no merges)

- For each `git_authors` entry, run `git log` with:
  - `--all`
  - `--author=<exact author string from log>` (repeat per variant)
  - `--no-merges`
  - `--format` that includes: hash, author name, email, subject, body
  - `-n <max_commits>` (default **500**; use full history if the repo is small)

**Suggested format** (newline-delimited blocks; use a unique end marker):

- `%H`, `%an`, `%ae`, `%s`, `%b`, then a sentinel line (e.g. `---END---`)

Parse into objects: `sha`, `author`, `email`, `subject`, `body`.

### 3.2 Pair flag

Set `is_pair` when the author string matches common pair patterns, e.g. regex like:

- `pair\+`, `&`, or ` and ` (case-insensitive)

Tune for the team's conventions.

### 3.3 Deduplicate

When merging commits from multiple author variants, **dedupe by `sha`**.

### 3.4 Diff stats (sampled)

For **solo** commits (or all, if pair rate is low), take the first **N** commits (default **100**) in log order and for each SHA run:

```bash
git -C "<REPO>" diff-tree --no-commit-id -r --numstat <SHA>
```

Aggregate per commit:

- `files_changed`, `insertions`, `deletions`, per-file `(path, added, deleted)`

From this sample compute:

- **File category counts** (see Step 3.6)
- **Per-file touch counts** (`Counter` over paths)
- **Commit size distribution** (e.g. min/max/avg/median of `insertions + deletions` over the sample)

### 3.5 Commit message analysis (solo commits recommended)

On the solo set, compute:

| Metric | Logic |
|--------|--------|
| **Avg subject length** | Mean character length of `%s` |
| **Ticket refs** | Regex match rate on subject (configure per org; see below) |
| **Has body** | `%` of commits with non-empty body |
| **Imperative mood (heuristic)** | First word of subject (after stripping common prefixes like `[#123]`) in a small verb allowlist: e.g. add, fix, update, remove, refactor, move, change, create, delete, extract, implement, improve, handle, use, set, replace, rename, convert, clean, bump, allow, prevent, ensure, make, introduce, enable, disable, wrap, unwrap, split, merge, revert |

**Configurable ticket regex** (examples — pick what matches the project):

- GitHub: `#\d+`
- Jira-style: `\b[A-Z][A-Z0-9]+-\d+\b`
- Bracketed: `\[#\d+\]`

Store **samples**: ~30 solo subjects; ~15 `{subject, body}` pairs where body is non-empty.

### 3.6 Classify touched files (adapt to language)

Implement `classify_file(path) -> category` using path suffixes and prefixes. **Rails/Ruby example** (replace for other stacks):

- `spec/`, `test/`, `*_spec.rb`, `*_test.rb` → `test`
- `app/models/` → `model`
- `app/controllers/` → `controller`
- `app/services/`, `app/lib/` → `service`
- `app/views/`, `app/assets/` → `view`
- `app/javascript/`, `frontend/`, or `*.tsx?`, `*.jsx?` → `frontend`
- `db/migrate` → `migration`
- `config/` → `config`
- other `*.rb` → `ruby_other`
- else → `other`

### 3.7 JSON output per engineer

Write one JSON file per engineer, e.g. `output/commits/<engineer_key>.json`, containing:

- Engineer metadata (`display_name`, `focus`, `git_authors`, patterns)
- `total_commits`, `solo_commits`, `pair_commits`
- `message_analysis` (aggregates + samples)
- `file_category_distribution`
- `top_touched_files` (e.g. top 50 paths)
- `commit_size_distribution`
- `sample_commits` (subset with `diff_stats` for inspection)

**CLI knobs:** `--max-commits` (default 500), `--diff-sample` (default 100).

## Step 4: Extract Code Artifacts

Use git to ground profiles in **real code** still in the tree.

### 4.1 Files they created

For each author variant:

```bash
git -C "<REPO>" log --all --no-merges --diff-filter=A --author='<AUTHOR>' --name-only --format='' | sort -u
```

Prefer **application** and **test** paths; skip generated/vendor if noisy.

### 4.2 Files they touched most

Use `top_touched_files` from Step 3, or recompute with:

```bash
git -C "<REPO>" log --all --no-merges --author='<AUTHOR>' --name-only --format='' | sort | uniq -c | sort -rn | head -50
```

### 4.3 Curated read list

Per engineer, **read in the editor** (agent: use read_file tools):

- **5–8** representative source files (mix of categories aligned with `focus`)
- **3–4** test files

Prioritize paths that **still exist** at `HEAD` and that appear in both "created" and "high touch" lists when possible.

## Step 5: Extract MR/PR Comments (Optional)

If API access is available, pull **review voice** and **MR/PR description style**. If not, proceed with commit + code only.

### GitLab (e.g. `python-gitlab`)

1. Connect with org-approved config (e.g. `Gitlab.from_config(...)`).
2. **Discover usernames** if unknown: scan recent merged MRs — match `author.name` / `username` / email substrings against `email_patterns` from git.
3. Extract, per engineer:
   - **Comments on a focal user's MRs** — list MRs `author_username=<focal_user>`, iterate notes; skip `system` notes; record MR metadata, body, `created_at`, whether diff-position note when API exposes it.
   - **MR descriptions they authored** — list MRs `author_username=<engineer_username>`, store title, description, URL, dates, branch.
   - **Review comments on others' MRs** — scan recent merged MRs; collect their non-system notes where MR author ≠ engineer (to emphasize review voice).

Persist raw JSON under `output/mr_comments/`. Save `_engineer_usernames.json` for reproducibility.

### GitHub (`gh` CLI or API)

Analogous queries:

- `gh pr list --author <user> --state merged --json ...`
- `gh api repos/{owner}/{repo}/pulls/comments` / review comments endpoints (filter by `user.login`)
- For threads: map PR number, path, and comment body

**Ghost / deactivated accounts:** API may show generic or missing users; fall back to **commit-only** analysis and any cached username map.

## Step 6: Analyze Patterns

For each engineer, produce a **style profile** (markdown) covering:

- **Naming** — methods, variables, classes, modules/packages
- **Organization** — file layout, module boundaries, layering
- **Testing** — what they test, factories/fixtures, assertion style, boundary vs unit
- **Language idioms** — framework patterns (Rails concerns/services, React hooks composition, Go errors, etc.)
- **Error handling** — return values, exceptions, result types, logging
- **Commit discipline** — subject length, ticket format, body usage, typical granularity (informed by diff stats)
- **Representative messages** — **5** commits with bodies (quote verbatim, redact if sensitive)
- **Anti-patterns** — older or outlier commits / files **not** to copy (explain why)
- **Signatures** — phrases, structural habits, or review ticks that distinguish them

Ground claims in **paths, SHAs, or MR links** where possible.

## Step 7: Synthesize

Create three synthesis documents under `output/analysis/`:

1. **`best_practices.md`** — patterns shared by **2+** engineers (label confidence: high when evidenced in multiple independent files/commits)
2. **`anti_patterns.md`** — legacy or inconsistent patterns to avoid, with **preferred modern replacement**
3. **`style_guide.md`** (or `<project>-style.md`) — **actionable** rules for new code: naming, structure, tests, errors, commits

## Step 8: Generate Cursor Skills

Under `output/skills/`, author markdown skills the team can copy into `.cursor/skills/` or `~/.cursor/skills/`:

1. **Per-engineer review personas** — `review-as-<engineer>.md`: "When reviewing, emulate X's priorities and voice; check for …"
2. **Combined review** — `combined-review.md`: checklist merging multiple perspectives (security, UX, API design, etc. as appropriate)
3. **Project style** — `<project>-style.md`: concise conventions for **writing** new code (links back to `style_guide.md` details if needed)

Use each skill's YAML `description` with **trigger terms** so agents discover them.

## Output Structure

```
output/
├── commits/           # Raw commit data per engineer (JSON)
├── mr_comments/       # Raw MR/PR comment data (JSON)
├── analysis/          # Per-engineer profiles + synthesis docs (MD)
│   ├── {engineer}_profile.md
│   ├── best_practices.md
│   ├── anti_patterns.md
│   └── style_guide.md   # optional fourth file from Step 7
└── skills/            # Generated Cursor skills (MD)
    ├── review-as-{engineer}.md
    ├── combined-review.md
    └── {project}-style.md
```

## Language-Specific Analysis Templates

When reading code and writing profiles, emphasize:

### Ruby / Rails

Models (validations, scopes, concerns), callbacks discipline, service objects, jobs (Sidekiq), controller thinness, RSpec style (contexts, let, doubles), migrations

### Python

Type hints, dataclasses/protocols, decorators, package layout, pytest (fixtures, parametrize), docstrings vs comments, explicit errors

### TypeScript / JavaScript

Component structure, hooks rules, state boundaries, type narrowing, module exports, Jest/Vitest patterns, async/error boundaries

### Go

Errors (`fmt.Errorf` / wrapping), interfaces at call site, goroutines/cancellation, table-driven tests, package naming, `internal/`

## Adaptation Notes

- **File classification** — replace `classify_file()` buckets for Django, Next.js, Kotlin, etc.
- **MR providers** — GitHub vs GitLab differ in note types; map "diff discussions" carefully.
- **Scale** — 500 commits/engineer is a good cap for large repos; smaller repos can use `--max-commits` equal to full solo history.
- **Pairs** — include pair commits in totals and optional messaging stats, but **segment** solo vs pair for cleaner defaults.
- **Privacy** — do not paste confidential issue/MR bodies into shared skills; summarize patterns instead.
- **Automation** — parameterize engineer lists and regexes in a small Python script; keep logic aligned with this document so runs are reproducible.

## Quick Reference: Core Git Commands

```bash
# Identity discovery
git -C "<REPO>" log --all --format='%an <%ae>' | sort | uniq -c | sort -rn

# Commits per author (adjust --author string)
git -C "<REPO>" log --all --no-merges --author='Name' -n 500 --format='%H%n%an%n%ae%n%s%n%b%n---END---'

# Numstat for one commit
git -C "<REPO>" diff-tree --no-commit-id -r --numstat <SHA>

# Files added by author
git -C "<REPO>" log --all --no-merges --diff-filter=A --author='Name' --name-only --format='' | sort -u
```
