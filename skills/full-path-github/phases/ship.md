# Ship Phase

Push the branch, open a draft PR with a complete execution log, and
mark it ready for review when validation is green. Post the execution
history as a comment on the issue.

## Pre-conditions

- Validate phase complete (all layers passed)
- Code committed in the worktree
- Execution log accumulated from all previous phases
- Access to `~/workspace/skills/gh-pr-create/SKILL.md`

## Step 1: Prepare Commits

```bash
cd {worktree_path}
git log --oneline main..HEAD
```

Verify commits follow project conventions:

- Issue reference where the team expects it (e.g., `#NNN` in subject or body)
- Imperative mood subject lines
- Body on non-obvious changes ("why" + tradeoffs)

If commits need cleanup, reorganize with interactive rebase or amend.
Check `CONTRIBUTING.md` for project conventions.

## Step 2: Rebase onto main, then Push

Before pushing, make sure the branch is current with `main` — `main` may have
moved during the run (e.g. a sibling leaf merged), which would make this PR
conflict or carry duplicate commits.

```bash
cd {worktree_path}
git fetch origin main

# Is this branch behind / stacked on something already merged?
git log --oneline origin/main..HEAD     # should be ONLY this issue's commits
```

If the branch was correctly cut from `main` (per `plan.md` Step 1), the log
shows just this issue's commits and a rebase is a fast no-op. If it shows a
**sibling leaf's commits too**, the branch was stacked — rebase to drop them:

```bash
git rebase origin/main
# Already-merged sibling commits drop out automatically (same patch-id).
# If a genuine conflict surfaces, resolve it, `git rebase --continue`,
# then RE-RUN the validation suite (Layer 1 tests) before pushing —
# a rebase can silently break a merge.
```

Re-confirm green, then push:

```bash
{test_command}            # must still pass after the rebase
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

Closes #{issue_number}

## Validation Results

- **Tests:** {pass_count} passing ({new_count} new)
- **ACs:** {covered}/{total} verified
- **Review score:** {band} ({pct}%)
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
  --repo {owner/repo} \
  --base main \
  --head {branch_name} \
  --draft \
  --title "{summary of change} (closes #{issue_number})" \
  --body-file /tmp/pr-body.md
```

Record the PR URL.

## Step 5: Mark PR Ready for Review

If all validation layers passed cleanly, mark the PR ready:

```bash
gh pr ready {pr_number} --repo {owner/repo}
```

If any layer was deferred (e.g., should-fix items left for human, or
E2E was n/a with no hook), keep the PR as draft and note that in the
issue comment in Step 6.

## Step 6: Post Execution Summary to Issue

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

## Step 7: Final Report

```text
Full-path orchestrator complete.

  Issue:     {repo}#{number} — {title}
  PR:        {pr_url} ({draft|ready})
  Branch:    {branch_name}
  Worktree:  {worktree_path}

  Tasks:     {completed}/{total}
  Tests:     {pass_count} passing ({new_count} new)
  ACs:       {covered}/{total} verified
  Review:    {band} ({pct}%)
  E2E:       {pass/fail/n/a}

  Decisions: {high_count} high-confidence, {medium_count} medium (flagged)
  Blocks:    {block_count} encountered, {resolved_count} resolved

Review the PR when ready.
```

## Output

- Branch pushed to origin
- PR created (draft) with execution log in description
- PR marked ready for review (if validation fully clean)
- Summary comment posted on issue
- Final report presented to user
- Proceed to `retrospect.md`
