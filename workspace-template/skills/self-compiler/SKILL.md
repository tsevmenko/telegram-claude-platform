---
name: self-compiler
description: "Refactor CLAUDE.md based on accumulated LEARNINGS.md. Promotes repeated lessons into permanent rules. Use when: I'm tired of repeating myself, consolidate learnings, update your rules."
user-invocable: true
---

# Self-Compiler

Read `core/LEARNINGS.md`, identify rules that fire frequently, and propose updates to the agent's `CLAUDE.md` so they become permanent rather than reactive.

## When to use

- The operator says "I keep telling you the same thing."
- `LEARNINGS.md` has more than ~20 entries and patterns are visible.
- The operator runs `/self-compiler` directly.

## Workflow

1. **Backup current CLAUDE.md** before editing:
   ```bash
   bash $CLAUDE_SKILL_DIR/scripts/backup.sh
   ```
2. **Read** `core/LEARNINGS.md` and group entries by topic (workflow, communication, security, tooling).
3. **Identify candidates for promotion** — rules that appear ≥3 times, or single-occurrence rules with high impact.
4. **Propose changes** to the operator before writing. Show a diff:
   - Which rules will be added to CLAUDE.md
   - Which LEARNINGS entries will be archived (no longer needed)
5. **On approval**, edit `CLAUDE.md` and move the promoted entries to a "## Archived" section in `LEARNINGS.md`.

## What NOT to do

- Don't auto-promote without asking.
- Don't delete from LEARNINGS — archive instead.
- Don't rewrite CLAUDE.md sections you don't understand. Ask first.
