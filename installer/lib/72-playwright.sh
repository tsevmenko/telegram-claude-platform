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

    register_mcp_for_user root
    register_mcp_for_user agent

    ok "Playwright + @playwright/mcp installed; MCP registered for root + agent."
}

# register_mcp_for_user USER
# Registers "playwright" MCP server for the given Linux user via the native
# `claude mcp add --scope user` subcommand. Why native and not jq-merge:
# claude CLI 2.x reads MCP config from ~/.claude.json (single dot-file in
# $HOME), NOT from ~/.claude/mcp.json. Direct jq-merge into the wrong
# file silently failed to load any MCP we registered through v0.4.3 /
# v0.4.4. Tyrion's diagnosis 2026-05-01.
register_mcp_for_user() {
    local user="$1"

    local sudo_pfx
    if [[ "$user" == "root" ]]; then
        sudo_pfx=""
    else
        sudo_pfx="sudo -u $user -H"
    fi

    # Idempotent remove first, then add with all the args inline. The
    # @playwright/mcp cli accepts a chain of flags; we pass them as
    # positional args after the command name (claude mcp add accepts
    # them as `args` after the command).
    $sudo_pfx /usr/bin/claude mcp remove playwright -s user >/dev/null 2>&1 || true
    if $sudo_pfx /usr/bin/claude mcp add --scope user \
            -e PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" \
            playwright /usr/bin/node \
            -- "$MCP_CLI" --browser=chromium --headless --isolated \
            >/dev/null 2>&1; then
        log "Registered playwright MCP for ${user}"
    else
        warn "claude mcp add playwright failed for ${user}; check manually"
    fi
}
