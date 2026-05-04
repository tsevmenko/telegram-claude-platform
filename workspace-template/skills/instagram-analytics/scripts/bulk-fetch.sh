#!/usr/bin/env bash
# bulk-fetch :: deep-dive author scrape for a public IG handle.
# Pulls profile + N reels (paginated) + captions; transcripts/comments/
# cover-images are OPT-IN (each multiplies cost). Live cost regression
# 2026-05-02 forced sane defaults — see _budget-guard.sh / _dedup-guard.sh.
#
# Usage: bulk-fetch.sh <handle>
#                     [--count N]                 (default 20, was 50)
#                     [--with-transcripts]        (default OFF, was --no-transcripts to opt out)
#                     [--top-transcripts K]       (default 10 when transcripts opted in, was 15)
#                     [--with-comments K]
#                     [--download-covers]
#                     [--no-profile]
#                     [--since-days N]
#                     [--force]                   (override 7-day dedup guard)
#
# Cost shape (per call to ScrapeCreators):
#   profile fetch:            ~1 credit
#   reels page (50 reels):   ~5 credits
#   caption fetch (per reel): ~1 credit
#   transcript (per reel):   ~30 credits     ← biggest multiplier
#   comments (per reel):     ~5 credits
#   cover image download:    ~1 credit each
#
# Defaults below assume "snapshot for analysis", not "deep dive". Add
# --with-transcripts only when you really need ASR text (e.g. audio
# script analysis); otherwise rely on captions which are cheap.
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

# Cost-discipline guards. _budget-guard refuses calls over daily/total
# credit budget; _dedup-guard refuses re-fetch of same handle within 7
# days (override with --force). Both source state from <skill>/state/.
# shellcheck disable=SC1091
source "$SKILL_DIR/scripts/_budget-guard.sh"
# shellcheck disable=SC1091
source "$SKILL_DIR/scripts/_dedup-guard.sh"

HANDLE=""
COUNT=20                   # was 50 — smaller default, covers most analysis needs
TOP_TRANS=10               # only used if --with-transcripts is on
WANT_TRANSCRIPTS=0         # was 1 — now opt-in via --with-transcripts (each transcript ~30 cr)
WANT_PROFILE=1
WITH_COMMENTS=0            # number of reels to fetch comments for (top-N by plays)
DOWNLOAD_COVERS=0
SINCE_DAYS=0               # 0 = no time filter; if >0 only keep reels taken_at >= now-N days
FORCE=0                    # 1 = bypass 7-day dedup guard

while [[ $# -gt 0 ]]; do
  case "$1" in
    --count)            COUNT="${2:?missing N}"; shift 2 ;;
    --top-transcripts)  TOP_TRANS="${2:?missing K}"; shift 2 ;;
    --with-transcripts) WANT_TRANSCRIPTS=1; shift ;;
    --no-transcripts)   WANT_TRANSCRIPTS=0; shift ;;   # kept for backward compat (no-op now since default off)
    --no-profile)       WANT_PROFILE=0; shift ;;
    --with-comments)    WITH_COMMENTS="${2:?missing K}"; shift 2 ;;
    --download-covers)  DOWNLOAD_COVERS=1; shift ;;
    --since-days)       SINCE_DAYS="${2:?missing N}"; shift 2 ;;
    --force)            FORCE=1; shift ;;
    -h|--help)          sed -n '2,18p' "$0"; exit 0 ;;
    -*)                 die "unknown flag: $1" ;;
    *)                  [[ -z "$HANDLE" ]] && HANDLE="$1" || die "extra arg: $1"; shift ;;
  esac
done
[[ -n "$HANDLE" ]] || die "missing <handle>"
HANDLE="${HANDLE#@}"

# Reject re-fetch of same handle within 7 days unless --force.
dedup_guard_check "$HANDLE" "bulk" "$FORCE"

# Pre-flight cost estimate. Conservative: assumes full pages + transcripts
# + comments + covers if those flags are on. Underestimate is fine — the
# RECORD step at the end uses actual count.
EST=$((1 + COUNT/10*5 + COUNT))                         # profile + paginate + captions
[[ "$WANT_TRANSCRIPTS" -eq 1 ]] && EST=$((EST + TOP_TRANS * 30))
[[ "$WITH_COMMENTS"    -gt 0 ]] && EST=$((EST + WITH_COMMENTS * 5))
[[ "$DOWNLOAD_COVERS"  -eq 1 ]] && EST=$((EST + COUNT))
budget_guard_check "bulk-fetch:$HANDLE" "$EST"

CUTOFF_TS=0
if [[ "$SINCE_DAYS" -gt 0 ]]; then
  CUTOFF_TS="$(( $(date +%s) - SINCE_DAYS * 86400 ))"
  echo "==> time filter: only reels taken_at >= $CUTOFF_TS ($(date -u -d @$CUTOFF_TS +%FT%TZ))"
fi

TS="$(date +%s)"
OUT_FILE="$OUT_DIR/${HANDLE}-bulk-${TS}.json"
COVERS_DIR="$OUT_DIR/${HANDLE}-covers-${TS}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# --- API helper ---
call_get() {
  local path="$1" out="$2"; shift 2
  local args=()
  local kv
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

extract_max_id() {
  jq -r '.paging_info.max_id // .next_max_id // .max_id // .paging_info.next_max_id // empty' "$1"
}

# --- Stage 1: paginate reels until COUNT collected ---
echo "==> stage 1: paginate reels until $COUNT collected"
echo '[]' >"$TMP/reels.json"
max_id=""
prev_max_id=""
page=0
got=0
MAX_PAGES=30
while [[ "$got" -lt "$COUNT" ]]; do
  if [[ "$page" -ge "$MAX_PAGES" ]]; then
    echo "  reached MAX_PAGES=$MAX_PAGES — stopping"
    break
  fi
  page=$((page+1))
  out="$TMP/page-$page.json"
  if [[ -z "$max_id" ]]; then
    call_get /v1/instagram/user/reels "$out" "handle=$HANDLE" \
      || { echo "  page $page failed; stopping pagination"; break; }
  else
    call_get /v1/instagram/user/reels "$out" "handle=$HANDLE" "max_id=$max_id" \
      || { echo "  page $page failed; stopping pagination"; break; }
  fi
  added="$(jq '.items | length' "$out")"
  echo "  page $page: +$added reels (max_id sent='$max_id')"
  jq -s --argjson n "$COUNT" '(.[0] + .[1].items) | .[:$n]' "$TMP/reels.json" "$out" \
    >"$TMP/reels.json.new" && mv "$TMP/reels.json.new" "$TMP/reels.json"
  got="$(jq 'length' "$TMP/reels.json")"
  new_max_id="$(extract_max_id "$out")"
  if [[ -z "$new_max_id" || "$new_max_id" == "null" ]]; then
    echo "  no more pages"
    break
  fi
  if [[ "$new_max_id" == "$prev_max_id" ]]; then
    echo "  cursor stuck (max_id repeated) — pagination broken, stopping"
    break
  fi
  prev_max_id="$new_max_id"
  max_id="$new_max_id"
  if [[ "$CUTOFF_TS" -gt 0 ]]; then
    oldest="$(jq -r '[.items[] | (.media.taken_at // .taken_at // 0)] | min // 0' "$out")"
    if [[ -n "$oldest" && "$oldest" != "null" && "$oldest" -lt "$CUTOFF_TS" ]]; then
      echo "  page $page oldest=$oldest < cutoff=$CUTOFF_TS — stop pagination"
      break
    fi
  fi
  sleep 0.5
done

if [[ "$CUTOFF_TS" -gt 0 ]]; then
  jq --argjson cut "$CUTOFF_TS" \
    '[.[] | select(((.media.taken_at // .taken_at // 0)) >= $cut)]' \
    "$TMP/reels.json" >"$TMP/reels.json.new" && mv "$TMP/reels.json.new" "$TMP/reels.json"
  got="$(jq 'length' "$TMP/reels.json")"
  echo "  after time filter: $got reels in last $SINCE_DAYS days"
fi
echo "  total reels collected: $got"

# --- Stage 2: caption + cover_url per reel (cover from feed item, no extra credits) ---
echo "==> stage 2: captions + cover URLs for $got reels"
: >"$TMP/reels-enriched.jsonl"
i=0
while read -r reel; do
  i=$((i+1))
  code="$(jq -r '.media.code // .code // ""' <<<"$reel")"
  [[ -z "$code" ]] && { echo "  [$i] no code, skip"; continue; }
  url="https://www.instagram.com/reel/$code/"
  echo "  [$i/$got] caption+cover $code"
  post_out="$TMP/post-$code.json"
  caption="null"
  if call_get /v1/instagram/post "$post_out" "url=$url"; then
    caption="$(jq '.xdt_shortcode_media.edge_media_to_caption.edges[0].node.text // null' "$post_out")"
  fi
  jq -c \
    --argjson cap "$caption" \
    --argjson reel_in "$reel" \
    '($reel_in.media // $reel_in) as $r |
     {
       code:       ($r.code // ""),
       pk:         ($r.pk // ""),
       taken_at:   ($r.taken_at // 0),
       duration:   ($r.video_duration // null),
       plays:      ($r.play_count // $r.ig_play_count // 0),
       likes:      ($r.like_count // 0),
       comments:   ($r.comment_count // 0),
       caption:    $cap,
       cover_url:  ($r.display_uri // ($r.image_versions2.candidates[1].url) // ($r.image_versions2.candidates[0].url) // null),
       cover_local: null,
       transcript: null,
       comments_sample: null
     }' <<<'{}' >>"$TMP/reels-enriched.jsonl"
  sleep 0.5
done < <(jq -c '.[]' "$TMP/reels.json")

jq -s '.' "$TMP/reels-enriched.jsonl" >"$TMP/reels-with-cap.json"

# --- Stage 3: transcripts for top-K by plays ---
if [[ $WANT_TRANSCRIPTS -eq 1 && $TOP_TRANS -gt 0 ]]; then
  echo "==> stage 3: transcripts for top-$TOP_TRANS by plays"
  jq -r --argjson n "$TOP_TRANS" 'sort_by(-.plays) | .[:$n] | .[].code' \
    "$TMP/reels-with-cap.json" >"$TMP/top-codes.txt"
  cp "$TMP/reels-with-cap.json" "$TMP/reels-final.json"
  while read -r code; do
    [[ -z "$code" ]] && continue
    url="https://www.instagram.com/reel/$code/"
    trans_out="$TMP/trans-$code.json"
    echo "  transcript $code"
    trans_text=""
    if call_get /v2/instagram/media/transcript "$trans_out" "url=$url"; then
      trans_text="$(jq -r '.transcripts[0].text // ""' "$trans_out")"
    fi
    jq --arg c "$code" --arg t "$trans_text" \
      'map(if .code == $c then .transcript = (if $t=="" then null else $t end) else . end)' \
      "$TMP/reels-final.json" >"$TMP/reels-final.json.new" \
      && mv "$TMP/reels-final.json.new" "$TMP/reels-final.json"
    sleep 0.5
  done <"$TMP/top-codes.txt"
else
  cp "$TMP/reels-with-cap.json" "$TMP/reels-final.json"
fi

# --- Stage 3b: comments for top-K by plays ---
if [[ $WITH_COMMENTS -gt 0 ]]; then
  echo "==> stage 3b: comments (top-$WITH_COMMENTS by plays)"
  jq -r --argjson n "$WITH_COMMENTS" 'sort_by(-.plays) | .[:$n] | .[].code' \
    "$TMP/reels-final.json" >"$TMP/comment-codes.txt"
  while read -r code; do
    [[ -z "$code" ]] && continue
    url="https://www.instagram.com/reel/$code/"
    com_out="$TMP/com-$code.json"
    echo "  comments $code"
    com_arr="[]"
    if call_get /v2/instagram/post/comments "$com_out" "url=$url"; then
      # ScrapeCreators comments shape varies; extract a normalized subset.
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
      "$TMP/reels-final.json" >"$TMP/reels-final.json.new" \
      && mv "$TMP/reels-final.json.new" "$TMP/reels-final.json"
    sleep 0.5
  done <"$TMP/comment-codes.txt"
fi

# --- Stage 3c: download cover JPEGs ---
if [[ $DOWNLOAD_COVERS -eq 1 ]]; then
  echo "==> stage 3c: downloading cover images → $COVERS_DIR"
  mkdir -p "$COVERS_DIR"
  while read -r row; do
    code="$(jq -r '.code' <<<"$row")"
    cover="$(jq -r '.cover_url // ""' <<<"$row")"
    [[ -z "$cover" || "$cover" == "null" ]] && { echo "  [$code] no cover_url"; continue; }
    target="$COVERS_DIR/$code.jpg"
    if curl -sS -o "$target" -w '%{http_code}' "$cover" | grep -q '^200$'; then
      echo "  [$code] saved $(stat -c%s "$target" 2>/dev/null || stat -f%z "$target") bytes"
    else
      echo "  [$code] download failed"
      rm -f "$target"
    fi
    sleep 0.2
  done < <(jq -c '.[]' "$TMP/reels-final.json")
  # Update local-path field
  jq --arg d "$COVERS_DIR" \
    'map(if .cover_url then .cover_local = ($d + "/" + .code + ".jpg") else . end)' \
    "$TMP/reels-final.json" >"$TMP/reels-final.json.new" \
    && mv "$TMP/reels-final.json.new" "$TMP/reels-final.json"
fi

# --- Stage 4: profile ---
profile_file="$TMP/profile.json"
echo '{}' >"$profile_file"
if [[ $WANT_PROFILE -eq 1 ]]; then
  echo "==> stage 4: profile"
  call_get /v1/instagram/profile "$profile_file" "handle=$HANDLE" \
    || { echo "  profile failed; continuing without"; echo '{}' >"$profile_file"; }
fi

# --- Assemble final JSON ---
jq -n \
  --arg handle "$HANDLE" \
  --arg fetched_at "$(date -u +%FT%TZ)" \
  --arg target "$COUNT" \
  --slurpfile profile "$profile_file" \
  --slurpfile reels "$TMP/reels-final.json" \
  '{
    handle: $handle,
    fetched_at: $fetched_at,
    target_count: ($target|tonumber),
    actual_count: ($reels[0] | length),
    profile: $profile[0],
    reels: $reels[0]
  }' >"$OUT_FILE"

echo
echo "── summary ──"
jq -r '
  "handle:          @\(.handle)",
  "fetched at:      \(.fetched_at)",
  "reels collected: \(.actual_count)/\(.target_count)",
  "with caption:    \([.reels[] | select(.caption != null)] | length)",
  "with transcript: \([.reels[] | select(.transcript != null)] | length)",
  "with comments:   \([.reels[] | select(.comments_sample != null)] | length)",
  "with cover_url:  \([.reels[] | select(.cover_url != null)] | length)",
  "covers on disk:  \([.reels[] | select(.cover_local != null)] | length)",
  "total plays:     \([.reels[].plays] | add)",
  "total likes:     \([.reels[].likes] | add)",
  "total comments:  \([.reels[].comments] | add)",
  "median plays:    \([.reels[].plays] | sort | .[length/2|floor])"
' "$OUT_FILE"

echo
echo "raw → $OUT_FILE"
[[ $DOWNLOAD_COVERS -eq 1 ]] && echo "covers → $COVERS_DIR/"

# Record actual credits used. We don't get a per-call counter from the
# server; we approximate from what we actually fetched (similar shape
# to the EST in pre-flight, but using the actual_count, not target).
ACTUAL=$((1 + got/10*5 + got))                              # profile + paginate + captions
[[ "$WANT_TRANSCRIPTS" -eq 1 ]] && ACTUAL=$((ACTUAL + TOP_TRANS * 30))
[[ "$WITH_COMMENTS"    -gt 0 ]] && ACTUAL=$((ACTUAL + WITH_COMMENTS * 5))
[[ "$DOWNLOAD_COVERS"  -eq 1 ]] && ACTUAL=$((ACTUAL + got))
budget_guard_record "bulk-fetch:$HANDLE" "$ACTUAL"
echo "  budget recorded: ~$ACTUAL credits used"
