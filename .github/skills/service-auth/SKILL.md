---
name: service-auth
description: "Authenticate and verify access to Railway, Ghost, Hostinger (IMAP/SMTP), GitHub, and LinkedIn before running scripts or pipeline operations. Use when: accessing Railway variables, publishing to Ghost, checking email credentials, calling GitHub Models API, refreshing LinkedIn tokens, setting up a new environment, or debugging a 401/403/connection error on any of these services."
argument-hint: "Optional: specify a service name to check only that one (railway | ghost | hostinger | github | linkedin)"
---

# Service Authentication

Establishes and verifies credentials for all four external services used by the BeyondTomorrow.World pipeline. **Always run this skill before executing scripts that touch any of these services.**

## Credential Sources (Priority Order)

Credentials are NEVER hardcoded. They are read in this order:

1. **`.env`** at the project root (gitignored) — primary source for local development
2. **`~/.railway/config.json`** — Railway CLI session token (fallback for Railway only)
3. **Environment variables** already exported in the shell

All sensitive values live in `.env`. The file is gitignored and never committed.

## Required `.env` Variables

```
# GitHub Models API
GITHUB_TOKEN=github_pat_...

# Railway GraphQL API (personal token from railway.app/account/tokens)
RAILWAY_TOKEN=...

# Ghost CMS
GHOST_URL=https://beyondtomorrow.world
GHOST_ADMIN_KEY=id:secret
GHOST_ADMIN_EMAIL=admin@beyondtomorrow.world   # owner account email (required for Code Injection / settings API)
GHOST_ADMIN_PASSWORD=...                       # owner account password (required for Code Injection / settings API)

# Hostinger IMAP (email listener)
EMAIL_HOST=imap.hostinger.com
EMAIL_PORT=993
EMAIL_USER=admin@beyondtomorrow.world
EMAIL_PASS=...

# Hostinger SMTP (reply notifications)
SMTP_HOST=smtp.hostinger.com
SMTP_PORT=587
# SMTP_USER and SMTP_PASS default to EMAIL_USER/EMAIL_PASS if not set

# LinkedIn cross-posting (optional)
LINKEDIN_CLIENT_ID=...
LINKEDIN_CLIENT_SECRET=...
LINKEDIN_ACCESS_TOKEN=...        # OAuth 2.0 bearer; expires 60 days after issue
LINKEDIN_PERSON_URN=urn:li:person:...  # your LinkedIn member ID
LINKEDIN_TOKEN_EXPIRES=YYYY-MM-DD      # pipeline warns when ≤7 days remain
```

## Procedure

### Step 1 — Load and verify credentials

Run the auth check script:

```bash
source .venv/bin/activate
python3 scripts/auth_check.py [service]
```

Where `[service]` is optional: `railway`, `ghost`, `hostinger`, or `github`. Omit to check all.

The script will:
- Load credentials from `.env` (never from hardcoded values)
- Test a live connection to each service
- Report ✓ / ✗ with a clear message for each
- Exit non-zero if any check fails

### Step 2 — Fix failures

| Error | Fix |
|---|---|
| `RAILWAY_TOKEN not set` | Go to railway.app/account/tokens → Create Token → paste into `.env` |
| `Railway: Unauthorized` | Token expired — create a new one at railway.app/account/tokens |
| `Ghost: 401 Unauthorized` | `GHOST_ADMIN_KEY` wrong or expired — copy fresh key from Ghost Admin → Settings → Integrations |
| `Ghost: 403 Forbidden` | Using `urllib` — always use `httpx` for Ghost calls |
| `Ghost settings API: 501 Not Implemented` | Custom integration keys cannot edit settings — use session auth via `node scripts/inject-code.js`. Requires `GHOST_ADMIN_EMAIL` + `GHOST_ADMIN_PASSWORD` in `.env` (owner account credentials, same as Ghost Admin login). |
| `Ghost: HTTP 530 / 521 / timeout` | Railway Ghost service is down — restart it at railway.app → caring-alignment → ghost service → Deployments → Restart. The auth check retries 3× automatically. |
| `Hostinger IMAP: auth failed` | `EMAIL_PASS` wrong — verify in Hostinger webmail settings |
| `Hostinger SMTP: auth failed` | Set `SMTP_USER` and `SMTP_PASS` explicitly in `.env` if they differ from IMAP credentials |
| `GitHub: 401` | `GITHUB_TOKEN` expired or missing `models:read` scope — regenerate at github.com/settings/tokens, then follow **Rotating the GitHub PAT** below |
| `LinkedIn: 401` | `LINKEDIN_ACCESS_TOKEN` expired (60-day TTL) — re-run `scripts/linkedin_auth.py` to refresh |
| `LinkedIn: 403` | Missing OAuth scope — re-run `scripts/linkedin_auth.py`; approve `w_member_social` |
| `LinkedIn: pipeline warns token expires soon` | Token expires within 7 days — re-run `scripts/linkedin_auth.py` before expiry to avoid downtime |

### Step 3 — Proceed

Only proceed with the original task once all required services report ✓.

---

## Rotating the GitHub PAT

The `GITHUB_TOKEN` must be kept in sync across **three** locations. Update all three every time the PAT is regenerated.

### 1. Generate a new PAT

Go to [github.com/settings/tokens](https://github.com/settings/tokens) → **Fine-grained tokens** → **Generate new token**.  
Required scope: `models:read`. Set an expiry that suits your rotation schedule.  
Copy the full token — it is only shown once.

### 2. Update `.env` (local)

Open `.env` and replace the `GITHUB_TOKEN` value:

```
GITHUB_TOKEN=github_pat_<new_token_here>
```

### 3. Update Railway — ghost service

```bash
NEW_TOKEN=github_pat_<new_token_here>
railway variables --service ghost --set "GITHUB_TOKEN=$NEW_TOKEN"
```

> Updating a Railway variable triggers an automatic redeploy of that service. Ghost will be briefly unavailable (~30–60s) while it restarts. Monitor with:
> ```bash
> curl -s -o /dev/null -w "%{http_code}\n" https://beyondtomorrow.world
> ```
> Wait for `200` before proceeding.

### 4. Update Railway — email-worker service

```bash
railway variables --service email-worker --set "GITHUB_TOKEN=$NEW_TOKEN"
```

### 5. Verify all three are in sync

```bash
# Local
python3 -c "from dotenv import load_dotenv; import os; load_dotenv(); print('Local:', os.getenv('GITHUB_TOKEN','')[:30])"

# Railway ghost
railway variables --service ghost 2>/dev/null | grep GITHUB_TOKEN

# Railway email-worker
railway variables --service email-worker 2>/dev/null | grep GITHUB_TOKEN
```

All three should show the same token prefix.

### 6. Run auth check

```bash
source .venv/bin/activate
python3 scripts/auth_check.py github
```

Expect: `✓  GitHub Models  43 models available`

## Security Rules

- **Never hardcode credentials** in scripts, notebooks, or source files
- **Never commit `.env`** — verify it is in `.gitignore` before any `git add`
- **Never log full credential values** — mask after first 8 chars: `val[:8] + "..."`
- **Never use `urllib` for Ghost** — Cloudflare blocks it with 403; always use `httpx`
- **Railway token scope**: use a personal token (railway.app/account/tokens), not a project token — project tokens cannot read variables across services
- **Rotate tokens** if they are accidentally logged, pasted in chat, or pushed to git

## Service Reference

| Service | Auth method | Key variable | Notes |
|---|---|---|---|
| Railway | Bearer token → GraphQL API | `RAILWAY_TOKEN` | Also stored in `~/.railway/config.json` after `railway login` |
| Ghost | HMAC-SHA256 JWT (5-min expiry) | `GHOST_ADMIN_KEY` | Generate fresh per request; use `httpx` |
| Hostinger IMAP | Plain login over IMAP4_SSL | `EMAIL_USER` + `EMAIL_PASS` | Port 993, `imap.hostinger.com` |
| Hostinger SMTP | STARTTLS login | `SMTP_USER` + `SMTP_PASS` | Port 587, `smtp.hostinger.com`; defaults to IMAP creds |
| GitHub Models | Bearer token | `GITHUB_TOKEN` | Fine-grained PAT with `models:read` scope; base URL: `https://models.github.ai/inference` |
| LinkedIn | OAuth 2.0 Bearer token (60-day expiry) | `LINKEDIN_ACCESS_TOKEN` | Also requires `LINKEDIN_PERSON_URN`; refresh via `scripts/linkedin_auth.py` |
