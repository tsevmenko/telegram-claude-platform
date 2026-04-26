# Prompt Library

A small library of pre-written prompts the operator can paste into Vesna for advanced operations. **None of these are required for a basic install** — the installer covers everything. Use these when something has gone wrong, or to do an audit.

Each prompt is meant to be sent to **Vesna** in the **Technical** topic.

---

## Pre-install: SSH troubleshooting

Use before running the installer if you can't connect via Cursor Remote-SSH.

```
Help me connect to my VPS via SSH through Cursor (Remote-SSH).

My situation:
- VPS IP: [PASTE]
- VPS OS: Ubuntu (22.04 or 24.04)
- My computer: [macOS / Windows / Linux]
- Connecting as: root

What I tried:
1. Installed Cursor (or VSCode)
2. Installed the Remote-SSH extension
3. [Describe what worked and what didn't]

Error:
[paste the error message if any]

Please walk me through:
1. Whether I have an SSH key (~/.ssh/id_ed25519 or id_rsa)
2. If not — generate one
3. Copy the public key to the VPS
4. Verify ssh root@IP works from a regular terminal
5. Configure Remote-SSH in Cursor (~/.ssh/config, host entry)
6. If anything fails, explain the cause and the fix
```

---

## Post-install verification (table format)

```
Verify everything the installer should have done. Format as a table:
[Check | Command | Expected | Actual | OK/FAIL]

1. User `agent` exists                    | id agent                                    | uid >= 1000
2. Node 20+                               | node -v                                     | v20.x or higher
3. Python 3.12+                           | python3 --version                           | 3.12+
4. claude on PATH                         | which claude                                | /usr/local/bin/claude
5. agent-vesna service active             | systemctl is-active agent-vesna             | active
6. agent-user-gateway service active      | systemctl is-active agent-user-gateway      | active
7. Vesna workspace                        | ls /root/.claude-lab/vesna/.claude/         | CLAUDE.md, core/, skills/
8. Leto workspace                         | ls /home/agent/.claude-lab/leto/.claude/    | CLAUDE.md, core/, skills/
9. Sudoers narrow file                    | ls -la /etc/sudoers.d/agent-narrow          | exists, 0440 root:root
10. Cron entries (vesna)                  | crontab -u root -l                          | 5 memory rotation lines
11. Cron entries (agent)                  | crontab -u agent -l                         | 5 memory rotation lines
12. Webhook token generated               | test -s /root/vesna/webhook-token.txt       | file exists, 64 hex chars
13. OpenViking reachable                  | curl -s localhost:1933/api/v1/health        | "ok"
14. Skills installed                      | ls /home/agent/.claude-lab/leto/.claude/skills/ | 10 skills

If any FAIL: report what's broken and how to fix it.
```

---

## Recovery: Leto silent

Use when Leto stops replying.

```
Leto isn't replying in the Main topic. Show me the last 50 lines of
`journalctl -u agent-user-gateway`. Identify the error, fix it, restart the service,
verify it's active. If OAuth credentials expired, tell me the exact command to run.
```

---

## Recovery: OAuth expired

```
Check whether `/home/agent/.claude/.credentials.json` is still valid OAuth.
If it's expired or missing, tell me the exact command I need to run from a terminal
to re-authenticate the agent user. Don't try to log in for me.
```

---

## Recovery: Disk full

```
Leto reported 'no space left'. Show me:
- df -h
- du -sh /home/agent/.cache
- du -sh /home/agent/.claude-lab/leto/logs
- du -sh /var/log/openviking
- du -sh /var/lib/openviking

Propose what to clean up and ask before deleting.
```

---

## Recovery: Cron didn't run last night

```
The HOT memory file is over 100KB — `trim-hot.sh` doesn't seem to have run.
Check:
- systemctl is-active cron
- /etc/cron.d/agent-memory-leto exists
- /tmp/trim-hot.log

Run trim-hot.sh manually as the agent user and report the result.
```

---

## Audit: full Day-1 self-diagnostic

```
Full system audit. Format as [Component | Status | Detail]:

1. Vesna service active                — systemctl is-active agent-vesna
2. user-gateway service active         — systemctl is-active agent-user-gateway
3. OpenViking active                   — systemctl is-active openviking
4. Vesna OAuth                         — test -f /root/.claude/.credentials.json
5. agent OAuth                         — test -f /home/agent/.claude/.credentials.json
6. Sudoers narrow file                 — visudo -cf /etc/sudoers.d/agent-narrow
7. Cron memory rotation                — crontab -u root -l && crontab -u agent -l
8. HOT file size for Leto              — wc -c /home/agent/.claude-lab/leto/.claude/core/hot/recent.md
9. WARM file size for Leto             — wc -c /home/agent/.claude-lab/leto/.claude/core/warm/decisions.md
10. OpenViking responding              — curl -s localhost:1933/api/v1/health
11. Webhook token present              — test -s /root/vesna/webhook-token.txt
12. Telegram bot Vesna reachable       — curl -s api.telegram.org/bot<TOKEN>/getMe
13. Telegram bot Leto reachable        — curl -s api.telegram.org/bot<TOKEN>/getMe

Verdict: READY / DEGRADED / DOWN. If degraded — list the fixes.
```

---

## Compare against source of truth

If something in the workspace looks wrong, compare to the canonical templates in this repo:

```
The agent's CLAUDE.md feels off. Compare /home/agent/.claude-lab/leto/.claude/CLAUDE.md
with the canonical template at workspace-template/CLAUDE.md.tmpl in our repo on GitHub
(github.com/tsevmenko/telegram-claude-platform). Show me the diff and which sections drifted.
```
