#!/usr/bin/env bash
# Install Playwright + Chromium system-wide and register the @playwright/mcp
# MCP server in both root's and agent's mcp.json. Shared installation means
# one Chromium binary (~430 MB) is used by all agents — no per-agent
# duplication.
#
# Why a separate step (vs. baking into 60-user-gateway.sh): Playwright is a
# system-level dep, not gateway code. The shared install path also serves
# Vesna and any future agents.

PLAYWRIGHT_DIR="${PLAYWRIGHT_DIR:-/opt/playwright}"
PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/opt/playwright/browsers}"
MCP_CLI="${PLAYWRIGHT_DIR}/node_modules/@playwright/mcp/cli.js"

step_main() {
    install -d -m 0755 -o root -g root "$PLAYWRIGHT_DIR" "$PLAYWRIGHT_BROWSERS_PATH"

    if [[ ! -d "${PLAYWRIGHT_DIR}/node_modules/@playwright/mcp" ]]; then
        log "Installing @playwright/mcp + playwright into ${PLAYWRIGHT_DIR}"
        ( cd "$PLAYWRIGHT_DIR" \
            && [[ -f package.json ]] || npm init -y >/dev/null 2>&1
          npm install --silent --prefix "$PLAYWRIGHT_DIR" \
              @playwright/mcp@latest playwright@latest 2>&1 | tail -3 )
    else
        log "Playwright already installed at ${PLAYWRIGHT_DIR}"
    fi

    if [[ ! -d "${PLAYWRIGHT_BROWSERS_PATH}/chromium-"* ]]; then
        log "Installing Chromium + system deps (≈430 MB)"
        PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" \
            "${PLAYWRIGHT_DIR}/node_modules/.bin/playwright" install chromium --with-deps 2>&1 | tail -3
    else
        log "Chromium browser already installed"
    fi

    chmod -R a+rX "$PLAYWRIGHT_BROWSERS_PATH" "$PLAYWRIGHT_DIR/node_modules"

    if [[ ! -x "$MCP_CLI" ]]; then
        err "Expected @playwright/mcp cli at $MCP_CLI but it's missing"
        return 1
    fi

    register_playwright_mcp_for root  /root/.claude/mcp.json
    register_playwright_mcp_for agent /home/agent/.claude/mcp.json

    ok "Playwright + @playwright/mcp installed; MCP registered for root + agent."
}

# register_playwright_mcp_for USER MCP_JSON_PATH
# Idempotently merge a "playwright" entry into the existing mcpServers map.
register_playwright_mcp_for() {
    local user="$1" mcp_path="$2"
    local mcp_dir; mcp_dir="$(dirname "$mcp_path")"
    install -d -m 0700 -o "$user" -g "$user" "$mcp_dir"

    local tmp; tmp="$(mktemp)"; TMPFILES+=("$tmp")

    if [[ -f "$mcp_path" ]]; then
        if jq --arg cli "$MCP_CLI" --arg bp "$PLAYWRIGHT_BROWSERS_PATH" \
              '.mcpServers = ((.mcpServers // {}) +
                  {"playwright": {"command": "node",
                                  "args": [$cli, "--browser=chromium", "--headless", "--isolated"],
                                  "env": {"PLAYWRIGHT_BROWSERS_PATH": $bp}}})' \
              "$mcp_path" >"$tmp" 2>/dev/null && [[ -s "$tmp" ]]; then
            install -m 0644 -o "$user" -g "$user" "$tmp" "$mcp_path"
            log "Registered playwright MCP for ${user} → ${mcp_path}"
        else
            warn "jq merge of ${mcp_path} failed; leaving file alone."
        fi
    else
        if jq -n --arg cli "$MCP_CLI" --arg bp "$PLAYWRIGHT_BROWSERS_PATH" \
                '{mcpServers: {playwright: {command: "node",
                                            args: [$cli, "--browser=chromium", "--headless", "--isolated"],
                                            env: {PLAYWRIGHT_BROWSERS_PATH: $bp}}}}' >"$tmp" 2>/dev/null \
                && [[ -s "$tmp" ]]; then
            install -m 0644 -o "$user" -g "$user" "$tmp" "$mcp_path"
            log "Created MCP config for ${user} at ${mcp_path}"
        fi
    fi
}
