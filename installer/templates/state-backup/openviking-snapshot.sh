#!/usr/bin/env bash
# openviking-snapshot — daily SQLite dump of the L4 semantic-memory store.
# Lives in shared/ inside the state-backup repo so cross-agent memory
# survives VPS death. Restore: `sqlite3 <path> < shared/ov-YYYY-MM-DD.sql`.
set -euo pipefail

REPO_DIR="/var/lib/agent-state-backup"
SHARED="$REPO_DIR/shared"
mkdir -p "$SHARED"

# Find the OV SQLite db. Default location for openviking-lite.
OV_DB="${OV_DB:-/var/lib/openviking/openviking.db}"
[[ -f "$OV_DB" ]] || OV_DB="/var/lib/openviking-lite/openviking.db"
[[ -f "$OV_DB" ]] || { echo "openviking db not found"; exit 0; }

DATE_TAG="$(date -u +%Y-%m-%d)"
OUT="$SHARED/ov-snapshot-${DATE_TAG}.sql.gz"

# .dump produces a portable SQL stream that re-creates the db on any
# platform. -readonly avoids locking the live db.
sqlite3 -readonly "$OV_DB" .dump | gzip -9 > "$OUT"
echo "openviking snapshot → $OUT ($(stat -c%s "$OUT" 2>/dev/null || stat -f%z "$OUT") bytes)"

# Keep last 14 daily snapshots; older snapshots get pruned (commit history
# in git still has them indefinitely if needed).
find "$SHARED" -name "ov-snapshot-*.sql.gz" -mtime +14 -delete 2>/dev/null || true
