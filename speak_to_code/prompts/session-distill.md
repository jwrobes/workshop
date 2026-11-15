You are maintaining a brief, voice-dictation-friendly summary of an active
coding session. The user will later dictate prompts that may reference
"that function" or "the service we discussed" — your summary must give a
cleanup LLM enough context to resolve those references.

Read the transcript below and produce markdown under 300 tokens covering:

1. **Current focus** — one sentence on what's being worked on right now.
2. **Names in play** — file paths, function names, services, proper nouns
   that have come up in the last few turns. Bullet list, no prose.
3. **Recent direction** — last 1-2 decisions or pivots, if any.

Output only the markdown. No commentary, no preamble.

Transcript:
[last N turns, user + assistant text only, tool calls stripped]
