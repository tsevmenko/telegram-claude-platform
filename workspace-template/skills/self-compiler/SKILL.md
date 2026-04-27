---
name: self-compiler
description: "Refactor CLAUDE.md based on accumulated LEARNINGS.md and PROPOSALS.md. Promotes repeated lessons into permanent rules. Use when: I'm tired of repeating myself, consolidate learnings, update your rules, /self-compiler."
user-invocable: true
---

# Self-Compiler

Read the structured episodes (`core/episodes.jsonl`), let the learnings-engine produce a list of promotion candidates, then propose updates to `CLAUDE.md` so the lessons stick permanently.

## When to use

- The operator says "I keep telling you the same thing".
- `learnings-engine score` shows several entries with `score >= 0.8` or `freq >= 3`.
- The operator runs `/self-compiler` directly.
- Weekly hygiene: review HOT learnings and either promote them or archive them.

## Workflow

1. **Run the engine** to see what's hot:
   ```bash
   python3 $CLAUDE_WORKSPACE/scripts/learnings-engine.py score --workspace $CLAUDE_WORKSPACE
   python3 $CLAUDE_WORKSPACE/scripts/learnings-engine.py lint  --workspace $CLAUDE_WORKSPACE
   ```
   `lint` returns JSON with three buckets: `promote`, `hot`, `stale`.

2. **Back up CLAUDE.md** before editing:
   ```bash
   bash $CLAUDE_SKILL_DIR/scripts/backup.sh
   ```

3. **For each PROMOTE candidate**, propose a concrete rule:
   ```bash
   python3 $CLAUDE_WORKSPACE/scripts/learnings-engine.py promote --workspace $CLAUDE_WORKSPACE
   ```
   This appends a structured proposal to `core/PROPOSALS.md` and marks the episode `status="promoted"` so it stops nagging.

4. **Read** `core/PROPOSALS.md` and `core/LEARNINGS.md`. Group related entries by topic (workflow, communication, security, tooling).

5. **Show the operator a diff** before writing — list the rule additions you intend to make to CLAUDE.md.

6. **On operator approval**, edit `CLAUDE.md`. Add the promoted rules under a clearly-marked section (e.g. `## Learned rules`) so they're easy to audit later.

7. **Archive stale entries** so old corrections don't dilute scoring:
   ```bash
   python3 $CLAUDE_WORKSPACE/scripts/learnings-engine.py archive-stale --workspace $CLAUDE_WORKSPACE
   ```

## What NOT to do

- Don't auto-promote without operator approval.
- Don't delete from `LEARNINGS.md` or `episodes.jsonl` — archive (status change) instead.
- Don't rewrite CLAUDE.md sections you don't understand. Ask first.
- Don't promote episodes whose `freq` is 1 unless the impact is `critical` and the operator confirms — single-occurrence is too noisy a signal.

## Composite scoring (FYI)

`score = recency*0.4 + frequency*0.3 + impact*0.3`

- `recency` linearly decays over 30 days
- `frequency` saturates at 3 occurrences
- `impact`: critical=1.0, high=0.7, medium=0.4, low=0.1

`PROMOTE` if score ≥ 0.8 OR freq ≥ 3. `STALE` if score < 0.15.

## Promotion pyramid

When a learning is ready to promote, decide *where* to put it. The higher
the layer, the wider the blast radius — and the harder to roll back.

```
                            ┌────────────────────────┐
       red zone — operator  │ CLAUDE.md (SOUL)       │  ← agent identity, principles
       confirmation needed  │  rules.md (boundaries) │  ← safety / output style
                            ├────────────────────────┤
                            │ TOOLS.md, AGENTS.md    │  ← directory of services / subagents
                            ├────────────────────────┤
       green zone — agent   │ SKILL.md bodies        │  ← reusable how-tos
       changes autonomously │ scripts/ helpers       │  ← bash / python utilities
                            ├────────────────────────┤
       enforcement layer    │ hooks/ (100% binding)  │  ← critical/security rules
                            └────────────────────────┘
```

| Severity | Lands at | Example |
|---|---|---|
| critical (security, data loss, prod break) | a hook script (PreToolUse / PostToolUse) — 100 % enforcement | "block `rm -rf /home`" → `block-dangerous.sh` |
| high (recurring workflow / methodology) | `CLAUDE.md` or `rules.md` (red zone — ask operator first) | "always run tests before commit" → 9-principles list |
| medium (tool / skill behaviour) | `tools/TOOLS.md` row or update an existing `SKILL.md` | "Datawrapper API token at this path" → TOOLS.md table |
| low (one-off note / style) | `core/LEARNINGS.md` archive only | a non-recurring nit |

**Rule of thumb:** if the lesson would surprise a *new* contributor a year
from now, it belongs in `CLAUDE.md` or `rules.md`. If it's just "remember
X exists in this codebase", `TOOLS.md` is enough. Don't pollute the SOUL
with operational trivia — the working-context budget is limited.
