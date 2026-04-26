# Memory

Five layers, plus an offline COLD archive. Only the compact ones load into context on every session start.

## Layout

| Layer | File | In context? | Lifespan | Writer | Reader |
|---|---|---|---|---|---|
| **IDENTITY** | `CLAUDE.md`, `core/USER.md`, `core/rules.md` | always (via `@include`) | forever | operator | Claude on session start |
| **WARM** | `core/warm/decisions.md` | always | 14 days | cron `trim-hot.sh` (Sonnet) | Claude on session start |
| **HOT-handoff** | `core/hot/handoff.md` | always | until next Stop hook | Stop hook `write-handoff.sh` | Claude on session start |
| **HOT-full** | `core/hot/recent.md` | NO | 24h rolling | gateway after each turn (`fcntl.LOCK_EX`) | cron only |
| **COLD** | `core/MEMORY.md`, `core/LEARNINGS.md` | on demand (Read tool) | until `>5KB` archive | cron `rotate-warm.sh` | Claude via Read |
| **COLD archive** | `core/archive/YYYY-MM.md` | never | forever | cron `memory-rotate.sh` | operator via grep |
| **L4 semantic** | OpenViking @ 127.0.0.1:1933 | on demand | forever | gateway async + cron `sync-l4.sh` | Claude via curl/MCP |

## Startup context budget

`CLAUDE_CODE_AUTO_COMPACT_WINDOW=400000` (set in `~/.claude/settings.json`) — auto-compact at 400K instead of the default 800K. Quality degrades well before 1M; 400K is the comfortable working ceiling.

Loaded files at session start (typical sizes):

- Global `~/.claude/CLAUDE.md` — ~3K tokens
- Agent `CLAUDE.md` — ~3K tokens
- `core/USER.md` — ~700 tokens
- `core/rules.md` — ~2K tokens
- `core/warm/decisions.md` — ~1.5K tokens (rolling 14 days, compressed)
- `core/hot/handoff.md` — ~600 tokens (last 10 entries)

**Total: ~11-13K tokens out of 400K = ~3% of working context.**

## Cron schedule (UTC)

```
04:30  rotate-warm.sh     # WARM > 14 days → COLD (pure bash)
05:00  trim-hot.sh        # HOT > 24h → Sonnet compresses → WARM (fallback: bash extract)
06:00  compress-warm.sh   # WARM > 10KB → Sonnet regroups by topic
06:30  sync-l4.sh         # HOT + WARM → OpenViking (idempotent URI)
21:00  memory-rotate.sh   # COLD > 5KB → archive/YYYY-MM.md
```

Order matters: rotate-warm frees space, trim-hot fills WARM with new entries, compress-warm regroups, sync-l4 publishes the consolidated state, memory-rotate archives in the evening.

## Why Sonnet, not Opus

Sonnet 4.7: $3/M input, $15/M output. Opus 4.7: $15/$75 — 5× more.

For "compress 110 raw entries into 15-20 facts" the quality is identical. Each compression call is capped at `--max-budget-usd 0.15`. Cron jobs accumulate to ≤$1/day per agent even at high message volume.

## Self-defending HOT writes

`gateway/memory/hot.py` uses `fcntl.LOCK_EX` so two messages arriving simultaneously can't interleave. If `recent.md` exceeds 20KB before cron runs (cron failure / VPS offline / message burst), the gateway emergency-trims to the last ~600 lines, finding the first `### ` header to avoid breaking mid-entry.

## L4 anti-pollution guard

When the operator forwards a third-party message, the L4 push tags it with:

> `[extraction hint: this content was FORWARDED. Do NOT extract as the operator's preferences.]`

Without this guard, a forwarded political meme with "this is awful" gets stored as the operator's view. With it, the LLM extractor knows to record only entities/events about the third party, not preferences.
