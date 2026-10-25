---
name: index-reports
description: "Check indexed PDF reports or index requested files into the current pgvector corpus; distinguish read-only inventory from paid embedding writes."
---

Run commands from the repository root using `.venv/bin/python`. Follow `AGENTS.md`; reuse established task authorisation and service access.

# Index PDF reports

The corpus uses 1536-dimensional `text-embedding-3-small` vectors. Read the current
chunking limits from `config/limits.yaml`; do not restore old 384-dimensional/MPS
migration instructions. PDF input lives in ignored `reports/`; `documents.source`
uses `reports/filename.pdf` as the deduplication key.

For inventory-only requests, query indexed PDF sources read-only and compare them
with local files. See [inventory query](references/inventory.md). Do not index as a
side effect of checking inventory.

For authorised indexing:

```bash
.venv/bin/python -m scripts.batch_index_reports
.venv/bin/python -m pipeline.main "INDEX: reports/selected-report.pdf"
```

The batch command skips indexed reports. Use `--force` only when replacing existing
chunks is requested or necessary for the user's stated reindex task. Indexing writes
PostgreSQL and incurs embedding usage; it does not publish to Ghost or send email.
Report indexed/skipped/failed files. A file with a .pdf extension may be HTML or a
scanned document; report extraction failures without inventing content.
