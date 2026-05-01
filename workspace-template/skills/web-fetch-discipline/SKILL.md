---
name: web-fetch-discipline
description: "Decision tree for fetching content from any external URL. Resolves which tool to use: Jina-Reader-via-markdown-extract (default for any web page including SPAs), Playwright MCP (for auth/interactive/screenshots), or built-in WebFetch (only confirmed-static HTML). Triggers: 'open url', 'fetch page', 'read website', 'разбери сайт', 'проанализируй страницу', 'screenshot', 'auth login', 'private page'."
user-invocable: true
---

# web-fetch-discipline

When the operator asks me to read or analyze ANY external web page, I pick the
right tool deterministically — not by gut feel. This skill encodes the rules.

## Live regression that motivated this skill (2026-05-01)

I (Tyrion) tried to read `course.u10.studio` via the **built-in `WebFetch`**
tool and got a 794-byte empty `<div id="root"></div>` shell — the page is a
React/Vite SPA, content is rendered client-side by JS, and WebFetch does not
execute JavaScript. I diagnosed "we need Playwright" and asked the operator
for screenshots.

The operator then ran `r.jina.ai/https://course.u10.studio/` directly — Jina
Reader returned **12 KB of full markdown** including the page's hero copy,
pricing, sections, the author's name, and CTAs. **Jina runs a headless
browser server-side** and serves the rendered DOM as markdown.

**Lesson**: I had `markdown-extract` skill installed, which is exactly a
wrapper for Jina Reader. I just didn't reach for it. From now on it's the
**default** for any external URL.

## Decision tree (run mentally before any external fetch)

```
External URL → which tool?
│
├─ Is it a public page (no auth, no signed cookies, no login wall)?
│  │
│  └─ YES → markdown-extract skill (Jina Reader, free, handles SPAs)
│           ✓ React/Vue/Svelte/Next/Vite SPAs render correctly
│           ✓ ~80% token saving vs raw HTML
│           ✓ Free tier is generous; no API key needed
│           ✗ Some sites with aggressive bot-detection may serve a captcha
│           ✗ Doesn't handle interaction (clicks, scroll, form fills)
│
├─ Is it auth-required, behind login, or needs interaction (click, scroll, fill)?
│  │
│  └─ YES → mcp__playwright__navigate (+ mcp__playwright__get_page_text /
│           click / fill / screenshot / network_requests as needed)
│           ✓ Real Chromium, full JS, can log in, click, scroll
│           ✓ Sees XHR network traffic (useful for ManyChat / API exploration)
│           ✓ Can screenshot
│           ✗ Heavier than Jina (~2-3s startup), runs locally on VPS
│           ✗ Cookies don't persist between calls unless we ask
│
├─ Is it a static HTML page I've already confirmed has no JS dependency?
│  │
│  └─ YES → built-in WebFetch (when nothing more sophisticated is needed)
│           ✓ Cheapest, fastest
│           ✗ Returns empty/garbage for SPAs — DEFAULT TO Jina if unsure
│
└─ Always: if the first tool returns suspiciously little content (<1KB on a
   page that looked content-rich), retry with the next tier up. Don't trust
   small responses.
```

## Hard rules

1. **Default for any web URL = `markdown-extract` skill.** Not WebFetch. If
   you're about to type "WebFetch" — pause and ask: did I confirm this is
   non-SPA? Most modern sites (any 2020+ marketing landing) are SPAs.

2. **WebFetch responses < ~1 KB on a "real" page = SPA red flag.** Re-fetch
   via markdown-extract. The empty-shell return is the canonical SPA tell.

3. **Auth / interactive / screenshot needs = `mcp__playwright__*` tools.**
   These are MCP-native (no shell wrapping); claude routes them like any
   other tool call.

4. **Document the failure mode in `core/LEARNINGS.md`** the first time you
   hit a wall: "tried WebFetch on X, got Y bytes, switched to markdown-
   extract, got Z bytes" — pin the lesson.

## Quick reference — invocation cheat sheet

```text
# Default (any public page)
Skill(markdown-extract)  # passes URL, returns markdown

# Auth or interactive
mcp__playwright__navigate { url: "..." }
mcp__playwright__get_page_text {}
mcp__playwright__network_requests {}     # see XHR traffic
mcp__playwright__screenshot { format: "png" }
mcp__playwright__click { ref: "...", element: "Login button" }
mcp__playwright__fill { ... }

# Last resort (confirmed static HTML)
WebFetch(url, prompt)
```

## Anti-patterns

- ❌ Reaching for WebFetch first because "it's the built-in one". WebFetch
  was designed before SPAs took over.
- ❌ Asking the operator for screenshots when Jina or Playwright would work.
  That's lazy — the operator hired me to read the web, not to be a relay.
- ❌ Falling back to "I can't see the page" without trying both Jina and
  Playwright. Both are local/free; cost of trying = 5 seconds.
- ❌ Forgetting that `markdown-extract` exists. It is in your `skills/`
  directory. Read its SKILL.md if you don't remember its trigger phrases.

## When all three fail

Real cases where neither tool gets you the content:
- **CloudFlare turnstile / hCaptcha** — site rejects all automated access.
  Don't burn time. Ask operator for a screenshot OR for a paste of the
  visible text.
- **Geo-block** — VPS IP not in the country the site serves. Ask operator
  to paste content; or schedule a follow-up via `self-schedule` for when
  you have a workaround.
- **Truly private content (logged-in account)** — operator must paste, or
  use Playwright with a saved session-cookie they provide once.

In all of the above, name the failure mode explicitly in your reply so the
operator knows the limit, not "I don't know".
