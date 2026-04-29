# AGENTS — Subagent directory (on-demand)

_NOT loaded into session context. Read with the `Read` tool when you need to spawn a subagent or look up another agent's role._

## Local subagents (Claude Code built-in)

| Subagent | When to use |
|---|---|
| `Explore` | Quickly find files by patterns, search code for keywords, answer questions about the codebase. |
| `general-purpose` | Open-ended research that spans the codebase or needs multiple tool calls in sequence. |
| `Plan` | Design implementation strategy before coding a non-trivial change. |
| `code-reviewer` | Independent review of a diff or PR. Get a second opinion on safety / correctness. |

Spawn with the `Task` tool. Brief the subagent like a smart colleague who just walked into the room — give context, files, what was tried, what success looks like.

## Cross-bot agents on this VPS

The platform runs **two isolated systemd gateway processes** by design (process isolation — Sprint 2 P5):

| Gateway service | User | Webhook | Hosts agents | Reachable from |
|---|---|---|---|---|
| `agent-vesna.service` | `root` | not exposed by default | Vesna only | Telegram Tech topic only |
| `agent-user-gateway.service` | `agent` | `127.0.0.1:8080` | Leto, Tyrion, any future client agents | Any process on the same host that holds `~/secrets/webhook-token.txt` |

```
| Agent  | Topic     | What it does |
|--------|-----------|--------------|
| Vesna  | Technical | VPS administration, agent CRUD, system recovery — root-level. |
| Leto   | Main      | Operator's primary work agent (chat, voice, code). |
| Tyrion | Social    | Social-media analytics + drafts (IG/Threads/Shorts/LinkedIn). |
```

### Cross-agent webhook (client-to-client only)

You CAN call other client agents on the user-gateway via `127.0.0.1:8080`:

```bash
# Leto pinging Tyrion (or vice versa). agent= must be a name that lives in
# /home/agent/gateway/config.json's "agents" map (currently leto, tyrion).
curl -X POST http://127.0.0.1:8080/hooks/agent \
  -H "Authorization: Bearer $(cat ~/secrets/webhook-token.txt)" \
  -H "Content-Type: application/json" \
  -d '{"agent":"<name>","chat_id":<id>,"text":"<message>"}'
```

### Vesna is NOT reachable via webhook from client agents — by design

Vesna runs on a separate root-owned gateway (`agent-vesna.service`) and her webhook is intentionally NOT exposed on `127.0.0.1`. The user-gateway has no programmatic path to her.

The only way to reach Vesna from a client agent is **through the operator**:

- Surface what you need to the operator in your own topic
- Operator decides whether the request is legitimate
- Operator messages Vesna in the Technical topic

This is a security feature — client agents must not be able to invoke root-level admin actions without human-in-the-loop. If an attacker compromises Tyrion via prompt injection in an Instagram comment, they cannot pivot to Vesna and run sudo commands on the host.

If a client agent tries to POST `agent=vesna` to `127.0.0.1:8080/hooks/agent`, the gateway returns `404 unknown agent: vesna` — that's correct behaviour.

## External agents

_(Operator can extend this section as new agents are added — e.g. for cron-driven background workers via the 3rd OAuth slot, see `docs/ADD-NEW-AGENT.md`.)_

## Coordination rules

- Never act on another agent's behalf. If a request comes from a different topic, refuse politely and direct the operator.
- For shared resources (memory, learnings), each agent reads / writes its own workspace. Cross-agent search via OpenViking is read-only.
- Vesna is the only path to admin actions. Client agents that need something at the root level must ask the operator, not Vesna directly.
