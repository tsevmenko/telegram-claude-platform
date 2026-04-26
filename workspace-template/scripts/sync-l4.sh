#!/usr/bin/env bash
# sync-l4.sh — Upload HOT + WARM memory to OpenViking (L4 semantic layer).
# Idempotent: same date = same URI = OV overwrites previous resource.
set -euo pipefail

WS="${AGENT_WORKSPACE:-${HOME}/.claude-lab/$(basename "$(dirname "$(dirname "$(realpath "$0")")")")/.claude}"
AGENT_NAME="${AGENT_NAME:-$(basename "$(dirname "$WS")")}"
OV_HOST="${OV_HOST:-http://127.0.0.1:1933}"
OV_ACCOUNT="${OV_ACCOUNT:-default}"
DATE="$(date -u '+%Y-%m-%d')"
LOG="/tmp/sync-l4.log"

log() { echo "$(date -u '+%H:%M:%S') $*" >>"$LOG"; }
echo "=== sync-l4.sh $(date -u '+%Y-%m-%dT%H:%M:%SZ') ===" >>"$LOG"

# Resolve API key.
if [ -z "${OV_KEY:-}" ]; then
    KEY_FILE="${OV_KEY_FILE:-${HOME}/.claude-lab/shared/secrets/openviking.key}"
    if [ ! -f "$KEY_FILE" ]; then
        log "OV_KEY not set and ${KEY_FILE} not found — skip"
        exit 0
    fi
    OV_KEY="$(cat "$KEY_FILE")"
fi

HOT="${WS}/core/hot/recent.md"
WARM="${WS}/core/warm/decisions.md"

CONTENT=""
if [ -f "$HOT" ]; then
    HOT_CONTENT="$(tail -n 200 "$HOT")"
    [ -n "$HOT_CONTENT" ] && CONTENT="# HOT (last 200 lines of recent.md)

${HOT_CONTENT}"
fi

if [ -f "$WARM" ]; then
    WARM_CONTENT="$(cat "$WARM")"
    [ -n "$WARM_CONTENT" ] && CONTENT="${CONTENT}

# WARM (decisions.md)

${WARM_CONTENT}"
fi

[ -z "$CONTENT" ] && { log "no content to sync"; exit 0; }

TMP="$(mktemp /tmp/l4-sync-XXXXXX.md)"
trap 'rm -f "$TMP"' EXIT
printf '%s\n' "$CONTENT" >"$TMP"

log "uploading to ${OV_HOST}..."

UPLOAD=$(curl -sS -X POST "${OV_HOST}/api/v1/resources/temp_upload" \
    -H "X-API-Key: ${OV_KEY}" \
    -H "X-OpenViking-Account: ${OV_ACCOUNT}" \
    -H "X-OpenViking-User: ${AGENT_NAME}" \
    -F "file=@${TMP}" 2>/dev/null) || UPLOAD=""

TEMP_ID=$(echo "$UPLOAD" | jq -r '.temp_file_id // empty' 2>/dev/null || echo "")
if [ -z "$TEMP_ID" ]; then
    log "temp_upload failed: ${UPLOAD}"
    exit 1
fi
log "temp_upload OK: ${TEMP_ID}"

URI="viking://resources/${AGENT_NAME}-sessions/${DATE}"
ADD=$(curl -sS -X POST "${OV_HOST}/api/v1/resources" \
    -H "X-API-Key: ${OV_KEY}" \
    -H "X-OpenViking-Account: ${OV_ACCOUNT}" \
    -H "X-OpenViking-User: ${AGENT_NAME}" \
    -H "Content-Type: application/json" \
    -d "{\"temp_file_id\":\"${TEMP_ID}\",\"to\":\"${URI}\",\"wait\":true}" 2>/dev/null) || ADD=""

STATUS=$(echo "$ADD" | jq -r '.status // .error // "unknown"' 2>/dev/null || echo "unknown")
log "add_resource ${URI}: ${STATUS}"
