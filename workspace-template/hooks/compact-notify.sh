#!/usr/bin/env bash
# PreCompact hook — record that compaction is about to happen, optionally
# ping the operator via the gateway webhook so they're not surprised by
# context-loss artefacts in subsequent replies.
set +e

INPUT="$(cat 2>/dev/null || true)"

WS="${AGENT_WORKSPACE:-${PWD}}"
LOG="${WS}/logs/compact.log"
mkdir -p "$(dirname "$LOG")" 2>/dev/null

TS=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
TRIGGER="$(printf '%s' "$INPUT" | jq -r '.trigger // "auto"' 2>/dev/null)"
echo "${TS} compact (trigger=${TRIGGER})" >>"$LOG"

# Optional: ping operator via webhook if a token is staged. Best-effort.
WEBHOOK_TOKEN_FILE="${AGENT_WEBHOOK_TOKEN_FILE:-${HOME}/secrets/webhook-token.txt}"
WEBHOOK_URL="${AGENT_WEBHOOK_URL:-http://127.0.0.1:8080/hooks/agent}"
OP_CHAT="${OPERATOR_CHAT_ID:-}"
AGENT_NAME="${AGENT_NAME:-$(basename "$(dirname "$(dirname "$WS")")")}"

if [ -s "$WEBHOOK_TOKEN_FILE" ] && [ -n "$OP_CHAT" ]; then
    TOKEN="$(cat "$WEBHOOK_TOKEN_FILE")"
    PAYLOAD=$(jq -nc --arg a "$AGENT_NAME" --arg c "$OP_CHAT" --arg t "context compaction starting (trigger=${TRIGGER})" \
        '{agent:$a, chat_id:($c|tonumber), text:$t}')
    curl -sS --max-time 3 -X POST "${WEBHOOK_URL}" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD" >/dev/null 2>&1 || true
fi

exit 0
