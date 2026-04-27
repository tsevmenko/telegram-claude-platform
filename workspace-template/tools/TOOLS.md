# TOOLS — Tool / service directory (on-demand)

_NOT loaded into session context. Read with the `Read` tool when you need a service URL, port, key path, or skill that isn't in active memory._

## Local services

| Service | URL / path | Auth | Purpose |
|---|---|---|---|
| OpenViking semantic memory | `http://127.0.0.1:1933` | `~/secrets/openviking.key` | L4 long-term recall, semantic + FTS5 hybrid |
| Webhook injection API | `http://127.0.0.1:8080/hooks/agent` | `~/secrets/webhook-token.txt` (Bearer) | External systems push messages to agents |
| Gateway logs | `journalctl -u agent-user-gateway` (or `agent-vesna`) | passwordless sudo | Diagnose silence / errors |

## Skills (loaded automatically; details on demand)

| Skill | When | Key path |
|---|---|---|
| voice-transcribe | Voice messages → text | `~/.claude-lab/shared/secrets/groq.key` |
| web-research     | Web search with citations | `~/.claude-lab/shared/secrets/perplexity.key` (optional, falls back to DuckDuckGo) |
| charts-and-tables | Datawrapper visualisations | `~/.claude-lab/shared/secrets/datawrapper.key` |
| diagram-generator | Excalidraw diagrams | _(no auth)_ |
| youtube-transcript | YT transcript fetch | _(yt-dlp default; optional `~/.claude-lab/shared/secrets/transcript-api.key`)_ |
| markdown-extract | URL → clean Markdown | _(no auth, uses r.jina.ai)_ |
| onboarding | First-run profile wizard | _(no auth)_ |
| self-compiler | Promote LEARNINGS to CLAUDE.md | _(no auth)_ |
| quick-reminders | One-shot at/cron reminders | webhook token |
| present | Markdown → reveal.js HTML deck | _(no auth, requires pandoc)_ |
| skill-finder | Discover new skills | _(no auth)_ |

## Plugins

| Plugin | Path | What it adds |
|---|---|---|
| Superpowers | `~/.claude/plugins/superpowers/` | 15 workflow skills: TDD, debugging, planning, code-review, brainstorming, parallel agents, task tracking with `.tasks.json` persistence |

## Anthropic API endpoints

- `claude` CLI (subprocess): `claude --resume <sid> --output-format stream-json`
- OAuth: `~/.claude/.credentials.json` (per-user, shared across this user's agents)

## OpenAI endpoints

| Endpoint | Used by |
|---|---|
| `POST https://api.openai.com/v1/embeddings` | openviking-lite for L4 semantic vectors (text-embedding-3-small, 1536-dim) |

## Cron jobs (per agent)

`/etc/cron.d/agent-memory-<agent>` — five rotation jobs in UTC:

```
04:30  rotate-warm.sh
05:00  trim-hot.sh        (Sonnet)
06:00  compress-warm.sh   (Sonnet)
06:30  sync-l4.sh
21:00  memory-rotate.sh
```

## Update policy

When you add a new tool or skill, append a row here. Keep TOOLS.md skimmable — one line per entry, no prose.
