---
name: fleet-llm-refresh
description: >-
  Refresh the fleet dashboard's LLM intelligence layer by chaining the on-demand
  collector passes in order (collect → triage → re-stamp → analyze → rollup →
  regenerate) and reporting what changed. A THIN orchestrator: each step is a
  plain `collector.py` CLI call — the LLM reasoning happens inside the passes
  (via `claude -p`), not in this skill. Use when the user says "refresh the
  fleet LLM", "run triage", "re-analyze the tracks", "run the fleet passes", or
  wants the dashboard's verdicts/suggestions brought up to date. Pass 1 (triage)
  is live today; analyze/rollup wire in as those passes land.
---

# fleet-llm-refresh (LLM intelligence orchestrator)

The dashboard is deterministic-first: `./run.sh` reuses cached LLM results so it
stays fast + offline. This skill is how you deliberately RE-RUN the (expensive,
on-demand) LLM passes and see the change-log — the same "chain grounded steps,
each verified against real state" shape as `full-path-github`, but each step is
a single `collector.py` flag rather than a reasoning phase.

**Where to run:** the fleet-dashboard implementation dir
(`~/workspace/workshop/fleet-dashboard/`, or the active worktree at
`~/workspace/workshop_workspace/workshop-fleet-attribution/fleet-dashboard/`).
Output lands in `~/.fleet` (or `$FLEET_OUT`).

## The sequence (order matters)

Triage changes track MEMBERSHIP, so it must run and re-stamp BEFORE analysis;
rollup consumes analysis. The collector enforces the order internally when you
pass `--llm-all`; you can also run a single pass ad hoc.

1. **Collect (ground truth).** `python3 collector.py --out ~/.fleet`
   Produces a fresh `status.json` — the real state the LLM passes read. Never
   skip this: the passes must reason over current data, not a stale cache.

2. **Triage (Pass 1 — live).** `python3 collector.py --out ~/.fleet --triage`
   Sweeps the Ungrouped strays vs existing tracks. HIGH-confidence attaches
   auto-apply (folded into `track-overrides.json` as `_source:"llm-triage"`) and
   the collector RE-STAMPS so membership reflects them; medium/low + all
   create/archive become suggestions. Writes `llm-runlog.json` (the "Since last
   analysis" panel) and prints a one-line summary.

3. **Analyze (Pass 2 — when built).** `--analyze` → per-track verdict +
   completion in `verdicts.json`.

4. **Rollup (Pass 3 — when built).** `--rollup` → product/fleet "where things
   stand" summary (consumes Pass 2; does not re-analyze).

5. **Regenerate + report.** The collector regenerates `dashboard.html` on every
   run. Read back the printed summary (auto-attaches, suggestion counts) and
   surface it to the user; point them at the dashboard's runlog panel to review
   the pending suggestions.

**Convenience:** `python3 collector.py --out ~/.fleet --llm-all` runs every
built pass in order. Today that's triage; analyze/rollup join as they land.

## What this skill does NOT do

- It does not itself reason — no prompt engineering here. The reasoning is in the
  passes (`consolidate.run_triage`, etc.), which shell out to `claude -p`.
- It does not auto-accept suggestions or archive anything — those stay human
  decisions in the dashboard (accept/dismiss → download corrections). Only
  high-confidence *attaches* auto-apply, and even those land in the overrides
  file the user inspects and can undo.
- It does not push. Nothing here touches git.

## Offline / failure behavior

Each pass is best-effort: a failed pass (CLI missing, bad JSON) leaves the prior
cache intact and is never fatal — `status.json`/`dashboard.html` still
regenerate. If `claude` isn't available, run without the LLM flags to just
refresh the deterministic dashboard.

## Testing note (for maintainers)

Never call the real `claude` CLI in a gate. The passes take an injectable
runner; the collector exposes `--triage-fixture <file>` (a canned proposals
JSON) so e2e/pytest exercise the REAL triage code path offline. See
`e2e_triage.mjs` / `e2e_llm_runlog.mjs` and `test_consolidate.py`.
