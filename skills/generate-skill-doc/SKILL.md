---
name: generate-skill-doc
description: Extract learnings from a debugging or investigation session and produce a structured skill doc. Use when the user says "document this", "generate a skill doc", "capture learnings", or wants to turn investigation context into reusable codebase documentation for future developers and LLMs.
---

# Generate Skill Doc

Turn investigation and debugging context into a structured reference document that helps future developers, colleagues, and LLMs understand a system without re-investigating from scratch.

## Workflow

### Step 1: Identify the Source Context

Ask the user (or infer from conversation) which context to draw from:

1. **Current conversation** — code files read, queries run, findings discussed
2. **Workbench initiative folder** — check for a `workbench/<initiative>/` folder with README, docs/, scripts/, output/
3. **Prior Cursor sessions** — agent transcripts in the agent-transcripts folder if the user references previous work
4. **Codebase files** — the actual source code that was investigated

Read all available sources before drafting.

### Step 2: Ask Placement Questions

Before writing, confirm:

1. **Topic name** — what system/feature is this documenting? (e.g., "coach vacation coverage", "review and engage recommended topic")
2. **Feature area** — what category does it fall under? (e.g., `care_team_features`, `recommended_topics`, `member_lifecycle`)
3. **Output location** — suggest one of:
   - `docs/skills/<feature_area>/<topic>.md` in the project workspace — for permanent, polished docs
   - `workbench/<initiative>/output/skill_<topic>.md` — for drafts tied to an active investigation
   - Or wherever the user specifies

### Step 3: Gather and Organize

Read all relevant code files, paying attention to:

- **Models**: table names, key columns, scopes, relationships, important methods
- **Controllers/Workers**: entry points, async processing, scheduling
- **Flows**: step-by-step "what happens when X triggers Y"
- **Conventions**: date semantics, timezone handling, naming patterns, polymorphic associations
- **Gotchas**: things that are easy to get wrong, gaps in the system

### Step 4: Write the Skill Doc

Use the template structure below. Every skill doc must have the Required sections. Add Optional sections when relevant.

### Step 5: Quality Check

Before presenting the draft, verify:

- [ ] Specific file paths (not vague references like "the model file")
- [ ] Actual method and scope names from the code
- [ ] Copy-pasteable console/debug commands
- [ ] Non-obvious conventions explained (date semantics, naming, etc.)
- [ ] Someone could debug a related issue using only this doc
- [ ] Tables used for structured data (models, columns, files)
- [ ] Clear separation between "how it works" and "how to investigate it"

## Skill Doc Template

```markdown
# Skill: [Feature/System Name]

Use this skill when investigating or working with [brief description of when this doc is relevant].

## System Summary

[2-3 paragraphs. Cover the key entities, how they relate, and the core workflow. Write for someone who has never seen the code.]

## Key Models / Components

| File | Purpose |
|------|---------|
| `app/models/example.rb` | Description. Key methods: `method_a`, `method_b`. Key scopes: `scope_x`, `scope_y` |
| `app/workers/example_worker.rb` | What it does and when it runs |
| `app/controllers/example_controller.rb` | Key actions: `create`, `update` |

## [Flow Name] (e.g., "Creation Flow", "Processing Pipeline")

1. Step one — what triggers the process
2. Step two — what happens next
3. Step three — key decision point
4. Step four — outcome

## Investigation Patterns

### When [symptom A] happens:
1. Check [first thing]: `[console command]`
2. If [condition] → [likely cause and fix]
3. If not → check [next thing]: `[console command]`

### When [symptom B] happens:
1. [Investigation steps]

## Console / Debug Commands

\`\`\`ruby
# [What this does]
[copy-pasteable command]

# [What this does]
[copy-pasteable command]
\`\`\`

## [Convention Name] (optional — e.g., "Date Semantics", "Timezone Handling")

[Explain non-obvious conventions that would trip someone up.]

## Known Issues / Gaps

1. **[Issue]**: [Description and impact]
2. **[Issue]**: [Description]

## Related Docs

- `docs/skills/[area]/[other_doc].md` — [relationship]
- `workbench/[initiative]/README.md` — [investigation that produced this doc]
```

## Reference Example

A high-quality skill doc produced from a real bug investigation will typically cover: system summary, key models with column tables, creation flow, investigation decision trees, console commands, date/timezone convention gotchas, and known gaps. Aim for that bar — the doc should let the next investigator skip the dead-ends you already walked.

## Guidelines

1. **Don't invent information.** Only document what you can verify from the code or conversation. If uncertain, flag it as "needs verification."
2. **Prioritize investigation patterns.** The highest-value section is "when X happens, check Y" — this is what saves time during the next incident.
3. **Include console commands.** Every investigation pattern should have a corresponding copy-pasteable command.
4. **Explain the non-obvious.** Date semantics, off-by-one conventions, timezone pinning, polymorphic associations — these are the things that waste hours when undocumented.
5. **Keep it under 500 lines.** If a system is complex, split into multiple skill docs by sub-system and cross-reference them.
