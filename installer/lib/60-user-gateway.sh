#!/usr/bin/env bash
# Deploy user-gateway: workspace for Leto, venv, multi-agent config, systemd unit.

readonly UG_DIR="/home/agent/gateway"
readonly LETO_WORKSPACE="/home/agent/.claude-lab/leto/.claude"
readonly AGENT_GLOBAL_CLAUDE="/home/agent/.claude"

step_main() {
    install -d -m 0700 -o agent -g agent /home/agent/secrets
    install -d -m 0755 -o agent -g agent "$UG_DIR" "${UG_DIR}/state" "${UG_DIR}/logs"
    install -d -m 0755 -o agent -g agent /home/agent/.claude-lab/shared/secrets

    deploy_user_gateway_code
    plant_workspace agent "$LETO_WORKSPACE" "leto" \
        "operator's primary work agent" \
        "${OPERATOR_NAME:-operator}" "${OPERATOR_LANGUAGE:-English}" "${OPERATOR_TIMEZONE:-Europe/Kyiv}"

    install_global_claude_dir agent "$AGENT_GLOBAL_CLAUDE" \
        "${LETO_WORKSPACE}/hooks" \
        "${OPERATOR_NAME:-operator}" \
        "${TG_USER_ID:-0}" \
        "${OPERATOR_LANGUAGE:-English}" \
        "${OPERATOR_TIMEZONE:-Europe/Kyiv}"

    render_user_gateway_config
    deploy_systemd_unit

    ok "user-gateway deployed at ${UG_DIR}"
}

deploy_user_gateway_code() {
    local src="${INSTALLER_ROOT}/gateway"
    [[ -d "$src" ]] || die "gateway/ source missing at ${src}"

    rsync -a --chown=agent:agent --exclude '__pycache__' --exclude '.venv' \
        "${src}/" "${UG_DIR}/source/"

    if [[ ! -x "${UG_DIR}/.venv/bin/python" ]]; then
        as_user agent python3 -m venv "${UG_DIR}/.venv"
    fi
    as_user agent "${UG_DIR}/.venv/bin/pip" install --upgrade pip --quiet
    as_user agent "${UG_DIR}/.venv/bin/pip" install -e "${UG_DIR}/source" --quiet
}

render_user_gateway_config() {
    local secrets_staging="${SECRETS_STAGING_DIR:-/var/lib/agent-installer/secrets}"
    local leto_user
    leto_user="$(cat "${secrets_staging}/leto-bot-username" 2>/dev/null || echo unknown)"
    local fgid="${FORUM_GROUP_ID:-$(cat "${secrets_staging}/forum-group-id" 2>/dev/null || echo "")}"
    local fgid_or_empty
    [[ -n "$fgid" ]] && fgid_or_empty="$fgid" || fgid_or_empty="0"

    local tmp; tmp="$(mktemp)"; TMPFILES+=("$tmp")
    render_template "${INSTALLER_ROOT}/installer/templates/user-gateway-config.json.tmpl" "$tmp" \
        TG_USER_ID                 "${TG_USER_ID}" \
        FORUM_GROUP_ID_OR_EMPTY    "${fgid_or_empty}" \
        VOICE_LANGUAGE             "${VOICE_LANGUAGE}" \
        LETO_BOT_USERNAME          "${leto_user}" \
        TOPIC_ROUTING_LETO         '{}'

    # Place secret files for the agent user.
    if [[ -f "${secrets_staging}/leto-bot-token" ]]; then
        install -m 0600 -o agent -g agent "${secrets_staging}/leto-bot-token" /home/agent/secrets/leto-bot-token
    fi
    if [[ -f "${secrets_staging}/groq-api-key" ]]; then
        install -m 0600 -o agent -g agent "${secrets_staging}/groq-api-key" /home/agent/secrets/groq.key
        # Shared secret accessible to skills.
        if [[ ! -e /home/agent/.claude-lab/shared/secrets/groq.key ]]; then
            ln -s /home/agent/secrets/groq.key /home/agent/.claude-lab/shared/secrets/groq.key
        fi
    fi

    install -m 0640 -o agent -g agent "$tmp" "${UG_DIR}/config.json"
}

deploy_systemd_unit() {
    local tmp; tmp="$(mktemp)"; TMPFILES+=("$tmp")
    render_template "${INSTALLER_ROOT}/installer/templates/systemd/agent-user-gateway.service.tmpl" "$tmp"
    install -m 0644 -o root -g root "$tmp" /etc/systemd/system/agent-user-gateway.service
    systemctl daemon-reload
    systemctl enable agent-user-gateway.service --quiet
}