#!/usr/bin/env bash
# PostToolUse hook (Edit | Write matcher) — count edits within a session
# and remind to run a code review after a threshold of changes.
#
# Output to stderr (gets surfaced to Claude as "additional system message").
# Counter persisted at /tmp/<agent>-review-count for the current process tree.
set +e

INPUT="$(cat 2>/dev/null || true)"
[ -z "$INPUT" ] && exit 0

TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null)"
[ "$TOOL" != "Edit" ] && [ "$TOOL" != "Write" ] && exit 0

THRESHOLD="${REVIEW_REMINDER_THRESHOLD:-10}"
SESSION="$(printf '%s' "$INPUT" | jq -r '.session_id // "default"' 2>/dev/null)"
COUNTER="/tmp/.review-count.${SESSION}"

# Increment.
n=0
[ -f "$COUNTER" ] && n=$(cat "$COUNTER" 2>/dev/null || echo 0)
n=$((n + 1))
printf '%d' "$n" >"$COUNTER"

# Fire reminder once when threshold crossed (n == threshold), then every
# THRESHOLD edits after that.
if [ "$n" -ge "$THRESHOLD" ] && [ $((n % THRESHOLD)) -eq 0 ]; then
    cat <<EOF >&2
You have made ${n} edits this session without an explicit review.
Before continuing, consider:
  - run the project's code review tool (gh pr create, claude-review, codex review)
  - read the diff yourself with 'git diff' or 'git diff --staged'
  - run tests for the affected modules
This is a soft reminder; you can keep editing if the work is mid-flow.
EOF
fi

exit 0
