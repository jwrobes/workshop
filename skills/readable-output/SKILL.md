---
name: readable-output
description: Rewrite a complex answer, conversation, change, or agent run into clear, easy-to-review output - simplified technical English (STE), then a diagram, interactive HTML page, or explainer video only when it helps. Use when the user says "make this readable", "STE", "Karpathy style", "readable output", "explain this so I can review it", or asks to summarize or review something with many steps or parts. Skip for short, simple answers.
---

# Readable Output

Goal: make LLM output easy for a human to understand and check. The human's
job is oversight, so optimize for fast comprehension, not impressive prose.

## When to use
- The user asks to make an answer, conversation, document, code change, or long
  agent run readable or reviewable.
- The user says "STE", "Karpathy style", or "readable output".
- Your own answer would be complex (many steps, parts, or relationships) and
  the user is reviewing it.

Skip for short, simple answers. The benefit grows with complexity.

## Step 1 - Find the source
1. If the user pasted or attached text, or gave a file path, use that.
2. Otherwise use the current session.
3. If the source is another session you cannot see, ask the user for it.
4. Identify: the question, the decisions, the final answer, the open issues.

## Step 2 - Always: write in ~80% ASD-STE100 (Simplified Technical English)
Go about 80% of the way. Keep correct domain terms. Do not make it robotic.
1. One topic per sentence. Max ~20 words in instructions, ~25 in descriptions.
2. Max ~6 sentences per paragraph.
3. Use active voice. Say who does what.
4. Use the imperative for procedures: "Run the script."
5. One word = one meaning. Once you name a thing, keep that exact name.
6. Use simple, common words. Define each technical term once, at first use.
7. Use numbered steps for sequences. One action per step.
8. Put warnings and conditions BEFORE the step they apply to.
9. No filler, no stacked hedges, no rhetorical questions.
10. Put the main point first.

## Step 3 - Pick the artifact (lowest rung that makes it clear)

| Content shape | Output |
|---|---|
| Linear facts, short answer | STE text only |
| Process, flow, architecture, relationships, timeline | Diagram (Mermaid or SVG) |
| Comparison of options | Table; diagram if structure matters |
| Many parts to explore, data to filter, numbers the reader can vary | Interactive single-file HTML page (tabs, accordions, filters, sliders - see "HTML pages") |
| Concept that unfolds over time (algorithm, mechanism, proof) | Explainer video (Step 4) |

Rules:
- Each artifact answers one question. Put that question in its title.
- Diagrams: max ~12 nodes. Label every arrow with a verb.
- A terminal cannot render Mermaid. Write diagrams into a self-contained HTML
  file (Mermaid via CDN is fine; use inline SVG if it must work offline) and
  open it with `open <path>`. Show the Mermaid source in chat only as a fallback.
- Save artifacts under `./readable-output/<slug>.html` unless the user names a
  location. Tell the user the path.
- Artifacts are disposable. Prefer a fast, single-use page over a polished one.
- A nice visual must not hide uncertainty. Label each assumption or unverified
  claim once, in the place it applies (for example "Unverified:").

### HTML pages (Tier 3 - the main rung)
Basics:
- One file. CSS in `<style>`, JS in `<script>`. No build step. No external
  scripts, except Mermaid or Lucide icons via CDN when needed.
- Readable on a phone. Light and dark palette (use `prefers-color-scheme`).
  Sans-serif text, monospace code, plenty of whitespace, status colors.
- Start with a short STE summary at the top. The page must read correctly
  with zero interaction.
- Start the response with the file path and a 1-3 sentence TL;DR. Do not paste
  the whole HTML into chat unless the user asks.

Pick the control by the reader's job:

| Reader's job | Control |
|---|---|
| Move between categories (Summary, Code, Logs, Next steps) | Tabs |
| Audit long logs, diffs, or nested code on demand | `<details>`/`<summary>`, collapsed by default (not for an MR's own diff; see "MR review walkthroughs") |
| Scan a big table or list | Search box + filter chips; sortable columns |
| Jump around a long document | Fixed sidebar with section links |
| Explore a tradeoff, threshold, cost, or "what if" | **Slider (or number input/toggle) that recomputes the output live** |
| Compare two versions or options | Side-by-side columns or a before/after toggle |

Sliders and live parameters:
- Add one only when the content has a real numeric input (threshold, count,
  rate, cost, time, size). Never add controls only to look interactive.
- Wire `input` events to one `render()` function that recomputes and redraws
  the result. Plain JS, no libraries.
- Show the current value and unit next to the control. Show the result right
  beside it, never off-screen.
- Set min, max, step, and a default that matches the real or recommended value.
  Add a "Reset" button.
- Show the key output as a number plus a small chart or bar. Highlight the
  point where the decision changes (for example, where a threshold flips a
  verdict).
- Label every assumption behind the model, once, next to the control
  (for example "Unverified: 10k messages/day").
- Max ~3 sliders per page. If you need more, split into separate pages or tabs.
- Keyboard and touch must work. Use native `<input type="range">` with a
  visible `<label>`.

Minimal slider pattern:
```html
<label>Threshold: <output id="v">0.5</output>
  <input id="t" type="range" min="0" max="1" step="0.05" value="0.5">
</label>
<div id="result"></div>
<script>
const t = document.getElementById('t');
function render() {
  document.getElementById('v').textContent = t.value;
  document.getElementById('result').textContent = compute(+t.value);
}
t.addEventListener('input', render);
render();
</script>
```

### MR review walkthroughs
A page that helps someone review a merge request has its own skill:
`mr-review-walkthrough` (rules, skeleton, lessons). Use it instead of this one.

## Step 4 - Explainer video (optional, top rung)
Only when the user asks, or a mechanism truly needs motion.
1. Check what is installed (for example Manim, ffmpeg). If tooling is missing,
   say so and ask before installing anything.
2. Write the script in STE: 5-10 scenes, one idea per scene. Get approval first.
3. Animate in code (Manim, or HTML/canvas).
4. Narration: use a TTS service only if the user supplies credentials. Else
   offer local/free TTS or captions. Never invent keys.

## Step 5 - Output format
Return, in this order:
1. **TL;DR** - 1-3 STE sentences.
2. **Main explanation** - STE text, numbered steps where relevant.
3. **Artifact(s)** - only those that add understanding (Step 3). Give paths.
4. **Open issues / what to verify** - short list.

## Converting a whole conversation
1. Remove dead ends, repeats, and back-and-forth.
2. Keep: the goal, the final decisions (and who made them), the final answer,
   and the unresolved questions.
3. Separate the user's decisions from the assistant's suggestions.
4. Rewrite in STE (Step 2). Add artifacts (Step 3) where they help.

## Quality check before finishing
- Can a reader get the main point from the TL;DR alone?
- Does every term keep one meaning?
- Does each artifact clarify something the text alone does not?
- If the content has a numeric tradeoff, does the page let the reader vary it?
- Does the HTML page read correctly with no interaction, and on a phone?
- Is each uncertain claim labeled once?
