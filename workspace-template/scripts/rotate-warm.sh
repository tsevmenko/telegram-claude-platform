#!/usr/bin/env bash
# rotate-warm.sh — Move WARM entries older than MAX_AGE_DAYS to COLD.
# Pure bash. No model calls. Safe to run idempotently.
set -euo pipefail

WS="${AGENT_WORKSPACE:-${PWD}}"
WARM="${WS}/core/warm/decisions.md"
COLD="${WS}/core/MEMORY.md"
LOG_DIR="${WS}/logs"
[ -d "$LOG_DIR" ] || LOG_DIR="/tmp"
LOG="${LOG_DIR}/memory-cron.log"
MAX_AGE_DAYS="${MAX_AGE_DAYS:-14}"

log() { echo "$(date -u '+%H:%M:%S') [rotate-warm] $*" >>"$LOG"; }
echo "=== rotate-warm.sh $(date -u '+%Y-%m-%dT%H:%M:%SZ') ===" >>"$LOG"

[ -f "$WARM" ] || { log "no decisions.md, skip"; exit 0; }

CUTOFF=$(date -u -d "${MAX_AGE_DAYS} days ago" '+%Y-%m-%d')

KEEP=$(mktemp)
ARCHIVE=$(mktemp)
trap 'rm -f "$KEEP" "$ARCHIVE"' EXIT

CURRENT_SECTION=""
CURRENT_DATE=""
ROTATED=0
KEPT=0

flush() {
    [ -z "$CURRENT_DATE" ] && return
    if [[ "$CURRENT_DATE" < "$CUTOFF" ]]; then
        printf '%s\n' "$CURRENT_SECTION" >>"$ARCHIVE"
        ROTATED=$((ROTATED + 1))
    else
        printf '%s\n' "$CURRENT_SECTION" >>"$KEEP"
        KEPT=$((KEPT + 1))
    fi
}

while IFS= read -r line || [ -n "$line" ]; do
    if [[ "$line" =~ ^##[[:space:]]([0-9]{4}-[0-9]{2}-[0-9]{2}) ]]; then
        flush
        CURRENT_SECTION="$line"
        CURRENT_DATE="${BASH_REMATCH[1]}"
    elif [[ "$line" =~ ^#[[:space:]] ]] || [[ "$line" =~ ^_ ]]; then
        echo "$line" >>"$KEEP"
    elif [ -n "$CURRENT_SECTION" ]; then
        CURRENT_SECTION="$CURRENT_SECTION
$line"
    else
        echo "$line" >>"$KEEP"
    fi
done <"$WARM"
flush

if [ -s "$ARCHIVE" ]; then
    {
        echo ""
        echo "## Archived from WARM ($(date -u '+%Y-%m-%d'))"
        echo ""
        cat "$ARCHIVE"
    } >>"$COLD"
    log "rotated ${ROTATED} sections to COLD"
fi

cp "$KEEP" "$WARM"
log "kept=${KEPT}, rotated=${ROTATED}"
