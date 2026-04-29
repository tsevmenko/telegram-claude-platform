#!/usr/bin/env bash
# compress-warm.sh — Sonnet recompression of WARM memory.
# Groups related events into topic-based key facts when WARM grows past
# 10KB or 50 lines. Runs claude from /tmp to avoid loading workspace CLAUDE.md.
set -euo pipefail

WS="${AGENT_WORKSPACE:-${PWD}}"
WARM="${WS}/core/warm/decisions.md"
LOCKFILE="/tmp/compress-warm.lock"
LOG_DIR="${WS}/logs"
[ -d "$LOG_DIR" ] || LOG_DIR="/tmp"
LOG="${LOG_DIR}/memory-cron.log"
MIN_SIZE="${MIN_SIZE:-10240}"
MIN_LINES="${MIN_LINES:-50}"
SONNET_BUDGET="${SONNET_BUDGET:-0.15}"

log() { echo "$(date -u '+%H:%M:%S') [compress-warm] $*" >>"$LOG"; }
echo "=== compress-warm.sh $(date -u '+%Y-%m-%dT%H:%M:%SZ') ===" >>"$LOG"

[ -f "$WARM" ] || { log "no decisions.md, skip"; exit 0; }

SIZE=$(wc -c <"$WARM")
LINES=$(grep -c '^- ' "$WARM" 2>/dev/null || echo 0)
log "WARM: ${SIZE}b ${LINES} lines"

if [ "$SIZE" -lt "$MIN_SIZE" ] && [ "$LINES" -lt "$MIN_LINES" ]; then
    log "too small, skip"; exit 0
fi

exec 200>"$LOCKFILE"
flock -n 200 || { log "lock held, skip"; exit 0; }

HEADER=$(mktemp)
BODY=$(mktemp)
trap 'rm -f "$HEADER" "$BODY"' EXIT

IN_STATIC=1
while IFS= read -r line || [ -n "$line" ]; do
    if [[ "$line" =~ auto-compressed ]] || [[ "$line" =~ Sonnet-compressed ]]; then
        IN_STATIC=0
        echo "$line" >>"$BODY"
    elif [[ "$line" =~ ^##[[:space:]] ]] && [ "$IN_STATIC" -eq 0 ]; then
        echo "$line" >>"$BODY"
    elif [ "$IN_STATIC" -eq 1 ]; then
        echo "$line" >>"$HEADER"
    else
        echo "$line" >>"$BODY"
    fi
done <"$WARM"

BODY_LINES=$(grep -c '^- ' "$BODY" 2>/dev/null || echo 0)
log "body lines=${BODY_LINES}"
[ "$BODY_LINES" -lt 20 ] && { log "body small, skip"; exit 0; }

BODY_CONTENT=$(grep '^- ' "$BODY")

PROMPT="Compress these ${BODY_LINES} event entries into 15-20 KEY FACTS grouped by topic.
Rules:
- Group related events (e.g. 10 backup entries = 1 line)
- Format: - TOPIC: key fact/decision/result
- Max 120 chars per line
- Remove duplicates, errors, intermediate steps
- ONLY output lines starting with '- '. Nothing else.

Entries:
${BODY_CONTENT}"

RESULT=$(cd /tmp && echo "$PROMPT" | claude --model sonnet --print \
    --max-budget-usd "$SONNET_BUDGET" \
    --append-system-prompt "Compress memory logs into key facts. Output ONLY lines starting with '- '. Group by topic." \
    2>/dev/null) || RESULT=""

[ -z "$RESULT" ] && { log "Sonnet unavailable, skip"; exit 0; }

COMPRESSED=$(echo "$RESULT" | grep '^- ' || true)
COUNT=$(echo "$COMPRESSED" | wc -l)
[ "$COUNT" -lt 3 ] && { log "too few lines (${COUNT}), skip"; exit 0; }
log "Sonnet OK: ${BODY_LINES} -> ${COUNT}"

TODAY=$(date -u '+%Y-%m-%d')
{
    cat "$HEADER"
    echo ""
    echo "## ${TODAY} (Sonnet-compressed)"
    echo ""
    echo "$COMPRESSED"
    echo ""
} >"$WARM"

log "WARM: ${SIZE}b -> $(wc -c <"$WARM")b"
