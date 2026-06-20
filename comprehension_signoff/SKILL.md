---
name: comprehension-signoff
description: Run a post-ship comprehension gate on AI-assisted code — generate layered explainer artifacts, then verify the user's understanding through active recall, teach-back graded to SOLO ≥ Relational, and predict/blast-radius questions. Use when the user says "comprehension check", "do I actually understand this", "sign off on this code", "comprehension gate", "I just vibe-coded this", or after a large AI-generated change they intend to maintain. Skip for throwaway prototypes.
disable_model_invocation: true
---

# Comprehension Sign-Off

Close the gap between *the code works* and *I understand the code well enough to maintain it*. This skill runs **after** a vibe-coding or large AI-assisted change, produces layered explainer artifacts, then gates a sign-off behind active verification of the user's understanding.

> Grounded in research collected in `reference/research.md`. Update that file when the evidence base changes — the design choices below cite it.

## When to use

| Trigger | Action |
|---|---|
| User says "comprehension check / gate / sign-off" | Run full workflow |
| User says "I just vibe-coded this and want to make sure I get it" | Run full workflow |
| Just-merged AI-generated change >~100 lines that the user intends to maintain | Suggest the skill, then run if accepted |
| Throwaway prototype, spike, or one-off script | Skip — the gate is friction without payoff |
| User is a domain expert on the code in question | Offer light mode (artifacts only, lighter quizzing — see *Calibration* below) |

## Why this design

The illusion of explanatory depth means re-reading AI code and *feeling* confident is a near-worthless signal — the gap collapses the moment you try to produce a causal explanation. So this skill forces production of explanation, not recognition. The N=78 "Explanation Gate" experiment (arXiv 2602.20206) cut post-AI maintenance failure from ~77% to ~39% by gating merges behind SOLO ≥ Relational explanations; that's the empirical anchor for the gate threshold here.

Key principles the workflow encodes (full citations in `reference/research.md`):

- **Recall, not recognition.** Quiz the user; don't re-show the explanation.
- **Self-explanation must be demanded.** Most users won't volunteer it.
- **Grade with a separate pass.** Reduces self-preference bias when one model both teaches and grades.
- **Calibrate to expertise.** The expertise reversal effect: heavy scaffolding hurts experts. Fade friction for users who consistently hit Relational+ on first try.
- **Record the sign-off.** Pays down "intent debt" (Storey) — the missing externalized rationale that makes the system unmaintainable.

## Workflow

The skill runs four phases. Phase 3 is the gate — do not skip ahead to Phase 4 until every key component passes.

### Phase 1 — Scope & artifact generation

1. Identify the **change set** to comprehend. Default: uncommitted diff + last N commits the user names. Ask if unclear.
2. Identify **key components** — the parts whose failure would matter. Pick from: entry points, state management, security-sensitive paths, novel logic, anything touching shared state, anything the user said they don't fully follow. Cap at ~5 components for a single session; if there are more, batch into multiple sessions.
3. Produce artifacts in `./.comprehension/<short-slug>/`:
   - `architecture.md` — Mermaid diagram of the changed flow, with each key component labeled.
   - `walkthrough.md` — plain-language ("explain it to a smart 12-year-old") walkthrough of each flow. One section per key component.
   - `annotated.md` — the most critical functions, annotated inline with *why* each block exists, not *what* it does.
   - `glossary.md` — project-specific terms, acronyms, and any domain concepts the change relies on.
   - `blast_radius.md` — "what breaks if X changes" list. One entry per key component, with the downstream things that would silently break.

Tell the user the artifacts are ready and ask them to read them before Phase 2. Do not rush them.

### Phase 2 — Confidence pre-rating

Before any quizzing, ask the user to **self-rate 1–5** for each key component:

> *"On a 1–5 scale, how well do you feel you understand &lt;component&gt;? (1 = could not explain it; 5 = could teach it cold)"*

Record these in `.comprehension/<slug>/signoff.md` under a `pre_ratings:` block. **Do not argue with the rating.** The point is to expose miscalibration later by comparing the pre-rating against the graded performance — that gap is the data, not the rating itself.

### Phase 3 — Active verification (the gate)

For each key component, run a mix of three question types. Aim for ~2–4 questions per component, not a quiz marathon — the goal is depth on the load-bearing parts.

1. **Teach-back.** *"In your own words, explain how `<component>` handles `<specific concern>`. Focus on cause and effect — what triggers what, and why."* Free-form answer.
2. **Predict-the-output.** Give a concrete input or scenario. Ask what happens, in what order, and what state the system is in afterward. Do not let the user run the code first.
3. **Blast radius.** *"If we changed `<X>` to do `<Y>` instead, what breaks?"* Pull candidates from `blast_radius.md`.

**Grade teach-back answers against SOLO** (see `reference/solo_rubric.md`). Require **Level 3 (Relational) or higher** to pass that question:

- Level 1 (Unistructural) — names one piece, misses connections. **Fail.**
- Level 2 (Multistructural) — lists multiple pieces, no causal links. **Fail.**
- **Level 3 (Relational) — connects pieces causally, explains why X leads to Y. Pass.**
- Level 4 (Extended Abstract) — generalizes, identifies invariants, sees the principle. Pass.

When grading, do a **separate pass**: read the answer, then independently re-derive the right answer from the code, then compare. Do not let your own explanation in the artifacts anchor the grade.

**Below threshold:** Do not reveal the answer. Give a Socratic hint that points at *the gap*, not the answer:

> *"You described what happens on the happy path, but didn't address the case where the lock is already held. Walk me through that branch."*

Loop until pass, or until the user explicitly defers the component (record it as a known gap in the sign-off).

### Phase 4 — Gated sign-off & record

Only when **every key component** has at least one passing teach-back **and** the user has answered at least one predict-the-output **and** at least one blast-radius question per component, emit the sign-off.

Write `./.comprehension/<slug>/signoff.md`:

```markdown
# Comprehension Sign-Off

- **Date:** <ISO date>
- **Commit:** <SHA of HEAD>
- **Change set:** <description>
- **Components covered:** <list>

## Pre-ratings vs outcome
| Component | Self-rating | First-try SOLO | Final SOLO | Iterations |
|---|---|---|---|---|
| ... | 4 | L2 | L3 | 2 |

## Residual gaps (signed off with awareness)
- <component>: <what the user knows they don't know>

## Recommended follow-ups
- <e.g., write a property test for the lock-handoff path>
- <e.g., revisit blast_radius.md before changing X>
```

Tell the user to commit `.comprehension/<slug>/` alongside the change. The sign-off doubles as the missing-rationale documentation that makes the code maintainable in three months.

## Calibration (expertise reversal)

Adapt friction to the user's demonstrated competence — heavy scaffolding for novices, light touch for experts on familiar ground:

- **Light mode.** User asks for it, or has passed at Relational+ on the first try for the last ~3 components in this session: skip predict-the-output, ask only one teach-back per component, still gate on SOLO ≥ 3.
- **Heavy mode.** First-try fails, large miscalibration (e.g., self-rated 5, graded L1), or user explicitly says "be tough": all three question types, more questions per component, no fading.
- **Default mode.** What the workflow above describes.

The point isn't to be lenient — it's to put friction where it pays. Burning a senior engineer's time on code they already understand erodes trust in the gate. Letting a confident-but-wrong user skip the verification erodes the gate's purpose.

## What this skill will not do

- **Will not grade itself as the sole judge.** When the same instance generates artifacts and grades answers, self-preference bias inflates pass rates. If a second model is available, have it grade; otherwise, re-derive the answer from the code (not the artifacts) before grading.
- **Will not let the user bypass the gate silently.** If they want to defer a component, that's fine — but it gets recorded as a residual gap, not erased.
- **Will not run on throwaway code.** The gate has real friction (~10–15 min). Prototypes and spikes don't earn that cost.

## References

- `reference/research.md` — full research dossier: cognitive/comprehension/epistemic debt, the Explanation Gate experiment, learning-science principles, Anthropic skill-authoring guidance. Cite this when revisiting design choices.
- `reference/solo_rubric.md` — the grading rubric with examples.

## Updating this skill

When the evidence base shifts, update `reference/research.md` first, then revise this SKILL.md to reflect any changed thresholds, rubric levels, or workflow phases. Note the change in the sign-off record's commit so future-you can diff design intent against design history.
