# Pipeline operational reference

Read the section relevant to the task. `config/` and `infra/services.json` are
the maintained configuration sources; this guide explains how to use them.
Current PostgreSQL migrations and deployment procedures are in `infra/README.md`.

## Stack at a Glance

| Layer | Service | Notes |
|---|---|---|
| Blog CMS | Ghost 6.72.0 (self-hosted) | `https://beyondtomorrow.world` |
| Hosting | Railway (`caring-alignment` project) | Ghost + agent worker services |
| Vector DB | PostgreSQL + pgvector (Railway) | 1536-dim embeddings for semantic search |
| AI Framework | OpenAI Agents SDK + OpenAI API | `gpt-6.1-sol` for research/write/edit; `gpt-6-luna` for orchestrate/publish/index (Responses API) |
| Embeddings | `text-embedding-3-small` | 1536-dim; ~$0.02/1M tokens |
| Email trigger | Hostinger IMAP (`admin@beyondtomorrow.world`) | Polled by `pipeline/email_listener.py` |


## Running the Pipeline

```bash
source .venv/bin/activate

# Check all env vars and DB connection
.venv/bin/python -m pipeline.main status

# Full blog pipeline (research → write → edit → publish → index)
.venv/bin/python -m pipeline.main "BLOG: your topic here"

# Research only (stores findings in pgvector, no blog post)
.venv/bin/python -m pipeline.main "RESEARCH: topic"

# Generate a full research report
.venv/bin/python -m pipeline.main "REPORT: topic"

# Index a document into the corpus
.venv/bin/python -m pipeline.main "INDEX: path/to/document.txt"

# Publish an already-edited file directly to Ghost + LinkedIn
.venv/bin/python -m pipeline.main "PUBLISH: 2026-03-28-my-post-edited.md"
```

CLI flags: `--model MODEL`, `--dry-run`, `--debug`.


## Model Assignments

| Agent | Model | Reasoning effort | Max output tokens (incl. reasoning) |
|---|---|---|---|
| Orchestrator | `gpt-6-luna` | none | 2,000 |
| Researcher | `gpt-6.1-sol` | low | 4,000 |
| Writer | `gpt-6.1-sol` | low | 4,000 |
| Editor | `gpt-6.1-sol` | low | 4,000 |
| Publisher | `gpt-6-luna` | none | 1,000 |
| Indexer | `gpt-6-luna` | none | 500 |

Agents use the Responses API. Omit temperature for Sol reasoning requests.
Routing order: `gpt-6.1-sol` → `gpt-6-luna`, loaded from `config/models.yaml`.
Researcher, Writer, and Editor disable automatic downgrades until fallback
quality is validated. Exhausted budgets defer work; they never bypass limits.
Usage is recorded per completed model turn, including turns before tool failures.


## Key Files

| File | Purpose |
|---|---|
| `pipeline/main.py` | Compatible CLI entry point; workflows live in `pipeline/workflows/` |
| `pipeline/definitions.py` | All six agent definitions |
| `pipeline/embeddings.py` | Embedding generation and pgvector operations |
| `pipeline/tools/files.py` | Research file I/O + text sanitisation |
| `pipeline/tools/ghost.py` | Ghost Admin API — JWT auth, post creation, image upload |
| `pipeline/tools/linkedin.py` | LinkedIn REST API — cross-posting |
| `pipeline/tools/search.py` | DuckDuckGo web search + pgvector semantic search |
| `pipeline/guardrails.py` | Content quality checks, rate-limit guardrails |
| `pipeline/degradation.py` | Model fallback chain (retries with backoff) |
| `config/models.yaml` | Model assignments per agent |
| `config/prompts.yaml` | System prompt overrides per agent |
| `config/limits.yaml` | Daily budget and fetch/search limits |


## Ghost CMS — Key Facts

- **Auth**: short-lived JWTs from `GHOST_ADMIN_KEY` (`{id}:{secret}`). Tokens expire in 5 minutes — generate fresh per request.
- **HTTP client**: always `httpx`. Never `urllib` or `requests`.
- **Content format**: Lexical HTML cards only. Do NOT use `?source=html` (lossy).
- **Lexical structure**:
  ```json
  {"root": {"children": [{"type": "html", "html": "<p>...</p>"}], "direction": null, "format": "", "indent": 0, "type": "root", "version": 1}}
  ```
- **Updating a post**: send `lexical` (not `html`), plus `id` and `updated_at`.
- **API base**: `https://beyondtomorrow.world/ghost/api/admin/`


## Railway Reference

- Project: `caring-alignment`, ID: `752fdaea-fd96-4521-bec6-b7d5ef451270`
- Environment: production, ID: `c9dfebe4-097a-4151-be37-2b1fcd414e74`
- Service: ghost, ID: `0daf496c-e14f-41d4-b89b-3624a778c99d`
- Service: email-worker (Python pipeline daemon — release this for code/deps changes), ID: `15b13afb-8515-49e9-ab38-7e138069064f`
- Railway GraphQL API returns 403 — always use the Railway CLI, not the API directly.
- List service variables: `railway variables --service 0daf496c-e14f-41d4-b89b-3624a778c99d`


## Environment Variables

All required variables live in `.env` at the project root (gitignored).

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key (`sk-...`) — powers agents and embeddings |
| `DATABASE_URL` | PostgreSQL connection string — **external proxy only**: `caboose.proxy.rlwy.net:21688` |
| `GHOST_URL` | `https://beyondtomorrow.world` |
| `GHOST_ADMIN_KEY` | Ghost Admin API key in `{id}:{secret}` format |
| `RAILWAY_API_TOKEN` | Personal Railway token (NOT `RAILWAY_TOKEN` — that's for project tokens) |
| `RESEND_API_KEY` | Resend API key for newsletter delivery |
| `LINKEDIN_ACCESS_TOKEN` | OAuth 2.0 bearer — expires 60 days after issue |
| `LINKEDIN_TOKEN_EXPIRES` | `YYYY-MM-DD` expiry; pipeline warns when ≤7 days remain |

> **Newsletter delivery**: after `BLOG:` or `PUBLISH:` confirms a live Ghost receipt, the workflow sends via Resend (`RESEND_API_KEY`) only to unsuppressed free members subscribed to the selected newsletter. PostgreSQL stores per-recipient delivery receipts; a missing key skips this stage. Set `GHOST_NEWSLETTER_ID` when several newsletters are active. See [delivery recovery](DELIVERY_RECOVERY.md) for retries and partial failures.


## Verifying Changes

Before committing or deploying, run only checks relevant to the change.
For a LinkedIn-only change, use the LinkedIn tests rather than the full suite.
The commands below are available checks, not a mandatory checklist:

```bash
source .venv/bin/activate

# 1. Env vars + DB connection sanity check
.venv/bin/python -m pipeline.main status

# 2. Run the relevant tests (example: LinkedIn)
.venv/bin/python -m pytest tests/test_linkedin.py

# 3. Dry-run the pipeline (no LLM calls, no publish)
.venv/bin/python -m pipeline.main --dry-run "BLOG: test topic"

# 4. Optional live end-to-end check; only when requested or directly necessary
.venv/bin/python -m pipeline.main "RESEARCH: a small test topic"
```

Where relevant, confirm no import/model-name errors, bare model strings in logs
(`gpt-6.1-sol`, not `openai/gpt-6.1-sol`), and DB connectivity via the external
proxy. Do not broaden or repeat checks after relevant validation passes unless
new evidence warrants it. For deployments, perform one status check and report
the result; do not wait and poll repeatedly unless the user requests monitoring.


The live MySQL service retains the name `ghost-mysql8-validation`; see
`infra/services.json`. The original `MySQL` service is preserved rollback data.
Private incident notes and credential-bearing evidence remain local.
