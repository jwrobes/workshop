# Ship Phase

Push the branch, open a draft PR with a complete execution log, and
mark it ready for review when validation is green. Post the execution
history as a comment on the issue.

## Pre-conditions

- Validate phase complete (all layers passed)
- Code committed in the worktree
- Execution log accumulated from all previous phases
- Access to `~/workspace/skills/gh-pr-create/SKILL.md`

## Step 0: Resolve the Target Repo and Base

Two facts come from the checkout and its remote, not from assumption.

**Target repo.** The PR goes where the code lives. Derive it from the
worktree's remote, which may differ from the issue's repo (e.g. an issue in a
tracker repo against code in another repo):

```bash
git -C {worktree_path} remote get-url origin
# git@github.com:owner/repo.git  or  https://github.com/owner/repo.git  ->  owner/repo
```

Strip a trailing `.git`. Call it `{target_repo}` and pass `--repo {target_repo}`
to every `gh pr` command below. If there is no `origin`, or it is not a GitHub
URL, stop and report; do NOT fall back to the issue's repo. The issue's repo
stays `{owner/repo}`, used for issue comments and labels. When the two differ,
the PR body closes the issue with the full reference (`Closes owner/repo#NNN`),
and commit subjects use that same form.

**Base branch.** The remote decides what the PR diffs against. A local default
branch that drifted ahead of the remote inflates the commit count with commits
the PR will not contain.

```bash
cd {worktree_path}
git fetch origin
git symbolic-ref --short refs/remotes/origin/HEAD     # e.g. origin/main
```

Strip the leading `origin/` to get `{default_branch}` (if the ref is unset,
use `gh repo view {target_repo} --json defaultBranchRef --jq .defaultBranchRef.name`).
Treat `origin/{default_branch}` as the base for every comparison, rebase, and
`--base` below; never hardcode `main`. Flag drift, do not fix it:

```bash
git rev-list --left-right --count {default_branch}...origin/{default_branch}
```

Anything other than `0	0` means the local branch diverged from the remote.
Say so in the final report; never reset or merge to "fix" it here.

## Step 1: Prepare Commits

```bash
cd {worktree_path}
git log --oneline origin/{default_branch}..HEAD
git rev-list --count origin/{default_branch}..HEAD    # the PR's commit count
```

Verify commits follow project conventions:

- Issue reference where the team expects it (e.g., `#NNN` in subject or body)
- Imperative mood subject lines
- Body on non-obvious changes ("why" + tradeoffs)

If commits need cleanup, reorganize with interactive rebase or amend.
Check `CONTRIBUTING.md` for project conventions.

## Step 2: Rebase onto the Default Branch

Before pushing, make sure the branch is current with `origin/{default_branch}`
— it may have moved during the run (e.g. a sibling leaf merged), which would make this PR
conflict or carry duplicate commits.

```bash
cd {worktree_path}
git fetch origin {default_branch}

# Is this branch behind / stacked on something already merged?
git log --oneline origin/{default_branch}..HEAD     # should be ONLY this issue's commits
```

If the branch was correctly cut from the default branch (per `plan.md` Step 1), the log
shows just this issue's commits and a rebase is a fast no-op. If it shows a
**sibling leaf's commits too**, the branch was stacked — rebase to drop them:

```bash
git rebase origin/{default_branch}
# Already-merged sibling commits drop out automatically (same patch-id).
# If a genuine conflict surfaces, resolve it, `git rebase --continue`,
# then RE-RUN the validation suite (Layer 1 tests) before pushing —
# a rebase can silently break a merge.
```

Re-confirm green:

```bash
{test_command}            # must still pass after the rebase
```

## Step 2.5: Local Review Gate (advisory)

Before pushing, get a fresh-eyes review of the committed branch, the same
review a human or CI reviewer would give, while fixes are still cheap. This
is **advisory**: record the result, never block shipping on it.

Skip, noting the reason in the log, if `claude` is not on PATH, the diff
against `origin/{default_branch}` is empty, or HEAD is behind it (rebase
first). A skip is a result to report, not something to work around.

Run a separate `claude -p` process in the worktree so the reviewer shares no
context with this run. It reads the committed diff, not the working tree:

```bash
cd {worktree_path}
claude -p "Use the code-review skill (~/workspace/skills/code-review/SKILL.md) \
to review the committed diff: git diff origin/{default_branch}...HEAD. \
Read-only: do not edit files. Report a verdict (approve | comment | \
request_changes) and findings sorted most to least severe, each with severity \
(critical | major | minor | info), file:line, and what to change. Any critical \
or major finding means request_changes; only minor/info means comment; none \
means approve. Your final message is the review." \
  --allowedTools "Read,Grep,Glob,Bash(git diff:*),Bash(git log:*),Bash(git show:*)" \
  > /tmp/local-review.md
```

Findings are an opinion, not fact. Check each claim against the code before
acting, especially claims about which callers or code paths are affected, and
say plainly when a finding is mistaken. Fix confirmed critical/major findings
with a new commit and re-run the tests, or list them under "Review Notes" in
the PR body. Record the verdict and counts by severity in the execution log
and the PR description.

## Step 2.7: Push

```bash
git push -u origin HEAD --force-with-lease   # --force-with-lease only if rebased
```

> Why this lives here: branching off `main` (plan.md Step 1) prevents stacking
> *up front*; this rebase is the **backstop** for when `main` moved mid-run or a
> dependency forced a stack. The orchestrator resolves its own branch currency
> rather than handing a `CONFLICTING` PR to the human.

## Step 3: Compose PR Description

Build the description from the execution log + validation results:

```markdown
{Summary paragraph — what this PR does and why, 2–3 sentences}

{Multi-line technical description of the approach:
- Architecture chosen and why
- Key components added/modified
- Integration points
- Feature flags}

### Observability
- **Logs:** {what gets logged and at what level}
- **Metrics:** {metrics added}
- **Traces:** {external tracing if applicable}

### Config
- {config files added or modified}
- Feature flag: `{flag_name}` (if any)

Closes #{issue_number}      <!-- Closes owner/repo#N when the issue is in another repo -->

## Validation Results

- **Tests:** {pass_count} passing ({new_count} new)
- **ACs:** {covered}/{total} verified
- **Review score:** {band} ({pct}%)
- **Local review:** {verdict} ({critical}/{major}/{minor} findings) or skipped: {reason}
- **E2E:** {pass/fail/n/a}

## Test Plan

- [ ] {test step derived from ACs}
- [ ] {test step derived from ACs}
- [ ] {E2E validation step}

## Review Notes

{Should-fix items deferred to human reviewer}
{Consider items noted}
{Any medium-confidence decisions flagged for override}

<details>
<summary>Orchestrator Execution Log</summary>

{Full execution log from all phases:
- Intake summary
- Enrich summary (decisions, confidence, patterns evaluated)
- Plan summary (task count, parallel groups)
- Execute summary (strategy, test results)
- Validate summary (all four layers)}

</details>
```

## Step 3.5: Comprehension Artifact (optional, strongly encouraged)

Before opening the PR, decide whether this change warrants a **comprehension
artifact** — a "what I built" HTML page so the human can review from a phone
without pulling code. This is the output-explainer half of decision #9.

Read `~/workspace/skills/comprehension-artifact/SKILL.md` and run its gate:

- **Multi-file / new capability / new external surface (API, tool, skill) /
  non-obvious design → render it.** Strongly encouraged, not mandatory.
- **Trivial (single-file fix, rename, dep bump, docs) → skip**, but say so
  explicitly in the PR body ("comprehension artifact: skipped (trivial)") so the
  reviewer knows it was a judgment call.

When it applies, the skill:
1. writes `docs/{slug}.html` into the **work-repo** (commit it with the change),
2. returns a `## What I built` PR-body section (splice it into Step 3's body —
   the link with three lines of context, inline in the PR),
3. reports GitHub Pages status (enable serving from `docs/` on `main` if in
   reach, else note as a follow-up).

If the change has a **live contract a human verifies after merge** (a new tool
surface, an external write path), the artifact is where the **tiered smoke
checklist** lives (reads / reversible writes / one-time semantic checks) — see
the `openclaw-is-the-smoke-harness` pattern. Don't also paste a second copy
elsewhere; the artifact carries it.

> Why a gate, not a hard block: a strong run can ship correct code without it,
> and forcing it on trivial fixes is noise. But for new-capability work it is the
> single highest-leverage thing for low-burden review — the email-triage run
> (#105) shipped good code and skipped it, which is exactly the miss this step
> exists to prevent.

## Step 4: Create the Draft PR

Read `~/workspace/skills/gh-pr-create/SKILL.md` for the exact `gh pr create`
recipe. The orchestrator opens the PR as a **draft** initially:

```bash
cat > /tmp/pr-body.md <<'EOF'
{Composed description from Step 3}
EOF

gh pr create \
  --repo {target_repo} \
  --base {default_branch} \
  --head {branch_name} \
  --draft \
  --title "{summary of change} (closes #{issue_number})" \
  --body-file /tmp/pr-body.md
```

Record the PR URL.

## Step 5: Mark PR Ready for Review

If all validation layers passed cleanly, mark the PR ready:

```bash
gh pr ready {pr_number} --repo {target_repo}
```

If any layer was deferred (e.g., should-fix items left for human, or
E2E was n/a with no hook), keep the PR as draft and note that in the
issue comment in Step 6.

## Step 6: Post Execution Summary to Issue

If the comment write is denied or fails, apply the **Outward-Write Fallback**
in `guardrails.md`: save the body to `{git_dir}/orchestrator/issue-summary.md`, print
the runnable `gh issue comment` command, and continue. Do not block.

```bash
gh issue comment {NNN} --repo {owner/repo} --body "$(cat <<EOF
## Orchestrator Complete

**PR:** ${PR_URL}
**Branch:** \`${BRANCH}\`
**Status:** ${PR_STATUS}  (draft / ready for review)

### What was built
${ONE_PARAGRAPH_SUMMARY}

### Decisions made
| Decision | Choice | Confidence |
|----------|--------|------------|
| ${DECISION} | ${CHOICE} | ${TIER} |

### Validation
- Tests: ${PASS_COUNT} passing (${NEW_COUNT} new)
- Acceptance criteria: ${COVERED}/${TOTAL} verified
- Code review: ${BAND}
- E2E: ${E2E_RESULT}

### For reviewer
${HUMAN_FLAGS}
EOF
)"
```

## Step 6.5: Surface Newly-Unblocked Downstream Issues

This PR `Closes #{issue}`. When a human merges it, that issue closes and any
issue that was **blocked by it** may become runnable. The orchestrator doesn't
merge (human gate), so it can't flip labels at merge time — but it **can report
what will unblock**, so the next loop tick (or the human) promotes them.

Find issues this one blocks, and whether closing it clears their last blocker:

```bash
# Issues that list THIS issue as a blocker:
gh api repos/{owner/repo}/issues/{NNN}/dependencies/blocking \
  --jq '.[] | "#\(.number) \(.title)"'

# For each, after this PR merges, check if it has any OTHER still-open blocker:
gh api repos/{owner/repo}/issues/{BLOCKED_N}/dependencies/blocked_by \
  --jq '[.[] | select(.state=="open" and .number != {NNN})] | length'
# 0 → it becomes fully unblocked when this merges → promote to `ready`
```

Note the result in the issue comment (Step 6) and the final report so the
queue can be kept honest:

```markdown
### Unblocks on merge
- #{B} — becomes `ready` (no other open blockers)
- #{C} — still blocked by #{D}
```

> Promotion itself (adding `ready` to newly-unblocked issues) is left to the
> human or a merge-triggered automation, since the orchestrator stops before
> merge. The dependency gate in `intake.md` is the backstop if a blocked issue
> is picked up anyway.

## Step 6.7: Verify the Deployed Artifact (continuously-deployed projects)

**Applies when** the merge/push actually deploys something a user hits — a
site, an app, a service. **Skip** where merging only lands code.

Green CI means *the build succeeded*, not *the thing works*. A deploy can be
"successful" and still serve a broken page: the build passes, the workflow goes
green, the artifact uploads — and the live URL renders unusable. That gap is
where a bad deploy can sit unnoticed until a human happens to look.

If the project has a `.visual.json` with a `url`, re-run the check against the
**live** deployment once it finishes:

```bash
gh run watch {run_id} --repo {owner/repo} --exit-status
VISUAL_URL={url from .visual.json} npm run check:visual   # or the manifest's command
```

Otherwise do the minimum by hand — and do it the way a **browser** would, not
by fetching URLs you composed yourself:

```bash
# Fetch the page, then resolve every asset link RELATIVE TO THE PAGE URL.
curl -s "$URL" | grep -oE '(href|src)="[^"]+"'   # what the page actually asks for
```

> Fetching an asset at the URL you *believe* it lives at proves nothing. The
> only URLs that matter are the ones the page emits. This distinction is what
> separated "verified" from "actually working" in the #6 failure.

| Result | Action |
|--------|--------|
| Live artifact renders correctly | Note the verified URL in the final report. |
| Live artifact is broken | **Say so plainly and immediately.** File a bug issue with the root cause, and fix it through the normal issue→PR flow. Do not quietly hot-patch the mainline. |

Record in the execution log: the live URL, what was asserted against it, and
the result.

## Step 7: Final Report

```text
Full-path orchestrator complete.

  Issue:     {repo}#{number} — {title}
  PR:        {pr_url} ({draft|ready})
  Branch:    {branch_name} ({commit_count} commits vs origin/{default_branch})
  Worktree:  {worktree_path}

  Tasks:     {completed}/{total}
  Tests:     {pass_count} passing ({new_count} new)
  ACs:       {covered}/{total} verified
  Review:    {band} ({pct}%)
  Local review: {verdict} / skipped
  E2E:       {pass/fail/n/a}
  Drift:     {none | local {default_branch} diverged from remote}

  Decisions: {high_count} high-confidence, {medium_count} medium (flagged)
  Blocks:    {block_count} encountered, {resolved_count} resolved

Review the PR when ready.
```

## Output

- Target repo and base branch derived from the remote
- Local review verdict recorded (advisory)
- Branch pushed to origin
- PR created (draft) with execution log in description
- PR marked ready for review (if validation fully clean)
- Summary comment posted on issue
- Final report presented to user
- Proceed to `retrospect.md`
