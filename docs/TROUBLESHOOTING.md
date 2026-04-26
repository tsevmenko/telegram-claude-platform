# Troubleshooting

## Installer

**`This installer must be run as root`** — prefix with `sudo`: `curl ... | sudo bash`.

**`Unsupported OS: Ubuntu 23.10`** — only 22.04 and 24.04 are tested. Override with `ALLOW_UNTESTED_UBUNTU=1` if you accept the risk.

**`Telegram rejected the token`** during interactive prompts — token is wrong or revoked. Open `@BotFather`, `/mybots → choose bot → API token`, paste again.

**Installer hung on `apt-get update`** — another dpkg/apt process holds the lock. Wait or `sudo lsof /var/lib/dpkg/lock-frontend` to find the holder. Kill or wait, then re-run `install.sh`.

**Installer reran but skipped a step you wanted re-done** — the state file `/var/lib/agent-installer/state.json` lists completed steps. Edit it and remove a step name to force it to run again.

## Gateway

**Bot doesn't reply in private chat** — check the allowlist: `grep allowed_user_ids /home/agent/gateway/config.json`. If empty, anyone can talk to the bot; if it has IDs, your user_id must be in there.

**Bot doesn't reply in the forum group** — two possible causes:
1. Group ID isn't in `allowed_group_ids` (gateway config).
2. The topic ID isn't routed to this agent. Either `@mention` the bot directly, or ask Vesna to route the topic.

**Live status updates stopped after a few seconds** — Telegram rate-limits `editMessageText` to ~1 per second per chat. The renderer throttles to one edit per 1.5s. If you still see it stalling, the agent may be blocked on a tool call (Bash subprocess hung). `/stop` clears it.

**`telegram.error.RetryAfter`** in logs — your bot is hitting global rate limits. Reduce streaming frequency by setting `streaming_mode_private: "partial"` or `"off"` in the agent's config.

## OAuth

**`claude login` shows 'no internet'** — check that the VPS has outbound HTTPS to `claude.ai`. From RU IPs the OAuth flow itself runs from the VPS but the browser portion needs a non-RU IP — open the link from a machine with a VPN.

**OAuth expired mid-session** — `~/.claude/.credentials.json` has a refresh token that auto-renews; if renewal fails (revoked from claude.com, etc.) you'll see 401s. Re-run `claude login` for that user.

## Cron

**Memory rotation didn't run** — `systemctl is-active cron`. On minimal Ubuntu cloud images cron is sometimes disabled by default. The installer enables it; if you've disabled it manually, `sudo systemctl enable --now cron`.

**`trim-hot.sh` errors with 'Sonnet unavailable'** — Anthropic credentials missing in cron's environment. Cron runs without your shell's PATH and HOME defaults. The cron file in `/etc/cron.d/agent-memory-<name>` sets `HOME` and `CRON_TZ`; if your `claude login` was newer than the cron deploy, restart the cron block by re-running step 85: edit `/var/lib/agent-installer/state.json`, remove `85-cron`, rerun the installer.

## OpenViking

**`openviking.service` failed to start** — most likely the binary isn't installed. The installer warns and skips the service; everything else works without L4. If you want L4, install OpenViking manually and re-run `installer/lib/70-openviking.sh`.

**`L4 push failed` warnings in gateway log** — OpenViking is unreachable. Check `systemctl is-active openviking` and `curl -s http://127.0.0.1:1933/api/v1/health`. If it's down, the gateway falls back gracefully — no L4 features, but everything else continues.

## Useful commands

```bash
# Real-time logs for both gateways
sudo journalctl -u agent-vesna -u agent-user-gateway -f

# Last hour of errors only
sudo journalctl -u agent-vesna -u agent-user-gateway --since '1 hour ago' | grep -iE 'error|fail|traceback'

# Verify config parses
sudo -u agent /home/agent/gateway/.venv/bin/python -c \
    "from agent_gateway.config import GatewayConfig; print(GatewayConfig.load('/home/agent/gateway/config.json'))"

# Manually fire a memory rotation
sudo -u agent /home/agent/.claude-lab/leto/.claude/scripts/trim-hot.sh
cat /tmp/trim-hot.log
```
