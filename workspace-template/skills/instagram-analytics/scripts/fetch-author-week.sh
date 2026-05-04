#!/usr/bin/env bash
# fetch-author-week :: default per-author scan = last 7 days, ALL formats.
# Runs bulk-fetch.sh (reels) + posts-fetch.sh (carousels + image posts) with
# --since-days 7. Per operator rule (2026-05-02): if profile is being analyzed,
# always grab last week, both reels AND posts. Not more per author.
#
# Usage: fetch-author-week.sh <handle> [--days N] [--with-comments K]
#                                       [--no-transcripts] [--download]
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

HANDLE=""
DAYS=7
WITH_COMMENTS=0
WANT_TRANSCRIPTS=1
DOWNLOAD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --days)            DAYS="${2:?missing N}"; shift 2 ;;
    --with-comments)   WITH_COMMENTS="${2:?missing K}"; shift 2 ;;
    --no-transcripts)  WANT_TRANSCRIPTS=0; shift ;;
    --download)        DOWNLOAD=1; shift ;;
    -h|--help)         sed -n '2,9p' "$0"; exit 0 ;;
    *)                 [[ -z "$HANDLE" ]] && HANDLE="$1" || { echo "extra arg: $1" >&2; exit 1; }; shift ;;
  esac
done
[[ -n "$HANDLE" ]] || { echo "missing <handle>" >&2; exit 1; }
HANDLE="${HANDLE#@}"

echo "============================================="
echo "  per-author week scan: @$HANDLE (last $DAYS days)"
echo "============================================="

REELS_ARGS=(--count 200 --since-days "$DAYS")
[[ $WANT_TRANSCRIPTS -eq 0 ]] && REELS_ARGS+=(--no-transcripts)
[[ $WITH_COMMENTS -gt 0 ]]    && REELS_ARGS+=(--with-comments "$WITH_COMMENTS")
[[ $DOWNLOAD -eq 1 ]]         && REELS_ARGS+=(--download-covers)

echo
echo ">>> reels"
bash "$DIR/bulk-fetch.sh" "$HANDLE" "${REELS_ARGS[@]}"

POSTS_ARGS=(--count 200 --since-days "$DAYS" --media-type all)
[[ $WITH_COMMENTS -gt 0 ]] && POSTS_ARGS+=(--with-comments "$WITH_COMMENTS")
[[ $DOWNLOAD -eq 1 ]]      && POSTS_ARGS+=(--download-images)

echo
echo ">>> posts/carousels"
bash "$DIR/posts-fetch.sh" "$HANDLE" "${POSTS_ARGS[@]}"

echo
echo "============================================="
echo "  done. outputs in $DIR/../out/"
ls -1t "$DIR/../out/" | grep "^${HANDLE}-" | head -10 | sed 's/^/  /'
echo "============================================="
