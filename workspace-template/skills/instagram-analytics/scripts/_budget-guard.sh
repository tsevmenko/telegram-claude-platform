#!/usr/bin/env bash
# Budget guard — sourced by ScrapeCreators-billing scripts to refuse calls
# that would push us over a daily or total credit limit. Live regression
# 2026-05-02: operator panicked when ~355 credits got burned across two
# days of exploratory bulk-fetches with --with-transcripts (default-on
# in earlier versions). Real damage was small but the pattern was scary
# — multiple bulks for same handle, no de-dup, no awareness of cost.
#
# State file: <skill>/state/budget.json
#
# Behaviour:
#  - On first call ever: creates state file with default limits.
#  - Resets daily counter automatically when UTC date changes.
#  - Hard kill-switch via `disabled: true` field — refuses ALL calls.
#  - Reports CURRENT spend in stderr before letting call through.
#
# Sourcing convention:
#   source "$SKILL_DIR/scripts/_budget-guard.sh"
#   budget_guard_check "bulk-fetch" 80   # estimated credits for this op
#   ... do API calls ...
#   budget_guard_record "bulk-fetch" 75  # actual credits used
#
# Bumping limits (operator):
#   jq '.daily_limit = 1000' <skill>/state/budget.json
#   jq '.disabled = false'   <skill>/state/budget.json   # re-enable

# Resolve skill dir from caller's location. ${BASH_SOURCE[1]} is the
# sourcing script (bulk-fetch.sh / analyze.sh / etc.); we go up two
# (scripts/<file> → scripts → skill-root).
_BUDGET_SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}")/.." && pwd)"
_BUDGET_FILE="$_BUDGET_SKILL_DIR/state/budget.json"

# Conservative defaults — bumpable by editing the JSON.
_BUDGET_DAILY_DEFAULT=500
_BUDGET_TOTAL_DEFAULT=5000

_budget_init() {
    if [[ ! -f "$_BUDGET_FILE" ]]; then
        mkdir -p "$(dirname "$_BUDGET_FILE")"
        cat >"$_BUDGET_FILE" <<EOF
{
  "_doc": "ScrapeCreators credit budget for instagram-analytics. Edit limits to bump; set disabled:true for kill-switch.",
  "daily_limit": $_BUDGET_DAILY_DEFAULT,
  "total_limit": $_BUDGET_TOTAL_DEFAULT,
  "spent_today": 0,
  "spent_total": 0,
  "last_reset_date": "$(date -u +%F)",
  "last_op": null,
  "last_op_ts": null,
  "disabled": false
}
EOF
    fi

    # Reset daily counter if UTC date changed.
    local today; today="$(date -u +%F)"
    local stored; stored="$(jq -r '.last_reset_date // ""' "$_BUDGET_FILE")"
    if [[ "$today" != "$stored" ]]; then
        local tmp; tmp="$(mktemp)"
        jq --arg d "$today" '.spent_today = 0 | .last_reset_date = $d' \
           "$_BUDGET_FILE" >"$tmp" && mv "$tmp" "$_BUDGET_FILE"
    fi
}

# budget_guard_check OP_NAME ESTIMATED_CREDITS
budget_guard_check() {
    local op="$1" est="$2"
    _budget_init

    if [[ "$(jq -r '.disabled' "$_BUDGET_FILE")" == "true" ]]; then
        echo "BUDGET: kill-switch engaged — instagram-analytics disabled by operator." >&2
        echo "  re-enable: jq '.disabled = false' $_BUDGET_FILE | sponge $_BUDGET_FILE" >&2
        exit 2
    fi

    local d_lim; d_lim="$(jq -r '.daily_limit'  "$_BUDGET_FILE")"
    local t_lim; t_lim="$(jq -r '.total_limit'  "$_BUDGET_FILE")"
    local d_sp;  d_sp="$(jq -r '.spent_today'  "$_BUDGET_FILE")"
    local t_sp;  t_sp="$(jq -r '.spent_total'  "$_BUDGET_FILE")"
    local would_d=$((d_sp + est))
    local would_t=$((t_sp + est))

    if [[ "$would_d" -gt "$d_lim" ]]; then
        echo "BUDGET: over daily limit on op=$op." >&2
        echo "  spent_today=$d_sp, est=$est, would_be=$would_d, limit=$d_lim" >&2
        echo "  bump: jq '.daily_limit = NEW_VALUE' $_BUDGET_FILE | sponge $_BUDGET_FILE" >&2
        exit 2
    fi
    if [[ "$would_t" -gt "$t_lim" ]]; then
        echo "BUDGET: over total limit on op=$op." >&2
        echo "  spent_total=$t_sp, est=$est, would_be=$would_t, limit=$t_lim" >&2
        echo "  reset/bump in $_BUDGET_FILE" >&2
        exit 2
    fi

    echo "  budget OK: op=$op est=$est | day $d_sp/$d_lim → $would_d | total $t_sp/$t_lim → $would_t" >&2
}

# budget_guard_record OP_NAME ACTUAL_CREDITS
budget_guard_record() {
    local op="$1" actual="$2"
    _budget_init
    local tmp; tmp="$(mktemp)"
    jq --arg op "$op" \
       --arg ts "$(date -u +%FT%TZ)" \
       --argjson c "$actual" \
       '.spent_today += $c
        | .spent_total += $c
        | .last_op = $op
        | .last_op_ts = $ts' \
       "$_BUDGET_FILE" >"$tmp" && mv "$tmp" "$_BUDGET_FILE"
}
