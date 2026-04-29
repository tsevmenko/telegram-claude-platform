#!/usr/bin/env bash
# PreToolUse hook (Edit / Write matcher).
# Blocks edits to secret/lock files. Exit 2 = stop the tool call.
set -euo pipefail

INPUT="$(cat)"
PATH_VAL="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // ""' 2>/dev/null || true)"

if [ -z "$PATH_VAL" ]; then
    exit 0
fi

# Patterns are matched as substrings against the file path.
PROTECTED=(
    '.env'
    '.env.'
    '.git/'
    '.ssh/'
    'package-lock.json'
    'yarn.lock'
    'poetry.lock'
    'Cargo.lock'
    '.pem'
    '.key'
    '.crt'
    '/secrets/'
    '/credentials.json'
    '/.credentials.json'
    'webhook-token.txt'
    'agent-installer/state.json'
    '/etc/sudoers'
    '/etc/passwd'
    '/etc/shadow'
    # Claude Code's own metadata directory — agents must not write here. The
    # ~/.claude/projects/<encoded-cwd>/ tree holds session JSONL transcripts
    # owned by the claude CLI itself. Live regression: an agent without USER.md
    # populated wandered into ~/.claude/projects/.../memory/ trying to dump
    # "feedback" notes. Real workspace memory lives at <workspace>/core/.
    '/.claude/projects/'
    '/.claude/statsig/'
    '/.claude/todos/'
    '/.claude/shell-snapshots/'
    '/.claude/ide/'
)

for needle in "${PROTECTED[@]}"; do
    if printf '%s' "$PATH_VAL" | grep -qF "$needle"; then
        printf 'BLOCKED: %s is a protected path (matched "%s").\nIf this is intentional, ask the operator first.\n' \
            "$PATH_VAL" "$needle" >&2
        exit 2
    fi
done

exit 0
