# Cross-Platform Publishing Plan
## Ghost + LinkedIn + Substack

**Goal**: After every `BLOG:` pipeline run, the post is live on Ghost, shared on LinkedIn (personal profile, summary + link card), and available on Substack — using the existing pipeline architecture with minimal added complexity.

**Date drafted**: 27 March 2026  
**Status**: Approved for implementation

---

## Critical Review — What the Original Plan Got Wrong

Before laying out the implementation, these are the problems uncovered after researching the actual APIs:

### 1. Substack RSS Import Is One-Time Only — Not Ongoing Sync

Substack's "Import from URL" is a bulk migration tool, **not a continuous sync**. After the initial import, new Ghost posts do NOT flow to Substack automatically. There is no official Substack public API.

**Realistic options for Substack:**

| Option | Automation | Reliability | Effort |
|---|---|---|---|
| **A. Manual RSS re-import** (recommended v1) | None — 2 clicks in Substack settings per batch | Rock-solid | Zero |
| **B. Unofficial API** (`substack-api` package) | Full | Fragile — breaks without warning | Medium |
| **C. Zapier/Make.com** | Blocked — no Substack "create post" action exists | N/A | N/A |
| **D. Email-to-Substack** | Possible | Undocumented, unreliable | Low |

**Decision**: Start with Option A. Revisit Option B as Phase 2 if manual import becomes tedious.

### 2. LinkedIn Article Post Type Is Better Than Text-Only

The LinkedIn REST Posts API supports an **Article** content type that creates a rich link preview card (thumbnail + title + description). Plain text with a URL in the body performs worse for engagement. The pipeline already has all required fields from Ghost frontmatter.

### 3. LinkedIn Access Tokens Expire Every 60 Days

This is a real maintenance burden. Refresh tokens last 1 year but require the `r_member_social` scope (needs separate LinkedIn approval). v1 uses manual re-auth; automated refresh is Phase 2.

### 4. LinkedIn App Setup May Take Up to 48 Hours

New apps must add the **"Share on LinkedIn"** product from the Developer Portal Products tab to unlock `w_member_social`. Some apps require manual review before approval.

### 5. LinkedIn Thumbnail: OG Scrape vs. Upload

The LinkedIn Images API can pre-upload a thumbnail for guaranteed display. However, LinkedIn will also scrape `og:image` from Ghost — which already sets a feature image. v1 uses OG scraping (simpler). Phase 2 can add explicit image upload if the preview is inconsistent.

---

## Architecture Overview

```
BLOG: topic
  └─► Orchestrator
        ├─► Researcher
        ├─► Writer
        ├─► Editor
        ├─► Publisher  ← changes here
        │     ├─► pick_random_asset_image()
        │     ├─► upload_image_to_ghost()
        │     ├─► publish_file_to_ghost()       → Ghost (live post)
        │     └─► post_to_linkedin()            → LinkedIn (article card)  [NEW]
        └─► Indexer
```

Substack receives posts via periodic RSS import (manual) — no pipeline changes needed.

---

## Phase 0 — Access Setup (Manual — You Do These Steps)

### LinkedIn

1. Go to [developer.linkedin.com](https://developer.linkedin.com) → **Create App**
   - App name: `BeyondTomorrow Publisher`
   - Associate with a LinkedIn Company Page (required even for personal posting — create a minimal page if needed)
2. Under the **Products** tab, request **"Share on LinkedIn"** → grants `w_member_social` scope
   - Allow up to 48 hours for LinkedIn review
3. Under the **Auth** tab:
   - Note your **Client ID** and **Client Secret**
   - Add redirect URI: `http://localhost:8000/callback`
4. Once the product is approved, run `scripts/linkedin_auth.py` (created in Phase 1) to complete the OAuth flow
5. Add to `.env`:
   ```
   LINKEDIN_CLIENT_ID=...
   LINKEDIN_CLIENT_SECRET=...
   LINKEDIN_ACCESS_TOKEN=...
   LINKEDIN_PERSON_URN=urn:li:person:...
   ```

> **Token expiry reminder**: Access tokens expire after **60 days**. Re-run `scripts/linkedin_auth.py` to refresh. Set a calendar reminder.

### Substack

6. In Substack dashboard: **Settings → Import → Import from URL**
7. Enter: `https://beyondtomorrow.world/rss/`
8. All existing published Ghost posts will appear as **drafts** in Substack for review and publish
9. For new posts: repeat this import after each batch of Ghost publishes (2 clicks)

---

## Phase 1 — Code Changes

### New file: `scripts/linkedin_auth.py`

One-time OAuth 2.0 helper script:

- Builds LinkedIn authorisation URL with `w_member_social` scope
- Starts a temporary localhost HTTP server on port 8000 to receive the callback
- Exchanges the `?code=...` for an access token via `POST https://www.linkedin.com/oauth/v2/accessToken`
- Calls `GET https://api.linkedin.com/v2/userinfo` to get the person URN
- Prints token, URN, and expiry date to stdout
- Optionally appends the values to `.env`

### New file: `pipeline/tools/linkedin.py`

New `@function_tool` following the same pattern as `ghost.py`:

```python
@function_tool
async def post_to_linkedin(title: str, excerpt: str, post_url: str) -> str:
    """Post a blog article card to LinkedIn personal profile."""
```

**Behaviour:**
- Reads `LINKEDIN_ACCESS_TOKEN` and `LINKEDIN_PERSON_URN` from environment
- If either is missing → returns `"SKIPPED: LinkedIn not configured"` (non-blocking, graceful)
- Posts using `httpx` to `POST https://api.linkedin.com/rest/posts` with headers:
  - `Authorization: Bearer {token}`
  - `Linkedin-Version: 202603`
  - `X-Restli-Protocol-Version: 2.0.0`
- Post body (Article type):
  ```json
  {
    "author": "urn:li:person:{id}",
    "commentary": "{excerpt — max 700 chars}\n\n{hashtags from tags}",
    "visibility": "PUBLIC",
    "distribution": { "feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": [] },
    "content": {
      "article": {
        "source": "{ghost_post_url}",
        "title": "{title}",
        "description": "{excerpt}"
      }
    },
    "lifecycleState": "PUBLISHED",
    "isReshareDisabledByAuthor": false
  }
  ```
- Extracts post URN from `x-restli-id` response header on HTTP 201
- Retries on 429 (rate limit) with backoff; max 3 attempts
- Returns `"Published to LinkedIn: urn:li:share:{id}"` or `"Error: {details}"`

### Modified file: `pipeline/tools/__init__.py`

Add `post_to_linkedin` to imports and `__all__`.

### Modified file: `pipeline/definitions.py` — Publisher agent

- Import `post_to_linkedin`
- Add to `tools=[..., post_to_linkedin]`
- Extend Publisher instructions with **Step 5**:

  ```
  STEP 5 — Cross-post to LinkedIn
    Using the title and excerpt from the frontmatter and the Ghost URL from Step 3,
    call post_to_linkedin(title=<title>, excerpt=<excerpt>, post_url=<ghost_url>).
    If the result starts with 'SKIPPED:' or 'Error:', log it but continue.
    LinkedIn posting is non-blocking — Ghost publish is the primary deliverable.
  ```

- Also update Step 4 to clarify the return value should include both the Ghost URL and the LinkedIn result.

### Modified file: `.env` + `.github/copilot-instructions.md`

Add the four new LinkedIn env vars to both files.

---

## Files Summary

| File | Change | Notes |
|---|---|---|
| `scripts/linkedin_auth.py` | **New** | One-time OAuth flow |
| `pipeline/tools/linkedin.py` | **New** | `post_to_linkedin` tool |
| `pipeline/tools/__init__.py` | Modified | Add export |
| `pipeline/definitions.py` | Modified | Publisher agent — add tool + Step 5 |
| `.env` | Modified | 4 new LinkedIn vars |
| `.github/copilot-instructions.md` | Modified | Document new vars |

---

## Environment Variables

| Variable | Description |
|---|---|
| `LINKEDIN_CLIENT_ID` | App Client ID from developer.linkedin.com |
| `LINKEDIN_CLIENT_SECRET` | App Client Secret |
| `LINKEDIN_ACCESS_TOKEN` | OAuth access token — expires 60 days after issue |
| `LINKEDIN_PERSON_URN` | `urn:li:person:{id}` — your LinkedIn member ID |

---

## Verification Steps

1. Run `scripts/linkedin_auth.py` → confirm token and URN printed, saved to `.env`
2. Run `.venv/bin/python -m pipeline.main status` → new LinkedIn vars show as set
3. Run test: `.venv/bin/python -m pipeline.main "BLOG: test topic"` → confirm:
   - Ghost post publishes live ✓
   - LinkedIn article card appears on personal profile with correct title, excerpt, and link ✓
4. Run Substack RSS import → confirm all existing Ghost posts appear as drafts in Substack ✓
5. Publish one Substack draft manually to verify formatting ✓

---

## Phase 2 — Future Improvements (Not in Scope for v1)

| Improvement | Complexity | Benefit |
|---|---|---|
| LinkedIn refresh token flow (auto-renew) | Medium — requires `r_member_social` approval from LinkedIn | Removes 60-day manual re-auth |
| LinkedIn thumbnail pre-upload via Images API | Low — ~40 lines | Guaranteed thumbnail vs. OG scrape |
| Substack unofficial API (`substack-api` package) | Medium — fragile, cookie-based | Automates Substack posting |
| Ghost webhook → LinkedIn (decoupled from pipeline) | Medium — needs a small HTTP endpoint | Posts on manual Ghost publishes too |
| Buffer/Typefully as LinkedIn proxy | Low code, adds paid dependency | Simpler auth, scheduling features |

---

## Constraints and Limitations

- **LinkedIn**: Access tokens expire every 60 days. No automated refresh in v1.
- **LinkedIn rate limit**: 150 posts/day per member — far above pipeline needs.
- **Substack**: No official API. Manual RSS import is the only reliable supported path today.
- **Post format**: LinkedIn posts link back to Ghost (canonical URL). No full article mirroring.
- **Failure handling**: LinkedIn failure does NOT block Ghost publish. Publisher agent treats it as non-blocking.
- **No company page posting** in v1 — personal profile only.
