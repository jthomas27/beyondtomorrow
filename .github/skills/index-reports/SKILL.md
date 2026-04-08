---
name: index-reports
description: "Index PDF reports into PostgreSQL + pgvector so the RAG pipeline can use them. Use when: adding new PDFs to reports/, re-indexing a specific file, checking which reports are indexed, batch-indexing all unindexed reports, or fixing a failed index run."
argument-hint: "Optional: describe what to do (e.g. 'index all new PDFs', 'check status', 'reindex IPCC report', 'index reports/myfile.pdf')"
---

# Index Reports

Indexes PDF files from `reports/` into PostgreSQL (`documents`, `chunks`) and pgvector (`embeddings`) so the Researcher agent's `search_corpus` tool can retrieve them.

## Database Tables

| Table | Purpose |
|---|---|
| `documents` | One row per source file — stores full extracted text and metadata |
| `chunks` | ~350-word overlapping chunks of each document |
| `embeddings` | 384-dim `BAAI/bge-small-en-v1.5` vectors for each chunk (pgvector) |

`source` is the dedup key — format: `reports/<filename.pdf>`. Re-running is safe (upserts).

---

## Procedure

### 1. Check what's indexed vs. not

```bash
cd /Users/jeremiah/Projects/BeyondTomorrow.World
source .venv/bin/activate
python /tmp/check_reports.py
```

If `/tmp/check_reports.py` doesn't exist, run this one-liner to recreate it:

```bash
python - << 'EOF'
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

### 2. Batch-index all unindexed PDFs

Runs the pre-built batch script. Skips already-indexed files automatically. Safe to re-run.

```bash
source .venv/bin/activate
python -m scripts.batch_index_reports
```

Output per file:
- `OK — Indexed N chunks from 'reports/...' into the knowledge corpus.`
- `SKIP (already indexed)` — dedup check passed, nothing to do
- `SKIP (no extractable text)` — scanned/image-only PDF; cannot index
- `FAIL (PDF extraction: ...)` — corrupt or non-PDF file (e.g. HTML with `.pdf` extension)

Final line: `Done.  Indexed: N  |  Skipped: N  |  Failed: N`

### 3. Force re-index (replace existing chunks + embeddings)

```bash
python -m scripts.batch_index_reports --force
```

Use when a PDF has been updated or you need to refresh embeddings.

### 4. Index a single file via the pipeline CLI

```bash
python -m pipeline.main "INDEX: reports/my-new-report.pdf"
```

Use this for a one-off file. The Indexer agent handles extraction, chunking, and embedding.

---

## Known Issues

| File | Issue |
|---|---|
| `appPage.pdf` | Not a real PDF — HTML file saved with wrong extension; cannot be extracted |
| Large PDFs (>150 pages) | May cause MPS memory pressure on macOS. If a file FAILs with `MPS backend out of memory`, re-run `batch_index_reports` — it will retry only the failed file and usually succeeds once memory pressure clears. |

---

## Verify Indexing in DB

```bash
source .venv/bin/activate
python - << 'EOF'
import os, psycopg2
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM documents WHERE source_type='pdf'")
print('PDF documents:', cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.source_type='pdf'")
print('PDF chunks:', cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM embeddings e JOIN chunks c ON c.id=e.chunk_id JOIN documents d ON d.id=c.document_id WHERE d.source_type='pdf'")
print('PDF embeddings:', cur.fetchone()[0])
conn.close()
EOF
```

---

## Adding New Reports

1. Drop the PDF into `reports/`
2. Run `python -m scripts.batch_index_reports` — it will pick up any new files automatically
3. The Researcher agent can now find this content via `search_corpus`

No pipeline restart needed.
