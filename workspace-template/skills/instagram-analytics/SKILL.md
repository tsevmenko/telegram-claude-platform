---
name: instagram-analytics
description: ScrapeCreators-backed Instagram intelligence — per-author 7-day scan (fetch-author-week.sh, default for any "analyze profile" request — pulls reels + posts + carousels), single-handle quick audit (analyze.sh), reels-only bulk dump with captions and transcripts (bulk-fetch.sh), per-reel detail pulls (reel-details.sh), and mixed-media posts/carousels fetcher (posts-fetch.sh). Use when the operator asks to research a competitor's Instagram, audit a handle, do a deep author dive for content typology, pull captions/transcripts of specific reels, or analyze carousels and posts.
---

# instagram-analytics

Five operations against ScrapeCreators API for public Instagram accounts.

For full pipeline (data → ClickUp → analysis), see `core/docs/competitor-pipeline.md`.

## Default rule (operator, 2026-05-02)

**Profile request → last 7 days, both formats.** When the operator says "проаналізуй @X" / "подивись профіль" without specifying scope, run `fetch-author-week.sh` — it grabs reels AND posts/carousels for the last 7 days. Don't pull more per author unless asked explicitly.

## Operations

### 0. Per-author week scan (default) — `scripts/fetch-author-week.sh`

Runs `bulk-fetch.sh` (reels) + `posts-fetch.sh --media-type all` (posts/carousels), both with `--since-days 7`.

```bash
scripts/fetch-author-week.sh <handle> [--days N] [--with-comments K] [--no-transcripts] [--download]
```

- `--days N` — override 7-day window.
- `--download` — also `--download-covers` for reels and `--download-images` for slides.

**Cost:** depends on author cadence. Typical (4-7 reels + 1-3 carousels/week) ~20-40 credits with transcripts, ~10-15 without.

**Output:** two files in `out/` — `<handle>-bulk-<unix>.json` (reels) and `<handle>-posts-<unix>.json` (mixed).

### 1. Quick audit — `scripts/analyze.sh`

Snapshot a handle's profile + last page of reels (~12) sorted by plays.

```bash
scripts/analyze.sh <handle> [--no-reels] [--reels-limit N]
```

- `<handle>` — username, with or without `@`.
- `--no-reels` — skip reels (1 credit).
- `--reels-limit N` — top-N in stdout summary (default 5).

**Cost:** 2 credits (profile + reels page).
**Output:** `out/<handle>-<unix>.json` + summary stdout.

### 2. Deep author dive — `scripts/bulk-fetch.sh`

Full corpus for typology / content-machine analysis. Paginates reels, pulls caption + cover URL per reel (cover URL is free — extracted from the feed payload), transcripts for top-K by plays, optionally comments and downloaded cover JPEGs.

```bash
scripts/bulk-fetch.sh <handle> [--count N] [--top-transcripts K] [--no-transcripts] [--no-profile]
                              [--with-comments K] [--download-covers]
```

- `--count N` — target number of reels (default 50). Paginates via `max_id`.
- `--top-transcripts K` — transcript only for top-K by plays (default 15). Saves credits vs all-transcripts.
- `--no-transcripts` — skip stage 3 entirely.
- `--no-profile` — skip stage 4 (saves 1 credit).
- `--with-comments K` — fetch top-page of comments for top-K reels by plays. 1 credit per reel. Saves a normalized sample (text, author, like_count, created_at) into `comments_sample`. Off by default.
- `--download-covers` — download cover JPEGs for every reel into `out/<handle>-covers-<unix>/<code>.jpg`. No API credits used; counts against IG CDN bandwidth only. Sets `cover_local` field on each reel.

**Cost (default 50/15, no comments):** ~71 credits.
- 5 reels pages × 1 = ~5
- 50 captions × 1 = 50
- 15 transcripts × 1 = 15
- 1 profile = 1

`--with-comments 15` adds ~15 credits. `--download-covers` adds 0 credits (only network I/O).

Use `--count 30 --top-transcripts 10` to halve the cost (~41 credits).

**Output:** `out/<handle>-bulk-<unix>.json`. Schema:

```json
{
  "handle": "...",
  "fetched_at": "ISO8601",
  "target_count": 50,
  "actual_count": 50,
  "profile": { /* full profile object */ },
  "reels": [
    {
      "code": "...", "pk": "...",
      "taken_at": 1714000000, "duration": 32.5,
      "plays": 12345, "likes": 678, "comments": 90,
      "caption": "...", "transcript": "...",
      "cover_url": "https://...cdn.../1080x1080.jpg",
      "cover_local": "out/<handle>-covers-<unix>/<code>.jpg",
      "comments_sample": [
        { "text": "...", "author": "username", "like_count": 5, "created_at": 1714000000 }
      ]
    }
  ]
}
```

`cover_local` is `null` unless `--download-covers` was passed. `comments_sample` is `null` unless `--with-comments K` was passed and the reel was in top-K.

### 3. Per-reel details — `scripts/reel-details.sh`

Pull caption + transcript for a known shortlist of reel codes.

```bash
scripts/reel-details.sh <code-or-url> [<code-or-url> ...] [--no-transcript]
```

**Cost:** 2 credits per reel (1 post + 1 transcript). `--no-transcript` halves it.

## When to invoke

| Trigger | Operation |
|---|---|
| "посмотри @X", "что у конкурента", quick audit | `analyze.sh` |
| "забери все рилзы", "глубокий анализ автора", "контент-машина", "типизация контента" | `bulk-fetch.sh` |
| "captions для этих 3 рилсов", "транскрипты топ-N" | `reel-details.sh` |

Always announce the cost estimate before running anything over 5 credits.

### 4. Posts + carousels fetch — `scripts/posts-fetch.sh`

Mixed-media feed (carousels, image posts, optionally all). Reels live elsewhere — use `bulk-fetch.sh` for those.

```bash
scripts/posts-fetch.sh <handle> [--count N] [--media-type all|carousel|image]
                                [--download-images] [--with-comments K]
```

- `<handle>` — username, with or without `@`.
- `--count N` — target items after filter (default 5).
- `--media-type` — filter (default `carousel`). Use `all` to keep image posts mixed in.
- `--download-images` — download every slide of every carousel into `out/<handle>-slides-<unix>/<code>/slide-NN.jpg`. No credits, just CDN bandwidth.
- `--with-comments K` — top-page comments for top-K by likes.

**Cost (default 5 carousels, no comments):** ~6 credits (1 page + 5 captions). `--with-comments K` adds K credits.

**Output:** `out/<handle>-posts-<unix>.json` with structure:

```json
{
  "handle": "...",
  "fetched_at": "ISO8601",
  "endpoint": "/v2/instagram/user/posts",
  "media_filter": "carousel",
  "actual_count": 5,
  "items": [
    {
      "code": "...", "pk": "...", "url": "https://www.instagram.com/p/<code>/",
      "taken_at": 1714000000, "type": "carousel",
      "slide_count": 7,
      "likes": 1234, "comments": 56, "plays": null,
      "caption": "...",
      "cover_url": "https://...",
      "slides": [{"url": "...", "local": null}, ...],
      "comments_sample": null
    }
  ]
}
```

**Endpoint detection:** the script feature-detects the working endpoint from a list (`/v2/instagram/user/posts`, `/v1/instagram/user/posts`, `/v1/instagram/user/feed`, `/v1/instagram/user/media`) on first call. If none works, fail loudly — update the candidate list and retry.

## API key

Stored at `~/.config/tyrion/scrapecreators` (chmod 600). Override via `TYRION_SCRAPECREATORS_KEY` env var. Never echoed to stdout.

## Endpoints used

| Purpose | Path | Credits | Used by |
|---|---|---|---|
| Profile | `GET /v1/instagram/profile` | 1 | analyze, bulk-fetch |
| Reels feed (paginated via `max_id`) | `GET /v1/instagram/user/reels` | 1 per page | analyze, bulk-fetch |
| Posts feed (mixed media, paginated) | `GET /v2/instagram/user/posts` (feature-detected) | 1 per page | posts-fetch |
| Post detail (caption + metrics) | `GET /v1/instagram/post` | 1 | bulk-fetch, posts-fetch, reel-details |
| Transcript | `GET /v2/instagram/media/transcript` | 1 | bulk-fetch, reel-details |
| Comments | `GET /v2/instagram/post/comments` | 1 (per item, top-page) | bulk-fetch / posts-fetch (`--with-comments K`) |

All requests use `trim=true` to keep responses small. Auth: `x-api-key`.

**Caption path:** `xdt_shortcode_media.edge_media_to_caption.edges[0].node.text` (no `data.` wrapper despite docs).
**Transcript field:** `transcripts[0].text` (null if no audio / over 2 min).
**Cover URL:** `display_uri` from each reels-feed item (cropped 1080x1080); fallback to `image_versions2.candidates[1].url` (1080x1920 full-frame). Both are FB CDN URLs with **time-limited signatures** — they expire in ~hours. Always `--download-covers` if you need cover images later than the same day.
**Comments shape:** ScrapeCreators normalises into `.comments[]` (with `text`, `user.username`, `like_count`, `created_at`). bulk-fetch normalises further into `comments_sample[]: { text, author, like_count, created_at }`. Top-page only (~20-50 comments per reel); deeper threads not fetched.

## Failure modes

- **HTTP 401** — key invalid. Ask operator.
- **HTTP 404** — handle missing or private. Report and stop.
- **HTTP 429** — rate-limited. Back off; bulk-fetch already sleeps 0.5s between calls.
- **`paging_info` missing** — endpoint reached end of reels; bulk-fetch breaks pagination loop.
- **Transcript null** — silent video or > 2 min. Recorded as null, no retry.

## What this skill does NOT do

- No login, no posting, no DM.
- Cannot fetch private profiles, stories, highlights metadata, or saved.
- Single-snapshot only — no time-series; for trend deltas, run periodically and diff outputs.
- No image OCR; captions only as returned by IG.
