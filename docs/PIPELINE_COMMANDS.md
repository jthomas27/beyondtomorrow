# Pipeline Commands

## Running the Pipeline

Always use the virtual environment:

```bash
source .venv/bin/activate
```

## Commands

| Command | Example | What it does |
|---|---|---|
| `BLOG:` | `.venv/bin/python -m pipeline.main "BLOG: AI regulation in 2026"` | Full end-to-end pipeline: Research → Write → Edit → Publish to Ghost → Post to LinkedIn → Index into corpus |
| `RESEARCH:` | `.venv/bin/python -m pipeline.main "RESEARCH: carbon capture economics"` | Runs only Research → Indexer. Stores findings in pgvector for future RAG retrieval. No post is written or published. |
| `REPORT:` | `.venv/bin/python -m pipeline.main "REPORT: global water scarcity"` | Extended research analysis → Indexer. Produces a detailed research report file without publishing a blog post. |
| `INDEX:` | `.venv/bin/python -m pipeline.main "INDEX: path/to/document.txt"` | Chunks, embeds, and stores an existing file into the pgvector corpus. No research or writing. |
| `PUBLISH:` | `.venv/bin/python -m pipeline.main "PUBLISH: 2026-04-08-my-post-edited.md"` | Takes an already-edited `.md` file, publishes it to Ghost, cross-posts to LinkedIn, and sends the newsletter. Skips all research/writing stages. |
| `status` | `.venv/bin/python -m pipeline.main status` | Checks env vars, database connection, and service reachability. Run this first when debugging. |

## CLI Flags

| Flag | Effect |
|---|---|
| `--model MODEL` | Override the orchestrator model for the run |
| `--dry-run` | Prints what the agent would do without making any LLM calls |
| `--debug` | Enables verbose SDK tracing output |

## Typical Workflows

**Write and publish a new post:**
```bash
.venv/bin/python -m pipeline.main "BLOG: the future of nuclear energy"
```

**Pre-research a topic for RAG, then blog later:**
```bash
.venv/bin/python -m pipeline.main "RESEARCH: rare earth mineral supply chains"
# The research will be retrieved automatically when blogging on the topic later
```

**Fix a post and re-publish without re-running the full pipeline:**
```bash
# Edit the -edited.md file manually, then:
.venv/bin/python -m pipeline.main "PUBLISH: 2026-04-08-my-post-edited.md"
```
