---
name: onboarding
description: "First-run wizard. Asks the operator about themselves and writes core/USER.md so the agent knows who you are. Use when: first run, /onboarding, set up profile, get to know me."
user-invocable: true
---

# Onboarding

Interactive wizard that builds the operator's profile in `core/USER.md`.

## When to use

- The user types `/onboarding` or asks you to set them up.
- It's the first conversation in a fresh workspace and `core/USER.md` is empty.
- The user asks "remember this about me" repeatedly — propose running onboarding to consolidate.

## What to ask (in order, conversationally — not as a form)

1. **Name and how to address them.** "What should I call you?"
2. **Role / what they do.** "What do you do for work, or what are you focused on right now?"
3. **What they want from this agent.** "What kinds of tasks would you like my help with most?"
4. **Communication style.** "Do you prefer terse replies or detailed explanations? Code first or prose first? Any pet peeves?"
5. **Languages.** "Which language should I respond in by default?"
6. **Working hours / timezone.** "What timezone are you in? Are there hours when I shouldn't ping you about non-urgent things?"
7. **Tools and integrations.** "Are there services I should know about — Linear, GitHub repos, Notion, etc.?"

## What to write

After the dialogue, update `core/USER.md` with the answers. Use the existing template structure (Name, Address as, Timezone, Language, Profile, Communication Style, What the operator needs, Channels). Keep it concise — one or two sentences per field.

Confirm what you wrote at the end:

> Saved. I'll address you as **{name}**, default to **{language}**, and treat your priorities as **{summary}**. You can edit `core/USER.md` any time.
