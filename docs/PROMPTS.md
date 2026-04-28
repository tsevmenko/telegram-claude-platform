# Prompt Library

Pre-written prompts you can paste into Vesna or Leto to drive specific workflows. **None of these are required for a basic install** — the installer covers everything end-to-end. Use these as a daily-driver toolkit.

Each prompt is meant to be sent to either:

- **Vesna** (Technical topic) — for system, install, audit, recovery
- **Leto** (Main topic, or whichever client agent you have) — for content, research, coding, daily tasks

---

# Daily-driver prompts (Leto / client agents)

## Onboarding (voice-first)

Send this to **Leto** in Main topic. Then send a voice memo + drop links.

```
/onboarding
```

Then record: who you are, what you do, mission, what you want from me. Drop links to your Telegram channel / IG / website / GitHub. Leto will synthesise `core/USER.md`.

If you prefer typing, just send `/onboarding` and answer the questions text-style.

---

## "Use this skill" — discovery

```
/skill-finder

Find me a skill that does X. Search skills.sh and our internal catalog.
If nothing matches, propose a SKILL.md draft and add it to my skills folder.
```

---

## Daily kickoff

Morning ritual to give the agent context for the day.

```
Quick brief on yesterday's open threads + today's plan:

1. Read core/hot/handoff.md and tell me what's hanging from yesterday.
2. I'm planning to work on: [LIST 2-3 THINGS].
3. Anything I should remember from L4 about these topics? Run a recall.
4. What would you do first if you were me?
```

---

## End of session — write handoff

```
Wrap up this session for tomorrow's me:

- What did we ship today (1 line)?
- What's blocked / waiting (1 line each)?
- What's the obvious next step?
- Save it to core/hot/handoff.md so I see it tomorrow.
```

---

## Compose a Telegram-channel post (voice → polished text)

Send a voice memo first; then:

```
Take what I just said and turn it into a Telegram-channel post:
- 800 chars max
- One emoji at the start, none in the body
- One actionable hook in the last sentence
- No filler ("Today I want to share…")
Show me 2 variants and let me pick.
```

---

## Research a topic

```
/web-research

Research [TOPIC]. Bring me the 3-5 most authoritative sources with 1-line summaries each, plus a 200-word digest. Cite URLs.
```

---

## Code review of a diff

```
/codex-review

Review this diff (show me as adversarial — assume the worst case). I'll paste below:

```diff
[PASTE]
```

Surface real bugs, not nits. Rate severity HIGH/MED/LOW each.
```

---

## YouTube transcript → summary

```
/youtube-transcript https://youtube.com/watch?v=XXXX

Then summarise in 5 bullets + a 1-line "should I watch?" verdict.
```

---

## Webpage → clean Markdown

```
/markdown-extract https://example.com/article

Strip ads, save it to /tmp/article.md, then summarise in 3 bullets.
```

---

## Quick reminder

```
/quick-reminders

Ping me in 4 hours: "review the PR Bob sent". Don't forget.
```

---

## Brainstorm a feature

```
Use the brainstorming skill (or just think out loud). I'm trying to decide between [OPTION A] and [OPTION B] for [GOAL]. Argue both sides hard, then commit to one with reasoning.
```

---

## Planning a multi-step task (TDD-style)

```
Use writing-plans + executing-plans + test-driven-development.

Goal: [DESCRIBE]. Constraints: [DESCRIBE]. Don't write code yet — give me a plan, ask 1-2 clarifying questions if needed, then I'll approve and you execute step by step with tests.
```

---

# System / install / audit prompts (Vesna)

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

Walk me through:
1. Whether I have an SSH key (~/.ssh/id_ed25519 or id_rsa)
2. If not — generate one
3. Copy the public key to the VPS
4. Verify ssh root@IP works from a regular terminal
5. Configure Remote-SSH in Cursor (~/.ssh/config, host entry)
6. If anything fails, explain the cause and the fix.
```

---

## Post-install verification (table format)

```
Verify everything the installer should have done. Format as a table:
[Check | Command | Expected | Actual | OK/FAIL]

1.  User `agent` exists                    | id agent                                    | uid >= 1000
2.  Node 22+                               | node -v                                     | v22.x or higher
3.  Python 3.12+                           | python3 --version                           | 3.12+
4.  claude on PATH                         | which claude                                | /usr/local/bin/claude
5.  agent-vesna service active             | systemctl is-active agent-vesna             | active
6.  agent-user-gateway service active      | systemctl is-active agent-user-gateway      | active
7.  openviking service active              | systemctl is-active openviking              | active
8.  Vesna workspace                        | ls /root/.claude-lab/vesna/.claude/         | CLAUDE.md, core/, skills/
9.  Leto workspace                         | ls /home/agent/.claude-lab/leto/.claude/    | CLAUDE.md, core/, skills/
10. Sudoers narrow file                    | ls -la /etc/sudoers.d/agent-narrow          | exists, 0440 root:root
11. Cron entries (vesna)                   | cat /etc/cron.d/agent-memory-vesna          | 5 lines + tcp marker
12. Cron entries (agent)                   | cat /etc/cron.d/agent-memory-leto           | 5 lines + tcp marker
13. Webhook token generated                | test -s /root/vesna/webhook-token.txt       | file exists, 64 hex chars
14. OpenViking reachable                   | curl -s localhost:1933/api/v1/health        | "ok"
15. Skills installed                       | ls /home/agent/.claude-lab/leto/.claude/skills/ | 12 skills
16. Superpowers plugin                     | ls /home/agent/.claude/plugins/superpowers/.git | exists
17. CLAUDE.md exactly 4 @include           | grep -c '^@core' /home/agent/.claude-lab/leto/.claude/CLAUDE.md | 4
18. /etc/openviking/key permissions        | stat -c '%a %U:%G' /etc/openviking/key      | 640 root:openviking

If any FAIL: report what's broken and how to fix it. Verdict: READY / DEGRADED / DOWN.
```

---

## Recovery: Leto silent

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
- tail -100 of the consolidated cron log: /home/agent/.claude-lab/leto/.claude/logs/memory-cron.log

Run trim-hot.sh manually as the agent user and report the result.
```

---

## Daily self-diagnostic (full)

Send to Vesna once a day or after suspicious behaviour. She walks the whole stack.

```
Full system audit. Format as [Component | Status | Detail]:

1. Vesna service active                — systemctl is-active agent-vesna
2. user-gateway service active         — systemctl is-active agent-user-gateway
3. OpenViking active                   — systemctl is-active openviking
4. Vesna OAuth                         — test -f /root/.claude/.credentials.json
5. agent OAuth                         — test -f /home/agent/.claude/.credentials.json
6. Sudoers narrow file                 — visudo -cf /etc/sudoers.d/agent-narrow
7. Cron memory rotation                — cat /etc/cron.d/agent-memory-vesna /etc/cron.d/agent-memory-leto
8. HOT file size (each agent)          — wc -c <each>/core/hot/recent.md
9. WARM file size (each agent)         — wc -c <each>/core/warm/decisions.md
10. OpenViking responding              — curl -s localhost:1933/api/v1/health
11. Webhook token present              — test -s /root/vesna/webhook-token.txt
12. Telegram bot Vesna reachable       — getMe via api.telegram.org
13. Telegram bot Leto reachable        — same
14. AGENTS.md / TOOLS.md present       — for each agent: ls core/AGENTS.md core/TOOLS.md
15. /compact has been used recently    — grep "compact" in cron log last 7 days
16. learnings-engine episodes          — wc -l <each>/core/episodes.jsonl
17. Last graceful /reset               — ls -la <each>/core/hot/handoff.md
18. Secrets dir permissions            — stat /home/agent/secrets /root/secrets

Verdict: READY / DEGRADED / DOWN. If DEGRADED, list the exact fixes (commands).
```

---

## Compare against source of truth

If something in the workspace looks wrong, compare to the canonical templates in this repo:

```
The agent's CLAUDE.md feels off. Compare /home/agent/.claude-lab/leto/.claude/CLAUDE.md
with the canonical template at workspace-template/CLAUDE.md.tmpl in our repo on GitHub
(github.com/tsevmenko/telegram-claude-platform). Show me the diff and which sections drifted.
```

---

## Add a new client agent

```
Add a new agent named `coder` (model `opus`, role: senior backend engineer
focused on Python+asyncio). Bot token is below. Don't restart anything until
I confirm.

Bot token: [PASTE]
```

After Vesna patches the config, ask:

```
Looks good. Restart user-gateway and confirm `coder` is reachable. Then walk me through creating a topic for him in our forum group and wiring topic_routing.
```

---

## Regenerate webhook token

```
Regenerate the webhook token (someone may have it). Update both Vesna's and
the user-gateway's references, restart user-gateway, send me the new token.
Don't echo the old one anywhere.
```

---

## Bump pinned Superpowers SHA

```
Look up the latest commit on pcvelz/superpowers main. If different from
SUPERPOWERS_SHA in installer/PINS, propose the bump. Don't apply yet — show
me the diff between the two SHAs first.
```

---

# Recovery / debug-only prompts

These are also in `docs/RECOVERY.md` (kept there for emergency-only use, mirrored here for discoverability).

See `docs/RECOVERY.md` for: OAuth full reset, restore from backup, agent crash loop, OpenViking corrupt index.
