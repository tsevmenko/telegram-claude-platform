#!/usr/bin/env bash
# Dedup guard — reject re-fetches for a given (handle, operation) pair if
# a recent (< 7 days) artifact already exists on disk. Live regression
# 2026-05-02: Tyrion bulk-fetched maxshirko 4 times in 48 hours, dashi 2
# times in 36 minutes — pure waste because IG state hadn't materially
# changed between calls. Dedup forces operator opt-in (`--force`) for
# expensive re-do.
#
# Sourcing convention:
#   source "$SKILL_DIR/scripts/_dedup-guard.sh"
#   dedup_guard_check "$HANDLE" "bulk" "$FORCE"   # exits 2 if recent file exists
#
# FORCE=1 skips the check (operator-blessed re-fetch).

_DEDUP_SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}")/.." && pwd)"
_DEDUP_OUT_DIR="$_DEDUP_SKILL_DIR/out"
_DEDUP_WINDOW_SEC="${DEDUP_WINDOW_SEC:-$((7 * 86400))}"  # 7 days

# dedup_guard_check HANDLE OP_TAG FORCE
dedup_guard_check() {
    local handle="$1" op="$2" force="$3"
    [[ "$force" == "1" ]] && return 0
    [[ -d "$_DEDUP_OUT_DIR" ]] || return 0

    local now; now="$(date +%s)"
    local cutoff=$((now - _DEDUP_WINDOW_SEC))
    local found=""

    # Look for ${handle}-${op}-*.json files
    while IFS= read -r f; do
        [[ -z "$f" ]] && continue
        local mtime
        # GNU stat first (Linux); fallback BSD stat (macOS, for tests)
        mtime="$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null || echo 0)"
        if [[ "$mtime" -gt "$cutoff" ]]; then
            found="$f"
            break
        fi
    done < <(find "$_DEDUP_OUT_DIR" -maxdepth 1 -name "${handle}-${op}-*.json" 2>/dev/null)

    if [[ -n "$found" ]]; then
        local age_h=$(( (now - mtime) / 3600 ))
        echo "DEDUP: recent ${op} for @${handle} found (${age_h}h ago):" >&2
        echo "  $found" >&2
        echo "  consider analyzing this file directly without re-scrape." >&2
        echo "  if a fresh fetch is required, re-run with --force." >&2
        exit 2
    fi
}
