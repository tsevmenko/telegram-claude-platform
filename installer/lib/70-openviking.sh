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
    install -d -m 0755 -o root  -g root  /root/.claude-lab/shared
    install -d -m 0755 -o root  -g root  /root/.claude-lab/shared/secrets
    install -d -m 0755 -o agent -g agent /home/agent/.claude-lab/shared/secrets

    # Copy the key (not symlink!) so each user can read it as their own.
    # The canonical key at /etc/openviking/key is 0640 root:openviking — only
    # the openviking service user can read it via group. Agents (root, agent)
    # are not in that group, and a symlink would require them to read the
    # restricted target. Per-user copies sidestep this and keep ownership
    # POSIX-clean. If Vesna regenerates the key, her admin tool must
    # re-distribute these copies.
    install -m 0600 -o root  -g root  "$OV_KEY_FILE" /root/secrets/openviking.key
    install -m 0600 -o root  -g root  "$OV_KEY_FILE" /root/.claude-lab/shared/secrets/openviking.key
    install -m 0600 -o agent -g agent "$OV_KEY_FILE" /home/agent/secrets/openviking.key
    install -m 0600 -o agent -g agent "$OV_KEY_FILE" /home/agent/.claude-lab/shared/secrets/openviking.key

    # Stage the OpenAI key (collected in step 40) so openviking-lite can
    # generate semantic embeddings.
    local secrets_staging="${SECRETS_STAGING_DIR:-/var/lib/agent-installer/secrets}"
    if [[ -f "${secrets_staging}/openai-api-key" ]]; then
        install -m 0640 -o root -g "$OV_USER" \
            "${secrets_staging}/openai-api-key" \
            /etc/openviking/openai.key
        ok "OpenAI API key staged → /etc/openviking/openai.key (semantic embeddings on)."
    else
        log "No OpenAI key — running L4 with FTS5 only (no embeddings)."
    fi

    if command -v openviking &>/dev/null; then
        log "Found 'openviking' binary on PATH — using it."
        deploy_systemd_unit /usr/local/bin/openviking
        return 0
    fi

    log "No 'openviking' binary found — installing the bundled openviking-lite."
    install_lite
    deploy_systemd_unit "${OV_VENV}/bin/openviking-lite"
    register_mcp_for root  /root/.claude/mcp.json
    register_mcp_for agent /home/agent/.claude/mcp.json
    ok "OpenViking-lite deployed (loopback 127.0.0.1:${OV_PORT})."
}

# register_mcp_for USER MCP_JSON_PATH
# Adds an "openviking" MCP server entry pointing at openviking-lite-mcp.
register_mcp_for() {
    local user="$1" mcp_path="$2"
    local mcp_dir; mcp_dir="$(dirname "$mcp_path")"
    install -d -m 0700 -o "$user" -g "$user" "$mcp_dir"

    local exec="${OV_VENV}/bin/openviking-lite-mcp"
    [[ -x "$exec" ]] || { warn "MCP exec missing at ${exec}"; return 0; }

    local tmp; tmp="$(mktemp)"; TMPFILES+=("$tmp")
    if [[ -f "$mcp_path" ]]; then
        if jq --arg cmd "$exec" --arg key "$OV_KEY_FILE" \
              '.mcpServers = ((.mcpServers // {}) +
                  {"openviking": {"command": $cmd, "args": [],
                                  "env": {"OV_HOST": "http://127.0.0.1:1933",
                                          "OV_KEY_FILE": $key,
                                          "OV_ACCOUNT": "default"}}})' \
              "$mcp_path" >"$tmp" 2>/dev/null && [[ -s "$tmp" ]]; then
            install -m 0644 -o "$user" -g "$user" "$tmp" "$mcp_path"
            log "Registered openviking MCP for ${user} → ${mcp_path}"
        else
            warn "jq merge of ${mcp_path} failed; leaving file alone."
        fi
    else
        if jq -n --arg cmd "$exec" --arg key "$OV_KEY_FILE" \
                '{mcpServers: {openviking: {command: $cmd, args: [],
                                            env: {OV_HOST: "http://127.0.0.1:1933",
                                                  OV_KEY_FILE: $key,
                                                  OV_ACCOUNT: "default"}}}}' >"$tmp" 2>/dev/null \
                && [[ -s "$tmp" ]]; then
            install -m 0644 -o "$user" -g "$user" "$tmp" "$mcp_path"
            log "Created MCP config for ${user} at ${mcp_path}"
        fi
    fi
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
    # The openviking system user has no $HOME (--no-create-home), so pip cache
    # would warn on every install. --no-cache-dir suppresses that and is
    # appropriate for a one-shot install.
    sudo -u "$OV_USER" -- "${OV_VENV}/bin/pip" install --upgrade pip --quiet --no-cache-dir
    sudo -u "$OV_USER" -- "${OV_VENV}/bin/pip" install -e /opt/openviking-lite/source --quiet --no-cache-dir
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
StandardOutput=journal
StandardError=journal
SyslogIdentifier=openviking

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
