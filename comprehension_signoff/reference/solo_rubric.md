# SOLO Taxonomy Grading Rubric

Used by the `comprehension-signoff` skill to grade teach-back answers. Pass threshold: **Level 3 (Relational) or higher**.

SOLO = Structure of Observed Learning Outcomes (Biggs & Collis, 1982). Originally for educational assessment; used in arXiv 2602.20206's Explanation Gate to grade explanations of AI-generated code.

## Levels

### Level 0 — Prestructural
The answer misses the point entirely or restates the question. No relevant content.

> *"Uh, it's a function that does the thing."*

**Fail.**

### Level 1 — Unistructural
Names exactly one piece of the component. Treats it in isolation. No connections to anything else.

> *"It uses a mutex."*

**Fail.** Hint at: "What does the mutex protect, and what happens when two callers race for it?"

### Level 2 — Multistructural
Lists multiple correct pieces, but as a flat enumeration. No causal links between them.

> *"It uses a mutex. It also has a retry loop. And there's a timeout."*

**Fail.** This is the most common failure mode for AI-assisted code — the user has *recognized* the components without *integrating* them. Hint at the connections: "How do those three interact when the timeout fires while the mutex is held?"

### Level 3 — Relational ✅
Connects pieces causally. Explains *why* X leads to Y, what triggers what, and what depends on what. Sees the component as an integrated system.

> *"The mutex serializes writers so the retry loop can safely re-read state without seeing a partial update. The timeout exists because the retry loop has no natural ceiling — if the lock holder crashed, we'd spin forever without it. So the timeout is the safety valve that converts a deadlock into a recoverable error."*

**Pass.** This is the threshold the skill gates on.

### Level 4 — Extended Abstract
Generalizes beyond the specific code. Identifies the invariant, the design principle, or the class of problems this pattern solves. Connects it to other parts of the system or to broader patterns.

> *"This is the standard lock-with-bounded-retry pattern — anywhere we have a shared resource plus a possibly-faulty holder, you want exactly these three pieces. The same shape shows up in our DB connection pool and the cache invalidation path."*

**Pass.** Don't *require* this — most working engineers operate at L3 and that's enough.

## Grading procedure

1. **Read the user's answer once without judgment.**
2. **Independently re-derive the right answer from the code** — not from the artifacts the skill generated. (Reading the artifacts and then grading inflates pass rates because the artifacts are the answer key.)
3. **Locate the highest level the answer reaches.** If it has a Level 3 thread and some Level 1 noise, it's Level 3.
4. **If borderline, downgrade.** The cost of a false pass (user thinks they understand and ships a bug) is higher than the cost of a false fail (one more question).
5. **If failed, identify the gap precisely.** "You skipped the failure mode" is better than "try again." The hint should make the gap visible without revealing the answer.

## Anti-patterns to flag

- **The recitation.** User regurgitates the walkthrough verbatim. Test: ask a question whose answer is *not* in the walkthrough.
- **The confident handwave.** User uses correct-sounding vocabulary without committing to mechanics. Test: ask for the order of operations.
- **The deflection.** "Well, that depends on the implementation." Test: pin them to *this* implementation, the one in front of them.
- **The "I would just..."** User describes what they would write, not what the code in front of them actually does. Test: ask them to point at the line.
