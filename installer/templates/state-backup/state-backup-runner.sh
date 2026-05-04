#!/usr/bin/env bash
# state-backup-runner — periodic state snapshot to private GitHub repo.
# Invoked by cron every 4 hours. Idempotent.
#
# Flow:
#   1. rsync per-agent workspace into local mirror, with strict --exclude.
#   2. git add . ; if diff exists, run secret-scanner; commit + push.
#   3. log status to .last-run-status.json.
set -euo pipefail

REPO_DIR="/var/lib/agent-state-backup"
LOG="/var/log/agent-state-backup.log"
STATUS_FILE="$REPO_DIR/.last-run-status.json"
TS="$(date -u +%FT%TZ)"

cd "$REPO_DIR"

log() { echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG"; }
log "=== state-backup run start ==="

# Per-agent rsync. -a archive, --delete keeps mirror in sync.
sync_one() {
    local src="$1" dst="$2"
    [[ -d "$src" ]] || { log "skip $src (not present)"; return 0; }
    mkdir -p "$dst"
    rsync -a --delete \
        --exclude="secrets/" \
        --exclude="*.token" \
        --exclude="*.key" \
        --exclude="*.pem" \
        --exclude="*.credentials*" \
        --exclude=".env*" \
        --exclude=".claude/projects/" \
        --exclude=".claude/sessions/" \
        --exclude=".claude/shell-snapshots/" \
        --exclude=".claude/statsig/" \
        --exclude=".claude/todos/" \
        --exclude=".claude/ide/" \
        --exclude="sessions/" \
        --exclude="node_modules/" \
        --exclude=".venv/" \
        --exclude="__pycache__/" \
        --exclude="*.pyc" \
        --exclude="logs/raw/" \
        --exclude="*.log" \
        --exclude=".cache/" \
        --exclude="*.deprecated.*" \
        "$src/" "$dst/" >>"$LOG" 2>&1 || true
}

sync_one /home/agent/.claude-lab/leto    "$REPO_DIR/leto"
sync_one /home/agent/.claude-lab/tyrion  "$REPO_DIR/tyrion"
sync_one /home/agent/.claude-lab/varys   "$REPO_DIR/varys"
sync_one /root/.claude-lab/vesna         "$REPO_DIR/vesna"

# Optional: OpenViking SQLite snapshot (nightly via separate cron — see
# openviking-snapshot.sh)

# Stage everything
git add -A 2>&1 | tee -a "$LOG" || true

# Run secret scanner before committing.
if ! ./tools/secret-scanner.sh 2>>"$LOG"; then
    log "SECRET SCANNER REJECTED — aborting, NOT pushing"
    git reset HEAD >/dev/null 2>&1 || true
    cat > "$STATUS_FILE" <<EOR
{"ts": "$TS", "result": "rejected_by_secret_scanner", "msg": "scanner found token-shaped strings; check $LOG"}
EOR
    exit 1
fi

# Anything to commit?
if git diff --cached --quiet; then
    log "no changes; skipping commit/push"
    cat > "$STATUS_FILE" <<EOR
{"ts": "$TS", "result": "no_changes"}
EOR
    exit 0
fi

# Compose commit message with delta summary.
DELTA="$(git diff --cached --shortstat 2>/dev/null || echo '')"
if ! git commit -q -m "state snapshot $TS" -m "$DELTA" 2>&1 | tee -a "$LOG"; then
    log "commit failed"
    cat > "$STATUS_FILE" <<EOR
{"ts": "$TS", "result": "commit_failed"}
EOR
    exit 1
fi

# Push (uses ssh deploy key via Host github-state-backup in ~/.ssh/config).
if git push origin main 2>&1 | tee -a "$LOG"; then
    log "push OK"
    SHA="$(git rev-parse --short HEAD)"
    cat > "$STATUS_FILE" <<EOR
{"ts": "$TS", "result": "pushed", "sha": "$SHA", "delta": "$DELTA"}
EOR
else
    log "push FAILED"
    cat > "$STATUS_FILE" <<EOR
{"ts": "$TS", "result": "push_failed"}
EOR
    exit 1
fi
