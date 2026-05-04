#!/usr/bin/env bash
# posts-fetch :: pull mixed-media feed (posts + carousels) for a public IG handle.
# Reels live in a different endpoint (use bulk-fetch.sh). This script targets
# images, image-carousels (sidecar), and any non-reel post.
#
# Usage: posts-fetch.sh <handle> [--count N] [--media-type all|carousel|image]
#                                [--download-images] [--with-comments K]
#
# Output: out/<handle>-posts-<unix>.json with fields per item:
#   { code, pk, taken_at, type, plays?, likes, comments, caption,
#     cover_url, slide_count, slides:[{url, local}], comments_sample? }
#
# Cost (default 5/no comments):
#   1 page = ~1-2 credits (paginate as needed)
#   5 carousels × 1 caption-call = 5 credits
#   --with-comments K adds K credits.
#   --download-images is free (CDN bandwidth only).

set -euo pipefail

KEY_FILE="${TYRION_SCRAPECREATORS_KEY:-$HOME/.config/tyrion/scrapecreators}"
API_BASE="https://api.scrapecreators.com"
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$SKILL_DIR/out"
mkdir -p "$OUT_DIR"

die() { echo "error: $*" >&2; exit 1; }
[[ -r "$KEY_FILE" ]] || die "key not readable: $KEY_FILE"
KEY="$(tr -d '[:space:]' <"$KEY_FILE")"
[[ -n "$KEY" ]] || die "key file empty"

HANDLE=""
COUNT=5
MEDIA_FILTER="carousel"   # all|carousel|image
DOWNLOAD_IMAGES=0
WITH_COMMENTS=0
SINCE_DAYS=0              # 0 = no time filter; if >0 only keep items taken_at >= now-N days

while [[ $# -gt 0 ]]; do
  case "$1" in
    --count)            COUNT="${2:?missing N}"; shift 2 ;;
    --media-type)       MEDIA_FILTER="${2:?missing}"; shift 2 ;;
    --download-images)  DOWNLOAD_IMAGES=1; shift ;;
    --with-comments)    WITH_COMMENTS="${2:?missing K}"; shift 2 ;;
    --since-days)       SINCE_DAYS="${2:?missing N}"; shift 2 ;;
    -h|--help)          sed -n '2,18p' "$0"; exit 0 ;;
    -*)                 die "unknown flag: $1" ;;
    *)                  [[ -z "$HANDLE" ]] && HANDLE="$1" || die "extra arg: $1"; shift ;;
  esac
done
[[ -n "$HANDLE" ]] || die "missing <handle>"
HANDLE="${HANDLE#@}"

CUTOFF_TS=0
if [[ "$SINCE_DAYS" -gt 0 ]]; then
  CUTOFF_TS="$(( $(date +%s) - SINCE_DAYS * 86400 ))"
  echo "==> time filter: only items taken_at >= $CUTOFF_TS ($(date -u -d @$CUTOFF_TS +%FT%TZ))"
fi

TS="$(date +%s)"
OUT_FILE="$OUT_DIR/${HANDLE}-posts-${TS}.json"
SLIDES_DIR="$OUT_DIR/${HANDLE}-slides-${TS}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

call_get() {
  local path="$1" out="$2"; shift 2
  local args=()
  for kv in "$@"; do args+=(--data-urlencode "$kv"); done
  args+=(--data-urlencode "trim=true")
  local code
  code="$(curl -sS -o "$out" -w '%{http_code}' \
    -H "x-api-key: $KEY" --get "${args[@]}" "$API_BASE$path")"
  if [[ "$code" != "200" ]]; then
    echo "  HTTP $code on $path" >&2
    sed -e 's/^/    /' "$out" >&2
    return 1
  fi
}

# --- Stage 1: paginate user posts (mixed media) ---
# Endpoint candidates: /v1/instagram/user/posts (primary), /v1/instagram/user/feed (fallback).
# If neither works, fall back to /v1/instagram/user/media.
echo "==> stage 1: paginate posts until $COUNT $MEDIA_FILTER collected"
echo '[]' >"$TMP/all.json"
max_id=""
page=0
matched=0

# Determine endpoint by feature-detect on first call (cheap)
ENDPOINT=""
for cand in "/v2/instagram/user/posts" "/v1/instagram/user/posts" "/v1/instagram/user/feed" "/v1/instagram/user/media"; do
  test_out="$TMP/probe.json"
  if call_get "$cand" "$test_out" "handle=$HANDLE" 2>/dev/null; then
    if jq -e '(.items // .data // .posts // [])  | length > 0' "$test_out" >/dev/null 2>&1; then
      ENDPOINT="$cand"
      echo "  endpoint=$ENDPOINT"
      mv "$test_out" "$TMP/page-1.json"
      page=1
      break
    fi
  fi
done
[[ -n "$ENDPOINT" ]] || die "no working posts endpoint found — check ScrapeCreators API docs and update this script"

extract_max_id() {
  jq -r '.paging_info.max_id // .next_max_id // .max_id // .paging_info.next_max_id // empty' "$1"
}

is_carousel_filter='(.media_type == 8) or (.product_type == "carousel_container") or ((.carousel_media // []) | length > 0)'
is_image_filter='(.media_type == 1) and ((.carousel_media // []) | length == 0)'

filter_jq=""
case "$MEDIA_FILTER" in
  all)      filter_jq='true' ;;
  carousel) filter_jq="$is_carousel_filter" ;;
  image)    filter_jq="$is_image_filter" ;;
  *)        die "bad --media-type: $MEDIA_FILTER" ;;
esac

# Effective cap during pagination: in time-window mode we keep paginating
# until cutoff is reached, ignoring --count. --count still bounds final list.
EFF_COUNT="$COUNT"
if [[ "$CUTOFF_TS" -gt 0 ]]; then EFF_COUNT=9999; fi

# Hard safeguards against runaway pagination (lesson 2026-05-03: ScrapeCreators
# /v2/instagram/user/posts ignored max_id and returned the same first page on
# every request. Burned 89 credits before kill.)
MAX_PAGES=30
prev_max_id=""

while [[ "$matched" -lt "$EFF_COUNT" ]]; do
  if [[ "$page" -ge "$MAX_PAGES" ]]; then
    echo "  reached MAX_PAGES=$MAX_PAGES — stopping pagination"
    break
  fi

  if [[ "$page" -eq 0 ]]; then
    page=1
    out="$TMP/page-$page.json"
    call_get "$ENDPOINT" "$out" "handle=$HANDLE" \
      || { echo "  page $page failed"; break; }
  elif [[ "$page" -gt 0 && -n "${max_id:-}" ]]; then
    page=$((page+1))
    out="$TMP/page-$page.json"
    call_get "$ENDPOINT" "$out" "handle=$HANDLE" "max_id=$max_id" \
      || { echo "  page $page failed"; break; }
  else
    out="$TMP/page-$page.json"
  fi

  # Append all items, filter at end
  jq -s --argjson n "$EFF_COUNT" --argjson f "$filter_jq" \
    "(.[0] + ((.[1].items // .[1].data // .[1].posts // []) | map(select($filter_jq)))) | .[:\$n]" \
    "$TMP/all.json" "$out" >"$TMP/all.json.new" 2>/dev/null \
    && mv "$TMP/all.json.new" "$TMP/all.json" || true

  matched="$(jq 'length' "$TMP/all.json")"
  echo "  page $page: total matched=$matched"

  if [[ "$CUTOFF_TS" -gt 0 ]]; then
    oldest="$(jq -r '[((.items // .data // .posts // [])[] | (.taken_at // 0))] | min // 0' "$out")"
    if [[ -n "$oldest" && "$oldest" != "null" && "$oldest" -lt "$CUTOFF_TS" ]]; then
      echo "  page $page oldest=$oldest < cutoff=$CUTOFF_TS — stop pagination"
      break
    fi
  fi

  new_max_id="$(extract_max_id "$out")"
  [[ -z "$new_max_id" || "$new_max_id" == "null" ]] && { echo "  end of feed"; break; }

  # Cursor-stuck detection: if API returns same next_max_id as last page,
  # pagination is broken. Bail out instead of spending credits.
  if [[ "$new_max_id" == "$prev_max_id" ]]; then
    echo "  cursor stuck (next_max_id repeated) — pagination broken, stopping"
    break
  fi
  prev_max_id="$new_max_id"
  max_id="$new_max_id"
  sleep 0.5
done

if [[ "$CUTOFF_TS" -gt 0 ]]; then
  jq --argjson cut "$CUTOFF_TS" \
    '[.[] | select(((.taken_at // 0)) >= $cut)]' \
    "$TMP/all.json" >"$TMP/all.json.new" && mv "$TMP/all.json.new" "$TMP/all.json"
  matched="$(jq 'length' "$TMP/all.json")"
  echo "  after time filter: $matched items in last $SINCE_DAYS days"
fi

# Dedup by code (broken-pagination safeguard repeats first page)
jq 'unique_by(.code)' "$TMP/all.json" >"$TMP/all.json.new" && mv "$TMP/all.json.new" "$TMP/all.json"
matched="$(jq 'length' "$TMP/all.json")"
echo "  after dedup by code: $matched unique items"

echo "==> matched $matched $MEDIA_FILTER items"

# --- Stage 2: enrich each with caption + slide URLs ---
# Captions are inline in feed payload (`.caption.text`). No extra API call needed.
# Read item from temp file (not here-string / argv) to avoid E2BIG on big carousels
# whose JSON exceeds bash's exec arg limit (~128KB).
echo "==> stage 2: per-item caption + slides"
: >"$TMP/enriched.jsonl"
n_items="$(jq 'length' "$TMP/all.json")"
for ((i=0; i<n_items; i++)); do
  jq -c ".[$i]" "$TMP/all.json" >"$TMP/item.json"
  code="$(jq -r '.code // ""' "$TMP/item.json")"
  [[ -z "$code" ]] && { echo "  [$((i+1))] no code, skip"; continue; }
  url="https://www.instagram.com/p/$code/"
  echo "  [$((i+1))/$matched] $code"
  jq -c \
    --arg url "$url" \
    '. as $r |
     {
       code:        ($r.code // ""),
       pk:          ($r.pk // ""),
       url:         $url,
       taken_at:    ($r.taken_at // 0),
       type:        (if (($r.carousel_media // []) | length > 0) then "carousel"
                     elif ($r.media_type == 8) then "carousel"
                     elif ($r.media_type == 2) then "video"
                     else "image" end),
       slide_count: (($r.carousel_media // []) | length),
       likes:       ($r.like_count // 0),
       comments:    ($r.comment_count // 0),
       plays:       ($r.play_count // $r.ig_play_count // null),
       caption:     ($r.caption.text // ""),
       cover_url:   ($r.image_versions2.candidates[1].url // $r.image_versions2.candidates[0].url // ($r.carousel_media[0].image_versions2.candidates[1].url) // null),
       slides:      (
         ($r.carousel_media // []) | map({
           url: (.image_versions2.candidates[1].url // .image_versions2.candidates[0].url // null),
           local: null
         })
       ),
       comments_sample: null
     }' "$TMP/item.json" >>"$TMP/enriched.jsonl"
done

jq -s '.' "$TMP/enriched.jsonl" >"$TMP/items.json"

# --- Stage 3: download slide images ---
if [[ $DOWNLOAD_IMAGES -eq 1 ]]; then
  echo "==> stage 3: downloading slides → $SLIDES_DIR"
  mkdir -p "$SLIDES_DIR"
  while read -r row; do
    code="$(jq -r '.code' <<<"$row")"
    sl_dir="$SLIDES_DIR/$code"
    mkdir -p "$sl_dir"
    j=0
    jq -c '.slides[]' <<<"$row" | while read -r slide; do
      j=$((j+1))
      surl="$(jq -r '.url' <<<"$slide")"
      [[ "$surl" == "null" ]] && continue
      target="$sl_dir/slide-$(printf '%02d' "$j").jpg"
      if curl -sS -o "$target" "$surl"; then
        echo "  [$code] slide $j -> $target"
      fi
    done
  done < <(jq -c '.[]' "$TMP/items.json")
fi

# --- Stage 4: comments per item ---
if [[ "$WITH_COMMENTS" -gt 0 ]]; then
  echo "==> stage 4: comments (top-$WITH_COMMENTS by likes)"
  jq -r --argjson n "$WITH_COMMENTS" 'sort_by(-.likes) | .[:$n] | .[].code' \
    "$TMP/items.json" >"$TMP/com-codes.txt"
  while read -r code; do
    [[ -z "$code" ]] && continue
    url="https://www.instagram.com/p/$code/"
    com_out="$TMP/com-$code.json"
    com_arr="[]"
    if call_get /v2/instagram/post/comments "$com_out" "url=$url"; then
      com_arr="$(jq -c '
        ((.comments // .data.comments // .edges // []) | map({
          text:        (.text // .node.text // ""),
          author:      (.user.username // .owner.username // .node.owner.username // null),
          like_count:  (.like_count // .node.like_count // 0),
          created_at:  (.created_at // .node.created_at // null)
        }))' "$com_out" 2>/dev/null || echo '[]')"
    fi
    jq --arg c "$code" --argjson com "$com_arr" \
      'map(if .code == $c then .comments_sample = $com else . end)' \
      "$TMP/items.json" >"$TMP/items.json.new" \
      && mv "$TMP/items.json.new" "$TMP/items.json"
    sleep 0.5
  done <"$TMP/com-codes.txt"
fi

# --- Final assembly ---
jq --arg h "$HANDLE" --arg ts "$(date -Iseconds -u)" --arg endpoint "$ENDPOINT" \
   --argjson count "$matched" --arg filter "$MEDIA_FILTER" \
  '{
    handle: $h,
    fetched_at: $ts,
    endpoint: $endpoint,
    media_filter: $filter,
    actual_count: $count,
    items: .
  }' "$TMP/items.json" >"$OUT_FILE"

echo
echo "==> saved: $OUT_FILE"
echo "==> items: $matched ($MEDIA_FILTER)"
[[ $DOWNLOAD_IMAGES -eq 1 ]] && echo "==> slides: $SLIDES_DIR"
