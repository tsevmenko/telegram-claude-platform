#!/usr/bin/env bash
# Install community @taazkareem/clickup-mcp-server system-wide and register
# the MCP server in both root's and agent's mcp.json. Wraps the binary in a
# small shell script that reads the API key from a chmod-600 secrets file
# (rather than inlining it in mcp.json which is mode 0644).
#
# Why community over official ClickUp MCP: rate limits. Official caps Free
# plan at 50 calls/24h and Unlimited at 300/24h. The community server uses
# the regular ClickUp REST API directly, where rate limits are far more
# generous (~100 req/min). For an actively-used multi-agent setup, those
# limits are the difference between "works" and "constantly throttled".

CLICKUP_DIR="${CLICKUP_DIR:-/opt/clickup-mcp}"
WRAPPER="${CLICKUP_DIR}/run.sh"
TOKEN_FILE="${CLICKUP_TOKEN_FILE:-/home/agent/.claude-lab/shared/secrets/clickup.token}"

step_main() {
    install -d -m 0755 -o root -g root "$CLICKUP_DIR"

    if [[ ! -d "${CLICKUP_DIR}/node_modules/@taazkareem/clickup-mcp-server" ]]; then
        log "Installing @taazkareem/clickup-mcp-server"
        ( cd "$CLICKUP_DIR" && {
            [[ -f package.json ]] || npm init -y >/dev/null 2>&1
            npm install --silent @taazkareem/clickup-mcp-server@latest 2>&1 | tail -3
          } )
    else
        log "@taazkareem/clickup-mcp-server already installed at ${CLICKUP_DIR}"
    fi

    chmod -R a+rX "${CLICKUP_DIR}/node_modules"

    if [[ ! -f "$TOKEN_FILE" ]]; then
        warn "ClickUp API token missing at ${TOKEN_FILE}. Skipping MCP registration."
        warn "Stage the token (chmod 600 owner=agent) and re-run this step."
        return 0
    fi

    # Resolve operator's primary CLICKUP_TEAM_ID via the API. If multiple
    # teams exist we take the first; operator can override via env var
    # CLICKUP_TEAM_ID before re-running this step.
    local team_id="${CLICKUP_TEAM_ID:-}"
    if [[ -z "$team_id" ]]; then
        local token; token="$(cat "$TOKEN_FILE")"
        team_id="$(curl -fsS -H "Authorization: ${token}" \
            https://api.clickup.com/api/v2/team 2>/dev/null \
            | jq -r '.teams[0].id // empty' 2>/dev/null)"
        if [[ -z "$team_id" ]]; then
            warn "Could not auto-resolve CLICKUP_TEAM_ID via API. Set it explicitly and re-run."
            return 0
        fi
        log "Auto-resolved primary CLICKUP_TEAM_ID=${team_id}"
    fi

    write_wrapper "$team_id"
    register_clickup_mcp_for root  /root/.claude/mcp.json
    register_clickup_mcp_for agent /home/agent/.claude/mcp.json

    ok "ClickUp MCP installed; wrapper at ${WRAPPER}; registered for root + agent."
}

write_wrapper() {
    local team_id="$1"
    cat >"$WRAPPER" <<EOR
#!/usr/bin/env bash
# Wrapper for the ClickUp MCP server. Reads the API key from a chmod-600
# secrets file rather than inlining it in mcp.json (which is mode 0644).
# Workspace ID (CLICKUP_TEAM_ID) is hardcoded here — change it if the
# operator switches primary workspace, or override via the env var.
set -e
CLICKUP_API_KEY=\$(cat ${TOKEN_FILE})
export CLICKUP_API_KEY
export CLICKUP_TEAM_ID=\${CLICKUP_TEAM_ID:-${team_id}}
export ENABLE_STDIO=true
exec /usr/bin/node ${CLICKUP_DIR}/node_modules/@taazkareem/clickup-mcp-server/build/index.js "\$@"
EOR
    chmod 0755 "$WRAPPER"
    chown root:root "$WRAPPER"
}

# register_clickup_mcp_for USER MCP_JSON_PATH
# Idempotently merge a "clickup" entry into the existing mcpServers map.
register_clickup_mcp_for() {
    local user="$1" mcp_path="$2"
    local mcp_dir; mcp_dir="$(dirname "$mcp_path")"
    install -d -m 0700 -o "$user" -g "$user" "$mcp_dir"

    local tmp; tmp="$(mktemp)"; TMPFILES+=("$tmp")

    if [[ -f "$mcp_path" ]]; then
        if jq --arg cmd "$WRAPPER" \
              '.mcpServers = ((.mcpServers // {}) +
                  {"clickup": {"command": $cmd, "args": []}})' \
              "$mcp_path" >"$tmp" 2>/dev/null && [[ -s "$tmp" ]]; then
            install -m 0644 -o "$user" -g "$user" "$tmp" "$mcp_path"
            log "Registered clickup MCP for ${user} → ${mcp_path}"
        else
            warn "jq merge of ${mcp_path} failed; leaving file alone."
        fi
    else
        if jq -n --arg cmd "$WRAPPER" \
                '{mcpServers: {clickup: {command: $cmd, args: []}}}' >"$tmp" 2>/dev/null \
                && [[ -s "$tmp" ]]; then
            install -m 0644 -o "$user" -g "$user" "$tmp" "$mcp_path"
            log "Created MCP config for ${user} at ${mcp_path}"
        fi
    fi
}
