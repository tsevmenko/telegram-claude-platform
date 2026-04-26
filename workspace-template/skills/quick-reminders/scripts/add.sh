#!/usr/bin/env bash
# Schedule a reminder. At fire time, the gateway webhook delivers the message.
# Usage: add.sh "<text>" --target <chat-id> -t <time-spec> [--agent <name>]
set -euo pipefail

TEXT=""
TARGET=""
WHEN=""
AGENT_NAME="${AGENT_NAME:-leto}"

while [ $# -gt 0 ]; do
    case "$1" in
        --target) TARGET="$2"; shift 2 ;;
        -t|--time) WHEN="$2"; shift 2 ;;
        --agent) AGENT_NAME="$2"; shift 2 ;;
        --) shift; break ;;
        -*) echo "unknown flag: $1" >&2; exit 1 ;;
        *) TEXT="$1"; shift ;;
    esac
done

[ -n "$TEXT" ] || { echo "missing text" >&2; exit 1; }
[ -n "$TARGET" ] || { echo "missing --target chat id" >&2; exit 1; }
[ -n "$WHEN" ] || { echo "missing -t time spec" >&2; exit 1; }

WEBHOOK_URL="${AGENT_WEBHOOK_URL:-http://127.0.0.1:8080/hooks/agent}"
TOKEN_FILE="${AGENT_WEBHOOK_TOKEN_FILE:-/root/vesna/webhook-token.txt}"
if [ ! -f "$TOKEN_FILE" ]; then
    TOKEN_FILE="${HOME}/secrets/webhook-token.txt"
fi
[ -f "$TOKEN_FILE" ] || { echo "webhook token file not found" >&2; exit 1; }
TOKEN="$(cat "$TOKEN_FILE")"

ID="rem-$(date +%s)-$$"
PAYLOAD=$(jq -nc --arg a "$AGENT_NAME" --arg c "$TARGET" --arg t "$TEXT" --arg id "$ID" '{
    agent: $a, chat_id: ($c|tonumber), text: $t, source: "reminder", id: $id
}')

# Schedule via at: use here-doc to inline the curl call.
# Convert short forms ("2h", "45m") to "now + N units" for at.
case "$WHEN" in
    *h)  AT_SPEC="now + ${WHEN%h} hours" ;;
    *m)  AT_SPEC="now + ${WHEN%m} minutes" ;;
    *d)  AT_SPEC="now + ${WHEN%d} days" ;;
    *)   AT_SPEC="$WHEN" ;;
esac

at "$AT_SPEC" <<EOF
curl -sS -X POST "${WEBHOOK_URL}" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d '${PAYLOAD}'
EOF

echo "reminder ${ID} scheduled at ${AT_SPEC}"
