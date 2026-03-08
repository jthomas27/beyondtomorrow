# RAG workflow
1. ✅ Install `sentence-transformers` and load `all-MiniLM-L6-v2` on Railway worker
2. ⏳ Migrate pgvector `embeddings` table from `vector(1536)` → `vector(384)`
    **ACTION REQUIRED:** Enable TCP proxy on pgvector Railway service (Railway dashboard → pgvector service → Settings → Networking → Enable TCP Proxy), then run **in order**:
    ```bash
    # Step 1 — create/verify all tables including schema_migrations, rate_limit_log, agent_sessions
    railway service pgvector
    railway run node scripts/db-test.js

    # Step 2 — migrate vector dimensions and re-embed existing data
    railway run python scripts/migrate-embeddings.py
    ```
    After migration, verify with:
    ```bash
    PGPASSWORD='...' psql -h ballast.proxy.rlwy.net -p 32490 -U postgres -d railway \
      -c "\d embeddings" \
      -c "SELECT version, applied_at FROM schema_migrations ORDER BY applied_at"
    ```
3. ✅ Build the embedding pipeline (chunk → embed → store) — `pipeline/tools/corpus.py`
4. ✅ Build the retrieval logic (embed query → pgvector cosine search → return chunks) — `pipeline/tools/corpus.py`
5. ✅ Add deduplication to `index_document` — source cascade via normalized schema (documents → chunks → embeddings)
6. ✅ Add pgvector asyncpg codec — vectors passed as Python lists, no manual string construction
7. ✅ Tune HNSW index — `ef_construction=128` for better recall
8. ✅ Add `schema_migrations`, `rate_limit_log`, `agent_sessions` tables
9. ✅ Normalize schema — `documents(source UNIQUE) → chunks(chunk_index) → embeddings(chunk_id FK)`; `search_corpus` joins for source/type trace; `migrate-embeddings.py` backfills existing flat rows


# Agent workflow
1. ⏳ Create a GitHub PAT (Fine-grained) with `models:read` scope — **ACTION REQUIRED (browser)**
2. ⏳ Store the PAT in Railway environment variables as `GITHUB_TOKEN` — **ACTION REQUIRED**
3. ✅ Install the SDK: `pip install openai-agents` (and all other packages — see `requirements.txt`)
4. ✅ Create `agents/setup.py` with:
   - `AsyncOpenAI` client pointed at `https://models.github.ai/inference`
   - `set_default_openai_client(client)` — all agents use this client
   - `set_default_openai_api("chat_completions")` — OpenAI-compatible mode
5. ✅ Define agents in `agents/definitions.py` with model, tools, and handoffs
6. ✅ Run via `Runner.run(orchestrator, input="your task")` — see `pipeline/main.py`
7. ✅ GitHub Actions workflow: `.github/workflows/agents.yml`

**Note:** App code lives in `pipeline/` (not `agents/`). The `openai-agents` SDK installs
as the `agents` Python package; using `pipeline/` avoids the name clash. 
Run with: `python -m pipeline.main "BLOG: topic"`

**ACTION REQUIRED before first run:**
- Set GitHub Actions secrets: `AGENT_GITHUB_TOKEN`, `DATABASE_URL`, `GHOST_URL`, `GHOST_ADMIN_KEY`



# Testing and Verification

### Unit Tests

| Module | What to Test |
|---|---|
| `setup.py` | GitHub Models client init, set_default_openai_client works |
| `config_loader.py` | YAML loading, validation, defaults applied correctly |
| `email_listener.py` | IMAP connection, email parsing, subject line command detection |
| `embeddings.py` | Model loads, produces correct dimension vectors, similarity works |
| `tools/search.py` | DuckDuckGo + Brave return results, fetch_page extracts text |
| `tools/corpus.py` | search_corpus returns relevant chunks, index_document stores correctly |
| `tools/ghost.py` | publish_to_ghost creates draft with correct metadata |
| `tools/quality.py` | score_credibility returns domain scores matching expected values |
| `guardrails.py` | Rate limit enforcement blocks over-budget requests |
| `degradation.py` | Model fallback selection triggers correctly at limits |
| `db.py` | asyncpg pool connects, rate_limit_log writes succeed |

### Integration Tests

| Test | What It Verifies |
|---|---|
| Email → Research | Send test email → agent detects → orchestrator dispatches → replies |
| CLI → Research | `python -m agents.main "topic"` → Runner.run() → structured output |
| Research → Corpus | Research output is chunked, embedded via embed_and_store, stored in pgvector |
| Rate limit → Degradation | Simulate hitting sonnet limit → guardrail triggers → agent uses haiku fallback |
| Research → Blog Pipeline | `--blog` flag → researcher handoff → writer → editor → publisher (draft) |
| Agent Handoffs | Orchestrator → researcher → writer chain completes without error |
| Agent Sessions | agent_sessions table records conversation state for each agent in a run |

### Quality Checks

- Manually review 3-5 research outputs for:
  - Accuracy of findings vs. source material
  - Source citations actually match provided sources
  - Confidence labels match source count/credibility
  - No hallucinated information beyond provided sources
  - Report structure is clear and well-organised

### Cost Verification

- Run 10 research tasks over a week
- Verify $0 charged beyond existing subscriptions
- Review `rate_limit_log` table to confirm usage is within GitHub Models limits
- Confirm Brave Search usage stays under 2,000/month free tier