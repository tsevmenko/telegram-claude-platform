#!/usr/bin/env bash
# Run an independent code review via OpenAI GPT-5 / Codex.
# Modes: standard (default), adversarial.
set -euo pipefail

MODE="standard"
DIFF_FROM="HEAD"
FILE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --mode)       MODE="$2"; shift 2 ;;
        --diff-from)  DIFF_FROM="$2"; shift 2 ;;
        --file)       FILE="$2"; shift 2 ;;
        -h|--help)
            grep -E '^# ' "$0" | sed 's/^# \?//'
            exit 0 ;;
        *) echo "unknown flag: $1" >&2; exit 1 ;;
    esac
done

KEY_FILE="${HOME}/.claude-lab/shared/secrets/openai.key"
[ -f "$KEY_FILE" ] || { echo "OpenAI key not found at $KEY_FILE" >&2; exit 1; }
KEY="$(cat "$KEY_FILE")"

# Collect the diff or single-file content.
if [ -n "$FILE" ]; then
    [ -f "$FILE" ] || { echo "file not found: $FILE" >&2; exit 1; }
    DIFF=$(cat "$FILE")
    SUBJECT="single file: ${FILE}"
else
    if [ "$DIFF_FROM" = "HEAD" ]; then
        DIFF=$(git diff HEAD 2>/dev/null; git diff --staged 2>/dev/null)
    else
        DIFF=$(git diff "${DIFF_FROM}...HEAD" 2>/dev/null)
    fi
    SUBJECT="diff against ${DIFF_FROM}"
fi

if [ -z "${DIFF// }" ]; then
    echo "Nothing to review (empty diff)." >&2
    exit 0
fi

# Cap input size at ~80K chars (~20K tokens) — anything beyond is partial review.
DIFF=$(printf '%s' "$DIFF" | head -c 80000)

case "$MODE" in
    standard)
        SYSTEM="You are an independent senior engineer reviewing a diff. \
Focus on real bugs, missing tests, edge cases, security issues, footguns. \
Be terse. Group findings by severity (critical/high/medium/nit). \
Skip style nits unless they hide bugs. If the diff is fine, say so in one line."
        ;;
    adversarial)
        SYSTEM="You are an adversarial security reviewer. Assume the author is hostile or careless. \
Find ways this code can be exploited, abused, run at unexpected scale, or fail under malformed input. \
Output a threat-model: attack vector / preconditions / impact / mitigation. \
Skip stylistic feedback. If the diff is genuinely safe, say so and stop."
        ;;
    *)
        echo "unknown mode: $MODE (use standard|adversarial)" >&2
        exit 1
        ;;
esac

USER_MSG="Review the following ${SUBJECT}.

\`\`\`diff
${DIFF}
\`\`\`"

# Use OpenAI's chat-completions API. Model selection prefers gpt-5-mini for
# cost; bump to gpt-5 if OPENAI_REVIEW_MODEL is set.
MODEL="${OPENAI_REVIEW_MODEL:-gpt-5-mini}"

REQUEST=$(jq -nc --arg m "$MODEL" --arg sys "$SYSTEM" --arg usr "$USER_MSG" '{
    model: $m,
    messages: [
        {role: "system", content: $sys},
        {role: "user",   content: $usr}
    ],
    temperature: 0.1
}')

RESP=$(curl -sS --fail --max-time 120 \
    "https://api.openai.com/v1/chat/completions" \
    -H "Authorization: Bearer ${KEY}" \
    -H "Content-Type: application/json" \
    -d "$REQUEST" 2>&1)

if ! echo "$RESP" | jq -e '.choices[0].message.content' >/dev/null 2>&1; then
    echo "OpenAI API error:" >&2
    echo "$RESP" | head -c 500 >&2
    exit 1
fi

echo "$RESP" | jq -r '.choices[0].message.content'
