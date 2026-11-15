# Validate Phase

Three (or four) layers: tests pass, ACs verified, `code-review` scores
the diff, and E2E hooks confirm the feature works end-to-end (when
available).

## Pre-conditions

- Execute phase complete (all tasks done, tests passing locally)
- Code committed in the worktree
- Task files with acceptance criteria available
- Access to `~/workspace/skills/code-review/SKILL.md`

## Layer 1: Test Suite

Run the full test suite in the worktree:

```bash
cd {worktree_path}
{test_command}
```

### Pass criteria

- [ ] All tests pass (zero failures)
- [ ] No pending tests that should be implemented
- [ ] No regressions (existing tests still pass)

If tests fail:

1. Read the failure output.
2. Fix the failures.
3. Re-run the suite.
4. If still failing after 2 attempts → stop and report per guardrails.

## Layer 1.5: Schema-Refutation Check (external-contract code)

**Applies when** the diff calls an external API, writes to a typed store,
or otherwise sends a payload whose field names/shapes are defined by a
contract the code doesn't own (REST/GraphQL bodies, DB columns, message
schemas, RPC requests). **Skip (`n/a`)** for pure-internal changes.

This is the layer that earns its keep on **write paths that silently
no-op on a wrong field name** — e.g. a financial API that returns `200 OK`
and ignores a misspelled key, so the test passes and the live effect never
happens. Tests and even a code-review can sail past a guessed field name;
only a check that *diffs the payload against the authoritative schema*
catches it.

Spawn a **fresh-context verifier** (subagent / new conversation) given
**only**: (a) the diff, (b) the authoritative schema source, and (c) the
list of write/contract call sites. Prompt it to **refute, not confirm**:

> You are a skeptical schema auditor. Default to "WRONG" unless you can
> prove a field is correct against the cited schema. Do **not** trust the
> code's comments, variable names, or the author's intent — trust only the
> schema source.
>
> Authoritative schema: {path/URL to the verified spec — e.g. the OpenAPI
> file, the migration, the .proto, or the verified-schemas block in the
> issue/plan}.
>
> For every outbound payload in the diff (every `_post`/`_patch`/`_put`/
> `_delete` body, every insert/update dict, every request object):
> 1. List each field name the code actually sends.
> 2. For each, find it in the schema. Quote the schema line. If you can't
>    find it verbatim → mark **WRONG (not in schema)**.
> 3. Check the value shape/units against the schema (e.g. milliunits vs
>    dollars, `YYYY-MM-01` vs `YYYY-MM-DD`, enum membership, required-vs-
>    optional, nesting depth like `{"category": {...}}`).
> 4. Flag any **required** field the schema demands that the payload omits.
>
> Return a table: `call site | field sent | in schema? (quote) | shape ok? | verdict`.
> End with: any WRONG verdict → overall **REFUTED**; else **CONFIRMED**.

### Pass criteria

- [ ] Every outbound field name appears verbatim in the authoritative schema
- [ ] Value shapes/units/enums/date-formats match the schema
- [ ] No required field is omitted
- [ ] Verifier returns **CONFIRMED**

If **REFUTED**: fix the field name/shape in the worktree, re-run Layer 1
tests, then re-run this verifier **once**. If still REFUTED → stop and
report per guardrails (a guessed contract is a correctness defect, not a
style nit — never ship past it).

> Why this exists: per improvement-plan move #2, the refute-first checker
> is the point of the maker/checker split. A confirming reviewer rubber-
> stamps plausible-looking field names; a refuting one assumes they're
> guessed until the schema proves otherwise.

## Layer 2: Acceptance Criteria Verification

Walk every AC from the enriched issue body. For each:

1. Find the corresponding test(s) in the new tests.
2. Verify the test exercises the specific AC (not just adjacent behavior).
3. Check the AC off if a passing test covers it.

```markdown
### AC Verification

| AC | Description | Test File | Test Name | Status |
|----|-------------|-----------|-----------|--------|
| #1 | {criterion} | {test_path} | {test name} | pass/fail/missing |
| #2 | {criterion} | {test_path} | {test name} | pass/fail/missing |
```

### Pass criteria

- [ ] Every AC has at least one corresponding test
- [ ] All corresponding tests pass
- [ ] No AC is uncovered

If any AC is uncovered:

1. Write the missing test(s).
2. Implement if needed to make them pass.
3. Re-run the full suite.

## Layer 3: code-review Rubric

Spawn a fresh-context reviewer (subagent or new conversation) to score
the diff against `code-review`:

> Read `~/workspace/skills/code-review/SKILL.md` for the framework.
>
> Review the diff: `git diff main...HEAD` in the worktree at
> {worktree_path}.
>
> Score each applicable phase (1–7) on the 0–3 scale:
> - Phase 1: Architecture / organization
> - Phase 2: Pairing & collaboration (score the PR description and
>   commit narrative; this is agent-generated, no human pairing)
> - Phase 3: Naming & domain alignment
> - Phase 4: Error handling & defensive coding
> - Phase 5: Testing completeness
> - Phase 6: Frontend quality (n/a if backend-only)
> - Phase 7: Commit discipline & change narrative
>
> For each phase, list:
> - Score (0–3)
> - Specific findings (file + line + what to change)
> - Classification: must-fix, should-fix, consider
>
> Return the scored rubric and overall band.

### Pass criteria

- [ ] No phase scores 0
- [ ] Overall band is "Solid" (≥70%) or better
- [ ] No must-fix items remain

### Processing review results

| Finding | Action |
|---------|--------|
| Must-fix | Fix immediately in the worktree. Re-run tests. |
| Should-fix | Fix if straightforward. Note in PR description if deferred. |
| Consider | Note in PR description for human reviewer. |

After addressing must-fix items, re-run the review **once**:

- If must-fix items remain after retry → stop and report per guardrails.
- If all must-fix resolved → proceed.

## Layer 4: E2E Validation (optional, soft-blocking)

If the feature has an E2E hook (identified in PLAN), the orchestrator
**must attempt** the E2E pipeline before declaring validation complete.
Specs green ≠ feature works; the extra few minutes here catches the
bugs that survive unit tests.

### Step 4a: Determine whether E2E applies

The orchestrator stays **project-agnostic** — it does not know any specific
API or test framework. It discovers a project's E2E hook through one
convention: a manifest file **`.e2e.json` at the repo root**.

```bash
cat {repo_root}/.e2e.json 2>/dev/null
```

The manifest is deliberately minimal:

```json
{
  "command": "python -m bosque.testing.e2e --replay",
  "record":  "python -m bosque.testing.e2e --record",
  "describe": "Stateful-fake + replay e2e for YNAB/Google/ElevenLabs tools"
}
```

| Field | Meaning |
|-------|---------|
| `command` | **Required.** The replay/verify run — deterministic, **no live keys**, safe to run in cloud/CI. Layer 4 runs this and gates on its exit code (0 = pass). |
| `record` | Optional. Refreshes fixtures against the real APIs — **needs live keys, dev-machine only.** The orchestrator NEVER runs this; it's a human action when an API changes. Surface it in the report if a contract drift is suspected. |
| `describe` | Optional. One line for the execution log. |

Resolution:

- **`.e2e.json` present** → run `command`, gate on it (Step 4b). The project
  owns everything behind that command (which fakes are stateful vs. replay,
  which tiers run); the orchestrator only sees pass/fail. This is how Layer 4
  stays generic while a project (e.g. claw-playbook) plugs in arbitrarily rich
  e2e — including stateful-fake **Tier-3 semantic** checks.
- **No `.e2e.json`** → fall back to any E2E hook identified in PLAN. If none was
  feasible either, Layer 4 is `n/a`; note it in the log and proceed.

> Why a manifest, not a hardcoded command: the orchestrator is reused across
> projects. It must not learn YNAB, Gmail, pytest, or OpenClaw. `.e2e.json` is
> the whole contract — "here's my one command, gate on it." A project with no
> manifest simply has no Layer-4 gate, exactly as today.

### Step 4b: Run the E2E pipeline

If a `.e2e.json` manifest was found, run its `command`. Otherwise invoke the
project's E2E skill or script identified in PLAN. Test at least one positive
case and (where applicable) one negative case.

### Pass criteria

- [ ] E2E run reports `PASS` on at least one positive case
- [ ] E2E run reports `PASS` on at least one negative case (where applicable)
- [ ] Every hard assertion passed (status, output shape, round-trip)
- [ ] No ERROR-level entries in logs for the feature during the E2E window

### Iterate loop

If the E2E run reports `FAIL`:

1. **Diagnose.** Read the failure output and any logs / traces.
2. **Fix the code.** Apply the minimal change. If the fix reveals a
   test gap (the unit tests stubbed the wrong shape), **update the
   test fixture to match the real shape** — this is as important as
   the fix itself.
3. **Re-run unit tests.** Must stay green.
4. **Re-run E2E.**
5. **Count iterations.** Iterate up to **3** times. If E2E still fails
   after the 3rd iteration, stop and ask the user whether this is a
   code problem to keep working on, an environment problem you can't
   see, or a test that needs relaxing.

### Soft-block, not hard-block

The user can say "ship it anyway" with an explicit override. Default
behavior:

- E2E PASS → proceed to ship.
- E2E FAIL after iteration budget exhausted → **stop before ship**, add
  `orchestrator-blocked` label, write diagnostic context into the
  draft PR description, and report.

Never ship after an E2E FAIL without explicit user consent.

### Recording the outcome

Append per iteration:

```markdown
### E2E Iteration {n}

- Positive case: PASS / FAIL ({details})
- Negative case: PASS / FAIL ({details})
- Friction observed: {list}
- Fixes applied: {list of commits}
```

## Parallel Plans: Winner Selection

If EXECUTE ran parallel plans (build-first mode), run Layers 1–4 on
both. Compare:

| Metric | Plan A | Plan B |
|--------|--------|--------|
| Tests passing | {count} | {count} |
| ACs covered | {count}/{total} | {count}/{total} |
| Review score | {band} ({pct}%) | {band} ({pct}%) |
| E2E result | {pass/fail} | {pass/fail} |
| New test count | {count} | {count} |
| Diff size (lines) | {count} | {count} |

**Winner selection priority:**

1. E2E passes (hard gate — disqualify if E2E fails)
2. Higher AC coverage
3. Higher review score
4. More tests
5. Smaller diff (simpler is better, all else equal)

Discard the losing plan's worktree. Proceed with the winner.

## Step 5: Comment Validation Summary

```bash
gh issue comment {NNN} --repo {owner/repo} --body "$(cat <<EOF
**Validation complete.**

- Tests: ${PASS_COUNT} passing (${NEW_COUNT} new)
- ACs: ${COVERED}/${TOTAL} verified
- Review: ${BAND} (${SCORE}%)
- E2E: ${E2E_RESULT}

${REVIEW_NOTES}
EOF
)"
```

## Step 6: Record Validate Summary

```markdown
## Validate

**Layer 1 — Tests:** {pass_count} passing, {fail_count} failing
**Layer 1.5 — Schema refutation:** {confirmed / refuted→fixed / n/a} ({fields_checked} fields across {call_sites} call sites)
**Layer 2 — ACs:** {covered}/{total} verified
**Layer 3 — Review:**
| Phase | Score | Findings |
|-------|-------|----------|
| 1. Architecture | {score}/3 | {summary} |
| 2. Collaboration | {score}/3 | {summary} |
| 3. Naming | {score}/3 | {summary} |
| 4. Error handling | {score}/3 | {summary} |
| 5. Testing | {score}/3 | {summary} |
| 6. Frontend | {score}/3 or n/a | {summary} |
| 7. Commits | {score}/3 | {summary} |
| **Overall** | **{pct}%** | **{band}** |

**Layer 4 — E2E ({iterations} iteration(s)):** {pass/fail/n/a}

**Must-fix items addressed:** {count}
**Should-fix deferred:** {count}
**Consider noted:** {count}
```

## Output

- All applicable validation layers passed
- Must-fix items resolved
- Should-fix and consider items documented
- Issue commented with validation summary
- Execution log updated
- Proceed to `ship.md`
