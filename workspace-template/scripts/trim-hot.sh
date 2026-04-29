#!/usr/bin/env bash
# trim-hot.sh — Compress HOT entries older than 24h into WARM via Sonnet.
# Falls back to bash extraction (first 120 chars per entry) if Sonnet fails.
# IMPORTANT: runs claude from /tmp so the agent's CLAUDE.md is NOT loaded.
set -euo pipefail

WS="${AGENT_WORKSPACE:-${PWD}}"
HOT="${WS}/core/hot/recent.md"
WARM="${WS}/core/warm/decisions.md"
LOCKFILE="/tmp/trim-hot.lock"
# Single consolidated cron log per workspace — survives reboots, easy to grep.
# Falls back to /tmp on first run before installer creates logs/.
LOG_DIR="${WS}/logs"
[ -d "$LOG_DIR" ] || LOG_DIR="/tmp"
LOG="${LOG_DIR}/memory-cron.log"
MAX_AGE_HOURS="${MAX_AGE_HOURS:-24}"
MAX_ENTRIES="${MAX_ENTRIES:-40}"
SONNET_BUDGET="${SONNET_BUDGET:-0.15}"

log() { echo "$(date -u '+%H:%M:%S') [trim-hot] $*" >>"$LOG"; }
echo "=== trim-hot.sh $(date -u '+%Y-%m-%dT%H:%M:%SZ') ===" >>"$LOG"

[ -f "$HOT" ] || { log "no recent.md, skip"; exit 0; }

SIZE=$(wc -c <"$HOT")
log "HOT size=${SIZE}b"
if [ "$SIZE" -lt 10240 ]; then
    log "<10KB, skip"
    exit 0
fi

exec 200>"$LOCKFILE"
flock -n 200 || { log "lock held, skip"; exit 0; }

CUTOFF=$(date -u -d "${MAX_AGE_HOURS} hours ago" +%s)

BLOCKS_DIR=$(mktemp -d)
trap 'rm -rf "$BLOCKS_DIR"' EXIT

BLOCK_IDX=0
CURRENT_FILE=""
while IFS= read -r line || [ -n "$line" ]; do
    if [[ "$line" =~ ^###[[:space:]]([0-9]{4}-[0-9]{2}-[0-9]{2})[[:space:]]([0-9]{2}:[0-9]{2}) ]]; then
        BLOCK_IDX=$((BLOCK_IDX + 1))
        CURRENT_FILE="$BLOCKS_DIR/$(printf '%04d' "$BLOCK_IDX")"
        echo "TS=${BASH_REMATCH[1]} ${BASH_REMATCH[2]}" >"${CURRENT_FILE}.meta"
        echo "$line" >"$CURRENT_FILE"
    elif [ -n "$CURRENT_FILE" ]; then
        echo "$line" >>"$CURRENT_FILE"
    fi
done <"$HOT"

TOTAL=$BLOCK_IDX
log "total blocks=${TOTAL}"

OLD_TEXT=$(mktemp)
OLD_COUNT=0
KEPT=0
for i in $(seq 1 "$TOTAL"); do
    FILE="$BLOCKS_DIR/$(printf '%04d' "$i")"
    META="${FILE}.meta"
    [ -f "$META" ] || continue
    TS=$(grep '^TS=' "$META" | sed 's/^TS=//')
    EPOCH=$(date -u -d "$TS" +%s 2>/dev/null || echo 0)
    if [ "$EPOCH" -lt "$CUTOFF" ]; then
        cat "$FILE" >>"$OLD_TEXT"; echo "" >>"$OLD_TEXT"
        rm -f "$FILE" "$META"
        OLD_COUNT=$((OLD_COUNT + 1))
    else
        KEPT=$((KEPT + 1))
    fi
done
log "phase1 (age): old=${OLD_COUNT} kept=${KEPT}"

REMAINING=$(find "$BLOCKS_DIR" -name '*.meta' | wc -l)
EXTRA=0
if [ "$REMAINING" -gt "$MAX_ENTRIES" ]; then
    TO_REMOVE=$((REMAINING - MAX_ENTRIES))
    while IFS= read -r META; do
        FILE="${META%.meta}"
        cat "$FILE" >>"$OLD_TEXT"; echo "" >>"$OLD_TEXT"
        rm -f "$FILE" "$META"
        EXTRA=$((EXTRA + 1))
    done < <(find "$BLOCKS_DIR" -name '*.meta' | sort | head -n "$TO_REMOVE")
    log "phase2 (size): trimmed ${EXTRA} more"
fi

TOTAL_TO_COMPRESS=$((OLD_COUNT + EXTRA))
SUMMARIES=$(mktemp)

if [ "$TOTAL_TO_COMPRESS" -gt 0 ] && [ -s "$OLD_TEXT" ]; then
    log "compressing ${TOTAL_TO_COMPRESS} blocks via Sonnet..."

    SONNET_PROMPT="Extract key facts from this AI agent dialog.
Rules:
- One line per entry, format: - YYYY-MM-DD HH:MM: fact/decision/result
- Max 120 chars per line
- Skip greetings and confirmations without facts
- ONLY output lines starting with '- '. Nothing else.

Dialog:
$(cat "$OLD_TEXT")"

    # --max-budget-usd is a hard cap so a runaway prompt can't burn $$$ on cron.
    # If claude rejects the flag (older binary), fall back to bash extraction.
    SONNET_RESULT=$(cd /tmp && echo "$SONNET_PROMPT" | claude --model sonnet --print \
        --max-budget-usd "$SONNET_BUDGET" \
        --append-system-prompt "You compress AI agent memory. Output ONLY lines starting with '- YYYY-MM-DD HH:MM: '." \
        2>/dev/null) || SONNET_RESULT=""

    if [ -n "$SONNET_RESULT" ]; then
        echo "$SONNET_RESULT" | grep '^- ' >"$SUMMARIES" || true
        log "Sonnet OK: $(wc -l <"$SUMMARIES") summaries"
    else
        log "Sonnet unavailable, fallback to bash"
        BLOCK_TS=""
        while IFS= read -r line || [ -n "$line" ]; do
            if [[ "$line" =~ ^###[[:space:]]([0-9]{4}-[0-9]{2}-[0-9]{2})[[:space:]]([0-9]{2}:[0-9]{2}) ]]; then
                BLOCK_TS="${BASH_REMATCH[1]} ${BASH_REMATCH[2]}"
            elif [[ "$line" =~ ^\*\*.*:\*\* ]] && [[ ! "$line" =~ ^\*\*User:\*\* ]]; then
                SUM=$(echo "$line" | sed 's/^\*\*[^*]*\*\* //' | head -c 120 | sed 's/[[:space:]]*$//')
                [ -n "$SUM" ] && echo "- ${BLOCK_TS}: ${SUM}" >>"$SUMMARIES"
            fi
        done <"$OLD_TEXT"
        log "fallback: $(wc -l <"$SUMMARIES") summaries"
    fi
fi
rm -f "$OLD_TEXT"

if [ -s "$SUMMARIES" ]; then
    TODAY=$(date -u '+%Y-%m-%d')
    {
        echo ""
        echo "## ${TODAY} (auto-compressed from HOT)"
        echo ""
        cat "$SUMMARIES"
    } >>"$WARM"
    log "appended $(wc -l <"$SUMMARIES") summaries to WARM"
fi
rm -f "$SUMMARIES"

{
    echo "# HOT memory — full rolling 24h journal"
    echo ""
    while IFS= read -r FILE; do
        [[ "$FILE" == *.meta ]] && continue
        cat "$FILE"; echo ""
    done < <(find "$BLOCKS_DIR" -type f | sort)
} >"$HOT"

NEW_SIZE=$(wc -c <"$HOT")
log "HOT: ${SIZE}b -> ${NEW_SIZE}b"
