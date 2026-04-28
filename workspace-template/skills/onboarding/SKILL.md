---
name: onboarding
description: "First-run wizard. Builds the operator's profile in core/USER.md from a voice memo (preferred) or a guided text dialogue. Use when: first run, /onboarding, set up profile, get to know me, who am I."
user-invocable: true
---

# Onboarding

Interactive wizard that builds the operator's profile in `core/USER.md`.

## When to use

- The user types `/onboarding` or asks you to set them up.
- It's the first conversation in a fresh workspace and `core/USER.md` only has placeholders.
- The user asks "remember this about me" repeatedly — propose running onboarding to consolidate.

## Voice-first preferred path

Open with this exact offer (translate to operator's language if not English):

> Hi! Two ways to get me up to speed about you:
>
> **Option A (recommended, 1 min):** Send me a **voice memo** answering: who you are, what you do, your mission, and what you want from me. Drop **links** to your Telegram channel / Instagram / website / GitHub if you have them — I'll read them.
>
> **Option B:** Just type answers to a few questions.
>
> Which works for you?

If the operator picks **A** (voice + links):

1. Once their voice arrives, you'll see the auto-transcribed text in the chat — work from that.
2. For each link they sent, use the `markdown-extract` skill (or the `WebFetch` tool if not available) to pull a short summary. Don't dump the full page.
3. Synthesise the profile from voice transcript + link summaries into `core/USER.md` (see "What to write" below).
4. Confirm in 2 sentences and ask "anything I got wrong?"

If the operator picks **B**, run the text dialogue below.

## Text dialogue (option B, conversationally — not as a form)

Ask one question at a time, infer answers when obvious from context, skip what was already provided.

1. **Name and how to address them.** "What should I call you?"
2. **Role / what they do.** "What do you do for work, or what are you focused on right now?"
3. **Mission / what they're building.** "What's the longer-term thing you're working toward?"
4. **What they want from this agent.** "What kinds of tasks would you like my help with most?"
5. **Channels they run.** "Do you have a Telegram channel, Instagram, website, GitHub, or YouTube I should know about? Drop links."
6. **Communication style.** "Terse or detailed? Code first or prose first? Any pet peeves?"
7. **Languages.** "Which language should I default to in our chats?"
8. **Working hours / timezone.** "What timezone? Hours I shouldn't ping you for non-urgent things?"
9. **Tools and integrations.** "Linear, Notion, particular repos, paid APIs — anything I should be aware of?"

## What to write

Update `core/USER.md` using exactly this section structure (the template ships these placeholders, fill them in):

- **Name**
- **Address as** — what to call them in replies (first name, role, etc.)
- **Timezone**
- **Language**
- **Profile** — 1-2 sentences: who they are + role + current focus
- **Mission** — 1 sentence: long-term goal
- **What the operator needs from this agent** — 3-4 bullets
- **Channels** — table: channel | URL | status (active/dormant/private)
- **Communication style** — 2-3 bullets

Keep each section terse. The whole file should fit in ~40 lines.

## Confirmation

After writing, send back:

> Saved. I'll call you **{name}**, default to **{language}** in chat, and prioritise **{top-2 needs}**. Edit `core/USER.md` any time. Anything I got wrong?

If they correct anything, edit `core/USER.md` immediately and re-confirm in one sentence.

## Anti-patterns

- ❌ Ask all 9 questions in one wall-of-text.
- ❌ Write more than 1-2 sentences per USER.md section.
- ❌ Force option B if they sent voice — the voice path is the recommended path.
- ❌ Save half-empty placeholders. If a field is unknown, use `_(operator did not specify)_`.
- ❌ Onboard on every fresh session — only when USER.md is empty or operator asks.
