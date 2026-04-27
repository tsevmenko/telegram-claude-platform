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

| Agent | Topic | What it does |
|---|---|---|
| Vesna | Technical | VPS administration, agent CRUD, system recovery |
| Leto  | Main      | Operator's primary work agent (chat, voice, code) |

To talk to another agent on this VPS, use the gateway's webhook API:

```bash
curl -X POST http://127.0.0.1:8080/hooks/agent \
  -H "Authorization: Bearer $(cat ~/secrets/webhook-token.txt)" \
  -H "Content-Type: application/json" \
  -d '{"agent":"<name>","chat_id":<id>,"text":"<message>"}'
```

## External agents

_(Operator can extend this section as new agents are added.)_

## Coordination rules

- Never act on another agent's behalf. If a request comes from a different topic, refuse politely and direct the operator.
- For shared resources (memory, learnings), each agent reads / writes its own workspace. Cross-agent search via OpenViking is read-only.
