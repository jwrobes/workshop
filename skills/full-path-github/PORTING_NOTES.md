# Porting notes

Improvements ported from a GitLab orchestrator into this GitHub skill, rewritten
for the `gh` CLI, a single `orchestrator-blocked` label, and a solo owner.

| Improvement | Status | Files | Reason |
|-------------|--------|-------|--------|
| Opus 5.5 prompting alignment + run-conduct guardrails | Ported | `phases/guardrails.md`, `SKILL.md`, `phases/execute.md`, `phases/validate.md`, `phases/intake.md` | Turn endings, subagent-return continuation (max 2), untrusted issue text with id-tagged wrapping, time signals for parallel fan-out only, default effort, "final message is the report". Confidentiality check skipped (n/a for personal repos). |
| Estimate gate (> 3 pauses shaping phases) | Ported | `phases/guardrails.md`, `phases/intake.md`, `SKILL.md` | Waivable by the owner up front. Adapted: no delivery-mode dial exists here, so the pause is on by default for estimates above 3. |
| Score-gated retro action items, autocreate standalone issues | Ported | `phases/retrospect.md`, `phases/guardrails.md` | Confidence x Priority table; Note-only items are logged, never filed. |
| Reinforced patterns, over-optimism check, long-term health, self-referential scope | Ported | `phases/retrospect.md`, `phases/guardrails.md` | Includes the reward-hacking boundary: guardrail/evaluator edits are proposed as issues only. |
| PR base and commit range from the origin default branch | Ported | `phases/ship.md`, `phases/validate.md` | Replaces hardcoded `main` in SHIP and the review diff. `plan.md` still branches off `origin/main`; see candidates. |
| Graceful degradation when an outward comment write is denied | Ported | `phases/guardrails.md`, `phases/ship.md`, `phases/retrospect.md`, `SKILL.md` | Save body to `.orchestrator/`, print the `gh` command, continue. |
| Pre-push local CI-style review | Ported (idea) | `phases/ship.md` Step 2.5 | Instructions only: a fresh `claude -p` reviewer using the `code-review` skill, advisory. No script; the upstream runner is specific to one CI setup. |
| Preserve reporter screenshots/recordings through enrichment | Ported | `phases/intake.md`, `phases/enrich.md` | Collected verbatim at intake, re-embedded and verified after the body rewrite. |
| Derive PR target repo from the git remote | Ported | `phases/ship.md` Step 0 | Cross-repo issues close with `Closes owner/repo#N`. |

## Candidates for later (not implemented)

- Run `plan.md` branch creation off the resolved default branch instead of `origin/main`.
- Per-lens pattern reviewer subagents (architecture, defensive coding, domain alignment,
  test coverage) scoring one candidate file each in ENRICH, in place of the inline rubric.
- A dedicated read-only implementation reviewer with a parseable `Confidence: N%` line
  and a severity-calibrated gate (must-fix caps confidence below the pass line).
- A task-implementer agent definition with a strict final-report contract.
- An explicit "no horizontal slicing / no new labels" check list in the retro for harness edits.
- A small generic `local-review` script, if the inline `claude -p` recipe proves brittle.
