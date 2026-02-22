# Research Agent — Detailed Build Plan

> **📌 Update (2026-02-22):** This plan uses the [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) (`openai-agents`) for all agent orchestration. The SDK is provider-agnostic and works with GitHub Models API at zero cost via Copilot Pro. Domain tools are wrapped as `@function_tool` decorators, agents communicate via **handoffs**, and cost controls are implemented as **guardrails**. See [OPENAI_AGENTS_SDK_GUIDE.md](OPENAI_AGENTS_SDK_GUIDE.md) for the full implementation guide with code examples.

A custom Python research agent for **BeyondTomorrow.World** that researches topics using preferred web sources and the private knowledge corpus, listens for email triggers, and produces structured notes for the blog pipeline or standalone research reports — all within the existing Railway Pro + GitHub Copilot Pro subscription (no additional API costs).

---

## Table of Contents

- [Design Principles](#design-principles)
- [Architecture Overview](#architecture-overview)
- [Step 1: LLM Access via GitHub Models API](#step-1-llm-access-via-github-models-api)
- [Step 2: Local Embeddings (Replace Paid OpenAI)](#step-2-local-embeddings-replace-paid-openai)
- [Step 3: Web Search Module](#step-3-web-search-module)
- [Step 4: Email Listener](#step-4-email-listener)
- [Step 5: Research Orchestration Engine](#step-5-research-orchestration-engine)
- [Step 6: Output Formatters](#step-6-output-formatters)
- [Step 7: Cost Controls and Safeguards](#step-7-cost-controls-and-safeguards)
- [Step 8: Quality Controls](#step-8-quality-controls)
- [Step 9: CLI Interface](#step-9-cli-interface)
- [Step 10: Configuration System](#step-10-configuration-system)
- [Step 11: GitHub Actions Automation](#step-11-github-actions-automation)
- [Step 12: Blog Pipeline Integration](#step-12-blog-pipeline-integration)
- [Database Migration](#database-migration)
- [File Structure](#file-structure)
- [Testing and Verification](#testing-and-verification)
- [Key Decisions](#key-decisions)
- [Build Order](#build-order)

---

## Design Principles

| Principle | What It Means |
|---|---|
| **Zero additional cost** | Every component stays within Railway Pro + GitHub Copilot plan limits |
| **Tiered model routing** | Use the cheapest model that can handle each task; reserve Opus for final synthesis |
| **Dual mode** | Works inside the blog pipeline AND as a standalone research tool |
| **Email-triggered** | Send an email to start research — no need to SSH into a server |
| **Auditable** | Every source, every LLM call, every decision is logged and traceable |
| **Configurable** | Change sources, models, limits, and prompts via YAML files — no code changes |
| **Graceful degradation** | If rate limits are hit, the agent downgrades models or queues tasks — never crashes |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         TRIGGER LAYER                                   │
│                                                                         │
│   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐              │
│   │  Email        │   │  CLI          │   │  GitHub       │              │
│   │  (IMAP Poll)  │   │  (Manual)     │   │  Actions      │              │
│   │              │   │              │   │  (Scheduled)  │              │
│   └──────┬───────┘   └──────┬───────┘   └──────┬───────┘              │
│          └──────────────────┼──────────────────┘                       │
│                             ▼                                           │
│              ┌──────────────────────────┐                               │
│              │  ORCHESTRATOR AGENT      │                               │
│              │  (OpenAI Agents SDK)     │                               │
│              │  Runner.run(orch, input) │                               │
│              └─────────┬────────────────┘                               │
│                        │ handoffs                                       │
│          ┌─────────────┼─────────────────┐                             │
│          ▼             ▼                  ▼                             │
│   ┌─────────────┐  ┌─────────────────┐  ┌──────────────┐              │
│   │ Researcher  │  │ Writer + Editor │  │ Publisher    │              │
│   │ Agent       │  │ Agents          │  │ Agent        │              │
│   │ (@func_tool)│  │ (handoff chain) │  │ (Ghost API)  │              │
│   └──────┬──────┘  └─────────────────┘  └──────────────┘              │
│          │                                                              │
│          │  @function_tool calls                                        │
│          ├──── web_search (DuckDuckGo/Brave)                           │
│          ├──── search_corpus (pgvector)                                 │
│          ├──── search_arxiv (arXiv API)                                 │
│          ├──── fetch_page (trafilatura)                                 │
│          └──── score_credibility                                        │
│                                                                         │
│                            │                                            │
│                            ▼                                            │
│                  ┌─────────────────────┐                                │
│                  │  LLM PROVIDER        │                                │
│                  │  (GitHub Models API) │                                │
│                  │                     │                                │
│                  │  Sonnet → Orchestrate│                                │
│                  │  Sonnet → Research   │                                │
│                  │  Sonnet → Write/Edit │                                │
│                  │  Haiku → Publish/Idx │                                │
│                  │  Opus → Deep synth   │                                │
│                  └─────────┬───────────┘                                │
│                            │                                            │
│          ┌─────────────────┼─────────────────┐                         │
│          ▼                 ▼                  ▼                         │
│   ┌─────────────┐  ┌─────────────────┐  ┌──────────────┐              │
│   │ Structured  │  │ Full Research   │  │ Corpus       │              │
│   │ Notes       │  │ Report          │  │ Entry        │              │
│   │ (→ Writer)  │  │ (→ Email/File)  │  │ (→ pgvector) │              │
│   └─────────────┘  └─────────────────┘  └──────────────┘              │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Step 1: LLM Access via GitHub Models API + OpenAI Agents SDK

### What This Is

Your GitHub Copilot Pro subscription includes access to the **GitHub Models API** — a programmatic endpoint for calling Claude, GPT-4o, Mistral, and other models. The **OpenAI Agents SDK** (`openai-agents`) wraps this into a full agentic framework with tool use, handoffs, guardrails, and tracing — all at zero additional cost.

### How It Works

- The GitHub Models API uses an **OpenAI-compatible REST interface**
- You authenticate with a **GitHub Personal Access Token** (PAT)
- The OpenAI Agents SDK connects via `AsyncOpenAI(base_url="https://models.github.ai/inference")`
- Agents can call tools, delegate to other agents, and loop autonomously
- Rate limits depend on your Copilot Pro tier (see below)

### Setup

1. Create a GitHub PAT (Fine-grained) with `models:read` scope
2. Store the PAT in Railway environment variables as `GITHUB_TOKEN`
3. Install the SDK: `pip install openai-agents`
4. Create `agents/setup.py` with:
   - `AsyncOpenAI` client pointed at `https://models.github.ai/inference`
   - `set_default_openai_client(client)` — all agents use this client
   - `set_default_openai_api("chat_completions")` — OpenAI-compatible mode
5. Define agents in `agents/definitions.py` with model, tools, and handoffs
6. Run via `Runner.run(orchestrator, input="your task")`

### Connection Details

| Setting | Value |
|---|---|
| **Base URL** | `https://models.github.ai/inference` |
| **Auth** | `Authorization: Bearer <GITHUB_TOKEN>` |
| **SDK** | `openai-agents` + `openai` Python packages |
| **Format** | OpenAI chat completions compatible |

### Model Router (Per-Agent Assignment)

Each Agent in the SDK has its own `model` parameter. The Orchestrator uses handoffs to delegate to the right agent with the right model:

| Agent | Default Model | Daily Budget (Copilot Pro) | Fallback |
|---|---|---|---|
| Orchestrator | `claude-sonnet-4` | 200 calls/day | `gpt-4o-mini` |
| Researcher | `claude-sonnet-4` | 200 calls/day | `gpt-4o-mini` |
| Writer | `claude-sonnet-4` | 200 calls/day | `gpt-4o-mini` |
| Editor | `claude-sonnet-4` | 200 calls/day | `gpt-4o-mini` |
| Publisher | `claude-haiku-3-5` | 3,000 calls/day | `gpt-4o-mini` |
| Indexer | `claude-haiku-3-5` | 3,000 calls/day | `gpt-4o-mini` |
| Deep synthesis (optional) | `claude-opus-4-6` | 50 calls/day | `claude-sonnet-4` |

### Copilot Pro Rate Limits

| Model Tier | Models | Req/min | Tokens/min (in) | Tokens/min (out) | Req/day |
|---|---|---|---|---|---|
| **High-cost** | claude-opus-4-6, gpt-4o | 10 | 30,000 | 10,000 | 50 |
| **Medium-cost** | claude-sonnet-4 | 10 | 60,000 | 10,000 | 200 |
| **Low-cost** | claude-haiku-3-5, gpt-4o-mini | 150 | 200,000 | 100,000 | 3,000 |

### User Controls

- Override the default model for any agent in `config/models.yaml`
- Override per-run via CLI flag: `--model opus` forces Opus for synthesis
- View rate limit status: `python -m agents status`
- Model routing is automatic via `agents/degradation.py` — checks daily budget before each run

### Automatic Degradation (Guardrails)

The SDK's `InputGuardrail` system checks rate limits before each agent run:

```
Normal:   Sonnet (research/writing) → Haiku (publish/index) → Opus (deep synthesis)
Low:      Sonnet (research/writing) → Haiku (all other tasks)
Critical: gpt-4o-mini (all tasks) or queue for next rate limit window
```

The `agents/guardrails.py` module implements a `rate_limit_guardrail` that:
- Checks the `rate_limit_log` table in PostgreSQL for today's usage
- Blocks the run if a model is at >95% of its daily budget
- Warns (but allows) at >80% — the agent should use `agents/degradation.py` to select a cheaper model
- Never crashes on rate limits — degrades or queues

---

## Step 2: Local Embeddings (Replace Paid OpenAI)

### What This Is

Instead of paying OpenAI for the `text-embedding-3-small` API, run a free embedding model locally on Railway's compute. This eliminates all embedding costs.

### How It Works

- Install the `sentence-transformers` Python package
- Load the model once when the worker starts — it stays in memory
- Call `model.encode(text)` to get a vector — no API calls, no network latency
- The model runs on CPU (no GPU needed)

### Model Options

| Model | Dimensions | Download Size | RAM Usage | Quality | Speed |
|---|---|---|---|---|---|
| **`all-MiniLM-L6-v2`** | 384 | 80 MB | ~250 MB | Good | Very fast |
| `all-mpnet-base-v2` | 768 | 420 MB | ~600 MB | Better | Fast |
| `bge-small-en-v1.5` | 384 | 130 MB | ~300 MB | Good | Fast |
| `nomic-embed-text-v1.5` | 768 | 550 MB | ~700 MB | Very good | Moderate |

### Recommendation

Start with **`all-MiniLM-L6-v2`**:
- Smallest download (80 MB) — fits easily on Railway
- Very fast inference on CPU
- 384 dimensions is enough for a knowledge base under 100K chunks
- Upgrade to `all-mpnet-base-v2` later if retrieval quality needs improvement

### Migration Required

Your current pgvector schema uses 1536 dimensions (OpenAI's size). Switching to a local model requires:

1. Update `embeddings` table: `vector(1536)` → `vector(384)`
2. Drop and recreate the HNSW index for the new dimension
3. Re-embed any existing documents (if any have been indexed already)

This is a one-time migration. A migration script will be provided.

### Module Interface

```python
# agents/embeddings.py

embed("some text")         → [0.012, -0.034, ...]  # 384-dim vector
embed_batch(["a", "b"])    → [[...], [...]]         # batch for efficiency
similarity(vec_a, vec_b)   → 0.87                    # cosine similarity
```

---

## Step 3: Web Search Module

### What This Is

The agent's ability to find information on the open web. Uses free search APIs — no paid subscriptions required.

### Search Engines (Free)

| Engine | How to Access | Rate Limit | API Key Needed | Best For |
|---|---|---|---|---|
| **DuckDuckGo** | `duckduckgo-search` Python package | No hard limit (be reasonable) | No | General web search, default |
| **Brave Search** | REST API | 2,000 queries/month (free tier) | Yes (free signup) | Higher quality results, academic queries |

### How a Search Works

```
1. Agent receives topic: "impact of quantum computing on cryptography"
2. LLM (Sonnet) generates 3-5 specific search queries:
   - "quantum computing threat to RSA encryption 2025"
   - "post-quantum cryptography NIST standards"
   - "quantum resistant algorithms current status"
3. Each query is sent to DuckDuckGo (primary) and/or Brave (secondary)
4. Results come back as: title, URL, snippet (short text preview)
5. Agent selects the top N most relevant URLs to fetch in full
```

### Full Page Fetching

After search results come back, the agent fetches the actual web pages to read the full content:

| Tool | What It Does | Why Use It |
|---|---|---|
| **`trafilatura`** | Extracts the main article text from any web page, strips ads/nav/boilerplate | Best general-purpose extractor; handles most sites cleanly |
| **`httpx`** | Makes HTTP requests (async-capable) | Fast, modern Python HTTP client |
| **`BeautifulSoup`** | Parses HTML when you need fine-grained control | Backup for pages where trafilatura struggles |

### Source-Specific APIs (Free)

For academic and government sources, dedicated APIs provide better results than general web search:

| Source | API / Package | Cost | What It Returns |
|---|---|---|---|
| **arXiv** | `arxiv` Python package | Free, no key | Paper titles, abstracts, PDF links |
| **Google Scholar** | `scholarly` Python package | Free (scraping, use carefully) | Paper citations, titles, abstracts |
| **PubMed** | NCBI E-utilities REST API | Free (register email) | Medical/bio research papers |
| **Wikipedia** | `wikipedia-api` Python package | Free, no key | Article summaries and references |
| **Semantic Scholar** | REST API | Free (100 req/5min) | Academic papers with citation graphs |
| **Government sites** | Direct HTTP fetch | Free | Policy documents, reports |

### Preferred Source Lists

Users define which sources the agent should prioritise in `config/sources.yaml`:

```yaml
# config/sources.yaml
default_sources:
  - duckduckgo        # Always search the general web
  - brave             # Higher quality, limited free queries

topic_sources:
  technology:
    - arxiv.org
    - news.ycombinator.com
    - arstechnica.com
    - spectrum.ieee.org
  
  geopolitics:
    - foreignaffairs.com
    - economist.com
    - bbc.com/news
    - reuters.com
  
  science:
    - nature.com
    - pubmed.ncbi.nlm.nih.gov
    - newscientist.com
  
  policy:
    - whitehouse.gov
    - parliament.uk
    - oecd.org
    - un.org

  custom:             # User adds their own
    - example.com
```

When researching a topic, the agent:
1. Runs general web search (DuckDuckGo/Brave)
2. Also searches topic-specific sources from this config
3. Prioritises results from preferred sources over random sites

### User Controls

- Add/remove sources by editing `config/sources.yaml`
- Limit search to specific sources via CLI: `--sources arxiv,scholar`
- Set max pages to fetch per query in `config/limits.yaml`

---

## Step 4: Email Listener

### What This Is

A module that connects to your Hostinger email account via IMAP, watches for incoming emails, and triggers research tasks based on what it finds.

### How It Works

```
┌──────────────────┐     ┌───────────────────┐     ┌──────────────────┐
│  1. Email sent   │     │  2. IMAP poll      │     │  3. Parse email  │
│  to admin@       │ ──▶ │     fetches new    │ ──▶ │     extract      │
│  beyondtomorrow  │     │     messages       │     │     topic +      │
│  .world          │     │                    │     │     instructions │
└──────────────────┘     └───────────────────┘     └────────┬─────────┘
                                                            │
                         ┌───────────────────┐              │
                         │  5. Reply email   │              │
                         │     sent with     │ ◀────────────┤
                         │     confirmation  │              │
                         └───────────────────┘              ▼
                                                  ┌──────────────────┐
                                                  │  4. Research     │
                                                  │     engine runs  │
                                                  │     the task     │
                                                  └──────────────────┘
```

### Connection Details

| Setting | Value |
|---|---|
| **IMAP Host** | `imap.hostinger.com` |
| **IMAP Port** | `993` (TLS) |
| **SMTP Host** | `smtp.hostinger.com` (for reply emails) |
| **SMTP Port** | `465` (TLS) |
| **Account** | `admin@beyondtomorrow.world` |
| **Credentials** | Stored in Railway env vars: `EMAIL_USER`, `EMAIL_PASS` |

### Polling Schedule

- The email listener checks for new messages every **5 minutes**
- Triggered by GitHub Actions cron or a lightweight loop inside the Railway worker
- Only unread messages in the Inbox are processed
- After processing, emails are marked as read and moved to a "Processed" folder

### Sender Allowlist (Security)

Only emails from approved senders are processed. All others are ignored silently.

```yaml
# config/allowlist.yaml
allowed_senders:
  - you@youremail.com
  - backup@yourdomain.com
  # Add more as needed
```

This prevents random people from triggering research (and burning rate limits) by emailing your address.

### Email Command Syntax

The subject line tells the agent what to do:

| Subject Format | What Happens | Example |
|---|---|---|
| `RESEARCH: topic` | Run research, save structured notes to corpus | `RESEARCH: quantum computing in 2026` |
| `REPORT: topic` | Run research, produce full report, email it back | `REPORT: EU AI regulation impact` |
| `BLOG: topic` | Run research → feed into Writer → Editor → Publisher | `BLOG: future of renewable energy` |
| `INDEX: description` | Index attached documents into knowledge corpus | `INDEX: NIST post-quantum standards` |

### Email Body (Optional Instructions)

The email body can contain additional instructions:

```
Subject: RESEARCH: quantum computing cryptography

Body:
Focus on:
- Timeline for quantum threat to current encryption
- NIST post-quantum standards progress
- Practical implications for enterprise software

Prefer sources from: arxiv, NIST, IEEE
Output: detailed notes with citations
```

If the body is empty, the agent uses defaults.

### Attachments

- PDF attachments are automatically sent to the **Indexer** agent
- They are extracted, chunked, embedded, and added to the knowledge corpus
- The research task then includes these new documents in its search

### Reply Confirmation

After processing, the agent sends a reply email:

```
Subject: RE: RESEARCH: quantum computing cryptography

Research complete ✓

Topic: quantum computing cryptography
Sources found: 12 (8 web, 4 corpus)
Output: Structured notes saved to corpus
Time: 3m 42s
Model: claude-sonnet-4 (via OpenAI Agents SDK + GitHub Models)

Key findings preview:
- NIST finalised 4 post-quantum algorithms in August 2024...
- Current estimates suggest 10-15 years until...
- [3 more bullet points]

Full output saved to: research/2026-02-22-quantum-crypto.md
```

---

## Step 5: Research Orchestration Engine (OpenAI Agents SDK)

### What This Is

The core brain of the agent system. Instead of a hand-coded 6-phase pipeline, the **OpenAI Agents SDK's agent loop** handles orchestration. The Researcher agent receives a topic, uses `@function_tool` tools autonomously (web search, corpus search, page fetching, credibility scoring), and produces structured output — all within a single `Runner.run()` call.

### How It Works (SDK Agent Loop)

```
┌─────────────────────────────────────────────────────────────────┐
│                    Runner.run(researcher, topic)                 │
│                                                                 │
│  1. Agent reads instructions + topic                            │
│  2. Agent decides which tools to call (autonomous)              │
│  3. SDK executes tool, returns result to agent                  │
│  4. Agent reads result, decides next tool/action                │
│  5. Repeat until agent produces final output                    │
│  6. SDK returns RunResult with final_output                     │
│                                                                 │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐ │
│  │  Agent    │ ─▶ │  Tool    │ ─▶ │  Agent   │ ─▶ │  Tool    │ │
│  │  thinks   │    │  call    │    │  reads   │    │  call    │ │
│  │  decides  │    │ (search) │    │  result  │    │ (fetch)  │ │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘ │
│                                                                 │
│  ... until agent returns structured findings JSON               │
└─────────────────────────────────────────────────────────────────┘
```

**Key difference from the original 6-phase pipeline:** The agent decides its own research strategy. Instead of rigidly following Plan → Search → Fetch → Filter → Synthesise → Store, the agent can:
- Search the corpus first, then decide what web searches are needed
- Fetch a page, realise it's not useful, and search for alternatives
- Run multiple search queries in sequence based on what it learns
- Skip phases entirely if the topic is well-covered in the corpus

### What the Agent Has Access To

| Tool (`@function_tool`) | What It Does | Typical Usage |
|---|---|---|
| `web_search(query, max_results)` | Search DuckDuckGo/Brave | 3-5 calls per research task |
| `search_corpus(query, top_k)` | Semantic search in pgvector | 1-2 calls per task |
| `search_arxiv(query, max_results)` | Search arXiv for papers | 1 call (if academic topic) |
| `fetch_page(url)` | Fetch + extract article text | 5-10 calls per task |
| `score_credibility(domain)` | Score source credibility | Called per source |

### Research Output Format

The Researcher agent's instructions tell it to output structured JSON:

```json
{
  "topic": "quantum computing impact on cryptography",
  "date": "2026-02-22",
  "key_findings": [
    {
      "finding": "NIST finalised four post-quantum cryptographic algorithms in August 2024",
      "confidence": "high",
      "sources": ["https://nist.gov/...", "https://arxiv.org/..."],
      "relevance": "Directly addresses the transition timeline"
    }
  ],
  "subtopics": [
    {
      "name": "Current Threat Timeline",
      "summary": "Most experts estimate 10-15 years before...",
      "bullet_points": ["...", "...", "..."]
    }
  ],
  "suggested_angles": [
    "The gap between theoretical threat and practical readiness",
    "Why most organisations haven't started migrating yet"
  ],
  "gaps": ["Limited data on quantum computing costs for attackers"],
  "source_list": [
    {"url": "https://...", "title": "...", "type": "academic_paper", "credibility": 5}
  ],
  "total_sources": 12,
  "model_used": "claude-sonnet-4"
}
```

This JSON is passed directly to the Writer agent via handoff — **no separate Summariser agent needed**.

### Pipeline Execution via Handoffs

```python
# The full pipeline is just one call:
result = await Runner.run(orchestrator, input="BLOG: quantum computing cryptography")

# The orchestrator automatically:
# 1. Hands off to Researcher → gets structured findings
# 2. Hands off to Writer → gets blog draft
# 3. Hands off to Editor → gets polished draft
# 4. Hands off to Publisher → gets Ghost URL
# 5. Hands off to Indexer → stores research in corpus
```

---

### How the Agent Loop Replaces the Old 6-Phase Pipeline

The original plan had a rigid 6-phase pipeline: Query Planning → Parallel Search → Source Fetching → Relevance Filtering → Deep Synthesis → Storage. With the OpenAI Agents SDK, the Researcher agent handles all of this **autonomously** within a single `Runner.run()` call.

| Old Phase | How the SDK Agent Handles It |
|---|---|
| **Phase 1: Query Planning** | The agent generates search queries as part of its reasoning — no separate LLM call needed |
| **Phase 2: Parallel Search** | Agent calls `web_search()` and `search_corpus()` tools multiple times as needed |
| **Phase 3: Source Fetching** | Agent calls `fetch_page(url)` for promising URLs — the tool handles trafilatura extraction |
| **Phase 4: Relevance Filtering** | Agent reads tool results inline and decides what's relevant — no separate Haiku call |
| **Phase 5: Deep Synthesis** | Agent synthesises all findings in its final output (uses Sonnet by default; upgrader to Opus for complex topics via config override) |
| **Phase 6: Storage & Indexing** | Orchestrator hands off to Indexer agent after research completes |

**Advantages:**
- **Fewer LLM calls** — no separate calls for planning, filtering, or summarisation
- **Adaptive** — agent can change strategy mid-research based on what it finds
- **Simpler code** — no manual phase orchestration; the SDK agent loop handles flow
- **Compounding knowledge** — research output is indexed in pgvector for future reference

**Typical tool call pattern for a research task:**
```
web_search("quantum computing cryptography 2026")     → 10 results
search_corpus("quantum post-quantum cryptography")      → 5 corpus matches
fetch_page("https://nist.gov/...")                       → full article text
fetch_page("https://arxiv.org/abs/...")                  → paper abstract
search_arxiv("post-quantum lattice cryptography")        → 5 papers
fetch_page("https://example.com/...")                    → ... (5-8 more fetches)
score_credibility("nist.gov")                            → 5/5
score_credibility("medium.com")                          → 2/5
→ Agent synthesises all gathered content into structured JSON
```

---

## Step 6: Output Formatters

### What This Is

The Researcher agent produces structured JSON output. For standalone reports, the output is formatted as Markdown. The Writer agent receives the JSON directly via handoff.

### Format A: Structured Notes (for Blog Pipeline)

Used when the research feeds into the Writer → Editor → Publisher chain.

```json
{
  "topic": "quantum computing impact on cryptography",
  "date": "2026-02-22",
  "key_findings": [
    {
      "finding": "NIST finalised four post-quantum cryptographic algorithms in August 2024",
      "confidence": "high",
      "sources": ["https://nist.gov/...", "https://arxiv.org/..."],
      "relevance": "Directly addresses the transition timeline"
    }
  ],
  "subtopics": [
    {
      "name": "Current Threat Timeline",
      "summary": "Most experts estimate 10-15 years before...",
      "bullet_points": ["...", "...", "..."]
    }
  ],
  "suggested_angles": [
    "The gap between theoretical threat and practical readiness",
    "Why most organisations haven't started migrating yet"
  ],
  "source_list": [
    {
      "url": "https://...",
      "title": "...",
      "type": "academic_paper",
      "relevance_score": 5
    }
  ],
  "gaps": ["Limited data on quantum computing costs for attackers"],
  "total_sources": 12,
  "model_used": "claude-sonnet-4"
}
```

The Writer agent receives this JSON directly via handoff from the Orchestrator — no separate Summariser step needed.

### Format B: Full Research Report (Standalone)

Used when triggered by a `REPORT:` email or `--report` CLI flag.

```markdown
# Research Report: Quantum Computing Impact on Cryptography
**Date:** 2026-02-22 | **Sources:** 12 | **Confidence:** High

## Executive Summary
[2-3 paragraph overview of key findings]

## 1. Current State of Quantum Computing
[Analysis with inline citations]

## 2. Threat to Current Encryption
[Analysis with inline citations]

## 3. Post-Quantum Standards
[Analysis with inline citations]

## 4. Practical Implications
[Analysis with inline citations]

## Confidence Assessment
| Finding | Confidence | Reason |
|---------|-----------|--------|
| ... | High | Confirmed by 4+ sources |
| ... | Medium | Only 2 sources, one is 2023 |

## Sources
1. [Title](URL) — accessed 2026-02-22
2. [Title](URL) — accessed 2026-02-22

## Methodology
- Models: claude-sonnet-4 (researcher/writer), claude-haiku (editor/publisher) via GitHub Models
- Search: DuckDuckGo, Brave, arXiv
- Corpus matches: 3 relevant documents
- Time: 3m 42s
```

This report can be:
- Saved to the repository
- Emailed back to the requester
- Converted to PDF via `weasyprint` (optional)

### Format C: Corpus Entry

Every research output is also stored as a corpus entry:
- Chunked into 500-1000 token pieces
- Embedded using the local model
- Indexed in pgvector for future retrieval
- This happens automatically after every research task

---

## Step 7: Cost Controls and Safeguards

### The Core Constraint

**All costs must stay within your existing Railway Pro + GitHub Copilot subscription.** There is no separate budget for API calls. This means every LLM call uses GitHub Models (included in Copilot), every embedding runs locally (free), and every web search uses free APIs.

### Rate Limit Management

GitHub Models has rate limits per model (requests per minute, tokens per minute, requests per day). The agent must stay within these limits.

| Control | How It Works |
|---|---|
| **Usage tracking** | Every LLM call is logged to a `rate_limit_log` table in PostgreSQL with: model, tokens used, timestamp |
| **Daily budgets** | Configurable per-model daily caps (e.g., max 50 Opus calls/day) |
| **Automatic degradation** | When approaching limits: Opus → Sonnet → Haiku |
| **Task queuing** | Non-urgent tasks are queued for the next rate limit window instead of failing |
| **Status command** | `python -m agents status` shows current usage vs. limits |

### Configurable Limits

```yaml
# config/limits.yaml
daily_budgets:
  claude-opus-4-6: 30          # Max Opus calls per day
  claude-sonnet-4: 100         # Max Sonnet calls per day
  claude-haiku-3-5: 200        # Max Haiku calls per day

search_limits:
  max_queries_per_task: 5       # Search queries generated per research task
  max_results_per_query: 10     # Results returned per search query
  max_pages_to_fetch: 10        # Full pages fetched per task
  page_fetch_timeout_seconds: 15

synthesis_limits:
  max_input_tokens: 50000       # Max tokens sent to synthesis model
  max_output_tokens: 8000       # Max tokens requested from synthesis model

task_limits:
  max_task_duration_minutes: 10 # Kill task if it exceeds this
  max_concurrent_tasks: 1       # Only one research task at a time

brave_search:
  monthly_budget: 2000          # Free tier limit
  current_usage: 0              # Tracked automatically
```

### What Happens When Limits Are Hit

| Scenario | Agent Behaviour |
|---|---|
| Opus daily limit reached | Downgrades to Sonnet for synthesis; logs warning |
| All model limits reached | Queues task, sends notification, retries next day |
| Brave Search monthly limit reached | Falls back to DuckDuckGo only |
| Page fetch times out | Skips that source, continues with others |
| Task exceeds time limit | Stops gracefully, outputs what it has so far |

---

## Step 8: Quality Controls

### Source Credibility Scoring

Not all sources are equal. The agent scores source credibility before synthesis:

| Domain Type | Credibility Score | Examples |
|---|---|---|
| Government (.gov) | 5 (highest) | nist.gov, whitehouse.gov |
| Academic (.edu) | 5 | mit.edu, stanford.edu |
| Peer-reviewed journals | 5 | nature.com, science.org |
| Established news orgs | 4 | reuters.com, bbc.com, apnews.com |
| Industry research | 4 | mckinsey.com, gartner.com |
| Quality tech publications | 3 | arstechnica.com, spectrum.ieee.org |
| General blogs/forums | 2 | medium.com, reddit.com |
| Unknown domains | 1 | Sites not in any known list |

Higher-credibility sources are weighted more heavily in synthesis.

### Recency Filtering

- By default, prefer sources from the last **2 years**
- Older sources are still included if highly relevant, but flagged as potentially outdated
- Configurable: `config/limits.yaml` → `max_source_age_years: 2`
- Override per-task: `--historical` flag includes older sources without penalty

### Cross-Reference Checking

The synthesis prompt instructs Opus to:
- Flag any claim that appears in **only one source** as "single-source" (lower confidence)
- Highlight claims confirmed by **3+ independent sources** as "high confidence"
- Note when sources **contradict** each other and present both perspectives

### Hallucination Prevention

| Safeguard | How It Works |
|---|---|
| **Source-grounded prompts** | The synthesis prompt explicitly says: "Only make claims supported by the provided sources. Do not add information from your training data." |
| **Citation requirement** | Every key finding must reference at least one provided source |
| **Post-processing verification** | After Opus responds, a simple script checks that cited URLs actually exist in the source list |
| **Confidence labelling** | Every finding has a confidence level (high/medium/low) based on source count and credibility |

### Human Review Gate (Optional)

For the blog pipeline, you can enable a review step before publishing:

| Mode | How It Works |
|---|---|
| **Auto-publish** (default off) | Research → Write → Edit → Publish automatically |
| **Review queue** (default on) | Research → Write → Edit → Save as draft → Email notification → You approve or reject |

This prevents the agent from publishing anything you haven't seen. Toggle in `config/limits.yaml` → `auto_publish: false`

---

## Step 9: CLI Interface

### What This Is

A command-line tool so you can trigger and manage research from your terminal.

### Commands

```bash
# Run research on a topic (produces structured notes)
python -m agents research "quantum computing impact on cryptography"

# Run research and produce a full report
python -m agents research "EU AI regulation" --report

# Run research and feed into blog pipeline
python -m agents research "future of renewable energy" --blog

# Override the synthesis model
python -m agents research "topic" --model sonnet

# Limit to specific source types
python -m agents research "topic" --sources arxiv,scholar,brave

# Check email for new research triggers
python -m agents email-check

# View rate limit usage, queued tasks, recent runs
python -m agents status

# List recent research runs
python -m agents history

# Re-run a previous research task with updated sources
python -m agents rerun <task-id>

# Index a local document into the knowledge corpus
python -m agents index /path/to/document.pdf

# Search the knowledge corpus
python -m agents corpus-search "quantum cryptography"
```

### Output

- Structured notes are printed to stdout and saved to file
- Reports are saved as Markdown files
- All runs are logged to the `research_runs` table
- Use `--quiet` flag to suppress stdout output

---

## Step 10: Configuration System

### What This Is

All agent behaviour is controlled by YAML config files. Change behaviour without touching Python code.

### Config Files

| File | What It Controls | How Often You'll Edit It |
|---|---|---|
| `config/sources.yaml` | Preferred web sources per topic category | Occasionally — when you want to add new sources |
| `config/allowlist.yaml` | Approved email senders | Rarely — when you add a new trusted sender |
| `config/models.yaml` | Which model handles each task | Rarely — defaults are optimised |
| `config/limits.yaml` | Rate limits, budgets, timeouts, max sources | Occasionally — tune based on usage patterns |
| `config/prompts.yaml` | System prompts for each agent phase | Occasionally — customise tone/style |

### Example: `config/models.yaml`

```yaml
# Which model to use for each task
# Options: claude-opus-4-6, claude-sonnet-4, claude-haiku-3-5, gpt-4o, gpt-4o-mini

task_models:
  query_planning: claude-sonnet-4
  relevance_filtering: claude-haiku-3-5
  source_summarisation: claude-sonnet-4
  deep_synthesis: claude-opus-4-6
  metadata_tagging: claude-haiku-3-5
  report_formatting: claude-sonnet-4

fallback_chain:
  - claude-opus-4-6
  - claude-sonnet-4
  - claude-haiku-3-5
  - gpt-4o-mini
```

### Example: `config/prompts.yaml`

```yaml
# Customise the system prompts for each phase
# These are injected as the system message in each LLM call

query_planning: |
  You are a research planning assistant. Given a topic, generate 
  3-5 specific search queries optimised for finding high-quality 
  information. Each query should target a different aspect of the topic.
  Return as a JSON array of strings.

relevance_filtering: |
  You are a source relevance evaluator. Rate each source 1-5 for 
  relevance to the given topic. Only rate based on the provided 
  summary — do not speculate about content you haven't seen.
  Return as JSON: [{"url": "...", "score": N, "reason": "..."}]

deep_synthesis: |
  You are a senior research analyst. Synthesise the provided sources 
  into a comprehensive analysis. Rules:
  - Only make claims supported by the provided sources
  - Cite sources for every key finding
  - Flag single-source claims as lower confidence
  - Note contradictions between sources
  - Identify gaps in the research
```

---

## Step 11: GitHub Actions Automation

### What This Is

GitHub Actions workflows that run the agent automatically on a schedule or on demand.

### Workflow: Email Check (Every 5 Minutes)

```yaml
# .github/workflows/email-check.yml
name: Check Email Triggers
on:
  schedule:
    - cron: '*/5 * * * *'    # Every 5 minutes
  workflow_dispatch:            # Manual trigger

jobs:
  check-email:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger Railway Worker
        run: |
          curl -X POST "${{ secrets.RAILWAY_WEBHOOK_URL }}" \
            -H "Authorization: Bearer ${{ secrets.RAILWAY_TOKEN }}" \
            -d '{"action": "email-check"}'
```

### Workflow: Scheduled Research (Daily Blog Post)

```yaml
# .github/workflows/daily-research.yml
name: Daily Blog Research
on:
  schedule:
    - cron: '0 8 * * *'       # Daily at 8am UTC
  workflow_dispatch:
    inputs:
      topic:
        description: 'Research topic (leave empty for auto-select)'
        required: false

jobs:
  research:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger Research
        run: |
          curl -X POST "${{ secrets.RAILWAY_WEBHOOK_URL }}" \
            -H "Authorization: Bearer ${{ secrets.RAILWAY_TOKEN }}" \
            -d '{"action": "blog-research", "topic": "${{ inputs.topic }}"}'
```

### Workflow: Manual Research (On Demand)

```yaml
# .github/workflows/research.yml
name: Run Research
on:
  workflow_dispatch:
    inputs:
      topic:
        description: 'Research topic'
        required: true
      mode:
        description: 'Output mode'
        type: choice
        options:
          - notes
          - report
          - blog
      model:
        description: 'Override synthesis model'
        type: choice
        options:
          - default
          - opus
          - sonnet
```

---

## Step 12: Blog Pipeline Integration

### How the Research Agent Connects to Existing Architecture

The research agent is one piece of the larger blog pipeline defined in [ARCHITECTURE.md](ARCHITECTURE.md):

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Research  │ ─▶ │Summariser│ ─▶ │  Writer  │ ─▶ │  Editor  │ ─▶ │Publisher │ ─▶ │  Ghost   │
│  Agent   │    │  Agent   │    │  Agent   │    │  Agent   │    │  Agent   │    │   CMS    │
│          │    │          │    │          │    │          │    │          │    │          │
│ (this    │    │ condense │    │ write    │    │ proofread│    │ post via │    │ MySQL    │
│  plan)   │    │ findings │    │ blog post│    │ + check  │    │ Admin API│    │          │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
     │                                                                │
     ▼                                                                ▼
┌──────────┐                                                    ┌──────────┐
│ pgvector │                                                    │  Slack   │
│ corpus   │                                                    │  alert   │
└──────────┘                                                    └──────────┘
```

### Data Handoff

The research agent outputs **Format A: Structured Notes** (JSON). This JSON is handed off directly to the Writer agent (no separate Summariser — the Researcher handles condensation).

All agents share:
- The same GitHub Models client (configured in `setup.py`)
- The same `embeddings.py` module (local model)
- The same `config/` YAML system
- The same `guardrails.py` rate limit enforcement
- The same `db.py` asyncpg connection pool

### Standalone vs Pipeline Mode

| Feature | Standalone Mode | Pipeline Mode |
|---|---|---|
| Trigger | `RESEARCH:` email, CLI, or `REPORT:` | `BLOG:` email, daily schedule, or `--blog` CLI |
| Output | Notes or full report | Structured notes JSON → Writer (via handoff) |
| Destination | Saved to file/corpus, emailed back | Feeds into Writer → Editor → Publisher |
| Human review | Optional (report emailed to you) | Recommended (draft saved, notification sent) |
| Auto-publish | N/A | Configurable (`auto_publish: true/false`) |

---

## Database Migration

### Changes to Existing pgvector Schema

The current schema (created by [scripts/db-test.js](../scripts/db-test.js)) uses 1536-dimension vectors for OpenAI embeddings. Switching to local embeddings requires a migration. Additionally, new tables are needed for the agent system.

### Migration Steps

1. **Backup** existing data (if any documents have been indexed)
2. **Alter** the `embeddings` table: change `vector(1536)` → `vector(384)`
3. **Drop and recreate** the HNSW index for the new dimension
4. **Add** new tables for the agent system:

| New Table | Purpose | Key Columns |
|---|---|---|
| `research_runs` | Track every research task | `id`, `topic`, `trigger_type`, `status`, `task_type`, `models_used`, `source_count`, `duration_sec`, `output_path`, `created_at` |
| `rate_limit_log` | Track every LLM API call | `id`, `model`, `tokens_in`, `tokens_out`, `run_id`, `phase`, `created_at` |
| `agent_sessions` | Persist agent conversation state | `id`, `session_id`, `run_id`, `agent_name`, `conversation`, `status`, `handoff_from`, `handoff_to`, `tool_calls`, `total_tokens` |
| `search_results` | Cache web search results | `id`, `query`, `url`, `title`, `snippet`, `fetched_text`, `relevance_score`, `source_type`, `run_id` |

5. **Re-embed** any existing documents with the new local model

Migration scripts: `scripts/init-schema.py` (creates all tables) and `scripts/migrate-to-384.py` (dimension migration).

See [OPENAI_AGENTS_SDK_GUIDE.md](OPENAI_AGENTS_SDK_GUIDE.md) for the full SQL schema.

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
├── init-schema.py              # Create all PostgreSQL tables
├── migrate-to-384.py           # One-time: pgvector 1536→384 dimension migration
└── (existing scripts)
.github/
└── workflows/
    ├── email-check.yml         # Every 5 min: check IMAP for triggers
    ├── daily-research.yml      # Daily: auto-select topic + blog pipeline
    └── research.yml            # Manual: on-demand research dispatch
```

---

## Testing and Verification

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

---

## Key Decisions

| Decision | Choice | Why |
|---|---|---|
| **Agent Framework** | OpenAI Agents SDK (`openai-agents`) | Provider-agnostic, Python-native, works with GitHub Models, MIT licence, $0 |
| **LLM Provider** | GitHub Models API | Zero cost — included in Copilot Pro subscription |
| **Primary Model** | `claude-sonnet-4` (orchestrator + researcher + writer) | Best balance of quality vs. rate limits (200 calls/day) |
| **Light Model** | `claude-haiku` (editor, publisher, indexer) | 3000 calls/day; used for lower-complexity tasks |
| **Embeddings** | Local `all-MiniLM-L6-v2` | Free, runs on Railway CPU, no API calls |
| **Embedding Dimensions** | 384 (down from 1536) | Requires pgvector migration; good enough for <100K chunks |
| **Summariser** | Merged into Researcher agent | One fewer LLM call per pipeline run; researcher outputs structured JSON directly |
| **Agent Persistence** | `agent_sessions` PostgreSQL table | Enables resumable runs and debugging via conversation replay |
| **Web Search** | DuckDuckGo (primary) + Brave (secondary) | Both free; no API costs |
| **Email Trigger** | IMAP polling every 5 min | Works with Hostinger; simpler than webhooks |
| **Automation** | GitHub Actions | Free tier; already in the architecture |
| **Config Format** | YAML files | Human-readable, easy to edit, no code changes needed |
| **Human Review** | Default ON (publish as `draft`) | Safety net before auto-publishing |

---

## Build Order

Recommended sequence for implementation:

| Phase | What to Build | Depends On | Est. Effort |
|---|---|---|---|
| **1** | `setup.py` + `db.py` — GitHub Models client init + asyncpg pool | GitHub PAT, Railway DB | 1 day |
| **2** | `config/` — all YAML config files + `config_loader.py` | Nothing | Half day |
| **3** | `tools/search.py` + `tools/corpus.py` — @function_tool search + pgvector | Phase 1 | 1 day |
| **4** | `tools/ghost.py` + `tools/quality.py` + `tools/files.py` — remaining tools | Phase 1 | 1 day |
| **5** | `definitions.py` — all Agent definitions + handoffs | Phases 1-4 | 1 day |
| **6** | `guardrails.py` + `degradation.py` — rate limit guardrail + fallback | Phase 1 | Half day |
| **7** | `main.py` + `cli.py` — entry point + CLI interface | Phases 5-6 | Half day |
| **8** | `email_listener.py` + `tools/email_tools.py` — IMAP + reply tool | Phase 7 | 1 day |
| **9** | `scripts/init-schema.py` + `scripts/migrate-to-384.py` — DB setup | Phase 1 | Half day |
| **10** | `.github/workflows/` — Actions for daily, email, manual triggers | Phase 7-8 | Half day |
| **11** | Integration testing + quality review | All phases | 1 day |

**Total estimated effort: 7-8 days**

See [OPENAI_AGENTS_SDK_GUIDE.md](OPENAI_AGENTS_SDK_GUIDE.md) for full implementation code for each phase.

---

## Open Questions

> **Resolved:** GitHub Copilot tier is **Copilot Pro** (10 req/min high-cost, 150 req/min low-cost, 200 sonnet/day, 3000 haiku/day).
> **Resolved:** Summariser agent merged into Researcher. Researcher outputs structured JSON directly.
> **Resolved:** Agent persistence via `agent_sessions` PostgreSQL table.

Remaining open questions:

1. **Existing corpus data** — Have any documents been indexed into pgvector yet? This affects whether the embedding migration needs a data re-embedding step.

2. **Email address for triggers** — Should the agent listen on `admin@beyondtomorrow.world` or a different mailbox (e.g., `research@beyondtomorrow.world`)?

3. **Blog topic selection** — For the daily scheduled run, how should the agent pick a topic? Options:
   - From a queue you maintain (YAML file of upcoming topics)
   - AI-generated based on trending news in your topic categories
   - Rotating through topic categories defined in `config/sources.yaml`

4. **Report delivery** — For standalone reports, preferred delivery method?
   - Email reply with report attached
   - Saved to repository and accessible via URL
   - Both
