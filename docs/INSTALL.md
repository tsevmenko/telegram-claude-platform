# Install

## Pre-flight checklist

| # | What | Where | Why |
|---|---|---|---|
| 1 | Ubuntu VPS | Hetzner / DigitalOcean / Linode | 22.04 or 24.04, 2GB+ RAM, root SSH |
| 2 | SSH key | `ssh-keygen -t ed25519` + `ssh-copy-id` | Key auth instead of password |
| 3 | Cursor / VSCode + Remote-SSH | cursor.com / code.visualstudio.com | Convenient SSH with file editor |
| 4 | Anthropic Max or Pro | claude.com/pricing | Required for `claude login` OAuth |
| 5 | Gmail for Anthropic | existing or new | Anthropic login |
| 6 | VPN if your IP is in a sanctioned region | any reputable VPN | Anthropic OAuth restricts certain regions — needed only for the browser-side step of `claude login` |
| 7 | Telegram on phone | already installed | Bot creation + user_id lookup |
| 8 | 2 Telegram bot tokens | `@BotFather` → `/newbot` × 2 | Vesna + Leto |
| 9 | Telegram numeric user_id | `@userinfobot` → `/start` | Bot allowlist |
| 10 | Forum group with 2 topics | Telegram → Group → Convert to forum | Main + Technical topics |
| 10a | **Bots promoted to admin** in the forum group | Group settings → Administrators → Add Admin | Telegram caches Privacy Mode at the moment a bot joins a group; admin status bypasses that and lets the bot see all messages reliably |
| 11 | Groq API key (recommended) | console.groq.com — free tier | Voice transcription |

## Run

On the VPS as root:

```bash
curl -fsSL https://raw.githubusercontent.com/tsevmenko/telegram-claude-platform/main/install.sh | sudo bash
```

Answer the interactive prompts. Each Telegram token is verified via `getMe`; on failure you can retry or skip.

## After install

1. **OAuth as root:** `sudo -u root -i bash -lc 'claude login'`
2. **OAuth as agent:** `sudo -u agent -i bash -lc 'claude login'`
3. **Save the webhook token** printed in the final banner (or read it later: `sudo cat /root/vesna/webhook-token.txt`).
4. **Run [CLIENT-TEST-INSTRUCTIONS.md](CLIENT-TEST-INSTRUCTIONS.md)** in Telegram — ~45 minutes total.

## Re-run

The installer is idempotent. Re-running picks up where it left off via `/var/lib/agent-installer/state.json`.

To force a step to run again: edit that file and remove the step name from `completed_steps`.
