#!/usr/bin/env bash
# UserPromptSubmit hook — detect correction phrases and append to LEARNINGS.md.
# Exit 0 always (we never block the agent over a correction signal).
set +e

INPUT="$(cat 2>/dev/null || true)"
[ -z "$INPUT" ] && exit 0

PROMPT="$(printf '%s' "$INPUT" | jq -r '.prompt // ""' 2>/dev/null || true)"
[ -z "$PROMPT" ] && exit 0

# Trigger phrases — both English and a few common Russian variants.
TRIGGERS=(
    "actually i meant"
    "no, i meant"
    "no i meant"
    "that's wrong"
    "thats wrong"
    "you got that wrong"
    "you misunderstood"
    "stop doing"
    "don't do that"
    "не надо"
    "не нужно"
    "неправильно"
    "не так"
    "ты опять"
    "сколько раз"
)

LOWER="$(printf '%s' "$PROMPT" | tr '[:upper:]' '[:lower:]')"
MATCHED=""
for trigger in "${TRIGGERS[@]}"; do
    if printf '%s' "$LOWER" | grep -qF "$trigger"; then
        MATCHED="$trigger"
        break
    fi
done

[ -z "$MATCHED" ] && exit 0

WS="${AGENT_WORKSPACE:-${HOME}/.claude-lab/$(basename "$(dirname "$(dirname "$(realpath "$0")")")")/.claude}"
LEARNINGS="${WS}/core/LEARNINGS.md"
TS=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

# Append a marker. The agent itself is responsible for writing the actual
# lesson body — this hook just flags the correction event.
{
    echo "- ${TS} CORRECTION-FLAG (trigger=\"${MATCHED}\"): ${PROMPT:0:240}"
} >>"$LEARNINGS" 2>/dev/null

# Inject feedback into Claude's context (printed to stderr, surfaced as an
# additional system message in claude-code).
printf 'CORRECTION DETECTED. Append a one-line lesson to core/LEARNINGS.md describing what to do differently.\n' >&2
exit 0
