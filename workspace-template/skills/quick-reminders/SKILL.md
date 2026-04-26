---
name: quick-reminders
description: "One-shot reminders up to 48 hours. Zero LLM tokens at fire time. Use when: remind me, set a reminder, don't forget, ping me at."
user-invocable: true
argument-hint: "<text> -t <time-spec> --target <chat-id-or-self>"
---

# Quick Reminders

Schedule a one-shot reminder. The agent composes the final message at creation time, then the system delivers it later via `at` (or a fallback cron entry) — **no LLM tokens are consumed at fire time**.

## When to use

- "Remind me in 30 minutes to..."
- "Tomorrow at 9am, ping me about..."
- "Don't let me forget to..."

## Setup

The system installer enables `atd` if it is not already running. On minimal images run:

```bash
sudo apt-get install -y at
sudo systemctl enable --now atd
```

Telegram delivery requires the gateway's webhook token — see the gateway's `webhook-token.txt`.

## Usage

```bash
bash $CLAUDE_SKILL_DIR/scripts/add.sh "Call about the project" \
    --target $CHAT_ID -t "2h"
```

Time specs accepted by `at`:
- `now + 30 minutes`
- `2h`, `45m`, `1d`
- `tomorrow 9am`, `noon`
- `14:30`

## How it works

1. The skill writes a small payload to `/var/spool/agent-reminders/<id>.json`.
2. It schedules an `at` job that POSTs the payload to the gateway's webhook API at fire time.
3. The gateway delivers the message to the operator's Telegram chat as if it came from the agent.
