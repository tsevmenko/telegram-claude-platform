# Recovery

Things go wrong. When Leto stops replying, when OAuth expires, when cron didn't run — Vesna is your safety net. This is the playbook.

## Principle

You don't SSH unless Vesna is also down. Send Vesna a recovery prompt in the **Technical** topic; she has the tools (passwordless `systemctl`, `journalctl`, `apt`) to investigate and fix.

## Scenarios

### Leto is silent

Symptom: you sent Leto a message and got nothing back, not even the `👀` reaction.

Send Vesna:

```
Leto isn't replying in the Main topic. Show me the last 50 lines of
`journalctl -u agent-user-gateway`. Identify the error, fix it, restart the service.
If OAuth expired, tell me the exact command I need to run myself.
```

### OAuth credentials expired

Symptom: gateway logs show `401 Unauthorized` from Anthropic.

Send Vesna:

```
Check whether `/home/agent/.claude/.credentials.json` is valid. If expired,
tell me the command I need to run myself — you can't log in on my behalf.
```

You will run something like:
```bash
sudo -u agent -i bash -lc 'claude login'
```

### Out of disk space

Symptom: gateway logs show `ENOSPC` or Leto answers "I can't write to disk".

Send Vesna:

```
Leto says it's out of disk space. Show df -h and du -sh on:
~/.cache, ~/.claude-lab/leto/logs, /var/log/openviking, /var/lib/openviking.
Propose what to clean up. Ask before deleting anything.
```

### Cron didn't run last night

Symptom: HOT file is huge; WARM didn't get yesterday's compressed entries.

Send Vesna:

```
HOT memory for Leto is over 100KB — yesterday's trim-hot.sh didn't run.
Check: systemctl is-active cron, /tmp/trim-hot.log, /etc/cron.d/agent-memory-leto.
Run trim-hot.sh manually as the agent user and report the result.
```

### A bot token leaked

If you accidentally pasted a bot token in the wrong place:

1. Open `@BotFather`, choose the bot, `/revoke` to invalidate the leaked token.
2. `/newtoken` to issue a new one.
3. Send Vesna: `update <agent>'s bot token: <NEW_TOKEN>` (only in Technical topic).

### Webhook token leaked

```
Regenerate the webhook token. Send me the new one in this topic only.
```

Vesna runs `openssl rand -hex 32`, updates `/root/vesna/webhook-token.txt` and `/home/agent/secrets/webhook-token.txt`, restarts user-gateway, and posts the new token to you.

### Vesna herself is down

This is the only scenario that requires SSH:

```bash
ssh root@<vps>
sudo journalctl -u agent-vesna -n 200 --no-pager
sudo systemctl restart agent-vesna
sudo systemctl status agent-vesna
```

If `claude login` is the issue:
```bash
sudo -u root -i bash -lc 'claude login'
sudo systemctl restart agent-vesna
```

If Vesna's workspace is corrupt and you want to re-plant it:
```bash
sudo bash /usr/local/share/agent-installer/install.sh   # idempotent — re-runs whatever's broken
```

(Or re-run the original `curl … | sudo bash` URL.)
