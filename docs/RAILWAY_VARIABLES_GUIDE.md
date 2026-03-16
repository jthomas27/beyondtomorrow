# Access & Variables Guide

Quick reference for accessing all services used by BeyondTomorrow.World. **No passwords or secrets are stored in this file.** All credentials live as Railway environment variables.

---

## 1. Ghost Admin

**Admin panel:** `https://beyondtomorrow.world/ghost/`

| Item | Value / Location |
|---|---|
| Login email | Railway → `GHOST_ADMIN_EMAIL` |
| Login password | Railway → `GHOST_ADMIN_PASSWORD` |
| Admin API key | Railway → `GHOST_ADMIN_KEY` (format: `{id}:{secret}`) |
| Custom integration | `Publisher Agent` — Settings → Integrations |

To retrieve credentials:
```bash
railway variables --service 0daf496c-e14f-41d4-b89b-3624a778c99d --json \
  | python3 -c "import json,sys; v=json.load(sys.stdin); [print(f'{k}={v[k]}') for k in ('GHOST_ADMIN_EMAIL','GHOST_ADMIN_PASSWORD','GHOST_ADMIN_KEY') if k in v]"
```

> Session auth via the Ghost Admin UI requires 2FA device verification on new logins. For scripts, always use JWT token auth from `GHOST_ADMIN_KEY` — see [GHOST_PUBLISHING_GUIDE.md](GHOST_PUBLISHING_GUIDE.md).

---

## 2. Railway

**Dashboard:** `https://railway.app` — log in with your GitHub account.

| Item | Value |
|---|---|
| Project | `caring-alignment` |
| Project ID | `752fdaea-fd96-4521-bec6-b7d5ef451270` |
| Environment | `production` |
| Service | `ghost` (service ID `0daf496c-e14f-41d4-b89b-3624a778c99d`) |

### CLI access

```bash
# Install (one-time)
brew install railway

# Authenticate — opens browser, writes token to ~/.railway/config.json
railway login

# List all variables for the ghost service
railway variables --service 0daf496c-e14f-41d4-b89b-3624a778c99d

# Set a new secret
railway variables --service 0daf496c-e14f-41d4-b89b-3624a778c99d --set "KEY=value"
```

> The Railway GraphQL API returns 403 — always use the CLI, not the API directly.

---

## 3. GitHub

**GitHub.com:** log in with your personal account.

**Repository:** `https://github.com/jthomas27/beyondtomorrow`

The pipeline uses a fine-grained PAT for GitHub Models inference. The token is stored in Railway and in the local `.env`:

| Item | Location |
|---|---|
| Personal Access Token | Railway → `GITHUB_TOKEN` |
| Required scope | `models:read` |
| API endpoint | `https://models.github.ai/inference` |

To create or rotate the token:
1. Go to `https://github.com/settings/tokens` → **Fine-grained tokens**
2. Set permission: **Models** → **Read**
3. Copy the token and update Railway:
```bash
railway variables --service 0daf496c-e14f-41d4-b89b-3624a778c99d --set "GITHUB_TOKEN=github_pat_..."
```
Then update `.env` locally as well.

---

## 4. Hostinger Email (`admin@beyondtomorrow.world`)

**Webmail:** `https://hmail.hostinger.com` — log in with `admin@beyondtomorrow.world` and the password from Railway → `GHOST_ADMIN_PASSWORD` (shared credential).

The pipeline's email listener (`pipeline/email_listener.py`) polls via IMAP. All connection settings are stored in Railway:

| Railway Variable | Value | Notes |
|---|---|---|
| `EMAIL_HOST` | `imap.hostinger.com` | Set ✅ |
| `EMAIL_PORT` | `993` | Set ✅ |
| `EMAIL_USER` | `admin@beyondtomorrow.world` | Set ✅ |
| `EMAIL_PASS` | *(Hostinger account password)* | **Set this manually — see below** |

### Setting EMAIL_PASS

`EMAIL_PASS` must match the Hostinger account password. Set it in Railway once:

```bash
railway variables --service 0daf496c-e14f-41d4-b89b-3624a778c99d --set "EMAIL_PASS=your_password_here"
```

The same password is also stored as `mail__options__auth__pass` (used by Ghost for outgoing SMTP). Both must stay in sync.

> SMTP outbound settings (for Ghost transactional email): host `smtp.hostinger.com`, port `465`, SSL.

---

## 5. Pipeline Variables — Full Reference

All variables live in the `ghost` service of the `caring-alignment` Railway project. Copy them into `.env` for local development.

| Variable | Purpose | Secret? |
|---|---|---|
| `GITHUB_TOKEN` | GitHub Models API — LLM inference | ✅ |
| `DATABASE_URL` | pgvector external proxy (`caboose.proxy.rlwy.net:21688`) | ✅ |
| `GHOST_URL` | `https://beyondtomorrow.world` | No |
| `GHOST_ADMIN_KEY` | Ghost Admin API JWT auth (`{id}:{secret}`) | ✅ |
| `GHOST_ADMIN_EMAIL` | Ghost admin login email | No |
| `GHOST_ADMIN_PASSWORD` | Ghost admin + Hostinger webmail password | ✅ |
| `EMAIL_HOST` | IMAP host for email listener | No |
| `EMAIL_PORT` | IMAP port (993) | No |
| `EMAIL_USER` | IMAP username | No |
| `EMAIL_PASS` | IMAP / Hostinger account password | ✅ |

### Pull variables to local `.env`

```bash
railway variables --service 0daf496c-e14f-41d4-b89b-3624a778c99d --json \
  | python3 -c "
import json, sys
v = json.load(sys.stdin)
for k in ('GITHUB_TOKEN', 'DATABASE_URL', 'GHOST_URL', 'GHOST_ADMIN_KEY', 'EMAIL_HOST', 'EMAIL_PORT', 'EMAIL_USER', 'EMAIL_PASS'):
    if k in v:
        print(f'{k}={v[k]}')
"
```

> **Important:** The Railway `DATABASE_URL` points to the internal Railway network. For local development, keep the external proxy URL (`caboose.proxy.rlwy.net:21688`) in `.env` — do not overwrite it with the Railway value.

### Verify local setup

```bash
.venv/bin/python -m pipeline.main status
```

Expected:
```
  ✓ GITHUB_TOKEN         GitHub Models API access (github_p...)
  ✓ DATABASE_URL         pgvector knowledge corpus (postgres...)
  ✓ GHOST_URL            Ghost CMS publishing (https://...)
  ✓ GHOST_ADMIN_KEY      Ghost Admin API (<key-id>...)
  ✓ Database connected — N embeddings in corpus

Status: READY ✓
```

---

## Troubleshooting

| Error | Fix |
|---|---|
| `railway: command not found` | `brew install railway` |
| `Error: Not authenticated` | `railway login` |
| Ghost API returns `403` | Regenerate JWT from `GHOST_ADMIN_KEY` — tokens expire in 5 min |
| Email listener auth failure | Ensure `EMAIL_PASS` is set in Railway and matches Hostinger password |

**`GHOST_ADMIN_KEY` format error** — The key must be in `id:secret` format (e.g. `<key-id>...:a55a3c...`). Check it has exactly one colon.

**Ghost 403 errors** — The Admin API key may have been regenerated. Go to [Ghost Admin → Integrations → Publisher Agent](https://beyondtomorrow.world/ghost/#/settings/integrations) and copy the new key.

**GitHub Models 404 / unknown_model** — Verify the model name is correct and available on the GitHub Models API. The pipeline uses `claude-sonnet-4-6` (researcher/writer/editor), `claude-haiku-4-5` (orchestrator/publisher/indexer). Check `config/models.yaml` for the current assignments and ensure your `GITHUB_TOKEN` has `models:read` scope.

---

## Publishing a Blog Post

Once `.env` is populated and `status` shows READY:

```bash
# Full pipeline: research → write → edit → Ghost draft → corpus index
.venv/bin/python -m pipeline.main "BLOG: your topic here"

# Research and index only (no blog post)
.venv/bin/python -m pipeline.main "RESEARCH: your topic here"

# Direct Ghost publish (bypasses pipeline, for testing)
.venv/bin/python scripts/publish_test_post.py
```

All blog posts are created as **drafts** by default. Review at:
`https://beyondtomorrow.world/ghost/#/posts`
