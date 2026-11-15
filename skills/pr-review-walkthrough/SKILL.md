---
name: pr-review-walkthrough
description: Build (or revise) a single-file HTML review walkthrough for one GitHub pull request, so a reviewer understands the change before reading the diff. Diagrams over tables, each fact once, links to the exact PR code, stable section anchors, draft review comments that point back at sections. Use when the user says "PR walkthrough", "review walkthrough", "walkthrough for PR #N", "explain this PR for reviewers", "help reviewers with this PR", or wants to revise an existing walkthrough page. For general "make this readable" output that is not a PR review page, use readable-output instead.
---

# PR review walkthrough

One page per pull request (not per commit). The page supports review on
GitHub; it does not replace the diff. Write in simple, short sentences
(simplified technical English: one idea per sentence, no idioms). Lessons and
feedback history: `lessons.md` in this folder. Append new feedback there, and
turn it into a rule below once the user confirms it.

## Working agreement (defaults; the user should not have to repeat them)
- Back up the page before every edit round (`<page>--BACKUP-before-<date>-<what>.html`).
- Local edits only. Publishing, PR comments, PR description and issue edits
  each need the user's explicit go.
- Work directly; no subagents unless the user asks for them.
- Keep replies brief. After each round report: what changed, what was dropped,
  the word count before and after, and the backup path.
- Render the page, look at every diagram, then open it for the user
  (`open <path>`).

## Before the first draft: ask these, then wait
Ask in one message. Each question exists because skipping it caused rework.
1. Who reviews it, and what must they decide? Is ~1,300 prose words right?
   Is the reviewer new to the domain model or the data it emits? (If yes, the
   page opens with a short drawn primer of the model and its outputs.)
2. **Fact inventory:** "here are the facts the page will carry, and the one
   place each lives (preferably a diagram). Approve or cut."
3. What is in scope and what is context? (Context, e.g. the upstream flow
   that leads to this PR's code, is collapsed behind a minimal strip.)
4. "Here are the entry points / paths I found in the code (callers listed).
   Is this complete?"
5. Which follow-ups are filed, which are design only, which are undecided?
6. Are the PR description and linked issues current? If not, I'll draft
   fixes there rather than note it on the page.
7. Any interactive element wanted? Default: none.
8. Where will it be published (GitHub Pages, a gist, a docs repo, local
   only), and which renderers are allowed (Mermaid via CDN, inline SVG)?

## Inputs to pin first
1. The PR number and repo (`<owner>/<repo>`), and the **full head SHA** the
   page describes:
   ```bash
   gh pr view <n> --repo <owner>/<repo> \
     --json number,title,body,baseRefName,headRefName,headRefOid,files,commits,url,reviewDecision
   ```
2. A local checkout that has the head commit (`gh pr checkout <n>` or
   `git fetch origin pull/<n>/head`). Read code with
   `git show "${SHA}:path"` (braces matter in zsh), never from a moving branch.
3. **Every entry point, from the code:** grep the callers of the changed
   components (and of any external API they wrap) before drawing any flow.
   Include the ones the PR does not touch.
4. The stacked or companion PRs, and whether each has its own walkthrough.
5. Any design doc or decision log the PR follows. Draw what the **code** does;
   label anything that exists only in the doc as planned. Cross-check the PR
   description and the log against the code, report each contradiction to the
   user, and fix the source (on their go) instead of carrying it onto the page.
6. Existing review feedback, so the page can answer it:
   ```bash
   gh api repos/<owner>/<repo>/pulls/<n>/comments --paginate   # line comments
   gh api repos/<owner>/<repo>/pulls/<n>/reviews --paginate    # review summaries
   gh pr view <n> --repo <owner>/<repo> --comments             # conversation
   ```
7. The diff, only to check claims (not to reproduce it on the page):
   `gh pr diff <n> --repo <owner>/<repo>`.
8. Re-check any older draft (issue drafts, earlier pages) against the head
   SHA before reusing it.

## Hard rules
- **Each fact once, preferably in a diagram.** Build the fact inventory first
  and give each fact one home. Never restate a diagram or the code in prose.
  One diagram per idea: if two sections show the same idea, merge them and
  fold any unique fact into the survivor as one line.
- **Each fact once across the stack too.** If a companion PR's walkthrough
  explains a model or flow, link to its section by anchor and title; keep one
  line on what this PR uses from it.
- **Only names that shipped.** Don't explain interim names that never reached
  the base branch or review (design-time words, keys renamed before review).
- **Length budget.** About 1,300 prose words (text inside `<main>`, excluding
  `<svg>`, Mermaid and scripts). A revision must not make the page longer
  unless the user asks. Default to not adding a diagram or section.
- **No "diff grouped by concern" section**, and no per-file tour of the diff.
  The Files changed tab already shows it.
- **No "where the PR description is out of date" section.** Fix the
  description instead: back up the live body (`gh pr view <n> --json body`),
  draft, show the diff, apply (`gh pr edit <n> --body-file ...`) only on the
  user's go. Terminology notes are plain facts with no pointer to the
  description.
- **Link to the code next to the claim it supports.** Two links per item:
  - lines at the head commit:
    `https://github.com/<owner>/<repo>/blob/<full-sha>/<path>#L10-L25`
  - the file in the PR diff:
    `https://github.com/<owner>/<repo>/pull/<n>/files#diff-<sha256(path)>`
    (the anchor is `diff-` plus the lowercase SHA-256 hex of the file path;
    append `R<line>` or `L<line>` for a line on the new or old side, e.g.
    `#diff-<hash>R42`)
  For a file the PR does not change, give the blob link and mark it
  "(unchanged)". Never cite `file.rb:12` as plain text.
- **Future work:** a link to a real issue, or "design only" plus the source
  document and section. Never cite drafts, "to be created", or a closed issue
  that is not the tracker. With no source, ask; never invent the shape. If the
  user wants it tracked, file it from the draft (on their go) and link it.
- **Open questions:** say them plainly, with no leaning, until the user decides.
- **Each mechanism section opens with why it exists**, in two sentences or fewer.
- **Stable anchors.** A descriptive `id` on every section and subsection
  (never a number), a visible `#` permalink on each heading, and ids on items
  reviewers may cite (each decision item). Never rename or delete a published
  id: when a section goes, keep its id as an alias (`<span id="old-id"></span>`)
  where its content now lives.
- **References survive renumbering.** Link by anchor and title ("see the
  ERD", "the anchor diagram"), not "section N", on the page, in PR comments
  and in replies to the user.
- **Describe the final change, not its history.** No "round 1 / round 2".
- **No live state that goes stale** (CI run numbers, approvals). Name the
  head SHA once, in the header and footer.
- Invented examples only. No real user or customer data.

## Visual rules
1. **Diagram vs table.** Diagram for order, flow, relationships and time
   windows (a timeline). Table only for reference lists (vocabularies, metric
   names).
   - Sequence diagram: what calls what, in which order.
   - System / flow diagram: entry points, the shared chain, outcomes.
   - Decision flow: "when does X happen, and what is written" (a few leaves).
   - Timeline: windowed rules (lookbacks, TTLs).
2. **The ERD is the only description of the schema.** Columns, types and the
   constraints that matter (NOT NULL, FK target and on_delete, unique,
   encrypted) go inside the entity. Draw the whole chain the change joins
   into, highlight the join columns, draw external systems as external
   entities keyed by their id, and mark new / existing / planned.
3. **Payloads as JSON, not tables.** Trace outputs, API bodies and stored JSON
   are shown as a real example (invented data), before and after side by side
   when the PR changes it, with a deep link to the filtered trace or log view
   and one-line notes under it. A key-by-key table only if the JSON fails;
   hover notes next.
4. **Never draw an absence or a non-event as a shape.** Say it in one line
   (caption or footnote).
5. **Every colour has a legend inside the figure, and one meaning per page.**
   Green: added by this PR, or the selected case. Dashed amber: skipped / no
   row. Grey band: context, external, or a UI boundary. Red: errors only,
   never "doesn't count".
6. **Steady-state cases only.** Rollout-only (transient) effects and redundant
   filters go in one footnote, or are dropped. About five cases at most per
   decision visual. No interactive explorers with presets; if one earns its
   place, it is collapsed by default, starts from a few named cases, and shows
   its result as a horizontal pipeline strip, not a field table.
7. **Labels must not suggest an outcome the term doesn't mean** (e.g. "routing
   run" read as "a route fired"). Use plain, outcome-neutral words, and mark
   the case the measurement is actually after.
8. **Crowded: split, never shrink** (e.g. upstream then downstream). Let a wide
   diagram break out of the text column
   (`width:min(1480px, calc(100vw - 32px))`, centred). No dashed borders on
   entities: they read as clipped.
9. **Draw a model's creation in the section that owns the model**, with its
   skip conditions from the code, and make the write order visible when a step
   depends on an earlier one.
10. **UI boundaries:** when several entry points live in one product surface,
    wrap them in a labelled band.

## Page skeleton
1. TL;DR: what it adds, how it links, what it doesn't change, flags. Three lines.
2. Why: two sentences (who needs it, and what was missing), then the ERD.
   For a reviewer new to the domain, a short drawn primer of the model and the
   data it emits comes first.
3. From entry point to row: the upstream context as a collapsed strip with the
   full diagram behind `<details>`, then the downstream diagram (entry points,
   shared chain, outcomes, entry points that write nothing).
4. Vocabularies: one small reference table.
5. One section per mechanism (rule, marker, guard), each opening with why.
6. Observability: signals, tags, log lines (a reference table is fine).
7. QA evidence: what was tested (case, how it was run, result, screenshot or
   trace link), and what was not tested. Trace links go to the right
   environment. Screenshots of invented test data only.
8. Decisions we made, and why; tracked follow-ups; release checklist (rules below).
9. Not in this PR, and what builds on it: real issues and "design only" items.

## Decisions we made, and why (not "what to check hardest")
Don't ask the reviewer to "check hardest". Explain each risky choice so the
reviewer can agree or push back. Three short parts, kept apart:
- **Decisions we made, and why.** One item per risky choice: the decision,
  why, and the mitigating factor (what limits the damage). Tie it to a diagram
  on the page where it helps. For a decision accepted earlier, cite where it
  is recorded (date and link). Before writing an item, establish from the
  code: the failure scenario (what triggers it), how likely it is, whether
  this PR makes it more or less likely, and the call (ship as is, fix in this
  PR, fix in the next PR). Put the conclusion on the page, not the analysis.
- **Tracked follow-ups.** Links to filed issues only, one line each. A drafted
  but unfiled follow-up stays off the page until it is filed.
- **Release checklist.** Deploy prerequisites and data caveats, one line each
  (secrets and keys per environment, "recall data starts at deploy + 24 h").
  Mirror them in the PR description's deploy notes.
Shorter than a "what to check" list: if an item needs a paragraph, it belongs
in a mechanism section or a follow-up issue.

## HTML conventions
- One self-contained file, light and dark (`prefers-color-scheme`), readable
  on a phone, reads correctly with no interaction (collapsed context aside).
- Hand-drawn inline SVG for flows, sequences and timelines. Define a shared
  arrow marker once (`<marker id="arr">`) in a hidden `<svg>` right after
  `<body>`; check every `marker-end:url(#...)` points at an id that exists.
- Mermaid for ERDs: a pinned `mermaid.esm.min.mjs` from jsdelivr, theme from
  `prefers-color-scheme`. Works on GitHub Pages (no CSP) and from `file://`
  in Chrome with network; offline it shows its source, so say so in the
  caption. Note that GitHub does not render uploaded HTML inline: publish via
  Pages, a gist preview service, or share the file directly. ER syntax: entity
  aliases (`T["tickets (NEW)"]`), `PK`/`FK`/`UK`/`FK,UK`, dashed non-FK
  relationships (`..`), `classDef` / `class` for new and external entities.
- Max ~12 nodes per diagram. Label every arrow. Estimate text width (~6.3 px
  per char at 11.5 px, ~7.5 px at 13 px bold) and widen or shorten.

## Code-link helper (Python, for pages built or revised by script)
```python
import hashlib

REPO = "https://github.com/<owner>/<repo>"
SHA = "<full head sha>"
PR = 123
BLOB = f"{REPO}/blob/{SHA}/"
DIFF = f"{REPO}/pull/{PR}/files"

def code(path, lines=None, label=None, in_diff=True):
    # lines: "30-40" or "35"
    frag = ""
    if lines:
        a, _, b = lines.partition("-")
        frag = f"#L{a}-L{b}" if b else f"#L{a}"
    inner = label or f"<code>{path.split('/')[-1]}{':' + lines if lines else ''}</code>"
    out = f'<a href="{BLOB}{path}{frag}">{inner}</a>'
    if in_diff:
        h = hashlib.sha256(path.encode()).hexdigest()
        return out + f' <a class="difflink" href="{DIFF}#diff-{h}">diff</a>'
    return out + ' <span class="muted">(unchanged)</span>'
```

## Verify before handing over
1. Every claim checked against the code at the head SHA (counts, names, lines).
2. Parse the HTML for unbalanced tags; assert every `href="#id"` resolves;
   grep for stale references after any structural change.
3. Word count before and after (prose only).
4. Render and look at each diagram. Playwright needs `http://` (serve the
   folder with `python3 -m http.server`; `file://` is blocked) and can hang;
   headless Chrome works as a fallback:
   `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --screenshot=out.png --window-size=1000,1200 file:///tmp/excerpt.html`
   (write an excerpt with the page's `<head>` plus one section). Fix
   overlapping, clipped or overflowing text.
5. **Open the page for the user** with `open <path>`.

## After the page
- Draft review comments (a top-level review guide plus notes on specific diff
  lines), each linking a section anchor by title. Draft only; post on the
  user's go (`gh pr review <n> --comment --body-file ...`, or
  `gh api repos/<owner>/<repo>/pulls/<n>/comments` for line comments), and
  only after the page with those anchors is published.
- Check the PR description and linked issues for terms the page corrected;
  back up, draft, diff, apply on the user's go.
- Record new feedback in `lessons.md`.
