#!/usr/bin/env bash
# PreCompact hook — push current HOT + WARM to L4 before Claude compacts.
# We don't want to lose context-relevant facts that are about to be summarised
# down to a few sentences by the auto-compactor.
set +e

WS="${AGENT_WORKSPACE:-${HOME}/.claude-lab/$(basename "$(dirname "$(dirname "$(realpath "$0")")")")/.claude}"
SYNC="${WS}/scripts/sync-l4.sh"

if [ -x "$SYNC" ]; then
    # OV_FULL=1 ships the entire recent.md, not the cron's last-200-lines tail.
    # Pre-compact is the single moment we MUST keep everything — Claude is about
    # to summarise the buffer and we lose anything not already in OV.
    AGENT_WORKSPACE="$WS" OV_FULL=1 bash "$SYNC" >/dev/null 2>&1 || true
fi

exit 0
