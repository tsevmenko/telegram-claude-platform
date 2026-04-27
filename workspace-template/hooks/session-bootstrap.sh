#!/usr/bin/env bash
# SessionStart hook — preload top-5 learnings + open inbox + heartbeat.
#
# stdout from a SessionStart hook is injected into Claude's session context,
# so we use it to surface the most relevant lessons-from-mistakes at session
# start. Non-fatal: if anything is missing we still return 0.
set +e

WS="${AGENT_WORKSPACE:-${HOME}/.claude-lab/$(basename "$(dirname "$(dirname "$(realpath "$0")")")")/.claude}"
ENGINE="${WS}/scripts/learnings-engine.py"
INBOX="${WS}/core/inbox.md"
HEARTBEAT="${WS}/core/heartbeat.json"

# 1. Mark the agent as online.
TS=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
printf '{"online":true,"started_at":"%s","pid":%d}\n' "$TS" "$$" >"$HEARTBEAT" 2>/dev/null

# 2. Top-5 active learnings by composite score, formatted for Claude context.
if command -v python3 >/dev/null 2>&1 && [ -x "$ENGINE" ]; then
    SCORED=$(python3 "$ENGINE" score --workspace "$WS" --format json 2>/dev/null)
    if [ -n "$SCORED" ]; then
        TOP=$(printf '%s' "$SCORED" \
            | jq -r 'map(select(.status == "active")) | .[:5]
                     | map("- (score=" + (.score|tostring)
                           + ", freq=" + (.freq|tostring)
                           + ", lang=" + .lang
                           + ", trigger=\"" + .trigger + "\")") | .[]' 2>/dev/null)
        if [ -n "$TOP" ]; then
            echo "## Active learnings (top 5 by score)"
            echo ""
            echo "These are corrections the operator has flagged. Avoid repeating them."
            echo ""
            echo "$TOP"
            echo ""
        fi
    fi
fi

# 3. Inbox messages from external systems (webhook, cron) — surface them once.
if [ -s "$INBOX" ]; then
    echo "## Inbox (unread)"
    echo ""
    head -c 4000 "$INBOX"
    echo ""
    # Move to processed.
    PROCESSED="${WS}/core/inbox-processed.md"
    {
        echo "## $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
        cat "$INBOX"
        echo ""
    } >>"$PROCESSED" 2>/dev/null
    : >"$INBOX"
fi

exit 0
