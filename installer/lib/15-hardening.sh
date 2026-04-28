#!/usr/bin/env bash
# Baseline VPS hardening — runs early so subsequent steps already have ufw +
# fail2ban + unattended-upgrades in place.
#
# Safe-by-default: this step installs and enables protective layers but
# DOES NOT lock the operator out of SSH. Aggressive SSH lockdown (no-root,
# no-password, custom port) is a separate Vesna admin command you trigger
# explicitly once you've confirmed key-based access works (see
# `vesna/skills/harden-vps/SKILL.md`).
#
# Skip with HARDENING_SKIP=1 if the host already has its own firewall stack
# (CrowdSec, internal corp firewall, etc.).

step_main() {
    if [[ "${HARDENING_SKIP:-0}" == "1" ]]; then
        log "HARDENING_SKIP=1 — skipping baseline hardening."
        return 0
    fi

    install_unattended_upgrades
    install_fail2ban
    install_ufw_default_deny
    sshd_conservative_hardening
    print_lockdown_hint

    ok "Baseline VPS hardening installed."
}

# --- unattended-upgrades — auto-apply security patches every night ---------
install_unattended_upgrades() {
    if dpkg -l unattended-upgrades 2>/dev/null | grep -q '^ii'; then
        log "unattended-upgrades already installed."
    else
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq unattended-upgrades \
            || { warn "unattended-upgrades install failed, continuing"; return 0; }
        log "unattended-upgrades installed."
    fi

    # Enable the periodic apt timer.
    cat >/etc/apt/apt.conf.d/20auto-upgrades <<'CFG'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
CFG

    # Tighten which origins get auto-applied — only Ubuntu Security.
    cat >/etc/apt/apt.conf.d/50unattended-upgrades-tcp <<'CFG'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
};
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
CFG
    log "unattended-upgrades configured for security-only auto-apply."
}

# --- fail2ban — drop SSH brute-forcers ------------------------------------
install_fail2ban() {
    if dpkg -l fail2ban 2>/dev/null | grep -q '^ii'; then
        log "fail2ban already installed."
    else
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq fail2ban \
            || { warn "fail2ban install failed, continuing"; return 0; }
        log "fail2ban installed."
    fi

    # Sane sshd jail: 5 strikes in 10 min → 1 hour ban. Whitelist the install
    # operator's current source IP automatically so we don't lock ourselves out
    # mid-install.
    local install_ip
    install_ip="$(echo "${SSH_CLIENT:-}" | awk '{print $1}')"
    [[ -z "$install_ip" ]] && install_ip="$(echo "${SSH_CONNECTION:-}" | awk '{print $1}')"

    local ignoreip="127.0.0.1/8 ::1"
    [[ -n "$install_ip" ]] && ignoreip="${ignoreip} ${install_ip}"

    cat >/etc/fail2ban/jail.d/tcp-platform.conf <<CFG
[DEFAULT]
ignoreip = ${ignoreip}
bantime = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port = ssh
backend = systemd
CFG

    systemctl enable --now fail2ban &>/dev/null || true
    systemctl restart fail2ban &>/dev/null || true
    log "fail2ban configured (sshd jail, 5/10min → 1h ban; whitelisted ${install_ip:-none})."
}

# --- ufw — host firewall, default-deny inbound ---------------------------
install_ufw_default_deny() {
    if ! command -v ufw &>/dev/null; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ufw \
            || { warn "ufw install failed, continuing"; return 0; }
    fi

    # Default rules: deny incoming, allow outgoing, allow loopback.
    ufw --force default deny incoming &>/dev/null || true
    ufw --force default allow outgoing &>/dev/null || true

    # SSH — keep open or operator gets locked out. (Tightening 22 happens
    # only via the Vesna `harden-vps` skill once Tailscale or another path
    # is verified.)
    ufw allow 22/tcp comment 'ssh — operator access' &>/dev/null || true

    # Webhook — allow ONLY if operator opted to expose it externally.
    # Default config now binds to 127.0.0.1, so this rule is dormant by
    # default. If a future install flips listen_host to 0.0.0.0, the firewall
    # is still default-deny — operator must `ufw allow 8080` explicitly.

    # OpenViking — bound to 127.0.0.1, never needs a firewall hole.

    ufw --force enable &>/dev/null || true
    log "ufw enabled: default-deny incoming, ssh allowed, all else blocked."
}

# --- sshd — conservative tightening that won't lock the operator out ------
sshd_conservative_hardening() {
    local cfg=/etc/ssh/sshd_config
    [[ -f "$cfg" ]] || { warn "sshd_config not found, skipping"; return 0; }
    cp -p "$cfg" "${cfg}.tcp-pre-hardening.bak" 2>/dev/null || true

    # Only set values that don't risk locking the operator out:
    # - MaxAuthTries 3 (slows brute force, doesn't break legit auth)
    # - ClientAliveInterval (kicks zombie sessions)
    # - LoginGraceTime 30s (tightens window for slowloris-style attempts)
    # - X11Forwarding no (server has no X)
    # We DELIBERATELY do NOT touch PermitRootLogin or PasswordAuthentication
    # at this layer — the Vesna `harden-vps` skill handles those once you
    # confirm key-based access works.
    apply_sshd_setting() {
        local key="$1" val="$2"
        if grep -qE "^[#[:space:]]*${key}[[:space:]]" "$cfg"; then
            sed -i -E "s|^[#[:space:]]*${key}[[:space:]].*|${key} ${val}|" "$cfg"
        else
            printf '\n%s %s\n' "$key" "$val" >>"$cfg"
        fi
    }
    apply_sshd_setting "MaxAuthTries" "3"
    apply_sshd_setting "LoginGraceTime" "30"
    apply_sshd_setting "ClientAliveInterval" "300"
    apply_sshd_setting "ClientAliveCountMax" "2"
    apply_sshd_setting "X11Forwarding" "no"
    apply_sshd_setting "PermitEmptyPasswords" "no"

    # Validate before reload — sshd refuses to start with bad config.
    if sshd -t 2>/dev/null; then
        systemctl reload sshd 2>/dev/null || systemctl reload ssh 2>/dev/null || true
        log "sshd hardened (MaxAuthTries=3, ClientAlive=300s, LoginGrace=30s)."
    else
        warn "sshd config validation failed — restoring backup."
        mv "${cfg}.tcp-pre-hardening.bak" "$cfg" 2>/dev/null || true
    fi
}

print_lockdown_hint() {
    log "Hardening hint: when ready to lock SSH down further, ask Vesna in"
    log "the Technical topic: 'Vesna, run the harden-vps skill.' She will"
    log "install Tailscale, close port 22 from the public internet, and"
    log "tighten sshd_config (PermitRootLogin no, PasswordAuth no)."
}
