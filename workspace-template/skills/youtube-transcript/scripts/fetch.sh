#!/usr/bin/env bash
# Fetch YouTube transcript via yt-dlp (preferred) or TranscriptAPI (fallback).
set -euo pipefail

URL="${1:?Usage: fetch.sh <youtube-url>}"

if command -v yt-dlp >/dev/null 2>&1; then
    TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
    if yt-dlp --quiet --skip-download --write-auto-subs --sub-format vtt \
        --sub-langs "en,ru,en-US" \
        -o "${TMP}/%(id)s.%(ext)s" "$URL" 2>/dev/null; then
        SUB=$(find "$TMP" -name '*.vtt' | head -n 1 || true)
        if [ -n "$SUB" ] && [ -f "$SUB" ]; then
            # Strip WEBVTT cues to plain "MM:SS  text" lines.
            awk '
                /^WEBVTT/ { next }
                /^[0-9]+:[0-9]+/ {
                    split($1, a, ".");
                    ts = a[1];
                    next
                }
                NF > 0 { gsub(/<[^>]+>/, ""); print ts "  " $0 }
            ' "$SUB" | awk '!seen[$0]++'
            exit 0
        fi
    fi
fi

KEY_FILE="${HOME}/.claude-lab/shared/secrets/transcript-api.key"
if [ -f "$KEY_FILE" ]; then
    KEY="$(cat "$KEY_FILE")"
    VID=$(echo "$URL" | sed -E 's#.*[?&]v=([^&]+).*#\1#; s#.*/shorts/([^?&/]+).*#\1#; s#.*/embed/([^?&/]+).*#\1#')
    [ -z "$VID" ] && { echo "could not extract video id from $URL" >&2; exit 1; }
    curl -sS --fail --max-time 30 \
        "https://api.transcriptapi.com/v1/transcripts/${VID}" \
        -H "Authorization: Bearer ${KEY}" \
        | jq -r '.transcript // .text // empty'
    exit 0
fi

echo "no transcript backend available — install yt-dlp or set transcript-api.key" >&2
exit 1
