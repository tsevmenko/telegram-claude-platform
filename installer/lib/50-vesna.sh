#!/usr/bin/env bash
# Deploy Vesna (root admin agent): workspace, venv, config, systemd unit.

readonly VESNA_DIR="/root/vesna"
readonly VESNA_WORKSPACE="/root/.claude-lab/vesna/.claude"
readonly VESNA_GLOBAL_CLAUDE="/root/.claude"

step_main() {
    install -d -m 0700 -o root -g root /root/secrets
    install -d -m 0755 -o root -g root "$VESNA_DIR" "${VESNA_DIR}/state" "${VESNA_DIR}/logs"

    deploy_gateway_code root "$VESNA_DIR"

    plant_workspace root "$VESNA_WORKSPACE" "vesna" \
        "VPS administrator agent" \
        "${OPERATOR_NAME:-operator}" "${OPERATOR_LANGUAGE:-English}" "${OPERATOR_TIMEZONE:-Europe/Kyiv}"

    install_global_claude_dir root "$VESNA_GLOBAL_CLAUDE" \
        "${VESNA_WORKSPACE}/hooks" \
        "${OPERATOR_NAME:-operator}" \
        "${TG_USER_ID:-0}" \
        "${OPERATOR_LANGUAGE:-English}" \
        "${OPERATOR_TIMEZONE:-Europe/Kyiv}" \
        "vesna"

    deploy_admin_skill

    render_vesna_config

    deploy_systemd_unit

    ok "Vesna deployed at ${VESNA_DIR}"
}

# Resolve operator profile values. Priority order:
#   1. Already-exported env var (set by step 40 collect_operator_profile)
#   2. Staged file from step 40 (/var/lib/agent-installer/secrets/operator-*)
#   3. Hard-coded sensible defaults
load_operator_profile() {
    local staging="${SECRETS_STAGING_DIR:-/var/lib/agent-installer/secrets}"
    OPERATOR_NAME="${OPERATOR_NAME:-$(cat "${staging}/operator-name"     2>/dev/null || echo operator)}"
    OPERATOR_LANGUAGE="${OPERATOR_LANGUAGE:-$(cat "${staging}/operator-language" 2>/dev/null || echo English)}"
    OPERATOR_TIMEZONE="${OPERATOR_TIMEZONE:-$(cat "${staging}/operator-timezone" 2>/dev/null || echo Europe/Kyiv)}"
    TG_USER_ID="${TG_USER_ID:-$(cat "${staging}/operator-user-id" 2>/dev/null || echo 0)}"

    # Voice transcription language is derived from the operator's language.
    # Whisper expects ISO 639-1 codes (en, uk, ru, de, fr, ...).
    case "${OPERATOR_LANGUAGE,,}" in
        ukrainian|українська) VOICE_LANGUAGE="uk" ;;
        russian|русский|русская) VOICE_LANGUAGE="ru" ;;
        english|en|英语) VOICE_LANGUAGE="en" ;;
        *) VOICE_LANGUAGE="${VOICE_LANGUAGE:-en}" ;;
    esac
}

deploy_gateway_code() {
    local owner="$1" home="$2"
    local src="${INSTALLER_ROOT}/gateway"
    [[ -d "$src" ]] || die "gateway/ source missing at ${src}"

    rsync -a --chown="${owner}:${owner}" --exclude '__pycache__' --exclude '.venv' \
        "${src}/" "${home}/source/"

    if [[ ! -x "${home}/.venv/bin/python" ]]; then
        as_user "$owner" python3 -m venv "${home}/.venv"
    fi
    as_user "$owner" "${home}/.venv/bin/pip" install --upgrade pip --quiet
    as_user "$owner" "${home}/.venv/bin/pip" install -e "${home}/source" --quiet
}

deploy_admin_skill() {
    install -d -m 0755 -o root -g root "${VESNA_WORKSPACE}/skills/admin-tools"
    cat >"${VESNA_WORKSPACE}/skills/admin-tools/SKILL.md" <<'SKILL'
---
name: admin-tools
description: "Admin commands: list/add/remove client agents, restart user-gateway, regenerate webhook token. ONLY for Vesna in the Technical topic."
user-invocable: true
---

# Admin Tools (Vesna only)

You manage the user-gateway's client agents and infrastructure.

## Available actions

- `list_agents` — read `/home/agent/gateway/config.json` and report agent names + statuses.
- `add_agent <name>` — guided dialogue: model? system reminder? bot token? Then patch `config.json`, create the workspace, **plant `core/.needs-onboarding` marker**, restart user-gateway, **tell operator to run `/onboarding` in the new agent's topic before any other work**.
- `remove_agent <name>` — confirm with operator → remove agent block from config + workspace → restart.
- `restart_user_gateway` — `sudo systemctl restart agent-user-gateway`.
- `regenerate_webhook_token` — generate new token, update both configs, send the new token to the operator (Technical topic only), restart user-gateway.
- `route_topic <topic_id> <agent>` — add a topic_id → agent_name mapping to the agent's `topic_routing` field, restart.
- `show_webhook_token` — read `/root/vesna/webhook-token.txt` and send to operator. NEVER paste it elsewhere.

## add_agent — required steps (in order)

A new agent is **not finished** until onboarding is queued. The operator must
not be told "added, work with them" without the onboarding step. Order:

1. Ask operator for: name, model (opus/sonnet), system_reminder (one sentence),
   bot token (from @BotFather).
2. Validate the bot token via `getMe`. Fail loud if Telegram rejects.
3. Stage token: `install -m 0600 -o agent -g agent <(echo "$TOKEN") /home/agent/secrets/<name>-bot-token`.
4. Create workspace from template: `rsync -a --chown=agent:agent /home/agent/gateway/source/workspace-template/ /home/agent/.claude-lab/<name>/.claude/`.
5. **Plant onboarding marker** so the new agent refuses real work until profile is captured:
   ```bash
   sudo -u agent touch /home/agent/.claude-lab/<name>/.claude/core/.needs-onboarding
   ```
6. Patch `/home/agent/gateway/config.json` — append agent block under `.agents.<name>` with bot_token_file, bot_username (from getMe), workspace, model, system_reminder, agent_names=[<name>], topic_routing={}, bypass_permissions=true.
7. Restart user-gateway: `sudo systemctl restart agent-user-gateway`.
8. **Tell the operator (final message), exact wording**:

   > ✓ <name> создан. Создай в forum-группе topic для него (если ещё нет),
   > пришли мне его topic_id командой "route topic <ID> <name>". После этого
   > **зайди в этот топик и напиши `/onboarding`** — без onboarding'а агент
   > не возьмётся за реальные задачи (он будет просить заполнить USER.md).

This sequence is non-negotiable — if operator skips step 8 and immediately
asks the new agent to do work, the agent will (correctly) refuse and ask
for onboarding. That refusal is the marker file working as intended.

## How to execute

Use the Bash tool with these commands:

```bash
# list_agents
jq '.agents | keys' /home/agent/gateway/config.json

# restart user-gateway (passwordless via /etc/sudoers.d/agent-narrow)
sudo systemctl restart agent-user-gateway

# regenerate_webhook_token
NEW_TOKEN=$(openssl rand -hex 32)
echo "$NEW_TOKEN" > /root/vesna/webhook-token.txt
chmod 600 /root/vesna/webhook-token.txt
# update user-gateway config
jq --arg t "$NEW_TOKEN" '.webhook.token_file = "/home/agent/secrets/webhook-token.txt"' \
   /home/agent/gateway/config.json > /tmp/cfg.json && mv /tmp/cfg.json /home/agent/gateway/config.json
echo "$NEW_TOKEN" > /home/agent/secrets/webhook-token.txt
chown agent:agent /home/agent/secrets/webhook-token.txt
sudo systemctl restart agent-user-gateway
```

## Safety

- Always confirm with the operator before destructive admin actions (remove_agent, regenerate_token, restart).
- Never expose secrets in cross-topic messages — webhook tokens, bot tokens, OpenViking keys live in the Technical topic only.
- Log every admin action to `/var/log/vesna-admin.log` with timestamp and operator request.
- **Never declare add_agent complete without the .needs-onboarding marker planted.** Steps 5 and 8 above are mandatory, not optional.
SKILL
    chmod 0644 "${VESNA_WORKSPACE}/skills/admin-tools/SKILL.md"
    chown -R root:root "${VESNA_WORKSPACE}/skills/admin-tools"
}

render_vesna_config() {
    local tmp; tmp="$(mktemp)"; TMPFILES+=("$tmp")
    local secrets_staging="${SECRETS_STAGING_DIR:-/var/lib/agent-installer/secrets}"
    local vesna_user
    vesna_user="$(cat "${secrets_staging}/vesna-bot-username" 2>/dev/null || echo unknown)"
    local fgid="${FORUM_GROUP_ID:-$(cat "${secrets_staging}/forum-group-id" 2>/dev/null || echo "")}"
    local fgid_or_empty
    [[ -n "$fgid" ]] && fgid_or_empty="$fgid" || fgid_or_empty="0"

    render_template "${INSTALLER_ROOT}/installer/templates/vesna-config.json.tmpl" "$tmp" \
        TG_USER_ID                 "${TG_USER_ID}" \
        FORUM_GROUP_ID_OR_EMPTY    "${fgid_or_empty}" \
        VOICE_LANGUAGE             "${VOICE_LANGUAGE}" \
        VESNA_BOT_USERNAME         "${vesna_user}" \
        TOPIC_ROUTING_VESNA        '{}'

    # Copy secret files into Vesna's tree.
    if [[ -f "${secrets_staging}/vesna-bot-token" ]]; then
        install -m 0600 -o root -g root "${secrets_staging}/vesna-bot-token" /root/secrets/vesna-bot-token
    fi
    if [[ -f "${secrets_staging}/groq-api-key" ]]; then
        install -m 0600 -o root -g root "${secrets_staging}/groq-api-key" /root/secrets/groq.key
    fi

    install -m 0640 -o root -g root "$tmp" "${VESNA_DIR}/config.json"
}

deploy_systemd_unit() {
    local tmp; tmp="$(mktemp)"; TMPFILES+=("$tmp")
    render_template "${INSTALLER_ROOT}/installer/templates/systemd/agent-vesna.service.tmpl" "$tmp"
    install -m 0644 -o root -g root "$tmp" /etc/systemd/system/agent-vesna.service
    systemctl daemon-reload
    systemctl enable agent-vesna.service --quiet
}

load_operator_profile