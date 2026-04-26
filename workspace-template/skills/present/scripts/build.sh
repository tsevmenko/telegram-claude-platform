#!/usr/bin/env bash
# Build a reveal.js HTML deck from a Markdown file.
# Usage: build.sh <title> <markdown-file>
set -euo pipefail

TITLE="${1:?Usage: build.sh <title> <md-file>}"
SRC="${2:?missing markdown file}"
[ -f "$SRC" ] || { echo "file not found: $SRC" >&2; exit 1; }

command -v pandoc >/dev/null || { echo "pandoc not installed" >&2; exit 1; }

THEME="${REVEAL_THEME:-black}"
OUT="/tmp/deck-$(date +%s).html"

pandoc -t revealjs --standalone \
    --metadata title="$TITLE" \
    -V revealjs-url="https://cdn.jsdelivr.net/npm/reveal.js@4.6.1" \
    -V theme="$THEME" \
    -V transition=slide \
    -o "$OUT" \
    "$SRC"

echo "$OUT"
