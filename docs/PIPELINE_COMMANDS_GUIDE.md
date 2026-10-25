# Pipeline Commands — Comprehensive Guide & Best Practices

This guide covers every pipeline command, how each one works internally, and how to write effective inputs that produce the best possible output.

---

## Before You Start

Always activate the virtual environment. The system Python (3.14 on macOS) has SSL cert issues.

```bash
source .venv/bin/activate
```

Verify the environment is healthy before running anything for the first time:

```bash
.venv/bin/python -m pipeline.main status
```

This checks all required environment variables (`GITHUB_TOKEN`, `DATABASE_URL`, `GHOST_URL`, `GHOST_ADMIN_KEY`), the PostgreSQL/pgvector connection, and Ghost API reachability.

---

## Command Reference

| Command | Stages Run | Publishes? | Indexes? |
|---|---|---|---|
| `BLOG:` | Research → Write → Edit → Publish → Index | Yes | Yes |
| `RESEARCH:` | Research → Index | No | Yes |
| `REPORT:` | Research (extended) → Index | No | Yes |
| `INDEX:` | Index only | No | Yes |
| `PUBLISH:` | Publish → Index | Yes | Yes |
| `status` | Health check only | No | No |

---

## `BLOG:` — Full End-to-End Pipeline

Runs the complete chain: Researcher → Writer → Editor → Publisher (Ghost + LinkedIn) → Newsletter → Indexer.

```bash
.venv/bin/python -m pipeline.main "BLOG: <topic>"
```

### What happens internally

1. **Researcher** runs 2–3 targeted web searches, stores embeddings in pgvector, then synthesises structured JSON findings
2. **Writer** picks the most compelling angle, drafts a 1,200–1,800 word post with YAML frontmatter, saves as `YYYY-MM-DD-slug.md`
3. **Editor** fact-checks, tightens prose, audits British English punctuation, saves as `YYYY-MM-DD-slug-edited.md`
4. **Publisher** picks a feature image, uploads it to Ghost, publishes the post live, cross-posts to LinkedIn
5. **Newsletter** sends via Resend to unsuppressed free members subscribed to the selected newsletter, with durable receipts per recipient
6. **Indexer** chunks and embeds the published post into pgvector for future RAG retrieval

### Writing effective `BLOG:` topics

**The formula:** `[concrete subject] + [tension, risk, or question]`

The topic becomes the Researcher's search brief. Too vague produces generic output. Too narrow produces thin research. The sweet spot is 8–20 words that name a real phenomenon and imply a "so what."

**Good examples:**

```bash
# Concrete commodity + specific risk + urgency signal
.venv/bin/python -m pipeline.main "BLOG: Why copper shortages could derail the clean energy transition faster than expected"

# Two intersecting domains + underreported angle
.venv/bin/python -m pipeline.main "BLOG: How central banks are quietly becoming climate policy actors"

# Anchored to a real event with a clear geopolitical frame
.venv/bin/python -m pipeline.main "BLOG: The geopolitics of rare earth minerals after China's 2025 export controls"

# Economic tension with a named stakeholder
.venv/bin/python -m pipeline.main "BLOG: Why AI data centre investment is slowing despite record demand"

# Technology risk framed for a general audience
.venv/bin/python -m pipeline.main "BLOG: What the semiconductor supply chain crisis means for the energy transition"
```

**Patterns to avoid:**

| Pattern | Why it fails |
|---|---|
| `BLOG: Climate change` | Too broad — Researcher has no angle, Writer produces a shallow survey |
| `BLOG: Is AI good or bad?` | Tired framing; Writer's title rules reject generic questions |
| `BLOG: Summarise the IMF World Economic Outlook` | Sounds like `REPORT:` — no tension, no audience hook |
| `BLOG: [very niche technical spec]` | Mismatches the target audience (curious generalists, not specialists) |
| `BLOG: Everything you need to know about X` | Explicitly banned by the Writer's title rules |

### Topic areas the blog covers

The pipeline is tuned for these domains. Topics that straddle two or more domains tend to produce the most engaging posts:

- **Climate** — energy transition, carbon markets, extreme weather, policy
- **Technology** — AI, semiconductors, biotech, surveillance, data infrastructure
- **Geopolitics** — trade, alliances, resource competition, sanctions
- **Economics** — investment risk, inequality, financial systems, central banks
- **Futures** — long-range trends, scenario thinking, civilisational risk

---

## `RESEARCH:` — Store Findings Without Publishing

Runs only the Researcher and Indexer. Stores structured findings in pgvector. No post is written or published. Use this to pre-load knowledge on a topic before writing about it.

```bash
.venv/bin/python -m pipeline.main "RESEARCH: <topic>"
```

**When to use it:**

- You want to build up corpus knowledge on a topic before writing about it
- The topic is too exploratory to blog about yet but worth indexing
- You want the Researcher to gather and verify sources without committing to a post
- You are preparing for a future `BLOG:` run that will benefit from pre-indexed context

**Good examples:**

```bash
# Pre-research a complex topic before writing
.venv/bin/python -m pipeline.main "RESEARCH: rare earth mineral supply chains"

# Build corpus knowledge on a fast-moving story
.venv/bin/python -m pipeline.main "RESEARCH: EU AI Act implementation timeline 2025-2026"

# Explore a technical area before tackling the policy angle
.venv/bin/python -m pipeline.main "RESEARCH: carbon capture and storage economics"
```

**Best practice:** Run `RESEARCH:` on a topic first, then follow up with `BLOG:` on the same topic. The Researcher will automatically retrieve the pre-indexed findings via pgvector RAG, improving depth and source quality without extra API calls.

```bash
# Step 1 — pre-research
.venv/bin/python -m pipeline.main "RESEARCH: deep sea mining environmental impact"

# Step 2 — blog using the indexed knowledge
.venv/bin/python -m pipeline.main "BLOG: Why the deep sea mining debate could reshape ocean governance"
```

---

## `REPORT:` — Extended Research Analysis

Runs the Researcher in extended analysis mode and the Indexer. Produces a detailed research report file (not a blog post). Useful for thorough topic exploration or briefing documents.

```bash
.venv/bin/python -m pipeline.main "REPORT: <topic>"
```

**When to use it:**

- You need a detailed briefing on a complex topic
- You want a structured analysis with multiple subtopics, source lists, and knowledge gaps documented
- The topic is too large or nuanced for a single blog post
- You want a research foundation before commissioning multiple related blog posts

**Good examples:**

```bash
.venv/bin/python -m pipeline.main "REPORT: global water scarcity"
.venv/bin/python -m pipeline.main "REPORT: the geopolitical implications of Arctic ice loss"
.venv/bin/python -m pipeline.main "REPORT: central bank digital currencies — risks and adoption"
```

**Output:** A structured JSON file saved to `research/YYYY-MM-DD-<slug>-research.json` and indexed into pgvector. No `.md` file is produced — both `REPORT:` and `RESEARCH:` route through the same `_run_research_pipeline()` function and produce only the JSON cache.

---

## `INDEX:` — Add an Existing Document to the Corpus

Chunks, embeds, and stores an existing file into the pgvector corpus. No research or writing. Use this to manually inject reference material — PDFs, reports, external articles, or local notes.

```bash
.venv/bin/python -m pipeline.main "INDEX: path/to/document.txt"
.venv/bin/python -m pipeline.main "INDEX: reports/ipcc-ar6-summary.pdf"
```

**When to use it:**

- You have a PDF or text file you want available for RAG retrieval
- You want to add a specific external report or dataset to the knowledge base
- You have manually written research notes you want indexed

**Supported formats:** `.txt`, `.md`, `.pdf`, `.json`

**Best practice:** Use the dedicated report indexer for batching PDFs in the `reports/` directory rather than calling `INDEX:` one file at a time.

---

## `PUBLISH:` — Publish an Already-Edited File

Publishes an existing `-edited.md` file directly to Ghost, cross-posts to LinkedIn, and sends the newsletter. Skips all research, writing, and editing stages.

```bash
.venv/bin/python -m pipeline.main "PUBLISH: YYYY-MM-DD-slug-edited.md"
```

**When to use it:**

- You manually edited a post and want to publish without re-running the full pipeline
- A previous pipeline run completed writing and editing but the publish step failed
- You want to re-publish a corrected version of an existing post

**Example:**

```bash
# After manually editing the file:
.venv/bin/python -m pipeline.main "PUBLISH: 2026-05-20-ai-chips-export-controls-edited.md"
```

**Pre-publish validation:** The Publisher checks before calling Ghost:
- Title present (5–10 words)
- Body content is at least 500 words
- Feature image URL is a hosted URL
- Excerpt is non-empty in frontmatter
- `## Just For Laughs` section is present

If any item is missing, the command returns `MISSING: [list]` without publishing. Fix the file and retry.

**File location:** Files must be in the `research/` directory.

---

## `status` — Health Check

Checks all environment variables, the PostgreSQL/pgvector connection, and Ghost API reachability.

```bash
.venv/bin/python -m pipeline.main status
```

Run this first whenever you encounter unexpected failures. It is fast and makes no LLM calls.

---

## CLI Flags

These flags work with any command prefix.

| Flag | Effect | When to use |
|---|---|---|
| `--model MODEL` | Override the orchestrator model for this run | Testing a specific model; debugging model-specific output quality |
| `--dry-run` | Prints what the agent would do without making any LLM calls | Validating command syntax and routing logic without spending API budget |
| `--debug` | Enables verbose SDK tracing output | Diagnosing which tool call failed; inspecting full agent reasoning |

**Examples:**

```bash
# Run with a specific model
.venv/bin/python -m pipeline.main "BLOG: AI regulation in 2026" --model openai/gpt-4.1

# Dry run to verify routing
.venv/bin/python -m pipeline.main "BLOG: nuclear fusion investment" --dry-run

# Debug a failing research stage
.venv/bin/python -m pipeline.main "RESEARCH: carbon border adjustment mechanism" --debug
```

---

## Typical Workflows

### Standard blog post

```bash
.venv/bin/python -m pipeline.main "BLOG: Why the energy transition is accelerating despite political headwinds"
```

### Pre-research then blog

```bash
# Build corpus context first
.venv/bin/python -m pipeline.main "RESEARCH: rare earth mineral supply chains"

# Blog on the topic — Researcher retrieves pre-indexed findings automatically
.venv/bin/python -m pipeline.main "BLOG: The rare earth bottleneck threatening the clean energy transition"
```

### Fix and republish a post

```bash
# 1. Edit the -edited.md file manually in research/
# 2. Republish directly
.venv/bin/python -m pipeline.main "PUBLISH: 2026-04-08-my-post-edited.md"
```

### Add a PDF report to the knowledge base

```bash
.venv/bin/python -m pipeline.main "INDEX: reports/iea-world-energy-outlook-2025.pdf"
```

### Debug a pipeline failure

```bash
# Check services first
.venv/bin/python -m pipeline.main status

# Re-run with verbose tracing
.venv/bin/python -m pipeline.main "BLOG: topic that previously failed" --debug
```

---

## Common Mistakes

| Mistake | Fix |
|---|---|
| Using system Python instead of `.venv` | Always prefix with `.venv/bin/python -m` |
| Forgetting the `BLOG:` / `RESEARCH:` prefix | Without a prefix the command is unrecognised |
| Passing a filename without path to `PUBLISH:` that isn't in `research/` | Ensure the `-edited.md` file is in the `research/` directory |
| Retrying a previously published request | Its stored Ghost receipt preserves the article; channel/recipient receipts prevent repeat delivery. Matching title slugs are never deleted automatically. See [recovery](DELIVERY_RECOVERY.md). |
| Using the Railway internal `DATABASE_URL` locally | Always use the external TCP proxy: `caboose.proxy.rlwy.net:21688` |
