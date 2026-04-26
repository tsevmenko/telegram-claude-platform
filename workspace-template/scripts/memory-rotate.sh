#!/usr/bin/env bash
# memory-rotate.sh — Archive COLD memory when MEMORY.md exceeds 5KB.
# Copies the file to core/archive/YYYY-MM.md and resets MEMORY.md to a header.
set -euo pipefail

WS="${AGENT_WORKSPACE:-${HOME}/.claude-lab/$(basename "$(dirname "$(dirname "$(realpath "$0")")")")/.claude}"
COLD="${WS}/core/MEMORY.md"
ARCHIVE_DIR="${WS}/core/archive"
LOG="/tmp/memory-rotate.log"
THRESHOLD="${THRESHOLD:-5000}"

echo "=== memory-rotate.sh $(date -u '+%Y-%m-%dT%H:%M:%SZ') ===" >>"$LOG"

[ -f "$COLD" ] || { echo "no MEMORY.md" >>"$LOG"; exit 0; }

SIZE=$(wc -c <"$COLD")
echo "MEMORY.md=${SIZE}b (threshold=${THRESHOLD}b)" >>"$LOG"

if [ "$SIZE" -lt "$THRESHOLD" ]; then
    echo "below threshold, skip" >>"$LOG"
    exit 0
fi

mkdir -p "$ARCHIVE_DIR"
MONTH=$(date -u '+%Y-%m')
cp "$COLD" "${ARCHIVE_DIR}/${MONTH}.md"
echo "archived to archive/${MONTH}.md" >>"$LOG"

# Keep just the canonical header.
cat >"$COLD" <<'EOF'
# MEMORY — COLD archive

_Permanent archive. NOT loaded into session context._
_Read on demand via the `Read` tool when older context is needed._
_Entries rotated here from WARM (>14 days) by `rotate-warm.sh`._
_When this file exceeds 5KB, `memory-rotate.sh` archives it to `core/archive/YYYY-MM.md`._
EOF
echo "MEMORY.md reset to header" >>"$LOG"
