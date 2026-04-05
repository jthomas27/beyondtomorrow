# BeyondTomorrow.World — GitHub Copilot Instructions

This workspace runs an automated research-and-publish pipeline for **BeyondTomorrow.World**, a blog covering climate, technology, geopolitics, and futures. The pipeline uses the OpenAI Agents SDK with GitHub Models API, pgvector for RAG retrieval, and Ghost CMS for publishing.

---

## Stack at a Glance

| Layer | Service | Notes |
|---|---|---|
| Blog CMS | Ghost 5.x (self-hosted) | `https://beyondtomorrow.world` |
| Hosting | Railway (`caring-alignment` project) | Ghost + agent worker services |
| Vector DB | PostgreSQL + pgvector (Railway) | 384-dim embeddings for semantic search |
| AI Framework | OpenAI Agents SDK + GitHub Models API | `gpt-4.1` for research/write/edit; `gpt-4.1-mini` for orchestrate/publish/index |
| Embeddings | `BAAI/bge-small-en-v1.5` (sentence-transformers) | 384-dim; 512-token context; runs locally; zero API cost |
| Email trigger | Hostinger IMAP (`admin@beyondtomorrow.world`) | Polled by `pipeline/email_listener.py` |

---

## Running the Workflow

### Always use `.venv` — system Python 3.14 has SSL cert issues on macOS

```bash
# Activate the virtual environment
source .venv/bin/activate

# Check all environment variables and database connection
.venv/bin/python -m pipeline.main status

# Run the full blog pipeline (research → write → edit → publish → index)
.venv/bin/python -m pipeline.main "BLOG: your topic here"

# Research only (stores findings in pgvector corpus, no blog post)
.venv/bin/python -m pipeline.main "RESEARCH: topic"

# Generate a full research report
.venv/bin/python -m pipeline.main "REPORT: topic"

# Index a document into the corpus
.venv/bin/python -m pipeline.main "INDEX: path/to/document.txt"

# Publish an already-edited file directly to Ghost + LinkedIn (debug/test)
.venv/bin/python -m pipeline.main "PUBLISH: 2026-03-28-my-post-edited.md"

# Check published Ghost posts
.venv/bin/python scripts/check_ghost.py
```

### CLI flags

| Flag | Effect |
|---|---|
| `--model MODEL` | Override the orchestrator model for this run |
| `--dry-run` | Print what the agent would do without making LLM calls |
| `--debug` | Enable verbose SDK tracing output |

---

## Environment Variables

All four core variables are required. They are stored in `.env` at the project root (gitignored) and auto-loaded by `pipeline/main.py`. For Railway deployments, they are set as service variables.

| Variable | Description |
|---|---|
| `GITHUB_TOKEN` | Fine-grained PAT with `models:read` scope (GitHub Models API access) |
| `DATABASE_URL` | PostgreSQL connection string — **always use the external TCP proxy**: `caboose.proxy.rlwy.net:21688`. Never overwrite with the Railway internal URL. |
| `GHOST_URL` | `https://beyondtomorrow.world` |
| `GHOST_ADMIN_KEY` | Ghost Admin API key in `{id}:{secret}` format |

### LinkedIn cross-posting (optional)

Required only for LinkedIn publishing. Set by running `scripts/linkedin_auth.py`.

| Variable | Description |
|---|---|
| `LINKEDIN_CLIENT_ID` | App Client ID from developer.linkedin.com |
| `LINKEDIN_CLIENT_SECRET` | App Client Secret |
| `LINKEDIN_ACCESS_TOKEN` | OAuth 2.0 bearer token — expires 60 days after issue |
| `LINKEDIN_PERSON_URN` | `urn:li:person:{id}` — your LinkedIn member ID |
| `LINKEDIN_TOKEN_EXPIRES` | `YYYY-MM-DD` expiry date — pipeline warns when ≤7 days remain |


To obtain/refresh LinkedIn credentials:
```bash
.venv/bin/python scripts/linkedin_auth.py
```
The script runs the OAuth flow, auto-detects the company URN, and saves all six variables to `.env`.

### Checking Railway variables (CLI)

```bash
# List all variables for the Ghost service
railway variables --service 0daf496c-e14f-41d4-b89b-3624a778c99d

# Railway project reference
# Project: caring-alignment, ID: 752fdaea-fd96-4521-bec6-b7d5ef451270
# Environment: production, ID: c9dfebe4-097a-4151-be37-2b1fcd414e74
# Service: ghost, ID: 0daf496c-e14f-41d4-b89b-3624a778c99d
```

> The Railway GraphQL API returns 403 — always use the Railway CLI, not the API directly.

---

## Agent Pipeline — Full Flow

The pipeline is defined in `pipeline/definitions.py` and runs sequentially. Each stage hands its output explicitly to the next (not via LLM handoff tools) for reliability.

```
BLOG: topic
  └─► Orchestrator
        ├─► Researcher   → structured JSON findings (saved to research/)
        ├─► Writer       → Markdown draft (saved to research/YYYY-MM-DD-slug.md)
        ├─► Editor       → polished post (saved as YYYY-MM-DD-slug-edited.md)
        ├─► Publisher    → Ghost CMS (live post) + LinkedIn personal profile
        └─► Indexer      → chunks + embeddings stored in pgvector corpus
```

### Code entry points

| File | Purpose |
|---|---|
| `pipeline/main.py` | CLI entry point — all runs start here |
| `pipeline/definitions.py` | All six agent definitions (Orchestrator, Researcher, Writer, Editor, Publisher, Indexer) |
| `pipeline/embeddings.py` | Embedding generation and pgvector operations |
| `pipeline/tools/ghost.py` | Ghost Admin API — JWT auth, post creation, image upload |
| `pipeline/tools/linkedin.py` | LinkedIn REST API — personal profile cross-posting, image upload, dedup guard |
| `pipeline/tools/search.py` | DuckDuckGo web search + pgvector semantic search |
| `pipeline/tools/corpus.py` | Knowledge corpus reads/writes (pgvector + Railway Object Storage) |
| `pipeline/guardrails.py` | Content quality checks before publishing |
| `pipeline/degradation.py` | Model fallback chain (retries with backoff) |
| `config/prompts.yaml` | System prompt overrides for each agent |
| `config/models.yaml` | Model assignments per agent |
| `config/limits.yaml` | Daily budget and fetch/search limits |
| `config/allowlist.yaml` | Email sender allowlist for trigger security |

---

## Ghost CMS — Key Facts

### Authentication

Ghost uses short-lived JWTs generated from `GHOST_ADMIN_KEY` (`{id}:{secret}`):
- HMAC-SHA256 over `{id}:{secret}` → `Authorization: Ghost {token}`
- Tokens expire in **5 minutes** — generate fresh per request
- `kid` header must match the key ID from `GHOST_ADMIN_KEY`

### HTTP client

**Always use `httpx`** — Cloudflare blocks `urllib` with `403 1010`. Never use `urllib` or `requests` for Ghost API calls.

### Content format

All BeyondTomorrow posts use **Lexical HTML cards** — this is lossless and required:

```json
{
  "root": {
    "children": [{ "type": "html", "html": "<p>Full post HTML here...</p>" }],
    "direction": null, "format": "", "indent": 0, "type": "root", "version": 1
  }
}
```

- **Do NOT use `?source=html`** — content conversion in Ghost is lossy
- When **updating** a post, send `lexical` (not `html`), plus `id` and `updated_at`

### Minimal publish payload

```json
{
  "posts": [{
    "title": "...",
    "lexical": "{...lexical JSON string...}",
    "status": "published",
    "tags": ["AI", "Geopolitics"],
    "custom_excerpt": "...",
    "meta_title": "...",
    "meta_description": "..."
  }]
}
```

### Image upload

```
POST /ghost/api/admin/images/upload/
Content-Type: multipart/form-data
```

Save the returned URL as `feature_image` in the post payload.

### API endpoints

```
Base: https://beyondtomorrow.world/ghost/api/admin/
Posts: POST /posts/
Update: PUT /posts/{id}/
Images: POST /images/upload/
```

---

## Agent Instructions — Quality Standards

These are the authoritative instructions each agent follows. When modifying agent behaviour, writing tools, or debugging output quality, these standards apply.

### Orchestrator

Routes tasks by prefix and manages the sequential handoff chain. Uses `gpt-4.1-mini` at `temperature=0.1`.

- `BLOG:` → Researcher → Writer → Editor → Publisher → Indexer → return live URL + file path + chunk count
- `RESEARCH:` → Researcher → Indexer → return file path + chunk count
- `REPORT:` → Researcher (extended analysis) → Indexer → return file path
- `INDEX:` → Indexer → return chunk count
- If Publisher returns `MISSING: [...]`, re-run the failing upstream agent before retrying Publisher
- Log decisions after each handoff; continue remaining steps if one agent fails

### Researcher

Uses `gpt-4.1` at `temperature=0.2`, `max_tokens=2000`. Tools: `search_and_index`, `search_corpus`, `fetch_page`, `search_arxiv`, `score_credibility`.

> **Token safety**: `fetch_page()` returns full page text directly into the conversation and will exhaust the 8,000-token input limit after ~2 pages. Only use it for a single specific URL that cannot be found any other way. Use `search_and_index` for all bulk research — it stores embeddings and returns only a ~50-token receipt.

**Sequence**:
1. Generate 2–3 targeted search queries covering different angles
2. For **each** query, call `search_and_index` (not `fetch_page`, not `web_search`) — this fetches pages, stores embeddings permanently, and returns only a short receipt
3. After all queries are indexed, call `search_corpus` **once** with `top_k=3`
4. For academic/scientific topics, also call `search_arxiv`
5. Score each source with `score_credibility`; discard sources scoring 1/5
6. Synthesise into structured JSON with exactly these keys:
   - `key_findings` — `[{finding, confidence: high|medium|low, sources: [URLs]}]`
   - `subtopics` — `[{name, summary, bullet_points}]`
   - `suggested_angles` — 3–5 compelling framings for the writer
   - `gaps` — what the research couldn't answer
   - `source_list` — `[{url, title, type, credibility_score}]`
   - `total_sources` — integer
   - `model_used` — model name string

**Rules**: Only assert claims supported by retrieved sources. Flag single-source claims as `medium` confidence. Note contradictions between sources. Prefer sources from the last 2 years. Output **only** the structured JSON — no preamble.

### Writer

Uses `gpt-4.1` at `temperature=0.7`, `max_tokens=4000`. Tools: `read_research_file`, `write_research_file`.

**Title rules** (apply before writing anything else):
- Must be **punchy**: 6–10 words, specific, and immediately clear
- Must be **factual**: accurately represents content — no exaggeration, no false urgency, no misleading omissions
- Must grab attention through **relevance and precision**, not sensationalism
- Avoid filler phrases like "Everything You Need to Know" — prefer concrete nouns and active verbs

**Sequence**:
1. Draft 3 candidate titles following the title rules; select the strongest one; record only the chosen title in frontmatter
2. Choose the most compelling angle from `suggested_angles`
3. Identify ONE central key issue; state it in the introduction and develop it progressively through every section; conclusion must resolve or reframe it
4. Write a well-structured post **900–1500 words** with clear H2/H3 headings, short paragraphs, and bullet points where appropriate
5. Writing must be **thought-provoking** — challenge assumptions, surface tensions, give the reader something to consider beyond the immediate facts
6. Use clear and concise grammar throughout — avoid jargon, complex sentences, and padding
7. Back all significant claims with inline markdown links to sources; flag unverifiable claims explicitly
8. Strong, non-clickbait opening paragraph that hooks the reader
9. Forward-looking conclusion — what does this mean for the future?
10. **ALWAYS** end the post with a `## Just For Laughs` section containing a short, witty joke directly related to the topic; clever and on-brand, not crass

**Output**: Markdown with YAML frontmatter:
```
---
title: Post Title Here
tags: tag1, tag2, tag3
excerpt: One to two sentence summary for the preview card.
---
```
Save using `write_research_file` with filename `YYYY-MM-DD-slug.md`.

### Editor

Uses `gpt-4.1` at `temperature=0.3`, `max_tokens=4000`. Tools: `read_research_file`, `write_research_file`, `search_corpus`, `score_credibility`.

**Review checklist**:
1. **Title quality** — must be punchy (6–10 words), factual, attention-grabbing without being misleading; rewrite before anything else if it fails this standard
2. **Factual accuracy** — cross-reference all claims against the research findings JSON
3. **Grammar and clarity** — clear and concise; remove padding, split run-ons, replace vague language with precise wording
4. **Punctuation audit** — correct comma splices, missing full stops, inconsistent hyphenation, misused apostrophes, improper dashes; **British English** punctuation conventions apply
5. **Spelling** — British English preferred
6. **Tone consistency** — authoritative but accessible; no jargon without explanation
7. **Key issue coherence** — single central issue introduced early and developed progressively; tighten if the argument drifts
8. **Evidence and sources** — every significant factual claim or statistic must have an inline source link; flag unsupported claims with `<!-- UNVERIFIED: ... -->`
9. **Structure and flow** — logical progression, clear transitions between sections
10. **SEO basics** — clear title, meta excerpt in frontmatter, proper H2/H3 hierarchy
11. **Length** — target 900–1500 words; trim padding or expand thin sections

**Rules**: Make **targeted edits** — do NOT rewrite from scratch unless the draft is structurally broken. Flag unverifiable claims with `<!-- UNVERIFIED: ... -->` rather than silently fixing them. Save edited version using `write_research_file` with `-edited` appended to the filename.

### Publisher

Uses `gpt-4.1-mini` at `temperature=0.0`, `max_tokens=1000`. Tools: `pick_random_asset_image`, `upload_image_to_ghost`, `publish_file_to_ghost`.

**Sequence** (exactly, every time):
1. Call `pick_random_asset_image()` — if result starts with `Error:`, stop and report
2. Call `upload_image_to_ghost(image_path=<path from step 1>)` — if result starts with `Error:`, stop and report
3. Call `publish_file_to_ghost(filename=<-edited.md filename>, feature_image_url=<URL from step 2>, status='published')`
4. Return `PUBLISHED: <ghost_url> | FEATURE_IMAGE: <url from step 2>`

**LinkedIn cross-posting is handled by `pipeline/main.py` directly after the publisher returns** — not by the publisher agent. `main.py` reads frontmatter from the edited file and calls `_post_to_linkedin_impl` so excerpt and tags are always correct.

**LinkedIn reliability controls** (implemented in Step 4b of `_run_blog_pipeline`):
- Tracked as a named `PipelineRunLogger` stage (`LinkedIn`) — success/failure/skipped appears in email notifications
- If the Ghost URL cannot be parsed from publisher output → `stage_error`, not a silent skip
- Up to **3 retries** with 10s/30s delays on any `Error:` result
- `SKIPPED: LinkedIn not configured` (missing env vars) → `stage_skipped`, not an error
- Email subject includes `(LinkedIn failed)` when Ghost published but LinkedIn errored

**Pre-publish validation** — `publish_file_to_ghost` validates before calling Ghost:
- `title` (from frontmatter, 5–10 words)
- `body_content` (at least 500 words)
- `feature_image` (hosted URL from step 2)
- `excerpt` (non-empty in frontmatter)
- `Just For Laughs` section present

If **any** item is missing: `publish_file_to_ghost` returns `MISSING: [list]`. Publisher must return this verbatim — do NOT retry.

### Indexer

Uses `gpt-4.1-mini` at `temperature=0.0`, `max_tokens=500`. Tools: `read_research_file`, `index_document`, `embed_and_store`.

**Sequence**:
1. Read the document using `read_research_file`
2. Call `index_document` to chunk, embed, and store the full document
   - `doc_type`: one of `research | article | pdf | email | webpage`
   - `date`: today's date in `YYYY-MM-DD` format if not known from the document
3. For research JSON outputs, also extract each `key_finding` as a separate high-priority chunk using `embed_and_store` with `metadata={"type": "finding"}`
4. Report: number of chunks stored + source identifier

**Rules**: Do not summarise, paraphrase, or alter content before indexing. Preserve the exact text.

---

## Model Assignments

| Agent | Model | Temperature | Max Tokens | Notes |
|---|---|---|---|---|
| Orchestrator | `openai/gpt-4.1-mini` | 0.1 | 2,000 | Fast routing; 1M context |
| Researcher | `openai/gpt-4.1` | 0.2 | 8,000 | Reasoning + tool-calling + 1M context |
| Writer | `openai/gpt-4.1` | 0.7 | 4,000 | Blog prose; 1M context |
| Editor | `openai/gpt-4.1` | 0.3 | 4,000 | Editorial pass; reliable fact-check |
| Publisher | `openai/gpt-4.1-mini` | 0.0 | 1,000 | Deterministic metadata extraction + Ghost API call |
| Indexer | `openai/gpt-4.1-mini` | 0.0 | 500 | Minimal reasoning; chunking + indexing |

> **Plan: Copilot Pro+** — unlimited premium requests; no daily caps.  
> **GitHub Models API does NOT have Claude/Anthropic models.** Use `openai/gpt-4.1`, `openai/gpt-4.1-mini`, or other supported OpenAI models.  
> **Fallback chain**: `gpt-4.1` → `gpt-4.1-mini` → `gpt-4.1-nano`

---

## RAG / Corpus

- **Vector DB**: PostgreSQL + pgvector on Railway; 384-dim vectors from `BAAI/bge-small-en-v1.5`
- **Chunk size**: ~350 words per chunk (fits within model's 512-token limit)
- **Search fallback**: pgvector fails → keyword search; web search returns nothing → corpus only
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

---

## Error Handling

| Scenario | Action |
|---|---|
| GitHub Models API fails | Retry up to 6× with exponential backoff (20s base, doubling to 300s cap); degrade to cheaper model via fallback chain |
| Ghost API fails | Retry 3×, then save draft locally and alert Slack |
| Research finds nothing | Fall back to knowledge corpus only |
| PDF extraction fails | Log error, skip file, continue |
| pgvector search fails | Fall back to keyword search |

---

## Hard Constraints

- **Agents never write to MySQL directly** — Ghost is the only service that touches the blog DB
- **Always use `.venv/bin/python3`** — system Python 3.14 has SSL cert issues on macOS
- **`DATABASE_URL` must use the external proxy** (`caboose.proxy.rlwy.net:21688`) — never overwrite with the Railway internal URL
- **Always use `httpx`** for Ghost API calls — Cloudflare blocks `urllib` with 403 1010
- **Posts publish live** via the Publisher agent (`status='published'`) — the Orchestrator handles the full chain end-to-end
- **Email triggers** are validated against `config/allowlist.yaml` — subject must begin with `BLOG:`, `RESEARCH:`, `REPORT:`, or `INDEX:`
- `pipeline/` is the runtime directory (not `agents/`) — the `openai-agents` SDK installs as the `agents` Python package; using `pipeline/` avoids the name clash
