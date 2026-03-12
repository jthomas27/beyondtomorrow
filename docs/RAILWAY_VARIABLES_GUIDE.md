# Railway Variables Guide

This guide describes how to retrieve environment variables from the **caring-alignment** Railway project and populate the local `.env` file. Follow this procedure before running any pipeline commands locally.

---

## Project Details

| Field | Value |
|---|---|
| Project | `caring-alignment` |
| Project ID | `752fdaea-fd96-4521-bec6-b7d5ef451270` |
| Environment | `production` |
| Environment ID | `c9dfebe4-097a-4151-be37-2b1fcd414e74` |
| Service | `ghost` |
| Service ID | `0daf496c-e14f-41d4-b89b-3624a778c99d` |

---

## One-Time Setup: Install Railway CLI

```bash
# macOS (Homebrew)
brew install railway

# Authenticate (opens browser)
railway login
```

The CLI writes your token to `~/.railway/config.json` automatically. You only need to do this once.

---

## Fetching Variables (use this before every new pipeline run)

```bash
# List all variables for the ghost service
railway variables --service 0daf496c-e14f-41d4-b89b-3624a778c99d

# Get specific variable values as JSON (pipe to jq or python)
railway variables --service 0daf496c-e14f-41d4-b89b-3624a778c99d --json
```

The four variables required by the local pipeline are:

| Variable in Railway | Variable in `.env` | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | `GITHUB_TOKEN` | GitHub Models API (LLM inference) |
| `DATABASE_URL` | `DATABASE_URL` | pgvector (external proxy URL) |
| `GHOST_URL` | `GHOST_URL` | Ghost site URL |
| `GHOST_ADMIN_KEY` | `GHOST_ADMIN_KEY` | Ghost Admin API auth key |

> **Note:** The `DATABASE_URL` in Railway points to the internal Railway network (`pgvector.railway.internal`). For local development, use the external proxy URL already set in `.env` (`caboose.proxy.rlwy.net:21688`). Do **not** overwrite it with the Railway value.

---

## Updating `.env` from Railway (scripted)

Run this to pull and print the three variables needed locally:

```bash
railway variables --service 0daf496c-e14f-41d4-b89b-3624a778c99d --json \
  | python3 -c "
import json, sys
v = json.load(sys.stdin)
for k in ('GITHUB_TOKEN', 'GHOST_URL', 'GHOST_ADMIN_KEY'):
    print(f'{k}={v.get(k, \"\")}')
"
```

Copy the output into `.env`.

---

## Current `.env` Values (as of March 2026)

All four required variables are set. Run the status check to verify:

```bash
.venv/bin/python -m pipeline.main status
```

Expected output:
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

**`railway: command not found`** — Run `brew install railway` then `railway login`.

**`Error: Not authenticated`** — Run `railway login` to refresh your token.

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
