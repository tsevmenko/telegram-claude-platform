# Architecture

## Process isolation between Vesna and Leto

The two services are intentionally fully isolated. Each has:

- its own systemd unit (`agent-vesna.service` vs `agent-user-gateway.service`),
- its own Linux user (`root` vs `agent`),
- its own Python venv (`/root/vesna/.venv` vs `/home/agent/gateway/.venv`),
- its own copy of the `gateway/` source tree (rsync'd via installer step 50/60, no symlinks between them),
- its own OAuth credentials (`/root/.claude/.credentials.json` vs `/home/agent/.claude/.credentials.json`).

**Why not a shared install?** A regression in `gateway/` should not be able to take down both agents at once. With separate venvs and code copies, you can `systemctl stop agent-user-gateway` and the Tech topic still answers; conversely a Vesna crash never affects user-facing chats. This is the same idea the original [edgelab.su](https://edgelab.su) project used by running two completely separate gateways (Jarvis + Richard) — we get the isolation property without the cost of a second codebase.

**Trade-off:** ~2× pip install time at first install (each venv installs the same wheels independently) and ~200MB extra disk. Both are negligible against the recovery story.

**Sync-up after gateway changes.** `installer/lib/50-vesna.sh` and `60-user-gateway.sh` both rsync from `gateway/` and pip-install in their own venvs. Rerunning the installer is the canonical way to roll a code update — the pip install -e in each venv picks up the new source.

## Two systemd services, one VPS

```
                                  ┌──────────────────────┐
                                  │ Operator (Telegram)  │
                                  │ forum group:         │
                                  │  - Main topic        │── Leto (and future client agents)
                                  │  - Technical topic   │── Vesna
                                  └──────────────────────┘
                                                │
                          ──────────────────────┼──────────────────────
                          │                                            │
                          ▼                                            ▼
                ┌─────────────────────┐                  ┌──────────────────────────┐
                │ agent-vesna.service │                  │ agent-user-gateway.svc   │
                │ User=root           │                  │ User=agent               │
                │ Single agent        │                  │ N agents (Leto + …)      │
                │ Full sudo           │                  │ Narrow sudoers           │
                └──────────┬──────────┘                  └────────────┬─────────────┘
                           │                                          │
                           ▼                                          ▼
              /root/.claude/ (OAuth)                     /home/agent/.claude/ (OAuth)
                           │                                          │
                           ▼                                          ▼
              /root/.claude-lab/vesna/                 /home/agent/.claude-lab/<agent>/
                  workspace tree                            workspace tree per agent
                                                                      │
                                                                      ▼
                                                            ┌──────────────────────┐
                                                            │ openviking.service   │
                                                            │ 127.0.0.1:1933 only  │
                                                            └──────────────────────┘
```

## Process model

- **`agent-vesna.service`** runs as `root`. One Telegram bot. Workspace at `/root/.claude-lab/vesna/.claude/`. Used for VPS administration and managing client agents.
- **`agent-user-gateway.service`** runs as `agent`. Multiple Telegram bots (one per client agent). Each has its own workspace at `/home/agent/.claude-lab/<name>/.claude/`. Used for day-to-day work.
- **`openviking.service`** runs as `openviking`. Bound to loopback only. Provides L4 semantic memory.

All three are started by the installer; the operator does **not** edit unit files by hand under normal operation.

## Per-agent gateway flow (single turn)

```
  Telegram message
        │
        ▼
  aiogram Dispatcher (multi-bot polling)
        │
        ▼
  per-agent Router
   ├─ OOB (/stop /cancel /status /reset /new) — handled inline, fast path
   ├─ /voice — VoiceTranscriber (Groq Whisper) → text → queue
   └─ text  — straight to queue
        │
        ▼
  asyncio.Queue (per agent, per chat)
        │
        ▼
  AgentConsumer
   ├─ /reset COLD bridge (latest MEMORY.md section)
   ├─ Telegram reaction "👀"
   ├─ placeholder status message
   ├─ ClaudeRunner.stream_turn()
   │      │
   │      ▼
   │   subprocess.exec claude -p --output-format stream-json --resume <sid>
   │      │
   │      ▼
   │   stream_parser → StreamEvent (init / thinking / text / tool_use / tool_result / todo / subagent_start / final)
   │      │
   │      ▼
   │   BoundaryTracker.feed(event)
   │      │
   │      ▼
   │   editMessageText (rate-limited 1 / 1.5s) ← live status
   │
   ├─ on `final`: replace status with answer (markdown→HTML, chunked at 4000 chars)
   ├─ append turn to HOT (fcntl.LOCK_EX)
   └─ fire-and-forget L4 push (bounded ThreadPoolExecutor max=2)
```

## Memory layers

See [MEMORY.md](MEMORY.md). Five layers + cron rotation; only the compact ones are loaded into Claude's context on startup, keeping the working window under ~3% of 400K.

## Hooks

See [HOOKS.md](HOOKS.md). Hooks are shell scripts wired into Claude Code's lifecycle events via `~/.claude/settings.json`. Exit code 2 blocks the action — the only enforcement mechanism that actually works (`CLAUDE.md` is ~80% compliance, hooks are 100%).

## Skills

See [SKILLS.md](SKILLS.md). Ten bundled skills under `workspace-template/skills/`, planted into each agent's workspace at deploy time.
