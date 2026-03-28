# BeyondTomorrow.World — Pipeline Overview

> Last updated: 22 March 2026

This document describes the full research-and-publish pipeline: how each agent works, how they hand off to each other, and what controls are in place.

---

## Table of Contents

- [Architecture at a Glance](#architecture-at-a-glance)
- [Pipeline Modes](#pipeline-modes)
- [BLOG Pipeline — Stage by Stage](#blog-pipeline--stage-by-stage)
  - [Stage 1: Research](#stage-1-research)
  - [Stage 2: Write](#stage-2-write)
  - [Stage 3: Edit](#stage-3-edit)
  - [Stage 4: Publish](#stage-4-publish)
  - [Stage 5: Index](#stage-5-index)
- [Agent Definitions](#agent-definitions)
- [Handoff Mechanism](#handoff-mechanism)
- [Rate Limiting and Model Fallback](#rate-limiting-and-model-fallback)
  - [Proactive Model Selection](#proactive-model-selection)
  - [Reactive Fallback Chain](#reactive-fallback-chain)
  - [Adaptive Cooldowns](#adaptive-cooldowns)
  - [Token Tracking](#token-tracking)
- [Pre-Publish Guardrails](#pre-publish-guardrails)
- [Recovery Flows](#recovery-flows)
- [Knowledge Corpus (RAG)](#knowledge-corpus-rag)
- [Email Trigger System](#email-trigger-system)
- [Configuration Reference](#configuration-reference)
- [Strengths and Weaknesses](#strengths-and-weaknesses)

---

## Architecture at a Glance

```
┌──────────────────────────────────────────────────────────────────┐
│                       Entry Points                               │
│  CLI: python -m pipeline.main "BLOG: topic"                      │
│  Email: IMAP poll → subject "BLOG: topic" → pipeline dispatch    │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                    pipeline/main.py                               │
│  Routes by prefix → runs 5-stage sequential chain                │
│  Manages cooldowns, retries, fallback, token tracking            │
└────────────────────────────┬─────────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
   ┌─────────────┐  ┌──────────────┐  ┌──────────────┐
   │  GitHub      │  │  PostgreSQL  │  │  Ghost CMS   │
   │  Models API  │  │  + pgvector  │  │  (httpx)     │
   │  (LLM calls) │  │  (corpus)   │  │  (publish)   │
   └─────────────┘  └──────────────┘  └──────────────┘
```

| Layer | Technology | Purpose |
|---|---|---|
| LLM | GitHub Models API (gpt-4.1, gpt-4.1-mini, gpt-4.1-nano) | Research, writing, editing, publishing decisions |
| Agent SDK | OpenAI Agents SDK (`agents` package) | Runs each agent with tool calling |
| Vector DB | PostgreSQL + pgvector (Railway) | 384-dim embeddings + tsvector full-text for hybrid search |
| Embeddings | `BAAI/bge-small-en-v1.5` (sentence-transformers) | Runs locally, zero API cost; 512-token context |
| CMS | Ghost 5.x (self-hosted, Railway) | Blog publishing via Admin API |
| Email | Hostinger IMAP/SMTP | Trigger pipeline via email |
| HTTP | httpx | Ghost API calls (Cloudflare blocks urllib) |

---

## Pipeline Modes

| Command | Pipeline | Stages | Output |
|---|---|---|---|
| `BLOG: topic` | Full publish | Research → Write → Edit → Publish → Index | Live blog URL |
| `RESEARCH: topic` | Research only | Research → Index | Corpus chunks |
| `REPORT: topic` | Extended research | Research → Index | Research file |
| `PUBLISH: file.md` | Publish only | Publish | Live blog URL |
| `INDEX: path` | Index only | Index | Chunk count |

---

## BLOG Pipeline — Stage by Stage

```
                    ┌─────────────────┐
                    │   Pre-fetch     │  Seed corpus before LLM
                    │   (2 queries)   │  via _prefetch_topic()
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  1. RESEARCHER  │  gpt-4.1  temp=0.2
                    │  search_and_index│  max_turns=8
                    │  search_corpus  │  Output: research JSON
                    │  score_credibility│
                    └────────┬────────┘
                             │ 20s cooldown
                    ┌────────▼────────┐
                    │  2. WRITER      │  gpt-4.1  temp=0.7
                    │  write_research │  max_turns=6
                    │  _file          │  Output: YYYY-MM-DD-slug.md
                    └────────┬────────┘
                             │ 20–60s adaptive cooldown
                    ┌────────▼────────┐
                    │  3. EDITOR      │  gpt-4.1  temp=0.3
                    │  read/write     │  max_turns=6
                    │  search_corpus  │  Output: -edited.md
                    └────────┬────────┘
                             │ 20s cooldown
                    ┌────────▼────────┐
                    │  4. PUBLISHER   │  gpt-4.1-mini  temp=0.0
                    │  pick_image     │  max_turns=6
                    │  upload_image   │  Output: live URL
                    │  publish_to_ghost│
                    └────────┬────────┘
                             │ 20s cooldown
                    ┌────────▼────────┐
                    │  5. INDEX       │  No LLM (direct call)
                    │  _index_document│  Chunk + embed + store
                    │  _impl()       │  Output: chunk count
                    └─────────────────┘
```

### Stage 1: Research

**Agent:** Researcher (gpt-4.1, temperature 0.2, max 8,000 tokens)

**Process:**
1. **Pre-fetch** — before the LLM runs, `_prefetch_topic()` generates 2 simple search queries and calls `search_and_index` to populate the corpus. This reduces the number of tool calls the LLM needs.
2. **Cache check** — if a research JSON for this topic/date already exists on disk, loads it instead of re-running.
3. **LLM research** — the Researcher agent:
   - Generates 2–3 targeted search queries covering different angles
   - Calls `search_and_index` for each (fetches full page text via trafilatura, stores embeddings permanently)
   - Calls `search_corpus` once with `top_k=3` to retrieve stored knowledge
   - Optionally calls `search_arxiv` for academic topics
   - Scores source credibility (1–5); discards 1/5 sources
4. **Output** — structured JSON with `key_findings`, `subtopics`, `suggested_angles`, `gaps`, `source_list`
5. **Post-processing** — research JSON is cached to disk and indexed into the corpus via `_index_document_impl()`

**Key constraint:** Only asserts claims supported by retrieved sources. Single-source claims flagged as "medium" confidence.

### Stage 2: Write

**Agent:** Writer (gpt-4.1, temperature 0.7, max 4,000 tokens)

**Cooldown:** 20 seconds (standard `_STAGE_COOLDOWN`)

**Process:**
1. Research JSON is compacted via `_compact_research()` (extracts key_findings, suggested_angles, subtopics, source_list; drops bulk metadata). **Writer receives up to 8,000 chars** — enough to retain all subtopics, angles, and source URLs. Truncation cuts at the last complete line and appends a hint to use `search_corpus` for any remainder.
2. Writer receives compacted research + explicit instruction to save via `write_research_file`
3. **Title rules** — drafts 3 candidates; selects the strongest (5–10 words, factual, punchy)
4. Writes 900–1,500 word post with H2/H3 headings, inline source links, strong opening, forward-looking conclusion
5. Must end with `## Just For Laughs` section
6. Saves as `YYYY-MM-DD-slug.md` with YAML frontmatter (title, tags, excerpt)

**Safety net:** If the Writer fails to save a file (detected by glob), the pipeline retries with an explicit "call write_research_file as your FIRST action" instruction.

### Stage 3: Edit

**Agent:** Editor (gpt-4.1, temperature 0.3, max 4,000 tokens)

**Cooldown:** Adaptive (20s if RPM is clear; 60s if RPM is under pressure — see [Adaptive Cooldowns](#adaptive-cooldowns))

**Review checklist (in order):**
1. Title quality — rewrite first if it fails 5–10 word / factual / punchy test
2. Factual accuracy — cross-reference claims against research JSON
3. Grammar and clarity — British English; remove padding; split run-ons
4. Punctuation audit — comma splices, hyphenation, apostrophes, dashes
5. Spelling — British English
6. Tone consistency — authoritative but accessible
7. Key issue coherence — single central issue developed progressively
8. Evidence and sources — inline source links on every significant claim; unsupported claims flagged with `<!-- UNVERIFIED: ... -->`
9. Structure and flow — logical progression, clear transitions
10. SEO — title, meta description, H2/H3 hierarchy
11. Length — 900–1,500 words; trim or expand

**Output:** Saves as `YYYY-MM-DD-slug-edited.md`

**Fallback:** If the Editor fails to produce an edited file, the pipeline falls back to the unedited draft.

### Stage 4: Publish

**Agent:** Publisher (gpt-4.1-mini, temperature 0.0, max 1,000 tokens)

**Cooldown:** 20 seconds

**Strict 3-step sequence:**
1. `pick_random_asset_image()` — select a feature image from `assets/images/`
2. `upload_image_to_ghost(image_path)` — upload to Ghost, get hosted URL
3. `publish_file_to_ghost(filename, feature_image_url, status='published')` — convert markdown to HTML, wrap in Lexical card, POST to Ghost Admin API

The Publisher does NOT read files directly — `publish_file_to_ghost` handles file reading, frontmatter parsing, and markdown-to-HTML conversion internally.

**Pre-publish validation** is enforced by the `publish_file_to_ghost` tool before the Ghost API call (see [Pre-Publish Guardrails](#pre-publish-guardrails)).

### Stage 5: Index

**No LLM agent** — direct call to `_index_document_impl()`

The Indexer agent was bypassed to avoid 413 Payload Too Large errors. The SDK conversation history accumulated the full article content twice (in read result and write args), exceeding the API's request body limit.

**Process:**
1. Reads edited file from disk
2. Chunks text (350 words max, 35-word overlap)
3. Batch-embeds all chunks via `BAAI/bge-small-en-v1.5`
4. Upserts document + chunks + embeddings into pgvector

---

## Agent Definitions

All agents are defined in `pipeline/definitions.py` using the OpenAI Agents SDK `Agent` class.

| Agent | Model | Temp | Max Tokens | Tools | Purpose |
|---|---|---|---|---|---|
| **Orchestrator** | gpt-4.1-mini | 0.1 | 2,000 | Handoffs to all agents | Routes tasks by prefix |
| **Researcher** | gpt-4.1 | 0.2 | 8,000 | search_and_index, search_corpus, fetch_page, search_arxiv, score_credibility | Web research + corpus search |
| **Writer** | gpt-4.1 | 0.7 | 4,000 | read_research_file, write_research_file | Drafts blog post from research |
| **Editor** | gpt-4.1 | 0.3 | 4,000 | read_research_file, write_research_file, search_corpus, score_credibility | Review, fact-check, polish |
| **Publisher** | gpt-4.1-mini | 0.0 | 1,000 | pick_random_asset_image, upload_image_to_ghost, publish_file_to_ghost | Image upload + Ghost publish |
| **Indexer** | gpt-4.1-mini | 0.0 | 1,000 | read_research_file, index_document, embed_and_store | Chunk + embed + store (currently bypassed) |

Temperature rationale:
- **0.0–0.1** for deterministic tasks (publishing, indexing, routing)
- **0.2–0.3** for accuracy-critical tasks (research, editing)
- **0.7** for creative tasks (writing)

---

## Handoff Mechanism

The pipeline uses **explicit sequential handoff** — not LLM-driven transfers.

```
main.py calls each agent in sequence:
  _run_agent_with_fallback(researcher, ...) → output
  _run_agent_with_fallback(writer, ...) → output
  _run_agent_with_fallback(editor, ...) → output
  _run_agent_with_fallback(publisher, ...) → output
  _index_document_impl(...) → direct call
```

Each stage's output is explicitly passed to the next via the input prompt. This is more reliable than LLM handoffs (`transfer_to_X` tools), which require the model to correctly decide when and how to hand off.

The Orchestrator agent has handoff tools defined but is only used for generic/fallback tasks — the main BLOG and RESEARCH pipelines bypass it entirely.

**Context compaction between stages:**
- Only key_findings, suggested_angles, subtopics, and source_list are retained; full summaries and redundant metadata are dropped
- **Writer** receives up to 8,000 chars — full research context including all subtopics, angles, and source URLs
- **Editor** receives up to 2,500 chars — findings and sources only; it reads the draft directly via `read_research_file` and can call `search_corpus` for additional verification
- Truncation cuts at the last complete line rather than mid-character, with a `search_corpus` hint appended

---

## Rate Limiting and Model Fallback

### Proactive Model Selection

Before each agent run, `_run_agent_with_fallback()` calls `select_model()` which:

1. Checks the preferred model's daily budget (`check_model_budget()`)
2. Checks the preferred model's per-minute RPM (`check_rpm()`)
3. If budget ≥ 95% used OR RPM limit hit → walks the fallback chain to find an available model
4. Switches the agent to the selected model before the first attempt

This avoids wasting an API call only to receive a 429.

### Reactive Fallback Chain

If an API call fails despite proactive checks:

```
Fallback chain: gpt-4.1 → gpt-4.1-mini → gpt-4.1-nano

On rate-limit error (429, 413, unsupported-param):
  1. Get next model in chain via get_fallback()
  2. Wait: exponential backoff (20s → 40s → 80s → 160s → 300s cap)
  3. Retry with fallback model
  4. Max 6 attempts total

On timeout:
  Fail immediately (no fallback for timeouts)

On other errors:
  Raise immediately
```

The agent's original model is always restored after each pipeline stage to prevent fallback from leaking.

### Adaptive Cooldowns

The Editor stage uses an adaptive cooldown based on real RPM data:

```
Before Editor runs:
  rpm_used = get_rpm_usage(pool, editor_model)  # calls in last 60s
  rpm_limit = RPM_LIMITS[editor_model]           # e.g. 10 for gpt-4.1

  If rpm_used ≥ rpm_limit - 1:
    cooldown = 60s    ← RPM pressure detected
  Else:
    cooldown = 20s    ← RPM window is clear

  On DB failure:
    cooldown = 60s    ← safe default
```

This means fast pipelines where Research completes quickly get a shorter wait, while pipelines that consumed most of the RPM window wait longer.

### Token Tracking

Every agent run logs actual token usage to the `rate_limit_log` table:

```python
result = Runner.run(agent, ...)
tokens_in, tokens_out = _extract_usage(result)  # from result.raw_responses
log_model_call(pool, model, tokens_in=..., tokens_out=..., phase="research")
```

This enables:
- Accurate daily budget calculation (not just call counting)
- Post-run analysis of token consumption per stage
- Future TPM-aware throttling

### Rate Limit Constants

| Model | Daily Limit | RPM Limit |
|---|---|---|
| gpt-4.1 | 80 calls/day | 10 req/min |
| gpt-4.1-mini | 500 calls/day | 30 req/min |
| gpt-4.1-nano | 500 calls/day | 30 req/min |

Budget thresholds:
- **Soft warning:** 80% of daily limit used
- **Hard block:** 95% of daily limit used → force fallback

---

## Pre-Publish Guardrails

The `publish_file_to_ghost` tool validates 5 checks before calling the Ghost API:

| Check | Requirement | Failure Message |
|---|---|---|
| **Title** | Non-empty, 5–10 words | `title length (X words — must be 5–10 words...)` |
| **Body content** | ≥ 500 words (HTML stripped) | `body_content too short (X words)` |
| **Feature image** | URL starts with `http` | `feature_image (no hosted image URL)` |
| **Excerpt** | Non-empty in frontmatter | `excerpt (empty in frontmatter)` |
| **Just For Laughs** | Section present in body (case-insensitive) | `'Just For Laughs' section (required)` |

If any check fails, the tool returns `MISSING: [items]` without calling Ghost. The pipeline then triggers a recovery flow (see below).

---

## Recovery Flows

### Publisher Validation Failure

```
Publisher returns "MISSING: [title, excerpt]"
  │
  ├─ If error mentions title/body/excerpt/Just For Laughs:
  │    └─ Re-run Editor in recovery mode with specific fix instructions
  │       └─ Editor reads draft, fixes issues, saves as -edited.md
  │
  └─ Retry Publisher with fixed file
       └─ If still MISSING: raise RuntimeError (hard stop)
```

### Writer File Save Failure

```
Writer completes but no new .md file detected
  │
  └─ Retry Writer with explicit instruction:
     "CRITICAL: call write_research_file as your FIRST action"
```

### Editor File Save Failure

```
Editor completes but no -edited.md file found
  │
  └─ Fall back to unedited draft (log warning, continue pipeline)
```

---

## Knowledge Corpus (RAG)

### Database Schema

```
documents (1)──────(N) chunks (1)──────(1) embeddings
  source (unique)       chunk_index         vector(384)
  content               content             ts tsvector (generated)
  source_type                               metadata (JSONB)
                                            model name
```

The `ts` column is a `GENERATED ALWAYS AS (to_tsvector('english', content)) STORED` column with a GIN index (`embeddings_ts_idx`). It populates automatically for every row — no manual maintenance needed.

### How Content Enters the Corpus

| Source | Method | doc_type |
|---|---|---|
| Web search results | `search_and_index` tool (Researcher) | `webpage` |
| arXiv abstracts | `search_arxiv` tool | `research` |
| Research JSON | `_index_document_impl()` (after Research stage) | `research` |
| Published posts | `_index_document_impl()` (after Index stage) | `article` |

### How Content is Retrieved

1. **`search_corpus(query, top_k)`** — hybrid search via **Reciprocal Rank Fusion (RRF)**:
   - **Vector leg** — embeds query → pgvector cosine similarity, filters at threshold 0.30, fetches `top_k × 2` candidates
   - **Full-text leg** — `plainto_tsquery('english', query)` matched against the generated `ts tsvector` column via GIN index, ranked by `ts_rank`
   - Both result lists are merged: `score = Σ 1 / (60 + rank)`. Rows appearing in both lists receive a combined score boost.
   - Top `top_k` by RRF score are returned, labelled `hybrid: 0.XXXX` in the output
2. **Graceful degradation** — if the `ts` column is absent (e.g. fresh DB restore), falls back automatically to vector-only search + `ILIKE` keyword fallback
3. Used by: Researcher (finding prior knowledge), Editor (fact-checking claims)

### Chunking Strategy

- Max 350 words per chunk, 35-word overlap
- Splits at paragraph boundaries (double newlines)
- Respects markdown heading breaks
- Embeddings: 384 dimensions via `BAAI/bge-small-en-v1.5` (local, zero cost; 512-token context window)

---

## Email Trigger System

```
┌──────────────────┐     IMAP poll      ┌──────────────┐
│  Gmail / Hostinger│───────────────────▶│ email_listener│
│  "BLOG: topic"   │   every 5 min      │  .py         │
└──────────────────┘                     └──────┬───────┘
                                                │
                              ┌──────────────────┼──────────────┐
                              ▼                  ▼              ▼
                        Parse subject     Validate sender   Dispatch
                        COMMAND: topic    vs allowlist      _run_blog_pipeline()
                                                │
                              ┌──────────────────┼──────────────┐
                              ▼                  ▼              ▼
                         ACK reply         Success reply   Failure reply
                         (immediate)       (with URL)      (with error)
```

**Security controls:**
- Sender validated against `config/allowlist.yaml` (currently: `admin@beyondtomorrow.world` and `jeremiah.thomas2701@gmail.com`)
- Subject must start with a valid prefix: `BLOG:`, `RESEARCH:`, `REPORT:`, or `INDEX:`
- Max body length: 5,000 chars; max 3 attachments; max 10 MB per attachment
- Unrecognised senders are silently ignored (no error reply)

---

## Configuration Reference

| File | Purpose | Key Settings |
|---|---|---|
| `config/models.yaml` | Agent model assignments, fallback chain, thresholds | Model per agent, temp, max_tokens |
| `config/limits.yaml` | Budget caps, fetch limits, search limits, chunking | 500 calls/day, 500K tokens/day, 20 tasks/day |
| `config/prompts.yaml` | System prompt overrides for each agent | Detailed instructions per role |
| `config/allowlist.yaml` | Approved email senders + permissions | 2 approved senders |
| `config/sources.yaml` | Approved domains + credibility scores | Academic + climate sources (scored 1–5) |

### Key Constants (pipeline/main.py)

| Constant | Value | Purpose |
|---|---|---|
| `_AGENT_TIMEOUT` | 300s | Max time per agent step |
| `_STAGE_COOLDOWN` | 20s | Default wait between stages |
| `_RETRY_BACKOFF_BASE` | 20s | Base for exponential backoff (20 → 40 → 80 → 160 → 300 cap) |

---

## Strengths and Weaknesses

### Strengths

| Area | Detail |
|---|---|
| **Proactive rate limiting** | `select_model()` checks RPM + daily budget before each agent run — avoids wasted 429 calls |
| **Graceful degradation** | 3-model fallback chain with exponential backoff; pipeline continues even when the primary model is throttled |
| **Adaptive cooldowns** | Editor stage queries real RPM data to decide wait duration — faster when RPM is clear, safer when it's not |
| **Token tracking** | Every agent run logs actual input/output tokens — enables analysis and future TPM-aware budgeting |
| **Research caching** | If the same topic is retried on the same day, research JSON is loaded from disk instead of re-running |
| **Pre-publish validation** | 5 checks (title, body, image, excerpt, Just For Laughs) prevent broken posts from reaching Ghost |
| **Recovery flows** | Publisher validation failures trigger automated Editor recovery before retrying; Writer failures trigger explicit retry |
| **Direct indexing** | Bypasses the Indexer LLM agent, avoiding 413 payload errors and saving API calls |
| **Zero-cost embeddings** | `BAAI/bge-small-en-v1.5` runs locally — no API cost for corpus operations |
| **Corpus persistence** | All web searches are indexed permanently via `search_and_index` — knowledge accumulates across runs |

### Weaknesses

| Area | Detail | Potential Improvement |
|---|---|---|
| **Undercounting API calls** | `log_model_call()` is invoked once per pipeline stage, but the SDK may make multiple LLM calls per `Runner.run()` (e.g., Researcher with tool calls). RPM checks are therefore based on incomplete data. | Hook into SDK-level request events to log every individual API call. |
| **No per-request RPM tracking** | The Agents SDK makes internal LLM calls for tool-use loops that are invisible to the pipeline's rate tracking. A stage marked as "1 call" may actually be 4–5 API requests. | Implement an SDK middleware/hook that calls `log_model_call()` on each raw request. |
| **Hardcoded gpt-5 entries** | `DAILY_LIMITS` and `RPM_LIMITS` include gpt-5 models that aren't in the fallback chain and have never been tested. | Remove or gate behind a feature flag. |
| **No TPM-aware throttling** | Token counts are logged but not yet used for budgeting decisions. Daily limits are call-count-only. | Add token-per-minute checks to `check_model_budget()`. |
| ~~**Context compaction is lossy**~~ ✅ Fixed | `_compact_research()` now uses an 8,000-char limit for the Writer (full subtopics, angles, sources) and a separate 2,500-char limit for the Editor (findings + sources only). Truncation cuts at the last complete line with a `search_corpus` hint. | Resolved — 2-pass approach implemented. |
| **Single-threaded pipeline** | All 5 stages run sequentially. There's no parallelism even where stages are independent (e.g., image upload could overlap with editing). | Overlap image selection/upload with Editor stage. |
| **No retry on Ghost API failure** | Publisher retries on LLM rate limits but the Ghost API call itself (`publish_file_to_ghost`) has its own 3-retry loop. If both fail, the post is lost. | Save draft locally before Ghost call; add a `PUBLISH:` recovery command (already exists). |
| **Email polling interval** | 5-minute poll means up to 5 minutes latency between sending an email and the pipeline starting. | Reduce interval or use IMAP IDLE for push-based triggers. |
| **Indexer agent still defined** | The Indexer agent definition in `definitions.py` is no longer invoked by BLOG or RESEARCH pipelines but is still loaded. | Remove definition or repurpose for standalone `INDEX:` commands. |
| **No quality scoring of output** | There's no automated check of the final post's quality (readability score, SEO score, engagement prediction) before publishing. | Add a lightweight post-edit quality gate. |

### Typical Pipeline Timing

Based on observed runs:

| Stage | Typical Duration | Notes |
|---|---|---|
| Research | 30–45s | Includes pre-fetch + LLM + tool calls |
| Write | 25–35s | Single LLM call + file save |
| Edit | 45–110s | LLM call; may hit rate limit and backoff |
| Publish | 5–10s | Image upload + Ghost API |
| Index | 2–5s | Direct chunking + embedding (no LLM) |
| **Cooldowns** | 60–120s total | Adaptive; depends on RPM pressure |
| **Total** | **4–6 minutes** | End-to-end for a typical BLOG run |
