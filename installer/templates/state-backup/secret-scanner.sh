#!/usr/bin/env bash
# Secret scanner — pre-commit guard. Refuses commit if any staged file
# contains a token-shaped string. Patterns intentionally broad — false
# positives require an allowlist entry, but a missed leak is much worse
# than a re-run.
#
# Performance: one python invocation per file scans ALL patterns at once.
# (Naive per-file × per-pattern was ~12K subprocess starts on a fresh
# 1251-file mirror — minutes vs seconds.)
#
# Portable across bash 3.2 (macOS dev) and bash 5+ (Ubuntu VPS) —
# avoids `mapfile` and `declare -A` which are bash-4-only.
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Collect staged file paths (regular files only).
FILES=()
while IFS= read -r line; do
    [[ -n "$line" ]] && FILES+=("$line")
done < <(git diff --cached --name-only --diff-filter=ACM 2>/dev/null)
[[ ${#FILES[@]} -eq 0 ]] && exit 0

# Single python script — receives file paths on argv, prints one line per
# match: `<file>\t<pattern_name>\t<truncated_match>`. Empty stdout = clean.
SCAN_OUTPUT=$(python3 - "${FILES[@]}" <<'PY'
import re, sys

PATTERNS = [
    ("anthropic_key",       r'sk-ant-[A-Za-z0-9_-]{40,}'),
    ("openai_key",          r'sk-(proj-)?[A-Za-z0-9_-]{40,}'),
    ("groq_key",            r'gsk_[A-Za-z0-9]{40,}'),
    ("github_pat",          r'gh[pousr]_[A-Za-z0-9]{36,}'),
    ("github_finegrained",  r'github_pat_[A-Za-z0-9_]{60,}'),
    ("slack_token",         r'xox[bp]-[A-Za-z0-9-]{20,}'),
    ("aws_access_key",      r'AKIA[0-9A-Z]{16}'),
    ("scrapecreators_pk",   r'pk_[0-9]{6,}_[A-Z0-9]{30,}'),
    ("scrapecreators_alt",  r'pXBZ[A-Za-z0-9]{20,}'),
    ("bearer_long",         r'Bearer [A-Za-z0-9_.\-]{40,}'),
    ("jwt",                 r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'),
    ("private_key_pem",     r'-----BEGIN [A-Z ]+PRIVATE KEY-----'),
]
COMPILED = [(name, re.compile(pat)) for name, pat in PATTERNS]

# Allowlist (literal substrings) — strings that match patterns but are
# known not to be secrets. Add carefully.
ALLOWLIST = [
    # (none yet)
]

for path in sys.argv[1:]:
    try:
        with open(path, errors="replace") as fh:
            data = fh.read()
    except (OSError, IsADirectoryError):
        continue
    for name, rx in COMPILED:
        for m in rx.finditer(data):
            match = m.group(0)
            if any(allow in match for allow in ALLOWLIST):
                continue
            short = match[:24] + "…"
            # Tab-separated; tab/newline can't appear in token-shaped matches.
            print(f"{path}\t{name}\t{short}")
PY
)

if [[ -z "$SCAN_OUTPUT" ]]; then
    exit 0
fi

# Render rejection report.
echo "═══ SECRET SCANNER REJECT ═══" >&2
echo "Found likely-secret strings in staged files:" >&2
while IFS=$'\t' read -r f name short; do
    [[ -z "$f" ]] && continue
    echo "  $f [$name]: $short" >&2
done <<< "$SCAN_OUTPUT"
echo "" >&2
echo "If genuine: REVOKE the secret + remove from file + retry." >&2
echo "If false-positive: add to ALLOWLIST in tools/secret-scanner.sh." >&2
exit 1
