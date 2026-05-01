---
name: self-schedule
description: "Schedule durable proactivity — recurring (cron-based) or one-shot (at-based) webhook triggers that wake yourself or another agent at a future time. Use when: 'remind me every Monday', 'каждое воскресенье', 'периодически', 'еженедельный дайджест', 'через 3 дня напомни', 'set up a recurring check'."
user-invocable: true
argument-hint: "once <when> <prompt> | recurring <cron-expr> <prompt> [tag] | list | remove <id>"
---

# Self-Schedule (durable proactivity)

This is how you (or another agent) wake up **without** the operator pinging
you. Unlike claude CLI's built-in `mcp__scheduled-tasks__create_scheduled_task`
(which is session-bound and auto-expires after 7 days), this skill writes
real OS-level schedule entries that survive sessions, restarts, and
weeks-long gaps.

## Two modes

| Mode | Mechanism | Use it when |
|---|---|---|
| **once** | `at` daemon | Single future trigger ≤ ~30 days away (reminders, follow-ups). Zero LLM tokens at fire time. |
| **recurring** | system cron at `/etc/cron.d/agent-personal-<agent>` | Periodic triggers (weekly digests, daily audits, every-3-hour competitor checks). Persists indefinitely. |

## Usage

```bash
# One-shot: fire `<prompt>` to yourself in 3 hours.
bash $CLAUDE_SKILL_DIR/scripts/schedule.sh once "now + 3 hours" \
    "Проверь, появились ли свежие комменты по последнему рилу"

# One-shot to a sibling agent (yourself=tyrion, target=varys):
bash $CLAUDE_SKILL_DIR/scripts/schedule.sh once "tomorrow 9am" \
    "Сделай проверку pipeline-state и пингни оператора" --target varys

# Recurring: every Sunday 18:00 UTC, ping yourself with weekly-digest prompt.
bash $CLAUDE_SKILL_DIR/scripts/schedule.sh recurring "0 18 * * 0" \
    "Weekly digest: pipeline state diff с прошлой недели, drop-offs, action items." \
    --tag weekly-digest

# List your scheduled triggers:
bash $CLAUDE_SKILL_DIR/scripts/list.sh

# Remove a recurring entry by line number (from `list` output):
bash $CLAUDE_SKILL_DIR/scripts/remove.sh recurring 7

# Remove a one-shot at-job by id:
bash $CLAUDE_SKILL_DIR/scripts/remove.sh once 42
```

## How it works (under the hood)

1. **Recurring path**: skill calls `sudo /opt/agent-installer/bin/cron-add add
   <self> "<cron-expr>" <base64-prompt> [tag]`. The cron-add binary
   validates args, then appends a line to
   `/etc/cron.d/agent-personal-<self>` of fixed shape:
   ```
   <cron-expr> <run-as-user> /opt/agent-installer/bin/fire-webhook <agent> <base64-prompt>
   ```
   At fire time, `fire-webhook` reads the gateway config + webhook token
   and POSTs the prompt to `/hooks/agent`. The gateway routes it to the
   target agent's queue, which processes the prompt as if from operator.

2. **One-shot path**: skill schedules an `at` job that runs the same
   `fire-webhook` invocation. The job survives the agent's session.

3. **Audit trail**: every schedule action is appended to
   `<workspace>/core/scheduled.md` with timestamp + tag + readable summary.
   When in doubt about what you've scheduled, **read this file first**
   before re-scheduling — duplicates are easy to create otherwise.

## When to use which

| Scenario | Pick |
|---|---|
| «Pingni meня через 30 минут / завтра / через неделю» (один раз) | `once` |
| «Каждый понедельник 9am давай мне brief по новым reels конкурентов» | `recurring` |
| «Этот A/B тест останавливаем через 14 дней — не дай мне забыть» | `once` (точная дата) |
| «Пройдись по `core/inspiration/` каждые выходные и скажи что нового» | `recurring` |
| «Если оператор за 24h не ответил — напомни себе пингнуть» | `once + 24h` (плюс flag в `core/`) |

## Self-discipline rules (Антипаттерны)

- ❌ **Не дублируй**: перед добавлением recurring всегда `bash list.sh` сначала. Если уже есть похожий — remove старый, добавь новый. Иначе оператор получит два дайджеста.
- ❌ **Не планируй чужого агента без согласования**: если хочешь чтобы Тирион на чужой топик пинговал Варис'а — спроси оператора, есть случаи когда это ок (cross-agent coordination), но ты не должен по своей инициативе тригерить чужие сессии.
- ❌ **Не ставь cron чаще раза в час** без явной просьбы оператора. Шумные триггеры заглушают подписку оператора на топик.
- ❌ **Не используй recurring для одноразовых дел**. «Через 14 дней проверим A/B тест» — это `once`, не `recurring 0 0 14 * *` (который сработает в каждом 14-м числе каждый месяц).
- ✅ **Логируй каждое расписание** в `core/scheduled.md` с тэгом + причиной + ожидаемым output'ом. Через месяц вспомнишь зачем это поставлено.
- ✅ **Tag descriptive**: `weekly-digest`, `monday-ritual`, `instagram-fresh-comments`. Не `task1`, `cron-thing`.

## Failure modes

| Что может сломаться | Симптом | Что делать |
|---|---|---|
| webhook token expired/invalidated | curl возвращает 401 в cron stderr | оператор: regenerate via Vesna's `/regenerate_webhook_token` |
| atd / cron не запущены | `at` job или cron entry не срабатывают | оператор: `sudo systemctl status atd cron` |
| gateway config поменялся (agent removed) | fire-webhook exits 2 «agent not found» | удалить устаревшие entries via `remove.sh` |
| dryout: после `/reset` собственной сессии я забываю что планировал | прочитать `core/scheduled.md` при следующей сессии | session-bootstrap уже это делает через `@core/...` includes |

## Anti-pattern: don't reach for `mcp__scheduled-tasks__create_scheduled_task`

claude CLI's built-in scheduler is **session-bound and auto-expires after
7 days** even with `durable=true`. Use this skill instead — it writes real
OS-level entries that don't go away.
