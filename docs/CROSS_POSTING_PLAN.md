# Cross-Platform Publishing Plan
## Ghost + LinkedIn + Substack

**Goal**: After every `BLOG:` pipeline run, the post is live on Ghost, shared on LinkedIn (personal profile + company page, summary + link card), and available on Substack — using the existing pipeline architecture with minimal added complexity.

**Date drafted**: 27 March 2026  
**Status**: Phase 1 complete. Phase 2 partially complete.

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

### 5. LinkedIn Thumbnail — OG Scrape vs. Upload

The LinkedIn Images API can pre-upload a thumbnail for guaranteed display. Unlike OG scraping, this is reliable. The pipeline now pre-uploads the feature image separately per author URN (person and organisation), since LinkedIn requires the `owner` to match the posting entity.

---

## Architecture Overview

```
BLOG: topic
  └─► Orchestrator
        ├─► Researcher
        ├─► Writer
        ├─► Editor
        ├─► Publisher
        │     ├─► pick_random_asset_image()
        │     ├─► upload_image_to_ghost()
        │     ├─► publish_file_to_ghost()       → Ghost (live post)
        │     └─► post_to_linkedin()            → LinkedIn personal profile + company page
        └─► Indexer
```

Substack receives posts via periodic RSS import (manual) — no pipeline changes needed.

---

## Phase 0 — Access Setup (Complete)

### LinkedIn

1. LinkedIn Developer App created: `BeyondTomorrow Publisher`
2. **"Share on LinkedIn"** product approved → `w_member_social` scope active
3. **"Share on LinkedIn" (Organisation)**  → `w_organization_social` scope active
4. Redirect URI set: `http://localhost:8000/callback`
5. `scripts/linkedin_auth.py` run → all six variables saved to `.env`

To refresh tokens (every 60 days):
```bash
.venv/bin/python scripts/linkedin_auth.py
```

### Substack

6. RSS import completed for existing posts: `https://beyondtomorrow.world/rss/`
7. New posts: repeat import manually after each publishing batch (2 clicks in Substack settings)

---

## Phase 1 — Code Changes (Complete)

### `scripts/linkedin_auth.py` (complete)

OAuth 2.0 helper script:

- Builds LinkedIn authorisation URL with `openid profile w_member_social w_organization_social` scopes
- Starts a temporary localhost HTTP server on port 8000 to receive the callback
- Exchanges the `?code=...` for an access token via `POST https://www.linkedin.com/oauth/v2/accessToken`
- Calls `GET https://api.linkedin.com/v2/userinfo` to get the person URN
- Calls `GET /rest/organizationAcls?q=roleAssignee&role=ADMINISTRATOR` to auto-detect the company URN
- Saves `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_PERSON_URN`, `LINKEDIN_TOKEN_EXPIRES`, `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, and `LINKEDIN_COMPANY_URN` to `.env`

### `pipeline/tools/linkedin.py` (complete)

Implemented `post_to_linkedin` tool with:

- **`_post_as_author(client, author_urn, label, ...)`** shared helper used for both personal and company posting
  - Uploads image with `owner` set to the posting entity's URN (required by LinkedIn)
  - Retries on 429 with exponential backoff; max `_RETRY_ATTEMPTS` attempts
  - Returns full share URN (e.g. `urn:li:share:7445854625041240064`) using `x-restli-id` header directly
- **Dedup guard**: `logs/linkedin_posts.json` tracks posted URLs; personal key = `post_url`, company key = `post_url|{company_urn}`
- **Token expiry warning**: reads `LINKEDIN_TOKEN_EXPIRES`, warns in pipeline output when ≤7 days remain
- **Company page**: reads `LINKEDIN_COMPANY_URN`; validates `urn:li:organization:` format; posts independently; non-blocking if not configured
- **API version constant**: `_LINKEDIN_API_VERSION = "202503"` — update here when bumping the version
- Returns: `Personal: urn:li:share:X | Company: urn:li:share:Y` (or partial)

### `pipeline/tools/__init__.py` (complete)

`post_to_linkedin` exported.

### `pipeline/definitions.py` — Publisher agent (complete)

- `post_to_linkedin` added to tools list
- Publisher instructions updated with LinkedIn step (Step 4)

### `pipeline/main.py` (complete)

- `_build_publish_input(filename)` helper extracted (was duplicated inline)
- `_check_status()` LinkedIn section: shows token value with expiry, `LINKEDIN_COMPANY_URN` status
- `_run_publish_only()` disables OpenAI tracing (`OPENAI_AGENTS_DISABLE_TRACING=1`)

### `.env` (complete)

All six LinkedIn variables set.

### `.github/copilot-instructions.md` and `service-auth/SKILL.md` (complete)

Documented.

---

## Files Summary

| File | Change | Status |
|---|---|---|
| `scripts/linkedin_auth.py` | New | ✅ Complete |
| `pipeline/tools/linkedin.py` | New | ✅ Complete |
| `pipeline/tools/__init__.py` | Modified | ✅ Complete |
| `pipeline/definitions.py` | Modified | ✅ Complete |
| `pipeline/main.py` | Modified | ✅ Complete |
| `.env` | Modified | ✅ Complete |
| `.github/copilot-instructions.md` | Modified | ✅ Complete |
| `.github/skills/service-auth/SKILL.md` | Modified | ✅ Complete |
| `tests/test_linkedin.py` | New | ✅ Complete |

---

## Environment Variables

| Variable | Description |
|---|---|
| `LINKEDIN_CLIENT_ID` | App Client ID from developer.linkedin.com |
| `LINKEDIN_CLIENT_SECRET` | App Client Secret |
| `LINKEDIN_ACCESS_TOKEN` | OAuth access token — expires 60 days after issue |
| `LINKEDIN_PERSON_URN` | `urn:li:person:{id}` — your LinkedIn member ID |
| `LINKEDIN_TOKEN_EXPIRES` | `YYYY-MM-DD` expiry date — pipeline warns when ≤7 days remain |
| `LINKEDIN_COMPANY_URN` | `urn:li:organization:{id}` — Beyond Tomorrow company page (optional) |

---

## Verification Steps

1. ✅ Run `scripts/linkedin_auth.py` → token, URN, and expiry saved to `.env`
2. ✅ Run `.venv/bin/python -m pipeline.main status` → LinkedIn vars confirmed set
3. ✅ Run `PUBLISH: 2026-03-28-assess-the-cost-of-edited.md` → Ghost published live; LinkedIn personal posted
4. Run Substack RSS import → confirm existing Ghost posts appear as drafts in Substack ✓
5. Publish one Substack draft manually to verify formatting ✓

---

## Phase 2 — Future Improvements

| Improvement | Complexity | Benefit | Status |
|---|---|---|---|
| LinkedIn token expiry tracking + pipeline warning | Low | Prevents silent failures | ✅ Done |
| LinkedIn thumbnail pre-upload via Images API | Low | Guaranteed thumbnail vs. OG scrape | ✅ Done |
| Duplicate post guard (`logs/linkedin_posts.json`) | Low | Prevents reposting same article | ✅ Done |
| Company page posting (`LINKEDIN_COMPANY_URN`) | Medium | Broader audience | ✅ Done |
| LinkedIn refresh token flow (auto-renew) | Medium — requires `r_member_social` approval | Removes 60-day manual re-auth | ❌ Not done |
| Substack unofficial API (`substack-api` package) | Medium — fragile, cookie-based | Automates Substack posting | ❌ Not done |
| Ghost webhook → LinkedIn (decoupled from pipeline) | Medium — needs a small HTTP endpoint | Posts on manual Ghost publishes too | ❌ Not done |

---

## Constraints and Limitations

- **LinkedIn**: Access tokens expire every 60 days. No automated refresh yet — re-run `scripts/linkedin_auth.py` manually.
- **LinkedIn rate limit**: 150 posts/day per member — far above pipeline needs.
- **LinkedIn company page**: Requires `w_organization_social` scope. Set `LINKEDIN_COMPANY_URN` in `.env` to activate. If unset, personal-only posting continues silently.
- **Substack**: No official API. Manual RSS import is the only reliable supported path.
- **Post format**: LinkedIn posts link back to Ghost (canonical URL). No full article mirroring.
- **Failure handling**: LinkedIn failure does NOT block Ghost publish. Publisher agent treats it as non-blocking.
