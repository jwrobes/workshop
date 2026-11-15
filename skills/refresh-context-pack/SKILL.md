---
name: refresh-context-pack
description: Build or refresh a fast-load, project-scoped context pack — a compact snapshot of live tracker state (GitLab epics/issues, or an equivalent) plus standing traps and links-out, meant to be read instead of re-deriving state from conversation history. Heavyweight — needs live tracker access and judgment about what to keep — so run it in a session with full project context, never from a lightweight helper. Deliberately decoupled from `sharpen-prompt`, which reads the pack this skill produces but never rebuilds it. Use when the user says "refresh the context pack", "rebuild the prompt pack", "the pack looks stale", or wants a durable, re-pullable snapshot of current tracker state for a project.
disable_model_invocation: true
---

# Refresh Context Pack

Produce or refresh a compact snapshot of a project's live tracker state, meant to replace re-deriving
context from conversation history. This is the heavy counterpart to `sharpen-prompt` — that skill reads
the pack this one produces, and the two stay decoupled on purpose (see `sharpen-prompt`'s Step 0). Don't
run this from inside a lightweight helper session, and don't have `sharpen-prompt` call it automatically.

## When this is warranted

- The user asks directly ("refresh the pack," "rebuild the context pack," "the pack looks stale").
- A lightweight session reported the pack disagreed with a live spot-check and pointed the user here.

Don't run this speculatively on every turn. It's a live pull across however many tracked items exist —
only worth it when something has plausibly changed since the pack's dated header.

## Step 1 — Read what already exists before pulling anything

If a pack already exists for this project, read it first. Its standing-traps table and links-out section
carry human judgment a mechanical tracker pull can't reconstruct — the goal is to refresh *state*, not
discard accumulated knowledge. If nothing exists yet, this step just tells you there's no prior version
to merge forward from.

Identify the root tracked item (a GitLab epic, a GitHub milestone, an equivalent root) — from the
existing pack if there is one, or ask.

## Step 2 — Pull live state, and keep intent separate from fact

Walk the tree from the root: every child epic/issue, current state, labels, parent. For GitLab: epics via
the group's epic list filtered by `parent_id`, each epic's `.issues.list()` for its children, recursively.

**Hard rule — this is the one thing that made the first working pack trustworthy and would make a sloppy
one actively misleading:** an edge is only "real" if it corresponds to an actual tracked link — a
blocking relationship, parent/child containment, an issue that exists. A dependency only described in an
epic's *prose* ("do X before Y") is **intent, not a tracked link**, and must be labeled as such
explicitly wherever it's shown. Collapsing the two makes unstarted work look scheduled — that's worse
than no pack at all, because it's confidently wrong rather than honestly absent.

## Step 3 — Merge forward the judgment sections, don't regenerate them

Standing traps and links-out don't come from the tracker — they come from prior docs, memory, and
lessons already paid for. Don't wipe and rewrite:

**Check `plans/DECISIONS_LOG.md` first, if the project has one.** It's written automatically by
`decision-capture-hook` (a Stop hook, see `hooks/`) every time a session ends with a scope decision,
narrowing/widening, or resolved judgment call in its last window of turns — append-only, and it exists
specifically so a decision made only in conversation doesn't evaporate before the next pack refresh sees
it. Read every entry since the pack's last `updated` date and fold relevant ones into the tree/traps
below; don't leave them sitting unread in the log once they're reflected in the pack.

- Carry forward every trap from the previous version unless it's now resolved. Mark resolved ones as
  closed rather than deleting them outright — a closed trap shows what got fixed, which is itself useful.
- Add a new trap only if it's (a) non-obvious, (b) would cause real damage if re-learned the hard way,
  and (c) not already fully explained in a doc the pack links to instead of inlining.
- Verify each trap's pointer still resolves to something real before keeping it — a dangling pointer to
  a doc that moved or a finding that got superseded is worse than dropping the trap.

## Step 4 — The refresh mechanism itself must be durable

The pack should carry its own re-pull instructions, but never as a script written to `/tmp/` or anywhere
else that doesn't survive a reboot or a fresh clone. Either:

- inline the exact query (the tracker walk, as a short script) directly in the pack's own header, or
- point at a script committed inside the project repo, never a scratch path.

If you find an existing pack pointing at a `/tmp/` script, that's a defect to fix on this pass, not
something to carry forward unchanged.

## Step 5 — Output shape

Same shape that already proved out: an epics/issues table, the tree as it *actually* stands (intent vs.
real edges marked per Step 2), standing traps, links out. Keep it a snapshot, not a narrative — no
rationale inline; that's what the linked docs are for. State the date it was pulled, prominently, at the
top.
