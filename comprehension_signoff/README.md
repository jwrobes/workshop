# comprehension_signoff

A Claude Code skill that runs a post-ship comprehension gate on AI-assisted code. Generates layered explainer artifacts (architecture diagram, plain-language walkthrough, annotated code, glossary, blast-radius list), then verifies the user's understanding through teach-back graded against the SOLO taxonomy.

This is a **standalone skill** — there's no companion tool. The skill folder is also the install target.

## Why

Vibe-coded code looks finished but isn't *understood*. The gap shows up in week-7 maintenance: nothing works and no one knows why. The N=78 Explanation Gate experiment (arXiv 2602.20206) cut post-AI maintenance failure from ~77% to ~39% by gating merges behind a graded explanation. This skill turns that gate into a repeatable workflow.

Full research dossier in [`reference/research.md`](./reference/research.md). The skill design cites it throughout.

## Install

This skill is local-only — not part of the synced `~/workspace/skills/` repo. Symlink it into Claude Code's skills directory:

```bash
ln -sf /Users/jonathanwrobel/workspace/workshop/comprehension_signoff \
       ~/.claude/skills/comprehension-signoff
```

Verify:

```bash
ls -la ~/.claude/skills/comprehension-signoff
```

Then in any Claude Code session, type `/comprehension-signoff` or trigger it by description (e.g., "run a comprehension check on the last commit").

## Usage

After a large AI-assisted change you intend to maintain:

```
> I just vibe-coded a chunk of the auth flow. Run a comprehension check.
```

The skill walks four phases:

1. **Scope & artifact generation** — picks key components, writes artifacts to `./.comprehension/<slug>/`.
2. **Confidence pre-rating** — you rate 1–5 per component before quizzing.
3. **Active verification (the gate)** — teach-back + predict-the-output + blast-radius. Graded to SOLO ≥ Relational. Loops with Socratic hints until pass.
4. **Sign-off record** — writes `signoff.md` with the pre-ratings vs graded outcome, residual gaps, follow-ups. Commit it alongside the change.

Skip the gate for throwaway prototypes — the friction (~10–15 min) only pays back on code you'll maintain.

## Layout

```
comprehension_signoff/
├── README.md              # This file
├── SKILL.md               # The skill itself (what Claude Code loads)
└── reference/
    ├── research.md        # Full research dossier (cite when updating design)
    └── solo_rubric.md     # SOLO grading rubric with examples
```

## Updating

When the evidence base shifts (new studies, new failure modes observed in practice), update `reference/research.md` first, then revise `SKILL.md` to reflect any changed thresholds or workflow steps. The research file is the canonical record of *why* the skill is shaped the way it is.

## Status

Alpha. Designed but not yet validated against the study's blackout-maintenance protocol on real changes. If first uses suggest the gate is theater (users routinely pass without genuine understanding) or pure friction (users bypass it), see the *Calibration* section of SKILL.md and tighten or fade accordingly.
