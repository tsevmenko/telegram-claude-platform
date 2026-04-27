# Troubleshooting

## Installer

**`This installer must be run as root`** — prefix with `sudo`: `curl ... | sudo bash`.

**`Unsupported OS: Ubuntu 23.10`** — only 22.04 and 24.04 are tested. Override with `ALLOW_UNTESTED_UBUNTU=1` if you accept the risk.

**`Telegram rejected the token`** during interactive prompts — token is wrong or revoked. Open `@BotFather`, `/mybots → choose bot → API token`, paste again.

**Installer hung on `apt-get update`** — another dpkg/apt process holds the lock. Wait or `sudo lsof /var/lib/dpkg/lock-frontend` to find the holder. Kill or wait, then re-run `install.sh`.

**Installer reran but skipped a step you wanted re-done** — the state file `/var/lib/agent-installer/state.json` lists completed steps. Edit it and remove a step name to force it to run again.

## Gateway

**Bot doesn't reply in private chat** — check the allowlist: `grep allowed_user_ids /home/agent/gateway/config.json`. If empty, anyone can talk to the bot; if it has IDs, your user_id must be in there.

**Bot doesn't reply in the forum group** — usually one of these:
1. **Bot isn't admin in the group.** This is the #1 cause: Telegram caches Privacy Mode per-group at join time, so toggling Privacy Mode in @BotFather doesn't affect bots already in groups. The fix is to **promote the bot to admin** (Group settings → Administrators → Add admin → choose bot). Admin bots see all messages regardless of Privacy Mode.
2. Group ID isn't in `allowed_group_ids` — `grep allowed_group_ids /home/agent/gateway/config.json` should include your group's chat_id.
3. The topic ID isn't routed to this agent. Either `@mention` the bot directly, or ask Vesna `/route_topic <topic_id> <agent>` to wire the topic.

**Verify the bot can read messages** (definitive test):
```bash
# Stop the gateway briefly, fetch any pending updates
sudo systemctl stop agent-vesna
TOKEN=$(sudo cat /root/secrets/vesna-bot-token)
# Now in Telegram, send any message in the group
sleep 5
curl -s "https://api.telegram.org/bot${TOKEN}/getUpdates" | python3 -m json.tool
sudo systemctl start agent-vesna
```
- Empty `result: []` → bot isn't seeing messages → make it admin.
- Has `result: [{message: ...}]` → Telegram delivers, gateway should be processing — check `journalctl -u agent-vesna`.

**Live status updates stopped after a few seconds** — Telegram rate-limits `editMessageText` to ~1 per second per chat. The renderer throttles to one edit per 1.5s. If you still see it stalling, the agent may be blocked on a tool call (Bash subprocess hung). `/stop` clears it.

**`telegram.error.RetryAfter`** in logs — your bot is hitting global rate limits. Reduce streaming frequency by setting `streaming_mode_private: "partial"` or `"off"` in the agent's config.

## OAuth

**`claude login` shows 'no internet'** — check that the VPS has outbound HTTPS to `claude.ai`. If your IP is in a region where Anthropic OAuth is restricted, the VPS-side flow runs fine but the browser-side authorization step needs a non-restricted IP — open the URL from a machine on a VPN.

**OAuth expired mid-session** — `~/.claude/.credentials.json` has a refresh token that auto-renews; if renewal fails (revoked from claude.com, etc.) you'll see 401s. Re-run `claude login` for that user.

## Cron

**Memory rotation didn't run** — `systemctl is-active cron`. On minimal Ubuntu cloud images cron is sometimes disabled by default. The installer enables it; if you've disabled it manually, `sudo systemctl enable --now cron`.

**`trim-hot.sh` errors with 'Sonnet unavailable'** — Anthropic credentials missing in cron's environment. Cron runs without your shell's PATH and HOME defaults. The cron file in `/etc/cron.d/agent-memory-<name>` sets `HOME` and `CRON_TZ`; if your `claude login` was newer than the cron deploy, restart the cron block by re-running step 85: edit `/var/lib/agent-installer/state.json`, remove `85-cron`, rerun the installer.

## OpenViking

**`openviking.service` failed to start** — most likely the binary isn't installed. The installer warns and skips the service; everything else works without L4. If you want L4, install OpenViking manually and re-run `installer/lib/70-openviking.sh`.

**`L4 push failed` warnings in gateway log** — OpenViking is unreachable. Check `systemctl is-active openviking` and `curl -s http://127.0.0.1:1933/api/v1/health`. If it's down, the gateway falls back gracefully — no L4 features, but everything else continues.

## Useful commands

```bash
# Real-time logs for both gateways (logs go to journald)
sudo journalctl -u agent-vesna -u agent-user-gateway -f

# Last hour of errors only
sudo journalctl -u agent-vesna -u agent-user-gateway --since '1 hour ago' | grep -iE 'error|fail|traceback'

# OpenViking-lite logs
sudo journalctl -u openviking -f

# Verify config parses
sudo -u agent /home/agent/gateway/.venv/bin/python -c \
    "from agent_gateway.config import GatewayConfig; print(GatewayConfig.load('/home/agent/gateway/config.json'))"

# Manually fire a memory rotation
sudo -u agent /home/agent/.claude-lab/leto/.claude/scripts/trim-hot.sh
cat /tmp/trim-hot.log
```
