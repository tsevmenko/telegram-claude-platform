#!/usr/bin/env bash
# self-schedule entry point — schedule a webhook injection.
#
# Usage:
#   schedule.sh once <when-spec> <prompt> [--target <agent>]
#   schedule.sh recurring <cron-expr> <prompt> [--tag <tag>] [--target <agent>]
#
# Identity:
#   <self> = inferred from $AGENT_WORKSPACE basename (e.g. /home/agent/.claude-lab/tyrion → tyrion)
#   --target <agent> overrides the recipient (default = self).
set -euo pipefail

WS="${AGENT_WORKSPACE:-${PWD}}"
SELF="$(basename "$WS")"

mode="${1:-}"
shift || true

TARGET=""
TAG="untagged"
WHEN=""
EXPR=""
PROMPT=""

case "$mode" in
    once)
        # Positional: <when-spec> <prompt>
        WHEN="${1:-}"; shift || true
        PROMPT="${1:-}"; shift || true
        ;;
    recurring)
        # Positional: <cron-expr> <prompt>
        EXPR="${1:-}"; shift || true
        PROMPT="${1:-}"; shift || true
        ;;
    "" | -h | --help)
        cat <<EOF >&2
Usage:
  schedule.sh once <when-spec> "<prompt>" [--target <agent>]
  schedule.sh recurring "<cron-expr>" "<prompt>" [--tag <tag>] [--target <agent>]

Examples:
  schedule.sh once "now + 3 hours" "Check competitors for new reels"
  schedule.sh recurring "0 18 * * 0" "Weekly digest" --tag weekly-digest

When-specs accepted by 'at': "now + N hours|minutes|days", "tomorrow 9am",
"14:30", "noon", absolute "May 5 18:00".

Cron-expr is standard 5 fields: 'minute hour day-of-month month day-of-week'.
EOF
        exit 1
        ;;
    *)
        echo "schedule.sh: unknown mode '$mode' (expected 'once' or 'recurring')" >&2
        exit 1
        ;;
esac

# Optional flags after positional args.
while [ $# -gt 0 ]; do
    case "$1" in
        --target) TARGET="$2"; shift 2 ;;
        --tag)    TAG="$2"; shift 2 ;;
        *) echo "schedule.sh: unknown flag '$1'" >&2; exit 1 ;;
    esac
done

[ -n "$PROMPT" ] || { echo "schedule.sh: missing prompt" >&2; exit 1; }
[ -n "$TARGET" ] || TARGET="$SELF"

# Encode prompt as base64 (no newlines) — survives any quoting/encoding.
B64=$(printf '%s' "$PROMPT" | base64 -w0 2>/dev/null || printf '%s' "$PROMPT" | base64 | tr -d '\n')

case "$mode" in
    once)
        [ -n "$WHEN" ] || { echo "schedule.sh: missing when-spec for 'once'" >&2; exit 1; }
        # Convert short forms to 'at' syntax.
        case "$WHEN" in
            *h)  AT_SPEC="now + ${WHEN%h} hours" ;;
            *m)  AT_SPEC="now + ${WHEN%m} minutes" ;;
            *d)  AT_SPEC="now + ${WHEN%d} days" ;;
            *)   AT_SPEC="$WHEN" ;;
        esac

        # at-job: just call fire-webhook with the encoded prompt.
        AT_OUT=$(at "$AT_SPEC" 2>&1 <<EOF
/opt/agent-installer/bin/fire-webhook "$TARGET" "$B64"
EOF
)
        # Extract the at job id from stderr ("job 42 at Sat May  3 09:00:00 2025").
        ID=$(printf '%s\n' "$AT_OUT" | awk '/^job /{print $2; exit}')
        ID="${ID:-?}"

        # Audit log entry.
        printf '%s | once  | id=%s | target=%s | when="%s" | tag=%s | prompt=%q\n' \
            "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$ID" "$TARGET" "$AT_SPEC" "$TAG" \
            "${PROMPT:0:120}" >>"$WS/core/scheduled.md"

        echo "scheduled once: id=$ID, target=$TARGET, when='$AT_SPEC', tag=$TAG"
        ;;
    recurring)
        [ -n "$EXPR" ] || { echo "schedule.sh: missing cron-expr for 'recurring'" >&2; exit 1; }
        # Delegate to root-owned cron-add binary via narrow sudo grant.
        if ! sudo -n /opt/agent-installer/bin/cron-add add "$TARGET" "$EXPR" "$B64" "$TAG"; then
            echo "schedule.sh: cron-add failed (sudoers grant or validation)" >&2
            exit 1
        fi

        printf '%s | cron  | target=%s | expr="%s" | tag=%s | prompt=%q\n' \
            "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$TARGET" "$EXPR" "$TAG" \
            "${PROMPT:0:120}" >>"$WS/core/scheduled.md"

        echo "scheduled recurring: target=$TARGET, expr='$EXPR', tag=$TAG"
        ;;
esac
