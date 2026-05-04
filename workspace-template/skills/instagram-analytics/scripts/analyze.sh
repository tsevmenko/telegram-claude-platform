#!/usr/bin/env bash
# instagram-analytics :: snapshot of a public IG handle via ScrapeCreators.
# Usage: analyze.sh <handle> [--no-reels] [--reels-limit N]
set -euo pipefail

KEY_FILE="${TYRION_SCRAPECREATORS_KEY:-$HOME/.config/tyrion/scrapecreators}"
API_BASE="https://api.scrapecreators.com"
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$SKILL_DIR/out"
mkdir -p "$OUT_DIR"

die() { echo "error: $*" >&2; exit 1; }

[[ -r "$KEY_FILE" ]] || die "key file not readable: $KEY_FILE"
KEY="$(tr -d '[:space:]' <"$KEY_FILE")"
[[ -n "$KEY" ]] || die "key file is empty"

HANDLE=""
FETCH_REELS=1
REELS_LIMIT=5

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-reels)     FETCH_REELS=0; shift ;;
    --reels-limit)  REELS_LIMIT="${2:?missing N}"; shift 2 ;;
    -h|--help)      sed -n '2,4p' "$0"; exit 0 ;;
    -*)             die "unknown flag: $1" ;;
    *)              [[ -z "$HANDLE" ]] && HANDLE="$1" || die "extra arg: $1"; shift ;;
  esac
done

[[ -n "$HANDLE" ]] || die "missing <handle>"
HANDLE="${HANDLE#@}"

call() {
  # call <path> <query>  -> stdout: body, stderr: status line
  local path="$1" query="$2"
  local tmp; tmp="$(mktemp)"
  local code
  code="$(curl -sS -o "$tmp" -w '%{http_code}' \
    -H "x-api-key: $KEY" \
    --get --data-urlencode "$query" \
    --data-urlencode "trim=true" \
    "$API_BASE$path")"
  if [[ "$code" != "200" ]]; then
    echo "HTTP $code on $path" >&2
    cat "$tmp" >&2; echo >&2
    rm -f "$tmp"
    return 1
  fi
  cat "$tmp"; rm -f "$tmp"
}

TS="$(date +%s)"
OUT_FILE="$OUT_DIR/${HANDLE}-${TS}.json"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
PROFILE_FILE="$TMP_DIR/profile.json"
REELS_FILE="$TMP_DIR/reels.json"

echo "==> profile @$HANDLE"
call /v1/instagram/profile "handle=$HANDLE" >"$PROFILE_FILE" \
  || die "profile fetch failed"

echo '{"items":[]}' >"$REELS_FILE"
if [[ $FETCH_REELS -eq 1 ]]; then
  echo "==> reels @$HANDLE"
  call /v1/instagram/user/reels "handle=$HANDLE" >"$REELS_FILE" \
    || die "reels fetch failed"
fi

jq -n \
  --arg handle "$HANDLE" \
  --arg fetched_at "$(date -u +%FT%TZ)" \
  --slurpfile profile "$PROFILE_FILE" \
  --slurpfile reels   "$REELS_FILE" \
  '{handle:$handle, fetched_at:$fetched_at, profile:$profile[0], reels:$reels[0]}' \
  >"$OUT_FILE"

# ---- summary ----
echo
echo "── @$HANDLE ──"
jq -r '
  (.data.user // .) as $u |
  [
    "name:       \($u.full_name // "—")",
    "verified:   \($u.is_verified // false)",
    "private:    \($u.is_private // false)",
    "followers:  \($u.edge_followed_by.count // $u.follower_count // "—")",
    "following:  \($u.edge_follow.count // $u.following_count // "—")",
    "posts:      \($u.edge_owner_to_timeline_media.count // $u.media_count // "—")",
    "bio:        \(($u.biography // "") | gsub("\n"; " ⏎ "))"
  ] | .[]
' "$PROFILE_FILE"

if [[ $FETCH_REELS -eq 1 ]]; then
  echo
  echo "── top $REELS_LIMIT reels by play count ──"
  jq -r --argjson n "$REELS_LIMIT" '
    [ .items[]? | (.media // .) |
      {
        code: (.code // .shortcode // ""),
        plays: (.play_count // .ig_play_count // 0),
        likes: (.like_count // 0),
        comments: (.comment_count // 0),
        taken_at: (.taken_at // 0)
      }
    ]
    | sort_by(-.plays)[:$n]
    | .[]
    | "  https://instagram.com/reel/\(.code)\n     plays=\(.plays)  likes=\(.likes)  comments=\(.comments)  taken_at=\((.taken_at|todate))"
  ' "$REELS_FILE"
fi

echo
echo "raw → $OUT_FILE"
