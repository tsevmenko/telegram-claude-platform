#!/usr/bin/env bash
# Collect operator secrets (Telegram bot tokens, user_id, optional API keys)
# with retry/skip flow and Telegram getMe validation.
#
# Outputs:
#   /var/lib/agent-installer/secrets/   (chmod 700 root-only) — staging area
#     vesna-bot-token, vesna-bot-username
#     leto-bot-token,  leto-bot-username
#     operator-user-id
#     anthropic-api-key (optional)
#     groq-api-key      (optional)
#     forum-group-id    (optional)
#     missing.json      ({"vesna_bot": false, ...} — flags for self-check)

readonly SECRETS_STAGING_DIR="/var/lib/agent-installer/secrets"

step_main() {
    install -d -m 0700 -o root -g root "$SECRETS_STAGING_DIR"

    : >"${SECRETS_STAGING_DIR}/missing.json"
    printf '{}\n' >"${SECRETS_STAGING_DIR}/missing.json"

    if ! is_noninteractive; then
        cat <<'BRIEF'

Token collection.

You'll be asked for:
  1. Vesna bot token       (root admin agent)
  2. Leto bot token        (first user-level chat agent)
  3. Operator user_id      (your numeric Telegram id)
  4. Anthropic API key     (optional — skip to use OAuth via 'claude login')
  5. Groq API key          (optional — needed for voice transcription)
  6. Forum group id        (optional — can be configured later via Vesna)

Each Telegram bot token is verified via api.telegram.org/getMe.
If a token is invalid, you can retry or skip (with a warning).
Tokens are NOT echoed to the terminal.

BRIEF
    fi

    collect_bot_token "Vesna" "VESNA_BOT_TOKEN" "vesna"
    collect_bot_token "Leto"  "LETO_BOT_TOKEN"  "leto"
    collect_operator_id
    collect_optional_api_key "Anthropic API key (skip if using 'claude login' OAuth)" \
        "ANTHROPIC_API_KEY" "anthropic-api-key"
    collect_optional_api_key "Groq API key (for voice transcription)" \
        "GROQ_API_KEY" "groq-api-key"
    collect_optional_value "Forum group id (Telegram supergroup with topics)" \
        "FORUM_GROUP_ID" "forum-group-id" "validate_int_or_neg"

    ok "Secrets staged at ${SECRETS_STAGING_DIR}"
}

# ----------------------------------------------------------------------------

# collect_bot_token PRETTY_NAME ENV_NAME OUTPUT_PREFIX
# Prompts (or reads from env), validates format, calls getMe to verify token.
# Saves to ${SECRETS_STAGING_DIR}/<prefix>-bot-token, also writes -bot-username.
# Retry/skip loop.
collect_bot_token() {
    local pretty="$1" env_name="$2" prefix="$3"
    local token="" username=""

    while true; do
        prompt_or_env token "$env_name" "${pretty} bot token" "" --secret

        if [[ -z "$token" ]]; then
            confirm_skip "${pretty} bot" "the ${pretty} agent will not start" "${prefix}_bot" || continue
            return 0
        fi

        if ! validate_tg_token "$token"; then
            warn "Invalid format. Expected '<digits>:<30+ chars>'."
            if prompt_retry_or_skip; then
                token=""
                continue
            else
                confirm_skip "${pretty} bot" "the ${pretty} agent will not start" "${prefix}_bot" || continue
                return 0
            fi
        fi

        local resp
        resp="$(tg_get_me "$token")"
        if [[ "$(echo "$resp" | jq -r '.ok // false' 2>/dev/null)" == "true" ]]; then
            username="$(echo "$resp" | jq -r '.result.username // ""')"
            ok "${pretty} bot verified: @${username:-unknown}"
            install -m 0600 -o root -g root /dev/stdin "${SECRETS_STAGING_DIR}/${prefix}-bot-token" <<<"$token"
            install -m 0644 -o root -g root /dev/stdin "${SECRETS_STAGING_DIR}/${prefix}-bot-username" <<<"$username"
            return 0
        else
            warn "Telegram rejected the token (getMe failed)."
            if prompt_retry_or_skip; then
                token=""
                continue
            else
                confirm_skip "${pretty} bot" "the ${pretty} agent will not start" "${prefix}_bot" || continue
                return 0
            fi
        fi
    done
}

collect_operator_id() {
    local user_id=""
    while true; do
        prompt_or_env user_id "OPERATOR_TG_USER_ID" "Operator Telegram user_id (numeric)"

        if [[ -z "$user_id" ]]; then
            confirm_skip "operator user_id" \
                "bots will not have an allowlist (anyone can talk to them — strongly discouraged)" \
                "operator_id" || continue
            return 0
        fi

        if [[ ! "$user_id" =~ ^[0-9]+$ ]]; then
            warn "user_id must be a positive integer."
            if prompt_retry_or_skip; then
                user_id=""
                continue
            else
                return 0
            fi
        fi

        ok "Operator user_id stored."
        install -m 0644 -o root -g root /dev/stdin "${SECRETS_STAGING_DIR}/operator-user-id" <<<"$user_id"
        return 0
    done
}

collect_optional_api_key() {
    local prompt_text="$1" env_name="$2" filename="$3"
    local val=""
    prompt_or_env val "$env_name" "$prompt_text" "" --secret

    if [[ -z "$val" ]]; then
        log "${env_name} skipped (optional)."
        mark_missing "$filename"
        return 0
    fi

    install -m 0600 -o root -g root /dev/stdin "${SECRETS_STAGING_DIR}/${filename}" <<<"$val"
    ok "${env_name} stored."
}

collect_optional_value() {
    local prompt_text="$1" env_name="$2" filename="$3" validator="${4:-}"
    local val=""
    prompt_or_env val "$env_name" "$prompt_text"

    if [[ -z "$val" ]]; then
        log "${env_name} skipped (optional)."
        mark_missing "$filename"
        return 0
    fi

    if [[ -n "$validator" ]]; then
        if ! "$validator" "$val"; then
            warn "Invalid value for ${env_name}; skipping."
            mark_missing "$filename"
            return 0
        fi
    fi

    install -m 0644 -o root -g root /dev/stdin "${SECRETS_STAGING_DIR}/${filename}" <<<"$val"
    ok "${env_name} stored."
}

# Validators

validate_int_or_neg() {
    local v="$1"
    [[ "$v" =~ ^-?[0-9]+$ ]]
}

# Helpers

prompt_retry_or_skip() {
    if is_noninteractive; then
        return 1
    fi
    local choice
    read -r -p "Retry or skip? [r/s]: " choice </dev/tty
    case "$choice" in
        r|R|retry) return 0 ;;
        *) return 1 ;;
    esac
}

confirm_skip() {
    local what="$1" consequence="$2" missing_key="$3"
    if is_noninteractive; then
        warn "Non-interactive: ${what} skipped (${consequence})."
        mark_missing "$missing_key"
        return 0
    fi
    local choice
    read -r -p "Skip ${what}? Without it, ${consequence}. [y/N]: " choice </dev/tty
    case "$choice" in
        y|Y|yes) mark_missing "$missing_key"; return 0 ;;
        *) return 1 ;;
    esac
}

mark_missing() {
    local key="$1"
    local tmp; tmp="$(mktemp)"; TMPFILES+=("$tmp")
    jq --arg k "$key" '. + {($k): true}' "${SECRETS_STAGING_DIR}/missing.json" >"$tmp"
    mv "$tmp" "${SECRETS_STAGING_DIR}/missing.json"
}
