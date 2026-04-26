# Add a new client agent

You don't edit configs by hand — Vesna does it. Open the **Technical** topic of your forum group and ask:

> Vesna, add a new agent named **coder** with model **opus**. System reminder: "you are a senior backend engineer; assume Python + asyncio." Bot token: `<paste from @BotFather>`.

Vesna will:

1. Patch `/home/agent/gateway/config.json` — append the agent block.
2. Create `/home/agent/.claude-lab/coder/.claude/` from `workspace-template/`.
3. Save the bot token under `/home/agent/secrets/coder-bot-token` (`chmod 600`).
4. `sudo systemctl restart agent-user-gateway`.
5. Confirm:
   > ✓ Coder added. Create a new topic in the group named "Coder" and tell me its ID — I'll wire the topic routing.

## Wire the topic

In the forum group, open the new topic, open the topic options, copy the topic ID. Tell Vesna:

> Vesna, route topic **42** to **coder**.

Vesna patches the agent's `topic_routing` and restarts. The new topic is now Coder's.

## Verify

In the new topic, send: `hi, who are you?` — Coder responds in its configured persona.

## Remove an agent

> Vesna, remove agent **coder**.

Vesna confirms, removes the config block, removes the workspace (and archives it to `/home/agent/.claude-lab/.archived/coder-YYYY-MM-DD/`), revokes the bot token from secrets, restarts user-gateway.

## Manual fallback

If Vesna is down, you can edit `/home/agent/gateway/config.json` directly:

```bash
sudo -u agent vim /home/agent/gateway/config.json
sudo systemctl restart agent-user-gateway
sudo journalctl -u agent-user-gateway -f
```

The `config.json` schema is in `gateway/src/agent_gateway/config.py` — pydantic will yell loudly if you miss a field.
