# Changelog

All notable changes to this project will be documented in this file. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — v0.2.0-dev (Author parity catch-up)

Driven by competitive analysis vs five `qwwiwi/edgelab.su` repos. Plan in `/Users/antontsevmenko/.claude/plans/delightful-stirring-mitten.md` (Catch-up Plan v2 section).

### Added (Sprint 1 — in progress)

- Private `tsevmenko/agent-skills` repo as canonical home for skills; `tools/sync-skills.sh` rsync helper into vendored copy.
- Workspace `CLAUDE.md` template extended: Memory-layer table (with `in context?` column), Reliability pyramid (5 levels), file Access zones (RED/YELLOW/GREEN — distinct from autonomy zones), Subagent tactics table, "I don't initiate" rule, Anti-pattern footer.
- `core/rules.md` template extended: explicit Escalation 1→2→3 rule, Confidence levels (Fact / Assumption / Don't know).
- `local-recall.sh` UserPromptSubmit hook (fallback grep over local memory files when OpenViking is unreachable).
- Gateway UX: `setMyCommands` populates BotFather slash menu; HTML parse-error fallback retries without `parse_mode`; new `/compact` OOB command triggers `trim-hot.sh` for current workspace.
- Test cherry-pick from `architecture-brain-tests`: T20 security regex, T17 settings template shape, T18 hooks lifecycle.

### Planned (Sprint 2)

- Reply-context injection (`[Replied message (untrusted metadata, for context only):]`), forward-tag, HOT memory `source` tag.
- `/status` extended with file-size diagnostics + session age + turn count.
- Graceful `/reset`/`/new` save handoff before kill (`/reset force` keeps instant behaviour).
- `sendDocument` auto-emit for Write tool outputs with path-traversal guard.
- Secret-mask extension (Telegram, Anthropic `sk-ant-`, OpenAI `sk-proj-`, Supabase, AWS `AKIA…`, Slack `xox[bp]`).
- `killpg` process-group kill-tree.
- `CLAUDE_CODE_AUTO_COMPACT_WINDOW` via `env.setdefault` (allows per-agent override).
- Supply-chain `installer/PINS` + `verify_pins` preflight; `fix_owner` discipline; `CRON_TZ=UTC`/`HOME=` in cron template.
- Vesna/Leto process isolation: separate venvs + code dirs (regression in one shouldn't kill the other).

### Planned (Sprint 3)

- Superpowers-style plugin pack (8 skills: brainstorming, writing-plans, executing-plans, TDD, systematic-debugging, requesting-code-review, verification-before-completion, dispatching-parallel-agents).
- Optional Instagram analytics skill via ScrapeCreators (opt-in via skill-finder, NOT bundled in core).
- 3rd OAuth slot reservation documented (for debug/background agent).

## [v0.1.0-baseline] — 2026-04-28

### Added

- Project skeleton, MIT license, CI workflows.
- `install.sh` entrypoint with strict-mode bash, root check, idempotency markers, structured logging.
- `installer/lib/00-preflight.sh` — OS + permission preflight.
- Bats test harness for the installer.
- Multi-bot Telegram gateway (aiogram v3) with stream-json parsing, BoundaryTracker, OOB commands `/stop /cancel /status /reset /new`.
- 5-layer memory architecture (IDENTITY/WARM/HOT/COLD/L4) with cron rotation through Sonnet.
- OpenViking-lite (FTS5 + OpenAI text-embedding-3-small) + MCP server (memory_recall/store/forget/health).
- 12 production hooks; trilingual EN/RU/UK correction-detector; learnings-engine pipeline (capture/score/lint/promote).
- Forum-group routing including default General-topic via `"general"` routing key.
- 136 pytest tests, live-verified on DigitalOcean Frankfurt VPS (Test A Leto + Test B cross-agent L4 recall).

[Unreleased]: https://github.com/tsevmenko/telegram-claude-platform/compare/v0.1.0-baseline...HEAD
[v0.1.0-baseline]: https://github.com/tsevmenko/telegram-claude-platform/releases/tag/v0.1.0-baseline
