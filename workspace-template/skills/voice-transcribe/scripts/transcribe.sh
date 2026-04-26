#!/usr/bin/env bash
# Transcribe an audio file via Groq Whisper API.
# Usage: bash transcribe.sh <audio-file>
set -euo pipefail

FILE_PATH="${1:?Usage: transcribe.sh <audio-file>}"
[ -f "$FILE_PATH" ] || { echo "file not found: $FILE_PATH" >&2; exit 1; }

KEY_FILE="${HOME}/.claude-lab/shared/secrets/groq.key"
[ -f "$KEY_FILE" ] || { echo "Groq key not found at $KEY_FILE" >&2; exit 1; }
GROQ_API_KEY="$(cat "$KEY_FILE")"

curl -sS --fail --max-time 60 \
    "https://api.groq.com/openai/v1/audio/transcriptions" \
    -H "Authorization: Bearer ${GROQ_API_KEY}" \
    -F "file=@${FILE_PATH}" \
    -F "model=whisper-large-v3-turbo" \
    -F "response_format=text"
