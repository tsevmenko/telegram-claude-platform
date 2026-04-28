#!/usr/bin/env bash
# UserPromptSubmit hook — fast local fallback for memory recall.
#
# Why: auto-recall.sh queries L4 (OpenViking) over HTTP. If OV is down,
# misconfigured, or just slow, we still want some context surfaced. This
# hook does a cheap grep over local memory files and emits the hits inside
# a `<local-context>` XML tag that mirrors `<recalled-memories>`.
#
# It runs IN ADDITION to auto-recall.sh — both fire on UserPromptSubmit.
# Claude is trained to handle multiple recall blocks gracefully.
#
# Always exits 0; never blocks the prompt. Silent on no hits.
set +e

INPUT="$(cat 2>/dev/null || true)"
[ -z "$INPUT" ] && exit 0

PROMPT="$(printf '%s' "$INPUT" | jq -r '.prompt // ""' 2>/dev/null || true)"
WORDS=$(printf '%s' "$PROMPT" | wc -w | tr -d ' ')
# Same gate as auto-recall: don't waste cycles on tiny prompts.
[ "$WORDS" -lt 3 ] && exit 0

# Resolve workspace root. The hook lives at <workspace>/hooks/local-recall.sh,
# so workspace is one level up.
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE="$(dirname "$HOOK_DIR")"

# Files to grep, in priority order. All optional — skip silently if missing.
FILES=(
    "$WORKSPACE/core/TOOLS.md"
    "$WORKSPACE/core/AGENTS.md"
    "$WORKSPACE/core/LEARNINGS.md"
    "$WORKSPACE/core/warm/decisions.md"
)

# Extract keywords: lowercase, drop punctuation, tokens > 3 chars, dedup,
# drop common stop-words. Tools like ``tr -dc`` are POSIX-portable.
STOPWORDS="the and for that with this from your you are have has not but how what when where which who why need like just only some more most very also been was were can could should would will did does done"
KEYWORDS="$(printf '%s' "$PROMPT" \
    | tr '[:upper:]' '[:lower:]' \
    | tr -c '[:alnum:]_\n ' ' ' \
    | tr ' ' '\n' \
    | awk 'length($0) > 3' \
    | sort -u \
    | grep -vxFf <(printf '%s\n' $STOPWORDS) 2>/dev/null \
    | head -8)"

[ -z "$KEYWORDS" ] && exit 0

HITS=""
for f in "${FILES[@]}"; do
    [ -r "$f" ] || continue
    while IFS= read -r kw; do
        # Case-insensitive grep, max 3 lines per keyword per file, with line numbers.
        match="$(grep -inF -m 3 "$kw" "$f" 2>/dev/null)"
        if [ -n "$match" ]; then
            rel="${f#$WORKSPACE/}"
            while IFS= read -r line; do
                # Strip line numbers, condense whitespace, cap line length at 240 chars.
                snippet="$(printf '%s' "$line" | sed 's/^[0-9]*://' | tr -s '[:space:]' ' ' | cut -c1-240)"
                [ -n "$snippet" ] && HITS="${HITS}- ${rel}: ${snippet}"$'\n'
            done <<< "$match"
        fi
    done <<< "$KEYWORDS"
done

# Dedup: same line may match multiple keywords. Preserve first-occurrence order.
if [ -n "$HITS" ]; then
    HITS="$(printf '%s' "$HITS" | awk '!seen[$0]++')"
    # Cap total output at ~6KB so we don't blow context budget on a chatty workspace.
    truncated="$(printf '%s' "$HITS" | head -c 6144)"
    echo "<local-context>"
    echo "Local-file hits for keywords from your prompt. Same-VPS only — no external query."
    echo "Use if relevant; ignore if not."
    echo ""
    printf '%s' "$truncated"
    echo ""
    echo "</local-context>"
fi

exit 0
