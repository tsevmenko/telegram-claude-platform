#!/usr/bin/env bash
# Final self-check: verify everything the installer was supposed to do.
# Prints a single human-readable report and exits 0 even if some checks fail —
# the operator gets a clear list of what to fix manually.

step_main() {
    local issues=0
    printf '\n%b═══════ Self-check Report ═══════%b\n' "$C_BOLD" "$C_NC"

    check "agent-vesna.service active"           "systemctl is-active --quiet agent-vesna"
    check "agent-user-gateway.service active"    "systemctl is-active --quiet agent-user-gateway"
    if systemctl list-unit-files openviking.service &>/dev/null; then
        check "openviking.service active"        "systemctl is-active --quiet openviking"
    else
        print_warn "openviking.service not deployed (binary missing) — L4 disabled"
    fi
    check "cron service running"                 "systemctl is-active --quiet cron"

    check "vesna cron installed"                 "test -f /etc/cron.d/agent-memory-vesna"
    check "leto cron installed"                  "test -f /etc/cron.d/agent-memory-leto"

    check "/root/.claude/.credentials.json present (run 'sudo -u root claude login' if missing)" \
        "test -f /root/.claude/.credentials.json"
    check "/home/agent/.claude/.credentials.json present (run 'sudo -u agent claude login' if missing)" \
        "test -f /home/agent/.claude/.credentials.json"

    check "Vesna workspace OK"                   "test -f /root/.claude-lab/vesna/.claude/CLAUDE.md"
    check "Leto workspace OK"                    "test -f /home/agent/.claude-lab/leto/.claude/CLAUDE.md"

    check "Vesna config present"                 "test -f /root/vesna/config.json"
    check "user-gateway config present"          "test -f /home/agent/gateway/config.json"

    check "sudoers narrow file installed"        "test -f /etc/sudoers.d/agent-narrow"
    check "sudoers passes visudo -cf"            "visudo -cf /etc/sudoers.d/agent-narrow"

    check "webhook token generated"              "test -s /root/vesna/webhook-token.txt"

    check_telegram "vesna" /root/secrets/vesna-bot-token
    check_telegram "leto"  /home/agent/secrets/leto-bot-token

    if command -v openviking &>/dev/null && systemctl is-active --quiet openviking; then
        check "openviking responds on 127.0.0.1:1933" \
            "curl -fsS --max-time 5 http://127.0.0.1:1933/api/v1/health"
    fi

    # --- baseline hardening (15-hardening.sh) -----------------------------
    if [[ "${HARDENING_SKIP:-0}" != "1" ]]; then
        check "ufw enabled (default-deny inbound)" \
            "ufw status 2>/dev/null | grep -q 'Status: active'"
        check "fail2ban running"                     "systemctl is-active --quiet fail2ban"
        check "unattended-upgrades enabled"          "test -f /etc/apt/apt.conf.d/20auto-upgrades"
        check "sshd MaxAuthTries hardened (=3)" \
            "grep -qE '^MaxAuthTries[[:space:]]+3' /etc/ssh/sshd_config"
        check "webhook bound to 127.0.0.1 (not public)" \
            "jq -e '.webhook.listen_host == \"127.0.0.1\"' /home/agent/gateway/config.json"
    fi

    printf '\n'
    if (( issues == 0 )); then
        ok "All checks passed."
    else
        warn "${issues} issue(s) require attention. See above."
    fi

    print_next_steps
}

check() {
    local label="$1" cmd="$2"
    if eval "$cmd" >/dev/null 2>&1; then
        printf '%b✓%b %s\n' "$C_GREEN" "$C_NC" "$label"
    else
        printf '%b✗%b %s\n' "$C_RED" "$C_NC" "$label"
        issues=$((issues + 1))
    fi
}

check_telegram() {
    local agent="$1" token_file="$2"
    if [[ ! -s "$token_file" ]]; then
        printf '%b!%b Telegram token for %s not configured (skipped)\n' "$C_YELLOW" "$C_NC" "$agent"
        return
    fi
    local token resp
    token="$(cat "$token_file")"
    resp="$(curl -fsS --max-time 5 "https://api.telegram.org/bot${token}/getMe" 2>/dev/null || true)"
    if [[ "$(echo "$resp" | jq -r '.ok // false' 2>/dev/null)" == "true" ]]; then
        local uname
        uname="$(echo "$resp" | jq -r '.result.username // ""')"
        printf '%b✓%b Telegram bot @%s (%s) reachable\n' "$C_GREEN" "$C_NC" "$uname" "$agent"
    else
        printf '%b✗%b Telegram bot for %s — getMe failed\n' "$C_RED" "$C_NC" "$agent"
        issues=$((issues + 1))
    fi
}

print_warn() {
    printf '%b!%b %s\n' "$C_YELLOW" "$C_NC" "$1"
}

print_next_steps() {
    printf '\n%bNext steps:%b\n' "$C_BOLD" "$C_NC"

    if [[ ! -f /root/.claude/.credentials.json ]]; then
        printf '  1. OAuth Vesna:  sudo -u root -i bash -lc '\''claude login'\''\n'
    fi
    if [[ ! -f /home/agent/.claude/.credentials.json ]]; then
        printf '  2. OAuth agent:  sudo -u agent -i bash -lc '\''claude login'\''\n'
    fi

    printf '  3. Start services: systemctl start agent-vesna agent-user-gateway\n'

    # Telegram-side step that breaks silently otherwise. Privacy Mode is cached
    # at the (bot, group) pair when the bot joins. Even if you flip Privacy off
    # in @BotFather, the cache persists. Promoting the bot to admin invalidates
    # the cache → bot reliably sees all messages.
    printf '\n%b⚠ Critical Telegram-side step:%b\n' "$C_YELLOW" "$C_NC"
    printf '   In your forum group, promote BOTH bots to Admin (Group Settings\n'
    printf '   → Administrators → Add Admin → @vesna_admin_bot, @<leto_bot>).\n'
    printf '   Minimum permission needed: "Manage messages" (Pin is nice).\n'
    printf '   Without this Telegram caches Privacy=on at the moment a bot\n'
    printf '   joined the group; even toggling Privacy off in @BotFather later\n'
    printf '   will NOT take effect — the bot only sees @mentions and ignores\n'
    printf '   plain messages in topics. Admin status bypasses the cache.\n'

    if [[ -s /root/vesna/webhook-token.txt ]]; then
        printf '\n%bWebhook token (save to your password manager):%b\n  ' "$C_BOLD" "$C_NC"
        cat /root/vesna/webhook-token.txt
    fi

    printf '\nOpen docs/CLIENT-TEST-INSTRUCTIONS.md and run the post-install tests in Telegram.\n'
}
