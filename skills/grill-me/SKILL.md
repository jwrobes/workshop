---
name: grill-me
description: Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when user wants to stress-test a plan, get grilled on their design, or mentions "grill me".
disable_model_invocation: true
---

# Grill Me — Design Interrogation

> **Attribution:** Based on Matt Pocock's [grill-me](https://github.com/mattpocock/skills/tree/main/grill-me) skill. See [5 Agent Skills I Use Every Day](https://www.aihero.dev/5-agent-skills-i-use-every-day) for context.

Systematically interrogate every aspect of a plan, design, or proposal until all ambiguity is resolved and shared understanding is reached.

## Core Behavior

1. **Explore before asking.** If a question can be answered by reading the codebase, repo docs, or attached context — do that first. Only ask the user what the codebase can't tell you.
2. **One branch at a time.** Walk the decision tree depth-first. Fully resolve one branch (including its dependencies) before moving to the next.
3. **Recommend, then ask.** For every question, state your recommended answer with reasoning, then ask the user to confirm, reject, or refine.
4. **Track the tree.** Maintain a visible decision tree that updates as branches are resolved. Mark each node as resolved, open, or blocked.
5. **Be relentless.** Don't accept hand-waves. If an answer is vague, follow up. If a dependency is unresolved, flag it. Comfortable silence is fine — incomplete understanding is not.

## Interview Protocol

### Phase 1: Orientation

Before asking anything, do the following silently:

- Read any attached files, plans, or designs the user referenced.
- Scan the relevant codebase directories for existing patterns, constraints, and prior art.
- Identify the top-level decisions the plan requires.

Then present:

```
## Decision Tree (initial)

1. [ ] <Top-level decision A>
   1.1 [ ] <Sub-decision>
   1.2 [ ] <Sub-decision>
2. [ ] <Top-level decision B>
   ...
```

Ask the user: *"Here's how I see the decision space. Anything missing before we start?"*

### Phase 2: Depth-First Interrogation

For each open node, follow this loop:

1. **State context** — Summarize what you know (from codebase exploration or prior answers).
2. **Identify the question** — What exactly needs to be decided?
3. **Give your recommendation** — *"I'd recommend X because Y."*
4. **Ask for their call** — *"Does that match your thinking, or do you see it differently?"*
5. **Resolve or drill deeper** — If agreed, mark resolved. If new sub-questions emerge, add them to the tree and continue depth-first.

### Phase 3: Synthesis

Once all branches are resolved, produce a summary:

```
## Resolved Decision Tree

1. [x] Decision A → chosen option (rationale)
   1.1 [x] Sub-decision → chosen option
   ...

## Key Constraints Identified
- ...

## Open Items / Follow-ups
- ...

## Recommended Next Steps
1. ...
```

## Question Style Guide

- **Be specific, not generic.** Instead of *"How will you handle errors?"*, ask *"When the upstream API returns a 429, should the worker retry with backoff or dead-letter the message?"*
- **Surface hidden dependencies.** *"You said X for decision 2, but that conflicts with Y from decision 1 — how do you reconcile?"*
- **Challenge defaults.** *"You're choosing Postgres here — what's the write volume look like? Would you hit any scaling concerns in the next 12 months?"*
- **Probe edge cases.** *"What happens if this runs on an empty dataset? On 10M rows? On malformed input?"*
- **Ask about operations.** *"How will you know if this is broken in production? What's the rollback plan?"*

## Pacing Rules

- Ask **1–3 questions per turn**, grouped by the current branch. Don't shotgun 10 questions.
- If a branch is getting long, checkpoint: *"Here's where we are on this branch — [summary]. Ready to continue, or want to jump to another area?"*
- After resolving a branch, briefly recap before moving to the next.

## When the User Pushes Back

If the user says "good enough" or tries to skip a branch:
- Acknowledge it: *"Got it, you want to move on."*
- Flag the risk: *"Just noting that [X] is unresolved — it could bite us when [Y]. Want to leave it as an open item?"*
- Respect their call, but log it in the decision tree as `[ ] (deferred)`.
