# AGENTS.md — BeyondTomorrow.World

Project-level rules for AI coding agents (Cline, etc.). Read this before editing any file or running any command.

---

## Stack at a Glance

| Layer | Service | Notes |
|---|---|---|
| Blog CMS | Ghost 5.x (self-hosted) | `https://beyondtomorrow.world` |
| Hosting | Railway (`caring-alignment` project) | Ghost + agent worker services |
| Vector DB | PostgreSQL + pgvector (Railway) | 1536-dim embeddings for semantic search |
| AI Framework | OpenAI Agents SDK + OpenAI API | `gpt-4.1` for research/write/edit; `gpt-4.1-mini` for orchestrate/publish/index |
| Embeddings | `text-embedding-3-small` | 1536-dim; ~$0.02/1M tokens |
| Email trigger | Hostinger IMAP (`admin@beyondtomorrow.world`) | Polled by `pipeline/email_listener.py` |

---

## Hard Rules — Read Before Touching Anything

1. **Always use `.venv`** — system Python 3.14 has SSL cert issues on macOS.
   ```bash
   source .venv/bin/activate
   .venv/bin/python -m pipeline.main status
   ```

2. **`DATABASE_URL` must use the external proxy** — `caboose.proxy.rlwy.net:21688`. Never overwrite with the Railway internal URL.

3. **Always use `httpx` for Ghost API calls** — Cloudflare blocks `urllib` and `requests` with 403 1010.

4. **Never commit `.env`** — it is gitignored. Contains all credentials.

5. **Never use `git add .` blindly** — stage files explicitly. Run `git check-ignore -v <file>` on any new file before staging.

6. **Agents never write to MySQL directly** — Ghost is the only service that touches the blog DB.

7. **Pipeline runtime directory is `pipeline/`** — the `openai-agents` SDK installs as the `agents` Python package; using `pipeline/` avoids the name clash.

8. **All model strings are bare** — `gpt-4.1`, not `openai/gpt-4.1`. The OpenAI API rejects the `openai/` prefix.

9. **Never print or log secret values** — do not echo, print, or include in command output: API keys, passwords, tokens, or the full `DATABASE_URL`. Reference them by variable name only (e.g. `$OPENAI_API_KEY`). If a command would reveal a secret in its output, mask it or skip the output entirely.

---

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

---

## Model Assignments

| Agent | Model | Temperature | Max Tokens |
|---|---|---|---|
| Orchestrator | `gpt-4.1-mini` | 0.1 | 2,000 |
| Researcher | `gpt-4.1` | 0.2 | 8,000 |
| Writer | `gpt-4.1` | 0.7 | 4,000 |
| Editor | `gpt-4.1` | 0.3 | 4,000 |
| Publisher | `gpt-4.1-mini` | 0.0 | 1,000 |
| Indexer | `gpt-4.1-mini` | 0.0 | 500 |

Fallback chain: `gpt-4.1` → `gpt-4.1-mini` → `gpt-4.1-nano`.

---

## Key Files

| File | Purpose |
|---|---|
| `pipeline/main.py` | CLI entry point |
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

---

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

---

## Railway Reference

- Project: `caring-alignment`, ID: `752fdaea-fd96-4521-bec6-b7d5ef451270`
- Environment: production, ID: `c9dfebe4-097a-4151-be37-2b1fcd414e74`
- Service: ghost, ID: `0daf496c-e14f-41d4-b89b-3624a778c99d`
- Service: email-worker (Python pipeline daemon — redeploy this for code/deps changes), ID: `15b13afb-8515-49e9-ab38-7e138069064f`
- Railway GraphQL API returns 403 — always use the Railway CLI, not the API directly.
- List service variables: `railway variables --service 0daf496c-e14f-41d4-b89b-3624a778c99d`

---

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

> **Newsletter delivery**: after a `BLOG:` post publishes, `pipeline/main.py` sends an HTML email to all `status:free` Ghost members via Resend (`RESEND_API_KEY`), deduplicated against `logs/newsletter_sent.json`. Missing key → the stage is skipped, not failed.

---

## Verifying Changes

After editing pipeline code, validate before committing or deploying:

```bash
source .venv/bin/activate

# 1. Env vars + DB connection sanity check
.venv/bin/python -m pipeline.main status

# 2. Run the test suite
.venv/bin/python -m pytest

# 3. Dry-run the pipeline (no LLM calls, no publish)
.venv/bin/python -m pipeline.main --dry-run "BLOG: test topic"

# 4. Cheap end-to-end check (research only — no Ghost publish)
.venv/bin/python -m pipeline.main "RESEARCH: a small test topic"
```

Confirm: no import/model-name errors, bare model strings in logs (`gpt-4.1`, not `openai/gpt-4.1`), and DB reachable via the external proxy.

---

## Skill: Push to GitHub

Use when committing and pushing code changes to `origin/main`.

### Procedure

**1. Review changes**
```bash
git status
git diff --stat HEAD
```

**2. Check `.gitignore` before staging any file**
```bash
git check-ignore -v <file>
```
If the command returns output, the file is ignored — do NOT stage it without explicit user approval.

**3. Stage files explicitly**
```bash
git add <files...>
```
Do NOT stage: `.env`, `research/`, `reports/`, `logs/`, `__pycache__/`, `.venv/`, `.DS_Store`.

**4. Commit using a heredoc**
```bash
git commit -F - << 'EOF'
<type>: <short summary>

- detail line 1
- detail line 2
EOF
```
Prefixes: `feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`. Subject line ≤ 72 chars.

**5. Push**
```bash
git push origin main
git log --oneline -1
```

### Rules
- Never use `--force` or `--force-with-lease` without explicit user instruction.
- Always push to `main` unless told otherwise.
- On `rejected — non-fast-forward`: `git pull --rebase origin main` then push again.

---

## Skill: Index PDF Reports

Use when adding new PDFs to `reports/`, re-indexing a file, or checking what's indexed.

### Check what's indexed vs. not
```bash
source .venv/bin/activate
.venv/bin/python - << 'EOF'
import os, psycopg2, pathlib
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute("SELECT source FROM documents WHERE source_type='pdf'")
indexed = {r[0] for r in cur.fetchall()}
pdfs = sorted(pathlib.Path('reports').glob('*.pdf'))
not_indexed = [p for p in pdfs if f'reports/{p.name}' not in indexed]
print(f'{len(pdfs)} total  |  {len(indexed)} indexed  |  {len(not_indexed)} pending')
for p in not_indexed:
    print(f'  NOT INDEXED: {p.name}')
conn.close()
EOF
```

### Batch-index all unindexed PDFs
```bash
source .venv/bin/activate
.venv/bin/python -m scripts.batch_index_reports
# Use --force to replace existing chunks/embeddings
.venv/bin/python -m scripts.batch_index_reports --force
```

### Index a single file via the pipeline CLI
```bash
.venv/bin/python -m pipeline.main "INDEX: reports/my-new-report.pdf"
```

### Known issues
- `appPage.pdf` — HTML file saved with wrong extension; cannot be extracted.
- Large PDFs (>150 pages) may cause MPS memory pressure on macOS; re-run if it fails — it retries the failed file only.

---

## Skill: Query Pipeline Logs

Use when checking run status, finding a published URL, or investigating failures.

### Query script
```bash
source .venv/bin/activate
.venv/bin/python scripts/query_logs.py [QUERY_NAME] [--run-id RUN_ID] [--days N] [--limit N]
```

| Query name | What it shows |
|---|---|
| `runs` (default) | Last N pipeline runs with status, topic, duration |
| `failures` | Recent failed runs with error details |
| `emails` | Email-triggered events (Railway runs) |
| `run` | Full event trace for a single `--run-id` |
| `stage` | Per-stage timing stats |
| `published` | Published URLs, newest first |

### Direct psql
```bash
psql "$DATABASE_URL"
```

### Key table: `pipeline_logs`
- `run_id` — 12-hex-char UUID prefix grouping all events for one run
- `event` — `run_start` / `stage_ok` / `stage_error` / `run_complete` / `run_failed` / `model_fallback` / `email_received` / etc.
- `stage` — `Research` / `Write` / `Edit` / `Publish` / `Index` / `LinkedIn`
- `data` — JSONB payload with `command`, `topic`, `published_url`, `error_message`, `traceback`, etc.

---

## Skill: Service Authentication

Use before running any script that touches Railway, Ghost, Hostinger, or LinkedIn.

### Check all services
```bash
source .venv/bin/activate
.venv/bin/python scripts/auth_check.py            # check all
.venv/bin/python scripts/auth_check.py railway    # check one service
.venv/bin/python scripts/auth_check.py ghost
.venv/bin/python scripts/auth_check.py hostinger
.venv/bin/python scripts/auth_check.py linkedin
```

### Common fixes

| Error | Fix |
|---|---|
| `RAILWAY_API_TOKEN not set` | railway.app/account/tokens → Create personal token → add to `.env` as `RAILWAY_API_TOKEN` |
| `Railway: Unauthorized` / `Project Token not found` | Personal tokens go in `RAILWAY_API_TOKEN`, not `RAILWAY_TOKEN` — regenerate |
| `Ghost: 401` | `GHOST_ADMIN_KEY` wrong or expired — Ghost Admin → Settings → Integrations |
| `Ghost: 403` | Using `urllib` — switch to `httpx` |
| `Ghost settings API: 501` | Custom keys can't edit settings — use session auth via `node scripts/inject-code.js`; requires `GHOST_ADMIN_EMAIL` + `GHOST_ADMIN_PASSWORD` |
| `Hostinger IMAP: auth failed` | `EMAIL_PASS` wrong — check Hostinger webmail settings |
| `LinkedIn: 401` | `LINKEDIN_ACCESS_TOKEN` expired (60-day TTL) — run `scripts/linkedin_auth.py` |
| `LinkedIn: 403` | Missing `w_member_social` scope — re-run `scripts/linkedin_auth.py` |

### Refresh LinkedIn tokens
```bash
.venv/bin/python scripts/linkedin_auth.py
```

### Rotate `OPENAI_API_KEY` across all locations
Update in all three places:
1. `.env` (local)
2. Railway ghost service: `railway variables --service 0daf496c-e14f-41d4-b89b-3624a778c99d --set "OPENAI_API_KEY=sk-..."`
3. Railway email-worker service: `railway variables --service 15b13afb-8515-49e9-ab38-7e138069064f --set "OPENAI_API_KEY=sk-..."`
