#!/usr/bin/env bash
# UserPromptSubmit hook — detect correction phrases and dispatch to the
# learnings-engine (capture). Triggers cover English, Russian, Ukrainian.
#
# Exit 0 always — never block the agent over a correction signal.
set +e

INPUT="$(cat 2>/dev/null || true)"
[ -z "$INPUT" ] && exit 0

PROMPT="$(printf '%s' "$INPUT" | jq -r '.prompt // ""' 2>/dev/null || true)"
[ -z "$PROMPT" ] && exit 0

# ---------------------------------------------------------------------------
# Trigger lists (lowercased; matched as substrings).
# Tags below are used by the engine to track which language/category fired.
# ---------------------------------------------------------------------------

# English
TRIGGERS_EN=(
    "actually i meant"
    "no, i meant"
    "no i meant"
    "that's wrong"
    "thats wrong"
    "you got that wrong"
    "you misunderstood"
    "stop doing"
    "don't do that"
    "why did you"
    "why are you"
    "you didn't"
    "you forgot"
    "you broke"
    "doesn't work"
    "not working"
    "i told you"
    "i already told you"
    "how many times"
)

# Russian
TRIGGERS_RU=(
    "не надо"
    "не нужно"
    "неправильно"
    "не так"
    "не делай"
    "перестань"
    "почему ты"
    "зачем ты"
    "ты не"
    "ты забыла"
    "ты забыл"
    "ты опять"
    "сломал"
    "сломала"
    "сломано"
    "не работает"
    "я же говорил"
    "я уже говорил"
    "сколько раз"
)

# Ukrainian
TRIGGERS_UK=(
    "не треба"
    "не потрібно"
    "неправильно"
    "не так"
    "не роби"
    "припини"
    "чому ти"
    "навіщо ти"
    "ти не"
    "ти забула"
    "ти забув"
    "ти знову"
    "зламав"
    "зламала"
    "зламано"
    "не працює"
    "я ж казав"
    "я вже казав"
    "скільки разів"
)

LOWER="$(printf '%s' "$PROMPT" | tr '[:upper:]' '[:lower:]')"

MATCHED=""
LANG=""

for t in "${TRIGGERS_EN[@]}"; do
    if printf '%s' "$LOWER" | grep -qF "$t"; then
        MATCHED="$t"; LANG="en"; break
    fi
done
if [ -z "$MATCHED" ]; then
    for t in "${TRIGGERS_RU[@]}"; do
        if printf '%s' "$LOWER" | grep -qF "$t"; then
            MATCHED="$t"; LANG="ru"; break
        fi
    done
fi
if [ -z "$MATCHED" ]; then
    for t in "${TRIGGERS_UK[@]}"; do
        if printf '%s' "$LOWER" | grep -qF "$t"; then
            MATCHED="$t"; LANG="uk"; break
        fi
    done
fi

[ -z "$MATCHED" ] && exit 0

# ---------------------------------------------------------------------------
# Dispatch to learnings-engine. The engine writes to core/episodes.jsonl
# (structured) and updates core/LEARNINGS.md (human-readable summary).
# ---------------------------------------------------------------------------

WS="${AGENT_WORKSPACE:-${HOME}/.claude-lab/$(basename "$(dirname "$(dirname "$(realpath "$0")")")")/.claude}"
ENGINE="${WS}/scripts/learnings-engine.py"

if [ -x "$ENGINE" ] && command -v python3 >/dev/null 2>&1; then
    python3 "$ENGINE" capture \
        --workspace "$WS" \
        --trigger "$MATCHED" \
        --lang "$LANG" \
        --prompt "$PROMPT" \
        2>/dev/null || true
else
    # Fallback: append a marker line to LEARNINGS.md if engine is missing.
    LEARNINGS="${WS}/core/LEARNINGS.md"
    TS=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    {
        echo "- ${TS} CORRECTION-FLAG (lang=${LANG}, trigger=\"${MATCHED}\"): ${PROMPT:0:240}"
    } >>"$LEARNINGS" 2>/dev/null
fi

# Inject feedback into Claude's context (printed to stderr).
printf 'CORRECTION DETECTED (lang=%s, trigger="%s"). Append a one-line lesson to core/LEARNINGS.md describing what to do differently next time.\n' \
    "$LANG" "$MATCHED" >&2

exit 0
