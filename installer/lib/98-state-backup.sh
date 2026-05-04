#!/usr/bin/env bash
# Install the state-backup infrastructure: clone an operator-supplied
# private GitHub repo into /var/lib/agent-state-backup/, plant runner
# scripts + secret-scanner, register cron entries.
#
# Why state backup at all: live operator data (USER profiles, decisions,
# scraped competitor archives, custom skills built by agents) lives only
# on the VPS by default. If the droplet dies, all accumulated agent
# learning vanishes. The state-backup repo (private, separate from the
# public source-code repo) holds rsync'd snapshots committed every 4
# hours and OpenViking SQLite dumps daily.
#
# Operator pre-requisites before running this step:
#   1. Create the private GitHub repo via UI or `gh repo create
#      <owner>/agent-state-backup --private`.
#   2. Generate an SSH deploy key on this VPS:
#         ssh-keygen -t ed25519 -f /root/.ssh/agent-state-backup-deploy \
#                    -N "" -C "vps-state-backup-writer"
#   3. Add the public key as a *write*-enabled deploy key on the repo:
#         gh repo deploy-key add /root/.ssh/agent-state-backup-deploy.pub \
#            --repo <owner>/agent-state-backup --title vps-writer --allow-write
#   4. Add an SSH-config alias on the VPS:
#         Host github-state-backup
#             HostName github.com
#             User git
#             IdentityFile /root/.ssh/agent-state-backup-deploy
#             IdentitiesOnly yes
#   5. Set STATE_BACKUP_REPO env var to the SSH URL before running this
#      installer step:
#         export STATE_BACKUP_REPO=git@github-state-backup:<owner>/agent-state-backup.git
#
# If STATE_BACKUP_REPO is not set, the step warns and exits 0 (skips
# backup setup — install proceeds, operator can re-run the step later).

BACKUP_DIR="${STATE_BACKUP_DIR:-/var/lib/agent-state-backup}"
BACKUP_REPO="${STATE_BACKUP_REPO:-}"

step_main() {
    if [[ -z "$BACKUP_REPO" ]]; then
        warn "STATE_BACKUP_REPO not set. Skipping state-backup setup."
        warn "Re-run this step after creating the private repo + deploy key."
        warn "See header of 80-state-backup.sh for the operator pre-flight."
        return 0
    fi

    install -d -m 0755 -o root -g root "$BACKUP_DIR"
    install -d -m 0755 -o root -g root "$BACKUP_DIR/tools"

    # Clone the (likely empty) repo if not already initialized.
    if [[ ! -d "$BACKUP_DIR/.git" ]]; then
        log "Initialising state-backup repo at ${BACKUP_DIR}"
        ( cd "$BACKUP_DIR" && {
            git init -b main >/dev/null
            git remote add origin "$BACKUP_REPO"
            git config user.name "vps-state-backup"
            git config user.email "vps-state-backup@$(hostname)"
            git config push.autoSetupRemote true
        } )
    else
        log "state-backup repo already at ${BACKUP_DIR}"
    fi

    # Plant the three operator scripts from installer templates.
    local tpl_dir="${INSTALLER_ROOT}/installer/templates/state-backup"
    if [[ ! -d "$tpl_dir" ]]; then
        err "templates/state-backup missing — installer state corrupt"
        return 1
    fi
    install -m 0755 -o root -g root "$tpl_dir/state-backup-runner.sh" "$BACKUP_DIR/tools/state-backup-runner.sh"
    install -m 0755 -o root -g root "$tpl_dir/secret-scanner.sh"      "$BACKUP_DIR/tools/secret-scanner.sh"
    install -m 0755 -o root -g root "$tpl_dir/openviking-snapshot.sh" "$BACKUP_DIR/tools/openviking-snapshot.sh"
    install -m 0644 -o root -g root "$tpl_dir/.gitignore"             "$BACKUP_DIR/.gitignore"
    install -m 0644 -o root -g root "$tpl_dir/README.md"              "$BACKUP_DIR/README.md"

    # Sanity check: bash -n + python3 + git available
    bash -n "$BACKUP_DIR/tools/state-backup-runner.sh" || { err "runner failed bash -n"; return 1; }
    bash -n "$BACKUP_DIR/tools/secret-scanner.sh" || { err "secret-scanner failed bash -n"; return 1; }

    # Cron entries — runs as root since the secrets-protected workspaces
    # need rsync access via -a (preserves perms; root reads /home/agent/...
    # via DAC override).
    local cron_file="/etc/cron.d/agent-state-backup"
    cat >"$cron_file" <<EOR
# State backup for telegram-claude-platform — auto-managed by 80-state-backup.sh
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
CRON_TZ=UTC

# every 4 hours: rsync workspaces, commit, push
0 */4 * * * root ${BACKUP_DIR}/tools/state-backup-runner.sh >>/var/log/agent-state-backup.log 2>&1

# daily 03:00: OpenViking SQLite dump
0 3 * * * root ${BACKUP_DIR}/tools/openviking-snapshot.sh >>/var/log/agent-state-backup.log 2>&1
EOR
    chmod 0644 "$cron_file"
    chown root:root "$cron_file"

    systemctl reload cron 2>/dev/null || systemctl restart cron 2>/dev/null || true

    ok "state-backup installed at ${BACKUP_DIR}; cron at ${cron_file}"
    log "First manual run: ${BACKUP_DIR}/tools/state-backup-runner.sh"
}
