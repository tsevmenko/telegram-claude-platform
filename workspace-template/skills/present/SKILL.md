---
name: present
description: "Build an HTML slide deck (reveal.js) from Markdown. Use when: make slides, presentation, deck, demo."
user-invocable: true
argument-hint: "<title> <markdown-file-or-content>"
---

# Present

Convert Markdown content into a self-contained reveal.js HTML slide deck. The deck loads from a CDN — no install needed on the viewer's side.

## When to use

- The user asks for slides, a deck, or a demo presentation.
- You have outline content and need to share it visually.

## Markdown conventions

- `# Title` → title slide
- `## Slide title` → new slide
- `---` → explicit slide break
- Bullet lists, code blocks, images — all standard Markdown.

## Usage

```bash
bash $CLAUDE_SKILL_DIR/scripts/build.sh "My Presentation" deck.md
# → outputs path to the generated HTML file (in /tmp).
```

The output is a single `.html` file you can attach to Telegram as a document or open directly in a browser.

## Notes

- Uses `pandoc` (installed by the system installer) to handle the Markdown → HTML conversion.
- Theme defaults to `black`. To override: set `REVEAL_THEME=white` in the environment before running.
