#!/usr/bin/env bash
# restore-from-backup — recover agent state on a fresh VPS.
#
# Pre-conditions: the platform `install.sh` already ran (so users, system
# deps, gateway, etc. exist) and the operator cloned the state-backup
# repo to /tmp/restore (see README of the state-backup repo).
#
# Behaviour: walks the operator through:
#   1. Confirming each agent that has a directory in the backup repo.
#   2. rsync-ing the backup's <agent>/ into the live workspace, with
#      ownership matching the agent (agent user for client agents,
#      root for vesna).
#   3. Optionally restoring the latest OpenViking SQLite snapshot.
#
# Idempotent: re-running re-syncs (same state); existing live files
# matching the backup are not deleted, only updated.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/tmp/restore}"
[[ -d "$BACKUP_DIR" ]] || { echo "BACKUP_DIR=$BACKUP_DIR not found; clone the repo first" >&2; exit 1; }

confirm() {
    local prompt="$1"
    read -r -p "$prompt [y/N] " ans
    [[ "$ans" =~ ^[yY]$ ]]
}

restore_one() {
    local agent="$1" target_owner="$2" target_dir="$3"
    local src="$BACKUP_DIR/$agent"
    [[ -d "$src" ]] || { echo "  [$agent] backup dir missing — skip"; return 0; }
    if ! confirm "Restore $agent → $target_dir (owner=$target_owner)?"; then
        echo "  [$agent] skipped by operator"
        return 0
    fi

    install -d -m 0755 -o "$target_owner" -g "$target_owner" "$target_dir"
    rsync -a --chown="$target_owner:$target_owner" "$src/" "$target_dir/"
    echo "  [$agent] restored → $target_dir"
}

restore_one leto    agent /home/agent/.claude-lab/leto
restore_one tyrion  agent /home/agent/.claude-lab/tyrion
restore_one varys   agent /home/agent/.claude-lab/varys
restore_one vesna   root  /root/.claude-lab/vesna

# OpenViking SQLite restore — latest snapshot in shared/.
SNAPSHOT="$(ls -t "$BACKUP_DIR/shared"/ov-snapshot-*.sql.gz 2>/dev/null | head -1 || true)"
if [[ -n "$SNAPSHOT" ]]; then
    echo ""
    echo "Latest OpenViking snapshot: $SNAPSHOT"
    if confirm "Restore OpenViking semantic memory from $SNAPSHOT?"; then
        OV_DB="${OV_DB:-/var/lib/openviking/openviking.db}"
        [[ -f "$OV_DB" ]] || OV_DB="/var/lib/openviking-lite/openviking.db"
        if [[ ! -f "$OV_DB" ]]; then
            echo "  WARN: OpenViking db file path unknown; skipping"
        else
            systemctl stop openviking 2>/dev/null || true
            mv "$OV_DB" "$OV_DB.before-restore.$(date +%s)"
            zcat "$SNAPSHOT" | sqlite3 "$OV_DB"
            chown openviking:openviking "$OV_DB"
            systemctl start openviking
            echo "  OpenViking restored from $SNAPSHOT"
        fi
    fi
fi

echo ""
echo "Restore complete."
echo "Next steps:"
echo "  1. Restart agent services to pick up restored workspaces:"
echo "       systemctl restart agent-user-gateway agent-vesna"
echo "  2. Send any agent /status in Telegram — expect post-restore session."
echo "  3. Each agent's first message will spawn fresh claude sessions; the"
echo "     restored core/hot/handoff.md feeds context into the new session."
