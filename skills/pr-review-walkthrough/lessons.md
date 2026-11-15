# PR review walkthroughs: what worked and what did not

Background for SKILL.md. Generic lessons from building walkthrough pages for
stacked and single pull requests. Append new feedback here; promote it to a
rule in SKILL.md once the user confirms it.

## What worked
- A plain-language TL;DR: what the PR does, what it leaves out, what did not change.
- Before and after, where "before" is what the base branch did before the PR.
- A table for something a diff hides (scope tables, flag combinations).
- A decision-flow diagram with a few leaves instead of an interactive explorer.
- An evidence table that says what was not tested.
- Checking every claim against the code. This caught wrong file counts, a wrong
  description of existing behaviour, and a CSS bug.

## What did not work
- **A per-file diff list.** It repeats the Files changed tab. Link to specific
  files and lines instead.
- **A one-item-at-a-time stepper whose steps jump between PRs.** The reader
  cannot see where a stack is going. Prefer one diagram of the whole flow.
- **Describing the history, not the PR.** "Round 1 / round 2" and earlier code
  nobody reviewed. Show the final change only.
- **Stale facts.** Force-pushes and rebases change heads, CI runs and file
  counts. Name the head SHA once; keep live state (CI numbers, approvals) off
  the page. When two pages cover one PR, keep each number in one place.
- **Links to an unpublished page.** Remove them until the page is live.
- **Interactive explorers with many presets plus a big output table.** Too many
  options for a reviewer who wants the few cases that matter. Replace with one
  static decision-flow diagram; if a reviewer still finds it unhelpful, drop
  the section rather than add controls back.
- **Pages that grow.** One page went from about 2,300 prose words to about
  1,400 after de-duplication. Watch the length on every revision.

## Rules that came from feedback (now in SKILL.md)
- Each fact once, preferably in a diagram. Never restate a diagram or code in
  prose. A section that only re-explains a diagram goes (keep its id as an alias).
- The ERD is the only description of a table: columns, types and key
  constraints live in the entity, with code links beside it.
- Draw the full chain a change joins into, not only the two joined tables.
  External systems are external entities keyed by their id. Mark what the PR
  adds, what exists, and what is planned.
- Base diagrams on the code at the head SHA, checked against any design doc.
  Report disagreements; label doc-only items "planned".
- A follow-up that is not filed is "planned, not filed yet". Ask if there is no
  source; never invent its shape.
- Mermaid renders ERDs from a pinned CDN build, also from `file://` in Chrome.
  Offline it shows source text; say so in the caption. A wide ERD in a narrow
  column reads as cut off: let the figure break out of the text column. Mark
  external entities with a grey fill, not a dashed border (dashes look clipped).
- Four sections showing one idea should become one section. Grep entry points
  from the code; callers that write nothing are easy to miss.
- Undecided questions are shown plainly, with no leaning.
- Upstream context is collapsed behind a short strip. A model's creation is
  drawn in the section that owns the model.
- Colours need an in-figure legend. Red boxes with no legend confused readers;
  rollout-only and redundant cases belong in a footnote; never draw an absence
  as a hollow shape; avoid labels that suggest an outcome the term does not mean.
- References by section number break on every renumbering. Link by anchor and
  title.
- Replace "what to check hardest" with "Decisions we made, and why" (decision,
  reason, mitigation or cost), plus "Tracked follow-ups" (filed issues only)
  and a "Release checklist" (deploy steps and data caveats).
- Show payloads as real JSON (invented data), before and after, with a link to
  a filtered trace view; describe each key under the JSON, with an id per key.
  Check each filter before putting its link on the page. When no run exists
  yet from the head commit, use the nearest real run, apply the known
  differences, and say so next to the JSON.
- Do not repeat a companion PR's walkthrough. Link to its anchors.
- Document only names that shipped. Interim names are history, not terms.
- A reviewer new to the model needs a short primer of it before any mechanism.
- Include QA evidence: screenshots (crop away anything that shows a test
  login) and trace links, with timezones stated.
- Check the page's own class names before claiming something is missing.

## What the skill does not cover
- How to order a stack of PRs, and how to show a flow that crosses PRs.
- What happens to the page when the PR is force-pushed (re-pin the head SHA and
  re-verify every code link).
- Where to host the page and what may go on it.
- The `comprehension-artifact` skill overlaps: it writes a page into the repo's
  `docs/` plus a "What I built" section in the PR body. This skill is for a
  reviewer-facing walkthrough with diagrams and draft review comments.
