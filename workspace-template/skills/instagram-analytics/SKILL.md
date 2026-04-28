---
name: instagram-analytics
description: "Instagram profile + reels analytics via ScrapeCreators API. Opt-in; not bundled with installer. Stub — implement before use."
status: stub
when_to_use: |
  - Operator asks: "what's @<handle>'s recent reels engagement?"
  - Operator asks: "find the top 10 reels for @<handle> in the last N days"
  - Operator pastes an Instagram profile URL and wants viral analysis.
license: MIT
requires:
  - SCRAPECREATORS_API_KEY at ~/.claude-lab/shared/secrets/scrapecreators.key
---

# Instagram Analytics (stub — fill in before deploying)

This skill is a structural placeholder for an Instagram analytics integration
through [ScrapeCreators](https://scrapecreators.com). It is NOT bundled with
the installer and NOT activated by default — operators pull it in explicitly
when they need it.

## Status

**Stub.** The skill metadata is in place (this file) but the actual scripts
haven't been written. To complete:

1. Sign up at scrapecreators.com, get an API key.
2. Save the key: `mkdir -p ~/.claude-lab/shared/secrets && echo "<key>" > ~/.claude-lab/shared/secrets/scrapecreators.key && chmod 600 ~/.claude-lab/shared/secrets/scrapecreators.key`.
3. Implement `scripts/analyze.sh` per the design below.
4. Run the smoke test: `bash scripts/analyze.sh nasa --days 7`.
5. Drop the `status: stub` line from this frontmatter.

## Design

### Endpoint mapping

| What we want | ScrapeCreators endpoint |
|---|---|
| Profile (followers, bio, recent posts) | `GET /v1/instagram/profile?handle=<h>` |
| Reels page (12 per page, paginated) | `GET /v1/instagram/user/reels?handle=<h>&page=<n>` |
| Single post detail | `GET /v1/instagram/post?url=<url>` |
| Comments under a post | `GET /v2/instagram/post/comments?url=<url>` |
| Reel auto-transcript | `GET /v2/instagram/media/transcript?url=<url>` |

Auth: `x-api-key: <key>` header. JSON responses.

### Output

`scripts/analyze.sh <handle> [--days 7]` should print a JSON document with:

```json
{
  "handle": "nasa",
  "followers": 100123456,
  "verified": true,
  "category": "Government Organization",
  "reels_window_days": 7,
  "reels_total": 14,
  "top_reels": [
    {
      "url": "...",
      "caption_excerpt": "...",
      "views": 1234567,
      "likes": 234567,
      "engagement_score": 1234567 + 10*234567,
      "posted_at": "2026-04-21T14:00:00Z"
    }
  ]
}
```

Engagement score: `views + 10*likes` per common Instagram analytics convention.

### What we DON'T support

ScrapeCreators doesn't expose Instagram hashtag analytics or follower lists.
If the operator asks for those, fail cleanly with a message pointing them at
an alternative provider (Apify or HikerAPI) — don't pretend the data is
unavailable.

### Reference

Author's `qwwiwi/instagram-superpowers/instagram-hikerapi/scripts/analyze.sh`
provides the rough shape (HikerAPI-bound, ~150 lines bash + python). Use it
as a starting point, swap base URL + auth header + response paths.

## Anti-patterns

- ❌ Don't include this skill in the installer's default skill list.
- ❌ Don't hardcode the API key — read from `~/.claude-lab/shared/secrets/`.
- ❌ Don't try to download media (use a separate Cobalt skill if needed).
- ❌ Don't fail silently when the key is missing — print "set up
  scrapecreators.key first" and exit 0.
