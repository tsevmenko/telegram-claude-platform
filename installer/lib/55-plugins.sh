#!/usr/bin/env bash
# Bundle the Superpowers Claude Code plugin (15 workflow skills:
# planning, TDD, debugging, code-review, brainstorming, parallel agents,
# task tracking with .tasks.json persistence between sessions).
#
# Source: https://github.com/pcvelz/superpowers (MIT-compatible fork of obra/superpowers).
# Pinned by SHA so a future upstream change can't surprise the deploy.

readonly SUPERPOWERS_REPO="https://github.com/pcvelz/superpowers.git"
readonly SUPERPOWERS_SHA="04bad33282e792ecfd1007a138331f1e6b288eed"

step_main() {
    install_for_user root  /root/.claude/plugins
    install_for_user agent /home/agent/.claude/plugins

    ok "Superpowers plugin bundled for both Vesna and the user-gateway."
}

install_for_user() {
    local user="$1" plugins_dir="$2"
    install -d -m 0755 -o "$user" -g "$user" "$plugins_dir"
    local sp_dir="${plugins_dir}/superpowers"
    local cfg="${plugins_dir}/config.json"

    if [[ -d "$sp_dir/.git" ]]; then
        log "Superpowers already cloned for ${user} — pinning SHA."
        as_user "$user" git -C "$sp_dir" fetch --depth=1 origin "$SUPERPOWERS_SHA" 2>/dev/null \
            || warn "Superpowers fetch failed — keeping existing checkout."
        as_user "$user" git -C "$sp_dir" checkout --quiet "$SUPERPOWERS_SHA" 2>/dev/null \
            || warn "Superpowers checkout of pinned SHA failed."
    else
        as_user "$user" git clone --quiet --depth 1 "$SUPERPOWERS_REPO" "$sp_dir" \
            || { warn "Failed to clone Superpowers for ${user} — skipping."; return 0; }
        as_user "$user" git -C "$sp_dir" fetch --depth=1 origin "$SUPERPOWERS_SHA" 2>/dev/null \
            || warn "fetch of pinned SHA failed; using HEAD."
        as_user "$user" git -C "$sp_dir" checkout --quiet "$SUPERPOWERS_SHA" 2>/dev/null \
            || warn "checkout of pinned SHA failed; using HEAD."
    fi

    # Patch ~/.claude/plugins/config.json to register the plugin.
    local tmp; tmp="$(mktemp)"; TMPFILES+=("$tmp")
    if [[ -f "$cfg" ]]; then
        if jq --arg p "$sp_dir" \
              '.plugins = ((.plugins // {}) + {"superpowers": {"enabled": true, "path": $p}})' \
              "$cfg" >"$tmp" 2>/dev/null && [[ -s "$tmp" ]]; then
            install -m 0644 -o "$user" -g "$user" "$tmp" "$cfg"
        else
            warn "jq merge of ${cfg} failed — leaving file untouched."
            return 0
        fi
    else
        if jq -n --arg p "$sp_dir" \
                '{plugins: {superpowers: {enabled: true, path: $p}}}' >"$tmp" 2>/dev/null \
                && [[ -s "$tmp" ]]; then
            install -m 0644 -o "$user" -g "$user" "$tmp" "$cfg"
        else
            warn "Failed to write ${cfg} — skipping."
            return 0
        fi
    fi

    fix_owner "$plugins_dir" "$user"
    log "Superpowers wired for ${user} at ${sp_dir}"
}
