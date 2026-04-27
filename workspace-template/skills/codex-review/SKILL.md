---
name: codex-review
description: "Independent code review by a non-Claude model (OpenAI GPT-5/Codex). Use when: about to merge, double-check a diff, get a second opinion, adversarial review, before deploying to production."
user-invocable: true
argument-hint: "[--mode standard|adversarial] [--diff-from <ref>]"
---

# Codex Review

Run an independent code review against your current diff using OpenAI's
GPT-5 / Codex. The point of "double review" is to catch issues the primary
model (Claude) might miss because it shares the same blindspots as the
agent that wrote the code.

## When to use

- Before pushing a non-trivial diff to main.
- When the operator says "second opinion" / "double check".
- After a long session of edits — review what got committed.
- For security-sensitive code: run the `adversarial` mode.

## Setup

```bash
mkdir -p ~/.claude-lab/shared/secrets
echo 'sk-...' > ~/.claude-lab/shared/secrets/openai.key
chmod 600 ~/.claude-lab/shared/secrets/openai.key
```

The same OpenAI key as for openviking-lite embeddings can be reused.

## Modes

| Mode | Prompt style | Output |
|---|---|---|
| `standard` (default) | "Review this diff. Spot bugs, missing tests, footguns." | Markdown bullet list grouped by severity |
| `adversarial` | "Assume the author is adversarial. Find ways this code can be exploited, abused, or fail at scale." | Threat-model report with attack vectors |

## Usage

```bash
# Review uncommitted + staged changes against HEAD
bash $CLAUDE_SKILL_DIR/scripts/run.sh --mode standard

# Adversarial review of a feature branch vs main
bash $CLAUDE_SKILL_DIR/scripts/run.sh --mode adversarial --diff-from main

# Review a specific file
bash $CLAUDE_SKILL_DIR/scripts/run.sh --mode standard --file src/auth.py
```

## Output

Markdown report on stdout. Save it as `core/reviews/<timestamp>.md` if you
want to keep an audit trail.

## When NOT to use

- Tiny diffs (< 5 lines). Just look at them yourself.
- Diffs to docs / config-only changes. The model will hallucinate "issues".
- During an active emergency — adds latency, doesn't help triage.

## Cost

Per review (using `gpt-5-mini`-tier model on a typical 200-line diff):
~$0.05–0.20. Adversarial mode is 2-3× the cost because the prompt is longer
and the response is more thorough. Cap your daily budget on the OpenAI
dashboard if running automated reviews.
