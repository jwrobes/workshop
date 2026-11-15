# Guardrails

Read this FIRST before any other `full-path-github` phase.
These are hard rules — violating any one is a stop-and-report condition.

## Where this skill lives (read if you're a cloud/headless session)

This orchestrator lives in the **public `jwrobes/skills` repo**, NOT in the
work-repo you're operating on. A session scoped to the work-repo can't see it
unless it cloned it. If you're reading this, you already have it — but the
**issue-tree conventions below are the canonical record**, because a session
that picks up a labeled issue without a launch prompt won't know them otherwise:

- **One leaf issue = one worktree = one branch (`build-{slug}`, cut from `main`)
  = one PR.** Branch off `origin/main`, never stack on a sibling (see `plan.md`).
- **Decomposition uses *native* GitHub sub-issues** (linked via the sub-issue
  API, `POST issues/{n}/sub_issues -F sub_issue_id=<int>`), **not** markdown
  checkbox lists. A parent tracker holds the leaves as native sub-issues.
- **`ready` gates execution; `build-spec` marks an authored spec.** Only labels
  that exist are used — don't invent a domain label that would 404 (create it
  first with `gh label create` if you genuinely need it).
- **`blocked_by` dependencies are respected** (intake gate) — don't start a leaf
  with open blockers.

> Why this is here: the #105 run had to reverse-engineer all of this from
> existing issues (#90–94) because it wasn't written down anywhere the session
> could reach. Any repo that delegates to this orchestrator should point at it —
> see the work-repo's `build-specs/README.md` (or equivalent) for the pointer.

### Multi-leaf-in-one-PR reconciliation

The default is one leaf → one PR. But when two leaves are small and splitting
them would create a **broken intermediate state** (e.g. a parser core + the loop
that consumes it), landing both on one branch is legitimate. When you do:

1. The PR body must say **which leaves it implements** and why they were combined.
2. **Close each combined leaf** as completed, referencing the PR.
3. **Annotate the parent tracker** — check the boxes, note "implemented in #PR".
4. The parent tracker closes on merge (its `Closes #tracker` or a manual close).

State this in the execution log so the queue stays honest.

### Spec-PR ↔ implementation linkage

When the work originates from a **spec that lives in its own PR** (the
build-spec flow), tie them together explicitly so a reviewer finds both:
the implementation PR body references the spec PR (`Implements spec PR #NN`),
and ideally the implementation commits land **on the spec PR's branch** (the
`build-specs/README.md` flow) rather than a disconnected branch. Don't leave the
link implicit in a branch name.

## GitHub Issue Rules

- The issue is the **single source of truth**. All state lives there.
- **Always** overwrite the issue body with enriched content via `gh issue edit --body-file …` (GitHub keeps the previous body in the edit history).
- **Never** create child issues or sub-tasks as separate GitHub issues. Tasks live as files in the worktree under `backlog/tasks/`.
- **Always** comment before blocking — the comment explains what's needed and adds the `orchestrator-blocked` label.

## Confidence Rules

When self-interrogating (answering your own grill-me questions):

| Tier | Signal | Action |
|------|--------|--------|
| **High** | Codebase has a direct precedent that passes `code-review` phases 1, 3, 4, 5 | Decide. Document reasoning in issue body. |
| **Medium** | Multiple valid approaches, one is lower-risk or better-aligned with conventions | Decide. Add a flag comment: "Chose X over Y because Z — override in a comment if you disagree." |
| **Low** | No precedent, multiple approaches with different tradeoffs, or irreversible consequence (DB schema, public API shape) | **Stop** (label + comment) OR **split** into parallel plans (mode-dependent). |

**Never** claim high confidence without citing a specific file path and explaining why it passes the review rubric.

**Never** proceed past a low-confidence decision without either blocking or splitting.

## Pattern Evaluation Rules

Before following any codebase pattern:

1. Read the candidate file(s).
2. Evaluate against `code-review` phases 1 (architecture), 3 (naming), 4 (error handling), 5 (testing).
3. Score each phase 0–3.

| Score | Action |
|-------|--------|
| All phases ≥ 2 | Follow the pattern. Cite it in the plan. |
| Any phase = 1 | Follow with noted improvements. Document what you'd change. |
| Any phase = 0 | **Do not follow.** Find a better pattern or flag as greenfield. |

## Vagueness Gate (Intake)

After reading the issue AND searching the codebase, the orchestrator must answer three questions:

1. **What** — Can you describe the desired behavior change in one paragraph?
2. **Where** — Do you know at least one directory/module where the work lives?
3. **How to verify** — Can you state at least one testable acceptance criterion?

All three must be "yes" to proceed. Any "no" → add `orchestrator-blocked` label with a comment listing which questions can't be answered.

## Spec-Grounding Gate (when the issue/spec was authored elsewhere)

When the work comes from a **build spec or plan authored away from this repo**
(e.g. an agent wrote a spec against its memory of the codebase, not the live
tree), the spec's paths/symbols are *assumptions, not facts*. Before EXECUTE,
**pre-flight the spec against reality** — for every file path, function name,
test path, and directory the spec cites:

```bash
# Does each cited path/symbol actually exist on main?
git ls-files | grep -F '{cited/path}'        # path exists?
grep -rn 'def {cited_function}' {dir}        # symbol exists?
```

| Finding | Action |
|---------|--------|
| All cited paths/symbols resolve | Proceed; note "spec grounded" in the log. |
| Spec cites things that don't exist or are misnamed | This is a **wrong-assumption** problem → per Discovered-Problem Triage, **correct the spec/issue to the real tree and document the deviation**, then proceed. Do NOT implement against the imagined structure. |

> Why this exists: the email-triage run (#105) found its spec referenced a
> `tests/` dir, a `plans/email-triage-review-…md` file, and inline Sonnet calls
> that **none existed** — the real repo used script-style tests, a different
> plan file, and a shared Haiku module. The implementer caught it reactively;
> this gate makes it a first-class step. The fix the run wrote up: spec authors
> should ground specs against the real tree, but the orchestrator pre-flighting
> is the backstop that always runs.

## E2E Validation Rules

- E2E validation hooks are a **soft prerequisite**. For personal projects, the orchestrator can ship without one only if no automated end-to-end check is feasible (e.g., a pure refactor with full unit-test coverage).
- If hooks don't exist for this feature and they make sense, building them is **task-001** in the structured backlog.
- If hooks can't be built (infrastructure missing, credentials unavailable), document the gap in the PR description and proceed.

## Discovered-Problem Triage (mid-run surprises)

When a phase uncovers a problem the issue didn't anticipate — a missing
precondition, a merge conflict, a wrong assumption in the plan, a file that
isn't where it was supposed to be — **do not silently work around it and do not
improvise a large fix.** Classify it first, then act by the table. The goal is
to never make the situation *harder to reason about* than you found it.

| The problem is… | Action |
|-----------------|--------|
| **In-scope and small** (a typo, a missing import, a test that needs a fixture you can write) | Fix it inline. Note it in the execution log. Continue. |
| **A wrong assumption in the issue/plan** (path doesn't exist, baseline differs from what the AC assumed, a "new" thing already partly exists) | **Stop. Comment on the issue** with exactly what you found vs. what was assumed, correct the issue body/ACs to match reality, and report. Do NOT proceed on a plan you now know is wrong — a wrong decomposition surfaced at PR time is the expensive failure mode. |
| **A missing precondition you could fabricate** (an entire file/module that "should" exist but doesn't) | **Stop and report. Never fabricate it.** Offer the human concrete unblock options (vendor the file, point you at the real repo, or confirm greenfield). Fabricating guesses a contract you can't verify. |
| **A blocker outside this issue's scope** (a sibling PR must merge first, infra missing) | Add `orchestrator-blocked`, comment which external thing blocks it, stop. |

**Cardinal rule:** *prefer reverting your own half-change and reporting over
leaving a partial, confusing state.* A clean "here's what I found, here's why I
stopped" is worth more than a messy attempt that someone has to untangle.

### Worked example — a sibling PR merged and now THIS PR conflicts

This is a *branch-currency* problem, not a code problem. Handle it in this exact
order — the order matters because GitHub will trap you otherwise:

1. **Rebase the EXISTING branch onto `main`**, don't start over:
   `git fetch origin main && git rebase origin/main`. Already-merged sibling
   commits drop out by patch-id; genuine conflicts are resolved by **keeping
   both sides** (sibling additions are usually orthogonal to yours).
2. **Re-run the test suite** — a rebase can silently break things.
3. **`git push --force-with-lease`** the same branch. If the PR is still open,
   this updates it in place — done.
4. **Do NOT delete the base branch or the head branch to "clean up" first.**
   A PR whose base branch was deleted (or whose head was force-pushed) **cannot
   be reopened** if it ends up closed. That is GitHub behavior, not a bug.
5. **If the PR was already auto-closed** (base branch gone): accept it's dead.
   Open a **clean replacement PR** from the rebased branch, and put
   "Supersedes #NN — original auto-closed when its stacked base branch was
   deleted" in the body. Report both numbers.

> Prevention beats all of this: per `plan.md` Step 1, branch every leaf off
> `main` (never stack on a sibling), and per `ship.md` Step 2, rebase before the
> first push. Stacking is what creates these conflicts in the first place.

## Hard Stops

Stop and report immediately if:

| Condition | Action |
|-----------|--------|
| Issue is private and access is denied | Do not proceed. |
| No project identifier provided | Ask the user which repo this targets. |
| Codebase is inaccessible (no clone, no worktree) | Stop. Cannot evaluate patterns or search for context. |
| Tests fail after 2 fix attempts at the same phase | Stop. Human debugging needed. |
| `code-review` scores any phase at 0 after retry | Stop. Structural issue needs human judgment. |
| `gh` CLI not authenticated (`gh auth status` fails) | Stop. Run `gh auth login` first. |

## Execution Log

Every phase must append to the execution log. The log tracks:

- Phase name and timestamp
- Decisions made (with confidence tier)
- Patterns evaluated (with scores)
- Questions asked (if blocked)
- Test results
- State transitions (assigned → draft PR → ready for review)

The log lives in memory during the run and is written into the PR description AND posted as an issue comment in the SHIP phase.
