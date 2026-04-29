#!/usr/bin/env bash
# Shared helpers sourced by install.sh BEFORE any step runs.
# Provides template rendering, ownership helpers, install_as_user, etc.

# render_template SRC DST KEY1 VAL1 [KEY2 VAL2 ...]
# Renders {{KEY}} placeholders to VAL in SRC, writes to DST. Uses python for
# safe literal replace (avoids regex escaping pitfalls in sed).
render_template() {
    local src="$1" dst="$2"; shift 2
    [[ -f "$src" ]] || { err "Template not found: $src"; return 1; }

    local tmp; tmp="$(mktemp)"
    TMPFILES+=("$tmp")
    cp "$src" "$tmp"

    while (( $# >= 2 )); do
        local key="$1" val="$2"; shift 2
        python3 - "$tmp" "{{${key}}}" "$val" <<'PY'
import sys, pathlib
path, needle, repl = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path(path)
p.write_text(p.read_text().replace(needle, repl))
PY
    done

    mv "$tmp" "$dst"
}

# install_as_user SRC DST OWNER [MODE]
# Copies SRC to DST owned by OWNER:OWNER, mode defaults to 0600.
install_as_user() {
    local src="$1" dst="$2" owner="$3" mode="${4:-0600}"
    install -m "$mode" -o "$owner" -g "$owner" "$src" "$dst"
}

# write_as_user SRC DST [MODE]
# Like install_as_user but uses the AGENT_USER if set, else root. For workspace
# files where the parent dir might not exist yet (creates it).
write_as_user() {
    local src="$1" dst="$2" mode="${3:-0644}"
    local owner="${OWNER_USER:-root}"
    local dst_dir; dst_dir="$(dirname "$dst")"
    if [[ ! -d "$dst_dir" ]]; then
        install -d -m 0755 -o "$owner" -g "$owner" "$dst_dir"
    fi
    install -o "$owner" -g "$owner" -m "$mode" "$src" "$dst"
}

# NOTE: fix_owner is defined in 00-preflight.sh with signature
# `fix_owner USER:GROUP PATH`. The OLD signature `fix_owner PATH OWNER` used
# to live here; the duplicate definition silently overrode the supply-chain
# helper and caused argument-order bugs when 00-preflight wasn't source-loaded
# yet. Use the canonical implementation only.

# as_user USER -- CMD ARGS ...
# Run CMD as USER with their HOME and a sensible cwd.
as_user() {
    local target="$1"; shift
    local home; home="$(getent passwd "$target" | cut -d: -f6)"
    sudo -u "$target" -H -- env -C "${home:-/}" "$@"
}

# is_noninteractive
# True if INSTALLER_NONINTERACTIVE=1 explicitly OR there's no controlling tty.
# We deliberately do NOT check `! -t 0` (stdin) because under `curl | bash`
# stdin is the curl pipe — not a tty — yet the operator is still sitting at
# a terminal that we can read from via /dev/tty. All interactive `read`
# calls in this codebase already redirect from /dev/tty for that reason.
is_noninteractive() {
    [[ "${INSTALLER_NONINTERACTIVE:-0}" == "1" ]] || [[ ! -r /dev/tty ]]
}

# prompt_or_env VAR ENV_NAME PROMPT [DEFAULT] [--secret]
# Reads VAR from ENV_NAME if set; otherwise prompts (unless non-interactive).
# shellcheck disable=SC2034
prompt_or_env() {
    local -n out_ref="$1"
    local env_name="$2"
    local prompt_text="$3"
    local default="${4:-}"
    local secret="${5:-}"
    local env_val="${!env_name:-}"

    if [[ -n "$env_val" ]]; then
        out_ref="$env_val"
        return 0
    fi

    if is_noninteractive; then
        if [[ -n "$default" ]]; then
            out_ref="$default"
            return 0
        fi
        die "Non-interactive mode: required value ${env_name} is missing (prompt: ${prompt_text})."
    fi

    local answer=""
    if [[ -n "$default" ]]; then
        prompt_text="${prompt_text} [${default}]"
    fi
    prompt_text="${prompt_text}: "

    if [[ "$secret" == "--secret" ]]; then
        read -r -s -p "$prompt_text" answer </dev/tty
        echo ""
    else
        read -r -p "$prompt_text" answer </dev/tty
    fi

    if [[ -z "$answer" && -n "$default" ]]; then
        answer="$default"
    fi
    out_ref="$answer"
}

# validate_tg_token TOKEN
# Returns 0 if format matches Telegram bot token regex.
validate_tg_token() {
    local token="$1"
    [[ "$token" =~ ^[0-9]{6,}:[A-Za-z0-9_-]{30,}$ ]]
}

# tg_get_me TOKEN
# Returns Telegram getMe response (JSON) or empty on failure.
tg_get_me() {
    local token="$1"
    curl "${CURL_OPTS[@]}" "https://api.telegram.org/bot${token}/getMe" 2>/dev/null || true
}

# plant_workspace OWNER WORKSPACE_DIR AGENT_NAME AGENT_ROLE OPERATOR_NAME LANGUAGE TIMEZONE
# Renders templates from workspace-template/ into WORKSPACE_DIR.
# v0.4.0+: WORKSPACE_DIR is `${parent}/${agent}` (no `.claude` suffix). The
# previous layout `${parent}/${agent}/.claude` triggered claude CLI 2.x's
# path-sensitivity classifier — see 60-user-gateway.sh for full context.
# Copies skills/, scripts/, hooks/ as-is and fixes ownership.
plant_workspace() {
    local owner="$1" ws="$2" agent="$3" role="$4" op_name="$5" lang="$6" tz="$7"

    install -d -m 0755 -o "$owner" -g "$owner" \
        "$ws" \
        "${ws}/core" \
        "${ws}/core/warm" \
        "${ws}/core/hot" \
        "${ws}/core/archive" \
        "${ws}/tools" \
        "${ws}/skills" \
        "${ws}/scripts" \
        "${ws}/hooks" \
        "${ws}/logs" \
        "${ws}/logs/activity"

    local tpl_root="${INSTALLER_ROOT}/workspace-template"

    # CLAUDE.md
    local tmp; tmp="$(mktemp)"; TMPFILES+=("$tmp")
    render_template "${tpl_root}/CLAUDE.md.tmpl" "$tmp" \
        AGENT_NAME              "${agent^}" \
        AGENT_ROLE              "$role" \
        AGENT_ROLE_DESCRIPTION  "$role" \
        OPERATOR_ADDRESS        "$op_name" \
        LANGUAGE                "$lang"
    install -m 0644 -o "$owner" -g "$owner" "$tmp" "${ws}/CLAUDE.md"

    tmp="$(mktemp)"; TMPFILES+=("$tmp")
    render_template "${tpl_root}/core/USER.md.tmpl" "$tmp" \
        OPERATOR_NAME    "$op_name" \
        OPERATOR_ADDRESS "$op_name" \
        TIMEZONE         "$tz" \
        LANGUAGE         "$lang" \
        OPERATOR_BIO     "(edit core/USER.md to fill this in)" \
        NEED_1           "primary work tasks" \
        NEED_2           "context-aware reminders" \
        NEED_3           "knowledge of past decisions"
    install -m 0644 -o "$owner" -g "$owner" "$tmp" "${ws}/core/USER.md"

    tmp="$(mktemp)"; TMPFILES+=("$tmp")
    render_template "${tpl_root}/core/rules.md.tmpl" "$tmp"
    install -m 0644 -o "$owner" -g "$owner" "$tmp" "${ws}/core/rules.md"

    # Static seed files (idempotent: only write if missing).
    for src_rel in \
        core/MEMORY.md core/LEARNINGS.md \
        core/AGENTS.md \
        core/warm/decisions.md core/hot/recent.md core/hot/handoff.md \
        tools/TOOLS.md
    do
        local src="${tpl_root}/${src_rel}"
        local dst="${ws}/${src_rel}"
        if [[ ! -f "$dst" && -f "$src" ]]; then
            install -m 0644 -o "$owner" -g "$owner" "$src" "$dst"
        fi
    done

    # Copy hooks, scripts, skills as trees (rsync to preserve perms).
    rsync -a --chown="${owner}:${owner}" "${tpl_root}/hooks/"   "${ws}/hooks/"
    rsync -a --chown="${owner}:${owner}" "${tpl_root}/scripts/" "${ws}/scripts/"
    rsync -a --chown="${owner}:${owner}" "${tpl_root}/skills/"  "${ws}/skills/"

    # Ensure executable bits stuck.
    find "${ws}/hooks"   -type f -name '*.sh' -exec chmod 0755 {} \;
    find "${ws}/scripts" -type f -name '*.sh' -exec chmod 0755 {} \;
    find "${ws}/skills"  -type f \( -name '*.sh' -o -name '*.py' \) -exec chmod 0755 {} \;

    fix_owner "${owner}:${owner}" "$ws"
}

# install_global_claude_dir OWNER GLOBAL_DIR HOOKS_DIR OPERATOR_NAME TG_USER_ID LANGUAGE TIMEZONE [SETTINGS_PROFILE]
# Plants ~/.claude/ — global CLAUDE.md, settings.json with hooks, mcp.json.
#
# SETTINGS_PROFILE selects which settings.json template:
#   "vesna" → vesna-settings.json.tmpl  (sysadmin allowlist; ~150 entries)
#   default → settings.json.tmpl        (compact dev allowlist for client agents)
#
# Why split: Vesna runs as root with bypass_permissions=false (Anthropic
# disallows --dangerously-skip-permissions for uid=0). Without a wide
# allowlist she has to ask the operator on every routine sysadmin command.
# Client agents (Leto + future user-agents) run with bypass_permissions=true
# and don't consult permissions.allow at all in the common case.
install_global_claude_dir() {
    local owner="$1" cdir="$2" hooks_dir="$3" op_name="$4" tg_uid="$5" lang="$6" tz="$7"
    local profile="${8:-default}"

    install -d -m 0700 -o "$owner" -g "$owner" "$cdir"
    install -d -m 0755 -o "$owner" -g "$owner" "${cdir}/plugins"

    local tpl_root="${INSTALLER_ROOT}/installer/templates/claude"

    # global CLAUDE.md
    if [[ ! -f "${cdir}/CLAUDE.md" ]]; then
        local tmp; tmp="$(mktemp)"; TMPFILES+=("$tmp")
        render_template "${tpl_root}/global-CLAUDE.md.tmpl" "$tmp" \
            USER          "$owner" \
            OPERATOR_NAME "$op_name" \
            TG_USER_ID    "$tg_uid" \
            LANGUAGE      "$lang" \
            TIMEZONE      "$tz"
        install -m 0644 -o "$owner" -g "$owner" "$tmp" "${cdir}/CLAUDE.md"
    fi

    # settings.json — pick template by profile.
    if [[ ! -f "${cdir}/settings.json" ]]; then
        local settings_src
        case "$profile" in
            vesna)   settings_src="${tpl_root}/vesna-settings.json.tmpl" ;;
            *)       settings_src="${tpl_root}/settings.json.tmpl" ;;
        esac
        local tmp; tmp="$(mktemp)"; TMPFILES+=("$tmp")
        render_template "$settings_src" "$tmp" \
            HOOKS_DIR "$hooks_dir"
        install -m 0644 -o "$owner" -g "$owner" "$tmp" "${cdir}/settings.json"
    fi

    # Empty mcp.json
    if [[ ! -f "${cdir}/mcp.json" ]]; then
        printf '{"mcpServers": {}}\n' >"/tmp/mcp.json.$$"
        install -m 0644 -o "$owner" -g "$owner" "/tmp/mcp.json.$$" "${cdir}/mcp.json"
        rm -f "/tmp/mcp.json.$$"
    fi
}
