#!/usr/bin/env bash
# Deploy OpenViking semantic memory server (loopback only) as a systemd unit.
#
# OpenViking is the L4 semantic search backend. It's bound to 127.0.0.1:1933
# (loopback only — never exposed). API key is generated here and shared with
# both Vesna and the user-gateway via secrets symlinks.
#
# This is a Phase-10 stub: spins up a systemd unit that runs whatever
# ``OV_BINARY`` resolves to (default ``/usr/local/bin/openviking``). If the
# binary isn't present, the step warns and skips — the gateway will simply
# disable L4 push at runtime when the API key file is missing.

readonly OV_USER="openviking"
readonly OV_DATA_DIR="/var/lib/openviking"
readonly OV_LOG_DIR="/var/log/openviking"
readonly OV_KEY_FILE="/etc/openviking/key"
readonly OV_PORT="1933"

step_main() {
    if id -u "$OV_USER" &>/dev/null; then
        ok "User '${OV_USER}' already exists."
    else
        useradd --system --no-create-home --shell /usr/sbin/nologin "$OV_USER"
        ok "User '${OV_USER}' created."
    fi

    install -d -m 0755 -o "$OV_USER" -g "$OV_USER" "$OV_DATA_DIR"
    install -d -m 0755 -o "$OV_USER" -g "$OV_USER" "$OV_LOG_DIR"
    install -d -m 0750 -o root -g "$OV_USER" /etc/openviking

    # Generate API key once. Shared by Vesna + user-gateway via symlinks.
    if [[ ! -f "$OV_KEY_FILE" ]]; then
        umask 077
        openssl rand -hex 32 >"$OV_KEY_FILE"
        chmod 0640 "$OV_KEY_FILE"
        chown root:"$OV_USER" "$OV_KEY_FILE"
        ok "Generated OpenViking API key at ${OV_KEY_FILE}."
    else
        ok "OpenViking API key already present at ${OV_KEY_FILE}."
    fi

    # Symlink into Vesna and agent secrets directories.
    install -d -m 0700 -o root  -g root  /root/secrets
    install -d -m 0700 -o agent -g agent /home/agent/secrets
    install -d -m 0755 -o agent -g agent /home/agent/.claude-lab/shared/secrets

    for dest in /root/secrets/openviking.key \
                /home/agent/secrets/openviking.key \
                /home/agent/.claude-lab/shared/secrets/openviking.key; do
        if [[ ! -e "$dest" ]]; then
            ln -s "$OV_KEY_FILE" "$dest"
        fi
    done

    if ! command -v openviking &>/dev/null; then
        warn "openviking binary not on PATH — installer skips service deploy."
        warn "Install OpenViking manually, then re-run this step."
        warn "Without OpenViking, L4 semantic memory is disabled (everything else still works)."
        return 0
    fi

    deploy_systemd_unit
    ok "OpenViking deployed (loopback 127.0.0.1:${OV_PORT})."
}

deploy_systemd_unit() {
    local unit=/etc/systemd/system/openviking.service
    cat >"$unit" <<UNIT
[Unit]
Description=OpenViking semantic memory server (L4)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${OV_USER}
Group=${OV_USER}
Environment=OV_KEY_FILE=${OV_KEY_FILE}
Environment=OV_DATA_DIR=${OV_DATA_DIR}
Environment=OV_LISTEN=127.0.0.1:${OV_PORT}
ExecStart=/usr/local/bin/openviking serve --listen 127.0.0.1:${OV_PORT} --data-dir ${OV_DATA_DIR}
Restart=on-failure
RestartSec=5
StandardOutput=append:${OV_LOG_DIR}/openviking.log
StandardError=append:${OV_LOG_DIR}/openviking.log

# Hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=${OV_DATA_DIR} ${OV_LOG_DIR}

[Install]
WantedBy=multi-user.target
UNIT
    chmod 0644 "$unit"
    systemctl daemon-reload
    systemctl enable openviking.service --quiet
    if ! systemctl start openviking.service 2>/dev/null; then
        warn "openviking.service failed to start — check 'journalctl -u openviking'."
    fi
}
