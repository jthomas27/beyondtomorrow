# RAG Publish Workflow — BeyondTomorrow.World

Quick reference for understanding and working on RAG agent publish requests.

---

## Stack at a Glance

| Layer | Service | Notes |
|---|---|---|
| Blog CMS | Ghost 5.x (self-hosted) | `https://beyondtomorrow.world` |
| Hosting | Railway (`caring-alignment` project) | Ghost + agent worker services |
| Blog DB | MySQL (Railway) | Ghost owns all writes — agents never touch it directly |
| Vector DB | PostgreSQL + pgvector (Railway) | Stores 384-dim embeddings for semantic search |
| Object Storage | Railway Object Storage | Raw PDFs, emails, images, knowledge corpus |
| AI Framework | OpenAI Agents SDK + GitHub Models API | `gpt-4o` for orch/research/write/edit; `gpt-4o-mini` for publish/index |
| Embeddings | `all-MiniLM-L6-v2` (sentence-transformers, local) | Runs on Railway compute; zero API cost |
| Trigger | GitHub Actions (cron or manual dispatch) | Also triggered by inbound email via IMAP |
| Email | Hostinger Business Email (`admin@beyondtomorrow.world`) | IMAP-polled by `email_listener.py` |
| Alerts | Slack webhook | Success/failure notifications |

---

## How a Post Gets Published — Full Flow

### Trigger Phase
1. GitHub Actions fires on cron schedule **or** inbound email arrives at `admin@beyondtomorrow.world`
2. Email sender is validated against `config/allowlist.yaml`; subject parsed for command prefix (`BLOG:` / `RESEARCH:` / `REPORT:` / `INDEX:`)

### Agent Handoff Chain (OpenAI Agents SDK)
3. **Orchestrator** — receives task, identifies type, manages the handoff chain
4. **Researcher** — searches the web + queries pgvector corpus (semantic similarity search on embeddings); returns structured JSON findings
5. **Summariser** — condenses raw research into bullet points for the Writer
6. **Writer** — produces 500–1500 word HTML draft grounded in research
7. **Editor** — proofreads, improves tone, runs quality guardrails

### Publish Phase
8. **Publisher agent** reads `GHOST_ADMIN_API_KEY` from Railway env vars
9. Generates short-lived JWT: HMAC-SHA256 over `{id}:{secret}` → `Authorization: Ghost {token}`
10. (If image) Uploads via `POST /ghost/api/admin/images/upload/`; saves returned URL for `feature_image`
11. Wraps HTML body in a **Lexical HTML card** (lossless — required for all BeyondTomorrow posts)
12. `POST /ghost/api/admin/posts/` with full payload (title, lexical, tags, SEO fields, social previews)
13. Post defaults to `status: "draft"` — requires human approval before going live

### Post-Publish Phase
14. **Indexer** — chunks + embeds research JSON/sources into pgvector for future corpus retrieval
15. Slack alert sent; post reviewed and promoted to `published` in Ghost Admin

---

## Key Code Entry Points

| File | Purpose |
|---|---|
| `pipeline/main.py` | Pipeline entry point — `python -m pipeline.main "BLOG: topic"` |
| `pipeline/email_listener.py` | IMAP polling; triggers agent runs from inbound email |
| `pipeline/definitions.py` | Agent definitions (Orchestrator, Researcher, Writer, Editor, Publisher, Indexer) |
| `pipeline/embeddings.py` | Embedding generation (all-MiniLM-L6-v2) and pgvector operations |
| `pipeline/tools/ghost.py` | Ghost Admin API calls — JWT auth, post creation/update |
| `pipeline/tools/search.py` | Web search + pgvector semantic search |
| `pipeline/tools/corpus.py` | Knowledge corpus reads/writes (Railway Object Storage) |
| `pipeline/guardrails.py` | Content quality checks before publishing |
| `pipeline/degradation.py` | Model fallback chain (retries with backoff; degrades to cheaper model) |
| `config/allowlist.yaml` | Email sender allowlist for trigger security |
| `config/prompts.yaml` | System prompts for each agent role |
| `config/models.yaml` | Model assignments per agent |

---

## Ghost API — Key Facts

- **Auth**: JWT generated from `GHOST_ADMIN_API_KEY` (`{id}:{secret}`) — short-lived (5 min), `kid` in header
- **Content format**: Lexical HTML card (lossless) — wrap full HTML in `{ root: { children: [{ type: 'html', html: "..." }] } }`
- **Do NOT use `?source=html`** for BeyondTomorrow posts — conversion is lossy
- **Updating posts**: Must send `lexical` (not `html`), plus `id` and `updated_at`
- **HTTP client**: Must use `httpx` — Cloudflare blocks `urllib` with 403 1010
- **Default post status**: `draft` — never publish directly without review

### Minimal publish payload
```json
{
  "posts": [{
    "title": "...",
    "lexical": "{...lexical JSON string...}",
    "status": "draft",
    "tags": ["AI", "Geopolitics"],
    "custom_excerpt": "...",
    "meta_title": "...",
    "meta_description": "..."
  }]
}
```

---

## RAG / Corpus — Key Facts

- **Vector DB**: PostgreSQL + pgvector on Railway; 384-dim vectors from `all-MiniLM-L6-v2`
- **Chunk size**: 500–1000 words per chunk
- **Corpus storage layout** (Railway Object Storage):
  ```
  knowledge-corpus/
  ├── pdfs/raw/         # Original PDFs
  ├── pdfs/extracted/   # Extracted text (JSON)
  ├── emails/inbound/   # Raw inbound emails
  ├── emails/processed/ # Parsed + indexed
  ├── webpages/saved/   # Archived web content
  └── index/metadata.json
  ```
- **Search fallback**: If pgvector fails → keyword search
- **Research fallback**: If web search returns nothing → corpus only

---

## Error Handling

| Scenario | Action |
|---|---|
| GitHub Models API fails | Retry 3× with exponential backoff (5s, 15s, 45s); degrade to cheaper model |
| Ghost API fails | Retry 3×, then save draft locally and alert Slack |
| Research finds nothing | Fall back to knowledge corpus only |
| PDF extraction fails | Log error, skip file, continue |
| pgvector search fails | Fall back to keyword search |

---

## Run Commands (Local)

```bash
# Activate venv (always use .venv — system python3 has SSL issues on macOS)
source .venv/bin/activate

# Run full pipeline
.venv/bin/python -m pipeline.main "BLOG: your topic here"

# Check pipeline status
.venv/bin/python -m pipeline.main status

# Direct Ghost publish (test/debug)
.venv/bin/python scripts/publish_test_post.py

# Check existing Ghost posts
.venv/bin/python scripts/check_ghost.py

# Railway variables
railway variables --service 0daf496c-e14f-41d4-b89b-3624a778c99d
```

---

## Important Constraints

- Agents **never write to MySQL directly** — Ghost is the only service that touches the blog DB
- Always use `.venv/bin/python3` — system Python 3.14 has SSL cert issues on macOS
- `DATABASE_URL` uses the **external proxy** (`caboose.proxy.rlwy.net:21688`) — do not overwrite with Railway internal URL
- GitHub Models API does **not** include Claude/Anthropic models — use `openai/gpt-4o` or `openai/gpt-4o-mini`
