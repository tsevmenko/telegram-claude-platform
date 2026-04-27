#!/usr/bin/env bash
# UserPromptSubmit hook — query L4 (openviking-lite) and inject recalled
# context into Claude's session before the prompt is processed.
#
# Output goes to stdout (UserPromptSubmit injects stdout into context).
# Best-effort: skip silently if OV is unreachable or no key configured.
set +e

INPUT="$(cat 2>/dev/null || true)"
[ -z "$INPUT" ] && exit 0

PROMPT="$(printf '%s' "$INPUT" | jq -r '.prompt // ""' 2>/dev/null || true)"
# Don't waste a query on empty / one-word prompts.
WORDS=$(printf '%s' "$PROMPT" | wc -w | tr -d ' ')
[ "$WORDS" -lt 3 ] && exit 0

OV_HOST="${OV_HOST:-http://127.0.0.1:1933}"
KEY_FILE="${OV_KEY_FILE:-${HOME}/.claude-lab/shared/secrets/openviking.key}"
[ ! -f "$KEY_FILE" ] && exit 0
KEY="$(cat "$KEY_FILE")"
[ -z "$KEY" ] && exit 0

# Health-check first so a downed L4 doesn't cost us a 5-second timeout per prompt.
if ! curl -sS --fail --max-time 1 "${OV_HOST}/api/v1/health" >/dev/null 2>&1; then
    exit 0
fi

ACCOUNT="${OV_ACCOUNT:-default}"
AGENT="${AGENT_NAME:-$(basename "$(dirname "$(dirname "$(dirname "$(realpath "$0")")")")")}"

# Hybrid search: BM25 + cosine if embeddings configured. Limit 5 results.
RESP=$(curl -sS --fail --max-time 5 \
    -H "X-API-Key: ${KEY}" \
    -H "X-OpenViking-Account: ${ACCOUNT}" \
    -H "X-OpenViking-User: ${AGENT}" \
    -H "Content-Type: application/json" \
    -d "$(jq -nc --arg q "$PROMPT" --arg a "$ACCOUNT" \
            '{query:$q, kind:"both", mode:"hybrid", limit:5, account:$a}')" \
    "${OV_HOST}/api/v1/search" 2>/dev/null)
[ -z "$RESP" ] && exit 0

# Extract resources + messages, format as markdown.
RES=$(printf '%s' "$RESP" | jq -r '
    [.resources // [], .messages // []]
    | flatten
    | map(select(. != null and (.content // "") != ""))
    | .[:5]
    | map("- " + (.uri // .ref_id // "memory") + ": " + (.content[:200] | gsub("\n"; " ")))
    | .[]' 2>/dev/null)

if [ -n "$RES" ]; then
    echo "## Recalled from long-term memory"
    echo ""
    echo "$RES"
    echo ""
    echo "_Use this context only if relevant to the current request. Ignore if unrelated._"
    echo ""
fi

exit 0
