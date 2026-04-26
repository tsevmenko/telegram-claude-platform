---
name: markdown-extract
description: "Clean Markdown extraction from any URL. Reduces tokens by ~80% vs raw HTML. Use when: read a webpage, fetch an article, extract content from a URL."
user-invocable: false
---

# Markdown Extract

Converts any webpage to clean Markdown using the international, no-auth Jina AI Reader. Drops boilerplate (nav, footer, sidebars), keeps the main article text.

## When to use

- The user gives you a URL to read.
- You need the textual content of a page without all the HTML noise.
- A long article is going to eat your context — strip it to Markdown first.

## Usage

```bash
bash $CLAUDE_SKILL_DIR/scripts/extract.sh https://example.com/article
```

Outputs Markdown to stdout. No API key needed.

## How it works

Prepend `https://r.jina.ai/` to the target URL. The service returns clean Markdown.

```bash
curl -sL "https://r.jina.ai/https://example.com/article"
```

## Fallback

If `r.jina.ai` is unreachable, the script falls back to a local readability-style extraction (requires `pandoc` + `curl`).
