---
name: service-auth
description: "Authenticate and verify access to Railway, Ghost, Hostinger (IMAP/SMTP), and GitHub before running scripts or pipeline operations. Use when: accessing Railway variables, publishing to Ghost, checking email credentials, calling GitHub Models API, setting up a new environment, or debugging a 401/403/connection error on any of these services."
argument-hint: "Optional: specify a service name to check only that one (railway | ghost | hostinger | github)"
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

# Hostinger IMAP (email listener)
EMAIL_HOST=imap.hostinger.com
EMAIL_PORT=993
EMAIL_USER=admin@beyondtomorrow.world
EMAIL_PASS=...

# Hostinger SMTP (reply notifications)
SMTP_HOST=smtp.hostinger.com
SMTP_PORT=587
# SMTP_USER and SMTP_PASS default to EMAIL_USER/EMAIL_PASS if not set
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
| `Hostinger IMAP: auth failed` | `EMAIL_PASS` wrong — verify in Hostinger webmail settings |
| `Hostinger SMTP: auth failed` | Set `SMTP_USER` and `SMTP_PASS` explicitly in `.env` if they differ from IMAP credentials |
| `GitHub: 401` | `GITHUB_TOKEN` expired or missing `models:read` scope — regenerate at github.com/settings/tokens |

### Step 3 — Proceed

Only proceed with the original task once all required services report ✓.

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
