#!/usr/bin/env bash
# Install a Claude Code skill from a GitHub repo URL.
# Usage: install.sh https://github.com/<owner>/<repo> [skill-name]
set -euo pipefail

URL="${1:?Usage: install.sh <github-url> [skill-name]}"
case "$URL" in
    https://github.com/*) ;;
    *) echo "Only https://github.com/ URLs are supported." >&2; exit 1 ;;
esac

# Derive default name from repo basename.
NAME="${2:-$(basename "${URL%.git}")}"

WS="${AGENT_WORKSPACE:-${PWD}}"
SKILLS_DIR="${WS}/skills"
DEST="${SKILLS_DIR}/${NAME}"
mkdir -p "$SKILLS_DIR"

if [ -d "$DEST" ]; then
    echo "Skill '${NAME}' already installed at ${DEST}." >&2
    echo "Remove it first or pass a different second argument."     >&2
    exit 1
fi

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

echo "Cloning ${URL}..." >&2
git clone --quiet --depth 1 "$URL" "${TMP}/clone" \
    || { echo "git clone failed" >&2; exit 1; }

# A valid skill MUST have SKILL.md somewhere in the tree.
SKILL_MD=$(find "${TMP}/clone" -maxdepth 3 -name 'SKILL.md' -print -quit)
if [ -z "$SKILL_MD" ]; then
    echo "no SKILL.md found in ${URL} — refusing to install." >&2
    exit 1
fi

# Resolve the skill root (the dir containing SKILL.md).
SKILL_ROOT="$(dirname "$SKILL_MD")"

# Print description for the operator's review.
echo "About to install:" >&2
awk '/^---/{c++; next} c==1' "$SKILL_MD" | head -10 >&2
echo "..." >&2
echo "" >&2

# Copy.
mkdir -p "$DEST"
rsync -a --exclude '.git' --exclude '.github' "${SKILL_ROOT}/" "${DEST}/"

# Set executable bits on helper scripts.
find "$DEST" -type f \( -name '*.sh' -o -name '*.py' \) -exec chmod 0755 {} \;

echo "Installed ${NAME} at ${DEST}"
