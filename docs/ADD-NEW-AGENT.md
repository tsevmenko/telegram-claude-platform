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

## Adding a 3rd OAuth slot for a debug or background agent

Anthropic Max permits **3 concurrent OAuth tokens** under one subscription — one per `~/.claude/` directory under each Linux user. Our default install uses two of them: `/root/.claude/` for Vesna and `/home/agent/.claude/` for Leto and any client agents under the user-gateway. The third slot is unused and reserved for cases like:

- A **dedicated background worker** that runs nightly audits / cron-driven analyses without competing for live-session OAuth.
- A **hot-spare debug agent** the operator can talk to when both Vesna and Leto are wedged (e.g. after a bad deploy that took down the gateway code shared by both).
- A **compute-isolated experiment slot** for trying new models, plugin packs, or hooks without destabilising the production agents.

### One-shot setup

```bash
# 1. Create a system user (no login, no shell access).
sudo useradd --system --create-home --shell /usr/sbin/nologin agent-debug

# 2. Plant a /home/agent-debug/.claude/ directory.
sudo install -d -o agent-debug -g agent-debug -m 0700 /home/agent-debug/.claude

# 3. Run `claude login` as that user — opens the OAuth browser flow against
#    a fresh ~/.claude/.credentials.json that's distinct from Vesna's and Leto's.
sudo -u agent-debug -i bash -lc 'claude login'

# 4. (If you want this user to run the agent_gateway code:) follow the
#    50-vesna.sh / 60-user-gateway.sh patterns to plant a venv, source copy,
#    config.json, systemd unit. Easiest is to copy 60-user-gateway.sh and
#    rename `agent` → `agent-debug` throughout.
```

### Recovery use case

If `gateway/` ships a regression that takes down both Vesna and Leto, the third OAuth slot lets you keep talking to a 3rd agent via Telegram (run from a stable older platform tag). That agent can SSH into the VPS and `git checkout v0.1.0-baseline && systemctl restart agent-vesna agent-user-gateway` to roll back. Without this slot you'd be stuck SSHing manually with no Telegram access.

This is the same insurance pattern the original `edgelab.su` project uses (Jarvis + Richard as separate processes) — except we're using it for hot-spare disaster recovery rather than as our primary architecture.

### Why keep it documented but not auto-deployed

We don't pre-deploy the third agent for two reasons:
- Most operators won't need it, and the OAuth flow requires an interactive browser step that we can't safely automate inside an installer.
- The use cases vary too much to ship a single pre-baked role — a nightly auditor and a hot-spare have different `system_reminder`, `model`, and `topic_routing` profiles.

Add the third agent only when you have a specific job for it. Reuse `60-user-gateway.sh` as a starting template.
