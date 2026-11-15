---
name: code-review
description: Seven-phase code review checklist (architecture, collaboration, naming, errors, tests, frontend, commits) with a 0–3 per-phase scoring rubric. Use for any backend or frontend MR/PR review.
---

# Code Review (Seven Phases)

You conduct code reviews using a single phased workflow that keeps feedback
**line-level, actionable, and prioritized**. The phases run **in order**; within
each, mark items **pass**, **gap**, or **n/a** and explain why.

This skill is intentionally opinionated and Rails/React-flavored, because
that's the stack it grew out of. Apply the **principles** with current
equivalents in your stack.

---

## 1. When to Use

Use this skill for any code review, including:

- **Backend** — models, concerns, controllers, services, workers, state machines, GraphQL types/resolvers.
- **Frontend** — React (or equivalent) components, styles, client GraphQL, accessibility-sensitive UI.
- **Infrastructure / delivery** — CI config, queues, Docker, deploy templates, schema artifacts.
- **Full-stack changes** — run all relevant phases; skip phases with **n/a** and note why briefly.

---

## 2. Review Process (Seven Phases)

| Phase | Focus |
|-------|--------|
| **1** | Architecture / organization / platform seams |
| **2** | Pairing & collaboration / reviewer affordances |
| **3** | Naming & domain alignment |
| **4** | Error handling & defensive coding |
| **5** | Testing completeness |
| **6** | Frontend quality |
| **7** | Commit discipline & change narrative |

**Triage**

- **Backend-only MRs:** Phases 1–5 and 7; phase 6 **n/a**.
- **Frontend-only MRs:** Phase 1 may be lighter (still check file organization and change shape); phases 4–5 apply to JS error paths and tests; phase 2 still applies (reviewability, handoff).
- **Infra-heavy MRs:** Phase 1 plus blast radius / rollback / observability hooks deserve extra weight.

**Closing summary:** Always separate **blocking** vs **nice-to-have**, tie blockers
to **correctness, safety, or maintainability**, and cite **one or two in-repo
patterns** to mirror.

---

## 3. Per-Phase Checklists

### Phase 1: Architecture & Organization

**Atomicity & change shape**

- [ ] Each logical chunk of the diff is **one short sentence**; unrelated refactors, formatting, and features are **not** bundled without justification.
- [ ] Methods and classes do **one clear job**; no mystery "do everything" methods.
- [ ] Commits and MR slices aim for **revert-friendly** units. **Medians matter more than means** — flag **unnecessary** giants, not every large generated diff (lockfiles, schema, structural moves).

**Layering & entry points**

- [ ] **Worker / interactor / service object** is the obvious home for heavy multi-step flows — not the controller. Flow reads: **input → parse → validate → mutate → announce** (events, metrics, notifications).
- [ ] **Controllers / HTTP layer:** load/validate auth, **delegate**, render or return status — question anything past a **~15-line** "real logic" ceiling without extraction.
- [ ] Shared worker behavior lives in a **base class**; subclasses narrow hooks (e.g. `do_perform`), not duplicated boilerplate.

**Model structure (Rails)**

- [ ] File order matches: **constants → associations → validations → callbacks → scopes → class methods → instance methods → private** (internals last).
- [ ] **Scopes** are a **domain vocabulary**: short lambdas where possible; **complex SQL** is justified and readable.
- [ ] **POROs / focused objects** hold behavior that is not a natural ActiveRecord row — avoid god models; extract when seams are clear.

**Platform & long-lived seams**

- [ ] If CI, queues, Docker, deploy templates, or schema/GraphQL artifacts move: **blast radius**, **rollback**, and **operational** impact are explicit (queue names, feature flags, job compatibility).
- [ ] Touching long-lived domain centers (account, search, GraphQL schema surfaces): watch for **N+1**, serializer/controller traversal cost, and **backward compatibility** for clients.

**Cross-cutting**

- [ ] **Concerns** use shared-behavior modules for **real** shared behavior, not unrelated dumping grounds.
- [ ] **Transactions** wrap multi-record updates; **`after_*_commit`** (not `after_save`) for side effects that must not run on rollback.

**Infrastructure** (if Dockerfile, CI, scripts appear)

- [ ] Changes are **iterative**; cache-friendly layers, non-root containers, no silent empty-env failures.

---

### Phase 2: Pairing & Collaboration

Treat collaboration as a **first-class review dimension**, not an afterthought.
Most cost in software is paid by the **next reader**, not the original author.

**Reviewability without "you had to be there"**

- [ ] **MR/PR description** (or top comment) states **intent**, **non-obvious decisions**, and **what reviewers should scrutinize** — especially for paired work where the diff alone may omit rationale.
- [ ] **"For Reviewer"**-style callouts for **tradeoffs**, **anti-decisions** ("we did not do X because…"), and **risky** areas.
- [ ] **Async handoff:** if pairing finished mid-flight, the remaining **TODOs**, **flags**, and **follow-up tests** are visible to the next reviewer or solo owner.

**Knowledge spread**

- [ ] Complex domains (auth, fulfillment, GraphQL, state machines) get **tests or comments** that help the **next** reader who was not in the session.
- [ ] **Co-authorship / Signed-off-by / Reviewed-by** follows team policy when pairs want attribution.

**Parallelism & cognitive load**

- [ ] Large MRs are **splittable** into reviewable chunks where feasible; **scope creep** is called out explicitly.
- [ ] **Cross-team / connector** work: ensure **boundary contracts** (API payloads, flags, idempotency) are documented for partners.

---

### Phase 3: Naming & Domain Alignment

**Domain language**

- [ ] Names read like the **business**, not generic CS jargon.
- [ ] **Predicates** end in `?` and read as English questions; **bang** (`!`) marks **mutations** or operations that may fail / must stand out.
- [ ] **Public instance methods** are **verb-first** and sentence-like where it helps.
- [ ] **Workers:** `{Domain}::{Action}{Noun}` or team suffix (`Worker`, `Processor`); **namespaces mirror paths** (`Fulfillment::OrderProcessor` ↔ `app/workers/fulfillment/...`).

**Queries & models**

- [ ] **Scopes** are **composable**; callers **compose** in class methods instead of duplicating SQL. Alphabetical ordering is a strong default when it matches the file.
- [ ] **Constants** (grouped, `freeze` where appropriate) replace **magic strings/numbers** for domain values, vendor slugs, regexes, cookie names.
- [ ] **Query entry points** as **class methods** where that matches codebase style; **find-or-fallback** is explicit, not hidden defaults.
- [ ] **`@ivars` in controllers**; avoid instance-variable state accumulating in models for orchestration.

**Frontend naming** (when Phase 6 applies)

- [ ] **Tiles** are noun-first (`CommentTile`); **Container / Page / Modal / Button** suffixes match role; **file name matches default export**.

---

### Phase 4: Error Handling & Defensive Coding

**Guards & control flow**

- [ ] **Guard clauses first** (`return unless`, `return if …blank?`); **happy path last** — no deep nesting for the main line.
- [ ] **Workers:** `do_perform` (or equivalent) opens with **precondition guards**; wrong type / missing resource → early return.
- [ ] **Nil safety:** `&.`, `allow_nil: true` on delegations, `presence` / `blank?` before work where needed.

**Failures & observability**

- [ ] **Structured logs** with **context** (ids, class name, key domain fields) on failure paths; messages identifiable for tracing.
- [ ] **Tiered severity:** errors for real failures; **warn** when something should have existed but did not; avoid noisy success logs.
- [ ] **Non-critical** side effects (timeline, metrics): **rescue, log**, do not take down the job — **without** blanket-swallowing **critical** persistence paths.
- [ ] **Impossible states** → **raise** with a message a human can act on (`ArgumentError` or clear string) — no silent fall-through.

**Graceful degradation**

- [ ] **Feature flags**, **fallback paths**, and **parallel old/new** behavior are **intentional** and **safe** — not accidental duplication.

**Batch & performance hygiene**

- [ ] Relations processed with **`find_each`** (or current equivalent), not unbounded `each`; **pluck** / selective reads where appropriate.

---

### Phase 5: Testing Completeness

**Coverage & placement**

- [ ] **1:1 rule:** each new/changed file under `app/` (or equivalent source root) has a **matching** spec path.
- [ ] **Success, failure, guard paths, and side effects** covered (jobs, mailers, events, metrics) where the code branches.

**Structure & style**

- [ ] **`subject` once**; **`let` / `let!`** for data; **avoid `@ivars` in specs**; **`describe` / `context` / `it`** mirror the public interface.
- [ ] **Context titles** use **when / with / for**; **example text** states **observable behavior** (what the system does), not internal steps.
- [ ] Prefer **one primary expectation per `it`** when practical; related checks share a **context**.

**Assertions**

- [ ] Mutations and side effects use **`expect { subject }.to change { ... }.from(...).to(...)`** (or `.by`, `.not_to change`) — not over-mocking internals.
- [ ] **`reload`** when asserting persistence; **`.not_to change`** locks invariants when accidental work must not happen.
- [ ] **Message expectations** (`receive`) only when testing a **specific collaboration** — setup, then invoke `subject`.
- [ ] **GraphQL / auth:** **shared examples** or project norms for access control when applicable.
- [ ] **Edge cases:** negative paths, idempotency, "already processed", wrong owner / unauthorized.

**Frontend tests** (when Phase 6 applies)

- [ ] Stable setup (`render(overrides)` or team equivalent); factories `createFakeThing(overrides)`; stable selectors (e.g. `data-testid` / `qa-*`); **focus** behavior covered when user-facing.

---

### Phase 6: Frontend Quality

**Component hierarchy**

- [ ] **Container** — data fetching, providers, routing; minimal presentational markup.
- [ ] **Page** — layout; breakpoint-driven structure if desktop/mobile paths diverge.
- [ ] **Content** — one clear responsibility per component.
- [ ] **Tile** — smallest reusable visual unit; **modals** sit as **siblings** of triggers, not nested inside buttons.
- [ ] **Props** — required vs optional clear; nested objects use **shape** or TypeScript types, not a loose `object`.
- [ ] **Context** — feature-scoped state (modals, editing, loading) uses Context; not leaked across unrelated trees.

**Accessibility**

- [ ] **Focus** — after close/submit/navigate, focus moves to a sensible element; programmatic targets use `tabIndex={-1}` when needed; match codebase patterns.
- [ ] **Icon-only controls** — `aria-label` (or equivalent accessible name).
- [ ] **Decorative icons** — `aria-hidden` with compensating **sr-only** text when meaning would otherwise be lost.
- [ ] **Lists/sections** labeled when needed; **timestamps/counts** have parallel screen-reader-friendly strings where product copy matters.
- [ ] **Keyboard** — layout switches do not strand keyboard users.

**GraphQL (client + server)**

- [ ] Types declare **`null:`** explicitly; resolvers enforce **authorization** before returning or mutating.
- [ ] **Mutations** — input types; **whitelist** / slice attributes; return **`{ entity, errors }`** (or team-equivalent) structured payloads.
- [ ] **Client** — queries in dedicated modules; **containers own fetching** and pass clean props; no deep data-fetch sprawl in presentational leaves.
- [ ] **Side effects in reads** — if present, intentional and documented.

**Styles**

- [ ] **Co-locate** feature styles; shared feature modules export for reuse; prefer **design tokens / grid utilities** over one-off magic numbers.

---

### Phase 7: Commit Discipline & Change Narrative

Calibrate to current team policy; the bar below is **aspirational**.

- [ ] **Ticket reference** on subjects when the team expects it.
- [ ] **Subject** — short (~50–65 characters), **imperative** when it helps scanability.
- [ ] **Body** when change is **non-obvious**, **multi-part**, or **operational**: **why**, **trade-offs**, **incident/root cause**, **compat** ("kept for jobs in flight"); **leading-dash bullets** for laundry lists.
- [ ] **Migration / rollout / feature-flag** notes when behavior spans deploys or depends on ordering.
- [ ] **`Reviewed-by:` / Signed-off-by** when pairing or review policy applies.
- [ ] **MR/PR description** carries **decision weight** for **large** or **paired** work.

---

## 4. Example Feedback Format

Structure comments so the author can **act without guessing**:

1. **Observation** — what you see (file + behavior), one clause.
2. **Standard** — which phase/checklist item it touches (optional but helps prioritization).
3. **Ask** — concrete change: extract, rename, add assertion, split commit, etc.
4. **Pattern** — point to an existing class/spec/commit in-repo when possible.

**Examples:**

```text
`app/workers/foo/process_message.rb` — `do_perform` parses XML, updates three models, and enqueues inline.
Phase 1 (layering): guard preconditions at the top, then delegate to private steps (parse → validate → persist → announce). Happy path should read top-to-bottom.
```

```text
Paired MR with no description — diff adds a new queue and moves workers.
Phase 2 + 7: document rollout order, flag behavior during partial deploy, and call out reviewer focus (queue config + in-flight jobs).
```

```text
`app/models/bar.rb` — scopes block is out of order and duplicates the same `joins` in two class methods.
Phase 1–3: alphabetize scopes if that matches file convention, extract the shared chain into a composable scope + class method so callers don't fork SQL.
```

```text
Specs stub `InternalService` and assert call counts only.
Phase 5: prefer `expect { subject }.to change { record.reload.status }.from('pending').to('done')` so the example documents observable behavior.
```

```text
Modal sets focus to `document.body` on close.
Phase 6 (a11y): restore focus to the opener (ref or focus manager) — match the pattern used elsewhere in this codebase.
```

```text
Subject `[#1234] wip` with no body for a 4-file behavior change.
Phase 7: imperative subject + a short why; bullets if you bundled unrelated fixes — future debugging and async reviewers depend on it.
```

---

## 5. Scoring Rubric

Rate the MR/PR **per phase** on a **0–3** scale, then sum for an overall band.
Use this for **self-review**, **pairing**, or **summary comments**.

| Score | Meaning |
|-------|---------|
| **0** | Multiple checklist failures or a **correctness/safety** risk in this area |
| **1** | Important gaps; would **request changes** if nothing else blocked |
| **2** | Minor nits or **n/a**-heavy phase; acceptable to ship with follow-ups noted |
| **3** | Clearly meets the bar; at most trivial suggestions |

### Phases and weights

| Phase | Max | Notes |
|-------|-----|--------|
| **1** — Architecture / organization / platform seams | **3** | God objects, fat controllers, missing transaction boundaries, unsafe infra rollout |
| **2** — Pairing & collaboration | **3** | Reviewability, handoff, MR affordances — penalize "tribal knowledge required" on non-trivial paired change |
| **3** — Naming & domain | **3** | Magic strings and vague names accumulate maintenance cost |
| **4** — Error handling & observability | **3** | If this phase is **0**, treat as **blocked** unless explicit risk acceptance |
| **5** — Testing | **3** | Missing specs for new source files → cap at **1** for this phase |
| **6** — Frontend | **3** | Use **n/a** and exclude from sum, or score **3** if no frontend files |
| **7** — Commits & change narrative | **3** | Risky/operational change with **no** context → cap at **1**; imperfect imperative mood alone should not cap |

**Overall bands**

Let **N** be the number of **scored** phases (typically **7**; **6** when Phase 6 is **n/a**). **Max = 3N**.

| Total | Band | Typical action |
|-------|------|----------------|
| **≥ 90% of max** | **Strong** | Approve; optional nits |
| **70–89% of max** | **Solid** | Approve with comments or small follow-ups |
| **40–69% of max** | **Needs work** | Request changes on highest-risk phases first |
| **< 40% of max** | **High risk** | Block; prioritize correctness, data safety, observability, tests, then collaboration narrative |

**Rules of thumb**

- If **Phase 4** or **Phase 5** is **0**, treat the MR as **blocked** until addressed unless explicit risk acceptance is documented.
- **Phase 2** scores **1** or **0** when paired or complex work ships **without** enough context for async review — collaboration debt is maintainability debt.
- **Phase 1** scores **0** on **silent** breaking infra/schema changes without rollback or flag strategy.

---

## Quick Reference Card

| Topic | Do |
|-------|-----|
| Structure | Thin controllers; worker/interactor owns orchestration; model section order; composable scopes; watch platform blast radius |
| Collaboration | MR **intent** + reviewer callouts; async-safe handoff; attribution per policy |
| Naming | Domain verbs/nouns; constants not literals; workers namespaced |
| Errors | Guards first; structured logs; rescue non-critical only; raise on impossible states; graceful paths intentional |
| Tests | 1:1 spec files; `subject` + `let`; `change` / `not_to change`; contexts = branches |
| Frontend | Container → Page → Content → Tile; focus + ARIA; containers fetch; stable selectors |
| Commits / MRs | Ticket traceability per current norm; **why** bodies on non-obvious work; revert-friendly slices |

---

## Caveats

- Historical examples may use older tools (Enzyme, Mocha, Apollo render props); judge **principles** with **current** stack equivalents.
- Some checklist items may conflict with local standards — defer to **lint, ADR, and team norms**.
- Do not paste confidential ticket text into public examples; keep samples generic.
