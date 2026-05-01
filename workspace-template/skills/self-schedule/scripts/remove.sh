#!/usr/bin/env bash
# self-schedule remove — drop a scheduled trigger.
#
# Usage:
#   remove.sh recurring <line-number>   # line-number from `list.sh` recurring section
#   remove.sh once <at-job-id>          # job id from `list.sh` once section
set -euo pipefail

WS="${AGENT_WORKSPACE:-${PWD}}"
SELF="$(basename "$WS")"

mode="${1:-}"
arg="${2:-}"

[ -n "$mode" ] && [ -n "$arg" ] || {
    echo "Usage: remove.sh recurring <line-number> | once <at-job-id>" >&2
    exit 1
}

case "$mode" in
    recurring)
        if ! [[ "$arg" =~ ^[0-9]+$ ]]; then
            echo "remove.sh: line-number must be numeric" >&2; exit 1
        fi
        sudo -n /opt/agent-installer/bin/cron-add remove "$SELF" "$arg"
        printf '%s | rm cron  | line=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$arg" \
            >>"$WS/core/scheduled.md"
        ;;
    once)
        if ! [[ "$arg" =~ ^[0-9]+$ ]]; then
            echo "remove.sh: at-job-id must be numeric" >&2; exit 1
        fi
        atrm "$arg"
        printf '%s | rm once  | id=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$arg" \
            >>"$WS/core/scheduled.md"
        ;;
    *)
        echo "remove.sh: unknown mode '$mode' (expected 'recurring' or 'once')" >&2
        exit 1
        ;;
esac

echo "removed: $mode $arg"
