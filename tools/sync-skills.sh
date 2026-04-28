#!/usr/bin/env bash
# Sync skills from the canonical repo (agent-skills) into our vendored copy.
#
# Usage:
#   SKILLS_REPO=~/projects/agent-skills tools/sync-skills.sh
#
# Default SKILLS_REPO is ~/projects/agent-skills. Override via env var.
#
# This is a one-way sync: agent-skills → workspace-template/skills/.
# The --delete flag means a skill removed in agent-skills is removed here too.
# Run `git diff --stat workspace-template/skills/` after to review.
set -euo pipefail

SKILLS_REPO="${SKILLS_REPO:-$HOME/projects/agent-skills}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_ROOT="$(dirname "$SCRIPT_DIR")"
DEST="$PLATFORM_ROOT/workspace-template/skills"

if [ ! -d "$SKILLS_REPO/skills" ]; then
    echo "error: $SKILLS_REPO/skills not found." >&2
    echo "       set SKILLS_REPO env to the path of your local agent-skills clone." >&2
    echo "       e.g.:  cd ~/projects && gh repo clone <owner>/agent-skills" >&2
    exit 1
fi

# Refuse to sync if agent-skills has uncommitted changes — the destination should
# always trace back to a known commit, not a dirty working tree.
if [ -n "$(git -C "$SKILLS_REPO" status --porcelain 2>/dev/null)" ]; then
    echo "error: $SKILLS_REPO has uncommitted changes." >&2
    echo "       commit or stash, then re-run." >&2
    exit 1
fi

src_sha="$(git -C "$SKILLS_REPO" rev-parse --short HEAD)"
src_branch="$(git -C "$SKILLS_REPO" rev-parse --abbrev-ref HEAD)"
echo "syncing from $SKILLS_REPO ($src_branch @ $src_sha) → $DEST"

mkdir -p "$DEST"
rsync -av --delete \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '.DS_Store' \
    "$SKILLS_REPO/skills/" "$DEST/"

# Stamp the source SHA so it's obvious which agent-skills commit produced this vendored copy.
echo "$src_sha" >"$DEST/.synced-from-sha"

# Show a quick summary so the operator can review before committing.
echo
echo "=== diff vs HEAD ==="
git -C "$PLATFORM_ROOT" diff --stat workspace-template/skills/ | tail -20 || true
echo
echo "next: review changes, then:"
echo "  git -C $PLATFORM_ROOT add workspace-template/skills"
echo "  git -C $PLATFORM_ROOT commit -m \"sync skills from agent-skills@${src_sha}\""
