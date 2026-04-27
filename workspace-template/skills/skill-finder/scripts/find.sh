#!/usr/bin/env bash
# Search public skill catalogues for a query. Returns JSON.
set -euo pipefail

QUERY="${1:?Usage: find.sh <query>}"
URL_QUERY=$(jq -rn --arg q "$QUERY" '$q | @uri')

# 1. skills.sh public registry (best-effort).
SKILLS_SH_URL="https://skills.sh/api/v1/search?q=${URL_QUERY}&limit=20"
RESP=$(curl -sS --fail --max-time 8 "$SKILLS_SH_URL" 2>/dev/null) || RESP=""

if [ -n "$RESP" ] && echo "$RESP" | jq -e 'type == "object" or type == "array"' >/dev/null 2>&1; then
    echo "$RESP" | jq '
        if type == "array" then . else (.results // .items // .) end
        | map({name: (.name // .title // ""),
               description: (.description // .summary // ""),
               source: (.source // .repo // .url // .html_url // "")})
        | map(select(.name != ""))
    '
    exit 0
fi

# 2. GitHub topic search fallback. Requires gh authenticated.
if command -v gh >/dev/null 2>&1; then
    gh search repos "$QUERY" --topic claude-skill --limit 20 --json name,description,url 2>/dev/null \
        | jq 'map({name: .name, description: .description, source: .url})' \
        || echo "[]"
    exit 0
fi

# 3. Plain GitHub API search (anonymous, rate-limited).
curl -sS --fail --max-time 8 \
    "https://api.github.com/search/repositories?q=${URL_QUERY}+topic:claude-skill&per_page=20" \
    2>/dev/null \
    | jq '.items // [] | map({name: .name, description: .description, source: .html_url})' \
    || echo "[]"
