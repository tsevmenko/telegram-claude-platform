#!/usr/bin/env bash
# Web research via Perplexity Sonar (preferred) or DuckDuckGo (fallback).
set -euo pipefail

QUERY="${1:?Usage: research.sh <query>}"
KEY_FILE="${HOME}/.claude-lab/shared/secrets/perplexity.key"

if [ -f "$KEY_FILE" ]; then
    PPLX_KEY="$(cat "$KEY_FILE")"
    BODY=$(jq -nc --arg q "$QUERY" '{
        model: "sonar",
        messages: [
            {role: "system", content: "Be precise. Cite sources inline as [n]."},
            {role: "user", content: $q}
        ]
    }')
    RESP=$(curl -sS --fail --max-time 30 \
        "https://api.perplexity.ai/chat/completions" \
        -H "Authorization: Bearer ${PPLX_KEY}" \
        -H "Content-Type: application/json" \
        -d "$BODY") || RESP=""
    if [ -n "$RESP" ]; then
        echo "$RESP" | jq -r '.choices[0].message.content // empty'
        echo ""
        echo "Sources:"
        echo "$RESP" | jq -r '.citations // [] | .[]' | nl
        exit 0
    fi
    echo "Perplexity failed; falling back to DuckDuckGo." >&2
fi

# DuckDuckGo Instant Answer fallback. Quality is lower but no key required.
URL_QUERY=$(jq -rn --arg q "$QUERY" '$q | @uri')
RESP=$(curl -sS --fail --max-time 15 \
    "https://api.duckduckgo.com/?q=${URL_QUERY}&format=json&no_html=1") || {
    echo "DuckDuckGo also failed." >&2
    exit 1
}
echo "$RESP" | jq -r '
    .Heading + "\n\n" + .AbstractText +
    (if .RelatedTopics then "\n\nRelated:\n" + (
        .RelatedTopics | map(.Text // empty) | map(select(. != "")) | join("\n- ")
    ) else "" end)
'
