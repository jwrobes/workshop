---
name: sharpen-prompt
description: Tighten a rough, bundled, or ambiguous prompt before it goes to another Claude session (a "main" session, a teammate agent, a scheduled job). Splits bundled asks apart, resolves ambiguous references against whatever context is available, reorders buried priorities, flags scope conflicts, and surfaces genuine open decisions instead of silently picking one. Output is a single copy-paste-safe block with explicit copy boundaries (fenced code, never blockquote — `>` corrupts multi-line paste in tmux and most terminals), carrying a READY / NOT READY verdict: open questions that would change words in the prompt block the copy until answered, while ones that only affect what happens afterward are flagged as non-blocking. Anything the user needs to read but must not paste — a false premise found in the draft, say — is separated out under its own label rather than blurred into the message. Every pass logs which failure patterns showed up, so the user can see their own recurring drafting habits over time — say "review my prompt log" for a rollup, or "sync my prompt log" to mirror it to a configurable durable location, instead of a fresh sharpen. Use when the user says "sharpen this prompt", "clean this up before I send it", "tighten this for the other session", "make this copy-pasteable", "review my prompt log", "how am I doing with prompts", "sync/push/share my prompt log", or hands over a rough draft meant for another agent/session to execute.
disable_model_invocation: true
---

# Sharpen Prompt

Take a rough prompt the user is about to send to another session (or another agent) and return a
tightened version, ready to paste, plus a short account of what changed and what's still an open call.

## The token-spend rule: identity, not execution

This skill optimizes for a fast turnaround on the sharpened prompt, not for doing the target session's
work early. Every tool call/lookup has to earn its place against one test:

**Would the answer change which task gets done, or only how well it gets done?**

- **Which task (check it — cheap, high-value):** referent resolution when two real things could be
  meant ("current branch" with two candidate branches in play), a false premise baked into the
  instruction itself (the draft assumes a file/branch/label/issue exists — a wrong guess here means the
  target session executes against a premise that isn't true and may never notice), a stale context
  pack. Get these right; a silent wrong pick here is exactly the failure this skill exists to prevent.
- **How well (skip it — expensive, low-value here):** diff stats, commit/line counts, code quality,
  whether an approach is actually sound, or anything the target session would hit as its own natural
  first step of doing the work. Don't pre-run the task to sharpen its instructions. This is the most
  common way the skill drifts into doing the work instead of tightening the ask — it looks thorough but
  it's redundant token spend, since the target session was going to produce that exact finding anyway.

Fast test: if resolving a claim changes a word in the sharpened prompt, check it. If it would only
change what a good *execution* of that prompt eventually turns up, leave it — name it as something the
target session should verify, don't verify it yourself.

Default to zero tool calls beyond what the user pasted or named directly. Escalate only for an
identity-level check from the list above, and stop the moment it's resolved — don't keep pulling once
the referent is disambiguated.

## Step 0 — Get context before touching the wording

Never sharpen a prompt using only what's in the current conversation if the task references external
state (a codebase, a tracker, epics/issues, prior decisions) that this session hasn't loaded. Check
what's actually available:

- If the target is a tracked item (GitLab/GitHub issue or epic, a Linear ticket, a file, a URL) — read
  it if a tool is available. Don't guess its state.
- If the user references "the doc", "the map", "what we decided", "the existing work" and no such
  doc/context is visible in this conversation or provided as an argument — **ask for it by name before
  proceeding.** Something like: *"To sharpen this well I need [X] — can you point me at it, or should I
  work from the prompt text alone?"*
- If the user is fine working from the prompt text alone (no extra context available or wanted), say so
  explicitly in the output rather than silently proceeding as if you had verified something you didn't.
- If it's not obvious which model will receive the sharpened prompt, ask. It changes real wording
  choices — see Step 1.5.
- **If a referenced context pack (e.g. `PROMPT_PACK.md`) looks stale** — a quick live spot-check
  disagrees with it, or its own dated header is old relative to the task — **say so and stop there.**
  Tell the user to run the `refresh-context-pack` skill in a session with full project/tracker access.
  Do not try to refresh it yourself from here: that's a heavyweight, live-tracker-pull task, and this
  skill is deliberately kept light and fast. The two are decoupled on purpose — don't re-couple them.

Only skip this step when the prompt is fully self-contained (no external references) or the user has
already supplied everything needed.

## Step 1 — Find what's actually wrong with the draft

Rough prompts fail in a small number of recurring ways. Check for each:

| failure | what it looks like | fix |
|---|---|---|
| **Bundled asks** | Several unrelated actions in one breath — create X, verify Y, research Z, and also loop in a person — with no ordering | Split into a numbered sequence; put the highest-leverage/blocking step first |
| **Buried priority** | The real instruction shows up after "but actually" or "wait, first" — a literal read would do the wrong thing first | Reorder so the stated final priority is step 1 |
| **Uncertain references** | "I have some code somewhere", "I think it's called X", a half-remembered file/table name | Keep the lead but mark it uncertain — tell whoever executes to search broadly and report what they actually find, not to assume the guess is correct |
| **Garbled/typo'd clauses** | A sentence that doesn't parse cleanly | Restate your best-guess reading plainly; don't just relay the typo |
| **Scope conflicts within the same message** | The user states scope A early and scope B (wider or narrower, or a different set of targets) later in the same draft | Do not silently pick one — flag it as an explicit either/or for the user to resolve before sending |
| **Silently-resolved judgment calls** | A real decision only the user (or someone with authority — an SME, a manager) can make, currently being glossed over | Surface it as a named open question; don't decide it for them |
| **Unlinked answer** | The draft reads as a reply to a question that isn't present anywhere in this session's context — an ambiguous referent with no visible antecedent ("rounds," a bare pronoun, a decision with no stated subject) | Don't guess at the missing question and don't sharpen as if the context were there. Name the ambiguous term and ask the user which they'd prefer: a one-shot pull of the other session's last message, or pasting the triggering question themselves. Only proceed once one of those happens — never guess, never proceed silently without either |

Apply the identity-vs-execution rule above here: check claims that would change which task gets done
(does this file/branch/issue exist, is "it" ambiguous between two real things) — skip claims that are
about how well the task would go (is this a good approach, how much work is on a branch). If you find a
concrete identity-level discrepancy, name it precisely — what disagrees with what — rather than a vague
"double-check this," and stop there; don't keep investigating past the point where the referent or
premise is settled.

**On "unlinked answer": ask before fetching, never automatically.** This skill does not read another
session's transcript by default. When `unlinked-answer` fires, ask the user which they'd rather do — a
one-shot pull of just the other session's **last message** (never its full transcript, never persisted
across passes — no digest file, no standing subagent), or pasting the triggering question themselves.
Act only on whichever they choose; never guess, and never proceed silently without one or the other. If
a pull is chosen but that session isn't reachable, say so plainly and fall back to asking for a paste —
don't silently drop the check.

**Exception: paired sharpen sessions.** When this skill runs in a session launched by the workshop's
`sharpen session` (tool: `workshop/sharpen_prompt/`), the user opted in to pairing with one
working session, and a hook attaches that session's last message to each draft as a
`<working_session_last_message>` block. Treat that block as the antecedent for `unlinked-answer`, and
ask only if it is absent or doesn't resolve the referent. It's still last-message-only, and it's local
to the user's machine. Follow the session prompt that comes with it for the header line, fence width,
and draft/refine handling.

## Step 1.5 — Account for the target model

The same instruction can need different phrasing depending on which model receives it. The two Jon
actually routes prompts to:

- **Opus 5** (usually "the main session"): verbose by default — `effort` does not reliably shorten it,
  so if brevity matters, say so explicitly. Already self-verifies well — don't bolt on "please
  double-check your work," it's redundant and adds latency. Delegates to subagents readily — if a step
  is simple, sequential, or single-file, say "work directly, don't delegate" rather than leaving it open.
- **Sonnet 5** (this skill's own model, or when Jon targets it deliberately): very literal
  instruction-following. Ambiguity a more inferential model would paper over, Sonnet won't — so for a
  Sonnet-bound prompt, disambiguating in Step 1 matters *more*, not less.

Cross-model, regardless of target:

- **"Can you suggest X?" gets a suggestion, not action.** If the draft wants something *done*, the
  sharpened version should say "implement/change/create X," not "can you look at X."
- **Irreversible or shared-system actions** (push, force-push, external messages, deletions) — state
  explicitly whether confirmation is wanted before those. Don't assume the target session's own defaults
  cover it; the sharpened prompt should say so if it matters for this specific task.
- **"Let's use a subagent for X"** — check whether X is actually parallelizable or needs isolated
  context. If it's simple or sequential, direct action is faster and the subagent instruction should
  come out, not just get relayed.

Full detail, other models (Fable, Haiku), and anything migration-related:
`references/model-guidance.md` — re-verify against that doc before trusting a specific claim; Anthropic
updates model behavior as new versions ship, and this reference will drift.

## Step 2 — Output format

Always return these parts, in this order. Part 0 appears only when there's something to say.

### 0. Read first — not part of the message (only when needed)

When sharpening turned up something **you** need to know before deciding whether to copy — a premise in
the draft that turned out to be false, a referent that resolved to something unexpected, a stale pack —
put it here under an explicit label:

```
**▼ READ FIRST — not part of the message**
```

Two rules, because this section's failure mode is real:

- **Never let it duplicate the prompt.** If the same finding also belongs *inside* the message (because
  the target session needs it too), state it here in one or two lines and say it's folded into the
  message below — don't write the full version twice. Two near-identical paragraphs with different
  audiences and no labels is the exact confusion this part exists to prevent.
- **Keep it to what changes your decision to send.** Findings that merely explain your own sharpening
  choices belong in "what changed," not here.

### 1. The message to copy, with a readiness verdict

Lead with a status line, then the prompt in a **fenced code block, never a blockquote** (`>`).
Blockquote markdown prefixes every line with `>` on copy in tmux and most terminals, corrupting a
multi-line paste. Code fences copy clean.

Mark the copy boundaries explicitly so the copyable text can't be confused with the commentary around
it — inline code in the "what changed" bullets otherwise blurs where the message stops. Both markers go
**outside** the fence; anything inside it gets copied along with the message.

```
**▼ MESSAGE TO COPY — READY**

<fenced code block containing the prompt>

**▲ END OF MESSAGE**
```

When something blocks readiness (see part 3), the status line instead reads:

```
**▼ MESSAGE TO COPY — NOT READY** (N blocking question(s) below)
```

Still show the prompt in that case — a best-guess version, clearly labeled — and name which specific
line or paragraph changes depending on the answer. Withholding the draft is worse than labeling it;
don't emit two full variants unless the answer genuinely forks the whole message.

### 2. What changed and why

Short bullets. What you split, reordered, disambiguated, corrected, or removed — and the reason.

### 3. Open questions, classified by whether they block the copy

Every open question from Step 1 (scope conflicts, judgment calls, unlinked answers) gets sorted into
one of two buckets, and each is phrased as a choice — or, for an unlinked answer, as a named request
for the missing question — not a recommendation dressed as a question.

- **Blocking — answer before sending.** The answer changes *words in the prompt*. A scope conflict
  (which target set?), a decision baked into the instruction as a silent assumption, an unlinked
  answer with no resolved referent. Say plainly that the message isn't ready until it's answered.
- **Worth considering — doesn't change the message.** The answer only changes what happens *after*
  the prompt runs, or is a downstream decision the target session will surface on its own. Say so
  explicitly: *"this doesn't affect the message — just flagging it."* Don't let it gate the copy.

**Default to non-blocking; bias hard against over-gating.** This is the same identity-vs-execution
test the token-spend rule uses: if the answer would change which task gets asked for, it blocks; if it
would only change how well that task goes, it doesn't. A pass that ends in "answer three things before
you can copy this" has defeated the point of the skill. Blocking should be uncommon and obviously
justified when it fires.

If there are no open questions at all, say that in one line rather than omitting the section — "no
open calls this pass" is useful signal that the draft resolved cleanly.

Keep every part tight. The point is a faster next turn for the user, not a longer one.

## Step 3 — Log the pattern

Append one row to `log/prompt_log.md` (create it from the template there if it's ever missing) — every
pass, not just the messy ones. Columns: date, target model, the failure-pattern tags from Step 1 that
actually applied (comma-separated, exact tag names — `bundled-asks`, `buried-priority`,
`uncertain-reference`, `garbled-clause`, `scope-conflict`, `silent-judgment-call`, `unlinked-answer`;
empty if genuinely none applied), a one-line context (what the prompt was for — not the full draft),
and an optional note.

This is the point of the skill, not a side effect. The sharpened prompt fixes today's draft; the log is
what teaches Jon to stop needing the fix. Don't skip it because the draft seemed clean — a clean pass is
signal too.

## Step 4 — Sync the log (on request only, configurable)

The local log is always the source of truth and Step 3 never depends on anything outside
`~/.claude/skills/sharpen-prompt/`. Syncing it somewhere durable/shared is a separate, explicit action —
never automatic — so the skill keeps working even where the sync target isn't reachable.

Triggered by "sync my prompt log," "push my log," "share my log," or similar:

1. Read the sync target from `~/.config/sharpen-prompt/prompt-log-sync.yaml`
   (`sync_target:` key). This is a personal config file: a path, not logic.
2. If that config file doesn't exist, **ask where to sync** rather than assuming none is wanted, and
   offer to write the config so future syncs don't need to ask again.
3. Copy the full current contents of `log/prompt_log.md` to the target path, overwriting it. This is a
   one-way mirror (local → target); the target is never read back as a source. Preserve or add a
   one-line HTML comment at the top of the target noting it's a mirror and the local path that's
   authoritative, so nobody edits the copy directly.
4. Confirm what was synced (row count, target path) — don't just say "done."

## Review mode

Triggered by "review my prompt log," "how am I doing with prompts," "what are my patterns," or similar
— instead of sharpening a new draft, read `log/prompt_log.md` and report back:

- Tally each failure tag over the requested window (default: all entries, or the last N if the user
  says a number/timeframe).
- Name the single most frequent tag and give one concrete, specific behavioral fix for it — not "be
  clearer," something Jon can actually do differently before he types the next rough draft (e.g. "write
  your asks as a numbered list before sending, even roughly — that alone kills bundled-asks").
- If a tag that was frequent earlier has dropped off in recent entries, say so — that's the actual
  signal that something is improving, and it's worth more than the raw counts.

Keep the report short. A long report about being told to write short prompts is its own failure.

## Example shape (illustrative, not literal)

Rough input: *"start doing X for that thing, oh also check if Y is right, and I think there's some old
code for Z somewhere, let's use a subagent for that, but actually let's do the simple part first."*

Output:
- **▼ MESSAGE TO COPY — READY** / fenced block / **▲ END OF MESSAGE**: reordered so the simple part is
  step 1, Y-verification is step 2 with the specific discrepancy named, Z becomes step 3 with "search
  broadly, the exact name may be wrong" attached.
- What changed: split 3 bundled asks into ordered steps; moved "the simple part" to step 1 per the
  user's own correction; flagged Z's naming as uncertain rather than passing it through as fact.
- Open questions: *worth considering* — whether Z's old code is even still worth reusing once found
  (doesn't change the message; the target session will surface it). Nothing blocking, so the status
  line reads READY.
- Log row: `2026-09-15 | opus-5 | bundled-asks, buried-priority, uncertain-reference | <one-line context> |`

Two contrasts:

- If checking Y had shown the draft's premise about it was **false**, that goes in **▼ READ FIRST — not
  part of the message** in one or two lines, noting the correction is folded into the message below —
  not restated at full length in both places.
- If the draft had said *"do this for the auth module"* early and *"actually do it repo-wide"* later,
  that scope conflict changes what the prompt instructs, so the status line would read **NOT READY
  (1 blocking question below)** and the open-questions section would name the either/or.
