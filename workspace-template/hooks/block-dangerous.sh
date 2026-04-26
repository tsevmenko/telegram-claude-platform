#!/usr/bin/env bash
# PreToolUse hook (Bash matcher).
# Blocks well-known destructive command patterns. Exit 2 = stop the tool call.
set -euo pipefail

INPUT="$(cat)"
CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null || true)"

if [ -z "$CMD" ]; then
    exit 0
fi

DANGEROUS=(
    'rm -rf /[^a-zA-Z]'
    'rm -rf ~'
    'rm -rf \$HOME'
    'mkfs'
    'dd if=.*of=/dev/'
    ':\(\)\{ :\|:& \};:'         # fork bomb
    'git reset --hard'
    'git push.*--force'
    'git push.*-f([[:space:]]|$)'
    'DROP +(TABLE|DATABASE|SCHEMA)'
    'TRUNCATE +TABLE'
    'curl[^|]+\|[[:space:]]*(bash|sh)([[:space:]]|$)'
    'wget[^|]+\|[[:space:]]*(bash|sh)([[:space:]]|$)'
    'chmod -R 0?777 /'
    '> /dev/sda'
)

for pattern in "${DANGEROUS[@]}"; do
    if printf '%s' "$CMD" | grep -qiE "$pattern"; then
        printf 'BLOCKED: command matches dangerous pattern "%s".\nCommand: %s\n' \
            "$pattern" "$CMD" >&2
        exit 2
    fi
done

exit 0
