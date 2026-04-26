---
name: web-research
description: "Web research with citations via Perplexity Sonar API (paid) or DuckDuckGo (free fallback). Use when: search the web, fact-check, find sources, current information."
user-invocable: true
argument-hint: "<query>"
---

# Web Research

Search the web, fact-check claims, gather sources. Two backends — Perplexity (paid, structured citations) and DuckDuckGo (free, lower quality).

## When to use

- The user asks to research a topic, fact-check, or find recent information.
- You need a few authoritative sources before answering a question.
- You need to verify a claim against current data.

## Setup (Perplexity)

```bash
mkdir -p ~/.claude-lab/shared/secrets
echo 'YOUR_PPLX_KEY' > ~/.claude-lab/shared/secrets/perplexity.key
chmod 600 ~/.claude-lab/shared/secrets/perplexity.key
```

If the key file is missing, the skill falls back to DuckDuckGo (no setup needed).

## Usage

```bash
bash $CLAUDE_SKILL_DIR/scripts/research.sh "what is the date of the next solar eclipse"
```

Returns a Markdown summary with cited sources. Exits non-zero if both backends fail.

## Notes

- Perplexity model: `sonar` (default, fastest).
- DuckDuckGo fallback returns Instant Answer JSON only — useful for definitions and basic facts; bad for trends.
