#!/usr/bin/env bash
# memory-rotate.sh — Archive COLD memory when MEMORY.md exceeds 5KB.
# Copies the file to core/archive/YYYY-MM.md and resets MEMORY.md to a header.
set -euo pipefail

WS="${AGENT_WORKSPACE:-${HOME}/.claude-lab/$(basename "$(dirname "$(dirname "$(realpath "$0")")")")/.claude}"
COLD="${WS}/core/MEMORY.md"
ARCHIVE_DIR="${WS}/core/archive"
LOG_DIR="${WS}/logs"
[ -d "$LOG_DIR" ] || LOG_DIR="/tmp"
LOG="${LOG_DIR}/memory-cron.log"
THRESHOLD="${THRESHOLD:-5000}"

log() { echo "$(date -u '+%H:%M:%S') [memory-rotate] $*" >>"$LOG"; }
echo "=== memory-rotate.sh $(date -u '+%Y-%m-%dT%H:%M:%SZ') ===" >>"$LOG"

[ -f "$COLD" ] || { log "no MEMORY.md"; exit 0; }

SIZE=$(wc -c <"$COLD")
log "MEMORY.md=${SIZE}b (threshold=${THRESHOLD}b)"

if [ "$SIZE" -lt "$THRESHOLD" ]; then
    log "below threshold, skip"
    exit 0
fi

mkdir -p "$ARCHIVE_DIR"
MONTH=$(date -u '+%Y-%m')
cp "$COLD" "${ARCHIVE_DIR}/${MONTH}.md"
log "archived to archive/${MONTH}.md"

# Keep just the canonical header.
cat >"$COLD" <<'EOF'
# MEMORY — COLD archive

_Permanent archive. NOT loaded into session context._
_Read on demand via the `Read` tool when older context is needed._
_Entries rotated here from WARM (>14 days) by `rotate-warm.sh`._
_When this file exceeds 5KB, `memory-rotate.sh` archives it to `core/archive/YYYY-MM.md`._
EOF
log "MEMORY.md reset to header"
