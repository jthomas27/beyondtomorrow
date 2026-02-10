# Ghost Publishing Guide

Quick reference for creating and updating posts on BeyondTomorrow.World via the Ghost Admin API.

**Ghost URL:** `https://www.beyondtomorrow.world`
**API Base:** `https://www.beyondtomorrow.world/ghost/api/admin/`
**Ghost Version:** 5.x (Lexical editor)

---

## Authentication

Ghost supports two auth methods for the Admin API. Use **token auth** for automated publishing (agents, scripts, CI). Use **session auth** only for one-off manual operations.

### Token Auth (Recommended for Agents)

A custom integration called **"Publisher Agent"** is already configured in Ghost Admin.

**Current setup:**
- Integration: `Publisher Agent` (created 2026-02-10)
- Admin API Key format: `{id}:{secret}` (64-char hex secret)
- Stored in Railway as: `GHOST_ADMIN_API_KEY`
- View in Ghost Admin: `https://www.beyondtomorrow.world/ghost/#/settings/integrations`

**If the key is lost or needs to be recreated:**

```bash
# One-time setup — logs in, creates integration, saves key to Railway, pushes code injection
node setup-ghost-api.js --email admin@beyondtomorrow.world --password <password>
```

This script (`setup-ghost-api.js`) does the following:
1. Logs in via session auth (one-time)
2. Checks for an existing "Publisher Agent" integration
3. Creates one if not found → gets the Admin API Key
4. Saves `GHOST_ADMIN_API_KEY` to Railway via `railway variables --set`
5. Pushes `header.txt` + `footer.txt` into Ghost Code Injection

**If you only need to create the integration manually:**
1. Go to `https://www.beyondtomorrow.world/ghost/#/settings/integrations`
2. Click **Add Custom Integration** → name it "Publisher Agent"
3. Copy the **Admin API Key** (format: `{id}:{secret}`)
4. Save to Railway: `railway variables --set "GHOST_ADMIN_API_KEY={id}:{secret}"`

**Generating a JWT for API requests:**

The Admin API Key is not used directly — it must be converted to a short-lived JWT for each request. Both `inject-code.js` and `setup-ghost-api.js` handle this automatically. For custom scripts:

```javascript
const crypto = require('crypto');

function makeToken(apiKey) {
  const [id, secret] = apiKey.split(':');
  const header = Buffer.from(JSON.stringify({
    alg: 'HS256', typ: 'JWT', kid: id
  })).toString('base64url');
  const payload = Buffer.from(JSON.stringify({
    iat: Math.floor(Date.now() / 1000),
    exp: Math.floor(Date.now() / 1000) + 300,
    aud: '/admin/'
  })).toString('base64url');
  const signature = crypto
    .createHmac('sha256', Buffer.from(secret, 'hex'))
    .update(`${header}.${payload}`)
    .digest('base64url');
  return `${header}.${payload}.${signature}`;
}

// Use in requests:
// Authorization: Ghost {token}
```

> **Note:** This implementation uses Node.js built-in `crypto` — no `jsonwebtoken` dependency required.

### Session Auth (Manual / One-Off)

```javascript
POST /ghost/api/admin/session/
Content-Type: application/json
Origin: https://www.beyondtomorrow.world

{ "username": "admin@beyondtomorrow.world", "password": "..." }
```

- Admin email: `admin@beyondtomorrow.world` (password in Railway env: `mail__options__auth__pass`)
- Returns `201` with `set-cookie` header
- Returns `403` if device verification is enabled → requires email code via `PUT /ghost/api/admin/session/verify/`
- Returns `429` if rate-limited → redeploy Ghost to clear: `railway redeploy --yes`
- Send the cookie with all subsequent requests

**Note:** Device verification (`security__staffDeviceVerification`) triggers a 2FA email on every new session. This makes session auth impractical for automation. Use token auth instead.

---

## Content Format

Ghost 5 uses **Lexical** as its native content format. There are two ways to send content:

### Option A: HTML with `?source=html` (Simplest)

Ghost converts HTML to Lexical automatically. Conversion is **lossy** — Ghost may alter the HTML structure.

```
POST /ghost/api/admin/posts/?source=html

{
  "posts": [{
    "title": "Post Title",
    "html": "<p>Your content here...</p>",
    "status": "published"
  }]
}
```

**Best for:** Simple text posts without custom formatting requirements.

### Option B: Lexical HTML Card (Lossless — Recommended)

Wrap your entire HTML body in a Lexical `html` card. Ghost renders it exactly as-is. No conversion, no loss.

```javascript
function buildLexical(html) {
  return JSON.stringify({
    root: {
      children: [{
        type: 'html',
        version: 1,
        html: html
      }],
      direction: 'ltr',
      format: '',
      indent: 0,
      type: 'root',
      version: 1
    }
  });
}
```

```
POST /ghost/api/admin/posts/

{
  "posts": [{
    "title": "Post Title",
    "lexical": "{...lexical JSON string...}",
    "status": "published"
  }]
}
```

**Best for:** Posts with charts, custom HTML, embedded scripts, or precise formatting. This is the method to use for all BeyondTomorrow posts.

### ⚠️ Updating Existing Posts

When updating a post that already has Lexical content, you **must** send `lexical` — not `html`. Sending `html` alone is silently ignored. Always include `id` and `updated_at`:

```
PUT /ghost/api/admin/posts/{id}/

{
  "posts": [{
    "id": "...",
    "updated_at": "2026-02-10T11:22:53.000Z",
    "lexical": "{...}"
  }]
}
```

---

## Post Structure

A typical BeyondTomorrow post includes all of these fields:

```javascript
{
  "posts": [{
    // Required
    "title": "The Future of AI Regulation in Europe",
    "lexical": buildLexical(htmlBody),     // content body (500–1500 words)
    "status": "published",                 // "draft" | "published" | "scheduled"

    // Feature image (upload first, then reference the URL)
    "feature_image": "https://www.beyondtomorrow.world/content/images/2026/02/ai-regulation.jpg",
    "feature_image_alt": "EU parliament building with AI overlay",
    "feature_image_caption": "Credit: Generated with DALL-E",

    // Metadata
    "custom_excerpt": "The EU's AI Act is reshaping how...",  // 1-2 sentences, shown in previews
    "meta_title": "The Future of AI Regulation in Europe — BeyondTomorrow",
    "meta_description": "How the EU AI Act will reshape...",  // ≤160 chars for SEO

    // Tags (auto-created if they don't exist)
    "tags": ["AI", "Geopolitics", "Regulation"],

    // Social previews
    "og_title": "The Future of AI Regulation in Europe",
    "og_description": "How the EU AI Act will reshape...",
    "twitter_title": "The Future of AI Regulation in Europe",
    "twitter_description": "How the EU AI Act will reshape...",

    // Scheduling (use with status: "scheduled")
    "published_at": "2026-02-15T09:00:00.000Z"
  }]
}
```

---

## Image Upload

Images must be uploaded **before** creating the post. The API returns a URL you then reference in the post body or `feature_image`.

```
POST /ghost/api/admin/images/upload/
Content-Type: multipart/form-data
```

Form fields:
| Field | Type | Description |
|-------|------|-------------|
| `file` | File/Blob | The image file (WEBP, JPEG, PNG, GIF, SVG) |
| `purpose` | String | `image` (default), `profile_image`, or `icon` |
| `ref` | String | Optional reference name for matching after upload |

Response:
```json
{
  "images": [{
    "url": "https://www.beyondtomorrow.world/content/images/2026/02/ai-chart.png",
    "ref": "ai-chart.png"
  }]
}
```

### Node.js Upload Example

```javascript
const FormData = require('form-data');
const fs = require('fs');

async function uploadImage(imagePath, cookie) {
  const form = new FormData();
  form.append('file', fs.createReadStream(imagePath));
  form.append('purpose', 'image');
  form.append('ref', path.basename(imagePath));

  const res = await fetch(`${GHOST_URL}/ghost/api/admin/images/upload/`, {
    method: 'POST',
    headers: { Origin: GHOST_URL, Cookie: cookie, ...form.getHeaders() },
    body: form
  });
  const data = await res.json();
  return data.images[0].url;  // use this URL in feature_image or html body
}
```

---

## JavaScript Charts in Posts

Ghost renders HTML cards exactly as written, including `<script>` tags. Embed charts directly in the HTML body using Chart.js, D3, or any CDN-loaded library.

### Chart.js Example

```html
<div style="max-width: 600px; margin: 2em auto;">
  <canvas id="ai-adoption-chart"></canvas>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script>
new Chart(document.getElementById('ai-adoption-chart'), {
  type: 'bar',
  data: {
    labels: ['2022', '2023', '2024', '2025', '2026'],
    datasets: [{
      label: 'Enterprise AI Adoption (%)',
      data: [35, 42, 55, 67, 78],
      backgroundColor: '#c8b8ff'
    }]
  },
  options: {
    responsive: true,
    plugins: { legend: { position: 'bottom' } }
  }
});
</script>
```

### How to Include in a Post

Include the chart HTML inside the same HTML string passed to `buildLexical()`. Everything inside the Lexical `html` card renders as raw HTML, including scripts.

```javascript
const body = `
<p>Intro paragraph...</p>

<h2>The Data</h2>
<p>Enterprise AI adoption has grown steadily:</p>

<div style="max-width: 600px; margin: 2em auto;">
  <canvas id="chart1"></canvas>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script>
new Chart(document.getElementById('chart1'), { /* config */ });
</script>

<p>As the chart shows...</p>
`;

const lexical = buildLexical(body);
```

### Notes on Charts
- Load chart libraries from CDN — Ghost does not bundle them
- Use unique `id` attributes if a post has multiple charts
- Charts render on page load only (no server-side rendering)
- Keep chart data inline in the script — no external API calls at render time
- Test locally first: paste the HTML into Ghost Admin → toggle to HTML card

---

## Input File Format

For automated publishing, agents should produce a JSON file per post:

```
posts/
  2026-02-10-ai-regulation.json
  2026-02-11-china-tariffs.json
  images/
    ai-regulation.jpg
    china-tariffs.png
```

### Post JSON Schema

```json
{
  "title": "string (required)",
  "slug": "string (optional, auto-generated from title)",
  "html": "string (required, the post body as HTML, 500-1500 words)",
  "excerpt": "string (required, 1-2 sentences)",
  "tags": ["string"],
  "feature_image": "string (local path to image file)",
  "feature_image_alt": "string",
  "meta_title": "string (≤70 chars)",
  "meta_description": "string (≤160 chars)",
  "status": "draft | published | scheduled",
  "published_at": "ISO 8601 (required if status is scheduled)",
  "charts": [
    {
      "id": "string (unique canvas id)",
      "type": "bar | line | pie | doughnut",
      "title": "string",
      "labels": ["string"],
      "datasets": [{ "label": "string", "data": [0] }]
    }
  ]
}
```

The publishing script should:
1. Read the JSON file
2. Upload `feature_image` → get back the Ghost URL
3. Generate chart HTML from `charts` array (if present)
4. Combine `html` body + chart HTML
5. Wrap in `buildLexical()`
6. POST to Ghost API

---

## Validation Checklist

After creating or updating a post, verify all of the following:

### API Response Checks (Immediate)

```javascript
async function validatePost(postId, cookie) {
  const res = await fetch(
    `${GHOST_URL}/ghost/api/admin/posts/${postId}/?formats=html,lexical`,
    { headers: { Cookie: cookie, Origin: GHOST_URL } }
  );
  const { posts } = await res.json();
  const post = posts[0];

  const checks = {
    exists:         !!post,
    published:      post.status === 'published',
    hasTitle:       !!post.title && post.title.length > 0,
    hasContent:     !!post.html && post.html.length > 100,
    hasImage:       !!post.feature_image,
    hasExcerpt:     !!post.custom_excerpt,
    hasTags:        post.tags && post.tags.length > 0,
    hasMetaTitle:   !!post.meta_title,
    hasMetaDesc:    !!post.meta_description,
    urlAccessible:  !!post.url,
  };

  const passed = Object.values(checks).every(v => v);
  console.log(passed ? '✅ All checks passed' : '❌ Some checks failed');
  console.log(checks);
  return { passed, checks, post };
}
```

### Live Page Checks (After Publish)

```javascript
async function validateLivePage(slug) {
  const url = `https://www.beyondtomorrow.world/${slug}/`;
  const res = await fetch(url);
  const html = await res.text();

  const checks = {
    httpOk:         res.status === 200,
    hasContent:     html.includes('gh-content') && html.length > 5000,
    hasTitle:       html.includes('<h1'),
    hasImage:       html.includes('feature-image') || html.includes('content/images'),
    hasCharts:      !html.includes('chart.js') || html.includes('<canvas'),
    noError:        !html.includes('error') && !html.includes('404'),
    ogTags:         html.includes('og:title') && html.includes('og:description'),
  };

  const passed = Object.values(checks).every(v => v);
  console.log(passed ? '✅ Live page OK' : '❌ Live page issues');
  console.log(checks);
  return { passed, checks };
}
```

### Quick Validation Summary

| Check | Method | Pass Criteria |
|-------|--------|---------------|
| API returns post | `GET /posts/{id}/` | Status 200, post object exists |
| Status is published | API response | `status === "published"` |
| HTML body present | API response `?formats=html` | `html.length > 100` |
| Feature image set | API response | `feature_image` is a valid URL |
| Tags assigned | API response | `tags.length > 0` |
| Meta fields set | API response | `meta_title` and `meta_description` present |
| Live page loads | `GET /{slug}/` | HTTP 200 |
| Content renders | Live HTML | Body contains post text |
| Image renders | Live HTML | `<img>` tag with image URL |
| Charts render | Live HTML | `<canvas>` elements present (if charts used) |

---

## Complete Publishing Script Template

```javascript
const https = require('https');
const fs = require('fs');
const path = require('path');
const jwt = require('jsonwebtoken');

const GHOST_URL = 'https://www.beyondtomorrow.world';
const API_KEY = process.env.GHOST_ADMIN_API_KEY; // {id}:{secret}

function ghostToken() {
  const [id, secret] = API_KEY.split(':');
  return jwt.sign({}, Buffer.from(secret, 'hex'), {
    keyid: id, algorithm: 'HS256', expiresIn: '5m', audience: '/admin/'
  });
}

function buildLexical(html) {
  return JSON.stringify({
    root: {
      children: [{ type: 'html', version: 1, html }],
      direction: 'ltr', format: '', indent: 0, type: 'root', version: 1
    }
  });
}

async function publish(postJson) {
  const token = ghostToken();
  const auth = { Authorization: `Ghost ${token}` };

  // 1. Upload feature image (if local path)
  let featureImageUrl = postJson.feature_image;
  if (featureImageUrl && !featureImageUrl.startsWith('http')) {
    featureImageUrl = await uploadImage(featureImageUrl, auth);
  }

  // 2. Build chart HTML (if charts provided)
  let chartHtml = '';
  if (postJson.charts && postJson.charts.length > 0) {
    chartHtml = buildChartHtml(postJson.charts);
  }

  // 3. Combine body + charts
  const fullHtml = postJson.html + chartHtml;

  // 4. Create post
  const res = await apiRequest('POST', '/ghost/api/admin/posts/', {
    posts: [{
      title: postJson.title,
      slug: postJson.slug,
      lexical: buildLexical(fullHtml),
      status: postJson.status || 'draft',
      published_at: postJson.published_at,
      feature_image: featureImageUrl,
      feature_image_alt: postJson.feature_image_alt,
      custom_excerpt: postJson.excerpt,
      tags: postJson.tags || [],
      meta_title: postJson.meta_title,
      meta_description: postJson.meta_description,
      og_title: postJson.meta_title,
      og_description: postJson.meta_description,
      twitter_title: postJson.meta_title,
      twitter_description: postJson.meta_description,
    }]
  }, auth);

  // 5. Validate
  const post = res.posts[0];
  console.log(`✅ Post created: ${post.url}`);
  console.log(`   ID: ${post.id} | Status: ${post.status}`);
  return post;
}
```

---

## API Quick Reference

| Action | Method | Endpoint |
|--------|--------|----------|
| Create post | `POST` | `/ghost/api/admin/posts/` |
| Update post | `PUT` | `/ghost/api/admin/posts/{id}/` |
| Delete post | `DELETE` | `/ghost/api/admin/posts/{id}/` |
| Get post | `GET` | `/ghost/api/admin/posts/{id}/?formats=html,lexical` |
| Get by slug | `GET` | `/ghost/api/admin/posts/slug/{slug}/?formats=html,lexical` |
| List posts | `GET` | `/ghost/api/admin/posts/?limit=15&page=1` |
| Upload image | `POST` | `/ghost/api/admin/images/upload/` (multipart) |
| Create page | `POST` | `/ghost/api/admin/pages/` |
| Update page | `PUT` | `/ghost/api/admin/pages/{id}/` |

All requests require `Content-Type: application/json` and `Authorization: Ghost {jwt}` (or session cookie).

---

## Code Injection Reference

Code Injection is how BeyondTomorrow's custom theme (dark UI, fonts, animations) is applied on top of Ghost's default Casper theme — without modifying the theme itself.

### Where It Lives

| Slot | Ghost Admin Location | What Goes There |
|------|----------------------|-----------------|
| **Site Header** | Settings → Code Injection → Site Header | `<link>` tags, `<style>` block |
| **Site Footer** | Settings → Code Injection → Site Footer | `<script>` block |

**Direct URL:** `https://www.beyondtomorrow.world/ghost/#/settings/code-injection`

### Source Files in This Repo

| File | Purpose | Injected Into |
|------|---------|---------------|
| `header.txt` | Fonts + full CSS theme (~430 lines) | Site Header (`codeinjection_head`) |
| `footer.txt` | Light-trail particle animation script | Site Footer (`codeinjection_foot`) |
| `ghost-code-injection.html` | Combined reference (header + footer in one file) | Reference only — not injected |
| `inject-code.js` | Pushes header.txt + footer.txt to Ghost via API | Run locally |
| `setup-ghost-api.js` | One-time setup: creates API key + saves to Railway + injects | Run once |

**`header.txt` and `footer.txt` are the source of truth.** Never edit code injection directly in Ghost Admin — always edit these files and push via script.

### Update Protocol

1. **Edit locally** — make changes in `header.txt` (CSS) or `footer.txt` (JS)
2. **Push to Ghost** — run the injection script:
   ```bash
   node inject-code.js
   ```
3. **Verify** — check `https://www.beyondtomorrow.world` in a browser (hard-refresh with ⌘⇧R)
4. **Commit** — save the working version to this repo
5. **Keep in sync** — update `ghost-code-injection.html` too if making large changes

### How `inject-code.js` Works

1. Reads `GHOST_ADMIN_API_KEY` from Railway env vars (or `--key` flag)
2. Generates a short-lived JWT (5 min expiry)
3. Reads `header.txt` and `footer.txt` from the repo
4. `PUT /ghost/api/admin/settings/` with `codeinjection_head` and `codeinjection_foot`
5. Verifies the update by reading settings back

```bash
# Standard usage (key from Railway)
node inject-code.js

# With explicit key override
node inject-code.js --key "<id>:<secret>"

# With env var
GHOST_ADMIN_API_KEY="<id>:<secret>" node inject-code.js
```

### What the Header Contains (CSS)

The `<style>` block in `header.txt` controls the entire visual theme:

| Section | What It Styles |
|---------|---------------|
| `:root` variables | Color palette (`--bt-bg`, `--bt-accent`, `--bt-text`, etc.) |
| Global / Typography | Body background, font families (Inter + Space Grotesk) |
| Site Header / Nav | Frosted-glass navbar with backdrop blur |
| Post Cards | Dark cards with hover lift + glow border effect |
| Tags | Accent-colored pill badges |
| Article Page | Content typography, links, blockquotes, code blocks |
| Subscription / CTA | Newsletter signup form styling |
| Footer | Dark elevated footer |
| Pagination | Styled page nav links |
| Koenig Cards | Bookmark cards, image cards |
| Light trail glow | `::before` pseudo-element glow on card hover |
| Animations | `fadeInUp` keyframe on page load |

### What the Footer Contains (JS)

The `<script>` block in `footer.txt` runs one feature:

- **Animated light-trail canvas** — creates a full-viewport `<canvas>` behind the page with 40 moving particles (lavender + amber). Fades out on scroll.

### Design Tokens (CSS Variables)

These are defined in `:root` and used throughout. Change these to update the entire palette:

```css
--bt-bg:            #0f0f14;        /* page background */
--bt-bg-elevated:   #18181f;        /* footer, raised surfaces */
--bt-bg-card:       #1e1e27;        /* card background */
--bt-bg-card-hover: #252530;        /* card hover state */
--bt-text:          #e8e8ec;        /* primary text */
--bt-text-secondary:#a0a0b0;        /* body text, excerpts */
--bt-text-muted:    #6b6b7b;        /* meta text, dates */
--bt-accent:        #c8b8ff;        /* links, tags, highlights (lavender) */
--bt-accent-dim:    rgba(200, 184, 255, 0.15);  /* accent backgrounds */
--bt-warm:          #ffd6a5;        /* hover link color (amber) */
--bt-border:        rgba(255, 255, 255, 0.06);  /* subtle borders */
--bt-border-hover:  rgba(255, 255, 255, 0.12);  /* hover borders */
--bt-radius:        12px;           /* default border radius */
--bt-radius-lg:     20px;           /* large border radius (cards) */
```

### Fonts

Loaded via Google Fonts `<link>` at the top of `header.txt`:

| Font | Used For | Weights |
|------|----------|---------|
| **Space Grotesk** | Headings, logo, site title | 400, 500, 600, 700 |
| **Inter** | Body text, UI elements | 300, 400, 500, 600, 700 |

### Common Edits

| Task | Where | What to Change |
|------|-------|----------------|
| Change accent color | `header.txt` → `:root` | `--bt-accent` and `--bt-accent-dim` |
| Change background | `header.txt` → `:root` | `--bt-bg` |
| Adjust card hover effect | `header.txt` → `.post-card:hover` | `transform`, `box-shadow` values |
| Change particle count | `footer.txt` → `Array.from` | Number `40` → desired count |
| Change particle colors | `footer.txt` → `LightParticle.reset()` | `this.hue` values (255=lavender, 40=amber) |
| Disable particle animation | `footer.txt` | Remove or comment out the entire `<script>` |
| Add a new font | `header.txt` | Add to `<link>` URL, then reference in CSS |

### Important Notes

- **`!important` is required** — Ghost's Casper theme has high-specificity selectors. Code injection styles must override them.
- **Ghost strips certain tags** — `<style>` and `<script>` are allowed in Code Injection. `<link>` with `rel="stylesheet"` is allowed. Other elements may be stripped.
- **Per-post injection** — individual posts/pages also have their own Code Injection fields (in the post settings sidebar). Use these for page-specific overrides.
- **No undo** — Ghost Code Injection has no version history. Always keep `header.txt` and `footer.txt` committed in the repo as backup. Use `git diff header.txt` to review changes before pushing.
- **Never edit in Ghost Admin** — always edit `header.txt` / `footer.txt` locally and push via `node inject-code.js`. This keeps the repo as the single source of truth.
- **Cache** — browsers may cache injected CSS. Hard-refresh (⌘⇧R) after pushing. Append a version comment (e.g. `/* v2.1 */`) for major changes.
- **Inspect before pushing** — use browser DevTools to test CSS changes live before running `inject-code.js`.
- **Rate limiting** — Ghost limits login attempts. If you get "Too many sign-in attempts", redeploy Ghost: `railway redeploy --yes`. This clears the in-memory rate counter. Token auth (inject-code.js) is not affected by this.
