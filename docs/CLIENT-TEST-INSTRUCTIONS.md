# Client Test Instructions

Post-install verification. Run each test in **Telegram**, not on the VPS. Total time ~45 minutes.

## Before you start

1. Confirm both bots are in your forum group.
2. **Promote both bots to admin** in the group (Group settings → Administrators → Add Admin → pick each bot). Default admin permissions are fine. This is required because Telegram caches Privacy Mode per-group at join time, and admin status is the cleanest way to bypass it.
3. In the **Technical** topic, send Vesna `/status`. She replies with a health summary.

If she doesn't, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Test 1 — Vesna basic functionality (3 min)

**Where:** Technical topic.
**Action:** `check server uptime and df -h`
**Expected:**
- Within 3-10s, live status updates show: `working — Xs ▸ bash uptime ▸ bash df -h`.
- Final reply contains real numbers from your VPS.
**Pass:** real data shown. **Fail:** error or empty.

## Test 2 — Leto basic functionality (3 min)

**Where:** Main topic.
**Action:** `hi, tell me about yourself in 2 sentences`
**Expected:** A short reply consistent with the configured system reminder.
**Pass:** sensible answer. **Fail:** silence or error.

## Test 3 — Live streaming UI (5 min)

**Where:** Main topic.
**Action:** `search the web for the date of the next solar eclipse, then write a 4-line poem about it`
**Expected:**
- One Telegram message keeps updating: thinking → WebSearch tool call → reasoning → final text.
- Poem renders cleanly (no raw markdown).
**Pass:** visible incremental updates roughly every 1-2 seconds.

## Test 4 — OOB commands (5 min)

**Where:** Main topic.

1. Send: `scan all files in /home and count sizes by type`.
2. After 5s (when the status shows `working — 5s ▸ bash find...`): send `/stop`.
   - Bot acknowledges within 2 seconds.
3. Send `/status` → bot replies `idle`.
4. Send `/reset` → bot confirms `session reset`.
5. Send `what do you remember about me?` → bot's reply mentions context bridged from COLD memory.

**Pass:** all four commands respond within 3 seconds.

## Test 5 — Voice (3 min)

**Where:** Main topic.
**Action:** Record a voice message — *"what's the capital of France?"*
**Expected:** Reply within 5-10 seconds: "Paris" (or longer answer per system reminder).
**Pass:** voice transcribed, bot responds correctly.

## Test 6 — Memory persistence (10 min — return next morning)

1. Tonight: have a 5-message conversation with Leto introducing yourself, stating preferences, asking a code question, correcting one of Leto's answers, thanking it.
2. Tomorrow morning, before sending anything: SSH in and run:
   ```bash
   sudo cat /home/agent/.claude-lab/leto/core/warm/decisions.md
   ```
   You should see Sonnet-compressed entries from last night.
3. In Telegram: `what did we discuss yesterday?` — Leto's reply references the compressed WARM content.

**Pass:** WARM has yesterday's entries; Leto recalls them.

## Test 7 — Security hooks (5 min)

**Action 1:** Leto, in Main topic — `run rm -rf /tmp/test`. Bot blocks with explanation.
**Action 2:** Leto — `edit the .env file in this project`. Blocked.
**Action 3:** Leto — `actually I meant Python, not Ruby` (after a brief language discussion).
- The correction is logged. Verify via Vesna in Technical topic: `show LEARNINGS for leto` (Vesna reads `/home/agent/.claude-lab/leto/core/LEARNINGS.md`).

## Test 8 — Vesna admin (5 min)

**Where:** Technical topic.

1. `/agents` → list of client agents (initially `leto`).
2. `add a new agent named coder with model opus, system reminder "you are a senior engineer", bot token <YOUR_TOKEN>`.
   - Vesna patches the config, restarts user-gateway, asks you to create a new topic and provide its ID.
3. Create a topic "Coder" in the group, copy its ID.
4. In Technical topic: `route topic <ID> to coder`.
5. In the new "Coder" topic, send `hi`. Coder responds.

## Test 9 — Webhook API (3 min)

**Where:** your laptop / another machine.

1. Get the webhook token: in Technical topic ask Vesna `show webhook token`.
2. From your shell:
   ```bash
   curl -X POST http://<YOUR_VPS_IP>:8080/hooks/agent \
     -H "Authorization: Bearer <TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"agent":"leto","chat_id":<MAIN_TOPIC_CHAT_ID>,"text":"external ping"}'
   ```
3. Leto in Telegram receives `external ping` and processes it as if you'd typed it.

**Token rotation:** in Technical topic, `regenerate webhook token`. Vesna sends a new token; the old one stops working.

## Test 10 — End-to-end smoke checklist

Daily quick-rerun:

- [ ] Vesna replies in Technical topic.
- [ ] Leto replies in Main topic.
- [ ] Voice message works.
- [ ] Live streaming visible.
- [ ] `/stop` interrupts.
- [ ] Cron last night left a `## YYYY-MM-DD (auto-compressed from HOT)` section in `core/warm/decisions.md`.
- [ ] OpenViking reachable: `sudo curl -s http://127.0.0.1:1933/api/v1/health`.
