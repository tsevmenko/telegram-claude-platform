#!/usr/bin/env bash
# Install the proactivity stack — bin/fire-webhook + bin/cron-add at
# /opt/agent-installer/bin/, idempotent. Per-agent personal cron files
# (/etc/cron.d/agent-personal-<name>) are created on-demand by cron-add
# when agents first schedule themselves; we don't pre-create them here.
#
# Why a separate step (vs. baking into 60-user-gateway.sh): these binaries
# are infra owned by root and are useful regardless of which agents exist.
# Re-running this step on an existing install picks up bin updates without
# touching agent workspaces.

step_main() {
    local bin_dir="/opt/agent-installer/bin"
    local tpl_dir="${INSTALLER_ROOT}/installer/templates/bin"

    install -d -m 0755 -o root -g root /opt/agent-installer
    install -d -m 0755 -o root -g root "$bin_dir"

    if [[ ! -f "${tpl_dir}/fire-webhook" || ! -f "${tpl_dir}/cron-add" ]]; then
        err "proactivity bin templates missing in ${tpl_dir} — refusing"
        return 1
    fi

    # Install (replace) the two binaries. Mode 0755, owner root:root —
    # callable by anyone but only modifiable by root. cron-add additionally
    # requires sudoers grant (handled in 30-users.sh) for the agent user.
    install -m 0755 -o root -g root "${tpl_dir}/fire-webhook" "${bin_dir}/fire-webhook"
    install -m 0755 -o root -g root "${tpl_dir}/cron-add"     "${bin_dir}/cron-add"

    # Sanity: bash syntax check before declaring success.
    if ! bash -n "${bin_dir}/fire-webhook"; then
        err "fire-webhook failed bash -n syntax check"
        return 1
    fi
    if ! bash -n "${bin_dir}/cron-add"; then
        err "cron-add failed bash -n syntax check"
        return 1
    fi

    ok "Proactivity binaries installed at ${bin_dir}/{fire-webhook,cron-add}"
}
