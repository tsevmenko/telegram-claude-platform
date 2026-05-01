#!/usr/bin/env bash
# self-schedule list — show all scheduled triggers for self.
set -euo pipefail

WS="${AGENT_WORKSPACE:-${PWD}}"
SELF="$(basename "$WS")"

echo "=== recurring (cron) — /etc/cron.d/agent-personal-${SELF} ==="
if ! sudo -n /opt/agent-installer/bin/cron-add list "$SELF" 2>&1; then
    echo "(none — no cron file yet)"
fi

echo ""
echo "=== once (at-jobs for $(whoami)) ==="
if command -v atq >/dev/null 2>&1; then
    atq | sort -k2,2 -k3,3 -k4,4 -k5,5 || echo "(none)"
else
    echo "atq not available — at daemon not installed?"
fi

echo ""
echo "=== audit log: ${WS}/core/scheduled.md ==="
if [ -f "${WS}/core/scheduled.md" ]; then
    tail -20 "${WS}/core/scheduled.md"
else
    echo "(no scheduled.md yet)"
fi
