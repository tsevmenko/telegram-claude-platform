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

# Try a list of conventional key paths in priority order. Different users
# have the key in different places (root in /root/secrets/, agent in
# /home/agent/secrets/ AND /home/agent/.claude-lab/shared/secrets/).
KEY_FILE=""
for candidate in \
    "$OV_KEY_FILE" \
    "${HOME}/.claude-lab/shared/secrets/openviking.key" \
    "${HOME}/secrets/openviking.key" \
    "/etc/openviking/key"
do
    if [ -n "$candidate" ] && [ -r "$candidate" ] 2>/dev/null; then
        KEY_FILE="$candidate"; break
    fi
done
[ -z "$KEY_FILE" ] && exit 0
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
# 1500 chars per result — long enough to actually capture per-turn facts
# (resource entries are typically 200-400 chars each, so this gives 3-5 entries
# worth of context per matched resource). Claude's context budget is 400K, so
# 5 results × 1500 chars × ~4 chars/token ≈ 1.9K tokens — well within budget.
RES=$(printf '%s' "$RESP" | jq -r '
    [.resources // [], .messages // []]
    | flatten
    | map(select(. != null and (.content // "") != ""))
    | .[:5]
    | map("- source=" + (.uri // .ref_id // "memory")
          + " | score=" + ((.score // .sem_score // 0) | tostring | .[0:5])
          + "\n  " + (.content[:1500] | gsub("\n"; " ")))
    | .[]' 2>/dev/null)

if [ -n "$RES" ]; then
    # Wrap in an XML tag so Claude treats this as retrieved context rather
    # than as part of the user prompt. The model is trained to respect such
    # explicit context blocks and to cite them when answering.
    echo "<recalled-memories>"
    echo "Long-term memory hits relevant to the user's current message."
    echo "Cross-agent: search includes facts pushed by other agents on this VPS."
    echo "If a fact answers the user's question, USE it; otherwise ignore."
    echo ""
    echo "$RES"
    echo ""
    echo "</recalled-memories>"
fi

exit 0
