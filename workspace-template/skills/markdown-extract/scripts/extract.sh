#!/usr/bin/env bash
# Fetch a URL and return clean Markdown via Jina AI Reader.
set -euo pipefail

URL="${1:?Usage: extract.sh <url>}"
case "$URL" in
    http://*|https://*) ;;
    *) echo "URL must start with http:// or https://" >&2; exit 1 ;;
esac

PROXIED="https://r.jina.ai/${URL}"

if curl -sSL --fail --max-time 30 \
    -H "Accept: text/markdown" \
    "$PROXIED" 2>/dev/null; then
    exit 0
fi

# Fallback: fetch raw and pipe through pandoc if available.
if command -v pandoc >/dev/null 2>&1; then
    curl -sSL --max-time 30 "$URL" | pandoc -f html -t markdown_strict --wrap=preserve
else
    echo "r.jina.ai unreachable and pandoc not installed for fallback." >&2
    exit 1
fi
