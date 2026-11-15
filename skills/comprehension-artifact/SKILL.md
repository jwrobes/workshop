---
name: comprehension-artifact
description: >-
  Render a "what I built" comprehension artifact for a non-trivial change so a
  reviewer can understand it from a phone without pulling code. Emits a
  self-contained HTML page into the work-repo's docs/ AND a PR-body section that
  links it. Optional-but-strongly-encouraged gate: invoked by the full-path
  orchestrator at SHIP for multi-file / new-capability work; skipped for trivial
  fixes. Use when the user says "comprehension doc", "what-I-built HTML",
  "explain this PR for review", or a loop ships a new capability.
---

# Comprehension Artifact

The better and more interpretable the change, the less cognitive/comprehension
debt the reviewer carries. This skill turns an implemented change into a
**reviewer-facing explainer** — a single self-contained HTML page (reviewable
from a phone, no checkout) plus a PR-body section that points at it.

This is the **output explainer** half of the comprehension-artifact decision
(STATE-OF-PLAY decision #9). The forward half (a signed-off design that *guides*
the build) is a separate input contract; this skill is the backward half — it
explains what an autonomous run actually produced.

## When to use (the gate)

This is an **optional-but-strongly-encouraged** gate, not a hard block. Apply
the same judgment as the maker/checker gates:

| Change shape | Artifact |
|--------------|----------|
| Multi-file, **new capability**, new external surface (API/tool/skill), or non-obvious design | **Strongly encouraged — render it.** |
| Touches a contract a human will smoke-test later (e.g. a new tool surface) | **Strongly encouraged** — the artifact carries the smoke checklist. |
| Single-file bugfix, rename, dep bump, doc-only, trivial mechanical change | **Skip.** Note "comprehension artifact: skipped (trivial)" in the PR. |

If you skip it, say so explicitly in the PR body so the reviewer knows it was a
judgment call, not an omission.

## What it produces

1. **`docs/<feature-slug>.html`** in the **work-repo** (not the planning repo —
   the artifact's home is where the code lives, resolving the two-repo-write
   dead-end). Self-contained: inline CSS, no build step, no external fetches.
2. **A PR-body section** (`## What I built`) that links the rendered page and
   summarizes it in three lines, so the link has context even before it's served.
3. **A note on GitHub Pages status** — whether the page is servable yet.

## Step 1: Decide it applies

Run the gate table above against the diff. If it's trivial → skip, note it,
done. Otherwise continue.

## Step 2: Gather the material

You already have most of it from the orchestrator's execution log. Collect:

- **The capability in one sentence** — what can the system do now that it couldn't.
- **The surface** — new functions / tools / endpoints / skills, grouped
  (e.g. read vs. write), each mapped to the file/function that implements it.
- **The non-obvious design decisions** — anything a reviewer would otherwise have
  to reverse-engineer (a boundary conversion like dollars↔milliunits, an
  escalation path like Haiku→Sonnet, a safety property like refuse-on-unmatched).
- **The boundary/contract** — what shape goes out, what comes back, any units or
  formats that bite.
- **The smoke checklist** (if the change has a live contract a human verifies
  after merge) — tiered by safety: reads (fire freely), reversible writes
  (create→verify→undo), one-time semantic checks. See the
  `openclaw-is-the-smoke-harness` pattern — the artifact is where this checklist
  lives so the reviewer runs it from the same page.

## Step 3: Render the HTML

Write a single self-contained file. Keep it skimmable on a phone: one capability
summary up top, then collapsible sections. Use this skeleton (adapt content;
keep it inline-styled and dependency-free):

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{Feature} — what I built</title>
<style>
  :root { --fg:#1a1a1a; --muted:#666; --line:#e3e3e3; --accent:#0b62d6; --warn:#b25b00; }
  body { font:16px/1.55 -apple-system,system-ui,sans-serif; color:var(--fg);
         max-width:46rem; margin:0 auto; padding:1.25rem; }
  h1 { font-size:1.5rem; margin:.2rem 0 .1rem; }
  .sub { color:var(--muted); margin:0 0 1.25rem; }
  h2 { font-size:1.15rem; border-bottom:1px solid var(--line); padding-bottom:.25rem; margin-top:2rem; }
  code { background:#f4f4f4; padding:.1em .35em; border-radius:4px; font-size:.9em; }
  table { border-collapse:collapse; width:100%; font-size:.92rem; }
  th,td { text-align:left; padding:.4rem .5rem; border-bottom:1px solid var(--line); vertical-align:top; }
  .pill { display:inline-block; font-size:.72rem; padding:.1em .5em; border-radius:999px; background:#eef3fb; color:var(--accent); }
  .warn { color:var(--warn); font-weight:600; }
  ul.smoke { list-style:none; padding-left:0; } ul.smoke li { padding:.2rem 0; }
  details { margin:.5rem 0; } summary { cursor:pointer; font-weight:600; }
</style>
</head>
<body>
  <h1>{Feature name}</h1>
  <p class="sub">{One sentence: what the system can do now that it couldn't. PR #NNN · {date}}</p>

  <h2>The surface</h2>
  <table>
    <tr><th>Capability</th><th>Implemented in</th><th>Notes</th></tr>
    <!-- one row per new function/tool/endpoint, grouped read/write -->
  </table>

  <h2>How it works</h2>
  <ul>
    <!-- the non-obvious decisions: boundary conversions, escalation, safety props -->
  </ul>

  <h2>The contract / boundary</h2>
  <p><!-- what goes out, what comes back, units/formats that bite --></p>

  <details open>
    <summary>Live smoke checklist — run after merge</summary>
    <p class="warn">Reads are safe; writes must be reversible (create → verify → undo) and run on throwaway data.</p>
    <ul class="smoke">
      <!-- Tier 1 reads / Tier 2 reversible writes / Tier 3 one-time semantic checks -->
    </ul>
  </details>
</body>
</html>
```

Write it to `{work_repo_root}/docs/{feature-slug}.html`. If `docs/` already
holds an `index.html` (landing page), add a link to your page from it rather
than overwriting it.

## Step 4: GitHub Pages status

Per decision #9, this artifact class is the one place the dashboard's
"no Pages" default is **flipped** — serving from `docs/` makes it reviewable
from anywhere.

```bash
gh api repos/{owner}/{repo}/pages 2>/dev/null \
  && echo "Pages already serving" \
  || echo "Pages NOT configured"
```

- If Pages is configured → note the served URL (`https://{owner}.github.io/{repo}/{slug}.html`).
- If not, and enabling it is in reach (you own the repo): enable serving from
  `docs/` on `main`. Otherwise note it as a one-line follow-up — the HTML still
  renders from the raw file / on a local checkout; Pages is a convenience, not a
  blocker.

## Step 5: Emit the PR-body section

Return this block for the orchestrator to splice into the PR description (it is
the instructions-in-PR part — the reviewer sees the link with context inline):

```markdown
## What I built

{One-sentence capability summary.}

📄 **Comprehension doc:** [`docs/{slug}.html`]({pages_url_or_blob_url})
_(open on a phone — full tool surface, the boundary, and the post-merge smoke
checklist, no checkout needed)_

- {bullet — the surface, one line}
- {bullet — the key non-obvious decision}
- {bullet — what to smoke-test after merge, or "no live contract — n/a"}
```

If Pages isn't served yet, link the blob URL
(`https://github.com/{owner}/{repo}/blob/{branch}/docs/{slug}.html`) and add
`(Pages setup: follow-up)`.

## Output

- `docs/{slug}.html` rendered into the **work-repo**, committed with the change.
- A `## What I built` PR-body section returned to the caller.
- Pages status determined (enabled, or noted as follow-up).
- If skipped: a one-line "skipped (trivial)" note for the PR.

## Composition

Invoked by `full-path-github`'s SHIP phase (Step 3.5) but **independently
usable** — point it at any merged/about-to-merge change to generate the
explainer. Pairs with the `openclaw-is-the-smoke-harness` pattern (the smoke
checklist this artifact carries) and the forward design-contract half of
decision #9.
