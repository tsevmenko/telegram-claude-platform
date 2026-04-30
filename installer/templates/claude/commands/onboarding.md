---
description: Run the first-run onboarding wizard. Builds operator profile in core/USER.md from a voice memo (preferred) or guided text dialogue.
---

Invoke the `onboarding` skill (under your `skills/onboarding/SKILL.md`) and follow its voice-first flow:

1. Open with the bilingual offer (voice memo vs. text dialogue) from the skill's "Voice-first preferred path" section.
2. If operator sends voice — work from the auto-transcribed text, fetch any links via the `markdown-extract` skill or `WebFetch`.
3. Synthesise into `core/USER.md` using exact section structure from the skill.
4. Confirm in 2 sentences and ask "anything I got wrong?"
5. **Delete the `core/.needs-onboarding` marker** after USER.md is written and confirmed — the session-bootstrap hook checks this marker on every session start.

Do not skip steps. Do not write more than 1-2 sentences per USER.md section. Do not fabricate details — if a field is unknown, write `_(operator did not specify)_`.
