# Model-specific prompting guidance — reference

Distilled from Anthropic's [Prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)
for the purpose of *sharpening natural-language prompts sent to another Claude Code session* — not
raw API integration. Skipped entirely: prefill migration, `thinking`/`budget_tokens` API parameters,
LaTeX/output-format flags, vision/frontend-design guidance. None of that changes how you phrase an
instruction to another agent. Re-verify anything below against the source doc before trusting a
specific claim on a model newer than the ones listed here.

## Opus 5

The usual target when Jon says "the main session."

- **Verbose by default, and `effort` doesn't reliably fix it.** If a task should come back short, say
  so explicitly in the prompt — don't rely on effort level.
- **Self-verifies well already.** Don't add "please double-check your answer" — that's boilerplate
  tuned for older models and just adds latency here.
- **Delegates to subagents readily**, sometimes past the point of being useful (e.g. spawning a
  subagent for something a direct grep would answer faster). If a step is simple, sequential, or
  single-file, say "work directly, don't delegate" rather than leaving it open.
- Response length, user-facing progress updates, and written-deliverable length all run longer than
  prior Opus models by default — same fix as above: ask explicitly for the length you want.

## Sonnet 5

- **Very literal instruction-following.** Ambiguity a more inferential model would smooth over, Sonnet
  won't — it does closer to exactly what's written. This cuts both ways: it also means Sonnet is the
  cheapest model to trust with a *precisely* sharpened prompt, and the worst one to hand a vague draft.
- Response length, tool-use triggering, and effort/thinking-depth calibration differ from Sonnet 4.6,
  but the literalness point above is the one that most changes how you'd phrase something for it.

## Cross-model techniques (apply regardless of target)

- **Say what to do, not what not to do.** "Your response should be flowing prose" beats "don't use
  markdown."
- **"Can you suggest X?" gets a suggestion. "Implement X" gets action.** If the rough draft wants
  something done, the sharpened version needs the imperative verb, not the polite question.
- **Be specific about format and constraints up front**, and give steps as an ordered list when order
  or completeness matters — a model won't infer "do this before that" from prose alone.
- **The golden-rule test still applies:** if a colleague with minimal context would misread the
  instruction, so will the model.
- **XML tags help when a prompt mixes instructions, context, and examples** in one block — wrap each
  in its own tag so the boundaries are unambiguous. Mostly matters for long or example-heavy prompts,
  not short task instructions.
- **Irreversible or shared-system actions** (push, force-push, external messages, deletions) — state
  explicitly whether the target session should confirm before those. Don't assume its defaults cover
  it; say so if it matters for this specific task.
- **Subagent orchestration is now largely automatic** — current models recognize when to delegate
  without being told. The failure mode worth catching in a rough draft is the opposite: "let's use a
  subagent for X" when X is small, sequential, or needs no isolated context — that instruction usually
  should come *out*, not be relayed as-is.

## Other models, briefly

- **Fable 5 / Fable 5.1 (and Mythos variants):** different defaults around effort levels, long-task
  completion, user-facing progress narration (Fable 5.1 under-narrates by default — ask for progress
  text explicitly if wanted), and thinking-block handling in multi-turn agent loops. Not part of Jon's
  current workflow; check the source doc directly if this becomes relevant.
- **Haiku 4.5:** not covered separately in the source doc beyond being listed as a current model.
