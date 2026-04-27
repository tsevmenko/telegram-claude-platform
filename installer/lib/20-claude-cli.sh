#!/usr/bin/env bash
# Install Node.js 20 + Claude Code CLI globally.
# Sourced by install.sh — defines step_main().
#
# Globally-installed CLI is reachable by both `root` and the `agent` user.
# Each user runs `claude login` once after install to get its own OAuth token
# in its own ~/.claude/.credentials.json.

readonly NODE_MAJOR="22"

step_main() {
    if command -v node &>/dev/null; then
        local current_major
        current_major="$(node -v 2>/dev/null | sed -E 's/^v([0-9]+).*/\1/')"
        if [[ "$current_major" == "$NODE_MAJOR" ]]; then
            ok "Node.js $(node -v) already installed."
        else
            warn "Node.js $(node -v) present but not v${NODE_MAJOR}; replacing."
            install_node
        fi
    else
        install_node
    fi

    if command -v claude &>/dev/null; then
        local cv
        cv="$(claude --version 2>/dev/null || echo unknown)"
        ok "Claude CLI already installed (v${cv})."
        return 0
    fi

    log "Installing Claude Code CLI globally..."
    if ! npm install -g @anthropic-ai/claude-code --silent; then
        err "npm install -g @anthropic-ai/claude-code failed."
        return 1
    fi

    if ! command -v claude &>/dev/null; then
        err "Claude CLI not on PATH after npm install. Check /usr/lib/node_modules/."
        return 1
    fi

    ok "Claude CLI installed: $(claude --version)"
}

install_node() {
    log "Installing Node.js ${NODE_MAJOR} via NodeSource..."
    curl "${CURL_OPTS[@]}" "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs
    ok "Node.js $(node -v) installed."
}
