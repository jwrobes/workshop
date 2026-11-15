---
name: gh-pr-create
description: Create GitHub pull requests with structured descriptions via the gh CLI. Use when the user says "create pr", "open pr", "submit pr", "push and create pr", or "draft pr".
---

# Create a GitHub Pull Request

A small recipe-style skill for opening clean PRs from the command line
via [`gh`](https://cli.github.com/). Optimized for personal projects:
draft-first, body-from-file, structured template.

## When to Use

Triggers:

- "create pr"
- "open pr"
- "submit pr"
- "push and create pr"
- "draft pr"

## Prerequisites

- `gh` CLI installed and authenticated (`gh auth status` shows green)
- Branch is committed and ready to push
- You have push access to the target repo (or are working on a fork)

## Workflow

### 1. Confirm the branch state

```bash
git status                               # working tree clean?
git log --oneline {base}..HEAD           # are these the commits you mean?
git diff {base}...HEAD --stat            # roughly the change shape you expect?
```

If commits need cleanup (squash, reword, reorder), do that **before**
opening the PR — much cheaper than amending after review starts.

### 2. Push the branch

```bash
git push -u origin HEAD
```

The `-u` sets up tracking so future `git push` / `git pull` work without
arguments.

### 3. Compose the PR body in a file

Don't pipe complex bodies through `--body "$(...)"` — markdown breaks in
weird ways. Use a temp file:

```bash
cat > /tmp/pr-body.md <<'EOF'
{Summary paragraph: what this PR does and why, 2–3 sentences}

{Technical detail:
- Architecture chosen and why
- Key components added/modified
- Integration points
- Feature flags}

## Test Plan

- [ ] {testable step 1}
- [ ] {testable step 2}

## Review Notes

{Anything the reviewer should scrutinize, defer, or override}

Closes #{issue_number}
EOF
```

### 4. Open the PR (draft by default)

```bash
gh pr create \
  --base main \
  --head $(git rev-parse --abbrev-ref HEAD) \
  --draft \
  --title "{imperative summary} (closes #{issue_number})" \
  --body-file /tmp/pr-body.md
```

Opening as draft is the safer default — it lets you self-review the
diff in the GitHub UI before flagging it for human eyes.

### 5. Self-review the diff

Open the PR URL `gh pr create` returns. Walk the diff once with the
checklist that lives in your head (or `code-review` if installed).
Common things to catch on self-review:

- Stray `console.log` / `binding.pry` / debug prints
- Files committed that shouldn't be (`.env.local`, `.idea/`, etc.)
- Generated artifacts that should be regenerated, not edited
- Commit subjects that drift from the actual change

### 6. Mark ready for review

```bash
gh pr ready
```

Or, if there are issues you spotted during self-review, fix them in
new commits (or amend), `git push`, and only then mark ready.

## Title Conventions

Strong defaults for personal projects:

| Pattern | Use when |
|---------|----------|
| `{imperative verb} {what}` | Most changes — `Add session expiry guard`, `Fix race in retry handler` |
| `{verb} {what} (closes #N)` | When the PR closes one specific issue |
| `[refactor] {what}` | Pure refactor; reviewer should expect zero behavior change |
| `[wip] {what}` | Stays as draft; signals "not for review yet" |

Keep titles ≤ ~70 characters. Move detail to the body.

## Body Template

A reusable template you can paste at the top of `/tmp/pr-body.md`:

```markdown
{Summary paragraph}

## Why

{Context, motivation, prior art, links}

## Approach

{What changed, in what order, and why}

## Test Plan

- [ ] {step}
- [ ] {step}

## Risk / Rollback

{What could go wrong; how to undo}

## Review Notes

{Anything the reviewer should scrutinize}

Closes #{issue_number}
```

## Common Variations

### Open against a fork

```bash
gh pr create \
  --repo upstream-owner/upstream-repo \
  --head my-fork-owner:branch-name \
  --base main \
  --draft \
  --title "..." \
  --body-file /tmp/pr-body.md
```

### Open non-draft (small / trivial change)

Drop `--draft`. Reserve this for changes you'd be comfortable merging
without a self-review pass — typo fixes, doc updates, dependency bumps
where the test suite carries the weight.

### Re-target the base branch

If you opened against `main` and need `release-2.x`:

```bash
gh pr edit {pr_number} --base release-2.x
```

## Anti-Patterns

- **Opening non-draft on a 500-line change without self-review.** Reviewer time is more expensive than yours.
- **Empty PR body.** "I'll fill it in later" — you won't, and the reviewer pays the cost.
- **Multiple unrelated changes in one PR.** Split first; the review will be faster and the revert cheaper.
- **Long-lived branches that diverge for weeks.** Rebase or open a smaller PR; large diffs get rubber-stamped.

## Output

After this skill runs you should have:

- A pushed branch tracking origin
- A draft PR open with a structured description
- A self-reviewed diff
- A PR marked ready for review (when validation is clean)
