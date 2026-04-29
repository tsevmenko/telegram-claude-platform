#!/usr/bin/env bash
# Back up CLAUDE.md before any self-compiler rewrite.
set -euo pipefail

WS="${AGENT_WORKSPACE:-${PWD}}"
SRC="${WS}/CLAUDE.md"
[ -f "$SRC" ] || { echo "no CLAUDE.md to back up at ${SRC}" >&2; exit 1; }

DEST_DIR="${WS}/core/archive/claude-md-backups"
mkdir -p "$DEST_DIR"
TS=$(date -u '+%Y-%m-%dT%H-%M-%SZ')
cp "$SRC" "${DEST_DIR}/CLAUDE.md.${TS}.bak"
echo "backed up to ${DEST_DIR}/CLAUDE.md.${TS}.bak"
