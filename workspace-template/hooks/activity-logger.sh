#!/usr/bin/env bash
# PostToolUse hook — append a structured JSONL entry per tool call.
# Best-effort: never block, never fail loudly. Tool output is NOT logged
# (only tool name + input summary), so secrets in returned data don't leak.
set +e

INPUT="$(cat 2>/dev/null || true)"
[ -z "$INPUT" ] && exit 0

WS="${AGENT_WORKSPACE:-${HOME}/.claude-lab/$(basename "$(dirname "$(dirname "$(realpath "$0")")")")/.claude}"
LOG_DIR="${WS}/logs/activity"
mkdir -p "$LOG_DIR"
DATE=$(date -u '+%Y-%m-%d')
LOG_FILE="${LOG_DIR}/${DATE}.jsonl"

# Emit a normalised JSONL line. All extraction is jq-internal so we never
# interpolate untrusted strings into shell.
jq -c --arg ts "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" '
    {
        ts: $ts,
        session: (.session_id // ""),
        event: (.hook_event_name // "PostToolUse"),
        tool: (.tool_name // ""),
        detail: (
            (.tool_input // {})
            | with_entries(
                if (.value | type) == "string"
                then .value |= (.[0:200])
                else .
                end
            )
        ),
        error: (.tool_response.error // null),
        cwd: (.cwd // "")
    }
' <<<"$INPUT" >>"$LOG_FILE" 2>/dev/null

chmod 600 "$LOG_FILE" 2>/dev/null || true
exit 0
