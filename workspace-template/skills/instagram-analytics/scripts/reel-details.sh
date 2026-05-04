#!/usr/bin/env bash
# reel-details :: pull caption + transcript for one or more Instagram reels.
# Usage: reel-details.sh <shortcode|reel-url> [<shortcode|reel-url> ...]
# Cost:  2 credits per reel (1 post + 1 transcript). Skips transcript if --no-transcript.
set -euo pipefail

KEY_FILE="${TYRION_SCRAPECREATORS_KEY:-$HOME/.config/tyrion/scrapecreators}"
API_BASE="https://api.scrapecreators.com"
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$SKILL_DIR/out"
mkdir -p "$OUT_DIR"

die() { echo "error: $*" >&2; exit 1; }

[[ -r "$KEY_FILE" ]] || die "key file not readable: $KEY_FILE"
KEY="$(tr -d '[:space:]' <"$KEY_FILE")"
[[ -n "$KEY" ]] || die "key file empty"

WANT_TRANSCRIPT=1
CODES=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-transcript) WANT_TRANSCRIPT=0; shift ;;
    -h|--help)       sed -n '2,4p' "$0"; exit 0 ;;
    -*)              die "unknown flag: $1" ;;
    *)               CODES+=("$1"); shift ;;
  esac
done
[[ ${#CODES[@]} -gt 0 ]] || die "need at least one shortcode or reel URL"

normalize_url() {
  # accept either a bare shortcode or a full URL; emit canonical reel URL
  local x="$1"
  if [[ "$x" =~ ^https?:// ]]; then
    echo "$x"
  else
    echo "https://www.instagram.com/reel/$x/"
  fi
}

fetch() {
  local path="$1" qkey="$2" qval="$3" out="$4"
  local code
  code="$(curl -sS -o "$out" -w '%{http_code}' \
    -H "x-api-key: $KEY" \
    --get --data-urlencode "$qkey=$qval" --data-urlencode "trim=true" \
    "$API_BASE$path")"
  if [[ "$code" != "200" ]]; then
    echo "  HTTP $code on $path" >&2
    sed -e 's/^/    /' "$out" >&2
    return 1
  fi
}

TS="$(date +%s)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
RESULTS_FILE="$TMP_DIR/results.json"
echo '[]' >"$RESULTS_FILE"

for raw in "${CODES[@]}"; do
  url="$(normalize_url "$raw")"
  short="$(sed -E 's#.*/reel/([^/?#]+).*#\1#' <<<"$url")"
  echo "==> $short"

  post_file="$TMP_DIR/$short.post.json"
  fetch /v1/instagram/post url "$url" "$post_file" \
    || { echo "  skip $short (post)" >&2; continue; }

  trans_file="$TMP_DIR/$short.trans.json"
  if [[ $WANT_TRANSCRIPT -eq 1 ]]; then
    fetch /v2/instagram/media/transcript url "$url" "$trans_file" \
      || echo '{"transcripts":[]}' >"$trans_file"
  else
    echo '{"transcripts":[]}' >"$trans_file"
  fi

  jq --slurpfile p "$post_file" --slurpfile t "$trans_file" \
     --arg short "$short" --arg url "$url" \
     '($p[0].xdt_shortcode_media // $p[0].data.xdt_shortcode_media // {}) as $m |
      . + [{
        shortcode: $short,
        url: $url,
        caption:  ($m.edge_media_to_caption.edges[0].node.text // null),
        plays:    ($m.video_play_count // $m.video_view_count // null),
        likes:    ($m.edge_media_preview_like.count // $m.edge_liked_by.count // null),
        comments: ($m.edge_media_to_parent_comment.count // $m.edge_media_to_comment.count // null),
        duration_s: ($m.video_duration // null),
        taken_at: ($m.taken_at_timestamp // null),
        transcript: ($t[0].transcripts[0].text // null)
      }]' "$RESULTS_FILE" >"$RESULTS_FILE.tmp" && mv "$RESULTS_FILE.tmp" "$RESULTS_FILE"
done

OUT_FILE="$OUT_DIR/reel-details-${TS}.json"
cp "$RESULTS_FILE" "$OUT_FILE"

echo
echo "── details ──"
jq -r '
  .[] |
  "\n• https://instagram.com/reel/\(.shortcode)",
  "  plays=\(.plays // "—") likes=\(.likes // "—") comments=\(.comments // "—")",
  "  caption: \((.caption // "—") | gsub("\n";" ⏎ ") | .[:400])",
  "  transcript: \((.transcript // "—") | gsub("\n";" ⏎ ") | .[:600])"
' "$OUT_FILE"

echo
echo "raw → $OUT_FILE"
