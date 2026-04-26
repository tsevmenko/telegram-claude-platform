#!/usr/bin/env bash
# Deploy semantic memory server (loopback only).
#
# Strategy:
#   1. If the user already installed an `openviking` binary on PATH, prefer it.
#   2. Otherwise install the bundled `openviking-lite` (Python aiohttp + SQLite FTS5).
#   3. Either way, generate a shared API key and symlink it into Vesna /
#      agent secrets so the gateway can push to L4.

readonly OV_USER="openviking"
readonly OV_DATA_DIR="/var/lib/openviking"
readonly OV_LOG_DIR="/var/log/openviking"
readonly OV_KEY_FILE="/etc/openviking/key"
readonly OV_PORT="1933"
readonly OV_VENV="/opt/openviking-lite/.venv"

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

    # Generate API key once, share via symlinks.
    if [[ ! -f "$OV_KEY_FILE" ]]; then
        umask 077
        openssl rand -hex 32 >"$OV_KEY_FILE"
        chmod 0640 "$OV_KEY_FILE"
        chown root:"$OV_USER" "$OV_KEY_FILE"
        ok "Generated API key at ${OV_KEY_FILE}."
    else
        ok "API key already present at ${OV_KEY_FILE}."
    fi

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

    if command -v openviking &>/dev/null; then
        log "Found 'openviking' binary on PATH — using it."
        deploy_systemd_unit /usr/local/bin/openviking
        return 0
    fi

    log "No 'openviking' binary found — installing the bundled openviking-lite."
    install_lite
    deploy_systemd_unit "${OV_VENV}/bin/openviking-lite"
    ok "OpenViking-lite deployed (loopback 127.0.0.1:${OV_PORT})."
}

install_lite() {
    local src="${INSTALLER_ROOT}/openviking-lite"
    [[ -d "$src" ]] || die "openviking-lite source missing at ${src}"

    install -d -m 0755 -o "$OV_USER" -g "$OV_USER" /opt/openviking-lite
    rsync -a --chown="${OV_USER}:${OV_USER}" --exclude '__pycache__' --exclude '.venv' \
        "${src}/" /opt/openviking-lite/source/

    if [[ ! -x "${OV_VENV}/bin/python" ]]; then
        as_user "$OV_USER" python3 -m venv "$OV_VENV" 2>/dev/null \
            || sudo -u "$OV_USER" -- python3 -m venv "$OV_VENV"
    fi
    sudo -u "$OV_USER" -- "${OV_VENV}/bin/pip" install --upgrade pip --quiet
    sudo -u "$OV_USER" -- "${OV_VENV}/bin/pip" install -e /opt/openviking-lite/source --quiet
}

deploy_systemd_unit() {
    local exec="$1"
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
ExecStart=${exec} serve --listen 127.0.0.1:${OV_PORT} --data-dir ${OV_DATA_DIR} --key-file ${OV_KEY_FILE}
Restart=on-failure
RestartSec=5
StandardOutput=append:${OV_LOG_DIR}/openviking.log
StandardError=append:${OV_LOG_DIR}/openviking.log

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
