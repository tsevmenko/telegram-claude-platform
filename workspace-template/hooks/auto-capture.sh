#!/usr/bin/env bash
# Stop hook — final L4 push of fresh HOT entries before the session ends.
#
# Difference from sync-l4.sh (which is a daily cron): this fires on every
# session-end, so day-over-day new memories are persisted even if the cron
# doesn't run for some reason. Idempotent on the OV side (same date → same URI).
set +e

WS="${AGENT_WORKSPACE:-${PWD}}"
SYNC="${WS}/scripts/sync-l4.sh"

if [ -x "$SYNC" ]; then
    AGENT_WORKSPACE="$WS" bash "$SYNC" >/dev/null 2>&1 || true
fi

exit 0
