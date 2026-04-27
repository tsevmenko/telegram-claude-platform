#!/usr/bin/env bash
# PreCompact hook — push current HOT + WARM to L4 before Claude compacts.
# We don't want to lose context-relevant facts that are about to be summarised
# down to a few sentences by the auto-compactor.
set +e

WS="${AGENT_WORKSPACE:-${HOME}/.claude-lab/$(basename "$(dirname "$(dirname "$(realpath "$0")")")")/.claude}"
SYNC="${WS}/scripts/sync-l4.sh"

if [ -x "$SYNC" ]; then
    AGENT_WORKSPACE="$WS" bash "$SYNC" >/dev/null 2>&1 || true
fi

exit 0
