#!/usr/bin/env bash
# Install /etc/cron.d/ entries for memory rotation per agent.
#
# Per-agent cron block runs the 5 rotation scripts under the right user with
# CRON_TZ=UTC so the schedule is stable regardless of host TZ.

step_main() {
    install -d -m 0755 -o root -g root /etc/cron.d
    install_cron_for_agent root  /root/.claude-lab/vesna/.claude  vesna
    install_cron_for_agent agent /home/agent/.claude-lab/leto/.claude leto
    systemctl restart cron 2>/dev/null || true
    ok "Memory-rotation cron installed for vesna and leto."
}

install_cron_for_agent() {
    local user="$1" ws="$2" name="$3"
    local file="/etc/cron.d/agent-memory-${name}"
    local home; home="$(getent passwd "$user" | cut -d: -f6)"

    cat >"$file" <<CRON
# Telegram Claude Platform — memory rotation for ${name} (user=${user})
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
HOME=${home}
CRON_TZ=UTC
AGENT_WORKSPACE=${ws}

30 4 * * * ${user} ${ws}/scripts/rotate-warm.sh
0  5 * * * ${user} ${ws}/scripts/trim-hot.sh
0  6 * * * ${user} ${ws}/scripts/compress-warm.sh
30 6 * * * ${user} ${ws}/scripts/sync-l4.sh
0  21 * * * ${user} ${ws}/scripts/memory-rotate.sh
CRON
    chmod 0644 "$file"
    chown root:root "$file"
    log "wrote ${file}"
}
