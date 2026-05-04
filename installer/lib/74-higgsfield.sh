#!/usr/bin/env bash
# Register Higgsfield as an HTTP MCP server (https://mcp.higgsfield.ai/mcp)
# for both root + agent users. Higgsfield uses OAuth 2.1 with PKCE +
# Dynamic Client Registration — no API token, no allowlist surprise.
#
# This step ONLY registers the connector. The OAuth flow itself must be
# completed interactively by the operator after install:
#
#   ssh -L 8181:localhost:8181 -i <key> root@<vps> -t /usr/bin/claude
#   # inside claude session: /mcp → Higgsfield → Authenticate
#   # then: ssh -L 8181:localhost:8181 ... -t 'sudo -u agent /usr/bin/claude'
#   # repeat /mcp auth flow as agent user
#
# Both authenticate against the same Higgsfield account (operator's).
# Refresh-tokens are stored in each user's ~/.claude.json and auto-renew.

HIGGSFIELD_URL="${HIGGSFIELD_URL:-https://mcp.higgsfield.ai/mcp}"
HIGGSFIELD_CALLBACK_PORT="${HIGGSFIELD_CALLBACK_PORT:-8181}"

step_main() {
    register_mcp_for_user root
    register_mcp_for_user agent

    ok "Higgsfield MCP registered for root + agent (status: needs OAuth)."
    log "Operator must complete OAuth flow interactively per user — see 74-higgsfield.sh header for command."
}

# register_mcp_for_user USER
# Use `claude mcp add --transport http --scope user --callback-port N`
# to register the HTTP MCP server. No tokens stored at registration time;
# they appear in ~/.claude.json under .mcpServers.higgsfield.oauth after
# the operator completes the browser flow.
register_mcp_for_user() {
    local user="$1"

    local sudo_pfx
    if [[ "$user" == "root" ]]; then
        sudo_pfx=""
    else
        sudo_pfx="sudo -u $user -H"
    fi

    $sudo_pfx /usr/bin/claude mcp remove higgsfield -s user >/dev/null 2>&1 || true
    if $sudo_pfx /usr/bin/claude mcp add --transport http --scope user \
            --callback-port "$HIGGSFIELD_CALLBACK_PORT" \
            higgsfield "$HIGGSFIELD_URL" >/dev/null 2>&1; then
        log "Registered higgsfield MCP for ${user} (OAuth pending)"
    else
        warn "claude mcp add higgsfield failed for ${user}; check manually"
    fi
}
