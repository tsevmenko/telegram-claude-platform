# Proactivity stack — v0.4.2+

How agents wake up at scheduled times **without** the operator pinging them.

## Two mechanisms, one back-end

| Mode | Mechanism | Use it for |
|---|---|---|
| **once** | `at` daemon | One-shot reminders / follow-ups / deadline triggers ≤ ~30 days away |
| **recurring** | system cron at `/etc/cron.d/agent-personal-<agent>` | Periodic triggers (weekly digests, daily audits, hourly polls) |

Both ultimately call `/opt/agent-installer/bin/fire-webhook <agent> <base64-prompt>`,
which POSTs the decoded prompt to `/hooks/agent` on the user-gateway. The agent
processes the wake-up prompt as if it came from the operator.

## Skill: `self-schedule`

Lives in every agent's workspace at `skills/self-schedule/`. Three scripts:

```bash
# One-shot
schedule.sh once "<when>" "<prompt>" [--target <other-agent>]

# Recurring
schedule.sh recurring "<cron-expr>" "<prompt>" [--tag <label>] [--target <other-agent>]

# List everything self has scheduled
list.sh

# Remove (id from list.sh)
remove.sh recurring <line-number>
remove.sh once <at-job-id>
```

Every action is appended to `<workspace>/core/scheduled.md` as a durable
audit log so the agent can see what's already armed (avoid duplicates) on
subsequent sessions.

## Architecture

```
[agent says "schedule weekly digest"]
   │
   ▼
[skill self-schedule] schedule.sh recurring "0 18 * * 0" "<prompt>" --tag X
   │
   ▼ (sudo, narrow grant in /etc/sudoers.d/agent-narrow)
/opt/agent-installer/bin/cron-add add tyrion "0 18 * * 0" <base64> X
   │ (validates: agent name in config, cron-expr 5-field, base64 alphabet)
   ▼
Append to /etc/cron.d/agent-personal-tyrion:
   "0 18 * * 0 agent /opt/agent-installer/bin/fire-webhook tyrion <base64>"
   │
   ▼ (cron fires Sunday 18:00 UTC)
fire-webhook tyrion <base64>:
   reads /home/agent/secrets/webhook-token.txt
   reads /home/agent/gateway/config.json (chat_id + thread_id for tyrion)
   POST /hooks/agent with decoded prompt
   │
   ▼
Gateway → Tyrion's queue → fresh claude subprocess with that prompt
   │
   ▼
Tyrion processes → writes response in Social topic
```

## Vesna self-schedule limitation (variant A — current state)

The webhook listener at `127.0.0.1:8080` lives **inside the
user-gateway-process** (Leto + Tyrion + Varys). Vesna runs in a separate
process (`agent-vesna.service`, root) without its own webhook listener.

**Consequence**: when `fire-webhook` is invoked with `agent=vesna`, the POST
goes to user-gateway, which doesn't know about Vesna and returns 404.

### What works

| Scenario | Works |
|---|---|
| Vesna creates a recurring trigger that fires Tyrion / Leto / Varys | ✅ — webhook routes to user-gateway agents |
| Vesna creates a one-shot at-job that fires another agent | ✅ |
| Tyrion / Leto / Varys schedule themselves | ✅ — same process |

### What doesn't (yet — see v0.4.4)

| Scenario | Current state |
|---|---|
| Vesna schedules a daily server-health check on **herself** | ❌ — webhook 404 on `agent=vesna` |
| Vesna self-monitors disk / journal / cron and pings the Technical topic | ❌ |
| Auto-self-test after deploy | ❌ for Vesna; ✅ if delegated to Tyrion-as-watchdog |

### Workarounds today

1. **Delegate to a user-agent**. Vesna creates a recurring entry that
   fires Tyrion: `0 8 * * * agent fire-webhook tyrion <base64-prompt>` where
   the prompt is "Run a server-health check via sudo, post the result in
   the Technical topic". Tyrion has narrow-sudo for the relevant commands
   (`systemctl`, `journalctl`).

2. **Pure-bash cron** for non-LLM monitoring. If the check is "is disk usage
   > 80%, alert if yes", that's a 10-line bash script — no LLM needed:
   ```cron
   0 * * * * root /usr/local/bin/disk-watch.sh
   ```
   `disk-watch.sh` curls Telegram Bot API directly to post in Technical when
   threshold crossed. Saves tokens, simpler.

### v0.4.4 fix (planned, not committed)

Add a webhook listener to `agent-vesna.service` on `127.0.0.1:8081`.
`fire-webhook` becomes router-aware:

```bash
case "$AGENT" in
    vesna)        WEBHOOK_URL=http://127.0.0.1:8081/hooks/agent ;;
    leto|tyrion|varys|*) WEBHOOK_URL=http://127.0.0.1:8080/hooks/agent ;;
esac
```

This unblocks Vesna self-schedule symmetrically with user-agents. ETA: ~1
hour of work (extend `webhook_api.py` config to be per-process, plant the
new endpoint, update fire-webhook). Held until there's a concrete operator
need (so far cross-agent delegation has covered all scenarios).

## Adding a new agent — proactivity inheritance

When Vesna's `add_agent` skill creates a new client agent (via
`rsync workspace-template/ → ~/.claude-lab/<name>/`), that agent automatically
inherits:

- `skills/self-schedule/` — full skill, ready to use
- `skills/quick-reminders/` — one-shot reminder helper
- `core/scheduled.md` placeholder (created on first schedule call)
- `CLAUDE.md` Proactivity section (rendered from `.tmpl` at workspace creation)

No additional setup needed — new agents can self-schedule from session 1.

## Practical patterns

| Trigger | Agent | Example prompt |
|---|---|---|
| Monday 9 UTC | Tyrion | "Walk through `core/competitors/`, summarise diffs since last week, propose 5 content ideas." |
| Sunday 18 UTC | Varys | "Weekly pipeline digest: ManyChat state diff, ClickUp deltas, drop-offs, action items." |
| Daily 8 UTC | Tyrion (delegated by Vesna) | "Run `df -h` and `journalctl -u agent-user-gateway --since 24h | grep -i error`. Post anomalies in Technical." |
| Every 3 hours | Tyrion | "Check `core/inspiration/` for new entries. If any, summarise the pattern they reveal." |

All of these use `self-schedule recurring`. The cron files are at
`/etc/cron.d/agent-personal-<agent>`, viewable via `list.sh`.

## When NOT to use self-schedule

- ❌ One-time tasks ("сделай X сейчас") — that's just normal operator → agent
  conversation. self-schedule is for **future** triggers only.
- ❌ Reactive triggers (when X happens, do Y) — that's webhook-from-external
  source, different mechanism. e.g. ManyChat fires our `/hooks/manychat` →
  routes to Tyrion. Future scope.
- ❌ Conditions checked in real-time ("if disk > 80% pingме") — cron polls
  every N minutes. Use systemd watchdog for instant alerting if you need
  sub-minute reaction.

## Failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| Cron entry exists but never fires | `cron` service down OR cron file not picked up | `systemctl status cron`, `systemctl reload cron` |
| `at` job exists but never fires | `atd` service down | `systemctl status atd; systemctl enable --now atd` |
| `fire-webhook` returns 401 | Webhook token rotated, old token in cron entry | Regenerate cron entries via `cron-add remove` + re-add |
| `fire-webhook` returns 404 with "agent not found" | Stale cron entry for agent removed from gateway config | `cron-add list <self> | grep <removed-agent>; cron-add remove ...` |
| Agent doesn't respond when fired | Subprocess stuck on previous turn (busy queue) | OOB `/stop` to clear queue; check logs |

## Audit & inspection

**See what's scheduled for self**:

```bash
# Inside agent's workspace context
bash skills/self-schedule/scripts/list.sh
```

Combines: cron entries (`/etc/cron.d/agent-personal-<self>`), at-jobs
(`atq`), and audit log tail (`core/scheduled.md`).

**See all per-agent cron files** (operator, via SSH):

```bash
ls -la /etc/cron.d/agent-personal-*
cat /etc/cron.d/agent-personal-tyrion
```

**Audit log per agent**:

```bash
cat ~/.claude-lab/<agent>/core/scheduled.md
```
