#!/usr/bin/env bash
# Create the `agent` system user and write narrow passwordless sudoers.
# Sourced by install.sh — defines step_main().

readonly AGENT_USER="agent"
readonly AGENT_HOME="/home/agent"
readonly SUDOERS_FILE="/etc/sudoers.d/agent-narrow"

step_main() {
    ensure_agent_user
    install_sudoers
}

ensure_agent_user() {
    if id -u "$AGENT_USER" &>/dev/null; then
        ok "User '${AGENT_USER}' already exists."
    else
        useradd --create-home --shell /bin/bash "$AGENT_USER"
        ok "User '${AGENT_USER}' created."
    fi

    if [[ ! -d "$AGENT_HOME" ]]; then
        err "Home dir ${AGENT_HOME} missing after useradd."
        return 1
    fi
    chown "${AGENT_USER}:${AGENT_USER}" "$AGENT_HOME"
    chmod 0755 "$AGENT_HOME"
}

install_sudoers() {
    local tmp
    tmp="$(mktemp)"
    TMPFILES+=("$tmp")

    cat >"$tmp" <<SUDOERS
# Telegram Claude Platform — narrow passwordless sudo for '${AGENT_USER}'.
# Scope: systemctl + journalctl on agent-managed units; apt for self-repair.

Cmnd_Alias AGENT_SYSTEMCTL = \\
    /usr/bin/systemctl start agent-user-gateway, \\
    /usr/bin/systemctl stop agent-user-gateway, \\
    /usr/bin/systemctl restart agent-user-gateway, \\
    /usr/bin/systemctl status agent-user-gateway, \\
    /usr/bin/systemctl is-active agent-user-gateway, \\
    /usr/bin/systemctl reload agent-user-gateway, \\
    /usr/bin/systemctl enable agent-user-gateway, \\
    /usr/bin/systemctl disable agent-user-gateway, \\
    /usr/bin/systemctl start openviking, \\
    /usr/bin/systemctl stop openviking, \\
    /usr/bin/systemctl restart openviking, \\
    /usr/bin/systemctl status openviking, \\
    /usr/bin/systemctl is-active openviking, \\
    /usr/bin/systemctl daemon-reload

Cmnd_Alias AGENT_JOURNAL = \\
    /usr/bin/journalctl -u agent-user-gateway, \\
    /usr/bin/journalctl -u agent-user-gateway *, \\
    /usr/bin/journalctl -u openviking, \\
    /usr/bin/journalctl -u openviking *

Cmnd_Alias AGENT_APT = \\
    /usr/bin/apt, /usr/bin/apt *, \\
    /usr/bin/apt-get, /usr/bin/apt-get *

${AGENT_USER} ALL=(root) NOPASSWD: AGENT_SYSTEMCTL, AGENT_JOURNAL, AGENT_APT
SUDOERS

    if ! visudo -cf "$tmp" >/dev/null 2>&1; then
        err "Generated sudoers failed visudo -cf syntax check. Refusing to install."
        return 1
    fi

    install -m 0440 -o root -g root "$tmp" "$SUDOERS_FILE"
    ok "Sudoers installed at ${SUDOERS_FILE} (0440)."
}
