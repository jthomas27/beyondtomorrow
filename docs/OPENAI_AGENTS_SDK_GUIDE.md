# OpenAI Agents SDK — Architecture & Implementation Guide

> **Framework:** [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) (`openai-agents` v0.9+)
> **LLM Provider:** GitHub Models API (zero cost via Copilot Pro+)
> **Orchestrator Model:** openai/gpt-4.1-mini | **Plan:** Copilot Pro+ (unlimited premium requests)

---

## Why OpenAI Agents SDK

The OpenAI Agents SDK is a **provider-agnostic** Python framework for building multi-agent workflows. It works with any OpenAI-compatible API — including GitHub Models — giving us full agentic capabilities at zero additional cost.

| Capability | What It Provides |
|---|---|
| **Agent Loop** | Built-in autonomous loop — agent calls tools, reads results, decides next steps |
| **@function_tool** | Decorate any Python function to make it callable by the LLM (auto-generates JSON schema from type hints) |
| **Handoffs** | Agents delegate to other agents seamlessly — orchestrator → researcher → writer |
| **Guardrails** | Input/output validation before and after agent runs |
| **Tracing** | Built-in tracing of every LLM call, tool invocation, and handoff |
| **Sessions** | Persistent conversation memory via SQLite or Redis |
| **MCP Support** | Connect to Model Context Protocol servers for additional tools |

### Why Not Claude Agent SDK?

The Claude Agent SDK requires an Anthropic API key (pay-per-token) and wraps the Claude Code CLI (requires Node.js). It does **not** work with GitHub Models. The OpenAI Agents SDK gives us equivalent agentic capabilities while using GitHub Models at zero cost.

---

## GitHub Models + OpenAI Agents SDK Setup

### Connection Architecture

```
┌──────────────────────────┐
│   OpenAI Agents SDK      │
│   (Python, local)        │
│                          │
│   Agent → Runner.run()   │
│   └─ tool calls          │
│   └─ handoffs            │
│   └─ guardrails          │
└──────────┬───────────────┘
           │ OpenAI Chat Completions API
           ▼
┌──────────────────────────┐
│   GitHub Models API      │
│   models.github.ai       │
│                          │
│   openai/gpt-4.1         │
│   openai/gpt-4.1-mini    │
│   openai/gpt-4.1-nano    │
└──────────────────────────┘
```

### Setup Code

```python
# agents/setup.py — SDK initialisation with GitHub Models

import os
from openai import AsyncOpenAI
from agents import set_default_openai_client, set_default_openai_api

def init_github_models():
    """Configure the OpenAI Agents SDK to use GitHub Models API."""
    client = AsyncOpenAI(
        base_url="https://models.github.ai/inference",
        api_key=os.environ["GITHUB_TOKEN"],
    )
    set_default_openai_client(client)
    set_default_openai_api("chat_completions")
    return client
```

### Copilot Pro Rate Limits

| Model Tier | Models | Requests/min | Tokens/min (input) | Tokens/min (output) | Requests/day |
|---|---|---|---|---|---|
| **Custom** | openai/gpt-5, gpt-5-mini, gpt-5-nano, o3, o4-mini | Unlimited (Pro+) | Unlimited (Pro+) | Unlimited (Pro+) | Unlimited (Pro+) |
| **High** | openai/gpt-4.1, gpt-4o | Unlimited (Pro+) | Unlimited (Pro+) | Unlimited (Pro+) | Unlimited (Pro+) |
| **Low** | openai/gpt-4.1-mini, gpt-4.1-nano | Unlimited (Pro+) | Unlimited (Pro+) | Unlimited (Pro+) | Unlimited (Pro+) |

> With Copilot Pro+, there are no daily request caps. The pipeline enforces its own soft RPM and daily budget limits via `pipeline/guardrails.py` to avoid transient rate-limit errors from the API.

**Architecture implication:** Use `gpt-4.1` for research, writing, and editing (1M context, reliable reasoning). Use `gpt-4.1-mini` for orchestration, publishing, and indexing (fast, lightweight). Fallback chain: `gpt-4.1` → `gpt-4.1-mini` → `gpt-4.1-nano`.

---

## Agent Architecture

### Agent Definitions

Each agent in the pipeline is an `Agent` object with its own model, tools, and instructions. Agents communicate via **handoffs** — when one agent finishes, it delegates to the next.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       ORCHESTRATOR AGENT                                │
│                       (openai/gpt-4.1-mini)                               │
│                                                                         │
│   Receives task → decides which agent to invoke via handoff             │
│                                                                         │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                │
│   │  Researcher   │  │   Writer     │  │   Editor     │                │
│   │  (gpt-4.1)    │  │  (gpt-4.1)   │  │  (gpt-4.1)   │                │
│   │              │  │              │  │              │                │
│   │  Tools:       │  │  Tools:       │  │  Tools:       │                │
│   │  - web_search │  │  - read_file  │  │  - read_file  │                │
│   │  - search_    │  │  - write_file │  │  - write_file │                │
│   │    corpus     │  │              │  │  - search_    │                │
│   │  - fetch_page │  │              │  │    corpus     │                │
│   │  - search_    │  │              │  │  - score_     │                │
│   │    arxiv      │  │              │  │    credibility│                │
│   └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                │
│          │                 │                 │                         │
│          └─────────────────┼─────────────────┘                         │
│                            ▼                                            │
│                  ┌──────────────┐  ┌──────────────┐                    │
│                  │  Publisher   │  │   Indexer    │                    │
│                  │ (gpt-4.1-mini│  │(gpt-4.1-mini)│                    │
│                  │              │  │              │                    │
│                  │  Tools:       │  │  Tools:       │                    │
│                  │  - publish_   │  │  - index_     │                    │
│                  │    to_ghost  │  │    document  │                    │
│                  │              │  │  - embed_text│                    │
│                  └──────────────┘  └──────────────┘                    │
└─────────────────────────────────────────────────────────────────────────┘
```

### Agent Definitions Code

```python
# agents/definitions.py — All agent definitions

from agents import Agent, ModelSettings
from agents.tools import (
    web_search, search_corpus, fetch_page, search_arxiv,
    publish_to_ghost, index_document, embed_and_store,
    read_research_file, write_research_file,
    send_reply_email, score_credibility,
)

# --- Subagents (defined first, referenced in handoffs) ---

researcher = Agent(
    name="Researcher",
    instructions="""You are a senior research analyst for BeyondTomorrow.World.

Given a topic:
1. Generate 3-5 targeted search queries covering different angles
2. Search the web (DuckDuckGo/Brave) AND the private knowledge corpus in parallel
3. For academic topics, also search arXiv and Semantic Scholar
4. Fetch and read the full content of the top 8-10 most promising sources
5. Score each source for credibility (government/academic = high, blogs = low)
6. Discard sources scoring below relevance threshold 3/5
7. Synthesise findings into structured JSON with:
   - key_findings (with confidence levels and source citations)
   - subtopics (with bullet points)
   - suggested_angles (for the writer)
   - gaps (what the research couldn't answer)

Rules:
- Only make claims supported by sources you actually read
- Flag single-source claims as lower confidence
- Note contradictions between sources
- Cite specific URLs for every key finding
- Prefer recent sources (last 2 years) but include older ones if highly relevant""",
    tools=[web_search, search_corpus, fetch_page, search_arxiv, score_credibility],
    model="openai/gpt-4.1",
    model_settings=ModelSettings(temperature=0.2, max_tokens=8000),
)

writer = Agent(
    name="Writer",
    instructions="""You are a skilled blog writer for BeyondTomorrow.World.

Given research findings (structured JSON from the Researcher):
1. Choose the most compelling angle from suggested_angles
2. Write an engaging, well-structured blog post (1500-2500 words)
3. Use clear headings (H2/H3), short paragraphs, and bullet points where appropriate
4. Cite sources naturally in the text (linked references)
5. Maintain an authoritative but accessible tone
6. Include a strong introduction that hooks the reader
7. End with a forward-looking conclusion

Output format: Markdown with frontmatter (title, tags, excerpt).
Save the draft using write_research_file.""",
    tools=[read_research_file, write_research_file],
    model="openai/gpt-4.1",
    model_settings=ModelSettings(temperature=0.7, max_tokens=4000),
)

editor = Agent(
    name="Editor",
    instructions="""You are a meticulous editor for BeyondTomorrow.World.

Review the blog post draft for:
1. Factual accuracy — cross-reference claims against the research findings
2. Grammar, spelling, and punctuation
3. Tone consistency — authoritative but accessible
4. Structure and flow — logical progression, clear transitions
5. Proper citations — every major claim has a source
6. SEO basics — clear title, meta description, proper heading hierarchy
7. Length — should be 1500-2500 words

Make targeted edits directly. Do NOT rewrite from scratch.
Flag any claims you cannot verify against the provided research.
Save the edited version using write_research_file.""",
    tools=[read_research_file, write_research_file, search_corpus, score_credibility],
    model="openai/gpt-4.1",
    model_settings=ModelSettings(temperature=0.3, max_tokens=4000),
)

publisher = Agent(
    name="Publisher",
    instructions="""You are the publishing agent for BeyondTomorrow.World.

Given a final edited blog post:
1. Read the post file
2. Extract title, tags, and excerpt from the frontmatter
3. Publish to Ghost CMS via the Admin API
4. Return the live post URL

Only publish posts that have been through the Editor.
If publishing fails, save the error and report it.""",
    tools=[read_research_file, publish_to_ghost],
    model="openai/gpt-4.1-mini",
    model_settings=ModelSettings(temperature=0.0, max_tokens=1000),
)

indexer = Agent(
    name="Indexer",
    instructions="""You are a document processing specialist.

Given a document (PDF text, research output, or web content):
1. Read the document content
2. Split into logical chunks (500-1000 tokens each, respecting paragraph boundaries)
3. Generate embeddings for each chunk using embed_and_store
4. Store the embeddings in pgvector with metadata (source, date, type)

For research outputs, also extract key findings as separate high-priority chunks.""",
    tools=[read_research_file, index_document, embed_and_store],
    model="openai/gpt-4.1-mini",
    model_settings=ModelSettings(temperature=0.0, max_tokens=500),
)

# --- Orchestrator (uses handoffs to delegate) ---

orchestrator = Agent(
    name="Orchestrator",
    instructions="""You are the orchestrator for BeyondTomorrow.World's automated blog pipeline.

When given a task, determine the type and execute the appropriate workflow:

**BLOG task** (subject: BLOG: topic):
1. Hand off to Researcher with the topic
2. Hand off to Writer with the research findings
3. Hand off to Editor to review the draft
4. Hand off to Publisher to publish the final post
5. Hand off to Indexer to store the research in the knowledge corpus

**RESEARCH task** (subject: RESEARCH: topic):
1. Hand off to Researcher with the topic
2. Hand off to Indexer to store findings in the corpus
3. Report completion

**REPORT task** (subject: REPORT: topic):
1. Hand off to Researcher with the topic (request full report format)
2. Hand off to Indexer to store findings
3. Report completion with the report file path

**INDEX task** (subject: INDEX: description):
1. Hand off to Indexer with the document content

Always log your decisions and report progress after each handoff.
If any agent fails, log the error and continue with the remaining steps.""",
    handoffs=[researcher, writer, editor, publisher, indexer],
    model="openai/gpt-4.1-mini",
    model_settings=ModelSettings(temperature=0.1, max_tokens=2000),
)
```

---

## Tool Definitions

Every domain capability is wrapped as a `@function_tool` — the SDK auto-generates the JSON schema from Python type hints and docstrings.

### Core Tools

```python
# agents/tools/__init__.py — Tool registry

from agents.tools.search import web_search, search_arxiv, fetch_page
from agents.tools.corpus import search_corpus, index_document, embed_and_store
from agents.tools.ghost import publish_to_ghost
from agents.tools.files import read_research_file, write_research_file
from agents.tools.email import send_reply_email
from agents.tools.quality import score_credibility

__all__ = [
    "web_search", "search_arxiv", "fetch_page",
    "search_corpus", "index_document", "embed_and_store",
    "publish_to_ghost",
    "read_research_file", "write_research_file",
    "send_reply_email",
    "score_credibility",
]
```

### Search Tools

```python
# agents/tools/search.py

from agents import function_tool
from duckduckgo_search import DDGS
import httpx
import trafilatura


@function_tool
async def web_search(query: str, max_results: int = 10) -> str:
    """Search the web using DuckDuckGo. Returns titles, URLs, and snippets.

    Args:
        query: The search query string.
        max_results: Maximum number of results to return (default 10).
    """
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))
    return "\n\n".join(
        f"**{r['title']}**\n{r['href']}\n{r['body']}"
        for r in results
    )


@function_tool
async def search_arxiv(query: str, max_results: int = 5) -> str:
    """Search arXiv for academic papers. Returns titles, abstracts, and links.

    Args:
        query: The search query for academic papers.
        max_results: Maximum number of papers to return (default 5).
    """
    import arxiv

    client = arxiv.Client()
    search = arxiv.Search(query=query, max_results=max_results, sort_by=arxiv.SortCriterion.Relevance)
    results = []
    for paper in client.results(search):
        results.append(
            f"**{paper.title}**\n"
            f"URL: {paper.entry_id}\n"
            f"Published: {paper.published.strftime('%Y-%m-%d')}\n"
            f"Abstract: {paper.summary[:500]}"
        )
    return "\n\n---\n\n".join(results) if results else "No arXiv results found."


@function_tool
async def fetch_page(url: str) -> str:
    """Fetch a web page and extract the main article text (strips ads, nav, boilerplate).

    Args:
        url: The URL of the web page to fetch and extract text from.
    """
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "BeyondTomorrow-Research/1.0"})
        resp.raise_for_status()

    text = trafilatura.extract(resp.text, include_comments=False, include_tables=True)
    if not text:
        return f"Could not extract text from {url}"

    # Truncate to ~4000 tokens worth of text to stay within context budget
    max_chars = 16000
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[... truncated]"

    return f"Source: {url}\n\n{text}"
```

### Corpus Tools (pgvector)

```python
# agents/tools/corpus.py

import json
from agents import function_tool
from agents.embeddings import embed, embed_batch
from agents.db import get_pool


@function_tool
async def search_corpus(query: str, top_k: int = 5) -> str:
    """Search the private knowledge corpus using semantic similarity (pgvector).

    Args:
        query: The search query — will be embedded and compared against stored documents.
        top_k: Number of most similar results to return (default 5).
    """
    query_vector = embed(query)
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT content, metadata, 1 - (embedding <=> $1::vector) AS similarity
            FROM embeddings
            WHERE 1 - (embedding <=> $1::vector) > 0.3
            ORDER BY embedding <=> $1::vector
            LIMIT $2
        """, str(query_vector), top_k)

    if not rows:
        return "No relevant documents found in the knowledge corpus."

    results = []
    for row in rows:
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        results.append(
            f"**[Corpus match — similarity: {row['similarity']:.3f}]**\n"
            f"Source: {meta.get('source', 'unknown')}\n"
            f"Date: {meta.get('date', 'unknown')}\n\n"
            f"{row['content'][:2000]}"
        )
    return "\n\n---\n\n".join(results)


@function_tool
async def index_document(content: str, source: str, doc_type: str, date: str = "") -> str:
    """Index a document into the knowledge corpus. Chunks the text, embeds it, and stores in pgvector.

    Args:
        content: The full text content to index.
        source: Where the document came from (URL, filename, or description).
        doc_type: Type of document — one of: research, article, pdf, email, webpage.
        date: ISO date string (YYYY-MM-DD) when the document was created or retrieved.
    """
    # Chunk the content (simple paragraph-based chunking)
    chunks = _chunk_text(content, max_tokens=500, overlap=50)
    if not chunks:
        return "No content to index."

    # Embed all chunks in batch
    vectors = embed_batch(chunks)

    # Store in pgvector
    pool = await get_pool()
    metadata = json.dumps({"source": source, "type": doc_type, "date": date})

    async with pool.acquire() as conn:
        for chunk, vector in zip(chunks, vectors):
            await conn.execute("""
                INSERT INTO embeddings (content, embedding, metadata)
                VALUES ($1, $2::vector, $3)
            """, chunk, str(vector), metadata)

    return f"Indexed {len(chunks)} chunks from '{source}' into the knowledge corpus."


@function_tool
async def embed_and_store(text: str, source: str, metadata_json: str = "{}") -> str:
    """Embed a single text chunk and store it in pgvector. Use for individual chunks.

    Args:
        text: The text chunk to embed and store.
        source: Source identifier for this chunk.
        metadata_json: JSON string with additional metadata.
    """
    vector = embed(text)
    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO embeddings (content, embedding, metadata)
            VALUES ($1, $2::vector, $3)
        """, text, str(vector), metadata_json)

    return f"Stored 1 chunk from '{source}'."


def _chunk_text(text: str, max_tokens: int = 500, overlap: int = 50) -> list[str]:
    """Split text into chunks by paragraph boundaries, with overlap."""
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = []
    current_length = 0

    for para in paragraphs:
        para_tokens = len(para.split())  # rough token estimate
        if current_length + para_tokens > max_tokens and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            # Overlap: keep last paragraph
            if overlap > 0 and current_chunk:
                current_chunk = [current_chunk[-1]]
                current_length = len(current_chunk[0].split())
            else:
                current_chunk = []
                current_length = 0

        current_chunk.append(para)
        current_length += para_tokens

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks
```

### Ghost Publishing Tool

```python
# agents/tools/ghost.py

import json
import jwt
import time
import httpx
from agents import function_tool


@function_tool
async def publish_to_ghost(title: str, html_content: str, tags: str = "", excerpt: str = "", status: str = "draft") -> str:
    """Publish a blog post to Ghost CMS via the Admin API.

    Args:
        title: The blog post title.
        html_content: The post content in HTML format.
        tags: Comma-separated list of tag names (e.g., "technology, AI, quantum").
        excerpt: A short custom excerpt for the post (1-2 sentences).
        status: Publication status — 'draft' (default, for review) or 'published' (live immediately).
    """
    import os

    ghost_url = os.environ["GHOST_URL"]       # e.g., https://beyondtomorrow.world
    admin_key = os.environ["GHOST_ADMIN_KEY"]  # format: id:secret

    # Generate JWT for Ghost Admin API
    key_id, secret = admin_key.split(":")
    iat = int(time.time())
    header = {"alg": "HS256", "typ": "JWT", "kid": key_id}
    payload = {"iat": iat, "exp": iat + 300, "aud": "/admin/"}
    token = jwt.encode(payload, bytes.fromhex(secret), algorithm="HS256", headers=header)

    # Build post payload
    tag_list = [{"name": t.strip()} for t in tags.split(",") if t.strip()] if tags else []
    post_data = {
        "posts": [{
            "title": title,
            "html": html_content,
            "tags": tag_list,
            "custom_excerpt": excerpt,
            "status": status,
        }]
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{ghost_url}/ghost/api/admin/posts/",
            json=post_data,
            headers={
                "Authorization": f"Ghost {token}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()

    result = resp.json()
    post = result["posts"][0]
    return f"Published: '{post['title']}' → {post['url']} (status: {post['status']})"
```

---

## Database Schema (PostgreSQL + pgvector)

### Tables

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Knowledge corpus embeddings (existing, migrated to 384 dims)
CREATE TABLE IF NOT EXISTS embeddings (
    id          SERIAL PRIMARY KEY,
    content     TEXT NOT NULL,
    embedding   vector(384) NOT NULL,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- HNSW index for fast similarity search
CREATE INDEX IF NOT EXISTS embeddings_hnsw_idx
    ON embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Research run tracking
CREATE TABLE IF NOT EXISTS research_runs (
    id              SERIAL PRIMARY KEY,
    topic           TEXT NOT NULL,
    trigger_type    VARCHAR(20) NOT NULL,  -- email, cli, scheduled
    status          VARCHAR(20) DEFAULT 'running',  -- running, completed, failed, partial
    task_type       VARCHAR(20) NOT NULL,  -- research, report, blog, index
    models_used     JSONB DEFAULT '{}',
    source_count    INTEGER DEFAULT 0,
    duration_sec    FLOAT,
    output_path     TEXT,
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

-- LLM API call tracking (rate limit management)
CREATE TABLE IF NOT EXISTS rate_limit_log (
    id          SERIAL PRIMARY KEY,
    model       VARCHAR(50) NOT NULL,
    tokens_in   INTEGER DEFAULT 0,
    tokens_out  INTEGER DEFAULT 0,
    run_id      INTEGER REFERENCES research_runs(id),
    phase       VARCHAR(30),  -- planning, search, filtering, synthesis, writing, editing
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Index on rate_limit_log for daily budget queries
CREATE INDEX IF NOT EXISTS rate_limit_log_daily_idx
    ON rate_limit_log (model, created_at);

-- Agent session persistence (for resumable tasks and debugging)
CREATE TABLE IF NOT EXISTS agent_sessions (
    id              SERIAL PRIMARY KEY,
    session_id      UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    run_id          INTEGER REFERENCES research_runs(id),
    agent_name      VARCHAR(50) NOT NULL,  -- orchestrator, researcher, writer, editor, publisher, indexer
    conversation    JSONB NOT NULL DEFAULT '[]',  -- message history
    status          VARCHAR(20) DEFAULT 'active',  -- active, completed, failed, paused
    handoff_from    VARCHAR(50),  -- which agent handed off to this one
    handoff_to      VARCHAR(50),  -- which agent this one handed off to
    tool_calls      JSONB DEFAULT '[]',  -- record of all tool invocations
    total_tokens    INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS agent_sessions_run_idx ON agent_sessions (run_id);
CREATE INDEX IF NOT EXISTS agent_sessions_status_idx ON agent_sessions (status);

-- Cached search results (avoid re-fetching the same URL)
CREATE TABLE IF NOT EXISTS search_results (
    id              SERIAL PRIMARY KEY,
    query           TEXT NOT NULL,
    url             TEXT NOT NULL,
    title           TEXT,
    snippet         TEXT,
    fetched_text    TEXT,
    relevance_score INTEGER,
    source_type     VARCHAR(30),  -- web, arxiv, pubmed, scholar, corpus
    run_id          INTEGER REFERENCES research_runs(id),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS search_results_url_idx ON search_results (url);
```

### Database Connection Module

```python
# agents/db.py — Async PostgreSQL connection pool

import os
import asyncpg

_pool = None

async def get_pool() -> asyncpg.Pool:
    """Get or create the async connection pool."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            os.environ["DATABASE_URL"],
            min_size=2,
            max_size=10,
        )
    return _pool

async def close_pool():
    """Close the connection pool gracefully."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None

async def log_rate_limit(model: str, tokens_in: int, tokens_out: int,
                         run_id: int = None, phase: str = None):
    """Log an LLM API call for rate limit tracking."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO rate_limit_log (model, tokens_in, tokens_out, run_id, phase)
            VALUES ($1, $2, $3, $4, $5)
        """, model, tokens_in, tokens_out, run_id, phase)

async def get_daily_usage(model: str) -> dict:
    """Get today's usage for a specific model."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT COUNT(*) as calls,
                   COALESCE(SUM(tokens_in), 0) as total_tokens_in,
                   COALESCE(SUM(tokens_out), 0) as total_tokens_out
            FROM rate_limit_log
            WHERE model = $1
              AND created_at >= CURRENT_DATE
        """, model)
    return dict(row) if row else {"calls": 0, "total_tokens_in": 0, "total_tokens_out": 0}
```

---

## Guardrails & Cost Controls

### Rate Limit Guardrail

```python
# agents/guardrails.py

from agents import InputGuardrail, GuardrailFunctionOutput, Runner
from agents.db import get_daily_usage

# Daily budget limits (self-imposed for Copilot Pro+)
DAILY_LIMITS = {
    "openai/gpt-4.1": {"calls": 80, "tokens_in": 500_000},
    "openai/gpt-4.1-mini": {"calls": 500, "tokens_in": 1_000_000},
    "openai/gpt-4.1-nano": {"calls": 1000, "tokens_in": 1_000_000},
    "openai/gpt-5": {"calls": 80, "tokens_in": 500_000},
    "openai/gpt-5-mini": {"calls": 500, "tokens_in": 1_000_000},
    "openai/gpt-5-nano": {"calls": 1000, "tokens_in": 1_000_000},
}

async def check_rate_limits(ctx, agent, input_text):
    """Block agent runs if daily rate limits are approaching."""
    model = agent.model or "openai/gpt-4.1-mini"
    usage = await get_daily_usage(model)
    limits = DAILY_LIMITS.get(model, {"calls": 100, "tokens_in": 500_000})

    usage_pct = usage["calls"] / limits["calls"]

    if usage_pct >= 0.95:
        return GuardrailFunctionOutput(
            output_info={"blocked": True, "reason": f"Daily limit reached for {model}"},
            tripwire_triggered=True,
        )

    if usage_pct >= 0.80:
        # Warn but allow — agent should degrade model if possible
        return GuardrailFunctionOutput(
            output_info={"warning": f"{model} at {usage_pct:.0%} of daily limit"},
            tripwire_triggered=False,
        )

    return GuardrailFunctionOutput(
        output_info={"ok": True, "usage_pct": f"{usage_pct:.0%}"},
        tripwire_triggered=False,
    )

rate_limit_guardrail = InputGuardrail(guardrail_function=check_rate_limits)
```

### Automatic Model Degradation

```python
# agents/degradation.py — Fallback model selection based on rate limits

from agents.db import get_daily_usage
from agents.guardrails import DAILY_LIMITS

FALLBACK_CHAIN = [
    "openai/gpt-4.1",
    "openai/gpt-4.1-mini",
    "openai/gpt-4.1-nano",
]

async def select_model(preferred: str) -> str:
    """Select the best available model, falling back if rate limits are high."""
    start_idx = FALLBACK_CHAIN.index(preferred) if preferred in FALLBACK_CHAIN else 0

    for model in FALLBACK_CHAIN[start_idx:]:
        usage = await get_daily_usage(model)
        limits = DAILY_LIMITS.get(model, {"calls": 100})
        if usage["calls"] < limits["calls"] * 0.9:
            return model

    return FALLBACK_CHAIN[-1]  # gpt-4.1-nano as last resort
```

---

## Running the Pipeline

### Entry Point

```python
# agents/main.py — Entry point for all agent tasks

import asyncio
from agents import Runner
from agents.setup import init_github_models
from agents.definitions import orchestrator
from agents.db import get_pool, close_pool

async def run_task(task_type: str, topic: str, instructions: str = ""):
    """Execute an agent task through the orchestrator."""
    init_github_models()

    prompt = f"""Task type: {task_type.upper()}
Topic: {topic}
{"Instructions: " + instructions if instructions else ""}

Execute the {task_type} workflow as described in your instructions."""

    result = await Runner.run(orchestrator, input=prompt)

    # Log the run
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO research_runs (topic, trigger_type, status, task_type)
            VALUES ($1, 'cli', 'completed', $2)
        """, topic, task_type)

    await close_pool()
    return result.final_output

# CLI entry point
if __name__ == "__main__":
    import sys
    task_type = sys.argv[1] if len(sys.argv) > 1 else "research"
    topic = sys.argv[2] if len(sys.argv) > 2 else "AI agents in 2026"
    print(asyncio.run(run_task(task_type, topic)))
```

### Email Listener Integration

```python
# agents/email_listener.py — IMAP polling + dispatch to orchestrator

import imaplib
import email
import os
import asyncio
from agents import Runner
from agents.setup import init_github_models
from agents.definitions import orchestrator

IMAP_HOST = "imap.hostinger.com"
IMAP_PORT = 993

def check_and_process_emails():
    """Poll IMAP for new emails and dispatch to the agent pipeline."""
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    mail.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASS"])
    mail.select("INBOX")

    _, messages = mail.search(None, "UNSEEN")
    if not messages[0]:
        print("[email] No new messages.")
        mail.logout()
        return

    for msg_id in messages[0].split():
        _, data = mail.fetch(msg_id, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])

        sender = email.utils.parseaddr(msg["From"])[1]
        subject = msg["Subject"] or ""
        body = _extract_body(msg)

        # Validate sender
        if not _is_allowed_sender(sender):
            print(f"[email] Blocked sender: {sender}")
            continue

        # Parse command from subject
        task_type, topic = _parse_subject(subject)
        if not task_type:
            print(f"[email] Unknown command in subject: {subject}")
            continue

        print(f"[email] Processing: {task_type} — {topic} (from {sender})")

        # Run the agent pipeline
        init_github_models()
        result = asyncio.run(
            Runner.run(orchestrator, input=f"Task: {task_type}\nTopic: {topic}\nInstructions: {body}")
        )
        print(f"[email] Completed: {result.final_output[:200]}")

        # Mark as read
        mail.store(msg_id, "+FLAGS", "\\Seen")

    mail.logout()

def _parse_subject(subject: str) -> tuple[str, str]:
    """Parse 'COMMAND: topic' from email subject."""
    for cmd in ["BLOG", "RESEARCH", "REPORT", "INDEX"]:
        if subject.upper().startswith(f"{cmd}:"):
            return cmd.lower(), subject[len(cmd) + 1:].strip()
    return None, None

def _extract_body(msg) -> str:
    """Extract plain text body from email message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode("utf-8", errors="replace")
    return msg.get_payload(decode=True).decode("utf-8", errors="replace")

def _is_allowed_sender(sender: str) -> bool:
    """Check sender against allowlist."""
    import yaml
    with open("config/allowlist.yaml") as f:
        config = yaml.safe_load(f)
    return sender.lower() in [s.lower() for s in config.get("allowed_senders", [])]
```

---

## File Structure

```
agents/
├── __init__.py                 # Package init
├── main.py                     # Entry point — Runner.run(orchestrator, ...)
├── setup.py                    # GitHub Models client init (AsyncOpenAI + set_default)
├── definitions.py              # All Agent definitions (orchestrator, researcher, writer, etc.)
├── embeddings.py               # Local sentence-transformers embeddings (unchanged)
├── email_listener.py           # IMAP polling + dispatch to orchestrator
├── db.py                       # asyncpg connection pool + rate limit logging
├── guardrails.py               # Rate limit guardrail + cost controls
├── degradation.py              # Automatic model fallback selection
├── config_loader.py            # Load + validate YAML configs
├── cli.py                      # CLI interface (argparse → Runner.run)
├── tools/
│   ├── __init__.py             # Tool registry (exports all @function_tool functions)
│   ├── search.py               # @function_tool: web_search, search_arxiv, fetch_page
│   ├── corpus.py               # @function_tool: search_corpus, index_document, embed_and_store
│   ├── ghost.py                # @function_tool: publish_to_ghost
│   ├── files.py                # @function_tool: read_research_file, write_research_file
│   ├── email_tools.py          # @function_tool: send_reply_email
│   └── quality.py              # @function_tool: score_credibility
├── prompts/                    # System prompt overrides (loaded by config_loader)
│   ├── researcher.md
│   ├── writer.md
│   ├── editor.md
│   └── publisher.md
config/
├── sources.yaml                # Preferred web sources per category
├── allowlist.yaml              # Approved email senders
├── models.yaml                 # Model assignments per agent + fallback chain
├── limits.yaml                 # Rate limits, budgets, timeouts
└── prompts.yaml                # Custom prompt overrides
scripts/
├── migrate-to-384.py           # One-time: pgvector 1536→384 dimension migration
├── init-schema.py              # Create all PostgreSQL tables
└── (existing scripts)
.github/
└── workflows/
    ├── email-check.yml         # Every 5 min: check IMAP for triggers
    ├── daily-research.yml      # Daily: auto-select topic + blog pipeline
    └── research.yml            # Manual: on-demand research dispatch
```

---

## Build Order

| Phase | What to Build | Depends On | Est. Effort |
|---|---|---|---|
| **1** | `setup.py` + `db.py` — GitHub Models client + asyncpg pool | GitHub PAT, Railway PostgreSQL | Half day |
| **2** | `scripts/init-schema.py` — Create all tables (embeddings, research_runs, rate_limit_log, agent_sessions, search_results) | Phase 1 | 2 hours |
| **3** | `scripts/migrate-to-384.py` — Migrate vector(1536) → vector(384) | Phase 2 | 2 hours |
| **4** | `embeddings.py` — Already done (keep as-is) | — | Done |
| **5** | `tools/search.py` + `tools/corpus.py` — Search + corpus tools | Phases 1-3 | 1 day |
| **6** | `tools/ghost.py` + `tools/files.py` + `tools/quality.py` — Publishing + file I/O + credibility | Phase 1 | Half day |
| **7** | `definitions.py` — All Agent definitions with handoffs | Phases 5-6 | 1 day |
| **8** | `guardrails.py` + `degradation.py` — Cost controls | Phase 1 | Half day |
| **9** | `main.py` + `cli.py` — Entry points | Phases 7-8 | Half day |
| **10** | `email_listener.py` + `tools/email_tools.py` — IMAP + reply | Phase 9 | 1 day |
| **11** | `config/` — All YAML configs + `config_loader.py` | — | Half day |
| **12** | GitHub Actions workflows | Phase 10 | Half day |
| **13** | Integration testing + quality review | All phases | 1-2 days |

**Total estimated effort: 7-8 days**

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| **Agent Framework** | OpenAI Agents SDK (`openai-agents`) | Provider-agnostic, works with GitHub Models, built-in agent loop + handoffs + guardrails |
| **LLM Provider** | GitHub Models API | Zero cost — included in Copilot Pro+ |
| **Orchestrator Model** | openai/gpt-4.1-mini | Fast routing; 1M context |
| **Heavy Tasks Model** | openai/gpt-4.1 (research/write/edit) | Reliable reasoning + tool-calling; 1M context |
| **Light Tasks Model** | openai/gpt-4.1-mini (publish/index/orchestrate) | Fast, 1M context |
| **Fallback Chain** | gpt-4.1 → gpt-4.1-mini → gpt-4.1-nano | Automatic degradation on rate limits |
| **Embeddings** | Local all-MiniLM-L6-v2 | Free, runs on Railway CPU, no API calls |
| **Async Driver** | asyncpg | Native async PostgreSQL, works with asyncio agent loop |
| **Session Persistence** | PostgreSQL agent_sessions table | Resumable tasks, full audit trail, debugging |
| **Summariser Agent** | Merged into Researcher | Saves 1 LLM call per run; Researcher outputs structured JSON directly |
| **Default Publish Status** | draft | Human review gate — posts must be approved before going live |

---

## Cost Summary

| Service | Cost Driver | Est. Monthly |
|---|---|---|
| Railway | Hosting + MySQL + PostgreSQL | $5–25 |
| LLM Calls | GitHub Models API (Copilot Pro) | $0 |
| Embeddings | Local all-MiniLM-L6-v2 on Railway CPU | $0 |
| OpenAI Agents SDK | Open source (MIT license) | $0 |
| Hostinger Email | Included with domain hosting | $0 |
| GitHub Actions | Workflow minutes | Free |
| **Total** | | **$5–25/month** |

---

## Comparison: What Changed from the Claude Agent SDK Plan

| Aspect | Claude Agent SDK Plan | OpenAI Agents SDK Plan |
|---|---|---|
| **Framework** | `claude-agent-sdk` (Anthropic) | `openai-agents` (OpenAI, MIT) |
| **LLM Cost** | Pay-per-token (Anthropic API) | $0 (GitHub Models via Copilot Pro+) |
| **Runtime Dependency** | Node.js (Claude Code CLI) | Python only |
| **Tool Decorator** | `@tool` | `@function_tool` |
| **Agent Definition** | `AgentDefinition` | `Agent(name, instructions, tools, handoffs)` |
| **Agent Loop** | `ClaudeSDKClient.query()` | `Runner.run(agent, input)` |
| **Subagent Delegation** | SDK `Task` tool | `handoffs=[agent_a, agent_b]` |
| **Hooks** | `PreToolUse`, `PostToolUse`, `Stop` | `InputGuardrail`, `OutputGuardrail`, lifecycle hooks |
| **Memory** | `CLAUDE.md` + session context | `SQLiteSession` / custom PostgreSQL |
| **MCP Support** | `create_sdk_mcp_server()` | `MCPServerStdio` / `MCPServerSse` |
| **Provider Lock-in** | Anthropic only | Any OpenAI-compatible API |
