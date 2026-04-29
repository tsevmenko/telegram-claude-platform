#!/usr/bin/env bash
# Stop hook — mark the agent as offline in core/heartbeat.json.
# Vesna's `/status` admin command reads this file to report each agent's state.
set +e

WS="${AGENT_WORKSPACE:-${PWD}}"
HEARTBEAT="${WS}/core/heartbeat.json"
TS=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

# Preserve started_at if present so /status can report uptime.
STARTED=""
if [ -f "$HEARTBEAT" ] && command -v jq >/dev/null 2>&1; then
    STARTED=$(jq -r '.started_at // empty' "$HEARTBEAT" 2>/dev/null)
fi

if [ -n "$STARTED" ]; then
    printf '{"online":false,"started_at":"%s","stopped_at":"%s"}\n' "$STARTED" "$TS" \
        >"$HEARTBEAT" 2>/dev/null
else
    printf '{"online":false,"stopped_at":"%s"}\n' "$TS" >"$HEARTBEAT" 2>/dev/null
fi

exit 0
