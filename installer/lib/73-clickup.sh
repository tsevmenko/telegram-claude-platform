#!/usr/bin/env bash
# Install community @nazruden/clickup-server (MIT) system-wide and register
# the MCP server for both root + agent users via `claude mcp add --scope user`.
# Wraps the binary in a small shell script that reads the Personal API
# Token from a chmod-600 secrets file (rather than inlining it in any
# config file).
#
# Why @nazruden over @taazkareem (the package we used in v0.4.4):
# taazkareem went paywall in v0.14 — the basic `list_spaces` call now
# returns a license-error and the server's `instructions` field contains
# a literal prompt-injection telling the AI to "guide the user to
# purchase links". That's manipulative and breaks our sole-writer ClickUp
# discipline. Tyrion caught both flags 2026-05-01.
# @nazruden/clickup-server is MIT-licensed, source-readable, exposes 31
# tools (create/get/update/delete across spaces, folders, lists, tasks,
# docs, doc pages, custom fields, views), no paywall, no injection.
#
# Why `claude mcp add` over the previous jq-merge into ~/.claude/mcp.json:
# we discovered (via Tyrion's diagnosis) that claude CLI 2.x reads MCP
# config from `~/.claude.json` (a single dot-file in $HOME), NOT from
# `~/.claude/mcp.json` (a path-with-subdir). The native `claude mcp add`
# subcommand writes to the right file and handles validation. Direct
# jq-merge into the wrong file silently failed to load any MCP server
# we registered through v0.4.3 / v0.4.4.

CLICKUP_DIR="${CLICKUP_DIR:-/opt/clickup-mcp-nazruden}"
WRAPPER="${CLICKUP_DIR}/run.sh"
TOKEN_FILE="${CLICKUP_TOKEN_FILE:-/home/agent/.claude-lab/shared/secrets/clickup.token}"

step_main() {
    install -d -m 0755 -o root -g root "$CLICKUP_DIR"

    if [[ ! -d "${CLICKUP_DIR}/node_modules/@nazruden/clickup-server" ]]; then
        log "Installing @nazruden/clickup-server"
        ( cd "$CLICKUP_DIR" && {
            [[ -f package.json ]] || npm init -y >/dev/null 2>&1
            npm install --silent @nazruden/clickup-server@latest 2>&1 | tail -3
          } )
    else
        log "@nazruden/clickup-server already installed at ${CLICKUP_DIR}"
    fi

    chmod -R a+rX "${CLICKUP_DIR}/node_modules"

    if [[ ! -f "$TOKEN_FILE" ]]; then
        warn "ClickUp API token missing at ${TOKEN_FILE}. Skipping MCP registration."
        warn "Stage the token (chmod 600 owner=agent) and re-run this step."
        return 0
    fi

    write_wrapper

    # Sanity smoke before registering — refuse to register a wrapper that
    # doesn't even pass syntax check, otherwise agents will fail silently
    # at session start.
    if ! bash -n "$WRAPPER"; then
        err "wrapper script $WRAPPER failed bash -n; aborting"
        return 1
    fi

    register_mcp_for_user root  "$WRAPPER"
    register_mcp_for_user agent "$WRAPPER"

    ok "ClickUp MCP (Nazruden) installed; wrapper at ${WRAPPER}; registered for root + agent."
}

write_wrapper() {
    cat >"$WRAPPER" <<EOR
#!/usr/bin/env bash
# Wrapper for @nazruden/clickup-server. Reads the ClickUp Personal API
# Token from a chmod-600 secrets file rather than inlining it in
# ~/.claude.json (which is readable by the owning user). Stdio MCP, runs
# fresh per-session.
set -e
CLICKUP_PERSONAL_TOKEN=\$(cat ${TOKEN_FILE})
export CLICKUP_PERSONAL_TOKEN
exec /usr/bin/node ${CLICKUP_DIR}/node_modules/@nazruden/clickup-server/dist/index.js "\$@"
EOR
    chmod 0755 "$WRAPPER"
    chown root:root "$WRAPPER"
}

# register_mcp_for_user USER COMMAND
# Use `claude mcp add --scope user` (the native subcommand) to register a
# stdio MCP server in the user's ~/.claude.json. Idempotent: removes any
# pre-existing entry with the same name first, then re-adds.
register_mcp_for_user() {
    local user="$1" cmd="$2"

    # `claude mcp` always operates on the invoking user's config. We use
    # sudo -u to switch user, with -H to set HOME so claude finds the
    # right dotfile.
    local sudo_pfx
    if [[ "$user" == "root" ]]; then
        sudo_pfx=""
    else
        sudo_pfx="sudo -u $user -H"
    fi

    # Idempotent remove. Ignore errors (entry might not exist yet).
    $sudo_pfx /usr/bin/claude mcp remove clickup -s user >/dev/null 2>&1 || true
    if $sudo_pfx /usr/bin/claude mcp add --scope user clickup "$cmd" >/dev/null 2>&1; then
        log "Registered clickup MCP for ${user}"
    else
        warn "claude mcp add failed for ${user}; check 'claude mcp list -s user' manually"
    fi
}
